"""CFO驾驶舱 — re-export from tx-brain

Sprint 9+ 实现：CFODashboardService
"""
import os
import sys

_TX_BRAIN_SRC = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../../tx-brain/src")
)
if _TX_BRAIN_SRC not in sys.path:
    sys.path.insert(0, _TX_BRAIN_SRC)

from services.cfo_dashboard import CFODashboardService  # noqa: E402

__all__ = ["CFODashboardService"]
