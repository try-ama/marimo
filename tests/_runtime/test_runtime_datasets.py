# Copyright 2026 Marimo. All rights reserved.

from __future__ import annotations

import pytest

from marimo._dependencies.dependencies import DependencyManager
from marimo._messaging.notification import (
    DataSourceConnectionsNotification,
    SQLDatabaseMetadata,
    SQLMetadata,
    SQLSchemaListPreviewNotification,
    SQLTableListPreviewNotification,
    SQLTablePreviewNotification,
    ValidateSQLResultNotification,
)
from marimo._runtime.commands import (
    ExecuteCellCommand,
    ListDataSourceConnectionCommand,
    ListSQLSchemasCommand,
    ListSQLTablesCommand,
    PreviewSQLTableCommand,
    ValidateSQLCommand,
)
from marimo._runtime.context.types import get_context
from marimo._session.model import SessionMode
from marimo._sql.engines.duckdb import INTERNAL_DUCKDB_ENGINE
from marimo._sql.parse import SqlCatalogCheckResult, SqlParseResult
from marimo._types.ids import CellId_t, RequestId
from tests.conftest import MockedKernel

HAS_SQL = DependencyManager.duckdb.has() and DependencyManager.polars.has()


DUCKDB_CONN = "duckdb_conn"
SQLITE_CONN = "sqlite_conn"


@pytest.fixture
async def connection_requests() -> list[ExecuteCellCommand]:
    return [
        ExecuteCellCommand(cell_id=CellId_t("0"), code="import duckdb"),
        ExecuteCellCommand(
            cell_id=CellId_t("1"),
            code=f"{DUCKDB_CONN} = duckdb.connect(':memory:')",
        ),
        ExecuteCellCommand(cell_id=CellId_t("2"), code="import sqlite3"),
        ExecuteCellCommand(
            cell_id=CellId_t("3"),
            code=f"{SQLITE_CONN} = sqlite3.connect(':memory:')",
        ),
    ]


# @pytest.mark.skipif(not HAS_SQL, reason="SQL deps not available")
# class TestGetSQLConnection:
#     async def test_non_existent_engine(
#         self, mocked_kernel: MockedKernel
#     ) -> None:
#         k = mocked_kernel.k

#         # Non-existent engine
#         k.get_sql_connection(DUCKDB_CONN)
#         assert k.get_sql_connection(DUCKDB_CONN) == (None, "Engine not found")

#     async def test_created_engine(
#         self,
#         mocked_kernel: MockedKernel,
#         connection_requests: list[ExecuteCellCommand],
#     ) -> None:
#         k = mocked_kernel.k

#         # Create duckdb and sqlite connections
#         await k.run(connection_requests)

#         connection, error = k.get_sql_connection("duckdb_conn")
#         assert connection is not None
#         assert error is None

#         # Test with SQLite engine (which is a QueryEngine, but not a EngineCatalog)
#         connection, error = k.get_sql_connection(SQLITE_CONN)
#         assert connection is not None
#         assert error is None


