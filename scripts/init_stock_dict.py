#!/usr/bin/env python3
"""
梯队 0.5 / P0-4 要求：初始化 A 股代码字典（~5000 只股票全量）。

从东方财富免费公开接口拉 5000 只全量 → 写入 Mongo stock_dict + Redis 24h 缓存。
每次启动 FastAPI 之前跑一次 `uv run python scripts/init_stock_dict.py`；
接口无额度 / 免费 / 零成本（路线 E 首选）。

如果东财免费接口被风控 / 超时 → 自动用本地 CSV 兜底（可选，第一次跑如果有 doc/stock_dict_baseline.csv 的话）。
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Any

from shopkeeper_kb import logging_config
from shopkeeper_kb.settings import get_settings
from shopkeeper_kb.tools.stock_dict import save_to_mongo_and_redis

EASTMONEY_CLIST_URL = (
    "https://80.push2.eastmoney.com/api/qt/clist/get"
    "?cb=&pn=1&pz=10000&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281"
    "&fltt=2&invt=2&wbp2u=&fid=f3"
    "&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
    "&fields=f12,f14,f2,f3,f100,f102,f103"
)
# 接口返回字段映射：
# f12 = ts_code 6 位代码
# f14 = 股票名称
# f2 = 现价
# f3 = 今日涨跌幅 %
# f100 = 申万一级行业名
# f102 = 申万二级行业名
# f103 = 上市日期（YYYYMMDD 整数 → 我们要转成 YYYY-MM-DD）


def _normalize_list_date(raw: Any) -> str:
    """把 f103 原始值（int 20180123 / str '20180123' / 0 / '-'）转成 YYYY-MM-DD，异常返回空串。"""
    if raw is None:
        return ""
    if isinstance(raw, (int, float)):
        if raw <= 0 or raw < 19900101 or raw > 21000101:
            return ""
        s = str(int(raw))
    else:
        s = str(raw).strip().replace("-", "").replace("/", "")
        if len(s) != 8 or not s.isdigit():
            return ""
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def _is_st(name: str) -> bool:
    """简单关键词判断是不是 ST/*ST/退市整理，合规围栏用（stock_dict 冗余存一份，合规围栏快查不用再调接口）。"""
    if not name:
        return False
    return any(k in name.upper() for k in ("ST", "*ST", "退", "S*ST", "NST"))


async def fetch_from_eastmoney() -> list[dict[str, Any]]:
    """从东财免费接口拉 5000 只全量（含北交所/主板/创业板/科创板，过滤 B 股/港股）。"""
    import httpx

    logging_config.info("Fetching full stock list from EastMoney free API...")
    start = time.time()
    async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=10), follow_redirects=True) as client:
        resp = await client.get(EASTMONEY_CLIST_URL)
        resp.raise_for_status()
        payload = resp.json()
    data = payload.get("data") or {}
    diff = data.get("diff") or []
    out: list[dict[str, Any]] = []
    skipped = 0
    for row in diff:
        code = str(row.get("f12") or "").strip()
        name = str(row.get("f14") or "").strip()
        if len(code) != 6 or not code.isdigit():
            skipped += 1
            continue  # 过滤掉 5 位港股 / 4 位北交所旧代码 / B 股美元等
        industry_l1 = str(row.get("f100") or "").strip()
        industry_l2 = str(row.get("f102") or "").strip()
        list_dt = _normalize_list_date(row.get("f103"))
        out.append({
            "code": code,
            "name": name,
            "market": "SH" if code.startswith(("6", "9")) else "SZ" if code.startswith(("0", "3", "2")) else "BJ",
            "industry_sw_level1": industry_l1 or "-",
            "industry_sw_level2": industry_l2 or "-",
            "list_date": list_dt,
            "is_st_or_special": _is_st(name),
            "last_close": float(row.get("f2")) if isinstance(row.get("f2"), (int, float)) and row.get("f2") != "-" else 0.0,
            "change_pct_today": float(row.get("f3")) if isinstance(row.get("f3"), (int, float)) and row.get("f3") != "-" else 0.0,
            "updated_at": int(time.time()),
        })
    elapsed = time.time() - start
    logging_config.info(
        "EastMoney fetch done: %d stocks fetched, %d skipped, elapsed=%.1fs",
        len(out), skipped, elapsed,
    )
    return out


def load_from_csv(path: str) -> list[dict[str, Any]]:
    """兜底：如果东财接口挂了，读 doc/stock_dict_baseline.csv（本地备份）。"""
    import csv

    logging_config.warning("Using CSV fallback: %s", path)
    out: list[dict[str, Any]] = []
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            code = (row.get("code") or "").strip().zfill(6)
            name = (row.get("name") or "").strip()
            if len(code) != 6:
                continue
            out.append({
                "code": code,
                "name": name,
                "market": (row.get("market") or "-").strip()[:2],
                "industry_sw_level1": (row.get("industry_sw_level1") or "-").strip(),
                "industry_sw_level2": (row.get("industry_sw_level2") or "-").strip(),
                "list_date": (row.get("list_date") or "").strip(),
                "is_st_or_special": _is_st(name),
                "last_close": float(row.get("last_close") or 0),
                "change_pct_today": float(row.get("change_pct_today") or 0),
                "updated_at": int(time.time()),
            })
    return out


async def async_main(fallback_csv: str | None) -> int:
    stocks: list[dict[str, Any]]
    try:
        stocks = await fetch_from_eastmoney()
    except Exception:
        logging_config.exception("EastMoney API failed")
        if fallback_csv:
            stocks = load_from_csv(fallback_csv)
        else:
            logging_config.error("No fallback CSV provided, abort.")
            return 2

    if not stocks:
        logging_config.error("No stocks loaded, abort.")
        return 3

    # 按东财 clist 接口默认只给 A 股主板/创业板/科创板，但我们冗余查一下有没有重复 code
    codes = {s["code"] for s in stocks}
    if len(codes) != len(stocks):
        logging_config.warning("Duplicate codes found: %d rows -> %d unique", len(stocks), len(codes))

    written = save_to_mongo_and_redis(stocks)
    logging_config.info("init_stock_dict.py DONE: %d written.", written)
    return 0


def main() -> int:
    settings = get_settings()
    logging_config.init_logging(settings.log_level)
    parser = argparse.ArgumentParser(description="初始化 A 股代码字典（东财免费接口 → Mongo + Redis）")
    parser.add_argument("--fallback-csv", default=None, help="东财接口失败时的本地 CSV 兜底路径（可选）")
    args = parser.parse_args()

    import asyncio
    try:
        return asyncio.run(async_main(args.fallback_csv))
    except KeyboardInterrupt:
        logging_config.warning("Interrupted by user")
        return 130


if __name__ == "__main__":
    sys.exit(main())
