"""Tests for SkillProvider ABC."""

from dataclasses import FrozenInstanceError
from hashlib import sha256

import pytest

from agentskills_core import (
    RESOURCE_KINDS,
    DiscoveryNotSupportedError,
    FileAccessNotSupportedError,
    ResourceListingNotSupportedError,
    ResourceNotFoundError,
    Skill,
    SkillProvider,
    SkillUnavailableError,
    capture_skill,
)


class _StubProvider(SkillProvider):
    async def get_metadata(self, skill_id: str) -> dict:
        return {"name": skill_id, "description": "A test skill."}

    async def get_body(self, skill_id: str) -> str:
        return "# Test"

    async def get_script(self, skill_id: str, name: str) -> bytes:
        return b""

    async def get_asset(self, skill_id: str, name: str) -> bytes:
        return b""

    async def get_reference(self, skill_id: str, name: str) -> bytes:
        return b""


class TestResourceListingCapability:
    """Listing is optional: opt in by overriding, declare via the flag."""

    def test_default_flag_is_false(self):
        assert _StubProvider().supports_resource_listing is False

    async def test_default_raises_rather_than_returning_empty(self):
        """'Cannot enumerate' must not be reported as 'has no resources'."""
        with pytest.raises(ResourceListingNotSupportedError, match="_StubProvider"):
            await _StubProvider().list_resources("some-skill")

    async def test_is_a_not_implemented_error(self):
        """Callers that only know the stdlib hierarchy can still catch it."""
        with pytest.raises(NotImplementedError):
            await _StubProvider().list_resources("some-skill")

    async def test_subclass_can_opt_in(self):
        class ListingProvider(_StubProvider):
            supports_resource_listing = True

            async def list_resources(self, skill_id: str) -> dict[str, list[str]]:
                return {kind: [] for kind in RESOURCE_KINDS}

        provider = ListingProvider()
        assert provider.supports_resource_listing is True
        assert await provider.list_resources("s") == {
            "references": [],
            "scripts": [],
            "assets": [],
        }

    def test_resource_kinds_are_the_spec_categories(self):
        assert RESOURCE_KINDS == ("references", "scripts", "assets")


class TestDiscoveryCapability:
    """Discovery is optional: opt in by overriding, declare via the flag."""

    def test_default_flag_is_false(self):
        assert _StubProvider().supports_discovery is False

    async def test_default_raises_rather_than_returning_empty(self):
        """'Cannot enumerate' must not be reported as 'holds no skills'."""
        with pytest.raises(DiscoveryNotSupportedError, match="_StubProvider"):
            await _StubProvider().discover()

    async def test_is_a_not_implemented_error(self):
        """Callers that only know the stdlib hierarchy can still catch it."""
        with pytest.raises(NotImplementedError):
            await _StubProvider().discover()

    async def test_subclass_can_opt_in(self):
        class DiscoverableProvider(_StubProvider):
            supports_discovery = True

            async def discover(self) -> list[str]:
                return ["alpha", "bravo"]

        provider = DiscoverableProvider()
        assert provider.supports_discovery is True
        assert await provider.discover() == ["alpha", "bravo"]


class TestFileAccessCapability:
    def test_default_flag_is_false(self):
        provider = _StubProvider()
        assert not provider.supports_file_access
        assert not Skill("some-skill", provider).supports_file_access

    async def test_default_raises_instead_of_reconstructing(self):
        skill = Skill("some-skill", _StubProvider())
        with pytest.raises(FileAccessNotSupportedError, match="_StubProvider"):
            await skill.list_files()
        with pytest.raises(FileAccessNotSupportedError, match="_StubProvider"):
            await skill.read_file("SKILL.md")

    async def test_handle_delegates_without_changing_bytes(self):
        original = b"---\r\nname: some-skill\r\n---\r\n# Body\r\n"

        class FileProvider(_StubProvider):
            supports_file_access = True

            async def list_files(self, skill_id: str) -> list[str]:
                assert skill_id == "some-skill"
                return ["SKILL.md", "data/nested.bin"]

            async def read_file(self, skill_id: str, path: str) -> bytes:
                assert skill_id == "some-skill"
                assert path == "SKILL.md"
                return original

        skill = Skill("some-skill", FileProvider())
        assert skill.supports_file_access
        assert await skill.list_files() == ["SKILL.md", "data/nested.bin"]
        assert await skill.read_file("SKILL.md") == original


class _RawProvider(_StubProvider):
    supports_file_access = True

    def __init__(self, files):
        self.files = files
        self.reads = []

    async def list_files(self, skill_id):
        return list(self.files)

    async def read_file(self, skill_id, path):
        self.reads.append(path)
        return self.files[path]


