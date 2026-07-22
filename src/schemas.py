from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Status = Literal["confirmed", "low_confidence", "conflict", "not_found"]


class Evidence(BaseModel):
    source_file: str = ""
    source_page: int = 1
    quote: str = ""


class ExtractedField(BaseModel):
    field_name: str
    value: str = ""
    raw_value: str = ""
    confidence: float = Field(default=0, ge=0, le=1)
    status: Status = "not_found"
    evidence: list[Evidence] = Field(default_factory=list)
    normalization_note: str = ""


class SurveyLine(BaseModel):
    commodity: str = ""
    bill_of_lading_number: str = ""
    policy_number: str = ""
    shore_tank: str = ""
    bl_quantity_mt: float | None = None
    received_quantity_mt: float | None = None
    shortage_mt: float | None = None
    shortage_percent: float | None = None
    source_file: str = ""
    source_page: int = 1


class ExtractionResult(BaseModel):
    fields: list[ExtractedField]
    survey_lines: list[SurveyLine] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def as_dict(self) -> dict[str, ExtractedField]:
        return {field.field_name: field for field in self.fields}

