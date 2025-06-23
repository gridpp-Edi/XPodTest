#!/bin/env python3
"""
This script manages the lifecycle of XRootD server and test containers using Podman.
It launches the XRootD server, runs test client containers, collects logs,
and uploads results to S3 or a compatible storage backend.
It also exports test metadata to OpenSearch or a compatible backend.
It is designed to be run in a GridPP environment with Podman and XRootD.
It supports running multiple tests defined in JSON files located in a specified directory.
It uses the Podman Python client to interact with containers and manage their lifecycle.
It includes functionality for:
- Launching an XRootD server container.
- Running test client containers against the server.
- Collecting logs from test containers.
- Uploading logs to S3 or a compatible storage backend.
"""

import argparse
import concurrent.futures
import datetime
import json
import logging
import os
import re
import time
import uuid
from functools import partial
from typing import Any, Dict, List, Optional

from osupload import OpenSearchLogger, real_opensearch_upload
from runner import XRootDTestRunner
from s3upload import S3Uploader, real_s3_upload

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger("xrootdtesting")
logger.setLevel(logging.INFO)

def load_config(config_path: str) -> dict:
    """
    Loads the main configuration file.

    Args:
        config_path (str): Path to the configuration JSON file.

    Returns:
        dict: Parsed configuration.
    """
    logger.debug(f"Loading config from: {config_path}")
    with open(config_path) as f:
        return json.load(f)

def load_private_config(config_path: str = "config.json") -> dict:
    """
    Loads private configuration (S3, OpenSearch) from a JSON file.

    Args:
        config_path (str): Path to the configuration JSON file.

    Returns:
        dict: Parsed configuration.
    """
    with open(config_path) as f:
        return json.load(f)

def substitute_path(value: Any, test_path: str) -> Any:
    """
    Recursively substitutes 'TEST_PATH' in strings within a data structure.

    Args:
        value: The value to substitute (can be dict, list, or str).
        test_path (str): The path to substitute for 'TEST_PATH'.

    Returns:
        The value with substitutions applied.
    """
    if isinstance(value, dict):
        return {substitute_path(k, test_path): substitute_path(v, test_path) for k, v in value.items()}
    elif isinstance(value, list):
        return [substitute_path(item, test_path) for item in value]
    elif isinstance(value, str):
        return value.replace("TEST_PATH", test_path)
    return value

def build_server_config(server: dict, test_path: str) -> dict:
    """
    Builds the server configuration for launching the server container.

    Args:
        server (dict): Server configuration from the main config.
        test_path (str): Path to use for test-specific substitutions.

    Returns:
        dict: Complete server configuration.
    """
    server_config = server.get("server_config")
    if server_config:
        server_config = substitute_path(server_config, test_path)
        server_config["host"] = server.get("server", "localhost")
        server_config["port"] = server.get("port", 1094)
        logger.debug(f"Built server config from test file: {server_config}")
    else:
        # Use a simple busybox container as the default server
        server_config = {
            "entrypoint": ["/bin/sh", "-c", "echo 'Hello world'; sleep 300"],
            "volumes": {},
            "host": server.get("server", "localhost"),
            "port": server.get("port", 9999)
        }
        logger.debug(f"Built default busybox server config: {server_config}")
    return server_config

def launch_servers(
    servers: List[dict], test_default_version: str, test_path: str, server_version: Optional[str] = None
) -> List[Any]:
    """
    Launches all server containers required for a test.

    Args:
        servers (List[dict]): List of server configuration dictionaries.
        test_default_version (str): Default container image version to use if not specified per server.
        test_path (str): Path to use for test-specific substitutions.
        server_version (Optional[str]): Override for the server container version.

    Returns:
        List[Any]: List of tuples containing runner, server, version, and test_path for each launched server.
    """
    runners: List[Any] = []
    for server in servers:
        # Priority: --server_version > server["version"] > test_default_version
        version: str = server_version or server.get("version", test_default_version)
        runner = XRootDTestRunner(podman_sock=server["uri"])
        server_config = build_server_config(server, test_path)
        runner.launch_server(version, server_config)  # version here is the CLI override if set
        runners.append((runner, server, version, test_path))
        logger.info(f"Initialized server container '{runner.server_container_name}' on host '{server.get('server', 'localhost')}' with image '{version}'")
    return runners

