from __future__ import annotations

import re
from typing import Any

from shopkeeper_kb.logging_config import get_logger
from shopkeeper_kb.settings import Settings, get_settings
from shopkeeper_kb.tools.eastmoney_client import EastMoneyClient, get_eastmoney_client
from shopkeeper_kb.tools.stock_dict import get_info as stock_dict_lookup
from shopkeeper_kb.tools.stock_dict import industry as stock_dict_industry
from shopkeeper_kb.tools.stock_dict import is_new_stock as stock_dict_is_new_stock
from shopkeeper_kb.workflows.state import DirectionT, StructuredInput

logger = get_logger("shopkeeper_kb.extract_features")

# ------------------------------------------------------------------
# 梯队 2.3：合并 5 类信息 → StructuredInput（7大规则的唯一输入中间结构）
#   1) stock_dict（3 层缓存 <1ms）→ 行业/上市天数/是否ST
#   2) 东财实时行情 + K 线（免费公开接口）→ 量比/换手/MA50/MA200/支撑压力
#   3) 东财 F10 财务 → ROE/负债率/经营现金流同比
#   4) 东财公告 → 利空/利好计数 + 关键词
#   5) user_profile 用户画像 3 字段 + 持仓列表（从 Mongo user_profiles 取，匿名 UUID）
#
# P0-8 假设模式追问：detect_hypothetical_modifiers 命中关键词 → 直接覆写字段，不再重走数据拉取
# ------------------------------------------------------------------


def _ma_direction(above: bool, neutral: bool = False) -> DirectionT:
    if neutral:
        return "neutral"
    return "bull" if above else "bear"


