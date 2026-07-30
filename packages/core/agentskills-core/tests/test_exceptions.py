"""Tests for the exception hierarchy."""

import contextlib

from agentskills_core import (
    AgentSkillsError,
    ResourceNotFoundError,
    SkillNotFoundError,
    SkillUnavailableError,
)


class TestExceptionHierarchy:
    def test_skill_not_found_is_agent_skills_error(self):
        assert issubclass(SkillNotFoundError, AgentSkillsError)

    def test_resource_not_found_is_agent_skills_error(self):
        assert issubclass(ResourceNotFoundError, AgentSkillsError)

    def test_skill_not_found_is_lookup_error(self):
        assert issubclass(SkillNotFoundError, LookupError)

    def test_resource_not_found_is_lookup_error(self):
        assert issubclass(ResourceNotFoundError, LookupError)

    def test_agent_skills_error_is_exception(self):
        assert issubclass(AgentSkillsError, Exception)

    def test_skill_not_found_message(self):
        err = SkillNotFoundError("my-skill")
        assert str(err) == "my-skill"

    def test_resource_not_found_message(self):
        err = ResourceNotFoundError("missing.md")
        assert str(err) == "missing.md"

    def test_catch_agent_skills_error_catches_skill_not_found(self):
        with _raises_agent_skills_error():
            raise SkillNotFoundError("test")

    def test_catch_agent_skills_error_catches_resource_not_found(self):
        with _raises_agent_skills_error():
            raise ResourceNotFoundError("test")

    def test_catch_lookup_error_catches_skill_not_found(self):
        with _raises_lookup_error():
            raise SkillNotFoundError("test")

    def test_catch_lookup_error_catches_resource_not_found(self):
        with _raises_lookup_error():
            raise ResourceNotFoundError("test")


class TestSkillUnavailableError:
    def test_is_agent_skills_error(self):
        assert issubclass(SkillUnavailableError, AgentSkillsError)

    def test_is_not_a_lookup_error(self):
        """'Unreachable' must not be catchable as 'not found'."""
        assert not issubclass(SkillUnavailableError, LookupError)
        assert not issubclass(SkillUnavailableError, SkillNotFoundError)

    def test_retry_after_defaults_to_none(self):
        assert SkillUnavailableError("boom").retry_after is None

    def test_retry_after_is_carried(self):
        err = SkillUnavailableError("boom", retry_after=12.5)
        assert err.retry_after == 12.5
        assert str(err) == "boom"


@contextlib.contextmanager
def _raises_agent_skills_error():
    try:
        yield
    except AgentSkillsError:
        pass
    else:
        raise AssertionError("AgentSkillsError was not raised")


@contextlib.contextmanager
def _raises_lookup_error():
    try:
        yield
    except LookupError:
        pass
    else:
        raise AssertionError("LookupError was not raised")
