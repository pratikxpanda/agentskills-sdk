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
- **Assessment** within 7 days - we will confirm whether the issue is
  accepted and provide an estimated timeline for a fix.
- **Fix and disclosure** - once a fix is ready, we will release a patch
  version and publish a GitHub Security Advisory crediting you (unless
  you prefer to remain anonymous).

## Threat Model

Agent Skills are **equivalent to executable code**. A skill's body,
references, scripts, and assets are loaded from the configured source
and injected into an LLM agent's context verbatim. A malicious skill
author can embed prompt-injection payloads or misleading instructions.

**Only load skills from sources you trust.**

### Security controls in this SDK

- **Input validation** - Skill IDs and resource names are validated
  against a safe-character pattern to prevent path-traversal and
  injection attacks.
- **TLS warnings** - The HTTP provider warns when `base_url` uses
  unencrypted HTTP and supports a `require_tls` flag.
- **Redirect protection** - The internally-created HTTP client does not
  follow redirects by default.
- **Timeouts** - Default 30-second timeout on HTTP requests.
- **Response size limits** - Responses and files exceeding 10 MB are
  rejected by default.
- **Frontmatter size limits** - YAML frontmatter blocks exceeding
  256 KB are rejected.
- **Safe XML generation** - Catalog XML is built with
  `xml.etree.ElementTree`, not string concatenation.
- **Path-traversal protection** - The filesystem provider validates
  that resolved paths stay within the skill root directory.
