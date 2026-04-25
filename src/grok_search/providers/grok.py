import httpx
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_random_exponential
from tenacity.wait import wait_base
from .base import BaseSearchProvider
from ..utils import search_prompt
from ..config import config


def get_local_time_info() -> str:
    try:
        local_tz = datetime.now().astimezone().tzinfo
        local_now = datetime.now(local_tz)
    except Exception:
        local_now = datetime.now(timezone.utc)

    weekdays_cn = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    weekday = weekdays_cn[local_now.weekday()]

    return (
        f"[Current Time Context]\n"
        f"- Date: {local_now.strftime('%Y-%m-%d')} ({weekday})\n"
        f"- Time: {local_now.strftime('%H:%M:%S')}\n"
        f"- Timezone: {local_now.tzname() or 'Local'}\n"
    )


def _needs_time_context(query: str) -> bool:
    cn_keywords = [
        "当前", "现在", "今天", "明天", "昨天",
        "本周", "上周", "下周", "这周",
        "本月", "上月", "下月", "这个月",
        "今年", "去年", "明年",
        "最新", "最近", "近期", "刚刚", "刚才",
        "实时", "即时", "目前",
    ]
    en_keywords = [
        "current", "now", "today", "tomorrow", "yesterday",
        "this week", "last week", "next week",
        "this month", "last month", "next month",
        "this year", "last year", "next year",
        "latest", "recent", "recently", "just now",
        "real-time", "realtime", "up-to-date",
    ]

    query_lower = query.lower()
    for keyword in cn_keywords:
        if keyword in query:
            return True
    for keyword in en_keywords:
        if keyword in query_lower:
            return True
    return False


RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def _is_retryable_exception(exc) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError, httpx.RemoteProtocolError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS_CODES
    return False


class _WaitWithRetryAfter(wait_base):
    """Wait strategy: honor Retry-After on any retryable HTTP status, else exponential backoff."""

    def __init__(self, multiplier: float, max_wait: int):
        self._base_wait = wait_random_exponential(multiplier=multiplier, max=max_wait)
        self._protocol_error_base = 3.0

    def __call__(self, retry_state):
        if retry_state.outcome and retry_state.outcome.failed:
            exc = retry_state.outcome.exception()
            if (
                isinstance(exc, httpx.HTTPStatusError)
                and exc.response.status_code in RETRYABLE_STATUS_CODES
            ):
                retry_after = self._parse_retry_after(exc.response)
                if retry_after is not None:
                    return retry_after
            if isinstance(exc, httpx.RemoteProtocolError):
                return self._base_wait(retry_state) + self._protocol_error_base
        return self._base_wait(retry_state)

    def _parse_retry_after(self, response: httpx.Response) -> Optional[float]:
        header = response.headers.get("Retry-After")
        if not header:
            return None
        header = header.strip()

        if header.isdigit():
            return float(header)

        try:
            retry_dt = parsedate_to_datetime(header)
            if retry_dt.tzinfo is None:
                retry_dt = retry_dt.replace(tzinfo=timezone.utc)
            delay = (retry_dt - datetime.now(timezone.utc)).total_seconds()
            return max(0.0, delay)
        except (TypeError, ValueError):
            return None


class GrokSearchProvider(BaseSearchProvider):
    def __init__(self, api_url: str, api_key: str, model: str = "grok-4-fast"):
        super().__init__(api_url, api_key)
        self.model = model

    def get_provider_name(self) -> str:
        return "Grok"

    async def search(self, query: str, platform: str = "") -> dict:
        platform_prompt = (
            f"\n\nFocus on these platforms: {platform}\n" if platform else ""
        )
        time_context = get_local_time_info() + "\n" if _needs_time_context(query) else ""

        payload = {
            "model": self.model,
            "input": [
                {"role": "system", "content": search_prompt},
                {"role": "user", "content": time_context + query + platform_prompt},
            ],
            "tools": [{"type": "web_search"}],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        timeout = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=None)
        endpoint = f"{self.api_url.rstrip('/')}/responses"

        data: dict = {}
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(config.retry_max_attempts + 1),
            wait=_WaitWithRetryAfter(config.retry_multiplier, config.retry_max_wait),
            retry=retry_if_exception(_is_retryable_exception),
            reraise=True,
        ):
            with attempt:
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                    r = await client.post(endpoint, headers=headers, json=payload)
                    r.raise_for_status()
                    data = r.json()

        return self._extract(data)

    @staticmethod
    def _extract(data: dict) -> dict:
        text_parts: list[str] = []
        annotations: list[dict] = []
        text_offset = 0

        for item in data.get("output") or []:
            if item.get("type") != "message":
                continue
            for c in item.get("content") or []:
                if c.get("type") != "output_text":
                    continue
                t = c.get("text")
                block_text = t if isinstance(t, str) else ""
                block_offset = text_offset
                if block_text:
                    text_parts.append(block_text)
                    text_offset += len(block_text)
                for a in c.get("annotations") or []:
                    if not isinstance(a, dict):
                        continue
                    out = dict(a)
                    if isinstance(out.get("start_index"), int) and isinstance(out.get("end_index"), int):
                        out["start_index"] += block_offset
                        out["end_index"] += block_offset
                    annotations.append(out)

        return {
            "text": "".join(text_parts),
            "annotations": annotations,
            "citations": data.get("citations") or [],
            "usage": data.get("usage") or {},
        }
