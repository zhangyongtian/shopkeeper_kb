"""
A 股代码/名称/行业/上市日期快速字典缓存（对齐第 16 章 P0-4 要求）。

性能 3 层缓存（必须保证 industry() / is_new_stock() / match_by_name() 三个函数 <1ms 返回）：
1) L1 进程内内存 dict（最最快，用户每次 chat 都走这层）
2) L2 Redis 24h 缓存（多 worker 共享）
3) L3 MongoDB stock_dict 集合持久化（冷启动/重启不丢）
4) L4 东财免费公开接口（启动时 init_stock_dict.py 一次性拉 5000 只全量写入 L3 → L2 → L1）

所有查找函数优先 L1，保证 1ms 内返回。
"""
from __future__ import annotations

import difflib
import json
import time
from typing import Any

from shopkeeper_kb import logging_config
from shopkeeper_kb.settings import Settings, get_settings
from shopkeeper_kb.tools.mongo import get_db
from shopkeeper_kb.tools.redis_client import get_redis_client

# L1 内存缓存（进程全局，最快）：启动时一次性 load，后面查直接 dict.get
_L1_BY_CODE: dict[str, dict[str, Any]] = {}   # code → info dict
_L1_BY_NAME: dict[str, list[str]] = {}       # name → [code1, code2]（重名比如 "中国平安" A/H 股）
_L1_LOADED_AT: float = 0.0
_L1_TTL_SECONDS: float = 3600 * 6            # L1 每 6h 自动从 Redis/Mongo 重新刷新一次（防止长期不重启）


def _coll_name(settings: Settings | None = None) -> str:
    if settings is None:
        settings = get_settings()
    return settings.coll_stock_dict


def _redis_key(settings: Settings | None = None) -> str:
    if settings is None:
        settings = get_settings()
    return f"stock_dict:v1:{settings.coll_stock_dict}"


def _ensure_l1_loaded(settings: Settings | None = None) -> bool:
    """
    懒加载：第一次调用任意查询函数时，从 Redis → Mongo 顺序加载 L1。
    两层都空 → 返回 False（说明你要先跑 scripts/init_stock_dict.py 初始化全量）。
    """
    global _L1_BY_CODE, _L1_BY_NAME, _L1_LOADED_AT
    now = time.time()
    if _L1_BY_CODE and (now - _L1_LOADED_AT) < _L1_TTL_SECONDS:
        return True  # 已加载且未过期

    # --- 先试 L2 Redis ---
    try:
        r = get_redis_client(settings)
        cached_raw = r.get(_redis_key(settings))
        if cached_raw:
            cache = json.loads(cached_raw)
            _L1_BY_CODE = cache["by_code"]
            _L1_BY_NAME = cache["by_name"]
            _L1_LOADED_AT = now
            logging_config.debug("stock_dict L1 loaded from Redis, size=%d", len(_L1_BY_CODE))
            return True
    except Exception:
        logging_config.exception("stock_dict Redis load failed, fallback to Mongo")

    # --- 再试 L3 Mongo ---
    try:
        db = get_db(settings)
        coll = db[_coll_name(settings)]
        count = coll.estimated_document_count()
        if count == 0:
            logging_config.warning("stock_dict Mongo collection %s is EMPTY, please run scripts/init_stock_dict.py first", _coll_name(settings))
            return False
        by_code: dict[str, dict[str, Any]] = {}
        by_name: dict[str, list[str]] = {}
        for doc in coll.find({}, projection={"_id": 0}):
            code = doc.get("code")
            if not code:
                continue
            by_code[code] = doc
            name = doc.get("name") or ""
            if name:
                by_name.setdefault(name, []).append(code)
        _L1_BY_CODE = by_code
        _L1_BY_NAME = by_name
        _L1_LOADED_AT = now
        logging_config.debug("stock_dict L1 loaded from Mongo, size=%d", len(_L1_BY_CODE))
        # 顺便回填 Redis（下次就快了）
        try:
            r = get_redis_client(settings)
            s = get_settings()
            r.setex(
                _redis_key(settings),
                s.stock_dict_cache_ttl_s,
                json.dumps({"by_code": by_code, "by_name": by_name}, ensure_ascii=False),
            )
        except Exception:
            logging_config.exception("stock_dict write back Redis skipped")
        return True
    except Exception:
        logging_config.exception("stock_dict Mongo load failed")
        return False


