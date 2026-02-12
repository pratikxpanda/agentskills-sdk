"""Exception hierarchy for Agent Skills.

All exceptions raised by :mod:`agentskills_core` (and by concrete
providers that follow the library conventions) inherit from
:class:`AgentSkillsError`, allowing callers to catch the entire family
with a single ``except`` clause.

The two most common exceptions are:

* :class:`SkillNotFoundError` -- the requested skill does not exist.
* :class:`ResourceNotFoundError` -- a resource (script, asset, or
  reference) does not exist within an otherwise valid skill.

Both inherit from :class:`LookupError` so that they are idiomatic
Python lookup failures and can also be caught with
``except LookupError``.
"""


class AgentSkillsError(Exception):
    """Base exception for all Agent Skills library errors."""


class SkillNotFoundError(AgentSkillsError, LookupError):
    """A requested skill does not exist.

    Raised by :class:`~agentskills_core.SkillProvider` methods when
    the given *skill_id* cannot be resolved, and by
    :meth:`SkillRegistry.get_skill <agentskills_core.SkillRegistry.get_skill>` when
    the skill is not in the index.

    Example::

        try:
            skill = await registry.get_skill("nonexistent")
        except SkillNotFoundError:
            print("Skill not found")
    """


class ResourceNotFoundError(AgentSkillsError, LookupError):
    """A requested resource does not exist within a skill.

    Resources include scripts, assets, and reference documents
    bundled with a skill.

    Raised by ``get_script``, ``get_asset``, and ``get_reference`` on
    both :class:`~agentskills_core.SkillProvider` and
    :class:`~agentskills_core.Skill` when the named resource cannot be
    found.

    Example::

        try:
            data = await skill.get_reference("missing.md")
        except ResourceNotFoundError:
            print("Reference not found")
    """
