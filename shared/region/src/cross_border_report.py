"""Cross-border consolidated reporting service

Phase 3 Sprint 3.6 — Multi-country restaurant OS regional expansion.
Provides multi-currency revenue consolidation, market performance comparison,
and cross-timezone operational hours aggregation for brands operating across
multiple Southeast Asian and Chinese markets.

All monetary amounts in fen (integer cents). Exchange rates are fixed
reference rates — not real-time. Real-time rates should come from a
dedicated exchange rate service or payment processor feed.

Usage:
    from shared.region.src.cross_border_report import CrossBorderReportService

    service = CrossBorderReportService()
    revenue = await service.consolidate_revenue(
        tenant_id="...",
        period_start="2026-01-01",
        period_end="2026-03-31",
        target_currency="CNY",
        db=db_session,
    )
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.region.src.region_config import (
    MarketRegion,
    RegionConfig,
    get_config,
    get_supported_markets,
)

logger = structlog.get_logger(__name__)


# ── Reference Exchange Rates ───────────────────────────────────────────
#
# These are fixed reference rates used for consolidated reporting only.
# They are NOT real-time forex rates. Real-time rates should be sourced
# from a payment processor or dedicated forex provider.
#
# Base: 1 unit of row currency → target currency in column.
# Example: 1 CNY = 0.65 MYR, 1 MYR = 1.54 CNY.
#
# Source: XE mid-market rates as of 2026-04-01 (fixed for reporting
# consistency). Update quarterly or on material market changes.

EXCHANGE_RATES: dict[str, dict[str, Decimal]] = {
    "CNY": {
        "MYR": Decimal("0.65"),
        "IDR": Decimal("2200"),
        "VND": Decimal("3400"),
        "SGD": Decimal("0.19"),
        "USD": Decimal("0.14"),
    },
    "MYR": {
        "CNY": Decimal("1.54"),
        "IDR": Decimal("3385"),
        "VND": Decimal("5231"),
        "SGD": Decimal("0.29"),
        "USD": Decimal("0.21"),
    },
    "IDR": {
        "CNY": Decimal("0.00045"),
        "MYR": Decimal("0.00030"),
        "VND": Decimal("1.55"),
        "SGD": Decimal("0.000085"),
        "USD": Decimal("0.000064"),
    },
    "VND": {
        "CNY": Decimal("0.00029"),
        "MYR": Decimal("0.00019"),
        "IDR": Decimal("0.65"),
        "SGD": Decimal("0.000055"),
        "USD": Decimal("0.000041"),
    },
    "SGD": {
        "CNY": Decimal("5.38"),
        "MYR": Decimal("3.50"),
        "IDR": Decimal("11800"),
        "VND": Decimal("18200"),
        "USD": Decimal("0.74"),
    },
    "USD": {
        "CNY": Decimal("7.24"),
        "MYR": Decimal("4.70"),
        "IDR": Decimal("15650"),
        "VND": Decimal("24200"),
        "SGD": Decimal("1.35"),
    },
}


def convert_currency(
    amount_fen: int,
    from_currency: str,
    to_currency: str,
) -> int:
    """Convert an amount from one currency to another using reference rates.

    Args:
        amount_fen: Amount in fen (integer) of the source currency.
        from_currency: ISO 4217 source currency code.
        to_currency: ISO 4217 target currency code.

    Returns:
        Converted amount in fen of the target currency, rounded to
        the nearest integer.

    Raises:
        ValueError: If either currency is not in the exchange rate table
                    or if from_currency == to_currency (no conversion needed).
    """
    if from_currency == to_currency:
        return amount_fen

    rates = EXCHANGE_RATES.get(from_currency)
    if rates is None:
        raise ValueError(f"Unknown source currency: {from_currency}")

    rate = rates.get(to_currency)
    if rate is None:
        raise ValueError(
            f"No exchange rate from {from_currency} to {to_currency}"
        )

    converted = Decimal(str(amount_fen)) * rate
    return int(converted.to_integral_value(rounding="ROUND_HALF_UP"))


# ── Supported currency set ─────────────────────────────────────────────

SUPPORTED_CURRENCIES: frozenset[str] = frozenset(
    ["CNY", "MYR", "IDR", "VND", "SGD", "USD"]
)


# ── Cross Border Report Service ───────────────────────────────────────


class CrossBorderReportService:
    """Multi-country consolidated reporting service.

    Aggregates revenue across all markets, converts to a target currency,
    compares market performance, and handles cross-timezone operational
    hour queries for brands with stores in multiple countries.
    """

    # ── Revenue Consolidation ──────────────────────────────────────

    async def consolidate_revenue(
        self,
        tenant_id: str,
        period_start: str,
        period_end: str,
        target_currency: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Aggregate revenue across all markets consolidated into target currency.

        Queries all stores belonging to the tenant, fetches revenue per
        store in its local currency, converts everything to target_currency,
        and returns per-market and consolidated totals.

        Args:
            tenant_id: Tenant UUID.
            period_start: Period start date (YYYY-MM-DD).
            period_end: Period end date (YYYY-MM-DD).
            target_currency: ISO 4217 target currency code for consolidation.
            db: AsyncSession.

        Returns:
            {
                period: { from, to },
                target_currency: str,
                per_market: {
                    "CN": { currency, revenue_fen, revenue_display, store_count },
                    "MY": { ... },
                    ...
                },
                consolidated: {
                    total_revenue_fen: int,
                    total_revenue_display: float,
                    currency: str,
                    store_count: int,
                },
                exchange_rate_note: str,
            }
        """
        log = logger.bind(
            tenant_id=tenant_id,
            period_start=period_start,
            period_end=period_end,
            target_currency=target_currency,
        )
        log.info("cross_border.consolidate_revenue")

        if target_currency not in SUPPORTED_CURRENCIES:
            raise ValueError(
                f"Unsupported target currency: {target_currency}. "
                f"Supported: {sorted(SUPPORTED_CURRENCIES)}"
            )

        try:
            rows = await db.execute(
                text("""
                    SELECT
                        s.id AS store_id,
                        s.name AS store_name,
                        s.country_code,
                        s.currency,
                        COALESCE(SUM(o.final_amount_fen), 0) AS revenue_fen,
                        COUNT(o.id) AS transaction_count
                    FROM stores s
                    LEFT JOIN orders o ON o.store_id = s.id
                        AND o.tenant_id = s.tenant_id
                        AND o.order_date >= :pstart
                        AND o.order_date <= :pend
                        AND o.status IN ('completed', 'settled')
                        AND o.is_deleted = FALSE
                    WHERE s.tenant_id = :tid
                      AND s.is_deleted = FALSE
                    GROUP BY s.id, s.name, s.country_code, s.currency
                    ORDER BY s.country_code, revenue_fen DESC
                """),
                {
                    "tid": tenant_id,
                    "pstart": period_start,
                    "pend": period_end,
                },
            )
            store_data = rows.mappings().fetchall()
        except Exception as exc:
            log.warning("consolidate_revenue_query_failed", error=str(exc))
            store_data = []

        # Per-market aggregation
        markets: dict[str, dict[str, Any]] = {}
        consolidated_fen = 0
        total_stores = 0

        for row in store_data:
            country_code = row.get("country_code") or "CN"
            currency = (row.get("currency") or "CNY").upper()
            revenue_fen = int(row.get("revenue_fen", 0) or 0)

            if country_code not in markets:
                markets[country_code] = {
                    "country_code": country_code,
                    "currency": currency,
                    "revenue_fen": 0,
                    "revenue_display": 0.0,
                    "store_count": 0,
                    "transaction_count": 0,
                }

            markets[country_code]["revenue_fen"] += revenue_fen
            markets[country_code]["store_count"] += 1
            markets[country_code]["transaction_count"] += int(
                row.get("transaction_count", 0) or 0
            )

        # Convert each market's revenue to target currency
        for country_code, market in markets.items():
            currency = market["currency"]
            market_fen = market["revenue_fen"]

            try:
                converted_fen = convert_currency(
                    market_fen, currency, target_currency
                )
            except (ValueError, KeyError) as exc:
                log.warning(
                    "cross_border.conversion_failed",
                    country_code=country_code,
                    currency=currency,
                    error=str(exc),
                )
                converted_fen = 0

            market["consolidated_fen"] = converted_fen
            market["consolidated_display"] = round(
                converted_fen / 100, 2
            )
            market["revenue_display"] = round(market_fen / 100, 2)
            consolidated_fen += converted_fen
            total_stores += market["store_count"]

        result = {
            "period": {"from": period_start, "to": period_end},
            "target_currency": target_currency,
            "per_market": markets,
            "consolidated": {
                "total_revenue_fen": consolidated_fen,
                "total_revenue_display": round(consolidated_fen / 100, 2),
                "currency": target_currency,
                "store_count": total_stores,
            },
            "exchange_rate_note": (
                "Consolidation uses fixed reference exchange rates "
                "(updated 2026-04-01). Not suitable for financial settlement."
            ),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        log.info(
            "cross_border.consolidate_revenue_complete",
            total_fen=consolidated_fen,
            markets=list(markets.keys()),
        )
        return result

    # ── Market Comparison ──────────────────────────────────────────

    async def compare_market_performance(
        self,
        tenant_id: str,
        period_start: str,
        period_end: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Compare store performance across markets.

        Fetches revenue, transaction volume, average order value,
        and store count per market, normalised to USD for cross-market
        comparison.

        Args:
            tenant_id: Tenant UUID.
            period_start: Period start date (YYYY-MM-DD).
            period_end: Period end date (YYYY-MM-DD).
            db: AsyncSession.

        Returns:
            {
                period: { from, to },
                markets: [
                    {
                        country_code, currency,
                        total_revenue_fen, total_revenue_usd,
                        transaction_count, avg_order_value_fen,
                        store_count, revenue_per_store_fen,
                    },
                    ...
                ],
                top_market: str,
                summary: { ... },
            }
        """
        log = logger.bind(
            tenant_id=tenant_id,
            period_start=period_start,
            period_end=period_end,
        )
        log.info("cross_border.compare_market_performance")

        try:
            rows = await db.execute(
                text("""
                    SELECT
                        s.country_code,
                        s.currency,
                        COALESCE(SUM(o.final_amount_fen), 0) AS revenue_fen,
                        COUNT(o.id) AS transaction_count,
                        CASE
                            WHEN COUNT(o.id) > 0
                            THEN COALESCE(SUM(o.final_amount_fen), 0) / COUNT(o.id)
                            ELSE 0
                        END AS avg_order_value_fen,
                        COUNT(DISTINCT s.id) AS store_count
                    FROM stores s
                    LEFT JOIN orders o ON o.store_id = s.id
                        AND o.tenant_id = s.tenant_id
                        AND o.order_date >= :pstart
                        AND o.order_date <= :pend
                        AND o.status IN ('completed', 'settled')
                        AND o.is_deleted = FALSE
                    WHERE s.tenant_id = :tid
                      AND s.is_deleted = FALSE
                    GROUP BY s.country_code, s.currency
                    ORDER BY revenue_fen DESC
                """),
                {
                    "tid": tenant_id,
                    "pstart": period_start,
                    "pend": period_end,
                },
            )
            market_rows = rows.mappings().fetchall()
        except Exception as exc:
            log.warning("market_comparison_query_failed", error=str(exc))
            market_rows = []

        markets_list: list[dict[str, Any]] = []
        best_revenue = 0
        top_market: Optional[str] = None

        for row in market_rows:
            country = row.get("country_code") or "CN"
            currency = (row.get("currency") or "CNY").upper()
            revenue_fen = int(row.get("revenue_fen", 0) or 0)
            tx_count = int(row.get("transaction_count", 0) or 0)
            avg_value_fen = int(row.get("avg_order_value_fen", 0) or 0)
            store_count = int(row.get("store_count", 0) or 0)

            try:
                usd_fen = convert_currency(revenue_fen, currency, "USD")
            except (ValueError, KeyError) as exc:
                log.warning(
                    "cross_border.usd_conversion_failed",
                    country=country,
                    error=str(exc),
                )
                usd_fen = 0

            revenue_per_store = (
                int(revenue_fen / store_count) if store_count > 0 else 0
            )

            entry: dict[str, Any] = {
                "country_code": country,
                "currency": currency,
                "total_revenue_fen": revenue_fen,
                "total_revenue_display": round(revenue_fen / 100, 2),
                "total_revenue_usd_fen": usd_fen,
                "total_revenue_usd": round(usd_fen / 100, 2),
                "transaction_count": tx_count,
                "avg_order_value_fen": avg_value_fen,
                "avg_order_value_display": round(avg_value_fen / 100, 2),
                "store_count": store_count,
                "revenue_per_store_fen": revenue_per_store,
                "revenue_per_store_display": round(revenue_per_store / 100, 2),
            }
            markets_list.append(entry)

            if revenue_fen > best_revenue:
                best_revenue = revenue_fen
                top_market = country

        result = {
            "period": {"from": period_start, "to": period_end},
            "markets": markets_list,
            "top_market": top_market,
            "market_count": len(markets_list),
            "summary": {
                "total_revenue_usd_fen": sum(
                    m["total_revenue_usd_fen"] for m in markets_list
                ),
                "total_transactions": sum(
                    m["transaction_count"] for m in markets_list
                ),
                "total_stores": sum(m["store_count"] for m in markets_list),
                "currency": "USD",
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        log.info(
            "cross_border.compare_market_performance_complete",
            markets=len(markets_list),
            top_market=top_market,
        )
        return result

    # ── Operational Hours ──────────────────────────────────────────

    async def get_operational_hours(
        self,
        tenant_id: str,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """Get operational hours for all stores in local time.

        Each store's opening hours are returned in its local timezone
        along with the UTC offset, so a brand operating across timezones
        can see when every store is open relative to their own location.

        Args:
            tenant_id: Tenant UUID.
            db: AsyncSession.

        Returns:
            [
                {
                    store_id, store_name,
                    country_code, timezone,
                    local_open, local_close,
                    utc_offset_hours,
                    current_local_time,
                    is_currently_open,
                },
                ...
            ]
        """
        log = logger.bind(tenant_id=tenant_id)
        log.info("cross_border.operational_hours")

        try:
            rows = await db.execute(
                text("""
                    SELECT
                        id AS store_id,
                        name AS store_name,
                        country_code,
                        timezone,
                        opening_time,
                        closing_time
                    FROM stores
                    WHERE tenant_id = :tid
                      AND is_deleted = FALSE
                    ORDER BY country_code, name
                """),
                {"tid": tenant_id},
            )
            store_rows = rows.mappings().fetchall()
        except Exception as exc:
            log.warning("operational_hours_query_failed", error=str(exc))
            store_rows = []

        results: list[dict[str, Any]] = []
        for row in store_rows:
            country_code = row.get("country_code") or "CN"
            tz_name = row.get("timezone") or "Asia/Shanghai"

            # Look up timezone offset from region config (fallback to UTC+8)
            region_config = get_config_by_country_code(country_code)
            effective_tz = region_config.timezone if region_config else tz_name

            # Determine UTC offset based on timezone
            utc_offset = _get_utc_offset_hours(effective_tz)

            # Current time in that timezone
            now = datetime.now(timezone.utc)
            current_local = _utc_to_local(now, utc_offset)

            opening = str(row.get("opening_time") or "08:00")
            closing = str(row.get("closing_time") or "22:00")

            is_open = _check_is_open(current_local, opening, closing)

            results.append({
                "store_id": str(row.get("store_id", "")),
                "store_name": row.get("store_name", ""),
                "country_code": country_code,
                "timezone": effective_tz,
                "utc_offset_hours": utc_offset,
                "local_open": opening,
                "local_close": closing,
                "current_local_time": current_local.strftime("%H:%M"),
                "is_currently_open": is_open,
            })

        log.info(
            "cross_border.operational_hours_complete",
            stores=len(results),
        )
        return results

    # ── Currency Info ──────────────────────────────────────────────

    @staticmethod
    def get_supported_currencies() -> list[str]:
        """Return list of supported currency codes."""
        return sorted(SUPPORTED_CURRENCIES)

    @staticmethod
    def get_exchange_rates() -> dict[str, dict[str, float]]:
        """Return the reference exchange rate table for display/audit."""
        return {
            from_c: {to_c: float(rate) for to_c, rate in rates.items()}
            for from_c, rates in EXCHANGE_RATES.items()
        }


# ── Internal Helpers ───────────────────────────────────────────────────


def get_config_by_country_code(code: str) -> Optional[RegionConfig]:
    """Resolve region config from a 2-letter country code.

    Args:
        code: ISO 3166-1 alpha-2 country code.

    Returns:
        RegionConfig or None.
    """
    from shared.region.src.region_config import get_config_by_code
    return get_config_by_code(code)


def _get_utc_offset_hours(timezone_name: str) -> int:
    """Get UTC offset hours for a known IANA timezone.

    Only handles the timezones relevant to our supported markets.
    For full timezone support, use zoneinfo (Python 3.9+).

    Args:
        timezone_name: IANA timezone string.

    Returns:
        UTC offset in hours.
    """
    known_offsets: dict[str, int] = {
        "Asia/Shanghai": 8,
        "Asia/Kuala_Lumpur": 8,
        "Asia/Singapore": 8,
        "Asia/Jakarta": 7,
        "Asia/Ho_Chi_Minh": 7,
        "Asia/Bangkok": 7,
        "Asia/Hong_Kong": 8,
    }
    return known_offsets.get(timezone_name, 8)


def _utc_to_local(
    utc_dt: datetime,
    offset_hours: int,
) -> datetime:
    """Convert a UTC datetime to a local time by applying offset.

    Args:
        utc_dt: Timezone-aware UTC datetime.
        offset_hours: UTC offset in hours (positive east of UTC).

    Returns:
        Local time as a naive datetime.
    """
    from datetime import timedelta
    return (utc_dt + timedelta(hours=offset_hours)).replace(tzinfo=None)


def _check_is_open(
    current_time: datetime,
    opening: str,
    closing: str,
) -> bool:
    """Check if a store is currently open based on its hours.

    Supports overnight hours (closing < opening, e.g. open 22:00 close 02:00).

    Args:
        current_time: Current local time as a datetime.
        opening: Opening time string (HH:MM).
        closing: Closing time string (HH:MM).

    Returns:
        True if the store is currently open.
    """
    current_minutes = current_time.hour * 60 + current_time.minute
    open_parts = opening.split(":")
    close_parts = closing.split(":")
    open_minutes = int(open_parts[0]) * 60 + int(open_parts[1])
    close_minutes = int(close_parts[0]) * 60 + int(close_parts[1])

    if close_minutes < open_minutes:
        # Overnight hours (e.g. 22:00 - 02:00)
        return current_minutes >= open_minutes or current_minutes < close_minutes
    return open_minutes <= current_minutes < close_minutes
