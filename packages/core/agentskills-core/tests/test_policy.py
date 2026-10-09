"""Content policy runs before delivered identities are computed."""

import pytest

from agentskills_core.policy import ContentDecision, ContentRejectedError, publish_snapshot
from agentskills_core.snapshots import SkillFile, SkillSnapshot
from agentskills_core.trust import TrustPolicy, VerificationError, content_revision


@pytest.fixture
def snapshot():
    return SkillSnapshot(
        "alpha",
        (
            SkillFile("SKILL.md", b"---\nname: alpha\ndescription: Test\n---\nsecret"),
            SkillFile("assets/raw.bin", b"\xff"),
        ),
    )


@pytest.fixture
def trust():
    return TrustPolicy("test", require_signature=False)


def test_given_redaction_when_published_then_revision_covers_delivered_bytes(snapshot, trust):
    result = publish_snapshot(
        snapshot,
        trust=trust,
        hooks=[
            lambda file: ContentDecision(
                file.data.replace(b"secret", b"redacted"), annotations=("scan",)
            )
        ],
    )

    assert result.transformed
    assert result.source_identity.revision == content_revision(snapshot)
    assert result.revision == content_revision(result.snapshot)
    assert result.annotations == ("scan", "scan")
    assert b"secret" not in result.snapshot.get_file("SKILL.md").data


def test_given_no_transform_when_published_then_identity_is_unchanged(snapshot, trust):
    result = publish_snapshot(snapshot, trust=trust, hooks=[lambda file: ContentDecision()])

    assert not result.transformed


def test_given_reject_hook_when_published_then_no_result(snapshot, trust):
    with pytest.raises(ContentRejectedError):
        publish_snapshot(snapshot, trust=trust, hooks=[lambda file: ContentDecision(reject=True)])


def test_given_unverified_source_when_policy_runs_then_hooks_cannot_bypass_trust(snapshot):
    def hook(file):
        pytest.fail("Hook ran before verification")

    with pytest.raises(VerificationError):
        publish_snapshot(snapshot, trust=TrustPolicy("test"), hooks=[hook])


@pytest.mark.parametrize(
    "limit,counter,error",
    [
        (-1, len, ValueError),
        (1, None, ValueError),
        (0, len, ContentRejectedError),
        (1000, lambda text: -1, ContentRejectedError),
        (1000, lambda text: True, ContentRejectedError),
    ],
)
def test_given_invalid_token_budget_when_published_then_rejected(
    snapshot, trust, limit, counter, error
):
    with pytest.raises(error):
        publish_snapshot(snapshot, trust=trust, max_tokens=limit, count_tokens=counter)


def test_given_binary_file_when_counting_tokens_then_bytes_remain_unchanged(snapshot, trust):
    result = publish_snapshot(snapshot, trust=trust, max_tokens=1000, count_tokens=len)

    assert result.snapshot == snapshot


@pytest.mark.parametrize(
    "decision",
    [
        ContentDecision(data="bad"),
        ContentDecision(annotations=(1,)),
        ContentDecision(annotations=("x" * 129,)),
    ],
)
def test_given_invalid_hook_output_when_published_then_rejected(snapshot, trust, decision):
    with pytest.raises(ContentRejectedError):
        publish_snapshot(snapshot, trust=trust, hooks=[lambda file: decision])


def test_given_invalid_transformed_frontmatter_when_published_then_rejected(snapshot, trust):
    with pytest.raises(ValueError):
        publish_snapshot(snapshot, trust=trust, hooks=[lambda file: ContentDecision(b"invalid")])
