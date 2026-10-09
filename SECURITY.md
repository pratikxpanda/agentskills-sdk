# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it
responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, please use one of the following methods:

1. **GitHub Security Advisories** (preferred): Navigate to the
   [Security Advisories](https://github.com/pratikxpanda/agentskills-sdk/security/advisories/new)
   page and create a new advisory.
2. **Email**: Send a detailed report to the repository maintainers via
   the email address listed in their GitHub profile.

### What to include

- A description of the vulnerability and its impact.
- Steps to reproduce the issue.
- Any relevant logs, screenshots, or proof-of-concept code.
- Suggested fix, if you have one.

### What to expect

- **Acknowledgement** within 48 hours.
- **Assessment** within 7 days: we will confirm whether the issue is
  accepted and provide an estimated timeline for a fix.
- **Fix and disclosure**: once a fix is ready, we will release a patch
  version and publish a GitHub Security Advisory crediting you (unless
  you prefer to remain anonymous).

## Threat Model

Agent Skills are **equivalent to executable code**. A skill's body,
references, scripts, and assets are loaded from the configured source
and injected into an LLM agent's context verbatim. A malicious skill
author can embed prompt-injection payloads or misleading instructions.

**Only load skills from sources you trust.**

A matching digest proves that a manifest and the bytes it describes are
consistent. It does not prove who wrote them or that they are safe. The SDK
does not execute scripts, grant `allowed-tools`, approve nested skills, or
sandbox a host. Those duties belong to the host application.

### Security controls in this SDK

- **Input validation**: Skill IDs and resource names are validated
  against a safe-character pattern to prevent path-traversal and
  injection attacks.
- **Public-network-only HTTP by default**: The HTTP provider resolves DNS
  at connection time, rejects private, loopback, link-local, multicast, and
  reserved answers, and connects to the validated IP. Internal hosts and
  caller-supplied clients need an explicit `allow_private_network=True`.
- **Redirects rejected**: The HTTP provider never follows redirects and does
  not inherit environment proxies.
- **TLS controls**: The HTTP provider warns on unencrypted `http://` URLs
  and supports `require_tls`.
- **Credential hygiene**: `base_url` rejects embedded credentials, query
  strings, and fragments. Errors and logs carry only redacted paths, never
  headers, hosts, or query strings.
- **Timeouts and size limits**: 30-second default request timeout, 10 MB
  default response and file limits, 256 KB frontmatter limit, and the Skills
  extension limits of 512 files and 16 MiB per skill.
- **Immutable snapshots**: Native delivery captures complete file sets and
  rejects ordinary source drift during capture.
- **Optional publisher verification**: Detached Ed25519 signatures bind a
  configured key, origin, skill ID, version, and every file. Invalid proofs,
  unknown keys, and pin mismatches fail closed.
- **Content policy**: Trusted reject, redact, and annotate hooks and an
  explicit token limit run before manifests are built.
- **Authenticated remote HTTP**: `secure_http_app` requires deployment-supplied
  MCP authorization and explicit host and origin allowlists.
- **Bounded stale serving**: Off by default. When enabled it serves only a
  previously verified snapshot during a provider outage and never after a
  known change, removal, revoked key, or verification failure.
- **Safe XML generation**: Catalog XML is built with
  `xml.etree.ElementTree`, not string concatenation.
- **Path-traversal protection**: The filesystem provider validates
  that resolved paths stay within the skill root directory.

See the [trust and operability guide](https://github.com/pratikxpanda/agentskills-sdk/blob/main/docs/trust-and-operability.md)
for contracts, limits, and deployment responsibilities.
