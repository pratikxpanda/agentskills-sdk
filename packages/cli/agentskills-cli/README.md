# agentskills-cli

Command line tools for authoring and validating [Agent Skills](https://agentskills.io).

Part of the [Agent Skills SDK](https://github.com/pratikxpanda/agentskills-sdk).

## Install

```bash
pip install agentskills-cli
```

The `serve` command needs the MCP server, which is an optional extra so that
validating skills in CI does not pull in `mcp` and `pydantic`:

```bash
pip install "agentskills-cli[serve]"
```

## Commands

Every command takes either one skill folder or a folder of skill folders — the
one containing `SKILL.md`, or the one containing directories that do.

| Command | What it does |
| --- | --- |
| `agentskills init <name>` | Scaffold a skill that already validates. |
| `agentskills validate <path>` | Check skills against the specification. Exits `1` on any error. |
| `agentskills lint <path>` | Report what is legal but still costly. |
| `agentskills inspect <path>` | Show what an agent would actually receive. |
| `agentskills serve <path>` | Run an MCP server over a folder of skills. |

### `init`

```bash
agentskills init incident-response --path ./skills
```

Creates `skills/incident-response/` with a valid `SKILL.md` and empty
`references/`, `scripts/`, and `assets/` directories. The template is validated
before anything is written, so an unusable name is refused rather than
scaffolded.

### `validate`

```bash
agentskills validate ./skills
```

```text
skills/incident-response
  ok
skills/broken-skill
  error   frontmatter-invalid-yaml (line 3): frontmatter is not valid YAML: mapping values are not allowed here

2 skills checked, 1 error, 0 warnings
```

Frontmatter is parsed by the CLI before the skill reaches the SDK's validator.
The SDK's parser is deliberately forgiving — malformed YAML yields an empty
mapping — which downstream reads as "no name, no description" and tells you
nothing about the colon you missed.

### `lint`

```bash
agentskills lint ./skills --strict --max-body-tokens 4000
```

| Code | Warning |
| --- | --- |
| `missing-version` | No `version`, so consumers cannot pin the skill or detect drift. |
| `description-too-long-for-catalog` | Catalog entries sit in context every turn. |
| `body-over-token-budget` | Body is large enough that detail belongs in `references/`. |
| `unreferenced-resource` | A file the body never mentions is a file no agent will load. |

Warnings do not fail the command unless `--strict` is passed.

### `inspect`

```bash
agentskills inspect ./skills/incident-response
```

Prints the metadata, the resource list, the catalog entry the agent sees on
every turn, and the body it loads on demand — each with an estimated token
cost, so you can see the price before shipping.

### `serve`

```bash
agentskills serve ./skills --transport stdio
```

Runs the MCP server over a folder of skills without hand-writing a config
file. For anything beyond a single filesystem root — HTTP providers,
per-skill options, environment placeholders — use
[agentskills-mcp-server](https://github.com/pratikxpanda/agentskills-sdk/tree/main/packages/integrations/agentskills-mcp-server)
with a `server.json`.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Ran, found nothing wrong. |
| `1` | Ran, found errors — or warnings under `--strict`. |
| `2` | Could not run: bad path, missing extra, unwritable directory. |

The distinction matters in CI: `1` means a skill is broken, `2` means the
invocation is.

## JSON output

`validate`, `lint`, and `inspect` accept `--format json`. The schema is a
published contract; `schemaVersion` is bumped only for a breaking change, and
new fields are added rather than existing ones repurposed.

```json
{
  "schemaVersion": 1,
  "command": "validate",
  "ok": false,
  "summary": { "skills": 2, "errors": 1, "warnings": 0 },
  "skills": [
    {
      "id": "broken-skill",
      "path": "skills/broken-skill",
      "ok": false,
      "findings": [
        {
          "severity": "error",
          "code": "frontmatter-invalid-yaml",
          "message": "frontmatter is not valid YAML: mapping values are not allowed here",
          "line": 3
        }
      ]
    }
  ]
}
```

`ok` mirrors the exit code, so a consumer never has to re-derive the
strictness rules. `line` is `null` unless the problem can be attributed to one
line of `SKILL.md`.

## Continuous integration

```yaml
- run: pip install agentskills-cli
- run: agentskills validate ./skills
```

## Logging

Pass `-v` to send the SDK's debug logs to stderr, leaving stdout parseable:

```bash
agentskills validate ./skills --format json -v > report.json
```

## Security

Agent Skills are **equivalent to executable code** — skill content is injected
into an LLM agent's context verbatim. Validating a skill does not make it safe
to run. **Only load skills from sources you trust.**

See
[SECURITY.md](https://github.com/pratikxpanda/agentskills-sdk/blob/main/SECURITY.md).

## License

MIT