def cleanup_servers(
    runners: List[Any],
    timestamp: str,
    s3_uploader: Optional[S3Uploader],
    server_logs_dict: Dict[str, str]
) -> None:
    """
    Stops all server containers, collects their logs, uploads logs to S3, and removes the containers.

    Args:
        runners (List[Any]): List of tuples containing runner and server info.
        timestamp (str): Timestamp string to use in log filenames.
        s3_uploader (Optional[S3Uploader]): S3 uploader instance for log upload.
        server_logs_dict (Dict[str, str]): Dictionary to store server container names and their S3 log keys.
    """
    for runner, _, _, _ in runners:
        try:
            with runner._get_client() as client:
                container = client.containers.get(runner.server_container_name)
                if container.attrs["State"]["Running"]:
                    container.stop()
                logs = "".join(line.decode() for line in container.logs(stream=True, stdout=True, stderr=True))
                server_log_key = f"server-logs/{runner.server_container_name}-{timestamp}.log"
                if s3_uploader:
                    s3_uploader.upload_logs(server_log_key, logs.encode())
                server_logs_dict[runner.server_container_name] = server_log_key
            container.remove(force=True)
        except Exception as e:
            logger.warning(f"Failed to collect/remove server logs: {e}")

def extract_transfer_speed(logs: str) -> float:
    """
    Extracts the final transfer speed in MB/s from xrdcp or curl logs.
    Supports kB/s, MB/s, and GB/s units, and curl's progress output.
    """
    # Try xrdcp first (existing logic)
    matches = re.findall(r"\[(\d+(?:\.\d+)?)([kMG]B/s)\]", logs)
    if matches:
        value, unit = matches[-1]  # Use the last occurrence
        value = float(value)
        if unit == "kB/s":
            return value / 1024
        elif unit == "MB/s":
            return value
        elif unit == "GB/s":
            return value * 1024

    # Try curl: look for the last line starting with 100 (completion line)
    curl_speed = None
    for line in logs.splitlines():
        columns = line.strip().split()
        if len(columns) >= 12 and columns[0] == "100":
            # The 7th column (index 6) is the average download speed, e.g. 220M
            speed_str = columns[6]
            match = re.match(r"([0-9.]+)([kMG])", speed_str)
            if match:
                value, unit = match.groups()
                value = float(value)
                if unit == "k":
                    curl_speed = value / 1024
                elif unit == "M":
                    curl_speed = value
                elif unit == "G":
                    curl_speed = value * 1024
    if curl_speed is not None:
        return curl_speed

    return None

