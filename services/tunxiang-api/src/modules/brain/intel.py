"""情报引擎 — re-export from tx-intel

Sprint 9+ 实现：IntelReportEngine, CompetitorMonitorService
"""

import os
import sys

_TX_INTEL_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../tx-intel/src"))
if _TX_INTEL_SRC not in sys.path:
    sys.path.insert(0, _TX_INTEL_SRC)

from services.competitor_monitor import CompetitorMonitorService  # noqa: E402
from services.intel_report_engine import IntelReportEngine  # noqa: E402

__all__ = ["IntelReportEngine", "CompetitorMonitorService"]
