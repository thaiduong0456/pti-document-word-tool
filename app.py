from __future__ import annotations

import base64
import hashlib
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from src.config import ROOT, load_fields, load_settings
from src.data_extractor import apply_upload_date, export_json
from src.exporters import result_to_excel
from src.file_handler import materialize_pages
from src.local_extractor import extract_with_local_ocr
from src.schemas import ExtractionResult, ExtractedField
from src.word_filler import editable_field_names, fill_template, layout_risks, remaining_placeholders, remove_all_highlights


st.set_page_config(page_title="Tạo tờ trình phí giám định", page_icon="📄", layout="wide")
settings = load_settings()
field_config = load_fields()


def secret_value(name: str) -> str:
    try:
        return str(st.secrets.get(name, ""))
    except Exception:
        return ""


def template_source() -> Path | bytes:
    local_path = ROOT / settings["template_path"]
    if local_path.exists():
        return local_path
    encoded = secret_value("TEMPLATE_DOCX_BASE64")
    if encoded:
        try:
            return base64.b64decode(encoded, validate=True)
        except ValueError as error:
            raise RuntimeError("TEMPLATE_DOCX_BASE64 không hợp lệ.") from error
    raise RuntimeError("Chưa cấu hình file Word mẫu cho ứng dụng.")


def init_state() -> None:
    st.session_state.setdefault("result", None)
    st.session_state.setdefault("pages", [])
    st.session_state.setdefault("confirmed", {})
    st.session_state.setdefault("generated_docx", None)
    st.session_state.setdefault("session_id", uuid.uuid4().hex)
    st.session_state.setdefault("processed_upload_signature", None)


def session_dir() -> Path:
    return Path(tempfile.gettempdir()) / "pti_doc_tool" / st.session_state.session_id


def upload_signature(uploads) -> str:
    digest = hashlib.sha256()
    for uploaded in uploads:
        digest.update(uploaded.name.encode("utf-8"))
        digest.update(uploaded.getvalue())
    return digest.hexdigest()


def field_rows(result: ExtractionResult, only_word_fields: bool = True) -> list[dict]:
    found = result.as_dict()
    rows = []
    for name, config in field_config.items():
        if only_word_fields and name not in editable_field_names():
            continue
        item = found.get(name, ExtractedField(field_name=name))
        evidence = item.evidence[0] if item.evidence else None
        rows.append({
            "field_name": name,
            "Trường": config["label"],
            "Giá trị": item.value or config.get("default", ""),
            "Tin cậy": item.confidence,
            "Trạng thái": item.status,
            "Nguồn": evidence.source_file if evidence else "",
            "Trang": evidence.source_page if evidence else "",
            "Bằng chứng": evidence.quote if evidence else "",
            "Bắt buộc": bool(config.get("required")),
            "Xác nhận": bool(st.session_state.confirmed.get(name, item.status == "confirmed" and item.confidence >= settings["confidence_threshold"])),
        })
    return rows


def update_result_from_editor(frame: pd.DataFrame) -> None:
    result: ExtractionResult = st.session_state.result
    current = result.as_dict()
    for row in frame.to_dict("records"):
        name = row["field_name"]
        value = str(row.get("Giá trị", "") or "").strip()
        item = current.get(name)
        if item:
            item.value = value
            if bool(row.get("Xác nhận")):
                item.status = "confirmed"
        else:
            result.fields.append(ExtractedField(field_name=name, value=value, raw_value="", confidence=1.0 if row.get("Xác nhận") else 0, status="confirmed" if row.get("Xác nhận") else "not_found"))
        st.session_state.confirmed[name] = bool(row.get("Xác nhận"))


init_state()
st.title("Tạo tờ trình thanh toán phí giám định")
st.caption("Tạo tờ trình thanh toán phí giám định tự động - MHL")
st.info("OCR chạy trực tiếp trên máy chủ. Không cần OpenAI API key và chứng từ không được gửi tới dịch vụ AI bên ngoài.")

upload_mode = st.radio("Cách tải chứng từ", ["Chọn một hoặc nhiều file", "Chọn cả thư mục"], horizontal=True)
directory_mode = upload_mode == "Chọn cả thư mục"
uploads = st.file_uploader(
    "Tải PDF hoặc ảnh của một bộ chứng từ",
    type=["pdf", "png", "jpg", "jpeg"],
    accept_multiple_files="directory" if directory_mode else True,
    max_upload_size=settings["max_file_mb"],
    help="Có thể chọn một file, nhiều file hoặc toàn bộ thư mục. PDF nhiều trang được xử lý theo từng trang.",
    key="folder_upload" if directory_mode else "files_upload",
)
if uploads:
    st.write(f"Đã chọn {len(uploads)} file: " + ", ".join(file.name for file in uploads))
    if len(uploads) > settings["max_files"]:
        st.error(f"Mỗi lần chỉ xử lý tối đa {settings['max_files']} file.")

