from __future__ import annotations

import re
import unicodedata
from statistics import mean
from typing import Callable

from .file_handler import PageAsset
from .ocr_service import OCRLine, OCRPage, get_local_ocr
from .schemas import Evidence, ExtractedField, ExtractionResult, SurveyLine
from .validators import format_money, parse_number


POLICY_RE = re.compile(r"\d{7}/GCN/[A-Z0-9./-]+/\d{4}", re.I)
REPORT_RE = re.compile(r"\d{2}NK\d+(?:-\d+)?/BH", re.I)
DECIMAL_RE = re.compile(r"(?<!\d)-?(?:\d{1,3}(?:,\d{3})+|\d+)[.]\d{3}(?!\d)")
DATE_RE = re.compile(r"(\d{1,2})\s*-\s*(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})")


def _plain(value: str) -> str:
    value = value.replace("Đ", "D").replace("đ", "d")
    value = "".join(char for char in unicodedata.normalize("NFD", value) if unicodedata.category(char) != "Mn")
    return re.sub(r"\s+", " ", value).strip().upper()


def _clean_value(value: str) -> str:
    return re.sub(r"^[\s:•·-]+", "", value).strip()


def _find(page: OCRPage, pattern: str, start: int = 0) -> int | None:
    regex = re.compile(pattern, re.I)
    for index in range(start, len(page.lines)):
        if regex.search(_plain(page.lines[index].text)):
            return index
    return None


def _span(page: OCRPage, start_pattern: str, end_pattern: str) -> list[OCRLine]:
    start = _find(page, start_pattern)
    if start is None:
        return []
    end = _find(page, end_pattern, start + 1)
    return list(page.lines[start + 1 : end if end is not None else len(page.lines)])


def _section_value(page: OCRPage, start_pattern: str, end_pattern: str) -> tuple[str, list[OCRLine]]:
    lines = _span(page, start_pattern, end_pattern)
    candidates = [line for line in lines if _clean_value(line.text) and not line.text.lstrip().startswith("-")]
    if not candidates:
        return "", []
    line = candidates[-1]
    return _clean_value(line.text), [line]


def _confidence(lines: list[OCRLine]) -> float:
    return round(mean(line.confidence for line in lines), 3) if lines else 0.0


def _field(name: str, value: str, page: OCRPage | None = None, lines: list[OCRLine] | None = None, note: str = "") -> ExtractedField:
    lines = lines or []
    confidence = _confidence(lines) if page else (1.0 if value else 0.0)
    evidence = []
    if page and value:
        evidence = [Evidence(source_file=page.source_file, source_page=page.page_number, quote=" | ".join(line.text for line in lines)[:500])]
    return ExtractedField(
        field_name=name,
        value=value,
        raw_value=value,
        confidence=confidence,
        status="confirmed" if value and confidence >= 0.85 else ("low_confidence" if value else "not_found"),
        evidence=evidence,
        normalization_note=note,
    )


def _page_kind(page: OCRPage) -> str:
    text = _plain(page.text)
    if "THONG BAO PHI" in text:
        return "fee"
    if "VAT INVOICE" in text or "HOA DON GIA TRI" in text:
        return "invoice"
    if "SURVEY REPORT ON SHORE QUANTITY" in text:
        return "survey"
    return "other"


def _date_range(text: str) -> str:
    match = DATE_RE.search(text)
    if not match:
        return ""
    day_from, day_to, month, year = match.groups()
    return f"{int(day_from):02d}-{int(day_to):02d}/{int(month):02d}/{year}"


def _money_near(page: OCRPage, label_pattern: str) -> tuple[str, list[OCRLine]]:
    index = _find(page, label_pattern)
    if index is None:
        return "", []
    lines = list(page.lines[index : min(index + 6, len(page.lines))])
    for line in lines:
        tokens = re.findall(r"(?<!\d)\d{1,3}(?:[.,]\d{3})+(?!\d)", line.text)
        if tokens:
            number = int(re.sub(r"\D", "", tokens[0]))
            return format_money(number), [line]
    return "", []


