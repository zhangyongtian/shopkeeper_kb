from __future__ import annotations

from typing import Any

from shopkeeper_kb.logging_config import get_logger
from shopkeeper_kb.settings import Settings, get_settings
from shopkeeper_kb.tools.mongo import get_db
from shopkeeper_kb.workflows.expert_rules import (
    CATEGORY_ANNOUNCE,
    CATEGORY_CANDLESTICK,
    CATEGORY_FUNDAMENTAL,
    CATEGORY_MASTER_WISDOM,
    CATEGORY_PSYCHOLOGY,
    CATEGORY_RISK_POSITION,
    CATEGORY_TREND,
    score_all_categories,
)
from shopkeeper_kb.workflows.state import (
    Chunk,
    DirectionT,
    ExpertRuleHit,
    PerExpertResult,
    StructuredInput,
)

logger = get_logger("shopkeeper_kb.score_per_expert")

# ================================================================
# 梯队 2.5：7 位专家独立打分（每位专家 → 1 条 PerExpertResult）
#
# 7 位专家 doc_type → category 映射（对应 init_expert_books 7 种子）
#   candlestick    → candlestick 蜡烛图形态
#   technical_trend→ trend 均线趋势
#   psychology     → psychology 交易心理
#   fundamental  → fundamental 财报（默认 disabled=true，占位财报 PDF）
#   master_wisdom→ master_wisdom 金融怪杰
#   risk_position→ risk_position 仓位风险
#   news_intel   → announce 公告/情报（HTTP 新闻不是 MinerU PDF）
# ================================================================

EXPERT_CATEGORY_MAP = {
    "candlestick": CATEGORY_CANDLESTICK,
    "technical_trend": CATEGORY_TREND,
    "psychology": CATEGORY_PSYCHOLOGY,
    "fundamental": CATEGORY_FUNDAMENTAL,
    "master_wisdom": CATEGORY_MASTER_WISDOM,
    "risk_position": CATEGORY_RISK_POSITION,
    "news_intel": CATEGORY_ANNOUNCE,
}

# 每位专家的默认 TopK chunk 数量（召回自己那本书的 TopN 最相似段落，作为 sources_local_raw 传入 state）
DEFAULT_TOPK_PER_EXPERT = 5


# ------------------------------------------------------------------
# 从 Mongo expert_books 集合取 7+N 专家配置（开放架构：admin 新增的书也会被自动当一个「新专家」）
# ------------------------------------------------------------------


def load_expert_books(settings: Settings | None = None) -> list[dict[str, Any]]:
    s = settings or get_settings()
    db = get_db(s)
    docs = list(
        db[s.coll_expert_books].find(
            {"soft_deleted": {"$ne": True}, "disabled": False},
            projection={"_id": 0},
        ).sort([("priority", 1), ("doc_type", 1)])
    )
    if not docs:
        logger.warning("expert_books 集合为空或全部 disabled；返回 7 默认专家占位（等 init_expert_books.py 跑一次即可）")
        return _fallback_seven_experts()
    return docs


def _fallback_seven_experts() -> list[dict[str, Any]]:
    return [
        {"doc_type": dt, "weight": 1.0, "display_name": n, "fixed_mantra": m, "priority": 50}
        for dt, n, m in [
            ("candlestick",    "蜡烛图形态师",  "我只看形态，不讲故事。形态说了算，其他都是噪音。"),
            ("technical_trend","趋势跟踪官",     "我不抢跑，等破位再动手。趋势为王，别跟市场较劲。"),
            ("psychology",    "行为心理师",   "情绪是最大的敌人。止损是最好的朋友。"),
            ("fundamental",   "基本面分析师", "财报是照妖镜。ROE 小于 8 的票我一概不碰。",),
            ("master_wisdom", "老交易员",     "截断亏损，让利润奔跑。第一铁律。"),
            ("risk_position", "仓位风控官",   "先算可以亏多少，再算能赚多少。仓位是生命线。"),
            ("news_intel",    "情报侦察员",   "有问题的票绝不沾边。拟减持立案直接拉黑。"),
        ]
    ]


