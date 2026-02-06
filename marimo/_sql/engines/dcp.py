# Copyright 2026 Marimo. All rights reserved.
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Optional, Union

from marimo import _loggers
from marimo._data.models import (
    Database,
    DataTable,
    DataTableColumn,
    DataType,
    Schema,
)
from marimo._sql.engines.types import InferenceConfig, SQLConnection
from marimo._sql.utils import convert_to_output
from marimo._types.ids import VariableName

LOGGER = _loggers.marimo_logger()

# DCP error code to user-friendly message mapping
_DCP_ERROR_MESSAGES: dict[str, str] = {
    "CONNECTOR_NOT_FOUND": "Data source not found. Check the connector_id.",
    "QUERY_VALIDATION_ERROR": (
        "Only SELECT queries are allowed. Write operations are blocked."
    ),
    "QUERY_TIMEOUT": "Query timed out.",
    "FORBIDDEN": "You don't have permission to access this data source.",
}

# Mapping from DCP connector type to sqlglot dialect
_CONNECTOR_TYPE_TO_DIALECT: dict[str, str] = {
    "snowflake": "snowflake",
    "postgresql": "postgres",
    "postgres": "postgres",
    "clickhouse": "clickhouse",
    "mysql": "mysql",
}


def _resolve_base_url() -> str:
    return os.environ.get(
        "MARIMO_DCP_BASE_URL",
        os.environ.get("AMA_BASE_URL", "http://localhost:8000"),
    )


def _resolve_token() -> str:
    return os.environ.get(
        "MARIMO_DCP_TOKEN",
        os.environ.get("AMA_NOTEBOOK_TOKEN", ""),
    )


@dataclass
class DCPConnection:
    """Connection to a data source via the Data Connector Protocol (DCP).

    Typically created automatically by the DCP registry during auto-discovery.
    Configuration is resolved from environment variables:

        MARIMO_DCP_BASE_URL (or AMA_BASE_URL)   — DCP server URL
        MARIMO_DCP_TOKEN    (or AMA_NOTEBOOK_TOKEN) — Bearer token
    """

    connector_id: str
    base_url: str = field(default_factory=_resolve_base_url)
    token: str = field(default_factory=_resolve_token, repr=False)
    timeout_seconds: int = 300
    max_rows: int = 100_000


def _sql_type_to_data_type(sql_type: str) -> DataType:
    """Map SQL type strings from DCP to Marimo's DataType."""
    t = sql_type.upper()
    if any(k in t for k in ("INT", "SERIAL", "BIGINT", "SMALLINT")):
        return "integer"
    if any(k in t for k in ("FLOAT", "DOUBLE", "DECIMAL", "NUMERIC", "REAL")):
        return "number"
    if any(k in t for k in ("BOOL",)):
        return "boolean"
    if any(k in t for k in ("DATE",)) and "TIME" not in t:
        return "date"
    if any(k in t for k in ("TIMESTAMP", "DATETIME")):
        return "datetime"
    if any(k in t for k in ("TIME",)) and "STAMP" not in t:
        return "time"
    if any(
        k in t for k in ("CHAR", "TEXT", "STRING", "VARCHAR", "CLOB", "UUID")
    ):
        return "string"
    return "unknown"


def _raise_dcp_error(status_code: int, response: Any) -> None:
    """Raise a user-friendly error from a DCP error response."""
    if status_code == 401:
        raise RuntimeError(
            "Authentication expired. Restart the notebook to get a fresh token."
        )

    try:
        body = response.json()
    except Exception:
        raise RuntimeError(
            f"DCP request failed with status {status_code}: {response.text}"
        ) from None

    error = body.get("error", {})
    code = error.get("code", "UNKNOWN")
    message = error.get("message", response.text)

    friendly = _DCP_ERROR_MESSAGES.get(code)
    if friendly:
        if code == "QUERY_TIMEOUT":
            raise RuntimeError(f"{friendly} Server message: {message}")
        raise RuntimeError(friendly)

    # For QUERY_EXECUTION_ERROR and unknown codes, pass through the server message
    raise RuntimeError(f"DCP error ({code}): {message}")


class _CacheEntry:
    """Simple TTL cache entry."""

    __slots__ = ("value", "expires_at")

    def __init__(self, value: Any, ttl_seconds: float) -> None:
        self.value = value
        self.expires_at = time.monotonic() + ttl_seconds

    @property
    def expired(self) -> bool:
        return time.monotonic() >= self.expires_at


