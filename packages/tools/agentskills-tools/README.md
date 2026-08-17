# agentskills-tools

Command line tools for authoring and validating [Agent Skills](https://agentskills.io).

Part of the [Agent Skills SDK](https://github.com/pratikxpanda/agentskills-sdk).

## Install

```bash
pip install agentskills-tools
```

The `serve` command needs the MCP server, which is an optional extra so that
validating skills in CI does not pull in `mcp` and `pydantic`:

```bash
pip install "agentskills-tools[serve]"
```

## Commands

Every command takes either one skill folder or a folder of skill folders — the
one containing `SKILL.md`, or the one containing directories that do.

| Command | What it does |
| --- | --- |
| `agentskills init <name>` | Scaffold a skill that already validates. |
| `agentskills validate <path>` | Check skills against the specification. Exits `1` on any error. |
| `agentskills lint <path>` | Report what is legal but still costly. |
| `agentskills inspect <path>` | Show what an agent would actually receive, and what it costs. |
| `agentskills eval <path>` | Measure what difference a skill makes. |
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

#### Token cost

```bash
agentskills inspect ./skills --cost
```

```text
skills/incident-response  (incident-response)
  counted with tiktoken/cl100k_base
  catalog entry                         66  every turn
  body                                 439  on load
    Incident Response                   14
      When to Declare an Incident       50
      Roles                             70
      General Triage Steps             121
  references/escalation-policy.md      448  on demand
  assets/escalation-flowchart.mermaid  235  on demand
  per turn 66, per load 505, all resources 2,197

1 skill, 66 tokens charged every turn
```

The right-hand column is the point. A catalog entry is injected on **every
turn** whether or not the skill is ever used; a body is charged **once per
load**; a reference is charged **only if the agent goes and reads it**. Authors
reliably get this backwards, trimming a body while ignoring a description that
costs a hundred tokens a turn forever.

Sections do not nest — a heading owns its own text up to the next heading of
any level — so the parts sum to the body exactly. Depth shows in the indent
instead. A `#` inside a fenced code block is a shell comment, not a heading.

A resource that is not UTF-8 text reports its size in bytes and no token count,
because an image has a size but not a token cost.

| Flag | Effect |
| --- | --- |
| `--budget N` | Exit `1` when catalog entry plus body exceeds `N` tokens. |
| `--turn-budget N` | Exit `1` when the catalog entry alone exceeds `N` tokens. |
| `--tokenizer` | `auto` (default), `tiktoken`, or `heuristic`. |

Two budgets rather than one, for the same reason: a single threshold is
dominated by the body, so the per-turn cost stays invisible to exactly the gate
meant to catch it.

Counting is exact when [`tiktoken`](https://pypi.org/project/tiktoken/) is
installed and a four-characters-per-token estimate otherwise. It is not a
dependency here: it ships a compiled wheel and fetches its vocabulary over the
network on first use, which is a poor trade for a tool whose main job is
reading YAML in CI. Install it yourself if you want exact numbers.

Whichever counter ran is named in every report, and `--tokenizer tiktoken`
refuses to fall back — a budget gate that quietly changes its arithmetic
depending on what happens to be installed is worse than no gate. Pin it in CI
and leave `auto` for the terminal.

`lint --max-body-tokens` keeps the estimate regardless, so its verdict never
depends on the machine it ran on.

### `eval`

A skill is a prompt, and nobody measures whether a given prompt makes an agent
better. Authors ship on intuition, reviewers approve on prose quality, and
editing a body can degrade task success with no signal anywhere.

Write cases beside the skill, in `evals/` inside the skill folder:

```yaml
# skills/incident-response/evals/triage.yaml
skill: incident-response      # optional; checked against the folder
judge_model: gpt-4o           # required if any case uses `judge`
cases:
  - name: declares-and-triages
    prompt: Checkout is returning 500s for a third of users.
    repeat: 3                 # models are not deterministic
    threshold: 0.67           # fraction of repeats that must pass
    expect:
      - contains: "Incident Commander"
      - not_contains: "I don't have access"
      - regex: "(?i)severity"
      - judge: "Tells the responder to assess severity before attempting a fix"
```

`repeat` defaults to `1` and `threshold` to `1.0`. Every expectation must hold
for a repeat to pass.

Eval files are checked by `agentskills validate`, with no model and no API key,
so a broken case fails in CI beside the skill rather than the first time
somebody pays to run it.

```bash
agentskills eval ./skills --model mypkg.evals:openai_client
```

```text
incident-response (triage.yaml)
  pass declares-and-triages: with 100%, without 33%, delta +67%
  FAIL postmortem-window: with 0%, without 0%, delta +0%
         unmet contains: 48 hours
  suite delta +33% on gpt-4o

2 cases run, 1 failed, mean delta +33%
```

Every case runs twice: once with the skill's body in the system prompt, once
without. Absolute pass rates mostly measure the underlying model, so the number
that means anything is the difference. A skill whose cases pass equally well
without it is not earning its tokens.

#### Bringing your own model

`--model` takes `module:factory` — a dotted path to a zero-argument callable
returning a client. Nothing in this project depends on a provider SDK, and a
ten-line adapter is a smaller ask than an opinion about which vendor you should
install:

```python
# mypkg/evals.py
from openai import AsyncOpenAI
from agentskills_tools.evals import ModelResponse


class OpenAIModel:
    model_id = "gpt-4o"

    def __init__(self) -> None:
        self._client = AsyncOpenAI()

    async def complete(self, *, system: str, prompt: str) -> ModelResponse:
        reply = await self._client.chat.completions.create(
            model=self.model_id,
            temperature=0,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return ModelResponse(reply.choices[0].message.content or "")


openai_client = OpenAIModel
```

`model_id` is part of every report and of the cache key, because a pass rate
without the model that produced it is not a measurement. Set temperature to
zero if your provider allows it; this side has no opinion it could enforce.

`--judge` names a second client for `judge` expectations and defaults to the
model under test — the cheapest judge and the least independent one. When
`repeat` is above `1`, the report flags cases whose repeats disagreed, because
a case that passes three times in five has measured sampling noise rather than
a skill.

#### Cost

These calls hit real APIs and cost real money. `eval` is never part of
`pytest`: it runs only when you invoke it, with credentials you supply.
Completions are cached under `.agentskills/eval-cache` by model, system prompt,
user prompt, and repeat index — so editing a skill re-buys its runs, while
tightening an expectation re-grades the answers already bought. `--no-cache`
turns that off; `--cache-dir` moves it.

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
| `1` | Ran, found errors — or warnings under `--strict`, or a cost over budget. |
| `2` | Could not run: bad path, missing extra, unwritable directory. |

The distinction matters in CI: `1` means a skill is broken, `2` means the
invocation is.

## JSON output

`validate`, `lint`, `inspect`, and `eval` accept `--format json`. The schema is
a published contract; `schemaVersion` is bumped only for a breaking change, and
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
          "line": 3,
          "file": "skills/broken-skill/SKILL.md"
        }
      ]
    }
  ]
}
```

`ok` mirrors the exit code, so a consumer never has to re-derive the
strictness rules. `line` is `null` unless the problem can be attributed to one
line. `file` is the skill's `SKILL.md` unless the finding is about another file
in the folder, such as an eval case file.

`inspect --cost --format json` reports each skill's `perTurn`, `perLoad` and
`onDemand` totals, the `sections` and `resources` they were summed from, the
`overBudget` messages, and the `counter` that produced the numbers — including
whether it was `exact`. A consumer that charts these over time needs to know
when the unit changed underneath it.

## Continuous integration

The published action wraps `validate` and `lint` and annotates every finding
on the pull request diff:

```yaml
- uses: pratikxpanda/agentskills-sdk/actions/validate@v1
  with:
    path: ./skills
    fail-on-lint: false
```

To run it yourself, `validate` and `lint` also accept `--format github`, which
emits [workflow commands](https://docs.github.com/actions/reference/workflow-commands-for-github-actions)
instead of a report:

```bash
agentskills validate ./skills --format github
```

```text
::error file=skills/deploy/SKILL.md,line=3,title=frontmatter-invalid-yaml::frontmatter is not valid YAML
```

Anywhere else, the exit code is enough:

```yaml
- run: pip install agentskills-tools
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
