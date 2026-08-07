from __future__ import annotations

import hashlib
import os
import re
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC
from typing import Any

from pypdf import PdfReader

from shopkeeper_kb.logging_config import get_logger
from shopkeeper_kb.settings import Settings, get_settings
from shopkeeper_kb.tools.embedding_client import EmbeddingClient, get_embedding_client
from shopkeeper_kb.tools.milvus_client import get_milvus_client, get_or_create_collection
from shopkeeper_kb.tools.minio_client import get_minio_client, get_minio_public_base_url
from shopkeeper_kb.tools.mongo import get_db
from shopkeeper_kb.workflows.state import Chunk

logger = get_logger("shopkeeper_kb.ingestion")

# ------------------------------------------------------------------
# 阶段枚举（对齐 ingestion_tasks.status）
# ------------------------------------------------------------------
STAGE_PREPARE = "prepare"          # 10%
STAGE_PARSE_MD = "parse_md"        # 20%
STAGE_UPLOAD_IMGS = "upload_imgs"  # 40%
STAGE_RESOLVE_PAGES = "resolve_pages"  # 50%
STAGE_EMBED = "embed"              # 70%
STAGE_UPSERT_VECS = "upsert_vecs"  # 85%
STAGE_UPSERT_META = "upsert_meta"  # 95%
STAGE_DONE = "done"                # 100%


ProgressCb = Callable[[int, str, dict | None], None]


@dataclass
class IngestRequest:
    doc_type: str                 # 对齐 expert_books.doc_type
    pdf_name: str                 # doc/xxx.pdf
    md_path: str                  # 本地 MinerU markdown 路径（xxx.md）
    pdf_path: str                 # 本地 PDF 路径
    force_reingest: bool = False  # 是否删除该 doc_type 旧图/旧向量/旧 meta
    resume_from_stage: str | None = None  # 续跑：上次失败的 stage 名（失败节点续跑 P1-4）
    resume_from_position: int = 0  # 续跑：上次失败的 chunk position

# ------------------------------------------------------------------
# Helper：稳定 chunk_id / doc_id
# ------------------------------------------------------------------


def _sha1(*parts: str) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update(p.encode("utf-8"))
    return h.hexdigest()[:24]


def _mk_doc_id(doc_type: str, pdf_name: str) -> str:
    return f"doc_{_sha1(doc_type, pdf_name)}"


def _mk_chunk_id(doc_id: str, section_path: str, position: int) -> str:
    return f"chk_{_sha1(doc_id, section_path, str(position))}"


# ------------------------------------------------------------------
# 1) 解析 MinerU Markdown → 按二级标题 + 长度溢出拆 chunk
# ------------------------------------------------------------------
_H2_RE = re.compile(r"^##\s+(.+?)\s*$")
_H1_RE = re.compile(r"^#\s+(.+?)\s*$")
_IMG_MD_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def _parse_sections_from_mineru_md(md_text: str, md_base_dir: str) -> list[dict[str, Any]]:
    """
    返回：[ {h1_title, h2_title, section_path, lines: [...], img_items: [{alt, path, abs_path, exists}]}, ... ]
    """
    current_h1 = "（无标题）"
    current_h2: str | None = None
    sections: list[dict[str, Any]] = []
    current_lines: list[str] = []

    def flush_section(force: bool = False):
        nonlocal current_h2, current_lines
        if current_h2 is None and not force:
            return
        if current_h2 is None:
            current_h2 = "（前言）"
        path = f"{current_h1} / {current_h2}"
        joined = "\n".join(current_lines)
        imgs = []
        for m in _IMG_MD_RE.finditer(joined):
            alt, rel = m.group(1).strip(), m.group(2).strip()
            if rel.startswith("http://") or rel.startswith("https://") or rel.startswith("data:"):
                abs_path = rel
                exists = True
            else:
                abs_path = os.path.abspath(os.path.join(md_base_dir, rel))
                exists = os.path.isfile(abs_path)
            imgs.append({"alt": alt, "rel_path": rel, "abs_path": abs_path, "exists": exists})
        sections.append({
            "h1_title": current_h1,
            "h2_title": current_h2,
            "section_path": path,
            "lines": list(current_lines),
            "img_items": imgs,
        })

    for raw in md_text.splitlines():
        line = raw.rstrip()
        m1 = _H1_RE.match(line)
        if m1:
            flush_section()
            current_h1 = m1.group(1).strip() or "（无标题）"
            current_h2 = None
            current_lines = []
            continue
        m2 = _H2_RE.match(line)
        if m2:
            flush_section()
            current_h2 = m2.group(1).strip() or "（未命名小节）"
            current_lines = [line]
            continue
        if current_h2 is not None:
            current_lines.append(line)

    flush_section(force=True)
    return sections


