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
Each skill is a directory beneath the configured prefix, for example
`published/incident-response/SKILL.md`. Upload valid skill content before running the example.
Authenticate for local development with `az login`, or configure a managed identity in Azure.
Replace the account URL and container name with yours.

```python
import asyncio

from agentskills_azure.blob import AzureBlobSkillProvider


async def main() -> None:
    async with AzureBlobSkillProvider(
        "https://account.blob.core.windows.net", "skills", prefix="published/"
    ) as provider:
        print(await provider.discover())
        print(await provider.get_body("incident-response"))


asyncio.run(main())
```

Pass an asynchronous Azure credential to `credential` when the application
manages authentication itself. Assign the identity only the blob permissions
needed to read the selected container.

## Azure Files

Use the async FileREST SDK to read skill directories from an SMB share without mounting it:
create the share and upload `published/incident-response/SKILL.md` first. The same Azure
credential-chain setup applies, but FileREST token authentication has different permissions.

```python
import asyncio

from agentskills_azure.files import AzureFilesSkillProvider


async def main() -> None:
    async with AzureFilesSkillProvider(
        "https://account.file.core.windows.net",
        "skills",
        prefix="published/",
        token_intent="backup",
    ) as provider:
        print(await provider.discover())
        print(await provider.read_file("incident-response", "SKILL.md"))


asyncio.run(main())
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
