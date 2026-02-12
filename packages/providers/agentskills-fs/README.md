# agentskills-fs

[![PyPI](https://img.shields.io/pypi/v/agentskills-fs)](https://pypi.org/project/agentskills-fs/)
[![Python 3.12+](https://img.shields.io/pypi/pyversions/agentskills-fs)](https://pypi.org/project/agentskills-fs/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/pratikxpanda/agentskills-sdk/blob/main/LICENSE)

> Local filesystem skill provider for the [Agent Skills SDK](../../README.md).

Serves [Agent Skills](https://agentskills.io) from a local directory tree. Each subdirectory containing a `SKILL.md` file is a skill.

## Installation

```bash
pip install agentskills-fs
```

Requires Python 3.12+. Installs `agentskills-core` and `pyyaml` as dependencies.

## Expected Directory Layout

```text
skills/
├── incident-response/
│   ├── SKILL.md              # YAML frontmatter + markdown body
│   ├── references/           # supplementary docs (optional)
│   ├── scripts/              # executable scripts (optional)
│   └── assets/               # diagrams, data files (optional)
└── another-skill/
    └── SKILL.md
```

## Usage

```python
from pathlib import Path
from agentskills_core import SkillRegistry
from agentskills_fs import LocalFileSystemSkillProvider

provider = LocalFileSystemSkillProvider(Path("./skills"))
registry = SkillRegistry()
await registry.register("incident-response", provider)

skill = registry.get_skill("incident-response")
meta = await skill.get_metadata()
body = await skill.get_body()
script = await skill.get_script("page-oncall.sh")
```

The provider reads files synchronously (local disk I/O is fast for small skill files) but exposes an `async` interface to satisfy the `SkillProvider` contract.

## Security

Path traversal is guarded — skill IDs and resource names are validated to stay within the root directory. Attempts to escape (e.g. `../../etc/passwd`) raise `SkillNotFoundError` or `ResourceNotFoundError`.

## API

### `LocalFileSystemSkillProvider(root: Path)`

| Method | Returns | Description |
| --- | --- | --- |
| `get_metadata(skill_id)` | `dict[str, Any]` | Parsed YAML frontmatter from `SKILL.md` |
| `get_body(skill_id)` | `str` | Markdown body after the frontmatter |
| `get_script(skill_id, name)` | `bytes` | Raw content of a script file |
| `get_asset(skill_id, name)` | `bytes` | Raw content of an asset file |
| `get_reference(skill_id, name)` | `bytes` | Raw content of a reference file |

## License

MIT
