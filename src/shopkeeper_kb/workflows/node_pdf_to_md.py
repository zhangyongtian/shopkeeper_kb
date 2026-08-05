from __future__ import annotations

import re
import shutil
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pypdf import PdfReader, PdfWriter

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


MAX_MINERU_PAGES = 200
_MD_IMAGE_PATH_PATTERN = re.compile(r"!\[([^\]]*)\]\((?:\./)?images/([^)]+)\)")


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


def _ensure_pdf_parts(pdf_file: Path, *, parts_dir: Path, pdf_stem: str, max_pages: int) -> list[tuple[str, Path]]:
    parts_dir.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(str(pdf_file))
    total = len(reader.pages)
    parts: list[tuple[str, Path]] = []
    for start in range(0, total, max_pages):
        end = min(start + max_pages, total)
        part_no = start // max_pages + 1
        part_id = f"part_{part_no:03d}"
        part_path = parts_dir / f"{pdf_stem}_{part_id}.pdf"
        if not part_path.exists():
            writer = PdfWriter()
            for i in range(start, end):
                writer.add_page(reader.pages[i])
            with part_path.open("wb") as f:
                writer.write(f)
        parts.append((part_id, part_path))
    return parts


def _mineru_pdf_to_md(
    *,
    pdf_file: Path,
    zip_stem: str,
    output_dir: Path,
    output_subdir: Path,
    final_md_path: Path,
    download_dir: Path,
    settings,
    display_name: str,
) -> None:
    zip_path = download_dir / f"{zip_stem}.zip"
    if zip_path.exists():
        log.info(f"-- node_pdf_to_md -- 检测到本地压缩包，跳过 API 调用: {zip_path}")
    else:
        if not settings.mineru_token:
            raise ValueError("未配置 MINERU_TOKEN，请在 .env 中设置")
        filename = f"{zip_stem}{pdf_file.suffix.lower()}"
        log.info(f"-- node_pdf_to_md -- 申请上传链接: {filename} ({display_name})")
        batch_id, upload_url = create_upload_batch(
            base_url=settings.mineru_base_url,
            token=settings.mineru_token,
            filename=filename,
            model_version="vlm",
        )

        log.info(f"-- node_pdf_to_md -- 上传文件: {pdf_file} ({display_name})")
        upload_file_to_presigned_url(file_path=str(pdf_file), upload_url=upload_url)

        log.info(f"-- node_pdf_to_md -- 轮询解析结果: batch_id={batch_id} ({display_name})")
        try:
            result = poll_batch_result(base_url=settings.mineru_base_url, token=settings.mineru_token, batch_id=batch_id)
        except MinerUError as e:
            raise MinerUError(f"MinerU 解析失败: {e}") from e

        log.info(f"-- node_pdf_to_md -- 下载压缩包: {zip_path} ({display_name})")
        download_file(url=result.full_zip_url, dst_path=str(zip_path))

    tmp_extract_dir = output_dir / f".tmp_mineru_{zip_path.stem}"
    if tmp_extract_dir.exists():
        shutil.rmtree(tmp_extract_dir)
    tmp_extract_dir.mkdir(parents=True, exist_ok=True)

    log.info(f"-- node_pdf_to_md -- 解压压缩包到临时目录: {tmp_extract_dir} ({display_name})")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(tmp_extract_dir)

    primary_md = _find_primary_md(tmp_extract_dir)
    primary_base = primary_md.parent
    if final_md_path.exists():
        final_md_path.unlink()
    final_md_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(primary_md), str(final_md_path))

    output_subdir.mkdir(parents=True, exist_ok=True)
    _merge_dir(tmp_extract_dir, output_subdir, primary_base=primary_base, exclude={primary_md})
    shutil.rmtree(tmp_extract_dir, ignore_errors=True)


def _rewrite_part_md_images(md_text: str, *, part_id: str) -> str:
    def repl(match: re.Match[str]) -> str:
        alt = match.group(1)
        suffix = match.group(2)
        return f"![{alt}](images/{part_id}/{suffix})"

    return _MD_IMAGE_PATH_PATTERN.sub(repl, md_text)


def _move_part_images(*, part_dir: Path, final_output_dir: Path, part_id: str) -> None:
    src_images = part_dir / "images"
    if not src_images.exists():
        return

    dst_images = final_output_dir / "images" / part_id
    for src_path in src_images.rglob("*"):
        if src_path.is_dir():
            continue
        rel = src_path.relative_to(src_images)
        dst_path = dst_images / rel
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        if dst_path.exists():
            if dst_path.is_file():
                dst_path.unlink()
            else:
                shutil.rmtree(dst_path)
        shutil.move(str(src_path), str(dst_path))
    shutil.rmtree(src_images, ignore_errors=True)


