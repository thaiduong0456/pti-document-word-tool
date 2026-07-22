from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from .file_handler import PageAsset


@dataclass(frozen=True)
class OCRLine:
    text: str
    confidence: float = 1.0


@dataclass(frozen=True)
class OCRPage:
    source_file: str
    page_number: int
    lines: tuple[OCRLine, ...]

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


class LocalOCR:
    """PaddleOCR pipeline kept in memory and shared between Streamlit sessions."""

    def __init__(self, language: str = "vi"):
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        os.environ.setdefault("FLAGS_use_mkldnn", "0")
        from paddleocr import PaddleOCR

        self.engine = PaddleOCR(
            lang=language,
            ocr_version="PP-OCRv5",
            text_detection_model_name="PP-OCRv5_mobile_det",
            text_recognition_model_name="latin_PP-OCRv5_mobile_rec",
            text_det_limit_side_len=960,
            text_det_limit_type="max",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=False,
        )

    def read_page(self, page: PageAsset) -> OCRPage:
        if page.text_layer:
            lines = tuple(OCRLine(text.strip(), 1.0) for text in page.text_layer.splitlines() if text.strip())
            return OCRPage(page.source_file, page.page_number, lines)

        predictions = list(self.engine.predict(str(page.image_path)))
        if not predictions:
            return OCRPage(page.source_file, page.page_number, ())
        payload = predictions[0].json["res"]
        texts = payload.get("rec_texts", [])
        scores = payload.get("rec_scores", [])
        lines = tuple(
            OCRLine(str(text).strip(), float(score))
            for text, score in zip(texts, scores)
            if str(text).strip()
        )
        return OCRPage(page.source_file, page.page_number, lines)

    def read(self, page: PageAsset) -> str:
        return self.read_page(page).text


@lru_cache(maxsize=1)
def get_local_ocr() -> LocalOCR:
    return LocalOCR()
