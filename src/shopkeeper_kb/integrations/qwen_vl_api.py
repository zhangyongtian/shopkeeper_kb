from __future__ import annotations

import json
import random
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from threading import Lock

from shopkeeper_kb.settings import Settings


_JSON_OBJECT_PATTERN = re.compile(r"\{[\s\S]*\}")


def _extract_first_json_object(text: str) -> dict:
    value = text.strip()
    if value.startswith("{") and value.endswith("}"):
        return json.loads(value)
    match = _JSON_OBJECT_PATTERN.search(value)
    if not match:
        raise ValueError("未找到 JSON 对象输出")
    return json.loads(match.group(0))


@dataclass(frozen=True)
class QwenVLResult:
    alt: str
    img_desc: str


class _RateLimiter:
    def __init__(self, *, rps: float):
        self._min_interval_s = 1.0 / rps if rps > 0 else 0.0
        self._lock = Lock()
        self._next_ts = 0.0

    def acquire(self):
        if self._min_interval_s <= 0:
            return
        with self._lock:
            now = time.time()
            wait_s = max(self._next_ts - now, 0.0)
            next_ts = max(self._next_ts, now) + self._min_interval_s
            self._next_ts = next_ts
        if wait_s > 0:
            time.sleep(wait_s)


class QwenVLClient:
    def __init__(self, settings: Settings):
        if not settings.qwen_base_url:
            raise ValueError("QWEN_BASE_URL 为空")
        if not settings.qwen_api_key:
            raise ValueError("QWEN_API_KEY 为空")
        self._base_url = settings.qwen_base_url.rstrip("/")
        self._api_key = settings.qwen_api_key
        self._model = settings.qwen_vl_model
        self._timeout_s = settings.qwen_timeout_s
        self._max_retry = max(int(settings.qwen_max_retry), 0)
        self._rate_limiter = _RateLimiter(rps=float(settings.qwen_rps))

    def describe_image(
        self,
        *,
        image_data_url: str,
        pre_text: str,
        next_text: str,
        current_alt: str,
    ) -> QwenVLResult:
        system_prompt = (
            "你是一个严谨的中文文档图片理解助手。"
            "你只允许输出严格 JSON，不要输出 markdown，不要输出多余文字。"
            '输出格式：{"alt":"...","img_desc":"..."}。'
            "alt：20-60 字，概括图片在当前上下文中的作用。"
            "img_desc：更详细的描述，可包含图表类型/关键信息/结论。"
        )
        user_text = "\n".join(
            [
                f"当前图片原始 alt：{current_alt}".strip(),
                "图片前文：",
                pre_text.strip(),
                "图片后文：",
                next_text.strip(),
            ]
        ).strip()

        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ],
                },
            ],
            "temperature": 0.2,
        }

        data = self._request_json(
            url=f"{self._base_url}/chat/completions",
            payload=body,
        )
        content = (
            (((data.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
        )
        parsed = _extract_first_json_object(str(content))
        alt = str(parsed.get("alt") or "").strip()
        img_desc = str(parsed.get("img_desc") or "").strip()
        if not alt and not img_desc:
            raise ValueError("千问输出为空")
        return QwenVLResult(alt=alt, img_desc=img_desc)

    def _request_json(self, *, url: str, payload: dict) -> dict:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        last_error: Exception | None = None

        for attempt in range(self._max_retry + 1):
            self._rate_limiter.acquire()
            try:
                req = urllib.request.Request(
                    url=url,
                    data=raw,
                    method="POST",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self._api_key}",
                    },
                )
                with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:
                    resp_raw = resp.read()
                    return json.loads(resp_raw.decode("utf-8"))
            except urllib.error.HTTPError as e:
                retryable = e.code == 429 or 500 <= e.code <= 599
                if not retryable or attempt >= self._max_retry:
                    raise
                retry_after = e.headers.get("Retry-After") if e.headers else None
                wait_s = _compute_backoff_s(attempt=attempt, retry_after=retry_after)
                time.sleep(wait_s)
                last_error = e
            except Exception as e:
                if attempt >= self._max_retry:
                    raise
                wait_s = _compute_backoff_s(attempt=attempt, retry_after=None)
                time.sleep(wait_s)
                last_error = e

        if last_error is not None:
            raise last_error
        raise RuntimeError("请求失败")


def _compute_backoff_s(*, attempt: int, retry_after: str | None) -> float:
    if retry_after:
        try:
            value = float(retry_after)
            if value > 0:
                return min(value, 120.0)
        except Exception:
            pass
    base = min(2 ** attempt, 60)
    jitter = random.random()
    return float(min(base + jitter, 120.0))

