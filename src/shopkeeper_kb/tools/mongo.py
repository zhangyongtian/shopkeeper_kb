from __future__ import annotations

from functools import lru_cache

from pymongo import MongoClient
from pymongo import errors as mongo_errors
from pymongo.database import Database

from shopkeeper_kb import logging_config
from shopkeeper_kb.settings import Settings, get_settings


# 【梯队 0.4 统一单例工厂：MongoDB】
# 用 lru_cache(maxsize=1) = 单例，避免每次 API 请求 new 一个 MongoClient（连接数爆炸）
@lru_cache(maxsize=1)
def create_mongo_client(settings: Settings | None = None) -> MongoClient:
    """
    创建 MongoDB 单例连接工厂。
    - 单例：同一进程内只 new 一次 MongoClient（内部自带连接池，默认 100 连接）
    - 参数 settings：允许测试时传入 mock Settings；生产用默认 None → get_settings()
    """
    if settings is None:
        settings = get_settings()
    client = MongoClient(settings.mongo_uri, maxPoolSize=50, minPoolSize=5, serverSelectionTimeoutMS=3000)
    logging_config.debug("MongoDB client created: uri=%s db=%s", settings.mongo_uri.replace("://", "://***:***@"), settings.mongo_db)
    return client


def get_mongo_client(settings: Settings | None = None) -> MongoClient:
    """获取 MongoDB 单例 MongoClient（全局唯一连接池）。"""
    return create_mongo_client(settings)


def get_db(settings: Settings | None = None) -> Database:
    """直接获取 settings.mongo_db 对应的 Database 对象，最常用。"""
    if settings is None:
        settings = get_settings()
    return get_mongo_client(settings)[settings.mongo_db]


def ping_mongo(settings: Settings | None = None) -> bool:
    """健康检查：MongoDB 是否可连（0.7 单测 / liveness probe 用）。"""
    try:
        client = get_mongo_client(settings)
        client.admin.command("ping")
        return True
    except mongo_errors.PyMongoError:
        logging_config.exception("MongoDB ping failed")
        return False

