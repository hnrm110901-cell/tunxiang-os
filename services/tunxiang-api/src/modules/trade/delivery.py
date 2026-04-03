"""外卖平台对接 — re-export from tx-trade

Sprint 5+ 实现：DeliveryPlatformAdapter
"""
import os
import sys

_TX_TRADE_SRC = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../../tx-trade/src")
)
if _TX_TRADE_SRC not in sys.path:
    sys.path.insert(0, _TX_TRADE_SRC)

from services.delivery_adapter import DeliveryPlatformAdapter  # noqa: E402

__all__ = ["DeliveryPlatformAdapter"]
