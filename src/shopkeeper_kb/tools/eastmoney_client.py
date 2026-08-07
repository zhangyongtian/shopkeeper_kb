from __future__ import annotations

import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx

from shopkeeper_kb.logging_config import get_logger
from shopkeeper_kb.settings import Settings, get_settings

logger = get_logger("shopkeeper_kb.eastmoney")

# ------------------------------------------------------------------
# 路线 E 零成本：全部用东方财富公开的免费 HTTP 接口（不买 Tushare 120 元永久）
# 所有接口用 httpx AsyncClient + 2 个单例（sync / async），全局共享连接池
# ------------------------------------------------------------------

_EASTMONEY_PUSH2_CLIST = "http://push2.eastmoney.com/api/qt/clist/get"
_EASTMONEY_PUSH2_STOCK = "http://push2.eastmoney.com/api/qt/stock/get"
_EASTMONEY_EMWEB_KLINE = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
_EASTMONEY_F10_FINANCE = "https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/ZYZBAjaxNew"
_EASTMONEY_NOTICES = "http://np-anotice-stock.eastmoney.com/api/security/ann"
_EASTMONEY_HSGT = "http://push2.eastmoney.com/api/qt/hsgt/nf1/get"
_EASTMONEY_MARGIN = "http://push2.eastmoney.com/api/qt/stock/margin/get"


def _market_prefix(code: str) -> str:
    """6 位代码 → 东财 secid：1.xxx（沪） / 0.xxx（深 / 北 / 创业板 / 科创板）"""
    code = code.strip()
    if code.startswith(("6", "9")):
        return f"1.{code}"
    return f"0.{code}"


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        s = str(v).strip().replace(",", "")
        if not s or s in {"-", "--", "null", "None"}:
            return default
        return float(s)
    except Exception:
        return default


def _to_int(v: Any, default: int = 0) -> int:
    return int(_to_float(v, float(default)))


@dataclass
class RealtimeQuote:
    code: str
    name: str
    last_close: float          # T-1 收盘价
    cur_price: float           # 最新价
    change_pct: float          # 今日涨跌幅（%，正负）
    volume_ratio: float        # 量比
    turnover_rate: float       # 换手率（%）
    pe_ttm: float              # 静态 PE
    market_cap: float          # 总市值（亿元）


@dataclass
class KlineSummary:
    code: str
    ma50: float                # 50 日均线
    ma200: float               # 200 日均线
    last_close_above_ma50: bool
    last_close_above_ma200: bool
    support_levels: list[float]  # 支撑位（从低到高 2~3 个）
    resistance_levels: list[float]  # 压力位（从低到高 2~3 个）


@dataclass
class Fundamentals:
    code: str
    roe_ttm: float              # ROE TTM（%）；连续 3 年 < 8% → FUND_01 熔断
    debt_ratio: float            # 资产负债率（%）；>70% → FUND_02 扣分
    op_cf_yoy: float             # 经营现金流同比（%）；负 → FUND_02 扣分
    eps_consensus_yoy: float     # 一致预期 EPS 同比（%）；没有则 0
    target_price_consensus: float  # 一致预期目标价；没有则 0


@dataclass
class CapitalFlow:
    code: str
    north_net_inflow_5d: float    # 北向资金 5 日累计净流入（亿元）
    margin_net_buy_5d: float      # 融资余额 5 日净买入（亿元）
    dragon_tiger_net_buy_today: float  # 龙虎榜今日净买入（亿元）；没有则 0


@dataclass
class NewsSummary:
    code: str
    neg_count_7d: int             # 近 7 天利空公告条数（ANNOUNCE_01 熔断：拟减持/立案/业绩预亏/非标/监管函 → 直接熔断）
    pos_count_7d: int             # 近 7 天利好公告条数
    keywords: list[str]           # 近 7 天公告关键词（情报师发言用）

# 公告关键词字典（ANNOUNCE_01 熔断用）
_NEG_KEYWORDS = [
    "拟减持", "减持计划", "股东减持", "立案调查", "立案告知", "业绩预亏",
    "业绩大幅下降", "向下修正", "非标意见", "无法表示意见", "保留意见",
    "监管函", "警示函", "问询函", "退市风险", "终止上市", "*ST",
    "商誉减值", "重大诉讼", "欺诈发行", "财务造假", "信息披露违法",
]
_POS_KEYWORDS = [
    "股权激励", "员工持股", "回购股份", "业绩预增", "业绩大幅上升",
    "重大合同", "中标", "增持", "举牌", "新产品上市", "获得批件",
    "政策利好", "行业景气", "超预期", "分红", "高送转",
]


# ================================================================
# Sync Client（FastAPI 同步路由 / 脚本直接用；单例）
# ================================================================

