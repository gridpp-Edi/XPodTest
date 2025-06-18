import logging
from typing import Callable, Optional

import boto3
from botocore.client import Config

class S3Uploader:
    """
    Handles uploading logs to S3 or a compatible storage backend.
    """
    def __init__(self, upload_fn: Callable[[str, bytes], None]):
        """
        Args:
            upload_fn (callable): Function to handle the upload.
        """
        self.upload_fn = upload_fn

    def upload_logs(self, key: str, content: bytes) -> None:
        """
        Uploads logs using the provided upload function.

        Args:
            key (str): The S3 key for the log file.
            content (bytes): The log content to upload.
        """
        logger.debug(f"Uploading logs with key: {key}")
        self.upload_fn(key, content)

def real_s3_upload(
    key: str,
    content: bytes,
    bucket: str = "your-bucket", 
    endpoint_url: str = "https://s3.amazonaws.com",
    aws_access_key_id: Optional[str] = "your-access-key",
    aws_secret_access_key: Optional[str] = "your-secret-key"
) -> None:
    """
    Uploads logs to S3-compatible storage using boto3.
    """
    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1"
    )
    s3.put_object(Bucket=bucket, Key=key, Body=content)
    logger.info(f"Uploaded logs to S3: s3://{bucket}/{key}")

# Add logger for this module
logger = logging.getLogger("xrootdtesting")