from __future__ import annotations

from fastapi import APIRouter, Request

from shopkeeper_kb.tools.milvus_client import ping_milvus
from shopkeeper_kb.tools.minio_client import ping_minio
from shopkeeper_kb.tools.mongo import ping_mongo
from shopkeeper_kb.tools.redis_client import ping_redis

router = APIRouter()


@router.get("/health", summary="健康检查：返回 4 个后端依赖的连通性（Mongo/Redis/MinIO/Milvus）")
async def health(request: Request) -> dict:
    """
    对齐梯队 0.4 4 个 client 的健康检查（liveness/readiness probe 用）。
    返回形如：
    {
        "status": "ok" | "degraded",
        "request_id": "xxx",
        "components": {
            "mongo": true,
            "redis": true,
            "minio": false,
            "milvus": true,
        }
    }
    如果所有依赖都通 → status=ok；任何一个挂了但应用自身还能降级跑 → status=degraded（HTTP 200 不会导致 K8s 重启，符合 P1-2 优雅降级）。
    """
    request_id = getattr(request.state, "request_id", "")
    components = {
        "mongo": ping_mongo(),
        "redis": ping_redis(),
        "minio": ping_minio(),
        "milvus": ping_milvus(),
    }
    all_ok = all(components.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "request_id": request_id,
        "components": components,
    }