# ================================================================
# Helper：规则总分 → 方向（bull/neutral/bear）
# ================================================================


def _score_to_direction(points: float) -> DirectionT:
    if points >= +15.0:
        return "bull"
    if points <= -15.0:
        return "bear"
    return "neutral"


def _spoken_body_template(
    doc_type: str,
    direction: DirectionT,
    score: float,
    top_hits: list[ExpertRuleHit],
) -> str:
    """合成专家发言 body（Markdown，将来 LLM 润色之前的结构化 fallback 骨架）。"""
    dir_map = {"bull": "📈 我看多", "bear": "📉 我看空", "neutral": "⏸ 我观望", "refused": "⛔ 我拒答"}
    s = f"### {dir_map.get(direction, '观望')}（打分：{score:+.1f} 分）\n\n"
    if not top_hits:
        s += "- 未命中关键规则\n"
        return s
    for i, h in enumerate(top_hits[:5], 1):
        sign = "+" if h["points"] >= 0 else ""
        n = len(h.get("evidence_text_snippets") or [])
        ev = (h.get("evidence_text_snippets") or [""])[0][:60]
        s += f"- [{i}] **{h['rule_id']}** {h['rule_description']}（{sign}{h['points']:+.1f} 分，置信度 {h.get('confidence', 0):.0%}）"
        if ev:
            s += f"\n  - 证据：_{ev}_"
        if n > 1:
            s += f"\n  - [🔍 更多证据共 {n} 条]"
        s += "\n"
    return s


# ================================================================
# 主入口：score_per_expert
# ================================================================


