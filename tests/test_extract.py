"""Unit tests for GrokSearchProvider._extract — covers offset arithmetic and citations field.

Run: python -m pytest tests/test_extract.py -v
Or:  python tests/test_extract.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from grok_search.providers.grok import GrokSearchProvider
from grok_search.sources_tail import split_tail_sources
from grok_search.sources import merge_sources


def test_single_message_single_block_two_annotations():
    data = {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "Hello world from xAI",
                        "annotations": [
                            {"type": "url_citation", "url": "http://a", "title": "A", "start_index": 0, "end_index": 5},
                            {"type": "url_citation", "url": "http://b", "title": "B", "start_index": 6, "end_index": 11},
                        ],
                    }
                ],
            }
        ],
        "usage": {"input_tokens": 10},
    }
    out = GrokSearchProvider._extract(data)
    assert out["text"] == "Hello world from xAI"
    assert len(out["annotations"]) == 2
    assert out["annotations"][0]["start_index"] == 0
    assert out["annotations"][0]["end_index"] == 5
    assert out["annotations"][1]["start_index"] == 6
    assert out["annotations"][1]["end_index"] == 11
    assert out["citations"] == []
    assert out["usage"] == {"input_tokens": 10}


def test_two_blocks_offsets_rewritten():
    data = {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "aa",
                        "annotations": [
                            {"type": "url_citation", "url": "http://x", "start_index": 0, "end_index": 2},
                        ],
                    },
                    {
                        "type": "output_text",
                        "text": "bbbb",
                        "annotations": [
                            {"type": "url_citation", "url": "http://y", "start_index": 0, "end_index": 4},
                        ],
                    },
                ],
            }
        ]
    }
    out = GrokSearchProvider._extract(data)
    assert out["text"] == "aabbbb"
    assert len(out["annotations"]) == 2
    assert out["annotations"][0]["start_index"] == 0
    assert out["annotations"][0]["end_index"] == 2
    # block 1 starts at offset 2
    assert out["annotations"][1]["start_index"] == 2
    assert out["annotations"][1]["end_index"] == 6
    # slice check
    assert out["text"][out["annotations"][0]["start_index"]:out["annotations"][0]["end_index"]] == "aa"
    assert out["text"][out["annotations"][1]["start_index"]:out["annotations"][1]["end_index"]] == "bbbb"


def test_top_level_citations_passthrough():
    data = {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "answer", "annotations": []}],
            }
        ],
        "citations": ["http://x.io", "http://y.io"],
    }
    out = GrokSearchProvider._extract(data)
    assert out["text"] == "answer"
    assert out["annotations"] == []
    assert out["citations"] == ["http://x.io", "http://y.io"]


def test_empty_output():
    out = GrokSearchProvider._extract({})
    assert out["text"] == ""
    assert out["annotations"] == []
    assert out["citations"] == []
    assert out["usage"] == {}

    out2 = GrokSearchProvider._extract({"output": []})
    assert out2["text"] == ""
    assert out2["annotations"] == []


def test_skips_reasoning_and_web_search_call_items():
    data = {
        "output": [
            {"type": "reasoning", "summary": "thinking..."},
            {"type": "web_search_call", "id": "ws_1"},
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "final", "annotations": []}],
            },
        ]
    }
    out = GrokSearchProvider._extract(data)
    assert out["text"] == "final"


def test_annotation_without_indices_preserved():
    data = {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "hi",
                        "annotations": [
                            {"type": "url_citation", "url": "http://a"},
                        ],
                    }
                ],
            }
        ]
    }
    out = GrokSearchProvider._extract(data)
    assert len(out["annotations"]) == 1
    assert out["annotations"][0]["url"] == "http://a"
    assert "start_index" not in out["annotations"][0]


def test_integration_proxy_response_with_tail_block():
    """End-to-end: simulate proxy response (3 url_citation annotations on body
    + tail '## Sources' with 30 links). Mirrors what server.py does after
    _extract, exercising the strip + merge pipeline.
    """
    body = (
        "Python 3.13 introduces a new REPL [[1]](https://docs.python.org/3/whatsnew/3.13.html). "
        "It also adds experimental free-threading [[2]](https://peps.python.org/pep-0703/) "
        "and a JIT compiler [[3]](https://peps.python.org/pep-0744/)."
    )
    tail = "\n\n## Sources\n" + "\n".join(
        f"{i}. [Source {i}](https://example.com/page{i})" for i in range(1, 31)
    )
    full_text = body + tail

    annotations = [
        {"type": "url_citation", "url": "https://docs.python.org/3/whatsnew/3.13.html",
         "title": "1", "start_index": body.index("[[1]]"), "end_index": body.index("[[1]]") + len("[[1]](https://docs.python.org/3/whatsnew/3.13.html)")},
        {"type": "url_citation", "url": "https://peps.python.org/pep-0703/",
         "title": "2", "start_index": body.index("[[2]]"), "end_index": body.index("[[2]]") + len("[[2]](https://peps.python.org/pep-0703/)")},
        {"type": "url_citation", "url": "https://peps.python.org/pep-0744/",
         "title": "3", "start_index": body.index("[[3]]"), "end_index": body.index("[[3]]") + len("[[3]](https://peps.python.org/pep-0744/)")},
    ]

    data = {
        "output": [{
            "type": "message",
            "content": [{
                "type": "output_text",
                "text": full_text,
                "annotations": annotations,
            }],
        }],
    }

    extracted = GrokSearchProvider._extract(data)
    assert extracted["text"] == full_text
    assert len(extracted["annotations"]) == 3

    # Mirror server.py's annotation→source loop
    grok_sources = []
    for a in extracted["annotations"]:
        item = {"url": a["url"], "title": a["title"],
                "start_index": a["start_index"], "end_index": a["end_index"]}
        grok_sources.append(item)

    text_body, tail_sources = split_tail_sources(extracted["text"])

    # Tail block stripped
    assert "## Sources" not in text_body
    assert "https://example.com/page1" not in text_body
    assert text_body.endswith("[[3]](https://peps.python.org/pep-0744/).")

    # 30 tail sources extracted
    assert len(tail_sources) == 30

    # Annotation indices must still land within stripped body
    for a in grok_sources:
        assert a["end_index"] <= len(text_body), f"annotation end {a['end_index']} > body len {len(text_body)}"

    # Merge: 3 annotations + 30 tail = 33 unique URLs (no overlap in this fixture)
    all_sources = merge_sources(grok_sources, tail_sources)
    assert len(all_sources) == 33


def test_integration_annotation_in_stripped_region_aborts_strip():
    """If an annotation index extends into the would-be stripped region,
    server.py guards against it. Simulate that guard locally.
    """
    # Construct text where annotation falls INSIDE the tail block
    full_text = (
        "Body.\n"
        "## Sources\n"
        "1. [A](https://a.com)\n"
        "2. [B](https://b.com)\n"
        "3. [C](https://c.com)\n"
    )
    # Annotation pointing into the tail block (e.g. covering "[A]")
    body_annotation_end = full_text.index("(https://a.com)") + len("(https://a.com)")
    grok_sources = [{
        "url": "https://a.com",
        "start_index": full_text.index("[A]"),
        "end_index": body_annotation_end,
    }]

    text_body, tail_sources = split_tail_sources(full_text)
    # Strip would happen; but server-side guard kicks in:
    if tail_sources and any(
        isinstance(s.get("end_index"), int) and s["end_index"] > len(text_body)
        for s in grok_sources
    ):
        text_body = full_text
        tail_sources = []

    assert text_body == full_text
    assert tail_sources == []


if __name__ == "__main__":
    tests = [
        test_single_message_single_block_two_annotations,
        test_two_blocks_offsets_rewritten,
        test_top_level_citations_passthrough,
        test_empty_output,
        test_skips_reasoning_and_web_search_call_items,
        test_annotation_without_indices_preserved,
        test_integration_proxy_response_with_tail_block,
        test_integration_annotation_in_stripped_region_aborts_strip,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            print(f"FAIL {t.__name__}: {e}")
            failed += 1
    sys.exit(failed)
