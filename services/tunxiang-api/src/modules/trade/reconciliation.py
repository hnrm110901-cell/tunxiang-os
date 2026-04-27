"""对账结算 — re-export from tx-trade

Sprint 3-4 实现：ReconciliationService
（ReconciliationService 位于 tx-trade，tx-finance 仅有路由层）
"""

import os
import sys

_TX_TRADE_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../tx-trade/src"))
if _TX_TRADE_SRC not in sys.path:
    sys.path.insert(0, _TX_TRADE_SRC)

from services.reconciliation import ReconciliationService  # noqa: E402

__all__ = ["ReconciliationService"]
