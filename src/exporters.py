from io import BytesIO

import pandas as pd

from .schemas import ExtractionResult


def result_to_excel(result: ExtractionResult) -> bytes:
    rows = []
    for field in result.fields:
        evidence = field.evidence[0] if field.evidence else None
        rows.append({
            "field_name": field.field_name,
            "value": field.value,
            "raw_value": field.raw_value,
            "confidence": field.confidence,
            "status": field.status,
            "source_file": evidence.source_file if evidence else "",
            "source_page": evidence.source_page if evidence else "",
            "evidence": evidence.quote if evidence else "",
            "normalization_note": field.normalization_note,
        })
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="Fields", index=False)
        pd.DataFrame([line.model_dump() for line in result.survey_lines]).to_excel(writer, sheet_name="Survey lines", index=False)
        pd.DataFrame({"warning": result.warnings}).to_excel(writer, sheet_name="Warnings", index=False)
    return output.getvalue()
