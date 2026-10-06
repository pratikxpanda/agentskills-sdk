"""Canonical manifests preserve author metadata and original file bytes."""

import hashlib

import pytest

from agentskills_core.manifests import build_skill_manifest
from agentskills_core.snapshots import SkillFile, SkillSnapshot


def _snapshot(frontmatter: bytes, *, skill_id: str = "example") -> SkillSnapshot:
    return SkillSnapshot(
        skill_id,
        (
            SkillFile("SKILL.md", frontmatter),
            SkillFile("data/raw #1.bin", b"\x00\xff\x01"),
        ),
    )


def test_manifest_preserves_frontmatter_and_exact_digests():
    raw = (
        b"\xef\xbb\xbf---\r\nname: example\r\ndescription: Example skill\r\n"
        b"author-field:\r\n  values: [true, 3, null]\r\n---\r\nOriginal body\r\n"
    )
    manifest = build_skill_manifest(_snapshot(raw))
    assert manifest["uri"] == "skill://example/SKILL.md"
    assert manifest["frontmatter"]["author-field"] == {"values": [True, 3, None]}
    assert manifest["resources"] == [
        {
            "uri": "skill://example/SKILL.md",
            "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "size": len(raw),
        },
        {
            "uri": "skill://example/data/raw%20%231.bin",
            "digest": "sha256:" + hashlib.sha256(b"\x00\xff\x01").hexdigest(),
            "size": 3,
        },
    ]


def test_manifest_alias_keeps_declared_name_as_final_segment():
    snapshot = _snapshot(b"---\nname: example\ndescription: Example\n---\n", skill_id="alias")
    assert build_skill_manifest(snapshot)["uri"] == "skill://alias/example/SKILL.md"
    assert build_skill_manifest(snapshot, skill_path="team/example")["uri"] == (
        "skill://team/example/SKILL.md"
    )
    with pytest.raises(ValueError, match="frontmatter name"):
        build_skill_manifest(snapshot, skill_path="team/alias")


@pytest.mark.parametrize(
    "extra",
    [b"date: 2026-10-06\n", b"name: duplicate\n", b"number: .nan\n", b"1: value\n"],
)
def test_manifest_rejects_ambiguous_or_non_json_yaml(extra):
    with pytest.raises(ValueError):
        build_skill_manifest(
            _snapshot(b"---\nname: example\ndescription: Example\n" + extra + b"---\n")
        )


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"name: example",
        b"---\nname: example",
        b"---\n- example\n---\n",
        b"---\n[invalid\n---\n",
        b"\xff",
        b"---\nname: example\ndescription: Example\nloop: &loop [*loop]\n---\n",
    ],
)
def test_manifest_rejects_invalid_documents(raw):
    with pytest.raises(ValueError):
        build_skill_manifest(_snapshot(raw))


@pytest.mark.parametrize(
    "name", ["null", "''", "123", "UPPER", "-name", "name-", "name--test", "under_score", "x" * 65]
)
def test_manifest_rejects_invalid_names(name):
    with pytest.raises(ValueError, match="Skill name"):
        build_skill_manifest(_snapshot(f"---\nname: {name}\ndescription: Example\n---\n".encode()))


@pytest.mark.parametrize("description", ["null", "123", "''", "'   '", "x" * 1025])
def test_manifest_rejects_invalid_descriptions(description):
    with pytest.raises(ValueError, match="Skill description"):
        build_skill_manifest(
            _snapshot(f"---\nname: example\ndescription: {description}\n---\n".encode())
        )


@pytest.mark.parametrize(
    "extra",
    [
        "license: []",
        "allowed-tools: []",
        "compatibility: null",
        "compatibility: ''",
        "compatibility: " + "x" * 501,
        "metadata: []",
        "metadata: {version: 1}",
    ],
)
def test_manifest_rejects_invalid_optional_fields(extra):
    with pytest.raises(ValueError):
        build_skill_manifest(
            _snapshot(f"---\nname: example\ndescription: Example\n{extra}\n---\n".encode())
        )


