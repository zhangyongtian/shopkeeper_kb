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
    chunks: list[str] # 分块内容列表
    item_name: str # 识别主体名称
    
    embedding: list[float] # 嵌入向量