@pytest.mark.skipif(not HAS_SQL, reason="SQL deps not available")
class TestPreviewSQLTable:
    async def test_non_existent_engine(
        self, mocked_kernel: MockedKernel
    ) -> None:
        k = mocked_kernel.k
        stream = mocked_kernel.stream

        preview_sql_table_request = PreviewSQLTableCommand(
            request_id=RequestId("0"),
            engine=DUCKDB_CONN,
            database="test",
            schema="test",
            table_name="t1",
        )
        await k.handle_message(preview_sql_table_request)

        preview_sql_table_results = [
            op
            for op in stream.operations
            if isinstance(op, SQLTablePreviewNotification)
        ]
        assert preview_sql_table_results == [
            SQLTablePreviewNotification(
                request_id=RequestId("0"),
                table=None,
                error="Engine not found",
                metadata=SQLMetadata(
                    connection=DUCKDB_CONN, database="test", schema="test"
                ),
            )
        ]

    async def test_catalog_engine(
        self,
        mocked_kernel: MockedKernel,
        connection_requests: list[ExecuteCellCommand],
    ) -> None:
        k = mocked_kernel.k
        stream = mocked_kernel.stream

        await k.run(connection_requests)

        preview_sql_table_request = PreviewSQLTableCommand(
            request_id=RequestId("0"),
            engine=DUCKDB_CONN,
            database="test",
            schema="test",
            table_name="t1",
        )
        await k.handle_message(preview_sql_table_request)

        preview_sql_table_results = [
            op
            for op in stream.operations
            if isinstance(op, SQLTablePreviewNotification)
        ]
        assert preview_sql_table_results == [
            SQLTablePreviewNotification(
                request_id=RequestId("0"),
                table=None,
                error=None,
                metadata=SQLMetadata(
                    connection=DUCKDB_CONN, database="test", schema="test"
                ),
            )
        ]

    async def test_query_engine(
        self,
        mocked_kernel: MockedKernel,
        connection_requests: list[ExecuteCellCommand],
    ) -> None:
        k = mocked_kernel.k
        stream = mocked_kernel.stream

        await k.run(connection_requests)

        preview_sql_table_request = PreviewSQLTableCommand(
            request_id=RequestId("0"),
            engine=SQLITE_CONN,
            database="test",
            schema="test",
            table_name="t1",
        )
        await k.handle_message(preview_sql_table_request)

        preview_sql_table_results = [
            op
            for op in stream.operations
            if isinstance(op, SQLTablePreviewNotification)
        ]
        assert preview_sql_table_results == [
            SQLTablePreviewNotification(
                request_id=RequestId("0"),
                table=None,
                error="Connection does not support catalog operations",
                metadata=SQLMetadata(
                    connection=SQLITE_CONN, database="test", schema="test"
                ),
            )
        ]


@pytest.mark.skipif(not HAS_SQL, reason="SQL deps not available")
class TestPreviewSQLSchemaList:
    async def test_non_existent_engine(
        self, mocked_kernel: MockedKernel
    ) -> None:
        k = mocked_kernel.k
        stream = mocked_kernel.stream

        preview_sql_schema_list_request = ListSQLSchemasCommand(
            request_id=RequestId("0"),
            engine=DUCKDB_CONN,
            database="test",
        )
        await k.handle_message(preview_sql_schema_list_request)
        preview_sql_schema_list_results = [
            op
            for op in stream.operations
            if isinstance(op, SQLSchemaListPreviewNotification)
        ]
        assert preview_sql_schema_list_results == [
            SQLSchemaListPreviewNotification(
                request_id=RequestId("0"),
                schemas=[],
                error="Engine not found",
                metadata=SQLDatabaseMetadata(
                    connection=DUCKDB_CONN, database="test"
                ),
            )
        ]

    async def test_catalog_engine(
        self,
        mocked_kernel: MockedKernel,
        connection_requests: list[ExecuteCellCommand],
    ) -> None:
        k = mocked_kernel.k
        stream = mocked_kernel.stream

        await k.run(connection_requests)

        preview_sql_schema_list_request = ListSQLSchemasCommand(
            request_id=RequestId("0"),
            engine=DUCKDB_CONN,
            database="test",
        )
        await k.handle_message(preview_sql_schema_list_request)

        preview_sql_schema_list_results = [
            op
            for op in stream.operations
            if isinstance(op, SQLSchemaListPreviewNotification)
        ]
        assert preview_sql_schema_list_results == [
            SQLSchemaListPreviewNotification(
                request_id=RequestId("0"),
                schemas=[],
                error=None,
                metadata=SQLDatabaseMetadata(
                    connection=DUCKDB_CONN, database="test"
                ),
            )
        ]

    async def test_query_engine(
        self,
        mocked_kernel: MockedKernel,
        connection_requests: list[ExecuteCellCommand],
    ) -> None:
        k = mocked_kernel.k
        stream = mocked_kernel.stream

        await k.run(connection_requests)

        preview_sql_schema_list_request = ListSQLSchemasCommand(
            request_id=RequestId("0"),
            engine=SQLITE_CONN,
            database="test",
        )
        await k.handle_message(preview_sql_schema_list_request)

        preview_sql_schema_list_results = [
            op
            for op in stream.operations
            if isinstance(op, SQLSchemaListPreviewNotification)
        ]
        assert preview_sql_schema_list_results == [
            SQLSchemaListPreviewNotification(
                request_id=RequestId("0"),
                schemas=[],
                error="Connection does not support catalog operations",
                metadata=SQLDatabaseMetadata(
                    connection=SQLITE_CONN, database="test"
                ),
            )
        ]

    async def test_nested_schema_path_echoed(
        self,
        mocked_kernel: MockedKernel,
        connection_requests: list[ExecuteCellCommand],
    ) -> None:
        """A request with a schema_path lists the child schemas at that path
        and echoes the path in the response metadata. Catalog engines without
        hierarchical namespaces return an empty list."""
        k = mocked_kernel.k
        stream = mocked_kernel.stream

        await k.run(connection_requests)

        preview_sql_schema_list_request = ListSQLSchemasCommand(
            request_id=RequestId("0"),
            engine=DUCKDB_CONN,
            database="test",
            schema_path=["sub"],
        )
        await k.handle_message(preview_sql_schema_list_request)

        results = [
            op
            for op in stream.operations
            if isinstance(op, SQLSchemaListPreviewNotification)
        ]
        assert results == [
            SQLSchemaListPreviewNotification(
                request_id=RequestId("0"),
                schemas=[],
                error=None,
                metadata=SQLDatabaseMetadata(
                    connection=DUCKDB_CONN,
                    database="test",
                    schema_path=["sub"],
                ),
            )
        ]