_CHAR_PER_TOKEN_CN = 1.3
_MAX_EMBED_CHARS = int(2000 * _CHAR_PER_TOKEN_CN)  # ≈ 2000 token 一段，bge-m3 8192 留余量


def _split_long_section(section: dict[str, Any]) -> list[dict[str, Any]]:
    """单节过长 → 按段落硬拆，保证 embed_text 不爆模型长度。"""
    section_text = "\n".join(section["lines"])
    if len(section_text) <= _MAX_EMBED_CHARS:
        return [section]
    pieces: list[dict[str, Any]] = []
    current_piece_lines: list[str] = []
    current_len = 0
    idx = 0
    for line in section["lines"]:
        current_piece_lines.append(line)
        current_len += len(line) + 1
        if current_len >= _MAX_EMBED_CHARS:
            idx += 1
            pieces.append({
                **section,
                "h2_title": f"{section['h2_title']} · 分节 {idx}",
                "section_path": f"{section['section_path']} · 分节 {idx}",
                "lines": list(current_piece_lines),
            })
            current_piece_lines = []
            current_len = 0
    if current_piece_lines:
        idx += 1
        pieces.append({
            **section,
            "h2_title": f"{section['h2_title']} · 分节 {idx}" if idx > 1 else section["h2_title"],
            "section_path": f"{section['section_path']} · 分节 {idx}" if idx > 1 else section["section_path"],
            "lines": list(current_piece_lines),
        })
    return pieces


# ------------------------------------------------------------------
# 2) 上传 MinIO：chunk 内的本地图片 → bucket/chunks/<chunk_id>/<hash>.<ext>
# ------------------------------------------------------------------
def _upload_chunk_images(chunk: Chunk, minio_client, bucket: str) -> tuple[list[str], list[str]]:
    urls: list[str] = []
    alts: list[str] = []
    base = get_minio_public_base_url().rstrip("/")
    for i, (img_abs, alt) in enumerate(
        zip(chunk.get("_local_img_abs_paths", []), chunk.get("_local_img_alts", []))
    ):
        try:
            if not img_abs or not os.path.isfile(img_abs):
                continue
            ext = os.path.splitext(img_abs)[1].lstrip(".").lower() or "jpg"
            obj_key = f"chunks/{chunk['chunk_id']}/img_{i:02d}.{ext}"
            minio_client.fput_object(bucket, obj_key, img_abs)
            urls.append(f"{base}/{bucket}/{obj_key}")
            alts.append(alt)
        except Exception as e:
            logger.warning(f"upload img failed chunk={chunk['chunk_id']} idx={i}: {e}")
    return urls, alts


# ------------------------------------------------------------------
# 3) 反推 PDF 页码（P.N 跳页预览）：拿 section 前 50 字去每一页 extract_text 模糊比
# ------------------------------------------------------------------
def _build_page_sigs(pdf_path: str) -> dict[int, str]:
    if not os.path.isfile(pdf_path):
        return {}
    try:
        reader = PdfReader(pdf_path)
    except Exception:
        return {}
    sigs: dict[int, str] = {}
    for i, p in enumerate(reader.pages):
        try:
            t = p.extract_text() or ""
        except Exception:
            t = ""
        t_norm = re.sub(r"\s+", "", t)
        if t_norm:
            sigs[i + 1] = t_norm  # 页码 1-based
    return sigs