class DCPEngine(SQLConnection[DCPConnection]):
    """Marimo SQL engine backed by the Data Connector Protocol (DCP)."""

    def __init__(
        self,
        connection: DCPConnection,
        engine_name: Optional[VariableName] = None,
    ) -> None:
        super().__init__(connection, engine_name)
        self._dialect: Optional[str] = None
        # Caches: connector detail (permanent), schemas/tables (TTL)
        self._connector_detail_cache: Optional[dict[str, Any]] = None
        self._cache: dict[str, _CacheEntry] = {}

    # ── HTTP helper ──────────────────────────────────────────────

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Make an authenticated DCP request."""
        import httpx

        url = f"{self._connection.base_url}{path}"
        headers = {"Authorization": f"Bearer {self._connection.token}"}

        response = httpx.request(
            method,
            url,
            headers=headers,
            timeout=self._connection.timeout_seconds,
            **kwargs,
        )
        if response.status_code >= 400:
            _raise_dcp_error(response.status_code, response)
        return response

    # ── Caching ──────────────────────────────────────────────────

    def _get_cached(self, key: str) -> Any:
        entry = self._cache.get(key)
        if entry is not None and not entry.expired:
            return entry.value
        return None

    def _set_cached(self, key: str, value: Any, ttl: float) -> None:
        self._cache[key] = _CacheEntry(value, ttl)

    def _get_connector_detail(self) -> dict[str, Any]:
        if self._connector_detail_cache is not None:
            return self._connector_detail_cache

        resp = self._request(
            "GET",
            f"/dcp/v1/connectors/{self._connection.connector_id}",
        )
        detail: dict[str, Any] = resp.json()
        self._connector_detail_cache = detail
        return detail

    # ── BaseEngine properties ────────────────────────────────────

    @property
    def source(self) -> str:
        return "dcp"

    @property
    def dialect(self) -> str:
        if self._dialect is not None:
            return self._dialect

        try:
            detail = self._get_connector_detail()
            connector_type = detail.get("type", "").lower()
            self._dialect = _CONNECTOR_TYPE_TO_DIALECT.get(
                connector_type, connector_type
            )
        except Exception:
            LOGGER.warning("Failed to fetch DCP connector detail for dialect")
            self._dialect = "sql"

        return self._dialect

    @staticmethod
    def is_compatible(var: Any) -> bool:
        return isinstance(var, DCPConnection)

    # ── QueryEngine ──────────────────────────────────────────────

    def execute(self, query: str) -> Any:
        """Execute SQL via DCP and return a DataFrame."""
        response = self._request(
            "POST",
            f"/dcp/v1/connectors/{self._connection.connector_id}/query",
            json={
                "sql": query,
                "timeout_seconds": self._connection.timeout_seconds,
                "max_rows": self._connection.max_rows,
            },
        )

        import pyarrow.ipc as ipc

        reader = ipc.open_stream(response.content)
        table = reader.read_all()

        sql_output = self.sql_output_format()

        def to_polars() -> Any:
            import polars as pl

            return pl.from_arrow(table)

        def to_pandas() -> Any:
            return table.to_pandas()

        return convert_to_output(
            sql_output_format=sql_output,
            to_polars=to_polars,
            to_pandas=to_pandas,
        )

    # ── EngineCatalog ────────────────────────────────────────────

    @property
    def inference_config(self) -> InferenceConfig:
        return InferenceConfig(
            auto_discover_schemas=True,
            auto_discover_tables=True,
            auto_discover_columns="auto",
        )

    def get_default_database(self) -> Optional[str]:
        try:
            detail = self._get_connector_detail()
            db: Optional[str] = detail.get("connection_info", {}).get(
                "database"
            )
            return db
        except Exception:
            LOGGER.warning("Failed to get default database from DCP")
            return None

    def get_default_schema(self) -> Optional[str]:
        try:
            detail = self._get_connector_detail()
            schema: Optional[str] = detail.get("connection_info", {}).get(
                "schema"
            )
            return schema
        except Exception:
            LOGGER.warning("Failed to get default schema from DCP")
            return None

    def get_databases(
        self,
        *,
        include_schemas: Union[bool, Literal["auto"]],
        include_tables: Union[bool, Literal["auto"]],
        include_table_details: Union[bool, Literal["auto"]],
    ) -> list[Database]:
        try:
            detail = self._get_connector_detail()
        except Exception:
            LOGGER.warning("Failed to get DCP connector detail")
            return []

        db_name = detail.get("connection_info", {}).get(
            "database", self._connection.connector_id
        )

        schemas: list[Schema] = []
        if self._resolve_auto(include_schemas):
            schemas = self._fetch_schemas(
                include_tables=self._resolve_auto(include_tables),
                include_table_details=self._resolve_auto(
                    include_table_details
                ),
            )

        return [
            Database(
                name=db_name,
                dialect=self.dialect,
                schemas=schemas,
                engine=self._engine_name,
            )
        ]

    def get_tables_in_schema(
        self, *, schema: str, database: str, include_table_details: bool
    ) -> list[DataTable]:
        _ = database
        return self._fetch_tables(schema, include_table_details)

    def get_table_details(
        self, *, table_name: str, schema_name: str, database_name: str
    ) -> Optional[DataTable]:
        _ = database_name
        return self._fetch_table_detail(table_name, schema_name)

    # ── Private catalog helpers ──────────────────────────────────

    def _resolve_auto(self, value: Union[bool, Literal["auto"]]) -> bool:
        if value == "auto":
            return True
        return value

    def _fetch_schemas(
        self, include_tables: bool, include_table_details: bool
    ) -> list[Schema]:
        cache_key = "schemas"
        cached: Optional[list[Schema]] = self._get_cached(cache_key)
        if cached is not None and not include_tables:
            return cached

        try:
            resp = self._request(
                "GET",
                f"/dcp/v1/connectors/{self._connection.connector_id}/schemas",
            )
            schema_list = resp.json().get("schemas", [])
        except Exception:
            LOGGER.warning("Failed to fetch schemas from DCP")
            return []

        schemas: list[Schema] = []
        for s in schema_list:
            tables: list[DataTable] = []
            if include_tables:
                tables = self._fetch_tables(s["name"], include_table_details)
            schemas.append(Schema(name=s["name"], tables=tables))

        if not include_tables:
            self._set_cached(cache_key, schemas, ttl=60)
        return schemas

    def _fetch_tables(
        self, schema: str, include_details: bool
    ) -> list[DataTable]:
        cache_key = f"tables:{schema}:{include_details}"
        cached: Optional[list[DataTable]] = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            resp = self._request(
                "GET",
                f"/dcp/v1/connectors/{self._connection.connector_id}/tables",
                params={"schema": schema, "limit": 500},
            )
            table_list = resp.json().get("tables", [])
        except Exception:
            LOGGER.warning(f"Failed to fetch tables for schema {schema}")
            return []

        tables: list[DataTable] = []
        for t in table_list:
            if include_details:
                dt = self._fetch_table_detail(t["name"], schema)
                if dt:
                    tables.append(dt)
            else:
                tables.append(
                    DataTable(
                        source_type="connection",
                        source=self.dialect,
                        name=t["name"],
                        num_rows=t.get("row_count"),
                        num_columns=None,
                        variable_name=None,
                        engine=self._engine_name,
                        type="view" if t.get("type") == "VIEW" else "table",
                        columns=[],
                    )
                )

        self._set_cached(cache_key, tables, ttl=60)
        return tables

    def _fetch_table_detail(
        self, table_name: str, schema: str
    ) -> Optional[DataTable]:
        cache_key = f"detail:{schema}:{table_name}"
        cached: Optional[DataTable] = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            resp = self._request(
                "GET",
                f"/dcp/v1/connectors/{self._connection.connector_id}/tables/{table_name}",
                params={"schema": schema},
            )
            data = resp.json()
        except Exception:
            LOGGER.warning(
                f"Failed to fetch table detail for {schema}.{table_name}"
            )
            return None

        columns = [
            DataTableColumn(
                name=c["name"],
                type=_sql_type_to_data_type(c["type"]),
                external_type=c["type"],
                sample_values=[],
            )
            for c in data.get("columns", [])
        ]

        result = DataTable(
            source_type="connection",
            source=self.dialect,
            name=data["name"],
            num_rows=(
                data.get("statistics", {}).get("row_count")
                if data.get("statistics")
                else None
            ),
            num_columns=len(columns),
            variable_name=None,
            engine=self._engine_name,
            columns=columns,
        )

        self._set_cached(cache_key, result, ttl=300)
        return result
