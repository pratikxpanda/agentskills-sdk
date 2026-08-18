"""Tests for resource media classification."""

from __future__ import annotations

import pytest

from agentskills_core import (
    DEFAULT_MAX_INLINE_IMAGE_BYTES,
    RENDERABLE_MEDIA_TYPES,
    classify_resource,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
GIF = b"GIF89a" + b"\x00" * 32
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 32


class TestRenderable:
    @pytest.mark.parametrize(
        ("data", "media_type"),
        [(PNG, "image/png"), (JPEG, "image/jpeg"), (GIF, "image/gif"), (WEBP, "image/webp")],
    )
    def test_the_four_raster_formats_are_renderable(self, data, media_type):
        media = classify_resource("diagram.bin", data)
        assert media.renderable
        assert media.media_type == media_type

    def test_the_renderable_set_is_exactly_those_four(self):
        assert sorted(RENDERABLE_MEDIA_TYPES) == [
            "image/gif",
            "image/jpeg",
            "image/png",
            "image/webp",
        ]

    def test_the_size_is_reported(self):
        assert classify_resource("a.png", PNG).size_bytes == len(PNG)

    def test_an_image_that_decodes_as_utf8_by_coincidence_is_still_an_image(self):
        # A short GIF or WebP header padded with NULs decodes cleanly.
        # Asking "does it decode?" before "what is it?" classified
        # those as text and refused to render them.
        media = classify_resource("tiny.gif", b"GIF89a" + b"\x00" * 8)
        assert not media.is_text
        assert media.renderable


class TestBytesBeatNames:
    def test_a_lying_name_does_not_make_something_renderable(self):
        # Handing a model an image/png block containing a ZIP is an API
        # error, not a worse answer.
        media = classify_resource("screenshot.png", b"PK\x03\x04not a png at all \xff")
        assert not media.renderable

    def test_a_wrong_extension_does_not_hide_a_real_image(self):
        media = classify_resource("screenshot.dat", PNG)
        assert media.renderable
        assert media.media_type == "image/png"

    def test_the_name_is_only_consulted_when_bytes_say_nothing(self):
        media = classify_resource("report.pdf", b"\x00\x01\x02\xff")
        assert media.media_type == "application/pdf"
        assert not media.renderable

    def test_an_unidentifiable_binary_falls_back(self):
        media = classify_resource("mystery", b"\x00\x01\x02\xff")
        assert media.media_type == "application/octet-stream"
        assert not media.renderable


class TestNotRenderable:
    def test_text_is_not_renderable(self):
        media = classify_resource("runbook.md", b"# Runbook\n")
        assert media.is_text
        assert not media.renderable

    def test_svg_stays_text(self):
        # It already arrives readable, and rasterising it would replace
        # something the model can reason about with something it can
        # only look at.
        media = classify_resource("diagram.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>")
        assert media.is_text
        assert not media.renderable

    def test_pdf_is_not_rendered_natively(self):
        # Some models read it and others reject it, and guessing wrong
        # is an API error.
        media = classify_resource("spec.pdf", b"%PDF-1.7\n\xff\xfe binary")
        assert media.media_type == "application/pdf"
        assert not media.renderable

    def test_an_oversized_image_is_described_rather_than_shown(self):
        big = PNG + b"\x00" * DEFAULT_MAX_INLINE_IMAGE_BYTES
        media = classify_resource("huge.png", big)
        assert media.media_type == "image/png"
        assert not media.renderable

    def test_the_image_ceiling_is_configurable(self):
        assert not classify_resource("a.png", PNG, max_inline_image_bytes=8).renderable
        assert classify_resource("a.png", PNG, max_inline_image_bytes=0).renderable is False

    def test_a_negative_ceiling_is_rejected(self):
        with pytest.raises(ValueError, match="must not be negative"):
            classify_resource("a.png", PNG, max_inline_image_bytes=-1)


class TestCeilingRationale:
    def test_the_image_ceiling_is_far_larger_than_the_binary_one(self):
        # The 64 KiB binary cap tracks tokens, because base64 in a text
        # field is billed per byte. A native image is billed by tile
        # count, so most real screenshots used to come back as a stub
        # saying they were too large.
        from agentskills_core import DEFAULT_MAX_INLINE_BINARY_BYTES

        assert DEFAULT_MAX_INLINE_IMAGE_BYTES > DEFAULT_MAX_INLINE_BINARY_BYTES * 50

    def test_a_typical_screenshot_now_fits(self):
        assert DEFAULT_MAX_INLINE_IMAGE_BYTES >= 2 * 1024 * 1024
