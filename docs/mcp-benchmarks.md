---
title: MCP Discovery and Delivery Benchmarks
description: Reproducible synthetic comparisons of native Skills and the retained legacy MCP API.
---

## Run the Benchmark

Use this development checkout with its development dependencies and `mcp==2.2.0`.
Released 0.5.0 packages do not contain the native server. From the repository root:

```bash
poetry run python examples/mcp/benchmark.py --sizes 1 10 100 --repeats 3
git rev-parse HEAD
```

For an isolated environment, install the checkout's core, filesystem, retrieval,
tools, and MCP packages plus `mcp==2.2.0`. Do not mix released SDK packages with
development sources. The benchmark prints JSON to stdout and diagnostic logs to
stderr. Record the source revision alongside the JSON. No model credentials,
external services, user skills, or network listener are used.

Each run creates and removes its own temporary corpus. Catalog sizes are bounded
to 1 through 128, with at most eight sizes and ten repetitions. Each mode has a
60-second sample deadline. CI retains a nine-sample JSON artifact from catalogs
of 1, 10, and 100 skills. Tests assert behavior and counts, not timing thresholds.

## Workloads

The versioned synthetic corpus contains up to four task-specific skills and
uniquely named archive distractors. Each skill has a full `SKILL.md`, a reference,
and a binary file in a nonstandard directory. Repeated body text makes accidental
eager delivery visible. This is a small controlled corpus, not a production dataset.

Native mode constructs complete immutable snapshots, connects an official MCP
client, performs direct lookup before enumeration, and enumerates pages of 25.
It then reads one full `SKILL.md` and one reference through `resources/read`,
verifying their sizes and SHA-256 digests. The binary file remains unread by the
client. The benchmark fails if connection, direct lookup, or enumeration causes
a resource read. A regression test injects such a read to prove that check works.

Legacy mode uses the retained v0.5 catalog/tool API in the same checkout and MCP
runtime. It lists tools, reads the XML catalog and usage instructions, then calls
the metadata, body, and reference tools for the same skill. This is a comparison
with the v0.5-style workflow, not an execution of the exact published v0.5 artifact.
Fast-path inlining, section selection, and vision delivery are disabled.

The native manifest includes metadata and integrity information for every file.
Legacy discovery exposes a catalog plus tool definitions and usage instructions.
Native delivery includes original frontmatter, while the legacy body tool does
not. The workloads serve the same task but are not byte-for-byte equivalent.

## Metrics and Limits

* `selection` measures the existing `LexicalSelector` independently of MCP.
  Four labelled queries and an explicit no-match query report top-one micro
  precision, recall, and empty-result accuracy. Missing task skills in smaller
  catalogs become additional no-match cases. Ranking never filters native
  enumeration or restricts direct lookup. Selection runs once per catalog and
  its result is reused in that catalog's repeated delivery samples.
* `selectionMetadataTokens` estimates native name/description projection costs.
  `catalogEstimatedTokens` estimates the legacy XML catalog. Neither is a model
  bill. All estimates use the SDK's deterministic four-characters-per-token
  heuristic, rounded up. `resultEstimatedTokens` includes full serialized
  results, including manifest digests or encoded content when present.
* `phases` separates connection, discovery, direct lookup, and delivery.
  Middleware counts actual server-observed request methods and compact UTF-8
  result JSON bytes. JSON-RPC envelopes, requests, notifications, transport
  framing, and TLS overhead are excluded. Resource content bytes are decoded
  bytes. Tool text bytes exclude structured-content duplication and are not
  necessarily original file bytes.
* `clientRoundTripMs` measures in-process official-client calls, including
  middleware overhead. It does not measure network latency, model latency,
  host activation, or digest-verification time. Connection requests are counted
  but not timed. `buildMs` separately includes server construction and source
  preparation. Client caching is disabled, servers are fresh per sample, and
  sample order alternates. OS filesystem caches are uncontrolled.
* `sourceSnapshotReadCalls` and `sourceSnapshotReadBytes` count native raw provider
  reads during publication, including the second drift-detection pass. These are
  distinct from client reads. They are not physical disk counters and have no
  equivalent legacy counter in this harness.
* Model calls and model round trips are zero. Tool calls are observed separately.
  The script does not simulate an LLM or infer model costs from tool counts.

## Initial Observations

Measured on 2026-10-06 with Python 3.13.9, MCP 2.2.0, Windows, corpus version 1,
and three repetitions. Times below are medians, rounded to two decimals.

| Skills | Native list JSON bytes | Legacy discovery JSON bytes | Native build ms | Legacy build ms | Native list ms | Legacy discovery ms |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 758 | 6,695 | 60.45 | 20.79 | 0.42 | 2.82 |
| 10 | 6,098 | 7,973 | 430.09 | 64.16 | 0.44 | 6.29 |
| 100 | 59,258 | 20,393 | 3,668.77 | 230.94 | 2.22 | 17.43 |

Native list bytes exclude connection and the independent direct-lookup request.
Legacy discovery bytes cover its three discovery calls. Full JSON output keeps
those phases separate so totals can be reconstructed without hiding extra calls.
All native samples observed zero discovery resource reads, two verified delivery
reads, and no additional source reads after publication. Synthetic precision,
recall, and no-match accuracy were 1.0. Those scores are sanity checks, not
evidence of general selection accuracy.

At 100 skills the complete native manifest costs more discovery bytes than the
legacy catalog workflow. Name/description projection costs roughly 2,310 tokens,
compared with 3,369 for the XML catalog, but the full native manifest is larger.
Do not inject that full manifest into a prompt and claim the projection's cost.
Snapshot preparation is also more expensive than legacy registration. These
measurements expose those trade-offs rather than promising universal speedups.

Production accuracy, cold-disk performance, exact released-artifact comparisons,
remote authenticated deployments, and host/model behavior require separate runs
with representative data and explicit environment records.
