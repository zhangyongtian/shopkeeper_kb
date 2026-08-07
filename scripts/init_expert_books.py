#!/usr/bin/env python3
"""
梯队 0.6 / 0.3 开放架构要求：初始化 expert_books 集合（7 条默认样板专家）。

⚠️  核心工程红线（对齐第 12 节禁止事项 5/6：
   ① 只在集合 **完全为空** 时，才 upsert 7 条默认样板；
   ② 若集合内已有任何一条文档（不管是用户 admin API 加的，还是手工加的）→ 本脚本 **绝不覆盖、绝不删除、绝不追加重复插入，立即打印一行提示就退出。
   ③ doc_type 上唯一索引，谁也不能重复（包括脚本、admin API），所以重复跑也会被 Mongo DuplicateKeyError 挡掉，保证唯一性。

这样设计 = 完全开放，不是锁死 7 本：用户可以随时 POST /api/admin/register_book 加新书，脚本跑多少次都不会覆盖用户添加的书！
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Any

from pymongo import errors as pymongo_errors

from shopkeeper_kb import logging_config
from shopkeeper_kb.settings import get_settings
from shopkeeper_kb.tools.mongo import get_db

DEFAULT_SEVEN_EXPERTS: list[dict[str, Any]] = [
    # 7 位默认专家样板（对应你现有的 5 本 PDF + 财报占位 + 情报师，按 Todo 第 0.3 节顺序写的颜色对齐）
    {
        "doc_type": "candlestick",
        "pdf_name": "日本蜡烛图技术.pdf",
        "display_name": "形态分析专家（蜡烛图）",
        "expert_role": "形态师",
        "emoji_tag": "📕",
        "color": "#ff6b6b",  # 🔴 形态：和 14.1 CSS 变量 --c-candlestick 对齐
        "priority": 1,
        "disabled": False,
        "weight": 1.0,
        "historical_accuracy": 0.0,  # V4-4 自动打标后回灌
        "historical_total": 0,
        "historical_correct": 0,
        "fixed_mantra": "我只看形态，不讲故事。形态说了算，其他都是噪音。",
        "domain_keywords": ["K线", "蜡烛图", "形态", "黄昏之星", "启明星", "吞没", "三白兵", "十字星", "头肩", "双顶"],
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
    },
    {
        "doc_type": "technical_trend",
        "pdf_name": "金融市场技术分析.pdf",
        "display_name": "趋势量价指标专家（约翰·墨菲）",
        "expert_role": "趋势师",
        "emoji_tag": "📗",
        "color": "#ffa940",  # 🟠 趋势
        "priority": 2,
        "disabled": False,
        "weight": 1.0,
        "historical_accuracy": 0.0,
        "historical_total": 0,
        "historical_correct": 0,
        "fixed_mantra": "我不抢跑，等破位再动手。趋势为王，别跟市场较劲。",
        "domain_keywords": ["均线", "MACD", "趋势", "量价", "背离", "RSI", "KDJ", "布林带", "支撑", "压力"],
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
    },
    {
        "doc_type": "fundamental",
        "pdf_name": "手把手教你读财报（唐朝）.pdf",
        "display_name": "财报基本面排雷师",
        "expert_role": "基本面师",
        "emoji_tag": "📊",
        "color": "#fadb14",  # 🟡 财报
        "priority": 3,
        "disabled": True,  # 占位：PDF 有了再开（对应 0.3 节写的默认 disabled=true
        "weight": 1.0,
        "historical_accuracy": 0.0,
        "historical_total": 0,
        "historical_correct": 0,
        "fixed_mantra": "先看排雷，再谈赚钱。红灯直接一票否决，别在垃圾堆里找黄金。",
        "domain_keywords": ["财报", "ROE", "毛利率", "现金流", "资产负债率", "扣非", "利润", "营收", "排雷", "杜邦"],
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
    },
    {
        "doc_type": "psychology",
        "pdf_name": "交易心理分析.pdf",
        "display_name": "交易心理教练",
        "expert_role": "心理师",
        "emoji_tag": "📘",
        "color": "#73d13d",  # 🟢 心理
        "priority": 4,
        "disabled": False,
        "weight": 1.0,
        "historical_accuracy": 0.0,
        "historical_total": 0,
        "historical_correct": 0,
        "fixed_mantra": "先看你自己，再看市场。纪律比预测重要 100 倍。",
        "domain_keywords": ["纪律", "止损", "心态", "贪婪", "恐惧", "交易心理", "追涨杀跌", "回撤容忍", "认知偏差"],
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
    },
    {
        "doc_type": "master_wisdom",
        "pdf_name": "金融怪杰.pdf",
        "display_name": "大师经验对照师",
        "expert_role": "大师经验",
        "emoji_tag": "📙",
        "color": "#40a9ff",  # 🔵 大师
        "priority": 5,
        "disabled": False,
        "weight": 1.0,
        "historical_accuracy": 0.0,
        "historical_total": 0,
        "historical_correct": 0,
        "fixed_mantra": "历史不会简单重复，但惊人地相似。看看大师们当年踩过的坑，再下手。",
        "domain_keywords": ["大师经验", "失败教训", "回撤控制", "盈利模式", "幸存者偏差", "习惯", "胜率", "盈亏比"],
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
    },
    {
        "doc_type": "risk_position",
        "pdf_name": "通向财务自由之路.pdf",
        "display_name": "风控仓位系统师（范·K·撒普）",
        "expert_role": "仓位师",
        "emoji_tag": "📓",
        "color": "#b37feb",  # 🟣 仓位风控
        "priority": 6,
        "disabled": False,
        "weight": 1.2,  # 风控权重稍微高一点（对应 0.3 节 priority 6，风险是最后说话更有分量，因为保命）
        "historical_accuracy": 0.0,
        "historical_total": 0,
        "historical_correct": 0,
        "fixed_mantra": "方向再对，仓位错，一样亏光。R 倍数、止损、总仓位才是真功夫。",
        "domain_keywords": ["仓位", "止损", "R倍数", "盈亏比", "风控", "凯利公式", "ATR", "分散", "总仓位控制"],
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
    },
    {
        "doc_type": "news_capital_flow",
        "pdf_name": "",  # 不是 PDF，虚拟专家
        "display_name": "情报分析师（新闻+公告+资金面）",
        "expert_role": "情报师",
        "emoji_tag": "⚫",
        "color": "#8c8c8c",  # ⚫ 情报
        "priority": 7,
        "disabled": False,
        "weight": 1.0,
        "historical_accuracy": 0.0,
        "historical_total": 0,
        "historical_correct": 0,
        "fixed_mantra": "听消息炒股死得快，但完全不看消息死得更快。我给你过滤噪音只看硬信号。",
        "domain_keywords": ["新闻", "公告", "减持", "增持", "回购", "北向", "融资", "龙虎榜", "立案", "监管函"],
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
    },
]


def ensure_indices(coll) -> None:
    """建两个索引：1) doc_type 唯一（工程红线，必须有，谁都不能重复）；2) priority 普通索引（查 enabled & priority 排序快）"""
    coll.create_index("doc_type", unique=True, name="uk_expert_books_doc_type")
    coll.create_index([("disabled", 1), ("priority", 1)], name="idx_enabled_priority")


def seed_if_empty(force: bool = False) -> tuple[int, int]:
    """
    核心逻辑：
    1. count_documents == 0 → 全量插入 7 条（只有第一次跑会走这里）
    2. 有任何文档 → 不插入，打印已有数量，退出（绝不覆盖用户加的书，对应开放架构要求）
    3. force=True 时，会把默认 7 条 upsert（但不删除其他 doc_type，只 upsert 7 条已有的 doc_type
       —— 用于修复默认字段，但仍然绝不删除用户手工加的新书！

    返回 (inserted_or_upserted_count, existed_count)
    """
    settings = get_settings()
    db = get_db()
    coll = db[settings.coll_expert_books]

    ensure_indices(coll)
    existed = coll.estimated_document_count()

    if existed > 0 and not force:
        logging_config.info(
            "expert_books already has %d docs. OPEN ARCHITECTURE: seed skipped inserting default 7 (will NOT overwrite user-added books).",
            existed,
        )
        return 0, existed

    written = 0
    for doc in DEFAULT_SEVEN_EXPERTS:
        doc["updated_at"] = int(time.time())
        try:
            res = coll.update_one(
                {"doc_type": doc["doc_type"]},
                {
                    "$setOnInsert": {k: v for k, v in doc.items() if k != "updated_at"},
                    "$set": {"updated_at": doc["updated_at"]},
                },
                upsert=True,
            )
            if res.upserted_id is not None or res.modified_count > 0:
                written += 1
        except pymongo_errors.DuplicateKeyError:
            # 唯一索引 race 兜底（理论上 upsert 不会抛）
            logging_config.warning("doc_type=%s duplicate key skipped (unique index ok)", doc["doc_type"])

    final_count = coll.estimated_document_count()
    logging_config.info(
        "expert_books seed finished: force=%s written=%d total_in_coll=%d",
        force, written, final_count,
    )
    return written, final_count


def main() -> int:
    settings = get_settings()
    logging_config.init_logging(settings.log_level)
    parser = argparse.ArgumentParser(
        description="初始化 expert_books 7 位默认专家（开放架构，仅在集合为空时插入，绝不覆盖用户加的书）"
    )
    parser.add_argument(
        "--force-upsert-defaults",
        action="store_true",
        help="只 upsert 7 条默认专家的字段（修复缺失字段用），但仍然不删除用户新增的其他 doc_type 文档（安全模式）",
    )
    args = parser.parse_args()

    written, final = seed_if_empty(force=args.force_upsert_defaults)
    print(f"✅ init_expert_books done: written={written}, total_in_collection={final}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
