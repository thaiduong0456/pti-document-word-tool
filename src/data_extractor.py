from __future__ import annotations

import json
import os
from pathlib import Path

from openai import OpenAI

from .config import load_fields
from .file_handler import PageAsset
from .ocr_service import image_data_url
from .schemas import ExtractionResult, ExtractedField
from .validators import parse_number, reconcile_quantities


SYSTEM_PROMPT = """Bạn trích xuất dữ liệu từ bộ chứng từ giám định hàng hóa để lập tờ trình thanh toán phí giám định.
TUYỆT ĐỐI không suy đoán. Nếu không thấy, trả chuỗi rỗng, confidence=0, status=not_found.
Đọc chính xác từng chữ số. Với mỗi giá trị phải ghi file/trang và trích dẫn ngắn làm bằng chứng.
Phân biệt: phí trước VAT, VAT, tổng thanh toán; khối lượng B/L, thực nhận, thiếu hụt; số hóa đơn và số chứng thư.
Với vessel_name, phải chép NGUYÊN VĂN dòng TÀU trên Thông báo phí, bao gồm tiền tố như MT., M.T. hoặc M/V. Không được tự bỏ tiền tố.
Với commodities, phải chép NGUYÊN VĂN toàn bộ dòng TÊN HÀNG trên Thông báo phí; không thay bằng tên trên chứng thư và không tự thêm tên đồng nghĩa trong ngoặc.
Với declared_quantity_mt, lấy NGUYÊN VĂN con số ở dòng KHỐI LƯỢNG trên Thông báo phí. Không dùng tổng khối lượng B/L thay thế.
Với origin, lấy Loading Port/cảng xếp hàng trên chứng thư. Không suy ra từ tên tàu hoặc địa điểm giám định.
Một bộ có thể có nhiều chứng thư/mặt hàng. Tạo một survey_line cho mỗi chứng thư và giữ nguyên từng số liệu.
Số B/L có thể chỉ là 01, 12 hoặc 13: phải giữ nguyên, không thêm tiền tố và không coi là thiếu dữ liệu.
Ngày giám định có thể là một ngày hoặc khoảng ngày; giữ đúng khoảng ngày nếu chứng từ ghi như vậy.
Không gộp các chứng thư trước khi tạo survey_lines. Chỉ phần mềm mới được cộng tổng sau khi nhận structured output.
Status chỉ là confirmed, low_confidence, conflict, not_found. Không coi giá trị xuất hiện một lần trên ảnh mờ là confirmed.
Trả kết quả đúng schema Pydantic được yêu cầu."""


def _field_prompt() -> str:
    fields = load_fields()
    return "Các field_name cần trả về:\n" + "\n".join(f"- {key}: {meta['label']}" for key, meta in fields.items())


def extract_with_openai(pages: list[PageAsset], model: str | None = None) -> ExtractionResult:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Chưa cấu hình OPENAI_API_KEY.")
    client = OpenAI()
    content: list[dict] = [{"type": "input_text", "text": _field_prompt()}]
    for page in pages:
        content.append({"type": "input_text", "text": f"FILE={page.source_file}; PAGE={page.page_number}"})
        content.append({"type": "input_image", "image_url": image_data_url(page.image_path), "detail": "original"})
    response = client.responses.parse(
        model=model or os.getenv("OPENAI_MODEL", "gpt-5.6"),
        instructions=SYSTEM_PROMPT,
        input=[{"role": "user", "content": content}],
        text_format=ExtractionResult,
    )
    if response.output_parsed is None:
        raise RuntimeError("AI không trả về dữ liệu có cấu trúc.")
    return finalize_result(response.output_parsed)


def extract_from_fixture(path: str | Path) -> ExtractionResult:
    return finalize_result(ExtractionResult.model_validate_json(Path(path).read_text(encoding="utf-8")))


def apply_upload_date(result: ExtractionResult, upload_date: str) -> ExtractionResult:
    """The document/signature date is a system fact, never an OCR guess."""
    by_name = result.as_dict()
    item = by_name.get("document_date")
    if item is None:
        item = ExtractedField(field_name="document_date")
        result.fields.append(item)
    item.value = upload_date
    item.raw_value = upload_date
    item.confidence = 1.0
    item.status = "confirmed"
    item.normalization_note = "Ngày người dùng upload/xử lý bộ chứng từ."
    item.evidence = []
    return result


def finalize_result(result: ExtractionResult) -> ExtractionResult:
    by_name = result.as_dict()
    if result.survey_lines:
        for index, line in enumerate(result.survey_lines, start=1):
            if line.bl_quantity_mt is None or line.received_quantity_mt is None:
                result.warnings.append(f"Chứng thư dòng {index} thiếu khối lượng B/L hoặc thực nhận.")
                continue
            expected_shortage, expected_percent, _ = reconcile_quantities(line.bl_quantity_mt, line.received_quantity_mt)
            if line.shortage_mt is not None and abs(line.shortage_mt - expected_shortage) > 0.002:
                result.warnings.append(f"Chứng thư dòng {index}: thiếu hụt đọc được {line.shortage_mt:.3f}, phép tính là {expected_shortage:.3f}.")
            if line.shortage_percent is not None and abs(line.shortage_percent - expected_percent) > 0.002:
                result.warnings.append(f"Chứng thư dòng {index}: tỷ lệ đọc được {line.shortage_percent:.3f}%, phép tính là {expected_percent:.3f}%.")
        bl_values = [line.bl_quantity_mt for line in result.survey_lines if line.bl_quantity_mt is not None]
        received_values = [line.received_quantity_mt for line in result.survey_lines if line.received_quantity_mt is not None]
        if len(bl_values) == len(result.survey_lines) and len(received_values) == len(result.survey_lines):
            bl_total = round(sum(bl_values), 3)
            received_total = round(sum(received_values), 3)
            shortage, percent, warnings = reconcile_quantities(bl_total, received_total)
            result.warnings.extend(warnings)
            computed = {
                "bl_quantity_mt": f"{bl_total:.3f}",
                "received_quantity_mt": f"{received_total:.3f}",
                "shortage_mt": f"{shortage:.3f}",
                "shortage_percent": f"{percent:.3f}",
            }
            for name, value in computed.items():
                item = by_name.get(name)
                if item:
                    read_number = parse_number(item.value)
                    computed_number = parse_number(value)
                    if item.value and (read_number is None or computed_number is None or abs(read_number - computed_number) > 0.002):
                        item.status = "conflict"
                        result.warnings.append(f"{name}: AI đọc {item.value}, phép tính cho kết quả {value}.")
                    item.value = value
                    item.confidence = max(item.confidence, 0.99)
                    item.normalization_note = "Tự tính từ toàn bộ các dòng chứng thư."
                else:
                    result.fields.append(ExtractedField(field_name=name, value=value, raw_value=value, confidence=0.99, status="confirmed", normalization_note="Tự tính từ toàn bộ các dòng chứng thư."))
    return result


def export_json(result: ExtractionResult) -> bytes:
    return json.dumps(result.model_dump(), ensure_ascii=False, indent=2).encode("utf-8")
