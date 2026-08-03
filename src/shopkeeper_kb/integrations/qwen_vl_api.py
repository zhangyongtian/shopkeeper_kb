from __future__ import annotations

import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from threading import Lock

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from shopkeeper_kb.settings import Settings


class _QwenVLStructuredOutput(BaseModel):
    alt: str = Field(min_length=1)
    img_desc: str = Field(min_length=1)


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
        self._llm = ChatOpenAI(
            model=self._model,
            api_key=self._api_key,
            base_url=self._base_url,
            timeout=self._timeout_s,
            max_retries=0,
        ).with_structured_output(_QwenVLStructuredOutput)

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

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(
                content=[
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ]
            ),
        ]

        last_error: Exception | None = None
        for attempt in range(self._max_retry + 1):
            self._rate_limiter.acquire()
            try:
                result = self._llm.invoke(messages)
                alt = str(getattr(result, "alt", "")).strip()
                img_desc = str(getattr(result, "img_desc", "")).strip()
                if not alt or not img_desc:
                    raise ValueError("千问输出不完整")
                return QwenVLResult(alt=alt, img_desc=img_desc)
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
