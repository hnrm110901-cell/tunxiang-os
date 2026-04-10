"""tx-brain voice_api 路由层测试

覆盖文件：src/api/voice_api.py（5 个端点）

测试共 10 个：

  1.  POST /command             — happy path（文件非空，store_id 有效）
  2.  POST /command             — 空音频 → 400 EMPTY_AUDIO
  3.  POST /command             — 缺少 store_id → 400 MISSING_STORE_ID
  4.  POST /transcribe          — happy path
  5.  POST /transcribe          — 空音频 → 400 EMPTY_AUDIO
  6.  POST /transcribe          — 不支持的 content_type → 400 INVALID_AUDIO_FORMAT
  7.  POST /understand          — happy path
  8.  POST /understand          — 空文本 → 400 EMPTY_TEXT
  9.  POST /session             — 创建会话 happy path
  10. GET  /session/{id}        — 获取会话 happy path / not found → 404
"""
from __future__ import annotations

import io
import os
import sys
import types
import uuid

# ─── sys.path 准备 ───────────────────────────────────────────────────────────
_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR   = os.path.join(_TESTS_DIR, "..")
_ROOT_DIR  = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))

for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _ensure_pkg(name: str, path: str) -> None:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod


_ensure_pkg("src",          _SRC_DIR)
_ensure_pkg("src.api",      os.path.join(_SRC_DIR, "api"))
_ensure_pkg("src.services", os.path.join(_SRC_DIR, "services"))

# ─── structlog mock ──────────────────────────────────────────────────────────
_structlog = types.ModuleType("structlog")
_structlog.get_logger = lambda: types.SimpleNamespace(  # type: ignore[attr-defined]
    info=lambda *a, **k: None,
    warning=lambda *a, **k: None,
    error=lambda *a, **k: None,
    debug=lambda *a, **k: None,
)
sys.modules.setdefault("structlog", _structlog)

# ─── voice_orchestrator mock ─────────────────────────────────────────────────
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

_orch_mod = types.ModuleType("src.services.voice_orchestrator")


class _FakeOrchestrator:
    async def process_voice_command(self, **kwargs):
        return {
            "transcription": {"text": "三号桌加一份酸菜鱼", "confidence": 0.97},
            "intent": "add_order_item",
            "entities": {"table": "3", "dish": "酸菜鱼", "qty": 1},
            "response_text": "好的，已为三号桌加一份酸菜鱼",
            "actions": [{"type": "add_item", "status": "success"}],
        }

    async def transcribe(self, audio_bytes: bytes, language: str = "zh"):
        return {"text": "三号桌加一份酸菜鱼", "confidence": 0.97, "language": language}

    async def understand(self, text: str, context=None):
        return {
            "intent": "add_order_item",
            "entities": {"table": "3", "dish": "酸菜鱼"},
            "confidence": 0.92,
        }


_orch_mod.VoiceOrchestrator = _FakeOrchestrator  # type: ignore[attr-defined]
sys.modules["src.services.voice_orchestrator"] = _orch_mod

# ─── voice_session mock ───────────────────────────────────────────────────────
_sess_mod = types.ModuleType("src.services.voice_session")

SESSION_ID = f"VS-{uuid.uuid4().hex[:12].upper()}"


class _FakeSessionManager:
    def create_session(self, employee_id: str, store_id: str, device_type: str = "pos"):
        return {
            "session_id": SESSION_ID,
            "employee_id": employee_id,
            "store_id": store_id,
            "device_type": device_type,
            "status": "active",
        }

    def add_turn(self, session_id: str, role: str, text: str):
        pass

    def update_context(self, session_id: str, ctx: dict):
        pass

    def get_session(self, session_id: str):
        if session_id == SESSION_ID:
            return {
                "ok": True,
                "session_id": session_id,
                "status": "active",
                "turns": [],
            }
        return {"ok": False, "error": "Session not found"}


_sess_mod.VoiceSessionManager = _FakeSessionManager  # type: ignore[attr-defined]
sys.modules["src.services.voice_session"] = _sess_mod

# ─── 正式 import ─────────────────────────────────────────────────────────────
import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api.voice_api import router  # type: ignore[import]  # noqa: E402

# ─── 测试 App ─────────────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(router)
client = TestClient(app)


