"""
梯队 3.1 ask_agent：LangGraph 5 节点全链路骨架，一次 invoke 出完整分析结果
（不依赖任何 LLM，完全走 2.1~2.5 本地模块 + 模板合成，保证磁盘/网络都不行时也能跑通）。

节点顺序（严格不跳步）：
  N1 extract_features     → state.structured / is_hypothetical / override_applied
  N2 compliance_fence     → state.compliance；passed=False → 路由到 END
  N3 score_per_expert(7)  → state.per_expert_results（每位专家独立方向/打分/本地 TopK 引用）
  N4 merge_sources        → state.sources_global_final（P0-1 合并去重 + 重写 supporting_source_idx 为全局下标）
  N5 generation           → state.final_answer_markdown / final_trade_plan / final_direction / segments
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

from langgraph.constants import END
from langgraph.graph import StateGraph

from shopkeeper_kb.logging_config import get_logger
from shopkeeper_kb.settings import Settings, get_settings
from shopkeeper_kb.workflows.ask_state import AskGraphState, AskGraphUserInput
from shopkeeper_kb.workflows.compliance_fence import ComplianceResult, check_compliance
from shopkeeper_kb.workflows.expert_rules import has_any_veto
from shopkeeper_kb.workflows.extract_features import build_structured_input, detect_hypothetical_modifiers
from shopkeeper_kb.workflows.score_per_expert import score_per_expert
from shopkeeper_kb.workflows.state import (
    ExpertRuleHit,
    FinalTradePlan,
    SourceCardItem,
)

logger = get_logger("shopkeeper_kb.ask_agent")


# ================================================================
# N1 extract_features：从 user_input.user_query 解析目标股票 + 假设追问 override → 36 字段 StructuredInput
# ================================================================
def _extract_stock_code_from_query(query: str) -> str:
    """
    骨架阶段：query 里出现 6 位数字就当作 A 股代码（首位 6=上证 3/0=深证），没有就兜底 600519 贵州茅台，不让骨架卡死。
    """
    import re
    m = re.search(r"\b(\d{6})\b", query)
    if m:
        return m.group(1)
    return "600519"


def node_extract_features(state: AskGraphState) -> dict[str, Any]:
    ui: AskGraphUserInput = state["user_input"]
    query = ui.get("user_query", "") or ""

    # 先按 P0-8 跑假设追问检测，没有命中再看接口是否传了 override_fields
    override: dict = dict(ui.get("override_fields") or {})
    hypothetical_hit = detect_hypothetical_modifiers(query) or {}
    for k, v in hypothetical_hit.items():
        override.setdefault(k, v)

    code = ui.get("stock_code") or _extract_stock_code_from_query(query)  # type: ignore[attr-defined]

    structured, _extra = build_structured_input(
        stock_code=code,
        user_account_capital=float(ui.get("user_account_capital") or 300_000),
        user_risk_r_pct=float(ui.get("user_risk_r_pct") or 0.01),
        user_single_ticket_max=float(ui.get("user_single_ticket_max") or 0.25),
        user_industry_max=float(ui.get("user_industry_max") or 0.30),
        user_risk_score=float(ui.get("user_risk_score") or 80.0),
        user_current_positions=list(ui.get("user_current_positions") or []),
        override=override or None,
    )
    return {
        "structured": structured,
        "is_hypothetical_override": bool(override),
        "override_applied": override,
        "started_at": time.time(),
    }


# ================================================================
# N2 compliance_fence：6 条硬规则，passed=False → 直接 END
# ================================================================
def node_compliance(state: AskGraphState) -> dict[str, Any]:
    s = state["structured"]
    result: ComplianceResult = check_compliance(
        code=s["stock_code"],
        name=s["stock_name"],
        list_days=int(s.get("list_days") or 0),
        is_st_or_special=bool(s.get("is_st_or_special")),
        risk_score=float(s.get("user_risk_score") or 80.0),
        single_ticket_max_percent=float(s.get("user_single_ticket_max") or 0.25),
        industry_max_percent=float(s.get("user_industry_max") or 0.30),
        account_capital=float(s.get("user_account_capital") or 300_000),
        current_positions=list(s.get("user_current_positions") or []),
        entry_price=_first_entry_or_zero(s),
        stop_loss_price=_first_stop_or_zero(s),
    )
    return {"compliance": result}


def _first_entry_or_zero(s: dict) -> float:
    supps = list(s.get("support_levels") or [])
    if supps:
        return float(supps[-1])
    return float(s.get("last_close") or 0.0)


def _first_stop_or_zero(s: dict) -> float:
    supps = list(s.get("support_levels") or [])
    if len(supps) >= 2:
        return float(supps[0])
    close = float(s.get("last_close") or 0.0)
    return round(close * 0.97, 2)


def router_after_compliance(state: AskGraphState) -> str:
    cp: ComplianceResult = state["compliance"]
    if not cp.passed:
        return "node_refused_finalize"
    return "node_score_experts"


def node_refused_finalize(state: AskGraphState) -> dict[str, Any]:
    """合规 refused 时，合成最终 refused 回答 + 6 数字交易计划（方向全部 refused）"""
    cp: ComplianceResult = state["compliance"]
    code = state["structured"]["stock_code"]
    name = state["structured"]["stock_name"]
    reasons = cp.refused_reasons or ["合规围栏拦截：不满足分析前提条件"]

    md_lines = [
        f"# 合规围栏 · 拒绝分析 {name}({code})",
        "",
        "本次请求未通过**6 条硬合规熔断**，为了保护您的账户安全，7 位专家**一律不打分、不出交易计划**：",
        "",
    ]
    for r in reasons:
        md_lines.append(f"- ❌ {r}")
    md_lines.append("")
    md_lines.append("> 「**看不懂不做、拿不住不买、风险>收益绝对不伸手**」")
    md_lines.append("> 如果对规则有疑问，点左上头像 → 交易顾问设置，调整您的风控阈值或开启 ST 豁免。")

    plan: FinalTradePlan = {
        "direction": "refused",
        "action": "standby",
        "entry_price": 0.0,
        "stop_loss_price": 0.0,
        "take_profit_price": 0.0,
        "position_shares_calc": 0,
        "position_percent_calc": 0.0,
        "position_shares_final": 0,
        "position_percent_final": 0.0,
        "r_multiplier": 0.0,
        "expiry_condition": "",
        "position_clamp_note": "",
        "extra_notes": reasons,
    }

    return {
        "per_expert_results": [],
        "sources_global_final": [],
        "final_answer_markdown": "\n".join(md_lines),
        "final_trade_plan": plan,
        "final_direction": "refused",
        "final_answer_delta_segments": _split_delta_segments(md_lines),
        "finished_at": time.time(),
    }


# ================================================================
# N3 7 专家并行打分（单节点 for 循环出 7 条；真 LangGraph parallel 可以拆成 7 个 Node，骨架阶段不拆）
# ================================================================
def node_score_experts(state: AskGraphState) -> dict[str, Any]:
    ui = state["user_input"]
    per = score_per_expert(
        state["structured"],
        user_original_query=ui.get("user_query") or "",
        _skip_sources=bool(state.get("_skip_sources")),
        doc_id_filter=list(state["enabled_doc_ids"]) if state.get("enabled_doc_ids") else None,
    )
    return {"per_expert_results": per}


# ================================================================
# N4 合并全局 sources（P0-1：把 supporting_source_idx 从「专家本地下标」重写为「全局最终下标」）
# ================================================================
def node_merge_sources(state: AskGraphState) -> dict[str, Any]:
    all_chunks: list[tuple[str, str, Any]] = []  # (doc_type, dedup_key, raw_chunk)
    # dedup_key = stable 哈希（doc_type + chunk_id 或 display_text+page 兜底），防止 ingestion 同一 chunk 被 2 个专家都召回
    for p in state.get("per_expert_results") or []:
        doc_type = str(p.get("doc_type") or "")
        for c in p.get("sources_local_raw") or []:
            chunk_id = str(c.get("chunk_id") or "")
            display_text = str(c.get("display_text") or "")
            page = int(c.get("page_number") or -1)
            dedup_key = chunk_id if chunk_id else hashlib.sha1(f"{doc_type}|{page}|{display_text[:120]}".encode()).hexdigest()
            all_chunks.append((doc_type, dedup_key, c))

    ordered_keys: list[tuple[str, str]] = []
    seen = set()
    for dt, k, _ in all_chunks:
        if (dt, k) in seen:
            continue
        seen.add((dt, k))
        ordered_keys.append((dt, k))

    key_to_global = {(dt, k): i for i, (dt, k) in enumerate(ordered_keys)}

    sources_global: list[SourceCardItem] = []
    for global_idx, (dt, k) in enumerate(ordered_keys):
        # 找第一个有这个 key 的 raw chunk
        raw = next(c for (d, kk, c) in all_chunks if d == dt and kk == k)
        disp = str(raw.get("display_text") or "")
        summary = (disp[:120].strip() + ("…" if len(disp) > 120 else "")) or "（原文空）"
        thumbnail = ""
        if raw.get("image_urls"):
            thumbnail = raw["image_urls"][0]
        sources_global.append({
            "source_global_idx": global_idx,
            "doc_type": dt,
            "display_name": _doc_type_display_name(dt),
            "page_number": int(raw.get("page_number") or -1),
            "chunk_id": str(raw.get("chunk_id") or ""),
            "pdf_name": "",
            "summary_text": summary,
            "thumbnail_url": thumbnail,
        })

    # P0-1：把每位专家 reason_rules 里的 supporting_source_idx = 专家本地 idx → 重写成全局 idx
    for p in state.get("per_expert_results") or []:
        doc_type = str(p.get("doc_type") or "")
        local_raw = list(p.get("sources_local_raw") or [])
        local_idx_to_global: dict[int, int] = {}
        for li, c in enumerate(local_raw):
            chunk_id = str(c.get("chunk_id") or "")
            disp = str(c.get("display_text") or "")
            page = int(c.get("page_number") or -1)
            dedup_key = chunk_id if chunk_id else hashlib.sha1(f"{doc_type}|{page}|{disp[:120]}".encode()).hexdigest()
            gi = key_to_global.get((doc_type, dedup_key))
            if gi is not None:
                local_idx_to_global[li] = gi
        for rule in p.get("reason_rules") or []:
            old = list(rule.get("supporting_source_idx") or [])
            new: list[int] = []
            for li in old:
                gi = local_idx_to_global.get(li)
                if gi is not None:
                    new.append(gi)
            rule["supporting_source_idx"] = new  # type: ignore[typeddict-item]

    return {"sources_global_final": sources_global, "_chunk_id_to_global": {}}


def _doc_type_display_name(doc_type: str) -> str:
    fallback = {
        "candlestick": "日本蜡烛图技术",
        "technical_trend": "股票趋势技术分析（第 10 版）",
        "psychology": "交易心理分析",
        "fundamental": "手把手教你读财报",
        "master_wisdom": "金融怪杰 / 新金融怪杰",
        "risk_position": "以交易为生 / 以趋势跟踪为生",
        "news_intel": "东方财富公告 · 7x24 情报",
    }
    return fallback.get(doc_type, doc_type or "未命名专家资料")


# ================================================================
# N5 generation：用 7 专家结果 + 6 数字交易计划 合成最终 Markdown（不依赖 LLM，纯模板拼接）
# ================================================================
def node_generation(state: AskGraphState) -> dict[str, Any]:
    structured = state["structured"]
    per_expert = state["per_expert_results"]
    sources_global = state.get("sources_global_final") or []

    # 先算 7 专家加权综合方向 + 总分
    total_ws = 0.0
    weighted_sum = 0.0
    bull_w = bear_w = neut_w = 0
    veto_hit: ExpertRuleHit | None = None
    for p in per_expert:
        ws = float(p.get("weighted_score") or 0)
        if has_any_veto({"_": p["reason_rules"]}):
            veto_hit = next((h for h in p["reason_rules"] if h.get("is_veto")), None)
            break
        weighted_sum += ws
        total_ws += abs(ws)
        if p["direction"] == "bull":
            bull_w += 1
        elif p["direction"] == "bear":
            bear_w += 1
        elif p["direction"] == "neutral":
            neut_w += 1

    if veto_hit is not None:
        direction = "refused"
    elif total_ws == 0:
        # 7 位专家都没打分（0 分 = neutral）
        direction = "neutral"
    elif weighted_sum > 0 and bull_w >= bear_w:
        direction = "bull"
    elif weighted_sum < 0 and bear_w > bull_w:
        direction = "bear"
    else:
        direction = "neutral"

    # 6 数字交易计划（P0-2 clamp）
    plan = _build_trade_plan(structured, direction, weighted_sum, bull_w, bear_w, neut_w)

    # Markdown 合成：标题 / 7 专家小卡片列表 / 6 数字交易计划表格 / 引用清单预告
    md = _synthesize_markdown(structured, per_expert, sources_global, plan, direction, weighted_sum)
    segments = _split_delta_segments(md.splitlines(keepends=False))

    return {
        "final_answer_markdown": md,
        "final_trade_plan": plan,
        "final_direction": direction,
        "final_answer_delta_segments": segments,
        "finished_at": time.time(),
    }


def _build_trade_plan(structured: dict, direction: str, weighted_sum: float, bull_w: int, bear_w: int, neut_w: int) -> FinalTradePlan:
    code = structured["stock_code"]
    close = float(structured.get("last_close") or 0)
    cap = float(structured.get("user_account_capital") or 300_000)
    r_pct = float(structured.get("user_risk_r_pct") or 0.01)
    single_max = float(structured.get("user_single_ticket_max") or 0.25)
    industry_max = float(structured.get("user_industry_max") or 0.30)
    _ = bull_w, bear_w, neut_w  # 骨架阶段不用，保留参数位

    if direction == "refused" or close <= 0:
        return {
            "direction": direction or "neutral",
            "action": "standby",
            "entry_price": 0.0,
            "stop_loss_price": 0.0,
            "take_profit_price": 0.0,
            "position_shares_calc": 0,
            "position_percent_calc": 0.0,
            "position_shares_final": 0,
            "position_percent_final": 0.0,
            "r_multiplier": 0.0,
            "expiry_condition": "",
            "position_clamp_note": "",
            "extra_notes": [],
        }

    supps = sorted([float(x) for x in (structured.get("support_levels") or []) if x])
    resists = sorted([float(x) for x in (structured.get("resistance_levels") or []) if x])
    close_rounded = round(close, 2)

    # 入场：默认当前价，多头方向再往压力位取一个小回踩
    if direction == "bull":
        entry = min(close_rounded * 1.005, close_rounded + 0.1)
    elif direction == "bear":
        entry = max(close_rounded * 0.995, close_rounded - 0.1)
    else:
        entry = close_rounded
    entry = round(entry, 2)

    # 止损：支撑位下限 or -3%
    stop_raw = supps[0] if supps else round(close_rounded * 0.97, 2)
    # 止盈：压力位 or +8%
    take_raw = resists[-1] if resists else round(close_rounded * 1.08, 2)
    stop = round(min(stop_raw, entry * 0.999), 2)
    take = round(max(take_raw, entry * 1.001), 2)

    r_per_share = abs(entry - stop)
    r_total = cap * r_pct
    if r_per_share > 0:
        shares_calc_raw = int(r_total / r_per_share)
    else:
        shares_calc_raw = 0
    # A 股 100 股一手
    shares_calc = int(shares_calc_raw // 100) * 100
    pct_calc = (shares_calc * entry) / cap if cap > 0 and shares_calc > 0 else 0.0

    # P0-2 clamp：单票 ≤25%，行业 ≤30%（这里只做单票 clamp，行业需要查持仓的行业百分比聚合，骨架阶段先不做）
    cap_single = int((cap * single_max) / entry) // 100 * 100 if entry > 0 else 0
    cap_industry = int((cap * industry_max) / entry) // 100 * 100 if entry > 0 else 0
    clamped_shares = min(shares_calc, cap_single, cap_industry)
    clamp_notes: list[str] = []
    if clamped_shares != shares_calc:
        old_pct = round(pct_calc * 100, 1)
        new_pct = round((clamped_shares * entry) / cap * 100, 1) if cap > 0 else 0
        clamp_notes.append(f"仓位已按您设置的单票 ≤{single_max*100:.0f}% / 行业 ≤{industry_max*100:.0f}% 上限，从 {shares_calc} 股（{old_pct}%）调整为 {clamped_shares} 股（{new_pct}%）")
    pct_final = (clamped_shares * entry) / cap if cap > 0 and clamped_shares > 0 else 0.0
    rr = (take - entry) / r_per_share if r_per_share > 0 else 0.0

    # 动作：按方向
    if direction == "bull":
        action = "open_long" if shares_calc > 0 else "standby"
    elif direction == "bear":
        action = "open_short" if shares_calc > 0 else "standby"
    else:
        action = "hold"

    expiry = "持有 ≤ 10 个交易日未触发止盈 → 无条件离场；跌破 20 日线无条件离场"
    extra = [
        f"标的 {structured.get('stock_name','')}({code}) 综合加权分：{weighted_sum:+.1f}",
        "交易成本按 0.25% 佣金 + 0.1% 印花税估算，实盘请以券商成交为准",
    ]
    if rr and rr < 1:
        extra.append("⚠️ 本计划 R/R < 1，属于「怪杰扣分」场景；只做看得懂的部分，不硬做")

    return {
        "direction": direction,  # type: ignore[typeddict-item]
        "action": action,  # type: ignore[typeddict-item]
        "entry_price": round(entry, 2),
        "stop_loss_price": round(stop, 2),
        "take_profit_price": round(take, 2),
        "position_shares_calc": int(shares_calc),
        "position_percent_calc": round(pct_calc, 4),
        "position_shares_final": int(clamped_shares),
        "position_percent_final": round(pct_final, 4),
        "r_multiplier": round(rr, 2),
        "expiry_condition": expiry,
        "position_clamp_note": "；".join(clamp_notes),
        "extra_notes": extra,
    }


def _synthesize_markdown(structured: dict, per_expert: list, sources_global: list, plan: FinalTradePlan, direction: str, weighted_sum: float) -> str:
    name = structured.get("stock_name") or "标的"
    code = structured.get("stock_code") or "??????"
    ind = structured.get("industry_sw_l1") or "未分类行业"
    close = float(structured.get("last_close") or 0)
    chg = float(structured.get("change_pct_today") or 0)
    roe = float(structured.get("roe_ttm") or 0)
    debt = float(structured.get("debt_ratio") or 0)

    dir_label = {"bull": "强烈看多 🟢", "bear": "强烈看空 🔴", "neutral": "建议观望 🟡", "refused": "拒答不碰 🚫"}.get(direction, "未知")

    lines: list[str] = []
    lines.append(f"# 老李最终意见：{dir_label} — {name}({code})")
    lines.append("")
    lines.append("| 字段 | 值 |")
    lines.append("| --- | --- |")
    lines.append(f"| 行业（申万一级） | {ind} |")
    lines.append(f"| 最新价 / 今日涨跌 | {close:.2f} 元 / **{chg:+.2f}%** |")
    lines.append(f"| ROE TTM / 资产负债率 | {roe:.1f}% / {debt:.1f}% |")
    lines.append(f"| 7 专家加权总分（含否决） | **{weighted_sum:+.1f}** |")
    lines.append("")

    if direction == "refused":
        lines.append("## 🚫 一票否决：不做这笔交易")
        lines.append("")
        for p in per_expert:
            for h in p.get("reason_rules") or []:
                if h.get("is_veto"):
                    lines.append(f"- **{h['rule_id']}**：{h['rule_description']}")
        lines.append("")
    else:
        lines.append("## 一、7 位专家各自怎么说")
        lines.append("")
        for p in per_expert:
            emoji = {"bull": "🟢", "bear": "🔴", "neutral": "🟡", "refused": "🚫"}.get(p["direction"], "⚪")
            lines.append(f"### {emoji} {p['spoken_opening']}")
            lines.append(f"- 方向：**{p['direction']}**  | 原始分 {p['score']:+.1f} | 加权分 {p['weighted_score']:+.1f}")
            lines.append(f"- 解释：{p['spoken_body']}")
            rules = p.get("reason_rules") or []
            top_rules = rules[:3]
            if top_rules:
                lines.append("- 命中前 3 条规则：")
                for r in top_rules:
                    refs = " ".join(f"[{i+1}]" for i in r.get("supporting_source_idx") or [])
                    lines.append(f"  - **{r['rule_id']}** {r['rule_description']}（{float(r['points']):+.1f} 分）{refs}")
            lines.append("")

        lines.append("## 二、6 数字交易计划（仲裁官老李最终拍板）")
        lines.append("")
        lines.append("| 数字 | 最终值 | 说明 |")
        lines.append("| --- | ---: | --- |")
        lines.append(f"| ① 入场价 | **{plan['entry_price']:.2f} 元** | 触发后再买，不要提前埋伏 |")
        lines.append(f"| ② 止损价 | **{plan['stop_loss_price']:.2f} 元** | 破位必须走，没有例外 |")
        lines.append(f"| ③ 止盈价（第一目标） | **{plan['take_profit_price']:.2f} 元** | 到价减一半，另一半用移动止盈 |")
        lines.append(f"| ④ 理论仓位（按 R） | {plan['position_shares_calc']} 股（{plan['position_percent_calc']*100:.1f}%） | 按单笔 R 反推 |")
        lines.append(f"| ⑤ 执行仓位（已 clamp） | **{plan['position_shares_final']} 股（{plan['position_percent_final']*100:.1f}%）** | P0-2 单票/行业上限修正 |")
        lines.append(f"| ⑥ R/R 盈亏比 | **1 : {plan['r_multiplier']:.2f}** | <1=怪杰扣分，≥2=优质 |")
        lines.append("")
        if plan.get("position_clamp_note"):
            lines.append(f"> ⚠️ {plan['position_clamp_note']}")
            lines.append("")
        lines.append(f"**失效条件**：{plan['expiry_condition']}")
        lines.append("")

    if sources_global:
        lines.append(f"## 三、引用清单（共 {len(sources_global)} 条）")
        lines.append("")
        for src in sources_global[:12]:
            idx = src["source_global_idx"] + 1
            page_note = f"，原书 P.{src['page_number']}" if src.get("page_number") and src["page_number"] > 0 else ""
            lines.append(f"- **[{idx}] {src['display_name']}**{page_note}：{src['summary_text']}")
        if len(sources_global) > 12:
            lines.append(f"- （其余 {len(sources_global)-12} 条在「🔍 为什么这么说？」里查看）")
        lines.append("")

    lines.append("---")
    lines.append("*本内容为 AI 交易顾问辅助分析结果，不构成任何投资建议；实盘盈亏请自负，风控永远第一位。*")
    return "\n".join(lines)


def _split_delta_segments(lines: list[str]) -> list[str]:
    """把完整 Markdown 切成 4~8 个增量段，供 E4 answer_delta 一段一段推流（骨架阶段模拟 SSE）"""
    if not lines:
        return [""]
    n = max(4, min(8, len(lines) // 3 + 1))
    step = max(1, (len(lines) + n - 1) // n)
    out: list[str] = []
    for i in range(0, len(lines), step):
        batch = lines[i:i + step]
        out.append("\n".join(batch) + ("\n" if i + step < len(lines) else ""))
    return out


# ================================================================
# 组装 LangGraph
# ================================================================
def build_ask_graph():
    builder = StateGraph(AskGraphState)
    builder.add_node("node_extract", node_extract_features)
    builder.add_node("node_compliance", node_compliance)
    builder.add_node("node_refused_finalize", node_refused_finalize)
    builder.add_node("node_score_experts", node_score_experts)
    builder.add_node("node_merge_sources", node_merge_sources)
    builder.add_node("node_generation", node_generation)

    builder.set_entry_point("node_extract")
    builder.add_edge("node_extract", "node_compliance")
    builder.add_conditional_edges("node_compliance", router_after_compliance, {
        "node_refused_finalize": "node_refused_finalize",
        "node_score_experts": "node_score_experts",
    })
    builder.add_edge("node_score_experts", "node_merge_sources")
    builder.add_edge("node_merge_sources", "node_generation")
    builder.add_edge("node_generation", END)
    builder.add_edge("node_refused_finalize", END)
    return builder.compile()


class AskAgentRunner:
    """对外入口：一次 invoke 拿到完整 AskGraphState final 字段 + 过程事件（SSE 用）。"""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.graph = build_ask_graph()

    def run(self, user_input: AskGraphUserInput, *,
            enabled_doc_ids: list[str] | None = None,
            _skip_sources: bool = False) -> AskGraphState:
        init_state: AskGraphState = {  # type: ignore[typeddict-item]
            "user_input": user_input,
            "enabled_doc_ids": list(enabled_doc_ids) if enabled_doc_ids else [],
            "_skip_sources": bool(_skip_sources),
        }
        result: AskGraphState = self.graph.invoke(init_state)
        return result


__all__ = [
    "AskAgentRunner",
    "build_ask_graph",
    "node_extract_features",
    "node_compliance",
    "router_after_compliance",
    "node_score_experts",
    "node_merge_sources",
    "node_generation",
]
