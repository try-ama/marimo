/* Copyright 2026 Marimo. All rights reserved. */
import type { TypedString } from "@/utils/typed";

export type ConnectionName = TypedString<"ConnectionName">;

// DuckDB engine is treated as the default engine
// As it doesn't require passing an engine variable to the backend
// Keep this in sync with the backend name
export const DUCKDB_ENGINE = "__marimo_duckdb" as ConnectionName;
export const INTERNAL_SQL_ENGINES = new Set([DUCKDB_ENGINE]);
export const DEFAULT_DUCKDB_DATABASE = "memory";

// DCP (Data Connection Platform) engines use virtual variable names
// that don't exist as real Python variables.
// Keep this prefix in sync with DCP_ENGINE_PREFIX in marimo/_sql/dcp_registry.py
export const DCP_ENGINE_PREFIX = "__dcp_";

export function isDCPEngine(name: string): boolean {
  return name.startsWith(DCP_ENGINE_PREFIX);
}
