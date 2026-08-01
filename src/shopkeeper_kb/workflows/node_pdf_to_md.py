from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path

from shopkeeper_kb import logging_config as log
from shopkeeper_kb.integrations.mineru_api import (
    MinerUError,
    create_upload_batch,
    download_file,
    poll_batch_result,
    upload_file_to_presigned_url,
)
from shopkeeper_kb.settings import get_settings
from shopkeeper_kb.workflows.base_node import NodeBase
from shopkeeper_kb.workflows.state import ImportGraphState


def _sanitize_stem(stem: str) -> str:
    value = stem.strip()
    value = re.sub(r"[\\/\x00-\x1f]+", "_", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:120] if len(value) > 120 else value


def _merge_dir(src_dir: Path, dst_dir: Path, *, primary_base: Path | None, exclude: set[Path]) -> None:
    for src_path in src_dir.rglob("*"):
        if src_path.is_dir():
            continue
        if src_path in exclude:
            continue
        if primary_base is not None and primary_base in src_path.parents:
            rel = src_path.relative_to(primary_base)
        else:
            rel = src_path.relative_to(src_dir)
        dst_path = dst_dir / rel
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        if dst_path.exists():
            if dst_path.is_file():
                dst_path.unlink()
            else:
                shutil.rmtree(dst_path)
        shutil.move(str(src_path), str(dst_path))


def _find_primary_md(extract_dir: Path) -> Path:
    candidates = list(extract_dir.rglob("full.md"))
    if not candidates:
        candidates = [p for p in extract_dir.rglob("*.md") if p.is_file()]
    if not candidates:
        raise FileNotFoundError(f"解压目录中未找到 Markdown 文件: {extract_dir}")
    return max(candidates, key=lambda p: p.stat().st_size)


class NodePDFToMD(NodeBase):
    """
    PDF 转 Markdown 节点：PDF结构化解析
    """

    name = "node_pdf_to_md"

    def process(self, state: ImportGraphState):
        log.info(f"-- {self.name} -- 结点开始处理")
        settings = get_settings()
        if not settings.mineru_token:
            raise ValueError("未配置 MINERU_TOKEN，请在 .env 中设置")

        pdf_path = state.get("pdf_path", "")
        if not pdf_path:
            raise ValueError("state.pdf_path 为空")

        pdf_file = Path(pdf_path)
        if not pdf_file.exists():
            raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")

        pdf_stem = _sanitize_stem(pdf_file.stem) or "document"
        download_dir = Path("/home/roott/work/download")
        output_dir = Path("/home/roott/work/output_doc")
        output_subdir = output_dir / pdf_stem
        download_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_subdir.mkdir(parents=True, exist_ok=True)
        log.info(f"-- {self.name} -- 输出目录: {output_subdir}")

        final_md_path = output_subdir / f"{pdf_stem}.md"
        if final_md_path.exists():
            md_content = final_md_path.read_text(encoding="utf-8", errors="replace")
            state["md_path"] = str(final_md_path)
            state["md_content"] = md_content
            state["is_md_read_enabled"] = True
            state["is_pdf_read_enabled"] = False
            return state

        zip_path = download_dir / f"{pdf_stem}.zip"
        if zip_path.exists():
            log.info(f"-- {self.name} -- 检测到本地压缩包，跳过 API 调用: {zip_path}")
        else:
            filename = f"{pdf_stem}{pdf_file.suffix.lower()}"
            log.info(f"-- {self.name} -- 申请上传链接: {filename}")
            batch_id, upload_url = create_upload_batch(
                base_url=settings.mineru_base_url,
                token=settings.mineru_token,
                filename=filename,
                model_version="vlm",
            )

            log.info(f"-- {self.name} -- 上传文件: {pdf_file}")
            upload_file_to_presigned_url(file_path=str(pdf_file), upload_url=upload_url)

            log.info(f"-- {self.name} -- 轮询解析结果: batch_id={batch_id}")
            try:
                result = poll_batch_result(
                    base_url=settings.mineru_base_url, token=settings.mineru_token, batch_id=batch_id
                )
            except MinerUError as e:
                raise MinerUError(f"MinerU 解析失败: {e}") from e

            log.info(f"-- {self.name} -- 解析结果压缩包地址: {result.full_zip_url}")
            log.info(f"-- {self.name} -- 下载压缩包: {zip_path}")
            download_file(url=result.full_zip_url, dst_path=str(zip_path))

        tmp_extract_dir = output_dir / f".tmp_mineru_{zip_path.stem}"
        if tmp_extract_dir.exists():
            shutil.rmtree(tmp_extract_dir)
        tmp_extract_dir.mkdir(parents=True, exist_ok=True)

        log.info(f"-- {self.name} -- 解压压缩包到临时目录: {tmp_extract_dir}")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp_extract_dir)

        primary_md = _find_primary_md(tmp_extract_dir)
        primary_base = primary_md.parent
        if final_md_path.exists():
            final_md_path.unlink()
        shutil.move(str(primary_md), str(final_md_path))

        _merge_dir(tmp_extract_dir, output_subdir, primary_base=primary_base, exclude={primary_md})
        shutil.rmtree(tmp_extract_dir, ignore_errors=True)

        md_content = final_md_path.read_text(encoding="utf-8", errors="replace")
        state["md_path"] = str(final_md_path)
        state["md_content"] = md_content
        state["is_md_read_enabled"] = True
        state["is_pdf_read_enabled"] = False
        return state
