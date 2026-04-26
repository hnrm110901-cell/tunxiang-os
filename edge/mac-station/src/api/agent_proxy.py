"""Agent 本地代理 — Core ML 推理 + 折扣守护 + 降级策略

端点：
  POST /api/v1/agent/predict         代理到 coreml-bridge:8100
  POST /api/v1/agent/discount-check  折扣守护（本地推理优先，超时转云端）

降级策略：
  coreml-bridge 不可用时用简单规则引擎兜底。
"""
from __future__ import annotations

import time
from typing import Any

import httpx
import structlog
from config import get_config
from fastapi import APIRouter

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/agent", tags=["agent-proxy"])

# ── Core ML 代理超时（秒） ──
_COREML_TIMEOUT_S = 5
# ── 云端 Agent 超时 ──
_CLOUD_TIMEOUT_S = 10


# ── 规则引擎降级 ──


def _rule_engine_predict(model_name: str, data: dict[str, Any]) -> dict[str, Any]:
    """简单规则引擎兜底预测。

    当 coreml-bridge 不可用且云端也不可达时，使用硬编码规则。

    Args:
        model_name: 模型名称（如 "dish-time", "discount-risk", "traffic"）
        data: 输入数据

    Returns:
        预测结果字典
    """
    if model_name == "dish-time":
        queue_depth = int(data.get("queue_depth", 0))
        base_seconds = 600.0
        estimated = base_seconds + queue_depth * 20.0
        return {
            "ok": True,
            "data": {
                "estimated_seconds": round(estimated, 1),
                "confidence": "low",
                "source": "rule_engine",
            },
        }

    if model_name == "discount-risk":
        discount_rate = float(data.get("discount_rate", 0))
        threshold = float(data.get("threshold", 0.5))
        risk_score = min(1.0, discount_rate / threshold) if threshold > 0 else 0.0
        risk_level = "low"
        if risk_score > 0.8:
            risk_level = "critical"
        elif risk_score > 0.6:
            risk_level = "high"
        elif risk_score > 0.4:
            risk_level = "medium"
        return {
            "ok": True,
            "data": {
                "risk_score": round(risk_score, 3),
                "risk_level": risk_level,
                "source": "rule_engine",
            },
        }

    if model_name == "traffic":
        hour = int(data.get("hour", 12))
        # 简单峰值模型：11-13点、17-20点为高峰
        if 11 <= hour <= 13 or 17 <= hour <= 20:
            predicted_count = 45
            level = "high"
        elif 14 <= hour <= 16:
            predicted_count = 15
            level = "low"
        else:
            predicted_count = 25
            level = "medium"
        return {
            "ok": True,
            "data": {
                "predicted_count": predicted_count,
                "density_level": level,
                "source": "rule_engine",
            },
        }

    return {
        "ok": True,
        "data": {
            "result": "no_rule_available",
            "source": "rule_engine",
            "model_name": model_name,
        },
    }


# ── 折扣守护规则引擎 ──


def _discount_check_rule_engine(data: dict[str, Any]) -> dict[str, Any]:
    """折扣守护规则引擎 — 不依赖 ML 的硬规则检查。

    规则：
    1. 折扣率超过阈值 → 标记 high/critical
    2. 单笔折扣金额超过 5000 分(50元) → 自动升级 risk_level
    3. 同一员工短时间内多次折扣 → 标记可疑（需外部状态，此处简化）
    """
    discount_rate = float(data.get("discount_rate", 0))
    threshold = float(data.get("threshold", 0.5))
    amount_fen = int(data.get("amount_fen", 0))
    employee_id = data.get("employee_id", "")

    risk_score = 0.0
    reasons: list[str] = []

    # 规则1: 折扣率检查
    if threshold > 0 and discount_rate > threshold:
        excess = (discount_rate - threshold) / threshold
        risk_score += min(0.5, excess)
        reasons.append(f"折扣率 {discount_rate:.1%} 超过阈值 {threshold:.1%}")

    # 规则2: 大额折扣
    if amount_fen > 5000:
        risk_score += 0.3
        reasons.append(f"折扣金额 {amount_fen/100:.2f}元 超过50元上限")

    # 规则3: 折扣率本身过高
    if discount_rate > 0.7:
        risk_score += 0.2
        reasons.append(f"折扣率 {discount_rate:.1%} 异常偏高（>70%）")

    risk_score = min(1.0, risk_score)

    if risk_score >= 0.7:
        risk_level = "critical"
        action = "block_and_alert"
    elif risk_score >= 0.4:
        risk_level = "high"
        action = "alert_manager"
    elif risk_score >= 0.2:
        risk_level = "medium"
        action = "log_only"
    else:
        risk_level = "low"
        action = "pass"

    return {
        "risk_score": round(risk_score, 3),
        "risk_level": risk_level,
        "action": action,
        "reasons": reasons,
        "source": "rule_engine",
    }


# ── 端点 ──


