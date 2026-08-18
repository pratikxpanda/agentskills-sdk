"""Split a skill body at its headings, one level below the body itself.

Progressive disclosure otherwise has two levels and then a cliff: a
catalog entry costs tens of tokens, and the only way to learn more is
the entire body.  A thorough four-thousand-token skill then charges all
four thousand to answer a question one section covers, which penalises
exactly the skills worth writing.

Everything here is computed on top of ``get_body()``.  Sectioning is a
property of a skill's content, not of where that content is stored, so
this is deliberately **not** a provider capability -- no third-party
provider has to grow a markdown parser, and the ADR 0002 capability-flag
machinery stays out of it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING = re.compile(r"^(#{1,6})[ \t]+(\S.*?)[ \t]*#*[ \t]*$")
_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
_KEY_STRIP = re.compile(r"[^a-z0-9]+")

#: Title given to whatever a body says before its first heading.
PREAMBLE_TITLE = "(before the first heading)"

#: Key for that section, since its title slugifies to nothing.
PREAMBLE_KEY = "preamble"

#: Fallback for a heading whose title is all punctuation.
_FALLBACK_KEY = "section"

#: Rough enough to flag an outlier, and honest about being rough: a real
#: count needs the tokenizer of whichever model is being targeted.
_CHARS_PER_TOKEN = 4

#: Below this, a body is small enough that outline-then-section costs
#: more than just fetching it -- an extra tool call, an extra model turn,
#: and the outline's own tokens, to save a few hundred.  A guess, but a
#: stated one, and the outline says which side of it a skill falls on.
WHOLE_BODY_CHEAPER_TOKENS = 1000


def estimate_tokens(text: str) -> int:
    """Estimate the token cost of *text* at four characters per token."""
    return -(-len(text) // _CHARS_PER_TOKEN)


@dataclass(frozen=True)
class Section:
    """One heading of a body, with the text charged to it.

    Attributes:
        key: Stable, addressable identifier, unique within one body.
        title: The heading text, or :data:`PREAMBLE_TITLE`.
        level: Number of leading ``#``, or ``0`` for the preamble.
        text: The heading line and everything up to the next heading.
    """

    key: str
    title: str
    level: int
    text: str


@dataclass(frozen=True)
class SectionRef:
    """One line of an outline: what a section is, and what it costs."""

    key: str
    title: str
    level: int
    tokens: int


def _slug(title: str) -> str:
    """Reduce a heading to a key an agent can type back."""
    slug = _KEY_STRIP.sub("-", title.casefold()).strip("-")
    return slug or _FALLBACK_KEY


def _keyed(titles: list[str]) -> list[str]:
    """Disambiguate repeated slugs by ordinal.

    ``## Setup`` can legitimately appear twice, so the second becomes
    ``setup-2``.  Ordinals suit the flat, non-overlapping model the
    splitter already uses; a hierarchical path would read better and
    imply a tree it does not build.
    """
    seen: dict[str, int] = {}
    keys: list[str] = []
    for title in titles:
        slug = _slug(title)
        seen[slug] = seen.get(slug, 0) + 1
        keys.append(slug if seen[slug] == 1 else f"{slug}-{seen[slug]}")
    return keys


def split_sections(body: str) -> list[Section]:
    """Split *body* at its headings, without overlapping.

    A heading owns its own line and everything up to the next heading of
    any level, so a nested section is not also counted inside its
    parent.  The parts therefore sum to the whole, which is the only
    property that makes a cost breakdown checkable.

    Text before the first heading becomes a level-0 section, and ``#``
    inside a fenced code block is a shell comment rather than a heading.
    """
    found: list[tuple[str, int, str]] = []
    lines: list[str] = []
    title = PREAMBLE_TITLE
    level = 0
    fence: str | None = None

    def flush() -> None:
        text = "\n".join(lines)
        if text.strip() or level:
            found.append((title, level, text))

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

    keys = _keyed([PREAMBLE_KEY if lvl == 0 else name for name, lvl, _ in found])
    return [
        Section(key, name, lvl, text) for key, (name, lvl, text) in zip(keys, found, strict=True)
    ]


@dataclass(frozen=True)
class SkillOutline:
    """A body's sections, their cost, and whether they are worth fetching.

    A section fetch is not automatically cheaper than a body fetch: it
    costs a tool call, a model turn, and the tokens of the outline that
    preceded it.  The outline therefore carries the whole-body figure
    and says plainly which is cheaper, because shipping the split
    without that guidance makes the common case worse to improve the
    rare one.
    """

    skill_id: str
    sections: list[SectionRef]
    total_tokens: int

    @property
    def whole_body_is_cheaper(self) -> bool:
        """Whether the agent should skip sectioning and read the body."""
        return self.total_tokens < WHOLE_BODY_CHEAPER_TOKENS

    def render(self) -> str:
        """Return the outline as text for an agent to read.

        One rendering, shared by every integration, so the three cannot
        drift into giving an agent three different cost estimates for
        the same skill.
        """
        if not self.sections:
            return f"'{self.skill_id}' has an empty body; there is nothing to fetch."

        lines = [
            f"'{self.skill_id}': ~{self.total_tokens} tokens in {len(self.sections)} sections.",
            "",
        ]
        lines += [
            f"{'  ' * max(section.level - 1, 0)}- {section.key} "
            f"(~{section.tokens}) — {section.title}"
            for section in self.sections
        ]
        lines.append("")

        if self.whole_body_is_cheaper:
            lines.append(
                f"Call get_skill_body instead: the whole body is only "
                f"~{self.total_tokens} tokens, less than this outline plus a "
                f"section fetch."
            )
        else:
            lines.append(
                f"Fetch one with get_skill_section using the key. Sections do not "
                f"nest — a section covers only its own text, up to the next heading "
                f"of any level, so fetching a parent does not include what is "
                f"indented under it. Past about three sections, call get_skill_body "
                f"instead (~{self.total_tokens} tokens)."
            )
        return "\n".join(lines)


def outline_of(skill_id: str, body: str) -> SkillOutline:
    """Build the outline of *body*."""
    sections = split_sections(body)
    return SkillOutline(
        skill_id=skill_id,
        sections=[
            SectionRef(section.key, section.title, section.level, estimate_tokens(section.text))
            for section in sections
        ],
        total_tokens=estimate_tokens(body),
    )