def _find_page_for_text(text: str, sigs: dict[int, str]) -> int:
    if not sigs:
        return -1
    needle = re.sub(r"\s+", "", text)[:60]
    if len(needle) < 8:
        return -1
    best_pg = -1
    best_overlap = 0.0
    for pg, body in sigs.items():
        if needle in body:
            return pg
        # 退而求其次：找最长子串匹配
        overlap = _longest_substr_len(needle, body)
        score = overlap / max(len(needle), 1)
        if score > best_overlap and score >= 0.4:
            best_overlap = score
            best_pg = pg
    return best_pg


def _longest_substr_len(a: str, b: str, limit: int = 60) -> int:
    """O(min(len(a),len(b)) * limit 的近似实现：滑窗找最长连续命中。"""
    if not a or not b:
        return 0
    best = 0
    blen = len(b)
    for start in range(0, min(len(a), limit)):
        for end in range(start + 1, min(len(a), start + limit) + 1):
            sub = a[start:end]
            if sub in b:
                best = max(best, end - start)
            else:
                break
    _ = blen
    return best


def _strip_image_md(text: str) -> str:
    """把 ![alt](path) 替换成 alt 文本，避免 embed 学进 URL 字符。"""
    return _IMG_MD_RE.sub(lambda m: m.group(1) or "", text)


