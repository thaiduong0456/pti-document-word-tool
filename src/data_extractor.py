from __future__ import annotations

import json
from pathlib import Path
from .schemas import ExtractionResult, ExtractedField
from .validators import parse_number, reconcile_quantities


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
                        result.warnings.append(f"{name}: OCR đọc {item.value}, phép tính cho kết quả {value}.")
                    item.value = value
                    item.confidence = max(item.confidence, 0.99)
                    item.normalization_note = "Tự tính từ toàn bộ các dòng chứng thư."
                else:
                    result.fields.append(ExtractedField(field_name=name, value=value, raw_value=value, confidence=0.99, status="confirmed", normalization_note="Tự tính từ toàn bộ các dòng chứng thư."))
    return result


def export_json(result: ExtractionResult) -> bytes:
    return json.dumps(result.model_dump(), ensure_ascii=False, indent=2).encode("utf-8")
