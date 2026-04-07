"""
语音点餐稳定性路由 — Y-A14

超时降级 + 本地缓存指令 + 埋点

Endpoints:
  POST   /api/v1/brain/voice/transcribe-stable    语音识别（带超时降级+缓存）
  POST   /api/v1/brain/voice/parse-order          语音指令解析为购物车项目
  GET    /api/v1/brain/voice/metrics              语音点餐错误率看板
  POST   /api/v1/brain/voice/cache/warm           预热菜品名缓存
  GET    /api/v1/brain/voice/cache/stats          缓存命中率统计
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from collections import deque
from typing import Any

import structlog
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from ..voice_command_cache import VoiceCommandCache, get_voice_cache

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/brain/voice", tags=["voice-stable"])

# ─── 埋点内存存储（最多 1000 条） ────────────────────────────────────────────
_MAX_METRICS = 1000
_call_metrics: deque[dict[str, Any]] = deque(maxlen=_MAX_METRICS)

# 语音识别超时阈值（秒）
_TRANSCRIBE_TIMEOUT_SECS = 3.0


# ─── Request / Response Models ───────────────────────────────────────────────


class ParseOrderRequest(BaseModel):
    text: str = Field(..., min_length=1, description="语音识别文本")
    store_id: str = Field(..., description="门店 ID")
    session_id: str = Field("", description="会话 ID（可选）")


class DishItem(BaseModel):
    name: str
    quantity: int = 1
    note: str = ""


class WarmCacheRequest(BaseModel):
    dish_catalog: list[dict[str, Any]] = Field(
        ..., description="菜品列表，每项包含 dish_id + name"
    )


# ─── 内部工具函数 ─────────────────────────────────────────────────────────────


def _audio_hash(audio_bytes: bytes) -> str:
    """计算音频内容的 SHA-256 哈希（用作缓存键）"""
    return hashlib.sha256(audio_bytes).hexdigest()


def _record_metric(
    duration_ms: float,
    method: str,
    success: bool,
    endpoint: str = "transcribe",
) -> None:
    """埋点：记录一次语音调用指标"""
    _call_metrics.append({
        "ts": time.time(),
        "endpoint": endpoint,
        "duration_ms": round(duration_ms, 2),
        "method": method,   # "cache" | "ai" | "timeout"
        "success": success,
    })


async def _mock_transcribe_ai(audio_bytes: bytes, language: str = "zh") -> dict[str, Any]:
    """模拟 AI 语音识别（真实部署替换为实际 ASR 调用）

    集成时替换为：
        from ..services.voice_orchestrator import VoiceOrchestrator
        result = await orchestrator.transcribe(audio_bytes, language)
    """
    # 模拟 AI 处理延迟
    await asyncio.sleep(0.05)
    return {
        "text": "来一份酸菜鱼",
        "confidence": 0.95,
        "language": language,
    }


def _parse_text_to_cart(text: str) -> list[dict[str, Any]]:
    """简单规则解析语音文本 → 购物车格式

    真实部署替换为 NLU 服务调用。
    支持格式：
      "来一份酸菜鱼"
      "三份宫保鸡丁"
      "加两个凉拌黄瓜不要辣"
    """
    import re

    # 数量词映射
    cn_nums = {"一": 1, "两": 2, "三": 3, "四": 4, "五": 5,
               "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    items: list[dict[str, Any]] = []

    # 匹配：(来/加)(数量词/数字)(份/个/碗/杯)(菜名)
    patterns = [
        r"(?:来|加|要|再来|再加)?([一两三四五六七八九十\d]+)[份个碗杯]([^\s，。,]+)",
        r"(?:来|加|要|再来|再加)一?([^\s一两三四五六七八九十\d份个碗杯，。,]+)",
    ]

    for pat in patterns:
        matches = re.findall(pat, text)
        for m in matches:
            if isinstance(m, tuple) and len(m) == 2:
                qty_str, name = m
                qty = cn_nums.get(qty_str, None)
                if qty is None:
                    try:
                        qty = int(qty_str)
                    except ValueError:
                        qty = 1
            else:
                name = m
                qty = 1
            name = name.strip()
            if name:
                items.append({"name": name, "quantity": qty, "note": ""})

    # 无法解析时返回原始文本作为单条目
    if not items and text.strip():
        items.append({"name": text.strip(), "quantity": 1, "note": ""})

    return items


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/transcribe-stable")
async def transcribe_stable(
    file: UploadFile = File(...),
    language: str = Form("zh"),
) -> dict[str, Any]:
    """POST /api/v1/brain/voice/transcribe-stable

    语音识别，带三层稳定性保障：
    1. 缓存命中 → 直接返回，跳过 AI 调用
    2. AI 识别（3秒超时）
    3. 超时 → 降级返回 {text: null, degraded: true}
    """
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(
            status_code=400,
            detail={"code": "EMPTY_AUDIO", "message": "Audio file is empty"},
        )

    start = time.perf_counter()
    cache: VoiceCommandCache = get_voice_cache()
    audio_key = _audio_hash(audio_bytes)

    # 1. 缓存命中
    cached = cache.get(audio_key)
    if cached is not None:
        duration_ms = (time.perf_counter() - start) * 1000
        _record_metric(duration_ms, method="cache", success=True)
        return {
            "ok": True,
            "data": {**cached, "from_cache": True},
        }

    # 2. AI 识别（带超时）
    try:
        result = await asyncio.wait_for(
            _mock_transcribe_ai(audio_bytes, language),
            timeout=_TRANSCRIBE_TIMEOUT_SECS,
        )
        cache.put(audio_key, result)
        duration_ms = (time.perf_counter() - start) * 1000
        _record_metric(duration_ms, method="ai", success=True)
        return {
            "ok": True,
            "data": {**result, "from_cache": False},
        }

    except asyncio.TimeoutError:
        duration_ms = (time.perf_counter() - start) * 1000
        _record_metric(duration_ms, method="timeout", success=False)
        log.warning(
            "voice_transcribe_timeout",
            timeout_secs=_TRANSCRIBE_TIMEOUT_SECS,
            audio_hash=audio_key[:8],
        )
        return {
            "ok": True,
            "data": {
                "text": None,
                "degraded": True,
                "reason": "timeout",
                "from_cache": False,
            },
        }

    except ValueError as e:
        duration_ms = (time.perf_counter() - start) * 1000
        _record_metric(duration_ms, method="ai", success=False)
        log.error("voice_transcribe_value_error", error=str(e))
        raise HTTPException(
            status_code=400,
            detail={"code": "TRANSCRIBE_ERROR", "message": str(e)},
        )


@router.post("/parse-order")
async def parse_order(req: ParseOrderRequest) -> dict[str, Any]:
    """POST /api/v1/brain/voice/parse-order

    语音指令解析为购物车项目列表。
    """
    start = time.perf_counter()

    if not req.text.strip():
        raise HTTPException(
            status_code=400,
            detail={"code": "EMPTY_TEXT", "message": "语音文本不能为空"},
        )

    try:
        cart_items = _parse_text_to_cart(req.text)
    except (ValueError, AttributeError) as e:
        duration_ms = (time.perf_counter() - start) * 1000
        _record_metric(duration_ms, method="ai", success=False, endpoint="parse_order")
        log.error("parse_order_failed", error=str(e), text=req.text)
        raise HTTPException(
            status_code=422,
            detail={"code": "PARSE_FAILED", "message": str(e)},
        )

    duration_ms = (time.perf_counter() - start) * 1000
    _record_metric(duration_ms, method="ai", success=True, endpoint="parse_order")

    log.info(
        "voice_order_parsed",
        store_id=req.store_id,
        item_count=len(cart_items),
        duration_ms=round(duration_ms, 2),
    )

    return {
        "ok": True,
        "data": {
            "cart_items": cart_items,
            "raw_text": req.text,
            "item_count": len(cart_items),
        },
    }


@router.get("/metrics")
async def voice_metrics() -> dict[str, Any]:
    """GET /api/v1/brain/voice/metrics

    语音点餐错误率看板：
    - 总调用次数
    - 各 method（cache/ai/timeout）分布
    - 错误率
    - 平均耗时
    - 超时率
    """
    metrics_list = list(_call_metrics)
    total = len(metrics_list)

    if total == 0:
        return {
            "ok": True,
            "data": {
                "total_calls": 0,
                "error_rate": 0.0,
                "timeout_rate": 0.0,
                "avg_duration_ms": 0.0,
                "method_breakdown": {"cache": 0, "ai": 0, "timeout": 0},
            },
        }

    error_count = sum(1 for m in metrics_list if not m["success"])
    timeout_count = sum(1 for m in metrics_list if m["method"] == "timeout")
    avg_duration = sum(m["duration_ms"] for m in metrics_list) / total

    method_counts: dict[str, int] = {"cache": 0, "ai": 0, "timeout": 0}
    for m in metrics_list:
        method = m.get("method", "ai")
        method_counts[method] = method_counts.get(method, 0) + 1

    return {
        "ok": True,
        "data": {
            "total_calls": total,
            "error_rate": round(error_count / total, 4),
            "timeout_rate": round(timeout_count / total, 4),
            "avg_duration_ms": round(avg_duration, 2),
            "method_breakdown": method_counts,
            "recent_errors": [
                m for m in metrics_list[-20:] if not m["success"]
            ],
        },
    }


@router.post("/cache/warm")
async def warm_cache(req: WarmCacheRequest) -> dict[str, Any]:
    """POST /api/v1/brain/voice/cache/warm

    预热菜品名缓存：将菜品列表写入持久化 dish_map。
    """
    if not req.dish_catalog:
        raise HTTPException(
            status_code=400,
            detail={"code": "EMPTY_CATALOG", "message": "dish_catalog 不能为空"},
        )

    cache: VoiceCommandCache = get_voice_cache()

    try:
        warmed_count = cache.warm(req.dish_catalog)
    except (ValueError, KeyError, OSError) as e:
        log.error("cache_warm_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail={"code": "WARM_FAILED", "message": str(e)},
        )

    return {
        "ok": True,
        "data": {
            "warmed_count": warmed_count,
            "message": f"成功预热 {warmed_count} 个菜品",
        },
    }


@router.get("/cache/stats")
async def cache_stats() -> dict[str, Any]:
    """GET /api/v1/brain/voice/cache/stats

    缓存命中率统计。
    """
    cache: VoiceCommandCache = get_voice_cache()
    stats = cache.get_stats()
    return {
        "ok": True,
        "data": stats,
    }
