"""Rendering — one human format and one JSON schema for every command.

The JSON shape is a published contract: the validation GitHub Action
and anything else in CI keys off it.  ``SCHEMA_VERSION`` is bumped only
for a breaking change, and new fields are added rather than existing
ones repurposed.
"""

from __future__ import annotations

import json
from typing import Any, TextIO

from agentskills_cli.discovery import relative_to_cwd
from agentskills_cli.findings import SkillReport

SCHEMA_VERSION = 1


def count(reports: list[SkillReport]) -> tuple[int, int]:
    """Return ``(errors, warnings)`` totalled across *reports*."""
    errors = sum(len(report.errors) for report in reports)
    warnings = sum(len(report.warnings) for report in reports)
    return errors, warnings


def exit_code(reports: list[SkillReport], *, strict: bool = False) -> int:
    """Return the process exit code for *reports*.

    Errors always fail.  Warnings fail only under *strict*, which is
    what a repository sets when it wants lint findings to gate a pull
    request.
    """
    errors, warnings = count(reports)
    if errors or (strict and warnings):
        return 1
    return 0


def plural(n: int, noun: str) -> str:
    """Return *n* and *noun*, pluralised by adding an ``s``."""
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def render_text(reports: list[SkillReport], out: TextIO) -> None:
    """Write a human-readable report."""
    for report in reports:
        print(relative_to_cwd(report.path), file=out)
        if not report.findings:
            print("  ok", file=out)
            continue
        for finding in report.findings:
            location = f" (line {finding.line})" if finding.line is not None else ""
            print(
                f"  {finding.severity:<7} {finding.code}{location}: {finding.message}",
                file=out,
            )

    errors, warnings = count(reports)
    print(
        f"\n{plural(len(reports), 'skill')} checked, "
        f"{plural(errors, 'error')}, {plural(warnings, 'warning')}",
        file=out,
    )


def render_json(
    command: str,
    reports: list[SkillReport],
    out: TextIO,
    *,
    strict: bool = False,
) -> None:
    """Write the machine-readable report.

    ``ok`` mirrors the exit code, so a consumer never has to re-derive
    the strictness rules to know whether the run passed.
    """
    errors, warnings = count(reports)
    payload: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "command": command,
        "ok": exit_code(reports, strict=strict) == 0,
        "summary": {"skills": len(reports), "errors": errors, "warnings": warnings},
        "skills": [
            {
                "id": report.skill_id,
                "path": relative_to_cwd(report.path),
                "ok": report.ok,
                "findings": [
                    {
                        "severity": finding.severity,
                        "code": finding.code,
                        "message": finding.message,
                        "line": finding.line,
                    }
                    for finding in report.findings
                ],
            }
            for report in reports
        ],
    }
    json.dump(payload, out, indent=2)
    print(file=out)
