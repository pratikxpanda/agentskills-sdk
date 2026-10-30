---
title: Azure Providers
description: Azure-backed skill providers with service-specific optional dependencies.
---

The `agentskills-azure` package groups Azure-backed providers under the `agentskills_azure`
namespace. Each service has its own module and optional SDK dependencies.

## Blob Storage

```bash
pip install "agentskills-azure[blob]"
```

Grant the provider's Azure identity read access to the
target container. The provider uses `DefaultAzureCredential` unless you pass an
asynchronous credential explicitly.

The [Blob quick start](https://github.com/pratikxpanda/agentskills-sdk/blob/main/packages/providers/agentskills-azure/README.md#blob-storage)
shows the required uploaded directory layout, authentication setup, and complete async usage.

The provider supports discovery, resource listing, and complete raw-file access.
Reads are bounded by `max_file_bytes`, and canonical paths are returned relative
to each skill directory.

## Azure Files

```bash
pip install "agentskills-azure[files]"
```

The [Files quick start](https://github.com/pratikxpanda/agentskills-sdk/blob/main/packages/providers/agentskills-azure/README.md#azure-files)
shows the SMB directory layout and complete async usage with explicit backup intent.

The provider uses async FileREST access to SMB shares. Token credentials require the explicit
`token_intent="backup"` opt-in, which bypasses file and directory ACLs subject to Azure RBAC.
Provision the required backup-read permissions at the narrowest applicable scope.

Directory discovery and recursive listing do not download file contents. Downloads preserve raw
bytes and enforce `max_file_bytes`. Use `max_files` and `max_depth` to bound traversal. NFS shares,
unsafe paths, and reparse points are rejected. The provider closes its own default credential
but leaves injected async credentials open.

## API Reference

::: agentskills_azure.blob.AzureBlobSkillProvider
    options:
      show_root_heading: true

::: agentskills_azure.files.AzureFilesSkillProvider
        options:
            show_root_heading: true
