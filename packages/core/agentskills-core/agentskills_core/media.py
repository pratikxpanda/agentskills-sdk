"""Decide whether a resource is something a model can actually see.

:func:`~agentskills_core.encode_resource_content` makes binary
resources *safe* -- base64 in a JSON envelope, never silently mangled.
It does not make them *useful*.  For a PNG the model receives a
description of an image rather than an image: base64 inflates the
payload by about a third, tokenizes as unstructured noise, and conveys
nothing.  A diagram can cost thousands of tokens to say exactly zero.

This module is the branch above that fallback.  Given a name and its
bytes it reports a media type and whether the resource is a candidate
for native delivery, so the three integrations cannot drift on what
counts as an image.  What to *do* with that answer -- an MCP
``ImageContent``, a LangChain content block, an Agent Framework data
content -- stays in each integration, because only the shapes differ.

Detection is by magic bytes first and file name second.  A name is a
claim and bytes are evidence; handing a model an ``image/png`` block
containing a ZIP is an API error, not a degradation.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass

from agentskills_core.encoding import FALLBACK_MEDIA_TYPE

#: Raster formats every vision-capable model in wide use accepts.
#:
#: PDF is deliberately absent: some models read it natively and others
#: reject it, and guessing wrong is an API error rather than a worse
#: answer.  SVG is absent for the opposite reason -- it is text, so it
#: already arrives readable through the normal path, and rasterising it
#: would replace something the model can reason about with something it
#: can only look at.
RENDERABLE_MEDIA_TYPES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
    }
)

#: Size ceiling for an image handed over natively.
#:
#: The 64 KiB binary cap exists because base64 in a text field maps
#: directly to tokens, where every byte is billed.  A native image is
#: billed by tile count, so that number is both far too small for a
#: real screenshot -- most exceed it, and used to come back as a stub
#: saying so -- and irrelevant to how it is charged.  5 MiB is the
#: lowest per-image limit among the major vision APIs, so an image that
#: fits here fits everywhere.
DEFAULT_MAX_INLINE_IMAGE_BYTES: int = 5 * 1024 * 1024  # 5 MiB

#: Leading bytes that identify a renderable format.  WebP is checked
#: separately because its signature is split across two ranges.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


@dataclass(frozen=True)
class ResourceMedia:
    """What a resource is, and whether a model can be shown it."""

    name: str
    """The resource file name, as requested."""

    media_type: str
    """Detected media type, or ``application/octet-stream``."""

    size_bytes: int
    """Size of the resource."""

    is_text: bool
    """Whether this should be treated as text needing no special handling.

    False for anything whose leading bytes identify a renderable image,
    whatever those bytes happen to decode to -- a file that starts
    ``GIF89a`` is a GIF, and a small one can decode as UTF-8 by
    coincidence.
    """

    renderable: bool
    """Whether this should be delivered as a native content block.

    False for text, for unrecognised binaries, and for images past
    :data:`DEFAULT_MAX_INLINE_IMAGE_BYTES` -- in every case the JSON
    envelope remains correct, so a caller can ignore this field and
    lose nothing but the improvement.
    """


def _sniff(data: bytes) -> str | None:
    """Identify a renderable format from its leading bytes."""
    for signature, media_type in _MAGIC:
        if data.startswith(signature):
            return media_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def classify_resource(
    name: str,
    data: bytes,
    *,
    max_inline_image_bytes: int = DEFAULT_MAX_INLINE_IMAGE_BYTES,
) -> ResourceMedia:
    """Report what *data* is and whether it can be shown to a model.

    Args:
        name: Resource file name.  Used only when the bytes are not
            self-identifying, since a name is a claim and bytes are
            evidence.
        data: Raw resource bytes as returned by a provider.
        max_inline_image_bytes: Ceiling above which an image is
            described rather than shown.  Use ``0`` to never render.

    Returns:
        A :class:`ResourceMedia`.

    Raises:
        ValueError: If *max_inline_image_bytes* is negative.
    """
    if max_inline_image_bytes < 0:
        raise ValueError("max_inline_image_bytes must not be negative")

    # Sniff first. A file whose leading bytes identify a GIF is a GIF,
    # and a short one can decode as UTF-8 by coincidence -- asking
    # "does it decode?" before "what is it?" would call that text.
    sniffed = _sniff(data)
    if sniffed is not None:
        is_text = False
    else:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            is_text = False
        else:
            is_text = True

    media_type = sniffed or mimetypes.guess_type(name)[0] or FALLBACK_MEDIA_TYPE

    renderable = (
        sniffed is not None
        and sniffed in RENDERABLE_MEDIA_TYPES
        and len(data) <= max_inline_image_bytes
    )
    return ResourceMedia(
        name=name,
        media_type=media_type,
        size_bytes=len(data),
        is_text=is_text,
        renderable=renderable,
    )
