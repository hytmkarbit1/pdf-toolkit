import os
from pypdf import PdfReader, PdfWriter
import pymupdf as fitz  # PyMuPDF — using the new import name (fitz is deprecated)
from pdf2docx import Converter
import pymupdf4llm


# ---------- MERGE ----------
def merge_pdfs(file_paths, output_path, progress_callback=None):
    writer = PdfWriter()
    total = len(file_paths)
    for i, path in enumerate(file_paths):
        reader = PdfReader(path)
        for page in reader.pages:
            writer.add_page(page)
        if progress_callback:
            progress_callback(int((i + 1) / total * 100))
    with open(output_path, "wb") as f:
        writer.write(f)
    return output_path


# ---------- SPLIT ----------
def get_page_count(pdf_path):
    return len(PdfReader(pdf_path).pages)


def split_all_pages(pdf_path, output_dir, progress_callback=None):
    reader = PdfReader(pdf_path)
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    out_files = []
    total = len(reader.pages)
    for i, page in enumerate(reader.pages, start=1):
        writer = PdfWriter()
        writer.add_page(page)
        out_path = os.path.join(output_dir, f"{base}_page_{i}.pdf")
        with open(out_path, "wb") as f:
            writer.write(f)
        out_files.append(out_path)
        if progress_callback:
            progress_callback(int(i / total * 100))
    return out_files


def split_every_n_pages(pdf_path, output_dir, n, progress_callback=None):
    reader = PdfReader(pdf_path)
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    total = len(reader.pages)
    out_files = []
    chunk_index = 1
    chunk_starts = list(range(0, total, n))
    for ci, start in enumerate(chunk_starts):
        writer = PdfWriter()
        end = min(start + n, total)
        for p in range(start, end):
            writer.add_page(reader.pages[p])
        out_path = os.path.join(output_dir, f"{base}_part_{chunk_index}.pdf")
        with open(out_path, "wb") as f:
            writer.write(f)
        out_files.append(out_path)
        chunk_index += 1
        if progress_callback:
            progress_callback(int((ci + 1) / len(chunk_starts) * 100))
    return out_files


def parse_page_ranges(range_str, max_page):
    pages = set()
    for part in range_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-")
            for p in range(int(start), int(end) + 1):
                if 1 <= p <= max_page:
                    pages.add(p - 1)
        else:
            p = int(part)
            if 1 <= p <= max_page:
                pages.add(p - 1)
    return sorted(pages)


def split_by_ranges(pdf_path, output_dir, range_str, progress_callback=None):
    reader = PdfReader(pdf_path)
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    pages_idx = parse_page_ranges(range_str, len(reader.pages))
    writer = PdfWriter()
    total = max(len(pages_idx), 1)
    for i, idx in enumerate(pages_idx):
        writer.add_page(reader.pages[idx])
        if progress_callback:
            progress_callback(int((i + 1) / total * 100))
    out_path = os.path.join(output_dir, f"{base}_custom.pdf")
    with open(out_path, "wb") as f:
        writer.write(f)
    return [out_path]


# ---------- CONVERT: PDF -> DOCX ----------
def pdf_to_docx(pdf_path, output_path, progress_callback=None):
    if progress_callback:
        progress_callback(-1)  # can't report %, so UI shows a simulated rising bar
    cv = Converter(pdf_path)
    cv.convert(output_path)
    cv.close()
    if progress_callback:
        progress_callback(100)
    return output_path


# ---------- CONVERT: PDF -> IMAGES ----------
def pdf_to_images(pdf_path, output_dir, img_format="png", dpi=200, progress_callback=None):
    doc = fitz.open(pdf_path)
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)
    out_files = []
    total = len(doc)
    for i, page in enumerate(doc, start=1):
        pix = page.get_pixmap(matrix=matrix)
        out_path = os.path.join(output_dir, f"{base}_page_{i}.{img_format}")
        pix.save(out_path)
        out_files.append(out_path)
        if progress_callback:
            progress_callback(int(i / total * 100))
    doc.close()
    return out_files


# ---------- CONVERT: PDF -> MARKDOWN ----------
def pdf_to_markdown(pdf_path, output_path, progress_callback=None):
    if progress_callback:
        progress_callback(-1)
    md_text = pymupdf4llm.to_markdown(pdf_path)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(md_text)
    if progress_callback:
        progress_callback(100)
    return output_path

# ---------- THUMBNAILS ----------
def render_page_thumbnail(pdf_path, page_index=0, max_dim=140):
    """Renders one page as PNG bytes, scaled so its longest side <= max_dim px."""
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    rect = page.rect
    scale = max_dim / max(rect.width, rect.height)
    matrix = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=matrix)
    data = pix.tobytes("png")
    doc.close()
    return data