@pytest.mark.skipif(not HAS_SQL, reason="SQL deps not available")
class TestPreviewSQLTableList:
    async def test_non_existent_engine(
        self, mocked_kernel: MockedKernel
    ) -> None:
        k = mocked_kernel.k
        stream = mocked_kernel.stream

        preview_sql_table_list_request = ListSQLTablesCommand(
            request_id=RequestId("0"),
            engine=DUCKDB_CONN,
            database="test",
            schema="test",
        )
        await k.handle_message(preview_sql_table_list_request)
        preview_sql_table_list_results = [
            op
            for op in stream.operations
            if isinstance(op, SQLTableListPreviewNotification)
        ]
        assert preview_sql_table_list_results == [
            SQLTableListPreviewNotification(
                request_id=RequestId("0"),
                tables=[],
                error="Engine not found",
                metadata=SQLMetadata(
                    connection=DUCKDB_CONN, database="test", schema="test"
                ),
            )
        ]

    async def test_catalog_engine(
        self,
        mocked_kernel: MockedKernel,
        connection_requests: list[ExecuteCellCommand],
    ) -> None:
        k = mocked_kernel.k
        stream = mocked_kernel.stream

        await k.run(connection_requests)

        preview_sql_table_list_request = ListSQLTablesCommand(
            request_id=RequestId("0"),
            engine=DUCKDB_CONN,
            database="test",
            schema="test",
        )
        await k.handle_message(preview_sql_table_list_request)

        preview_sql_table_list_results = [
            op
            for op in stream.operations
            if isinstance(op, SQLTableListPreviewNotification)
        ]
        assert preview_sql_table_list_results == [
            SQLTableListPreviewNotification(
                request_id=RequestId("0"),
                tables=[],
                error=None,
                metadata=SQLMetadata(
                    connection=DUCKDB_CONN, database="test", schema="test"
                ),
            )
        ]

    async def test_query_engine(
        self,
        mocked_kernel: MockedKernel,
        connection_requests: list[ExecuteCellCommand],
    ) -> None:
        k = mocked_kernel.k
        stream = mocked_kernel.stream

        await k.run(connection_requests)

        preview_sql_table_list_request = ListSQLTablesCommand(
            request_id=RequestId("0"),
            engine=SQLITE_CONN,
            database="test",
            schema="test",
        )
        await k.handle_message(preview_sql_table_list_request)

        preview_sql_table_list_results = [
            op
            for op in stream.operations
            if isinstance(op, SQLTableListPreviewNotification)
        ]
        assert preview_sql_table_list_results == [
            SQLTableListPreviewNotification(
                request_id=RequestId("0"),
                tables=[],
                error="Connection does not support catalog operations",
                metadata=SQLMetadata(
                    connection=SQLITE_CONN, database="test", schema="test"
                ),
            )
        ]