@router.post("/predict", summary="Core ML 代理推理")
async def agent_predict(data: dict[str, Any]) -> dict[str, Any]:
    """代理推理请求到 coreml-bridge。

    降级链：coreml-bridge → 云端 Agent → 本地规则引擎。

    请求体:
        model_name: str — 模型名称（dish-time / discount-risk / traffic）
        其余字段透传给模型
    """
    cfg = get_config()
    model_name = data.pop("model_name", "default")
    start = time.monotonic()

    # 第一优先：coreml-bridge 本地推理
    try:
        async with httpx.AsyncClient(timeout=_COREML_TIMEOUT_S) as client:
            resp = await client.post(
                f"{cfg.coreml_bridge_url}/predict/{model_name}",
                json=data,
            )
            if resp.status_code == 200:
                result = resp.json()
                elapsed_ms = int((time.monotonic() - start) * 1000)
                logger.info(
                    "agent_predict_coreml_ok",
                    model=model_name,
                    elapsed_ms=elapsed_ms,
                )
                return {
                    "ok": True,
                    "data": {
                        **result,
                        "source": "coreml",
                        "elapsed_ms": elapsed_ms,
                    },
                }
    except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError, OSError) as exc:
        logger.warning("agent_predict_coreml_unavailable", model=model_name, error=str(exc))

    # 第二优先：云端 Agent（如果在线）
    if not cfg.offline:
        try:
            async with httpx.AsyncClient(timeout=_CLOUD_TIMEOUT_S) as client:
                resp = await client.post(
                    f"{cfg.cloud_api_url}/api/v1/agent/predict",
                    json={"model_name": model_name, **data},
                    headers={
                        "X-Tenant-ID": cfg.tenant_id,
                        "X-Store-ID": cfg.store_id,
                    },
                )
                if resp.status_code == 200:
                    result = resp.json()
                    elapsed_ms = int((time.monotonic() - start) * 1000)
                    logger.info(
                        "agent_predict_cloud_ok",
                        model=model_name,
                        elapsed_ms=elapsed_ms,
                    )
                    return {
                        "ok": True,
                        "data": {
                            **result.get("data", result),
                            "source": "cloud",
                            "elapsed_ms": elapsed_ms,
                        },
                    }
        except (httpx.ConnectError, httpx.TimeoutException, OSError) as exc:
            logger.warning("agent_predict_cloud_unavailable", model=model_name, error=str(exc))

    # 第三优先：本地规则引擎
    result = _rule_engine_predict(model_name, data)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    if result.get("data"):
        result["data"]["elapsed_ms"] = elapsed_ms

    logger.info(
        "agent_predict_rule_engine_fallback",
        model=model_name,
        elapsed_ms=elapsed_ms,
    )
    return result


@router.post("/discount-check", summary="折扣守护检查")
async def discount_check(data: dict[str, Any]) -> dict[str, Any]:
    """折扣守护 — 检测折扣操作是否异常。

    降级链：coreml-bridge(discount-risk模型) → 云端折扣守护Agent → 本地规则引擎。

    请求体:
        order_id: str        — 订单 ID
        employee_id: str     — 操作员 ID
        discount_rate: float — 实际折扣率 0.0-1.0
        threshold: float     — 允许的最大折扣率
        amount_fen: int      — 折扣金额（分）
        items: list          — 订单项（可选，供模型分析）
    """
    cfg = get_config()
    start = time.monotonic()

    order_id = data.get("order_id", "")
    employee_id = data.get("employee_id", "")

    # 第一优先：coreml-bridge 本地推理
    try:
        async with httpx.AsyncClient(timeout=_COREML_TIMEOUT_S) as client:
            resp = await client.post(
                f"{cfg.coreml_bridge_url}/predict/discount-risk",
                json=data,
            )
            if resp.status_code == 200:
                result = resp.json()
                elapsed_ms = int((time.monotonic() - start) * 1000)
                logger.info(
                    "discount_check_coreml_ok",
                    order_id=order_id,
                    risk_level=result.get("risk_level"),
                    elapsed_ms=elapsed_ms,
                )
                return {
                    "ok": True,
                    "data": {
                        **result,
                        "source": "coreml",
                        "elapsed_ms": elapsed_ms,
                        "order_id": order_id,
                        "employee_id": employee_id,
                    },
                }
    except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError, OSError) as exc:
        logger.warning("discount_check_coreml_unavailable", error=str(exc))

    # 第二优先：云端折扣守护 Agent
    if not cfg.offline:
        try:
            async with httpx.AsyncClient(timeout=_CLOUD_TIMEOUT_S) as client:
                resp = await client.post(
                    f"{cfg.cloud_api_url}/api/v1/agent/discount-guard/check",
                    json=data,
                    headers={
                        "X-Tenant-ID": cfg.tenant_id,
                        "X-Store-ID": cfg.store_id,
                    },
                )
                if resp.status_code == 200:
                    result = resp.json()
                    elapsed_ms = int((time.monotonic() - start) * 1000)
                    logger.info(
                        "discount_check_cloud_ok",
                        order_id=order_id,
                        elapsed_ms=elapsed_ms,
                    )
                    return {
                        "ok": True,
                        "data": {
                            **result.get("data", result),
                            "source": "cloud",
                            "elapsed_ms": elapsed_ms,
                            "order_id": order_id,
                            "employee_id": employee_id,
                        },
                    }
        except (httpx.ConnectError, httpx.TimeoutException, OSError) as exc:
            logger.warning("discount_check_cloud_unavailable", error=str(exc))

    # 第三优先：本地规则引擎
    result = _discount_check_rule_engine(data)
    elapsed_ms = int((time.monotonic() - start) * 1000)

    logger.info(
        "discount_check_rule_engine",
        order_id=order_id,
        employee_id=employee_id,
        risk_level=result["risk_level"],
        risk_score=result["risk_score"],
        elapsed_ms=elapsed_ms,
    )

    return {
        "ok": True,
        "data": {
            **result,
            "elapsed_ms": elapsed_ms,
            "order_id": order_id,
            "employee_id": employee_id,
        },
    }