@lru_cache(maxsize=1)
def _sync_client() -> httpx.Client:
    timeout = httpx.Timeout(8.0, connect=4.0)
    limits = httpx.Limits(max_connections=16, max_keepalive_connections=4)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36",
        "Referer": "https://quote.eastmoney.com/",
    }
    return httpx.Client(timeout=timeout, limits=limits, headers=headers, follow_redirects=True)


class EastMoneyClient:
    """东财公开免费 HTTP 接口封装；异常捕获 → 返回默认值（P1-2 优雅降级），不把异常抛到上层。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.http = _sync_client()

    # ------------------------------------------------------------------
    # 实时行情（push2 / api/qt/stock/get → 量比 / 换手率 / 涨跌幅 一步到位）
    # ------------------------------------------------------------------
    def get_realtime_quote(self, code: str) -> RealtimeQuote:
        secid = _market_prefix(code)
        params = {
            "secid": secid,
            "fields": "f43,f44,f45,f46,f47,f48,f50,f51,f52,f55,f57,f58,f60,f116,f117,f162,f167,f168,f169,f170,f171,f177",
            "ut": "fa5fd1943c7b386f172d6893dbbdca5e",
        }
        try:
            r = self.http.get(_EASTMONEY_PUSH2_STOCK, params=params)
            r.raise_for_status()
            data = (r.json() or {}).get("data") or {}
            # 字段含义来自东财公开文档
            last_close = _to_float(data.get("f60")) / 100.0          # 昨收
            cur_price = _to_float(data.get("f43")) / 100.0 or last_close  # 最新价
            change_pct = _to_float(data.get("f170")) / 100.0           # 涨跌幅 %
            volume_ratio = _to_float(data.get("f50")) / 100.0          # 量比
            turnover_rate = _to_float(data.get("f168")) / 100.0        # 换手率 %
            pe_ttm = _to_float(data.get("f167")) / 100.0               # PE TTM
            market_cap = _to_float(data.get("f116")) / 1e8             # 总市值（亿）
            name = str(data.get("f58") or code)
            return RealtimeQuote(
                code=code, name=name, last_close=last_close, cur_price=cur_price,
                change_pct=change_pct, volume_ratio=volume_ratio, turnover_rate=turnover_rate,
                pe_ttm=pe_ttm, market_cap=market_cap,
            )
        except Exception as e:
            logger.warning(f"eastmoney get_realtime_quote {code} fail: {e}; 优雅降级返回 0 字段")
            return RealtimeQuote(code=code, name=code, last_close=0.0, cur_price=0.0,
                                 change_pct=0.0, volume_ratio=0.0, turnover_rate=0.0, pe_ttm=0.0, market_cap=0.0)

    # ------------------------------------------------------------------
    # K线：前复权日 K → 算 MA50 / MA200 + 支撑压力位（近 250 根 = 约 1 年）
    # ------------------------------------------------------------------
    def get_kline_summary(self, code: str, days: int = 250) -> KlineSummary:
        secid = _market_prefix(code)
        params = {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",         # 101 = 日 K
            "fqt": "1",           # 1 = 前复权
            "end": "20500101",
            "lmt": str(days),
            "ut": "fa5fd1943c7b386f172d6893dbbdca5e",
        }
        try:
            r = self.http.get(_EASTMONEY_EMWEB_KLINE, params=params)
            r.raise_for_status()
            data = (r.json() or {}).get("data") or {}
            klines = data.get("klines") or []
            if not klines:
                raise ValueError("no klines")
            closes: list[float] = []
            for line in klines:
                parts = line.split(",")
                if len(parts) >= 3:
                    closes.append(_to_float(parts[2]))  # index 2 = 收盘
            if len(closes) < 20:
                raise ValueError(f"closes < 20: {len(closes)}")
            ma50 = sum(closes[-50:]) / min(len(closes), 50)
            ma200 = sum(closes[-200:]) / min(len(closes), 200)
            last_close = closes[-1]
            # 支撑/压力位：近 60 日 前低/前高 + MA50 + MA200
            recent60 = closes[-60:]
            support = sorted(set([
                round(min(recent60), 2),
                round(min(recent60[-20:]), 2),
                round(ma50, 2),
            ]))
            resistance = sorted(set([
                round(max(recent60), 2),
                round(max(recent60[-20:]), 2),
                round(ma200, 2),
            ]))
            return KlineSummary(
                code=code, ma50=round(ma50, 2), ma200=round(ma200, 2),
                last_close_above_ma50=last_close >= ma50,
                last_close_above_ma200=last_close >= ma200,
                support_levels=[x for x in support if x < last_close * 1.02][:3],
                resistance_levels=[x for x in resistance if x > last_close * 0.98][:3],
            )
        except Exception as e:
            logger.warning(f"eastmoney get_kline_summary {code} fail: {e}; 优雅降级返回中性")
            return KlineSummary(code=code, ma50=0.0, ma200=0.0,
                                last_close_above_ma50=True, last_close_above_ma200=True,
                                support_levels=[], resistance_levels=[])

    # ------------------------------------------------------------------
    # 基本面：F10 ZYZB（主要财务指标 → ROE TTM / 负债率 / 经营现金流同比）
    # ------------------------------------------------------------------
    def get_fundamentals(self, code: str) -> Fundamentals:
        secid = _market_prefix(code)
        params = {
            "type": "0",
            "code": secid.split(".")[-1],
            "sty": "ALL",
            "filter": f"(securitycode={code})",
            "p": "1",
            "ps": "100",
        }
        try:
            r = self.http.get(_EASTMONEY_F10_FINANCE, params=params, timeout=httpx.Timeout(15, connect=8))
            r.raise_for_status()
            data = r.json() or {}
            result = data.get("result") or []
            if not result:
                raise ValueError("no f10 data")
            # ZYZBAjaxNew 的 list[dict] 里最近一期 = result[-1]（按报告期排）
            latest = result[-1] if result else {}
            roe_ttm = _to_float(latest.get("ROEJQ"), 0.0)       # 加权 ROE 近 12 个月
            debt_ratio = _to_float(latest.get("ZCFZYL"), 0.0)   # 资产负债率 %
            op_cf_yoy = _to_float(latest.get("YYSRZZL"), 0.0)   # 营收同比作近似（没有专门经营现金流同比就复用，避免漏 0）
            return Fundamentals(
                code=code, roe_ttm=roe_ttm, debt_ratio=debt_ratio, op_cf_yoy=op_cf_yoy,
                eps_consensus_yoy=0.0, target_price_consensus=0.0,
            )
        except Exception as e:
            logger.warning(f"eastmoney get_fundamentals {code} fail: {e}; 优雅降级返回 0")
            return Fundamentals(code=code, roe_ttm=0.0, debt_ratio=0.0, op_cf_yoy=0.0,
                                eps_consensus_yoy=0.0, target_price_consensus=0.0)

    # ------------------------------------------------------------------
    # 资金流：北向 5 日 / 融资余额 5 日 / 龙虎榜今日
    # ------------------------------------------------------------------
    def get_capital_flow(self, code: str) -> CapitalFlow:
        # 北向 / 融资 / 龙虎榜免费接口都比较复杂且不稳定，这里先用 0 默认值（数据缺失不影响打分，只是 CAPITAL_01~03 不给分）
        # 真正 E 路线 5 日北向可以用 push2 抓沪深港通板块再对应当日股票，后续梯队 3 精细化补；现在先返回 0 不抛错
        try:
            # 轻量：尝试龙虎榜单只查询，如果失败就 0
            params = {
                "secid": _market_prefix(code),
                "fields": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
                "ut": "fa5fd1943c7b386f172d6893dbbdca5e",
            }
            self.http.get("http://push2.eastmoney.com/api/qt/stock/lhb/get", params=params, timeout=3)
        except Exception:
            pass
        return CapitalFlow(code=code, north_net_inflow_5d=0.0, margin_net_buy_5d=0.0, dragon_tiger_net_buy_today=0.0)

    # ------------------------------------------------------------------
    # 近 7 天公告利空 / 利好计数（ANNOUNCE_01 熔断：>0 条利空即触发）
    # ------------------------------------------------------------------
    def get_news_summary(self, code: str, days: int = 7) -> NewsSummary:
        params = {
            "sr": "-1",
            "page_size": "50",
            "page_index": "1",
            "ann_type": "A",
            "client_source": "web",
            "f_node": "0",
            "s_node": "0",
            "stock_list": _market_prefix(code).split(".")[-1],
            "s_date": time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400)),
            "e_date": time.strftime("%Y-%m-%d"),
        }
        try:
            r = self.http.get(_EASTMONEY_NOTICES, params=params, timeout=8)
            r.raise_for_status()
            data = r.json() or {}
            items = (data.get("data") or {}).get("list") or []
            titles = [str((it or {}).get("title") or "") for it in items]
            neg = sum(1 for t in titles if any(k in t for k in _NEG_KEYWORDS))
            pos = sum(1 for t in titles if any(k in t for k in _POS_KEYWORDS))
            kws: list[str] = []
            for t in titles:
                for k in _NEG_KEYWORDS + _POS_KEYWORDS:
                    if k in t and k not in kws:
                        kws.append(k)
            return NewsSummary(code=code, neg_count_7d=neg, pos_count_7d=pos, keywords=kws[:15])
        except Exception as e:
            logger.warning(f"eastmoney get_news_summary {code} fail: {e}; 优雅降级返回 0")
            return NewsSummary(code=code, neg_count_7d=0, pos_count_7d=0, keywords=[])


@lru_cache(maxsize=1)
def get_eastmoney_client(settings: Settings | None = None) -> EastMoneyClient:
    return EastMoneyClient(settings)
