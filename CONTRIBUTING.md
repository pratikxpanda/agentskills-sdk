# Contributing to Agent Skills SDK

Thank you for your interest in contributing! This guide covers the process for reporting issues, suggesting improvements, and submitting pull requests.

## Code of Conduct

Be respectful and constructive. Harassment, discrimination, and abusive behavior will not be tolerated.

## Getting Started

### Prerequisites

- Python 3.12+
- [Poetry](https://python-poetry.org/) 2.0+

### Development Setup

```bash
# Clone the repository
git clone https://github.com/pratikxpanda/agentskills-sdk.git
cd agentskills-sdk

# Install all packages in editable mode with dev dependencies
poetry install
```

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for the full development guide, including testing, linting, type checking, and project structure.

## Reporting Issues

- **Bugs**: Open a [GitHub issue](https://github.com/pratikxpanda/agentskills-sdk/issues/new) with a clear description, steps to reproduce, and expected vs actual behavior.
- **Feature requests**: Open an issue to discuss your idea before submitting a PR.
- **Security vulnerabilities**: **Do not open a public issue.** Follow the process in [SECURITY.md](SECURITY.md).

## Pull Request Process

1. **Fork** the repository and create a feature branch:
   ```bash
   git checkout -b feat/my-feature
   ```

2. **Make your changes** with tests. Every new feature or bug fix should include tests.

3. **Run checks** locally before pushing:
   ```bash
   python scripts/dev.py check    # lint + format check + type check
   python scripts/dev.py test     # run all tests
   ```

4. **Commit** with a clear, descriptive message (see below).

5. **Open a pull request** against `main`. Fill in the PR template and link any related issues.

6. **Address review feedback** - maintainers may request changes before merging.

### What makes a good PR

- **Focused**: One feature or fix per PR. Avoid mixing unrelated changes.
- **Tested**: Include unit tests that cover your changes.
- **Documented**: Update READMEs or docstrings if your change affects the public API.
- **Passing CI**: All checks (lint, format, type check, tests) must pass.

## Code Style

- **Type hints**: Use type annotations on all public functions and methods.
- **Docstrings**: Use Google-style docstrings for public APIs.
- **`py.typed`**: All packages ship type information - maintain `py.typed` markers.

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting. See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for the full list of dev commands.

## Commit Messages

Use clear, imperative-mood commit messages:

```
feat: add TLS enforcement option to HTTP provider
fix: prevent path traversal in filesystem provider
test: add boundary tests for frontmatter parsing
docs: update core README with security section
chore: pin CI actions to commit SHAs
```

Prefix with `feat:`, `fix:`, `test:`, `docs:`, `chore:`, `refactor:`, or `ci:` to categorise the change.

## Testing

All tests must pass before a PR can be merged. Aim for meaningful test coverage - test edge cases and error paths, not just happy paths.

```bash
python scripts/dev.py check    # lint + format check + type check
python scripts/dev.py test     # run all tests
```

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for per-package test commands, coverage, and the full dev task runner reference.

## Project Structure

This is a Python monorepo managed by Poetry. Each package under `packages/` has its own `pyproject.toml` and can be published independently to PyPI. When adding code, keep dependencies minimal - providers depend only on `agentskills-core`, integrations depend on `agentskills-core` + their framework.

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for the full package table, CI pipeline, and release process.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