def score_per_expert(
    structured: StructuredInput,
    *,
    user_original_query: str = "",
    settings: Settings | None = None,
    top_k_per_expert: int = DEFAULT_TOPK_PER_EXPERT,
    _skip_sources: bool = False,
    doc_id_filter: list[str] | None = None,
) -> list[PerExpertResult]:
    """
    输入：StructuredInput（36 字段结构化输入中间结构）。
    输出：list[PerExpertResult] — 7+N 位专家（开放架构：admin 新增专家也会被自动打分）。
    _skip_sources=True：跳过 Milvus 向量召回（embedding 模型 2.2G、磁盘不够 / 未初始化时用，保证打分骨架先过）。
    doc_id_filter：只在这些 doc_id 里检索（对应书架 UI 的「仅勾选生效」开关；未传或 None=不限制）。
    """
    s = settings or get_settings()
    experts = load_expert_books(s)
    category_hits = score_all_categories(structured)

    # 全局查询 query（缺省就拼「代码+名称+行业+关键特征」，对每本书做召回）
    if user_original_query and len(user_original_query) >= 4:
        q = f"{structured['stock_name']}({structured['stock_code']}) {structured['industry_sw_l1']} {user_original_query}"
    else:
        q = " ".join([
            structured["stock_name"],
            structured["stock_code"],
            structured["industry_sw_l1"],
            " ".join(structured["chart_features"][:4]),
            f"ROE {structured['roe_ttm']:.1f}% 负债率 {structured['debt_ratio']:.1f}%",
            f"今日涨跌 {structured['change_pct_today']:+.2f}%",
        ])

    out: list[PerExpertResult] = []
    for book in experts:
        doc_type = str(book.get("doc_type") or "")
        if not doc_type:
            continue
        category = EXPERT_CATEGORY_MAP.get(doc_type)
        if category is None:
            # admin 新增专家没有内置 category → 全部 category_hits 的综合评分（所有分类合并）
            hits_flat: list[ExpertRuleHit] = []
            for cat_hits in category_hits.values():
                hits_flat.extend(cat_hits)
            category = "__all__"
        else:
            hits_flat = list(category_hits.get(category, []))

        raw_score = sum(float(h.get("points", 0.0)) for h in hits_flat if not h.get("is_veto"))
        vetoes = [h for h in hits_flat if h.get("is_veto")]
        if vetoes:
            # 该专家投票直接 refused（只看自己 category 的 veto；跨 category 的 veto 交给 compliance / generation 做全拒）
            direction: DirectionT = "refused"
        else:
            direction = _score_to_direction(raw_score)

        weight = float(book.get("weight") or 1.0)
        weighted_score = round(raw_score * weight, 2)
        fixed_mantra = str(book.get("fixed_mantra") or "")
        display_name = str(book.get("display_name") or doc_type)
        color = str(book.get("color") or "#8ecae6")
        _ = color  # 骨架阶段先不用，3.3 合成 SSE 事件时会用

        # 召回自己 doc_type 的 TopK（开放架构：如果 admin 新增专家 doc_type 也能正确召回自己的 chunks）
        # 注意：embedding 模型 ~2.2GB 懒加载，首次调用会等 5~20s；磁盘空间不够 / 模型未初始化 → 走空列表降级，
        # 不阻塞 7 专家打分骨架（P1-2 优雅降级）。_skip_sources=True 时完全不触发 embedding 加载。
        sources_local_raw: list[Chunk] = []
        if not _skip_sources:
            try:
                from shopkeeper_kb.tools.ingestion import search_chunks as _sc
            except Exception:
                _sc = None  # type: ignore[assignment]
            if _sc is not None:
                try:
                    local_chunks_raw = _sc(
                        q,
                        top_k=top_k_per_expert,
                        doc_type_filter=None if category == "__all__" else [doc_type],
                        doc_id_filter=doc_id_filter,
                        settings=s,
                    )
                    for h in local_chunks_raw:
                        sources_local_raw.append({  # type: ignore[typeddict-unknown-key]
                            "doc_id": str(h.get("doc_id") or ""),
                            "doc_type": str(h.get("doc_type") or doc_type),
                            "chunk_id": str(h.get("chunk_id") or ""),
                            "chunk_level": "child",
                            "parent_id": "",
                            "section_path": str(h.get("section_path") or ""),
                            "position": int(h.get("position") or len(sources_local_raw)),
                            "page_number": int(h.get("page_number") or -1),
                            "token_count": 0,
                            "embed_text": "",
                            "display_text": str(h.get("display_text_preview") or ""),
                            "image_urls": list(h.get("image_urls") or []),
                            "image_alts": [],
                            "quality": "normal",
                        })
                except Exception as e:
                    logger.debug(f"search_chunks doc_type={doc_type} fail (expected empty collection): {e}")
                    sources_local_raw = []

        # P0-1 预留：把 supporting_source_idx = 本地 sources 的下标（生成节点合并全局 sources 后重写）；rules 按分值排序 top5 展示
        hits_sorted = sorted(
            hits_flat,
            key=lambda h: (-abs(float(h.get("points", 0.0)))),
        )[:6]
        for idx, h in enumerate(hits_sorted):
            # 本地 sources 的第 idx 条（不保证每一条 rule 都有对应 chunk，先填 idx，后面 generation 重写为全局 idx）
            if idx < len(sources_local_raw) and not h.get("supporting_source_idx"):
                h["supporting_source_idx"] = [idx]  # type: ignore[typeddict-item]

        opening = (f"{fixed_mantra} " if fixed_mantra else "") + (
            f"我是{display_name}，针对 {structured['stock_name']}({structured['stock_code']}) 我的观点是："
        )
        if direction == "bull":
            opening += "强烈看多。"
        elif direction == "bear":
            opening += "强烈看空。"
        elif direction == "neutral":
            opening += "建议观望先不动。"
        else:
            opening += "这票我拒答不碰。"

        spoken_body = _spoken_body_template(doc_type, direction, raw_score, hits_sorted)

        out.append({
            "doc_type": doc_type,
            "direction": direction,
            "score": round(raw_score, 2),
            "weighted_score": weighted_score,
            "reason_rules": hits_sorted,
            "spoken_opening": opening,
            "spoken_body": spoken_body,
            "sources_local_raw": sources_local_raw,
        })

    return out


__all__ = ["score_per_expert", "load_expert_books"]
