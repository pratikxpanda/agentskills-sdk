"""Tests for agentskills_core.parsing."""

from agentskills_core.parsing import split_frontmatter


class TestSplitFrontmatter:
    def test_normal_frontmatter(self):
        raw = "---\nname: test\ndescription: A test skill.\n---\n# Body"
        meta, body = split_frontmatter(raw)
        assert meta["name"] == "test"
        assert meta["description"] == "A test skill."
        assert body == "# Body"

    def test_no_frontmatter(self):
        raw = "# Just body content"
        meta, body = split_frontmatter(raw)
        assert meta == {}
        assert body == raw

    def test_unclosed_frontmatter(self):
        raw = "---\nname: test\n# Body without closing delimiter"
        meta, body = split_frontmatter(raw)
        assert meta == {}
        assert body == raw

    def test_malformed_yaml(self):
        raw = "---\n: :\ninvalid yaml{{{\n---\n# Body"
        meta, body = split_frontmatter(raw)
        assert meta == {}
        assert body == raw

    def test_empty_frontmatter(self):
        raw = "---\n---\n# Body"
        meta, body = split_frontmatter(raw)
        assert meta == {}
        assert body == "# Body"

    def test_empty_string(self):
        meta, body = split_frontmatter("")
        assert meta == {}
        assert body == ""

    def test_oversized_frontmatter_rejected(self):
        """Frontmatter larger than MAX_FRONTMATTER_BYTES is treated as no frontmatter."""
        from agentskills_core.parsing import MAX_FRONTMATTER_BYTES

        huge_fm = "---\ndata: " + "x" * (MAX_FRONTMATTER_BYTES + 100) + "\n---\n# Body"
        meta, body = split_frontmatter(huge_fm)
        assert meta == {}
        assert body == huge_fm

    def test_frontmatter_exactly_at_max_size_passes(self):
        """Frontmatter exactly at MAX_FRONTMATTER_BYTES should be accepted."""
        from agentskills_core.parsing import MAX_FRONTMATTER_BYTES

        # The key "data: " is 6 bytes; calculate padding to reach exactly the limit.
        prefix = "data: "
        padding_len = MAX_FRONTMATTER_BYTES - len(prefix.encode("utf-8"))
        fm_text = prefix + "x" * padding_len
        raw = "---\n" + fm_text + "\n---\n# Body"
        meta, body = split_frontmatter(raw)
        assert meta == {"data": "x" * padding_len}
        assert body == "# Body"

    def test_windows_line_endings(self):
        """Frontmatter with \\r\\n line endings should be parsed correctly."""
        raw = "---\r\nname: test\r\ndescription: Desc.\r\n---\r\n# Body"
        meta, _body = split_frontmatter(raw)
        assert meta["name"] == "test"
        assert meta["description"] == "Desc."

    def test_triple_dash_inside_yaml_value(self):
        """A '---' on its own line always terminates the frontmatter block.

        The regex-based parser does not parse YAML quoting, so a bare
        ``---`` on a line inside a value still closes the block.  When
        this produces malformed YAML the parser returns an empty dict.
        This test documents the current behaviour rather than an ideal one.
        """
        raw = '---\nname: test\nnote: "has\n---\ninside"\n---\n# Body'
        meta, _body = split_frontmatter(raw)
        # Frontmatter becomes 'name: test\nnote: "has' — malformed YAML
        # Parser returns empty dict on malformed YAML
        assert meta == {}

    def test_unicode_frontmatter(self):
        """Unicode content in frontmatter should be parsed correctly."""
        raw = (
            "---\nname: test\n"
            "description: \u00c9l\u00e8ve d'\u00e9cole \u2014 \u65e5\u672c\u8a9e\n"
            "---\n# Body"
        )
        meta, _body = split_frontmatter(raw)
        assert meta["name"] == "test"
        assert "\u00c9l\u00e8ve" in meta["description"]
        assert "\u65e5\u672c\u8a9e" in meta["description"]

    def test_whitespace_only_frontmatter(self):
        """Frontmatter with only whitespace between delimiters yields empty dict."""
        raw = "---\n   \n   \n---\n# Body"
        meta, body = split_frontmatter(raw)
        assert meta == {}
        assert body == "# Body"