def _wav_bytes() -> bytes:
    """最小合法 WAV 文件头（44 bytes）"""
    import struct
    data_size = 44
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,       # PCM
        1,       # channels
        16000,   # sample rate
        32000,   # byte rate
        2,       # block align
        16,      # bits per sample
        b"data",
        data_size,
    )
    return header + b"\x00" * data_size


# ═══════════════════════════════════════════════════════════════════════════════
# 1. POST /command — happy path
# ═══════════════════════════════════════════════════════════════════════════════

def test_voice_command_happy_path():
    audio = _wav_bytes()
    resp = client.post(
        "/api/v1/voice/command",
        data={"language": "zh", "store_id": "store-001", "employee_id": "emp-001"},
        files={"file": ("test.wav", io.BytesIO(audio), "audio/wav")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "transcription" in body["data"]
    assert body["data"]["intent"] == "add_order_item"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. POST /command — 空音频 → 400
# ═══════════════════════════════════════════════════════════════════════════════

def test_voice_command_empty_audio():
    resp = client.post(
        "/api/v1/voice/command",
        data={"language": "zh", "store_id": "store-001"},
        files={"file": ("empty.wav", io.BytesIO(b""), "audio/wav")},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "EMPTY_AUDIO"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. POST /command — 缺少 store_id → 400
# ═══════════════════════════════════════════════════════════════════════════════

def test_voice_command_missing_store_id():
    audio = _wav_bytes()
    resp = client.post(
        "/api/v1/voice/command",
        data={"language": "zh"},
        files={"file": ("test.wav", io.BytesIO(audio), "audio/wav")},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "MISSING_STORE_ID"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. POST /transcribe — happy path
# ═══════════════════════════════════════════════════════════════════════════════

def test_transcribe_happy_path():
    audio = _wav_bytes()
    resp = client.post(
        "/api/v1/voice/transcribe",
        data={"language": "zh"},
        files={"file": ("test.wav", io.BytesIO(audio), "audio/wav")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "text" in body["data"]


# ═══════════════════════════════════════════════════════════════════════════════
# 5. POST /transcribe — 空音频 → 400
# ═══════════════════════════════════════════════════════════════════════════════

def test_transcribe_empty_audio():
    resp = client.post(
        "/api/v1/voice/transcribe",
        data={"language": "zh"},
        files={"file": ("empty.wav", io.BytesIO(b""), "audio/wav")},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "EMPTY_AUDIO"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. POST /transcribe — 不支持的 content_type → 400
# ═══════════════════════════════════════════════════════════════════════════════

def test_transcribe_invalid_format():
    resp = client.post(
        "/api/v1/voice/transcribe",
        data={"language": "zh"},
        files={"file": ("test.xyz", io.BytesIO(b"fake audio"), "audio/xyz-unknown")},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "INVALID_AUDIO_FORMAT"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. POST /understand — happy path
# ═══════════════════════════════════════════════════════════════════════════════

def test_understand_happy_path():
    resp = client.post(
        "/api/v1/voice/understand",
        json={"text": "三号桌加一份酸菜鱼"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["intent"] == "add_order_item"


# ═══════════════════════════════════════════════════════════════════════════════
# 8. POST /understand — 空文本 → 400
# ═══════════════════════════════════════════════════════════════════════════════

def test_understand_empty_text():
    resp = client.post(
        "/api/v1/voice/understand",
        json={"text": "   "},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "EMPTY_TEXT"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. POST /session — 创建会话 happy path
# ═══════════════════════════════════════════════════════════════════════════════

def test_create_session_happy_path():
    resp = client.post(
        "/api/v1/voice/session",
        json={"employee_id": "emp-001", "store_id": "store-001", "device_type": "pos"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["session_id"] == SESSION_ID
    assert data["status"] == "active"


# ═══════════════════════════════════════════════════════════════════════════════
# 10a. GET /session/{id} — happy path
# ═══════════════════════════════════════════════════════════════════════════════

def test_get_session_happy_path():
    resp = client.get(f"/api/v1/voice/session/{SESSION_ID}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["session_id"] == SESSION_ID


# ═══════════════════════════════════════════════════════════════════════════════
# 10b. GET /session/{id} — not found → 404
# ═══════════════════════════════════════════════════════════════════════════════

def test_get_session_not_found():
    resp = client.get("/api/v1/voice/session/VS-NONEXISTENT")
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["code"] == "SESSION_NOT_FOUND"
