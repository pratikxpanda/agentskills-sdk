"""``agentskills inspect --cost`` — what a skill charges, and how often.

The catalog entry is injected on every single turn; the body is charged
once per load; a reference is charged only if the agent goes and reads
it.  Authors reliably get this backwards, budgeting the body and
ignoring a description that costs a hundred tokens a turn forever, so
the report separates the three rather than printing one total.

Counting is exact when ``tiktoken`` is importable and a heuristic
otherwise.  Which one produced a number is printed beside it, because a
budget gate that silently changes its arithmetic depending on what
happens to be installed is worse than no gate.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TextIO

from agentskills_cli.discovery import CliError
from agentskills_cli.lint import estimate_tokens
from agentskills_core import RESOURCE_KINDS, Skill, get_logger

_logger = get_logger(__name__)

#: Encoding used when ``tiktoken`` is available.  GPT-4o and the Claude
#: family tokenize differently, but within a few percent for prose,
#: which is the resolution a budget needs.
TIKTOKEN_ENCODING = "cl100k_base"

#: What ``--tokenizer`` accepts.
TOKENIZERS = ("auto", "tiktoken", "heuristic")

_HEADING = re.compile(r"^(#{1,6})[ \t]+(\S.*?)[ \t]*#*[ \t]*$")
_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")

PREAMBLE_TITLE = "(before the first heading)"


@dataclass(frozen=True)
class TokenCounter:
    """A way to count tokens, and how much to trust it.

    Attributes:
        name: Identifier for the report, e.g. ``tiktoken/cl100k_base``.
        exact: ``False`` when the count is a character heuristic.
        count: Callable returning the token count of a string.
    """

    name: str
    exact: bool
    count: Callable[[str], int]


HEURISTIC = TokenCounter("heuristic", False, estimate_tokens)


def _tiktoken_counter() -> TokenCounter | None:
    """Return an exact counter, or ``None`` if one cannot be built."""
    try:
        import tiktoken
    except ImportError:
        _logger.debug("tiktoken is not installed; counting with the heuristic")
        return None

    try:
        encoding = tiktoken.get_encoding(TIKTOKEN_ENCODING)
    except Exception as exc:
        # An installed tiktoken still downloads its vocabulary on first
        # use, so "importable" does not mean "usable" on an air-gapped
        # runner.  Degrading beats failing a cost report over it.
        _logger.debug("tiktoken could not load %s: %s", TIKTOKEN_ENCODING, exc)
        return None

    return TokenCounter(
        f"tiktoken/{TIKTOKEN_ENCODING}", True, lambda text: len(encoding.encode(text))
    )


def resolve_counter(preference: str = "auto") -> TokenCounter:
    """Return the counter *preference* asks for.

    Args:
        preference: One of :data:`TOKENIZERS`.  ``auto`` prefers
            ``tiktoken`` and falls back; ``tiktoken`` refuses to fall
            back, which is what CI wants when a budget has to mean the
            same thing on every run.

    Raises:
        CliError: If ``tiktoken`` was demanded and is unusable.
    """
    if preference == "heuristic":
        return HEURISTIC

    counter = _tiktoken_counter()
    if counter is not None:
        return counter
    if preference == "tiktoken":
        raise CliError(
            "tiktoken was requested but is not installed or could not load its "
            f"'{TIKTOKEN_ENCODING}' vocabulary; install it, or pass "
            "--tokenizer heuristic to accept an estimate"
        )
    return HEURISTIC


@dataclass(frozen=True)
class Section:
    """One heading of a body, with the text charged to it."""

    title: str
    level: int
    text: str


def split_sections(body: str) -> list[Section]:
    """Split *body* at its headings, without overlapping.

    A heading owns its own line and everything up to the next heading of
    any level, so a nested section is not also counted inside its
    parent.  The parts therefore sum to the whole, which is the only
    property that makes a cost breakdown checkable.

    Text before the first heading becomes a level-0 section, and ``#``
    inside a fenced code block is a shell comment rather than a heading.
    """
    sections: list[Section] = []
    lines: list[str] = []
    title = PREAMBLE_TITLE
    level = 0
    fence: str | None = None

    def flush() -> None:
        text = "\n".join(lines)
        if text.strip() or level:
            sections.append(Section(title, level, text))

    for line in body.splitlines():
        opener = _FENCE.match(line)
        if fence is not None:
            if opener is not None and opener.group(1)[0] == fence[0]:
                fence = None
            lines.append(line)
            continue
        if opener is not None:
            fence = opener.group(1)
            lines.append(line)
            continue

        heading = _HEADING.match(line)
        if heading is None:
            lines.append(line)
            continue

        flush()
        level = len(heading.group(1))
        title = heading.group(2)
        lines = [line]

    flush()
    return sections


@dataclass(frozen=True)
class SectionCost:
    """A body section and what it costs."""

    title: str
    level: int
    tokens: int


@dataclass(frozen=True)
class ResourceCost:
    """A resource file and what it would cost to load.

    ``tokens`` is ``None`` for a file that is not UTF-8 text: an image
    has a size but no token count, and inventing one would be a lie in
    the column that matters.
    """

    kind: str
    name: str
    size: int
    tokens: int | None


@dataclass(frozen=True)
class SkillCost:
    """Everything ``--cost`` reports for one skill."""

    skill_id: str
    path: str
    counter: TokenCounter
    catalog_tokens: int
    body_tokens: int
    sections: list[SectionCost] = field(default_factory=list)
    resources: list[ResourceCost] = field(default_factory=list)

    @property
    def per_turn(self) -> int:
        """Tokens charged on every turn, whether or not the skill is used."""
        return self.catalog_tokens

    @property
    def per_load(self) -> int:
        """Tokens in context once the agent has loaded the skill."""
        return self.catalog_tokens + self.body_tokens

    @property
    def on_demand(self) -> int:
        """Tokens the resources would add if every one were read."""
        return sum(resource.tokens or 0 for resource in self.resources)


_RESOURCE_READERS = {
    "references": "get_reference",
    "scripts": "get_script",
    "assets": "get_asset",
}


async def _resource_costs(skill: Skill, counter: TokenCounter) -> list[ResourceCost]:
    """Cost every resource the skill lists."""
    if not skill.supports_resource_listing:
        return []

    listing = await skill.list_resources()
    costs: list[ResourceCost] = []
    for kind in RESOURCE_KINDS:
        read = getattr(skill, _RESOURCE_READERS[kind])
        for name in listing.get(kind, []):
            raw = await read(name)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                costs.append(ResourceCost(kind, name, len(raw), None))
            else:
                costs.append(ResourceCost(kind, name, len(raw), counter.count(text)))
    return costs


async def cost_skill(
    skill: Skill,
    path: str,
    catalog_entry: str,
    body: str,
    counter: TokenCounter,
) -> SkillCost:
    """Break one skill down into what it charges and when."""
    sections = [
        SectionCost(section.title, section.level, counter.count(section.text))
        for section in split_sections(body)
    ]
    resources = await _resource_costs(skill, counter)
    _logger.debug("Costed %s with %s", skill.get_id(), counter.name)
    return SkillCost(
        skill.get_id(),
        path,
        counter,
        counter.count(catalog_entry),
        counter.count(body),
        sections,
        resources,
    )


def over_budget(cost: SkillCost, *, budget: int | None, turn_budget: int | None) -> list[str]:
    """Return one message per budget *cost* exceeds."""
    breaches = []
    if turn_budget is not None and cost.per_turn > turn_budget:
        breaches.append(
            f"per-turn cost is {cost.per_turn} tokens, over the {turn_budget} budget; "
            f"shorten the description, which is charged on every turn"
        )
    if budget is not None and cost.per_load > budget:
        breaches.append(
            f"per-load cost is {cost.per_load} tokens, over the {budget} budget; "
            f"move detail into references/ so it loads only when needed"
        )
    return breaches


def _thousands(value: int) -> str:
    return f"{value:,}"


def _rows(cost: SkillCost) -> list[tuple[str, str, str]]:
    """Return ``(label, amount, when)`` for every line of one skill."""
    rows = [
        ("  catalog entry", _thousands(cost.catalog_tokens), "every turn"),
        ("  body", _thousands(cost.body_tokens), "on load"),
    ]
    for section in cost.sections:
        indent = "    " + "  " * max(section.level - 1, 0)
        rows.append((indent + section.title, _thousands(section.tokens), ""))
    for resource in cost.resources:
        label = f"  {resource.kind}/{resource.name}"
        if resource.tokens is None:
            rows.append((label, _thousands(resource.size), "bytes, not text"))
        else:
            rows.append((label, _thousands(resource.tokens), "on demand"))
    return rows


def render_cost_text(
    costs: list[SkillCost],
    out: TextIO,
    *,
    budget: int | None = None,
    turn_budget: int | None = None,
) -> None:
    """Write the cost report in human-readable form."""
    for index, cost in enumerate(costs):
        if index:
            print(file=out)
        estimated = "" if cost.counter.exact else ", estimated"
        print(f"{cost.path}  ({cost.skill_id})", file=out)
        print(f"  counted with {cost.counter.name}{estimated}", file=out)

        rows = _rows(cost)
        label_width = max(len(label) for label, _, _ in rows)
        amount_width = max(len(amount) for _, amount, _ in rows)
        for label, amount, when in rows:
            line = f"{label:<{label_width}}  {amount:>{amount_width}}"
            print(f"{line}  {when}".rstrip(), file=out)

        print(
            f"  per turn {_thousands(cost.per_turn)}, "
            f"per load {_thousands(cost.per_load)}, "
            f"all resources {_thousands(cost.on_demand)}",
            file=out,
        )
        for breach in over_budget(cost, budget=budget, turn_budget=turn_budget):
            print(f"  over budget: {breach}", file=out)

    turn_total = sum(cost.per_turn for cost in costs)
    print(
        f"\n{len(costs)} skill{'' if len(costs) == 1 else 's'}, "
        f"{_thousands(turn_total)} tokens charged every turn",
        file=out,
    )


def cost_payload(
    costs: list[SkillCost],
    *,
    budget: int | None = None,
    turn_budget: int | None = None,
) -> list[dict[str, Any]]:
    """Return the machine-readable cost report."""
    return [
        {
            "id": cost.skill_id,
            "path": cost.path,
            "counter": {"name": cost.counter.name, "exact": cost.counter.exact},
            "perTurn": cost.per_turn,
            "perLoad": cost.per_load,
            "onDemand": cost.on_demand,
            "catalogEntry": cost.catalog_tokens,
            "body": cost.body_tokens,
            "sections": [
                {"title": section.title, "level": section.level, "tokens": section.tokens}
                for section in cost.sections
            ],
            "resources": [
                {
                    "kind": resource.kind,
                    "name": resource.name,
                    "bytes": resource.size,
                    "tokens": resource.tokens,
                }
                for resource in cost.resources
            ],
            "overBudget": over_budget(cost, budget=budget, turn_budget=turn_budget),
        }
        for cost in costs
    ]


def cost_exit_code(
    costs: list[SkillCost],
    *,
    budget: int | None = None,
    turn_budget: int | None = None,
) -> int:
    """Return ``1`` when any skill is over any budget."""
    breached = any(over_budget(cost, budget=budget, turn_budget=turn_budget) for cost in costs)
    return 1 if breached else 0
