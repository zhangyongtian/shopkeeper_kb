from __future__ import annotations

import re
from pathlib import Path

from shopkeeper_kb import logging_config as log
from shopkeeper_kb.settings import get_settings
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
        context_chars = max(int(getattr(settings, "md_img_context_chars", 800)), 0)

        items = []
        for match in _MD_IMAGE_PATTERN.finditer(md_content):
            alt = match.group(1) or ""
            raw_target = match.group(2) or ""
            img_rel_path = _parse_md_image_target(raw_target)
            if not img_rel_path:
                continue

            img_path = Path(img_rel_path)
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
            }
            items.append(item)

        state["md_img_items"] = items

        log.info(f"-- {self.name} -- 识别图片数量: {len(items)}; context_chars={context_chars}")
        for idx, item in enumerate(items, start=1):
            pre_preview = item["pre_text"].replace("\n", " ")
            pre_preview = pre_preview[-150:] if len(pre_preview) > 150 else pre_preview
            next_preview = item["next_text"].replace("\n", " ")
            next_preview = next_preview[:150] + ("..." if len(next_preview) > 150 else "")
            log.info(
                f"-- {self.name} -- 图片[{idx}] rel={item['img_rel_path']} abs={item['img_abs_path']} exists={item['exists']} alt={item['alt']}"
            )
            log.info(f"-- {self.name} -- 图片[{idx}] pre_preview={pre_preview}")
            log.info(f"-- {self.name} -- 图片[{idx}] next_preview={next_preview}")
        return state
