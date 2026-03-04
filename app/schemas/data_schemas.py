"""Pydantic schemas for the validated invoice / form data.

This is the *target schema* the LLM must produce.  Add or swap schemas
here to handle different document types (invoices, surveys, etc.).
"""

from __future__ import annotations

from datetime import date
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ═══════════════════════════════════════════════════════════════════════
# Line-item inside an invoice
# ═══════════════════════════════════════════════════════════════════════

class LineItem(BaseModel):
    description: str = Field(..., min_length=1, description="Item description")
    quantity: int = Field(..., ge=1, description="Quantity (must be >= 1)")
    unit_price: float = Field(..., ge=0, description="Price per unit")
    total: Optional[float] = Field(None, ge=0, description="Line total = quantity * unit_price")

    @field_validator("unit_price", "total", mode="before")
    @classmethod
    def parse_money_fields(cls, value: Any) -> Any:
        if isinstance(value, str):
            cleaned = value.replace("$", "").replace(",", "").strip()
            if cleaned == "":
                return None
            return cleaned
        return value

    @model_validator(mode="after")
    def check_line_total(self) -> "LineItem":
        expected = round(self.quantity * self.unit_price, 2)
        if self.total is None:
            self.total = expected
            return self
        if round(self.total, 2) != expected:
            raise ValueError(
                f"Line total ({self.total}) != quantity ({self.quantity}) "
                f"* unit_price ({self.unit_price}) = {expected}"
            )
        return self


# ═══════════════════════════════════════════════════════════════════════
# Invoice document – the main target schema
# ═══════════════════════════════════════════════════════════════════════

class InvoiceSchema(BaseModel):
    """Strict schema for a parsed invoice document."""

    invoice_number: str = Field(..., min_length=1, description="Unique invoice identifier")
    invoice_date: date = Field(..., description="Invoice date (YYYY-MM-DD)")
    due_date: Optional[date] = Field(None, description="Payment due date (YYYY-MM-DD)")
    vendor_name: str = Field(..., min_length=1, description="Vendor / seller name")
    vendor_address: Optional[str] = Field(None, description="Vendor address")
    customer_name: str = Field(..., min_length=1, description="Customer / buyer name")
    customer_address: Optional[str] = Field(None, description="Customer address")
    line_items: List[LineItem] = Field(..., min_length=1, description="At least one line item")
    subtotal: float = Field(..., ge=0, description="Sum of all line-item totals")
    tax_rate: Optional[float] = Field(None, ge=0, le=1, description="Tax rate as decimal (e.g. 0.1 for 10%)")
    tax_amount: Optional[float] = Field(None, ge=0, description="Tax amount")
    total_amount: float = Field(..., ge=0, description="Grand total including tax")
    currency: str = Field(default="USD", description="ISO 4217 currency code")
    notes: Optional[str] = Field(None, description="Additional notes")

    @field_validator("vendor_name", "customer_name", mode="before")
    @classmethod
    def normalize_name_fields(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().rstrip(".,;:")
        return value

    @field_validator("subtotal", "tax_amount", "total_amount", mode="before")
    @classmethod
    def parse_invoice_money_fields(cls, value: Any) -> Any:
        if isinstance(value, str):
            cleaned = value.replace("$", "").replace(",", "").strip()
            if cleaned == "":
                return None
            return cleaned
        return value

    @model_validator(mode="before")
    @classmethod
    def normalize_tax_rate(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        tax_rate = values.get("tax_rate")
        if isinstance(tax_rate, str):
            tax_rate = tax_rate.replace("%", "").strip()
            values["tax_rate"] = tax_rate
        try:
            rate_num = float(values["tax_rate"]) if values.get("tax_rate") is not None else None
            if rate_num is not None and rate_num > 1 and rate_num <= 100:
                values["tax_rate"] = rate_num / 100.0
        except (ValueError, TypeError):
            pass
        return values

    @model_validator(mode="after")
    def check_totals(self) -> "InvoiceSchema":
        if self.tax_amount is None and round(self.total_amount, 2) == round(self.subtotal, 2):
            self.tax_amount = 0.0
            if self.tax_rate is None:
                self.tax_rate = 0.0

        # Subtotal must equal sum of line items
        items_sum = round(sum(item.total for item in self.line_items), 2)
        if round(self.subtotal, 2) != items_sum:
            raise ValueError(
                f"subtotal ({self.subtotal}) != sum of line-item totals ({items_sum})"
            )

        # Total = subtotal + tax
        expected_total = self.subtotal
        if self.tax_amount is not None:
            expected_total += self.tax_amount
        if round(self.total_amount, 2) != round(expected_total, 2):
            raise ValueError(
                f"total_amount ({self.total_amount}) != subtotal ({self.subtotal}) "
                f"+ tax_amount ({self.tax_amount}) = {round(expected_total, 2)}"
            )
        return self


# ═══════════════════════════════════════════════════════════════════════
# Survey response – an alternative target schema
# ═══════════════════════════════════════════════════════════════════════

class SurveyResponse(BaseModel):
    """Schema for a parsed survey / form response."""

    respondent_name: str = Field(..., min_length=1)
    respondent_email: Optional[str] = Field(None)
    submission_date: date = Field(...)
    responses: dict[str, str | int | float | bool] = Field(
        ..., description="Question-ID → answer mapping"
    )
    overall_score: Optional[float] = Field(None, ge=0, le=10)


# ═══════════════════════════════════════════════════════════════════════
# Registry – maps a short name to its Pydantic model
# ═══════════════════════════════════════════════════════════════════════

SCHEMA_REGISTRY: dict[str, type[BaseModel]] = {
    "invoice": InvoiceSchema,
    "survey": SurveyResponse,
}

DEFAULT_SCHEMA = "invoice"


def get_schema_class(name: str | None = None) -> type[BaseModel]:
    """Return the Pydantic model class for the given schema name."""
    key = (name or DEFAULT_SCHEMA).lower()
    if key not in SCHEMA_REGISTRY:
        raise ValueError(
            f"Unknown schema '{key}'. Available: {list(SCHEMA_REGISTRY.keys())}"
        )
    return SCHEMA_REGISTRY[key]
