"""
梯队 1 · ImportMainGraphRunner（文档导入主图）
LangGraph 编排 7 个 NodeBase 子类节点，结构按「构建 → 执行」两层拆分：

一、构建阶段（首次实例化时执行一次，之后 graph 单例复用）：
  1) _build_nodes()：7 个节点按顺序注册到 StateGraph（每个节点的 name=LangGraph 的 key）
  2) _build_edges()：
       · Entry → 条件边（PDF 分支走 NodePDFToMD；MD 分支直接走 NodeMDImg；两者都没有 → END）
       · NodePDFToMD → NodeMDImg → NodeDocumentSplit → NodeItemNameRecognition → NodeBGEEmbedding → NodeImportMilvus → END
二、执行阶段（每次 run 一次）：
  · invoke(state) → 返回 (final_state, stages_log)
  · 任意节点异常：捕获 → 包装成 RuntimeError 带上 failed_node / last_error / stages_log
三、单例：get_runner() 模块级缓存，FastAPI 里只构建一次 StateGraph（避免每次请求都新建一堆实例）。
"""
from __future__ import annotations

from threading import Lock
from typing import ClassVar

from langgraph.constants import END
from langgraph.graph import StateGraph

from shopkeeper_kb import logging_config as log
from shopkeeper_kb.workflows.node_bge_embedding import NodeBGEEmbedding
from shopkeeper_kb.workflows.node_document_split import NodeDocumentSplit
from shopkeeper_kb.workflows.node_entry import NodeEntry
from shopkeeper_kb.workflows.node_import_milvus import NodeImportMilvus
from shopkeeper_kb.workflows.node_item_name_recognition import NodeItemNameRecognition
from shopkeeper_kb.workflows.node_md_img import NodeMDImg
from shopkeeper_kb.workflows.node_pdf_to_md import NodePDFToMD
from shopkeeper_kb.workflows.state import ImportGraphState

# ================================================================
# Stage_log → Progress 百分比锚点（与 tools.ingestion 8 个阶段对齐）
# ================================================================
_STAGE_PROGRESS: dict[str, tuple[int, str]] = {
    NodeEntry.name: (15, "准备文档元数据与路由"),
    NodePDFToMD.name: (30, "将 PDF 解析为 Markdown"),
    NodeMDImg.name: (45, "上传 MD 图片到 MinIO"),
    NodeDocumentSplit.name: (60, "按章节切分为 Chunk"),
    NodeItemNameRecognition.name: (75, "识别文档主体：doc_type / 书名"),
    NodeBGEEmbedding.name: (90, "向量化：BGE-M3 Embedding"),
    NodeImportMilvus.name: (100, "写入 Milvus + Mongo 元数据"),
}


def stage_log_to_progress(stages_log: list[dict]) -> tuple[int, str, dict]:
    """
    把 LangGraph stages_log 转成 ingestion_tasks 同一套进度字段：
    返回 (progress_pct, stage, stage_extra)。

    规则：
    - 取最后一个 ok=True 的节点，映射百分比；
    - 若某节点 ok=False 失败：stage_extra["failed_node"] = 节点名；pct 停在该节点前一节点；
    - stages_log 为空：返回 (5, "queued", {})
    """
    if not stages_log:
        return 5, "queued", {}
    last_ok_idx = -1
    failed_node: str | None = None
    for i, s in enumerate(stages_log):
        if s.get("ok"):
            last_ok_idx = i
        else:
            failed_node = str(s.get("node") or s.get("name") or f"node_{i}")
            break
    pct = 5
    stage = "queued"
    extra: dict = {}
    if last_ok_idx >= 0:
        last_name = str(stages_log[last_ok_idx].get("node") or stages_log[last_ok_idx].get("name") or "")
        mapping = _STAGE_PROGRESS.get(last_name)
        if mapping:
            pct, stage = mapping
        note = str(stages_log[last_ok_idx].get("note") or "")
        if note:
            extra["note"] = note[:120]
    if failed_node:
        extra["failed_node"] = failed_node
        extra["last_error"] = str(stages_log[last_ok_idx + 1].get("note") if last_ok_idx + 1 < len(stages_log) else "")[:200]
    return pct, stage, extra


