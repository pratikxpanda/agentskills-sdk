"""Tests for splitting a skill body into addressable sections."""

from __future__ import annotations

from agentskills_core import (
    PREAMBLE_TITLE,
    WHOLE_BODY_CHEAPER_TOKENS,
    estimate_tokens,
    outline_of,
    split_sections,
)


class TestSplitSections:
    def test_text_with_no_headings_is_one_preamble(self):
        [section] = split_sections("just prose\nover two lines")

        assert section.title == PREAMBLE_TITLE
        assert section.level == 0

    def test_empty_body_produces_nothing(self):
        assert split_sections("") == []

    def test_whitespace_before_a_heading_is_not_a_section(self):
        [section] = split_sections("\n\n# Title\n\nbody")

        assert section.title == "Title"

    def test_headings_become_sections_in_order(self):
        sections = split_sections("# One\n\na\n\n## Two\n\nb\n\n## Three\n\nc")

        assert [(s.title, s.level) for s in sections] == [("One", 1), ("Two", 2), ("Three", 2)]

    def test_a_nested_section_is_not_also_counted_in_its_parent(self):
        body = "## Parent\n\nparent text\n\n### Child\n\nchild text"
        parent, child = split_sections(body)

        assert "child text" not in parent.text
        assert "child text" in child.text

    def test_the_parts_sum_to_the_whole(self):
        body = "intro\n\n# One\n\na\n\n## Two\n\nb\n"
        sections = split_sections(body)

        # Rejoining is exact except for the trailing newline splitlines drops.
        assert "\n".join(section.text for section in sections) == body.rstrip("\n")

    def test_a_hash_inside_a_fence_is_a_comment_not_a_heading(self):
        body = "# Real\n\n```bash\n# not a heading\necho hi\n```\n\ntail"
        [section] = split_sections(body)

        assert section.title == "Real"
        assert "not a heading" in section.text

    def test_tilde_fences_are_honoured_too(self):
        body = "# Real\n\n~~~\n# not a heading\n~~~\n"
        [section] = split_sections(body)

        assert section.title == "Real"

    def test_a_fence_of_a_different_character_does_not_close_one(self):
        body = "# Real\n\n```\n~~~\n# still inside\n```\n\n# After"
        real, after = split_sections(body)

        assert "still inside" in real.text
        assert after.title == "After"

    def test_closing_hashes_are_stripped_from_the_title(self):
        [section] = split_sections("## Title ##\n\nbody")

        assert section.title == "Title"

    def test_a_hash_without_a_space_is_not_a_heading(self):
        [section] = split_sections("#hashtag\n\nbody")

        assert section.title == PREAMBLE_TITLE

    def test_seven_hashes_are_not_a_heading(self):
        [section] = split_sections("####### too deep\n\nbody")

        assert section.title == PREAMBLE_TITLE

    def test_an_empty_section_still_counts(self):
        # A heading with nothing under it still charges for its own line.
        sections = split_sections("# One\n# Two\n")

        assert [s.title for s in sections] == ["One", "Two"]


class TestSectionKeys:
    def test_a_title_becomes_a_slug(self):
        [section] = split_sections("## Rolling Back a Deploy\n\nbody")

        assert section.key == "rolling-back-a-deploy"

    def test_punctuation_and_case_are_normalised(self):
        [section] = split_sections("## Step 1: *Triage* (fast!)\n\nbody")

        assert section.key == "step-1-triage-fast"

    def test_duplicate_titles_get_ordinals(self):
        sections = split_sections("## Setup\n\na\n\n## Setup\n\nb\n\n## Setup\n\nc")

        assert [s.key for s in sections] == ["setup", "setup-2", "setup-3"]

    def test_duplicates_at_different_levels_still_collide(self):
        # Addressing is flat, so depth does not disambiguate.
        sections = split_sections("## Setup\n\na\n\n### Setup\n\nb")

        assert [s.key for s in sections] == ["setup", "setup-2"]

    def test_the_preamble_has_a_stable_key(self):
        [section] = split_sections("prose with no heading")

        assert section.key == "preamble"

    def test_a_title_with_no_usable_characters_falls_back(self):
        [section] = split_sections("## ---\n\nbody")

        assert section.key == "section"


class TestEstimateTokens:
    def test_empty_text_costs_nothing(self):
        assert estimate_tokens("") == 0

    def test_a_partial_token_rounds_up(self):
        assert estimate_tokens("ab") == 1

    def test_four_characters_is_one_token(self):
        assert estimate_tokens("abcd") == 1
        assert estimate_tokens("abcde") == 2


class TestOutline:
    def test_an_empty_body_says_so(self):
        outline = outline_of("alpha", "")

        assert outline.sections == []
        assert outline.total_tokens == 0
        assert "empty body" in outline.render()

    def test_the_outline_lists_every_section_with_its_key(self):
        outline = outline_of("alpha", "# One\n\na\n\n## Two\n\nb")
        rendered = outline.render()

        assert [ref.key for ref in outline.sections] == ["one", "two"]
        assert "- one (~" in rendered
        assert "Two" in rendered

    def test_depth_is_shown_as_indentation(self):
        outline = outline_of("alpha", "# One\n\na\n\n## Two\n\nb")

        assert "\n- one " in outline.render()
        assert "\n  - two " in outline.render()

    def test_the_total_is_the_whole_body_not_the_sum_of_the_parts(self):
        body = "# One\n\na\n\n## Two\n\nb"
        outline = outline_of("alpha", body)

        # Per-section figures each round up, so summing them overstates
        # the body.  The total is what a get_skill_body call would cost.
        assert outline.total_tokens == estimate_tokens(body)
        assert outline.total_tokens <= sum(ref.tokens for ref in outline.sections)

    def test_a_small_body_is_cheaper_read_whole(self):
        outline = outline_of("alpha", "# One\n\nshort")

        assert outline.whole_body_is_cheaper
        assert "Call get_skill_body instead" in outline.render()

    def test_a_large_body_is_worth_sectioning(self):
        body = "# One\n\n" + ("word " * (WHOLE_BODY_CHEAPER_TOKENS * 2))
        outline = outline_of("alpha", body)

        assert not outline.whole_body_is_cheaper
        rendered = outline.render()
        assert "get_skill_section" in rendered
        assert "Sections do not nest" in rendered
