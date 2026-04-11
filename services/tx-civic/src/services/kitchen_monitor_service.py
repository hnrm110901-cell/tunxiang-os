"""
明厨亮灶管理 — Transparent Kitchen Monitoring Service

设备注册、AI告警管理、设备在线率统计。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import text

from shared.ontology.src.database import TenantSession

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------

def calculate_online_rate(devices: list[dict]) -> float:
    """计算设备在线率百分比。

    在线判定: status == 'online'
    返回 0.0 ~ 100.0
    """
    if not devices:
        return 0.0
    online = sum(1 for d in devices if d.get("status") == "online")
    return round(online / len(devices) * 100, 1)


def classify_alert_severity(alert_type: str, confidence: float) -> str:
    """根据告警类型和置信度判断严重程度。

    严重程度: critical / warning / info
    规则:
    - 鼠患(rat)、明火(fire)、异物(foreign_object) → 任何置信度 >= 0.5 即 critical
    - 未戴口罩(no_mask)、未戴手套(no_gloves)、未穿工服(no_uniform) → >=0.7 warning, >=0.9 critical
    - 其他 → >=0.8 warning, else info
    """
    critical_types = {"rat", "fire", "foreign_object", "smoke"}
    hygiene_types = {"no_mask", "no_gloves", "no_uniform", "no_cap"}

    if alert_type in critical_types:
        if confidence >= 0.5:
            return "critical"
        return "warning"

    if alert_type in hygiene_types:
        if confidence >= 0.9:
            return "critical"
        if confidence >= 0.7:
            return "warning"
        return "info"

    # 默认
    if confidence >= 0.8:
        return "warning"
    return "info"


# ---------------------------------------------------------------------------
# 业务服务
# ---------------------------------------------------------------------------

async def register_device(
    tenant_id: str,
    store_id: str,
    data: dict[str, Any],
) -> dict:
    """注册设备。

    data: device_name, device_type, location, rtsp_url, model_version
    """
    device_id = str(uuid.uuid4())

    async with TenantSession(tenant_id) as db:
        await db.execute(
            text(
                "INSERT INTO civic_kitchen_devices "
                "(id, tenant_id, store_id, device_name, device_type, "
                " location, rtsp_url, model_version, status, created_at) "
                "VALUES (:id, :tenant_id, :store_id, :device_name, :device_type, "
                " :location, :rtsp_url, :model_version, 'offline', NOW())"
            ),
            {
                "id": device_id,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "device_name": data["device_name"],
                "device_type": data.get("device_type", "camera"),
                "location": data.get("location"),
                "rtsp_url": data.get("rtsp_url"),
                "model_version": data.get("model_version"),
            },
        )
        await db.commit()

    logger.info("device_registered", tenant_id=tenant_id, device_id=device_id, name=data["device_name"])
    return {"id": device_id, "status": "offline", **data}


async def get_devices(tenant_id: str, store_id: str) -> list[dict]:
    """设备列表。"""
    async with TenantSession(tenant_id) as db:
        rows = await db.execute(
            text(
                "SELECT id, device_name, device_type, location, rtsp_url, "
                "  model_version, status, last_heartbeat, created_at "
                "FROM civic_kitchen_devices "
                "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                "ORDER BY created_at"
            ),
            {"tenant_id": tenant_id, "store_id": store_id},
        )
        return [dict(r) for r in rows.mappings().all()]


async def update_device_status(
    tenant_id: str,
    device_id: str,
    status: str,
    heartbeat: str | None = None,
) -> dict:
    """更新设备状态 (online/offline/error)。"""
    async with TenantSession(tenant_id) as db:
        await db.execute(
            text(
                "UPDATE civic_kitchen_devices "
                "SET status = :status, last_heartbeat = COALESCE(:heartbeat, NOW()), "
                "    updated_at = NOW() "
                "WHERE tenant_id = :tenant_id AND id = :device_id"
            ),
            {
                "tenant_id": tenant_id,
                "device_id": device_id,
                "status": status,
                "heartbeat": heartbeat,
            },
        )
        await db.commit()

    logger.info("device_status_updated", device_id=device_id, status=status)
    return {"device_id": device_id, "status": status}


async def record_ai_alert(
    tenant_id: str,
    store_id: str,
    device_id: str,
    alert_data: dict[str, Any],
) -> dict:
    """记录AI告警。

    alert_data: alert_type, confidence, snapshot_url, detail
    """
    alert_id = str(uuid.uuid4())
    alert_type = alert_data["alert_type"]
    confidence = alert_data.get("confidence", 0.0)
    severity = classify_alert_severity(alert_type, confidence)

    async with TenantSession(tenant_id) as db:
        await db.execute(
            text(
                "INSERT INTO civic_kitchen_alerts "
                "(id, tenant_id, store_id, device_id, alert_type, confidence, "
                " severity, snapshot_url, detail, resolved, created_at) "
                "VALUES (:id, :tenant_id, :store_id, :device_id, :alert_type, "
                " :confidence, :severity, :snapshot_url, :detail, FALSE, NOW())"
            ),
            {
                "id": alert_id,
                "tenant_id": tenant_id,
                "store_id": store_id,
                "device_id": device_id,
                "alert_type": alert_type,
                "confidence": confidence,
                "severity": severity,
                "snapshot_url": alert_data.get("snapshot_url"),
                "detail": alert_data.get("detail"),
            },
        )
        await db.commit()

    logger.info(
        "ai_alert_recorded",
        tenant_id=tenant_id, alert_id=alert_id,
        alert_type=alert_type, severity=severity,
    )
    return {
        "id": alert_id,
        "alert_type": alert_type,
        "severity": severity,
        "confidence": confidence,
        "resolved": False,
    }


async def get_alerts(
    tenant_id: str,
    store_id: str,
    resolved: bool | None = None,
    alert_type: str | None = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    """告警列表（支持过滤）。"""
    offset = (page - 1) * size
    conditions = ["tenant_id = :tenant_id", "store_id = :store_id"]
    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "store_id": store_id,
        "limit": size,
        "offset": offset,
    }

    if resolved is not None:
        conditions.append("resolved = :resolved")
        params["resolved"] = resolved
    if alert_type:
        conditions.append("alert_type = :alert_type")
        params["alert_type"] = alert_type

    where = " AND ".join(conditions)

    async with TenantSession(tenant_id) as db:
        count_result = await db.execute(
            text(f"SELECT COUNT(*) AS cnt FROM civic_kitchen_alerts WHERE {where}"),
            params,
        )
        total = count_result.scalar() or 0

        rows = await db.execute(
            text(
                f"SELECT id, device_id, alert_type, confidence, severity, "
                f"  snapshot_url, detail, resolved, resolved_by, resolve_notes, "
                f"  false_positive, created_at, resolved_at "
                f"FROM civic_kitchen_alerts "
                f"WHERE {where} "
                f"ORDER BY created_at DESC "
                f"LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        items = [dict(r) for r in rows.mappings().all()]

    return {"total": total, "page": page, "size": size, "items": items}


async def resolve_alert(
    tenant_id: str,
    alert_id: str,
    resolved_by: str,
    notes: str | None = None,
    false_positive: bool = False,
) -> dict:
    """处理告警。"""
    async with TenantSession(tenant_id) as db:
        await db.execute(
            text(
                "UPDATE civic_kitchen_alerts "
                "SET resolved = TRUE, resolved_by = :resolved_by, "
                "    resolve_notes = :notes, false_positive = :false_positive, "
                "    resolved_at = NOW() "
                "WHERE tenant_id = :tenant_id AND id = :alert_id"
            ),
            {
                "tenant_id": tenant_id,
                "alert_id": alert_id,
                "resolved_by": resolved_by,
                "notes": notes,
                "false_positive": false_positive,
            },
        )
        await db.commit()

    logger.info("alert_resolved", alert_id=alert_id, resolved_by=resolved_by, false_positive=false_positive)
    return {"alert_id": alert_id, "resolved": True, "false_positive": false_positive}


async def get_online_rate(tenant_id: str, store_id: str) -> dict:
    """计算设备在线率。"""
    devices = await get_devices(tenant_id, store_id)
    rate = calculate_online_rate(devices)
    total = len(devices)
    online = sum(1 for d in devices if d.get("status") == "online")

    return {
        "store_id": store_id,
        "total_devices": total,
        "online_devices": online,
        "online_rate": rate,
    }


async def get_alert_stats(
    tenant_id: str,
    store_id: str,
    days: int = 30,
) -> dict:
    """告警统计 — 最近N天。"""
    async with TenantSession(tenant_id) as db:
        # 总告警数
        total_row = await db.execute(
            text(
                "SELECT COUNT(*) AS cnt FROM civic_kitchen_alerts "
                "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                "  AND created_at >= CURRENT_DATE - :days"
            ),
            {"tenant_id": tenant_id, "store_id": store_id, "days": days},
        )
        total = total_row.scalar() or 0

        # 已处理
        resolved_row = await db.execute(
            text(
                "SELECT COUNT(*) AS cnt FROM civic_kitchen_alerts "
                "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                "  AND created_at >= CURRENT_DATE - :days AND resolved = TRUE"
            ),
            {"tenant_id": tenant_id, "store_id": store_id, "days": days},
        )
        resolved = resolved_row.scalar() or 0

        # 误报
        fp_row = await db.execute(
            text(
                "SELECT COUNT(*) AS cnt FROM civic_kitchen_alerts "
                "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                "  AND created_at >= CURRENT_DATE - :days AND false_positive = TRUE"
            ),
            {"tenant_id": tenant_id, "store_id": store_id, "days": days},
        )
        false_positives = fp_row.scalar() or 0

        # 按类型分布
        type_rows = await db.execute(
            text(
                "SELECT alert_type, COUNT(*) AS cnt "
                "FROM civic_kitchen_alerts "
                "WHERE tenant_id = :tenant_id AND store_id = :store_id "
                "  AND created_at >= CURRENT_DATE - :days "
                "GROUP BY alert_type ORDER BY cnt DESC"
            ),
            {"tenant_id": tenant_id, "store_id": store_id, "days": days},
        )
        by_type = {r["alert_type"]: r["cnt"] for r in type_rows.mappings().all()}

    resolve_rate = round(resolved / total * 100, 1) if total else 0.0

    return {
        "store_id": store_id,
        "period_days": days,
        "total_alerts": total,
        "resolved": resolved,
        "resolve_rate": resolve_rate,
        "false_positives": false_positives,
        "by_type": by_type,
    }
