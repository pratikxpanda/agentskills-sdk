---
title: agentskills-azure-blob
description: Azure Blob Storage provider for Agent Skills
---

Read Agent Skills from Azure Blob Storage with the asynchronous Azure SDK. The
provider uses `DefaultAzureCredential` by default, discovers skills from
`SKILL.md` blobs, and preserves original file bytes for complete manifests.

```python
from agentskills_azure_blob import AzureBlobSkillProvider

async with AzureBlobSkillProvider(
    "https://account.blob.core.windows.net",
    "skills",
    prefix="published/",
) as provider:
    skill_ids = await provider.discover()
```

Pass an asynchronous Azure credential to `credential` when the application
manages authentication itself. Assign the identity only the blob permissions
needed to read the selected container.
