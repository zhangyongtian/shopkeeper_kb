from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    conversation_id: str = Field(..., description="会话唯一 ID，用于多轮记忆")
    question: str = Field(..., min_length=1, description="用户问题")
    filters: dict[str, Any] = Field(default_factory=dict, description="可选，检索过滤条件（如 doc_type / quality / doc_id 等）")
    stream: bool = True


class SourceRef(BaseModel):
    idx: int | None = Field(default=None, description="引用编号 [1][2]...，不填则按下标自动+1")
    doc_id: str | None = None
    chunk_id: str | None = None
    doc_title: str | None = Field(default=None, description="文档标题（通常是 PDF 文件名）")
    pdf_name: str | None = Field(default=None, description="源 PDF 文件名（用于 /api/pdf/{pdf_name} 预览跳转）")
    pdf_page: int | None = Field(default=None, description="PDF 页码估计（点击跳 P.N）")
    section_path: str | None = Field(default=None, description="章节路径 Ch.4/反转形态/黄昏之星")
    display_text: str | None = None
    preview: str | None = Field(default=None, description="卡片预览文本（短）")
    score: float | None = None
    image_urls: list[str] = Field(default_factory=list, description="chunk 中提取出的图片 URL（MinIO 公网地址/本地 /api/image 路径），用于卡片缩略图 + 正文插图显示")
    image_alts: list[str] = Field(default_factory=list, description="对应 image_urls 的图注 alt 文本，可空")


class RelatedHit(BaseModel):
    title: str | None = None
    doc_title: str | None = None
    pdf_name: str | None = None
    pdf_page: int | None = None
    section_path: str | None = None
    display_text: str | None = None
    image_urls: list[str] = Field(default_factory=list, description="可选，related chunk 的缩略图 URL")


class SearchRequest(BaseModel):
    q: str = ""
    filters: dict[str, Any] = Field(default_factory=dict)
    topk: int = 20


class SearchResponse(BaseModel):
    hits: list[SourceRef]


class ErrorEnvelope(BaseModel):
    class InnerError(BaseModel):
        code: str
        message: str
        details: dict[str, Any] | list | None = None
        request_id: str = ""

    error: InnerError
