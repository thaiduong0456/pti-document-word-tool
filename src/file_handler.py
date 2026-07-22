from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import fitz
from PIL import Image


ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}


@dataclass
class PageAsset:
    source_file: str
    page_number: int
    image_path: Path
    text_layer: str = ""


def safe_name(name: str) -> str:
    # Directory uploads may return a relative path. Flatten it safely while
    # retaining enough path context to avoid same-name collisions.
    normalized = name.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part not in {"", ".", ".."}]
    flattened = "__".join(parts)
    stem = re.sub(r"[^\w.-]+", "_", flattened, flags=re.UNICODE).strip("._")
    return stem[:120] or "document"


def validate_upload(name: str, data: bytes, max_mb: int = 25) -> None:
    if Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Định dạng không hỗ trợ: {name}")
    if len(data) > max_mb * 1024 * 1024:
        raise ValueError(f"{name} vượt quá {max_mb} MB")
    if not data:
        raise ValueError(f"{name} là file rỗng")


def materialize_pages(name: str, data: bytes, session_dir: Path) -> list[PageAsset]:
    validate_upload(name, data)
    session_dir.mkdir(parents=True, exist_ok=True)
    clean = safe_name(name)
    suffix = Path(clean).suffix.lower()
    output: list[PageAsset] = []
    if suffix == ".pdf":
        document = fitz.open(stream=data, filetype="pdf")
        for index, page in enumerate(document):
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2.2, 2.2), alpha=False)
            path = session_dir / f"{Path(clean).stem}_p{index + 1}.png"
            pixmap.save(path)
            output.append(PageAsset(clean, index + 1, path, page.get_text("text").strip()))
        document.close()
    else:
        path = session_dir / clean
        image = Image.open(__import__("io").BytesIO(data)).convert("RGB")
        image.save(path, quality=95)
        output.append(PageAsset(clean, 1, path))
    return output
