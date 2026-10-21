"""Pydantic contracts shared by every stage. Mirrors Listing 1 of the report."""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field

from mock491.config import HITL_CONFIDENCE_THRESHOLD


class DocType(StrEnum):
    CONTRACT = "contract"
    INVOICE = "invoice"


class ReviewStatus(StrEnum):
    AUTO_APPROVED = "auto_approved"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class Financials(BaseModel):
    amount: float = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    penalty_rate_daily: float | None = Field(default=None, ge=0, le=1)


class Lineage(BaseModel):
    """Where a value came from, so the UI can point back at the source document."""

    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_number: int | None = Field(default=None, ge=1)
    bounding_box: tuple[float, float, float, float] | None = None  # pt, top-left origin
    row_number: int | None = Field(default=None, ge=1)  # spreadsheet sources
    confidence: float = Field(ge=0, le=1)
    issues: list[str] = []  # why confidence was lowered, shown to the human reviewer


class Extraction(BaseModel):
    extraction_id: str
    tenant_id: str
    doc_type: DocType
    document_ref: str | None = None  # contract / invoice number printed on the document
    document_date: date | None = None
    counterparty_name: str
    # Kept as written; a value failing the checksum is flagged in issues, not dropped.
    counterparty_vkn: str | None = Field(default=None, pattern=r"^\d{10}$")
    financials: Financials
    paid: bool | None = None
    lineage: Lineage

    @property
    def initial_status(self) -> ReviewStatus:
        if self.lineage.confidence < HITL_CONFIDENCE_THRESHOLD:
            return ReviewStatus.PENDING_REVIEW
        return ReviewStatus.AUTO_APPROVED
