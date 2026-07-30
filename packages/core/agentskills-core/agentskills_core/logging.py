"""Logging helpers shared by every ``agentskills`` package.

The SDK logs under a single ``agentskills.*`` namespace so that a host
application can raise or silence the whole library with one call::

    logging.getLogger("agentskills").setLevel(logging.DEBUG)

Per the standard library's guidance for libraries, a
:class:`~logging.NullHandler` is attached to the namespace root and no
other handler is ever installed: output is entirely the host's decision.

Levels used across the SDK:

* ``DEBUG`` -- fetch, parse and cache events.  Per-request volume.
* ``INFO`` -- registration outcomes.  Once per skill.
* ``WARNING`` -- degraded but recovered behaviour, such as a retried
  request or an unrecognised metadata key.

Failures that raise are not logged.  An exception that is both logged
and raised gets reported twice, and the caller loses the ability to
decide whether it mattered.
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

#: Root of the SDK logger namespace.
LOGGER_NAMESPACE: str = "agentskills"

#: Placeholder substituted for credential-bearing URL components.
REDACTED: str = "[redacted]"

logging.getLogger(LOGGER_NAMESPACE).addHandler(logging.NullHandler())


def get_logger(module: str) -> logging.Logger:
    """Return the ``agentskills.*`` logger for a module.

    Pass ``__name__``.  The distribution prefix is rewritten so that
    ``agentskills_http.static`` logs as ``agentskills.http.static``,
    giving every package a common namespace root while keeping the
    logger name tied to the module it lives in.

    Args:
        module: The calling module's ``__name__``.

    Returns:
        A configured :class:`~logging.Logger`.
    """
    suffix = module.removeprefix("agentskills_")
    return logging.getLogger(f"{LOGGER_NAMESPACE}.{suffix}")


def redact_url(url: str, *, relative_to: str | None = None) -> str:
    """Strip credentials from *url* so it is safe to log or raise.

    Query strings, fragments and userinfo are dropped, because that is
    where credentials actually live: SAS tokens, signed-URL signatures
    and basic-auth passwords.  When *relative_to* is given the scheme
    and host are dropped too, leaving only the path beneath that base --
    a host is recoverable from configuration, but a full path sitting in
    a shared log is not something the operator can take back.

    Args:
        url: The URL to sanitise.
        relative_to: Base URL to express the result relative to.

    Returns:
        A string safe to place in a log record or an exception message.
    """
    if relative_to is not None:
        path = urlsplit(url.removeprefix(relative_to.rstrip("/"))).path
        if path:
            return path

    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    safe = f"{parts.scheme}://{host}{parts.path}" if parts.scheme else parts.path
    if parts.query or parts.fragment:
        safe = f"{safe}?{REDACTED}"
    return safe or REDACTED