def _extract_fee(page: OCRPage) -> dict[str, ExtractedField]:
    output: dict[str, ExtractedField] = {}

    commodity_lines = _span(page, r"T.?N HANG", r"KHOI LU")
    commodity_values = [_clean_value(line.text) for line in commodity_lines if _clean_value(line.text)]
    commodities = " ".join(commodity_values).replace(" ;", ";")
    output["commodities"] = _field("commodities", commodities, page, commodity_lines)

    quantity_lines = _span(page, r"KHOI LU", r"B/L SO")
    quantity_match = DECIMAL_RE.search(" ".join(line.text for line in quantity_lines))
    quantity = quantity_match.group(0).replace(",", "") if quantity_match else ""
    output["declared_quantity_mt"] = _field("declared_quantity_mt", quantity, page, quantity_lines)

    bl_start = _find(page, r"B/L SO")
    bl_lines = list(page.lines[bl_start + 1 : bl_start + 3]) if bl_start is not None else []
    bl_text = " ".join(_clean_value(line.text) for line in bl_lines)
    bl_parts = re.findall(r"EX\s*\d+/\d{4}|(?<=[;&])\s*\d{1,2}(?=\s*(?:[;&]|$))", bl_text, re.I)
    bl_value = "; ".join(part.strip() for part in bl_parts)
    output["bill_of_lading_numbers"] = _field("bill_of_lading_numbers", bl_value, page, bl_lines)

    policy_lines = [line for line in page.lines if "/GCN/" in line.text.upper()]
    policies = []
    for line in policy_lines:
        policies.extend(POLICY_RE.findall(line.text.replace(" ", "")))
    output["policy_numbers"] = _field("policy_numbers", "; ".join(dict.fromkeys(policies)), page, policy_lines)

    vessel_lines = _span(page, r"\bTAU\s*$", r"GIAM D")
    vessel = " ".join(_clean_value(line.text) for line in vessel_lines)
    vessel = re.sub(r"^M\.?\s*T\.?\s*", "MT. ", vessel, flags=re.I).strip()
    output["vessel_name"] = _field("vessel_name", vessel, page, vessel_lines)

    arrival_lines = _span(page, r"^GIAM D", r"DIA D")
    arrival = _date_range(" ".join(line.text for line in arrival_lines))
    output["arrival_date"] = _field("arrival_date", arrival, page, arrival_lines)

    report_lines = [line for line in page.lines if REPORT_RE.search(line.text)]
    report = REPORT_RE.search(report_lines[0].text).group(0) if report_lines else ""
    report = re.sub(r"-\d+(?=/BH)", "", report)
    output["survey_report_number"] = _field("survey_report_number", report, page, report_lines[:1])

    fee, fee_lines = _money_near(page, r"^PHI GIAM D")
    vat, vat_lines = _money_near(page, r"VAT\s*10|THU.*VAT")
    total, total_lines = _money_near(page, r"TONG C")
    output["survey_fee"] = _field("survey_fee", fee, page, fee_lines)
    output["vat_amount"] = _field("vat_amount", vat, page, vat_lines)
    output["grand_total"] = _field("grand_total", total, page, total_lines)
    return output


def _extract_invoice(page: OCRPage) -> dict[str, ExtractedField]:
    output: dict[str, ExtractedField] = {}
    invoice_lines = [line for line in page.lines if "INVOICE NO" in _plain(line.text)]
    invoice_match = re.search(r"(?<!\d)(\d{8})(?!\d)", invoice_lines[0].text) if invoice_lines else None
    output["invoice_number"] = _field("invoice_number", invoice_match.group(1) if invoice_match else "", page, invoice_lines)

    date_lines = [line for line in page.lines if "NGAY (DATE)" in _plain(line.text)]
    date_value = ""
    if date_lines:
        match = re.search(r"(\d{1,2})\s+THANG.*?(\d{1,2})\s+NAM.*?(\d{4})", _plain(date_lines[0].text))
        if match:
            date_value = f"{int(match.group(1)):02d}/{int(match.group(2)):02d}/{match.group(3)}"
    output["invoice_date"] = _field("invoice_date", date_value, page, date_lines)
    return output