class TestPreviewDatasourceConnection:
    async def test_non_existent_engine(
        self, mocked_kernel: MockedKernel
    ) -> None:
        k = mocked_kernel.k
        stream = mocked_kernel.stream

        preview_datasource_connection_request = (
            ListDataSourceConnectionCommand(engine=DUCKDB_CONN)
        )
        await k.handle_message(preview_datasource_connection_request)
        preview_datasource_connection_results = [
            op
            for op in stream.operations
            if isinstance(op, DataSourceConnectionsNotification)
        ]
        assert preview_datasource_connection_results == []

    @pytest.mark.skipif(not HAS_SQL, reason="SQL deps not available")
    async def test_query_only_engine_is_broadcast(
        self,
        mocked_kernel: MockedKernel,
        connection_requests: list[ExecuteCellCommand],
    ) -> None:
        """Regression: query-only engines (QueryEngine, not EngineCatalog) must broadcast."""
        k = mocked_kernel.k
        stream = mocked_kernel.stream

        await k.run(connection_requests)

        baseline = sum(
            1
            for op in stream.operations
            if isinstance(op, DataSourceConnectionsNotification)
        )

        await k.handle_message(
            ListDataSourceConnectionCommand(engine=SQLITE_CONN)
        )

        results = [
            op
            for op in stream.operations
            if isinstance(op, DataSourceConnectionsNotification)
        ]
        assert len(results) == baseline + 1
        connection = results[-1].connections[0]
        assert connection.name == SQLITE_CONN
        assert connection.databases == []

    @pytest.mark.xfail(
        reason="Should have only 2 connections (duckdb and sqlite)"
    )
    async def test_engines(
        self,
        mocked_kernel: MockedKernel,
        connection_requests: list[ExecuteCellCommand],
    ) -> None:
        k = mocked_kernel.k
        stream = mocked_kernel.stream

        await k.run(connection_requests)

        preview_datasource_connection_request = (
            ListDataSourceConnectionCommand(engine=DUCKDB_CONN)
        )
        await k.handle_message(preview_datasource_connection_request)

        preview_datasource_connection_results = [
            op
            for op in stream.operations
            if isinstance(op, DataSourceConnectionsNotification)
        ]
        assert len(preview_datasource_connection_results) == 2


