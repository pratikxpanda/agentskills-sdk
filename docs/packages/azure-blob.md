---
title: Azure Blob provider
description: Read Agent Skills from Azure Blob Storage with native Azure credentials.
---

## Usage

Install `agentskills-azure-blob` and grant its Azure identity read access to the
target container. The provider uses `DefaultAzureCredential` unless you pass an
asynchronous credential explicitly.

```python
from agentskills_azure_blob import AzureBlobSkillProvider

async with AzureBlobSkillProvider(
    "https://account.blob.core.windows.net",
    "skills",
    prefix="published/",
) as provider:
    skill_ids = await provider.discover()
```

The provider supports discovery, resource listing, and complete raw-file access.
Reads are bounded by `max_file_bytes`, and canonical paths are returned relative
to each skill directory.

## API Reference

::: agentskills_azure_blob.AzureBlobSkillProvider
    options:
      show_root_heading: true
