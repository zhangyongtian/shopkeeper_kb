from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from shopkeeper_kb.app.schemas import (
    ChatRequest,
    RelatedHit,
    SearchRequest,
    SearchResponse,
    SourceRef,
)

router = APIRouter(prefix="/api/mock", tags=["mock"])


"""
Mock 假数据接口：
 - 目的是**验证前端 UI / 引用卡片 / PDF 跳转 / Ctrl+K 搜索 / SSE 打字机效果是否全部跑通。
 - 真实后端梯队 2+3 完成后，前端只把 index.html 里的 CHAT_ENDPOINT 改为 /api/chat/stream,
   SEARCH_ENDPOINT 改为 /api/search 即可，无需改动前端其它代码。
"""


DEMO_PDF_NAME = "日本蜡烛图技术.pdf"
DEMO_PDF = DEMO_PDF_NAME


def _sources_demo() -> list[SourceRef]:
    return [
        SourceRef(
            idx=1,
            doc_title=DEMO_PDF,
            pdf_name=DEMO_PDF,
            pdf_page=68,
            section_path="第4章/主要反转形态/黄昏之星",
            display_text="黄昏之星是一种经典的顶部反转形态，由三根蜡烛线组成：第一天是一根长长的白色蜡烛线，第二天是一根实体较小的星线，第三天是一根深色蜡烛线，它的实体深深地向下扎入第一天的白色实体内部。",
            preview="黄昏之星是一种经典的顶部反转形态，由三根蜡烛线组成：第一天是一根长长的白色蜡烛线…",
            score=0.92,
            image_urls=[
                "https://coresg-normal.trae.ai/api/ide/v1/text_to_image?prompt=Japanese%20candlestick%20Evening%20Star%20pattern%2C%20three%20candles%20top%20reversal%20chart%2C%20clean%20minimalist%20trading%20chart%20with%20green%20first%20candle%2C%20small%20doji%20second%2C%20long%20red%20third%20candle%20on%20white%20background&image_size=square",
                "https://coresg-normal.trae.ai/api/ide/v1/text_to_image?prompt=Evening%20Star%20candlestick%20diagram%20annotated%20with%20three%20parts%20labeled%3A%20first%20long%20white%20candle%2C%20small%20star%20line%2C%20third%20black%20candle%20penetrating%20first%20body%2C%20Chinese%20labels%20stylized%20financial%20illustration&image_size=landscape_16_9",
            ],
            image_alts=["黄昏之星蜡烛形态 K 线图", "黄昏之星三阶段结构示意图"],
        ),
        SourceRef(
            idx=2,
            doc_title=DEMO_PDF,
            pdf_name=DEMO_PDF,
            pdf_page=70,
            section_path="第4章/主要反转形态/黄昏之星/变体",
            display_text="理想的黄昏之星形态中，第二天的星线实体与第一天的白色实体之间存在价格跳空（向上），第三天的黑色实体与星线实体之间也存在跳空（向下）。如果第三天收盘价深入第一天实体的 50% 以上，信号强度更高。",
            preview="如果第三天收盘价深入第一天实体 50% 以上，信号强度更高…",
            score=0.87,
            image_urls=[
                "https://coresg-normal.trae.ai/api/ide/v1/text_to_image?prompt=Candlestick%20Evening%20Star%20variant%20annotated%20with%20gap%20arrows%20and%2050%25%20retracement%20line%20highlighted%2C%20professional%20trading%20textbook%20illustration%20style&image_size=landscape_4_3",
            ],
            image_alts=["黄昏之星变体：跳空缺口 + 50% 回吐线图解"],
        ),
        SourceRef(
            idx=3,
            doc_title=DEMO_PDF,
            pdf_name=DEMO_PDF,
            pdf_page=72,
            section_path="第4章/主要反转形态/启明星",
            display_text="启明星是底部反转形态，是黄昏之星在底部的镜像：第一天长黑线，第二天星线，第三天长白线。",
            preview="启明星是黄昏之星在底部的镜像形态…",
            score=0.81,
            image_urls=[
                "https://coresg-normal.trae.ai/api/ide/v1/text_to_image?prompt=Japanese%20candlestick%20Morning%20Star%20pattern%2C%20three%20candles%20bottom%20reversal%20chart%2C%20long%20red%20first%20candle%2C%20small%20doji%20second%2C%20long%20green%20third%20candle%20on%20white%20background%20financial%20illustration&image_size=square",
            ],
            image_alts=["启明星底部反转 K 线图"],
        ),
    ]