@pytest.mark.skipif(not HAS_SQL, reason="SQL deps not available")
class TestSQLValidate:
    async def test_non_existent_engine(
        self, mocked_kernel: MockedKernel
    ) -> None:
        k = mocked_kernel.k
        stream = mocked_kernel.stream

        # Non-existent engine
        validate_sql_request = ValidateSQLCommand(
            request_id=RequestId("0"),
            engine=DUCKDB_CONN,
            query="SELECT * from t1",
            only_parse=False,
        )
        await k.handle_message(validate_sql_request)
        validate_sql_results = [
            op
            for op in stream.operations
            if isinstance(op, ValidateSQLResultNotification)
        ]
        assert validate_sql_results == [
            ValidateSQLResultNotification(
                request_id=RequestId("0"),
                parse_result=None,
                validate_result=None,
                error="Failed to get engine duckdb_conn",
            )
        ]

    async def test_internal_engine_and_valid_query(
        self, mocked_kernel: MockedKernel
    ) -> None:
        k = mocked_kernel.k
        stream = mocked_kernel.stream

        # Internal engine and valid query
        validate_sql_request = ValidateSQLCommand(
            request_id=RequestId("1"),
            engine=INTERNAL_DUCKDB_ENGINE,
            query="SELECT 1, 2",
            only_parse=False,
        )
        await k.handle_message(validate_sql_request)
        validate_sql_results = [
            op
            for op in stream.operations
            if isinstance(op, ValidateSQLResultNotification)
        ]
        assert validate_sql_results[-1] == ValidateSQLResultNotification(
            request_id=RequestId("1"),
            parse_result=SqlParseResult(success=True, errors=[]),
            validate_result=SqlCatalogCheckResult(
                success=True, error_message=None
            ),
            error=None,
        )

    async def test_internal_engine_and_invalid_query(
        self, mocked_kernel: MockedKernel
    ) -> None:
        k = mocked_kernel.k
        stream = mocked_kernel.stream

        # Internal engine and invalid query
        validate_sql_request = ValidateSQLCommand(
            request_id=RequestId("2"),
            engine=INTERNAL_DUCKDB_ENGINE,
            query="SELECT * FROM t1",
            only_parse=False,
        )
        await k.handle_message(validate_sql_request)
        validate_sql_results = [
            op
            for op in stream.operations
            if isinstance(op, ValidateSQLResultNotification)
        ]
        latest_validate_sql_result = validate_sql_results[-1]
        assert latest_validate_sql_result.request_id == RequestId("2")

        assert latest_validate_sql_result.parse_result is not None
        # query is syntactically valid
        assert latest_validate_sql_result.parse_result.success is True
        assert len(latest_validate_sql_result.parse_result.errors) == 0

        assert latest_validate_sql_result.validate_result is not None
        assert latest_validate_sql_result.validate_result.success is False
        assert (
            latest_validate_sql_result.validate_result.error_message
            is not None
        )
        assert latest_validate_sql_result.error is None

        stream.operations.clear()

    async def test_other_engine_and_valid_query(
        self,
        mocked_kernel: MockedKernel,
        connection_requests: list[ExecuteCellCommand],
    ) -> None:
        k = mocked_kernel.k
        stream = mocked_kernel.stream

        # Handle other engines
        await k.run(connection_requests)
        validate_sql_request = ValidateSQLCommand(
            request_id=RequestId("3"),
            engine=SQLITE_CONN,
            query="SELECT 1, 2",
            only_parse=False,
        )
        await k.handle_message(validate_sql_request)
        validate_sql_results = [
            op
            for op in stream.operations
            if isinstance(op, ValidateSQLResultNotification)
        ]
        assert (
            validate_sql_results[-1]
            == ValidateSQLResultNotification(
                request_id=RequestId("3"),
                parse_result=None,  # Currently does not support parse errors for non-duckdb engines
                validate_result=SqlCatalogCheckResult(
                    success=True, error_message=None
                ),
                error=None,
            )
        )

    async def test_only_parse_with_no_dialect(
        self,
        mocked_kernel: MockedKernel,
        connection_requests: list[ExecuteCellCommand],
    ) -> None:
        k = mocked_kernel.k
        stream = mocked_kernel.stream

        await k.run(connection_requests)

        validate_sql_request = ValidateSQLCommand(
            request_id=RequestId("4"),
            engine=SQLITE_CONN,
            query="SELECT 1, 2",
            only_parse=True,
        )
        await k.handle_message(validate_sql_request)

        validate_sql_results = [
            op
            for op in stream.operations
            if isinstance(op, ValidateSQLResultNotification)
        ]
        assert validate_sql_results[-1] == ValidateSQLResultNotification(
            request_id=RequestId("4"),
            parse_result=None,
            validate_result=None,
            error="Dialect is required when only parsing",
        )

    async def test_only_parse_unsupported_dialect(
        self,
        mocked_kernel: MockedKernel,
        connection_requests: list[ExecuteCellCommand],
    ) -> None:
        k = mocked_kernel.k
        stream = mocked_kernel.stream

        await k.run(connection_requests)

        validate_sql_request = ValidateSQLCommand(
            request_id=RequestId("5"),
            dialect="sqlite",
            query="SELECT 1, 2",
            only_parse=True,
        )
        await k.handle_message(validate_sql_request)

        validate_sql_results = [
            op
            for op in stream.operations
            if isinstance(op, ValidateSQLResultNotification)
        ]
        assert validate_sql_results[-1] == ValidateSQLResultNotification(
            request_id=RequestId("5"),
            parse_result=None,
            validate_result=None,
            error="Unsupported dialect: sqlite",
        )

    async def test_only_parse_duckdb(
        self,
        mocked_kernel: MockedKernel,
        connection_requests: list[ExecuteCellCommand],
    ) -> None:
        k = mocked_kernel.k
        stream = mocked_kernel.stream

        await k.run(connection_requests)

        validate_sql_request = ValidateSQLCommand(
            request_id=RequestId("6"),
            dialect="duckdb",
            query="SELECT 1, 2",
            only_parse=True,
        )
        await k.handle_message(validate_sql_request)

        validate_sql_results = [
            op
            for op in stream.operations
            if isinstance(op, ValidateSQLResultNotification)
        ]
        assert validate_sql_results[-1] == ValidateSQLResultNotification(
            request_id=RequestId("6"),
            parse_result=SqlParseResult(success=True, errors=[]),
            validate_result=None,
            error=None,
        )

    async def test_validate_but_no_engine(
        self,
        mocked_kernel: MockedKernel,
        connection_requests: list[ExecuteCellCommand],
    ) -> None:
        k = mocked_kernel.k
        stream = mocked_kernel.stream

        await k.run(connection_requests)

        validate_sql_request = ValidateSQLCommand(
            request_id=RequestId("7"),
            query="SELECT 1, 2",
            only_parse=False,
        )
        await k.handle_message(validate_sql_request)

        validate_sql_results = [
            op
            for op in stream.operations
            if isinstance(op, ValidateSQLResultNotification)
        ]
        assert validate_sql_results[-1] == ValidateSQLResultNotification(
            request_id=RequestId("7"),
            parse_result=None,
            validate_result=None,
            error="Engine is required for validating catalog",
        )


