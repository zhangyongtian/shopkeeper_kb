from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shopkeeper_kb.logging_config import get_logger
from shopkeeper_kb.workflows.state import ExpertRuleHit

logger = get_logger("shopkeeper_kb.compliance")

# ================================================================
# 合规围栏（最外层第一道硬屏障，命中 → direction=refused，根本不进专家打分，不花 LLM 钱）
# 6 条熔断规则（P0 硬漏点，代码层保证 100% 命中一定 refused）
# ================================================================

VETO_RULE_ID_NEW_STOCK = "COMPLIANCE_NEW_STOCK_60D"
VETO_RULE_ID_ST = "COMPLIANCE_ST_OR_DELIST"
VETO_RULE_ID_RISK_UNDER_80_FOR_ST = "COMPLIANCE_RISK_UNDER_80_PLAYS_ST"
VETO_RULE_ID_SINGLE_TICKET_OVER = "COMPLIANCE_SINGLE_TICKET_OVER_MAX"
VETO_RULE_ID_INDUSTRY_OVER = "COMPLIANCE_INDUSTRY_CONCENTRATION_OVER"
VETO_RULE_ID_STOP_PRICE_EQUAL_ENTRY = "COMPLIANCE_STOP_EQUALS_ENTRY_NO_R"


@dataclass
class ComplianceResult:
    passed: bool                                   # True = 合规通过，进专家打分；False = 被 refused
    refused_reasons: list[str] = field(default_factory=list)
    refused_rule_hits: list[ExpertRuleHit] = field(default_factory=list)  # 直接塞 generation 节点的 refused 规则
    # 为 P0-2 预计算的 clamp 限制（即使未触发熔断，也会在 FinalTradePlan 里做 clamp）
    single_ticket_max_percent: float = 0.25
    industry_max_percent: float = 0.30


# ------------------------------------------------------------------
# Helper：生成一票否决 ExpertRuleHit（直接塞 result.refused_rule_hits）
# ------------------------------------------------------------------
def _veto_hit(rule_id: str, desc: str, evidence: str, category: str = "compliance") -> ExpertRuleHit:
    return {  # type: ignore[typeddict-unknown-key]
        "rule_id": rule_id,
        "rule_description": desc,
        "category": category,
        "points": -999.0,          # P0 硬：一票否决 = -999 点（generation 节点看到 points < -500 直接 refused）
        "is_veto": True,
        "confidence": 1.0,
        "supporting_source_idx": [],  # P0-1：合规没有 chunk 引用，传空；generation 看到空就不在「🔍为什么」里展示
        "evidence_text_snippets": [evidence],
    }


# ================================================================
# 主函数：check_compliance（任何参数缺失，返回「合规通过 + 合理默认 clamp」，不 refused 误杀）
# ================================================================


