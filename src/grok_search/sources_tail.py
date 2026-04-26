import re

_LINK_LINE_RE = re.compile(
    r'^\s*(?:[-*]|\d+[.)])?\s*\[([^\]]+)\]\((https?://[^\s)]+)'
    r'(?:\s+["\'][^"\']*["\'])?\)\s*\.?\s*$'
)
_BARE_URL_LINE_RE = re.compile(r'^\s*<?(https?://[^\s>]+)>?\s*\.?\s*$')
_HR_RE = re.compile(r'^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$')
_SOURCES_HEADING_RE = re.compile(
    r'^\s*(?:#{1,6}\s*)?(?:\*\*|__)?\s*'
    r'(?:Sources?|References?|Citations?|Bibliography'
    r'|参考(?:资料|文献)?|引用|来源|信源)'
    r'\s*(?:\*\*|__)?\s*[:：]?\s*$',
    re.IGNORECASE,
)


def split_tail_sources(text: str, min_links: int = 3) -> tuple[str, list[dict]]:
    """Detect a trailing markdown block of source links and split it from `text`.

    Refuses to strip when:
      - block has fewer than `min_links` link lines
      - a double blank-line gap appears within the candidate block
      - stripping would leave an empty body (the entire response IS the link list)

    Returns (body, sources). On no detection: (original_text, []).
    """
    if not text:
        return text, []

    lines = text.split('\n')
    i = len(lines) - 1
    while i >= 0 and not lines[i].strip():
        i -= 1
    if i < 0:
        return text, []

    sources_rev: list[dict] = []
    block_top: int | None = None
    consecutive_blanks = 0
    aborted = False

    while i >= 0:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            consecutive_blanks += 1
            if consecutive_blanks > 1:
                aborted = True
                break
            i -= 1
            continue

        consecutive_blanks = 0

        if _SOURCES_HEADING_RE.match(line):
            block_top = i
            break

        if _HR_RE.match(line) and sources_rev:
            block_top = i
            i -= 1
            continue

        m = _LINK_LINE_RE.match(line)
        if m:
            url = m.group(2).strip().rstrip('.,;:!?')
            title = m.group(1).strip()
            sources_rev.append({"title": title, "url": url} if title else {"url": url})
            block_top = i
            i -= 1
            continue

        m = _BARE_URL_LINE_RE.match(line)
        if m:
            url = m.group(1).strip().rstrip('.,;:!?')
            sources_rev.append({"url": url})
            block_top = i
            i -= 1
            continue

        break

    if aborted or block_top is None or len(sources_rev) < min_links:
        return text, []

    sources = list(reversed(sources_rev))
    body = '\n'.join(lines[:block_top]).rstrip()
    if not body.strip():
        return text, []
    return body, sources