class TestDCPBroadcastInEmbeddedMode:
    """DCP connections are platform-managed and should broadcast even when
    the kernel is running in an embedded context (``App.embed()``).
    """

    async def test_dcp_connections_broadcast_when_embedded(
        self,
        mocked_kernel: MockedKernel,
    ) -> None:
        """DCP connections should be broadcast in edit mode even when embedded."""
        from unittest.mock import MagicMock, patch

        from marimo._data.models import DataSourceConnection
        from marimo._runtime.runner.cell_runner import _should_broadcast_data
        from marimo._runtime.runner.hooks_post_execution import (
            _broadcast_data_source_connection,
        )

        ctx = get_context()
        # Simulate embedded mode by setting a parent
        original_parent = ctx.parent
        ctx.parent = MagicMock()  # non-None parent → is_embedded() == True
        assert ctx.is_embedded()

        fake_connection = DataSourceConnection(
            source="dcp",
            dialect="postgresql",
            name="__dcp_test_connector",
            display_name="Test DCP Connector",
            databases=[],
            default_database=None,
            default_schema=None,
        )

        mock_cell = MagicMock()
        mock_cell.defs = []
        mock_hook_ctx = MagicMock()
        mock_hook_ctx.glbls = {}
        # Embedded → the runner would compute should_broadcast_data=False
        mock_hook_ctx.should_broadcast_data = _should_broadcast_data()
        assert mock_hook_ctx.should_broadcast_data is False
        mock_run_result = MagicMock()

        stream = mocked_kernel.stream

        try:
            with (
                patch(
                    "marimo._sql.dcp_registry.is_dcp_enabled",
                    return_value=True,
                ),
                patch(
                    "marimo._sql.dcp_registry.DCPRegistry"
                ) as mock_registry_cls,
            ):
                mock_registry = MagicMock()
                mock_registry.get_connections.return_value = [fake_connection]
                mock_registry_cls.get.return_value = mock_registry

                # Clear previous operations
                stream.operations.clear()

                _broadcast_data_source_connection(
                    mock_cell, mock_hook_ctx, mock_run_result
                )

            dcp_notifications = [
                op
                for op in stream.operations
                if isinstance(op, DataSourceConnectionsNotification)
            ]
            assert len(dcp_notifications) == 1
            assert dcp_notifications[0].connections == [fake_connection]
        finally:
            ctx.parent = original_parent

    async def test_dcp_connections_not_broadcast_in_run_mode(
        self,
        mocked_kernel: MockedKernel,
    ) -> None:
        """DCP connections should NOT be broadcast in run mode."""
        from unittest.mock import MagicMock, patch

        from marimo._runtime.runner.cell_runner import _should_broadcast_data
        from marimo._runtime.runner.hooks_post_execution import (
            _broadcast_data_source_connection,
        )

        # MockedKernel defaults to EDIT mode; switch to RUN
        ctx = get_context()
        original_mode = ctx._session_mode
        ctx._session_mode = SessionMode.RUN

        mock_cell = MagicMock()
        mock_cell.defs = []
        mock_hook_ctx = MagicMock()
        mock_hook_ctx.glbls = {}
        # Run mode → the runner would compute should_broadcast_data=False
        mock_hook_ctx.should_broadcast_data = _should_broadcast_data()
        assert mock_hook_ctx.should_broadcast_data is False
        mock_run_result = MagicMock()

        stream = mocked_kernel.stream

        try:
            with patch(
                "marimo._sql.dcp_registry.is_dcp_enabled",
                return_value=True,
            ) as mock_enabled:
                stream.operations.clear()

                _broadcast_data_source_connection(
                    mock_cell, mock_hook_ctx, mock_run_result
                )

                # is_dcp_enabled should never be called in run mode
                mock_enabled.assert_not_called()

            dcp_notifications = [
                op
                for op in stream.operations
                if isinstance(op, DataSourceConnectionsNotification)
            ]
            assert len(dcp_notifications) == 0
        finally:
            ctx._session_mode = original_mode

    async def test_user_engines_not_broadcast_when_embedded(
        self,
        mocked_kernel: MockedKernel,
    ) -> None:
        """User-defined SQL engines should still be suppressed when embedded."""
        from unittest.mock import MagicMock, patch

        from marimo._runtime.runner.cell_runner import _should_broadcast_data
        from marimo._runtime.runner.hooks_post_execution import (
            _broadcast_data_source_connection,
        )

        ctx = get_context()
        original_parent = ctx.parent
        ctx.parent = MagicMock()  # embedded
        assert ctx.is_embedded()

        mock_cell = MagicMock()
        mock_cell.defs = ["my_engine"]
        mock_hook_ctx = MagicMock()
        mock_hook_ctx.glbls = {"my_engine": MagicMock()}
        # Embedded → the runner would compute should_broadcast_data=False
        mock_hook_ctx.should_broadcast_data = _should_broadcast_data()
        assert mock_hook_ctx.should_broadcast_data is False
        mock_run_result = MagicMock()

        stream = mocked_kernel.stream

        try:
            with (
                patch(
                    "marimo._sql.dcp_registry.is_dcp_enabled",
                    return_value=False,
                ),
                patch(
                    "marimo._runtime.runner.hooks_post_execution.get_engines_from_variables",
                    return_value=[],
                ) as mock_get_engines,
            ):
                stream.operations.clear()

                _broadcast_data_source_connection(
                    mock_cell, mock_hook_ctx, mock_run_result
                )

                # _should_broadcast_data() returns False when embedded,
                # so get_engines_from_variables should never be called
                mock_get_engines.assert_not_called()

            dcp_notifications = [
                op
                for op in stream.operations
                if isinstance(op, DataSourceConnectionsNotification)
            ]
            assert len(dcp_notifications) == 0
        finally:
            ctx.parent = original_parent
