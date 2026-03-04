"""Tests for the Pydantic validation layer."""

from __future__ import annotations

import pytest

from app.schemas.data_schemas import InvoiceSchema, LineItem
from app.services.validator import validate_against_schema


class TestLineItem:
    def test_valid_line_item(self):
        item = LineItem(
            description="Widget",
            quantity=3,
            unit_price=10.0,
            total=30.0,
        )
        assert item.total == 30.0

    def test_invalid_line_total(self):
        with pytest.raises(Exception):
            LineItem(
                description="Widget",
                quantity=3,
                unit_price=10.0,
                total=25.0,  # wrong
            )


class TestInvoiceSchema:
    def _valid_invoice_data(self) -> dict:
        return {
            "invoice_number": "INV-001",
            "invoice_date": "2026-01-15",
            "vendor_name": "Acme Corp",
            "customer_name": "Widget Inc",
            "line_items": [
                {
                    "description": "Cloud Hosting",
                    "quantity": 2,
                    "unit_price": 100.0,
                    "total": 200.0,
                },
                {
                    "description": "Support",
                    "quantity": 1,
                    "unit_price": 50.0,
                    "total": 50.0,
                },
            ],
            "subtotal": 250.0,
            "tax_rate": 0.1,
            "tax_amount": 25.0,
            "total_amount": 275.0,
            "currency": "USD",
        }

    def test_valid_invoice(self):
        data = self._valid_invoice_data()
        result = validate_against_schema(data, InvoiceSchema)
        assert result.is_valid
        assert result.data is not None

    def test_missing_required_field(self):
        data = self._valid_invoice_data()
        del data["invoice_number"]
        result = validate_against_schema(data, InvoiceSchema)
        assert not result.is_valid
        assert any("invoice_number" in e for e in result.errors)

    def test_wrong_subtotal(self):
        data = self._valid_invoice_data()
        data["subtotal"] = 999.0  # wrong
        result = validate_against_schema(data, InvoiceSchema)
        assert not result.is_valid

    def test_wrong_total(self):
        data = self._valid_invoice_data()
        data["total_amount"] = 1000.0  # wrong
        result = validate_against_schema(data, InvoiceSchema)
        assert not result.is_valid

    def test_wrong_data_type(self):
        data = self._valid_invoice_data()
        data["subtotal"] = "not_a_number"
        result = validate_against_schema(data, InvoiceSchema)
        assert not result.is_valid
