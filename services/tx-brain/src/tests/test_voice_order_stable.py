"""
Y-A14 语音点餐稳定性测试

覆盖文件：
  services/tx-brain/src/api/voice_order_stable_routes.py
  services/tx-brain/src/voice_command_cache.py

测试共 6 个：
  1. test_transcribe_cache_hit          — 缓存命中绕过 AI
  2. test_transcribe_timeout_degrades_gracefully — 超时返回降级
  3. test_parse_order_returns_cart_items — 解析返回购物车格式
  4. test_metrics_records_calls         — metrics 端点聚合
  5. test_cache_warm                    — 预热缓存
  6. test_fuzzy_match_dish              — 模糊匹配菜品
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import sys
import types

# ─── sys.path 准备 ────────────────────────────────────────────────────────────
_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_ROOT_DIR = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))

for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _ensure_pkg(name: str, path: str) -> None:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod


_ensure_pkg("src", _SRC_DIR)
_ensure_pkg("src.api", os.path.join(_SRC_DIR, "api"))
_ensure_pkg("src.services", os.path.join(_SRC_DIR, "services"))

# ─── structlog mock ───────────────────────────────────────────────────────────
_structlog = types.ModuleType("structlog")
_bound_logger = types.SimpleNamespace(
    info=lambda *a, **k: None,
    warning=lambda *a, **k: None,
    error=lambda *a, **k: None,
    debug=lambda *a, **k: None,
)
_structlog.get_logger = lambda *a, **k: _bound_logger  # type: ignore[attr-defined]
_structlog.stdlib = types.SimpleNamespace(BoundLogger=object)  # type: ignore[attr-defined]
sys.modules.setdefault("structlog", _structlog)

# ─── 正式 import ──────────────────────────────────────────────────────────────
# 重置单例缓存，防止跨测试污染
import importlib
from unittest.mock import patch  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

_cache_mod = importlib.import_module("src.voice_command_cache")
_cache_mod._cache = None  # type: ignore[attr-defined]

_routes_mod = importlib.import_module("src.api.voice_order_stable_routes")
_routes_mod._call_metrics.clear()  # type: ignore[attr-defined]

from src.api.voice_order_stable_routes import router  # type: ignore[import]  # noqa: E402
from src.voice_command_cache import VoiceCommandCache  # type: ignore[import]  # noqa: E402

# 测试专用应用
app = FastAPI()
app.include_router(router)
client = TestClient(app)


# ─── 辅助工具 ─────────────────────────────────────────────────────────────────


def _wav_bytes() -> bytes:
    """最小合法 WAV 文件内容（44 bytes header）"""
    import struct

    data_size = 4
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        16000,
        32000,
        2,
        16,
        b"data",
        data_size,
    )
    return header + b"\x00" * data_size


def _audio_hash(audio_bytes: bytes) -> str:
    return hashlib.sha256(audio_bytes).hexdigest()


# ─── Tests ────────────────────────────────────────────────────────────────────


class TestTranscribeStable:
    def test_transcribe_cache_hit(self) -> None:
        """1. 缓存命中：第二次相同音频直接从缓存返回，跳过 AI 调用

        方法：先手动写入缓存，再发起请求验证 from_cache=True。
        """
        audio = _wav_bytes()
        audio_key = _audio_hash(audio)

        # 手动预填缓存
        cache = _cache_mod.get_voice_cache()
        cache.put(audio_key, {"text": "来一份酸菜鱼", "confidence": 0.99, "language": "zh"})

        resp = client.post(
            "/api/v1/brain/voice/transcribe-stable",
            files={"file": ("test.wav", io.BytesIO(audio), "audio/wav")},
            data={"language": "zh"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["from_cache"] is True
        assert body["data"]["text"] == "来一份酸菜鱼"

    def test_transcribe_timeout_degrades_gracefully(self) -> None:
        """2. AI 超时后返回降级结果（degraded=True, text=None）"""
        audio = b"\xff\xfe" + os.urandom(1024)  # 随机音频，不命中缓存

        async def _slow(*args, **kwargs):
            await asyncio.sleep(10)  # 远超 3s 超时
            return {"text": "不会返回这个", "confidence": 1.0}

        with patch.object(_routes_mod, "_mock_transcribe_ai", side_effect=_slow):
            resp = client.post(
                "/api/v1/brain/voice/transcribe-stable",
                files={"file": ("test.wav", io.BytesIO(audio), "audio/wav")},
                data={"language": "zh"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["text"] is None
        assert data["degraded"] is True
        assert data["reason"] == "timeout"

    def test_empty_audio_returns_400(self) -> None:
        """空音频 → 400"""
        resp = client.post(
            "/api/v1/brain/voice/transcribe-stable",
            files={"file": ("empty.wav", io.BytesIO(b""), "audio/wav")},
        )
        assert resp.status_code == 400


class TestParseOrder:
    def test_parse_order_returns_cart_items(self) -> None:
        """3. 解析返回购物车格式 {cart_items: [...], item_count: N}"""
        resp = client.post(
            "/api/v1/brain/voice/parse-order",
            json={
                "text": "来三份宫保鸡丁",
                "store_id": "store_001",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert "cart_items" in data
        assert "item_count" in data
        assert data["item_count"] >= 1

        # 购物车项目字段校验
        item = data["cart_items"][0]
        assert "name" in item
        assert "quantity" in item

    def test_parse_order_empty_text_returns_400(self) -> None:
        """空文本 → 400"""
        resp = client.post(
            "/api/v1/brain/voice/parse-order",
            json={
                "text": "   ",
                "store_id": "store_001",
            },
        )
        assert resp.status_code == 400


class TestMetrics:
    def test_metrics_records_calls(self) -> None:
        """4. metrics 端点聚合：每次调用后 total_calls 递增"""
        # 清空历史数据
        _routes_mod._call_metrics.clear()  # type: ignore[attr-defined]

        audio = _wav_bytes()
        # 触发一次 AI 调用（缓存已清空，第一次请求走 AI）
        cache = _cache_mod.get_voice_cache()
        cache._lru._cache.clear()

        client.post(
            "/api/v1/brain/voice/transcribe-stable",
            files={"file": ("test.wav", io.BytesIO(audio), "audio/wav")},
            data={"language": "zh"},
        )

        resp = client.get("/api/v1/brain/voice/metrics")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["total_calls"] >= 1
        assert "error_rate" in data
        assert "timeout_rate" in data
        assert "avg_duration_ms" in data
        assert "method_breakdown" in data


class TestCacheWarm:
    def test_cache_warm(self) -> None:
        """5. 预热缓存：POST /cache/warm 返回预热数量"""
        catalog = [
            {"dish_id": "D001", "name": "酸菜鱼"},
            {"dish_id": "D002", "name": "宫保鸡丁"},
            {"dish_id": "D003", "name": "麻婆豆腐"},
        ]
        resp = client.post("/api/v1/brain/voice/cache/warm", json={"dish_catalog": catalog})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["warmed_count"] == 3

    def test_cache_stats_returns_hit_rate(self) -> None:
        """缓存统计端点返回命中率字段"""
        resp = client.get("/api/v1/brain/voice/cache/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        stats = body["data"]
        assert "hit_rate" in stats
        assert "hits" in stats
        assert "misses" in stats
        assert "lru_size" in stats


class TestFuzzyMatch:
    def test_fuzzy_match_dish(self) -> None:
        """6. 模糊匹配：'酸菜鱼' 匹配 '酸菜鱼片' 且相似度 >= 0.6"""
        cache = VoiceCommandCache(cache_path="/tmp/txos_voice_cache_test.json")  # noqa: S108 — test-only path
        catalog = [
            {"dish_id": "D001", "name": "酸菜鱼片"},
            {"dish_id": "D002", "name": "宫保鸡丁"},
            {"dish_id": "D003", "name": "干锅牛蛙"},
        ]

        result = cache.fuzzy_match_dish("酸菜鱼", catalog)
        assert result is not None
        assert result["dish_id"] == "D001"
        assert result["match_score"] >= 0.6

    def test_fuzzy_match_no_match_returns_none(self) -> None:
        """完全不相关的文本 → 返回 None"""
        cache = VoiceCommandCache(cache_path="/tmp/txos_voice_cache_test.json")  # noqa: S108 — test-only path
        catalog = [
            {"dish_id": "D001", "name": "酸菜鱼"},
            {"dish_id": "D002", "name": "宫保鸡丁"},
        ]
        result = cache.fuzzy_match_dish("xyzabc123", catalog)
        assert result is None

    def test_fuzzy_match_empty_inputs(self) -> None:
        """空输入 → 返回 None"""
        cache = VoiceCommandCache(cache_path="/tmp/txos_voice_cache_test.json")  # noqa: S108 — test-only path
        assert cache.fuzzy_match_dish("", []) is None
        assert cache.fuzzy_match_dish("酸菜鱼", []) is None
