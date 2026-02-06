# Copyright 2026 Marimo. All rights reserved.
"""DCP (Data Connector Protocol) registry.

DCP can be enabled via marimo config or environment variables:

    Config (marimo.toml / pyproject.toml):
        [tool.marimo.datasources]
        dcp_enabled = true
        dcp_base_url = "http://my-server:8000"

    Environment variables (fallback):
        MARIMO_DCP_TOKEN / AMA_NOTEBOOK_TOKEN  — Bearer token (required)
        MARIMO_DCP_BASE_URL / AMA_BASE_URL     — Server URL

When enabled, DCP auto-discovers connectors and surfaces them as SQL engines
alongside DuckDB.  Other built-in engines are suppressed so users connect
through pre-configured DCP data sources for everything except local work.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from marimo import _loggers
from marimo._config.config import DatasourcesConfig
from marimo._data.models import DataSourceConnection
from marimo._sql.engines.dcp import DCPConnection, DCPEngine
from marimo._sql.engines.types import BaseEngine
from marimo._types.ids import VariableName

LOGGER = _loggers.marimo_logger()

# Prefix for auto-discovered DCP engine variable names.
# These are "virtual" — they don't exist in user globals.
DCP_ENGINE_PREFIX = "__dcp_"


# ── Config helpers ────────────────────────────────────────────


def _get_datasources_config() -> DatasourcesConfig:
    """Read the [datasources] section from marimo config.

    Returns an empty dict if the context is not yet initialised or the
    key is missing — callers should treat missing keys as "not configured".
    """
    try:
        from marimo._runtime.context.types import (
            ContextNotInitializedError,
            get_context,
        )

        return get_context().marimo_config.get("datasources", {})
    except ContextNotInitializedError:
        pass
    except Exception:
        pass

    try:
        from marimo._config.manager import get_default_config_manager

        return (
            get_default_config_manager(current_path=None)
            .get_config()
            .get("datasources", {})
        )
    except Exception:
        pass

    return {}


def _get_dcp_base_url() -> str:
    """Resolve DCP base URL.

    Priority: config → MARIMO_DCP_BASE_URL → AMA_BASE_URL → default.
    """
    cfg = _get_datasources_config()
    config_url: Optional[str] = cfg.get("dcp_base_url")
    if config_url:
        return config_url

    return os.environ.get(
        "MARIMO_DCP_BASE_URL",
        os.environ.get("AMA_BASE_URL", "http://localhost:8000"),
    )


def _get_dcp_token() -> str:
    """Resolve DCP token from environment.

    Tokens are secrets and are only read from env vars, never config files.
    Checks MARIMO_DCP_TOKEN first, falls back to AMA_NOTEBOOK_TOKEN.
    """
    return os.environ.get(
        "MARIMO_DCP_TOKEN",
        os.environ.get("AMA_NOTEBOOK_TOKEN", ""),
    )


def is_dcp_enabled() -> bool:
    """Check if DCP mode is active.

    Resolution order:
      1. ``datasources.dcp_enabled`` in marimo config (explicit toggle)
      2. Presence of a DCP token env var (auto-detect)
    """
    cfg = _get_datasources_config()
    explicit: Optional[bool] = cfg.get("dcp_enabled")
    if explicit is not None:
        return explicit

    # Auto-detect: enabled if a token is available
    return bool(_get_dcp_token())


# ── Engine name helpers ───────────────────────────────────────


def _make_engine_name(connector: dict[str, Any]) -> VariableName:
    """Create a virtual variable name for a DCP connector."""
    name = connector.get("name", connector.get("id", "unknown"))
    # Sanitize: replace non-alphanumeric with underscore
    sanitized = "".join(c if c.isalnum() or c == "_" else "_" for c in name)
    return VariableName(f"{DCP_ENGINE_PREFIX}{sanitized}")


# ── Registry ──────────────────────────────────────────────────


class DCPRegistry:
    """Registry of auto-discovered DCP connectors.

    Singleton that caches discovered connectors for the session lifetime.
    """

    _instance: Optional[DCPRegistry] = None

    def __init__(self) -> None:
        self._engines: Optional[dict[VariableName, DCPEngine]] = None

    @classmethod
    def get(cls) -> DCPRegistry:
        if cls._instance is None:
            cls._instance = DCPRegistry()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (for testing)."""
        cls._instance = None

    def get_engines(self) -> dict[VariableName, DCPEngine]:
        """Return all auto-discovered DCP engines, discovering on first call."""
        if self._engines is not None:
            return self._engines

        self._engines = {}

        if not is_dcp_enabled():
            return self._engines

        base_url = _get_dcp_base_url()
        token = _get_dcp_token()

        try:
            import httpx

            resp = httpx.get(
                f"{base_url}/dcp/v1/connectors",
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
            if resp.status_code >= 400:
                LOGGER.warning(
                    "DCP connector discovery failed: %s", resp.status_code
                )
                return self._engines

            connectors: list[dict[str, Any]] = resp.json().get(
                "connectors", []
            )
        except Exception:
            LOGGER.warning("DCP connector discovery failed", exc_info=True)
            return self._engines

        for connector in connectors:
            if connector.get("status") != "active":
                continue

            connector_id = connector.get("id", "")
            engine_name = _make_engine_name(connector)

            conn = DCPConnection(
                connector_id=connector_id,
                base_url=base_url,
                token=token,
            )
            engine = DCPEngine(conn, engine_name=engine_name)

            # Pre-populate the connector detail cache to avoid a redundant
            # HTTP call (we already have the data from the list response).
            engine._connector_detail_cache = connector

            self._engines[engine_name] = engine
            LOGGER.debug(
                "DCP: registered connector %s as %s", connector_id, engine_name
            )

        LOGGER.info("DCP: discovered %d connectors", len(self._engines))
        return self._engines

    def get_engine(self, variable_name: VariableName) -> Optional[DCPEngine]:
        """Look up a DCP engine by its virtual variable name."""
        return self.get_engines().get(variable_name)

    def get_connections(self) -> list[DataSourceConnection]:
        """Return DataSourceConnection objects for all DCP engines."""
        from marimo._sql.get_engines import engine_to_data_source_connection

        return [
            engine_to_data_source_connection(name, engine)
            for name, engine in self.get_engines().items()
        ]


def get_dcp_engines() -> list[tuple[VariableName, BaseEngine[Any]]]:
    """Get all auto-discovered DCP engines as (name, engine) pairs.

    Returns empty list if DCP is not enabled.
    """
    registry = DCPRegistry.get()
    return list(registry.get_engines().items())
