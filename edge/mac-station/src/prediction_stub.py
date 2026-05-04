"""
Phase 3-A/B1: 出餐时间预测 + 翻台时机预测 — Core ML Bridge 集成

本模块从纯 stub（硬编码字典）升级为调用 coreml-bridge (Swift, port 8100) 真实推理。
三层策略：
  1. 优先：coreml-bridge HTTP 推理（M4 Neural Engine，< 5ms）
  2. 降级：规则引擎（bridge 不可用或推理失败时）
  3. 兜底：硬编码常数（规则引擎也不可用时的最低保证）

路由注册方式（在 main.py 中添加）:
  from prediction_stub import router as prediction_stub_router
  app.include_router(prediction_stub_router)
"""

from __future__ import annotations

import asyncio
import os
import random
from calendar import day_name
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, status

logger = structlog.get_logger(__name__)

# ─── Edge API 认证 ───────────────────────────────────────────────────────────
# mac-station 运行在门店局域网，所有 /predict/* 和 /vision/* 端点需携带
# X-Edge-Token 进行简单认证（防止局域网内未授权设备调用 AI 推理接口）。
# 生产环境通过 EDGE_API_TOKEN 环境变量配置，开发环境默认跳过。
_EDGE_TOKEN: str | None = os.getenv("EDGE_API_TOKEN")


async def _verify_edge_token(
    x_edge_token: str | None = Header(None, alias="X-Edge-Token"),
) -> None:
    """验证边缘接口认证令牌。"""
    if _EDGE_TOKEN is None:
        # 未配置则不强制认证（向后兼容开发环境）
        return
    if not x_edge_token or x_edge_token != _EDGE_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing X-Edge-Token",
        )


router = APIRouter(
    prefix="/predict",
    tags=["prediction"],
    dependencies=[Depends(_verify_edge_token)],
)

# ─── 配置 ────────────────────────────────────────────────────────────────────

COREML_BRIDGE_URL = os.getenv("COREML_BRIDGE_URL", "http://localhost:8100")
BRIDGE_TIMEOUT = float(os.getenv("COREML_BRIDGE_TIMEOUT", "3.0"))  # 秒
BRIDGE_MAX_RETRIES = int(os.getenv("COREML_BRIDGE_MAX_RETRIES", "1"))

# ─── 兜底常数（bridge 和规则引擎都不可用时的最低保证） ──────────────────────

_DISH_BASE_SECONDS: dict[str, float] = {
    "default": 600.0,
    "mock_dish_1": 480.0,
    "mock_dish_2": 720.0,
    "noodle": 300.0,
    "stew": 900.0,
    "cold_dish": 120.0,
    "soup": 540.0,
    "rice": 180.0,
}

_TABLE_AVG_MINUTES: dict[int, float] = {
    2: 42.0,
    4: 52.0,
    6: 68.0,
    8: 82.0,
    12: 98.0,
}

# ─── 时段与星期辅助 ──────────────────────────────────────────────────────────

# 午市 11-13, 晚市 17-20 为高峰期
_PEAK_HOURS: set[int] = {11, 12, 13, 17, 18, 19, 20}

# 中文星期名 → 英文
_WEEKDAY_CN_TO_EN: dict[str, str] = {
    "Monday": "weekday", "Tuesday": "weekday", "Wednesday": "weekday",
    "Thursday": "weekday", "Friday": "weekday",
    "Saturday": "weekend", "Sunday": "weekend",
}


def _get_hour_and_day_type() -> tuple[int, str]:
    """获取当前小时和星期类型（weekday/weekend）"""
    now = datetime.now(tz=timezone.utc)
    # 使用 Asia/Shanghai 时区（UTC+8）
    hour = (now.hour + 8) % 24
    en_day = day_name[now.weekday()]
    day_type = _WEEKDAY_CN_TO_EN.get(en_day, "weekday")
    return hour, day_type


# ─── CoreML Bridge HTTP 客户端 ───────────────────────────────────────────────

