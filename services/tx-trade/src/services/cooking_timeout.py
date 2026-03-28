"""出餐超时预警 — 监控出品时效，触发预警和 Agent 联动

三级预警机制：
- normal: 正常出品中
- warning: 接近超时阈值 -> WebSocket 推送标红到 KDS 前端
- critical: 已超时(2x阈值) -> 推送告警到管理员手机 + 触发 serve_dispatch Agent
"""
import os
import uuid
from datetime import datetime, timezone

import httpx
import structlog
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Order, OrderItem

logger = structlog.get_logger()

# Mac mini 推送地址
MAC_STATION_URL = os.getenv("MAC_STATION_URL", "http://localhost:8000")

# ─── 默认超时配置（分钟） ───

DEFAULT_NORMAL_MINUTES = 15
DEFAULT_WARNING_MINUTES = 20
DEFAULT_CRITICAL_MINUTES = 30

# ─── 内存中的超时配置（后续迁移到 store_configs 表） ───
_timeout_configs: dict[str, dict] = {}


def _get_timeout_config(store_id: str) -> dict:
    """获取门店超时配置"""
    if store_id not in _timeout_configs:
        _timeout_configs[store_id] = {
            "normal_minutes": DEFAULT_NORMAL_MINUTES,
            "warning_minutes": DEFAULT_WARNING_MINUTES,
            "critical_minutes": DEFAULT_CRITICAL_MINUTES,
        }
    return _timeout_configs[store_id]


def _classify_timeout_status(wait_minutes: float, config: dict) -> str:
    """根据等待时间和配置判定超时级别"""
    if wait_minutes >= config["critical_minutes"]:
        return "critical"
    elif wait_minutes >= config["warning_minutes"]:
        return "warning"
    return "normal"


async def _push_timeout_to_kds(station_id: str, timeout_entry: dict) -> bool:
    """通过 WebSocket 推送超时状态变更到 KDS 前端。

    warning 级别: 前端标红显示
    critical 级别: 前端标红 + 闪烁 + 声音告警
    """
    log = logger.bind(station_id=station_id, status=timeout_entry["status"])
    message = {
        "type": "timeout_alert",
        "station_id": station_id,
        "payload": {
            "order_item_id": timeout_entry["order_item_id"],
            "order_no": timeout_entry["order_no"],
            "table_number": timeout_entry["table_number"],
            "dish": timeout_entry["dish"],
            "wait_minutes": timeout_entry["wait_minutes"],
            "status": timeout_entry["status"],
            "alert": True,
            "sound": "timeout_critical" if timeout_entry["status"] == "critical" else "timeout_warning",
            "highlight": "red",
            "blink": timeout_entry["status"] == "critical",
        },
    }
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.post(
                f"{MAC_STATION_URL}/api/v1/kds/push",
                json={"station_id": station_id, "message": message},
            )
            if resp.status_code == 200:
                log.info("cooking_timeout.ws_push.ok")
                return True
            log.warning("cooking_timeout.ws_push.failed", status=resp.status_code)
            return False
    except httpx.ConnectError:
        log.warning("cooking_timeout.ws_push.mac_station_unavailable")
        return False
    except httpx.TimeoutException:
        log.warning("cooking_timeout.ws_push.timeout")
        return False


