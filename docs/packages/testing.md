---
title: Testing Toolkit
description: Provider conformance suites, in-memory providers, and automatic pytest fixtures.
---

Provider conformance suite and in-memory test provider.

```bash
pip install agentskills-testing
```

Installation registers the pytest fixtures automatically. Subclass `ProviderConformanceSuite`
and supply the documented skill/resource fixture contract. The
[package guide](https://github.com/pratikxpanda/agentskills-sdk/blob/main/packages/testing/agentskills-testing/README.md#conformance-suite)
includes a runnable test file, content-limit checks, and in-memory usage. Async application
tests should use `@pytest.mark.asyncio` unless your project explicitly enables auto mode.

::: agentskills_testing
    options:
      show_root_heading: true
