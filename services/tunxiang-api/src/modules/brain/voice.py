"""语音交互 — re-export from tx-brain

Sprint 9+ 实现：VoiceOrchestrator
"""
import os
import sys

_TX_BRAIN_SRC = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../../tx-brain/src")
)
if _TX_BRAIN_SRC not in sys.path:
    sys.path.insert(0, _TX_BRAIN_SRC)

from services.voice_orchestrator import VoiceOrchestrator  # noqa: E402

__all__ = ["VoiceOrchestrator"]
