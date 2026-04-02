"""归因钩子 — tx-trade 向 tx-growth 发布归因事件

当订单结算完成或预订确认时，通过此模块异步触发 tx-growth 的归因检查接口。

集成方式：HTTP（优先）+ Redis Stream（降级/异步）
  - 优先：直接 POST 到 tx-growth /api/v1/growth/attribution/attribute-conversion
  - 降级：写入 Redis Stream "attribution_events"，由 tx-growth worker 消费

调用点：
  - OrderService.settle_order() 完成后
  - ReservationService.confirm_reservation() 完成后

不阻断主业务流程：所有调用均 fire-and-forget（create_task），异常只记日志。
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

# tx-growth 服务地址（通过环境变量注入，Mac mini 本地时使用 localhost:8003）
_GROWTH_SERVICE_URL = os.getenv(
    "TX_GROWTH_SERVICE_URL", "http://localhost:8003"
)
_ATTRIBUTION_ENDPOINT = f"{_GROWTH_SERVICE_URL}/api/v1/growth/attribution/attribute-conversion"

# Redis Stream（降级用）
_ATTRIBUTION_STREAM = "attribution_events"


async def _post_attribution(
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
    conversion_type: str,
    conversion_id: uuid.UUID,
    conversion_value: float,
    converted_at: datetime,
    attribution_window_hours: int = 72,
) -> None:
    """向 tx-growth 发送归因检查请求（内部实现，fire-and-forget）。

    先尝试 HTTP 调用，失败后写入 Redis Stream 降级。
    """
    payload = {
        "customer_id": str(customer_id),
        "conversion_type": conversion_type,
        "conversion_id": str(conversion_id),
        "conversion_value": conversion_value,
        "converted_at": converted_at.isoformat(),
        "attribution_window_hours": attribution_window_hours,
        "model": "last_touch",
    }
    headers = {"X-Tenant-ID": str(tenant_id), "Content-Type": "application/json"}

    try:
        import httpx  # type: ignore
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(_ATTRIBUTION_ENDPOINT, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                log.info(
                    "attribution_hook_success",
                    conversion_type=conversion_type,
                    conversion_id=str(conversion_id),
                    attributed=data.get("data", {}).get("attributed", False),
                    tenant_id=str(tenant_id),
                )
                return
            log.warning(
                "attribution_hook_http_error",
                status=resp.status_code,
                conversion_id=str(conversion_id),
            )
    except ImportError:
        log.warning("httpx_not_installed_falling_back_to_redis")
    except Exception as exc:  # noqa: BLE001 — fire-and-forget 最外层兜底
        log.warning(
            "attribution_hook_http_failed",
            error=str(exc),
            conversion_id=str(conversion_id),
            exc_info=True,
        )

    # 降级：写入 Redis Stream
    await _fallback_redis_stream(
        tenant_id=tenant_id,
        payload={**payload, "tenant_id": str(tenant_id)},
        conversion_id=str(conversion_id),
    )


async def _fallback_redis_stream(
    tenant_id: uuid.UUID,
    payload: dict,
    conversion_id: str,
) -> None:
    """Redis Stream 降级：写入 attribution_events stream。"""
    try:
        import json

        import redis.asyncio as aioredis  # type: ignore
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = aioredis.from_url(redis_url, decode_responses=True, socket_connect_timeout=1)
        await r.xadd(
            _ATTRIBUTION_STREAM,
            {"payload": json.dumps(payload, ensure_ascii=False)},
        )
        await r.aclose()
        log.info(
            "attribution_event_queued_redis",
            conversion_id=conversion_id,
            tenant_id=str(tenant_id),
        )
    except Exception as exc:  # noqa: BLE001
        log.error(
            "attribution_fallback_redis_failed",
            error=str(exc),
            conversion_id=conversion_id,
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# 公开 API — 在业务代码中调用这两个函数
# ---------------------------------------------------------------------------


def fire_order_attribution(
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
    order_id: uuid.UUID,
    order_amount_yuan: float,
    completed_at: Optional[datetime] = None,
) -> None:
    """触发订单归因（fire-and-forget）。

    在 OrderService.settle_order() 完成后调用：
        attribution_hook.fire_order_attribution(
            tenant_id=self.tenant_id,
            customer_id=order.customer_id,
            order_id=order.id,
            order_amount_yuan=order.final_amount_fen / 100,
        )

    Args:
        tenant_id:          租户 UUID
        customer_id:        客户 UUID
        order_id:           订单 UUID
        order_amount_yuan:  订单金额（元）
        completed_at:       完成时间（默认 now()）
    """
    now = completed_at or datetime.now(timezone.utc)
    asyncio.create_task(
        _post_attribution(
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversion_type="order",
            conversion_id=order_id,
            conversion_value=order_amount_yuan,
            converted_at=now,
        )
    )
    log.debug(
        "attribution_task_created",
        conversion_type="order",
        order_id=str(order_id),
        tenant_id=str(tenant_id),
    )


def fire_reservation_attribution(
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
    reservation_id: uuid.UUID,
    deposit_yuan: float = 0.0,
    confirmed_at: Optional[datetime] = None,
) -> None:
    """触发预订确认归因（fire-and-forget）。

    在 ReservationService.confirm_reservation() 完成后调用：
        attribution_hook.fire_reservation_attribution(
            tenant_id=uuid.UUID(tenant_id_str),
            customer_id=uuid.UUID(record.customer_id),
            reservation_id=uuid.UUID(reservation_id),
            deposit_yuan=record.deposit_fen / 100 if record.deposit_fen else 0.0,
        )

    Args:
        tenant_id:       租户 UUID
        customer_id:     客户 UUID
        reservation_id:  预订 UUID
        deposit_yuan:    订金金额（元，无订金传 0.0）
        confirmed_at:    确认时间（默认 now()）
    """
    now = confirmed_at or datetime.now(timezone.utc)
    asyncio.create_task(
        _post_attribution(
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversion_type="reservation",
            conversion_id=reservation_id,
            conversion_value=deposit_yuan,
            converted_at=now,
        )
    )
    log.debug(
        "attribution_task_created",
        conversion_type="reservation",
        reservation_id=str(reservation_id),
        tenant_id=str(tenant_id),
    )
