---
title: agentskills-azure
description: Azure-backed providers for Agent Skills with service-specific optional extras.
---

Azure-backed skill providers share this package and use service-specific modules and
optional dependencies. Blob Storage is available through the `blob` extra.
Azure Files SMB shares are available through the `files` extra.

## Install

```bash
pip install "agentskills-azure[blob,files]"
```

Install only `agentskills-azure[blob]` or `agentskills-azure[files]` when you need one service.

## Blob Storage

Read Agent Skills from Azure Blob Storage with the asynchronous Azure SDK. The
provider uses `DefaultAzureCredential` by default, discovers skills from
`SKILL.md` blobs, and preserves original file bytes for complete manifests.

```python
from agentskills_azure.blob import AzureBlobSkillProvider

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

## Azure Files

Use the async FileREST SDK to read skill directories from an SMB share without mounting it:

```python
from agentskills_azure.files import AzureFilesSkillProvider

async with AzureFilesSkillProvider(
    "https://account.file.core.windows.net",
    "skills",
    prefix="published/",
    token_intent="backup",
) as provider:
    skill_ids = await provider.discover()
```

Token authentication requires the explicit `token_intent="backup"` opt-in. FileREST backup
intent bypasses file and directory ACLs, subject to Azure RBAC permissions. Assign the identity
only the required backup-read permissions at the narrowest applicable scope.

Discovery and listing read metadata without downloading file contents. Reads preserve original
bytes, disable automatic decompression, and enforce `max_file_bytes`. Recursive listing is bounded
by `max_files` and `max_depth`. NFS shares and reparse points are rejected.

Both providers close owned clients and default credentials. Caller-supplied async credentials
remain caller-owned. Fake-client conformance tests do not certify a production identity or share
configuration.
