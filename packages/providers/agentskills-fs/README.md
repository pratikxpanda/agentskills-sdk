---
title: agentskills-fs
description: Read Agent Skills from a local directory with bounded, byte-preserving file access.
---

[![PyPI](https://img.shields.io/pypi/v/agentskills-fs)](https://pypi.org/project/agentskills-fs/)
[![Python 3.12 | 3.13](https://img.shields.io/pypi/pyversions/agentskills-fs)](https://pypi.org/project/agentskills-fs/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/pratikxpanda/agentskills-sdk/blob/main/LICENSE)

> Local filesystem skill provider for the [Agent Skills SDK](https://github.com/pratikxpanda/agentskills-sdk).

Serves [Agent Skills](https://agentskills.io) from a local directory tree. Each subdirectory containing a `SKILL.md` file is a skill.

## Installation

```bash
pip install agentskills-fs
```

Requires Python 3.12 or newer. Installs `agentskills-core` and `pyyaml` as dependencies.

## Expected Directory Layout

```text
skills/
├── incident-response/
│   ├── SKILL.md              # YAML frontmatter + markdown body
│   ├── references/           # supplementary docs (optional)
│   ├── scripts/              # script files, never executed by the SDK (optional)
│   └── assets/               # diagrams, data files (optional)
└── another-skill/
    └── SKILL.md
```

## Usage

Create `skills/incident-response/SKILL.md` before running the example:

```markdown
---
name: incident-response
description: Triage production incidents.
---

# Incident response

Check service health and identify the affected deployment.
```

```python
import asyncio
from pathlib import Path

from agentskills_core import SkillRegistry
from agentskills_fs import LocalFileSystemSkillProvider


async def main() -> None:
    provider = LocalFileSystemSkillProvider(Path("./skills"))
    registry = SkillRegistry()
    await registry.register_all(provider)

    skill = registry.get_skill("incident-response")
    print(await skill.get_metadata())
    print(await skill.get_body())


asyncio.run(main())
```

Use `await registry.register("incident-response", provider)` to register just one named skill.
The provider has no network client to close. The remaining `await` snippets belong inside an
async function with a `provider` created as above. Request scripts, assets, and references only
when those files exist in the skill directory.

Blocking file I/O runs in a worker thread, so a slow or networked filesystem does not stall other coroutines.

`SKILL.md` content is cached per provider instance after the first read: a single skill is otherwise re-read up to five times in one agent session. Call `invalidate()` when skills change on disk.

```python
provider.invalidate("incident-response")  # forget one skill
provider.invalidate()                      # forget everything
```

## Lossless File Access

The file-access capability preserves original bytes and lists the complete
skill tree, including hidden files and arbitrary nested directories:

```python
paths = await provider.list_files("incident-response")
original = await provider.read_file("incident-response", "SKILL.md")
data = await provider.read_file("incident-response", "data/nested.bin")
```

Listing does not read file contents. Reads bypass the parsed `SKILL.md` cache and
enforce `max_file_bytes`. Negative limits are rejected. Zero permits empty files only.
Links, junctions, special files, absolute paths, and traversal are rejected instead
of silently producing an incomplete listing.

Publish only directories intended for sharing. Hidden files are not automatically
excluded, so remove credentials and private files before exposing a skill. The
provider does not freeze the tree or prevent concurrent filesystem changes. Use a
trusted, immutable publication directory when constructing verified manifests.

## Security

- **Path-traversal protection**: Skill IDs and resource names are validated to stay within the root directory. Attempts to escape (e.g. `../../etc/passwd`) raise `SkillNotFoundError` or `ResourceNotFoundError`.
- **File size limits**: Files exceeding 10 MB (default) are rejected before reading into memory. Configure via the `max_file_bytes` parameter.
- **Error-message sanitization**: Error messages reference the `skill_id` rather than full filesystem paths, preventing internal path leakage.

For the full security policy, see [SECURITY.md](https://github.com/pratikxpanda/agentskills-sdk/blob/main/SECURITY.md).

## API

### `LocalFileSystemSkillProvider(root, *, max_file_bytes=10_485_760)`

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `root` | `Path` | - | Path to the directory containing skill subdirectories |
| `max_file_bytes` | `int` | `10_485_760` (10 MB) | Maximum allowed file size in bytes |

| Method | Returns | Description |
| --- | --- | --- |
| `get_metadata(skill_id)` | `dict[str, Any]` | Parsed YAML frontmatter from `SKILL.md` |
| `get_body(skill_id)` | `str` | Markdown body after the frontmatter |
| `get_script(skill_id, name)` | `bytes` | Raw content of a script file |
| `get_asset(skill_id, name)` | `bytes` | Raw content of an asset file |
| `get_reference(skill_id, name)` | `bytes` | Raw content of a reference file |
| `list_resources(skill_id)` | `dict[str, list[str]]` | Resource filenames grouped by kind |
| `list_files(skill_id)` | `list[str]` | Complete sorted tree, including `SKILL.md` and nested files |
| `read_file(skill_id, path)` | `bytes` | Original bytes from a skill-relative path |
| `invalidate(skill_id=None)` | `None` | Drop cached `SKILL.md` content for one skill, or all skills |

## Resource Discovery

This provider sets `supports_resource_listing = True` and can enumerate a skill's bundled files:

```python
listing = await provider.list_resources("incident-response")
# {"references": ["severity-levels.md"], "scripts": ["page-oncall.sh"], "assets": []}
```

All three keys are always present; unused categories are empty lists. Only regular files directly inside `references/`, `scripts/` and `assets/` are reported. Dotfiles, subdirectories, and symlinks resolving outside the skill root are skipped rather than raising, so one stray entry cannot make a whole skill unlistable, and listing can never offer a name that a subsequent read would reject.

## License

MIT
