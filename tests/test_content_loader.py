"""
test_content_loader - TDD tests for the content loader.

Verifies loading .txt files into a namespace with correct format detection,
include resolution, and error handling.
"""

import logging
import pytest
from pathlib import Path
from content.loader import load_content


@pytest.fixture
def content_dir(tmp_path):
    """Create a temporary directory for content files."""
    return tmp_path


class TestPlainString:
    def test_load_plain_string(self, content_dir):
        (content_dir / "greeting.txt").write_text("שלום עולם", encoding="utf-8")
        ns = load_content(content_dir, logging.getLogger("test"))
        assert ns.GREETING == "שלום עולם"

    def test_preserves_content_exactly(self, content_dir):
        (content_dir / "msg.txt").write_text("hello\n", encoding="utf-8")
        ns = load_content(content_dir, logging.getLogger("test"))
        assert ns.MSG == "hello\n"

    def test_preserves_leading_newlines(self, content_dir):
        (content_dir / "msg.txt").write_text("\n\nhello", encoding="utf-8")
        ns = load_content(content_dir, logging.getLogger("test"))
        assert ns.MSG == "\n\nhello"

    def test_placeholders_survive(self, content_dir):
        (content_dir / "hello.txt").write_text("שלום, {name}!", encoding="utf-8")
        ns = load_content(content_dir, logging.getLogger("test"))
        assert ns.HELLO.format(name="שי") == "שלום, שי!"

    def test_format_placeholder_with_format_spec(self, content_dir):
        (content_dir / "cal.txt").write_text("{calories:,} קלוריות", encoding="utf-8")
        ns = load_content(content_dir, logging.getLogger("test"))
        assert ns.CAL.format(calories=1900) == "1,900 קלוריות"


class TestListFormat:
    def test_splits_on_separator(self, content_dir):
        (content_dir / "prompts.txt").write_text(
            "אחד\n---\nשתיים\n---\nשלוש", encoding="utf-8"
        )
        ns = load_content(content_dir, logging.getLogger("test"))
        assert isinstance(ns.PROMPTS, list)
        assert len(ns.PROMPTS) == 3

    def test_strips_each_variant(self, content_dir):
        (content_dir / "items.txt").write_text(
            "  first  \n---\n  second  ", encoding="utf-8"
        )
        ns = load_content(content_dir, logging.getLogger("test"))
        assert ns.ITEMS == ["first", "second"]

    def test_list_with_placeholders(self, content_dir):
        (content_dir / "pool.txt").write_text(
            "שלום {habit}\n---\nביי {habit}", encoding="utf-8"
        )
        ns = load_content(content_dir, logging.getLogger("test"))
        assert ns.POOL[0].format(habit="שינה") == "שלום שינה"

    def test_five_variants(self, content_dir):
        variants = "\n---\n".join([f"variant {i}" for i in range(5)])
        (content_dir / "five.txt").write_text(variants, encoding="utf-8")
        ns = load_content(content_dir, logging.getLogger("test"))
        assert len(ns.FIVE) == 5

    def test_multiline_variants(self, content_dir):
        (content_dir / "multi.txt").write_text(
            "line1\nline2\n---\nline3\nline4", encoding="utf-8"
        )
        ns = load_content(content_dir, logging.getLogger("test"))
        assert ns.MULTI[0] == "line1\nline2"
        assert ns.MULTI[1] == "line3\nline4"


class TestDictFormat:
    def test_parses_sections(self, content_dir):
        (content_dir / "data.txt").write_text(
            "[sleep]\nvalue1\n[workouts]\nvalue2", encoding="utf-8"
        )
        ns = load_content(content_dir, logging.getLogger("test"))
        assert isinstance(ns.DATA, dict)
        assert ns.DATA["sleep"] == "value1"
        assert ns.DATA["workouts"] == "value2"

    def test_preserves_leading_newlines(self, content_dir):
        (content_dir / "close.txt").write_text(
            "[sleep]\n\n\ntext here\n[workouts]\n\nother text",
            encoding="utf-8",
        )
        ns = load_content(content_dir, logging.getLogger("test"))
        assert ns.CLOSE["sleep"] == "\n\ntext here"
        assert ns.CLOSE["workouts"] == "\nother text"

    def test_dict_multiple_keys(self, content_dir):
        (content_dir / "d.txt").write_text(
            "[a]\nA\n[b]\nB\n[c]\nC", encoding="utf-8"
        )
        ns = load_content(content_dir, logging.getLogger("test"))
        assert list(ns.D.keys()) == ["a", "b", "c"]


