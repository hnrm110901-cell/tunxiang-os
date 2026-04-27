"""配送在途温控服务 (TASK-3 / v368)

职责：
  - 阈值配置（GLOBAL / TEMPERATURE_TYPE / CATEGORY / SKU 优先级）
  - 时序温度上报（单条 + 批量 ≥ 500 ops/s）
  - 异步告警评估（连续超限合并为一条告警）
  - 时序查询 + 全程温度凭证（用于签收对比）
  - 事件总线：DELIVERY.TEMPERATURE_RECORDED / DELIVERY.TEMPERATURE_BREACH

关键约束：
  - 写入路径不被告警评估阻塞（asyncio.create_task）
  - 连续超限合并：12:00:01 超限 → 12:00:30 超限 → 一条告警 duration=29s
  - 异常处理只用具体类型，禁止 broad except
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import structlog
from sqlalchemy import desc, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events import emit_event
from shared.events.src.event_types import DeliveryTempEventType

from ..models.delivery_temperature import (
    SCOPE_PRIORITY,
    AlertStatus,
    BreachType,
    DeliveryTemperatureAlert,
    DeliveryTemperatureLog,
    DeliveryTemperatureThreshold,
    ScopeType,
    Severity,
    Source,
)

logger = structlog.get_logger(__name__)

# 连续超限合并的最大间隔（两条样本之间相差 >= 此值视为新的告警事件）
CONTINUITY_GAP_SECONDS = 120

# 严重性升级阈值（持续秒数）
SEVERITY_CRITICAL_SECONDS = 600  # 持续超限 ≥10 分钟升 CRITICAL
SEVERITY_WARNING_SECONDS = 60    # 持续超限 ≥1 分钟升 WARNING


def _uuid(val: str | uuid.UUID) -> uuid.UUID:
    return val if isinstance(val, uuid.UUID) else uuid.UUID(str(val))


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS 当前租户上下文"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


def _to_decimal(v: Any) -> Optional[Decimal]:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


# ════════════════════════════════════════════════════════════════════
#  阈值配置
# ════════════════════════════════════════════════════════════════════


async def create_threshold(
    *,
    tenant_id: str,
    scope_type: str,
    scope_value: Optional[str],
    min_temp_celsius: Optional[float],
    max_temp_celsius: Optional[float],
    alert_min_seconds: int = 60,
    enabled: bool = True,
    description: Optional[str] = None,
    db: AsyncSession,
) -> dict:
    if scope_type not in {s.value for s in ScopeType}:
        raise ValueError(f"非法 scope_type: {scope_type}")
    if min_temp_celsius is None and max_temp_celsius is None:
        raise ValueError("min_temp_celsius / max_temp_celsius 不能同时为空")
    if (
        min_temp_celsius is not None
        and max_temp_celsius is not None
        and max_temp_celsius < min_temp_celsius
    ):
        raise ValueError("max_temp_celsius 必须 >= min_temp_celsius")
    if alert_min_seconds < 1:
        raise ValueError("alert_min_seconds 必须 >= 1")

    await _set_tenant(db, tenant_id)
    threshold = DeliveryTemperatureThreshold(
        tenant_id=_uuid(tenant_id),
        scope_type=scope_type,
        scope_value=scope_value,
        min_temp_celsius=_to_decimal(min_temp_celsius),
        max_temp_celsius=_to_decimal(max_temp_celsius),
        alert_min_seconds=alert_min_seconds,
        enabled=enabled,
        description=description,
    )
    db.add(threshold)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ValueError(f"阈值写入冲突: {exc}") from exc

    return _serialize_threshold(threshold)


async def list_thresholds(
    *,
    tenant_id: str,
    enabled_only: bool = False,
    db: AsyncSession,
) -> list[dict]:
    await _set_tenant(db, tenant_id)
    stmt = select(DeliveryTemperatureThreshold).where(
        DeliveryTemperatureThreshold.tenant_id == _uuid(tenant_id),
        DeliveryTemperatureThreshold.is_deleted.is_(False),
    )
    if enabled_only:
        stmt = stmt.where(DeliveryTemperatureThreshold.enabled.is_(True))
    result = await db.execute(stmt)
    return [_serialize_threshold(t) for t in result.scalars().all()]


async def get_applicable_threshold(
    *,
    tenant_id: str,
    delivery_id: Optional[str] = None,
    sku_id: Optional[str] = None,
    category: Optional[str] = None,
    temperature_type: Optional[str] = None,
    db: AsyncSession,
) -> Optional[dict]:
    """按优先级匹配最高优先级阈值（SKU > CATEGORY > TEMPERATURE_TYPE > GLOBAL）。

    delivery_id 仅作为日志参数；当前不做按配送单的特例匹配，配送单的品类
    由调用方传入 category/sku_id/temperature_type。
    """
    await _set_tenant(db, tenant_id)
    stmt = select(DeliveryTemperatureThreshold).where(
        DeliveryTemperatureThreshold.tenant_id == _uuid(tenant_id),
        DeliveryTemperatureThreshold.enabled.is_(True),
        DeliveryTemperatureThreshold.is_deleted.is_(False),
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    if not rows:
        return None

    candidates: list[tuple[int, DeliveryTemperatureThreshold]] = []
    for row in rows:
        match_value = {
            ScopeType.SKU.value: sku_id,
            ScopeType.CATEGORY.value: category,
            ScopeType.TEMPERATURE_TYPE.value: temperature_type,
            ScopeType.GLOBAL.value: None,
        }.get(row.scope_type)

        if row.scope_type == ScopeType.GLOBAL.value or match_value is not None and (row.scope_value or "").lower() == match_value.lower():
            candidates.append((SCOPE_PRIORITY[row.scope_type], row))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    return _serialize_threshold(candidates[0][1])


def _serialize_threshold(t: DeliveryTemperatureThreshold) -> dict:
    return {
        "id": str(t.id),
        "scope_type": t.scope_type,
        "scope_value": t.scope_value,
        "min_temp_celsius": float(t.min_temp_celsius) if t.min_temp_celsius is not None else None,
        "max_temp_celsius": float(t.max_temp_celsius) if t.max_temp_celsius is not None else None,
        "alert_min_seconds": t.alert_min_seconds,
        "enabled": t.enabled,
        "description": t.description,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


# ════════════════════════════════════════════════════════════════════
#  温度记录写入
# ════════════════════════════════════════════════════════════════════


async def record_temperature(
    *,
    tenant_id: str,
    delivery_id: str,
    temperature_celsius: float,
    recorded_at: Optional[datetime] = None,
    humidity_percent: Optional[float] = None,
    gps_lat: Optional[float] = None,
    gps_lng: Optional[float] = None,
    device_id: Optional[str] = None,
    source: str = Source.DEVICE.value,
    extra: Optional[dict] = None,
    db: AsyncSession,
    evaluate_alert: bool = True,
) -> dict:
    """单条温度上报。

    evaluate_alert=True 时通过 asyncio.create_task 异步评估告警，
    不阻塞写入路径。
    """
    if source not in {s.value for s in Source}:
        raise ValueError(f"非法 source: {source}")

    await _set_tenant(db, tenant_id)
    log = DeliveryTemperatureLog(
        tenant_id=_uuid(tenant_id),
        delivery_id=_uuid(delivery_id),
        recorded_at=recorded_at or _now(),
        temperature_celsius=_to_decimal(temperature_celsius),
        humidity_percent=_to_decimal(humidity_percent),
        gps_lat=_to_decimal(gps_lat),
        gps_lng=_to_decimal(gps_lng),
        device_id=device_id,
        source=source,
        extra=extra,
    )
    db.add(log)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ValueError(f"温度记录写入失败: {exc}") from exc

    record_id = str(log.id)

    # 旁路事件（不阻塞主路径，失败也不影响业务）
    asyncio.create_task(
        emit_event(
            event_type=DeliveryTempEventType.RECORDED,
            tenant_id=str(tenant_id),
            stream_id=str(delivery_id),
            payload={
                "delivery_id": str(delivery_id),
                "temperature_celsius": float(temperature_celsius),
                "recorded_at": (recorded_at or log.recorded_at).isoformat(),
                "device_id": device_id,
                "source": source,
            },
            source_service="tx-supply",
        )
    )

    if evaluate_alert:
        # 异步触发告警评估，避免阻塞写入
        asyncio.create_task(_safe_evaluate_alert(tenant_id, delivery_id, db_session_factory=None, db=db))

    return {
        "record_id": record_id,
        "delivery_id": str(delivery_id),
        "recorded_at": log.recorded_at.isoformat(),
        "temperature_celsius": float(temperature_celsius),
        "source": source,
    }


async def record_temperatures_batch(
    *,
    tenant_id: str,
    delivery_id: str,
    records: list[dict],
    db: AsyncSession,
    evaluate_alert: bool = True,
) -> dict:
    """批量温度写入（≥ 500 ops/s）。

    实现：构造 ORM 对象列表并一次性 add_all + flush。
    PostgreSQL asyncpg driver 配合 SQLAlchemy 批量 INSERT，性能足以扛 500 ops/s。
    """
    if not records:
        return {"inserted": 0, "delivery_id": str(delivery_id)}

    await _set_tenant(db, tenant_id)

    tid = _uuid(tenant_id)
    did = _uuid(delivery_id)
    now = _now()

    objs: list[DeliveryTemperatureLog] = []
    payload_summaries: list[dict] = []
    for r in records:
        src = r.get("source", Source.DEVICE.value)
        if src not in {s.value for s in Source}:
            raise ValueError(f"非法 source: {src}")
        recorded_at = r.get("recorded_at") or now
        if isinstance(recorded_at, str):
            recorded_at = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))

        objs.append(
            DeliveryTemperatureLog(
                tenant_id=tid,
                delivery_id=did,
                recorded_at=recorded_at,
                temperature_celsius=_to_decimal(r["temperature_celsius"]),
                humidity_percent=_to_decimal(r.get("humidity_percent")),
                gps_lat=_to_decimal(r.get("gps_lat")),
                gps_lng=_to_decimal(r.get("gps_lng")),
                device_id=r.get("device_id"),
                source=src,
                extra=r.get("extra"),
            )
        )
        payload_summaries.append(
            {
                "temperature_celsius": float(r["temperature_celsius"]),
                "recorded_at": recorded_at.isoformat() if hasattr(recorded_at, "isoformat") else str(recorded_at),
            }
        )

    try:
        db.add_all(objs)
        await db.flush()
    except (IntegrityError, SQLAlchemyError) as exc:
        await db.rollback()
        raise ValueError(f"批量温度写入失败: {exc}") from exc

    # 降采样事件：批量写入时只发一条聚合事件，避免事件爆炸
    asyncio.create_task(
        emit_event(
            event_type=DeliveryTempEventType.RECORDED,
            tenant_id=str(tenant_id),
            stream_id=str(delivery_id),
            payload={
                "delivery_id": str(delivery_id),
                "batch_size": len(objs),
                "first_recorded_at": payload_summaries[0]["recorded_at"] if payload_summaries else None,
                "last_recorded_at": payload_summaries[-1]["recorded_at"] if payload_summaries else None,
            },
            source_service="tx-supply",
        )
    )

    if evaluate_alert:
        asyncio.create_task(_safe_evaluate_alert(tenant_id, delivery_id, db_session_factory=None, db=db))

    return {
        "inserted": len(objs),
        "delivery_id": str(delivery_id),
        "first_recorded_at": payload_summaries[0]["recorded_at"] if payload_summaries else None,
        "last_recorded_at": payload_summaries[-1]["recorded_at"] if payload_summaries else None,
    }


# ════════════════════════════════════════════════════════════════════
#  告警评估（合并连续超限）
# ════════════════════════════════════════════════════════════════════


async def _safe_evaluate_alert(
    tenant_id: str,
    delivery_id: str,
    *,
    db_session_factory: Any,
    db: Optional[AsyncSession] = None,
) -> None:
    """带异常隔离的告警评估包装器（asyncio.create_task 调用入口）"""
    try:
        if db is not None:
            await evaluate_alert_for_delivery(
                tenant_id=tenant_id,
                delivery_id=delivery_id,
                db=db,
            )
        # db_session_factory 路径预留：生产场景应该用独立 session
    except (SQLAlchemyError, ValueError) as exc:
        logger.warning(
            "delivery_temp_alert_eval_failed",
            tenant_id=tenant_id,
            delivery_id=delivery_id,
            error=str(exc),
        )


async def evaluate_alert_for_delivery(
    *,
    tenant_id: str,
    delivery_id: str,
    sku_id: Optional[str] = None,
    category: Optional[str] = None,
    temperature_type: Optional[str] = None,
    db: AsyncSession,
) -> dict:
    """评估告警：扫描该配送单的全部记录，按时序合并连续超限段。

    合并规则：
      - 同一阈值方向（HIGH 或 LOW）连续超限，且相邻样本间隔 < CONTINUITY_GAP_SECONDS
      - 持续 >= alert_min_seconds 才生成告警
      - 持续 >= SEVERITY_CRITICAL_SECONDS 升 CRITICAL；>= SEVERITY_WARNING_SECONDS 升 WARNING

    幂等：每次评估前查找该配送单仍 ACTIVE 的告警，删除后重新生成
    （或仅当告警时间戳变化时更新）。
    """
    await _set_tenant(db, tenant_id)
    threshold = await get_applicable_threshold(
        tenant_id=tenant_id,
        delivery_id=delivery_id,
        sku_id=sku_id,
        category=category,
        temperature_type=temperature_type,
        db=db,
    )
    if not threshold:
        return {"alerts_created": 0, "alerts_updated": 0, "reason": "no_applicable_threshold"}

    min_t = threshold["min_temp_celsius"]
    max_t = threshold["max_temp_celsius"]
    alert_min_seconds = threshold["alert_min_seconds"]
    threshold_id = _uuid(threshold["id"])

    # 扫描该配送单全部记录（按 recorded_at 升序）
    logs_stmt = (
        select(DeliveryTemperatureLog)
        .where(
            DeliveryTemperatureLog.tenant_id == _uuid(tenant_id),
            DeliveryTemperatureLog.delivery_id == _uuid(delivery_id),
            DeliveryTemperatureLog.is_deleted.is_(False),
        )
        .order_by(DeliveryTemperatureLog.recorded_at.asc())
    )
    logs_result = await db.execute(logs_stmt)
    logs = list(logs_result.scalars().all())
    if not logs:
        return {"alerts_created": 0, "alerts_updated": 0, "reason": "no_logs"}

    # 计算每条记录的超限状态
    breaches: list[dict] = []
    current_segment: Optional[dict] = None

    for log in logs:
        temp = float(log.temperature_celsius)
        breach_type: Optional[str] = None
        if max_t is not None and temp > max_t:
            breach_type = BreachType.HIGH.value
        elif min_t is not None and temp < min_t:
            breach_type = BreachType.LOW.value

        if breach_type is None:
            # 不超限：关闭当前段（如有）
            if current_segment is not None:
                breaches.append(current_segment)
                current_segment = None
            continue

        if (
            current_segment is None
            or current_segment["breach_type"] != breach_type
            or (log.recorded_at - current_segment["last_at"]).total_seconds() > CONTINUITY_GAP_SECONDS
        ):
            # 关闭旧段
            if current_segment is not None:
                breaches.append(current_segment)
            # 开新段
            current_segment = {
                "breach_type": breach_type,
                "started_at": log.recorded_at,
                "last_at": log.recorded_at,
                "peak": temp,
                "samples": 1,
            }
        else:
            current_segment["last_at"] = log.recorded_at
            if breach_type == BreachType.HIGH.value:
                current_segment["peak"] = max(current_segment["peak"], temp)
            else:
                current_segment["peak"] = min(current_segment["peak"], temp)
            current_segment["samples"] += 1

    if current_segment is not None:
        breaches.append(current_segment)

    # 过滤出持续 >= alert_min_seconds 的有效告警段
    valid_breaches: list[dict] = []
    for seg in breaches:
        duration = int((seg["last_at"] - seg["started_at"]).total_seconds())
        if duration >= alert_min_seconds:
            seg["duration_seconds"] = duration
            valid_breaches.append(seg)

    # 幂等：先把该配送单的 ACTIVE 告警标记为已重算（删除并重建）
    # 注意：HANDLED / FALSE_POSITIVE 状态保留
    existing_stmt = select(DeliveryTemperatureAlert).where(
        DeliveryTemperatureAlert.tenant_id == _uuid(tenant_id),
        DeliveryTemperatureAlert.delivery_id == _uuid(delivery_id),
        DeliveryTemperatureAlert.status == AlertStatus.ACTIVE.value,
        DeliveryTemperatureAlert.is_deleted.is_(False),
    )
    existing_result = await db.execute(existing_stmt)
    existing_alerts = list(existing_result.scalars().all())
    for ea in existing_alerts:
        ea.is_deleted = True

    created = 0
    new_alerts: list[DeliveryTemperatureAlert] = []
    for seg in valid_breaches:
        severity = _compute_severity(seg["duration_seconds"])
        alert = DeliveryTemperatureAlert(
            tenant_id=_uuid(tenant_id),
            delivery_id=_uuid(delivery_id),
            threshold_id=threshold_id,
            breach_type=seg["breach_type"],
            breach_started_at=seg["started_at"],
            breach_ended_at=seg["last_at"],
            duration_seconds=seg["duration_seconds"],
            peak_temperature_celsius=_to_decimal(seg["peak"]),
            threshold_min_celsius=_to_decimal(min_t),
            threshold_max_celsius=_to_decimal(max_t),
            severity=severity,
            status=AlertStatus.ACTIVE.value,
        )
        db.add(alert)
        new_alerts.append(alert)
        created += 1

    try:
        await db.flush()
    except (IntegrityError, SQLAlchemyError) as exc:
        await db.rollback()
        logger.error("delivery_temp_alert_persist_failed", error=str(exc))
        raise

    # 旁路事件：每条新告警发一条 BREACH_STARTED
    for alert in new_alerts:
        asyncio.create_task(
            emit_event(
                event_type=DeliveryTempEventType.BREACH_STARTED,
                tenant_id=str(tenant_id),
                stream_id=str(delivery_id),
                payload={
                    "alert_id": str(alert.id),
                    "delivery_id": str(delivery_id),
                    "breach_type": alert.breach_type,
                    "duration_seconds": alert.duration_seconds,
                    "peak_temperature_celsius": float(alert.peak_temperature_celsius)
                    if alert.peak_temperature_celsius is not None
                    else None,
                    "severity": alert.severity,
                    "started_at": alert.breach_started_at.isoformat(),
                },
                source_service="tx-supply",
            )
        )

    return {
        "alerts_created": created,
        "alerts_replaced": len(existing_alerts),
        "valid_breaches": len(valid_breaches),
        "all_breaches": len(breaches),
    }


def _compute_severity(duration_seconds: int) -> str:
    if duration_seconds >= SEVERITY_CRITICAL_SECONDS:
        return Severity.CRITICAL.value
    if duration_seconds >= SEVERITY_WARNING_SECONDS:
        return Severity.WARNING.value
    return Severity.INFO.value


# ════════════════════════════════════════════════════════════════════
#  查询：时序 / 摘要 / 告警 / 凭证
# ════════════════════════════════════════════════════════════════════


async def get_timeline(
    *,
    tenant_id: str,
    delivery_id: str,
    from_at: Optional[datetime] = None,
    to_at: Optional[datetime] = None,
    limit: int = 5000,
    db: AsyncSession,
) -> list[dict]:
    await _set_tenant(db, tenant_id)
    stmt = (
        select(DeliveryTemperatureLog)
        .where(
            DeliveryTemperatureLog.tenant_id == _uuid(tenant_id),
            DeliveryTemperatureLog.delivery_id == _uuid(delivery_id),
            DeliveryTemperatureLog.is_deleted.is_(False),
        )
        .order_by(DeliveryTemperatureLog.recorded_at.asc())
        .limit(limit)
    )
    if from_at is not None:
        stmt = stmt.where(DeliveryTemperatureLog.recorded_at >= from_at)
    if to_at is not None:
        stmt = stmt.where(DeliveryTemperatureLog.recorded_at <= to_at)

    result = await db.execute(stmt)
    return [_serialize_log(row) for row in result.scalars().all()]


def _serialize_log(log: DeliveryTemperatureLog) -> dict:
    return {
        "id": str(log.id),
        "delivery_id": str(log.delivery_id),
        "recorded_at": log.recorded_at.isoformat(),
        "temperature_celsius": float(log.temperature_celsius),
        "humidity_percent": float(log.humidity_percent) if log.humidity_percent is not None else None,
        "gps_lat": float(log.gps_lat) if log.gps_lat is not None else None,
        "gps_lng": float(log.gps_lng) if log.gps_lng is not None else None,
        "device_id": log.device_id,
        "source": log.source,
    }


async def get_summary(
    *,
    tenant_id: str,
    delivery_id: str,
    db: AsyncSession,
) -> dict:
    """配送单温度摘要：min/max/avg + 超限次数 + 总超限秒数"""
    await _set_tenant(db, tenant_id)
    logs = await get_timeline(
        tenant_id=tenant_id,
        delivery_id=delivery_id,
        db=db,
    )
    if not logs:
        return {
            "delivery_id": str(delivery_id),
            "sample_count": 0,
            "min_celsius": None,
            "max_celsius": None,
            "avg_celsius": None,
            "alert_count": 0,
            "total_breach_seconds": 0,
            "first_recorded_at": None,
            "last_recorded_at": None,
        }

    temps = [l["temperature_celsius"] for l in logs]
    alerts = await list_alerts_for_delivery(tenant_id=tenant_id, delivery_id=delivery_id, db=db)
    total_breach_seconds = sum(a["duration_seconds"] for a in alerts)

    return {
        "delivery_id": str(delivery_id),
        "sample_count": len(logs),
        "min_celsius": round(min(temps), 2),
        "max_celsius": round(max(temps), 2),
        "avg_celsius": round(sum(temps) / len(temps), 2),
        "alert_count": len(alerts),
        "total_breach_seconds": total_breach_seconds,
        "first_recorded_at": logs[0]["recorded_at"],
        "last_recorded_at": logs[-1]["recorded_at"],
    }


async def list_active_alerts(
    *,
    tenant_id: str,
    severity: Optional[str] = None,
    limit: int = 200,
    db: AsyncSession,
) -> list[dict]:
    await _set_tenant(db, tenant_id)
    stmt = (
        select(DeliveryTemperatureAlert)
        .where(
            DeliveryTemperatureAlert.tenant_id == _uuid(tenant_id),
            DeliveryTemperatureAlert.status == AlertStatus.ACTIVE.value,
            DeliveryTemperatureAlert.is_deleted.is_(False),
        )
        .order_by(desc(DeliveryTemperatureAlert.breach_started_at))
        .limit(limit)
    )
    if severity:
        stmt = stmt.where(DeliveryTemperatureAlert.severity == severity)
    result = await db.execute(stmt)
    return [_serialize_alert(a) for a in result.scalars().all()]


async def list_alerts_for_delivery(
    *,
    tenant_id: str,
    delivery_id: str,
    db: AsyncSession,
) -> list[dict]:
    await _set_tenant(db, tenant_id)
    stmt = (
        select(DeliveryTemperatureAlert)
        .where(
            DeliveryTemperatureAlert.tenant_id == _uuid(tenant_id),
            DeliveryTemperatureAlert.delivery_id == _uuid(delivery_id),
            DeliveryTemperatureAlert.is_deleted.is_(False),
        )
        .order_by(DeliveryTemperatureAlert.breach_started_at.asc())
    )
    result = await db.execute(stmt)
    return [_serialize_alert(a) for a in result.scalars().all()]


async def handle_alert(
    *,
    tenant_id: str,
    alert_id: str,
    action: str,
    comment: Optional[str] = None,
    handled_by: Optional[str] = None,
    db: AsyncSession,
) -> dict:
    """处理告警：ACTIVE -> HANDLED / FALSE_POSITIVE。"""
    await _set_tenant(db, tenant_id)
    stmt = select(DeliveryTemperatureAlert).where(
        DeliveryTemperatureAlert.tenant_id == _uuid(tenant_id),
        DeliveryTemperatureAlert.id == _uuid(alert_id),
        DeliveryTemperatureAlert.is_deleted.is_(False),
    )
    result = await db.execute(stmt)
    alert = result.scalar_one_or_none()
    if not alert:
        raise ValueError(f"告警不存在: {alert_id}")

    new_status = AlertStatus.FALSE_POSITIVE.value if action.upper() == "FALSE_POSITIVE" else AlertStatus.HANDLED.value
    alert.status = new_status
    alert.handle_action = action
    alert.handle_comment = comment
    alert.handled_by = _uuid(handled_by) if handled_by else None
    alert.handled_at = _now()
    if alert.breach_ended_at is None:
        alert.breach_ended_at = alert.handled_at

    try:
        await db.flush()
    except (IntegrityError, SQLAlchemyError) as exc:
        await db.rollback()
        raise ValueError(f"告警处理失败: {exc}") from exc

    asyncio.create_task(
        emit_event(
            event_type=DeliveryTempEventType.BREACH_ENDED,
            tenant_id=str(tenant_id),
            stream_id=str(alert.delivery_id),
            payload={
                "alert_id": str(alert.id),
                "delivery_id": str(alert.delivery_id),
                "status": alert.status,
                "handle_action": action,
                "handled_at": alert.handled_at.isoformat() if alert.handled_at else None,
            },
            source_service="tx-supply",
        )
    )

    return _serialize_alert(alert)


def _serialize_alert(a: DeliveryTemperatureAlert) -> dict:
    return {
        "id": str(a.id),
        "delivery_id": str(a.delivery_id),
        "threshold_id": str(a.threshold_id) if a.threshold_id else None,
        "breach_type": a.breach_type,
        "breach_started_at": a.breach_started_at.isoformat() if a.breach_started_at else None,
        "breach_ended_at": a.breach_ended_at.isoformat() if a.breach_ended_at else None,
        "duration_seconds": a.duration_seconds,
        "peak_temperature_celsius": float(a.peak_temperature_celsius)
        if a.peak_temperature_celsius is not None
        else None,
        "threshold_min_celsius": float(a.threshold_min_celsius)
        if a.threshold_min_celsius is not None
        else None,
        "threshold_max_celsius": float(a.threshold_max_celsius)
        if a.threshold_max_celsius is not None
        else None,
        "severity": a.severity,
        "status": a.status,
        "handle_action": a.handle_action,
        "handle_comment": a.handle_comment,
        "handled_by": str(a.handled_by) if a.handled_by else None,
        "handled_at": a.handled_at.isoformat() if a.handled_at else None,
    }


async def get_temperature_proof(
    *,
    tenant_id: str,
    delivery_id: str,
    db: AsyncSession,
    sample_step: int = 60,  # 抽样步长（秒），用于 GPS 轨迹摘要
) -> dict:
    """全程温度凭证（用于签收对比）。

    返回：
      - summary: 摘要（min/max/avg/sample_count）
      - alerts: 该配送单全部告警（含已处理）
      - timeline_sampled: 抽样时序，控制响应大小
      - gps_trail_summary: GPS 轨迹摘要（点数 + 起止点）
    """
    await _set_tenant(db, tenant_id)
    summary = await get_summary(tenant_id=tenant_id, delivery_id=delivery_id, db=db)
    alerts = await list_alerts_for_delivery(tenant_id=tenant_id, delivery_id=delivery_id, db=db)
    timeline = await get_timeline(tenant_id=tenant_id, delivery_id=delivery_id, db=db, limit=5000)

    # 抽样：每隔 sample_step 秒取一条
    sampled: list[dict] = []
    last_at: Optional[datetime] = None
    for row in timeline:
        ts = datetime.fromisoformat(row["recorded_at"].replace("Z", "+00:00"))
        if last_at is None or (ts - last_at).total_seconds() >= sample_step:
            sampled.append(row)
            last_at = ts

    gps_points = [(r["gps_lat"], r["gps_lng"]) for r in timeline if r["gps_lat"] and r["gps_lng"]]
    gps_summary = {
        "point_count": len(gps_points),
        "start": {"lat": gps_points[0][0], "lng": gps_points[0][1]} if gps_points else None,
        "end": {"lat": gps_points[-1][0], "lng": gps_points[-1][1]} if gps_points else None,
    }

    return {
        "delivery_id": str(delivery_id),
        "summary": summary,
        "alerts": alerts,
        "timeline_sampled": sampled,
        "timeline_full_count": len(timeline),
        "sample_step_seconds": sample_step,
        "gps_trail_summary": gps_summary,
        "generated_at": _now().isoformat(),
    }


__all__ = [
    "create_threshold",
    "list_thresholds",
    "get_applicable_threshold",
    "record_temperature",
    "record_temperatures_batch",
    "evaluate_alert_for_delivery",
    "get_timeline",
    "get_summary",
    "list_active_alerts",
    "list_alerts_for_delivery",
    "handle_alert",
    "get_temperature_proof",
    "CONTINUITY_GAP_SECONDS",
    "SEVERITY_CRITICAL_SECONDS",
    "SEVERITY_WARNING_SECONDS",
]
