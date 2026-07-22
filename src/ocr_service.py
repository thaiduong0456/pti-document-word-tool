from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

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

    @staticmethod
    def _plain(value: str) -> str:
        value = value.replace("Đ", "D").replace("đ", "d")
        value = "".join(
            char
            for char in unicodedata.normalize("NFD", value)
            if unicodedata.category(char) != "Mn"
        )
        return re.sub(r"\s+", " ", value).strip().upper()

    @classmethod
    def _fixed_page_kind(cls, title_lines: list[OCRLine]) -> str:
        text = cls._plain(" ".join(line.text for line in title_lines))
        if "THONG BAO PHI" in text:
            return "fee"
        if "HOA DON GIA TRI" in text or "VAT INVOICE" in text:
            return "invoice"
        if (
            "SURVEY REPORT" in text
            or "SHORE QUANTITY" in text
            or "CHUNG THU GIAM DINH" in text
            or "BAO CAO GIAM DINH" in text
        ):
            return "survey"
        return "other"

    @classmethod
    def _content_page_kind(cls, lines: list[OCRLine]) -> str:
        """Classify from recognized business labels, not page geometry alone."""
        text = cls._plain(" ".join(line.text for line in lines))
        survey_markers = (
            "SHORE TANK",
            "RECEIVED FROM",
            "LOADING PORT",
            "DISCHARGING PORT",
            "BILL OF LADING",
            "INSURANCE POLICY",
            "RESULT OF INSPECTION",
        )
        if sum(marker in text for marker in survey_markers) >= 3:
            return "survey"
        if "INVOICE NO" in text or "NGAY (DATE)" in text:
            return "invoice"
        fee_markers = ("TEN HANG", "KHOI LU", "PHI GIAM D", "TONG CONG")
        if sum(marker in text for marker in fee_markers) >= 2:
            return "fee"
        return cls._fixed_page_kind(lines)

    @staticmethod
    def _poly_metrics(poly, width: int, height: int) -> tuple[float, float, float, float]:
        xs = [float(point[0]) for point in poly]
        ys = [float(point[1]) for point in poly]
        return (
            sum(xs) / len(xs) / width,
            sum(ys) / len(ys) / height,
            (max(xs) - min(xs)) / width,
            (max(ys) - min(ys)) / height,
        )

    @classmethod
    def _is_title_poly(cls, poly, width: int, height: int) -> bool:
        center_x, center_y, box_width, box_height = cls._poly_metrics(poly, width, height)
        return (
            0.08 <= center_y <= 0.28
            and 0.05 <= center_x <= 0.90
            and box_width >= 0.20
            and box_height >= 0.018
        )

    @classmethod
    def _fixed_page_kind_from_polys(cls, polys, width: int, height: int) -> str:
        metrics = [cls._poly_metrics(poly, width, height) for poly in polys]
        title_metrics = [
            item
            for item in metrics
            if 0.08 <= item[1] <= 0.28
            and 0.05 <= item[0] <= 0.90
            and item[2] >= 0.20
            and item[3] >= 0.018
        ]
        if any(
            0.21 <= center_y <= 0.25
            and 0.25 <= box_width <= 0.55
            and box_height >= 0.026
            for _, center_y, box_width, box_height in title_metrics
        ):
            return "invoice"
        if len(title_metrics) <= 2 and any(
            0.145 <= center_y <= 0.20
            and 0.20 <= box_width <= 0.32
            and box_height >= 0.025
            for _, center_y, box_width, box_height in title_metrics
        ):
            return "fee"
        if any(
            0.09 <= center_y <= 0.18
            and box_width >= 0.40
            and box_height >= 0.023
            for _, center_y, box_width, box_height in title_metrics
        ):
            return "survey"
        return "other"

    @classmethod
    def _is_field_poly(cls, poly, width: int, height: int, kind: str) -> bool:
        center_x, center_y, _, _ = cls._poly_metrics(poly, width, height)
        if kind == "fee":
            return 0.27 <= center_y <= 0.66
        if kind == "invoice":
            return 0.22 <= center_y <= 0.34
        if kind == "survey":
            return (
                0.15 <= center_y <= 0.45
                and (center_x <= 0.30 or center_x >= 0.48)
            ) or (0.45 < center_y <= 0.69 and center_x >= 0.65)
        return True

    def _recognize_crops(self, crops) -> list[OCRLine]:
        if not crops:
            return []
        pipeline = self.engine.paddlex_pipeline._pipeline
        results = list(pipeline.text_rec_model(crops, batch_size=4))
        return [
            OCRLine(str(item["rec_text"]).strip(), float(item["rec_score"]))
            for item in results
        ]

    def read_pages_fixed_regions(
        self,
        pages: list[PageAsset],
        progress_callback: Callable[[int, int, PageAsset], None] | None = None,
        phase_callback: Callable[[str], None] | None = None,
    ) -> list[OCRPage]:
        """Detect text once, then recognize only fixed business-field regions.

        Unknown layouts automatically recognize every detected line, preserving
        the previous full-page behavior without running text detection twice.
        """
        recognized: list[OCRPage | None] = [None] * len(pages)
        image_entries: list[tuple[int, PageAsset]] = []
        for index, page in enumerate(pages):
            if page.text_layer:
                recognized[index] = self.read_page(page)
            else:
                image_entries.append((index, page))

        if image_entries:
            if phase_callback:
                phase_callback("Đang phát hiện vùng thông tin trên chứng từ...")
            pipeline = self.engine.paddlex_pipeline._pipeline
            images = pipeline.img_reader([str(page.image_path) for _, page in image_entries])
            params = pipeline.get_text_det_params(None, None, None, None, None, None)
            detections = list(pipeline.text_det_model(images, **params))
            all_polys = [pipeline._sort_boxes(result["dt_polys"]) for result in detections]

            page_kinds = []
            for image, polys in zip(images, all_polys):
                height, width = image.shape[:2]
                page_kinds.append(
                    self._fixed_page_kind_from_polys(polys, width, height)
                )

            title_crops = []
            title_chunks = [0]
            unknown_positions = []
            for position, (image, polys, kind) in enumerate(
                zip(images, all_polys, page_kinds)
            ):
                if kind != "other":
                    continue
                height, width = image.shape[:2]
                selected = [
                    poly for poly in polys if self._is_title_poly(poly, width, height)
                ]
                title_crops.extend(pipeline._crop_by_polys(image, selected))
                title_chunks.append(len(title_crops))
                unknown_positions.append(position)
            title_lines = self._recognize_crops(title_crops)
            for chunk_index, position in enumerate(unknown_positions):
                lines = title_lines[
                    title_chunks[chunk_index] : title_chunks[chunk_index + 1]
                ]
                page_kinds[position] = self._fixed_page_kind(lines)

            if phase_callback:
                phase_callback("Đang đọc các trường cần điền vào tờ trình...")
            field_crops = []
            field_chunks = [0]
            for image, polys, kind in zip(images, all_polys, page_kinds):
                height, width = image.shape[:2]
                selected = [
                    poly
                    for poly in polys
                    if self._is_field_poly(poly, width, height, kind)
                ]
                field_crops.extend(pipeline._crop_by_polys(image, selected))
                field_chunks.append(len(field_crops))
            field_lines = self._recognize_crops(field_crops)

            # A photographed document can shift enough for its title geometry to
            # resemble another template. Validate against actual labels and only
            # fall back to all detected lines for mismatched/unknown pages.
            fallback_positions = []
            for position, kind in enumerate(page_kinds):
                lines = field_lines[
                    field_chunks[position] : field_chunks[position + 1]
                ]
                content_kind = self._content_page_kind(lines)
                if content_kind != "other" and content_kind != kind:
                    page_kinds[position] = content_kind
                    fallback_positions.append(position)
                elif kind == "other":
                    fallback_positions.append(position)

            if fallback_positions:
                fallback_crops = []
                fallback_chunks = [0]
                for position in fallback_positions:
                    fallback_crops.extend(
                        pipeline._crop_by_polys(images[position], all_polys[position])
                    )
                    fallback_chunks.append(len(fallback_crops))
                fallback_lines = self._recognize_crops(fallback_crops)
                replacements = {}
                for chunk_index, position in enumerate(fallback_positions):
                    lines = fallback_lines[
                        fallback_chunks[chunk_index] : fallback_chunks[chunk_index + 1]
                    ]
                    replacements[position] = lines
                    content_kind = self._content_page_kind(lines)
                    if content_kind != "other":
                        page_kinds[position] = content_kind
            else:
                replacements = {}

            kind_headers = {
                "fee": OCRLine("THÔNG BÁO PHÍ", 1.0),
                "invoice": OCRLine("HÓA ĐƠN GIÁ TRỊ GIA TĂNG (VAT INVOICE)", 1.0),
                "survey": OCRLine("SURVEY REPORT ON SHORE QUANTITY", 1.0),
            }
            for position, ((original_index, page), kind) in enumerate(
                zip(image_entries, page_kinds)
            ):
                source_lines = replacements.get(
                    position,
                    field_lines[field_chunks[position] : field_chunks[position + 1]],
                )
                lines = [line for line in source_lines if line.text]
                if kind in kind_headers:
                    lines = [kind_headers[kind], *lines]
                recognized[original_index] = OCRPage(
                    page.source_file,
                    page.page_number,
                    tuple(lines),
                )

        final = [page for page in recognized if page is not None]
        if progress_callback:
            for done, (asset, _) in enumerate(zip(pages, final), start=1):
                progress_callback(done, len(pages), asset)
        return final

    def read(self, page: PageAsset) -> str:
        return self.read_page(page).text


@lru_cache(maxsize=1)
def get_local_ocr() -> LocalOCR:
    return LocalOCR()
