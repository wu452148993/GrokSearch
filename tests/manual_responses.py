"""Manual end-to-end test against real xAI Responses API.

Reads two key sets from env:
  OFFICIAL_GROK_API_URL, OFFICIAL_GROK_API_KEY, OFFICIAL_GROK_MODEL
  PROXY_GROK_API_URL,    PROXY_GROK_API_KEY,    PROXY_GROK_MODEL

Run:
  python tests/manual_responses.py official
  python tests/manual_responses.py proxy
  python tests/manual_responses.py both

Prints (does not assert) per query:
  - HTTP duration
  - len(text), len(annotations), len(citations)
  - first 3 annotations with slice check (text[start_index:end_index])
  - usage dict (server_side_tool_usage_details if present)
  - first 240 chars of text
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from grok_search.providers.grok import GrokSearchProvider


QUERIES = [
    ("real_search", "What's new in Python 3.13 release notes?"),
    ("trivial", "What is 2+2?"),
]


def _load_profile(prefix: str) -> dict | None:
    url = os.getenv(f"{prefix}_GROK_API_URL")
    key = os.getenv(f"{prefix}_GROK_API_KEY")
    model = os.getenv(f"{prefix}_GROK_MODEL")
    if not (url and key and model):
        return None
    return {"url": url, "key": key, "model": model}


async def _run_one(label: str, profile: dict, query_label: str, query: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"[{label}] model={profile['model']} url={profile['url']}")
    print(f"[{label}] query ({query_label}): {query}")
    print(f"{'=' * 70}")

    provider = GrokSearchProvider(profile["url"], profile["key"], profile["model"])
    t0 = time.time()
    try:
        result = await provider.search(query)
    except Exception as e:
        dt = time.time() - t0
        print(f"  EXCEPTION after {dt:.1f}s: {type(e).__name__}: {e}")
        return
    dt = time.time() - t0

    text = result["text"]
    annotations = result["annotations"]
    citations = result.get("citations", [])
    usage = result.get("usage", {})

    print(f"  duration: {dt:.1f}s")
    print(f"  len(text)={len(text)}  annotations={len(annotations)}  top_level_citations={len(citations)}")

    for i, a in enumerate(annotations[:3]):
        url = a.get("url", "?")
        title = a.get("title")
        s = a.get("start_index")
        e = a.get("end_index")
        slice_str = ""
        if isinstance(s, int) and isinstance(e, int) and 0 <= s <= e <= len(text):
            sl = text[s:e]
            slice_str = f"  slice={sl!r}"
        else:
            slice_str = f"  slice=<no_indices_or_oob s={s} e={e}>"
        print(f"  [{i}] {url}  title={title!r}{slice_str}")

    if citations:
        print(f"  top-level citations sample: {citations[:3]}")

    if usage:
        kept = {k: v for k, v in usage.items() if k in ("input_tokens", "output_tokens", "total_tokens", "num_sources_used", "server_side_tool_usage", "server_side_tool_usage_details")}
        print(f"  usage: {json.dumps(kept, ensure_ascii=False)}")

    preview = text.replace("\n", " ")[:240]
    print(f"  text preview: {preview}")


async def _run_profile(label: str, profile: dict) -> None:
    for query_label, query in QUERIES:
        await _run_one(label, profile, query_label, query)


async def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else "both"
    targets: list[tuple[str, dict]] = []

    if target in ("official", "both"):
        p = _load_profile("OFFICIAL")
        if p:
            targets.append(("OFFICIAL", p))
        else:
            print("[skip] OFFICIAL_GROK_API_URL / OFFICIAL_GROK_API_KEY / OFFICIAL_GROK_MODEL not all set")

    if target in ("proxy", "both"):
        p = _load_profile("PROXY")
        if p:
            targets.append(("PROXY", p))
        else:
            print("[skip] PROXY_GROK_API_URL / PROXY_GROK_API_KEY / PROXY_GROK_MODEL not all set")

    if not targets:
        print("\nno valid profile; export env vars and retry")
        sys.exit(2)

    for label, profile in targets:
        await _run_profile(label, profile)


if __name__ == "__main__":
    asyncio.run(main())
