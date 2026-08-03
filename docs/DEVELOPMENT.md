# Development

> Part of the [Agent Skills SDK](../README.md).

## Prerequisites

- Python 3.12 or newer
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
poetry run pytest packages/cli/agentskills-cli -v
```

### Coverage

```bash
poetry run python scripts/dev.py test:cov
```

This runs the suite with branch coverage, writes `coverage.xml` and `htmlcov/`, and fails if any
package or the aggregate is below its floor. CI runs the same command and publishes the report to
the job summary of every run.

Coverage is measured by **import name**, not by path — `[tool.coverage.run] source_pkgs` in the
root `pyproject.toml`. Measuring `packages/` instead would count the test files, and a test file
is trivially covered by the act of running it.

Floors are enforced at two levels:

| Scope | Where | Why |
|---|---|---|
| Aggregate | `[tool.coverage.report] fail_under` | Enforced by `coverage report` itself, so a bare run is gated too |
| Per package | `COVERAGE_FLOORS` in `scripts/dev.py` | An aggregate floor alone lets one package rot behind the others |

Both were set to the value measured when the gate was introduced, and are meant to ratchet
upward. Raise a floor when its package moves up. If you have to lower one, say why in the PR —
the point of the gate is that lowering it is a visible decision rather than a silent drift.

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

GitHub Actions runs automatically on every push and pull request to `main`. The pipeline is defined in `.github/workflows/ci.yml` and includes these jobs:

- **Lint**: checks formatting (`ruff format --check`) and linting (`ruff check`)
- **Test**: runs `pytest` across Python 3.12, 3.13, and 3.14
- **Coverage**: runs the coverage gate and publishes the report to the job summary
- **Test (latest permitted dependencies)**: resolves without `poetry.lock` to surface upstream breakage; advisory only

All checks must pass before a PR can be merged. The CI status badge is shown on the root README.

### Security CI

- **pip-audit**: scans installed dependencies for known vulnerabilities (runs in the lint job)
- **CodeQL**: static application security testing for Python (`.github/workflows/codeql.yml`)
- **Dependabot**: automated dependency updates for `pip` and `github-actions` (`.github/dependabot.yml`)

For the full security policy and threat model, see [SECURITY.md](../SECURITY.md).

## Type Checking

All packages ship `py.typed` markers for PEP 561 compatibility. Run mypy via the dev task runner:

```bash
python scripts/dev.py typecheck
```

Type annotations are expected on all public functions and methods.

## Logging Conventions

Every package logs into one `agentskills.*` namespace. Get a logger with the shared helper and
pass `__name__` — the distribution prefix is rewritten, so `agentskills_http.static` logs as
`agentskills.http.static`:

```python
from agentskills_core import get_logger

