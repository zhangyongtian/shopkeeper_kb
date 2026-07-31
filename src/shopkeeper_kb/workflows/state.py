from typing import TypedDict

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
    chunks: list[str] # 分块内容列表
    item_name: str # 识别主体名称
    
    embedding: list[float] # 嵌入向量