def run_single_test(
    test_file: str,
    default_version: str,
    s3_uploader: Optional[S3Uploader],
    opensearch_logger: Optional[OpenSearchLogger] = None,
    server_version: Optional[str] = None,
    test_version: Optional[str] = None,
    repeat: int = 1,
    sleep_after_servers: int = 0,
    extra_env: Optional[Dict[str, str]] = None,
    container_suffix: str = ""
) -> None:
    """
    Runs a single test as described in the given test configuration file, possibly multiple times or in parallel.
    Records start and finish times and includes them in OpenSearch metadata.
    """
    with open(test_file) as f:
        test_json: dict = json.load(f)

    test_config: dict = test_json.get("test_config", test_json)
    test_path: str = test_json.get("TEST_PATH", "/tmp")
    parallel_repeats = test_config.get("parallel_repeats", 0)

    # Only do parallel on outermost call
    if parallel_repeats and parallel_repeats > 1 and not container_suffix:
        servers: List[dict] = test_json.get("servers", [])
        if not servers:
            logger.warning(f"No servers defined in {test_file}, skipping.")
            return

        test_default_version: str = default_version or test_json.get("default_version", "gridppedi/xrdtesting:xrd-v5.8.3")
        # Start servers ONCE
        logger.info(f"Launching servers for parallel test execution ({parallel_repeats} clients)...")
        runners = launch_servers(servers, test_default_version, test_path, server_version=server_version)
        if not runners:
            logger.warning("No runners launched, skipping test.")
            return

        # Attach runner info to each server dict for use in client-only runs
        for idx, (runner, server, version, test_path) in enumerate(runners):
            servers[idx]["runner_tuple"] = (runner, server, version, test_path)

        if sleep_after_servers > 0:
            logger.info(f"Sleeping for {sleep_after_servers} seconds before running parallel test clients...")
            time.sleep(sleep_after_servers)

        logger.info(f"Starting {parallel_repeats} parallel test client runs for {test_file}...")
        def run_client_instance(suffix):
            logger.debug(f"Starting parallel test client with suffix {suffix}")
            return run_test_client_only(
                test_json,
                test_config,
                test_path,
                default_version,
                s3_uploader,
                opensearch_logger,
                server_version,
                test_version,
                0,  # Don't sleep again
                extra_env,
                suffix
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_repeats) as executor:
            futures = [
                executor.submit(run_client_instance, f"-parallel-{i}-{uuid.uuid4().hex[:8]}")
                for i in range(parallel_repeats)
            ]
            logger.info(f"Submitted all {parallel_repeats} parallel test client jobs.")
            for future in concurrent.futures.as_completed(futures):
                try:
                    result = future.result()
                    logger.debug("A parallel test client finished successfully.")
                except Exception as e:
                    logger.error(f"Parallel test run failed: {e}")

        logger.info("All parallel test clients have completed. Cleaning up servers...")
        # Clean up servers after all clients are done
        timestamp = datetime.datetime.utcnow().isoformat()
        server_logs_dict: Dict[str, str] = {}
        cleanup_servers(runners, timestamp, s3_uploader, server_logs_dict)
        logger.info("Server cleanup after parallel execution complete.")
        return  # Do not continue with the sequential logic

    for i in range(repeat):
        logger.info(f"Running test iteration {i+1}/{repeat} for: {test_file}")
        logger.info(f"Processing test file: {test_file}")
        with open(test_file) as f:
            test_json: dict = json.load(f)

        servers: List[dict] = test_json.get("servers", [])
        if not servers:
            logger.warning(f"No servers defined in {test_file}, skipping.")
            return

        # Use the passed default_version (from CLI if provided) instead of the config's default_version
        test_default_version: str = default_version or test_json.get("default_version", "gridppedi/xrdtesting:xrd-v5.8.3")
        test_config: dict = test_json.get("test_config", test_json)
        test_path: str = test_json.get("TEST_PATH", "/tmp")

        # Record test start time
        test_start = datetime.datetime.utcnow().isoformat()

        runners = launch_servers(servers, test_default_version, test_path, server_version=server_version)
        if not runners:
            logger.warning("No runners launched, skipping test.")
            return

        # Optional sleep after starting servers
        if sleep_after_servers > 0:
            logger.info(f"Sleeping for {sleep_after_servers} seconds before running the test...")
            time.sleep(sleep_after_servers)

        test_command = substitute_path(test_config["test_command"], test_path)
        test_volumes = substitute_path(test_config["test_volumes"], test_path)
        artefact_paths = substitute_path(test_config.get("artefact_paths", []), test_path)
        test_env = test_config.get("test_env", {})

        # Handle extra environment variables from CLI
        test_env = test_config.get("test_env", {})
        if extra_env:
            test_env.update(extra_env)

        runner, server, _, _ = runners[0]

        # Determine the Podman URI for the test client container
        test_client_uri = test_config.get("uri", server.get("uri"))
        if not test_client_uri:
            logger.warning("No Podman URI specified for test client; using server's URI.")
            test_client_uri = server.get("uri")

        # Use the specified Podman URI to run the test client container
        test_runner = XRootDTestRunner(podman_sock=test_client_uri)
        test_client_version = test_version or test_config.get("version", test_default_version)

        logger.info(f"Running test client for {server.get('server', 'localhost')} with image {test_client_version} on podman URI {test_client_uri}")
        exit_code, logs = test_runner.run_test(
            test_client_version, test_command, test_volumes, test_env, container_suffix=container_suffix
        )

        logger.debug("\n========== Test Logs ==========")
        logger.debug(logs)
        logger.debug("======== End Test Logs ========\n")

        # Extract transfer speed from logs
        transfer_speed = extract_transfer_speed(logs)
        logger.info(f"Extracted transfer speed: {transfer_speed} MB/s" if transfer_speed is not None else "No transfer speed found in logs.")

        # Record test finish time
        test_finish = datetime.datetime.utcnow().isoformat()

        timestamp: str = test_finish  # Use finish time for log key
        test_client_log_key = f"logs/{test_runner.test_container_name}-{timestamp}.log"
        if s3_uploader:
            s3_uploader.upload_logs(test_client_log_key, logs.encode())

        test_client_exit_code = exit_code
        test_client_container_name = test_runner.test_container_name

        # Compose test name with folder name
        folder_name = os.path.basename(os.path.dirname(test_file))
        original_test_name = test_json.get("name", os.path.basename(test_file))
        test_name = f"{folder_name}/{original_test_name}"

        # Clean up artefact files if specified
        if artefact_paths:
            # Remove artefact files from host-mounted volumes using a cleanup container
            XRootDTestRunner.cleanup_artefacts_with_container(
                test_volumes, artefact_paths, cleanup_image="busybox", podman_sock=runner.podman_sock
            )

        # Collect and upload server logs, then remove containers
        server_logs_dict: Dict[str, str] = {}
        cleanup_servers(runners, timestamp, s3_uploader, server_logs_dict)

        # Export test metadata and log references to OpenSearch, including start/finish
        if opensearch_logger:
            opensearch_logger.export_metadata(
                version=test_client_version,
                container_name=test_client_container_name,
                timestamp=timestamp,
                exit_code=test_client_exit_code,
                log_key=test_client_log_key,
                test_name=test_name,
                server_logs=server_logs_dict,
                test_client_log=None,
                test_start=test_start,
                test_finish=test_finish,
                transfer_speed=transfer_speed
            )