# ------------------------------------------------------------------
# 4) 核心：跑一次完整的 ingestion（可被 路由 / 脚本 / admin 接口复用）
# ------------------------------------------------------------------
def run_ingest_one(
    req: IngestRequest,
    settings: Settings | None = None,
    emb: EmbeddingClient | None = None,
    progress_cb: ProgressCb | None = None,
) -> dict[str, Any]:
    """
    返回：{doc_id, doc_type, chunk_count, stages_ms: {...}, milvus_upserted, mongo_upserted}
    抛出异常：调用方写进 ingestion_tasks.last_traceback，可 resume_from_stage 续跑。
    """
    s = settings or get_settings()
    emb = emb or get_embedding_client()
    db = get_db(s)
    milvus = get_milvus_client(s)
    minio = get_minio_client(s)
    bucket = s.minio_bucket

    def prog(pct: int, stage: str, extra: dict | None = None):
        if progress_cb is not None:
            try:
                progress_cb(pct, stage, extra or {})
            except Exception:
                pass

    doc_id = _mk_doc_id(req.doc_type, req.pdf_name)
    result: dict[str, Any] = {
        "doc_id": doc_id,
        "doc_type": req.doc_type,
        "pdf_name": req.pdf_name,
        "chunk_count": 0,
        "stages_ms": {},
        "milvus_upserted": 0,
        "mongo_upserted": 0,
    }

    # ------------------------------------------------------------------
    # Stage 0: force reingest → 清旧数据
    # ------------------------------------------------------------------
    t0 = time.time()
    if req.force_reingest and (req.resume_from_stage is None or req.resume_from_stage == STAGE_PREPARE):
        prog(8, STAGE_PREPARE, {"note": "force reingest 清理旧数据"})
        try:
            db[s.coll_ingestion_tasks].update_many(
                {"doc_type": req.doc_type, "status": {"$ne": "running"}},
                {"$set": {"status": "obsolete", "obsoleted_at": int(time.time())}},
            )
            try:
                milvus.delete(
                    collection_name=_chunk_collection_name(s),
                    filter_expr=f"doc_type == \"{req.doc_type}\" and doc_id == \"{doc_id}\"",
                )
            except Exception as e:
                logger.debug(f"milvus delete (probably empty collection) ok: {e}")
            try:
                db["chunks_metadata"].delete_many({"doc_type": req.doc_type, "doc_id": doc_id})
            except Exception as e:
                logger.debug(f"delete chunks_meta ok: {e}")
            # 删 MinIO 旧图
            try:
                for obj in list(minio.list_objects(bucket, prefix="chunks/", recursive=True)):
                    if obj.object_name and f"doc_{doc_id[4:]}" in obj.object_name:  # 粗略匹配
                        try:
                            minio.remove_object(bucket, obj.object_name)
                        except Exception:
                            pass
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"force reingest cleanup got non-fatal error: {e}")
    result["stages_ms"]["prepare"] = int((time.time() - t0) * 1000)
    prog(10, STAGE_PREPARE)

    # ------------------------------------------------------------------
    # Stage 1: 读 md + 切 chunk
    # ------------------------------------------------------------------
    t0 = time.time()
    if req.resume_from_stage in (None, STAGE_PREPARE):
        if not os.path.isfile(req.md_path):
            raise FileNotFoundError(f"MinerU markdown not found: {req.md_path}")
        with open(req.md_path, encoding="utf-8") as fp:
            md_text = fp.read()
        md_base_dir = os.path.dirname(os.path.abspath(req.md_path))
        raw_sections = _parse_sections_from_mineru_md(md_text, md_base_dir)
        split_sections: list[dict[str, Any]] = []
        for sec in raw_sections:
            split_sections.extend(_split_long_section(sec))
        chunks: list[Chunk] = []
        for pos, sec in enumerate(split_sections):
            display_md = "\n".join(sec["lines"])
            embed_text = f"【{sec['section_path']}】\n{_strip_image_md(display_md)}".strip()
            tkn = int(len(embed_text) / _CHAR_PER_TOKEN_CN)
            section_path = sec["section_path"]
            c: Chunk = {
                "doc_id": doc_id,
                "doc_type": req.doc_type,
                "chunk_id": _mk_chunk_id(doc_id, section_path, pos),
                "chunk_level": "child",
                "parent_id": _sha1(doc_id, sec["h1_title"]),
                "section_path": section_path,
                "position": pos,
                "page_number": -1,  # 后面反推
                "token_count": max(tkn, 8),
                "embed_text": embed_text,
                "display_text": display_md,
                "image_urls": [],
                "image_alts": [],
                "quality": "normal",
                "_local_img_abs_paths": [it["abs_path"] for it in sec["img_items"] if it["exists"]],  # type: ignore[typeddict-unknown-key]
                "_local_img_alts": [it["alt"] for it in sec["img_items"] if it["exists"]],  # type: ignore[typeddict-unknown-key]
                "_first_paragraph": _strip_image_md(display_md).strip()[:300],  # type: ignore[typeddict-unknown-key]
            }
            chunks.append(c)
    result["stages_ms"]["parse_md"] = int((time.time() - t0) * 1000)
    if not chunks:
        raise ValueError("parser produced 0 chunks; 至少要有前言")
    prog(22, STAGE_PARSE_MD, {"chunks": len(chunks)})

    # ------------------------------------------------------------------
    # Stage 2: 上传 chunk 内本地图 → MinIO
    # ------------------------------------------------------------------
    t0 = time.time()
    if req.resume_from_stage in (None, STAGE_PREPARE, STAGE_PARSE_MD):
        for i, c in enumerate(chunks):
            urls, alts = _upload_chunk_images(c, minio, bucket)
            c["image_urls"] = urls
            c["image_alts"] = alts
            if (i + 1) % 25 == 0:
                prog(22 + int((i / len(chunks)) * 18), STAGE_UPLOAD_IMGS, {"done": i + 1, "total": len(chunks)})
            # 把第一张图的 URL 拿出来做 thumbnail_url（generation 合成 sources 时会用）
            if urls:
                c["_thumbnail_url"] = urls[0]  # type: ignore[typeddict-unknown-key]
    result["stages_ms"]["upload_imgs"] = int((time.time() - t0) * 1000)
    prog(42, STAGE_UPLOAD_IMGS, {"imgs_uploaded": sum(len(c["image_urls"]) for c in chunks)})

    # ------------------------------------------------------------------
    # Stage 3: 反推 page_number（P.N 跳页）
    # ------------------------------------------------------------------
    t0 = time.time()
    if req.resume_from_stage in (None, STAGE_PREPARE, STAGE_PARSE_MD, STAGE_UPLOAD_IMGS):
        sigs: dict[int, str] = {}
        if os.path.isfile(req.pdf_path):
            sigs = _build_page_sigs(req.pdf_path)
        last_page = 1
        for i, c in enumerate(chunks):
            if c["position"] < req.resume_from_position:
                continue
            para = c.get("_first_paragraph") or c["embed_text"]  # type: ignore[union-attr]
            pg = _find_page_for_text(para, sigs)
            if pg == -1 and sigs:
                pg = last_page  # 匹配不到就沿用上一页（段落通常不会跳太多页）
            if pg > 0:
                last_page = pg
                c["page_number"] = pg
            if (i + 1) % 80 == 0:
                prog(42 + int((i / len(chunks)) * 10), STAGE_RESOLVE_PAGES, {"done": i, "total": len(chunks)})
    result["stages_ms"]["resolve_pages"] = int((time.time() - t0) * 1000)
    resolved = sum(1 for c in chunks if c["page_number"] > 0)
    prog(52, STAGE_RESOLVE_PAGES, {"resolved": resolved, "total": len(chunks)})

    # ------------------------------------------------------------------
    # Stage 4: 本地 bge-m3 embed
    # ------------------------------------------------------------------
    t0 = time.time()
    vecs: list[list[float]] = []
    if req.resume_from_stage in (None, STAGE_PREPARE, STAGE_PARSE_MD, STAGE_UPLOAD_IMGS, STAGE_RESOLVE_PAGES):
        texts = [c["embed_text"] for c in chunks]

        def _emb_cb(done, total):
            prog(52 + int(done / max(total, 1) * 22), STAGE_EMBED, {"done": done, "total": total})

        vecs = emb.embed_documents(texts, progress_cb=_emb_cb)
        if len(vecs) != len(chunks):
            raise RuntimeError(f"embed length mismatch: {len(vecs)} vs {len(chunks)}")
    result["stages_ms"]["embed"] = int((time.time() - t0) * 1000)
    prog(74, STAGE_EMBED, {"embed_done": len(vecs)})

    # ------------------------------------------------------------------
    # Stage 5: Milvus Lite 批量 upsert（doc_type 索引 + enabled 过滤键）
    # ------------------------------------------------------------------
    t0 = time.time()
    if req.resume_from_stage in (None, STAGE_PREPARE, STAGE_PARSE_MD, STAGE_UPLOAD_IMGS, STAGE_RESOLVE_PAGES, STAGE_EMBED):
        dim = len(vecs[0]) if vecs else emb.dim
        col_name = _chunk_collection_name(s)
        get_or_create_collection(col_name, dim, milvus)
        # Milvus insert 按列构造
        data = {
            "chunk_id": [c["chunk_id"] for c in chunks],
            "doc_id": [doc_id for _ in chunks],
            "doc_type": [c["doc_type"] for c in chunks],
            "position": [c["position"] for c in chunks],
            "page_number": [c["page_number"] for c in chunks],
            "section_path": [c["section_path"] for c in chunks],
            "token_count": [c["token_count"] for c in chunks],
            "embedding": vecs,
            "ingested_at": [int(time.time()) for _ in chunks],
        }
        milvus.insert(collection_name=col_name, data=data)
        # upsert：b 也有，若 collection 支持 upsert 直接用；insert 覆盖 primary key chunk_id 就是幂等 upsert
        try:
            milvus.flush(collection_name=col_name)
        except Exception:
            pass
        result["milvus_upserted"] = len(chunks)
    result["stages_ms"]["upsert_vecs"] = int((time.time() - t0) * 1000)
    prog(87, STAGE_UPSERT_VECS, {"milvus": result["milvus_upserted"]})

    # ------------------------------------------------------------------
    # Stage 6: Mongo chunks_metadata（展示层、打标回朔、二次检索 display_text）
    # ------------------------------------------------------------------
    t0 = time.time()
    if req.resume_from_stage in (None, STAGE_PREPARE, STAGE_PARSE_MD, STAGE_UPLOAD_IMGS, STAGE_RESOLVE_PAGES, STAGE_EMBED, STAGE_UPSERT_VECS):
        col_chunks = db[getattr(s, "coll_chunks_metadata", "chunks_metadata")]
        col_docs = db[getattr(s, "coll_documents_metadata", "documents_metadata")]
        try:
            col_chunks.create_index([("chunk_id", 1)], unique=True, background=True)
            col_chunks.create_index([("doc_type", 1), ("doc_id", 1), ("position", 1)], background=True)
            col_docs.create_index([("doc_id", 1)], unique=True, background=True)
            col_docs.create_index([("enabled", 1), ("updated_at", -1)], background=True)
        except Exception:
            pass
        written = 0
        for i, c in enumerate(chunks):
            meta_doc = {
                "chunk_id": c["chunk_id"],
                "doc_id": doc_id,
                "doc_type": c["doc_type"],
                "pdf_name": req.pdf_name,
                "section_path": c["section_path"],
                "position": c["position"],
                "page_number": c["page_number"],
                "token_count": c["token_count"],
                "display_text": c["display_text"],
                "embed_text_preview": c["embed_text"][:400],
                "image_urls": c["image_urls"],
                "image_alts": c["image_alts"],
                "thumbnail_url": (c.get("image_urls") or [""])[0] if c.get("image_urls") else "",  # type: ignore[union-attr]
                "quality": c["quality"],
                "ingested_at": int(time.time()),
            }
            res = col_chunks.update_one(
                {"chunk_id": c["chunk_id"]},
                {"$set": meta_doc},
                upsert=True,
            )
            if res.upserted_id is not None or res.modified_count > 0:
                written += 1
            if (i + 1) % 80 == 0:
                prog(87 + int((i / len(chunks)) * 8), STAGE_UPSERT_META, {"done": i, "total": len(chunks)})
        result["mongo_upserted"] = written
        # 补 documents_metadata（与 LangGraph 一致，书架/enabled 开关统一用这张表）
        try:
            from datetime import datetime

            now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            doc_meta = {
                "doc_id": doc_id,
                "task_id": "",
                "doc_type": req.doc_type,
                "display_name": req.pdf_name.rsplit(".", 1)[0],
                "file_title": req.pdf_name,
                "item_name": req.pdf_name,
                "item_tags": [],
                "chunk_count": len(chunks),
                "page_count": 0,
                "ingested_at": now_iso,
                "updated_at": now_iso,
                "status": "active",
                "source": "tools_ingestion",
                "pdf_name": req.pdf_name,
            }
            col_docs.update_one(
                {"doc_id": doc_id},
                {"$setOnInsert": {"enabled": True}, "$set": doc_meta},
                upsert=True,
            )
        except Exception as e:
            logger.debug(f"documents_metadata upsert non-fatal: {e}")
    result["stages_ms"]["upsert_meta"] = int((time.time() - t0) * 1000)
    result["chunk_count"] = len(chunks)
    prog(100, STAGE_DONE, result)
    return result