def build_structured_input(
    *,
    stock_code: str,
    user_id: str | None = None,
    # ---- user_profile 默认值（Mongo user_profiles 拿不到时用合理默认）----
    user_account_capital: float | None = None,
    user_risk_r_pct: float | None = None,
    user_single_ticket_max: float | None = None,
    user_industry_max: float | None = None,
    user_risk_score: int | None = None,
    user_current_positions: list[dict[str, Any]] | None = None,
    # ---- 东财 client（允许外部传入，便于单测 mock）----
    client: EastMoneyClient | None = None,
    settings: Settings | None = None,
    # ---- P0-8 假设模式追问：覆写字段字典（if_clause_modifiers）----
    override: dict[str, Any] | None = None,
) -> tuple[StructuredInput, dict[str, Any]]:
    """
    返回：(StructuredInput, extra) — extra 里放上市天数 / 名称 / 行业等调试/合规围栏要用的字段
    """
    s = settings or get_settings()
    code = stock_code.strip()
    cli = client or get_eastmoney_client(s)

    # ------------------------------------------------------------------
    # Step 1：stock_dict 3 层缓存 <1ms
    # ------------------------------------------------------------------
    info = stock_dict_lookup(code) or {}
    stock_name = info.get("name") or code
    industry_sw_l1 = info.get("industry_sw_l1") or stock_dict_industry(code) or "（未分类行业）"
    list_days = int(info.get("list_days") or 0)
    if list_days <= 0:
        list_days = stock_dict_is_new_stock(code, days=999999) or 999999  # 取不到数据就当老股，不误杀
    is_st_or_special = bool(info.get("is_st_or_special")) or _judge_st_by_name(stock_name)

    # ------------------------------------------------------------------
    # Step 2：东财行情 + K线
    # ------------------------------------------------------------------
    rt = cli.get_realtime_quote(code)
    if rt.name and rt.name != code:
        stock_name = rt.name  # 东财的名称优先级更高（含 *ST 前缀）
    kline = cli.get_kline_summary(code, days=250)

    # ------------------------------------------------------------------
    # Step 3：东财 F10 财务
    # ------------------------------------------------------------------
    fund = cli.get_fundamentals(code)

    # ------------------------------------------------------------------
    # Step 4：东财公告 7 天利好/利空计数 + 关键词
    # ------------------------------------------------------------------
    news = cli.get_news_summary(code, days=7)

    # ------------------------------------------------------------------
    # Step 5：用户画像合理默认（Mongo user_profiles 取不到时，对应用户第一次进来的「默认散户配置」）
    # ------------------------------------------------------------------
    capital = float(user_account_capital or 100000.0)  # 默认 10 万本金
    r_pct = float(user_risk_r_pct or 0.01)                # 默认单笔 R = 1%
    single_max = float(user_single_ticket_max or 0.25)    # 单票 ≤ 25%
    ind_max = float(user_industry_max or 0.30)            # 单行业 ≤ 30%
    positions = list(user_current_positions or [])

    _ = user_id  # 预留：将来查 Mongo user_profiles 用

    # ------------------------------------------------------------------
    # 组装成 StructuredInput 36 字段（全部字段必填，绝不留 None）
    # ------------------------------------------------------------------
    out: StructuredInput = {  # type: ignore[typeddict-unknown-key]
        # ==== 个股基本信息 ====
        "stock_code": code,
        "stock_name": stock_name,
        "industry_sw_l1": industry_sw_l1,
        "list_days": list_days,
        "is_st_or_special": is_st_or_special,
        # ==== 东财行情（当日）====
        "last_close": float(rt.last_close or kline.ma50 or 0.0),
        "change_pct_today": float(rt.change_pct),
        "volume_ratio_today": float(rt.volume_ratio),
        "turnover_rate_today": float(rt.turnover_rate),
        # ==== K 线 / 形态（前复权日K）====
        "support_levels": list(kline.support_levels),
        "resistance_levels": list(kline.resistance_levels),
        "chart_features": _infer_chart_features(rt, kline, news),  # 关键词：箱体/放量破位/多头排列等
        "trend_50d": _ma_direction(kline.last_close_above_ma50),
        "trend_200d": _ma_direction(kline.last_close_above_ma200),
        # ==== 基本面（F10）====
        "roe_ttm": float(fund.roe_ttm),
        "debt_ratio": float(fund.debt_ratio),
        "op_cf_yoy": float(fund.op_cf_yoy),
        "eps_consensus_yoy": float(fund.eps_consensus_yoy),
        "target_price_consensus": float(fund.target_price_consensus),
        # ==== 资金流（北向/融资/龙虎榜；E 路线免费接口不稳定，先 0，不影响打分）====
        "north_net_inflow_5d": 0.0,
        "margin_net_buy_5d": 0.0,
        "dragon_tiger_net_buy_today": 0.0,
        # ==== 公告利好/利空（ANNOUNCE_01 熔断用）====
        "news_neg_count_7d": int(news.neg_count_7d),
        "news_pos_count_7d": int(news.pos_count_7d),
        "news_keywords": list(news.keywords),
        # ==== 用户画像 5 字段 + 当前持仓列表（P0-2 clamp 直接用）====
        "user_account_capital": capital,
        "user_risk_r_pct": r_pct,
        "user_single_ticket_max": single_max,
        "user_industry_max": ind_max,
        "user_current_positions": positions,
    }

    # ------------------------------------------------------------------
    # P0-8 假设模式追问：直接覆写字段（detect_hypothetical_modifiers 返回的 override dict 传进来即可）
    # 例：如果用户说「假如跌破 1640 止损」→ override = {"support_levels": [1600,1640]}
    # 覆写之后直接进 2.4 expert_rules.score()，**不重走 Milvus**（5× 快）
    # ------------------------------------------------------------------
    if override:
        for k, v in override.items():
            if k in StructuredInput.__annotations__ and v is not None:
                out[k] = v  # type: ignore[literal-required]
        logger.info(f"P0-8 假设模式追问覆写 {len(override)} 个字段，不重走 Milvus")

    extra: dict[str, Any] = {
        "stock_name": stock_name,
        "industry_sw_l1": industry_sw_l1,
        "list_days": list_days,
        "is_st_or_special": is_st_or_special,
        "user_risk_score": int(user_risk_score or 70),  # 默认 70 分（普通散户，<80 禁玩 ST）
        "user_account_capital": capital,
        "user_risk_r_pct": r_pct,
        "user_single_ticket_max": single_max,
        "user_industry_max": ind_max,
        "user_current_positions": positions,
        "rt_quote": rt,
        "kline": kline,
        "fundamentals": fund,
        "news": news,
    }
    return out, extra