def _clean_discharge_port(value: str) -> str:
    value = re.sub(r"Jetty\s*B1", "Jetty B1", value, flags=re.I)
    value = re.sub(r"Go\s*Dau\s*Term\.?", "Go Dau Terminal", value, flags=re.I)
    value = re.sub(r"[- ]*Dong\s*Nai\s*Prov\.?,?", ", Đồng Nai", value, flags=re.I)
    return re.sub(r"\s+,", ",", value).strip(" ,-.")


def _clean_vessel(value: str) -> str:
    value = _clean_value(value).strip(' "')
    value = re.sub(r"^M\.?\s*T\.?\s*:?\s*", "", value, flags=re.I).strip(' "')
    return f"MT. {value}" if value else ""


def _extract_survey(page: OCRPage) -> tuple[SurveyLine, dict[str, tuple[str, list[OCRLine]]]]:
    commodity, commodity_lines = _section_value(page, r"COMMODITY AS PER B/L", r"BILL OF LADING NO")
    bill, bill_lines = _section_value(page, r"BILL OF LADING NO", r"INSURANCE POLICY NO")
    policy, policy_lines = _section_value(page, r"INSURANCE POLICY NO", r"SHORE TANK NO")
    tank, tank_lines = _section_value(page, r"SHORE TANK NO", r"RECEIVED FROM")
    vessel, vessel_lines = _section_value(page, r"RECEIVED FROM", r"LOADING PORT")
    origin, origin_lines = _section_value(page, r"LOADING PORT", r"DISCHARGING PORT")
    discharge, discharge_lines = _section_value(page, r"DISCHARGING PORT", r"DATE OF RECEIVING")
    if ":" in commodity and "HANG HOA" in _plain(commodity):
        commodity = commodity.split(":", 1)[1].strip()

    result_index = _find(page, r"RESULT OF INSPECTION")
    numeric_lines: list[tuple[float, OCRLine]] = []
    numeric_start = result_index + 1 if result_index is not None else 0
    for line in page.lines[numeric_start:]:
        match = re.fullmatch(r"\s*(-?\d{1,6}[.,]\d{3})\s*", line.text)
        if match:
            number = parse_number(match.group(1))
            if number is not None:
                numeric_lines.append((number, line))
    unique: list[tuple[float, OCRLine]] = []
    for item in numeric_lines:
        if not unique or abs(unique[-1][0] - item[0]) > 0.0001:
            unique.append(item)
    positives = [item for item in unique if item[0] > 0]
    received = positives[0][0] if len(positives) >= 1 else None
    bl_quantity = positives[1][0] if len(positives) >= 2 else None
    shortage = round(received - bl_quantity, 3) if received is not None and bl_quantity is not None else None
    shortage_percent = round(shortage / bl_quantity * 100, 3) if shortage is not None and bl_quantity else None

    line = SurveyLine(
        commodity=commodity,
        bill_of_lading_number=bill,
        policy_number=policy,
        shore_tank=tank,
        bl_quantity_mt=bl_quantity,
        received_quantity_mt=received,
        shortage_mt=shortage,
        shortage_percent=shortage_percent,
        source_file=page.source_file,
        source_page=page.page_number,
    )
    shared = {
        "vessel_name": (_clean_vessel(vessel), vessel_lines),
        "origin": (origin, origin_lines),
        "discharge_port": (_clean_discharge_port(discharge), discharge_lines),
    }
    return line, shared