# ------------------------------------------------------------------
# 5) 向量 TopK 检索（梯队 2.1 会复用；提前写好，便于 1.6 冒烟按 doc_type 召回）
# ------------------------------------------------------------------
def search_chunks(
    query: str,
    *,
    top_k: int = 5,
    doc_type_filter: list[str] | None = None,
    doc_id_filter: list[str] | None = None,
    settings: Settings | None = None,
    emb: EmbeddingClient | None = None,
) -> list[dict[str, Any]]:
    s = settings or get_settings()
    emb = emb or get_embedding_client()
    milvus = get_milvus_client(s)
    col_name = _chunk_collection_name(s)
    try:
        get_or_create_collection(col_name, emb.dim, milvus)
    except Exception:
        pass
    vec = emb.embed_query(query)
    exprs: list[str] = []
    if doc_type_filter:
        quoted = ",".join(f'"{d}"' for d in doc_type_filter)
        exprs.append(f"doc_type in [{quoted}]")
    if doc_id_filter:
        quoted = ",".join(f'"{d}"' for d in doc_id_filter)
        exprs.append(f"doc_id in [{quoted}]")
    expr = " and ".join(exprs) if exprs else None
    try:
        res = milvus.search(
            collection_name=col_name,
            data=[vec],
            limit=top_k,
            output_fields=["chunk_id", "doc_id", "doc_type", "position", "page_number", "section_path", "token_count"],
            expr=expr,
        )
    except Exception as e:
        logger.warning(f"milvus search failed (empty collection?): {e}")
        return []
    hits = res[0] if res else []
    db = get_db(s)
    ids = [h.get("chunk_id") for h in hits if h.get("chunk_id")]
    meta_map: dict[str, dict] = {}
    coll_chunks = db[getattr(s, "coll_chunks_metadata", "chunks_metadata")]
    if ids:
        for d in coll_chunks.find({"chunk_id": {"$in": ids}}):
            meta_map[d["chunk_id"]] = d
    out: list[dict[str, Any]] = []
    for h in hits:
        entity = h.get("entity") or {}
        cid = entity.get("chunk_id") or h.get("chunk_id")
        meta = meta_map.get(cid, {})
        doc_id = str(entity.get("doc_id") or meta.get("doc_id") or "")
        # 白名单兜底：如果传了 doc_id_filter，最终输出只保留在白名单里的 doc
        if doc_id_filter and doc_id not in doc_id_filter:
            continue
        out.append({
            "score": float(h.get("distance") or 0.0),
            "chunk_id": cid,
            "doc_type": entity.get("doc_type") or h.get("doc_type"),
            "doc_id": entity.get("doc_id") or h.get("doc_id"),
            "page_number": entity.get("page_number") or h.get("page_number") or meta.get("page_number") or -1,
            "section_path": entity.get("section_path") or meta.get("section_path", ""),
            "pdf_name": meta.get("pdf_name", ""),
            "display_text_preview": (meta.get("display_text") or entity.get("section_path") or "")[:400],
            "thumbnail_url": meta.get("thumbnail_url") or "",
            "image_urls": meta.get("image_urls") or [],
        })
    return out


