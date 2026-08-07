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

    # =============== V1.1 梯队 0.2 新增：API 安全 + MongoDB 集合名统一（禁止写死在代码里） ===============
    admin_api_key: str
    # P1-1 admin 路由保护：请求头 X-Admin-Key 必须等于 admin_api_key，否则 403；默认随机 UUID，开发时可在 .env 改

    # ---- 集合名（对齐第 16 章所有 P0-4 / P0-5 / P1-5 / P1-1 / P1-4 用的集合，不要散落在各处写字符串）----
    coll_expert_books: str
    coll_stock_dict: str
    coll_user_profiles: str
    coll_analysis_snapshots: str
    coll_ingestion_tasks: str
    coll_documents_metadata: str
    coll_chunks_metadata: str

    # ---- P0-4 A 股代码字典缓存配置 ----
    stock_dict_cache_ttl_s: int

    # ---- P1-2 优雅降级链：LLM 模型（主 + fallback）+ 搜索 key（E 路线先用免费额度，留字段以后加购）----
    chat_default_model: str
    chat_fallback_model: str
    serpapi_api_key: str
    eastmoney_free_enabled: bool


def _get_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_nonempty(value: str | None, default: str) -> str:
    if value is None:
        return default
    stripped = value.strip()
    return stripped if stripped else default


@lru_cache
def get_settings() -> Settings:
    load_dotenv()

    return Settings(
        api_host=_get_nonempty(os.getenv("API_HOST"), "0.0.0.0"),
        api_port=int(os.getenv("API_PORT", "8000")),
        api_reload=_get_bool(os.getenv("API_RELOAD"), default=False),
        log_level=_get_nonempty(os.getenv("LOG_LEVEL"), "INFO"),
        mongo_uri=_get_nonempty(os.getenv("MONGO_URI"), "mongodb://127.0.0.1:27017"),
        mongo_db=_get_nonempty(os.getenv("MONGO_DB"), "shopkeeper_kb"),
        redis_url=_get_nonempty(os.getenv("REDIS_URL"), "redis://127.0.0.1:6379/0"),
        redis_cache_ttl_s=int(os.getenv("REDIS_CACHE_TTL_S", "2592000")),
        minio_endpoint=_get_nonempty(os.getenv("MINIO_ENDPOINT"), "127.0.0.1:9002"),
        minio_access_key=_get_nonempty(os.getenv("MINIO_ACCESS_KEY"), "minioadmin"),
        minio_secret_key=_get_nonempty(os.getenv("MINIO_SECRET_KEY"), "minioadmin"),
        minio_bucket=_get_nonempty(os.getenv("MINIO_BUCKET"), "shopkeeper-kb"),
        minio_secure=_get_bool(os.getenv("MINIO_SECURE"), default=False),
        minio_public_base_url=_get_nonempty(os.getenv("MINIO_PUBLIC_BASE_URL"), "http://127.0.0.1:9002").rstrip("/"),
        doc_dir=_get_nonempty(os.getenv("DOC_DIR"), "/home/roott/work/doc"),
        download_dir=_get_nonempty(os.getenv("DOWNLOAD_DIR"), "/home/roott/work/download"),
        output_doc_dir=_get_nonempty(os.getenv("OUTPUT_DOC_DIR"), "/home/roott/work/output_doc"),
        mineru_token=os.getenv("MINERU_TOKEN", "").strip(),
        mineru_base_url=_get_nonempty(os.getenv("MINERU_BASE_URL"), "https://mineru.net").rstrip("/"),
        mineru_page_limit=int(os.getenv("MINERU_PAGE_LIMIT", "200")),
        mineru_split_pages=int(os.getenv("MINERU_SPLIT_PAGES", "200")),
        mineru_concurrency=int(os.getenv("MINERU_CONCURRENCY", "1")),
        md_img_context_chars=int(os.getenv("MD_IMG_CONTEXT_CHARS", "800")),
        md_writeback=_get_bool(os.getenv("MD_WRITEBACK"), default=False),
        md_writeback_backup=_get_bool(os.getenv("MD_WRITEBACK_BACKUP"), default=True),
        qwen_api_key=os.getenv("QWEN_API_KEY", "").strip(),
        qwen_base_url=os.getenv("QWEN_BASE_URL", "").strip().rstrip("/"),
        qwen_vl_model=_get_nonempty(os.getenv("QWEN_VL_MODEL"), "qwen3-vl-flash"),
        qwen_timeout_s=float(os.getenv("QWEN_TIMEOUT_S", "60")),
        qwen_max_retry=int(os.getenv("QWEN_MAX_RETRY", "6")),
        qwen_concurrency=int(os.getenv("QWEN_CONCURRENCY", "2")),
        qwen_rps=float(os.getenv("QWEN_RPS", "1")),
        # ---- 梯队 0.2 新增字段（默认值安全且合理，无需用户手动改 .env 就能跑）----
        admin_api_key=_get_nonempty(
            os.getenv("ADMIN_API_KEY"),
            "sk-admin-change-me-in-env-please-4a7b9c2d",  # 随机占位值，生产环境必须在 .env 里覆盖
        ),
        coll_expert_books=_get_nonempty(os.getenv("COLL_EXPERT_BOOKS"), "expert_books"),
        coll_stock_dict=_get_nonempty(os.getenv("COLL_STOCK_DICT"), "stock_dict"),
        coll_user_profiles=_get_nonempty(os.getenv("COLL_USER_PROFILES"), "user_profiles"),
        coll_analysis_snapshots=_get_nonempty(os.getenv("COLL_ANALYSIS_SNAPSHOTS"), "analysis_snapshots"),
        coll_ingestion_tasks=_get_nonempty(os.getenv("COLL_INGESTION_TASKS"), "ingestion_tasks"),
        coll_documents_metadata=_get_nonempty(os.getenv("COLL_DOCUMENTS_METADATA"), "documents_metadata"),
        coll_chunks_metadata=_get_nonempty(os.getenv("COLL_CHUNKS_METADATA"), "chunks_metadata"),
        stock_dict_cache_ttl_s=int(os.getenv("STOCK_DICT_CACHE_TTL_S", "86400")),  # P0-4：Redis 24h 缓存
        chat_default_model=_get_nonempty(os.getenv("CHAT_DEFAULT_MODEL"), "qwen-plus"),  # E 路线默认主模型
        chat_fallback_model=_get_nonempty(os.getenv("CHAT_FALLBACK_MODEL"), "qwen-turbo"),  # P1-2：plus 额度用完切 turbo
        serpapi_api_key=os.getenv("SERPAPI_API_KEY", "").strip(),  # E 路线先用免费 100 次/月，留字段将来补 20 元/月升级
        eastmoney_free_enabled=_get_bool(os.getenv("EASTMONEY_FREE_ENABLED"), default=True),  # 路线 E 默认启用东财免费接口
    )
