"""付费会员卡 Service — 次卡（count_card）+ 周期卡（period_card）

所有金额单位：分(fen)。
card_type:
  count_card  — 购买N次使用权，每次到店核销1次
  period_card — 按月/季/年计费，持有期享固定权益
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


# ── 工具函数 ──────────────────────────────────────────────────


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> date:
    return _now_utc().date()


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS tenant 上下文（v006+ 标准模式）"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _period_end(start: date, period_type: str) -> date:
    """根据 period_type 计算周期结束日"""
    if period_type == "monthly":
        # 下一个月同一天 -1 天
        m = start.month + 1
        y = start.year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        try:
            return date(y, m, start.day) - timedelta(days=1)
        except ValueError:
            # 月末边界处理（如 1月31日 → 2月28日）
            import calendar

            last_day = calendar.monthrange(y, m)[1]
            return date(y, m, last_day)
    elif period_type == "quarterly":
        m = start.month + 3
        y = start.year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        try:
            return date(y, m, start.day) - timedelta(days=1)
        except ValueError:
            import calendar

            last_day = calendar.monthrange(y, m)[1]
            return date(y, m, last_day)
    elif period_type == "yearly":
        try:
            return date(start.year + 1, start.month, start.day) - timedelta(days=1)
        except ValueError:
            # 2月29日闰年边界
            return date(start.year + 1, start.month, 28)
    else:
        raise ValueError(f"unsupported_period_type:{period_type}")


# ── ANNUAL_PLANS 保留（旧路由兼容） ──────────────────────────

ANNUAL_PLANS = {
    "silver": {
        "name": "银卡",
        "price_fen": 69800,
        "duration_days": 365,
        "benefits": [
            {"key": "dining_discount", "name": "堂食折扣", "value": 95, "unit": "percent"},
            {"key": "retail_discount", "name": "甄选商城折扣", "value": 95, "unit": "percent"},
            {"key": "free_dish_monthly", "name": "每月免费菜", "value": 1, "unit": "count"},
            {"key": "birthday_gift", "name": "生日专属礼遇", "value": 1, "unit": "count"},
            {"key": "priority_booking", "name": "优先预订", "value": 0, "unit": "flag"},
        ],
    },
    "gold": {
        "name": "金卡",
        "price_fen": 129800,
        "duration_days": 365,
        "benefits": [
            {"key": "dining_discount", "name": "堂食折扣", "value": 90, "unit": "percent"},
            {"key": "retail_discount", "name": "甄选商城折扣", "value": 90, "unit": "percent"},
            {"key": "free_dish_monthly", "name": "每月免费菜", "value": 2, "unit": "count"},
            {"key": "birthday_gift", "name": "生日专属礼遇", "value": 1, "unit": "count"},
            {"key": "priority_booking", "name": "优先预订", "value": 1, "unit": "flag"},
            {"key": "dedicated_service", "name": "专属客服", "value": 0, "unit": "flag"},
            {"key": "free_parking", "name": "免费停车", "value": 2, "unit": "hours"},
        ],
    },
    "diamond": {
        "name": "钻石卡",
        "price_fen": 299800,
        "duration_days": 365,
        "benefits": [
            {"key": "dining_discount", "name": "堂食折扣", "value": 85, "unit": "percent"},
            {"key": "retail_discount", "name": "甄选商城折扣", "value": 85, "unit": "percent"},
            {"key": "free_dish_monthly", "name": "每月免费菜", "value": 4, "unit": "count"},
            {"key": "birthday_gift", "name": "生日专属礼遇", "value": 1, "unit": "count"},
            {"key": "priority_booking", "name": "优先预订", "value": 1, "unit": "flag"},
            {"key": "dedicated_service", "name": "专属客服(1对1)", "value": 1, "unit": "flag"},
            {"key": "free_parking", "name": "免费停车", "value": 4, "unit": "hours"},
            {"key": "private_room_priority", "name": "包厢优先", "value": 1, "unit": "flag"},
            {"key": "annual_banquet", "name": "年度答谢宴", "value": 1, "unit": "count"},
        ],
    },
}


# ── 等级联动 ──────────────────────────────────────────────────


async def _sync_member_level(
    customer_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> None:
    """检查该会员是否持有 period_card，同步 member_level。

    逻辑：
      - 持有任意 active period_card → member_level 至少 gold
      - 所有 period_card 都不 active → 不自动降级（保留历史等级或由其他规则管）
    注意：Customer 实体无 member_level 字段，此处写入 extra JSONB 字段作为临时承载，
    待 Ontology 正式添加 member_level 列后替换 SQL。
    """
    row = await db.execute(
        text("""
            SELECT COUNT(*) FROM premium_cards
            WHERE customer_id = :cid
              AND tenant_id = :tid
              AND card_type = 'period_card'
              AND status = 'active'
              AND (expires_at IS NULL OR expires_at > :now)
              AND is_deleted = false
        """),
        {"cid": customer_id, "tid": tenant_id, "now": _now_utc()},
    )
    active_period_count = row.scalar() or 0

    if active_period_count > 0:
        # 提升为 gold（最低）
        await db.execute(
            text("""
                UPDATE customers
                SET extra = jsonb_set(
                    COALESCE(extra, '{}'),
                    '{member_level}',
                    '"gold"'
                ),
                updated_at = :now
                WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
            """),
            {"cid": customer_id, "tid": tenant_id, "now": _now_utc()},
        )
        logger.info(
            "member_level_upgraded_to_gold",
            tenant_id=tenant_id,
            customer_id=customer_id,
        )


# ── 模板管理 ──────────────────────────────────────────────────


async def list_templates(
    tenant_id: str,
    db: AsyncSession,
    active_only: bool = True,
) -> list[dict[str, Any]]:
    """付费卡模板列表

    Returns:
        [{"id", "name", "card_type", "price_fen", "benefits", ...}]
    """
    await _set_tenant(db, tenant_id)

    where = "tenant_id = :tid AND is_deleted = false"
    if active_only:
        where += " AND is_active = true"

    rows = await db.execute(
        text(f"""
            SELECT id, name, card_type, price_fen,
                   total_uses, period_type,
                   benefits::text, valid_days, is_active, sort_order
            FROM premium_card_templates
            WHERE {where}
            ORDER BY sort_order ASC, created_at DESC
        """),
        {"tid": tenant_id},
    )
    templates = []
    for r in rows.mappings():
        t = dict(r)
        t["benefits"] = json.loads(t["benefits"]) if t.get("benefits") else []
        templates.append(t)

    logger.info(
        "premium_card_templates_listed",
        tenant_id=tenant_id,
        count=len(templates),
        active_only=active_only,
    )
    return templates


async def create_template(
    name: str,
    card_type: str,
    price_fen: int,
    benefits: list[dict],
    tenant_id: str,
    db: AsyncSession,
    total_uses: Optional[int] = None,
    period_type: Optional[str] = None,
    valid_days: Optional[int] = None,
    sort_order: int = 0,
) -> dict[str, Any]:
    """创建付费卡模板

    Args:
        card_type: count_card | period_card
        price_fen: 售价（分）
        benefits: 权益配置列表
        total_uses: 次卡总次数
        period_type: monthly | quarterly | yearly
        valid_days: 次卡有效天数

    Returns:
        新建模板详情
    """
    await _set_tenant(db, tenant_id)

    if card_type not in ("count_card", "period_card"):
        raise ValueError(f"invalid_card_type:{card_type}, valid: count_card|period_card")
    if card_type == "count_card" and not total_uses:
        raise ValueError("count_card requires total_uses")
    if card_type == "period_card" and not period_type:
        raise ValueError("period_card requires period_type")
    if period_type and period_type not in ("monthly", "quarterly", "yearly"):
        raise ValueError(f"invalid_period_type:{period_type}")
    if price_fen <= 0:
        raise ValueError("price_fen must be positive")

    template_id = str(uuid.uuid4())
    now = _now_utc()

    await db.execute(
        text("""
            INSERT INTO premium_card_templates
                (id, tenant_id, name, card_type, price_fen,
                 total_uses, period_type, benefits,
                 valid_days, is_active, sort_order,
                 created_at, updated_at, is_deleted)
            VALUES
                (:id, :tid, :name, :card_type, :price_fen,
                 :total_uses, :period_type, :benefits::jsonb,
                 :valid_days, true, :sort_order,
                 :now, :now, false)
        """),
        {
            "id": template_id,
            "tid": tenant_id,
            "name": name,
            "card_type": card_type,
            "price_fen": price_fen,
            "total_uses": total_uses,
            "period_type": period_type,
            "benefits": json.dumps(benefits, ensure_ascii=False),
            "valid_days": valid_days,
            "sort_order": sort_order,
            "now": now,
        },
    )
    await db.flush()

    logger.info(
        "premium_card_template_created",
        tenant_id=tenant_id,
        template_id=template_id,
        name=name,
        card_type=card_type,
    )

    return {
        "id": template_id,
        "name": name,
        "card_type": card_type,
        "price_fen": price_fen,
        "total_uses": total_uses,
        "period_type": period_type,
        "benefits": benefits,
        "valid_days": valid_days,
        "is_active": True,
        "sort_order": sort_order,
        "created_at": now.isoformat(),
    }


# ── 购卡 ──────────────────────────────────────────────────────


async def purchase_card(
    customer_id: str,
    template_id: str,
    tenant_id: str,
    db: AsyncSession,
    store_id: Optional[str] = None,
) -> dict[str, Any]:
    """购买付费会员卡

    - 次卡：设 remaining_uses = template.total_uses，计算 expires_at
    - 周期卡：设 period_start/end，触发等级提升

    Returns:
        新建卡详情
    """
    await _set_tenant(db, tenant_id)

    # 查模板
    tpl_row = await db.execute(
        text("""
            SELECT id, name, card_type, price_fen,
                   total_uses, period_type,
                   benefits::text, valid_days, is_active
            FROM premium_card_templates
            WHERE id = :tid_param AND tenant_id = :tid AND is_deleted = false
        """),
        {"tid_param": template_id, "tid": tenant_id},
    )
    tpl = tpl_row.mappings().first()
    if not tpl:
        raise ValueError("template_not_found")
    if not tpl["is_active"]:
        raise ValueError("template_inactive")

    now = _now_utc()
    today = _today()
    card_id = str(uuid.uuid4())
    card_type: str = tpl["card_type"]

    # 次卡字段
    remaining_uses: Optional[int] = None
    total_uses: Optional[int] = None
    expires_at: Optional[datetime] = None

    # 周期卡字段
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    next_renewal_at: Optional[date] = None

    if card_type == "count_card":
        total_uses = tpl["total_uses"]
        remaining_uses = total_uses
        if tpl["valid_days"]:
            expires_at = now + timedelta(days=tpl["valid_days"])

    elif card_type == "period_card":
        period_type: str = tpl["period_type"]
        period_start = today
        period_end = _period_end(today, period_type)
        next_renewal_at = period_end + timedelta(days=1)
        # 周期卡有效期 = 第一个周期的结束日（续费后延长）
        expires_at = datetime(period_end.year, period_end.month, period_end.day, 23, 59, 59, tzinfo=timezone.utc)

    benefits_json = tpl["benefits"] or "[]"

    await db.execute(
        text("""
            INSERT INTO premium_cards
                (id, tenant_id, template_id, customer_id, store_id,
                 card_type, status,
                 remaining_uses, total_uses,
                 period_start, period_end, next_renewal_at,
                 purchased_at, expires_at,
                 period_used_benefits,
                 created_at, updated_at, is_deleted)
            VALUES
                (:id, :tid, :template_id, :cid, :store_id,
                 :card_type, 'active',
                 :remaining_uses, :total_uses,
                 :period_start, :period_end, :next_renewal_at,
                 :now, :expires_at,
                 '{}',
                 :now, :now, false)
        """),
        {
            "id": card_id,
            "tid": tenant_id,
            "template_id": template_id,
            "cid": customer_id,
            "store_id": store_id,
            "card_type": card_type,
            "remaining_uses": remaining_uses,
            "total_uses": total_uses,
            "period_start": period_start,
            "period_end": period_end,
            "next_renewal_at": next_renewal_at,
            "now": now,
            "expires_at": expires_at,
        },
    )
    await db.flush()

    logger.info(
        "premium_card_purchased",
        tenant_id=tenant_id,
        card_id=card_id,
        customer_id=customer_id,
        template_id=template_id,
        card_type=card_type,
    )

    # 等级联动（仅 period_card 触发升级）
    if card_type == "period_card":
        await _sync_member_level(customer_id, tenant_id, db)

    return {
        "card_id": card_id,
        "customer_id": customer_id,
        "template_id": template_id,
        "template_name": tpl["name"],
        "card_type": card_type,
        "status": "active",
        "remaining_uses": remaining_uses,
        "total_uses": total_uses,
        "period_start": period_start.isoformat() if period_start else None,
        "period_end": period_end.isoformat() if period_end else None,
        "next_renewal_at": next_renewal_at.isoformat() if next_renewal_at else None,
        "purchased_at": now.isoformat(),
        "expires_at": expires_at.isoformat() if expires_at else None,
        "benefits": json.loads(benefits_json),
    }


# ── 次卡核销 ──────────────────────────────────────────────────


async def use_count_card(
    card_id: str,
    tenant_id: str,
    db: AsyncSession,
    order_id: Optional[str] = None,
    store_id: Optional[str] = None,
    operator_id: Optional[str] = None,
) -> dict[str, Any]:
    """核销次卡一次

    验证：status=active、remaining_uses > 0、未过期
    副作用：
      - remaining_uses -= 1
      - 剩余2次时记录提醒标记（可接通知系统）
      - remaining_uses == 0 时 status → expired
      - 触发等级检查

    Returns:
        usage 记录详情
    """
    await _set_tenant(db, tenant_id)

    # 加行锁查卡
    row = await db.execute(
        text("""
            SELECT id, customer_id, card_type, status,
                   remaining_uses, expires_at
            FROM premium_cards
            WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
            FOR UPDATE
        """),
        {"cid": card_id, "tid": tenant_id},
    )
    card = row.mappings().first()
    if not card:
        raise ValueError("card_not_found")
    if card["card_type"] != "count_card":
        raise ValueError("not_a_count_card")
    if card["status"] != "active":
        raise ValueError(f"card_not_active:status={card['status']}")
    if card["remaining_uses"] is None or card["remaining_uses"] <= 0:
        raise ValueError("no_remaining_uses")

    now = _now_utc()
    if card["expires_at"] and card["expires_at"] < now:
        # 过期但 status 未更新，修正
        await db.execute(
            text("""
                UPDATE premium_cards
                SET status = 'expired', updated_at = :now
                WHERE id = :cid AND tenant_id = :tid
            """),
            {"cid": card_id, "tid": tenant_id, "now": now},
        )
        await db.flush()
        raise ValueError("card_expired")

    uses_before: int = card["remaining_uses"]
    uses_after: int = uses_before - 1
    new_status = "expired" if uses_after == 0 else "active"

    await db.execute(
        text("""
            UPDATE premium_cards
            SET remaining_uses = :uses_after,
                status = :status,
                updated_at = :now
            WHERE id = :cid AND tenant_id = :tid
        """),
        {
            "uses_after": uses_after,
            "status": new_status,
            "cid": card_id,
            "tid": tenant_id,
            "now": now,
        },
    )

    usage_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO premium_card_usages
                (id, tenant_id, card_id, customer_id, store_id, order_id,
                 usage_type, benefit_type,
                 uses_before, uses_after,
                 used_at, operator_id,
                 created_at, updated_at, is_deleted)
            VALUES
                (:id, :tid, :card_id, :cid, :store_id, :order_id,
                 'count_deduct', NULL,
                 :uses_before, :uses_after,
                 :now, :operator_id,
                 :now, :now, false)
        """),
        {
            "id": usage_id,
            "tid": tenant_id,
            "card_id": card_id,
            "cid": card["customer_id"],
            "store_id": store_id,
            "order_id": order_id,
            "uses_before": uses_before,
            "uses_after": uses_after,
            "now": now,
            "operator_id": operator_id,
        },
    )
    await db.flush()

    # 触发提醒（剩余2次）
    low_stock_alert = False
    if uses_after == 2:
        low_stock_alert = True
        logger.warning(
            "count_card_low_uses_alert",
            tenant_id=tenant_id,
            card_id=card_id,
            customer_id=card["customer_id"],
            remaining_uses=uses_after,
            alert="还剩2次，请提醒续卡",
        )

    if new_status == "expired":
        logger.info(
            "count_card_exhausted",
            tenant_id=tenant_id,
            card_id=card_id,
            customer_id=card["customer_id"],
        )
        # 等级检查（次卡耗尽后重新评估）
        await _sync_member_level(str(card["customer_id"]), tenant_id, db)

    logger.info(
        "count_card_used",
        tenant_id=tenant_id,
        card_id=card_id,
        usage_id=usage_id,
        uses_before=uses_before,
        uses_after=uses_after,
        new_status=new_status,
    )

    return {
        "usage_id": usage_id,
        "card_id": card_id,
        "usage_type": "count_deduct",
        "uses_before": uses_before,
        "uses_after": uses_after,
        "card_status": new_status,
        "low_stock_alert": low_stock_alert,
        "used_at": now.isoformat(),
    }


