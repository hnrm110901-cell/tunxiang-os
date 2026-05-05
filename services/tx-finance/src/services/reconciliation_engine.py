"""ReconciliationEngine — cross-platform settlement matching.

Matches platform settlement reports against internal orders.
Flags discrepancies for manual review. Tracks T+N payment arrival.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

import structlog

logger = structlog.get_logger()


class ReconciliationStatus(str, Enum):
    MATCHED = "matched"
    MISMATCH = "mismatch"
    MISSING_INTERNAL = "missing_internal"
    MISSING_PLATFORM = "missing_platform"
    PENDING = "pending"


@dataclass
class SettlementRecord:
    platform: str
    platform_order_id: str
    platform_amount_fen: int
    platform_commission_fen: int
    platform_settlement_fen: int
    settlement_date: str
    internal_order_id: Optional[str] = None
    internal_amount_fen: int = 0
    internal_commission_fen: int = 0
    status: ReconciliationStatus = ReconciliationStatus.PENDING
    discrepancy_fen: int = 0
    notes: str = ""


class ReconciliationEngine:
    """Cross-platform settlement reconciliation.

    Matches platform settlement records against internal order data.
    Flags mismatches, missing orders, and commission anomalies.
    """

    PLATFORM_COMMISSION_RATES: dict[str, float] = {
        "meituan": 0.20,
        "eleme": 0.18,
        "douyin": 0.05,
        "amap": 0.10,
        "taobao": 0.15,
    }

    # Tolerance: 50 fen (0.5 yuan) for rounding differences
    AMOUNT_TOLERANCE_FEN = 50

    def get_expected_commission(self, platform: str, amount_fen: int) -> int:
        rate = self.PLATFORM_COMMISSION_RATES.get(platform, 0.20)
        return round(amount_fen * rate)

    def match_settlement(
        self,
        platform: str,
        platform_order_id: str,
        platform_amount_fen: int,
        platform_commission_fen: int,
        internal_order_id: str = "",
        internal_amount_fen: int = 0,
    ) -> SettlementRecord:
        expected_commission = self.get_expected_commission(
            platform, platform_amount_fen
        )
        commission_tolerance = max(1, expected_commission * 0.05)

        record = SettlementRecord(
            platform=platform,
            platform_order_id=platform_order_id,
            platform_amount_fen=platform_amount_fen,
            platform_commission_fen=platform_commission_fen,
            platform_settlement_fen=platform_amount_fen - platform_commission_fen,
            settlement_date=datetime.now().strftime("%Y-%m-%d"),
            internal_order_id=internal_order_id or None,
            internal_amount_fen=internal_amount_fen,
            internal_commission_fen=expected_commission,
        )

        if not internal_order_id:
            record.status = ReconciliationStatus.MISSING_INTERNAL
            record.notes = "平台有结算记录但内部无对应订单"
        elif abs(internal_amount_fen - platform_amount_fen) > self.AMOUNT_TOLERANCE_FEN:
            record.status = ReconciliationStatus.MISMATCH
            record.discrepancy_fen = abs(internal_amount_fen - platform_amount_fen)
            record.notes = f"金额不符: 平台={platform_amount_fen} 内部={internal_amount_fen}"
        elif abs(platform_commission_fen - expected_commission) > commission_tolerance:
            record.status = ReconciliationStatus.MISMATCH
            record.discrepancy_fen = abs(platform_commission_fen - expected_commission)
            record.notes = f"佣金异常: 平台={platform_commission_fen} 预期={expected_commission}"
        else:
            record.status = ReconciliationStatus.MATCHED

        logger.info(
            "reconciliation.result",
            platform=platform,
            order_id=platform_order_id,
            status=record.status.value,
        )
        return record

    def batch_reconcile(self, settlements: list[dict[str, Any]]) -> dict[str, Any]:
        results: list[SettlementRecord] = []
        matched = mismatched = missing = 0
        total_discrepancy = 0

        for s in settlements:
            r = self.match_settlement(**s)
            results.append(r)
            if r.status == ReconciliationStatus.MATCHED:
                matched += 1
            elif r.status == ReconciliationStatus.MISMATCH:
                mismatched += 1
                total_discrepancy += r.discrepancy_fen
            else:
                missing += 1

        total = max(len(results), 1)
        return {
            "results": [vars(r) for r in results],
            "summary": {
                "total": len(results),
                "matched": matched,
                "mismatched": mismatched,
                "missing": missing,
                "total_discrepancy_fen": total_discrepancy,
                "match_rate": matched / total,
            },
        }
