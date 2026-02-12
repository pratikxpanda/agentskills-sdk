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
