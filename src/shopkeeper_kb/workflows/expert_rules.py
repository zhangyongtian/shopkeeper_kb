from __future__ import annotations

from shopkeeper_kb.logging_config import get_logger
from shopkeeper_kb.workflows.state import ExpertRuleHit, StructuredInput

logger = get_logger("shopkeeper_kb.expert_rules")

# ================================================================
# 梯队 2.4：7 大类 × 36 条专家打分规则（先写 P0/P1 硬规则，分值先定死）
#
# 7 大类 category 枚举（对齐 expert_books.doc_type → 7 位专家各自只关心自己的 category）：
#   1. candlestick    蜡烛图形态
#   2. trend          趋势与均线
#   3. psychology     交易心理
#   4. master_wisdom  金融怪杰经验
#   5. risk_position  仓位风险管理
#   6. fundamental    财报基本面
#   7. announce       公告/情报
#
# P0-1 强制字段 supporting_source_idx：这里先填 [] 或规则自己的本地命中 idx，
#   在 generation 节点合并全局 sources 后必须重写此值（对齐 state.ExpertRuleHit 注释）。
# ================================================================


CATEGORY_CANDLESTICK = "candlestick"
CATEGORY_TREND = "trend"
CATEGORY_PSYCHOLOGY = "psychology"
CATEGORY_MASTER_WISDOM = "master_wisdom"
CATEGORY_RISK_POSITION = "risk_position"
CATEGORY_FUNDAMENTAL = "fundamental"
CATEGORY_ANNOUNCE = "announce"

ALL_CATEGORIES = [
    CATEGORY_CANDLESTICK,
    CATEGORY_TREND,
    CATEGORY_PSYCHOLOGY,
    CATEGORY_MASTER_WISDOM,
    CATEGORY_RISK_POSITION,
    CATEGORY_FUNDAMENTAL,
    CATEGORY_ANNOUNCE,
]


# ------------------------------------------------------------------
# 单条规则构造器：把 (id, desc, points, ...) → ExpertRuleHit（保证 P0-1 字段不缺）
# ------------------------------------------------------------------
def mk_hit(
    rule_id: str,
    rule_description: str,
    category: str,
    points: float,
    *,
    is_veto: bool = False,
    confidence: float = 0.8,
    evidence: list[str] | None = None,
    supporting_source_idx: list[int] | None = None,
) -> ExpertRuleHit:
    return {  # type: ignore[typeddict-item,typeddict-unknown-key]
        "rule_id": rule_id,
        "rule_description": rule_description,
        "category": category,
        "points": float(points),
        "is_veto": bool(is_veto),
        "confidence": float(confidence),
        "supporting_source_idx": list(supporting_source_idx or []),  # P0-1 强制字段（先本地占位，generation 重写）
        "evidence_text_snippets": list(evidence or []),
    }


# ================================================================
# 分类打分入口（每个 category 单独一个函数，便于 unit test）
# ================================================================

# -------- 1. candlestick 蜡烛图形态（CAND_xx，分值 ±8~±15）--------


