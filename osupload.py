import logging
from typing import Any, Callable, Dict, Optional

from opensearchpy import OpenSearch

class OpenSearchLogger:
    """
    Handles exporting test metadata to OpenSearch or a compatible backend.
    """

    def __init__(self, upload_fn: Callable[[Dict[str, Any]], None]):
        """
        Args:
            upload_fn (callable): Function to handle the metadata export.
        """
        self.upload_fn = upload_fn

    def export_metadata(
        self,
        version: str,
        container_name: str,
        timestamp: str,
        exit_code: Optional[int],
        log_key: str,
        test_name: Optional[str] = None,
        server_logs: Optional[Dict[str, str]] = None,
        test_client_log: Optional[str] = None,
        test_start: Optional[str] = None,
        test_finish: Optional[str] = None,
        transfer_speed: Optional[float] = None,
        missing_artefacts: Optional[list] = None,  # <-- Added parameter
    ) -> None:
        """
        Exports metadata about a test run, including start and finish times, transfer speed, and missing artefacts.

        Args:
            version (str): The container image version.
            container_name (str): The name of the test container.
            timestamp (str): The timestamp of the test run.
            exit_code (int): The exit code of the test.
            log_key (str): The S3 key where logs are stored.
            test_name (str, optional): The test name from config.
            server_logs (dict, optional): The server logs S3 keys.
            test_client_log (str, optional): The test client logs.
            test_start (str, optional): The start time of the test.
            test_finish (str, optional): The finish time of the test.
            transfer_speed (float, optional): The transfer speed in MB/s.
            missing_artefacts (list, optional): List of missing artefact paths.
        """
        metadata: Dict[str, Any] = {
            "version": version,
            "timestamp": timestamp,
            "exit_code": exit_code,
            "log_s3_key": log_key,
            "container_name": container_name,
        }
        if test_name:
            metadata["test_name"] = test_name
        if server_logs:
            metadata["server_logs"] = server_logs
        if test_client_log:
            metadata["test_client_log"] = test_client_log
        if test_start:
            metadata["test_start"] = test_start
        if test_finish:
            metadata["test_finish"] = test_finish
        if transfer_speed is not None:
            metadata["transfer_speed_MBps"] = transfer_speed
        if missing_artefacts is not None:
            metadata["missing_artefacts"] = missing_artefacts  # <-- Add to metadata
        logger.debug(f"Exporting metadata: {metadata}")
        self.upload_fn(metadata)


def real_opensearch_upload(
    metadata: Dict[str, Any],
    host: str = "localhost",
    port: int = 9200,
    index: str = "xrootd-tests",
    username: Optional[str] = None,
    password: Optional[str] = None,
    use_ssl: bool = False
) -> None:
    """
    Uploads metadata to OpenSearch.
    """
    auth = (username, password) if username and password else None
    client = OpenSearch(
        hosts=[{"host": host, "port": port}],
        http_auth=auth,
        use_ssl=use_ssl,
        verify_certs=use_ssl,
    )
    response = client.index(index=index, body=metadata)
    logger.info(f"Uploaded metadata to OpenSearch: {response}")

# Add logger for this module
logger = logging.getLogger("xrootdtesting")
