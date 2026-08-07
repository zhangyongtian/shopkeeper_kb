"""
NodeItemNameRecognition：主体识别 + doc_type 推断（骨架阶段走规则匹配，不依赖 LLM）。
职责（单节点单职责）：
  1) 读取 file_title / md_content 前 40 行 / user_doc_type
  2) 若 user 传了 user_doc_type，直接信它（兜底写 item_name=file_title）
  3) 否则按 7 位专家 doc_type 关键词匹配：出现「蜡烛/酒田/K线」→ candlestick；「趋势/均线/MACD」→ technical_trend；
     「财报/资产负债/利润表/现金流」→ fundamental；「怪杰/投资/利弗莫尔/禅师/交易心理」→ master_wisdom 等；
     匹配不到 → other
  4) 产出 item_name / item_type / item_tags / doc_type / display_name 给 N4~N6 使用（chunks.doc_type = 这里产出的 doc_type）
"""
from __future__ import annotations

import re
from collections import OrderedDict

from shopkeeper_kb import logging_config as log
from shopkeeper_kb.workflows.base_node import NodeBase
from shopkeeper_kb.workflows.state import ImportGraphState

# 规则库（doc_type → 关键词列表；命中的关键词数越多，得分越高，最终 display_name 用它的标准名）
DOC_TYPE_RULES: OrderedDict[str, dict] = OrderedDict(
    [
        ("candlestick", {
            "display_name": "日本蜡烛图技术",
            "item_type": "book",
            "keywords": ["蜡烛", "酒田战法", "k线", "Ｋ线", "阴阳线", "阳线", "阴线", "锤子线", "吞没形态", "doji", "十字星"],
        }),
        ("technical_trend", {
            "display_name": "股票趋势技术分析",
            "item_type": "book",
            "keywords": ["道氏理论", "趋势", "移动平均", "均线", "ma5", "ma20", "ma200", "macd", "rsi", "kdj", "boll", "布林", "头肩", "支撑位", "压力位", "突破", "回撤", "technical trend"],
        }),
        ("psychology", {
            "display_name": "交易心理分析",
            "item_type": "book",
            "keywords": ["交易心理", "认知偏差", "贪婪", "恐惧", "沉没成本", "锚定", "过度自信", "discipline", "纪律", "心态", "交易赢家", "心理优势"],
        }),
        ("master_wisdom", {
            "display_name": "金融怪杰 · 投资大师语录",
            "item_type": "book",
            "keywords": ["金融怪杰", "market wizards", "利弗莫尔", "livermore", "缠中说禅", "禅师", "巴菲特", "芒格", "达利欧", "索罗斯", "彼得林奇", "施瓦格", "克罗", "青泽", "大作手"],
        }),
        ("risk_position", {
            "display_name": "以交易为生 · 仓位/风控",
            "item_type": "book",
            "keywords": ["仓位管理", "凯利公式", "止损", "止盈", "r/r", "盈亏比", "单笔风险", "资金曲线", "最大回撤", "以交易为生", "以趋势跟踪为生", "risk management", "position sizing"],
        }),
        ("fundamental", {
            "display_name": "手把手教你读财报",
            "item_type": "book",
            "keywords": ["财报", "资产负债表", "利润表", "现金流量表", "roe", "毛利率", "pe", "pb", "dcf", "自由现金流", "应收账款", "商誉", "固定资产", "三大表", "估值"],
        }),
        ("news_intel", {
            "display_name": "东方财富公告 · 7x24 情报",
            "item_type": "research_report",
            "keywords": ["公告", "研报", "招股说明书", "董事会决议", "减持", "增持", "业绩预告", "问询函", "调研", "机构调研", "新闻", "情报"],
        }),
    ]
)


def _match_doc_type(*, file_title: str, md_text_head: str, user_doc_type: str) -> dict:
    """按规则匹配 doc_type / display_name / tags；user 传了 doc_type 就直接信它（display_name 用规则库兜底）。"""
    text = f"{file_title}\n{md_text_head}".lower()
    user_doc_type = (user_doc_type or "").strip()

    if user_doc_type and user_doc_type in DOC_TYPE_RULES:
        rule = DOC_TYPE_RULES[user_doc_type]
        tags = [rule["display_name"]]
        tags.extend(k for k in rule["keywords"] if k.lower() in text)
        return {
            "doc_type": user_doc_type,
            "display_name": rule["display_name"],
            "item_type": rule["item_type"],
            "item_tags": tags[:10],
        }
    if user_doc_type:
        return {
            "doc_type": user_doc_type,
            "display_name": user_doc_type,
            "item_type": "other",
            "item_tags": [user_doc_type],
        }

    scores: list[tuple[int, int, str, dict]] = []
    for doc_type, rule in DOC_TYPE_RULES.items():
        hits = [k for k in rule["keywords"] if k.lower() in text]
        if hits:
            scores.append((len(hits), len(rule["keywords"]), doc_type, rule))
    scores.sort(key=lambda x: (-x[0], x[1]))
    if scores:
        _, _, doc_type, rule = scores[0]
        return {
            "doc_type": doc_type,
            "display_name": rule["display_name"],
            "item_type": rule["item_type"],
            "item_tags": [rule["display_name"]] + re.findall(r"[^\s，。；,.;]{2,20}", file_title)[:5] + [f"{scores[0][0]}个关键词命中"],
        }
    return {
        "doc_type": "other",
        "display_name": file_title or "未命名资料",
        "item_type": "other",
        "item_tags": ["未分类"],
    }


class NodeItemNameRecognition(NodeBase):
    """
    主体识别节点：主体识别 + 标签提取 + doc_type 推断（纯规则骨架，不依赖 LLM）。

    消费：file_title / md_content / user_doc_type
    产出：item_name / item_type / item_tags / doc_type / display_name
    """

    name = "node_item_name_recognition"
    consumes_fields = ("file_title",)
    produces_fields = ("item_name", "item_type", "item_tags", "doc_type", "display_name")

    def process(self, state: ImportGraphState) -> dict:
        log.info(f"-- {self.name} -- 结点开始处理")
        file_title = str(state.get("file_title") or "").strip()
        user_doc_type = str(state.get("user_doc_type") or "").strip()
        md_head = (state.get("md_content") or "")[:2000]  # 只看前 2000 字符，避免长 MD 卡
        info = _match_doc_type(file_title=file_title, md_text_head=md_head, user_doc_type=user_doc_type)
        return {
            "item_name": info["display_name"],
            "item_type": info["item_type"],
            "item_tags": info["item_tags"],
            "doc_type": info["doc_type"],
            "display_name": info["display_name"],
        }
