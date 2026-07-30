"""Tests for encode_resource_content."""

import base64
import json

import pytest

from agentskills_core import DEFAULT_MAX_INLINE_BINARY_BYTES, encode_resource_content

PNG_HEADER = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"


class TestTextPassthrough:
    def test_ascii_returned_verbatim(self):
        assert encode_resource_content("run.sh", b"#!/bin/bash\necho hi") == (
            "#!/bin/bash\necho hi"
        )

    def test_non_ascii_utf8_preserved(self):
        text = "# Sévérité\n\nDéjà vu — naïve café 日本語 🚨"
        assert encode_resource_content("sev.md", text.encode("utf-8")) == text

    def test_empty_resource(self):
        assert encode_resource_content("empty.txt", b"") == ""

    def test_valid_utf8_containing_null_byte_is_intact(self):
        """A null byte does not by itself make content binary."""
        raw = b"line one\x00line two"
        assert encode_resource_content("odd.txt", raw) == "line one\x00line two"


class TestBinaryEnvelope:
    def test_png_round_trips(self):
        result = json.loads(encode_resource_content("architecture.png", PNG_HEADER))
        assert result["encoding"] == "base64"
        assert base64.b64decode(result["content"]) == PNG_HEADER

    def test_no_replacement_characters(self):
        result = encode_resource_content("blob.bin", b"\x80\x81\xfe\xff")
        assert "\ufffd" not in result

    def test_media_type_inferred_from_name(self):
        result = json.loads(encode_resource_content("architecture.png", PNG_HEADER))
        assert result["media_type"] == "image/png"

    def test_media_type_falls_back_for_unknown_extension(self):
        result = json.loads(encode_resource_content("blob.zzz", b"\xff\xfe\xfd"))
        assert result["media_type"] == "application/octet-stream"

    def test_envelope_reports_size_and_name(self):
        result = json.loads(encode_resource_content("blob.bin", b"\xff" * 7))
        assert result["name"] == "blob.bin"
        assert result["size_bytes"] == 7


class TestSizeCeiling:
    def test_oversized_binary_is_not_inlined(self):
        data = b"\xff" * 200
        result = json.loads(encode_resource_content("big.bin", data, max_inline_binary_bytes=100))
        assert result["encoding"] == "none"
        assert "content" not in result
        assert result["size_bytes"] == 200
        assert "200" in result["note"]

    def test_content_is_never_truncated(self):
        """Oversized binaries are omitted whole, not cut short."""
        data = b"\xff" * 200
        result = json.loads(encode_resource_content("big.bin", data, max_inline_binary_bytes=100))
        assert base64.b64encode(data).decode("ascii") not in json.dumps(result)

    def test_boundary_is_inclusive(self):
        data = b"\xff" * 100
        result = json.loads(encode_resource_content("edge.bin", data, max_inline_binary_bytes=100))
        assert result["encoding"] == "base64"

    def test_zero_ceiling_never_inlines(self):
        result = json.loads(encode_resource_content("any.bin", b"\xff", max_inline_binary_bytes=0))
        assert result["encoding"] == "none"

    def test_large_text_is_unaffected_by_the_ceiling(self):
        """The ceiling applies to binaries only."""
        text = "x" * (DEFAULT_MAX_INLINE_BINARY_BYTES + 1)
        assert encode_resource_content("big.md", text.encode()) == text

    def test_negative_ceiling_rejected(self):
        with pytest.raises(ValueError, match="must not be negative"):
            encode_resource_content("any.bin", b"\xff", max_inline_binary_bytes=-1)