def _merge_part_mds(
    *,
    parts: list[tuple[str, Path]],
    parts_out_dir: Path,
    final_md_path: Path,
    final_output_dir: Path,
) -> None:
    merged_sections: list[str] = []
    for part_id, _ in parts:
        part_dir = parts_out_dir / part_id
        part_md = part_dir / f"{part_id}.md"
        if not part_md.exists():
            raise FileNotFoundError(f"分卷 Markdown 不存在: {part_md}")

        _move_part_images(part_dir=part_dir, final_output_dir=final_output_dir, part_id=part_id)
        md_text = part_md.read_text(encoding="utf-8", errors="replace")
        md_text = _rewrite_part_md_images(md_text, part_id=part_id).strip()
        merged_sections.append(f"## {part_id}\n\n{md_text}")

    final_md_path.parent.mkdir(parents=True, exist_ok=True)
    final_md_path.write_text("\n\n---\n\n".join(merged_sections).strip() + "\n", encoding="utf-8")


class NodePDFToMD(NodeBase):
    """
    PDF 转 Markdown 节点：PDF结构化解析
    """

    name = "node_pdf_to_md"

    def process(self, state: ImportGraphState):
        log.info(f"-- {self.name} -- 结点开始处理")
        settings = get_settings()

        pdf_path = state.get("pdf_path", "")
        if not pdf_path:
            raise ValueError("state.pdf_path 为空")

        pdf_file = Path(pdf_path)
        if not pdf_file.exists():
            raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")

        pdf_stem = _sanitize_stem(pdf_file.stem) or "document"
        download_dir = Path(getattr(settings, "download_dir", "/home/roott/work/download"))
        output_dir = Path(getattr(settings, "output_doc_dir", "/home/roott/work/output_doc"))
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

        try:
            page_count = len(PdfReader(str(pdf_file)).pages)
        except Exception as e:
            raise RuntimeError(f"读取 PDF 页数失败: {pdf_file}") from e

        split_pages = int(getattr(settings, "mineru_split_pages", MAX_MINERU_PAGES))
        if split_pages < 1:
            split_pages = MAX_MINERU_PAGES

        page_limit = int(getattr(settings, "mineru_page_limit", MAX_MINERU_PAGES))
        if page_limit < 0:
            page_limit = 0
        effective_split_pages = split_pages
        if page_limit > 0:
            effective_split_pages = min(split_pages, page_limit)

        concurrency = int(getattr(settings, "mineru_concurrency", 1))
        if concurrency < 1:
            concurrency = 1

        if page_count > effective_split_pages:
            log.info(
                f"-- {self.name} -- 检测到 PDF 需要切分: pages={page_count}, split_pages={split_pages}, page_limit={page_limit}, effective_split_pages={effective_split_pages}, concurrency={concurrency}"
            )
            parts_pdf_dir = output_subdir / ".parts_pdf"
            parts_out_dir = output_subdir / ".parts_out"
            parts = _ensure_pdf_parts(
                pdf_file, parts_dir=parts_pdf_dir, pdf_stem=pdf_stem, max_pages=effective_split_pages
            )

            def run_part(part_id: str, part_pdf: Path) -> None:
                part_dir = parts_out_dir / part_id
                part_md_path = part_dir / f"{part_id}.md"
                if part_md_path.exists():
                    return
                _mineru_pdf_to_md(
                    pdf_file=part_pdf,
                    zip_stem=f"{pdf_stem}_{part_id}",
                    output_dir=output_dir,
                    output_subdir=part_dir,
                    final_md_path=part_md_path,
                    download_dir=download_dir,
                    settings=settings,
                    display_name=part_id,
                )

            if concurrency == 1:
                for part_id, part_pdf in parts:
                    run_part(part_id, part_pdf)
            else:
                executor = ThreadPoolExecutor(max_workers=concurrency)
                futures = {executor.submit(run_part, part_id, part_pdf): part_id for part_id, part_pdf in parts}
                try:
                    for fut in as_completed(futures):
                        fut.result()
                except Exception:
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise
                finally:
                    executor.shutdown(wait=True)

            _merge_part_mds(parts=parts, parts_out_dir=parts_out_dir, final_md_path=final_md_path, final_output_dir=output_subdir)
        else:
            _mineru_pdf_to_md(
                pdf_file=pdf_file,
                zip_stem=pdf_stem,
                output_dir=output_dir,
                output_subdir=output_subdir,
                final_md_path=final_md_path,
                download_dir=download_dir,
                settings=settings,
                display_name="single",
            )

        md_content = final_md_path.read_text(encoding="utf-8", errors="replace")
        state["md_path"] = str(final_md_path)
        state["md_content"] = md_content
        state["is_md_read_enabled"] = True
        state["is_pdf_read_enabled"] = False
        return state
