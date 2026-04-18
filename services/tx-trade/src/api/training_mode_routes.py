"""演示/训练模式 API — training_mode_routes.py

演示模式让销售人员或店长在真实POS设备上演示操作流程，
所有操作产生的订单、会员、流水均标记 demo=True，不影响真实数据。

状态存 Redis，Key: tx:training:{store_id}:mode  TTL=duration_minutes*60
演示订单索引：tx:training:{store_id}:orders（Set，member=order_id）

端点：
  GET  /api/v1/training-mode/status/{store_id}
  POST /api/v1/training-mode/enable/{store_id}
  POST /api/v1/training-mode/disable/{store_id}
  POST /api/v1/training-mode/reset/{store_id}
  GET  /api/v1/training-mode/demo-orders/{store_id}

编码规范：FastAPI + Pydantic V2 + async/await，统一响应 {ok, data, error}
"""
import json
import os
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/training-mode", tags=["training-mode"])

# ─── Redis Key 常量 ──────────────────────────────────────────────────────────

_KEY_MODE = "tx:training:{store_id}:mode"         # Hash：模式状态
_KEY_ORDERS = "tx:training:{store_id}:orders"     # Set ：演示订单ID集合


# ─── Pydantic 模型 ───────────────────────────────────────────────────────────

class TrainingStatusResponse(BaseModel):
    is_demo_mode: bool
    demo_tenant_id: str
    watermark_text: str
    auto_reset_minutes: int
    enabled_at: Optional[str] = None
    enabled_by: Optional[str] = None


class EnableTrainingModeRequest(BaseModel):
    duration_minutes: int = Field(default=60, ge=5, le=480)
    watermark_text: str = Field(default="演示模式", max_length=20)
    operator_id: Optional[str] = None


class TrainingModeActionResponse(BaseModel):
    success: bool
    message: str


class DemoOrdersResponse(BaseModel):
    store_id: str
    demo_order_ids: list[str]
    total_count: int


# ─── Redis 工具 ──────────────────────────────────────────────────────────────

def _mode_key(store_id: str) -> str:
    return _KEY_MODE.format(store_id=store_id)


def _orders_key(store_id: str) -> str:
    return _KEY_ORDERS.format(store_id=store_id)


async def _get_redis():
    """获取 Redis 异步客户端（懒导入，不可用时抛 RuntimeError）"""
    try:
        import redis.asyncio as aioredis  # type: ignore
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        return aioredis.from_url(redis_url, decode_responses=True)
    except ImportError as exc:
        raise RuntimeError("redis[asyncio] 包未安装，演示模式需要 Redis 支持") from exc


async def _get_mode_state(store_id: str) -> dict | None:
    """从 Redis 读取演示模式状态，不存在或过期返回 None"""
    try:
        client = await _get_redis()
        async with client as redis:
            raw = await redis.get(_mode_key(store_id))
            if raw:
                return json.loads(raw)
            return None
    except (ConnectionError, OSError) as exc:
        logger.warning("training_mode_redis_read_failed", store_id=store_id, error=str(exc))
        return None


# ─── 端点 ─────────────────────────────────────────────────────────────────────

