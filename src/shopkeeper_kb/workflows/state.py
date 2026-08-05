from typing import TypedDict


class MDImgItem(TypedDict):
    """
    Markdown 图片一次出现（occurrence）的结构化信息。

    字段说明：
    - img_rel_path: Markdown 中图片的原始路径（通常为相对路径）
    - img_abs_path: 图片在本机文件系统中的绝对路径（用于多模态模型读取）
    - alt: Markdown 图片的 alt 文本，即 ![alt](...) 中的 alt
    - pre_text: 图片标记前的上下文文本片段（固定窗口左侧）
    - next_text: 图片标记后的上下文文本片段（固定窗口右侧）
    - start: 图片 Markdown 片段在 md_content 中的起始下标
    - end: 图片 Markdown 片段在 md_content 中的结束下标
    - exists: img_abs_path 指向的文件是否存在
    - img_desc: 图片经大模型解析后的内容信息（后续节点填充）
    - minio_url: 图片写回后的可访问 URL（通常来自 MinIO 公网地址）
    """
    img_rel_path: str
    img_abs_path: str
    alt: str
    pre_text: str
    next_text: str
    start: int
    end: int
    exists: bool
    img_desc: str
    minio_url: str


class Chunk(TypedDict):
    """
    结构化切分结果（顶级切分：结构化 + token-aware + 展示/检索解耦）。

    字段说明：
    - doc_id: 文档稳定标识（用于增量更新、跨文件去重）
    - chunk_id: chunk 的稳定标识（用于入库/溯源/去重）
    - chunk_level: chunk 层级（通常为 child；可扩展 parent）
    - parent_id: 章节/父级聚合标识（常与 section_path 一一对应）
    - section_path: 章节路径（标题链），用于提供语境与聚合
    - position: chunk 在文档中的顺序号（从 0 开始）
    - token_count: embed_text 的 token 估算值（用于预算控制与调参）
    - embed_text: 用于向量化的纯语义文本（去 URL、融合图片语义）
    - display_text: 用于展示的 Markdown 原文（保留图片/表格/列表等）
    - image_urls: chunk 内关联图片 URL（用于前端展示）
    - image_alts: chunk 内图片的 alt/caption（用于检索与展示提示）
    - quality: 内容质量标签（normal/low），用于去噪、降权或过滤
    """
    doc_id: str
    chunk_id: str
    chunk_level: str
    parent_id: str
    section_path: str
    position: int
    token_count: int
    embed_text: str
    display_text: str
    image_urls: list[str]
    image_alts: list[str]
    quality: str

class ImportGraphState(TypedDict):
    task_id: str # 任务的唯一键
    
    is_md_read_enabled: bool # 是否启用Markdown读取功能
    is_pdf_read_enabled: bool # 是否启用PDF读取功能
    
    local_dir: str # 本地目录路径
    local_file_path: str # 本地文件路径
    file_title: str # 文件标题
    pdf_path: str # PDF文件路径
    md_path: str # Markdown文件路径
    
    md_content: str # Markdown文件内容
    md_img_items: list[MDImgItem]
    chunks: list[Chunk] # 分块内容列表（结构化：用于检索与展示）
    item_name: str # 识别主体名称
    
    embedding: list[float] # 嵌入向量
