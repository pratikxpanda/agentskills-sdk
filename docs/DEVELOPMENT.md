# Development

> Part of the [Agent Skills SDK](../README.md).

## Prerequisites

- Python 3.12+
- [Poetry](https://python-poetry.org/) 2.0+

## Setup

```bash
poetry install
```

This creates a `.venv` in the project root and installs all packages in editable mode along with dev dependencies (pytest, ruff).

## Testing

Run the full test suite from the repository root:

```bash
poetry run pytest packages/ -v
```

Run tests for a single package:

```bash
poetry run pytest packages/core/agentskills-core -v
poetry run pytest packages/providers/agentskills-fs -v
poetry run pytest packages/providers/agentskills-http -v
poetry run pytest packages/integrations/agentskills-langchain -v
poetry run pytest packages/integrations/agentskills-agentframework -v
poetry run pytest packages/integrations/agentskills-mcp-server -v
```

## Linting & Formatting

This project uses [Ruff](https://docs.astral.sh/ruff/) for both linting and formatting. Configuration lives in the root `pyproject.toml`.

```bash
# Check for lint issues
poetry run ruff check packages/ examples/

# Auto-fix safe issues
poetry run ruff check packages/ examples/ --fix

# Format code
poetry run ruff format packages/ examples/
```

## Cleaning Caches

Remove all generated caches and build artifacts:

```bash
# PowerShell
Get-ChildItem -Recurse -Directory -Include __pycache__,.pytest_cache,.ruff_cache,*.egg-info | Remove-Item -Recurse -Force

# Bash / macOS / Linux
find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache -o -name '*.egg-info' \) -exec rm -rf {} +
```

## Dev Task Runner

A task runner script is available at `scripts/dev.py` for common development tasks:

```bash
python scripts/dev.py lint          # Check linting
python scripts/dev.py lint:fix      # Auto-fix lint issues
python scripts/dev.py format        # Auto-format code
python scripts/dev.py format:check  # Check formatting without changes
python scripts/dev.py typecheck     # Run mypy type checking
python scripts/dev.py check         # Lint + format check + type check
python scripts/dev.py test          # Run all tests
python scripts/dev.py test:cov      # Run tests with coverage
python scripts/dev.py clean         # Remove cache files
python scripts/dev.py all           # Format + lint + test
```

## CI

GitHub Actions runs automatically on every push and pull request to `main`. The pipeline is defined in `.github/workflows/ci.yml` and includes two jobs:

- **Lint**: checks formatting (`ruff format --check`) and linting (`ruff check`)
- **Test**: runs `pytest` across Python 3.12 and 3.13

All checks must pass before a PR can be merged. The CI status badge is shown on the root README.

## Releasing

### 1. Bump version

All packages share the same version. Use the bump script to update all `pyproject.toml` files at once:

```powershell
# Patch: 0.2.0 -> 0.2.1
.\scripts\bump-version.ps1

# Minor: 0.2.0 -> 0.3.0
.\scripts\bump-version.ps1 -Bump minor

# Major: 0.2.0 -> 1.0.0
.\scripts\bump-version.ps1 -Bump major

# Explicit version
.\scripts\bump-version.ps1 -Version 1.0.0

# Preview without changing files
.\scripts\bump-version.ps1 -Bump minor -DryRun
```

### 2. Commit and merge

Create a branch, commit the version bump, open a PR, and merge to `main`.

### 3. Publish to PyPI

```powershell
# Publish all packages in dependency order
.\scripts\publish.ps1

# Test on TestPyPI first
.\scripts\publish.ps1 -TestPyPI

# Build only (no publish)
.\scripts\publish.ps1 -BuildOnly
```

Packages are published in dependency order: core, then providers, then integrations.

### 4. Tag and release

Push a version tag to trigger the GitHub Release workflow (`.github/workflows/release.yml`):

```bash
git tag v0.3.0
git push origin v0.3.0
```

This automatically creates a GitHub Release with auto-generated notes from merged PRs and commits since the previous tag.

## Project Structure

| Package | Description |
| --- | --- |
| `packages/core/agentskills-core` | Storage-agnostic abstractions (`SkillProvider`, `Skill`, `SkillRegistry`, `validate_skill`) |
| `packages/providers/agentskills-fs` | Load skills from the local filesystem |
| `packages/providers/agentskills-http` | Load skills from a static HTTP server |
| `packages/integrations/agentskills-langchain` | Integrate skills with LangChain agents |
| `packages/integrations/agentskills-agentframework` | Integrate skills with Microsoft Agent Framework agents |
| `packages/integrations/agentskills-mcp-server` | MCP server for exposing skills as MCP tools and resources (`agentskills-mcp-server` on PyPI) |

Each package has its own `pyproject.toml` under `packages/` and can be published independently. `agentskills-fs`, `agentskills-http`, `agentskills-langchain`, `agentskills-agentframework`, and `agentskills-mcp-server` depend on `agentskills-core`. The root `pyproject.toml` uses Poetry to manage workspace-level dependencies and installs all packages in editable mode.
