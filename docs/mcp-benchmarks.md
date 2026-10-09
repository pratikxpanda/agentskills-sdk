---
title: MCP Benchmarks
description: Reproducible native Skills discovery, verification, and delivery measurements.
---

## Run

From a development checkout with MCP 2.2.0 and the workspace dependencies:

```bash
python examples/mcp/benchmark.py --sizes 1 10 100 --repeats 3
```

The benchmark creates bounded synthetic skills in a temporary directory. It uses
the official MCP client in-process, with no LLM calls or external transport.
Catalog sizes are limited to 1-128, at most eight sizes, and 1-10 repetitions.

## Measurements

Schema version 2 contains only native measurements. The previous legacy comparison
and its recorded results remain in the
[v0.6.0 benchmark](https://github.com/pratikxpanda/agentskills-sdk/blob/v0.6.0/docs/mcp-benchmarks.md).

- Lexical top-one precision, recall, and explicit no-match cases, separate from discovery
- Direct `skills/get` before enumeration and paginated `skills/list`
- Zero client resource reads during connection, lookup, and discovery
- Two progressive file reads, checked against manifest sizes and SHA-256 digests
- Source snapshot read counts and bytes, separate from client resource reads
- Compact result JSON bytes, heuristic token estimates, request counts, and timings

Each repetition constructs a fresh server with client caching disabled. Source
capture reads complete files to establish coherent immutable snapshots. This
server-side work is not client prefetch. Discovery returns metadata and manifests,
not file contents. A request observer fails the benchmark if discovery reads files.

## Limits

Synthetic lexical scores do not establish production retrieval accuracy. Token
estimates are character heuristics, not model-tokenizer counts. Timings include
instrumentation and uncontrolled OS filesystem caching, not network latency.
Byte counts exclude JSON-RPC and transport framing. No measurement establishes
host activation, approval, model effectiveness, or production deployment security.