class ImportMainGraphRunner:
    """导入主图运行器：节点构建 / 边构建 / 执行 三部分分离，结构清晰。"""

    # 模块级单例（首次 get_runner() 时才实例化；不用 __new__ 避免 pytest mock 困难）
    _instance: ClassVar[ImportMainGraphRunner | None] = None
    _instance_lock: ClassVar[Lock] = Lock()

    def __init__(self) -> None:
        # 构建顺序：StateGraph → 注册节点 → 注册边 → compile → builder 丢弃（只读 graph 不再改）
        builder = StateGraph(ImportGraphState)
        self._build_nodes(builder)
        self._build_edges(builder)
        self.graph = builder.compile()

    # ================================================================
    # 构建：节点（一组 add_node 调用，按节点编号顺序排，肉眼能一眼看到 1→2→3→4→5→6→7）
    # ================================================================
    @staticmethod
    def _build_nodes(builder: StateGraph) -> None:
        builder.add_node(NodeEntry.name, NodeEntry())                                          # N0 入口 + 路由
        builder.add_node(NodePDFToMD.name, NodePDFToMD())                                      # N1 PDF → MD（MinerU）
        builder.add_node(NodeMDImg.name, NodeMDImg())                                          # N2 MD 图片上传 + 多模态
        builder.add_node(NodeDocumentSplit.name, NodeDocumentSplit())                          # N3 MD → Chunks
        builder.add_node(NodeItemNameRecognition.name, NodeItemNameRecognition())              # N4 主体识别 → doc_type
        builder.add_node(NodeBGEEmbedding.name, NodeBGEEmbedding())                            # N5 向量化
        builder.add_node(NodeImportMilvus.name, NodeImportMilvus())                            # N6 Milvus + Mongo 持久化

    # ================================================================
    # 构建：边（entry → conditional → serial → END）
    # ================================================================
    def _build_edges(self, builder: StateGraph) -> None:
        builder.set_entry_point(NodeEntry.name)

        # N0 → 条件分支
        builder.add_conditional_edges(
            NodeEntry.name,
            self._after_entry_router,
            {
                NodePDFToMD.name: NodePDFToMD.name,
                NodeMDImg.name: NodeMDImg.name,
                END: END,
            },
        )

        # PDF 分支：PDF2MD 成功后（必然落地 md_path + md_content）→ 并入 MD 主链路
        builder.add_edge(NodePDFToMD.name, NodeMDImg.name)

        # MD 主链路串行：N2 → N3 → N4 → N5 → N6 → END
        builder.add_edge(NodeMDImg.name, NodeDocumentSplit.name)
        builder.add_edge(NodeDocumentSplit.name, NodeItemNameRecognition.name)
        builder.add_edge(NodeItemNameRecognition.name, NodeBGEEmbedding.name)
        builder.add_edge(NodeBGEEmbedding.name, NodeImportMilvus.name)
        builder.add_edge(NodeImportMilvus.name, END)

    # ================================================================
    # 路由函数（条件边）：Entry 后到底走 PDF 还是 MD
    # ================================================================
    @staticmethod
    def _after_entry_router(state: ImportGraphState) -> str:
        is_pdf = bool(state.get("is_pdf_read_enabled"))
        is_md = bool(state.get("is_md_read_enabled"))
        if is_pdf:
            return NodePDFToMD.name
        if is_md:
            return NodeMDImg.name
        log.warning(f"ImportMainGraph entry router：既不是 PDF 也不是 MD，直接 END。state.keys={sorted(state.keys())}")
        return END

    # ================================================================
    # 执行：一次 invoke → 返回 (final_state, stages_log)；失败时带上 failed_node/last_error 抛出
    # ================================================================
    def run(self, state: ImportGraphState) -> tuple[ImportGraphState, list[dict]]:
        """
        运行导入主图。返回：(最终 state, stages_log 列表)。
        任一步失败：抛出 RuntimeError，message 里包含 failed_node / last_error，stages_log 在异常 args[1]（也可以从 __notes__ 取）。
        """
        final: ImportGraphState = self.graph.invoke(state)
        stages_log = list(final.get("stage_log") or [])
        failed_node = str(final.get("last_failed_node") or "")
        last_error = str(final.get("last_error") or "")
        if failed_node and last_error:
            # 任意节点异常（NodeBase 捕获写 state 后 LangGraph 也正常 END；但我们在业务层把它识别为失败，方便调用方写 ingestion_tasks.status=failed）
            msg = f"ImportMainGraph 节点 {failed_node} 失败：{last_error}"
            err = RuntimeError(msg)
            try:
                err.__notes__ = [  # type: ignore[attr-defined]
                    str({"stages_log": stages_log, "failed_node": failed_node, "last_error": last_error})
                ]
            except Exception:
                pass
            raise err
        return final, stages_log


# ================================================================
# 单例访问（FastAPI worker 进程里只构建一次 graph）
# ================================================================
def get_runner() -> ImportMainGraphRunner:
    if ImportMainGraphRunner._instance is None:
        with ImportMainGraphRunner._instance_lock:
            if ImportMainGraphRunner._instance is None:
                ImportMainGraphRunner._instance = ImportMainGraphRunner()
    return ImportMainGraphRunner._instance


__all__ = ["ImportMainGraphRunner", "get_runner"]
