# Marimo Fork Customizations

This is a fork of [marimo-team/marimo](https://github.com/marimo-team/marimo) maintained by try-ama.

## Why this fork exists

This fork is the **notebook surface of [Ama](https://github.com/try-ama/ama)**, the
agent-first notebook platform. Ama runs marimo kernels in per-notebook containers
and proxies agents (over MCP) and humans (browser) into the same shared kernel.

The fundamental connection point between the two repos is **DCP** — the Data
Connector Protocol (Ama RFC-022). Ama's server exposes governed, read-only data
sources (Snowflake, PostgreSQL, ClickHouse, MySQL) at `/dcp/v1/*`; this fork
carries the client: a `DCPEngine` SQL engine plus a registry that auto-discovers
connectors when a kernel boots, using the `AMA_BASE_URL` / `AMA_NOTEBOOK_TOKEN`
environment variables that Ama injects into each notebook container. Data sources
appear in the notebook's sources panel with no drivers or credentials in the
notebook itself.

Everything else in the fork (S3 notebook storage, embedding/panel mode, fork CI)
exists to make marimo run well inside that platform.

## Fork Strategy

We maintain a long-running fork that:
- Keeps `main` as a mirror of upstream (never commit directly)
- Uses the `fork` branch as our working main branch (all custom work lives here)
- Creates feature branches off `fork` for new work, merged back into `fork`
- Rebases `fork` onto `main` periodically to stay current with upstream

## Remotes

```
origin   -> git@github.com:try-ama/marimo.git (our fork)
upstream -> git@github.com:marimo-team/marimo.git (original)
```

## Fork Maintenance Scripts

All scripts are defined in `pyproject.toml` and run via hatch:

```bash
# Check how far behind/ahead of upstream
uvx hatch run fork-status

# Fetch latest from both remotes
uvx hatch run fork-fetch

# Sync main with upstream (fast-forward only, safe)
uvx hatch run fork-sync-main

# Push main to origin
uvx hatch run fork-push-main

# Rebase current feature branch onto main
uvx hatch run fork-rebase-branch

# Push feature branch with --force-with-lease (safe)
uvx hatch run fork-push-branch

# Full sync: fetch + sync main (then manually rebase branch)
uvx hatch run fork-full-sync

# Show recent upstream commits not yet in main
uvx hatch run fork-upstream-log
```

## Sync Workflow

### Weekly Sync (or before releases)

```bash
# 1. Check current status
uvx hatch run fork-status

# 2. Sync main with upstream
uvx hatch run fork-sync-main
uvx hatch run fork-push-main

# 3. Rebase fork onto updated main
git checkout fork
uvx hatch run fork-rebase-branch
uvx hatch run fork-push-branch
```

### Handling Conflicts During Rebase

If conflicts occur during `fork-rebase-branch`:

1. Resolve conflicts manually
2. `git add <resolved-files>`
3. `git rebase --continue`
4. Run `uvx hatch run fork-push-branch` when complete

## Custom Features

The full delta is visible with `git diff origin/main...fork`. Current customizations:

### 1. DCP SQL engine (the Ama connection point)
- `DCPEngine` + `DCPConnection`: a `SQLConnection` implementation that executes
  SQL cells over HTTP against Ama's DCP server and parses Arrow IPC responses
  into Polars DataFrames. Catalog methods populate the data sources panel.
- `dcp_registry.py`: singleton registry that calls `GET /dcp/v1/connectors` on
  kernel init and registers one virtual engine per connector
  (e.g. `__dcp_snowflake_prod`). Auth token from `MARIMO_DCP_TOKEN`, falling back
  to `AMA_NOTEBOOK_TOKEN` (env vars only — never config files).
- Files: `marimo/_sql/engines/dcp.py`, `marimo/_sql/dcp_registry.py`,
  `marimo/_sql/get_engines.py` (registered ahead of SQLAlchemy/DuckDB),
  `tests/_sql/test_dcp.py`.

### 2. S3 notebook storage
- Persists notebooks to S3 so Ama's containerized kernels are stateless.
- Files: `marimo/_session/notebook/s3_storage.py`, `marimo/_session/notebook/__init__.py`.

### 3. Embedding / panel mode
- Config-driven embedding features for running marimo inside the Ama frontend:
  panel visibility, chrome/sidebar adjustments, DCP connection broadcasting to
  the datasources panel, cached cell execution hooks.
- Files: `marimo/_config/config.py`, `marimo/_runtime/runtime.py`,
  `marimo/_runtime/runner/hooks_post_execution.py`,
  `frontend/src/core/config/embedding.ts`,
  `frontend/src/core/config/IfEmbeddingFeature.tsx`, plus chrome/sidebar/
  datasources component changes.

### 4. Display / fonts
- Custom font loading (Lilex, Geist Sans) behind a feature flag.
- Files: `frontend/src/hooks/useFontLoader.ts`, `frontend/src/theme/ThemeProvider.tsx`.

### 5. Fork CI
- Upstream release workflows removed; fork build/release automation and an
  upstream drift check added (`.github/workflows/upstream-check.yml`,
  `build-release.yml`). See "Build & Release Process" below.

### Design notes
- `docs/rfc-embedding-marimo-agentic.md` and
  `docs/rfc-embedding-marimo-agentic-frontend.md` — the RFCs behind the
  embedding work.
- Ama-side spec: `docs/DCP_MARIMO_INTEGRATION.md` and
  `docs/rfcs/RFC-022-data-connector-protocol.md` in the
  [try-ama/ama](https://github.com/try-ama/ama) repo.

## Installation in Other Projects

### From Branch (Development)
```toml
[project]
dependencies = [
    "marimo @ git+https://github.com/try-ama/marimo.git@fork",
]
```

### From Commit (Production)
```toml
[project]
dependencies = [
    "marimo @ git+https://github.com/try-ama/marimo.git@COMMIT_HASH",
]
```

Or with uv:
```bash
uv add "marimo @ git+https://github.com/try-ama/marimo.git@fork"
```

## Build & Release Process

The fork uses GitHub Actions to automatically build frontend assets and Python wheels.

### Automatic Builds

Every push to these branches triggers a build:
- `fork` - Auto-creates a GitHub release
- `ama-*` - Builds only, no release
- `feat/*`, `feature/*` - Builds only, no release

### Version Format

Versions follow the pattern `{upstream}-fork.{iteration}`:
- `0.19.6-fork.1` - First fork release based on upstream 0.19.6
- `0.19.6-fork.2` - Second iteration (e.g., fork-specific fixes)
- `0.19.7-fork.1` - After syncing with upstream 0.19.7

The iteration number is tracked in `.fork-version`.

### Creating a Release

**Automatic (recommended):** Push to `main` branch → release created automatically.

**Manual (for feature branches):**
1. Go to Actions → "Build & Release"
2. Click "Run workflow"
3. Check "Create a GitHub release"
4. Optionally override the fork iteration number

### Bumping the Fork Version

When making changes that warrant a new release:

```bash
# Increment the iteration number
echo "2" > .fork-version
git add .fork-version
git commit -m "chore: bump fork version to 2"
```

### Using Fork Releases

**Install via pip:**
```bash
pip install "marimo @ https://github.com/try-ama/marimo/releases/download/v0.19.6-fork.1/marimo-0.19.6-py3-none-any.whl"
```

**Use CDN assets (for containers/deployments):**
```bash
marimo edit --asset-url "https://cdn.jsdelivr.net/gh/try-ama/marimo@v0.19.6-fork.1/_static"
```

### CDN Asset URL Pattern

Assets are served via jsDelivr from GitHub releases:
```
https://cdn.jsdelivr.net/gh/try-ama/marimo@v{version}/_static
```

This is useful for:
- Docker containers that bundle only Python (no frontend build)
- Deployments where you want to serve assets from CDN
- Reducing container image size

### Version Reconciliation After Upstream Sync

When syncing with a new upstream version:

1. Sync main with upstream: `uvx hatch run fork-full-sync`
2. Reset iteration to 1: `echo "1" > .fork-version`
3. Rebase feature branch: `uvx hatch run fork-rebase-branch`
4. Push to trigger new release

## Upstream Contribution Policy

If a feature is general-purpose and could benefit the marimo community:
1. Create the feature in a separate branch
2. Submit a PR to upstream
3. Once merged upstream, remove from our fork during next sync
