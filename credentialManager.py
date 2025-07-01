import logging
import os
import subprocess
from typing import List, Dict, Optional

# Ensure logger is defined for this module
logger = logging.getLogger("credentialManager")

class CredentialManager:
    """
    Handles checking and distributing authentication credentials required for XRootD tests.
    """

    def __init__(self, x509_path: str = "/tmp/x509up_u1000", bearer_env: str = "BEARER_TOKEN"):
        self.x509_path = x509_path
        self.bearer_env = bearer_env
        self.bearer_token = None

    def check_credentials(self) -> bool:
        """
        Checks for the existence of the x509 file and the BEARER_TOKEN environment variable,
        and ensures the x509 proxy is valid with sufficient time left.

        Returns:
            bool: True if both credentials are present and valid, False otherwise.
        """
        if not os.path.isfile(self.x509_path):
            logger.error(f"Credential file not found: {self.x509_path}")
            return False
        if not os.access(self.x509_path, os.R_OK):
            logger.error(f"Credential file not readable: {self.x509_path}")
            return False
        # Check x509 proxy validity (>1hr left)
        if not check_x509_proxy_validity(self.x509_path, min_seconds=3600):
            logger.error(f"x509 proxy at {self.x509_path} is invalid or has less than 1 hour left.")
            return False
        self.bearer_token = os.environ.get(self.bearer_env)
        if not self.bearer_token:
            logger.error(f"Environment variable {self.bearer_env} is not set or empty.")
            return False
        logger.info("All required credentials are present and valid.")
        return True

    def distribute_x509_to_nodes(self, remote_hosts: List[str], remote_path: str = "/tmp/x509up_u1000", user: str = "root") -> None:
        """
        Copies the x509 file to the specified remote hosts using scp. Removes the old cert before uploading the new one, and ensures the file is owned by uid:gid 1000:1000.

        Args:
            remote_hosts (List[str]): List of hostnames or IPs to copy the file to.
            remote_path (str): Path on the remote host to copy the file to.
            user (str): Username for scp/ssh.
        """
        for host in remote_hosts:
            dest = f"{user}@{host}:{remote_path}"
            try:
                # Remove old cert on remote host before copying new one
                logger.info(f"Removing old x509 cert at {remote_path} on {host}")
                subprocess.run([
                    "ssh", f"{user}@{host}", f"rm -f {remote_path}"
                ], check=True)
                logger.info(f"Copying {self.x509_path} to {dest}")
                subprocess.run(["scp", self.x509_path, dest], check=True)
                # Ensure file ownership is 1000:1000
                logger.info(f"Setting ownership of {remote_path} to 1000:1000 on {host}")
                subprocess.run([
                    "ssh", f"{user}@{host}", f"chown 1000:1000 {remote_path}"
                ], check=True)
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to copy x509 file to {host}: {e}")
                raise RuntimeError(f"Failed to copy x509 file to {host}: {e}")

    def inject_bearer_token(self, env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """
        Adds the BEARER_TOKEN to the provided environment dictionary.

        Args:
            env (Optional[Dict[str, str]]): Existing environment variables.

        Returns:
            Dict[str, str]: Updated environment variables including BEARER_TOKEN.
        """
        if env is None:
            env = {}
        env[self.bearer_env] = self.bearer_token
        return env

def check_x509_proxy_validity(x509_path: str = "/tmp/x509up_u1000", min_seconds: int = 3600) -> bool:
    """
    Checks if the x509 proxy at the given path is valid using voms-proxy-info,
    and ensures it has at least min_seconds of validity left.

    Args:
        x509_path (str): Path to the x509 proxy file.
        min_seconds (int): Minimum required validity in seconds (default: 3600 = 1 hour).

    Returns:
        bool: True if the proxy is valid and has at least min_seconds left, False otherwise.
    """
    try:
        result = subprocess.run(
            ["voms-proxy-info", "--all", "--file", x509_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            text=True
        )
        output = result.stdout
        if "timeleft" in output:
            for line in output.splitlines():
                if line.strip().startswith("timeleft"):
                    _, value = line.split(":", 1)
                    value = value.strip()
                    h, m, s = map(int, value.split(":"))
                    total_seconds = h * 3600 + m * 60 + s
                    if total_seconds >= min_seconds:
                        return True
                    else:
                        logger.error(f"x509 proxy at {x509_path} has only {total_seconds//3600}h{(total_seconds%3600)//60}m left (< {min_seconds//3600}h required).")
                        return False
        logger.error(f"x509 proxy at {x509_path} is invalid or expired:\n{output}")
        return False
    except Exception as e:
        logger.error(f"Failed to check x509 proxy validity: {e}")
        return False