def run_test_client_only(
    test_json: dict,
    test_config: dict,
    test_path: str,
    default_version: str,
    s3_uploader: Optional[S3Uploader],
    opensearch_logger: Optional[OpenSearchLogger],
    server_version: Optional[str],
    test_version: Optional[str],
    sleep_after_servers: int,
    extra_env: Optional[Dict[str, str]],
    container_suffix: str
) -> None:
    servers: List[dict] = test_json.get("servers", [])
    if not servers or "runner_tuple" not in servers[0]:
        logger.error("No server runner info found for parallel test client run.")
        return

    test_default_version: str = default_version or test_json.get("default_version", "gridppedi/xrdtesting:xrd-v5.8.3")
    test_command = substitute_path(test_config["test_command"], test_path)
    test_volumes = substitute_path(test_config["test_volumes"], test_path)
    artefact_paths = substitute_path(test_config.get("artefact_paths", []), test_path)
    test_env = test_config.get("test_env", {})
    if extra_env:
        test_env.update(extra_env)

    runner, server, _, _ = servers[0]["runner_tuple"]

    test_client_uri = test_config.get("uri", server.get("uri"))
    if not test_client_uri:
        logger.warning("No Podman URI specified for test client; using server's URI.")
        test_client_uri = server.get("uri")

    test_runner = XRootDTestRunner(podman_sock=test_client_uri)
    test_client_version = test_version or test_config.get("version", test_default_version)

    logger.info(f"Running test client for {server.get('server', 'localhost')} with image {test_client_version} on podman URI {test_client_uri}")
    exit_code, logs = test_runner.run_test(
        test_client_version, test_command, test_volumes, test_env, container_suffix=container_suffix
    )

    logger.debug("\n========== Test Logs ==========")
    logger.debug(logs)
    logger.debug("======== End Test Logs ========\n")

    transfer_speed = extract_transfer_speed(logs)
    logger.info(f"Extracted transfer speed: {transfer_speed} MB/s" if transfer_speed is not None else "No transfer speed found in logs.")

    test_finish = datetime.datetime.utcnow().isoformat()
    timestamp: str = test_finish
    test_client_log_key = f"logs/{test_runner.test_container_name}-{timestamp}.log"
    if s3_uploader:
        s3_uploader.upload_logs(test_client_log_key, logs.encode())

    test_client_exit_code = exit_code
    test_client_container_name = test_runner.test_container_name

    folder_name = os.path.basename(os.path.dirname(test_json.get('name', '')))
    original_test_name = test_json.get("name", os.path.basename(test_json.get('name', '')))
    test_name = f"{folder_name}/{original_test_name}"

    if artefact_paths:
        XRootDTestRunner.cleanup_artefacts_with_container(
            test_volumes, artefact_paths, cleanup_image="busybox", podman_sock=runner.podman_sock
        )

    # No server cleanup here! Only client logic.

    if opensearch_logger:
        opensearch_logger.export_metadata(
            version=test_client_version,
            container_name=test_client_container_name,
            timestamp=timestamp,
            exit_code=test_client_exit_code,
            log_key=test_client_log_key,
            test_name=test_name,
            server_logs=None,
            test_client_log=None,
            test_start=None,
            test_finish=test_finish,
            transfer_speed=transfer_speed
        )

def run_tests_from_folder(
    test_dir: str = "tests",
    s3_uploader: Optional[S3Uploader] = None,
    opensearch_logger: Optional[OpenSearchLogger] = None,
    default_version: Optional[str] = None,
    server_version: Optional[str] = None,
    test_version: Optional[str] = None,
    repeat: int = 1,
    sleep_after_servers: int = 0,
    extra_env: Optional[Dict[str, str]] = None
) -> None:
    """
    Loads all test configurations from a folder (recursively) and runs each test, possibly multiple times.

    Args:
        test_dir (str): Directory containing test configuration files.
        s3_uploader (Optional[S3Uploader]): S3 uploader instance for log upload.
        opensearch_logger (Optional[OpenSearchLogger]): OpenSearch logger instance.
        default_version (Optional[str]): Override for the default container version.
        server_version (Optional[str]): Override for the server container version.
        test_version (Optional[str]): Override for the test client container version.
        repeat (int): Number of times to repeat each test.
    """
    default_version = default_version or "gridppedi/xrdtesting:xrd-v5.8.3"
    for root, _, files in os.walk(test_dir):
        for test_file in sorted(files):
            if not test_file.endswith(".json"):
                continue
            run_single_test(
                os.path.join(root, test_file),
                default_version,
                s3_uploader,
                opensearch_logger,
                server_version=server_version,
                test_version=test_version,
                repeat=repeat,
                sleep_after_servers=sleep_after_servers,
                extra_env=extra_env
            )