async def _push_admin_alert(
    store_id: str,
    tenant_id: str,
    critical_items: list[dict],
) -> None:
    """超过时限2倍的菜品，推送告警到管理员手机。

    通过 Mac mini 转发到云端推送服务（企微/钉钉/短信等）。
    """
    log = logger.bind(store_id=store_id, critical_count=len(critical_items))

    alert_payload = {
        "type": "admin_timeout_alert",
        "severity": "critical",
        "store_id": store_id,
        "tenant_id": tenant_id,
        "title": f"出品超时告警: {len(critical_items)}道菜严重超时",
        "items": [
            {
                "dish": item["dish"],
                "table_number": item["table_number"],
                "wait_minutes": item["wait_minutes"],
                "order_no": item["order_no"],
            }
            for item in critical_items
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                f"{MAC_STATION_URL}/api/v1/admin/alert",
                json=alert_payload,
            )
            if resp.status_code == 200:
                log.info("cooking_timeout.admin_alert.sent")
            else:
                log.warning("cooking_timeout.admin_alert.failed", status=resp.status_code)
    except httpx.ConnectError:
        log.warning("cooking_timeout.admin_alert.mac_station_unavailable")
    except httpx.TimeoutException:
        log.warning("cooking_timeout.admin_alert.timeout")


async def check_timeouts(
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> list[dict]:
    """检查门店所有待出品任务的超时情况。

    对超时任务自动：
    1. warning 级别: WebSocket 推送标红到 KDS 前端
    2. critical 级别(2x阈值): WebSocket 推送 + 推送告警到管理员手机

    Returns:
        [{"task_id": ..., "dish": ..., "wait_minutes": ..., "threshold": ..., "status": ...}]
    """
    tid = uuid.UUID(tenant_id)
    log = logger.bind(store_id=store_id, tenant_id=tenant_id)
    now = datetime.now(timezone.utc)
    config = _get_timeout_config(store_id)

    # 查询该门店所有待出品的订单项
    stmt = (
        select(OrderItem, Order.order_no, Order.table_number)
        .join(Order, OrderItem.order_id == Order.id)
        .where(
            and_(
                Order.tenant_id == tid,
                Order.store_id == uuid.UUID(store_id),
                OrderItem.sent_to_kds_flag == True,  # noqa: E712
                Order.is_deleted == False,  # noqa: E712
            )
        )
        .order_by(OrderItem.created_at.asc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    timeout_items = []
    critical_items = []

    for item, order_no, table_no in rows:
        if not item.created_at:
            continue

        created_at = item.created_at
        # 确保 created_at 带时区信息，避免与 tz-aware now 相减时 TypeError
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        wait_seconds = (now - created_at).total_seconds()
        wait_minutes = round(wait_seconds / 60, 1)
        status = _classify_timeout_status(wait_minutes, config)

        if status in ("warning", "critical"):
            timeout_entry = {
                "order_item_id": str(item.id),
                "order_id": str(item.order_id),
                "order_no": order_no,
                "table_number": table_no,
                "dish": item.item_name,
                "dish_id": str(item.dish_id) if item.dish_id else None,
                "dept": item.kds_station,
                "wait_minutes": wait_minutes,
                "threshold": config[f"{status}_minutes"],
                "status": status,
            }
            timeout_items.append(timeout_entry)

            # ── WebSocket 推送超时状态到 KDS 前端 ──
            kds_station = item.kds_station
            if kds_station:
                await _push_timeout_to_kds(kds_station, timeout_entry)

            if status == "critical":
                critical_items.append(timeout_entry)

    # ── critical 级别: 推送告警到管理员手机 ──
    if critical_items:
        await _push_admin_alert(store_id, tenant_id, critical_items)
        await _trigger_serve_dispatch_agent(store_id, tenant_id, len(critical_items), timeout_items)

    log.info(
        "cooking_timeout.check",
        total_pending=len(rows),
        warning=len([t for t in timeout_items if t["status"] == "warning"]),
        critical=len(critical_items),
    )
    return timeout_items


async def get_timeout_config(store_id: str, db: AsyncSession) -> dict:
    """获取门店超时配置。

    Returns:
        {"normal_minutes": N, "warning_minutes": N, "critical_minutes": N}
    """
    config = _get_timeout_config(store_id)
    logger.info("cooking_timeout.get_config", store_id=store_id, **config)
    return config


async def update_timeout_config(
    store_id: str,
    normal_minutes: int | None = None,
    warning_minutes: int | None = None,
    critical_minutes: int | None = None,
    db: AsyncSession | None = None,
) -> dict:
    """更新门店超时配置。"""
    config = _get_timeout_config(store_id)

    if normal_minutes is not None:
        config["normal_minutes"] = normal_minutes
    if warning_minutes is not None:
        config["warning_minutes"] = warning_minutes
    if critical_minutes is not None:
        config["critical_minutes"] = critical_minutes

    _timeout_configs[store_id] = config
    logger.info("cooking_timeout.update_config", store_id=store_id, **config)
    return config


async def _trigger_serve_dispatch_agent(
    store_id: str,
    tenant_id: str,
    critical_count: int,
    timeout_items: list[dict],
):
    """触发出餐调度 Agent（serve_dispatch）处理超时任务。

    Agent 可执行动作：
    - 通知前厅经理
    - 调配人力支援档口
    - 推送催菜到对应档口 KDS
    - 向顾客发送等待致歉通知

    TODO: 接入 tx-agent 域的 Master Agent 编排。
    """
    log = logger.bind(store_id=store_id, tenant_id=tenant_id)
    log.warning(
        "cooking_timeout.agent_triggered",
        critical_count=critical_count,
        dishes=[t["dish"] for t in timeout_items if t["status"] == "critical"],
    )
    # TODO: HTTP 调用 tx-agent 的 serve_dispatch Agent
    # await httpx.post(f"{AGENT_URL}/api/v1/agent/serve-dispatch/trigger", json={...})
