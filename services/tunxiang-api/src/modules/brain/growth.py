"""增长引擎 — re-export from tx-growth

Sprint 9+ 实现：JourneyEngine
"""

import os
import sys

_TX_GROWTH_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../tx-growth/src"))
if _TX_GROWTH_SRC not in sys.path:
    sys.path.insert(0, _TX_GROWTH_SRC)

from engine.journey_engine import JourneyEngine  # noqa: E402

__all__ = ["JourneyEngine"]
