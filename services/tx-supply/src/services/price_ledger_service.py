"""价格台账服务（v366）

核心能力：
  - record_price()        价格快照写入（幂等：tenant+source_doc_id+ingredient_id 唯一）
  - query_ledger()        台账查询（按 ingredient/supplier/时间窗筛选）
  - compute_trend()       趋势聚合（按周/月）
  - compare_suppliers()   多供应商同食材对比
  - evaluate_alerts()     写入价格后立即评估所有规则
  - acknowledge_alert()   预警处理

约定：
  - 所有金额字段 int（分）
  - 异常处理使用具体类型（SQLAlchemyError/ValueError）
  - 写入成功后异步发射 PRICE.RECORDED 事件
  - 触发预警时异步发射 PRICE.ALERT_TRIGGERED 事件
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event
from shared.events.src.event_types import PriceEventType

from ..models.price_ledger import (
    ALERT_RULE_TYPES,
    ALERT_SEVERITIES,
    ALERT_STATUSES,
)

logger = structlog.get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────
# 工具
# ──────────────────────────────────────────────────────────────────────


def _uuid(val: str | uuid.UUID | None) -> Optional[uuid.UUID]:
    if val is None:
        return None
    return val if isinstance(val, uuid.UUID) else uuid.UUID(str(val))


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """注入 RLS 租户上下文。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


def _row_to_record(row: dict[str, Any]) -> dict[str, Any]:
    """统一把 supplier_price_history 行转 dict（UUID/datetime 安全序列化）。"""
    return {
        "id": str(row["id"]),
        "ingredient_id": str(row["ingredient_id"]),
        "supplier_id": str(row["supplier_id"]),
        "unit_price_fen": int(row["unit_price_fen"]),
        "quantity_unit": row.get("quantity_unit"),
        "captured_at": row["captured_at"],
        "source_doc_type": row.get("source_doc_type"),
        "source_doc_id": str(row["source_doc_id"]) if row.get("source_doc_id") else None,
        "source_doc_no": row.get("source_doc_no"),
        "store_id": str(row["store_id"]) if row.get("store_id") else None,
        "notes": row.get("notes"),
    }


def _row_to_alert(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "rule_id": str(row["rule_id"]),
        "ingredient_id": str(row["ingredient_id"]),
        "supplier_id": str(row["supplier_id"]) if row.get("supplier_id") else None,
        "triggered_at": row["triggered_at"],
        "current_price_fen": int(row["current_price_fen"]),
        "baseline_price_fen": int(row["baseline_price_fen"])
        if row.get("baseline_price_fen") is not None
        else None,
        "breach_value": row.get("breach_value"),
        "severity": row["severity"],
        "status": row["status"],
        "acked_by": str(row["acked_by"]) if row.get("acked_by") else None,
        "acked_at": row.get("acked_at"),
        "ack_comment": row.get("ack_comment"),
    }


def _row_to_rule(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "ingredient_id": str(row["ingredient_id"]) if row.get("ingredient_id") else None,
        "rule_type": row["rule_type"],
        "threshold_value": row["threshold_value"],
        "baseline_window_days": int(row["baseline_window_days"]),
        "enabled": bool(row["enabled"]),
        "created_at": row.get("created_at"),
    }


# ──────────────────────────────────────────────────────────────────────
# 1. 价格快照写入（核心入口）
# ──────────────────────────────────────────────────────────────────────


