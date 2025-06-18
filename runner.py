import re
import time
import socket
import datetime
import logging
import requests
from typing import Any, Dict, Optional, Tuple, List
from podman import PodmanClient
from podman.errors.exceptions import NotFound, APIError

# Ensure logger is defined for this module
logger = logging.getLogger("xrootdtesting")

class XRootDTestRunner:
    """
    Manages the lifecycle of XRootD server and test containers using Podman.
    Provides methods to launch servers, run test clients, collect logs, and clean up containers and artefacts.
    """

    def __init__(self, podman_sock: str):
        """
        Initialize the test runner with a Podman socket URI.

        Args:
            podman_sock (str): The Podman socket URI.
        """
        self.podman_sock: str = podman_sock
        self.test_volumes: Dict[str, Any] = {}

    def _get_client(self) -> PodmanClient:
        """
        Returns a Podman client connected to the specified socket.

        Returns:
            PodmanClient: A Podman client instance.
        """
        logger.debug(f"Connecting to Podman socket: {self.podman_sock}")
        return PodmanClient(base_url=self.podman_sock)

    def _generate_name(self, base: str, version: str, host: str) -> str:
        """
        Generates a unique container name, replacing invalid characters.

        Args:
            base (str): Base name for the container.
            version (str): Container image version.
            host (str): Hostname or identifier.

        Returns:
            str: Generated container name.
        """
        safe_version: str = re.sub(r'[^a-zA-Z0-9_.-]', '_', version)
        safe_host: str = re.sub(r'[^a-zA-Z0-9_.-]', '_', host)
        name: str = f"{base}-{safe_version}-{safe_host}"
        logger.debug(f"Generated container name: {name}")
        return name

    def _wait_for_service(self, host: str, port: int, timeout: int = 30) -> None:
        """
        Waits for a TCP service to become available.

        Args:
            host (str): Hostname to connect to.
            port (int): Port to connect to.
            timeout (int): Maximum number of seconds to wait.

        Raises:
            RuntimeError: If the service does not become ready in time.
        """
        logger.debug(f"Waiting for service {host}:{port} to become ready...")
        for i in range(timeout):
            try:
                with socket.create_connection((host, port), timeout=1):
                    logger.debug(f"Service {host}:{port} is ready.")
                    return
            except (ConnectionRefusedError, socket.timeout):
                logger.debug(f"Service {host}:{port} not ready yet, retry {i+1}/{timeout}")
                time.sleep(1)
        logger.error(f"Service {host}:{port} did not become ready in time")
        raise RuntimeError("Service did not become ready in time")

    def launch_server(self, version: str, server_config: Dict[str, Any]) -> None:
        """
        Launches the XRootD server container.

        Args:
            version (str): Container image version to use.
            server_config (Dict[str, Any]): Configuration for the server container, including entrypoint, volumes, host, port, and optionally environment variables.
        """
        self.server_container_name: str = self._generate_name("xrootd-posix", version, server_config['host'])
        logger.debug(f"Launching server container: {self.server_container_name} with image {version}")
        try:
            with self._get_client() as client:
                try:
                    client.containers.get(self.server_container_name).remove(force=True)
                    logger.debug(f"Removed existing server container: {self.server_container_name}")
                except NotFound:
                    logger.debug(f"No existing server container to remove: {self.server_container_name}")
                self.server_container = client.containers.run(
                    image=version,
                    name=self.server_container_name,
                    volumes=server_config["volumes"],
                    entrypoint=server_config["entrypoint"],
                    environment=server_config.get("environment", {}),
                    network_mode="host",
                    detach=True,
                    tty=True,
                    stdin_open=True,
                )
                logger.debug(f"Started server container: {self.server_container_name}")

                # Only wait for service if not using the default busybox config
                is_default: bool = (
                    server_config["entrypoint"] == ["/bin/sh", "-c", "echo 'Hello world'; sleep 300"]
                    and not server_config["volumes"]
                )
                if not is_default:
                    self._wait_for_service(server_config["host"], server_config["port"])
        except (requests.exceptions.ConnectionError, APIError) as e:
            logger.warning(f"Could not connect to Podman on {server_config['host']} ({self.podman_sock}): {e}")

    def run_test(
        self,
        version: str,
        test_command: List[str],
        test_volumes: Dict[str, Any],
        test_env: Dict[str, Any]
    ) -> Tuple[int, str]:
        """
        Runs the test client container and collects logs.

        Args:
            version (str): Container image version to use for the test client.
            test_command (List[str]): Command to run in the test client container.
            test_volumes (Dict[str, Any]): Volume mappings for the test client container.
            test_env (Dict[str, Any]): Environment variables for the test client container.

        Returns:
            Tuple[int, str]: (exit_code, logs) where exit_code is the container exit code and logs is the combined stdout/stderr output.
        """
        self.test_container_name: str = self._generate_name("xrootd-test-client", version, "test")
        self.test_volumes = test_volumes
        logger.debug(f"Running test client container: {self.test_container_name} with image {version}")
        with self._get_client() as client:
            try:
                client.containers.get(self.test_container_name).remove(force=True)
                logger.debug(f"Removed existing test container: {self.test_container_name}")
            except NotFound:
                logger.debug(f"No existing test container to remove: {self.test_container_name}")

            test_container = client.containers.run(
                image=version,
                name=self.test_container_name,
                volumes=test_volumes,
                environment=test_env,
                command=test_command,
                detach=True,
                remove=False,
                network_mode="host",
                tty=True,
            )
            logger.debug(f"Started test client container: {self.test_container_name}")

            test_container.wait()
            test_container.reload()
            exit_code: int = test_container.attrs["State"]["ExitCode"]
            logs: str = "".join(line.decode() for line in test_container.logs(stream=True, stdout=True, stderr=True))
            logger.debug(f"Test client container logs:\n{logs}")

            test_container.remove(force=True)
            logger.debug(f"Removed test client container: {self.test_container_name}")
            return exit_code, logs

    def cleanup_server(
        self,
        s3_uploader: Optional[Any] = None,
        opensearch_logger: Optional[Any] = None,
        test_name: Optional[str] = None
    ) -> None:
        """
        Stops the server container, captures and prints its logs, uploads logs to S3 and OpenSearch, then removes the server container if it exists.

        Args:
            s3_uploader (Optional[Any]): S3Uploader instance for uploading logs (optional).
            opensearch_logger (Optional[Any]): OpenSearchLogger instance for exporting metadata (optional).
            test_name (Optional[str]): Name of the test for metadata (optional).
        """
        logger.info(f"Cleaning up server container: {getattr(self, 'server_container_name', None)}")
        try:
            with self._get_client() as client:
                try:
                    container = client.containers.get(self.server_container_name)
                    # Stop the container first (if running)
                    if container.attrs["State"]["Running"]:
                        container.stop()
                        logger.debug(f"Stopped server container: {self.server_container_name}")
                    # Capture logs after stopping
                    logs: str = "".join(line.decode() for line in container.logs(stream=True, stdout=True, stderr=True))
                    print(f"\n========== Server Logs: {self.server_container_name} ==========")
                    print(logs)
                    print("======== End Server Logs ========\n")
                    # Upload logs to S3 if uploader is provided
                    if s3_uploader:
                        timestamp: str = datetime.datetime.utcnow().isoformat()
                        log_key: str = f"server-logs/{self.server_container_name}-{timestamp}.log"
                        s3_uploader.upload_logs(log_key, logs.encode())
                        logger.info(f"Uploaded server logs to S3: s3://{log_key}")
                    # Upload logs to OpenSearch if logger is provided
                    if opensearch_logger:
                        timestamp = datetime.datetime.utcnow().isoformat()
                        opensearch_logger.export_metadata(
                            version="server",
                            container_name=self.server_container_name,
                            timestamp=timestamp,
                            exit_code=None,
                            log_key=None,
                            test_name=test_name,
                            server_logs=logs
                        )
                    container.remove(force=True)
                    logger.debug(f"Removed server container: {self.server_container_name}")
                except NotFound:
                    logger.debug(f"No server container to remove: {self.server_container_name}")
        except (requests.exceptions.ConnectionError, APIError) as e:
            logger.warning(f"Could not connect to Podman for cleanup on {getattr(self, 'server_container_name', None)}: {e}")

    @staticmethod
    def cleanup_artefacts_with_container(
        volumes: Dict[str, Any],
        artefact_paths: List[str],
        cleanup_image: str = "busybox",
        podman_sock: str = "unix:///run/user/1000/podman/podman.sock"
    ) -> None:
        """
        Removes artefact files from host-mounted volumes using a short-lived cleanup container.

        Args:
            volumes (Dict[str, Any]): Volume mappings to mount into the cleanup container.
            artefact_paths (List[str]): List of file paths to remove from the mounted volumes.
            cleanup_image (str): Image to use for the cleanup container (default: "busybox").
            podman_sock (str): Podman socket URI to use for the cleanup container (default: user's podman.sock).
        """
        if not artefact_paths:
            logger.debug("No artefacts to clean up.")
            return

        cleanup_script: str = " && ".join([f"rm -f '{path}'" for path in artefact_paths])
        logger.debug(f"Cleaning up artefacts with cleanup container: {artefact_paths}")

        try:
            with PodmanClient(base_url=podman_sock) as client:
                client.containers.run(
                    image=cleanup_image,
                    name="cleanup-all-artefacts",
                    volumes=volumes,
                    command=["/bin/sh", "-c", cleanup_script],
                    remove=True,
                    detach=False,
                )
        except Exception as e:
            logger.error(f"Failed to clean up artefacts: {e}")
        else:
            logger.debug("Artefact cleanup container ran successfully.")
