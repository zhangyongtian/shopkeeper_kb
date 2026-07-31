from __future__ import annotations

import logging

import colorlog

logger = logging.getLogger(__name__)
log = logger


def init_logging(level: str = "INFO") -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = colorlog.StreamHandler()
    handler.setFormatter(
        colorlog.ColoredFormatter(
            "%(log_color)s%(asctime)s - %(filename)s:%(lineno)d - %(levelname)s - %(message)s",
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
    logger.exception(msg, *args, **kwargs)


if __name__ == "__main__":
    init_logging("INFO")
    logger.error("Hello, world!")