class CoreMLBridgeClient:
    """与 coreml-bridge (Swift, port 8100) 通信的异步 HTTP 客户端。"""

    def __init__(self, base_url: str = COREML_BRIDGE_URL, timeout: float = BRIDGE_TIMEOUT) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._model_version: Optional[str] = None
        self._bridge_available: Optional[bool] = None
        self._last_health_check: float = 0.0

    async def health(self) -> dict:
        """GET /health → 检查 bridge 状态并缓存模型版本。"""
        try:
            async with httpx.AsyncClient(timeout=min(self.timeout, 2.0)) as client:
                resp = await client.get(f"{self.base_url}/health")
                if resp.status_code == 200:
                    data = resp.json()
                    self._bridge_available = True
                    self._model_version = data.get("version") or data.get("model_version", "unknown")
                    self._last_health_check = asyncio.get_event_loop().time()
                    logger.info("coreml_bridge_healthy", version=self._model_version)
                    return {"ok": True, **data}
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError, OSError):
            pass
        self._bridge_available = False
        return {"ok": False, "error": "bridge_unreachable"}

    async def predict_dish_time(
        self,
        dish_id: str,
        hour: int,
        day_type: str,
        queue_length: int,
    ) -> dict:
        """POST /predict/dish-time → 调用 Swift bridge 推理。

        Args:
            dish_id: 菜品 ID
            hour: 当前时段 0-23
            day_type: "weekday" | "weekend"
            queue_length: 当前后厨队列深度

        Returns:
            {"ok": bool, "predicted_seconds": int, "confidence": float, "model": str}
            失败时返回 {"ok": False, "error": str}
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/predict/dish-time",
                    json={
                        "dish_id": dish_id,
                        "hour": hour,
                        "day_type": day_type,
                        "queue_length": queue_length,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    self._bridge_available = True
                    return {"ok": True, **data}
                else:
                    error_detail = resp.text[:200]
                    logger.warning("coreml_bridge_dish_time_error", status=resp.status_code, detail=error_detail)
                    return {"ok": False, "error": f"bridge_returned_{resp.status_code}"}
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as e:
            self._bridge_available = False
            logger.warning("coreml_bridge_dish_time_unreachable", error=type(e).__name__)
            return {"ok": False, "error": type(e).__name__}
        except OSError as e:
            self._bridge_available = False
            logger.warning("coreml_bridge_dish_time_os_error", error=str(e))
            return {"ok": False, "error": "os_error"}

    @property
    def model_version(self) -> str:
        return self._model_version or "unknown"

    @property
    def is_available(self) -> bool:
        return self._bridge_available is True


# 全局单例
_bridge_client: Optional[CoreMLBridgeClient] = None


def _get_bridge() -> CoreMLBridgeClient:
    global _bridge_client
    if _bridge_client is None:
        _bridge_client = CoreMLBridgeClient()
    return _bridge_client


# ─── 规则引擎降级（dish_time） ──────────────────────────────────────────────


def _rule_fallback_dish_time(dish_id: str, queue_depth: int) -> dict:
    """规则引擎：基于菜品大类 + 队列深度 + 时段 的出餐时间估算。

    当 CoreML bridge 不可用时使用此降级路径。
    规则参数与 Swift ModelManager.predictDishTime() fallback 保持一致。
    """
    hour, day_type = _get_hour_and_day_type()

    # 查找菜品基础时间
    base = _DISH_BASE_SECONDS.get(dish_id, _DISH_BASE_SECONDS["default"])

    # 队列惩罚：每单队列加 15-25 秒
    queue_penalty = queue_depth * 20.0

    # 高峰加成
    peak_bonus = 60.0 if hour in _PEAK_HOURS else 0.0

    # 周末加成
    weekend_bonus = 30.0 if day_type == "weekend" else 0.0

    estimated = max(60.0, base + queue_penalty + peak_bonus + weekend_bonus)

    # 置信度与 Swift fallback 对齐
    confidence = 0.85 if queue_depth < 5 else 0.72

    return {
        "estimated_seconds": round(estimated, 1),
        "confidence": confidence,
        "model": "dish_time_v1_fallback",
        "source": "rule_fallback",
    }


# ─── 规则引擎降级（table_turn） ──────────────────────────────────────────────


def _rule_fallback_table_turn(seats: int, elapsed_minutes: int, table_no: str) -> dict:
    """规则引擎：基于座位数 + 已用餐时长的翻台剩余时间估算。

    无等价 Swift bridge 端点，此规则引擎为主路径。
    """
    # 找最近匹配座位数
    keys = sorted(_TABLE_AVG_MINUTES.keys())
    avg_minutes = _TABLE_AVG_MINUTES.get(seats)
    if avg_minutes is None:
        best = keys[0]
        for k in keys:
            if k <= seats:
                best = k
        avg_minutes = _TABLE_AVG_MINUTES[best]

    # 剩余时间 + 轻微噪声
    noise = random.uniform(-5.0, 5.0)
    remaining = max(0.0, avg_minutes - elapsed_minutes + noise)
    estimated_finish_minutes = max(0, round(remaining))

    # 置信度：已用餐时长占比越高 → 置信度越高
    ratio = elapsed_minutes / avg_minutes if avg_minutes > 0 else 0
    if ratio >= 0.8:
        confidence = "high"
    elif ratio >= 0.5:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "ok": True,
        "estimated_finish_minutes": estimated_finish_minutes,
        "confidence": confidence,
        "source": "rule_fallback",
    }


# ─── 路由 ────────────────────────────────────────────────────────────────────


@router.post("/dish-time")
async def predict_dish_time(data: dict) -> dict:
    """出餐时间预测 — CoreML Bridge 集成版。

    输入:
      dish_id: str       — 菜品 ID
      queue_depth: int   — 当前后厨队列深度

    返回:
      estimated_seconds: float
      confidence: float  (0-1)
      model: str         — 模型版本标识
      source: "coreml_bridge" | "rule_fallback" | "static_fallback"
    """
    dish_id = data.get("dish_id", "default")
    queue_depth = int(data.get("queue_depth", 0))

    hour, day_type = _get_hour_and_day_type()
    bridge = _get_bridge()

    # ── 策略 1: CoreML Bridge 推理 ──
    bridge_result = await bridge.predict_dish_time(
        dish_id=dish_id,
        hour=hour,
        day_type=day_type,
        queue_length=queue_depth,
    )

    if bridge_result.get("ok"):
        estimated_seconds = float(bridge_result.get("predicted_seconds", 0))
        confidence_val = float(bridge_result.get("confidence", 0.85))
        model_tag = bridge_result.get("model", bridge.model_version)

        logger.info(
            "dish_time_coreml",
            dish_id=dish_id,
            queue_depth=queue_depth,
            hour=hour,
            day_type=day_type,
            estimated_seconds=round(estimated_seconds, 1),
            model=model_tag,
        )

        return {
            "ok": True,
            "estimated_seconds": round(estimated_seconds, 1),
            "confidence": confidence_val,
            "model": model_tag,
            "source": "coreml_bridge",
        }

    # ── 策略 2: 规则引擎降级 ──
    logger.info(
        "dish_time_fallback",
        dish_id=dish_id,
        queue_depth=queue_depth,
        bridge_error=bridge_result.get("error", "unknown"),
    )

    try:
        rule_result = _rule_fallback_dish_time(dish_id, queue_depth)
        return {
            **rule_result,
            "ok": True,
            "source": "rule_fallback",
        }
    except (ValueError, TypeError, KeyError) as exc:
        logger.error("rule_fallback_dish_time_failed", error=str(exc), exc_info=True)

    # ── 策略 3: 兜底常数 ──
    base = _DISH_BASE_SECONDS.get(dish_id, _DISH_BASE_SECONDS["default"])
    return {
        "ok": True,
        "estimated_seconds": base,
        "confidence": "low",
        "model": "static_fallback",
        "source": "static_fallback",
    }


@router.post("/table-turn")
async def predict_table_turn(data: dict) -> dict:
    """翻台剩余时间预测。

    输入:
      table_no: str        — 桌台号
      seats: int           — 座位数
      elapsed_minutes: int — 已用餐时长（分钟）

    返回:
      estimated_finish_minutes: int
      confidence: "high" | "medium" | "low"
      source: "rule_fallback" | "static_fallback"

    注意：coreml-bridge 暂无 /predict/table-turn 端点（时序模型训练中）。
    当前使用规则引擎作为主路径，待时序模型就绪后升级。
    """
    seats = int(data.get("seats", 4))
    elapsed_minutes = int(data.get("elapsed_minutes", 0))
    table_no = str(data.get("table_no", ""))

    logger.info(
        "table_turn_predict",
        table_no=table_no,
        seats=seats,
        elapsed_minutes=elapsed_minutes,
    )

    # 规则引擎推理
    try:
        result = _rule_fallback_table_turn(seats, elapsed_minutes, table_no)
        return result
    except (ValueError, TypeError, KeyError) as exc:
        logger.error("rule_fallback_table_turn_failed", error=str(exc), exc_info=True)

    # 兜底
    avg_minutes = float(_TABLE_AVG_MINUTES.get(seats, 60.0))
    remaining = max(0, round(avg_minutes - elapsed_minutes))

    return {
        "ok": True,
        "estimated_finish_minutes": remaining,
        "confidence": "low",
        "source": "static_fallback",
    }


@router.get("/health")
async def prediction_health() -> dict:
    """Prediction 服务健康检查 — 含 CoreML bridge 状态与模型版本信息。"""
    bridge = _get_bridge()
    bridge_status = await bridge.health()

    return {
        "ok": True,
        "data": {
            "service": "prediction",
            "mode": "coreml_bridge_integrated",
            "bridge_url": COREML_BRIDGE_URL,
            "bridge_available": bridge.is_available,
            "bridge_model_version": bridge.model_version,
            "bridge_health": bridge_status,
        },
    }
