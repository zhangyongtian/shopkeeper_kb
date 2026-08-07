"""
查询/导入流程节点基类
定义统一的节点接口规范：
  1) 自动打 stage_log（每个节点成功/失败都追加到 state.stage_log，供 ingestion_tasks.failed_stage 写库）
  2) 捕获异常 → 写入 state.last_error / last_failed_node → 再 raise（让上层 LangGraph 也能捕获并走 failed 分支）
  3) 提供统一的「我消费什么字段 / 我写什么字段」的 docstring 规范（子类 __doc__ 里写清楚）
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod

from shopkeeper_kb import logging_config as log
from shopkeeper_kb.workflows.state import ImportGraphState


class NodeBase(ABC):
    name: str = "node_base"  # 子类必须重写：LangGraph 里注册的 key，也是 stage_log.node 的值

    # ---- 子类可选声明（用于静态/动态自检：run 前检查依赖） ----
    consumes_fields: tuple[str, ...] = ()    # 我运行前 state 必须有这些字段（空=不检查）
    produces_fields: tuple[str, ...] = ()    # 我运行后会写入这些字段（仅文档 / debug 用）

    def __init__(self) -> None:
        if self.name in {"node_base", ""}:
            raise ValueError(f"子类 {self.__class__.__name__} 必须覆盖 name 属性")

    # ------------------------------------------------------------------
    # 对外调用入口（统一打 log + 打 stage_log + 异常捕获写 last_error）
    # ------------------------------------------------------------------
    def __call__(self, state: ImportGraphState) -> ImportGraphState:
        stage_log = list(state.get("stage_log") or [])
        t0 = time.time()
        # 前置检查：之前节点已经失败（last_failed_node 非空）→ 直接 skip，不再继续跑 process
        prev_failed = bool(state.get("last_failed_node"))
        try:
            if prev_failed:
                partial: dict = {}
                note = f"skip（上一节点 {state.get('last_failed_node')} 已失败）"
                ok = False
            else:
                self._ensure_consumed(state)
                log.info(f"-- {self.name} -- 开始执行")
                partial = self.process(state) or {}
                note = self._summarize(partial)
                ok = True
            merged: ImportGraphState = {**state, **partial}  # type: ignore[misc]
            stage_log.append({
                "node": self.name,
                "ts": int(time.time() * 1000),
                "elapsed_ms": int((time.time() - t0) * 1000),
                "ok": ok,
                "note": note,
            })
            merged["stage_log"] = stage_log
            if ok:
                log.info(f"-- {self.name} -- 执行完成 ({stage_log[-1]['elapsed_ms']}ms)")
            else:
                log.info(f"-- {self.name} -- 跳过（prev failed：{note}）")
            return merged
        except Exception as e:
            stage_log.append({
                "node": self.name,
                "ts": int(time.time() * 1000),
                "elapsed_ms": int((time.time() - t0) * 1000),
                "ok": False,
                "note": f"{type(e).__name__}: {e}",
            })
            partial_fail: ImportGraphState = {  # type: ignore[misc]
                **state,
                "stage_log": stage_log,
                "last_error": f"{type(e).__name__}: {e}",
                "last_failed_node": self.name,
            }
            log.error(f"-- {self.name} -- 执行异常: {e}")
            return partial_fail

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
    def _ensure_consumed(self, state: ImportGraphState) -> None:
        if not self.consumes_fields:
            return
        missing = [f for f in self.consumes_fields if state.get(f) in (None, "", [])]
        if missing:
            raise ValueError(f"{self.name} 缺少必须字段: {missing}（state.keys={sorted(state.keys())}）")

    @staticmethod
    def _summarize(partial: dict) -> str:
        """子类可重写：stage_log.note 里写一句简短总结（例：chunks=32 / embeddings=32 / milvus=32）。"""
        if not partial:
            return ""
        # 默认取几个常见的数，超过 64 字符截断
        interesting = ["chunks", "chunk_embeddings", "milvus_inserted_count", "mongo_inserted_count", "item_name", "doc_type"]
        parts = [f"{k}={len(partial[k]) if hasattr(partial[k], '__len__') and not isinstance(partial[k], (str, bytes)) else partial[k]}" for k in interesting if k in partial and partial[k] not in (None, [], 0, "")]
        if not parts:
            return "ok"
        s = ", ".join(parts)
        return s[:120] + ("…" if len(s) > 120 else "")

    # ------------------------------------------------------------------
    # 子类实现
    # ------------------------------------------------------------------
    @abstractmethod
    def process(self, state: ImportGraphState) -> ImportGraphState | dict:
        """
        子类具体逻辑，返回一个「partial state dict」即可（不要返回整份 state 大拷贝）。
        例：return {"chunks": chunks, "doc_type": "candlestick"}
        """

