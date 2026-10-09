"""Reproducible synthetic selection and MCP delivery measurements."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import platform
from collections import Counter
from collections.abc import Awaitable, Callable
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any

from pydantic import BaseModel

from agentskills_core import Skill, SkillRegistry
from agentskills_fs import LocalFileSystemSkillProvider
from agentskills_retrieval import LexicalSelector
from agentskills_tools.lint import estimate_tokens

SCENARIOS = (
    (
        "incident-response",
        "Triage production outages and service incidents.",
        "production outage incident",
    ),
    (
        "release-management",
        "Coordinate software deployment rollback and release approvals.",
        "software deployment rollback",
    ),
    (
        "invoice-review",
        "Review supplier invoices and accounting payment discrepancies.",
        "supplier invoice payment",
    ),
    (
        "docs-maintenance",
        "Update documentation examples and repair broken hyperlinks.",
        "documentation broken hyperlinks",
    ),
)


def write_corpus(root: Path, size: int) -> list[str]:
    """Write a new bounded corpus into an owned temporary directory."""
    if not 1 <= size <= 128:
        raise ValueError("catalog size must be between 1 and 128")
    identifiers = []
    for index in range(size):
        if index < len(SCENARIOS):
            identifier, description, _query = SCENARIOS[index]
        else:
            identifier = f"archive-{index:04d}"
            description = f"Archived reference entry identifier catalogindex{index}."
        directory = root / identifier
        directory.mkdir()
        (directory / "references").mkdir()
        (directory / "data").mkdir()
        document = (
            f"---\nname: {identifier}\ndescription: {json.dumps(description)}\n---\n\n"
            f"# {identifier}\n\nRead [details](references/details.md) when needed.\n\n"
            + "Follow the documented procedure and record the outcome.\n"
            * 64
        )
        (directory / "SKILL.md").write_bytes(document.encode("utf-8"))
        (directory / "references" / "details.md").write_bytes(
            b"Supporting evidence and procedure.\n" * 32
        )
        (directory / "data" / "sample.bin").write_bytes(bytes(range(256)))
        identifiers.append(identifier)
    return identifiers


async def selection_metrics(registry: SkillRegistry) -> dict[str, Any]:
    """Measure top-one micro precision/recall and explicit empty-result accuracy."""
    selector = LexicalSelector(registry)
    started = perf_counter()
    await selector.index()
    index_ms = (perf_counter() - started) * 1000
    available = {skill.get_id() for skill in registry.list_skills()}
    cases = [(query, {identifier} & available) for identifier, _description, query in SCENARIOS]
    cases.append(("picnic lunch packing", set()))
    rows = []
    true_positive = predicted_count = relevant_count = no_match_correct = no_match_count = 0
    for query, expected in cases:
        started = perf_counter()
        selected = await selector.select(query, limit=1)
        elapsed_ms = (perf_counter() - started) * 1000
        predicted = set(selected.skill_ids)
        true_positive += len(predicted & expected)
        predicted_count += len(predicted)
        relevant_count += len(expected)
        if not expected:
            no_match_count += 1
            no_match_correct += not predicted
        rows.append(
            {
                "query": query,
                "expected": sorted(expected),
                "selected": selected.skill_ids,
                "latencyMs": elapsed_ms,
            }
        )
    return {
        "dataset": "synthetic lexical sanity cases, not production accuracy",
        "selector": "LexicalSelector",
        "limit": 1,
        "indexMs": index_ms,
        "precision": true_positive / predicted_count if predicted_count else None,
        "recall": true_positive / relevant_count if relevant_count else None,
        "noMatchAccuracy": no_match_correct / no_match_count,
        "cases": rows,
    }


async def build_registry(root: Path) -> SkillRegistry:
    """Create the framework-neutral metadata registry used for ranking."""
    registry = SkillRegistry()
    await registry.register_all(LocalFileSystemSkillProvider(root))
    return registry


def json_text(value: Any) -> str:
    """Serialize measured result payloads consistently, excluding transport framing."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", by_alias=True, exclude_none=True)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