# ================================================================
# Helper：从 名称判断 ST / *ST
# ================================================================
def _judge_st_by_name(name: str) -> bool:
    return ("ST" in name) or ("退市" in name)


# ================================================================
# Helper：根据 K线+放量/换手 → 推断 chart_features 关键词（供形态/趋势专家规则触发用）
# ================================================================

def _infer_chart_features(rt, kline, news) -> list[str]:  # type: ignore[no-untyped-def]
    feats: list[str] = []
    # MA50 & MA200 方向组合
    if kline.last_close_above_ma200 and kline.last_close_above_ma50:
        feats.append("多头排列")
    if not kline.last_close_above_ma200 and not kline.last_close_above_ma50:
        feats.append("空头排列")
    # 放量：量比 > 2
    if rt.volume_ratio >= 2.0:
        feats.append("放量")
        if rt.change_pct <= -3.0:
            feats.append("放量破位")
        if rt.change_pct >= 3.0:
            feats.append("放量突破")
    # 高换手：日换手率 ≥ 15%
    if rt.turnover_rate >= 15.0:
        feats.append("高换手")
    # 箱体：支撑位 - 压力位区间 < 15%
    if kline.support_levels and kline.resistance_levels:
        low = min(kline.support_levels)
        high = max(kline.resistance_levels)
        if 0 < low < high and (high - low) / low <= 0.15:
            feats.append("箱体震荡")
    # 利好/利空关键词
    if news and news.neg_count_7d:
        feats.append("利空消息")
    if news and news.pos_count_7d >= 2:
        feats.append("利好消息")
    return feats


# ================================================================
# P0-8 假设模式：检测 query 中「假如/如果/假设」+ 关键字段 → 返回 override dict
# ================================================================
_HYPOTHETICAL_PATTERNS = [
    # re pattern, StructuredInput.field, coerce func
    (r"(?:假如|如果|假设).*?(?:止损|跌破|支撑)[^\d]{0,8}(\d+(?:\.\d+)?)", "support_levels", lambda m: [float(m.group(1)) - 2.0, float(m.group(1))]),
    (r"(?:假如|如果|假设).*?(?:止盈|压力|突破)[^\d]{0,8}(\d+(?:\.\d+)?)", "resistance_levels", lambda m: [float(m.group(1)), float(m.group(1)) + 3.0]),
    (r"(?:假如|如果|假设).*?ROE[^\d]{0,4}(?:降到|低于|为)[^\d]{0,4}(\d+(?:\.\d+)?)", "roe_ttm", lambda m: float(m.group(1))),
    (r"(?:假如|如果|假设).*?(?:换手率|换手)[^\d]{0,4}(\d+(?:\.\d+)?)", "turnover_rate_today", lambda m: float(m.group(1))),
    (r"(?:假如|如果|假设).*?(?:涨跌幅|涨跌|跌了|涨了)[^\d]{0,4}(-?\d+(?:\.\d+)?)", "change_pct_today", lambda m: float(m.group(1))),
]


def detect_hypothetical_modifiers(query: str) -> dict[str, Any] | None:
    """
    P0-8：检测到「假如/如果/假设」+ 字段关键词 → 返回可直接传给 build_structured_input(override=...) 的 dict；
    没检测到就返回 None，走正常全流程。
    """
    q = query or ""
    if not any(k in q for k in ("假如", "如果", "假设")):
        return None
    out: dict[str, Any] = {}
    for pat, field, fn in _HYPOTHETICAL_PATTERNS:
        m = re.search(pat, q)
        if m:
            try:
                out[field] = fn(m)
            except Exception:
                pass
    return out if out else None
