from __future__ import annotations

import logging
from contextvars import ContextVar

import colorlog

# =============== V1.1 梯队 0.3 新增：request_id 跨协程上下文 + 结构化日志（对齐 error-handling 规则 6/7）===============
# 用 contextvars（Python 3.7+ 原生支持异步协程/线程安全）存储当前请求的 request_id
# - FastAPI/Starlette 中间件里写入，logging.Formatter 里取出写入日志
# - 子任务（后台 ingestion、cron 自动打标）也可以手动 set_request_id 追踪
_REQUEST_ID: ContextVar[str] = ContextVar("request_id", default="-")


def set_request_id(request_id: str) -> None:
    """给当前协程/线程设置 request_id（中间件调用，或后台任务手动设置）。"""
    _REQUEST_ID.set(request_id or "-")


def get_request_id() -> str:
    """取出当前 request_id（Formatter、错误堆栈日志里用），取不到返回 -。"""
    return _REQUEST_ID.get() or "-"


class RequestIdFilter(logging.Filter):
    """Python logging Filter，把 request_id 注入到每条日志的 LogRecord.request_id 字段。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()  # type: ignore[attr-defined]
        return True


logger = logging.getLogger(__name__)
log = logger


def get_logger(name: str) -> logging.Logger:
    """返回一个统一带 RequestIdFilter 的 logger（路由/tools 模块直接用这个初始化）。"""
    lg = logging.getLogger(name)
    if not any(isinstance(f, RequestIdFilter) for f in lg.filters):
        lg.addFilter(RequestIdFilter())
    return lg


def init_logging(level: str = "INFO") -> None:
    """
    结构化彩色日志初始化（对齐 error-handling 规则第 6/7 条）。

    日志统一格式（所有行都带 request_id，方便 grep 一次拉出整条调用链）：
    `2026-08-07 15:30:01 - req=abc123 - api.py:46 - INFO - GET /api/chat 200 latency=432ms`
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    fmt = (
        "%(log_color)s%(asctime)s - req=%(request_id)s - %(filename)s:%(lineno)d - %(levelname)s - %(message)s"
    )
    handler = colorlog.StreamHandler()
    handler.setFormatter(
        colorlog.ColoredFormatter(
            fmt,
            datefmt="%Y-%m-%d %H:%M:%S",
            log_colors={
                "DEBUG": "cyan",
                "INFO": "green",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "bold_red",
            },
        )
    )
    handler.addFilter(RequestIdFilter())  # 把 request_id 注入到 LogRecord

    root_logger.handlers.clear()
    root_logger.addHandler(handler)


def debug(msg: object, *args: object, **kwargs: object) -> None:
    logger.debug(msg, *args, **kwargs)


def info(msg: object, *args: object, **kwargs: object) -> None:
    logger.info(msg, *args, **kwargs)


def warning(msg: object, *args: object, **kwargs: object) -> None:
    logger.warning(msg, *args, **kwargs)


def error(msg: object, *args: object, **kwargs: object) -> None:
    logger.error(msg, *args, **kwargs)


def critical(msg: object, *args: object, **kwargs: object) -> None:
    logger.critical(msg, *args, **kwargs)


def exception(msg: object, *args: object, **kwargs: object) -> None:
    # P0-5 / error-handling 6：异常日志必须带堆栈，且 request_id 从 ContextVar 自动注入
    logger.exception(msg, *args, **kwargs)


if __name__ == "__main__":
    init_logging("INFO")
    logger.error("Hello, world!")

