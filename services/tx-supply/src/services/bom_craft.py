"""BOM 工艺管理服务 — 加工工艺卡 / 档口路由 / 替代料 / 版本管理

扩展 BOM 基础模块，支持工艺卡、工序路由、原料替代和版本生命周期。
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# BOM 版本状态机
_VALID_TRANSITIONS = {
    "draft": {"review"},
    "review": {"approved", "draft"},
    "approved": {"archived"},
    "archived": set(),
}


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS tenant context"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ─── 加工工艺卡 ───


async def create_craft_card(
    dish_id: str,
    steps: list[dict],
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """创建加工工艺卡（步骤/时间/温度/工具）

    Args:
        dish_id: 菜品 ID
        steps: 工艺步骤列表，每项包含:
            - seq: int 步骤序号
            - name: str 步骤名称
            - duration_seconds: int 耗时(秒)
            - temperature: Optional[float] 温度(摄氏度)
            - tool: Optional[str] 工具/设备
            - notes: Optional[str] 备注
        tenant_id: 租户 ID
        db: 数据库会话
    """
    await _set_tenant(db, tenant_id)

    card_id = uuid.uuid4()
    tenant_uuid = uuid.UUID(tenant_id)
    dish_uuid = uuid.UUID(dish_id)
    now = datetime.now(timezone.utc)

    await db.execute(
        text("""
            INSERT INTO craft_cards (
                id, tenant_id, dish_id,
                total_duration_seconds, is_deleted,
                created_at, updated_at
            ) VALUES (
                :id, :tenant_id, :dish_id,
                :total_duration, false,
                :now, :now
            )
        """),
        {
            "id": card_id,
            "tenant_id": tenant_uuid,
            "dish_id": dish_uuid,
            "total_duration": sum(s.get("duration_seconds", 0) for s in steps),
            "now": now,
        },
    )

    created_steps = []
    for step in steps:
        step_id = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO craft_card_steps (
                    id, tenant_id, card_id, seq, name,
                    duration_seconds, temperature, tool, notes,
                    is_deleted, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :card_id, :seq, :name,
                    :duration_seconds, :temperature, :tool, :notes,
                    false, :now, :now
                )
            """),
            {
                "id": step_id,
                "tenant_id": tenant_uuid,
                "card_id": card_id,
                "seq": step["seq"],
                "name": step["name"],
                "duration_seconds": step.get("duration_seconds", 0),
                "temperature": step.get("temperature"),
                "tool": step.get("tool"),
                "notes": step.get("notes"),
                "now": now,
            },
        )
        created_steps.append(
            {
                "id": str(step_id),
                "seq": step["seq"],
                "name": step["name"],
                "duration_seconds": step.get("duration_seconds", 0),
                "temperature": step.get("temperature"),
                "tool": step.get("tool"),
            }
        )

    await db.flush()

    log.info(
        "craft_card_created",
        card_id=str(card_id),
        dish_id=dish_id,
        step_count=len(steps),
        tenant_id=tenant_id,
    )

    return {
        "id": str(card_id),
        "dish_id": dish_id,
        "total_duration_seconds": sum(s.get("duration_seconds", 0) for s in steps),
        "steps": created_steps,
    }


# ─── 档口工艺路由 ───


