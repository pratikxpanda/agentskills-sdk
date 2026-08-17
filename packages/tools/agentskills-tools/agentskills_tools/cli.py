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

from agentskills_core import LOGGER_NAMESPACE, Skill
from agentskills_fs import LocalFileSystemSkillProvider
from agentskills_tools.cost import (
    TOKENIZERS,
    SkillCost,
    cost_exit_code,
    cost_payload,
    cost_skill,
    render_cost_text,
    resolve_counter,
)
from agentskills_tools.discovery import CliError, SkillLocation, discover, relative_to_cwd
from agentskills_tools.evals import (
    DEFAULT_CACHE_DIR,
    CompletionCache,
    EvalRunner,
    eval_exit_code,
    load_model,
    render_results_text,
    results_payload,
    run_suites,
)
from agentskills_tools.evalspec import EvalSuite, load_skill_evals
from agentskills_tools.findings import SkillReport
from agentskills_tools.inspection import inspect_location, render_inspection_text
from agentskills_tools.lint import DEFAULT_BODY_TOKEN_BUDGET, lint_locations
from agentskills_tools.render import (
    SCHEMA_VERSION,
    exit_code,
    plural,
    render_github,
    render_json,
    render_text,
)
from agentskills_tools.scaffold import DEFAULT_DESCRIPTION, init_from, init_skill
from agentskills_tools.serve import build_registry, create_server
from agentskills_tools.validate import validate_locations

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
    init.add_argument("name", nargs="?", help="Skill name, also used as the directory name.")
    init.add_argument(
        "--path",
        type=Path,
        default=Path("."),
        help="Directory to create the skill in (default: the working directory).",
    )
    init.add_argument(
        "--description",
        default=None,
        help="Frontmatter description for the new skill.",
    )
    init.add_argument(
        "--from",
        dest="source",
        type=Path,
        help="Import an AGENTS.md, Copilot file, Cursor rule, or Claude skill folder.",
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
    inspect.add_argument(
        "--cost",
        action="store_true",
        help="Report token cost per turn, per load, and on demand instead of the content.",
    )
    inspect.add_argument(
        "--budget",
        type=int,
        metavar="N",
        help="With --cost, exit 1 when catalog entry plus body exceeds N tokens.",
    )
    inspect.add_argument(
        "--turn-budget",
        type=int,
        metavar="N",
        help="With --cost, exit 1 when the catalog entry alone exceeds N tokens.",
    )
    inspect.add_argument(
        "--tokenizer",
        choices=list(TOKENIZERS),
        default="auto",
        help="Token counter (default: auto, which uses tiktoken when it is usable).",
    )

    evaluate = subparsers.add_parser(
        "eval",
        parents=[common, formatted],
        help="Measure what difference a skill makes.",
        description=(
            "Run each eval case twice, with and without the skill, and report "
            "the delta. Calls a real model: opt in deliberately."
        ),
    )
    evaluate.add_argument("path", type=Path, help="A skill folder or a folder of skills.")
    evaluate.add_argument(
        "--model",
        required=True,
        metavar="MODULE:FACTORY",
        help="Dotted path to a zero-argument callable returning a model client.",
    )
    evaluate.add_argument(
        "--judge",
        metavar="MODULE:FACTORY",
        help="Model client for judged expectations (default: the model under test).",
    )
    evaluate.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help=f"Where to cache completions (default: {DEFAULT_CACHE_DIR}).",
    )
    evaluate.add_argument(
        "--no-cache",
        action="store_true",
        help="Call the model for every attempt, ignoring and not writing the cache.",
    )

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
    if args.source:
        target = asyncio.run(init_from(args.source, args.path, args.name, args.description))
    elif args.name:
        target = asyncio.run(
            init_skill(args.name, args.path, args.description or DEFAULT_DESCRIPTION)
        )
    else:
        raise CliError("init requires a skill name or --from source")
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


async def _cost_all(root: Path, locations: list[SkillLocation], tokenizer: str) -> list[SkillCost]:
    counter = resolve_counter(tokenizer)
    provider = LocalFileSystemSkillProvider(root)
    costs = []
    for location in locations:
        inspection = await inspect_location(root, location)
        skill = Skill(location.skill_id, provider)
        costs.append(
            await cost_skill(
                skill,
                inspection["path"],
                inspection["catalogEntry"],
                inspection["body"],
                counter,
            )
        )
    return costs


def _run_cost(args: argparse.Namespace, out: TextIO) -> int:
    root, locations = discover(args.path)
    costs = asyncio.run(_cost_all(root, locations, args.tokenizer))
    budgets = {"budget": args.budget, "turn_budget": args.turn_budget}
    if args.format == "json":
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "command": "inspect",
            "skills": cost_payload(costs, **budgets),
        }
        json.dump(payload, out, indent=2)
        print(file=out)
    else:
        render_cost_text(costs, out, **budgets)
    return cost_exit_code(costs, **budgets)


def _run_inspect(args: argparse.Namespace, out: TextIO) -> int:
    if args.cost:
        return _run_cost(args, out)

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


async def _collect_suites(
    root: Path, locations: list[SkillLocation]
) -> tuple[list[tuple[EvalSuite, str]], list[SkillReport]]:
    """Load every eval suite, pairing each with its skill's body."""
    provider = LocalFileSystemSkillProvider(root)
    pairs: list[tuple[EvalSuite, str]] = []
    broken: list[SkillReport] = []
    for location in locations:
        suites, findings = load_skill_evals(location.path, location.skill_id)
        if findings:
            broken.append(SkillReport(location.skill_id, location.path, findings))
        if not suites:
            continue
        # The skill's body is the whole intervention being measured, so
        # it is what goes in the system prompt for the "with" run.
        body = await Skill(location.skill_id, provider).get_body()
        pairs.extend((suite, body) for suite in suites)
    return pairs, broken


def _run_eval(args: argparse.Namespace, out: TextIO) -> int:
    root, locations = discover(args.path)
    pairs, broken = asyncio.run(_collect_suites(root, locations))
    if broken:
        render_text(broken, sys.stderr)
        print(
            "error: fix the eval files above before spending money on them",
            file=sys.stderr,
        )
        return EXIT_ERROR
    if not pairs:
        raise CliError(f"no eval cases found under {relative_to_cwd(root)}")

    model = load_model(args.model)
    judge = load_model(args.judge) if args.judge else None
    cache = CompletionCache(None if args.no_cache else args.cache_dir)
    runner = EvalRunner(model, judge=judge, cache=cache)
    results = asyncio.run(run_suites(runner, pairs))

    if args.format == "json":
        payload = {"schemaVersion": SCHEMA_VERSION, **results_payload(results)}
        json.dump(payload, out, indent=2)
        print(file=out)
    else:
        render_results_text(results, out)
    return eval_exit_code(results)


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
    "eval": _run_eval,
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
