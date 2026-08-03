from __future__ import annotations

from minio import Minio

from shopkeeper_kb.settings import Settings, get_settings


def create_minio_client(settings: Settings) -> Minio:
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def get_minio_client() -> Minio:
    settings = get_settings()
    return create_minio_client(settings)

