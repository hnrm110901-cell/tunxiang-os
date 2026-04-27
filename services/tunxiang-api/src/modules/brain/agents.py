"""Agent OS — re-export from tx-agent

Sprint 5-8 实现：MasterAgent, SkillAgents
"""

import os
import sys

_TX_AGENT_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../tx-agent/src"))
if _TX_AGENT_SRC not in sys.path:
    sys.path.insert(0, _TX_AGENT_SRC)

from agents.master import MasterAgent  # noqa: E402
from agents.skills import DiscountGuardAgent  # noqa: E402

__all__ = ["MasterAgent", "DiscountGuardAgent"]