# ------------------------------------------------------------------
# 6) 杂项：集合名 / 失败包装（P1-4 失败 3 次指数退避重试 + 续跑）
# ------------------------------------------------------------------
def _chunk_collection_name(s: Settings) -> str:
    return f"{s.mongo_db}_chunks"  # Milvus collection 名和 mongo db 前缀统一，避免环境冲突


def run_ingest_with_retry(req: IngestRequest, **kwargs) -> dict[str, Any]:
    """P1-4：失败 3 次指数退避；每次失败把 traceback / failed_stage / failed_position 写 ingestion_tasks，下次 resume_from_stage。"""
    settings = kwargs.pop("settings", None) or get_settings()
    max_attempts = kwargs.pop("max_attempts", 3)
    progress_cb: ProgressCb | None = kwargs.get("progress_cb")
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return run_ingest_one(req, settings=settings, **kwargs)
        except Exception as e:
            last_err = e
            tb = traceback.format_exc()
            # 写 ingestion_tasks
            try:
                db = get_db(settings)
                db[settings.coll_ingestion_tasks].update_one(
                    {"task_id": _task_id_from_req(req)},
                    {"$set": {
                        "last_attempt": attempt,
                        "last_status": "failed",
                        "failed_stage": _detect_failed_stage_from_tb(tb),
                        "failed_position": req.resume_from_position,
                        "last_err": str(e),
                        "last_traceback": tb,
                        "failed_at": int(time.time()),
                    }},
                    upsert=True,
                )
            except Exception:
                pass
            # 指数退避：1s / 2s / 4s
            wait_s = 2 ** (attempt - 1)
            if attempt < max_attempts:
                logger.warning(f"ingest attempt {attempt} failed: {e}; wait {wait_s}s then retry")
                if progress_cb:
                    progress_cb(
                        max(5, 10 * (10 - attempt)),
                        "retry",
                        {"attempt": attempt, "wait_s": wait_s, "err": str(e)[:120]},
                    )
                time.sleep(wait_s)
    # 3 次都失败：抛出最终异常
    assert last_err is not None
    raise last_err


def _task_id_from_req(req: IngestRequest) -> str:
    return f"ingest_{_sha1(req.doc_type, req.pdf_name, str(req.force_reingest))}_{int(time.time()/3600)}"


def _detect_failed_stage_from_tb(tb: str) -> str:
    order = [
        (STAGE_UPSERT_META, "upsert_meta"),
        (STAGE_UPSERT_VECS, "insert"),
        (STAGE_EMBED, "encode"),
        (STAGE_RESOLVE_PAGES, "resolve_pages"),
        (STAGE_UPLOAD_IMGS, "upload"),
        (STAGE_PARSE_MD, "parse"),
        (STAGE_PREPARE, "prepare"),
    ]
    for stage, kw in order:
        if kw in tb.lower():
            return stage
    return STAGE_PREPARE
