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
import datetime
import json
import logging
import os
from functools import partial
from typing import Any, Dict, List, Optional

from runner import XRootDTestRunner
from s3upload import S3Uploader, real_s3_upload
from osupload import OpenSearchLogger, real_opensearch_upload

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
    servers: List[dict], test_default_version: str, test_path: str
) -> List[Any]:
    """
    Launches all server containers required for a test.

    Args:
        servers (List[dict]): List of server configuration dictionaries.
        test_default_version (str): Default container image version to use if not specified per server.
        test_path (str): Path to use for test-specific substitutions.

    Returns:
        List[Any]: List of tuples containing runner, server, version, and test_path for each launched server.
    """
    runners: List[Any] = []
    for server in servers:
        version: str = server.get("version", test_default_version)
        is_busybox: bool = not server.get("server_config")
        if is_busybox:
            logger.debug(
                f"Launching dummy busybox server for {server.get('server', 'localhost')} (no image/server_config defined, using busybox 'hello world')"
            )
        else:
            logger.debug(
                f"Launching server for {server.get('server', 'localhost')} with image {version}"
            )
        runner = XRootDTestRunner(podman_sock=server["uri"])
        server_config = build_server_config(server, test_path)
        runner.launch_server(version, server_config)
        runners.append((runner, server, version, test_path))
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

def run_single_test(
    test_file: str,
    default_version: str,
    s3_uploader: Optional[S3Uploader],
    opensearch_logger: Optional[OpenSearchLogger] = None
) -> None:
    """
    Runs a single test as described in the given test configuration file.
    Records start and finish times and includes them in OpenSearch metadata.
    """
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

    runners = launch_servers(servers, test_default_version, test_path)
    if not runners:
        logger.warning("No runners launched, skipping test.")
        return

    test_command = substitute_path(test_config["test_command"], test_path)
    test_volumes = substitute_path(test_config["test_volumes"], test_path)
    artefact_paths = substitute_path(test_config.get("artefact_paths", []), test_path)
    test_env = test_config.get("test_env", {})

    runner, server, version, _ = runners[0]

    # Determine the Podman URI for the test client container
    test_client_uri = test_config.get("uri", server.get("uri"))
    if not test_client_uri:
        logger.warning("No Podman URI specified for test client; using server's URI.")
        test_client_uri = server.get("uri")

    # Use the specified Podman URI to run the test client container
    test_runner = XRootDTestRunner(podman_sock=test_client_uri)

    logger.info(f"Running test client for {server.get('server', 'localhost')} with image {version} on podman URI {test_client_uri}")
    exit_code, logs = test_runner.run_test(version, test_command, test_volumes, test_env, artefact_paths)

    print("\n========== Test Logs ==========")
    print(logs)
    print("======== End Test Logs ========\n")

    # Record test finish time
    test_finish = datetime.datetime.utcnow().isoformat()

    timestamp: str = test_finish  # Use finish time for log key
    test_client_log_key = f"logs/{test_runner.test_container_name}-{timestamp}.log"
    if s3_uploader:
        s3_uploader.upload_logs(test_client_log_key, logs.encode())

    test_client_exit_code = exit_code
    test_client_container_name = test_runner.test_container_name

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
            version=version,
            container_name=test_client_container_name,
            timestamp=timestamp,
            exit_code=test_client_exit_code,
            log_key=test_client_log_key,
            test_name=test_json.get("name"),
            server_logs=server_logs_dict,
            test_client_log=None,
            test_start=test_start,
            test_finish=test_finish
        )

def run_tests_from_folder(
    test_dir: str = "tests",
    s3_uploader: Optional[S3Uploader] = None,
    opensearch_logger: Optional[OpenSearchLogger] = None,
    default_version: Optional[str] = None
) -> None:
    """
    Loads all test configurations from a folder and runs each test.

    Args:
        test_dir (str): Directory containing test configuration files.
        s3_uploader (Optional[S3Uploader]): S3 uploader instance for log upload.
        opensearch_logger (Optional[OpenSearchLogger]): OpenSearch logger instance.
        default_version (Optional[str]): Override for the default container version.
    """
    default_version = default_version or "gridppedi/xrdtesting:xrd-v5.8.3"
    for test_file in sorted(os.listdir(test_dir)):
        if not test_file.endswith(".json"):
            continue
        run_single_test(
            os.path.join(test_dir, test_file),
            default_version,
            s3_uploader,
            opensearch_logger
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
        help="Path to a single test configuration JSON file to run only that test"
    )
    parser.add_argument(
        "--container_version",
        type=str,
        default=None,
        help="Override the default container version for all tests"
    )
    # You can add more arguments here as needed
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

    if args.test_config:
        logger.info(f"Running single test from config: {args.test_config}")
        run_single_test(args.test_config, cli_default_version, s3_uploader, opensearch_logger)
    else:
        run_tests_from_folder(
            s3_uploader=s3_uploader,
            opensearch_logger=opensearch_logger,
            default_version=cli_default_version
        )
    logger.info("All tests complete.")

if __name__ == "__main__":
    main()