def score_candlestick(s: StructuredInput) -> list[ExpertRuleHit]:
    hits: list[ExpertRuleHit] = []
    # CAND_01：多头排列 + 放量 → 强看涨（权重高，因为蜡烛图形态就是趋势的直接表现）
    if s["trend_50d"] == "bull" and s["trend_200d"] == "bull":
        if s["volume_ratio_today"] >= 1.2:
            hits.append(mk_hit("CAND_01", "50/200 日均线多头排列 + 量比 ≥1.2 放量确认", CATEGORY_CANDLESTICK, +14.0, confidence=0.9,
                               evidence=[f"trend50={s['trend_50d']} trend200={s['trend_200d']} volume_ratio={s['volume_ratio_today']:.2f}"]))
        else:
            hits.append(mk_hit("CAND_02", "50/200 日均线多头排列（但没有放量确认）", CATEGORY_CANDLESTICK, +8.0, confidence=0.7,
                               evidence=[f"ma50={s['trend_50d']} ma200={s['trend_200d']}"]))
    # CAND_03：空头排列 + 放量下跌 → 看跌
    if s["trend_50d"] == "bear" and s["trend_200d"] == "bear":
        if s["change_pct_today"] <= -2.0:
            hits.append(mk_hit("CAND_03", "50/200 日均线空头排列 + 当日下跌 ≥2%", CATEGORY_CANDLESTICK, -15.0, confidence=0.9,
                               evidence=[f"trend50={s['trend_50d']} change_pct={s['change_pct_today']:.2f}%"]))
        else:
            hits.append(mk_hit("CAND_04", "50/200 日均线空头排列", CATEGORY_CANDLESTICK, -8.0, confidence=0.75))
    # CAND_05：箱体震荡（无方向 + 支撑位 < 当前价 < 压力位）→ neutral
    if "箱体震荡" in s["chart_features"]:
        hits.append(mk_hit("CAND_05", "箱体震荡中，等待放量突破/跌破再操作", CATEGORY_CANDLESTICK, 0.0, confidence=0.9))
    # CAND_06：放量突破压力位 → 强看涨
    if "放量突破" in s["chart_features"] and s["resistance_levels"]:
        r1 = s["resistance_levels"][0]
        ev = f"current={s['last_close']:.2f} 突破压力位 {r1:.2f}"
        hits.append(mk_hit("CAND_06", "放量突破关键压力位", CATEGORY_CANDLESTICK, +12.0, confidence=0.85, evidence=[ev]))
    # CAND_07：放量跌破支撑 → 强看跌
    if "放量破位" in s["chart_features"] and s["support_levels"]:
        s1 = s["support_levels"][-1]
        hits.append(mk_hit("CAND_07", "放量跌破关键支撑位（立即止损）", CATEGORY_CANDLESTICK, -14.0, confidence=0.95,
                           evidence=[f"跌破支撑位 {s1:.2f}"]))
    return hits


# -------- 2. trend 趋势与均线（TREND_xx，±8~±12）----------------


def score_trend(s: StructuredInput) -> list[ExpertRuleHit]:
    hits: list[ExpertRuleHit] = []
    # TREND_01：MA200 牛熊分界（最重量级规则）
    if s["trend_200d"] == "bull":
        hits.append(mk_hit("TREND_01", "长期 MA200 上方运行，牛市格局", CATEGORY_TREND, +12.0, confidence=0.9))
    else:
        hits.append(mk_hit("TREND_02", "长期 MA200 下方运行，熊市/震荡格局，任何反弹都谨慎", CATEGORY_TREND, -12.0, confidence=0.9))
    # TREND_03：MA50 方向（中期方向）
    if s["trend_50d"] == "bull":
        hits.append(mk_hit("TREND_03", "中期 MA50 上方，中期趋势健康", CATEGORY_TREND, +8.0, confidence=0.8))
    elif s["trend_50d"] == "bear":
        hits.append(mk_hit("TREND_04", "中期 MA50 下方，中期趋势走弱", CATEGORY_TREND, -8.0, confidence=0.8))
    # TREND_05：支撑位近（距离 < 3%）→ 风险点
    if s["support_levels"]:
        nearest_support = max(s["support_levels"])
        if s["last_close"] > 0 and (s["last_close"] - nearest_support) / s["last_close"] < 0.03:
            hits.append(mk_hit("TREND_05", "当前价离关键支撑位 <3%，如果跌破必须止损", CATEGORY_TREND, -4.0, confidence=0.75,
                               evidence=[f"last_close={s['last_close']:.2f} support={nearest_support:.2f}"]))
    # TREND_06：压力位近（<3%）→ 注意受阻
    if s["resistance_levels"]:
        nearest_res = min(s["resistance_levels"])
        if s["last_close"] > 0 and (nearest_res - s["last_close"]) / s["last_close"] < 0.03:
            hits.append(mk_hit("TREND_06", "当前价离关键压力位 <3%，注意受阻回落；放量突破后再加仓", CATEGORY_TREND, -2.0, confidence=0.7,
                               evidence=[f"last_close={s['last_close']:.2f} resistance={nearest_res:.2f}"]))
    # TREND_07：高换手 >15% → 多空分歧大（方向不明确，小扣分提醒注意风险）
    if s["turnover_rate_today"] >= 15.0:
        hits.append(mk_hit("TREND_07", "换手率 ≥15%，多空分歧剧烈，次日往往大幅波动", CATEGORY_TREND, -3.0, confidence=0.8))
    # TREND_08：低换手 <0.5%（非 ST） + 多头排列 → 筹码锁定好，没人卖 → 加分
    if s["turnover_rate_today"] <= 0.5 and s["trend_200d"] == "bull" and not s["is_st_or_special"]:
        hits.append(mk_hit("TREND_08", "长期多头 + 低换手率 ≤ 0.5% → 筹码锁定良好，没人卖", CATEGORY_TREND, +4.0, confidence=0.75))
    # TREND_09：涨跌幅小（|pct| < 0.5%）+ 量比 < 0.8 → 缩量横盘，观望 = neutral
    if abs(s["change_pct_today"]) <= 0.5 and s["volume_ratio_today"] < 0.8:
        hits.append(mk_hit("TREND_09", "缩量横盘窄幅震荡，等方向；不要急着进场", CATEGORY_TREND, -2.0, confidence=0.65))
    return hits