class RequestMetrics:
    """Observe actual requests using the MCP 2.2 public middleware contract."""

    def __init__(self) -> None:
        self.phase = "connect"
        self.events: list[dict[str, Any]] = []
        self.timings: dict[str, list[float]] = {}

    async def __call__(self, context: Any, call_next: Callable[[Any], Awaitable[Any]]) -> Any:
        phase = self.phase
        result = await call_next(context)
        if context.request_id is not None:
            serialized = json_text(result)
            payload = json.loads(serialized)
            resource_bytes = 0
            tool_text_bytes = 0
            if context.method == "resources/read":
                for content in payload["contents"]:
                    if "blob" in content:
                        resource_bytes += len(base64.b64decode(content["blob"], validate=True))
                    else:
                        resource_bytes += len(content["text"].encode("utf-8"))
            if context.method == "tools/call":
                tool_text_bytes = sum(
                    len(content.get("text", "").encode("utf-8"))
                    for content in payload.get("content", [])
                )
            self.events.append(
                {
                    "phase": phase,
                    "method": context.method,
                    "resultJsonBytes": len(serialized.encode("utf-8")),
                    "resultEstimatedTokens": estimate_tokens(serialized),
                    "resourceContentBytes": resource_bytes,
                    "toolTextBytes": tool_text_bytes,
                }
            )
        return result

    async def timed(self, phase: str, operation: Awaitable[Any]) -> Any:
        self.phase = phase
        started = perf_counter()
        result = await operation
        self.timings.setdefault(phase, []).append((perf_counter() - started) * 1000)
        return result

    def report(self) -> dict[str, Any]:
        result = {}
        for phase in dict.fromkeys(event["phase"] for event in self.events):
            events = [event for event in self.events if event["phase"] == phase]
            result[phase] = {
                "requests": len(events),
                "methods": dict(Counter(event["method"] for event in events)),
                "resultJsonBytes": sum(event["resultJsonBytes"] for event in events),
                "resultEstimatedTokens": sum(event["resultEstimatedTokens"] for event in events),
                "resourceContentBytes": sum(event["resourceContentBytes"] for event in events),
                "toolTextBytes": sum(event["toolTextBytes"] for event in events),
                "clientRoundTripMs": self.timings.get(phase, []),
            }
        return result


class CountingProvider(LocalFileSystemSkillProvider):
    """Count raw source reads during native snapshot construction."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.file_reads = 0
        self.file_bytes = 0

    async def read_file(self, skill_id: str, path: str) -> bytes:
        result = await super().read_file(skill_id, path)
        self.file_reads += 1
        self.file_bytes += len(result)
        return result


async def native_request(client: Any, method: str, **params: Any) -> dict[str, Any]:
    """Keep extension parameters intact through the SDK's generic request type."""
    from mcp.types import Request
    from pydantic import TypeAdapter

    return await client.session.send_request(
        Request[dict[str, Any], str](method=method, params=params), TypeAdapter(dict[str, Any])
    )


