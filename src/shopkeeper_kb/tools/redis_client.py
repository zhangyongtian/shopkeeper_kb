from __future__ import annotations

from redis import Redis

from shopkeeper_kb.settings import Settings, get_settings


def create_redis_client(settings: Settings) -> Redis:
    return Redis.from_url(settings.redis_url)


def get_redis_client() -> Redis:
    settings = get_settings()
    return create_redis_client(settings)

