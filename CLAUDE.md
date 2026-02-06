@AGENTS.md

## Quality Checks (Required Before Committing)

Every commit must pass all quality gates. Run these commands before `/checkpoint` or `/ship`:

```bash
# Run ALL checks (recommended)
make py-check && make fe-check

# Or run individually:
make py-check    # Python: typos, copyright, lint, format, typecheck
make fe-check    # Frontend: biome lint, eslint, stylelint, typecheck
```

### If Python Config Types Change

When modifying `marimo/_config/config.py` (adding TypedDicts, config fields), regenerate the OpenAPI schema:

```bash
# 1. Generate OpenAPI schema from Python
python -m marimo development openapi > packages/openapi/api.yaml

# 2. Regenerate TypeScript types
pnpm --filter @marimo-team/marimo-api codegen

# 3. Run frontend checks to verify types
make fe-check
```

### Common Lint Fixes

| Error | Fix |
|-------|-----|
| `noUnusedImports` | Remove the unused import |
| `noUselessFragments` | Replace `<>{children}</>` with `children` |
| Biome suppression placeholder | Replace `<explanation>` with actual reason |

## Slash Commands

| Command | Description |
|---------|-------------|
| `/checkpoint` | Create a local commit with rich context (for saving progress) |
| `/ship` | Commit, push, and open a PR (for completed work) |

Use `/checkpoint` during development to save progress at natural breakpoints.
Use `/ship` when work is complete and ready for review.

## Fork Workflow (try-ama/marimo)

This is a fork of marimo-team/marimo. See [FORK.md](FORK.md) for full documentation.

### Remotes

```
origin   -> try-ama/marimo (our fork)
upstream -> marimo-team/marimo (original)
```

### Branch Strategy

- **`main`**: Mirror of upstream. NEVER commit directly.
- **`fork`**: Our working main branch. All custom work lives here.
- **Feature branches**: Branch off `fork`, merge back into `fork`.

### Starting a New Feature

```bash
# 1. Ensure fork is up to date
git checkout fork

# 2. Create feature branch from fork
git checkout -b my-feature-name

# 3. Make changes, commit normally
git add <files>
git commit -m "feat: description"

# 4. Push to origin
git push -u origin my-feature-name
```

### Shipping Changes to Fork

```bash
# Push directly to fork branch
git checkout fork
git push origin fork

# Or after rebasing (use --force-with-lease for safety)
uvx hatch run fork-push-branch
```

### Keeping Fork Updated with Upstream

```bash
# 1. Sync main with upstream
uvx hatch run fork-full-sync

# 2. Rebase fork onto updated main
git checkout fork
uvx hatch run fork-rebase-branch

# 3. Push rebased fork branch (force-with-lease)
uvx hatch run fork-push-branch
```

### Fork Maintenance Scripts

| Command | Description |
|---------|-------------|
| `uvx hatch run fork-status` | Check commits behind/ahead of upstream |
| `uvx hatch run fork-sync-main` | Sync main with upstream (fast-forward only) |
| `uvx hatch run fork-push-main` | Push synced main to origin |
| `uvx hatch run fork-rebase-branch` | Rebase current branch onto main |
| `uvx hatch run fork-push-branch` | Push branch with --force-with-lease |
| `uvx hatch run fork-full-sync` | Fetch + sync main in one command |
| `uvx hatch run fork-upstream-log` | Show recent upstream commits |

### Safety Rules

1. **NEVER create PRs against upstream (marimo-team/marimo)** - All PRs go to our fork only
2. **Never commit to main** - It mirrors upstream
3. **Commit custom work to `fork` branch** - This is our working main
4. **Never use `--force`** - Always use `--force-with-lease` (scripts do this)
5. **Sync before branching** - Ensure `fork` is rebased on latest `main`
6. **Document customizations** - Update FORK.md when adding features

### Creating Pull Requests

Always specify the fork repo and base branch explicitly to avoid accidentally targeting upstream:

```bash
# CORRECT: PR against our fork's fork branch
gh pr create --repo try-ama/marimo --base fork

# WRONG: Don't use bare `gh pr create` - it may target upstream
```

### If Something Goes Wrong

```bash
# Check current state
uvx hatch run fork-status
git status
git log --oneline -10

# If main diverged from upstream (fork-sync-main failed)
git checkout main
git reset --hard upstream/main  # WARNING: discards local main commits
git push origin main --force-with-lease

# If rebase has conflicts
# Resolve conflicts, then:
git add <resolved-files>
git rebase --continue
# Or abort:
git rebase --abort
```
