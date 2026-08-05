# Working in this repository

Poetry monorepo. Eight packages, versioned and released together.

| Path | Package |
| --- | --- |
| `packages/core/agentskills-core` | Registry, `SkillProvider` ABC, spec validation. Only dependency is `pyyaml`. |
| `packages/providers/agentskills-fs` | Local filesystem provider |
| `packages/providers/agentskills-http` | Static HTTP / CDN provider |
| `packages/integrations/agentskills-langchain` | LangChain tools |
| `packages/integrations/agentskills-agentframework` | Microsoft Agent Framework context provider |
| `packages/integrations/agentskills-mcp-server` | MCP server + Agent Framework MCP bridge |
| `packages/cli/agentskills-cli` | `agentskills` command: init, validate, lint, inspect, serve |
| `packages/testing/agentskills-testing` | Provider conformance suite, `InMemorySkillProvider`, pytest fixtures |

Planning lives in `docs/ROADMAP.md`, per-milestone specs in `docs/issues/`, settled
decisions in `docs/adr/`.

## Branch workflow

Never commit to `main`. For every unit of work:

```bash
git checkout main
git pull --prune
git checkout -b <type>/<slug>      # fix/ feat/ perf/ docs/ chore/
# implement, test, lint
git push -u origin <branch>
```

The maintainer merges pull requests manually. **Do not create, update, or comment on
issues or pull requests, and do not use the `gh` CLI for that.** After a merge, sync
`main` and cut a fresh branch for the next item.

One roadmap item — or one tightly coupled cluster — per branch. If scope drifts, rename
the branch or squash-merge under a title that matches what actually landed.

### Labels

Releases are built with `generate_release_notes: true`, which groups merged pull requests
by the label map in `.github/release.yml`. **The label is the only input — the branch
prefix and commit message are ignored.** An unlabelled pull request lands under "Other
Changes", which is where most of 0.3.0 ended up.

| Branch prefix | Label to assign | Release-notes section |
| --- | --- | --- |
| `feat/` | `enhancement` or `feature` | Features |
| `fix/` | `bug` or `fix` | Bug Fixes |
| `docs/` | `documentation` | Documentation |
| CI, workflows, release tooling | `ci` or `automation` | CI/CD |
| `perf/`, `chore/` | — | Other Changes |

Label the pull request before merging; adding it afterwards does not change notes that
have already been generated. Adding a category means editing `.github/release.yml` and
creating the label in the repository — a label used in that file but absent from the
repository silently matches nothing.

## Commands

```bash
poetry install                                    # after any pyproject change, run poetry lock first
python -m pytest packages -q --no-header          # baseline: 1131 passed, 7 skipped
python -m ruff check packages/ examples/       # CI lints these two paths only
python -m ruff format --check packages/ examples/
python scripts/check_declared_dependencies.py     # a package must declare what it imports
```

`scripts/dev.py check` also runs a `mypy` step, but `mypy` is not currently installed —
that task fails for reasons unrelated to your change.

## Conventions

- Type hints on all public functions; Google-style docstrings on public APIs.
- Every package ships `py.typed`; keep the marker intact.
- Comments explain what the code cannot show on its own. One line, not a paragraph.
- Package READMEs are used verbatim as the PyPI `long_description`, so **every relative
  link in them is broken on PyPI**. Use absolute `https://github.com/...` URLs.

## Traps worth knowing

- **A new package must be registered in seven places.** Root `pyproject.toml` (path
  dependency, `[tool.coverage.run] source_pkgs`, `[tool.ruff.lint.isort]
  known-first-party`), `scripts/dev.py` `COVERAGE_FLOORS`, both `bump-version` scripts,
  `scripts/check_release_version.py`, and the build loop plus a publish step in
  `.github/workflows/publish.yml`. Miss the last one and the package silently never ships.
  `scripts/check_declared_dependencies.py` has its own list too, so eight.
- **A package can import what it never declared and nothing will notice**, because every
  package is installed into one shared virtualenv here. `agentskills-cli` imported `yaml`
  without declaring `pyyaml` for a whole milestone, riding on the copy `agentskills-core`
  pulled in. `scripts/check_declared_dependencies.py` runs in the lint job now; an import
  meant to stay optional belongs inside a function or behind `except ImportError`.
- **A package with a `pytest11` entry point is invisible to `pytest --cov`.** Entry-point
  plugins are imported before pytest-cov starts measuring, so the package reports 0% and
  drags everything it imports down with it. `scripts/dev.py test:cov` runs
  `coverage run -m pytest` for this reason; do not "simplify" it back.
- **Constructing an `httpx.AsyncClient` costs ~0.17s** (TLS context), which is why
  `agentskills-http`'s tests dominate the suite runtime. Share one module-scoped client
  when adding tests there — respx intercepts before it binds to an event loop.
- **`poetry.lock` hides upstream breaking changes.** Locked installs kept CI green while
  the published packages were broken for every new user. The advisory `test-unlocked` CI
  job resolves without the lock; when it fails, the fix belongs in a version constraint,
  not in the job.
- **Dependency ceilings need evidence.** Check the dependency's real `requires_python` and
  classifiers on PyPI before adding or trusting an upper bound.
- **The local venv holds packages that `poetry.lock` does not.** `tiktoken` is one. Anything
  imported optionally will therefore behave differently here and in CI, so a test that cares
  must force the branch with `monkeypatch.setitem(sys.modules, ...)` rather than rely on what
  happens to be importable.
- **Dependabot mangles the version comment on action pins.** `# v4.37.4.4.37.42.4.37.4` has
  appeared twice. The SHA is right and the comment is not, so read it as decoration and
  confirm with `git ls-remote --tags <repo> 'refs/tags/vX.Y.Z^{}'` — annotated tags, which
  `github/codeql-action` uses, need the `^{}` or you compare against the tag object.
- **A 200 response does not mean a badge rendered.** shields.io returns 200 with the words
  "rate limited by upstream service" drawn into the SVG. Inspect the rendered text.
- **An optional provider capability is a flag plus a raising default**, never an empty
  return. See [ADR 0002](../docs/adr/0002-optional-provider-capabilities.md):
  `supports_resource_listing` / `supports_discovery` are plain attributes, not `ClassVar`,
  so an instance can decide at construction time. Returning `[]` from `discover()` says the
  backend is empty, and a caller told that stops looking.
- **Adding an assertion to `ProviderConformanceSuite` is a downstream breaking change** if
  it needs anything new from the `provider` fixture. The fixture contract in `CONTRACT` is
  a compatibility surface for every third-party provider inheriting the suite.
- **Resolve markdown links programmatically** rather than counting `../` by eye.
- **PowerShell has no heredoc.** Use repeated `-m` flags for commit messages; embedded
  `` `n `` desynchronises the shell.
