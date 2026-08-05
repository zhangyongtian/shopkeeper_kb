from __future__ import annotations

import base64
import hashlib
import io
import json
import mimetypes
import posixpath
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from shopkeeper_kb import logging_config as log
from shopkeeper_kb.integrations.qwen_vl_api import QwenVLClient
from shopkeeper_kb.settings import get_settings
from shopkeeper_kb.tools.minio_client import create_minio_client
from shopkeeper_kb.tools.redis_client import create_redis_client
from shopkeeper_kb.workflows.base_node import NodeBase
from shopkeeper_kb.workflows.state import ImportGraphState


_MD_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def _parse_md_image_target(raw: str) -> str:
    value = raw.strip()
    if value.startswith("<") and value.endswith(">") and len(value) >= 3:
        value = value[1:-1].strip()
    if not value:
        return ""

    token = value.split()[0].strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}:
        token = token[1:-1].strip()
    return token


def _cleanup_context_text(text: str) -> str:
    value = _MD_IMAGE_PATTERN.sub("", text)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _extract_pre_next(md: str, *, span: tuple[int, int], context_chars: int) -> tuple[str, str]:
    start, end = span
    half = max(context_chars // 2, 0)
    left_chars = half
    right_chars = max(context_chars - half, 0)

    left = max(start - left_chars, 0)
    right = min(end + right_chars, len(md))

    pre_text = md[left:start]
    next_text = md[end:right]
    return _cleanup_context_text(pre_text), _cleanup_context_text(next_text)


def _normalize_object_key(value: str) -> str:
    raw = value.strip().replace("\\", "/")
    raw = raw.removeprefix("./")
    norm = posixpath.normpath(raw)
    norm = norm.lstrip("/")
    if norm.startswith("../") or norm in {"..", "."}:
        raise ValueError(f"非法图片相对路径: {value}")
    return norm


def _normalize_book_prefix(value: str) -> str:
    norm = str(value).strip().replace("/", "-").replace("\\", "-")
    norm = re.sub(r"\s+", " ", norm).strip()
    if not norm:
        raise ValueError("书名前缀为空")
    return norm


def _guess_content_type(path: str) -> str:
    ct, _ = mimetypes.guess_type(path)
    if not ct:
        return "application/octet-stream"
    return ct


def _build_public_url(*, public_base_url: str, bucket: str, object_key: str) -> str:
    safe_key = quote(object_key, safe="/")
    return f"{public_base_url.rstrip('/')}/{bucket}/{safe_key}"


def _try_extract_minio_object_key_from_url(url: str, *, bucket: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None
    path = parsed.path or ""
    marker = f"/{bucket}/"
    idx = path.find(marker)
    if idx < 0:
        return None
    encoded_key = path[idx + len(marker) :].lstrip("/")
    if not encoded_key:
        return None
    return unquote(encoded_key)


def _atomic_write_text(path: Path, text: str) -> None:
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def _try_load_minio_json(*, minio_client, bucket: str, json_key: str) -> dict | None:
    try:
        resp = minio_client.get_object(bucket, json_key)
    except Exception:
        return None
    try:
        raw = resp.read()
    finally:
        try:
            resp.close()
        except Exception:
            pass
        try:
            resp.release_conn()
        except Exception:
            pass
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


class NodeMDImg(NodeBase):
    """
    MarkDown图片处理节点：多模态图片理解
    """


    name = "node_md_img"

    def process(self, state: ImportGraphState):
        log.info(f"-- {self.name} -- 结点开始处理")
        settings = get_settings()

        md_path = state.get("md_path", "")
        md_content = state.get("md_content", "")
        if not md_path:
            raise ValueError("state.md_path 为空")
        if not md_content:
            raise ValueError("state.md_content 为空")

        md_dir = Path(md_path).parent
        book_prefix = _normalize_book_prefix(md_dir.name)
        context_chars = max(int(getattr(settings, "md_img_context_chars", 800)), 0)

        items = []
        for match in _MD_IMAGE_PATTERN.finditer(md_content):
            alt = match.group(1) or ""
            raw_target = match.group(2) or ""
            target = _parse_md_image_target(raw_target)
            if not target:
                continue

            img_rel_path = target
            img_abs_path = None
            target_is_url = target.startswith("http://") or target.startswith("https://")
            minio_object_key = ""

            if target_is_url:
                object_key = _try_extract_minio_object_key_from_url(target, bucket=settings.minio_bucket)
                if object_key:
                    minio_object_key = object_key
                    raw_object_key = object_key
                    prefix = f"{book_prefix}/"
                    if raw_object_key.startswith(prefix):
                        raw_object_key = raw_object_key[len(prefix) :]
                    img_rel_path = raw_object_key
                    img_abs_path = (md_dir / Path(raw_object_key)).resolve()
            if img_abs_path is None:
                img_path = Path(target)
                if img_path.is_absolute():
                    img_abs_path = img_path
                else:
                    img_abs_path = (md_dir / img_path).resolve()

            pre_text, next_text = _extract_pre_next(
                md_content, span=(match.start(), match.end()), context_chars=context_chars
            )
            exists = img_abs_path.exists()

            item = {
                "img_rel_path": img_rel_path,
                "img_abs_path": str(img_abs_path),
                "alt": alt,
                "pre_text": pre_text,
                "next_text": next_text,
                "start": match.start(),
                "end": match.end(),
                "exists": exists,
                "img_desc": "",
                "minio_url": "",
                "cache_hit": False,
                "error": "",
                "target_is_url": target_is_url,
                "minio_object_key": minio_object_key,
            }
            items.append(item)

        state["md_img_items"] = items

        log.info(f"-- {self.name} -- 识别图片数量: {len(items)}; context_chars={context_chars}")
        qwen_enabled = bool(settings.qwen_base_url and settings.qwen_api_key)
        if not qwen_enabled:
            log.info(f"-- {self.name} -- 未配置 QWEN_BASE_URL / QWEN_API_KEY，将跳过多模态识别，仅做上传/写回")

        redis_client = None
        try:
            redis_client = create_redis_client(settings)
            redis_client.ping()
        except Exception:
            redis_client = None
        if redis_client is None:
            log.info(f"-- {self.name} -- Redis 不可用，跳过缓存")

        qwen_client = QwenVLClient(settings) if qwen_enabled else None
        minio_client = create_minio_client(settings)
        bucket = settings.minio_bucket
        if not minio_client.bucket_exists(bucket):
            minio_client.make_bucket(bucket)
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": ["*"]},
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{bucket}/*"],
                }
            ],
        }
        minio_client.set_bucket_policy(bucket, json.dumps(policy))

        def handle_one(item: dict) -> dict:
            target_is_url = bool(item.get("target_is_url"))
            minio_object_key_from_url = str(item.get("minio_object_key") or "").strip()

            if not item.get("exists"):
                if target_is_url and minio_object_key_from_url:
                    json_key = posixpath.splitext(minio_object_key_from_url)[0] + ".json"
                    meta = _try_load_minio_json(minio_client=minio_client, bucket=bucket, json_key=json_key)
                    if meta:
                        if not str(item.get("alt") or "").strip():
                            item["alt"] = str(meta.get("alt") or "").strip()
                        item["img_desc"] = str(meta.get("img_desc") or "").strip()
                        item["minio_url"] = str(meta.get("minio_url") or "").strip() or _build_public_url(
                            public_base_url=settings.minio_public_base_url,
                            bucket=bucket,
                            object_key=minio_object_key_from_url,
                        )
                        meta_cache_key = str(meta.get("cache_key") or "").strip()
                        if redis_client is not None and meta_cache_key:
                            redis_client.setex(
                                meta_cache_key,
                                int(settings.redis_cache_ttl_s),
                                json.dumps(
                                    {"alt": item["alt"], "img_desc": item["img_desc"], "minio_url": item["minio_url"]},
                                    ensure_ascii=False,
                                ).encode("utf-8"),
                            )
                return item

            img_abs = Path(str(item["img_abs_path"]))
            image_bytes = img_abs.read_bytes()
            image_sha256 = hashlib.sha256(image_bytes).hexdigest()
            raw_object_key = _normalize_object_key(str(item["img_rel_path"]))
            object_key = posixpath.join(book_prefix, raw_object_key)
            json_key = posixpath.splitext(object_key)[0] + ".json"
            cache_h = hashlib.sha256()
            cache_h.update(b"|mdimg_cache=v3|")
            cache_h.update(image_sha256.encode("utf-8"))
            cache_h.update(b"|")
            cache_h.update(str(settings.qwen_vl_model).encode("utf-8"))
            cache_key = f"mdimg:{cache_h.hexdigest()}"

            if redis_client is not None:
                cached_raw = redis_client.get(cache_key)
                if cached_raw:
                    cached = json.loads(cached_raw.decode("utf-8"))
                    item["alt"] = str(cached.get("alt") or item.get("alt") or "").strip()
                    item["img_desc"] = str(cached.get("img_desc") or "").strip()
                    item["minio_url"] = str(cached.get("minio_url") or "").strip()
                    item["cache_hit"] = True

            meta_before = _try_load_minio_json(minio_client=minio_client, bucket=bucket, json_key=json_key)

            if (
                not item.get("cache_hit")
                and meta_before
                and str(meta_before.get("model") or "").strip() == str(settings.qwen_vl_model).strip()
                and str(meta_before.get("img_desc") or "").strip()
            ):
                item["alt"] = str(meta_before.get("alt") or item.get("alt") or "").strip()
                item["img_desc"] = str(meta_before.get("img_desc") or "").strip()
                item["minio_url"] = str(meta_before.get("minio_url") or "").strip() or _build_public_url(
                    public_base_url=settings.minio_public_base_url,
                    bucket=bucket,
                    object_key=object_key,
                )
                item["cache_hit"] = True
                if redis_client is not None:
                    redis_client.setex(
                        cache_key,
                        int(settings.redis_cache_ttl_s),
                        json.dumps(
                            {"alt": item["alt"], "img_desc": item["img_desc"], "minio_url": item["minio_url"]},
                            ensure_ascii=False,
                        ).encode("utf-8"),
                    )

            if (
                not item.get("cache_hit")
                and meta_before
                and str(meta_before.get("cache_key") or "").strip() == cache_key
                and str(meta_before.get("model") or "").strip() == str(settings.qwen_vl_model).strip()
            ):
                item["alt"] = str(meta_before.get("alt") or item.get("alt") or "").strip()
                item["img_desc"] = str(meta_before.get("img_desc") or item.get("img_desc") or "").strip()
                item["minio_url"] = str(meta_before.get("minio_url") or "").strip() or _build_public_url(
                    public_base_url=settings.minio_public_base_url,
                    bucket=bucket,
                    object_key=object_key,
                )
                if str(item.get("img_desc") or "").strip():
                    item["cache_hit"] = True
                    if redis_client is not None:
                        redis_client.setex(
                            cache_key,
                            int(settings.redis_cache_ttl_s),
                            json.dumps(
                                {"alt": item["alt"], "img_desc": item["img_desc"], "minio_url": item["minio_url"]},
                                ensure_ascii=False,
                            ).encode("utf-8"),
                        )
            if qwen_client is not None and (not str(item.get("img_desc") or "").strip()):
                ct = _guess_content_type(item["img_rel_path"])
                if not ct.startswith("image/"):
                    ct = "image/png"
                b64 = base64.b64encode(image_bytes).decode("utf-8")
                data_url = f"data:{ct};base64,{b64}"

                last_error = None
                for _ in range(2):
                    try:
                        result = qwen_client.describe_image(
                            image_data_url=data_url,
                            pre_text=str(item.get("pre_text") or ""),
                            next_text=str(item.get("next_text") or ""),
                            current_alt=str(item.get("alt") or ""),
                        )
                        item["alt"] = result.alt.strip()
                        item["img_desc"] = result.img_desc.strip()
                        break
                    except Exception as e:
                        last_error = e
                if not str(item.get("alt") or "").strip() or not str(item.get("img_desc") or "").strip():
                    raise last_error or ValueError("img_desc 为空")

            ct = _guess_content_type(item["img_rel_path"])
            if not ct.startswith("image/"):
                ct = "image/png"

            object_exists = False
            try:
                minio_client.stat_object(bucket, object_key)
                object_exists = True
            except Exception:
                object_exists = False
            should_overwrite = False
            if meta_before and str(meta_before.get("image_sha256") or "").strip():
                should_overwrite = str(meta_before.get("image_sha256") or "").strip() != image_sha256
            if not object_exists or should_overwrite:
                minio_client.put_object(
                    bucket,
                    object_key,
                    io.BytesIO(image_bytes),
                    length=len(image_bytes),
                    content_type=ct,
                )

            minio_url = _build_public_url(
                public_base_url=settings.minio_public_base_url,
                bucket=bucket,
                object_key=object_key,
            )
            meta = {
                "alt": item["alt"],
                "img_desc": item["img_desc"],
                "pre_text": item.get("pre_text") or "",
                "next_text": item.get("next_text") or "",
                "hash": cache_h.hexdigest(),
                "image_sha256": image_sha256,
                "model": settings.qwen_vl_model,
                "ts": int(time.time()),
                "minio_bucket": bucket,
                "minio_object_key": object_key,
                "minio_url": minio_url,
                "cache_key": cache_key,
            }
            meta_bytes = json.dumps(meta, ensure_ascii=False).encode("utf-8")
            minio_client.put_object(
                bucket,
                json_key,
                io.BytesIO(meta_bytes),
                length=len(meta_bytes),
                content_type="application/json",
            )

            item["minio_url"] = minio_url
            if redis_client is not None:
                redis_client.setex(
                    cache_key,
                    int(settings.redis_cache_ttl_s),
                    json.dumps(
                        {"alt": item["alt"], "img_desc": item["img_desc"], "minio_url": item["minio_url"]},
                        ensure_ascii=False,
                    ).encode("utf-8"),
                )
            return item

        max_workers = max(int(settings.qwen_concurrency), 1)
        futures = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for idx, item in enumerate(items):
                futures[executor.submit(_safe_handle_one, handle_one, item)] = idx
            for fut in as_completed(futures):
                idx = futures[fut]
                items[idx] = fut.result()

        replacements: list[tuple[int, int, str]] = []
        cache_hits = 0
        errors = 0
        for item in items:
            if item.get("cache_hit"):
                cache_hits += 1
            if item.get("error"):
                errors += 1
            minio_url = str(item.get("minio_url") or "").strip()
            if not minio_url:
                continue
            alt = str(item.get("alt") or "").strip()
            new_md = f"![{alt}]({minio_url})"
            replacements.append((int(item["start"]), int(item["end"]), new_md))

        md_new = md_content
        for start, end, new_text in sorted(replacements, key=lambda x: x[0], reverse=True):
            md_new = md_new[:start] + new_text + md_new[end:]

        state["md_content"] = md_new
        state["md_img_items"] = items

        if settings.md_writeback:
            md_file = Path(md_path)
            if settings.md_writeback_backup:
                bak_path = md_file.with_name(f"{md_file.name}.bak")
                if not bak_path.exists():
                    bak_path.write_text(md_content, encoding="utf-8")
            _atomic_write_text(md_file, md_new)

        log.info(
            f"-- {self.name} -- 图片处理完成 total={len(items)} replaced={len(replacements)} cache_hit={cache_hits} errors={errors}"
        )
        return state


def _safe_handle_one(fn, item: dict) -> dict:
    try:
        return fn(item)
    except Exception as e:
        item["error"] = str(e)
        return item
