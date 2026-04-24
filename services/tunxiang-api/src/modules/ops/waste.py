"""损耗管控 — re-export from tx-supply

Sprint 5-8 实现：WasteGuardV2
"""

import os
import sys

_TX_SUPPLY_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../tx-supply/src"))
if _TX_SUPPLY_SRC not in sys.path:
    sys.path.insert(0, _TX_SUPPLY_SRC)

from services.waste_guard_v2 import WasteGuardV2  # noqa: E402

__all__ = ["WasteGuardV2"]
