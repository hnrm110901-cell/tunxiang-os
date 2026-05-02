"""预警闭环引擎 API — BI-2.2

8 个端点：
  GET    /api/v1/analytics/alerts/rules              — 列出所有预警规则
  PUT    /api/v1/analytics/alerts/rules/{rule_id}     — 更新单条规则
  GET    /api/v1/analytics/alerts/active              — 活跃告警列表
  GET    /api/v1/analytics/alerts/{alert_id}          — 告警详情 + 处理历史
  POST   /api/v1/analytics/alerts/{alert_id}/acknowledge — 认领告警
  POST   /api/v1/analytics/alerts/{alert_id}/resolve     — 解决告警
  POST   /api/v1/analytics/alerts/{alert_id}/close       — 关闭告警
  GET    /api/v1/analytics/alerts/stats                — 告警统计
"""

from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..alert.engine import AlertEngine
from ..alert.models import AlertRule, AlertSeverity, AlertStatus
from ..alert.notifier import AlertNotifier
from ..alert.rules_registry import DEFAULT_ALERT_RULES, RULES_BY_ID

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/analytics/alerts", tags=["alerts"])

_engine = AlertEngine()
_notifier = AlertNotifier()


# ─── 请求/响应模型 ───────────────────────────────────────────────────

class RuleUpdateRequest(BaseModel):
    """更新规则请求"""
    enabled: Optional[bool] = None
    threshold: Optional[float] = None
    severity: Optional[str] = None
    cooldown_minutes: Optional[int] = None
    notify_roles: Optional[list[str]] = None
    notify_channels: Optional[list[str]] = None

class AcknowledgeRequest(BaseModel):
    """认领告警请求"""
    user_id: str

class ResolveRequest(BaseModel):
    """解决告警请求"""
    user_id: str
    notes: str = ""
    resolution_type: str = "fixed"


# ─── 1. 列出所有预警规则 ─────────────────────────────────────────────

@router.get("/rules")
async def list_rules(
    domain: Optional[str] = Query(None, description="按域筛选"),
    enabled_only: bool = Query(False, description="仅返回启用的规则"),
) -> dict:
    """列出所有预置预警规则，可按域筛选"""
    rules = DEFAULT_ALERT_RULES
    if domain:
        rules = [r for r in rules if r.domain == domain]
    if enabled_only:
        rules = [r for r in rules if r.enabled]

    return {
        "ok": True,
        "data": {
            "rules": [r.model_dump() for r in rules],
            "total": len(rules),
            "domains": list(set(r.domain for r in rules)),
        },
    }


# ─── 2. 更新单条规则 ─────────────────────────────────────────────────

@router.put("/rules/{rule_id}")
async def update_rule(rule_id: str, body: RuleUpdateRequest) -> dict:
    """更新预警规则配置（启用/禁用、改阈值、改严重级别等）

    对规则做深拷贝后修改，避免污染模块级常量 RULES_BY_ID / DEFAULT_ALERT_RULES。
    修改仅进程生命周期内有效，重启后恢复预置值（后续版本将迁移到 DB 持久化）。
    """
    template: AlertRule | None = RULES_BY_ID.get(rule_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"规则 {rule_id} 不存在")

    # 深拷贝后修改，不影响模块级常量
    rule = template.model_copy(deep=True)

    if body.enabled is not None:
        rule.enabled = body.enabled
    if body.threshold is not None:
        rule.threshold = body.threshold
    if body.severity is not None:
        try:
            rule.severity = AlertSeverity(body.severity)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"无效的严重级别: {body.severity}")
    if body.cooldown_minutes is not None:
        rule.cooldown_minutes = body.cooldown_minutes
    if body.notify_roles is not None:
        rule.notify_roles = body.notify_roles
    if body.notify_channels is not None:
        rule.notify_channels = body.notify_channels

    # 写入 writable 副本供 engine 使用（同时更新 DEFAULT_ALERT_RULES 和 RULES_BY_ID）
    RULES_BY_ID[rule_id] = rule
    for i, r in enumerate(DEFAULT_ALERT_RULES):
        if r.rule_id == rule_id:
            DEFAULT_ALERT_RULES[i] = rule
            break
    log.info("alert_rule_updated", rule_id=rule_id, updates=body.model_dump(exclude_none=True))
    return {"ok": True, "data": {"rule": rule.model_dump()}}


# ─── 3. 活跃告警列表 ─────────────────────────────────────────────────