async def set_dept_routing(
    dish_id: str,
    dept_sequence: list[dict],
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """设置档口工艺路由（哪道工序在哪个档口执行）

    Args:
        dish_id: 菜品 ID
        dept_sequence: 路由序列，每项包含:
            - seq: int 顺序
            - dept_id: str 档口 ID
            - process_name: str 工序名称
            - estimated_seconds: int 预估耗时
        tenant_id: 租户 ID
        db: 数据库会话
    """
    await _set_tenant(db, tenant_id)

    tenant_uuid = uuid.UUID(tenant_id)
    dish_uuid = uuid.UUID(dish_id)
    now = datetime.now(timezone.utc)

    # 软删除旧路由
    await db.execute(
        text("""
            UPDATE dept_routings
            SET is_deleted = true, updated_at = :now
            WHERE dish_id = :dish_id AND tenant_id = :tenant_id
        """),
        {"dish_id": dish_uuid, "tenant_id": tenant_uuid, "now": now},
    )

    created_routes = []
    for route in dept_sequence:
        route_id = uuid.uuid4()
        dept_uuid = uuid.UUID(route["dept_id"])

        await db.execute(
            text("""
                INSERT INTO dept_routings (
                    id, tenant_id, dish_id, dept_id,
                    seq, process_name, estimated_seconds,
                    is_deleted, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :dish_id, :dept_id,
                    :seq, :process_name, :estimated_seconds,
                    false, :now, :now
                )
            """),
            {
                "id": route_id,
                "tenant_id": tenant_uuid,
                "dish_id": dish_uuid,
                "dept_id": dept_uuid,
                "seq": route["seq"],
                "process_name": route["process_name"],
                "estimated_seconds": route.get("estimated_seconds", 0),
                "now": now,
            },
        )
        created_routes.append(
            {
                "id": str(route_id),
                "seq": route["seq"],
                "dept_id": route["dept_id"],
                "process_name": route["process_name"],
                "estimated_seconds": route.get("estimated_seconds", 0),
            }
        )

    await db.flush()

    log.info(
        "dept_routing_set",
        dish_id=dish_id,
        route_count=len(dept_sequence),
        tenant_id=tenant_id,
    )

    return {
        "dish_id": dish_id,
        "routes": created_routes,
    }


# ─── 替代料规则 ───


async def set_substitute_rules(
    ingredient_id: str,
    substitutes: list[dict],
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """设置原料替代规则

    Args:
        ingredient_id: 原料 ID
        substitutes: 替代料列表，每项包含:
            - substitute_id: str 替代原料 ID
            - ratio: float 替代比例（1.0=等量）
            - priority: int 优先级（1最高）
            - conditions: Optional[str] 替代条件说明
        tenant_id: 租户 ID
        db: 数据库会话
    """
    await _set_tenant(db, tenant_id)

    tenant_uuid = uuid.UUID(tenant_id)
    ingredient_uuid = uuid.UUID(ingredient_id)
    now = datetime.now(timezone.utc)

    # 软删除旧替代规则
    await db.execute(
        text("""
            UPDATE substitute_rules
            SET is_deleted = true, updated_at = :now
            WHERE ingredient_id = :ingredient_id AND tenant_id = :tenant_id
        """),
        {"ingredient_id": ingredient_uuid, "tenant_id": tenant_uuid, "now": now},
    )

    created_rules = []
    for sub in substitutes:
        rule_id = uuid.uuid4()
        sub_uuid = uuid.UUID(sub["substitute_id"])

        await db.execute(
            text("""
                INSERT INTO substitute_rules (
                    id, tenant_id, ingredient_id, substitute_id,
                    ratio, priority, conditions,
                    is_deleted, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :ingredient_id, :substitute_id,
                    :ratio, :priority, :conditions,
                    false, :now, :now
                )
            """),
            {
                "id": rule_id,
                "tenant_id": tenant_uuid,
                "ingredient_id": ingredient_uuid,
                "substitute_id": sub_uuid,
                "ratio": sub.get("ratio", 1.0),
                "priority": sub.get("priority", 1),
                "conditions": sub.get("conditions"),
                "now": now,
            },
        )
        created_rules.append(
            {
                "id": str(rule_id),
                "substitute_id": sub["substitute_id"],
                "ratio": sub.get("ratio", 1.0),
                "priority": sub.get("priority", 1),
                "conditions": sub.get("conditions"),
            }
        )

    await db.flush()

    log.info(
        "substitute_rules_set",
        ingredient_id=ingredient_id,
        rule_count=len(substitutes),
        tenant_id=tenant_id,
    )

    return {
        "ingredient_id": ingredient_id,
        "substitutes": created_rules,
    }


# ─── BOM 版本管理 ───


async def manage_bom_version(
    template_id: str,
    action: str,
    tenant_id: str,
    db: AsyncSession,
    *,
    operator_id: Optional[str] = None,
) -> dict:
    """BOM 版本状态管理（draft → review → approved → archived）

    Args:
        template_id: BOM 模板 ID
        action: 目标状态 (review/approved/draft/archived)
        tenant_id: 租户 ID
        db: 数据库会话
        operator_id: 操作人 ID
    """
    await _set_tenant(db, tenant_id)

    tenant_uuid = uuid.UUID(tenant_id)
    template_uuid = uuid.UUID(template_id)
    now = datetime.now(timezone.utc)

    # 查询当前状态
    result = await db.execute(
        text("""
            SELECT id, dish_id, version, status
            FROM bom_templates
            WHERE id = :id AND tenant_id = :tenant_id AND is_deleted = false
        """),
        {"id": template_uuid, "tenant_id": tenant_uuid},
    )
    row = result.mappings().first()
    if not row:
        log.warning(
            "bom_version_not_found",
            template_id=template_id,
            tenant_id=tenant_id,
        )
        return {"ok": False, "error": "BOM template not found"}

    current_status = row["status"] or "draft"

    # 校验状态转换合法性
    allowed = _VALID_TRANSITIONS.get(current_status, set())
    if action not in allowed:
        log.warning(
            "bom_version_invalid_transition",
            template_id=template_id,
            current=current_status,
            target=action,
            tenant_id=tenant_id,
        )
        return {
            "ok": False,
            "error": f"Cannot transition from '{current_status}' to '{action}'",
        }

    # 更新状态
    update_params: dict = {
        "id": template_uuid,
        "tenant_id": tenant_uuid,
        "status": action,
        "now": now,
    }

    extra_set = ""
    if action == "approved":
        extra_set = ", is_approved = true, approved_by = :operator_id, approved_at = :now"
        update_params["operator_id"] = operator_id

    await db.execute(
        text(f"""
            UPDATE bom_templates
            SET status = :status, updated_at = :now{extra_set}
            WHERE id = :id AND tenant_id = :tenant_id
        """),
        update_params,
    )

    await db.flush()

    log.info(
        "bom_version_transitioned",
        template_id=template_id,
        from_status=current_status,
        to_status=action,
        operator_id=operator_id,
        tenant_id=tenant_id,
    )

    return {
        "ok": True,
        "template_id": template_id,
        "dish_id": str(row["dish_id"]),
        "version": row["version"],
        "previous_status": current_status,
        "current_status": action,
    }
