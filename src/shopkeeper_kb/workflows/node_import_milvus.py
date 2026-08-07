"""
NodeImportMilvus：向量库 + Mongo 持久化节点（对齐梯队 1.6 tools/ingestion.py upsert_vecs / upsert_meta）。
职责（单节点单职责，不对外暴露工具依赖）：
  1) Milvus Lite：幂等建集合（dim=settings.embedding_dim），AUTOINDEX + COSINE；
  2) 遍历 chunks + chunk_embeddings 合并成 Milvus insert rows；
  3) 写 Mongo：
       - documents_metadata（1 条 / doc）
       - chunks_metadata（N 条 / chunk，bulk_write upsert）
Milvus / Mongo 任一失败，只写 inserted_count = 实际成功数，不 raise（P1-2 优雅降级）。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import time

from pymongo import UpdateOne

from shopkeeper_kb import logging_config as log
from shopkeeper_kb.workflows.base_node import NodeBase
from shopkeeper_kb.workflows.state import ImportGraphState


def _now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat()


class NodeImportMilvus(NodeBase):
    """
    导入向量库 + Mongo 节点：数据持久化（对齐梯队 1.6 tools.ingestion upsert_vecs/upsert_meta）。

    消费：chunks / chunk_embeddings / doc_type / display_name / item_name / item_tags / file_title / md_path / pdf_page_count / task_id
    产出：milvus_collection / milvus_inserted_count / mongo_doc_id / mongo_inserted_count
    """

    name = "node_import_milvus"
    consumes_fields = ("chunks",)
    produces_fields = ("milvus_collection", "milvus_inserted_count", "mongo_doc_id", "mongo_inserted_count")

    def process(self, state: ImportGraphState) -> dict:
        from shopkeeper_kb.settings import get_settings
        from shopkeeper_kb.tools.mongo import get_db

        log.info(f"-- {self.name} -- 结点开始处理")
        settings = get_settings()

        chunks = list(state.get("chunks") or [])
        embeddings_dict: dict[str, list[float]] = dict(state.get("chunk_embeddings") or {})
        doc_type = str(state.get("doc_type") or "other")
        display_name = str(
            state.get("display_name") or state.get("item_name") or state.get("file_title") or "未命名资料"
        )
        item_name = str(state.get("item_name") or "")
        item_tags = list(state.get("item_tags") or [])
        file_title = str(state.get("file_title") or "")
        md_path = str(state.get("md_path") or "")
        pdf_path = str(state.get("pdf_path") or "")
        task_id = str(state.get("task_id") or "")
        pdf_page_count = int(state.get("pdf_page_count") or 0)

        empty_result = {
            "milvus_collection": "",
            "milvus_inserted_count": 0,
            "mongo_doc_id": "",
            "mongo_inserted_count": 0,
        }
        if not chunks:
            return empty_result

        # doc_id：用 chunks[0].doc_id，没有则从 doc_type/md_path/task_id 哈希兜底
        doc_id = str(chunks[0].get("doc_id") or "")
        if not doc_id:
            h = hashlib.sha1(f"{doc_type}|{md_path}|{file_title}|{task_id}".encode()).hexdigest()
            doc_id = f"doc_{doc_type}_{h[:12]}"

        # page_count：pdf_page_count 或 max(page_number+1)
        max_page_plus1 = max((int(c.get("page_number") or -1) for c in chunks), default=-1) + 1
        page_count = pdf_page_count or max_page_plus1

        # ==============================================================
        # 1) Milvus：建集合 + insert（失败 → inserted=0 不抛）
        # ==============================================================
        collection_name = str(getattr(settings, "milvus_collection", "shopkeeper_chunks") or "shopkeeper_chunks")
        dim = int(getattr(settings, "embedding_dim", 1024) or 1024)
        milvus_inserted = 0
        try:
            from shopkeeper_kb.tools.milvus_client import get_milvus_client, get_or_create_collection

            mc = get_milvus_client(settings)
            if mc is None:
                raise RuntimeError("milvus client is None")
            get_or_create_collection(collection_name, dim=dim, client=mc, settings=settings)

            rows = []
            for c in chunks:
                cid = str(c.get("chunk_id") or "")
                if not cid:
                    continue
                vec = list(embeddings_dict.get(cid) or [])
                if len(vec) != dim:
                    vec = (list(vec) + [0.0] * dim)[:dim]
                rows.append({
                    "chunk_id": cid,
                    "doc_id": doc_id,
                    "doc_type": str(c.get("doc_type") or doc_type),
                    "position": int(c.get("position") or 0),
                    "page_number": int(c.get("page_number") or -1),
                    "section_path": str(c.get("section_path") or "root"),
                    "token_count": int(c.get("token_count") or 0),
                    "embedding": [float(x) for x in vec],
                    "ingested_at": int(time.time()),
                })
            if rows:
                # pymilvus 3.x insert(collection_name, data)；旧版 insert(collection_name, rows)；两种都兼容
                try:
                    mc.insert(collection_name, rows)
                except TypeError:
                    mc.insert(collection_name=collection_name, data=rows)
                milvus_inserted = len(rows)
        except Exception as e:
            log.warning(f"-- {self.name} -- Milvus upsert 失败（优雅降级，不抛）：{e}")
            milvus_inserted = 0

        # ==============================================================
        # 2) Mongo：documents_metadata + chunks_metadata（失败 → inserted=0）
        # ==============================================================
        mongo_inserted = 0
        mongo_doc_id = doc_id
        try:
            db = get_db(settings)
            coll_doc = db[getattr(settings, "coll_documents_metadata", "documents_metadata")]
            coll_chunk = db[getattr(settings, "coll_chunks_metadata", "chunks_metadata")]
            doc_meta = {
                "doc_id": doc_id,
                "task_id": task_id,
                "doc_type": doc_type,
                "display_name": display_name,
                "item_name": item_name,
                "item_tags": item_tags,
                "file_title": file_title,
                "md_path": md_path,
                "pdf_path": pdf_path,
                "page_count": int(page_count or 0),
                "chunk_count": len(chunks),
                "ingested_at": _now_iso(),
                "updated_at": _now_iso(),
                "status": "active",
                "source": "import_main_graph",
            }
            try:
                coll_doc.update_one({"doc_id": doc_id}, {"$setOnInsert": {"enabled": True}, "$set": doc_meta}, upsert=True)
            except Exception as e:
                log.debug(f"-- {self.name} -- documents_metadata upsert 失败：{e}")

            ops: list[UpdateOne] = []
            for c in chunks:
                cid = str(c.get("chunk_id") or "")
                if not cid:
                    continue
                row = {
                    "chunk_id": cid,
                    "doc_id": doc_id,
                    "doc_type": str(c.get("doc_type") or doc_type),
                    "display_name": display_name,
                    "parent_id": str(c.get("parent_id") or ""),
                    "section_path": str(c.get("section_path") or "root"),
                    "position": int(c.get("position") or 0),
                    "page_number": int(c.get("page_number") or -1),
                    "token_count": int(c.get("token_count") or 0),
                    "display_text_preview": str(c.get("display_text") or "")[:500],
                    "image_urls": list(c.get("image_urls") or [])[:20],
                    "image_alts": list(c.get("image_alts") or [])[:20],
                    "quality": str(c.get("quality") or "normal"),
                    "ingested_at": _now_iso(),
                }
                ops.append(UpdateOne({"chunk_id": cid}, {"$setOnInsert": row}, upsert=True))
            if ops:
                res = coll_chunk.bulk_write(ops, ordered=False)
                mongo_inserted = int(getattr(res, "upserted_count", 0) or 0)
        except Exception as e:
            log.warning(f"-- {self.name} -- Mongo 写入失败：{e}")
            mongo_inserted = 0

        return {
            "milvus_collection": collection_name,
            "milvus_inserted_count": int(milvus_inserted),
            "mongo_doc_id": mongo_doc_id,
            "mongo_inserted_count": int(mongo_inserted),
        }