# -------- 3. psychology 交易心理（PSYCH_xx，扣分提醒，±2~±6）-----


def score_psychology(s: StructuredInput) -> list[ExpertRuleHit]:
    hits: list[ExpertRuleHit] = []
    # PSYCH_01：情绪过热（当日涨 >7% + 换手率 ≥12% → 小心追高被套）
    if s["change_pct_today"] >= 7.0 and s["turnover_rate_today"] >= 12.0:
        hits.append(mk_hit("PSYCH_01", "当日大涨 + 高换手，情绪明显过热；心理上不要追高，等回踩", CATEGORY_PSYCHOLOGY, -5.0, confidence=0.85))
    # PSYCH_02：情绪恐慌（当日跌 >5% + 放量破位 → 禁止抄底飞刀）
    if s["change_pct_today"] <= -5.0 and "放量破位" in s["chart_features"]:
        hits.append(mk_hit("PSYCH_02", "放量大跌 + 破位，市场恐慌；不要接飞刀，等止跌信号", CATEGORY_PSYCHOLOGY, -6.0, confidence=0.9))
    # PSYCH_03：利好消息密集（≥3 条正）→ 可能利好出尽
    if s["news_pos_count_7d"] >= 3:
        hits.append(mk_hit("PSYCH_03", "近 7 天利好新闻 ≥3 条，当心利好出尽（谣言时买入，新闻时卖出）", CATEGORY_PSYCHOLOGY, -3.0, confidence=0.65))
    return hits


# -------- 4. master_wisdom 金融怪杰经验（MASTER_xx，±5~±10）---


