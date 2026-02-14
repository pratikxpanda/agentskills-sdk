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
