# ABOUTME: Extract plain text from various file formats for ingestion.
# ABOUTME: Supports PDF, DOCX, Jupyter notebooks, Python source, and plain text.

from __future__ import annotations

import json
from pathlib import Path

TEXT_EXTENSIONS = {".txt", ".md", ".json", ".csv", ".dip", ".py", ".pyx", ".pxd", ".pyi", ".rst", ".toml", ".yaml", ".yml", ".xml", ".html", ".htm", ".js", ".ts", ".tsx", ".jsx", ".css", ".sh", ".bash", ".zsh", ".sql"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
PDF_EXTENSIONS = {".pdf"}
DOCX_EXTENSIONS = {".docx"}
NOTEBOOK_EXTENSIONS = {".ipynb"}

ALL_SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | IMAGE_EXTENSIONS | PDF_EXTENSIONS | DOCX_EXTENSIONS | NOTEBOOK_EXTENSIONS


def _check_magic(file_bytes: bytes, expected: bytes, label: str) -> None:
    if not file_bytes.startswith(expected):
        raise ValueError(f"File does not appear to be a valid {label} (magic bytes mismatch)")


def extract_text_from_pdf(file_bytes: bytes) -> str:
    from io import BytesIO
    import pypdf

    _check_magic(file_bytes, b"%PDF", "PDF")
    reader = pypdf.PdfReader(BytesIO(file_bytes))
    parts = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            parts.append(text)
    result = "\n\n".join(parts)
    if not result.strip():
        raise ValueError("PDF contains no extractable text (scanned or image-only PDF)")
    return result


_DOCX_UNZIP_LIMIT = 50 * 1024 * 1024  # 50 MB uncompressed


def extract_text_from_docx(file_bytes: bytes) -> str:
    from io import BytesIO
    import zipfile
    import docx

    _check_magic(file_bytes, b"PK\x03\x04", "DOCX")

    with zipfile.ZipFile(BytesIO(file_bytes)) as zf:
        total_uncompressed = sum(zi.file_size for zi in zf.infolist())
        if total_uncompressed > _DOCX_UNZIP_LIMIT:
            raise ValueError(
                f"DOCX uncompressed content ({total_uncompressed // (1024 * 1024)} MB) exceeds limit"
            )

    doc = docx.Document(BytesIO(file_bytes))
    # Tables, headers/footers, and text boxes are not extracted — body paragraphs only.
    return "\n".join(para.text for para in doc.paragraphs if para.text.strip())


def extract_text_from_notebook(file_bytes: bytes) -> str:
    nb = json.loads(file_bytes.decode("utf-8"))
    parts = []
    for cell in nb.get("cells", []):
        cell_type = cell.get("cell_type", "")
        source = "".join(cell.get("source", []))
        if not source.strip():
            continue
        if cell_type == "markdown":
            parts.append(source)
        elif cell_type == "code":
            parts.append(f"```python\n{source}\n```")
            for output in cell.get("outputs", []):
                text = output.get("text") or output.get("data", {}).get("text/plain")
                if text:
                    out_str = "".join(text) if isinstance(text, list) else text
                    if out_str.strip():
                        parts.append(f"Output:\n{out_str}")
    return "\n\n".join(parts)


def extract_text(filename: str, file_bytes: bytes) -> str:
    """Return plain text for any supported file type. Raises ValueError for unsupported types."""
    suffix = Path(filename).suffix.lower()

    if suffix in PDF_EXTENSIONS:
        return extract_text_from_pdf(file_bytes)
    if suffix in DOCX_EXTENSIONS:
        return extract_text_from_docx(file_bytes)
    if suffix in NOTEBOOK_EXTENSIONS:
        return extract_text_from_notebook(file_bytes)
    if suffix in TEXT_EXTENSIONS:
        return file_bytes.decode("utf-8", errors="replace")

    raise ValueError(f"Unsupported file type: {suffix}")