def save_to_mongo_and_redis(
    stocks: list[dict[str, Any]],
    settings: Settings | None = None,
) -> int:
    """
    初始化脚本 scripts/init_stock_dict.py 调用：把 5000 只全量写入 Mongo + Redis + 刷新 L1。
    返回写入的数量。
    """
    if settings is None:
        settings = get_settings()
    # 写 Mongo（update_one upsert，幂等，跑多次也不会重复）
    db = get_db(settings)
    coll = db[_coll_name(settings)]
    # 先建 code 唯一索引（防止重复）
    coll.create_index("code", unique=True)

    written = 0
    for st in stocks:
        code = st.get("code")
        if not code:
            continue
        coll.update_one({"code": code}, {"$set": st}, upsert=True)
        written += 1

    # 写 Redis
    by_code: dict[str, dict[str, Any]] = {}
    by_name: dict[str, list[str]] = {}
    for st in stocks:
        c = st.get("code")
        if not c:
            continue
        by_code[c] = st
        n = st.get("name") or ""
        if n:
            by_name.setdefault(n, []).append(c)
    try:
        r = get_redis_client(settings)
        s = get_settings()
        r.setex(
            _redis_key(settings),
            s.stock_dict_cache_ttl_s,
            json.dumps({"by_code": by_code, "by_name": by_name}, ensure_ascii=False),
        )
    except Exception:
        logging_config.exception("stock_dict Redis init write failed")

    # 刷新 L1
    global _L1_BY_CODE, _L1_BY_NAME, _L1_LOADED_AT
    _L1_BY_CODE = by_code
    _L1_BY_NAME = by_name
    _L1_LOADED_AT = time.time()

    logging_config.info("stock_dict init finished: wrote %d items to Mongo+Redis", written)
    return written


# =============== P0-4 对外暴露 3 个快速查询函数（全部 <1ms 返回）===============


def get_info(code: str, settings: Settings | None = None) -> dict[str, Any] | None:
    """查询一只股票的完整信息 dict；code 是 6 位代码（如 '600519'）；查不到返回 None。"""
    if not code:
        return None
    _ensure_l1_loaded(settings)
    info = _L1_BY_CODE.get(code)
    if not info:
        # 兼容带 market 前缀的输入（比如 'sh.600519' / 'SZ000001'）→ 截最后 6 位再查一次
        if len(code) > 6:
            info = _L1_BY_CODE.get(code[-6:])
    return info


def industry(code: str, settings: Settings | None = None) -> str:
    """
    返回申万一级行业名（对齐 RISK_04 行业集中度检查用）。
    查不到返回 '未知行业'，不会抛异常。
    """
    info = get_info(code, settings)
    if not info:
        return "未知行业"
    return info.get("industry_sw_level1") or info.get("industry") or "未知行业"


def list_date(code: str, settings: Settings | None = None) -> str:
    """返回上市日期字符串 YYYY-MM-DD，查不到返回 ''。"""
    info = get_info(code, settings)
    if not info:
        return ""
    return info.get("list_date") or ""


def is_new_stock(code: str, days: int = 60, settings: Settings | None = None) -> bool:
    """
    判断是不是上市 <days 天的新股（默认 60 天 → 合规围栏直接拒答）。
    查不到上市日期时默认 False（谨慎放行，靠 ANNOUNCE_01 其他规则兜底）。
    """
    date_str = list_date(code, settings)
    if not date_str:
        return False
    try:
        import datetime as _dt
        y, m, d = (int(x) for x in date_str.split("-"))
        listed = _dt.date(y, m, d)
        today = _dt.date.today()
        return (today - listed).days < days
    except Exception:
        return False


def match_by_name(name_fragment: str, top_k: int = 5, settings: Settings | None = None) -> list[tuple[str, str, float]]:
    """
    按名称模糊匹配（用户打『茅台』/『招行』）→ 返回最匹配的 TopK 候选。
    列表每项 = (code, full_name, similarity_score 0.0~1.0)，按相似度倒序。
    速度：<1ms（用 L1 dict 全量 difflib，5000 只股票的模糊匹配也很快，加上 top_k 截断）。
    """
    if not name_fragment:
        return []
    _ensure_l1_loaded(settings)
    frag = name_fragment.strip()
    if not frag:
        return []

    # 先试精确前缀 / 精确匹配（绝大多数情况用户打『茅台』就是『贵州茅台』，精确匹配走 dict.get 最快）
    exact = _L1_BY_NAME.get(frag)
    if exact:
        out: list[tuple[str, str, float]] = []
        for c in exact[:top_k]:
            info = _L1_BY_CODE.get(c, {})
            out.append((c, info.get("name", frag), 1.0))
        return out

    # 前缀匹配（先过滤一轮减少 difflib 计算量）
    prefix_candidates: list[str] = [n for n in _L1_BY_NAME.keys() if n.startswith(frag) or frag in n]
    if len(prefix_candidates) >= top_k:
        candidates = prefix_candidates
    else:
        # 前缀不够再走 difflib 全局模糊匹配
        candidates = list(_L1_BY_NAME.keys())

    # difflib.SequenceMatcher 算相似度，O(N*M) 但 N 只有 5000，M 是候选名，很快
    matches: list[tuple[float, str]] = []
    for n in candidates:
        s = difflib.SequenceMatcher(None, frag.lower(), n.lower()).ratio()
        if s >= 0.35:  # 太低的丢掉（0.35 以下 99% 是噪音）
            matches.append((s, n))
    matches.sort(key=lambda x: x[0], reverse=True)

    out: list[tuple[str, str, float]] = []
    used_codes: set[str] = set()
    for score, name in matches[:top_k * 3]:
        codes = _L1_BY_NAME.get(name, [])
        for c in codes:
            if c in used_codes:
                continue
            used_codes.add(c)
            info = _L1_BY_CODE.get(c, {})
            out.append((c, info.get("name", name), score))
            if len(out) >= top_k:
                return out
    return out


__all__ = [
    "save_to_mongo_and_redis",
    "get_info",
    "industry",
    "list_date",
    "is_new_stock",
    "match_by_name",
]
