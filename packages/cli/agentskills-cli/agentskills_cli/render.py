"""Rendering — one report, three audiences.

Text is for a person at a terminal, JSON for a program, and GitHub for
a pull request diff.  The JSON shape is a published contract, so
``SCHEMA_VERSION`` is bumped only for a breaking change and new fields
are added rather than existing ones repurposed.
"""

from __future__ import annotations

import json
from typing import Any, TextIO

from agentskills_cli.discovery import SKILL_FILE, relative_to_cwd
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
            where = ", ".join(
                part
                for part in (finding.file, None if finding.line is None else f"line {finding.line}")
                if part
            )
            location = f" ({where})" if where else ""
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


def _escape_data(value: str) -> str:
    """Escape the message half of a workflow command."""
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(value: str) -> str:
    """Escape a workflow command property value.

    Properties are comma-separated and colon-terminated, so those two
    characters have to go as well as the message escapes.
    """
    return _escape_data(value).replace(":", "%3A").replace(",", "%2C")


def render_github(reports: list[SkillReport], out: TextIO) -> None:
    """Write findings as GitHub Actions workflow commands.

    Every finding becomes an annotation against the file it is about —
    the skill's ``SKILL.md`` unless the finding names another — so it
    lands on the pull request diff rather than in a log nobody opens.
    ``severity`` is already ``error`` or ``warning``, which are the
    workflow command names, so the mapping is the identity.
    """
    for report in reports:
        default = relative_to_cwd(report.path / SKILL_FILE)
        for finding in report.findings:
            properties = [f"file={_escape_property(finding.file or default)}"]
            if finding.line is not None:
                properties.append(f"line={finding.line}")
            properties.append(f"title={_escape_property(finding.code)}")
            print(
                f"::{finding.severity} {','.join(properties)}::{_escape_data(finding.message)}",
                file=out,
            )

    errors, warnings = count(reports)
    print(
        f"{plural(len(reports), 'skill')} checked, "
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
                        "file": finding.file or relative_to_cwd(report.path / SKILL_FILE),
                    }
                    for finding in report.findings
                ],
            }
            for report in reports
        ],
    }
    json.dump(payload, out, indent=2)
    print(file=out)
