"""Unit tests for GrokSearchProvider._extract — covers offset arithmetic and citations field.

Run: python -m pytest tests/test_extract.py -v
Or:  python tests/test_extract.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from grok_search.providers.grok import GrokSearchProvider


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


if __name__ == "__main__":
    tests = [
        test_single_message_single_block_two_annotations,
        test_two_blocks_offsets_rewritten,
        test_top_level_citations_passthrough,
        test_empty_output,
        test_skips_reasoning_and_web_search_call_items,
        test_annotation_without_indices_preserved,
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
