from shopkeeper_kb import logging_config as log
from shopkeeper_kb.workflows.base_node import NodeBase
from shopkeeper_kb.workflows.state import ImportGraphState
from pathlib import Path
class NodeEntry(NodeBase):
    """
    入口节点：任务分发
    """

    name = "node_entry"

    def process(self, state: ImportGraphState):
        log.info(f"-- {self.name} -- 结点开始处理")
        local_file_path = state.get("local_file_path", "")
        local_file_path_obj = Path(local_file_path)
        if not local_file_path_obj.exists():
            raise FileNotFoundError(f"文件不存在：{local_file_path}")

        file_title = local_file_path_obj.stem
        suffix = local_file_path_obj.suffix

        if suffix.lower() == ".pdf":
            return {
                "is_pdf_read_enabled": True,
                "file_title": file_title,
                "pdf_path": str(local_file_path_obj)
            }

        elif suffix.lower() == ".md":
            state["is_md_read_enabled"] = True
            state["file_title"] = file_title
            state["md_path"] = str(local_file_path_obj)
            return state
        else:
            raise ValueError(f"不支持的文件类型：{suffix}")
