"""
Vietnam VAT (Value Added Tax) calculation service.

Vietnamese VAT Law:
  - Standard rate: 10% (most goods and services)
  - Reduced rate: 8% (2024-2026 economic stimulus — certain goods/services)
  - Export rate: 0% (export services, goods exported abroad)
  - Exempt: 0% (certain categories per Vietnamese tax law)

All monetary amounts are in "fen" (integer), representing VND directly.
VND has no decimal subunit, so 1 VND = 1 fen in the system.
VAT is price-inclusive (the displayed price already includes VAT).

Reference:
  - Law on Value Added Tax (Law No. 13/2008/QH12, amended)
  - Decree 72/2024/ND-CP (2024-2026 reduced VAT rate)
  - Circular 219/2013/TT-BTC (VAT implementation guidance)
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger()


class VATCategory(Enum):
    """VAT rate categories per Vietnamese tax law."""

    STANDARD = "standard"   # 10% — standard rate for most goods/services
    REDUCED = "reduced"     # 8%  — reduced rate (2024-2026 stimulus program)
    EXPORT = "export"       # 0%  — export services / goods
    EXEMPT = "exempt"       # 0%  — exempt per Vietnamese tax law


# VAT rate table (as decimals)
_VAT_RATES: dict[VATCategory, Decimal] = {
    VATCategory.STANDARD: Decimal("0.10"),
    VATCategory.REDUCED: Decimal("0.08"),
    VATCategory.EXPORT: Decimal("0.00"),
    VATCategory.EXEMPT: Decimal("0.00"),
}


class VATError(Exception):
    """VAT calculation exception."""

    pass


class InvalidVATCategoryError(VATError):
    """Raised when an invalid VAT category is used."""

    pass


class InvalidAmountError(VATError):
    """Raised when amount is negative or invalid."""

    pass


class InvalidTaxIDError(VATError):
    """Raised when Vietnamese tax ID validation fails."""

    pass


def _validate_amount_fen(amount_fen: int) -> None:
    """Validate that amount is non-negative."""
    if amount_fen < 0:
        raise InvalidAmountError(f"Amount must be non-negative, got {amount_fen}")


def _decimal_vat_amount(amount_fen: int, rate: Decimal) -> int:
    """Calculate VAT amount from price-inclusive amount using the given rate.

    Price-inclusive VAT formula:
      VAT = total_price - (total_price / (1 + rate))
      = total_price * rate / (1 + rate)

    Args:
        amount_fen: Price-inclusive amount in VND (as int).
        rate: VAT rate as Decimal (e.g. Decimal('0.10') for 10%).

    Returns:
        VAT amount in VND (as int, rounded half-up).
    """
    total = Decimal(str(amount_fen))
    vat_amount = total * rate / (Decimal("1") + rate)
    return int(vat_amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class VATService:
    """Vietnam VAT calculation service.

    All monetary amounts are in VND (integer). VND has no decimals,
    so amounts are stored as-is without fen-to-currency conversion.
    """

    @staticmethod
    def calculate_vat(category: VATCategory, amount_fen: int) -> int:
        """Calculate VAT amount from a price-inclusive total.

        Args:
            category: VAT category (standard/reduced/export/exempt).
            amount_fen: Price-inclusive amount in VND.

        Returns:
            VAT amount in VND (integer).

        Raises:
            InvalidVATCategoryError: if category is invalid.
            InvalidAmountError: if amount is negative.

        Examples:
            >>> VATService.calculate_vat(VATCategory.STANDARD, 110_000)
            10000  # 10% VAT on VND 110,000 inclusive

            >>> VATService.calculate_vat(VATCategory.REDUCED, 108_000)
            8000   # 8% VAT on VND 108,000 inclusive

            >>> VATService.calculate_vat(VATCategory.EXEMPT, 100_000)
            0      # Exempt, no VAT
        """
        if not isinstance(category, VATCategory):
            raise InvalidVATCategoryError(
                f"category must be a VATCategory enum value, got {category}"
            )

        _validate_amount_fen(amount_fen)

        rate = _VAT_RATES.get(category)
        if rate is None:
            raise InvalidVATCategoryError(
                f"Unknown VAT category: {category}"
            )

        if rate == Decimal("0"):
            return 0

        return _decimal_vat_amount(amount_fen, rate)

    @staticmethod
    def calculate_price_exclusive(category: VATCategory, amount_fen: int) -> int:
        """Calculate price exclusive of VAT from a price-inclusive total.

        Args:
            category: VAT category.
            amount_fen: Price-inclusive amount in VND.

        Returns:
            Price exclusive of VAT in VND (integer).
        """
        vat_amount = VATService.calculate_vat(category, amount_fen)
        return amount_fen - vat_amount

    @staticmethod
    def calculate_invoice_vat(items: list[dict[str, Any]]) -> dict[str, Any]:
        """Calculate VAT breakdown for a list of invoice items.

        Each item dict must contain:
            - amount_fen: int — price-inclusive amount in VND
            - vat_category: str — one of 'standard', 'reduced', 'export', 'exempt'

        Returns:
            dict with:
                items: list of items with calculated VAT
                total_vat_fen: total VAT amount
                total_exclusive_fen: total exclusive of VAT
                total_inclusive_fen: total inclusive (sum of input amounts)
                breakdown: dict mapping category -> {count, amount_fen, vat_fen}
        """
        if not items:
            return {
                "items": [],
                "total_vat_fen": 0,
                "total_exclusive_fen": 0,
                "total_inclusive_fen": 0,
                "breakdown": {},
            }

        result_items: list[dict[str, Any]] = []
        total_vat = 0
        total_exclusive = 0
        total_inclusive = 0
        breakdown: dict[str, dict[str, int]] = {}

        for item in items:
            amount_fen = item.get("amount_fen", 0)
            category_str = item.get("vat_category", "standard")

            try:
                category = VATCategory(category_str)
            except ValueError as exc:
                raise InvalidVATCategoryError(
                    f"Invalid VAT category: {category_str}"
                ) from exc

            _validate_amount_fen(amount_fen)

            vat_fen = VATService.calculate_vat(category, amount_fen)
            exclusive_fen = amount_fen - vat_fen

            item_result = {
                **item,
                "vat_fen": vat_fen,
                "exclusive_fen": exclusive_fen,
            }
            result_items.append(item_result)

            total_vat += vat_fen
            total_exclusive += exclusive_fen
            total_inclusive += amount_fen

            cat_key = category.value
            if cat_key not in breakdown:
                breakdown[cat_key] = {
                    "count": 0,
                    "amount_fen": 0,
                    "vat_fen": 0,
                }
            breakdown[cat_key]["count"] += 1
            breakdown[cat_key]["amount_fen"] += amount_fen
            breakdown[cat_key]["vat_fen"] += vat_fen

        return {
            "items": result_items,
            "total_vat_fen": total_vat,
            "total_exclusive_fen": total_exclusive,
            "total_inclusive_fen": total_inclusive,
            "breakdown": breakdown,
        }

    @staticmethod
    def get_rates() -> dict[str, dict[str, str | int]]:
        """Return current VAT rate table.

        Returns:
            dict mapping category names to their rate info.
        """
        return {
            VATCategory.STANDARD.value: {
                "rate": "10%",
                "rate_percent": 10,
                "label": "Thuế suất tiêu chuẩn",
                "description": "Standard rate for most goods and services",
            },
            VATCategory.REDUCED.value: {
                "rate": "8%",
                "rate_percent": 8,
                "label": "Thuế suất giảm",
                "description": "Reduced rate per 2024-2026 stimulus (Decree 72/2024/ND-CP)",
            },
            VATCategory.EXPORT.value: {
                "rate": "0%",
                "rate_percent": 0,
                "label": "Thuế suất 0% (xuất khẩu)",
                "description": "Export services and goods",
            },
            VATCategory.EXEMPT.value: {
                "rate": "0%",
                "rate_percent": 0,
                "label": "Miễn thuế",
                "description": "VAT exempt per Vietnamese tax law",
            },
        }

    @staticmethod
    def validate_tax_id(ma_so_thue: str) -> bool:
        """Validate Vietnamese tax ID (Mã số thuế).

        Vietnamese tax IDs are either 10 digits or 13 digits (10-digit + 3-digit suffix).
        Validation is format-only (10 or 13 chars, all digits); the Vietnamese tax
        authority does not publish a public checksum algorithm.

        Args:
            ma_so_thue: Vietnamese tax ID string.

        Returns:
            True if the tax ID is valid, False otherwise.

        Examples:
            >>> VATService.validate_tax_id("0100109106")
            True
            >>> VATService.validate_tax_id("0100109106-001")
            True
            >>> VATService.validate_tax_id("12345")
            False
        """
        if not ma_so_thue or not isinstance(ma_so_thue, str):
            return False

        tax_id = ma_so_thue.strip()

        # 10-digit format
        if len(tax_id) == 10 and tax_id.isdigit():
            return True

        # 14-char format: 10 digits + "-" + 3-digit suffix
        if len(tax_id) == 14 and tax_id[10] == "-":
            base_part = tax_id[:10]
            suffix_part = tax_id[11:]
            return base_part.isdigit() and suffix_part.isdigit()

        return False
