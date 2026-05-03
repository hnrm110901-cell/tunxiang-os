"""Central region configuration for all supported markets

Phase 3 Sprint 3.6 — Multi-country restaurant OS regional expansion.
Supports CN, MY, ID, VN with extensible pattern for SG, TH (future).

Each market has its own tax regime, payment methods, delivery platforms,
invoice system, locale, and timezone. This module provides a single
source of truth for all region-specific configuration.

Usage:
    from shared.region.src.region_config import (
        MarketRegion, RegionConfig, REGION_CONFIGS,
        get_config, get_supported_markets, is_market_supported,
    )

    config = get_config(MarketRegion.MALAYSIA)
    sst_rates = [r for r in config.tax_rates if r["rate"] > 0]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


# ── Markets ────────────────────────────────────────────────────────────


class MarketRegion(Enum):
    """Enum of all supported and planned markets.

    Values are ISO 3166-1 alpha-2 country codes used throughout the
    system for routing, localization, and compliance.
    """

    CHINA = "CN"
    MALAYSIA = "MY"
    INDONESIA = "ID"
    VIETNAM = "VN"
    SINGAPORE = "SG"   # future
    THAILAND = "TH"    # future


# ── Config Dataclass ───────────────────────────────────────────────────


@dataclass
class RegionConfig:
    """Immutable configuration for a single market region.

    All monetary amounts in the system use fen (integer cents) as the
    base unit. Currency display fields (symbol, code) are for UI only.

    Attributes:
        code:            MarketRegion enum value.
        name:            Localised name dict keyed by language code.
        currency_code:   ISO 4217 currency code (e.g. "CNY", "MYR").
        currency_symbol: Display symbol (e.g. "¥", "RM").
        locale:          BCP 47 locale tag (e.g. "zh-CN", "ms-MY").
        timezone:        IANA timezone string (e.g. "Asia/Shanghai").
        tax_label:       Short tax regime name (e.g. "VAT", "SST", "PPN").
        tax_rates:       List of applicable tax rates with labels.
        payment_methods: Supported payment method keys.
        delivery_platforms: Supported third-party delivery platform keys.
        invoice_system:  Invoice/compliance system identifier.
        date_format:     Locale-appropriate date format string.
        phone_prefix:    International dialling prefix.
        language_codes:  Official/business language codes for the region.
    """

    code: MarketRegion
    name: dict
    currency_code: str
    currency_symbol: str
    locale: str
    timezone: str
    tax_label: str
    tax_rates: list[dict]
    payment_methods: list[str]
    delivery_platforms: list[str]
    invoice_system: str
    date_format: str
    phone_prefix: str
    language_codes: list[str]


# ── Region Configs ─────────────────────────────────────────────────────


REGION_CONFIGS: dict[MarketRegion, RegionConfig] = {
    MarketRegion.CHINA: RegionConfig(
        code=MarketRegion.CHINA,
        name={"zh": "中国", "en": "China", "ms": "China", "ta": "சீனா"},
        currency_code="CNY",
        currency_symbol="¥",
        locale="zh-CN",
        timezone="Asia/Shanghai",
        tax_label="VAT",
        tax_rates=[
            {"name": "standard", "rate": 0.13},
            {"name": "reduced", "rate": 0.09},
            {"name": "small_scale", "rate": 0.06},
            {"name": "exempt", "rate": 0.0},
        ],
        payment_methods=["wechat_pay", "alipay", "cash", "card"],
        delivery_platforms=["meituan", "eleme", "douyin"],
        invoice_system="nuonuo",
        date_format="YYYY-MM-DD",
        phone_prefix="+86",
        language_codes=["zh", "en"],
    ),
    MarketRegion.MALAYSIA: RegionConfig(
        code=MarketRegion.MALAYSIA,
        name={
            "zh": "马来西亚",
            "en": "Malaysia",
            "ms": "Malaysia",
            "ta": "மலேசியா",
        },
        currency_code="MYR",
        currency_symbol="RM",
        locale="ms-MY",
        timezone="Asia/Kuala_Lumpur",
        tax_label="SST",
        tax_rates=[
            {"name": "standard", "rate": 0.08},
            {"name": "f&b", "rate": 0.06},
            {"name": "exempt", "rate": 0.0},
        ],
        payment_methods=["tng_ewallet", "grabpay", "boost", "cash", "card"],
        delivery_platforms=["grabfood", "foodpanda", "shopeefood"],
        invoice_system="myinvois",
        date_format="DD/MM/YYYY",
        phone_prefix="+60",
        language_codes=["ms", "zh", "en", "ta"],
    ),
    MarketRegion.INDONESIA: RegionConfig(
        code=MarketRegion.INDONESIA,
        name={
            "zh": "印度尼西亚",
            "en": "Indonesia",
            "ms": "Indonesia",
            "ta": "இந்தோனேசியா",
        },
        currency_code="IDR",
        currency_symbol="Rp",
        locale="id-ID",
        timezone="Asia/Jakarta",
        tax_label="PPN",
        tax_rates=[
            {"name": "standard", "rate": 0.11},
            {"name": "exempt", "rate": 0.0},
        ],
        payment_methods=["gopay", "dana", "cash", "card"],
        delivery_platforms=["gofood", "shopeefood"],
        invoice_system="efaktur",
        date_format="DD/MM/YYYY",
        phone_prefix="+62",
        language_codes=["id", "en"],
    ),
    MarketRegion.VIETNAM: RegionConfig(
        code=MarketRegion.VIETNAM,
        name={
            "zh": "越南",
            "en": "Vietnam",
            "ms": "Vietnam",
            "ta": "வியட்நாம்",
        },
        currency_code="VND",
        currency_symbol="₫",
        locale="vi-VN",
        timezone="Asia/Ho_Chi_Minh",
        tax_label="VAT",
        tax_rates=[
            {"name": "standard", "rate": 0.10},
            {"name": "reduced", "rate": 0.08},
            {"name": "exempt", "rate": 0.0},
        ],
        payment_methods=["momo", "zalopay", "cash", "card"],
        delivery_platforms=["grabfood", "shopeefood"],
        invoice_system="einvoice",
        date_format="DD/MM/YYYY",
        phone_prefix="+84",
        language_codes=["vi", "en"],
    ),
}


# ── Public API ─────────────────────────────────────────────────────────


def get_config(region: MarketRegion) -> Optional[RegionConfig]:
    """Get the region configuration for a given market.

    Args:
        region: The target MarketRegion.

    Returns:
        RegionConfig if the market is supported, None otherwise.
    """
    config = REGION_CONFIGS.get(region)
    if config is None:
        logger.warning(
            "region_config.not_found",
            region=region.value if region else "None",
        )
    return config


def get_config_by_code(code: str) -> Optional[RegionConfig]:
    """Look up region configuration by ISO country code string.

    Args:
        code: ISO 3166-1 alpha-2 country code (e.g. "CN", "MY").

    Returns:
        RegionConfig if found, None otherwise.
    """
    try:
        region = MarketRegion(code.upper())
        return get_config(region)
    except ValueError:
        logger.warning(
            "region_config.unknown_code",
            code=code,
        )
        return None


def get_supported_markets(include_future: bool = False) -> list[dict]:
    """Return list of supported markets with basic info.

    Args:
        include_future: If True, include planned markets (SG, TH).

    Returns:
        List of dicts with code, name, currency, locale for each market.
    """
    result: list[dict] = []
    for region, config in REGION_CONFIGS.items():
        result.append({
            "code": region.value,
            "name": config.name,
            "currency_code": config.currency_code,
            "currency_symbol": config.currency_symbol,
            "locale": config.locale,
            "timezone": config.timezone,
            "tax_label": config.tax_label,
        })

    if include_future:
        result.append({
            "code": "SG",
            "name": {"en": "Singapore", "zh": "新加坡", "ms": "Singapura", "ta": "சிங்கப்பூர்"},
            "currency_code": "SGD",
            "currency_symbol": "S$",
            "locale": "en-SG",
            "timezone": "Asia/Singapore",
            "tax_label": "GST",
        })
        result.append({
            "code": "TH",
            "name": {"en": "Thailand", "zh": "泰国", "ms": "Thailand", "ta": "தாய்லாந்து"},
            "currency_code": "THB",
            "currency_symbol": "฿",
            "locale": "th-TH",
            "timezone": "Asia/Bangkok",
            "tax_label": "VAT",
        })

    return result


def is_market_supported(code: str) -> bool:
    """Check whether a given country code is a currently supported market.

    Args:
        code: ISO 3166-1 alpha-2 country code.

    Returns:
        True if the market has an active RegionConfig.
    """
    return get_config_by_code(code) is not None
