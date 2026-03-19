"""
信号路由规则管理 API

让运营后台可以动态增删改 SignalBus 路由规则，无需改代码。

GET    /api/v1/signal-routing/rules          — 列出所有规则（支持 enabled 过滤）
POST   /api/v1/signal-routing/rules          — 创建新规则
PATCH  /api/v1/signal-routing/rules/{id}     — 更新规则（enabled/params/priority）
DELETE /api/v1/signal-routing/rules/{id}     — 禁用规则（软删除：设 enabled=false）
POST   /api/v1/signal-routing/run/{store_id} — 立即触发规则驱动扫描（调试/手动）
"""

from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.dependencies import get_current_active_user, get_db
from ..models.user import User
from ..models.signal_routing_rule import SignalRoutingRule

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/signal-routing", tags=["signal_routing"])


# ── Pydantic schema ──────────────────────────────────────────────────────────

class RuleCreate(BaseModel):
    condition_type:   str = Field(..., description="review_negative | inventory_near_expiry | large_table_booking | revenue_drop | churn_risk | custom")
    condition_params: Dict[str, Any] = Field(default_factory=dict)
    action_type:      str = Field(..., description="repair_journey | waste_push | referral_engine | wechat_alert | celery_task | webhook")
    action_params:    Dict[str, Any] = Field(default_factory=dict)
    priority:         int = Field(100, ge=1, le=999)
    description:      Optional[str] = None


class RulePatch(BaseModel):
    enabled:          Optional[bool] = None
    condition_params: Optional[Dict[str, Any]] = None
    action_params:    Optional[Dict[str, Any]] = None
    priority:         Optional[int] = Field(None, ge=1, le=999)
    description:      Optional[str] = None


def _rule_to_dict(r: SignalRoutingRule) -> Dict[str, Any]:
    return {
        "id":               r.id,
        "condition_type":   r.condition_type,
        "condition_params": r.condition_params or {},
        "action_type":      r.action_type,
        "action_params":    r.action_params or {},
        "priority":         r.priority,
        "enabled":          r.enabled,
        "description":      r.description,
        "created_by":       r.created_by,
        "created_at":       r.created_at.isoformat() if r.created_at else None,
        "updated_at":       r.updated_at.isoformat() if r.updated_at else None,
    }


# ── 端点 ─────────────────────────────────────────────────────────────────────

@router.get("/rules")
async def list_rules(
    enabled: Optional[bool] = Query(None, description="true=只看启用，false=只看禁用，不传=全部"),
    db:      AsyncSession = Depends(get_db),
    _:       User         = Depends(get_current_active_user),
):
    """列出信号路由规则，按 priority 升序。"""
    stmt = select(SignalRoutingRule).order_by(SignalRoutingRule.priority)
    if enabled is not None:
        stmt = stmt.where(SignalRoutingRule.enabled == enabled)
    rows = (await db.execute(stmt)).scalars().all()
    return {"rules": [_rule_to_dict(r) for r in rows], "total": len(rows)}


@router.post("/rules", status_code=201)
async def create_rule(
    body: RuleCreate,
    db:   AsyncSession = Depends(get_db),
    user: User         = Depends(get_current_active_user),
):
    """创建新路由规则。"""
    rule = SignalRoutingRule(
        condition_type   = body.condition_type,
        condition_params = body.condition_params,
        action_type      = body.action_type,
        action_params    = body.action_params,
        priority         = body.priority,
        enabled          = True,
        description      = body.description,
        created_by       = str(user.id) if hasattr(user, "id") else None,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return _rule_to_dict(rule)


@router.patch("/rules/{rule_id}")
async def patch_rule(
    rule_id: int,
    body:    RulePatch,
    db:      AsyncSession = Depends(get_db),
    _:       User         = Depends(get_current_active_user),
):
    """更新路由规则（部分更新）。"""
    rule = await db.get(SignalRoutingRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    if body.enabled is not None:
        rule.enabled = body.enabled
    if body.condition_params is not None:
        rule.condition_params = body.condition_params
    if body.action_params is not None:
        rule.action_params = body.action_params
    if body.priority is not None:
        rule.priority = body.priority
    if body.description is not None:
        rule.description = body.description
    await db.commit()
    await db.refresh(rule)
    return _rule_to_dict(rule)


@router.delete("/rules/{rule_id}", status_code=204)
async def disable_rule(
    rule_id: int,
    db:      AsyncSession = Depends(get_db),
    _:       User         = Depends(get_current_active_user),
):
    """禁用规则（软删除：设 enabled=false，保留审计记录）。"""
    rule = await db.get(SignalRoutingRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    rule.enabled = False
    await db.commit()


@router.post("/run/{store_id}")
async def run_scan(
    store_id: str,
    db:       AsyncSession = Depends(get_db),
    _:        User         = Depends(get_current_active_user),
):
    """手动触发指定门店的规则驱动信号扫描（调试 / 运营手动补扫）。"""
    from ..services.signal_bus import run_rule_driven_scan
    result = await run_rule_driven_scan(store_id=store_id, db=db)
    return result
