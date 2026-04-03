"""智能排班 — re-export from tx-org

Sprint 5-8 实现：SmartScheduleService
"""
import os
import sys

_TX_ORG_SRC = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../../tx-org/src")
)
if _TX_ORG_SRC not in sys.path:
    sys.path.insert(0, _TX_ORG_SRC)

from services.smart_schedule import SmartScheduleService  # noqa: E402

__all__ = ["SmartScheduleService"]