async def record_price(
    *,
    tenant_id: str,
    ingredient_id: str,
    supplier_id: str,
    unit_price_fen: int,
    db: AsyncSession,
    quantity_unit: Optional[str] = None,
    captured_at: Optional[datetime] = None,
    source_doc_type: Optional[str] = "manual",
    source_doc_id: Optional[str] = None,
    source_doc_no: Optional[str] = None,
    store_id: Optional[str] = None,
    notes: Optional[str] = None,
    created_by: Optional[str] = None,
    evaluate_alerts_after: bool = True,
) -> dict[str, Any]:
    """写入一条价格快照。幂等：相同 tenant+source_doc_id+ingredient_id 直接返回已存在记录。

    Returns:
        {"ok": True, "data": {...record...}, "alerts": [...], "duplicated": bool}
    """
    if not isinstance(unit_price_fen, int) or unit_price_fen < 0:
        return {
            "ok": False,
            "error": "unit_price_fen 必须是非负整数（分）",
        }

    captured_at = captured_at or _now()
    await _set_tenant(db, tenant_id)

    # ── 幂等：source_doc_id 存在时先查重 ──
    if source_doc_id:
        existing = await db.execute(
            text(
                """
                SELECT id, ingredient_id, supplier_id, unit_price_fen, quantity_unit,
                       captured_at, source_doc_type, source_doc_id, source_doc_no,
                       store_id, notes
                FROM supplier_price_history
                WHERE tenant_id = :tid
                  AND source_doc_id = :sid
                  AND ingredient_id = :ing
                  AND is_deleted = false
                LIMIT 1
                """
            ),
            {
                "tid": str(tenant_id),
                "sid": str(source_doc_id),
                "ing": str(ingredient_id),
            },
        )
        existing_row = existing.mappings().one_or_none()
        if existing_row is not None:
            logger.info(
                "price_record_duplicated",
                tenant_id=str(tenant_id),
                source_doc_id=str(source_doc_id),
                ingredient_id=str(ingredient_id),
            )
            return {
                "ok": True,
                "duplicated": True,
                "data": _row_to_record(dict(existing_row)),
                "alerts": [],
            }

    record_id = uuid.uuid4()
    try:
        await db.execute(
            text(
                """
                INSERT INTO supplier_price_history
                    (id, tenant_id, ingredient_id, supplier_id, unit_price_fen,
                     quantity_unit, captured_at, source_doc_type, source_doc_id,
                     source_doc_no, store_id, notes, created_by)
                VALUES
                    (:id, :tid, :ing, :sup, :price,
                     :unit, :cap, :stype, :sid,
                     :sno, :store, :notes, :cby)
                """
            ),
            {
                "id": record_id,
                "tid": str(tenant_id),
                "ing": str(ingredient_id),
                "sup": str(supplier_id),
                "price": int(unit_price_fen),
                "unit": quantity_unit,
                "cap": captured_at,
                "stype": source_doc_type,
                "sid": _uuid(source_doc_id),
                "sno": source_doc_no,
                "store": _uuid(store_id),
                "notes": notes,
                "cby": _uuid(created_by),
            },
        )
        await db.flush()
    except IntegrityError as exc:
        # 并发写入命中唯一约束 → 退化为查重返回
        await db.rollback()
        await _set_tenant(db, tenant_id)
        if source_doc_id:
            existing = await db.execute(
                text(
                    "SELECT id, ingredient_id, supplier_id, unit_price_fen, "
                    "quantity_unit, captured_at, source_doc_type, source_doc_id, "
                    "source_doc_no, store_id, notes "
                    "FROM supplier_price_history "
                    "WHERE tenant_id = :tid AND source_doc_id = :sid "
                    "AND ingredient_id = :ing AND is_deleted = false LIMIT 1"
                ),
                {
                    "tid": str(tenant_id),
                    "sid": str(source_doc_id),
                    "ing": str(ingredient_id),
                },
            )
            existing_row = existing.mappings().one_or_none()
            if existing_row is not None:
                return {
                    "ok": True,
                    "duplicated": True,
                    "data": _row_to_record(dict(existing_row)),
                    "alerts": [],
                }
        logger.error("price_record_integrity_error", error=str(exc))
        return {"ok": False, "error": f"integrity_error: {exc.orig}"}
    except SQLAlchemyError as exc:
        logger.error("price_record_db_error", error=str(exc))
        return {"ok": False, "error": f"db_error: {exc}"}

    record_dict = {
        "id": str(record_id),
        "ingredient_id": str(ingredient_id),
        "supplier_id": str(supplier_id),
        "unit_price_fen": int(unit_price_fen),
        "quantity_unit": quantity_unit,
        "captured_at": captured_at,
        "source_doc_type": source_doc_type,
        "source_doc_id": str(source_doc_id) if source_doc_id else None,
        "source_doc_no": source_doc_no,
        "store_id": str(store_id) if store_id else None,
        "notes": notes,
    }

    # ── 异步发射 PRICE.RECORDED ──
    asyncio.create_task(
        emit_event(
            event_type=PriceEventType.RECORDED,
            tenant_id=tenant_id,
            stream_id=str(record_id),
            payload={
                "ingredient_id": str(ingredient_id),
                "supplier_id": str(supplier_id),
                "unit_price_fen": int(unit_price_fen),
                "source_doc_type": source_doc_type,
                "source_doc_no": source_doc_no,
            },
            store_id=str(store_id) if store_id else None,
            source_service="tx-supply",
            metadata={"captured_at": captured_at.isoformat()},
        )
    )

    triggered_alerts: list[dict[str, Any]] = []
    if evaluate_alerts_after:
        triggered_alerts = await evaluate_alerts(
            tenant_id=tenant_id,
            ingredient_id=str(ingredient_id),
            supplier_id=str(supplier_id),
            current_price_fen=int(unit_price_fen),
            db=db,
            store_id=str(store_id) if store_id else None,
        )

    logger.info(
        "price_recorded",
        tenant_id=str(tenant_id),
        ingredient_id=str(ingredient_id),
        supplier_id=str(supplier_id),
        unit_price_fen=int(unit_price_fen),
        alerts_triggered=len(triggered_alerts),
    )

    return {
        "ok": True,
        "duplicated": False,
        "data": record_dict,
        "alerts": triggered_alerts,
    }


