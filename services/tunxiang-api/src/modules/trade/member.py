"""会员服务 — re-export from tx-trade

Sprint 3-4 实现：MemberGoldenIDService
"""
import os
import sys

_TX_TRADE_SRC = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../../tx-trade/src")
)
if _TX_TRADE_SRC not in sys.path:
    sys.path.insert(0, _TX_TRADE_SRC)

from services.member_golden_id import MemberGoldenIDService  # noqa: E402

__all__ = ["MemberGoldenIDService"]
