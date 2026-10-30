"""Regression checks for the repository's reproducible MCP benchmark."""

import importlib.util
import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def benchmark():
    return runpy.run_path(str(Path(__file__).parents[4] / "examples" / "mcp" / "benchmark.py"))


@pytest.mark.parametrize("size", [1, 10, 100])
async def test_selection_has_explicit_gold_and_no_match_cases(benchmark, tmp_path, size):
    identifiers = benchmark["write_corpus"](tmp_path, size)
    registry = await benchmark["build_registry"](tmp_path)

    metrics = await benchmark["selection_metrics"](registry)

    assert len(identifiers) == size
    assert metrics["precision"] == 1
    assert metrics["recall"] == 1
    assert metrics["noMatchAccuracy"] == 1
    assert len(metrics["cases"]) == 5
    assert metrics["cases"][-1]["expected"] == []
    assert metrics["cases"][-1]["selected"] == []
    assert metrics["indexMs"] >= 0


@pytest.mark.parametrize("size", [0, 129])
def test_corpus_bounds_are_explicit(benchmark, tmp_path, size):
    with pytest.raises(ValueError, match="between 1 and 128"):
        benchmark["write_corpus"](tmp_path, size)


@pytest.mark.skipif(
    importlib.util.find_spec("mcp.server.extension") is None, reason="Requires MCP 2.2"
)
async def test_native_measurements_observe_requests_and_no_prefetch(benchmark, tmp_path):
    identifiers = benchmark["write_corpus"](tmp_path, 30)

    result = await benchmark["measure_native"](tmp_path, identifiers)

    assert result["discoveredSkills"] == 30
    assert result["phases"]["discovery"]["methods"] == {"skills/list": 2}
    assert result["phases"]["directLookup"]["methods"] == {"skills/get": 1}
    assert result["phases"]["delivery"]["methods"] == {"resources/read": 2}
    assert result["phases"]["discovery"]["resourceContentBytes"] == 0
    assert result["phases"]["delivery"]["resourceContentBytes"] > 0
    assert result["sourceSnapshotReadCalls"] == 30 * 3 * 2
    assert result["sourceReadCallsAfterBuild"] == 0
    assert result["discoveryResourcePrefetches"] == 0
    assert result["verifiedResources"] == 2


@pytest.mark.skipif(
    importlib.util.find_spec("mcp.server.extension") is None, reason="Requires MCP 2.2"
)
async def test_native_prefetch_guard_detects_an_extra_read(benchmark, tmp_path, monkeypatch):
    identifiers = benchmark["write_corpus"](tmp_path, 1)
    original_request = benchmark["native_request"]

    async def prefetch(client, method, **params):
        await client.read_resource(f"skill://{identifiers[0]}/SKILL.md")
        return await original_request(client, method, **params)

    monkeypatch.setitem(benchmark["measure_native"].__globals__, "native_request", prefetch)

    with pytest.raises(ExceptionGroup) as caught:
        await benchmark["measure_native"](tmp_path, identifiers)

    assert (
        caught.value.subgroup(
            lambda error: (
                isinstance(error, RuntimeError) and "prefetched file resources" in str(error)
            )
        )
        is not None
    )


@pytest.mark.parametrize(
    ("sizes", "repeats"), [([0], 1), ([129], 1), ([], 1), ([1] * 9, 1), ([1], 0), ([1], 11)]
)
async def test_benchmark_limits(benchmark, sizes, repeats):
    with pytest.raises(ValueError):
        await benchmark["run_benchmark"](sizes, repeats)


def test_benchmark_cli_emits_json_or_actionable_sdk_error():
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parents[4] / "examples" / "mcp" / "benchmark.py"),
            "--sizes",
            "1",
            "--repeats",
            "1",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if importlib.util.find_spec("mcp.server.extension") is None:
        assert result.returncode == 2
        assert "requires mcp==2.2.0" in result.stderr
        assert result.stdout == ""
    else:
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report["schemaVersion"] == 2
        assert report["measurement"]["modelCalls"] == 0
        assert len(report["samples"]) == 1
        assert report["samples"][0]["native"]["discoveryResourcePrefetches"] == 0
