from __future__ import annotations

from functools import lru_cache

from minio import Minio
from minio.error import MinioException
from urllib3 import exceptions as urllib3_exc

from shopkeeper_kb import logging_config
from shopkeeper_kb.settings import Settings, get_settings


# 【梯队 0.4 统一单例工厂：MinIO】
@lru_cache(maxsize=1)
def create_minio_client(settings: Settings | None = None) -> Minio:
    """
    创建 MinIO 单例（内部自带连接池）。
    - 单例：同一进程内只 new 一次
    - 自动确保 bucket 存在（如果不存在且有权限就创建）
    """
    if settings is None:
        settings = get_settings()
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    try:
        if not client.bucket_exists(settings.minio_bucket):
            logging_config.warning(
                "MinIO bucket %s not found, trying to create...", settings.minio_bucket
            )
            client.make_bucket(settings.minio_bucket)
    except MinioException:
        logging_config.warning("MinIO bucket ensure failed (may not have permission), will lazy create on upload")
    logging_config.debug(
        "MinIO client created: endpoint=%s bucket=%s secure=%s",
        settings.minio_endpoint,
        settings.minio_bucket,
        settings.minio_secure,
    )
    return client


def get_minio_client(settings: Settings | None = None) -> Minio:
    """获取 MinIO 单例。"""
    return create_minio_client(settings)


def ping_minio(settings: Settings | None = None) -> bool:
    """健康检查：MinIO 是否可连（0.7 单测 / liveness probe 用）。"""
    try:
        client = get_minio_client(settings)
        client.list_buckets()
        return True
    except (MinioException, urllib3_exc.HTTPError, OSError):
        logging_config.exception("MinIO ping failed")
        return False


def get_minio_public_base_url(settings: Settings | None = None) -> str:
    """MinIO 公网/内网 URL 前缀，用于拼接 chunk 内图片的 minio_url（前端直接展示）。"""
    s = settings or get_settings()
    return (s.minio_public_base_url or f"http://{s.minio_endpoint}").rstrip("/")


