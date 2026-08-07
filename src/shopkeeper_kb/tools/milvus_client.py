from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pymilvus import MilvusClient, MilvusException

from shopkeeper_kb import logging_config
from shopkeeper_kb.settings import Settings, get_settings

# 【梯队 0.4 统一单例工厂：Milvus（路线 E 默认 Milvus Lite】
# 路线 E：不要求分布式 Milvus 服务（docker → 用 pymilvus 自带的 Milvus Lite（本地 SQLite 文件存储，零成本零运维，开发环境跑起来也可以）
# 生产想切分布式 Milvus：只改环境变量 MILVUS_URI = "http://user:pass@host:19530"，不用改代码

DEFAULT_MILVUS_LITE_FILENAME = "milvus_lite_v2.db"


def _resolve_milvus_uri(settings: Settings) -> str:
    """
    计算最终 Milvus URI：
    1) 优先用 .env 里显式写 MILVUS_URI（分布式）
    2) 否则用 Milvus Lite：output_doc_dir/milvus_lite.db）
    """
    env_uri = os.getenv("MILVUS_URI", "").strip()
    if env_uri:
        return env_uri
    # 路线 E 默认 Milvus Lite
    db_dir = Path(settings.output_doc_dir)
    db_dir = Path(db_dir) / DEFAULT_MILVUS_LITE_FILENAME
    return str(db_dir.resolve())


@lru_cache(maxsize=1)
def create_milvus_client(settings: Settings | None = None) -> MilvusClient:
    """
    创建 Milvus 单例客户端。
    - 单例：同一进程只 new 一次。
    - 路线 E 默认 Milvus Lite：本地 SQLite 文件，零成本零运维；
    生产可通过 MILVUS_URI 环境变量一键切换到分布式 Milvus 集群。
    """
    if settings is None:
        settings = get_settings()
    uri = _resolve_milvus_uri(settings)
    # Milvus Lite URI 如果目录不存在则创建
    if not uri.startswith("http://") and not uri.startswith("https://") and not uri.startswith("tcp://"):
        Path(uri).parent.mkdir(parents=True, exist_ok=True)
    client = MilvusClient(uri=uri)
    logging_config.debug(
        "Milvus client created: uri_type=%s uri=%s",
        "lite" if "://" not in uri else "distributed",
        uri if "://" in uri else "<local_lite>",
    )
    return client


def get_milvus_client(settings: Settings | None = None) -> MilvusClient:
    """获取 Milvus 单例客户端。"""
    return create_milvus_client(settings)


def ping_milvus(settings: Settings | None = None) -> bool:
    """健康检查：Milvus 是否可连（0.7 单测 / liveness probe 用）。
    Milvus Lite 没有严格的 ping → 就尝试列集合列表确认文件存在即可。
    """
    try:
        client = get_milvus_client(settings)
        # MilvusClient 本身懒加载，调用任意一个轻量方法
        client.list_collections()
        return True
    except (MilvusException, OSError, RuntimeError, ValueError):
        logging_config.exception("Milvus ping failed")
        return False


def get_or_create_collection(
    collection_name: str,
    dim: int,
    client: MilvusClient | None = None,
    settings: Settings | None = None,
) -> str:
    """
    获取或创建 Milvus collection（幂等：多次调用不会重复建；chunk 向量集合 schema 对齐 ingestion 1.2）。
    返回 collection_name。
    字段：
      - chunk_id (VARCHAR(64), 主键，唯一，不自动生成 id；避免 Milvus 自增 id 与 chunk_id 双主键冲突）
      - doc_id (VARCHAR(64))
      - doc_type (VARCHAR(64)), 召回过滤键（=开放架构：按专家过滤 TopK）
      - position (INT64)
      - page_number (INT32)
      - section_path (VARCHAR(1024))
      - token_count (INT32)
      - embedding (FLOAT_VECTOR, dim)
      - ingested_at (INT64)
    索引：
      - embedding: AUTOINDEX（Milvus 默认的 IVF_FLAT 自动索引，Milvus Lite 本地也能跑，零成本）
      - doc_type + page_number: 标量过滤
    """
    from pymilvus import CollectionSchema, DataType, FieldSchema

    if client is None:
        client = get_milvus_client(settings)
    if client.has_collection(collection_name):
        return collection_name
    logger = logging_config.get_logger("shopkeeper_kb.milvus")  # type: ignore[attr-defined]
    fields = [
        FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, is_primary=True, auto_id=False, max_length=96),
        FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=96),
        FieldSchema(name="doc_type", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="position", dtype=DataType.INT64),
        FieldSchema(name="page_number", dtype=DataType.INT32),
        FieldSchema(name="section_path", dtype=DataType.VARCHAR, max_length=1024),
        FieldSchema(name="token_count", dtype=DataType.INT32),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
        FieldSchema(name="ingested_at", dtype=DataType.INT64),
    ]
    schema = CollectionSchema(fields=fields, description=f"shopkeeper chunks dim={dim}")
    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="embedding",
        index_type="AUTOINDEX",
        metric_type="COSINE",
        params={},
    )
    client.create_collection(
        collection_name=collection_name,
        schema=schema,
        index_params=index_params,
    )
    logger.info(f"milvus collection {collection_name} created (schema-only), dim={dim}")
    return collection_name
