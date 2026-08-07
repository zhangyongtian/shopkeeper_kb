from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

import torch

from shopkeeper_kb.logging_config import get_logger

logger = get_logger("shopkeeper_kb.embedding")


@dataclass
class EmbeddingConfig:
    model_name: str = "BAAI/bge-m3"
    local_model_dir: str = "models/bge-m3"
    device: str | None = None  # None = auto (cuda / mps / cpu)
    batch_size: int = 64
    max_length: int = 8192
    normalize_embeddings: bool = True


def _resolve_device(preferred: str | None) -> str:
    if preferred:
        return preferred
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class EmbeddingClient:
    """
    路线 E 零成本：本地 FlagEmbedding BGE-M3，CPU/GPU 自动识别。
    维度 = 1024（Milvus 集合维度与这里严格对齐）。
    第一次调用会从 ModelScope / HuggingFace 自动下载，缓存到 local_model_dir。
    """

    def __init__(self, config: EmbeddingConfig | None = None) -> None:
        self.config = config or EmbeddingConfig()
        self._device = _resolve_device(self.config.device)
        self._model = None  # 懒加载，避免导入时加载 2GB 模型
        self._model_loaded = False
        logger.info(
            f"embedding_client init: model={self.config.model_name} "
            f"device={self._device} batch={self.config.batch_size} lazy=True"
        )

    # ------------------------------------------------------------------
    # 模型懒加载
    # ------------------------------------------------------------------
    def _ensure_model_loaded(self) -> None:
        if self._model_loaded and self._model is not None:
            return
        logger.info(f"loading bge-m3 model on {self._device}... (首次调用会自动下载缓存到 models/)")
        try:
            from FlagEmbedding import FlagModel

            self._model = FlagModel(
                self.config.local_model_dir
                if _model_dir_exists(self.config.local_model_dir)
                else self.config.model_name,
                query_instruction_for_retrieval="为这个句子生成表示以用于检索相关文章：",
                use_fp16=self._device == "cuda",
                device=self._device,
                normalize_embeddings=self.config.normalize_embeddings,
            )
            self._model_loaded = True
            dim = len(self.embed_documents(["warmup"])[0])
            logger.info(f"embedding model loaded ok，维度={dim} (Milvus 集合维度必须等于 {dim})")
        except Exception as e:  # pragma: no cover - 模型下载失败由调用方降级
            logger.exception(f"load embedding model failed: {e}")
            raise

    # ------------------------------------------------------------------
    # Public：文档 / 查询向量
    # ------------------------------------------------------------------
    def embed_documents(self, texts: list[str], progress_cb: Callable[[int, int], None] | None = None) -> list[list[float]]:
        self._ensure_model_loaded()
        if not texts:
            return []
        n = len(texts)
        bs = self.config.batch_size
        all_vecs: list[list[float]] = []
        for i in range(0, n, bs):
            batch = texts[i : i + bs]
            vecs = self._model.encode(batch, max_length=self.config.max_length)  # type: ignore[union-attr]
            all_vecs.extend([v.tolist() if hasattr(v, "tolist") else list(v) for v in vecs])
            if progress_cb is not None:
                progress_cb(min(i + bs, n), n)
        return all_vecs

    def embed_queries(self, queries: list[str]) -> list[list[float]]:
        self._ensure_model_loaded()
        if not queries:
            return []
        vecs = self._model.encode_queries(queries)  # type: ignore[union-attr]
        return [v.tolist() if hasattr(v, "tolist") else list(v) for v in vecs]

    def embed_query(self, query: str) -> list[float]:
        return self.embed_queries([query])[0]

    @property
    def dim(self) -> int:
        self._ensure_model_loaded()
        return len(self.embed_documents(["warmup"])[0])


def _model_dir_exists(path: str) -> bool:
    import os

    if not os.path.isdir(path):
        return False
    has_bin = any(f.endswith(".safetensors") or f.endswith(".bin") or f.endswith(".pth") for f in os.listdir(path))
    has_cfg = os.path.exists(os.path.join(path, "config.json"))
    return has_bin and has_cfg


@lru_cache(maxsize=1)
def get_embedding_client(config: EmbeddingConfig | None = None) -> EmbeddingClient:
    """全局单例 embedding client，避免重复加载 2GB 模型。"""
    return EmbeddingClient(config)
