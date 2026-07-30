# Working in this repository

Poetry monorepo. Six packages, versioned and released together.

| Path | Package |
| --- | --- |
| `packages/core/agentskills-core` | Registry, `SkillProvider` ABC, spec validation. Only dependency is `pyyaml`. |
| `packages/providers/agentskills-fs` | Local filesystem provider |
| `packages/providers/agentskills-http` | Static HTTP / CDN provider |
| `packages/integrations/agentskills-langchain` | LangChain tools |
| `packages/integrations/agentskills-agentframework` | Microsoft Agent Framework context provider |
| `packages/integrations/agentskills-mcp-server` | MCP server + Agent Framework MCP bridge |

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

## Commands

```bash
poetry install                                    # after any pyproject change, run poetry lock first
python -m pytest packages -q --no-header          # baseline: 327 passed, 1 skipped
python -m ruff check packages
python -m ruff format --check packages
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

- **`poetry.lock` hides upstream breaking changes.** Locked installs kept CI green while
  the published packages were broken for every new user. The advisory `test-unlocked` CI
  job resolves without the lock; when it fails, the fix belongs in a version constraint,
  not in the job.
- **Dependency ceilings need evidence.** Check the dependency's real `requires_python` and
  classifiers on PyPI before adding or trusting an upper bound.
- **A 200 response does not mean a badge rendered.** shields.io returns 200 with the words
  "rate limited by upstream service" drawn into the SVG. Inspect the rendered text.
- **Resolve markdown links programmatically** rather than counting `../` by eye.
- **PowerShell has no heredoc.** Use repeated `-m` flags for commit messages; embedded
  `` `n `` desynchronises the shell.