# ── 周期权益检查 ──────────────────────────────────────────────


async def check_benefit(
    card_id: str,
    benefit_type: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """检查周期权益是否可用

    Returns:
        {"available", "remaining_quota", "resets_at", "benefit_config"}
    """
    await _set_tenant(db, tenant_id)

    row = await db.execute(
        text("""
            SELECT pc.id, pc.card_type, pc.status,
                   pc.period_end, pc.expires_at,
                   pc.period_used_benefits::text,
                   pct.benefits::text as tpl_benefits
            FROM premium_cards pc
            JOIN premium_card_templates pct ON pct.id = pc.template_id
                AND pct.tenant_id = pc.tenant_id
            WHERE pc.id = :cid AND pc.tenant_id = :tid AND pc.is_deleted = false
        """),
        {"cid": card_id, "tid": tenant_id},
    )
    card = row.mappings().first()
    if not card:
        raise ValueError("card_not_found")
    if card["status"] != "active":
        raise ValueError(f"card_not_active:status={card['status']}")

    now = _now_utc()
    if card["expires_at"] and card["expires_at"] < now:
        raise ValueError("card_expired")

    tpl_benefits: list = json.loads(card["tpl_benefits"]) if card["tpl_benefits"] else []
    target = next(
        (b for b in tpl_benefits if b.get("type") == benefit_type or b.get("key") == benefit_type),
        None,
    )
    if not target:
        raise ValueError(f"benefit_not_in_template:{benefit_type}")

    used_dict: dict = json.loads(card["period_used_benefits"]) if card["period_used_benefits"] else {}
    used_key = f"{benefit_type}_used"
    used_count: int = used_dict.get(used_key, 0)

    # 获取每周期配额
    quota_per_period: int = target.get("quota_per_period") or target.get("value") or 0
    # flag 类型权益无次数限制
    if target.get("unit") == "flag":
        return {
            "available": True,
            "remaining_quota": None,
            "resets_at": card["period_end"].isoformat() if card["period_end"] else None,
            "benefit_config": target,
        }

    remaining_quota = max(0, quota_per_period - used_count)
    resets_at = (card["period_end"] + timedelta(days=1)).isoformat() if card["period_end"] else None

    return {
        "available": remaining_quota > 0,
        "remaining_quota": remaining_quota,
        "used_this_period": used_count,
        "total_quota_per_period": quota_per_period,
        "resets_at": resets_at,
        "benefit_config": target,
    }


# ── 使用周期权益 ──────────────────────────────────────────────


async def use_benefit(
    card_id: str,
    benefit_type: str,
    tenant_id: str,
    db: AsyncSession,
    order_id: Optional[str] = None,
    store_id: Optional[str] = None,
    operator_id: Optional[str] = None,
) -> dict[str, Any]:
    """使用周期权益

    - 验证权益可用
    - period_used_benefits[f"{benefit_type}_used"] += 1
    - INSERT 使用记录

    Returns:
        usage 记录详情
    """
    await _set_tenant(db, tenant_id)

    # 先检查可用性
    benefit_check = await check_benefit(card_id, benefit_type, tenant_id, db)
    if not benefit_check["available"] and benefit_check["remaining_quota"] is not None:
        raise ValueError(f"benefit_quota_exhausted:{benefit_type}")

    # 加行锁
    row = await db.execute(
        text("""
            SELECT id, customer_id, period_used_benefits::text
            FROM premium_cards
            WHERE id = :cid AND tenant_id = :tid AND is_deleted = false
            FOR UPDATE
        """),
        {"cid": card_id, "tid": tenant_id},
    )
    card = row.mappings().first()
    if not card:
        raise ValueError("card_not_found_on_lock")

    used_dict: dict = json.loads(card["period_used_benefits"]) if card["period_used_benefits"] else {}
    used_key = f"{benefit_type}_used"
    used_dict[used_key] = used_dict.get(used_key, 0) + 1

    now = _now_utc()
    await db.execute(
        text("""
            UPDATE premium_cards
            SET period_used_benefits = :used_benefits::jsonb,
                updated_at = :now
            WHERE id = :cid AND tenant_id = :tid
        """),
        {
            "used_benefits": json.dumps(used_dict),
            "cid": card_id,
            "tid": tenant_id,
            "now": now,
        },
    )

    usage_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO premium_card_usages
                (id, tenant_id, card_id, customer_id, store_id, order_id,
                 usage_type, benefit_type,
                 uses_before, uses_after,
                 used_at, operator_id,
                 created_at, updated_at, is_deleted)
            VALUES
                (:id, :tid, :card_id, :cid, :store_id, :order_id,
                 'benefit_use', :benefit_type,
                 NULL, NULL,
                 :now, :operator_id,
                 :now, :now, false)
        """),
        {
            "id": usage_id,
            "tid": tenant_id,
            "card_id": card_id,
            "cid": card["customer_id"],
            "store_id": store_id,
            "order_id": order_id,
            "benefit_type": benefit_type,
            "now": now,
            "operator_id": operator_id,
        },
    )
    await db.flush()

    logger.info(
        "premium_card_benefit_used",
        tenant_id=tenant_id,
        card_id=card_id,
        usage_id=usage_id,
        benefit_type=benefit_type,
        used_count_this_period=used_dict[used_key],
    )

    return {
        "usage_id": usage_id,
        "card_id": card_id,
        "usage_type": "benefit_use",
        "benefit_type": benefit_type,
        "used_count_this_period": used_dict[used_key],
        "used_at": now.isoformat(),
    }


# ── 周期卡续费 ────────────────────────────────────────────────


async def renew_period(
    card_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """续费周期卡

    - 更新 period_start/end（从现有到期日顺延一个周期）
    - 重置 period_used_benefits = {}
    - status → active
    - INSERT usage_type=period_renewal 记录

    Returns:
        续费后卡详情
    """
    await _set_tenant(db, tenant_id)

    row = await db.execute(
        text("""
            SELECT pc.id, pc.customer_id, pc.card_type,
                   pc.status, pc.period_end, pc.expires_at,
                   pct.period_type
            FROM premium_cards pc
            JOIN premium_card_templates pct ON pct.id = pc.template_id
                AND pct.tenant_id = pc.tenant_id
            WHERE pc.id = :cid AND pc.tenant_id = :tid AND pc.is_deleted = false
            FOR UPDATE
        """),
        {"cid": card_id, "tid": tenant_id},
    )
    card = row.mappings().first()
    if not card:
        raise ValueError("card_not_found")
    if card["card_type"] != "period_card":
        raise ValueError("not_a_period_card")

    now = _now_utc()
    today = _today()
    period_type: str = card["period_type"]

    # 续费基准日：未到期从到期日顺延，已过期从今天重新开始
    old_period_end: Optional[date] = card["period_end"]
    if old_period_end and old_period_end >= today:
        new_period_start = old_period_end + timedelta(days=1)
    else:
        new_period_start = today

    new_period_end = _period_end(new_period_start, period_type)
    new_next_renewal = new_period_end + timedelta(days=1)
    new_expires_at = datetime(
        new_period_end.year, new_period_end.month, new_period_end.day, 23, 59, 59, tzinfo=timezone.utc
    )

    await db.execute(
        text("""
            UPDATE premium_cards
            SET period_start = :period_start,
                period_end = :period_end,
                next_renewal_at = :next_renewal_at,
                expires_at = :expires_at,
                period_used_benefits = '{}',
                status = 'active',
                updated_at = :now
            WHERE id = :cid AND tenant_id = :tid
        """),
        {
            "period_start": new_period_start,
            "period_end": new_period_end,
            "next_renewal_at": new_next_renewal,
            "expires_at": new_expires_at,
            "cid": card_id,
            "tid": tenant_id,
            "now": now,
        },
    )

    usage_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO premium_card_usages
                (id, tenant_id, card_id, customer_id, store_id, order_id,
                 usage_type, benefit_type,
                 uses_before, uses_after,
                 used_at, operator_id,
                 created_at, updated_at, is_deleted)
            VALUES
                (:id, :tid, :card_id, :cid, NULL, NULL,
                 'period_renewal', NULL,
                 NULL, NULL,
                 :now, NULL,
                 :now, :now, false)
        """),
        {
            "id": usage_id,
            "tid": tenant_id,
            "card_id": card_id,
            "cid": card["customer_id"],
            "now": now,
        },
    )
    await db.flush()

    logger.info(
        "premium_card_period_renewed",
        tenant_id=tenant_id,
        card_id=card_id,
        old_period_end=old_period_end.isoformat() if old_period_end else None,
        new_period_end=new_period_end.isoformat(),
        period_type=period_type,
    )

    # 续费后重新确认等级
    await _sync_member_level(str(card["customer_id"]), tenant_id, db)

    return {
        "card_id": card_id,
        "renewed": True,
        "old_period_end": old_period_end.isoformat() if old_period_end else None,
        "new_period_start": new_period_start.isoformat(),
        "new_period_end": new_period_end.isoformat(),
        "new_expires_at": new_expires_at.isoformat(),
        "period_used_benefits_reset": True,
    }