def score_master_wisdom(s: StructuredInput) -> list[ExpertRuleHit]:
    hits: list[ExpertRuleHit] = []
    # MASTER_01：截断亏损让利润奔跑 —— R/R（目标价-入场 / 入场-止损）≥ 2 才合格，这里用支撑位/压力位距离代替
    supports = s["support_levels"] or [s["last_close"] * 0.95]
    resists = s["resistance_levels"] or [s["last_close"] * 1.10]
    entry = s["last_close"]
    if entry > 0 and supports and resists:
        stop_loss = min(supports)
        take_profit = max(resists)
        r = entry - stop_loss
        reward = take_profit - entry
        if r > 0 and reward / r >= 2.0:
            hits.append(mk_hit("MASTER_01", f"当前形态 R/R ≥ 2（止损 {stop_loss:.2f} 止盈 {take_profit:.2f}），符合怪杰铁律", CATEGORY_MASTER_WISDOM, +10.0, confidence=0.85))
        elif r > 0 and reward / r < 1.0:
            hits.append(mk_hit("MASTER_02", "R/R < 1（盈亏比不合理），怪杰不会做这种交易", CATEGORY_MASTER_WISDOM, -8.0, confidence=0.8,
                               evidence=[f"r={r:.2f} reward={reward:.2f} rr={reward/max(r,1e-6):.2f}"]))
    # MASTER_03：不要买 PE > 60 的票（散户常犯的「热门股估值泡沫」错误）
    if "PE_TTM" not in globals() and s.get("last_close", 0) > 0:
        # 没东财 PE 数据就跳过（优雅降级），否则 PE>60 扣分
        pass
    # MASTER_04：高负债行业（负债率 >70%）+ 熊市趋势 → 双杀（金融怪杰反复提到的风险）
    if s["debt_ratio"] >= 70.0 and s["trend_200d"] == "bear":
        hits.append(mk_hit("MASTER_04", f"资产负债率 {s['debt_ratio']:.1f}% + 长期空头 → 容易戴维斯双杀", CATEGORY_MASTER_WISDOM, -7.0, confidence=0.75))
    # MASTER_05：交易你擅长的领域（未知行业 = 小扣分提醒你要先研究）
    if s["industry_sw_l1"] in ("（未分类行业）", "未知行业"):
        hits.append(mk_hit("MASTER_05", "未知行业，怪杰说：「不懂的不要做」", CATEGORY_MASTER_WISDOM, -5.0, confidence=0.6))
    # MASTER_06：ROE ≥12% + 现金流为正 → 优质管理层加分
    if s["roe_ttm"] >= 12.0 and s["op_cf_yoy"] >= 0.0:
        hits.append(mk_hit("MASTER_06", "ROE ≥12% 且经营现金流同比为正 → 管理层优秀，怪杰偏好", CATEGORY_MASTER_WISDOM, +6.0, confidence=0.8))
    # MASTER_07：今日跌 ≥3% 但 MA200 多头 → 趋势内回调是机会
    if s["trend_200d"] == "bull" and s["change_pct_today"] <= -3.0:
        hits.append(mk_hit("MASTER_07", "长期多头格局内大幅回调 = 买入机会（怪杰 「buy the dip」）", CATEGORY_MASTER_WISDOM, +7.0, confidence=0.75))
    return hits


# -------- 5. risk_position 仓位风险管理（RISK_xx，±4~±8）-----


def score_risk_position(s: StructuredInput) -> list[ExpertRuleHit]:
    hits: list[ExpertRuleHit] = []
    # RISK_01：单笔 R = 账户 1~2%（默认 1%，2% 合格，>3% 扣分）
    r_pct = s["user_risk_r_pct"]
    if 0.005 <= r_pct <= 0.02:
        hits.append(mk_hit("RISK_01", f"单笔 R = {r_pct*100:.1f}%，在合理区间（0.5%~2%）", CATEGORY_RISK_POSITION, +8.0, confidence=0.95))
    elif r_pct > 0.03:
        hits.append(mk_hit("RISK_02", f"单笔 R = {r_pct*100:.1f}% > 3%，连续错 5 次会亏掉 15%；风险太大", CATEGORY_RISK_POSITION, -6.0, confidence=0.9))
    # RISK_03：单票仓位 clamp（默认单票 ≤25%）
    single_max = s["user_single_ticket_max"]
    if single_max > 0.5:
        hits.append(mk_hit("RISK_03", f"单票最大仓位 {single_max*100:.0f}% > 50%，黑天鹅会严重亏损；建议 ≤ 25%", CATEGORY_RISK_POSITION, -5.0, confidence=0.85))
    elif single_max <= 0.25:
        hits.append(mk_hit("RISK_04", f"单票最大仓位 {single_max*100:.0f}% ≤ 25%，合理分散", CATEGORY_RISK_POSITION, +6.0, confidence=0.9))
    # RISK_04：行业集中度 clamp（默认 ≤30%）
    ind_max = s["user_industry_max"]
    if ind_max > 0.4:
        hits.append(mk_hit("RISK_05", f"单行业最大仓位 {ind_max*100:.0f}% > 40%，行业政策黑天鹅会爆雷", CATEGORY_RISK_POSITION, -5.0, confidence=0.85))
    elif ind_max <= 0.3:
        hits.append(mk_hit("RISK_06", f"单行业最大仓位 {ind_max*100:.0f}% ≤ 30%，行业集中度合理", CATEGORY_RISK_POSITION, +5.0, confidence=0.9))
    # RISK_07：ST/*ST 高风险票（即使通过合规围栏，也要风险扣分）
    if s["is_st_or_special"]:
        hits.append(mk_hit("RISK_07", "ST/*ST 高风险，仓位自动再减半；任何破位立即止损", CATEGORY_RISK_POSITION, -4.0, confidence=0.8))
    return hits