def extract_with_local_ocr(
    pages: list[PageAsset],
    progress_callback: Callable[[int, int, PageAsset], None] | None = None,
    phase_callback: Callable[[str], None] | None = None,
) -> ExtractionResult:
    engine = get_local_ocr()
    recognized = engine.read_pages_fixed_regions(
        pages,
        progress_callback,
        phase_callback,
    )
    fee_page = next((page for page in recognized if _page_kind(page) == "fee"), None)
    invoice_page = next((page for page in recognized if _page_kind(page) == "invoice"), None)
    survey_pages = [page for page in recognized if _page_kind(page) == "survey"]

    fields: dict[str, ExtractedField] = {}
    if fee_page:
        fields.update(_extract_fee(fee_page))
    if invoice_page:
        fields.update(_extract_invoice(invoice_page))

    survey_lines: list[SurveyLine] = []
    shared_values: dict[str, tuple[str, list[OCRLine], OCRPage]] = {}
    for survey_page in survey_pages:
        survey_line, shared = _extract_survey(survey_page)
        survey_lines.append(survey_line)
        for name, (value, evidence_lines) in shared.items():
            if value and name not in shared_values:
                shared_values[name] = (value, evidence_lines, survey_page)

    if survey_lines:
        bill_numbers = [line.bill_of_lading_number for line in survey_lines if line.bill_of_lading_number]
        if bill_numbers:
            fields["bill_of_lading_numbers"] = _field(
                "bill_of_lading_numbers",
                "; ".join(bill_numbers),
                note="Lấy theo từng dòng B/L trên các chứng thư để đồng nhất với bảng khối lượng.",
            )
        policy_numbers = list(
            dict.fromkeys(line.policy_number for line in survey_lines if line.policy_number)
        )
        current_policies = fields.get("policy_numbers")
        if policy_numbers and (current_policies is None or not current_policies.value):
            fields["policy_numbers"] = _field(
                "policy_numbers",
                "; ".join(policy_numbers),
                note="Đối chiếu từ từng chứng thư khi Thông báo phí không đọc đủ.",
            )
        shore_tanks = list(dict.fromkeys(line.shore_tank for line in survey_lines if line.shore_tank))
        if shore_tanks:
            fields["shore_tanks"] = _field(
                "shore_tanks",
                "; ".join(shore_tanks),
                note="Tổng hợp danh sách bồn từ các chứng thư.",
            )
    for name, (value, evidence_lines, source_page) in shared_values.items():
        current = fields.get(name)
        if current is None or not current.value:
            fields[name] = _field(name, value, source_page, evidence_lines)

    constants = {
        "issuing_unit": "PTI Hồ Chí Minh",
        "survey_company": "Công ty Cổ phần Giám định Nam Việt",
        "deductible": "0,5%/STBH",
        "submitter_name": "Mai Hạnh Lê",
        "director_name": "Nguyễn Ngọc Tuyến",
    }
    for name, value in constants.items():
        fields.setdefault(name, _field(name, value, note="Giá trị cố định theo mẫu nghiệp vụ."))

    for name in ("claim_number", "insured_name", "insured_address"):
        fields.setdefault(name, _field(name, ""))

    warnings: list[str] = []
    if not fee_page:
        warnings.append("Không nhận diện được trang Thông báo phí; cần nhập tay tên hàng, tàu, B/L và phí.")
    if not invoice_page:
        warnings.append("Không nhận diện được hóa đơn VAT; cần nhập tay số và ngày hóa đơn.")
    if not survey_pages:
        warnings.append("Không nhận diện được chứng thư giám định; cần nhập tay các khối lượng và cảng.")
    warnings.append("OCR chạy cục bộ; hãy đối chiếu các trường có độ tin cậy thấp với ảnh gốc trước khi xuất Word.")

    from .data_extractor import finalize_result

    return finalize_result(ExtractionResult(fields=list(fields.values()), survey_lines=survey_lines, warnings=warnings))
