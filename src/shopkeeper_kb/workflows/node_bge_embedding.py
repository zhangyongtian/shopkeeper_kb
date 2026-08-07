"""
NodeBGEEmbedding：BGE-M3 混合向量化（对齐梯队 1.3 tools/embedding_client.py get_embedding_client）。
注意：embedding 模型 2.2GB，首次懒加载会花 5~20s；
    1) 若磁盘空间不够 / 模型未初始化 → 返回「零向量占位」并在 stage_log note 里写 "placeholder (embedding client init failed)"
    2) 保证 skeleton 不卡死不崩，真实 ingestion 时向量是真的就行
产出：chunk_embeddings: dict[chunk_id, list[float]]（dict 防 chunks 顺序与 embedding list 错位）
"""
from __future__ import annotations

from shopkeeper_kb import logging_config as log
from shopkeeper_kb.workflows.base_node import NodeBase
from shopkeeper_kb.workflows.state import ImportGraphState


def _embed_one_chunk_safe(chunk_embed_text: str, *, embedding_client, embedding_dim: int) -> list[float]:
    """安全向量化一条：client 任何异常 / 返回空 → 返回全 0 占位（维度对齐）。"""
    try:
        vecs = embedding_client.encode([chunk_embed_text])
        if not vecs:
            return [0.0] * embedding_dim
        v0 = list(vecs[0])
        if len(v0) != embedding_dim:
            # 维度不对 → 截断或补 0
            if len(v0) > embedding_dim:
                return v0[:embedding_dim]
            return v0 + [0.0] * (embedding_dim - len(v0))
        return [float(x) for x in v0]
    except Exception as e:
        log.debug(f"NodeBGEEmbedding.encode 失败（{len(chunk_embed_text)} chars）: {e}")
        return [0.0] * embedding_dim


class NodeBGEEmbedding(NodeBase):
    """
    混合向量化节点：使用 BGE-M3 模型将每个 chunk.embed_text 转换为向量（对齐梯队 1.3 tools/embedding_client）。

    消费：chunks（且 chunk.chunk_id / embed_text 非空）
    产出：chunk_embeddings dict[chunk_id, list[float]]，embedding_dim 从 settings.embedding_dim 或 client 推断
    """

    name = "node_bge_embedding"
    consumes_fields = ("chunks",)
    produces_fields = ("chunk_embeddings",)

    def process(self, state: ImportGraphState) -> dict:
        from shopkeeper_kb.settings import get_settings

        log.info(f"-- {self.name} -- 结点开始处理")
        settings = get_settings()
        chunks = list(state.get("chunks") or [])
        if not chunks:
            return {"chunk_embeddings": {}}

        embedding_dim = int(getattr(settings, "embedding_dim", 1024) or 1024)
        client = None
        try:
            from shopkeeper_kb.tools.embedding_client import get_embedding_client

            client = get_embedding_client(settings, _lazy_load=True)
        except Exception as e:
            log.info(f"-- {self.name} -- embedding 客户端初始化失败（骨架阶段占位）：{e}")
            client = None

        out: dict[str, list[float]] = {}
        for c in chunks:
            cid = str(c.get("chunk_id") or "")
            if not cid:
                continue
            embed_text = str(c.get("embed_text") or c.get("display_text") or "")
            if client is None:
                out[cid] = [0.0] * embedding_dim
            else:
                out[cid] = _embed_one_chunk_safe(embed_text, embedding_client=client, embedding_dim=embedding_dim)
        return {"chunk_embeddings": out}