def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments for the test runner.

    Returns:
        argparse.Namespace: Parsed arguments.
    """
    parser = argparse.ArgumentParser(description="XRootD Test Runner")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    parser.add_argument(
        "--test_config",
        type=str,
        help="Path to a single test configuration JSON file or directory to run tests"
    )
    parser.add_argument(
        "--container_version",
        type=str,
        default=None,
        help="Override the default container version for both servers and test client"
    )
    parser.add_argument(
        "--server_version",
        type=str,
        default=None,
        help="Override the container version for all servers"
    )
    parser.add_argument(
        "--test_version",
        type=str,
        default=None,
        help="Override the container version for all test clients"
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Repeat each test N times (default: 1)"
    )
    parser.add_argument(
        "--sleep_after_servers",
        type=int,
        default=0,
        help="Sleep N seconds after starting servers and before running the test (default: 0)"
    )
    parser.add_argument(
        "--test_env",
        action="append",
        default=[],
        help="Extra environment variables for the test container, e.g. --test_env BEARER_TOKEN=abc123"
    )
    return parser.parse_args()

def main() -> None:
    """
    Entry point for running all tests.

    This function sets up the S3 uploader, runs all tests in the specified folder or a single test,
    and logs completion.
    """
    args = parse_args()
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    logger.setLevel(log_level)
    logger.info("Starting XRootD test runner.")


    extra_env = dict(item.split("=", 1) for item in args.test_env)

    # Load private config
    private_config = load_private_config()

    # S3 config
    s3_cfg = private_config["s3"]
    s3_uploader = S3Uploader(
        partial(
            real_s3_upload,
            endpoint_url=s3_cfg["endpoint_url"],
            bucket=s3_cfg["bucket"],
            aws_access_key_id=s3_cfg["access_key"],
            aws_secret_access_key=s3_cfg["secret_key"]
        )
    )

    # OpenSearch config and logger
    opensearch_cfg = private_config["opensearch"]
    today = datetime.datetime.utcnow().strftime("%Y.%m.%d")
    os_index = f"{opensearch_cfg['index_prefix']}-{today}"
    opensearch_logger = OpenSearchLogger(
        partial(
            real_opensearch_upload,
            host=opensearch_cfg["host"],
            port=opensearch_cfg["port"],
            index=os_index,
            username=opensearch_cfg["username"],
            password=opensearch_cfg["password"],
            use_ssl=opensearch_cfg["use_ssl"],
        )
    )

    # Use the CLI-provided container version if given, else None
    cli_default_version = args.container_version
    cli_server_version = args.server_version
    cli_test_version = args.test_version
    repeat = args.repeat
    sleep_after_servers = args.sleep_after_servers

    if args.test_config:
        if os.path.isdir(args.test_config):
            logger.info(f"Running all tests in directory: {args.test_config}")
            run_tests_from_folder(
                test_dir=args.test_config,
                s3_uploader=s3_uploader,
                opensearch_logger=opensearch_logger,
                default_version=cli_default_version,
                server_version=cli_server_version,
                test_version=cli_test_version,
                repeat=repeat,
                sleep_after_servers=sleep_after_servers,
                extra_env=extra_env
            )
        else:
            logger.info(f"Running single test from config: {args.test_config}")
            run_single_test(
                args.test_config,
                cli_default_version,
                s3_uploader,
                opensearch_logger,
                server_version=cli_server_version,
                test_version=cli_test_version,
                repeat=repeat,
                sleep_after_servers=sleep_after_servers,
                extra_env=extra_env
            )
    else:
        run_tests_from_folder(
            s3_uploader=s3_uploader,
            opensearch_logger=opensearch_logger,
            default_version=cli_default_version,
            server_version=cli_server_version,
            test_version=cli_test_version,
            repeat=repeat,
            sleep_after_servers=sleep_after_servers,
            extra_env=extra_env
        )
    logger.info("All tests complete.")

if __name__ == "__main__":
    main()
