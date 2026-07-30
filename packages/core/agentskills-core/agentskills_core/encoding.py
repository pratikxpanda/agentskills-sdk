"""Safe encoding of skill resource bytes for LLM tool output.

Skill resources (``scripts/``, ``assets/``, ``references/``) may hold
arbitrary files.  Tool interfaces, however, return text.  This module
provides the single conversion used by every integration so the
behaviour cannot drift apart between them.

Text resources pass through unchanged.  Anything that is not valid
UTF-8 is wrapped in a JSON envelope describing the resource and
carrying its bytes as base64, so a binary payload is never silently
mangled into replacement characters.
"""

from __future__ import annotations

import base64
import json
import mimetypes

#: Maximum size of a binary resource that will be inlined as base64.
#: Base64 costs ~1.37 characters per byte, so a large asset would
#: otherwise swamp the model's context window.
DEFAULT_MAX_INLINE_BINARY_BYTES: int = 64 * 1024  # 64 KiB

#: Media type reported when the resource name gives no better hint.
FALLBACK_MEDIA_TYPE: str = "application/octet-stream"


def encode_resource_content(
    name: str,
    data: bytes,
    *,
    max_inline_binary_bytes: int = DEFAULT_MAX_INLINE_BINARY_BYTES,
) -> str:
    """Encode raw resource bytes as text an LLM can consume.

    Valid UTF-8 is returned verbatim.  Everything else is returned as a
    JSON envelope::

        {
          "name": "architecture.png",
          "media_type": "image/png",
          "size_bytes": 20481,
          "encoding": "base64",
          "content": "iVBORw0KGgo..."
        }

    Binaries larger than *max_inline_binary_bytes* use the same envelope
    with ``"encoding": "none"`` and an explanatory ``note`` instead of
    content, so the agent still learns the resource exists and why it
    was withheld.

    Args:
        name: Resource file name, used to infer the media type.
        data: Raw resource bytes as returned by a provider.
        max_inline_binary_bytes: Size ceiling for inlining binary
            content.  Use ``0`` to never inline binaries.

    Returns:
        The decoded text, or a JSON envelope string for binary content.

    Raises:
        ValueError: If *max_inline_binary_bytes* is negative.

    Example::

        text = encode_resource_content("sev.md", await skill.get_reference("sev.md"))
    """
    if max_inline_binary_bytes < 0:
        raise ValueError("max_inline_binary_bytes must not be negative")

    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass

    envelope: dict[str, object] = {
        "name": name,
        "media_type": mimetypes.guess_type(name)[0] or FALLBACK_MEDIA_TYPE,
        "size_bytes": len(data),
    }

    if len(data) > max_inline_binary_bytes:
        envelope["encoding"] = "none"
        envelope["note"] = (
            f"Binary content omitted: {len(data)} bytes exceeds the "
            f"{max_inline_binary_bytes}-byte inline limit. Retrieve this "
            f"resource out of band if you need it."
        )
    else:
        envelope["encoding"] = "base64"
        envelope["content"] = base64.b64encode(data).decode("ascii")

    return json.dumps(envelope)