# ──────────────────────────────────────────────────────────────────────
# 2. 台账查询
# ──────────────────────────────────────────────────────────────────────


async def query_ledger(
    *,
    tenant_id: str,
    db: AsyncSession,
    ingredient_id: Optional[str] = None,
    supplier_id: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    page: int = 1,
    size: int = 50,
) -> dict[str, Any]:
    """台账查询：支持 ingredient/supplier/时间窗筛选 + 分页。"""
    if page < 1:
        page = 1
    if size < 1 or size > 500:
        size = 50

    await _set_tenant(db, tenant_id)

    where_clauses: list[str] = ["tenant_id = :tid", "is_deleted = false"]
    params: dict[str, Any] = {"tid": str(tenant_id)}
    if ingredient_id:
        where_clauses.append("ingredient_id = :ing")
        params["ing"] = str(ingredient_id)
    if supplier_id:
        where_clauses.append("supplier_id = :sup")
        params["sup"] = str(supplier_id)
    if date_from:
        where_clauses.append("captured_at >= :df")
        params["df"] = date_from
    if date_to:
        where_clauses.append("captured_at <= :dt")
        params["dt"] = date_to

    where_sql = " AND ".join(where_clauses)

    count_result = await db.execute(
        text(f"SELECT COUNT(*)::bigint AS c FROM supplier_price_history WHERE {where_sql}"),
        params,
    )
    total = int(count_result.scalar() or 0)

    list_params = dict(params)
    list_params["limit"] = size
    list_params["offset"] = (page - 1) * size
    rows = await db.execute(
        text(
            f"""
            SELECT id, ingredient_id, supplier_id, unit_price_fen, quantity_unit,
                   captured_at, source_doc_type, source_doc_id, source_doc_no,
                   store_id, notes
            FROM supplier_price_history
            WHERE {where_sql}
            ORDER BY captured_at DESC, id DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        list_params,
    )
    items = [_row_to_record(dict(r)) for r in rows.mappings().all()]

    return {
        "ok": True,
        "items": items,
        "total": total,
        "page": page,
        "size": size,
    }


# ──────────────────────────────────────────────────────────────────────
# 3. 趋势聚合
# ──────────────────────────────────────────────────────────────────────


async def compute_trend(
    *,
    tenant_id: str,
    ingredient_id: str,
    db: AsyncSession,
    bucket: str = "week",
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    supplier_id: Optional[str] = None,
) -> dict[str, Any]:
    """按周/月聚合食材的价格趋势。"""
    if bucket not in ("week", "month"):
        return {"ok": False, "error": "bucket 必须是 week 或 month"}

    await _set_tenant(db, tenant_id)

    where = ["tenant_id = :tid", "ingredient_id = :ing", "is_deleted = false"]
    params: dict[str, Any] = {"tid": str(tenant_id), "ing": str(ingredient_id)}
    if supplier_id:
        where.append("supplier_id = :sup")
        params["sup"] = str(supplier_id)
    if date_from:
        where.append("captured_at >= :df")
        params["df"] = date_from
    if date_to:
        where.append("captured_at <= :dt")
        params["dt"] = date_to
    where_sql = " AND ".join(where)

    rows = await db.execute(
        text(
            f"""
            SELECT
                date_trunc(:bucket, captured_at)::date AS period_start,
                AVG(unit_price_fen)::bigint AS avg_price_fen,
                MIN(unit_price_fen)::bigint AS min_price_fen,
                MAX(unit_price_fen)::bigint AS max_price_fen,
                COUNT(*)::bigint AS sample_count
            FROM supplier_price_history
            WHERE {where_sql}
            GROUP BY 1
            ORDER BY 1 ASC
            """
        ),
        {**params, "bucket": bucket},
    )

    points = [
        {
            "period_start": r["period_start"],
            "avg_price_fen": int(r["avg_price_fen"]),
            "min_price_fen": int(r["min_price_fen"]),
            "max_price_fen": int(r["max_price_fen"]),
            "sample_count": int(r["sample_count"]),
        }
        for r in rows.mappings().all()
    ]

    return {
        "ok": True,
        "ingredient_id": str(ingredient_id),
        "bucket": bucket,
        "points": points,
    }


# ──────────────────────────────────────────────────────────────────────
# 4. 多供应商同食材对比
# ──────────────────────────────────────────────────────────────────────


async def compare_suppliers(
    *,
    tenant_id: str,
    ingredient_id: str,
    db: AsyncSession,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> dict[str, Any]:
    """对比同一食材在多个供应商的价格。"""
    await _set_tenant(db, tenant_id)

    where = ["tenant_id = :tid", "ingredient_id = :ing", "is_deleted = false"]
    params: dict[str, Any] = {"tid": str(tenant_id), "ing": str(ingredient_id)}
    if date_from:
        where.append("captured_at >= :df")
        params["df"] = date_from
    if date_to:
        where.append("captured_at <= :dt")
        params["dt"] = date_to
    where_sql = " AND ".join(where)

    rows = await db.execute(
        text(
            f"""
            WITH agg AS (
                SELECT
                    supplier_id,
                    AVG(unit_price_fen)::bigint AS avg_price_fen,
                    MIN(unit_price_fen)::bigint AS min_price_fen,
                    MAX(unit_price_fen)::bigint AS max_price_fen,
                    COUNT(*)::bigint AS sample_count
                FROM supplier_price_history
                WHERE {where_sql}
                GROUP BY supplier_id
            ),
            last_per_supplier AS (
                SELECT DISTINCT ON (supplier_id)
                    supplier_id,
                    unit_price_fen AS last_price_fen,
                    captured_at AS last_captured_at
                FROM supplier_price_history
                WHERE {where_sql}
                ORDER BY supplier_id, captured_at DESC
            )
            SELECT a.supplier_id, a.avg_price_fen, a.min_price_fen, a.max_price_fen,
                   a.sample_count, l.last_price_fen, l.last_captured_at
            FROM agg a
            JOIN last_per_supplier l USING (supplier_id)
            ORDER BY a.avg_price_fen ASC
            """
        ),
        params,
    )

    suppliers = [
        {
            "supplier_id": str(r["supplier_id"]),
            "avg_price_fen": int(r["avg_price_fen"]),
            "min_price_fen": int(r["min_price_fen"]),
            "max_price_fen": int(r["max_price_fen"]),
            "last_price_fen": int(r["last_price_fen"]),
            "last_captured_at": r["last_captured_at"],
            "sample_count": int(r["sample_count"]),
        }
        for r in rows.mappings().all()
    ]

    return {
        "ok": True,
        "ingredient_id": str(ingredient_id),
        "suppliers": suppliers,
    }


# ──────────────────────────────────────────────────────────────────────
# 5. 预警评估
# ──────────────────────────────────────────────────────────────────────


def _classify_severity(rule_type: str, breach: Decimal) -> str:
    """根据 rule_type 与 breach 值估算严重程度。简单分级，后续可演进。"""
    abs_breach = abs(breach) if breach is not None else Decimal("0")
    if rule_type in ("PERCENT_RISE", "PERCENT_FALL", "YOY_RISE", "YOY_FALL"):
        # 百分比规则：>30 点 = CRITICAL，>10 点 = WARNING，否则 INFO
        if abs_breach >= Decimal("30"):
            return "CRITICAL"
        if abs_breach >= Decimal("10"):
            return "WARNING"
        return "INFO"
    # 绝对值规则：默认 WARNING
    return "WARNING"


async def evaluate_alerts(
    *,
    tenant_id: str,
    ingredient_id: str,
    supplier_id: str,
    current_price_fen: int,
    db: AsyncSession,
    store_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """对刚写入的价格快照立即评估所有规则，命中的写入 price_alerts。

    返回触发的 alert 字典列表。
    """
    await _set_tenant(db, tenant_id)

    rules_result = await db.execute(
        text(
            """
            SELECT id, rule_type, threshold_value, baseline_window_days, ingredient_id
            FROM price_alert_rules
            WHERE tenant_id = :tid
              AND enabled = true
              AND is_deleted = false
              AND (ingredient_id = :ing OR ingredient_id IS NULL)
            """
        ),
        {"tid": str(tenant_id), "ing": str(ingredient_id)},
    )
    rules = [dict(r) for r in rules_result.mappings().all()]
    if not rules:
        return []

    triggered: list[dict[str, Any]] = []
    now = _now()

    for rule in rules:
        rule_type = rule["rule_type"]
        threshold = Decimal(rule["threshold_value"])
        window_days = int(rule["baseline_window_days"] or 30)
        baseline_price: Optional[int] = None
        breach: Optional[Decimal] = None
        hit = False

        if rule_type == "ABSOLUTE_HIGH":
            if current_price_fen >= int(threshold):
                breach = Decimal(current_price_fen) - threshold
                hit = True
        elif rule_type == "ABSOLUTE_LOW":
            if current_price_fen <= int(threshold):
                breach = threshold - Decimal(current_price_fen)
                hit = True
        elif rule_type in ("PERCENT_RISE", "PERCENT_FALL"):
            baseline = await _baseline_avg(
                db,
                tenant_id=tenant_id,
                ingredient_id=ingredient_id,
                window_start=now - timedelta(days=window_days),
                window_end=now,
                exclude_recent_seconds=10,  # 排除刚写入的本条
            )
            if baseline is None or baseline <= 0:
                continue
            baseline_price = int(baseline)
            pct = (Decimal(current_price_fen) - Decimal(baseline)) / Decimal(baseline) * Decimal("100")
            breach = pct
            if rule_type == "PERCENT_RISE" and pct >= threshold:
                hit = True
            if rule_type == "PERCENT_FALL" and pct <= -threshold:
                hit = True
        elif rule_type in ("YOY_RISE", "YOY_FALL"):
            yoy_end = now - timedelta(days=365 - window_days // 2)
            yoy_start = now - timedelta(days=365 + window_days // 2)
            baseline = await _baseline_avg(
                db,
                tenant_id=tenant_id,
                ingredient_id=ingredient_id,
                window_start=yoy_start,
                window_end=yoy_end,
            )
            if baseline is None or baseline <= 0:
                continue
            baseline_price = int(baseline)
            pct = (Decimal(current_price_fen) - Decimal(baseline)) / Decimal(baseline) * Decimal("100")
            breach = pct
            if rule_type == "YOY_RISE" and pct >= threshold:
                hit = True
            if rule_type == "YOY_FALL" and pct <= -threshold:
                hit = True

        if not hit or breach is None:
            continue

        severity = _classify_severity(rule_type, breach)
        alert_id = uuid.uuid4()
        try:
            await db.execute(
                text(
                    """
                    INSERT INTO price_alerts
                        (id, tenant_id, rule_id, ingredient_id, supplier_id,
                         triggered_at, current_price_fen, baseline_price_fen,
                         breach_value, severity, status)
                    VALUES
                        (:id, :tid, :rid, :ing, :sup,
                         :tat, :cp, :bp, :br, :sev, 'ACTIVE')
                    """
                ),
                {
                    "id": alert_id,
                    "tid": str(tenant_id),
                    "rid": rule["id"],
                    "ing": str(ingredient_id),
                    "sup": str(supplier_id),
                    "tat": now,
                    "cp": int(current_price_fen),
                    "bp": baseline_price,
                    "br": breach,
                    "sev": severity,
                },
            )
            await db.flush()
        except SQLAlchemyError as exc:
            logger.error(
                "price_alert_insert_failed",
                error=str(exc),
                rule_id=str(rule["id"]),
            )
            continue

        alert_dict = {
            "id": str(alert_id),
            "rule_id": str(rule["id"]),
            "ingredient_id": str(ingredient_id),
            "supplier_id": str(supplier_id),
            "triggered_at": now,
            "current_price_fen": int(current_price_fen),
            "baseline_price_fen": baseline_price,
            "breach_value": breach,
            "severity": severity,
            "status": "ACTIVE",
            "rule_type": rule_type,
        }
        triggered.append(alert_dict)

        asyncio.create_task(
            emit_event(
                event_type=PriceEventType.ALERT_TRIGGERED,
                tenant_id=tenant_id,
                stream_id=str(alert_id),
                payload={
                    "rule_id": str(rule["id"]),
                    "rule_type": rule_type,
                    "ingredient_id": str(ingredient_id),
                    "supplier_id": str(supplier_id),
                    "current_price_fen": int(current_price_fen),
                    "baseline_price_fen": baseline_price,
                    "breach_value": str(breach),
                    "severity": severity,
                },
                store_id=store_id,
                source_service="tx-supply",
            )
        )

    return triggered


async def _baseline_avg(
    db: AsyncSession,
    *,
    tenant_id: str,
    ingredient_id: str,
    window_start: datetime,
    window_end: datetime,
    exclude_recent_seconds: int = 0,
) -> Optional[float]:
    """取窗口期均价。可选 exclude_recent_seconds 排除刚刚写入的本条。"""
    cutoff_clause = ""
    params: dict[str, Any] = {
        "tid": str(tenant_id),
        "ing": str(ingredient_id),
        "ws": window_start,
        "we": window_end,
    }
    if exclude_recent_seconds > 0:
        cutoff_clause = " AND captured_at < :cutoff"
        params["cutoff"] = _now() - timedelta(seconds=exclude_recent_seconds)
    result = await db.execute(
        text(
            f"""
            SELECT AVG(unit_price_fen)::float AS avg_p
            FROM supplier_price_history
            WHERE tenant_id = :tid
              AND ingredient_id = :ing
              AND is_deleted = false
              AND captured_at BETWEEN :ws AND :we
              {cutoff_clause}
            """
        ),
        params,
    )
    avg_p = result.scalar()
    if avg_p is None:
        return None
    return float(avg_p)


# ──────────────────────────────────────────────────────────────────────
# 6. 预警规则 CRUD
# ──────────────────────────────────────────────────────────────────────


async def create_alert_rule(
    *,
    tenant_id: str,
    rule_type: str,
    threshold_value: Decimal,
    db: AsyncSession,
    ingredient_id: Optional[str] = None,
    baseline_window_days: int = 30,
    enabled: bool = True,
    created_by: Optional[str] = None,
) -> dict[str, Any]:
    if rule_type not in ALERT_RULE_TYPES:
        return {"ok": False, "error": f"rule_type 必须是 {ALERT_RULE_TYPES} 之一"}
    await _set_tenant(db, tenant_id)
    rule_id = uuid.uuid4()
    try:
        await db.execute(
            text(
                """
                INSERT INTO price_alert_rules
                    (id, tenant_id, ingredient_id, rule_type, threshold_value,
                     baseline_window_days, enabled, created_by)
                VALUES
                    (:id, :tid, :ing, :rt, :tv, :bw, :en, :cby)
                """
            ),
            {
                "id": rule_id,
                "tid": str(tenant_id),
                "ing": _uuid(ingredient_id),
                "rt": rule_type,
                "tv": threshold_value,
                "bw": int(baseline_window_days),
                "en": bool(enabled),
                "cby": _uuid(created_by),
            },
        )
        await db.flush()
    except SQLAlchemyError as exc:
        logger.error("price_alert_rule_create_failed", error=str(exc))
        return {"ok": False, "error": f"db_error: {exc}"}
    return {
        "ok": True,
        "data": {
            "id": str(rule_id),
            "ingredient_id": str(ingredient_id) if ingredient_id else None,
            "rule_type": rule_type,
            "threshold_value": threshold_value,
            "baseline_window_days": int(baseline_window_days),
            "enabled": bool(enabled),
        },
    }


async def list_alert_rules(
    *,
    tenant_id: str,
    db: AsyncSession,
    enabled_only: bool = False,
    ingredient_id: Optional[str] = None,
) -> dict[str, Any]:
    await _set_tenant(db, tenant_id)
    where = ["tenant_id = :tid", "is_deleted = false"]
    params: dict[str, Any] = {"tid": str(tenant_id)}
    if enabled_only:
        where.append("enabled = true")
    if ingredient_id:
        where.append("(ingredient_id = :ing OR ingredient_id IS NULL)")
        params["ing"] = str(ingredient_id)
    where_sql = " AND ".join(where)
    rows = await db.execute(
        text(
            f"""
            SELECT id, ingredient_id, rule_type, threshold_value,
                   baseline_window_days, enabled, created_at
            FROM price_alert_rules
            WHERE {where_sql}
            ORDER BY created_at DESC
            """
        ),
        params,
    )
    items = [_row_to_rule(dict(r)) for r in rows.mappings().all()]
    return {"ok": True, "items": items, "total": len(items)}


# ──────────────────────────────────────────────────────────────────────
# 7. 活跃预警查询 + 处理
# ──────────────────────────────────────────────────────────────────────


async def list_active_alerts(
    *,
    tenant_id: str,
    db: AsyncSession,
    severity: Optional[str] = None,
    ingredient_id: Optional[str] = None,
    limit: int = 100,
) -> dict[str, Any]:
    await _set_tenant(db, tenant_id)
    where = ["tenant_id = :tid", "status = 'ACTIVE'", "is_deleted = false"]
    params: dict[str, Any] = {"tid": str(tenant_id), "limit": int(limit)}
    if severity:
        if severity not in ALERT_SEVERITIES:
            return {"ok": False, "error": f"severity 必须是 {ALERT_SEVERITIES} 之一"}
        where.append("severity = :sev")
        params["sev"] = severity
    if ingredient_id:
        where.append("ingredient_id = :ing")
        params["ing"] = str(ingredient_id)
    where_sql = " AND ".join(where)
    rows = await db.execute(
        text(
            f"""
            SELECT id, rule_id, ingredient_id, supplier_id, triggered_at,
                   current_price_fen, baseline_price_fen, breach_value,
                   severity, status, acked_by, acked_at, ack_comment
            FROM price_alerts
            WHERE {where_sql}
            ORDER BY triggered_at DESC
            LIMIT :limit
            """
        ),
        params,
    )
    items = [_row_to_alert(dict(r)) for r in rows.mappings().all()]
    return {"ok": True, "items": items, "total": len(items)}


async def acknowledge_alert(
    *,
    tenant_id: str,
    alert_id: str,
    acked_by: str,
    db: AsyncSession,
    ack_comment: Optional[str] = None,
    new_status: str = "ACKED",
) -> dict[str, Any]:
    if new_status not in ("ACKED", "IGNORED"):
        return {"ok": False, "error": "new_status 必须是 ACKED 或 IGNORED"}
    if new_status not in ALERT_STATUSES:
        # 双保险（虽然上面已判过）
        return {"ok": False, "error": "非法 status"}
    await _set_tenant(db, tenant_id)

    found = await db.execute(
        text(
            "SELECT id, status FROM price_alerts "
            "WHERE id = :aid AND tenant_id = :tid AND is_deleted = false"
        ),
        {"aid": str(alert_id), "tid": str(tenant_id)},
    )
    row = found.mappings().one_or_none()
    if row is None:
        return {"ok": False, "error": "alert not found"}
    if row["status"] != "ACTIVE":
        return {"ok": False, "error": f"alert 已是 {row['status']} 状态"}

    try:
        await db.execute(
            text(
                """
                UPDATE price_alerts
                SET status = :ns,
                    acked_by = :ab,
                    acked_at = :at,
                    ack_comment = :cm
                WHERE id = :aid AND tenant_id = :tid
                """
            ),
            {
                "ns": new_status,
                "ab": _uuid(acked_by),
                "at": _now(),
                "cm": ack_comment,
                "aid": str(alert_id),
                "tid": str(tenant_id),
            },
        )
        await db.flush()
    except SQLAlchemyError as exc:
        logger.error("price_alert_ack_failed", error=str(exc), alert_id=str(alert_id))
        return {"ok": False, "error": f"db_error: {exc}"}

    return {
        "ok": True,
        "data": {
            "id": str(alert_id),
            "status": new_status,
            "acked_by": str(acked_by),
            "ack_comment": ack_comment,
        },
    }


# ──────────────────────────────────────────────────────────────────────
# 8. CSV 导出
# ──────────────────────────────────────────────────────────────────────


async def export_ledger_csv(
    *,
    tenant_id: str,
    db: AsyncSession,
    ingredient_id: Optional[str] = None,
    supplier_id: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> str:
    """导出 CSV 字符串（无分页，最多 10000 行）。"""
    result = await query_ledger(
        tenant_id=tenant_id,
        db=db,
        ingredient_id=ingredient_id,
        supplier_id=supplier_id,
        date_from=date_from,
        date_to=date_to,
        page=1,
        size=500,
    )
    rows = result.get("items", [])
    header = [
        "id",
        "ingredient_id",
        "supplier_id",
        "unit_price_fen",
        "quantity_unit",
        "captured_at",
        "source_doc_type",
        "source_doc_no",
        "store_id",
        "notes",
    ]
    out_lines = [",".join(header)]
    for r in rows:
        captured = r["captured_at"]
        captured_str = captured.isoformat() if hasattr(captured, "isoformat") else str(captured)
        notes = (r.get("notes") or "").replace(",", " ").replace("\n", " ")
        out_lines.append(
            ",".join(
                [
                    r["id"],
                    r["ingredient_id"],
                    r["supplier_id"],
                    str(r["unit_price_fen"]),
                    r.get("quantity_unit") or "",
                    captured_str,
                    r.get("source_doc_type") or "",
                    r.get("source_doc_no") or "",
                    r.get("store_id") or "",
                    notes,
                ]
            )
        )
    return "\n".join(out_lines) + "\n"