@router.get("/active")
async def list_active_alerts(
    severity: Optional[str] = Query(None, description="按严重级别筛选: P0/P1/P2/P3"),
    domain: Optional[str] = Query(None, description="按业务域筛选"),
    store_id: Optional[str] = Query(None, description="按门店筛选"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取活跃告警列表（fired/acknowledged/processing 状态）"""
    try:
        alerts = await _engine.get_active_alerts(
            db=db, tenant_id=x_tenant_id,
            severity=severity, domain=domain, store_id=store_id,
            limit=limit, offset=offset,
        )
        return {
            "ok": True,
            "data": {
                "alerts": [a.model_dump() for a in alerts],
                "total": len(alerts),
                "limit": limit,
                "offset": offset,
            },
        }
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("list_active_alerts.error", tenant_id=x_tenant_id, exc_info=True)
        raise HTTPException(status_code=500, detail="告警查询失败") from exc


# ─── 4. 告警详情 ─────────────────────────────────────────────────────

@router.get("/{alert_id}")
async def get_alert_detail(
    alert_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取单个告警的完整详情"""
    try:
        alert = await _engine.get_alert(db, alert_id)
        if not alert:
            raise HTTPException(status_code=404, detail=f"告警 {alert_id} 不存在")
        if alert.tenant_id != x_tenant_id:
            raise HTTPException(status_code=403, detail="无权访问该告警")

        return {"ok": True, "data": {"alert": alert.model_dump()}}
    except HTTPException:
        raise
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("get_alert_detail.error", alert_id=alert_id, exc_info=True)
        raise HTTPException(status_code=500, detail="告警查询失败") from exc


# ─── 5. 认领告警 ─────────────────────────────────────────────────────

@router.post("/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    body: AcknowledgeRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """认领告警，指定处理人"""
    try:
        # 先检查租户所有权（不执行变更）
        alert = await _engine.get_alert(db, alert_id)
        if not alert:
            raise HTTPException(status_code=404, detail="告警不存在")
        if alert.tenant_id != x_tenant_id:
            raise HTTPException(status_code=403, detail="无权操作该告警")
        # 再执行状态变更
        alert = await _engine.acknowledge(db, alert_id, body.user_id)
        if not alert:
            raise HTTPException(status_code=400, detail="告警状态不允许认领")

        return {"ok": True, "data": {"alert": alert.model_dump()}}
    except HTTPException:
        raise
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("acknowledge_alert.error", alert_id=alert_id, exc_info=True)
        raise HTTPException(status_code=500, detail="告警认领失败") from exc


# ─── 6. 解决告警 ─────────────────────────────────────────────────────

@router.post("/{alert_id}/resolve")
async def resolve_alert(
    alert_id: str,
    body: ResolveRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """解决告警，记录解决方案"""
    try:
        # 先检查租户所有权（不执行变更）
        alert = await _engine.get_alert(db, alert_id)
        if not alert:
            raise HTTPException(status_code=404, detail="告警不存在")
        if alert.tenant_id != x_tenant_id:
            raise HTTPException(status_code=403, detail="无权操作该告警")
        # 再执行状态变更
        alert = await _engine.resolve(db, alert_id, body.user_id, body.notes, body.resolution_type)
        if not alert:
            raise HTTPException(status_code=400, detail="告警状态不允许解决")

        return {"ok": True, "data": {"alert": alert.model_dump()}}
    except HTTPException:
        raise
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("resolve_alert.error", alert_id=alert_id, exc_info=True)
        raise HTTPException(status_code=500, detail="告警解决失败") from exc


# ─── 7. 关闭告警 ─────────────────────────────────────────────────────

@router.post("/{alert_id}/close")
async def close_alert(
    alert_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """关闭告警（验证通过后关闭，仅 resolved 状态可关闭）"""
    try:
        # 先检查租户所有权（不执行变更）
        alert = await _engine.get_alert(db, alert_id)
        if not alert:
            raise HTTPException(status_code=404, detail="告警不存在")
        if alert.tenant_id != x_tenant_id:
            raise HTTPException(status_code=403, detail="无权操作该告警")
        # 再执行状态变更
        alert = await _engine.close(db, alert_id)
        if not alert:
            raise HTTPException(status_code=400, detail="告警状态不允许关闭（需先解决）")

        return {"ok": True, "data": {"alert": alert.model_dump()}}
    except HTTPException:
        raise
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("close_alert.error", alert_id=alert_id, exc_info=True)
        raise HTTPException(status_code=500, detail="告警关闭失败") from exc


# ─── 8. 告警统计 ─────────────────────────────────────────────────────

@router.get("/stats")
async def get_alert_stats(
    store_id: Optional[str] = Query(None, description="按门店筛选"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取告警统计数据（按严重级别、状态、域分布）"""
    try:
        stats = await _engine.get_stats(db=db, tenant_id=x_tenant_id, store_id=store_id)
        return {
            "ok": True,
            "data": {
                "total": stats.total,
                "by_severity": stats.by_severity,
                "by_status": stats.by_status,
                "by_domain": stats.by_domain,
                "sla_breached_count": stats.sla_breached_count,
                "avg_resolution_minutes": stats.avg_resolution_minutes,
            },
        }
    except (OperationalError, SQLAlchemyError) as exc:
        log.error("get_alert_stats.error", tenant_id=x_tenant_id, exc_info=True)
        raise HTTPException(status_code=500, detail="告警统计查询失败") from exc
