"""集点卡服务 — 模板管理 / 发卡 / 自动盖章 / 集满兑换

所有金额单位：分(fen)。
自动盖章：订单完成事件 → auto_stamp() → 检查活跃集点卡 → 盖章 → 集满发奖。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ═══════════════════════════════════════════════════════════════
# 1. 集点卡模板 CRUD
# ═══════════════════════════════════════════════════════════════


async def create_template(
    name: str,
    target_stamps: int,
    reward_type: str,
    reward_config: dict,
    validity_days: int,
    min_order_fen: int,
    applicable_stores: list[str],
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """创建集点卡模板"""
    await _set_tenant(db, tenant_id)
    import json

    if target_stamps < 2:
        raise ValueError("target_stamps must be >= 2")

    template_id = uuid.uuid4()
    now = _now_utc()
    tid = uuid.UUID(tenant_id)

    await db.execute(
        text("""
            INSERT INTO stamp_card_templates
                (id, tenant_id, name, target_stamps, reward_type, reward_config,
                 validity_days, min_order_fen, applicable_stores, status,
                 created_at, updated_at)
            VALUES
                (:id, :tid, :name, :target, :rtype, :rconfig::jsonb,
                 :vdays, :min_order, :stores::jsonb, 'active',
                 :now, :now)
        """),
        {
            "id": template_id,
            "tid": tid,
            "name": name,
            "target": target_stamps,
            "rtype": reward_type,
            "rconfig": json.dumps(reward_config),
            "vdays": validity_days,
            "min_order": min_order_fen,
            "stores": json.dumps(applicable_stores),
            "now": now,
        },
    )
    await db.flush()
    logger.info("stamp_card.template_created", template_id=str(template_id), name=name)
    return {
        "template_id": str(template_id),
        "name": name,
        "target_stamps": target_stamps,
        "reward_type": reward_type,
        "validity_days": validity_days,
        "status": "active",
    }


async def list_templates(
    tenant_id: str,
    db: AsyncSession,
    status: Optional[str] = None,
) -> list[dict[str, Any]]:
    """列出集点卡模板"""
    await _set_tenant(db, tenant_id)
    tid = uuid.UUID(tenant_id)

    sql = """
        SELECT id, name, target_stamps, reward_type, reward_config,
               validity_days, min_order_fen, status, issued_count, completed_count,
               created_at
        FROM stamp_card_templates
        WHERE tenant_id = :tid AND is_deleted = false
    """
    params: dict[str, Any] = {"tid": tid}
    if status:
        sql += " AND status = :status"
        params["status"] = status
    sql += " ORDER BY created_at DESC"

    rows = await db.execute(text(sql), params)
    return [
        {
            "template_id": str(r.id),
            "name": r.name,
            "target_stamps": r.target_stamps,
            "reward_type": r.reward_type,
            "status": r.status,
            "issued_count": r.issued_count,
            "completed_count": r.completed_count,
        }
        for r in rows
    ]


# ═══════════════════════════════════════════════════════════════
# 2. 自动盖章（核心链路）
# ═══════════════════════════════════════════════════════════════


async def auto_stamp(
    customer_id: str,
    order_id: str,
    order_amount_fen: int,
    store_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """订单完成后自动盖章

    流程：
    1. 查找用户所有活跃的集点卡实例
    2. 检查门店适用性 + 最低消费
    3. 盖章（原子递增 stamp_count）
    4. 集满则标记完成 + 发放奖励
    """
    await _set_tenant(db, tenant_id)
    tid = uuid.UUID(tenant_id)
    uid = uuid.UUID(customer_id)
    now = _now_utc()

    # 查用户活跃集点卡（含模板信息）
    rows = await db.execute(
        text("""
            SELECT i.id AS instance_id, i.stamp_count, i.target_stamps,
                   t.min_order_fen, t.applicable_stores, t.reward_type, t.reward_config
            FROM stamp_card_instances i
            JOIN stamp_card_templates t ON t.id = i.template_id
            WHERE i.tenant_id = :tid
              AND i.customer_id = :uid
              AND i.status = 'active'
              AND i.expired_at > :now
              AND i.is_deleted = false
        """),
        {"tid": tid, "uid": uid, "now": now},
    )
    instances = rows.fetchall()
    if not instances:
        # 尝试为用户自动发放新卡
        auto_issued = await _auto_issue_card(uid, tid, now, db)
        if not auto_issued:
            return {"stamped": False, "reason": "no_active_card"}
        instances = [auto_issued]

    stamped_results = []
    for inst in instances:
        min_order = inst.min_order_fen if hasattr(inst, "min_order_fen") else 0
        if order_amount_fen < min_order:
            continue

        stores = inst.applicable_stores if hasattr(inst, "applicable_stores") else []
        if isinstance(stores, str):
            import json

            stores = json.loads(stores)
        if stores and store_id not in [str(s) for s in stores]:
            continue

        # 盖章
        instance_id = inst.instance_id if hasattr(inst, "instance_id") else inst[0]
        new_count = (inst.stamp_count if hasattr(inst, "stamp_count") else inst[1]) + 1
        target = inst.target_stamps if hasattr(inst, "target_stamps") else inst[2]
        completed = new_count >= target

        stamp_no = new_count
        await db.execute(
            text("""
                INSERT INTO stamp_card_stamps
                    (id, tenant_id, instance_id, order_id, store_id, stamp_no, stamped_at)
                VALUES
                    (:id, :tid, :iid, :oid, :sid, :sno, :now)
            """),
            {
                "id": uuid.uuid4(),
                "tid": tid,
                "iid": instance_id,
                "oid": uuid.UUID(order_id),
                "sid": uuid.UUID(store_id),
                "sno": stamp_no,
                "now": now,
            },
        )

        # 原子更新印章计数
        update_sql = """
            UPDATE stamp_card_instances
            SET stamp_count = stamp_count + 1, updated_at = NOW()
        """
        if completed:
            update_sql += ", status = 'completed', completed_at = NOW(), reward_issued = true"
        update_sql += " WHERE id = :iid AND tenant_id = :tid"
        await db.execute(text(update_sql), {"iid": instance_id, "tid": tid})

        if completed:
            await db.execute(
                text("""
                    UPDATE stamp_card_templates
                    SET completed_count = completed_count + 1, updated_at = NOW()
                    WHERE id = (SELECT template_id FROM stamp_card_instances WHERE id = :iid)
                      AND tenant_id = :tid
                """),
                {"iid": instance_id, "tid": tid},
            )

        stamped_results.append(
            {
                "instance_id": str(instance_id),
                "stamp_count": new_count,
                "target_stamps": target,
                "completed": completed,
            }
        )

    await db.flush()
    if stamped_results:
        logger.info(
            "stamp_card.auto_stamped",
            customer_id=customer_id,
            results=len(stamped_results),
        )
    return {"stamped": bool(stamped_results), "results": stamped_results}


async def _auto_issue_card(
    uid: uuid.UUID,
    tid: uuid.UUID,
    now: datetime,
    db: AsyncSession,
) -> Optional[Any]:
    """自动为用户发放活跃模板的新集点卡"""
    row = await db.execute(
        text("""
            SELECT id, target_stamps, validity_days, min_order_fen,
                   applicable_stores, reward_type, reward_config
            FROM stamp_card_templates
            WHERE tenant_id = :tid AND status = 'active' AND is_deleted = false
            ORDER BY created_at DESC LIMIT 1
        """),
        {"tid": tid},
    )
    template = row.fetchone()
    if not template:
        return None

    # 检查是否已有同模板的活跃卡
    dup = await db.execute(
        text("""
            SELECT id FROM stamp_card_instances
            WHERE tenant_id = :tid AND customer_id = :uid
              AND template_id = :tmpl AND status = 'active' AND is_deleted = false
        """),
        {"tid": tid, "uid": uid, "tmpl": template.id},
    )
    if dup.fetchone():
        return None

    instance_id = uuid.uuid4()
    expired_at = now + timedelta(days=template.validity_days)

    await db.execute(
        text("""
            INSERT INTO stamp_card_instances
                (id, tenant_id, template_id, customer_id, stamp_count,
                 target_stamps, status, expired_at, created_at, updated_at)
            VALUES
                (:id, :tid, :tmpl, :uid, 0, :target, 'active', :exp, :now, :now)
        """),
        {
            "id": instance_id,
            "tid": tid,
            "tmpl": template.id,
            "uid": uid,
            "target": template.target_stamps,
            "exp": expired_at,
            "now": now,
        },
    )
    await db.execute(
        text("""
            UPDATE stamp_card_templates
            SET issued_count = issued_count + 1, updated_at = NOW()
            WHERE id = :tmpl AND tenant_id = :tid
        """),
        {"tmpl": template.id, "tid": tid},
    )
    await db.flush()
    logger.info("stamp_card.auto_issued", instance_id=str(instance_id), customer_id=str(uid))
    return template


# ═══════════════════════════════════════════════════════════════
# 3. 用户查询
# ═══════════════════════════════════════════════════════════════


async def get_my_cards(
    customer_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """查询用户的集点卡列表（含进度）"""
    await _set_tenant(db, tenant_id)
    tid = uuid.UUID(tenant_id)
    uid = uuid.UUID(customer_id)

    rows = await db.execute(
        text("""
            SELECT i.id, i.stamp_count, i.target_stamps, i.status,
                   i.expired_at, i.completed_at, i.reward_issued,
                   t.name, t.reward_type, t.reward_config
            FROM stamp_card_instances i
            JOIN stamp_card_templates t ON t.id = i.template_id
            WHERE i.tenant_id = :tid AND i.customer_id = :uid AND i.is_deleted = false
            ORDER BY i.created_at DESC
        """),
        {"tid": tid, "uid": uid},
    )
    return [
        {
            "instance_id": str(r.id),
            "name": r.name,
            "stamp_count": r.stamp_count,
            "target_stamps": r.target_stamps,
            "progress_pct": round(r.stamp_count / r.target_stamps * 100, 1),
            "status": r.status,
            "reward_type": r.reward_type,
            "expired_at": r.expired_at.isoformat(),
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in rows
    ]


async def redeem_card(
    instance_id: str,
    customer_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """手动兑换集满奖励（备用：auto_stamp 已自动发放）"""
    await _set_tenant(db, tenant_id)
    tid = uuid.UUID(tenant_id)

    row = await db.execute(
        text("""
            SELECT i.id, i.status, i.reward_issued, i.stamp_count, i.target_stamps,
                   t.reward_type, t.reward_config
            FROM stamp_card_instances i
            JOIN stamp_card_templates t ON t.id = i.template_id
            WHERE i.id = :iid AND i.tenant_id = :tid
              AND i.customer_id = :uid AND i.is_deleted = false
        """),
        {"iid": uuid.UUID(instance_id), "tid": tid, "uid": uuid.UUID(customer_id)},
    )
    inst = row.fetchone()
    if not inst:
        raise ValueError("instance_not_found")
    if inst.status != "completed":
        raise ValueError("card_not_completed")
    if inst.reward_issued:
        raise ValueError("reward_already_issued")

    import json

    reward = inst.reward_config
    if isinstance(reward, str):
        reward = json.loads(reward)

    await db.execute(
        text("""
            UPDATE stamp_card_instances
            SET reward_issued = true, updated_at = NOW()
            WHERE id = :iid AND tenant_id = :tid
        """),
        {"iid": uuid.UUID(instance_id), "tid": tid},
    )
    await db.flush()

    logger.info("stamp_card.redeemed", instance_id=instance_id, customer_id=customer_id)
    return {
        "instance_id": instance_id,
        "reward_type": inst.reward_type,
        "reward_config": reward,
        "redeemed": True,
    }