_logger = get_logger(__name__)
```

Never call `logging.getLogger(__name__)` directly. It produces `agentskills_http.static`, which
does **not** descend from `agentskills`, so a host that raises the level on the namespace root
would silently miss that module.

A host application controls output with a single call:

```python
logging.getLogger("agentskills").setLevel(logging.DEBUG)
```

### Levels

| Level | Use for | Volume |
|---|---|---|
| `DEBUG` | Fetch, parse and cache events | Per request |
| `INFO` | Registration outcomes | Once per skill |
| `WARNING` | Degraded but recovered behaviour — a retried request, an unrecognised metadata key | Rare |

There is no `ERROR` level in the SDK. Anything that fails raises, and the caller decides whether
it was an error. Logging and raising the same failure reports it twice and takes that decision
away.

### Never log secrets

The library attaches only a `NullHandler`, so it has no idea where records end up — assume a
shared log aggregator.

- **Never log a raw URL.** Pass it through `redact_url()` first. Credentials live in query
  strings (SAS tokens, signed-URL signatures) and in userinfo. Providers with a configured base
  URL should use `redact_url(url, relative_to=base_url)`, which drops the host as well.
- **Never log request headers,** redacted or otherwise. There is no legitimate operational
  question that a header value answers, and a redactor you have to remember to call is a trap.
- **Never pass `exc_info` for a transport exception.** `httpx` exception reprs embed the full
  request URL, query string included — the same leak fixed in the error paths.

New log statements touching a URL or a request must be covered by a test asserting the secret
does not appear in `caplog.text`. See `TestLogRecordsCarryNoSecrets` in the HTTP provider tests.

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

The script also rewrites each dependent's `agentskills-core` constraint to `>=<new>,<1.0`. The
packages ship in lockstep, so a dependent must require the core it was released with —
otherwise pip can resolve an older core against a newer dependent and fail at import.

### 2. Commit and merge

Create a branch, commit the version bump, open a PR, and merge to `main`.

### 3. Tag

Publishing is triggered by the tag and nothing else. Verify the bump landed, then tag `main`:

```bash
python scripts/check_release_version.py --tag v<version>
git tag v<version>
git push origin v<version>
```

The tag must be `v` followed by the exact version string — `0.3.0rc1` is tagged `v0.3.0rc1`.
Only a bare `vX.Y.Z` tag publishes to PyPI; every other tag shape goes to TestPyPI, so a
malformed tag cannot burn a real version number.

### 4. Approve

`.github/workflows/publish.yml` builds every distribution, then waits on the `pypi`
environment for a reviewer. Approving releases all of them; there is one approval per
release, not one per package.

Publishing uses [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/) — the
runner mints a short-lived OIDC token, and no PyPI API token exists anywhere in the repository,
in Actions secrets, or on a workstation. Each distribution is uploaded with a PEP 740 provenance
attestation.

Packages go up in dependency order: core, then providers, then integrations. PyPI does not
enforce this; it exists so that nobody installing mid-release resolves a package whose
dependency is not there yet. If a run fails part-way, the failing step names the package and
everything above it is already live — re-running the job is safe, because published versions are
skipped rather than re-uploaded.

The GitHub Release, with auto-generated notes, is created only after every package is live, so
the notes never advertise a version that failed to publish. Releases from a non-`vX.Y.Z` tag are
marked as pre-releases.

### Dry runs

Run the **Publish** workflow manually (`workflow_dispatch`) to push the current build to
TestPyPI. Manual runs can only ever target TestPyPI; a production release requires a tag.

### Publishing by hand

`scripts/publish.ps1` still works and needs a PyPI token. It is for emergencies — recovering a
release when GitHub Actions is down. Prefer the workflow: it is the only path that produces
attestations and an audit trail.

#### One-time setup

Trusted Publishing is configured once per project, per index. Under *Manage → Publishing*, add a
GitHub publisher:

| Field | Value |
| --- | --- |
| Owner | `pratikxpanda` |
| Repository | `agentskills-sdk` |
| Workflow | `publish.yml` |
| Environment | `pypi` (on PyPI) / `testpypi` (on TestPyPI) |

Then create both environments under *Settings → Environments*, and add required reviewers to
`pypi`. The trusted publisher is bound to the workflow **filename**; renaming `publish.yml`
breaks publishing with an opaque OIDC error.

##### Bootstrapping a project that does not exist yet

A project with no releases has nothing to attach a publisher to, so you register a *pending*
publisher instead, from the account-level publishing page rather than the project's settings.

Pending publishers must be **uniquely identifiable by their claims**, and every package here
shares the same owner, repository, workflow and environment. The index cannot tell which pending
project an incoming token belongs to, so only one pending publisher can exist at a time:

> A pending trusted publisher matching this configuration has already been registered for a
> different project name.

Bootstrapping N projects on a fresh index therefore takes N sequential rounds — register one,
publish it, and the pending publisher converts to a project-scoped one, freeing the slot for the
next. `skip-existing` makes each round cheap, since packages already published are skipped.

This is worth knowing before adding a seventh package, or publishing to any new index.

## Project Structure

| Package | Description |
| --- | --- |
| `packages/core/agentskills-core` | Storage-agnostic abstractions (`SkillProvider`, `Skill`, `SkillRegistry`, `validate_skill`) |
| `packages/providers/agentskills-fs` | Load skills from the local filesystem |
| `packages/providers/agentskills-http` | Load skills from a static HTTP server |
| `packages/integrations/agentskills-langchain` | Integrate skills with LangChain agents |
| `packages/integrations/agentskills-agentframework` | Integrate skills with Microsoft Agent Framework agents |
| `packages/integrations/agentskills-mcp-server` | MCP server for exposing skills as MCP tools and resources (`agentskills-mcp-server` on PyPI) |
| `packages/cli/agentskills-cli` | The `agentskills` command: `init`, `validate`, `lint`, `inspect`, `serve` |

Each package has its own `pyproject.toml` under `packages/` and can be published independently. Every package except `agentskills-core` depends on it. The root `pyproject.toml` uses Poetry to manage workspace-level dependencies and installs all packages in editable mode.