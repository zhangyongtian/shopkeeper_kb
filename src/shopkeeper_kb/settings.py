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

    doc_dir: str
    download_dir: str
    output_doc_dir: str

    mineru_token: str
    mineru_base_url: str
    mineru_page_limit: int
    mineru_split_pages: int
    mineru_concurrency: int
    md_img_context_chars: int


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
        doc_dir=os.getenv("DOC_DIR", "/home/roott/work/doc"),
        download_dir=os.getenv("DOWNLOAD_DIR", "/home/roott/work/download"),
        output_doc_dir=os.getenv("OUTPUT_DOC_DIR", "/home/roott/work/output_doc"),
        mineru_token=os.getenv("MINERU_TOKEN", "").strip(),
        mineru_base_url=os.getenv("MINERU_BASE_URL", "https://mineru.net").rstrip("/"),
        mineru_page_limit=int(os.getenv("MINERU_PAGE_LIMIT", "200")),
        mineru_split_pages=int(os.getenv("MINERU_SPLIT_PAGES", "200")),
        mineru_concurrency=int(os.getenv("MINERU_CONCURRENCY", "1")),
        md_img_context_chars=int(os.getenv("MD_IMG_CONTEXT_CHARS", "800")),
    )
