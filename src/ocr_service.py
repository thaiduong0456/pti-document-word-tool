from __future__ import annotations

import base64
import os
from pathlib import Path

import pytesseract

from .file_handler import PageAsset


class LocalOCR:
    def __init__(self, language: str = "vie+eng"):
        self.language = language
        command = os.getenv("TESSERACT_CMD")
        if command:
            pytesseract.pytesseract.tesseract_cmd = command

    def read(self, page: PageAsset) -> str:
        if page.text_layer:
            return page.text_layer
        try:
            return pytesseract.image_to_string(str(page.image_path), lang=self.language, config="--psm 6")
        except pytesseract.TesseractError:
            return pytesseract.image_to_string(str(page.image_path), lang="eng", config="--psm 6")


def image_data_url(path: Path) -> str:
    suffix = path.suffix.lower().replace("jpg", "jpeg").lstrip(".")
    return f"data:image/{suffix};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"