class TestIncludeResolution:
    def test_single_include(self, content_dir):
        (content_dir / "block.txt").write_text("BLOCK CONTENT", encoding="utf-8")
        (content_dir / "main.txt").write_text(
            "before\n{{include:block.txt}}\nafter", encoding="utf-8"
        )
        ns = load_content(content_dir, logging.getLogger("test"))
        assert ns.MAIN == "before\nBLOCK CONTENT\nafter"

    def test_multiple_includes(self, content_dir):
        (content_dir / "a.txt").write_text("AAA", encoding="utf-8")
        (content_dir / "b.txt").write_text("BBB", encoding="utf-8")
        (content_dir / "combined.txt").write_text(
            "{{include:a.txt}}\n{{include:b.txt}}", encoding="utf-8"
        )
        ns = load_content(content_dir, logging.getLogger("test"))
        assert ns.COMBINED == "AAA\nBBB"

    def test_nested_include(self, content_dir):
        (content_dir / "inner.txt").write_text("INNER", encoding="utf-8")
        (content_dir / "middle.txt").write_text(
            "MID-{{include:inner.txt}}-MID", encoding="utf-8"
        )
        (content_dir / "outer.txt").write_text(
            "OUT-{{include:middle.txt}}-OUT", encoding="utf-8"
        )
        ns = load_content(content_dir, logging.getLogger("test"))
        assert ns.OUTER == "OUT-MID-INNER-MID-OUT"

    def test_circular_include_raises(self, content_dir):
        (content_dir / "x.txt").write_text("{{include:y.txt}}", encoding="utf-8")
        (content_dir / "y.txt").write_text("{{include:x.txt}}", encoding="utf-8")
        with pytest.raises(RuntimeError, match="[Cc]ircular"):
            load_content(content_dir, logging.getLogger("test"))

    def test_missing_include_raises(self, content_dir):
        (content_dir / "broken.txt").write_text(
            "{{include:nonexistent.txt}}", encoding="utf-8"
        )
        with pytest.raises(FileNotFoundError, match="nonexistent.txt"):
            load_content(content_dir, logging.getLogger("test"))

    def test_include_resolved_before_format_detection(self, content_dir):
        """A plain file that includes a block should remain plain after resolution."""
        (content_dir / "rule.txt").write_text("rule text", encoding="utf-8")
        (content_dir / "prompt.txt").write_text(
            "intro\n{{include:rule.txt}}\noutro", encoding="utf-8"
        )
        ns = load_content(content_dir, logging.getLogger("test"))
        assert isinstance(ns.PROMPT, str)
        assert ns.PROMPT == "intro\nrule text\noutro"


class TestFilenameConversion:
    def test_lowercase_to_uppercase(self, content_dir):
        (content_dir / "onboarding_greeting.txt").write_text("hi", encoding="utf-8")
        ns = load_content(content_dir, logging.getLogger("test"))
        assert ns.ONBOARDING_GREETING == "hi"

    def test_ignores_non_txt_files(self, content_dir):
        (content_dir / "readme.md").write_text("ignore me", encoding="utf-8")
        (content_dir / "real.txt").write_text("keep me", encoding="utf-8")
        ns = load_content(content_dir, logging.getLogger("test"))
        assert ns.REAL == "keep me"
        assert not hasattr(ns, "README")


class TestFormatHint:
    def test_format_plain_overrides_list_detection(self, content_dir):
        """A file with --- that should NOT be treated as a list."""
        (content_dir / "template.txt").write_text(
            "# format: plain\nsome content\n---\nmore content", encoding="utf-8"
        )
        ns = load_content(content_dir, logging.getLogger("test"))
        assert isinstance(ns.TEMPLATE, str)
        assert "---" in ns.TEMPLATE

    def test_format_list_forced(self, content_dir):
        (content_dir / "items.txt").write_text(
            "# format: list\none\n---\ntwo", encoding="utf-8"
        )
        ns = load_content(content_dir, logging.getLogger("test"))
        assert ns.ITEMS == ["one", "two"]

    def test_format_dict_forced(self, content_dir):
        (content_dir / "data.txt").write_text(
            "# format: dict\n[key1]\nval1\n[key2]\nval2", encoding="utf-8"
        )
        ns = load_content(content_dir, logging.getLogger("test"))
        assert ns.DATA == {"key1": "val1", "key2": "val2"}

    def test_format_hint_stripped_from_content(self, content_dir):
        (content_dir / "msg.txt").write_text(
            "# format: plain\nactual content", encoding="utf-8"
        )
        ns = load_content(content_dir, logging.getLogger("test"))
        assert ns.MSG == "actual content"
        assert "# format" not in ns.MSG


class TestEdgeCases:
    def test_empty_directory(self, content_dir):
        ns = load_content(content_dir, logging.getLogger("test"))
        assert vars(ns) == {}

    def test_hebrew_roundtrip(self, content_dir):
        text = "שלום עולם, מה שלומך? 👋"
        (content_dir / "heb.txt").write_text(text, encoding="utf-8")
        ns = load_content(content_dir, logging.getLogger("test"))
        assert ns.HEB == text

    def test_getattr_raises_on_missing(self, content_dir):
        (content_dir / "exists.txt").write_text("yes", encoding="utf-8")
        ns = load_content(content_dir, logging.getLogger("test"))
        with pytest.raises(AttributeError):
            _ = ns.DOES_NOT_EXIST


class TestLogging:
    def test_logs_loading_start_and_end(self, content_dir, caplog):
        (content_dir / "one.txt").write_text("a", encoding="utf-8")
        (content_dir / "two.txt").write_text("b", encoding="utf-8")
        with caplog.at_level(logging.INFO):
            load_content(content_dir, logging.getLogger("test"))
        assert any("Loading content" in r.message for r in caplog.records)
        assert any("Loaded 2" in r.message for r in caplog.records)