def test_manifest_accepts_unicode_names_and_preserves_optional_fields():
    name = "\u00e9tude"
    raw = (
        f"---\nname: {name}\ndescription: Example\nlicense: MIT\nallowed-tools: Read\n"
        'compatibility: Python\nmetadata: {version: "1"}\ncustom: [true, null]\n---\n'
        "Indented delimiter in body:\n  ---\n"
    ).encode()
    manifest = build_skill_manifest(_snapshot(raw, skill_id=name))
    assert manifest["uri"] == "skill://%C3%A9tude/SKILL.md"
    assert manifest["frontmatter"] == {
        "name": name,
        "description": "Example",
        "license": "MIT",
        "allowed-tools": "Read",
        "compatibility": "Python",
        "metadata": {"version": "1"},
        "custom": [True, None],
    }


@pytest.mark.parametrize(
    "path", ["/example", "../example", "team//example", "team\\example", "\x00/example"]
)
def test_manifest_rejects_unsafe_skill_paths(path):
    with pytest.raises(ValueError, match="skill_path"):
        build_skill_manifest(
            _snapshot(b"---\nname: example\ndescription: Example\n---\n"), skill_path=path
        )


def test_manifest_revalidates_manually_constructed_snapshot_limits():
    with pytest.raises(ValueError, match="512-file"):
        build_skill_manifest(
            SkillSnapshot("example", tuple(SkillFile(str(index), b"") for index in range(513)))
        )
    with pytest.raises(ValueError, match="16 MiB"):
        build_skill_manifest(
            SkillSnapshot("example", (SkillFile("SKILL.md", b"x" * (16 * 1024 * 1024 + 1)),))
        )
    with pytest.raises(ValueError, match="unsafe"):
        build_skill_manifest(SkillSnapshot("example", (SkillFile("../SKILL.md", b""),)))
    with pytest.raises(ValueError, match="unique"):
        build_skill_manifest(SkillSnapshot("example", (SkillFile("SKILL.md", b""),) * 2))


def test_frontmatter_alias_expansion_is_bounded(monkeypatch):
    import agentskills_core.manifests as manifests

    monkeypatch.setattr(manifests, "DEFAULT_SNAPSHOT_MAX_BYTES", 500)
    raw = (
        "---\nname: example\ndescription: Example\nvalue: &value "
        + "x" * 32
        + "\noverflow: ["
        + ", ".join(["*value"] * 20)
        + "]\n---\n"
    ).encode()
    assert len(raw) < 500
    with pytest.raises(ValueError, match="Frontmatter JSON"):
        build_skill_manifest(_snapshot(raw))


def test_frontmatter_yaml_merges_preserve_resolved_values():
    raw = (
        b"---\nname: example\ndescription: Example\ndefaults: &defaults {value: original}\n"
        b"custom: {<<: *defaults, value: overridden, extra: true}\n---\n"
    )
    manifest = build_skill_manifest(_snapshot(raw))
    assert manifest["frontmatter"]["defaults"] == {"value": "original"}
    assert manifest["frontmatter"]["custom"] == {"value": "overridden", "extra": True}


def test_frontmatter_rejects_non_string_keys_in_merges():
    raw = b"---\nname: example\ndescription: Example\ncustom: {<<: {1: value}}\n---\n"
    with pytest.raises(ValueError, match="mapping keys"):
        build_skill_manifest(_snapshot(raw))


def test_frontmatter_rejects_duplicates_inside_inline_merges():
    raw = b"---\nname: example\ndescription: Example\ncustom: {<<: {value: one, value: two}}\n---\n"
    with pytest.raises(ValueError, match="Duplicate frontmatter key"):
        build_skill_manifest(_snapshot(raw))


def test_frontmatter_accepts_chained_merge_overrides():
    raw = (
        b"---\nname: example\ndescription: Example\nbase: &base {value: original}\n"
        b"merged: &merged {<<: *base, value: changed}\ncustom: {<<: *merged}\n---\n"
    )
    assert build_skill_manifest(_snapshot(raw))["frontmatter"]["custom"] == {"value": "changed"}