# ── 查询即将到期 ──────────────────────────────────────────────


async def get_expiring_cards(
    days_ahead: int,
    tenant_id: str,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """查询 N 天内到期的卡（用于定时提醒任务）

    - 次卡：expires_at <= now + N days
    - 周期卡：next_renewal_at <= now + N days

    Returns:
        [{"card_id", "customer_id", "card_type", "expires_at", "remaining_uses", ...}]
    """
    await _set_tenant(db, tenant_id)

    now = _now_utc()
    deadline = now + timedelta(days=days_ahead)

    rows = await db.execute(
        text("""
            SELECT pc.id, pc.customer_id, pc.card_type, pc.status,
                   pc.remaining_uses, pc.expires_at,
                   pc.period_end, pc.next_renewal_at,
                   pct.name AS template_name
            FROM premium_cards pc
            JOIN premium_card_templates pct ON pct.id = pc.template_id
                AND pct.tenant_id = pc.tenant_id
            WHERE pc.tenant_id = :tid
              AND pc.status = 'active'
              AND pc.is_deleted = false
              AND (
                  (pc.card_type = 'count_card'
                   AND pc.expires_at IS NOT NULL
                   AND pc.expires_at <= :deadline
                   AND pc.expires_at > :now)
                  OR
                  (pc.card_type = 'period_card'
                   AND pc.next_renewal_at IS NOT NULL
                   AND pc.next_renewal_at <= :deadline_date
                   AND pc.next_renewal_at > :today)
              )
            ORDER BY pc.expires_at ASC NULLS LAST,
                     pc.next_renewal_at ASC NULLS LAST
        """),
        {
            "tid": tenant_id,
            "deadline": deadline,
            "now": now,
            "deadline_date": deadline.date(),
            "today": _today(),
        },
    )

    cards = []
    for r in rows.mappings():
        c = dict(r)
        for k in ("expires_at", "period_end", "next_renewal_at"):
            if c.get(k) and hasattr(c[k], "isoformat"):
                c[k] = c[k].isoformat()
        cards.append(c)

    logger.info(
        "expiring_cards_queried",
        tenant_id=tenant_id,
        days_ahead=days_ahead,
        count=len(cards),
    )
    return cards


# ── 会员持有的卡列表 ──────────────────────────────────────────


async def list_customer_cards(
    customer_id: str,
    tenant_id: str,
    db: AsyncSession,
    active_only: bool = True,
) -> list[dict[str, Any]]:
    """查某会员持有的所有付费卡

    Returns:
        [{"card_id", "template_name", "card_type", "status", ...}]
    """
    await _set_tenant(db, tenant_id)

    where = "pc.customer_id = :cid AND pc.tenant_id = :tid AND pc.is_deleted = false"
    if active_only:
        where += " AND pc.status = 'active'"

    rows = await db.execute(
        text(f"""
            SELECT pc.id, pc.card_type, pc.status,
                   pc.remaining_uses, pc.total_uses,
                   pc.period_start, pc.period_end, pc.next_renewal_at,
                   pc.purchased_at, pc.expires_at,
                   pc.period_used_benefits::text,
                   pct.name AS template_name,
                   pct.benefits::text AS tpl_benefits,
                   pct.price_fen
            FROM premium_cards pc
            JOIN premium_card_templates pct ON pct.id = pc.template_id
                AND pct.tenant_id = pc.tenant_id
            WHERE {where}
            ORDER BY pc.purchased_at DESC
        """),
        {"cid": customer_id, "tid": tenant_id},
    )

    cards = []
    for r in rows.mappings():
        c = dict(r)
        c["period_used_benefits"] = json.loads(c["period_used_benefits"]) if c.get("period_used_benefits") else {}
        c["tpl_benefits"] = json.loads(c["tpl_benefits"]) if c.get("tpl_benefits") else []
        for k in ("period_start", "period_end", "next_renewal_at", "purchased_at", "expires_at"):
            if c.get(k) and hasattr(c[k], "isoformat"):
                c[k] = c[k].isoformat()
        cards.append(c)

    logger.info(
        "customer_cards_listed",
        tenant_id=tenant_id,
        customer_id=customer_id,
        count=len(cards),
        active_only=active_only,
    )
    return cards


# ── 卡详情 ────────────────────────────────────────────────────


async def get_card_detail(
    card_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """获取单张付费卡详情（含权益和使用情况）"""
    await _set_tenant(db, tenant_id)

    row = await db.execute(
        text("""
            SELECT pc.id, pc.customer_id, pc.store_id,
                   pc.card_type, pc.status,
                   pc.remaining_uses, pc.total_uses,
                   pc.period_start, pc.period_end, pc.next_renewal_at,
                   pc.purchased_at, pc.expires_at,
                   pc.period_used_benefits::text,
                   pct.name AS template_name,
                   pct.benefits::text AS tpl_benefits,
                   pct.price_fen, pct.period_type, pct.valid_days
            FROM premium_cards pc
            JOIN premium_card_templates pct ON pct.id = pc.template_id
                AND pct.tenant_id = pc.tenant_id
            WHERE pc.id = :cid AND pc.tenant_id = :tid AND pc.is_deleted = false
        """),
        {"cid": card_id, "tid": tenant_id},
    )
    card = row.mappings().first()
    if not card:
        raise ValueError("card_not_found")

    c = dict(card)
    c["period_used_benefits"] = json.loads(c["period_used_benefits"]) if c.get("period_used_benefits") else {}
    c["tpl_benefits"] = json.loads(c["tpl_benefits"]) if c.get("tpl_benefits") else []
    for k in ("period_start", "period_end", "next_renewal_at", "purchased_at", "expires_at"):
        if c.get(k) and hasattr(c[k], "isoformat"):
            c[k] = c[k].isoformat()

    return c


# ── 使用历史 ──────────────────────────────────────────────────


async def get_card_usage_history(
    card_id: str,
    tenant_id: str,
    db: AsyncSession,
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """查询付费卡使用历史（分页）"""
    await _set_tenant(db, tenant_id)

    offset = (page - 1) * size

    count_row = await db.execute(
        text("""
            SELECT COUNT(*) FROM premium_card_usages
            WHERE card_id = :cid AND tenant_id = :tid AND is_deleted = false
        """),
        {"cid": card_id, "tid": tenant_id},
    )
    total = count_row.scalar() or 0

    rows = await db.execute(
        text("""
            SELECT id, usage_type, benefit_type,
                   uses_before, uses_after,
                   store_id, order_id, operator_id,
                   used_at
            FROM premium_card_usages
            WHERE card_id = :cid AND tenant_id = :tid AND is_deleted = false
            ORDER BY used_at DESC
            LIMIT :size OFFSET :offset
        """),
        {"cid": card_id, "tid": tenant_id, "size": size, "offset": offset},
    )

    items = []
    for r in rows.mappings():
        item = dict(r)
        if item.get("used_at") and hasattr(item["used_at"], "isoformat"):
            item["used_at"] = item["used_at"].isoformat()
        items.append(item)

    return {"items": items, "total": total, "page": page, "size": size}


# ── 旧版兼容函数（保留不删）────────────────────────────────────


async def list_annual_plans(
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """年卡方案列表（旧接口兼容）"""
    await _set_tenant(db, tenant_id)
    plans = [{"plan_id": k, **v} for k, v in ANNUAL_PLANS.items()]
    logger.info("annual_plans_listed", tenant_id=tenant_id, plans_count=len(plans))
    return {"plans": plans}


async def purchase_annual_card(
    customer_id: str,
    plan_id: str,
    payment_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """购买年卡（旧接口兼容）"""
    await _set_tenant(db, tenant_id)

    plan = ANNUAL_PLANS.get(plan_id)
    if not plan:
        raise ValueError(f"invalid_plan_id:{plan_id}")

    existing = await db.execute(
        text("""
            SELECT id FROM premium_cards
            WHERE customer_id = :cid AND tenant_id = :tid
              AND status = 'active' AND (expires_at IS NULL OR expires_at > :now)
              AND is_deleted = false
            ORDER BY expires_at DESC LIMIT 1
        """),
        {"cid": customer_id, "tid": tenant_id, "now": _now_utc()},
    )
    if existing.mappings().first():
        raise ValueError("active_card_exists")

    card_id = str(uuid.uuid4())
    now = _now_utc()
    end_date = now + timedelta(days=plan["duration_days"])

    await db.execute(
        text("""
            INSERT INTO premium_cards
                (id, tenant_id, customer_id, template_id, store_id,
                 card_type, status,
                 remaining_uses, total_uses,
                 period_start, period_end, next_renewal_at,
                 purchased_at, expires_at,
                 period_used_benefits,
                 created_at, updated_at, is_deleted)
            VALUES
                (:id, :tid, :cid, NULL, NULL,
                 'period_card', 'active',
                 NULL, NULL,
                 :today, :period_end, :renewal,
                 :now, :expires_at,
                 '{}',
                 :now, :now, false)
        """),
        {
            "id": card_id,
            "tid": tenant_id,
            "cid": customer_id,
            "today": now.date(),
            "period_end": (now + timedelta(days=plan["duration_days"])).date(),
            "renewal": (now + timedelta(days=plan["duration_days"] + 1)).date(),
            "now": now,
            "expires_at": end_date,
        },
    )
    await db.flush()

    logger.info(
        "premium_card_purchased_legacy",
        tenant_id=tenant_id,
        card_id=card_id,
        customer_id=customer_id,
        plan_id=plan_id,
    )

    return {
        "card_id": card_id,
        "customer_id": customer_id,
        "plan_id": plan_id,
        "plan_name": plan["name"],
        "price_fen": plan["price_fen"],
        "start_date": now.isoformat(),
        "end_date": end_date.isoformat(),
        "benefits": plan["benefits"],
        "status": "active",
    }


async def get_card_benefits(
    card_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """权益清单（旧接口兼容）"""
    return await get_card_detail(card_id, tenant_id, db)


async def check_benefit_usage(
    card_id: str,
    benefit_type: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """权益使用情况（旧接口兼容）"""
    return await check_benefit(card_id, benefit_type, tenant_id, db)


async def renew_card(
    card_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """续费（旧接口兼容 → 路由至 renew_period）"""
    return await renew_period(card_id, tenant_id, db)


async def gift_card(
    sender_id: str,
    receiver_phone: str,
    plan_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """赠送年卡（旧接口兼容，保留原逻辑）"""
    await _set_tenant(db, tenant_id)

    plan = ANNUAL_PLANS.get(plan_id)
    if not plan:
        raise ValueError(f"invalid_plan_id:{plan_id}")
    if not receiver_phone or len(receiver_phone) != 11:
        raise ValueError("invalid_phone_number")

    gift_id = str(uuid.uuid4())
    redeem_code = uuid.uuid4().hex[:8].upper()
    now = _now_utc()

    await db.execute(
        text("""
            INSERT INTO premium_card_gifts
                (id, tenant_id, sender_id, receiver_phone, plan_id,
                 price_fen, redeem_code, status, created_at, updated_at, is_deleted)
            VALUES (:id, :tid, :sid, :phone, :pid,
                    :price, :code, 'pending', :now, :now, false)
        """),
        {
            "id": gift_id,
            "tid": tenant_id,
            "sid": sender_id,
            "phone": receiver_phone,
            "pid": plan_id,
            "price": plan["price_fen"],
            "code": redeem_code,
            "now": now,
        },
    )
    await db.flush()

    logger.info(
        "premium_card_gifted",
        tenant_id=tenant_id,
        gift_id=gift_id,
        sender_id=sender_id,
        receiver_phone=receiver_phone[-4:],
        plan_id=plan_id,
    )

    return {
        "gift_id": gift_id,
        "sender_id": sender_id,
        "receiver_phone": receiver_phone,
        "plan_id": plan_id,
        "plan_name": plan["name"],
        "price_fen": plan["price_fen"],
        "redeem_code": redeem_code,
        "status": "pending",
        "created_at": now.isoformat(),
    }
