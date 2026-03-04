"""Tests for prompt building utilities."""

from __future__ import annotations

from app.llm.prompts import build_correction_prompt, build_extraction_prompt
from app.schemas.data_schemas import InvoiceSchema


class TestPrompts:
    def test_extraction_prompt_contains_schema(self):
        prompt = build_extraction_prompt("Sample invoice text", InvoiceSchema)
        assert "invoice_number" in prompt
        assert "Sample invoice text" in prompt
        assert "JSON" in prompt

    def test_correction_prompt_contains_errors(self):
        prompt = build_correction_prompt(
            raw_text="Sample invoice text",
            previous_json='{"invoice_number": "INV-1"}',
            validation_errors="[subtotal] value is not valid",
            schema_cls=InvoiceSchema,
        )
        assert "CORRECTION" in prompt
        assert "value is not valid" in prompt
        assert "INV-1" in prompt
