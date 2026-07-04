# Copyright 2026 Marimo. All rights reserved.
"""Environment-driven notebook storage selection (ama fork).

When a notebook server runs in a stateless container (e.g. a Kubernetes pod
managed by the ama control plane), notebook files must live in object storage
rather than on the pod's ephemeral filesystem. The control plane injects:

    NOTEBOOK_STORAGE_BACKEND=s3
    NOTEBOOK_S3_BUCKET=<bucket>
    NOTEBOOK_S3_PREFIX=notebooks           # optional
    NOTEBOOK_S3_ENDPOINT_URL=<minio-url>   # optional; unset = AWS
    NOTEBOOK_S3_REGION=us-east-1           # optional
    NOTEBOOK_LOCAL_ROOT=/notebooks         # optional; see below

The server is started with a local-style path (``marimo edit
/notebooks/{tenant}/{name}.py``). That path stays the session's identity and
the local file acts as a cache: on session start the file is *hydrated* from
S3 (the app loader reads the local file), and every save *writes through* to
both S3 (durable) and the local file (so watchers/exports keep working).
Keys are built by relativizing the local path against ``NOTEBOOK_LOCAL_ROOT``:

    /notebooks/{tenant}/{name}.py  →  s3://{bucket}/{prefix}/{tenant}/{name}.py

which matches the key scheme the ama API uses when it creates/reads notebook
files server-side.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from marimo import _loggers
from marimo._session.notebook.s3_storage import S3Storage
from marimo._session.notebook.storage import StorageInterface
from marimo._utils.http import HTTPException, HTTPStatus

LOGGER = _loggers.marimo_logger()

_DEFAULT_LOCAL_ROOT = "/notebooks"


class WriteThroughS3Storage(S3Storage):
    """S3 storage with a local-file cache and root-relative keys.

    - ``_make_key`` strips the configured local root, so
      ``/notebooks/{tenant}/{name}.py`` becomes
      ``{prefix}/{tenant}/{name}.py`` in the bucket.
    - ``write`` persists to S3 first (durable), then mirrors to the local
      path best-effort so file watchers and exports keep working.
    - ``read`` prefers S3 and falls back to the local file when the object
      does not exist yet (fresh notebooks created empty by the CLI).
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        endpoint_url: Optional[str] = None,
        region: str = "us-east-1",
        local_root: str = _DEFAULT_LOCAL_ROOT,
    ) -> None:
        super().__init__(
            bucket=bucket,
            prefix=prefix,
            endpoint_url=endpoint_url,
            region=region,
        )
        self._local_root = local_root.rstrip("/")

    # -- key mapping --------------------------------------------------

    def _relativize(self, path: Path | str) -> str:
        path_str = str(path)
        root = self._local_root
        if root:
            # Handle both '/notebooks/x' and 'notebooks/x' forms — related
            # files (css/layout) arrive without the leading slash after
            # normalization in read_related_file.
            for candidate in (root + "/", root.lstrip("/") + "/"):
                if path_str.startswith(candidate):
                    return path_str[len(candidate) :]
        return path_str

    def _make_key(self, path: Path | str) -> str:
        return super()._make_key(self._relativize(path))

    def _local_path(self, path: Path | str) -> Optional[Path]:
        """The on-disk cache location for a storage path, if absolute."""
        path_str = str(path)
        if path_str.startswith("/"):
            return Path(path_str)
        if self._local_root:
            return Path(self._local_root) / self._relativize(path_str)
        return None

    # -- storage interface --------------------------------------------

    def read(self, path: Path | str) -> str:
        try:
            return super().read(path)
        except HTTPException as err:
            if err.status_code == HTTPStatus.NOT_FOUND:
                local = self._local_path(path)
                if local is not None and local.is_file():
                    return local.read_text(encoding="utf-8")
            raise

    def write(self, path: Path | str, content: str) -> None:
        super().write(path, content)
        local = self._local_path(path)
        if local is None:
            return
        try:
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_text(content, encoding="utf-8")
        except OSError as err:  # local mirror is best-effort
            LOGGER.warning("Failed to mirror notebook locally: %s", err)

    def exists(self, path: Path | str) -> bool:
        if super().exists(path):
            return True
        local = self._local_path(path)
        return local is not None and local.is_file()

    # -- session-start hydration ---------------------------------------

    def hydrate(self, path: Path | str) -> bool:
        """Materialize the S3 object to the local cache before app load.

        The app loader reads the local file directly, so a stateless pod
        must pull the durable copy down first. Returns True if hydrated.
        """
        local = self._local_path(path)
        if local is None:
            return False
        try:
            content = super().read(path)
        except HTTPException as err:
            if err.status_code == HTTPStatus.NOT_FOUND:
                LOGGER.debug("No S3 object to hydrate for %s", path)
                return False
            raise
        try:
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_text(content, encoding="utf-8")
        except OSError as err:
            LOGGER.error("Failed to hydrate notebook to %s: %s", local, err)
            return False
        LOGGER.info("Hydrated notebook from S3: %s (%d bytes)", path, len(content))
        return True


def notebook_storage_from_env(
    path: str | Path | None = None,
) -> Optional[StorageInterface]:
    """Build the storage backend the environment asks for, if any.

    When *path* is given and an S3 object exists for it, the local file is
    hydrated from S3 before returning (session start on a stateless pod).
    Returns ``None`` when no object-storage backend is configured, in which
    case callers fall back to the default filesystem storage.
    """
    backend = os.environ.get("NOTEBOOK_STORAGE_BACKEND", "").strip().lower()
    if backend in ("", "filesystem"):
        return None
    if backend != "s3":
        LOGGER.warning(
            "Unknown NOTEBOOK_STORAGE_BACKEND=%r; falling back to filesystem",
            backend,
        )
        return None

    bucket = os.environ.get("NOTEBOOK_S3_BUCKET", "").strip()
    if not bucket:
        LOGGER.warning(
            "NOTEBOOK_STORAGE_BACKEND=s3 but NOTEBOOK_S3_BUCKET is unset; "
            "falling back to filesystem storage — notebook edits will NOT "
            "be persisted across container restarts"
        )
        return None

    storage = WriteThroughS3Storage(
        bucket=bucket,
        prefix=os.environ.get("NOTEBOOK_S3_PREFIX", "").strip(),
        endpoint_url=os.environ.get("NOTEBOOK_S3_ENDPOINT_URL", "").strip()
        or None,
        region=os.environ.get("NOTEBOOK_S3_REGION", "").strip()
        or "us-east-1",
        local_root=os.environ.get("NOTEBOOK_LOCAL_ROOT", _DEFAULT_LOCAL_ROOT),
    )
    if path is not None:
        storage.hydrate(path)
    return storage
