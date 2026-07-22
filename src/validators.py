from __future__ import annotations

import re
from datetime import datetime


DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y")


def normalize_date(value: str) -> str:
    value = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).strftime("%d/%m/%Y")
        except ValueError:
            pass
    match = re.fullmatch(r"(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})", value, re.I)
    if match:
        return f"{int(match.group(1)):02d}/{int(match.group(2)):02d}/{match.group(3)}"
    return value


def parse_number(value: str | float | int | None) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (float, int)):
        return float(value)
    text = re.sub(r"[^\d,.-]", "", value.strip())
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(",", "") if text.rfind(".") > text.rfind(",") else text.replace(".", "").replace(",", ".")
    elif text.count(",") == 1 and len(text.rsplit(",", 1)[1]) <= 3:
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def reconcile_quantities(bl: float, received: float, tolerance: float = 0.002) -> tuple[float, float, list[str]]:
    shortage = round(received - bl, 3)
    percent = round(shortage / bl * 100, 3) if bl else 0.0
    warnings: list[str] = []
    if received > bl:
        warnings.append("Khối lượng thực nhận lớn hơn khối lượng vận đơn.")
    if abs(shortage) > 0 and abs(shortage / bl) < tolerance:
        warnings.append("Chênh lệch rất nhỏ; cần kiểm tra dấu thập phân OCR.")
    return shortage, percent, warnings


def format_money(value: str | float | int) -> str:
    number = parse_number(value)
    return f"{number:,.0f} VND" if number is not None else str(value)

