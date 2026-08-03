"""Argument parsing and dispatch for the ``agentskills`` command.

Exit codes are the contract CI depends on:

* ``0`` — the command ran and found nothing wrong.
* ``1`` — the command ran and found errors (or, under ``--strict``,
  warnings).
* ``2`` — the command could not run: a bad path, a missing extra, an
  unwritable directory.

Keeping "found a problem" distinct from "could not look" means a
workflow can tell a broken skill from a broken invocation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, TextIO

from agentskills_cli.discovery import CliError, SkillLocation, discover, relative_to_cwd
from agentskills_cli.findings import SkillReport
from agentskills_cli.inspection import inspect_location, render_inspection_text
from agentskills_cli.lint import DEFAULT_BODY_TOKEN_BUDGET, lint_locations
from agentskills_cli.render import (
    SCHEMA_VERSION,
    exit_code,
    plural,
    render_github,
    render_json,
    render_text,
)
from agentskills_cli.scaffold import DEFAULT_DESCRIPTION, init_skill
from agentskills_cli.serve import build_registry, create_server
from agentskills_cli.validate import validate_locations
from agentskills_core import LOGGER_NAMESPACE

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2


def _format_parent(*choices: str) -> argparse.ArgumentParser:
    """Build a parent parser offering ``--format`` over *choices*.

    Only ``validate`` and ``lint`` produce findings, so only they can
    offer ``github``; advertising it on ``inspect`` would promise an
    output that command has no way to produce.
    """
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--format",
        choices=list(choices),
        default="text",
        help="Output format (default: text).",
    )
    return parent


def build_parser() -> argparse.ArgumentParser:
    """Build the ``agentskills`` argument parser."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print the SDK's debug logs to stderr.",
    )

    reported = _format_parent("text", "json", "github")
    formatted = _format_parent("text", "json")

    parser = argparse.ArgumentParser(
        prog="agentskills",
        description="Author, validate, and serve Agent Skills.",
        parents=[common],
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser(
        "init",
        parents=[common],
        help="Scaffold a new skill.",
        description="Scaffold a new skill directory that already validates.",
    )
    init.add_argument("name", help="Skill name, also used as the directory name.")
    init.add_argument(
        "--path",
        type=Path,
        default=Path("."),
        help="Directory to create the skill in (default: the working directory).",
    )
    init.add_argument(
        "--description",
        default=DEFAULT_DESCRIPTION,
        help="Frontmatter description for the new skill.",
    )

    validate = subparsers.add_parser(
        "validate",
        parents=[common, reported],
        help="Check skills against the specification.",
        description="Check one skill or a directory of skills. Exits 1 on any error.",
    )
    validate.add_argument("path", type=Path, help="A skill folder or a folder of skills.")

    lint = subparsers.add_parser(
        "lint",
        parents=[common, reported],
        help="Report quality warnings.",
        description="Report problems that are legal per the spec but still cost you.",
    )
    lint.add_argument("path", type=Path, help="A skill folder or a folder of skills.")
    lint.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 on warnings as well as errors.",
    )
    lint.add_argument(
        "--max-body-tokens",
        type=int,
        default=DEFAULT_BODY_TOKEN_BUDGET,
        metavar="N",
        help=f"Estimated body token budget (default: {DEFAULT_BODY_TOKEN_BUDGET}).",
    )

    inspect = subparsers.add_parser(
        "inspect",
        parents=[common, formatted],
        help="Show what an agent would receive.",
        description="Render the catalog entry, metadata, and body, with estimated token cost.",
    )
    inspect.add_argument("path", type=Path, help="A skill folder or a folder of skills.")

    serve = subparsers.add_parser(
        "serve",
        parents=[common],
        help="Run an MCP server over a folder of skills.",
        description="Run an MCP server over a folder of skills, with no config file.",
    )
    serve.add_argument("path", type=Path, help="A skill folder or a folder of skills.")
    serve.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="MCP transport (default: stdio).",
    )
    serve.add_argument(
        "--name",
        default="Agent Skills",
        help="Display name advertised by the server.",
    )

    return parser


def _enable_debug_logging() -> None:
    """Send the SDK's own logs to stderr, leaving stdout parseable."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logger = logging.getLogger(LOGGER_NAMESPACE)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)


def _run_init(args: argparse.Namespace, out: TextIO) -> int:
    target = asyncio.run(init_skill(args.name, args.path, args.description))
    print(f"Created {relative_to_cwd(target)}", file=out)
    return EXIT_OK


def _render(
    command: str,
    output_format: str,
    reports: list[SkillReport],
    out: TextIO,
    *,
    strict: bool = False,
) -> None:
    """Write *reports* in the requested format."""
    if output_format == "json":
        render_json(command, reports, out, strict=strict)
    elif output_format == "github":
        render_github(reports, out)
    else:
        render_text(reports, out)


def _run_validate(args: argparse.Namespace, out: TextIO) -> int:
    root, locations = discover(args.path)
    reports = asyncio.run(validate_locations(root, locations))
    _render("validate", args.format, reports, out)
    return exit_code(reports)


def _run_lint(args: argparse.Namespace, out: TextIO) -> int:
    root, locations = discover(args.path)
    reports = asyncio.run(lint_locations(root, locations, body_token_budget=args.max_body_tokens))
    _render("lint", args.format, reports, out, strict=args.strict)
    return exit_code(reports, strict=args.strict)


async def _inspect_all(root: Path, locations: list[SkillLocation]) -> list[dict[str, Any]]:
    return [await inspect_location(root, location) for location in locations]


def _run_inspect(args: argparse.Namespace, out: TextIO) -> int:
    root, locations = discover(args.path)
    inspections = asyncio.run(_inspect_all(root, locations))
    if args.format == "json":
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "command": "inspect",
            "skills": inspections,
        }
        json.dump(payload, out, indent=2)
        print(file=out)
    else:
        for index, inspection in enumerate(inspections):
            if index:
                print("\n" + "-" * 60 + "\n", file=out)
            render_inspection_text(inspection, out)
    return EXIT_OK


def _run_serve(args: argparse.Namespace, out: TextIO) -> int:
    root, locations = discover(args.path)
    registry = asyncio.run(build_registry(root, locations))
    server = create_server(registry, name=args.name)
    print(f"Serving {plural(len(locations), 'skill')} over {args.transport}", file=sys.stderr)
    server.run(transport=args.transport)
    return EXIT_OK


_COMMANDS = {
    "init": _run_init,
    "validate": _run_validate,
    "lint": _run_lint,
    "inspect": _run_inspect,
    "serve": _run_serve,
}


def main(argv: list[str] | None = None, out: TextIO | None = None) -> int:
    """Run the ``agentskills`` command line.

    Args:
        argv: Arguments to parse.  Defaults to ``sys.argv[1:]``.
        out: Stream to write reports to.  Defaults to stdout.

    Returns:
        A process exit code.
    """
    args = build_parser().parse_args(argv)
    if args.verbose:
        _enable_debug_logging()

    try:
        return _COMMANDS[args.command](args, out or sys.stdout)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