def _related_demo() -> list[RelatedHit]:
    return [
        RelatedHit(
            title="启明星形态",
            doc_title=DEMO_PDF,
            pdf_name=DEMO_PDF,
            pdf_page=72,
            section_path="第4章/主要反转形态/启明星",
            display_text="黄昏之星对应顶部反转的反面：启明星是典型的底部反转信号…",
            image_urls=[
                "https://coresg-normal.trae.ai/api/ide/v1/text_to_image?prompt=Morning%20Star%20candlestick%20pattern%20icon%2C%20three%20candles%20in%20green%20rising%20trend%2C%20flat%20minimalist%20vector%20logo%20style&image_size=square",
            ],
        ),
        RelatedHit(
            title="三只乌鸦形态",
            doc_title=DEMO_PDF,
            pdf_name=DEMO_PDF,
            pdf_page=84,
            section_path="第4章/主要反转形态/三只乌鸦",
            image_urls=[
                "https://coresg-normal.trae.ai/api/ide/v1/text_to_image?prompt=Three%20Black%20Crows%20candlestick%20pattern%20icon%2C%20three%20descending%20red%20candles%20flat%20minimalist%20vector%20logo%20style&image_size=square",
            ],
        ),
        RelatedHit(
            title="十字星的含义",
            doc_title=DEMO_PDF,
            pdf_name=DEMO_PDF,
            pdf_page=42,
            section_path="第2章/基本概念/十字星",
            image_urls=[
                "https://coresg-normal.trae.ai/api/ide/v1/text_to_image?prompt=Doji%20candlestick%20cross%20shape%20icon%2C%20single%20candle%20with%20long%20wicks%20and%20small%20body%2C%20flat%20minimalist%20vector%20logo&image_size=square",
            ],
        ),
    ]


_HI = _sources_demo()
_REL = _related_demo()


def _answer_tokens(question: str) -> tuple[str, str]:
    q = question or ""
    ql = q.lower()

    if any(k in q for k in ("找不到", "没有", "不知道", "火星", "月球", "外星", "宇宙")):
        return "refused", ""

    if any(k in ql for k in ("区别", "对比", "vs", "不同")):
        return "ok", (
            "启明星和黄昏之星的核心区别在于**出现的位置与方向**，两者互为镜像 [1][2][3]：\n"
            "1. **位置**：黄昏之星出现在一段上涨趋势的顶部，预示上升趋势的**顶部**，属于看跌反转信号 [1]；启明星出现在下跌趋势的**底部**，属于看涨反转信号 [3]。\n"
            "2. **颜色顺序**：黄昏之星的顺序是「长阳 → 星线 → 长阴」[1][2]；启明星的顺序是「长阴 → 星线 → 长阳」[3]。\n"
            "3. **强度判断**：两者第三天实体回吐幅度越深入第一天的实体，信号越强。黄昏之星要求黑色实体深入白色实体 50% 以上更可靠 [2]；反之，启明星反之亦然 [3]。\n\n"
            "简单记忆：黄昏之星 = 「黄昏落顶；启明星 = 「黎明升起」。"
        )

    if any(k in q for k in ("反转", "哪些", "常见", "全部")):
        return "ok", (
            "经典的蜡烛图反转形态主要包括以下几大类 [1][2][3]：\n"
            "1. **锤子线与上吊线**：单根蜡烛线形态。锤子出现在下跌末端为底部反转，上吊线出现在上涨末端为顶部反转。\n"
            "2. **吞没形态（抱线）**：由两根相反颜色的蜡烛线组成，后一根实体完全包住前一根实体，属强烈反转信号。\n"
            "3. **乌云盖顶与刺透形态**：前者顶部反转（长白后长黑盖到前一根 50% 以上）；后者底部反转（长黑后长白刺到前一根 50% 以上）。\n"
            "4. **星线家族** [1][2][3]：黄昏之星（顶，看跌）、启明星（底，看涨）、十字黄昏星、十字启明星；以及它们的变体弃婴形态。\n"
            "5. **三只乌鸦**（顶）、三白兵（底）等三山/三川等复合形态。"
        )

    return "ok", (
        "**黄昏之星**是一种经典的顶部反转蜡烛图形态，出现在一段明显的上涨趋势之后，预示上涨动能衰竭、可能反转向下 [1][2]。\n"
        "它由**三根 K 线**组成：\n"
        "1. 第一根：一根坚挺的**白色（阳线）**，实体较长，体现上涨仍在延续** [1]。\n"
        "2. 第二根：一根实体较小的**星线**（可以是小阳/小阴/十字星），实体与前一根白色实体之间通常存在向上的跳空缺口，**星线本身代表市场犹豫不决 [1][2]。\n"
        "3. 第三根：一根**黑色（阴线）**，实体较长，其收盘价**深深地向下扎入第一根白色蜡烛线实体的内部（经典要求至少刺入第一根实体的 50%）[2]。\n\n"
        "第三根黑色实体回吐第一根实体的幅度越大，该形态的看跌意义越强 [2]；若第二根星线同时伴随成交量放大，反转信号更加可靠。"
    )


