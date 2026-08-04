"""Findings — the single currency every command reports in.

``validate`` and ``lint`` differ only in which findings they produce and
whether those findings fail the build.  Modelling both as a list of
:class:`Finding` keeps one renderer for human output and one JSON schema
for machines, so a consumer that can read ``validate`` output can read
``lint`` output too.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class Finding:
    """A single problem found in a skill.

    Attributes:
        severity: Either ``"error"`` or ``"warning"``.
        code: Stable machine-readable identifier, e.g.
            ``"frontmatter-invalid-yaml"``.  Callers may key off this;
            *message* is free to be reworded.
        message: Human-readable explanation.
        line: 1-based line in the file the finding is about, when the
            problem can be attributed to one.  ``None`` otherwise.
        file: Path the finding is about, relative to the working
            directory, when it is not the skill's ``SKILL.md``.
    """

    severity: str
    code: str
    message: str
    line: int | None = None
    file: str | None = None


@dataclass(frozen=True)
class SkillReport:
    """Every finding for one skill."""

    skill_id: str
    path: Path
    findings: list[Finding]

    @property
    def errors(self) -> list[Finding]:
        """Findings with ``error`` severity."""
        return [f for f in self.findings if f.severity == ERROR]

    @property
    def warnings(self) -> list[Finding]:
        """Findings with ``warning`` severity."""
        return [f for f in self.findings if f.severity == WARNING]

    @property
    def ok(self) -> bool:
        """``True`` when the skill produced no error-severity findings."""
        return not self.errors