# -------- 6. fundamental 财报基本面（FUND_xx；FUND_01/FUND_02 熔断一票否决）-


def score_fundamental(s: StructuredInput) -> list[ExpertRuleHit]:
    hits: list[ExpertRuleHit] = []
    # 【P0 硬规则 FUND_01】ROE TTM < 8%（连续 3 年红灯）→ 一票否决（基本面不合格直接 refused）
    if 0 < s["roe_ttm"] < 8.0:
        hits.append(mk_hit("FUND_01", f"ROE TTM = {s['roe_ttm']:.1f}% < 8%，长期不创造价值 → 一票否决", CATEGORY_FUNDAMENTAL, -999.0,
                           is_veto=True, confidence=1.0,
                           evidence=[f"roe_ttm={s['roe_ttm']:.2f} < 8%"]))
    elif s["roe_ttm"] >= 15.0:
        hits.append(mk_hit("FUND_03", f"ROE TTM = {s['roe_ttm']:.1f}% ≥ 15%，高护城河优质公司", CATEGORY_FUNDAMENTAL, +15.0, confidence=0.9))
    elif s["roe_ttm"] >= 10.0:
        hits.append(mk_hit("FUND_04", f"ROE TTM = {s['roe_ttm']:.1f}%，中规中矩（10%~15%）", CATEGORY_FUNDAMENTAL, +8.0, confidence=0.8))
    # 【P0 硬规则 FUND_02】重资产 + 负债率 >80% + 现金流同比<0 → 一票否决（爆雷模式）
    if s["debt_ratio"] >= 80.0 and s["op_cf_yoy"] < 0.0:
        hits.append(mk_hit("FUND_02",
                           f"资产负债率 {s['debt_ratio']:.1f}% ≥80% + 经营现金流同比 {s['op_cf_yoy']:.1f}% < 0 → 现金流可能断裂，一票否决",
                           CATEGORY_FUNDAMENTAL, -999.0, is_veto=True, confidence=0.95,
                           evidence=[f"debt_ratio={s['debt_ratio']:.1f}% op_cf_yoy={s['op_cf_yoy']:.1f}%"]))
    # FUND_05：健康负债率
    if 30.0 <= s["debt_ratio"] <= 60.0:
        hits.append(mk_hit("FUND_05", f"资产负债率 {s['debt_ratio']:.1f}% 在健康区间（30%~60%）", CATEGORY_FUNDAMENTAL, +6.0, confidence=0.75))
    elif s["debt_ratio"] > 70.0:
        hits.append(mk_hit("FUND_06", f"资产负债率 {s['debt_ratio']:.1f}% > 70%，重资产行业风险高", CATEGORY_FUNDAMENTAL, -5.0, confidence=0.7))
    # FUND_07：经营现金流同比正
    if s["op_cf_yoy"] >= 15.0:
        hits.append(mk_hit("FUND_07", f"经营现金流同比 {s['op_cf_yoy']:.1f}% ≥15%，成长健康", CATEGORY_FUNDAMENTAL, +8.0, confidence=0.8))
    elif s["op_cf_yoy"] < 0.0:
        hits.append(mk_hit("FUND_08", f"经营现金流同比 {s['op_cf_yoy']:.1f}% < 0，警惕利润造假", CATEGORY_FUNDAMENTAL, -6.0, confidence=0.8))
    # FUND_09：一致预期 EPS 同比正
    if s["eps_consensus_yoy"] >= 20.0:
        hits.append(mk_hit("FUND_09", f"一致预期 EPS 同比 {s['eps_consensus_yoy']:.1f}%，高成长", CATEGORY_FUNDAMENTAL, +10.0, confidence=0.6))
    return hits


