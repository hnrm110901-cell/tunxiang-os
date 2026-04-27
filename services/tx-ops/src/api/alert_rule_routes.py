"""预警规则配置 API 路由（真实DB版）

数据源：
  规则列表  → compliance_alerts（按 alert_type 聚合推导规则配置）
  创建规则  → 无专属 alert_rules 表，INSERT 一条 compliance_alerts 作为规则锚点
  更新/开关 → 更新 compliance_alerts 对应记录
  测试规则  → 统计 compliance_alerts 中 alert_type 的历史触发次数

端点:
  GET    /api/v1/ops/alert-rules              规则列表
  POST   /api/v1/ops/alert-rules              创建规则
  PUT    /api/v1/ops/alert-rules/{id}         更新规则
  PATCH  /api/v1/ops/alert-rules/{id}/toggle  启用/禁用
  POST   /api/v1/ops/alert-rules/{id}/test    测试规则

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/ops/alert-rules", tags=["ops-alert-rules"])
log = structlog.get_logger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  常量
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_VALID_CATEGORIES = {"food_safety", "revenue", "cost", "service", "equipment", "inventory", "hr", "compliance"}
_VALID_SEVERITIES = {"critical", "high", "medium", "low"}
_VALID_CHANNELS = {"app", "sms", "wecom", "email", "webhook"}

# compliance_alerts.severity 映射（DB 值 → API 值）
_SEVERITY_MAP = {"critical": "critical", "warning": "high", "info": "low"}
_SEVERITY_RMAP = {"critical": "critical", "high": "warning", "medium": "info", "low": "info"}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class AlertCondition(BaseModel):
    metric: str = Field(..., description="监控指标: temperature/revenue/discount_rate/order_count/kds_time等")
    operator: str = Field(..., description="比较运算符: gt/gte/lt/lte/eq/neq")
    threshold: float = Field(..., description="阈值")
    unit: Optional[str] = Field(None, description="单位说明: fen/celsius/percent/minutes/count")
    duration_minutes: Optional[int] = Field(None, description="持续时间窗口（分钟），持续满足条件才触发")


class CreateAlertRuleRequest(BaseModel):
    name: str = Field(..., max_length=100, description="规则名称")
    description: Optional[str] = Field(None, description="规则描述")
    category: str = Field(..., description="规则类别")
    severity: str = Field("medium", description="告警级别")
    conditions: List[AlertCondition] = Field(..., min_length=1, description="触发条件（多条件AND）")
    notify_channels: List[str] = Field(default_factory=lambda: ["app"], description="通知渠道")
    notify_roles: List[str] = Field(default_factory=lambda: ["store_manager"], description="通知角色")
    apply_stores: Optional[List[str]] = Field(None, description="适用门店（空=全部）")
    cooldown_minutes: int = Field(30, description="告警冷却时间（分钟）")
    enabled: bool = Field(True, description="是否启用")


class UpdateAlertRuleRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    category: Optional[str] = None
    severity: Optional[str] = None
    conditions: Optional[List[AlertCondition]] = None
    notify_channels: Optional[List[str]] = None
    notify_roles: Optional[List[str]] = None
    apply_stores: Optional[List[str]] = None
    cooldown_minutes: Optional[int] = None
    enabled: Optional[bool] = None


class ToggleRequest(BaseModel):
    enabled: bool = Field(..., description="是否启用")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  内部辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _row_to_rule(row: Any) -> Dict[str, Any]:
    """将 compliance_alerts 聚合行转为预警规则对象。"""
    detail: Dict[str, Any] = {}
    if row.detail:
        try:
            detail = row.detail if isinstance(row.detail, dict) else json.loads(row.detail)
        except (ValueError, TypeError):
            detail = {}

    severity_raw = row.severity or "info"
    severity_api = _SEVERITY_MAP.get(severity_raw, "medium")

    return {
        "id": str(row.id),
        "name": row.title or row.alert_type,
        "description": detail.get("description", ""),
        "category": detail.get("category", row.alert_type or "compliance"),
        "severity": severity_api,
        "conditions": detail.get("conditions", []),
        "notify_channels": detail.get("notify_channels", ["app"]),
        "notify_roles": detail.get("notify_roles", ["store_manager"]),
        "apply_stores": detail.get("apply_stores"),
        "cooldown_minutes": detail.get("cooldown_minutes", 30),
        "enabled": row.status not in ("dismissed",),
        "trigger_count_today": row.trigger_count_today or 0,
        "last_triggered_at": str(row.last_triggered_at) if row.last_triggered_at else None,
        "created_at": str(row.created_at) if row.created_at else None,
        "updated_at": str(row.updated_at) if row.updated_at else None,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("")
async def list_alert_rules(
    category: Optional[str] = Query(None, description="按类别筛选"),
    enabled: Optional[bool] = Query(None, description="按启用状态筛选"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """预警规则列表（从 compliance_alerts 聚合推导）。"""
    log.info("alert_rules_listed", tenant_id=x_tenant_id, category=category, enabled=enabled)

    try:
        await _set_rls(db, x_tenant_id)

        # 以每种 alert_type 的最新一条 compliance_alert 作为规则定义行
        where_clauses = ["source = 'rule'"]
        params: Dict[str, Any] = {}

        if category:
            where_clauses.append("detail->>'category' = :category")
            params["category"] = category
        if enabled is not None:
            # disabled rules stored with status='dismissed'
            if enabled:
                where_clauses.append("status != 'dismissed'")
            else:
                where_clauses.append("status = 'dismissed'")

        where_sql = " AND ".join(where_clauses)

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM compliance_alerts WHERE {where_sql}"),
            params,
        )
        total = count_result.scalar() or 0

        offset = (page - 1) * size
        rows_result = await db.execute(
            text(
                f"""
                SELECT
                    id, title, alert_type, severity, status, detail,
                    created_at, updated_at,
                    (
                        SELECT COUNT(*) FROM compliance_alerts sub
                        WHERE sub.tenant_id = ca.tenant_id
                          AND sub.alert_type = ca.alert_type
                          AND sub.source != 'rule'
                          AND sub.created_at >= CURRENT_DATE
                    ) AS trigger_count_today,
                    (
                        SELECT MAX(sub2.created_at) FROM compliance_alerts sub2
                        WHERE sub2.tenant_id = ca.tenant_id
                          AND sub2.alert_type = ca.alert_type
                          AND sub2.source != 'rule'
                    ) AS last_triggered_at
                FROM compliance_alerts ca
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT :lim OFFSET :off
                """
            ),
            {**params, "lim": size, "off": offset},
        )
        rows = rows_result.fetchall()

        items = [_row_to_rule(r) for r in rows]
        return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}

    except SQLAlchemyError as exc:
        log.error("alert_rules_list_db_error", error=str(exc), tenant_id=x_tenant_id)
        return {"ok": True, "data": {"items": [], "total": 0, "page": page, "size": size}}


@router.post("", status_code=201)
async def create_alert_rule(
    body: CreateAlertRuleRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """创建预警规则（写入 compliance_alerts，source='rule'）。"""
    if body.category not in _VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"category 必须是 {_VALID_CATEGORIES} 之一")
    if body.severity not in _VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"severity 必须是 {_VALID_SEVERITIES} 之一")

    now = datetime.now(tz=timezone.utc)
    rule_id = str(uuid.uuid4())
    db_severity = _SEVERITY_RMAP.get(body.severity, "info")
    detail_payload = {
        "description": body.description,
        "category": body.category,
        "conditions": [c.model_dump() for c in body.conditions],
        "notify_channels": body.notify_channels,
        "notify_roles": body.notify_roles,
        "apply_stores": body.apply_stores,
        "cooldown_minutes": body.cooldown_minutes,
    }

    try:
        await _set_rls(db, x_tenant_id)
        await db.execute(
            text(
                """
                INSERT INTO compliance_alerts
                    (id, tenant_id, alert_type, severity, title, detail, status, source, created_at, updated_at)
                VALUES
                    (:id, :tid::uuid, :atype, :sev, :title, :detail::jsonb, :status, 'rule', :now, :now)
                """
            ),
            {
                "id": rule_id,
                "tid": x_tenant_id,
                "atype": body.category,
                "sev": db_severity,
                "title": body.name,
                "detail": json.dumps(detail_payload, ensure_ascii=False),
                "status": "open" if body.enabled else "dismissed",
                "now": now,
            },
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("alert_rule_create_db_error", error=str(exc), tenant_id=x_tenant_id)
        raise HTTPException(status_code=503, detail="数据库暂时不可用")

    new_rule: Dict[str, Any] = {
        "id": rule_id,
        "name": body.name,
        "description": body.description,
        "category": body.category,
        "severity": body.severity,
        "conditions": [c.model_dump() for c in body.conditions],
        "notify_channels": body.notify_channels,
        "notify_roles": body.notify_roles,
        "apply_stores": body.apply_stores,
        "cooldown_minutes": body.cooldown_minutes,
        "enabled": body.enabled,
        "trigger_count_today": 0,
        "last_triggered_at": None,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    log.info("alert_rule_created", rule_id=rule_id, name=body.name, category=body.category, tenant_id=x_tenant_id)
    return {"ok": True, "data": new_rule}


@router.put("/{rule_id}")
async def update_alert_rule(
    rule_id: str,
    body: UpdateAlertRuleRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """更新预警规则（更新 compliance_alerts 对应记录）。"""
    if body.category and body.category not in _VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"category 必须是 {_VALID_CATEGORIES} 之一")
    if body.severity and body.severity not in _VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"severity 必须是 {_VALID_SEVERITIES} 之一")

    try:
        await _set_rls(db, x_tenant_id)

        row_result = await db.execute(
            text(
                "SELECT id, title, alert_type, severity, status, detail, created_at, updated_at "
                "FROM compliance_alerts WHERE id = :rid AND source = 'rule'"
            ),
            {"rid": rule_id},
        )
        row = row_result.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="预警规则不存在")

        existing_detail: Dict[str, Any] = {}
        if row.detail:
            try:
                existing_detail = row.detail if isinstance(row.detail, dict) else json.loads(row.detail)
            except (ValueError, TypeError):
                existing_detail = {}

        update_data = body.model_dump(exclude_none=True)
        now = datetime.now(tz=timezone.utc)

        new_title = update_data.get("name", row.title)
        new_severity_api = update_data.get("severity", _SEVERITY_MAP.get(row.severity, "medium"))
        new_db_severity = _SEVERITY_RMAP.get(new_severity_api, "info")

        for field in (
            "description",
            "category",
            "conditions",
            "notify_channels",
            "notify_roles",
            "apply_stores",
            "cooldown_minutes",
        ):
            if field in update_data:
                val = update_data[field]
                if field == "conditions" and val:
                    val = [c.model_dump() if hasattr(c, "model_dump") else c for c in val]
                existing_detail[field] = val

        new_status = row.status
        if "enabled" in update_data:
            new_status = "open" if update_data["enabled"] else "dismissed"

        await db.execute(
            text(
                """
                UPDATE compliance_alerts
                SET title = :title, severity = :sev, status = :status,
                    detail = :detail::jsonb, updated_at = :now
                WHERE id = :rid
                """
            ),
            {
                "title": new_title,
                "sev": new_db_severity,
                "status": new_status,
                "detail": json.dumps(existing_detail, ensure_ascii=False),
                "now": now,
                "rid": rule_id,
            },
        )
        await db.commit()

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("alert_rule_update_db_error", error=str(exc), rule_id=rule_id, tenant_id=x_tenant_id)
        raise HTTPException(status_code=503, detail="数据库暂时不可用")

    log.info("alert_rule_updated", rule_id=rule_id, tenant_id=x_tenant_id)

    updated = {
        "id": rule_id,
        "name": new_title,
        "description": existing_detail.get("description"),
        "category": existing_detail.get("category", row.alert_type),
        "severity": new_severity_api,
        "conditions": existing_detail.get("conditions", []),
        "notify_channels": existing_detail.get("notify_channels", ["app"]),
        "notify_roles": existing_detail.get("notify_roles", ["store_manager"]),
        "apply_stores": existing_detail.get("apply_stores"),
        "cooldown_minutes": existing_detail.get("cooldown_minutes", 30),
        "enabled": new_status != "dismissed",
        "created_at": str(row.created_at) if row.created_at else None,
        "updated_at": now.isoformat(),
    }
    return {"ok": True, "data": updated}


@router.patch("/{rule_id}/toggle")
async def toggle_alert_rule(
    rule_id: str,
    body: ToggleRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """启用/禁用预警规则（更新 compliance_alerts.status）。"""
    log.info("alert_rule_toggled", rule_id=rule_id, enabled=body.enabled, tenant_id=x_tenant_id)

    try:
        await _set_rls(db, x_tenant_id)

        row_result = await db.execute(
            text(
                "SELECT id, title, alert_type, severity, status, detail, created_at, updated_at "
                "FROM compliance_alerts WHERE id = :rid AND source = 'rule'"
            ),
            {"rid": rule_id},
        )
        row = row_result.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="预警规则不存在")

        now = datetime.now(tz=timezone.utc)
        new_status = "open" if body.enabled else "dismissed"

        await db.execute(
            text("UPDATE compliance_alerts SET status = :status, updated_at = :now WHERE id = :rid"),
            {"status": new_status, "now": now, "rid": rule_id},
        )
        await db.commit()

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        log.error("alert_rule_toggle_db_error", error=str(exc), rule_id=rule_id, tenant_id=x_tenant_id)
        raise HTTPException(status_code=503, detail="数据库暂时不可用")

    existing_detail: Dict[str, Any] = {}
    if row.detail:
        try:
            existing_detail = row.detail if isinstance(row.detail, dict) else json.loads(row.detail)
        except (ValueError, TypeError):
            existing_detail = {}

    updated = {
        "id": rule_id,
        "name": row.title,
        "enabled": body.enabled,
        "updated_at": now.isoformat(),
        "category": existing_detail.get("category", row.alert_type),
        "severity": _SEVERITY_MAP.get(row.severity, "medium"),
    }
    return {"ok": True, "data": updated}


@router.post("/{rule_id}/test")
async def test_alert_rule(
    rule_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """测试预警规则（统计 compliance_alerts 中该类型的历史触发次数）。"""
    log.info("alert_rule_tested", rule_id=rule_id, tenant_id=x_tenant_id)

    try:
        await _set_rls(db, x_tenant_id)

        row_result = await db.execute(
            text(
                "SELECT id, title, alert_type, severity, status, detail "
                "FROM compliance_alerts WHERE id = :rid AND source = 'rule'"
            ),
            {"rid": rule_id},
        )
        row = row_result.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="预警规则不存在")

        is_enabled = row.status != "dismissed"

        # 统计该 alert_type 今日实际触发数量（排除 rule 锚点行）
        count_result = await db.execute(
            text(
                """
                SELECT COUNT(*) AS cnt,
                       ARRAY_AGG(DISTINCT store_id::text) FILTER (WHERE store_id IS NOT NULL) AS stores
                FROM compliance_alerts
                WHERE alert_type = :atype
                  AND source != 'rule'
                  AND created_at >= CURRENT_DATE
                """
            ),
            {"atype": row.alert_type},
        )
        count_row = count_result.fetchone()
        matched_stores = count_row.stores or [] if count_row else []

        existing_detail: Dict[str, Any] = {}
        if row.detail:
            try:
                existing_detail = row.detail if isinstance(row.detail, dict) else json.loads(row.detail)
            except (ValueError, TypeError):
                existing_detail = {}

        conditions = existing_detail.get("conditions", [])
        threshold = conditions[0].get("threshold", 0) if conditions else 0

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("alert_rule_test_db_error", error=str(exc), rule_id=rule_id, tenant_id=x_tenant_id)
        raise HTTPException(status_code=503, detail="数据库暂时不可用")

    return {
        "ok": True,
        "data": {
            "rule_id": rule_id,
            "rule_name": row.title,
            "test_result": "triggered" if is_enabled else "skipped_disabled",
            "matched_stores": matched_stores if is_enabled else [],
            "sample_alert": {
                "message": f"[测试] {row.title} - 今日触发 {count_row.cnt if count_row else 0} 次",
                "severity": _SEVERITY_MAP.get(row.severity, "medium"),
                "threshold": threshold,
            }
            if is_enabled
            else None,
            "tested_at": datetime.now(tz=timezone.utc).isoformat(),
        },
    }
