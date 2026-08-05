from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from shopkeeper_kb import logging_config as log
from shopkeeper_kb.settings import get_settings
from shopkeeper_kb.workflows.base_node import NodeBase
from shopkeeper_kb.workflows.state import Chunk, ImportGraphState, MDImgItem


_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*)$")
_HR_PATTERN = re.compile(r"^\s*(?:---|\*\*\*|___)\s*$")
_CODE_FENCE_PATTERN = re.compile(r"^\s*```")
_LIST_PATTERN = re.compile(r"^\s*(?:[-+*]|\d+\.)\s+")
_TABLE_PATTERN = re.compile(r"^\s*\|.+\|\s*$")
_MD_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_TABLE_SEPARATOR_HINT = re.compile(r"-{3,}")
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[。！？；?!;])\s+")


def _normalize_newlines(text: str) -> str:
    """
    统一换行符，避免 Windows / macOS 换行导致的切分偏差。
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _collapse_blank_lines(text: str) -> str:
    """
    把 3+ 个连续空行压缩为 2 个，减少无意义空白对 chunk 长度的干扰。
    """
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _parse_md_image_target(raw: str) -> str:
    """
    解析 ![alt](target) 里的 target，去掉 <...> 包裹与 title 等尾随内容。
    """
    value = (raw or "").strip()
    if value.startswith("<") and value.endswith(">") and len(value) >= 3:
        value = value[1:-1].strip()
    if not value:
        return ""

    token = value.split()[0].strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}:
        token = token[1:-1].strip()
    return token


def _build_img_desc_map(items: list[MDImgItem]) -> dict[str, str]:
    """
    从 NodeMDImg 的 md_img_items 构建 url -> img_desc 的映射。

    说明：
    - NodeMDImg 会把图片链接写回为 minio_url（通常是 http(s)）
    - 召回时我们希望把 img_desc 这种“语义”写入 embed_text，但不直接塞 URL
    """
    result: dict[str, str] = {}
    for item in items or []:
        url = str(item.get("minio_url") or "").strip()
        desc = str(item.get("img_desc") or "").strip()
        if url and desc and url not in result:
            result[url] = desc
    return result


def _md_to_blocks(md: str) -> list[dict]:
    """
    把 Markdown 解析为“结构块（block）”，用于结构感知切分。

    为什么要 block？
    - 直接按字数硬切，会把表格/列表/代码块切碎，语义会断裂，召回会变差
    - block 保证这些结构尽量整体保留，然后再按长度组合成 chunk
    """
    lines = md.split("\n")
    blocks: list[dict] = []

    def flush_paragraph(buf: list[str]) -> None:
        if not buf:
            return
        text = "\n".join(buf).strip()
        if text:
            blocks.append({"type": "paragraph", "text": text})
        buf.clear()

    i = 0
    paragraph_buf: list[str] = []
    while i < len(lines):
        line = lines[i]

        if _CODE_FENCE_PATTERN.match(line):
            flush_paragraph(paragraph_buf)
            code_lines = [line]
            i += 1
            while i < len(lines):
                code_lines.append(lines[i])
                if _CODE_FENCE_PATTERN.match(lines[i]):
                    i += 1
                    break
                i += 1
            blocks.append({"type": "code", "text": "\n".join(code_lines).rstrip()})
            continue

        m_heading = _HEADING_PATTERN.match(line)
        if m_heading:
            flush_paragraph(paragraph_buf)
            blocks.append({"type": "heading", "text": line.rstrip(), "level": len(m_heading.group(1)), "title": m_heading.group(2).strip()})
            i += 1
            continue

        if _HR_PATTERN.match(line):
            flush_paragraph(paragraph_buf)
            blocks.append({"type": "hr", "text": line.rstrip()})
            i += 1
            continue

        if not line.strip():
            flush_paragraph(paragraph_buf)
            i += 1
            continue

        if _LIST_PATTERN.match(line):
            flush_paragraph(paragraph_buf)
            list_lines = [line.rstrip()]
            i += 1
            while i < len(lines) and lines[i].strip() and _LIST_PATTERN.match(lines[i]):
                list_lines.append(lines[i].rstrip())
                i += 1
            blocks.append({"type": "list", "text": "\n".join(list_lines).rstrip()})
            continue

        if _TABLE_PATTERN.match(line):
            flush_paragraph(paragraph_buf)
            table_lines = [line.rstrip()]
            i += 1
            while i < len(lines) and lines[i].strip() and _TABLE_PATTERN.match(lines[i]):
                table_lines.append(lines[i].rstrip())
                i += 1
            blocks.append({"type": "table", "text": "\n".join(table_lines).rstrip()})
            continue

        paragraph_buf.append(line.rstrip())
        i += 1

    flush_paragraph(paragraph_buf)
    return blocks


def _assign_section_paths(blocks: list[dict]) -> None:
    """
    为每个 block 计算 section_path（标题链）。

    section_path 的作用：
    - 为 chunk 提供“语境”，减少同一句话在不同章节下的歧义
    - 为后续做章节聚合（Parent-Child Retrieval）预留关键字段
    """
    stack: list[tuple[int, str]] = []
    current_path = "root"
    for block in blocks:
        if block.get("type") == "heading":
            level = int(block.get("level") or 1)
            title = str(block.get("title") or "").strip() or "untitled"
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            current_path = "/".join([t for _, t in stack]) if stack else "root"
        block["section_path"] = current_path


def _extract_images_from_display(text: str) -> tuple[list[str], list[str]]:
    """
    从 display_text 中提取图片 URL 与 alt，供前端展示/图集使用。
    """
    urls: list[str] = []
    alts: list[str] = []
    for m in _MD_IMAGE_PATTERN.finditer(text):
        alt = (m.group(1) or "").strip()
        target = _parse_md_image_target(m.group(2) or "")
        if target:
            urls.append(target)
        if alt:
            alts.append(alt)
    return urls, alts


def _rewrite_images_for_embed(display_text: str, *, img_desc_map: dict[str, str]) -> str:
    """
    把 display_text 中的图片 Markdown 替换为纯文本语义（alt + img_desc），避免 URL 污染向量。
    """
    def repl(match: re.Match[str]) -> str:
        alt = (match.group(1) or "").strip()
        target = _parse_md_image_target(match.group(2) or "")
        desc = (img_desc_map.get(target or "") or "").strip()

        parts: list[str] = []
        if alt:
            parts.append(f"图示：{alt}")
        else:
            parts.append("图示")
        if desc:
            parts.append(f"图像说明：{desc}")
        return "\n".join(parts)

    value = _MD_IMAGE_PATTERN.sub(repl, display_text)
    value = _collapse_blank_lines(value)
    return value


def _count_tokens(text: str, *, model_name: str | None = None) -> int:
    """
    估算 token 数量（优先 tiktoken；不可用则降级为启发式估算）。

    token-aware 是顶级 RAG 切分的基础：字符数和 token 数并不等价。
    """
    value = text or ""
    try:
        import tiktoken  # type: ignore

        if model_name:
            enc = tiktoken.encoding_for_model(model_name)
        else:
            enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(value))
    except Exception:
        pass

    cjk = len(re.findall(r"[\u4e00-\u9fff]", value))
    words = len(re.findall(r"[A-Za-z0-9_]+", value))
    punct = len(re.findall(r"[^\sA-Za-z0-9_\u4e00-\u9fff]", value))
    return cjk + int(words * 0.75) + int(punct * 0.25)


def _make_chunk_id(section_path: str, display_text: str) -> str:
    """
    生成稳定 chunk_id：相同输入得到相同 id（便于去重与溯源）。
    """
    h = hashlib.sha256()
    h.update(section_path.encode("utf-8"))
    h.update(b"\n")
    h.update(display_text.encode("utf-8", errors="replace"))
    return h.hexdigest()[:24]


def _is_table_separator_line(line: str) -> bool:
    """
    判断 Markdown 表格的分隔线（常见形态：| --- | --- | 或 | :--- | ---: |）。
    """
    value = (line or "").strip()
    if "|" not in value:
        return False
    return bool(_TABLE_SEPARATOR_HINT.search(value))


def _split_oversize_block(
    *,
    text: str,
    block_type: str,
    max_tokens: int,
    model_name: str | None,
) -> list[str]:
    """
    当单个 block 的 token 数超过 max_tokens 时，做结构保持的兜底拆分。

    目标：
    - code：每个分片仍保持 fenced 结构（``` 开头 + ``` 结尾）
    - table：每个分片仍保持可渲染表格（尽量重复表头+分隔线）
    - 其它：按行拆分
    """
    if max_tokens <= 0:
        return [text]

    value = (text or "").rstrip()
    if _count_tokens(value, model_name=model_name) <= max_tokens:
        return [value]

    lines = value.split("\n")
    if not lines:
        return [value]

    if block_type == "code":
        open_fence = lines[0].rstrip()
        close_fence = "```"
        inner = lines[1:]
        if len(lines) >= 2 and _CODE_FENCE_PATTERN.match(lines[-1]):
            close_fence = lines[-1].rstrip()
            inner = lines[1:-1]
        base_text = "\n".join([open_fence, close_fence]).rstrip()
        if _count_tokens(base_text, model_name=model_name) >= max_tokens:
            return [value]

        parts: list[str] = []
        buf: list[str] = []
        for ln in inner:
            candidate = "\n".join([open_fence, *buf, ln.rstrip("\n"), close_fence]).rstrip()
            if buf and _count_tokens(candidate, model_name=model_name) > max_tokens:
                part = "\n".join([open_fence, *buf, close_fence]).rstrip()
                parts.append(part)
                buf = []
            buf.append(ln.rstrip("\n"))
        part = "\n".join([open_fence, *buf, close_fence]).rstrip()
        parts.append(part)
        return parts

    if block_type == "table":
        header: list[str] = []
        data_lines = lines
        if len(lines) >= 2 and _is_table_separator_line(lines[1]):
            header = [lines[0].rstrip(), lines[1].rstrip()]
            data_lines = [ln.rstrip() for ln in lines[2:]]
        else:
            data_lines = [ln.rstrip() for ln in lines]

        if header and _count_tokens("\n".join(header), model_name=model_name) >= max_tokens:
            return [value]

        parts: list[str] = []
        buf: list[str] = []
        for ln in data_lines:
            candidate_lines = [*header, *buf, ln] if header else [*buf, ln]
            if buf and _count_tokens("\n".join(candidate_lines), model_name=model_name) > max_tokens:
                part_lines = [*header, *buf] if header else [*buf]
                parts.append("\n".join(part_lines).rstrip())
                buf = []
            buf.append(ln)

        part_lines = [*header, *buf] if header else [*buf]
        parts.append("\n".join(part_lines).rstrip())
        return parts

    parts: list[str] = []
    buf: list[str] = []
    for ln in lines:
        ln = ln.rstrip()
        candidate_lines = [*buf, ln]
        if buf and _count_tokens("\n".join(candidate_lines), model_name=model_name) > max_tokens:
            parts.append("\n".join(buf).rstrip())
            buf = []
        buf.append(ln)
    if buf:
        parts.append("\n".join(buf).rstrip())
    return parts


def _split_sentences(text: str) -> list[str]:
    """
    把一段自然语言拆成句子级单元，用于生成更小、更尖锐的检索 chunk。
    """
    value = (text or "").strip()
    if not value:
        return []
    value = re.sub(r"\s+", " ", value).strip()
    parts = [p.strip() for p in _SENTENCE_SPLIT_PATTERN.split(value) if p.strip()]
    return parts if parts else [value]


def _split_list_items(text: str) -> list[str]:
    """
    把列表 block 拆成“列表项”单元。
    """
    lines = [ln.rstrip() for ln in (text or "").split("\n") if ln.strip()]
    if not lines:
        return []

    items: list[str] = []
    buf: list[str] = []
    for ln in lines:
        if _LIST_PATTERN.match(ln):
            if buf:
                items.append("\n".join(buf).rstrip())
                buf = []
            buf.append(ln)
        else:
            if buf:
                buf.append(ln)
            else:
                buf = [ln]
    if buf:
        items.append("\n".join(buf).rstrip())
    return items


def _classify_quality(text: str) -> str:
    """
    对内容质量做轻量标记：low 通常代表版权页/CIP/广告/发行信息等低价值内容。
    """
    value = (text or "").strip()
    if not value:
        return "low"

    patterns = [
        r"\bISBN\b",
        r"\bCIP\b",
        r"版权所有",
        r"未经.*许可",
        r"出版(?:社|人)",
        r"印刷",
        r"经销",
        r"责任编辑",
        r"定\s*价",
        r"书号",
        r"国家版本馆",
    ]
    if any(re.search(p, value, flags=re.IGNORECASE) for p in patterns):
        return "low"
    return "normal"


def _make_doc_id(*, md_path: str, file_title: str) -> str:
    """
    生成稳定 doc_id：优先使用 md_path，否则退化为 file_title。
    """
    seed = (md_path or file_title or "document").strip()
    h = hashlib.sha256(seed.encode("utf-8", errors="replace")).hexdigest()
    return h[:24]


def _make_parent_id(*, doc_id: str, section_path: str) -> str:
    """
    生成父级聚合标识：同一文档同一章节应稳定一致。
    """
    h = hashlib.sha256()
    h.update(doc_id.encode("utf-8"))
    h.update(b"\n")
    h.update(section_path.encode("utf-8", errors="replace"))
    return h.hexdigest()[:24]


def _build_chunk(
    *,
    doc_id: str,
    chunk_level: str,
    parent_id: str,
    position: int,
    section_path: str,
    file_title: str,
    display_text: str,
    img_desc_map: dict[str, str],
    overlap_text: str,
    model_name: str | None,
) -> Chunk:
    """
    构建单个 Chunk（方案 2）。
    """
    display_text = _collapse_blank_lines(display_text)
    image_urls, image_alts = _extract_images_from_display(display_text)
    embed_body = _rewrite_images_for_embed(display_text, img_desc_map=img_desc_map)

    embed_parts: list[str] = []
    if file_title:
        embed_parts.append(f"标题：{file_title}")
    if section_path:
        embed_parts.append(f"章节：{section_path}")
    if overlap_text:
        embed_parts.append(overlap_text)
    if embed_body:
        embed_parts.append(embed_body)

    embed_text = "\n\n".join([p for p in embed_parts if p.strip()]).strip() + "\n"
    quality = _classify_quality(embed_body)
    token_count = _count_tokens(embed_text, model_name=model_name)
    chunk: Chunk = {
        "doc_id": doc_id,
        "chunk_id": _make_chunk_id(section_path, display_text),
        "chunk_level": chunk_level,
        "parent_id": parent_id,
        "section_path": section_path,
        "position": position,
        "token_count": token_count,
        "embed_text": embed_text,
        "display_text": display_text + "\n",
        "image_urls": image_urls,
        "image_alts": image_alts,
        "quality": quality,
    }
    return chunk


class NodeDocumentSplit(NodeBase):
    """
    文档切分节点：智能文档切片（方案 2：展示与向量解耦）。

    设计要点（对应你要的“最强方案”）：
    1) 结构感知：先把 MD 拆成 block（标题/段落/列表/表格/代码块...），避免切碎结构
    2) 章节语境：为每个 block 计算 section_path，并确保 chunk 不跨章节
    3) 双文本：display_text 用于展示（保留图片链接），embed_text 用于向量（去 URL + 融合图片语义）
    4) 图片可召回：把 alt/img_desc 写入 embed_text，同时把 image_urls/image_alts 作为结构化字段输出
    """

    name = "node_document_split"

    def process(self, state: ImportGraphState):
        log.info(f"-- {self.name} -- 结点开始处理")

        settings = get_settings()
        md_content = state.get("md_content", "")
        if not md_content:
            raise ValueError("state.md_content 为空")

        file_title = str(state.get("file_title") or "").strip()
        if not file_title:
            md_path = str(state.get("md_path") or "").strip()
            if md_path:
                file_title = Path(md_path).stem

        model_name = str(getattr(settings, "doc_split_token_model", "") or "").strip() or None
        target_tokens = int(getattr(settings, "doc_split_child_target_tokens", 260))
        max_tokens = int(getattr(settings, "doc_split_child_max_tokens", 360))
        overlap_units = int(getattr(settings, "doc_split_overlap_units", 1))
        min_tokens = int(getattr(settings, "doc_split_child_min_tokens", 80))

        target_tokens = max(target_tokens, 80)
        max_tokens = max(max_tokens, target_tokens)
        overlap_units = max(overlap_units, 0)
        min_tokens = max(min_tokens, 0)

        md_norm = _collapse_blank_lines(_normalize_newlines(md_content))
        blocks = _md_to_blocks(md_norm)
        _assign_section_paths(blocks)

        img_items = state.get("md_img_items") or []
        img_desc_map = _build_img_desc_map(img_items)

        chunks: list[Chunk] = []
        md_path_value = str(state.get("md_path") or "").strip()
        doc_id = _make_doc_id(md_path=md_path_value, file_title=file_title)
        current_section = "root"
        position = 0
        current_display_units: list[str] = []
        current_embed_units: list[str] = []
        current_tokens = 0
        prev_overlap_units: list[str] = []

        def flush_current() -> None:
            nonlocal current_display_units, current_embed_units, current_tokens, position, prev_overlap_units
            if not current_display_units:
                return

            display_text = "\n\n".join(current_display_units).strip()
            overlap_text = "\n\n".join(prev_overlap_units).strip()
            parent_id = _make_parent_id(doc_id=doc_id, section_path=current_section)
            chunk = _build_chunk(
                doc_id=doc_id,
                chunk_level="child",
                parent_id=parent_id,
                position=position,
                section_path=current_section,
                file_title=file_title,
                display_text=display_text,
                img_desc_map=img_desc_map,
                overlap_text=overlap_text,
                model_name=model_name,
            )

            if min_tokens > 0 and chunks and chunk["section_path"] == chunks[-1]["section_path"]:
                if chunk["token_count"] < min_tokens:
                    merged_display = (chunks[-1]["display_text"].rstrip() + "\n\n" + chunk["display_text"].lstrip()).strip()
                    merged_chunk = _build_chunk(
                        doc_id=doc_id,
                        chunk_level="child",
                        parent_id=parent_id,
                        position=chunks[-1]["position"],
                        section_path=current_section,
                        file_title=file_title,
                        display_text=merged_display,
                        img_desc_map=img_desc_map,
                        overlap_text="",
                        model_name=model_name,
                    )
                    chunks[-1] = merged_chunk
                    prev_overlap_units = []
                else:
                    chunks.append(chunk)
                    position += 1
            else:
                chunks.append(chunk)
                position += 1

            prev_overlap_units = current_embed_units[-overlap_units:] if overlap_units > 0 else []
            current_display_units = []
            current_embed_units = []
            current_tokens = 0

        def push_unit(*, unit_display: str, unit_embed: str) -> None:
            nonlocal current_display_units, current_embed_units, current_tokens, prev_overlap_units
            unit_embed = (unit_embed or "").strip()
            if not unit_embed:
                return

            unit_tokens = _count_tokens(unit_embed, model_name=model_name)
            if current_embed_units and (current_tokens + unit_tokens) > max_tokens:
                flush_current()

            if unit_tokens > max_tokens and not current_embed_units:
                for part in _split_oversize_block(
                    text=unit_display,
                    block_type="paragraph",
                    max_tokens=max_tokens,
                    model_name=model_name,
                ):
                    part_embed = _rewrite_images_for_embed(part, img_desc_map=img_desc_map)
                    current_display_units = [part]
                    current_embed_units = [part_embed]
                    current_tokens = _count_tokens(part_embed, model_name=model_name)
                    flush_current()
                return

            current_display_units.append(unit_display)
            current_embed_units.append(unit_embed)
            current_tokens += unit_tokens
            if current_tokens >= target_tokens:
                flush_current()

        for block in blocks:
            section_path = str(block.get("section_path") or "root")
            block_type = str(block.get("type") or "").strip()
            text = str(block.get("text") or "").strip()
            if not text:
                continue

            if section_path != current_section:
                flush_current()
                current_section = section_path
                prev_overlap_units = []

            if block_type == "paragraph":
                for sent in _split_sentences(text):
                    sent_embed = _rewrite_images_for_embed(sent, img_desc_map=img_desc_map)
                    push_unit(unit_display=sent, unit_embed=sent_embed)
                continue

            if block_type == "list":
                for item in _split_list_items(text):
                    item_embed = _rewrite_images_for_embed(item, img_desc_map=img_desc_map)
                    push_unit(unit_display=item, unit_embed=item_embed)
                continue

            if block_type in {"table", "code"}:
                block_embed = _rewrite_images_for_embed(text, img_desc_map=img_desc_map)
                block_tokens = _count_tokens(block_embed, model_name=model_name)
                if block_tokens > max_tokens:
                    for part in _split_oversize_block(
                        text=text,
                        block_type=block_type,
                        max_tokens=max_tokens,
                        model_name=model_name,
                    ):
                        part_embed = _rewrite_images_for_embed(part, img_desc_map=img_desc_map)
                        push_unit(unit_display=part, unit_embed=part_embed)
                else:
                    push_unit(unit_display=text, unit_embed=block_embed)
                continue

            other_embed = _rewrite_images_for_embed(text, img_desc_map=img_desc_map)
            push_unit(unit_display=text, unit_embed=other_embed)

        flush_current()

        state["chunks"] = chunks
        export_enabled = bool(getattr(settings, "doc_split_export_json", True))
        if export_enabled:
            doc_dir = Path(getattr(settings, "doc_dir", "/home/roott/work/doc"))
            export_dir = Path(getattr(settings, "doc_json_data_dir", str(doc_dir / "json_data")))
            export_dir.mkdir(parents=True, exist_ok=True)

            safe_title = re.sub(r"[\\\\/]+", "-", file_title).strip() or "document"
            full_payload = {
                "schema_version": "chunk.v2",
                "file_title": file_title,
                "md_path": md_path_value,
                "chunk_count": len(chunks),
                "chunks": chunks,
            }
            sample_payload = {
                "schema_version": "chunk.v2",
                "file_title": file_title,
                "md_path": md_path_value,
                "chunk_count": len(chunks),
                "sample_size": min(len(chunks), 10),
                "chunks": chunks[:10],
            }

            full_file = export_dir / f"{safe_title}.chunks.v2.full.json"
            sample_file = export_dir / f"{safe_title}.chunks.v2.sample.json"
            full_file.write_text(json.dumps(full_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            sample_file.write_text(json.dumps(sample_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        log.info(
            f"-- {self.name} -- 切分完成 chunks={len(chunks)} target_tokens={target_tokens} max_tokens={max_tokens} overlap_units={overlap_units}"
        )
        return state
