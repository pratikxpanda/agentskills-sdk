"""A labelled corpus for measuring selection, not just exercising it.

Twelve skills with overlapping vocabulary, and queries phrased the way
a user would phrase them rather than the way the skill is written. The
overlap is the point: a corpus of twelve unrelated skills would score
perfectly under any ranker and prove nothing.
"""

from __future__ import annotations

import pytest

from agentskills_core import SkillRegistry
from agentskills_testing import InMemorySkillProvider, build_skill

#: skill_id -> (description, when_to_use, when_not_to_use, tags)
CORPUS: dict[str, tuple[str, list[str], list[str], list[str]]] = {
    "incident-response": (
        "Triage and mitigate production incidents affecting live traffic.",
        [
            "A production service is returning errors or is unreachable",
            "Customers are reporting an outage",
        ],
        ["A test is failing on a developer laptop"],
        ["incident", "oncall", "production"],
    ),
    "postmortem-writing": (
        "Write a blameless postmortem after an incident is resolved.",
        ["An incident has been mitigated and needs a written record"],
        ["The incident is still ongoing"],
        ["incident", "writing"],
    ),
    "database-migrations": (
        "Plan and apply schema migrations to a relational database safely.",
        ["A table needs a new column or index", "A migration must run without downtime"],
        ["Querying data for a report"],
        ["database", "sql"],
    ),
    "sql-query-tuning": (
        "Diagnose and speed up slow SQL queries by reading query plans.",
        ["A query is slow", "A report takes minutes to load"],
        ["Changing the schema itself"],
        ["database", "sql", "performance"],
    ),
    "kubernetes-debugging": (
        "Debug pods that will not start, crash-loop, or fail their probes.",
        ["A pod is in CrashLoopBackOff", "A deployment never becomes ready"],
        ["Provisioning a new cluster"],
        ["kubernetes", "containers"],
    ),
    "docker-image-builds": (
        "Build small, reproducible container images and fix broken builds.",
        ["A Dockerfile build fails", "An image is far larger than expected"],
        ["Running containers in production"],
        ["containers", "build"],
    ),
    "api-style-guide": (
        "House conventions for designing HTTP APIs: naming, status codes, pagination.",
        ["Designing a new REST endpoint", "Reviewing an API change"],
        ["Debugging a failing API call"],
        ["api", "review"],
    ),
    "code-review": (
        "Review a pull request for correctness, tests, and readability.",
        ["A pull request is waiting for review"],
        ["Writing the change yourself"],
        ["review", "quality"],
    ),
    "onboarding-new-hire": (
        "Get a new engineer productive in their first two weeks.",
        ["Someone has just joined the team"],
        ["A contractor needing read-only access"],
        ["people", "onboarding"],
    ),
    "security-disclosure": (
        "Handle an inbound vulnerability report and coordinate a fix.",
        ["A researcher has reported a vulnerability", "A CVE affects a dependency"],
        ["Routine dependency upgrades with no known vulnerability"],
        ["security"],
    ),
    "release-process": (
        "Cut, tag, and publish a versioned release of a library.",
        ["A new version is ready to ship", "A release needs to be rolled back"],
        ["Deploying a service"],
        ["release", "publishing"],
    ),
    "cost-optimisation": (
        "Find and remove wasteful cloud spend.",
        ["The monthly bill has jumped", "An account is over budget"],
        ["Estimating the cost of a new project"],
        ["cost", "cloud"],
    ),
}

#: Query -> the skill that should win. Phrased as a user would phrase it.
LABELLED_QUERIES: list[tuple[str, str]] = [
    ("checkout is down and customers cannot pay", "incident-response"),
    ("the payments service is returning 503 to live traffic", "incident-response"),
    ("we mitigated the outage, now write up what happened", "postmortem-writing"),
    ("add an index to the orders table without downtime", "database-migrations"),
    ("this report query takes four minutes, read the plan", "sql-query-tuning"),
    ("my pod is stuck in CrashLoopBackOff", "kubernetes-debugging"),
    ("the Dockerfile build keeps failing on the copy step", "docker-image-builds"),
    ("what status code should a new REST endpoint return", "api-style-guide"),
    ("there is a pull request waiting for me to review", "code-review"),
    ("someone joins the team on Monday", "onboarding-new-hire"),
    ("a researcher emailed us about a vulnerability", "security-disclosure"),
    ("we need to tag and publish version 2.1", "release-process"),
    ("the monthly cloud bill jumped by forty percent", "cost-optimisation"),
]


async def labelled_registry() -> SkillRegistry:
    """Register the whole fixture corpus."""
    skills = {
        skill_id: build_skill(
            skill_id,
            description=description,
            body=f"# {skill_id}\n\nInstructions.",
            metadata={
                "when_to_use": when_to_use,
                "when_not_to_use": when_not_to_use,
                "metadata": {"tags": tags},
            },
        )
        for skill_id, (description, when_to_use, when_not_to_use, tags) in CORPUS.items()
    }
    registry = SkillRegistry()
    await registry.register(
        [(skill_id, InMemorySkillProvider({skill_id: skill})) for skill_id, skill in skills.items()]
    )
    return registry


@pytest.fixture
async def labelled() -> SkillRegistry:
    """A registry holding the whole labelled corpus."""
    return await labelled_registry()


@pytest.fixture
def queries() -> list[tuple[str, str]]:
    """The labelled query set, as ``(query, expected_skill_id)``."""
    return list(LABELLED_QUERIES)
