from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    api_host: str
    api_port: int
    api_reload: bool
    log_level: str

    mongo_uri: str
    mongo_db: str

    redis_url: str
    redis_cache_ttl_s: int

    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str
    minio_secure: bool
    minio_public_base_url: str

    doc_dir: str
    download_dir: str
    output_doc_dir: str

    mineru_token: str
    mineru_base_url: str
    mineru_page_limit: int
    mineru_split_pages: int
    mineru_concurrency: int
    md_img_context_chars: int

    md_writeback: bool
    md_writeback_backup: bool

    qwen_api_key: str
    qwen_base_url: str
    qwen_vl_model: str
    qwen_timeout_s: float
    qwen_max_retry: int
    qwen_concurrency: int
    qwen_rps: float


def _get_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@lru_cache
def get_settings() -> Settings:
    load_dotenv()

    return Settings(
        api_host=os.getenv("API_HOST", "0.0.0.0"),
        api_port=int(os.getenv("API_PORT", "8000")),
        api_reload=_get_bool(os.getenv("API_RELOAD"), default=False),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        mongo_uri=os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017"),
        mongo_db=os.getenv("MONGO_DB", "shopkeeper_kb"),
        redis_url=os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
        redis_cache_ttl_s=int(os.getenv("REDIS_CACHE_TTL_S", "2592000")),
        minio_endpoint=os.getenv("MINIO_ENDPOINT", "127.0.0.1:9002"),
        minio_access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
        minio_secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
        minio_bucket=os.getenv("MINIO_BUCKET", "shopkeeper-kb"),
        minio_secure=_get_bool(os.getenv("MINIO_SECURE"), default=False),
        minio_public_base_url=os.getenv("MINIO_PUBLIC_BASE_URL", "http://127.0.0.1:9002").rstrip("/"),
        doc_dir=os.getenv("DOC_DIR", "/home/roott/work/doc"),
        download_dir=os.getenv("DOWNLOAD_DIR", "/home/roott/work/download"),
        output_doc_dir=os.getenv("OUTPUT_DOC_DIR", "/home/roott/work/output_doc"),
        mineru_token=os.getenv("MINERU_TOKEN", "").strip(),
        mineru_base_url=os.getenv("MINERU_BASE_URL", "https://mineru.net").rstrip("/"),
        mineru_page_limit=int(os.getenv("MINERU_PAGE_LIMIT", "200")),
        mineru_split_pages=int(os.getenv("MINERU_SPLIT_PAGES", "200")),
        mineru_concurrency=int(os.getenv("MINERU_CONCURRENCY", "1")),
        md_img_context_chars=int(os.getenv("MD_IMG_CONTEXT_CHARS", "800")),
        md_writeback=_get_bool(os.getenv("MD_WRITEBACK"), default=False),
        md_writeback_backup=_get_bool(os.getenv("MD_WRITEBACK_BACKUP"), default=True),
        qwen_api_key=os.getenv("QWEN_API_KEY", "").strip(),
        qwen_base_url=os.getenv("QWEN_BASE_URL", "").strip().rstrip("/"),
        qwen_vl_model=os.getenv("QWEN_VL_MODEL", "qwen3-vl-flash").strip(),
        qwen_timeout_s=float(os.getenv("QWEN_TIMEOUT_S", "60")),
        qwen_max_retry=int(os.getenv("QWEN_MAX_RETRY", "6")),
        qwen_concurrency=int(os.getenv("QWEN_CONCURRENCY", "2")),
        qwen_rps=float(os.getenv("QWEN_RPS", "1")),
    )
