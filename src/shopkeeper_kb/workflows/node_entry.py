from __future__ import annotations

from pathlib import Path

from shopkeeper_kb import logging_config as log
from shopkeeper_kb.workflows.base_node import NodeBase
from shopkeeper_kb.workflows.state import ImportGraphState


class NodeEntry(NodeBase):
    """
    入口节点：任务分发
    - 校验 local_file_path 是否存在
    - 根据后缀：.pdf → 走 PDF 分支；.md → 读 md_content，写 md_path / md_content / file_title
    """

    name = "node_entry"
    consumes_fields = ("local_file_path",)
    produces_fields = ("is_pdf_read_enabled", "is_md_read_enabled", "file_title", "pdf_path", "md_path", "md_content")

    def process(self, state: ImportGraphState) -> dict:
        log.info(f"-- {self.name} -- 结点开始处理")
        local_file_path = state.get("local_file_path", "")
        p = Path(local_file_path)
        if not p.exists():
            raise FileNotFoundError(f"文件不存在：{local_file_path}")
        file_title = p.stem
        suffix = p.suffix.lower()

        if suffix == ".pdf":
            return {
                "is_pdf_read_enabled": True,
                "is_md_read_enabled": False,
                "file_title": file_title,
                "pdf_path": str(p.resolve()),
            }
        if suffix == ".md":
            text = p.read_text(encoding="utf-8", errors="replace")
            return {
                "is_pdf_read_enabled": False,
                "is_md_read_enabled": True,
                "file_title": file_title,
                "md_path": str(p.resolve()),
                "md_content": text,
            }
        raise ValueError(f"不支持的文件类型：{suffix}（仅支持 .pdf / .md）")