too_many = bool(uploads and len(uploads) > settings["max_files"])
current_upload_signature = upload_signature(uploads) if uploads else None
should_process = bool(
    uploads
    and not too_many
    and current_upload_signature != st.session_state.processed_upload_signature
)
if should_process:
    try:
        with st.status("Đang xử lý chứng từ...", expanded=True) as status:
            work_dir = session_dir()
            shutil.rmtree(work_dir, ignore_errors=True)
            pages = []
            for index, uploaded in enumerate(uploads):
                st.write(f"Chuẩn bị {uploaded.name} ({index + 1}/{len(uploads)})")
                pages.extend(materialize_pages(uploaded.name, uploaded.getvalue(), work_dir))
            st.session_state.pages = pages
            st.write("Đang nhận dạng chữ bằng PaddleOCR tiếng Việt/Anh...")
            st.session_state.result = extract_with_local_ocr(pages)
            upload_date = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).strftime("%d/%m/%Y")
            st.session_state.result = apply_upload_date(st.session_state.result, upload_date)
            st.session_state.confirmed = {}
            st.session_state.generated_docx = None
            st.session_state.processed_upload_signature = current_upload_signature
            status.update(label="Đã trích xuất xong", state="complete")
    except Exception as error:
        st.error(f"Không thể xử lý: {error}")

result: ExtractionResult | None = st.session_state.result
if result:
    st.subheader("Kiểm tra và xác nhận")
    if result.warnings:
        for warning in result.warnings:
            st.warning(warning)
    st.info("Bảng dưới đây chỉ gồm các trường được phép ghi vào vùng tô vàng của Word mẫu.")
    edited = st.data_editor(
        pd.DataFrame(field_rows(result)),
        hide_index=True,
        use_container_width=True,
        disabled=["field_name", "Trường", "Tin cậy", "Trạng thái", "Nguồn", "Trang", "Bằng chứng", "Bắt buộc"],
        column_config={
            "field_name": None,
            "Giá trị": st.column_config.TextColumn(width="large"),
            "Tin cậy": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.0f%%"),
            "Xác nhận": st.column_config.CheckboxColumn(),
        },
        key="field_editor",
    )
    update_result_from_editor(edited)

    reference_rows = field_rows(result, only_word_fields=False)
    reference_rows = [row for row in reference_rows if row["field_name"] not in editable_field_names()]
    if reference_rows:
        with st.expander("Thông tin OCR đọc được nhưng không được ghi vào Word"):
            st.dataframe(pd.DataFrame(reference_rows).drop(columns=["Xác nhận"]), use_container_width=True, hide_index=True)

    if result.survey_lines:
        with st.expander("Chi tiết từng chứng thư giám định"):
            st.dataframe(pd.DataFrame([line.model_dump() for line in result.survey_lines]), use_container_width=True, hide_index=True)

    with st.expander("Xem chứng từ nguồn"):
        for page in st.session_state.pages:
            st.caption(f"{page.source_file} — trang {page.page_number}")
            st.image(str(page.image_path), use_container_width=True)

    values = {field.field_name: field.value for field in result.fields}
    word_fields = editable_field_names()
    required_missing = [name for name, meta in field_config.items() if name in word_fields and meta.get("required") and (not values.get(name) or not st.session_state.confirmed.get(name, False))]
    if required_missing:
        st.error("Chưa thể tạo Word. Hãy nhập và xác nhận các trường bắt buộc: " + ", ".join(field_config[name]["label"] for name in required_missing))
    risks = layout_risks(values)
    if risks:
        st.warning("Một số giá trị dài hơn đáng kể so với vùng vàng mẫu và có thể làm dồn trang: " + ", ".join(field_config.get(name, {}).get("label", name) for name in risks))
    if st.button("Tạo file Word", disabled=bool(required_missing)):
        review_data = fill_template(template_source(), values)
        unresolved = remaining_placeholders(review_data)
        if unresolved:
            st.error("Còn placeholder chưa xử lý: " + ", ".join(unresolved))
        else:
            st.session_state.generated_docx = remove_all_highlights(review_data)
            st.success("Đã tạo bản Word hoàn chỉnh và tự động bỏ toàn bộ bôi vàng.")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.session_state.generated_docx:
            st.download_button("Tải file Word", st.session_state.generated_docx, "To_trinh_phi_giam_dinh.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    with c2:
        st.download_button("Tải dữ liệu JSON", export_json(result), "du_lieu_trich_xuat.json", "application/json")
    with c3:
        st.download_button("Tải bảng kiểm tra Excel", result_to_excel(result), "bang_kiem_tra.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
