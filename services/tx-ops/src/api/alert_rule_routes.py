"""预警规则配置 API 路由（Mock 数据版）

端点:
  GET    /api/v1/ops/alert-rules              规则列表
  POST   /api/v1/ops/alert-rules              创建规则
  PUT    /api/v1/ops/alert-rules/{id}         更新规则
  PATCH  /api/v1/ops/alert-rules/{id}/toggle  启用/禁用
  POST   /api/v1/ops/alert-rules/{id}/test    测试规则

统一响应格式: {"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/ops/alert-rules", tags=["ops-alert-rules"])
log = structlog.get_logger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  常量
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_VALID_CATEGORIES = {"food_safety", "revenue", "cost", "service", "equipment", "inventory", "hr", "compliance"}
_VALID_SEVERITIES = {"critical", "high", "medium", "low"}
_VALID_CHANNELS = {"app", "sms", "wecom", "email", "webhook"}

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
#  Mock 数据
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_MOCK_RULES: List[Dict[str, Any]] = [
    {
        "id": "rule-001",
        "name": "冷库温度异常",
        "description": "冷库温度高于-15度持续10分钟，触发食安告警",
        "category": "food_safety",
        "severity": "critical",
        "conditions": [
            {"metric": "freezer_temperature", "operator": "gt", "threshold": -15, "unit": "celsius", "duration_minutes": 10},
        ],
        "notify_channels": ["app", "sms", "wecom"],
        "notify_roles": ["store_manager", "food_safety_officer", "regional_manager"],
        "apply_stores": None,
        "cooldown_minutes": 15,
        "enabled": True,
        "trigger_count_today": 1,
        "last_triggered_at": "2026-04-10T09:15:00+08:00",
        "created_at": "2026-03-01T10:00:00+08:00",
        "updated_at": "2026-04-05T14:00:00+08:00",
    },
    {
        "id": "rule-002",
        "name": "折扣率异常告警",
        "description": "单笔订单折扣率超过30%且未经主管审批",
        "category": "revenue",
        "severity": "high",
        "conditions": [
            {"metric": "discount_rate", "operator": "gt", "threshold": 30, "unit": "percent", "duration_minutes": None},
        ],
        "notify_channels": ["app", "wecom"],
        "notify_roles": ["store_manager", "cashier_supervisor"],
        "apply_stores": None,
        "cooldown_minutes": 5,
        "enabled": True,
        "trigger_count_today": 3,
        "last_triggered_at": "2026-04-10T13:22:00+08:00",
        "created_at": "2026-02-15T09:00:00+08:00",
        "updated_at": "2026-03-20T11:00:00+08:00",
    },
    {
        "id": "rule-003",
        "name": "KDS出餐超时",
        "description": "出餐时间超过15分钟",
        "category": "service",
        "severity": "high",
        "conditions": [
            {"metric": "kds_prepare_time", "operator": "gt", "threshold": 15, "unit": "minutes", "duration_minutes": None},
        ],
        "notify_channels": ["app"],
        "notify_roles": ["kitchen_manager", "store_manager"],
        "apply_stores": None,
        "cooldown_minutes": 10,
        "enabled": True,
        "trigger_count_today": 5,
        "last_triggered_at": "2026-04-10T12:35:00+08:00",
        "created_at": "2026-02-01T10:00:00+08:00",
        "updated_at": "2026-02-01T10:00:00+08:00",
    },
    {
        "id": "rule-004",
        "name": "日营收低于目标80%",
        "description": "门店截至当前时间点的营收低于日目标的80%（按时间进度换算）",
        "category": "revenue",
        "severity": "medium",
        "conditions": [
            {"metric": "revenue_achievement_rate", "operator": "lt", "threshold": 80, "unit": "percent", "duration_minutes": None},
        ],
        "notify_channels": ["app", "wecom"],
        "notify_roles": ["store_manager", "regional_manager"],
        "apply_stores": None,
        "cooldown_minutes": 60,
        "enabled": True,
        "trigger_count_today": 2,
        "last_triggered_at": "2026-04-10T14:00:00+08:00",
        "created_at": "2026-03-10T08:00:00+08:00",
        "updated_at": "2026-03-10T08:00:00+08:00",
    },
    {
        "id": "rule-005",
        "name": "食材库存低位预警",
        "description": "关键食材库存低于安全库存的30%",
        "category": "inventory",
        "severity": "medium",
        "conditions": [
            {"metric": "inventory_ratio", "operator": "lt", "threshold": 30, "unit": "percent", "duration_minutes": None},
        ],
        "notify_channels": ["app"],
        "notify_roles": ["store_manager", "procurement"],
        "apply_stores": None,
        "cooldown_minutes": 120,
        "enabled": True,
        "trigger_count_today": 1,
        "last_triggered_at": "2026-04-10T08:30:00+08:00",
        "created_at": "2026-02-20T10:00:00+08:00",
        "updated_at": "2026-02-20T10:00:00+08:00",
    },
    {
        "id": "rule-006",
        "name": "员工迟到告警",
        "description": "员工打卡时间超过排班开始时间15分钟",
        "category": "hr",
        "severity": "low",
        "conditions": [
            {"metric": "clock_in_delay", "operator": "gt", "threshold": 15, "unit": "minutes", "duration_minutes": None},
        ],
        "notify_channels": ["app"],
        "notify_roles": ["store_manager"],
        "apply_stores": None,
        "cooldown_minutes": 0,
        "enabled": False,
        "trigger_count_today": 0,
        "last_triggered_at": None,
        "created_at": "2026-03-15T10:00:00+08:00",
        "updated_at": "2026-04-01T09:00:00+08:00",
    },
    {
        "id": "rule-007",
        "name": "食材成本率超标",
        "description": "门店日食材成本率超过38%",
        "category": "cost",
        "severity": "medium",
        "conditions": [
            {"metric": "food_cost_rate", "operator": "gt", "threshold": 38, "unit": "percent", "duration_minutes": None},
        ],
        "notify_channels": ["app", "wecom"],
        "notify_roles": ["store_manager", "finance_manager"],
        "apply_stores": None,
        "cooldown_minutes": 240,
        "enabled": True,
        "trigger_count_today": 0,
        "last_triggered_at": "2026-04-08T20:00:00+08:00",
        "created_at": "2026-03-01T10:00:00+08:00",
        "updated_at": "2026-03-01T10:00:00+08:00",
    },
    {
        "id": "rule-008",
        "name": "设备离线告警",
        "description": "POS/KDS/摄像头等设备离线超过5分钟",
        "category": "equipment",
        "severity": "high",
        "conditions": [
            {"metric": "device_offline_duration", "operator": "gt", "threshold": 5, "unit": "minutes", "duration_minutes": 5},
        ],
        "notify_channels": ["app", "sms"],
        "notify_roles": ["store_manager", "it_support"],
        "apply_stores": None,
        "cooldown_minutes": 30,
        "enabled": True,
        "trigger_count_today": 1,
        "last_triggered_at": "2026-04-10T10:15:00+08:00",
        "created_at": "2026-02-10T10:00:00+08:00",
        "updated_at": "2026-02-10T10:00:00+08:00",
    },
]


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
) -> Dict[str, Any]:
    """预警规则列表。"""
    log.info("alert_rules_listed", tenant_id=x_tenant_id, category=category, enabled=enabled)

    filtered = _MOCK_RULES[:]
    if category:
        filtered = [r for r in filtered if r["category"] == category]
    if enabled is not None:
        filtered = [r for r in filtered if r["enabled"] == enabled]

    total = len(filtered)
    offset = (page - 1) * size
    items = filtered[offset: offset + size]

    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}


@router.post("", status_code=201)
async def create_alert_rule(
    body: CreateAlertRuleRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """创建预警规则。"""
    if body.category not in _VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"category 必须是 {_VALID_CATEGORIES} 之一")
    if body.severity not in _VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"severity 必须是 {_VALID_SEVERITIES} 之一")

    now = datetime.now(tz=timezone.utc).isoformat()
    new_rule: Dict[str, Any] = {
        "id": f"rule-{uuid.uuid4().hex[:8]}",
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
        "created_at": now,
        "updated_at": now,
    }

    log.info("alert_rule_created", rule_id=new_rule["id"], name=body.name,
             category=body.category, tenant_id=x_tenant_id)
    return {"ok": True, "data": new_rule}


@router.put("/{rule_id}")
async def update_alert_rule(
    rule_id: str,
    body: UpdateAlertRuleRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """更新预警规则。"""
    if body.category and body.category not in _VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"category 必须是 {_VALID_CATEGORIES} 之一")
    if body.severity and body.severity not in _VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"severity 必须是 {_VALID_SEVERITIES} 之一")

    log.info("alert_rule_updated", rule_id=rule_id, tenant_id=x_tenant_id)

    for r in _MOCK_RULES:
        if r["id"] == rule_id:
            updated = {**r, "updated_at": datetime.now(tz=timezone.utc).isoformat()}
            update_data = body.model_dump(exclude_none=True)
            if "conditions" in update_data:
                update_data["conditions"] = [c.model_dump() if hasattr(c, "model_dump") else c for c in update_data["conditions"]]
            updated.update(update_data)
            return {"ok": True, "data": updated}

    raise HTTPException(status_code=404, detail="预警规则不存在")


@router.patch("/{rule_id}/toggle")
async def toggle_alert_rule(
    rule_id: str,
    body: ToggleRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """启用/禁用预警规则。"""
    log.info("alert_rule_toggled", rule_id=rule_id, enabled=body.enabled, tenant_id=x_tenant_id)

    for r in _MOCK_RULES:
        if r["id"] == rule_id:
            updated = {**r, "enabled": body.enabled, "updated_at": datetime.now(tz=timezone.utc).isoformat()}
            return {"ok": True, "data": updated}

    raise HTTPException(status_code=404, detail="预警规则不存在")


@router.post("/{rule_id}/test")
async def test_alert_rule(
    rule_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> Dict[str, Any]:
    """测试预警规则（使用模拟数据检查是否会触发）。"""
    log.info("alert_rule_tested", rule_id=rule_id, tenant_id=x_tenant_id)

    for r in _MOCK_RULES:
        if r["id"] == rule_id:
            # Mock: 返回模拟的测试结果
            return {
                "ok": True,
                "data": {
                    "rule_id": rule_id,
                    "rule_name": r["name"],
                    "test_result": "triggered" if r["enabled"] else "skipped_disabled",
                    "matched_stores": ["store-001", "store-003"] if r["enabled"] else [],
                    "sample_alert": {
                        "message": f"[测试] {r['name']} - 芙蓉广场店触发告警",
                        "severity": r["severity"],
                        "metric_value": r["conditions"][0]["threshold"] * 1.1 if r["conditions"] else 0,
                        "threshold": r["conditions"][0]["threshold"] if r["conditions"] else 0,
                    } if r["enabled"] else None,
                    "tested_at": datetime.now(tz=timezone.utc).isoformat(),
                },
            }

    raise HTTPException(status_code=404, detail="预警规则不存在")