class TestSkillSnapshots:
    async def test_capture_preserves_original_bytes_and_remains_immutable(self):
        original = b"\xef\xbb\xbf---\r\nname: demo\r\n---\r\n# Body\r\n"
        provider = _RawProvider({"z/deep.bin": b"\x00\xff", "SKILL.md": original})
        snapshot = await capture_skill(Skill("demo", provider))
        provider.files["SKILL.md"] = b"changed"
        assert snapshot.skill_id == "demo"
        assert [file.path for file in snapshot.files] == ["SKILL.md", "z/deep.bin"]
        assert snapshot.total_bytes == len(original) + 2
        for file in snapshot.files:
            assert file.digest == "sha256:" + sha256(file.data).hexdigest()
            assert file.size == len(file.data)
        assert snapshot.get_file("SKILL.md").data == original
        assert snapshot.get_file("z/deep.bin").data == b"\x00\xff"
        assert provider.reads == ["SKILL.md", "z/deep.bin"] * 2
        with pytest.raises(FrozenInstanceError):
            snapshot.get_file("SKILL.md").data = b"changed"
        with pytest.raises(FrozenInstanceError):
            snapshot.files = ()
        with pytest.raises(ResourceNotFoundError):
            snapshot.get_file("../SKILL.md")

    @pytest.mark.parametrize("limits", [{"max_files": 0}, {"max_total_bytes": -1}])
    async def test_invalid_limits(self, limits):
        with pytest.raises(ValueError, match="Snapshot limits"):
            await capture_skill(Skill("demo", _StubProvider()), **limits)

    async def test_requires_lossless_capability(self):
        with pytest.raises(FileAccessNotSupportedError):
            await capture_skill(Skill("demo", _StubProvider()))

    @pytest.mark.parametrize(
        "path", ["", "/root", "../bad", "a//b", "a/./b", "a\\b", "a:b", "a\0b"]
    )
    async def test_rejects_unsafe_listing_before_reading(self, path):
        provider = _RawProvider({"SKILL.md": b"", path: b""})
        with pytest.raises(ValueError, match="unsafe"):
            await capture_skill(Skill("demo", provider))
        assert not provider.reads

    async def test_requires_skill_document(self):
        with pytest.raises(ValueError, match=r"include SKILL\.md"):
            await capture_skill(Skill("demo", _RawProvider({})))

    async def test_rejects_duplicate_paths(self):
        class DuplicateProvider(_RawProvider):
            async def list_files(self, skill_id):
                return ["SKILL.md", "SKILL.md"]

        with pytest.raises(ValueError, match="unique"):
            await capture_skill(Skill("demo", DuplicateProvider({})))

    async def test_limits_accept_boundary_and_reject_overflow(self):
        provider = _RawProvider({"SKILL.md": b"123", "empty": b""})
        assert await capture_skill(Skill("demo", provider), max_files=2, max_total_bytes=3)
        with pytest.raises(ValueError, match="1-file"):
            await capture_skill(Skill("demo", provider), max_files=1)
        provider.reads.clear()
        with pytest.raises(ValueError, match="2-byte"):
            await capture_skill(Skill("demo", provider), max_total_bytes=2)
        assert provider.reads == ["SKILL.md"]
        empty = await capture_skill(
            Skill("demo", _RawProvider({"SKILL.md": b""})), max_total_bytes=0
        )
        assert empty.total_bytes == 0

    async def test_rejects_non_bytes(self):
        with pytest.raises(ValueError, match="return bytes"):
            await capture_skill(Skill("demo", _RawProvider({"SKILL.md": "text"})))

    async def test_default_file_limit(self):
        provider = _RawProvider(
            {"SKILL.md": b"", **{f"files/{index}": b"" for index in range(511)}}
        )
        snapshot = await capture_skill(Skill("demo", provider))
        assert len(snapshot.files) == 512
        provider.files["overflow"] = b""
        provider.reads.clear()
        with pytest.raises(ValueError, match="512-file"):
            await capture_skill(Skill("demo", provider))
        assert not provider.reads

    async def test_default_byte_limit(self):
        provider = _RawProvider({"SKILL.md": b"x" * (16 * 1024 * 1024)})
        snapshot = await capture_skill(Skill("demo", provider))
        assert snapshot.total_bytes == 16 * 1024 * 1024
        provider.files["extra"] = b"x"
        with pytest.raises(ValueError, match="16777216-byte"):
            await capture_skill(Skill("demo", provider))

    async def test_rejects_non_string_path(self):
        with pytest.raises(ValueError, match="unsafe"):
            await capture_skill(Skill("demo", _RawProvider({"SKILL.md": b"", 7: b""})))

    async def test_rejects_membership_change(self):
        class ChangingProvider(_RawProvider):
            async def read_file(self, skill_id, path):
                self.files["new"] = b""
                return await super().read_file(skill_id, path)

        with pytest.raises(SkillUnavailableError, match="listing changed"):
            await capture_skill(Skill("demo", ChangingProvider({"SKILL.md": b"first"})))

    async def test_rejects_content_change(self):
        class ChangingProvider(_RawProvider):
            async def read_file(self, skill_id, path):
                data = await super().read_file(skill_id, path)
                self.files[path] = b"changed"
                return data

        with pytest.raises(SkillUnavailableError, match="content changed"):
            await capture_skill(Skill("demo", ChangingProvider({"SKILL.md": b"first"})))


class TestSkillProviderABC:
    """SkillProvider cannot be instantiated directly."""

    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            SkillProvider()  # type: ignore[abstract]

    def test_concrete_subclass_works(self):
        """A fully-implemented subclass can be instantiated."""
        provider = _StubProvider()
        # Verify the instance was created — async methods are tested elsewhere
        assert provider is not None

    def test_partial_implementation_raises(self):
        """A subclass missing abstract methods cannot be instantiated."""

        class PartialProvider(SkillProvider):
            async def get_metadata(self, skill_id: str) -> dict:
                return {}

        with pytest.raises(TypeError):
            PartialProvider()  # type: ignore[abstract]
