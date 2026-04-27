"""收银引擎 — re-export from tx-trade

Sprint 1-2 实现：CashierEngine, PaymentGateway
"""

import os
import sys

_TX_TRADE_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../tx-trade/src"))
if _TX_TRADE_SRC not in sys.path:
    sys.path.insert(0, _TX_TRADE_SRC)

from services.cashier_engine import CashierEngine  # noqa: E402
from services.payment_gateway import PaymentGateway  # noqa: E402

__all__ = ["CashierEngine", "PaymentGateway"]
