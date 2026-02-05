# Copyright 2026 Marimo. All rights reserved.
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from marimo._data.models import DataSourceConnection
from marimo._dependencies.dependencies import DependencyManager
from marimo._sql.engines.dcp import (
    DCPConnection,
    DCPEngine,
    _sql_type_to_data_type,
)
from marimo._sql.engines.types import EngineCatalog, QueryEngine
from marimo._sql.get_engines import (
    engine_to_data_source_connection,
    get_engines_from_variables,
)
from marimo._types.ids import VariableName

HAS_POLARS = DependencyManager.polars.has()
HAS_PANDAS = DependencyManager.pandas.has()
HAS_DATAFRAME_LIB = HAS_POLARS or HAS_PANDAS


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def dcp_connection() -> DCPConnection:
    return DCPConnection(
        connector_id="test-connector",
        base_url="http://test-api:8000",
        token="test-jwt-token",
        timeout_seconds=30,
        max_rows=1000,
    )


@pytest.fixture
def dcp_engine(dcp_connection: DCPConnection) -> DCPEngine:
    return DCPEngine(dcp_connection, engine_name=VariableName("sf"))


# ── Helpers ───────────────────────────────────────────────────


def _make_response(
    status_code: int = 200,
    json_data: Any = None,
    content: bytes = b"",
    text: str = "",
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


CONNECTOR_DETAIL = {
    "id": "test-connector",
    "name": "Snowflake Prod",
    "type": "snowflake",
    "status": "active",
    "connection_info": {
        "account": "xy12345",
        "database": "ANALYTICS_DB",
        "schema": "PUBLIC",
    },
    "grants": {
        "can_query": True,
        "max_rows_per_query": None,
    },
}

SCHEMAS_RESPONSE = {
    "schemas": [
        {"name": "PUBLIC", "is_default": True},
        {"name": "STAGING", "is_default": False},
    ]
}

TABLES_RESPONSE = {
    "tables": [
        {"name": "users", "schema": "PUBLIC", "type": "TABLE"},
        {"name": "active_users", "schema": "PUBLIC", "type": "VIEW"},
    ],
    "pagination": {"total": 2, "limit": 500, "offset": 0, "has_more": False},
}

TABLE_DETAIL_RESPONSE = {
    "name": "users",
    "schema": "PUBLIC",
    "fully_qualified_name": "ANALYTICS_DB.PUBLIC.users",
    "columns": [
        {"name": "id", "type": "UUID", "nullable": False},
        {"name": "name", "type": "VARCHAR(255)", "nullable": False},
        {"name": "age", "type": "INTEGER", "nullable": True},
        {"name": "balance", "type": "DECIMAL(10,2)", "nullable": True},
        {"name": "is_active", "type": "BOOLEAN", "nullable": False},
        {"name": "created_at", "type": "TIMESTAMP", "nullable": False},
        {"name": "birth_date", "type": "DATE", "nullable": True},
        {"name": "login_time", "type": "TIME", "nullable": True},
    ],
    "statistics": {"row_count": 250000},
}


# ── DCPConnection tests ──────────────────────────────────────


def test_dcp_connection_creation() -> None:
    conn = DCPConnection(
        connector_id="my-snowflake",
        base_url="http://api:8000",
        token="jwt-token",
    )
    assert conn.connector_id == "my-snowflake"
    assert conn.base_url == "http://api:8000"
    assert conn.token == "jwt-token"
    assert conn.timeout_seconds == 300
    assert conn.max_rows == 100_000


def test_dcp_connection_defaults_from_env() -> None:
    with patch.dict(
        "os.environ",
        {
            "AMA_BASE_URL": "http://env-api:9000",
            "AMA_NOTEBOOK_TOKEN": "env-token",
        },
    ):
        conn = DCPConnection(connector_id="test")
        assert conn.base_url == "http://env-api:9000"
        assert conn.token == "env-token"


def test_dcp_connection_defaults_without_env() -> None:
    with patch.dict("os.environ", {}, clear=True):
        conn = DCPConnection(connector_id="test")
        assert conn.base_url == "http://localhost:8000"
        assert conn.token == ""


def test_dcp_connection_repr_hides_token() -> None:
    conn = DCPConnection(
        connector_id="test",
        token="secret-jwt-token",
    )
    r = repr(conn)
    assert "secret-jwt-token" not in r
    assert "connector_id" in r


# ── DCPEngine.is_compatible tests ────────────────────────────


def test_is_compatible_with_dcp_connection() -> None:
    conn = DCPConnection(connector_id="test")
    assert DCPEngine.is_compatible(conn) is True


def test_is_compatible_with_other_types() -> None:
    assert DCPEngine.is_compatible("not a connection") is False
    assert DCPEngine.is_compatible(42) is False
    assert DCPEngine.is_compatible(None) is False
    assert DCPEngine.is_compatible({"connector_id": "test"}) is False


# ── DCPEngine properties ─────────────────────────────────────


def test_engine_source(dcp_engine: DCPEngine) -> None:
    assert dcp_engine.source == "dcp"


def test_engine_is_instance(dcp_engine: DCPEngine) -> None:
    assert isinstance(dcp_engine, DCPEngine)
    assert isinstance(dcp_engine, EngineCatalog)
    assert isinstance(dcp_engine, QueryEngine)


@patch("httpx.request")
def test_engine_dialect(
    mock_request: MagicMock, dcp_engine: DCPEngine
) -> None:
    mock_request.return_value = _make_response(json_data=CONNECTOR_DETAIL)
    assert dcp_engine.dialect == "snowflake"


@patch("httpx.request")
def test_engine_dialect_postgres(mock_request: MagicMock) -> None:
    conn = DCPConnection(
        connector_id="pg",
        base_url="http://test:8000",
        token="tok",
    )
    engine = DCPEngine(conn)
    detail = {**CONNECTOR_DETAIL, "type": "postgresql"}
    mock_request.return_value = _make_response(json_data=detail)
    assert engine.dialect == "postgres"


@patch("httpx.request")
def test_engine_dialect_cached(
    mock_request: MagicMock, dcp_engine: DCPEngine
) -> None:
    mock_request.return_value = _make_response(json_data=CONNECTOR_DETAIL)
    # First call fetches
    assert dcp_engine.dialect == "snowflake"
    # Second call uses cache
    assert dcp_engine.dialect == "snowflake"
    # Should only have made one HTTP call for connector detail
    assert mock_request.call_count == 1


# ── DCPEngine.execute tests ──────────────────────────────────


@pytest.mark.skipif(not HAS_DATAFRAME_LIB, reason="polars or pandas required")
@patch("httpx.request")
def test_execute_returns_polars(
    mock_request: MagicMock, dcp_engine: DCPEngine
) -> None:
    import pyarrow as pa
    import pyarrow.ipc as ipc

    # Build Arrow IPC bytes
    table = pa.table({"id": [1, 2, 3], "name": ["a", "b", "c"]})
    sink = pa.BufferOutputStream()
    writer = ipc.new_stream(sink, table.schema)
    writer.write_table(table)
    writer.close()
    arrow_bytes = sink.getvalue().to_pybytes()

    mock_request.return_value = _make_response(content=arrow_bytes)

    result = dcp_engine.execute("SELECT * FROM users")

    # Should be a polars DataFrame or pandas (depends on availability)
    assert result is not None
    assert len(result) == 3

    # Verify the HTTP call
    mock_request.assert_called_once()
    call_kwargs = mock_request.call_args
    assert call_kwargs[0][0] == "POST"
    assert "/dcp/v1/connectors/test-connector/query" in call_kwargs[0][1]
    assert call_kwargs[1]["json"]["sql"] == "SELECT * FROM users"


# ── EngineCatalog tests ──────────────────────────────────────


@patch("httpx.request")
def test_get_default_database(
    mock_request: MagicMock, dcp_engine: DCPEngine
) -> None:
    mock_request.return_value = _make_response(json_data=CONNECTOR_DETAIL)
    assert dcp_engine.get_default_database() == "ANALYTICS_DB"


@patch("httpx.request")
def test_get_default_schema(
    mock_request: MagicMock, dcp_engine: DCPEngine
) -> None:
    mock_request.return_value = _make_response(json_data=CONNECTOR_DETAIL)
    assert dcp_engine.get_default_schema() == "PUBLIC"


@patch("httpx.request")
def test_get_databases(mock_request: MagicMock, dcp_engine: DCPEngine) -> None:
    # Mock responses for connector detail and schemas
    def side_effect(_method: str, url: str, **_kwargs: Any) -> MagicMock:
        if "/schemas" in url:
            return _make_response(json_data=SCHEMAS_RESPONSE)
        if "/tables/" in url:
            return _make_response(json_data=TABLE_DETAIL_RESPONSE)
        if "/tables" in url:
            return _make_response(json_data=TABLES_RESPONSE)
        # connector detail
        return _make_response(json_data=CONNECTOR_DETAIL)

    mock_request.side_effect = side_effect

    databases = dcp_engine.get_databases(
        include_schemas=True,
        include_tables=False,
        include_table_details=False,
    )

    assert len(databases) == 1
    db = databases[0]
    assert db.name == "ANALYTICS_DB"
    assert db.dialect == "snowflake"
    assert len(db.schemas) == 2
    assert db.schemas[0].name == "PUBLIC"
    assert db.schemas[1].name == "STAGING"


@patch("httpx.request")
def test_get_databases_with_tables(
    mock_request: MagicMock, dcp_engine: DCPEngine
) -> None:
    def side_effect(_method: str, url: str, **_kwargs: Any) -> MagicMock:
        if "/schemas" in url:
            return _make_response(json_data=SCHEMAS_RESPONSE)
        if "/tables/" in url:
            return _make_response(json_data=TABLE_DETAIL_RESPONSE)
        if "/tables" in url:
            return _make_response(json_data=TABLES_RESPONSE)
        return _make_response(json_data=CONNECTOR_DETAIL)

    mock_request.side_effect = side_effect

    databases = dcp_engine.get_databases(
        include_schemas=True,
        include_tables=True,
        include_table_details=False,
    )

    assert len(databases) == 1
    # PUBLIC schema should have tables
    public_schema = databases[0].schemas[0]
    assert len(public_schema.tables) == 2
    assert public_schema.tables[0].name == "users"
    assert public_schema.tables[0].type == "table"
    assert public_schema.tables[1].name == "active_users"
    assert public_schema.tables[1].type == "view"


@patch("httpx.request")
def test_get_databases_no_schemas(
    mock_request: MagicMock, dcp_engine: DCPEngine
) -> None:
    mock_request.return_value = _make_response(json_data=CONNECTOR_DETAIL)

    databases = dcp_engine.get_databases(
        include_schemas=False,
        include_tables=False,
        include_table_details=False,
    )

    assert len(databases) == 1
    assert databases[0].schemas == []


@patch("httpx.request")
def test_get_table_details(
    mock_request: MagicMock, dcp_engine: DCPEngine
) -> None:
    mock_request.return_value = _make_response(json_data=TABLE_DETAIL_RESPONSE)

    table = dcp_engine.get_table_details(
        table_name="users",
        schema_name="PUBLIC",
        database_name="ANALYTICS_DB",
    )

    assert table is not None
    assert table.name == "users"
    assert table.num_rows == 250000
    assert table.num_columns == 8
    assert len(table.columns) == 8

    # Check column type mapping
    col_map = {c.name: c for c in table.columns}
    assert col_map["id"].type == "string"  # UUID → string
    assert col_map["name"].type == "string"  # VARCHAR → string
    assert col_map["age"].type == "integer"  # INTEGER → integer
    assert col_map["balance"].type == "number"  # DECIMAL → number
    assert col_map["is_active"].type == "boolean"  # BOOLEAN → boolean
    assert col_map["created_at"].type == "datetime"  # TIMESTAMP → datetime
    assert col_map["birth_date"].type == "date"  # DATE → date
    assert col_map["login_time"].type == "time"  # TIME → time

    # Check external types are preserved
    assert col_map["id"].external_type == "UUID"
    assert col_map["name"].external_type == "VARCHAR(255)"


@patch("httpx.request")
def test_get_tables_in_schema(
    mock_request: MagicMock, dcp_engine: DCPEngine
) -> None:
    mock_request.return_value = _make_response(json_data=TABLES_RESPONSE)

    tables = dcp_engine.get_tables_in_schema(
        schema="PUBLIC",
        database="ANALYTICS_DB",
        include_table_details=False,
    )

    assert len(tables) == 2
    assert tables[0].name == "users"
    assert tables[1].name == "active_users"
    assert tables[1].type == "view"


# ── Type mapping tests ────────────────────────────────────────


@pytest.mark.parametrize(
    ("sql_type", "expected"),
    [
        ("INTEGER", "integer"),
        ("INT", "integer"),
        ("BIGINT", "integer"),
        ("SMALLINT", "integer"),
        ("SERIAL", "integer"),
        ("FLOAT", "number"),
        ("DOUBLE", "number"),
        ("DECIMAL(10,2)", "number"),
        ("NUMERIC", "number"),
        ("REAL", "number"),
        ("BOOLEAN", "boolean"),
        ("BOOL", "boolean"),
        ("DATE", "date"),
        ("TIMESTAMP", "datetime"),
        ("TIMESTAMP_NTZ", "datetime"),
        ("DATETIME", "datetime"),
        ("TIME", "time"),
        ("VARCHAR(255)", "string"),
        ("CHAR(10)", "string"),
        ("TEXT", "string"),
        ("STRING", "string"),
        ("CLOB", "string"),
        ("UUID", "string"),
        ("VARIANT", "unknown"),
        ("OBJECT", "unknown"),
        ("ARRAY", "unknown"),
    ],
)
def test_sql_type_to_data_type(sql_type: str, expected: str) -> None:
    assert _sql_type_to_data_type(sql_type) == expected


# ── Error handling tests ──────────────────────────────────────


@patch("httpx.request")
def test_error_connector_not_found(
    mock_request: MagicMock, dcp_engine: DCPEngine
) -> None:
    mock_request.return_value = _make_response(
        status_code=404,
        json_data={
            "error": {
                "code": "CONNECTOR_NOT_FOUND",
                "message": "Connector 'test-connector' not found",
            }
        },
    )

    with pytest.raises(
        RuntimeError, match="Data source not found. Check the connector_id."
    ):
        dcp_engine.execute("SELECT 1")


@patch("httpx.request")
def test_error_query_validation(
    mock_request: MagicMock, dcp_engine: DCPEngine
) -> None:
    mock_request.return_value = _make_response(
        status_code=400,
        json_data={
            "error": {
                "code": "QUERY_VALIDATION_ERROR",
                "message": "Write operations are not permitted",
            }
        },
    )

    with pytest.raises(RuntimeError, match="Only SELECT queries are allowed"):
        dcp_engine.execute("DROP TABLE users")


@patch("httpx.request")
def test_error_query_timeout(
    mock_request: MagicMock, dcp_engine: DCPEngine
) -> None:
    mock_request.return_value = _make_response(
        status_code=504,
        json_data={
            "error": {
                "code": "QUERY_TIMEOUT",
                "message": "Query exceeded 300s limit",
            }
        },
    )

    with pytest.raises(RuntimeError, match="Query timed out"):
        dcp_engine.execute("SELECT * FROM huge_table")


@patch("httpx.request")
def test_error_authentication_expired(
    mock_request: MagicMock, dcp_engine: DCPEngine
) -> None:
    mock_request.return_value = _make_response(
        status_code=401,
        text="Unauthorized",
    )

    with pytest.raises(RuntimeError, match="Authentication expired"):
        dcp_engine.execute("SELECT 1")


@patch("httpx.request")
def test_error_forbidden(
    mock_request: MagicMock, dcp_engine: DCPEngine
) -> None:
    mock_request.return_value = _make_response(
        status_code=403,
        json_data={
            "error": {
                "code": "FORBIDDEN",
                "message": "No permission",
            }
        },
    )

    with pytest.raises(RuntimeError, match="don't have permission"):
        dcp_engine.execute("SELECT 1")


@patch("httpx.request")
def test_error_execution_error_passes_through(
    mock_request: MagicMock, dcp_engine: DCPEngine
) -> None:
    mock_request.return_value = _make_response(
        status_code=500,
        json_data={
            "error": {
                "code": "QUERY_EXECUTION_ERROR",
                "message": 'Column "nonexistent" not found in table "users"',
            }
        },
    )

    with pytest.raises(RuntimeError, match="Column.*nonexistent.*not found"):
        dcp_engine.execute("SELECT nonexistent FROM users")


# ── Caching tests ─────────────────────────────────────────────


@patch("httpx.request")
def test_connector_detail_cached(
    mock_request: MagicMock, dcp_engine: DCPEngine
) -> None:
    mock_request.return_value = _make_response(json_data=CONNECTOR_DETAIL)

    # Multiple calls should only hit HTTP once
    dcp_engine.get_default_database()
    dcp_engine.get_default_database()
    dcp_engine.get_default_schema()

    assert mock_request.call_count == 1


@pytest.mark.skipif(not HAS_DATAFRAME_LIB, reason="polars or pandas required")
@patch("httpx.request")
def test_execute_never_cached(
    mock_request: MagicMock, dcp_engine: DCPEngine
) -> None:
    import pyarrow as pa
    import pyarrow.ipc as ipc

    table = pa.table({"x": [1]})
    sink = pa.BufferOutputStream()
    writer = ipc.new_stream(sink, table.schema)
    writer.write_table(table)
    writer.close()

    mock_request.return_value = _make_response(
        content=sink.getvalue().to_pybytes()
    )

    dcp_engine.execute("SELECT 1")
    dcp_engine.execute("SELECT 1")

    assert mock_request.call_count == 2


# ── Engine registration tests ────────────────────────────────


def test_get_engines_from_variables_dcp() -> None:
    conn = DCPConnection(
        connector_id="test",
        base_url="http://test:8000",
        token="tok",
    )
    variables: list[tuple[str, object]] = [("sf", conn)]

    engines = get_engines_from_variables(variables)
    assert len(engines) == 1
    var_name, engine = engines[0]
    assert var_name == "sf"
    assert isinstance(engine, DCPEngine)


def test_get_engines_dcp_does_not_match_other_types() -> None:
    variables: list[tuple[str, object]] = [
        ("a_string", "not a connection"),
        ("a_number", 42),
        ("a_dict", {"connector_id": "test"}),
    ]

    engines = get_engines_from_variables(variables)
    assert len(engines) == 0


@patch("httpx.request")
def test_engine_to_data_source_connection_dcp(
    mock_request: MagicMock,
) -> None:
    def side_effect(_method: str, url: str, **_kwargs: Any) -> MagicMock:
        if "/schemas" in url:
            return _make_response(json_data=SCHEMAS_RESPONSE)
        if "/tables" in url:
            return _make_response(
                json_data={"tables": [], "pagination": {"total": 0}}
            )
        return _make_response(json_data=CONNECTOR_DETAIL)

    mock_request.side_effect = side_effect

    conn = DCPConnection(
        connector_id="test-connector",
        base_url="http://test:8000",
        token="tok",
    )
    engine = DCPEngine(conn, engine_name=VariableName("sf"))

    connection = engine_to_data_source_connection(VariableName("sf"), engine)

    assert isinstance(connection, DataSourceConnection)
    assert connection.source == "dcp"
    assert connection.dialect == "snowflake"
    assert connection.name == "sf"
    assert connection.display_name == "snowflake (sf)"
    assert connection.default_database == "ANALYTICS_DB"
    assert connection.default_schema == "PUBLIC"


# ── Inference config test ─────────────────────────────────────


def test_inference_config(dcp_engine: DCPEngine) -> None:
    config = dcp_engine.inference_config
    assert config.auto_discover_schemas is True
    assert config.auto_discover_tables is True
    assert config.auto_discover_columns == "auto"
