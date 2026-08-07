from __future__ import annotations

from functools import lru_cache

from redis import Redis
from redis import exceptions as redis_errors

from shopkeeper_kb import logging_config
from shopkeeper_kb.settings import Settings, get_settings


# 【梯队 0.4 统一单例工厂：Redis】
@lru_cache(maxsize=1)
def create_redis_client(settings: Settings | None = None) -> Redis:
    """
    创建 Redis 单例连接池（redis.from_url 自带连接池，默认 2**31 连接上限）。
    - 单例：同一进程内只 new 一次
    - decode_responses=True 统一返回 str（避免到处处理 bytes）
    - socket_connect_timeout=2s（优雅降级：P1-2 Redis 挂了时别卡主整个 chat）
    """
    if settings is None:
        settings = get_settings()
    client = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
        health_check_interval=30,
    )
    logging_config.debug("Redis client created: url=%s", settings.redis_url.split("@")[-1] if "@" in settings.redis_url else settings.redis_url)
    return client


def get_redis_client(settings: Settings | None = None) -> Redis:
    """获取 Redis 单例（全局唯一连接池，decode_responses=True 直接返回 str）。"""
    return create_redis_client(settings)


def ping_redis(settings: Settings | None = None) -> bool:
    """健康检查：Redis 是否可连（0.7 单测 / liveness probe 用）。"""
    try:
        client = get_redis_client(settings)
        return bool(client.ping())
    except redis_errors.RedisError:
        logging_config.exception("Redis ping failed")
        return False


