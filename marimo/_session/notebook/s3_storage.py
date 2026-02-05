# Copyright 2026 Marimo. All rights reserved.
"""S3-based storage implementation for notebook persistence."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

from marimo import _loggers
from marimo._utils.http import HTTPException, HTTPStatus

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

LOGGER = _loggers.marimo_logger()


class S3Storage:
    """S3-based storage implementation.

    Stores notebook files in an S3 bucket with tenant-level prefixing
    for isolation. Compatible with S3-compatible services like MinIO.

    Example:
        storage = S3Storage(
            bucket="ama-notebooks",
            prefix="notebooks/tenant-123",
            endpoint_url="http://minio:9000",  # Optional for MinIO
            region="us-east-1",
        )

        # Read/write notebooks
        storage.write(Path("notebook.py"), "# marimo app...")
        content = storage.read(Path("notebook.py"))
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        endpoint_url: Optional[str] = None,
        region: str = "us-east-1",
    ) -> None:
        """Initialize S3 storage.

        Args:
            bucket: S3 bucket name.
            prefix: Key prefix for all objects (e.g., "notebooks/tenant-id").
            endpoint_url: S3 endpoint URL. None for AWS, set for MinIO/localstack.
            region: AWS region (default: us-east-1).
        """
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._endpoint_url = endpoint_url
        self._region = region
        self._client: Optional[S3Client] = None

    def _get_client(self) -> S3Client:
        """Get or create S3 client (lazy initialization)."""
        if self._client is None:
            try:
                import boto3
            except ImportError as err:
                raise ImportError(
                    "boto3 is required for S3 storage. "
                    "Install with: pip install marimo[s3]"
                ) from err

            self._client = boto3.client(
                "s3",
                endpoint_url=self._endpoint_url,
                region_name=self._region,
            )
        return self._client

    def _make_key(self, path: Path | str) -> str:
        """Convert a path to an S3 key with prefix.

        Args:
            path: Local-style path (e.g., Path("notebook.py") or "tenant/notebook.py")

        Returns:
            Full S3 key (e.g., "notebooks/tenant-123/notebook.py")
        """
        path_str = str(path).lstrip("/")
        if self._prefix:
            return f"{self._prefix}/{path_str}"
        return path_str

    def _strip_prefix(self, key: str) -> str:
        """Remove prefix from S3 key to get relative path."""
        if self._prefix and key.startswith(self._prefix + "/"):
            return key[len(self._prefix) + 1 :]
        return key

    def read(self, path: Path | str) -> str:
        """Read content from S3.

        Args:
            path: Path to read from (relative to prefix).

        Returns:
            File contents as string.

        Raises:
            HTTPException: If read fails (404 for not found, 500 for other errors).
        """
        client = self._get_client()
        key = self._make_key(path)

        try:
            response = client.get_object(Bucket=self._bucket, Key=key)
            content = response["Body"].read().decode("utf-8")
            LOGGER.debug(
                f"Read {len(content)} bytes from s3://{self._bucket}/{key}"
            )
            return content
        except client.exceptions.NoSuchKey as err:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=f"File not found: {path}",
            ) from err
        except Exception as err:
            LOGGER.error(f"Failed to read from S3: {err}")
            raise HTTPException(
                status_code=HTTPStatus.SERVER_ERROR,
                detail=f"Failed to read file {path}",
            ) from err

    def write(self, path: Path | str, content: str) -> None:
        """Write content to S3.

        Args:
            path: Path to write to (relative to prefix).
            content: Content to write.

        Raises:
            HTTPException: If write fails.
        """
        client = self._get_client()
        key = self._make_key(path)

        try:
            client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=content.encode("utf-8"),
                ContentType="text/x-python",
            )
            LOGGER.debug(
                f"Wrote {len(content)} bytes to s3://{self._bucket}/{key}"
            )
        except Exception as err:
            LOGGER.error(f"Failed to write to S3: {err}")
            raise HTTPException(
                status_code=HTTPStatus.SERVER_ERROR,
                detail=f"Failed to save file {path}",
            ) from err

    def exists(self, path: Path | str) -> bool:
        """Check if path exists in S3.

        Args:
            path: Path to check (relative to prefix).

        Returns:
            True if path exists, False otherwise.
        """
        client = self._get_client()
        key = self._make_key(path)

        try:
            client.head_object(Bucket=self._bucket, Key=key)
            return True
        except client.exceptions.ClientError as err:
            error_code = err.response.get("Error", {}).get("Code", "")
            if error_code == "404":
                return False
            LOGGER.warning(f"Error checking S3 object existence: {err}")
            return False
        except Exception as err:
            LOGGER.warning(f"Error checking S3 object existence: {err}")
            return False

    def rename(self, old_path: Path | str, new_path: Path | str) -> None:
        """Rename/move a file in S3.

        S3 doesn't support native rename, so this copies then deletes.

        Args:
            old_path: Source path (relative to prefix).
            new_path: Destination path (relative to prefix).

        Raises:
            HTTPException: If rename fails.
        """
        client = self._get_client()
        old_key = self._make_key(old_path)
        new_key = self._make_key(new_path)

        try:
            # Copy to new location
            client.copy_object(
                Bucket=self._bucket,
                CopySource={"Bucket": self._bucket, "Key": old_key},
                Key=new_key,
            )
            # Delete old object
            client.delete_object(Bucket=self._bucket, Key=old_key)
            LOGGER.debug(f"Renamed s3://{self._bucket}/{old_key} to {new_key}")
        except Exception as err:
            LOGGER.error(f"Failed to rename in S3: {err}")
            raise HTTPException(
                status_code=HTTPStatus.SERVER_ERROR,
                detail=f"Failed to rename from {old_path} to {new_path}",
            ) from err

    def delete(self, path: Path | str) -> bool:
        """Delete a file from S3.

        Args:
            path: Path to delete (relative to prefix).

        Returns:
            True if deleted, False if file didn't exist.
        """
        client = self._get_client()
        key = self._make_key(path)

        try:
            # Check existence first (S3 delete is idempotent)
            if not self.exists(path):
                return False

            client.delete_object(Bucket=self._bucket, Key=key)
            LOGGER.debug(f"Deleted s3://{self._bucket}/{key}")
            return True
        except Exception as err:
            LOGGER.warning(f"Failed to delete from S3: {err}")
            return False

    def is_same_path(self, path1: Path | str, path2: Path | str) -> bool:
        """Check if two paths refer to the same S3 location.

        Args:
            path1: First path.
            path2: Second path.

        Returns:
            True if paths refer to same S3 key.
        """
        key1 = self._make_key(path1)
        key2 = self._make_key(path2)
        return key1 == key2

    def get_absolute_path(self, path: Path | str) -> Path:
        """Get absolute path (returns virtual path for S3).

        For S3, we return a virtual path representing the S3 location.
        This is primarily for compatibility with the StorageInterface.

        Args:
            path: Path to make absolute.

        Returns:
            Virtual path as Path object.
        """
        # Return a virtual path that represents the S3 location
        # Format: /s3/{bucket}/{key}
        key = self._make_key(path)
        return Path(f"/s3/{self._bucket}/{key}")

    def read_related_file(
        self, base_path: Path | str, relative_path: str
    ) -> Optional[str]:
        """Read a file relative to a base path.

        Used for reading CSS files, layout configs, etc.

        Args:
            base_path: Base path (typically the notebook path).
            relative_path: Relative path from base.

        Returns:
            File contents or None if not found.
        """
        base_str = str(base_path)

        # Get the directory of the base path
        if "/" in base_str:
            base_dir = "/".join(base_str.split("/")[:-1])
        else:
            base_dir = ""

        # Resolve relative path
        if base_dir:
            full_path = f"{base_dir}/{relative_path}"
        else:
            full_path = relative_path

        # Normalize path (handle .. and .)
        parts = []
        for part in full_path.split("/"):
            if part == "..":
                if parts:
                    parts.pop()
            elif part != "." and part:
                parts.append(part)
        normalized_path = "/".join(parts)

        try:
            return self.read(normalized_path)
        except HTTPException as err:
            if err.status_code == HTTPStatus.NOT_FOUND:
                LOGGER.debug(f"Related file not found: {normalized_path}")
                return None
            raise

    def list_objects(self, prefix: str = "") -> list[str]:
        """List objects with an optional additional prefix.

        Args:
            prefix: Additional prefix to filter objects.

        Returns:
            List of object keys (relative to storage prefix).
        """
        client = self._get_client()
        full_prefix = self._make_key(prefix) if prefix else self._prefix

        try:
            response = client.list_objects_v2(
                Bucket=self._bucket,
                Prefix=full_prefix + "/" if full_prefix else "",
            )

            objects = []
            for obj in response.get("Contents", []):
                key = obj["Key"]
                relative_key = self._strip_prefix(key)
                objects.append(relative_key)

            return objects
        except Exception as err:
            LOGGER.warning(f"Failed to list S3 objects: {err}")
            return []
