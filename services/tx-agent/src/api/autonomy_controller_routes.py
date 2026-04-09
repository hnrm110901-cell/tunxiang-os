"""Agent 自治等级控制器 — L1/L2/L3 分级自治

端点:
  GET  /api/v1/agent/autonomy/config              — 获取各Agent自治等级配置
  PUT  /api/v1/agent/autonomy/config/{agent_id}    — 设置Agent自治等级
  GET  /api/v1/agent/autonomy/actions              — 自动执行日志
  GET  /api/v1/agent/autonomy/pending              — 等待人工确认的高风险操作

自治等级说明:
  L1: 仅建议（人必须确认后才执行）
  L2: 低风险操作自动执行 + 高风险操作需人确认
  L3: 大部分操作自动执行 + 人监督审计
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/agent/autonomy", tags=["agent-autonomy"])

# ── 自动执行规则引擎 ─────────────────────────────────────────────────────────

AUTO_EXECUTE_RULES: dict[str, dict[str, list[str]]] = {
    "discount_guardian": {
        "L2": ["freeze_suspicious_coupon", "alert_manager"],
        "L3": ["freeze_suspicious_coupon", "alert_manager", "auto_adjust_discount_limit"],
    },
    "inventory_agent": {
        "L2": ["auto_soldout_sync", "alert_low_stock"],
        "L3": ["auto_soldout_sync", "alert_low_stock", "auto_generate_purchase_order"],
    },
    "scheduling_agent": {
        "L2": ["suggest_schedule", "alert_understaffed"],
        "L3": ["suggest_schedule", "alert_understaffed", "auto_publish_schedule"],
    },
    "smart_menu": {
        "L2": ["alert_poor_performer"],
        "L3": ["alert_poor_performer", "auto_soldout_poor_dish"],
    },
    "serve_dispatch": {
        "L2": ["alert_slow_dish"],
        "L3": ["alert_slow_dish", "auto_reprioritize_queue"],
    },
    "member_insight": {
        "L2": ["alert_churn_risk"],
        "L3": ["alert_churn_risk", "auto_trigger_recall_campaign"],
    },
    "finance_audit": {
        "L2": ["alert_anomaly"],
        "L3": ["alert_anomaly", "auto_freeze_suspicious_account"],
    },
    "store_inspect": {
        "L2": ["alert_violation"],
        "L3": ["alert_violation", "auto_create_rectification_task"],
    },
    "private_ops": {
        "L2": ["suggest_campaign"],
        "L3": ["suggest_campaign", "auto_send_campaign"],
    },
}

AUTONOMY_LEVELS = {
    1: {"label": "L1", "name": "仅建议", "description": "人必须确认后才执行"},
    2: {"label": "L2", "name": "半自动", "description": "低风险自动执行 + 高风险需人确认"},
    3: {"label": "L3", "name": "全自治", "description": "大部分操作自动执行 + 人监督审计"},
}


# ── 请求/响应模型 ─────────────────────────────────────────────────────────────

class AutonomyConfigUpdate(BaseModel):
    level: int = Field(..., ge=1, le=3, description="自治等级: 1/2/3")
    auto_rules: list[str] | None = Field(None, description="自定义自动执行规则列表（为空则使用默认）")


# ── DB 依赖 ──────────────────────────────────────────────────────────────────

async def _get_db(
    x_tenant_id: str = Header("default", alias="X-Tenant-ID"),
) -> AsyncSession:
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def get_auto_actions(agent_id: str, level: int) -> list[str]:
    """根据 agent_id 和 level 获取可自动执行的操作列表。"""
    label = f"L{level}"
    rules = AUTO_EXECUTE_RULES.get(agent_id, {})
    return rules.get(label, [])


def is_auto_executable(agent_id: str, level: int, action: str) -> bool:
    """判断某个操作在当前自治等级下是否可自动执行。"""
    return action in get_auto_actions(agent_id, level)


# ── 端点 ─────────────────────────────────────────────────────────────────────

@router.get("/config")
async def get_autonomy_configs(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """获取各Agent自治等级配置。"""
    try:
        result = await db.execute(text("""
            SELECT agent_id, level, auto_rules, updated_at
            FROM agent_autonomy_configs
            WHERE tenant_id = :tenant_id AND is_deleted = FALSE
            ORDER BY agent_id
        """), {"tenant_id": x_tenant_id})
        rows = result.mappings().all()
    except Exception:
        # 表可能尚未创建，返回默认配置
        rows = []

    # 合并数据库配置 + 默认配置
    db_configs = {r["agent_id"]: r for r in rows}
    configs = []
    for agent_id, rules in AUTO_EXECUTE_RULES.items():
        if agent_id in db_configs:
            row = db_configs[agent_id]
            level = row["level"]
            auto_rules = row["auto_rules"] or get_auto_actions(agent_id, level)
            updated_at = row["updated_at"]
        else:
            level = 1  # 默认 L1
            auto_rules = []
            updated_at = None

        configs.append({
            "agent_id": agent_id,
            "level": level,
            "level_info": AUTONOMY_LEVELS[level],
            "auto_rules": auto_rules,
            "available_rules": rules,
            "updated_at": updated_at.isoformat() if updated_at else None,
        })

    return {"ok": True, "data": configs}


@router.put("/config/{agent_id}")
async def update_autonomy_config(
    agent_id: str,
    body: AutonomyConfigUpdate,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """设置某个Agent的自治等级。"""
    if agent_id not in AUTO_EXECUTE_RULES:
        return {"ok": False, "error": {"code": "UNKNOWN_AGENT", "message": f"未知的Agent: {agent_id}"}}

    level = body.level
    auto_rules = body.auto_rules if body.auto_rules is not None else get_auto_actions(agent_id, level)
    now = datetime.now(timezone.utc)

    await db.execute(text("""
        INSERT INTO agent_autonomy_configs (id, tenant_id, agent_id, level, auto_rules, updated_at)
        VALUES (gen_random_uuid(), :tenant_id, :agent_id, :level, :auto_rules, :now)
        ON CONFLICT (tenant_id, agent_id) WHERE is_deleted = FALSE
        DO UPDATE SET level = :level, auto_rules = :auto_rules, updated_at = :now
    """), {
        "tenant_id": x_tenant_id,
        "agent_id": agent_id,
        "level": level,
        "auto_rules": auto_rules,
        "now": now,
    })
    await db.commit()

    logger.info(
        "autonomy_config_updated",
        tenant_id=x_tenant_id,
        agent_id=agent_id,
        level=level,
        auto_rules=auto_rules,
    )

    return {"ok": True, "data": {
        "agent_id": agent_id,
        "level": level,
        "level_info": AUTONOMY_LEVELS[level],
        "auto_rules": auto_rules,
    }}


@router.get("/actions")
async def get_auto_execution_log(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
    agent_id: str | None = Query(None, description="按Agent过滤"),
    start_date: date | None = Query(None, description="起始日期"),
    end_date: date | None = Query(None, description="结束日期"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> dict:
    """自动执行日志 — 哪些操作被Agent自动执行了。"""
    conditions = ["tenant_id = :tenant_id"]
    params: dict = {"tenant_id": x_tenant_id}

    if agent_id:
        conditions.append("agent_id = :agent_id")
        params["agent_id"] = agent_id
    if start_date:
        conditions.append("executed_at >= :start_date")
        params["start_date"] = start_date.isoformat()
    if end_date:
        conditions.append("executed_at < :end_date::date + interval '1 day'")
        params["end_date"] = end_date.isoformat()

    where = " AND ".join(conditions)
    offset = (page - 1) * size
    params["limit"] = size
    params["offset"] = offset

    try:
        count_result = await db.execute(
            text(f"SELECT COUNT(*)::int FROM agent_auto_executions WHERE {where}"),
            params,
        )
        total = count_result.scalar() or 0

        result = await db.execute(text(f"""
            SELECT id, agent_id, action, params, result, status, executed_at
            FROM agent_auto_executions
            WHERE {where}
            ORDER BY executed_at DESC
            LIMIT :limit OFFSET :offset
        """), params)
        rows = result.mappings().all()
    except Exception:
        return {"ok": True, "data": {"items": [], "total": 0}}

    return {"ok": True, "data": {
        "items": [dict(r) for r in rows],
        "total": total,
    }}


@router.get("/pending")
async def get_pending_actions(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> dict:
    """等待人工确认的高风险操作列表。"""
    offset = (page - 1) * size
    try:
        count_result = await db.execute(text("""
            SELECT COUNT(*)::int FROM agent_auto_executions
            WHERE tenant_id = :tenant_id AND status = 'pending'
        """), {"tenant_id": x_tenant_id})
        total = count_result.scalar() or 0

        result = await db.execute(text("""
            SELECT id, agent_id, action, params, created_at
            FROM agent_auto_executions
            WHERE tenant_id = :tenant_id AND status = 'pending'
            ORDER BY created_at ASC
            LIMIT :limit OFFSET :offset
        """), {"tenant_id": x_tenant_id, "limit": size, "offset": offset})
        rows = result.mappings().all()
    except Exception:
        return {"ok": True, "data": {"items": [], "total": 0}}

    return {"ok": True, "data": {
        "items": [dict(r) for r in rows],
        "total": total,
    }}
