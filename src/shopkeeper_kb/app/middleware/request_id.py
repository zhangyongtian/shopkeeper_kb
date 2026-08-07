from __future__ import annotations

import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from shopkeeper_kb import logging_config


class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    请求链路追踪中间件（对齐第 16 章 P0-1 + error-handling 规则第 6/7 条）。

    做三件事：
    1) 优先从请求头 X-Request-Id 取（客户端排障可指定），无则 uuid4 生成；
       → 同时 set 到 contextvars，让所有日志自动带 request_id（不需要在每个函数里传参）
    2) 响应头里写回 X-Request-Id；
    3) 记录 access log（包含 method / path / status_code / latency_ms 5 件套，安全合规）。
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-Id") or str(uuid4())
        logging_config.set_request_id(request_id)
        request.state.request_id = request_id

        started_at = time.perf_counter()
        status_code = 500
        response: Response | None = None
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            # 异常会被 app.errors 里的全局异常处理器接住返回 JSONResponse
            # 这里仅记录堆栈日志（对齐 error-handling 第 6 条：服务端日志必须有堆栈）
            logging_config.exception(
                "Unhandled exception in %s %s", request.method, request.url.path
            )
            raise
        finally:
            latency_ms = int((time.perf_counter() - started_at) * 1000)
            # 结构化 access log：对齐 error-handling 第 6 条「必须输出 method/path/status_code/latency_ms」
            logging_config.info(
                "%s %s status=%d latency_ms=%d user_agent=%s",
                request.method,
                request.url.path,
                status_code,
                latency_ms,
                request.headers.get("user-agent", "-")[:120],  # 截断超长 UA
            )
            if response is not None:
                response.headers["X-Request-Id"] = request_id
            logging_config.set_request_id("-")  # 协程归还池前清空，防止串号