async def _stream_events(question: str) -> AsyncIterator[str]:
    confidence, answer = _answer_tokens(question)
    if confidence == "refused":
        refused_payload = {
            "delta": "",
            "sources": [],
            "related": [],
            "confidence": "refused",
            "done": True,
        }
        yield "data: " + json.dumps(refused_payload, ensure_ascii=False) + "\n\n"
        yield "data: [DONE]\n\n"
        return

    # Step 1: 先流式吐 answer 的 delta（逐 token 约 10-30ms 一个字，模拟打字机）
    words = re.findall(r".{1,4}", answer)  # 中文字符 1-4 字一次
    sources_sent = False
    related_sent = False
    total = len(words)
    for i, w in enumerate(words):
        payload = {"delta": w, "sources": None, "related": None, "done": False}
        yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
        # 在 60% 左右插入 sources
        if not sources_sent and i >= int(total * 0.6):
            s_payload = {"delta": "", "sources": [s.model_dump() for s in _HI], "related": None, "done": False}
            yield "data: " + json.dumps(s_payload, ensure_ascii=False) + "\n\n"
            sources_sent = True
        # 在 85% 左右插入 related
        if not related_sent and i >= int(total * 0.85):
            r_payload = {"delta": "", "sources": None, "related": [r.model_dump() for r in _REL], "done": False}
            yield "data: " + json.dumps(r_payload, ensure_ascii=False) + "\n\n"
            related_sent = True
        await asyncio.sleep(0.012)

    done_payload = {
        "delta": "",
        "sources": None,
        "related": None,
        "confidence": confidence,
        "done": True,
    }
    yield "data: " + json.dumps(done_payload, ensure_ascii=False) + "\n\n"
    yield "data: [DONE]\n\n"


@router.post("/chat/stream", summary="Mock 流式问答（验证 UI）")
async def mock_chat_stream(req: ChatRequest, request: Request):
    async def gen():
        async for chunk in _stream_events(req.question):
            yield chunk

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/chat", summary="Mock 非流式问答")
async def mock_chat(req: ChatRequest):
    confidence, answer = _answer_tokens(req.question)
    return {
        "answer": answer,
        "confidence": confidence,
        "sources": [s.model_dump() for s in _HI],
        "related": [r.model_dump() for r in _REL],
    }


@router.get("/search", response_model=SearchResponse, summary="Mock Ctrl+K 搜索")
async def mock_search(q: str = "", topk: int = 20):
    hits: list[SourceRef] = []
    if not q:
        hits = [_HI[0], _HI[2], _REL[0], _REL[1], _REL[2]]  # type: ignore[assignment]
    else:
        ql = q.lower()
        # 简单关键词匹配
        for s in _HI:
            hay = " ".join(filter(None, [s.section_path or "", s.display_text or "", s.doc_title or ""]))
            if any(k in hay.lower() for k in ql.split()) or any(k in ql for k in (s.section_path or "").split("/")):
                hits.append(s)
        for r in _REL:
            hay = " ".join(filter(None, [r.title or "", r.section_path or "", r.doc_title or ""]))
            if any(k in hay.lower() for k in ql.split()):
                hits.append(SourceRef(
                    idx=None, doc_title=r.doc_title, pdf_name=r.pdf_name,
                    pdf_page=r.pdf_page, section_path=r.section_path,
                    display_text=r.display_text, preview=r.display_text, score=0.6,
                ))
        if not hits:
            hits = [s for s in _HI]
    return SearchResponse(hits=hits[:topk])


@router.post("/search", response_model=SearchResponse, summary="Mock Ctrl+K 搜索（POST 版本）")
async def mock_search_post(body: SearchRequest):
    return await mock_search(q=body.q, topk=body.topk)