async def measure_native(root: Path, identifiers: list[str]) -> dict[str, Any]:
    """Measure native discovery and progressive reads with an official client."""
    from mcp import Client

    from agentskills_mcp_server import create_mcp_server

    provider = CountingProvider(root)
    started = perf_counter()
    server = await create_mcp_server(
        [Skill(identifier, provider) for identifier in identifiers], page_size=25
    )
    build_ms = (perf_counter() - started) * 1000
    startup_reads = provider.file_reads
    metrics = RequestMetrics()
    server.middleware.append(metrics)
    async with Client(server, cache=None, read_timeout_seconds=10) as client:
        direct = await metrics.timed(
            "directLookup",
            native_request(client, "skills/get", uri=f"skill://{identifiers[0]}/SKILL.md"),
        )
        entries = []
        params: dict[str, Any] = {}
        while True:
            page = await metrics.timed("discovery", native_request(client, "skills/list", **params))
            entries.extend(page["skills"])
            if "nextCursor" not in page:
                break
            params = {"cursor": page["nextCursor"]}
        before_delivery = metrics.report()
        prefetched = sum(
            phase["methods"].get("resources/read", 0) for phase in before_delivery.values()
        )
        if prefetched:
            raise RuntimeError("Native connection or discovery prefetched file resources")
        entry = direct["skill"]
        wanted = [entry["uri"], entry["uri"].removesuffix("SKILL.md") + "references/details.md"]
        manifest = {resource["uri"]: resource for resource in entry["resources"]}
        for uri in wanted:
            resource = await metrics.timed("delivery", client.read_resource(uri))
            content = resource.contents[0]
            text = getattr(content, "text", None)
            data = (
                text.encode("utf-8")
                if text is not None
                else base64.b64decode(content.blob, validate=True)
            )
            if (
                len(data) != manifest[uri]["size"]
                or "sha256:" + sha256(data).hexdigest() != manifest[uri]["digest"]
            ):
                raise RuntimeError("Native resource failed manifest verification")
    metadata = [
        {"name": entry["frontmatter"]["name"], "description": entry["frontmatter"]["description"]}
        for entry in entries
    ]
    return {
        "buildMs": build_ms,
        "discoveredSkills": len(entries),
        "selectionMetadataTokens": estimate_tokens(json_text(metadata)),
        "sourceSnapshotReadCalls": startup_reads,
        "sourceSnapshotReadBytes": provider.file_bytes,
        "sourceReadCallsAfterBuild": provider.file_reads - startup_reads,
        "discoveryResourcePrefetches": prefetched,
        "directLookupBeforeListing": True,
        "verifiedResources": len(wanted),
        "phases": metrics.report(),
    }


async def run_benchmark(sizes: list[int], repeats: int) -> dict[str, Any]:
    """Run fresh servers per sample without model calls or network transport."""
    if not 1 <= repeats <= 10:
        raise ValueError("repeats must be between 1 and 10")
    if not 1 <= len(sizes) <= 8 or any(not 1 <= size <= 128 for size in sizes):
        raise ValueError("provide one to eight catalog sizes, each between 1 and 128")
    samples = []
    for size in sizes:
        with TemporaryDirectory(prefix="agentskills-benchmark-") as directory:
            root = Path(directory)
            identifiers = write_corpus(root, size)
            selection = await selection_metrics(await build_registry(root))
            for repetition in range(repeats):
                async with asyncio.timeout(60):
                    measurement = await measure_native(root, identifiers)
                samples.append(
                    {
                        "catalogSize": size,
                        "repetition": repetition + 1,
                        "selection": selection,
                        "native": measurement,
                    }
                )
    return {
        "schemaVersion": 2,
        "corpusVersion": 1,
        "environment": {
            "python": platform.python_version(),
            "mcp": version("mcp"),
            "platform": platform.platform(),
        },
        "measurement": {
            "transport": "official MCP Client in-process",
            "latency": "in-process round-trip ms with instrumentation, not network latency",
            "bytes": "compact UTF-8 result JSON without JSON-RPC or transport framing",
            "tokens": "SDK estimate_tokens character heuristic, not model-tokenizer counts",
            "modelCalls": 0,
            "modelRoundTrips": 0,
            "cache": "client cache off, fresh servers, uncontrolled OS filesystem cache",
            "selection": "lexical sanity checks, not native enumeration or model accuracy",
        },
        "samples": samples,
    }


def main(argv: list[str] | None = None) -> None:
    """Print bounded synthetic benchmark results as JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[1, 10, 100])
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args(argv)
    try:
        from mcp import Client  # noqa: F401
        from mcp.server.extension import Extension  # noqa: F401
    except ImportError:
        parser.error("This benchmark requires mcp==2.2.0 and the SDK development dependencies")
    try:
        result = asyncio.run(run_benchmark(args.sizes, args.repeats))
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