@router.get("/status/{store_id}", response_model=dict)
async def get_training_mode_status(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取演示模式当前状态。

    返回 is_demo_mode=false 时其余字段为空默认值，前端只需判断此字段。
    """
    state = await _get_mode_state(store_id)
    if state is None:
        data = TrainingStatusResponse(
            is_demo_mode=False,
            demo_tenant_id=x_tenant_id,
            watermark_text="演示模式",
            auto_reset_minutes=60,
        )
    else:
        data = TrainingStatusResponse(
            is_demo_mode=True,
            demo_tenant_id=x_tenant_id,
            watermark_text=state.get("watermark_text", "演示模式"),
            auto_reset_minutes=state.get("duration_minutes", 60),
            enabled_at=state.get("enabled_at"),
            enabled_by=state.get("enabled_by"),
        )

    logger.info(
        "training_mode_status_queried",
        store_id=store_id,
        is_demo_mode=data.is_demo_mode,
    )
    return {"ok": True, "data": data.model_dump(), "error": None}


@router.post("/enable/{store_id}", response_model=dict)
async def enable_training_mode(
    store_id: str,
    body: EnableTrainingModeRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """启用演示模式。

    - 状态写入 Redis，TTL = duration_minutes * 60 秒
    - 后续收银创建的订单应检查此标志并设置 demo=True
    - 演示模式激活期间可重复调用以刷新 TTL 或更新水印文字
    """
    try:
        client = await _get_redis()
        async with client as redis:
            state = {
                "store_id": store_id,
                "tenant_id": x_tenant_id,
                "duration_minutes": body.duration_minutes,
                "watermark_text": body.watermark_text,
                "enabled_at": datetime.now(timezone.utc).isoformat(),
                "enabled_by": body.operator_id or "unknown",
            }
            ttl = body.duration_minutes * 60
            await redis.set(_mode_key(store_id), json.dumps(state, ensure_ascii=False), ex=ttl)

        logger.info(
            "training_mode_enabled",
            store_id=store_id,
            duration_minutes=body.duration_minutes,
            operator_id=body.operator_id,
        )
        return {
            "ok": True,
            "data": {
                "success": True,
                "message": f"演示模式已启用，将在 {body.duration_minutes} 分钟后自动关闭",
                "duration_minutes": body.duration_minutes,
                "watermark_text": body.watermark_text,
            },
            "error": None,
        }
    except (ConnectionError, OSError) as exc:
        logger.error("training_mode_enable_failed", store_id=store_id, error=str(exc))
        raise HTTPException(status_code=503, detail="Redis 连接失败，无法启用演示模式") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/disable/{store_id}", response_model=dict)
async def disable_training_mode(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """关闭演示模式（立即删除 Redis Key，不等待 TTL 过期）。"""
    try:
        client = await _get_redis()
        async with client as redis:
            deleted = await redis.delete(_mode_key(store_id))

        was_active = deleted > 0
        logger.info(
            "training_mode_disabled",
            store_id=store_id,
            was_active=was_active,
        )
        return {
            "ok": True,
            "data": {
                "success": True,
                "message": "演示模式已关闭" if was_active else "演示模式本来就未启用",
            },
            "error": None,
        }
    except (ConnectionError, OSError) as exc:
        logger.error("training_mode_disable_failed", store_id=store_id, error=str(exc))
        raise HTTPException(status_code=503, detail="Redis 连接失败，无法关闭演示模式") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/reset/{store_id}", response_model=dict)
async def reset_training_data(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """清理本轮演示产生的所有 demo=True 数据。

    当前实现：
    1. 清除 Redis 中记录的演示订单 ID 集合
    2. 关闭演示模式（删除 mode Key）
    3. 真实数据库侧的清理应通过定时任务或后台任务处理
       （标记 demo=True 的订单可由数据库侧安全物理删除）

    注意：此操作不可逆，清理前请确认。
    """
    try:
        client = await _get_redis()
        async with client as redis:
            # 先获取演示订单数量（用于响应）
            order_count = await redis.scard(_orders_key(store_id))
            # 批量删除相关 Keys
            await redis.delete(_mode_key(store_id), _orders_key(store_id))

        logger.info(
            "training_mode_reset",
            store_id=store_id,
            cleared_order_ids=order_count,
        )
        return {
            "ok": True,
            "data": {
                "success": True,
                "message": f"演示数据已清除（共 {order_count} 条演示订单索引）",
                "cleared_order_count": order_count,
            },
            "error": None,
        }
    except (ConnectionError, OSError) as exc:
        logger.error("training_mode_reset_failed", store_id=store_id, error=str(exc))
        raise HTTPException(status_code=503, detail="Redis 连接失败，无法清理演示数据") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/demo-orders/{store_id}", response_model=dict)
async def get_demo_orders(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """获取当前演示会话产生的所有演示订单 ID 列表。

    演示收银成功时，应调用 /api/v1/training-mode/register-order/{store_id} 将
    order_id 写入此集合（由收银引擎 cashier_engine.py 在 demo 模式下调用）。

    供演示结束时前端展示演示订单汇总，或批量清除使用。
    """
    try:
        client = await _get_redis()
        async with client as redis:
            order_ids = await redis.smembers(_orders_key(store_id))

        demo_order_ids = sorted(order_ids)  # 排序保持一致性
        data = DemoOrdersResponse(
            store_id=store_id,
            demo_order_ids=demo_order_ids,
            total_count=len(demo_order_ids),
        )
        return {"ok": True, "data": data.model_dump(), "error": None}
    except (ConnectionError, OSError) as exc:
        logger.warning("training_mode_orders_read_failed", store_id=store_id, error=str(exc))
        # 降级：返回空列表，不中断前端流程
        return {
            "ok": True,
            "data": {"store_id": store_id, "demo_order_ids": [], "total_count": 0},
            "error": None,
        }
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# ─── 内部调用端点（供 cashier_engine.py 使用）────────────────────────────────

@router.post("/register-order/{store_id}", response_model=dict, include_in_schema=False)
async def register_demo_order(
    store_id: str,
    order_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """（内部端点）收银引擎在演示模式下创建订单后调用，将 order_id 记录到演示集合。

    TTL 与 mode Key 保持一致：演示结束后集合自动过期。
    此端点不暴露在 OpenAPI 文档中（include_in_schema=False）。
    """
    try:
        client = await _get_redis()
        async with client as redis:
            # 获取 mode Key 的剩余 TTL，同步设置 orders Key TTL
            ttl = await redis.ttl(_mode_key(store_id))
            await redis.sadd(_orders_key(store_id), order_id)
            if ttl > 0:
                await redis.expire(_orders_key(store_id), ttl)

        logger.debug("demo_order_registered", store_id=store_id, order_id=order_id)
        return {"ok": True, "data": {"registered": True}, "error": None}
    except (ConnectionError, OSError) as exc:
        # 仅记录日志，不影响收银主流程
        logger.warning("demo_order_register_failed", store_id=store_id, order_id=order_id, error=str(exc))
        return {"ok": True, "data": {"registered": False}, "error": None}
    except RuntimeError as exc:
        return {"ok": False, "data": None, "error": {"message": str(exc)}}
