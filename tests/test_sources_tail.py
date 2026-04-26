"""Unit tests for split_tail_sources — 14 cases.

Run: python tests/test_sources_tail.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from grok_search.sources_tail import split_tail_sources


def test_heading_plus_5_links_strip():
    text = (
        "Answer body here.\n"
        "More content.\n"
        "\n"
        "## Sources\n"
        "1. [Title 1](https://a.com)\n"
        "2. [Title 2](https://b.com)\n"
        "3. [Title 3](https://c.com)\n"
        "4. [Title 4](https://d.com)\n"
        "5. [Title 5](https://e.com)\n"
    )
    body, sources = split_tail_sources(text)
    assert "## Sources" not in body
    assert "https://a.com" not in body
    assert body.endswith("More content.")
    assert len(sources) == 5
    assert sources[0] == {"title": "Title 1", "url": "https://a.com"}
    assert sources[4] == {"title": "Title 5", "url": "https://e.com"}


def test_no_heading_5_links_strip():
    text = (
        "Some answer.\n"
        "1. [A](https://a.com)\n"
        "2. [B](https://b.com)\n"
        "3. [C](https://c.com)\n"
        "4. [D](https://d.com)\n"
        "5. [E](https://e.com)\n"
    )
    body, sources = split_tail_sources(text)
    assert body == "Some answer."
    assert len(sources) == 5


def test_2_links_no_strip():
    text = (
        "Body content.\n"
        "1. [A](https://a.com)\n"
        "2. [B](https://b.com)\n"
    )
    body, sources = split_tail_sources(text)
    assert body == text
    assert sources == []


def test_normal_prose_unchanged():
    text = "This is just plain prose with no source list at all.\nMore prose."
    body, sources = split_tail_sources(text)
    assert body == text
    assert sources == []


def test_empty_string():
    body, sources = split_tail_sources("")
    assert body == ""
    assert sources == []


def test_mixed_bare_and_md_links():
    text = (
        "Body.\n"
        "## References\n"
        "- [A](https://a.com)\n"
        "https://b.com\n"
        "- [C](https://c.com)\n"
    )
    body, sources = split_tail_sources(text)
    assert body == "Body."
    assert len(sources) == 3
    urls = [s["url"] for s in sources]
    assert "https://a.com" in urls
    assert "https://b.com" in urls
    assert "https://c.com" in urls


def test_single_blank_gap_in_block_strip():
    text = (
        "Body.\n"
        "## Sources\n"
        "- [A](https://a.com)\n"
        "- [B](https://b.com)\n"
        "\n"
        "- [C](https://c.com)\n"
    )
    body, sources = split_tail_sources(text)
    assert body == "Body."
    assert len(sources) == 3


def test_double_blank_gap_no_strip():
    text = (
        "Body.\n"
        "- [A](https://a.com)\n"
        "- [B](https://b.com)\n"
        "\n"
        "\n"
        "- [C](https://c.com)\n"
        "- [D](https://d.com)\n"
        "- [E](https://e.com)\n"
    )
    body, sources = split_tail_sources(text)
    assert body == text
    assert sources == []


def test_mid_text_sources_heading_no_strip():
    text = (
        "Intro.\n"
        "## Sources\n"
        "- [A](https://a.com)\n"
        "- [B](https://b.com)\n"
        "- [C](https://c.com)\n"
        "\n"
        "Conclusion paragraph after the heading.\n"
    )
    body, sources = split_tail_sources(text)
    assert body == text
    assert sources == []


def test_trailing_trash_no_strip():
    text = (
        "Body.\n"
        "- [A](https://a.com)\n"
        "- [B](https://b.com)\n"
        "- [C](https://c.com)\n"
        "That's all folks.\n"
    )
    body, sources = split_tail_sources(text)
    assert body == text
    assert sources == []


def test_tooltip_link_match():
    text = (
        "Body.\n"
        '- [A](https://a.com "Title A")\n'
        '- [B](https://b.com "Title B")\n'
        '- [C](https://c.com "Title C")\n'
    )
    body, sources = split_tail_sources(text)
    assert body == "Body."
    assert len(sources) == 3
    assert sources[0] == {"title": "A", "url": "https://a.com"}


def test_angle_bare_url_match():
    text = (
        "Body.\n"
        "<https://a.com>\n"
        "<https://b.com>\n"
        "<https://c.com>\n"
    )
    body, sources = split_tail_sources(text)
    assert body == "Body."
    assert len(sources) == 3
    assert sources[0]["url"] == "https://a.com"


def test_hr_consumed_as_boundary():
    text = (
        "Body content.\n"
        "More body.\n"
        "\n"
        "---\n"
        "- [A](https://a.com)\n"
        "- [B](https://b.com)\n"
        "- [C](https://c.com)\n"
    )
    body, sources = split_tail_sources(text)
    # HR + 3 links case: HR consumed, links extracted, body has neither
    assert "---" not in body
    assert "https://a.com" not in body
    assert body.endswith("More body.")
    assert len(sources) == 3


def test_pure_link_list_no_strip():
    text = (
        "## Sources\n"
        "- [A](https://a.com)\n"
        "- [B](https://b.com)\n"
        "- [C](https://c.com)\n"
    )
    body, sources = split_tail_sources(text)
    # body would be empty after strip → refuse
    assert body == text
    assert sources == []


if __name__ == "__main__":
    tests = [
        test_heading_plus_5_links_strip,
        test_no_heading_5_links_strip,
        test_2_links_no_strip,
        test_normal_prose_unchanged,
        test_empty_string,
        test_mixed_bare_and_md_links,
        test_single_blank_gap_in_block_strip,
        test_double_blank_gap_no_strip,
        test_mid_text_sources_heading_no_strip,
        test_trailing_trash_no_strip,
        test_tooltip_link_match,
        test_angle_bare_url_match,
        test_hr_consumed_as_boundary,
        test_pure_link_list_no_strip,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(failed)
