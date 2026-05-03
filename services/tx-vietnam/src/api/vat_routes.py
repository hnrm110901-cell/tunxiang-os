"""
Vietnam VAT API routes.

Provides endpoints for VAT calculation, invoice VAT breakdown,
rate lookup, and tax ID validation.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from tx_vietnam.src.services.vat_service import (
    VATCategory,
    VATError,
    VATService,
)

router = APIRouter(prefix="/api/v1/vat", tags=["vietnam-vat"])

OK_RESPONSE = {"ok": True}


@router.get("/rates")
async def get_vat_rates() -> dict:
    """Get current Vietnamese VAT rate table.

    Returns all four rate categories with descriptions.
    """
    return {
        **OK_RESPONSE,
        "data": VATService.get_rates(),
    }


@router.post("/calculate")
async def calculate_vat(body: dict[str, Any]) -> dict:
    """Calculate VAT for a single price-inclusive amount.

    Request:
        {
            "category": "standard",   # standard | reduced | export | exempt
            "amount_fen": 110000       # price-inclusive amount in VND (int)
        }

    Response:
        {
            "ok": true,
            "data": {
                "category": "standard",
                "amount_fen": 110000,
                "vat_fen": 10000,
                "exclusive_fen": 100000,
                "rate_percent": 10
            }
        }
    """
    category_str = body.get("category", "standard")
    amount_fen = body.get("amount_fen", 0)

    if not isinstance(amount_fen, int) or amount_fen < 0:
        raise HTTPException(status_code=400, detail="amount_fen must be a non-negative integer")

    try:
        category = VATCategory(category_str)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid VAT category: {category_str}. Must be one of: "
                   f"{[c.value for c in VATCategory]}",
        ) from exc

    try:
        vat_fen = VATService.calculate_vat(category, amount_fen)
        exclusive_fen = amount_fen - vat_fen
        rates = VATService.get_rates()
        rate_info = rates.get(category.value, {})
    except VATError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        **OK_RESPONSE,
        "data": {
            "category": category.value,
            "amount_fen": amount_fen,
            "vat_fen": vat_fen,
            "exclusive_fen": exclusive_fen,
            "rate_percent": rate_info.get("rate_percent", 0),
        },
    }


@router.post("/invoice")
async def calculate_invoice_vat(body: dict[str, Any]) -> dict:
    """Calculate VAT breakdown for invoice items.

    Request:
        {
            "items": [
                {"name": "Phở Bò", "amount_fen": 55000, "vat_category": "reduced"},
                {"name": "Bia", "amount_fen": 22000, "vat_category": "standard"},
                {"name": "Export service", "amount_fen": 100000, "vat_category": "export"}
            ]
        }

    Response:
        {
            "ok": true,
            "data": {
                "items": [...],
                "total_vat_fen": ...,
                "total_exclusive_fen": ...,
                "total_inclusive_fen": ...,
                "breakdown": {...}
            }
        }
    """
    items = body.get("items", [])
    if not isinstance(items, list) or len(items) == 0:
        raise HTTPException(status_code=400, detail="items must be a non-empty array")

    # Validate each item
    for i, item in enumerate(items):
        if "amount_fen" not in item:
            raise HTTPException(
                status_code=400,
                detail=f"Item {i} is missing required field 'amount_fen'",
            )
        if not isinstance(item["amount_fen"], int) or item["amount_fen"] < 0:
            raise HTTPException(
                status_code=400,
                detail=f"Item {i}: amount_fen must be a non-negative integer",
            )
        if "vat_category" not in item:
            raise HTTPException(
                status_code=400,
                detail=f"Item {i} is missing required field 'vat_category'",
            )

    try:
        result = VATService.calculate_invoice_vat(items)
    except VATError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {**OK_RESPONSE, "data": result}


@router.post("/validate-tax-id")
async def validate_tax_id(body: dict[str, Any]) -> dict:
    """Validate a Vietnamese tax ID (Mã số thuế).

    Request:
        {
            "tax_id": "0100109106"
        }

    Response:
        {
            "ok": true,
            "data": {
                "valid": true,
                "tax_id": "0100109106",
                "format": "10-digit"
            }
        }
    """
    tax_id = body.get("tax_id", "")
    if not tax_id or not isinstance(tax_id, str):
        raise HTTPException(status_code=400, detail="tax_id must be a non-empty string")

    is_valid = VATService.validate_tax_id(tax_id)

    # Determine format
    tax_id_str = tax_id.strip()
    if len(tax_id_str) == 10:
        fmt = "10-digit"
    elif len(tax_id_str) == 14 and tax_id_str[10] == "-":
        fmt = "13-digit (10-digit + suffix)"
    else:
        fmt = "unknown"

    return {
        **OK_RESPONSE,
        "data": {
            "valid": is_valid,
            "tax_id": tax_id,
            "format": fmt,
        },
    }