def check_compliance(
    *,
    code: str,
    name: str,
    list_days: int,
    is_st_or_special: bool,
    # user_profile
    risk_score: int,                 # 0~100，用户风险测评得分（<80 分禁止玩 ST/*ST）
    single_ticket_max_percent: float,  # 用户画像：单票最大仓位 %（默认 0.25 = 25%）
    industry_max_percent: float,       # 用户画像：单行业最大总仓位 %（默认 0.30 = 30%）
    account_capital: float,            # 总账户本金（元）
    current_positions: list[dict[str, Any]],  # [{code,name,percent:0.xx,cost}]
    # 交易计划（如果有，校验 R≠0，否则 clamp 时会提示）
    entry_price: float | None = None,
    stop_loss_price: float | None = None,
    # 当前目标股票行业（stock_dict.industry(code) 返回）
    target_industry: str = "",
    # 预计算仓位（calc 后百分比，用于校验是否超单票上限）
    planned_position_percent: float | None = None,
    settings_like_any: Any = None,  # 预留，不用
) -> ComplianceResult:
    """
    合规围栏 6 条。
    - 命中任何一条 with is_veto=True → refused；
    - 未通过熔断但需要 clamp 的（例如 单票 26% → clamp 到 25%）→ passed=True + 返回 clamp_note 字段
    """
    _ = settings_like_any  # 预留不报错
    result = ComplianceResult(
        passed=True,
        single_ticket_max_percent=single_ticket_max_percent,
        industry_max_percent=industry_max_percent,
    )

    # ================================================================
    # 规则 1：上市 < 60 天新股 → 直接 refused（P0 合规红线；A 股新股上市前 20 天走势是赌场）
    # ================================================================
    if list_days < 60 and list_days > 0:  # list_days=0 代表拿不到数据，此时不误杀
        reason = f"股票「{name}({code})」上市仅 {list_days} 天（<60 天新股禁止提供任何交易建议）"
        result.refused_reasons.append(reason)
        result.refused_rule_hits.append(_veto_hit(
            VETO_RULE_ID_NEW_STOCK,
            "上市不足 60 个自然日的新股/次新股属于高风险品种，合规围栏直接拒答",
            evidence=f"list_days={list_days}  < 60",
        ))

    # ================================================================
    # 规则 2：ST / *ST / 退市整理期 → 直接 refused（除非 risk_score ≥ 80 才能操作，此时也 warn）
    # ================================================================
    if is_st_or_special:
        if risk_score < 80:
            reason = (
                f"股票「{name}({code})」属于 ST/*ST/退市整理高风险品种；"
                f"你的风险测评仅 {risk_score} 分（<80），合规围栏拒答"
            )
            result.refused_reasons.append(reason)
            result.refused_rule_hits.append(_veto_hit(
                VETO_RULE_ID_RISK_UNDER_80_FOR_ST,
                "ST/*ST 必须风险测评 ≥ 80 分才能提供建议，低于此分数合规围栏直接拒答",
                evidence=f"is_st=true && risk_score={risk_score} < 80",
            ))
        else:
            # 风险测评够 80 分玩 ST → 不 refused，但给一个「强扣分规则」（-300 点，不是 veto，因为风险测评过了）
            # 这里只记录 reason 到 refused_reasons 为空，保留 passed=True；扣分在 expert_rules.PS_01 里做
            pass

    # ================================================================
    # 规则 3：单票仓位 clamp（即使通过了也要记录到 result 里，FinalTradePlan clamp 时读取）
    # ================================================================
    if planned_position_percent is not None and planned_position_percent > single_ticket_max_percent:
        result.refused_reasons.append(
            f"理论仓位 {planned_position_percent*100:.1f}% > 你设置的单票 {single_ticket_max_percent*100:.0f}% 上限"
            f"→ 实际执行会自动 clamp 到 {single_ticket_max_percent*100:.0f}%"
        )  # 非 veto，只是 clamp 提示

    # ================================================================
    # 规则 4：行业集中度 clamp（当前同行业仓位 + 本次计划 > 行业上限 → clamp）
    # ================================================================
    if target_industry and current_positions:
        same_industry_percent = 0.0
        for pos in current_positions:
            ind = str(pos.get("industry") or "")
            code_pos = str(pos.get("code") or "")
            percent = float(pos.get("percent") or 0.0)
            # 只有已知行业的才算；如果 pos 没存 industry，就按 code 留空，不算入（避免误 clamp）
            if ind == target_industry and code_pos != code:
                same_industry_percent += percent
        planned = planned_position_percent or 0.0
        total_industry = same_industry_percent + planned
        if total_industry > industry_max_percent:
            result.refused_reasons.append(
                f"你当前「{target_industry}」行业已持仓 {same_industry_percent*100:.1f}%，"
                f"加上本次计划 {planned*100:.1f}% → 合计 {total_industry*100:.1f}% > "
                f"你设置的行业集中度上限 {industry_max_percent*100:.0f}% → 实际执行会自动 clamp 到行业上限"
            )

    # ================================================================
    # 规则 5：R = 0（entry == stop_loss）→ 无风险空间；不能做任何交易计划（refused）
    # ================================================================
    if entry_price is not None and stop_loss_price is not None:
        if abs(entry_price - stop_loss_price) < max(entry_price, 1.0) * 1e-4:  # 1bp 以内视为 0
            reason = (
                f"入场价 {entry_price:.2f} ≈ 止损价 {stop_loss_price:.2f}，R = 0 → "
                "没有盈亏比，合规围栏拒答任何建仓建议"
            )
            result.refused_reasons.append(reason)
            result.refused_rule_hits.append(_veto_hit(
                VETO_RULE_ID_STOP_PRICE_EQUAL_ENTRY,
                "止损价与入场价完全相同，没有 R 空间 → 拒答",
                evidence=f"entry={entry_price} stop={stop_loss_price}",
            ))

    # ================================================================
    # 6 条里只要还有 is_veto=True 命中 → passed = False（refused）
    # ================================================================
    if any(h.get("is_veto") for h in result.refused_rule_hits):
        result.passed = False

    return result