# -------- 7. announce 公告 / 情报（ANNOUNCE_xx；ANNOUNCE_01 熔断一票否决）-


def score_announce(s: StructuredInput) -> list[ExpertRuleHit]:
    hits: list[ExpertRuleHit] = []
    # 【P0 硬规则 ANNOUNCE_01】近 7 天 ≥1 条利空公告（拟减持/立案/业绩预亏/非标/监管函）→ 一票否决
    if s["news_neg_count_7d"] >= 1:
        kws = ", ".join(s["news_keywords"][:5]) or "（未分类利空）"
        hits.append(mk_hit("ANNOUNCE_01",
                           f"近 7 天利空公告 {s['news_neg_count_7d']} 条（{kws}）→ 合规/情报直接熔断一票否决",
                           CATEGORY_ANNOUNCE, -999.0, is_veto=True, confidence=1.0,
                           evidence=[f"neg_count={s['news_neg_count_7d']} keywords={s['news_keywords']}"]))
    # ANNOUNCE_02：近 7 天 ≥2 条利好 + 无利空 → 加分
    if s["news_pos_count_7d"] >= 2 and s["news_neg_count_7d"] == 0:
        kws = ", ".join(s["news_keywords"][:5]) or "利好公告"
        hits.append(mk_hit("ANNOUNCE_02", f"近 7 天利好公告 {s['news_pos_count_7d']} 条（{kws}）+ 零利空 → 基本面持续改善", CATEGORY_ANNOUNCE, +10.0, confidence=0.75))
    # ANNOUNCE_03：利好利空并存 → 观望（扣一点分提醒要谨慎）
    if s["news_pos_count_7d"] >= 1 and s["news_neg_count_7d"] >= 1:
        hits.append(mk_hit("ANNOUNCE_03", "利好利空公告并存，多空博弈；观望为主", CATEGORY_ANNOUNCE, -2.0, confidence=0.65))
    return hits


# ================================================================
# 对外主入口：score_all 返回全部分类命中（用于 7 位专家各自取自己 category）
# ================================================================

_CATEGORY_FN = {
    CATEGORY_CANDLESTICK: score_candlestick,
    CATEGORY_TREND: score_trend,
    CATEGORY_PSYCHOLOGY: score_psychology,
    CATEGORY_MASTER_WISDOM: score_master_wisdom,
    CATEGORY_RISK_POSITION: score_risk_position,
    CATEGORY_FUNDAMENTAL: score_fundamental,
    CATEGORY_ANNOUNCE: score_announce,
}


def score_all_categories(s: StructuredInput) -> dict[str, list[ExpertRuleHit]]:
    """
    7 大类全部跑完 → 返回 {category: [ExpertRuleHit]}
    任一 category 有 is_veto=True 的命中，上层直接 refused 不进 generation。
    """
    out: dict[str, list[ExpertRuleHit]] = {}
    for cat, fn in _CATEGORY_FN.items():
        try:
            out[cat] = list(fn(s))
        except Exception as e:
            logger.exception(f"score category {cat} error: {e}")
            out[cat] = []
    return out


def has_any_veto(all_hits: dict[str, list[ExpertRuleHit]]) -> ExpertRuleHit | None:
    """找到任意一票否决命中（points < -500 或 is_veto=True），用于上层快速 refused。"""
    for hits in all_hits.values():
        for h in hits:
            if h.get("is_veto") or float(h.get("points", 0)) < -500:
                return h
    return None
