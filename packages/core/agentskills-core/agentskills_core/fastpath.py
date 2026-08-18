"""Skip discovery when there is nothing to discover.

An agent with exactly one skill pays the full discovery apparatus to
reach content there was never a choice about: a catalog listing one
entry, eight tool definitions, a block of instructions describing a
multi-step selection workflow, and then a complete model round trip
while the agent calls ``get_skill_body`` and waits.

A catalog exists to let a model choose.  With one skill there is nothing
to choose, so the body goes straight into the prompt.

This lives in core rather than in each integration for two reasons.
The decision is identical everywhere -- how many skills, how big is the
body -- so three copies could only ever disagree.  And the token ceiling
is the part that has to be tuned; one knob is tunable, three that must
be kept in step are not.

Whether the fast path is a win depends on body size and conversation
length.  Inlining a twenty-thousand-token body on every turn of a long
conversation is strictly worse than one tool call that happens once, so
the ceiling is a named, configurable threshold and a declined fast path
is logged.  Taking a different code path based on content size without
saying so is how token bills become impossible to explain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentskills_core.logging import get_logger
from agentskills_core.sections import estimate_tokens

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

    from agentskills_core.registry import SkillRegistry

_logger = get_logger(__name__)

#: The size below which the fast path wins at *any* conversation length.
#:
#: The arithmetic: the normal path pays the catalog and the usage
#: instructions every turn (~500 tokens together) and the body once. The
#: fast path pays a ~200-token wrapper and the body every turn. So over
#: T turns the fast path wins while ``body * (T - 1) < 300 * T``, which
#: falls from "any size" at one turn to ~306 tokens asymptotically.
#:
#: An integration knows the body size but not how many turns the
#: conversation will run, so the default is the value that needs no
#: assumption about the latter. Callers who know their conversations are
#: short can raise it — at three turns the break-even is ~459 tokens —
#: and the decline is logged either way.
#:
#: This is deliberately small. A skill elaborate enough to exceed it is
#: one where re-sending the body every turn costs more than the single
#: tool call the fast path removes, which is precisely when it should
#: not fire.
DEFAULT_FAST_PATH_MAX_TOKENS = 300

#: Tools that only return content the fast path has already inlined.
#: ``get_skill_body`` is the obvious one; ``get_skill_outline`` and
#: ``get_skill_section`` index into a body the agent is already holding,
#: and ``get_skill_metadata`` answers "should I use this skill", which is
#: the question the fast path exists because nobody is asking.
#:
#: Resource tools are deliberately absent.  References, scripts and
#: assets are still genuinely progressive, and a skill carrying a 2 MB
#: dataset must not have it inlined because the skill count happened to
#: be one.
FAST_PATH_DROPPED_TOOLS = frozenset(
    {
        "get_skill_metadata",
        "get_skill_body",
        "get_skill_outline",
        "get_skill_section",
    }
)

#: The resource half of the usage instructions, without the selection
#: workflow.  Dropping the instructions wholesale would leave the model
#: unaware it can read references at all, while keeping the "pick a
#: skill from the catalog" workflow would point it at a catalog that is
#: no longer there.
FAST_PATH_RESOURCE_INSTRUCTIONS = """\
### Bundled resources

The instructions above may name reference documents, scripts or assets. \
Retrieve one only when the instructions call for it:

- `get_skill_reference(skill_id, name)` - reference documents \
(policies, templates, runbooks)
- `get_skill_script(skill_id, name)` - executable scripts
- `get_skill_asset(skill_id, name)` - diagrams, data files, or other assets

Do not guess resource names. Fetch only what the instructions name, or \
what `list_skill_resources(skill_id)` reports. That tool reports that it \
is unsupported on backends that cannot be enumerated - when it does, rely \
on the instructions above alone.\
"""


@dataclass(frozen=True)
class FastPath:
    """A resolved single-skill fast path.

    Passed to an integration's ``fast_path=`` argument.  Holding the
    decision in a value rather than re-deriving it means the prompt an
    integration injects and the tools it drops cannot disagree about
    which skill was chosen.
    """

    skill_id: str
    """The one skill whose body is being inlined."""

    body: str
    """That skill's full body, frontmatter already stripped."""

    tokens: int
    """Estimated cost of the body, by the counter the outline uses."""

    @property
    def prompt(self) -> str:
        """The instruction block to inject instead of a catalog."""
        return (
            f"You have one skill, `{self.skill_id}`, and its full instructions "
            f"are below. Follow them when the task aligns with their domain.\n\n"
            f'<skill id="{self.skill_id}">\n{self.body.rstrip()}\n</skill>\n\n'
            f"{FAST_PATH_RESOURCE_INSTRUCTIONS}"
        )

    def keeps(self, tool_name: str) -> bool:
        """Whether *tool_name* should still be offered to the agent."""
        return tool_name not in FAST_PATH_DROPPED_TOOLS


async def resolve_fast_path(
    registry: SkillRegistry,
    *,
    include: Iterable[str] | None = None,
    max_tokens: int = DEFAULT_FAST_PATH_MAX_TOKENS,
) -> FastPath | None:
    """Decide whether *registry* qualifies for the single-skill fast path.

    Returns ``None`` -- meaning "use the normal catalog path" -- unless
    the effective skill set is exactly one and its body fits under
    *max_tokens*.

    *include* narrows the registry to an effective set, so a registry of
    fifty skills that a selector has narrowed to one takes the same path
    as a registry that only ever held one.  That is the same situation
    and the ``len(list_skills()) == 1`` test would miss it.

    Both refusals are logged, because an integration silently choosing
    between two prompt shapes is worse than a slightly slower one.
    """
    skills = registry.list_skills()
    if include is not None:
        wanted = set(include)
        skills = [skill for skill in skills if skill.get_id() in wanted]

    if len(skills) != 1:
        _logger.debug(
            "Fast path declined: effective skill set is %d, not 1",
            len(skills),
        )
        return None

    skill = skills[0]
    body = await skill.get_body()
    tokens = estimate_tokens(body)
    if tokens > max_tokens:
        _logger.info(
            "Fast path declined for skill '%s': body is ~%d tokens, ceiling is %d. "
            "Inlining it on every turn would cost more than the one tool call it saves.",
            skill.get_id(),
            tokens,
            max_tokens,
        )
        return None

    _logger.debug("Fast path resolved for skill '%s' (~%d tokens)", skill.get_id(), tokens)
    return FastPath(skill_id=skill.get_id(), body=body, tokens=tokens)
