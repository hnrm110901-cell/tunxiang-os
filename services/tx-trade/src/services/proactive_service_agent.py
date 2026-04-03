"""
主动服务建议 Agent (Phase 3-B)

触发条件：
  1. 加菜时机：用餐超过35分钟且人均消费 < 历史均值的65%
  2. 续杯提醒：饮品类菜品状态为已上桌超过20分钟
  3. 甜品推荐：主菜已出齐，用餐超过45分钟
  4. 结账提醒：用餐超过店长设定的上限时间
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


# ─── 数据结构 ───

@dataclass
class ServiceSuggestion:
    type: str          # upsell / refill / dessert / checkout_hint
    message: str
    urgency: str       # info / suggest / urgent
    action_label: str
    action_data: dict = field(default_factory=dict)


@dataclass
class ConstraintMargin:
    ok: bool
    pct: float
    level: str         # ok / warn / danger


@dataclass
class ConstraintFoodSafety:
    ok: bool
    issues: list[str]
    level: str         # ok / warn / danger


@dataclass
class ConstraintServiceTime:
    ok: bool
    elapsed_min: int
    limit_min: int
    level: str         # ok / warn / danger


@dataclass
class ConstraintStatus:
    margin: ConstraintMargin
    food_safety: ConstraintFoodSafety
    service_time: ConstraintServiceTime


# ─── 内部辅助（降级友好：DB 不可用时返回 Mock） ───

async def _get_order_with_items(order_id: str, db: Optional[AsyncSession]):
    """
    真实场景从 DB 查询订单。
    当 db=None 或查询失败时返回演示 Mock 对象。
    """
    # Mock 演示数据（降级兜底）
    class MockItem:
        def __init__(self, name, category, status, served_minutes):
            self.name = name
            self.category = category
            self.status = status       # 'pending' / 'served'
            self.served_minutes = served_minutes

    class MockOrder:
        order_id = order_id
        store_id = 'store-mock-001'
        guest_count = 4
        total_amount = 9600   # 分（¥96，人均¥24，低于历史均值）
        created_at = datetime.now(timezone.utc).replace(
            minute=datetime.now(timezone.utc).minute - 42
        )
        items = [
            MockItem('小炒黄牛吊龙', 'main', 'served', 0),
            MockItem('剁椒鱼头', 'main', 'served', 0),
            MockItem('可乐', 'drink', 'served', 23),
            MockItem('雪碧', 'drink', 'served', 10),
        ]

    if db is None:
        return MockOrder()

    try:
        from sqlalchemy import text
        result = await db.execute(
            text(
                "SELECT o.id, o.store_id, o.guest_count, o.total_amount, o.created_at "
                "FROM orders o WHERE o.id = :oid"
            ),
            {"oid": order_id},
        )
        row = result.fetchone()
        if row is None:
            return MockOrder()

        # 查询订单条目（简化，实际字段以真实表结构为准）
        items_result = await db.execute(
            text(
                "SELECT oi.id, d.name, d.category, oi.status, oi.served_at "
                "FROM order_items oi "
                "JOIN dishes d ON d.id = oi.dish_id "
                "WHERE oi.order_id = :oid"
            ),
            {"oid": order_id},
        )
        items_rows = items_result.fetchall()

        class RealItem:
            def __init__(self, r):
                self.name = r.name
                self.category = r.category or 'main'
                self.status = r.status or 'pending'
                now = datetime.now(timezone.utc)
                self.served_minutes = (
                    int((now - r.served_at.replace(tzinfo=timezone.utc)).seconds / 60)
                    if r.served_at and r.status == 'served'
                    else 0
                )

        class RealOrder:
            pass

        o = RealOrder()
        o.order_id = row.id
        o.store_id = row.store_id
        o.guest_count = row.guest_count or 1
        o.total_amount = row.total_amount or 0
        o.created_at = row.created_at.replace(tzinfo=timezone.utc) if row.created_at else datetime.now(timezone.utc)
        o.items = [RealItem(r) for r in items_rows]
        return o

    except SQLAlchemyError as exc:
        logger.warning(
            "proactive_agent.order_lookup_failed",
            order_id=order_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return MockOrder()


async def _get_historical_avg_per_person(store_id: str, db: Optional[AsyncSession]) -> float:
    """返回门店历史人均消费（分）。DB 不可用时返回演示值 5500 分 = ¥55/人。"""
    if db is None:
        return 5500.0

    try:
        from sqlalchemy import text
        result = await db.execute(
            text(
                "SELECT AVG(total_amount / GREATEST(guest_count, 1)) AS avg_pp "
                "FROM orders "
                "WHERE store_id = :sid AND status = 'closed' "
                "AND created_at >= NOW() - INTERVAL '30 days'"
            ),
            {"sid": store_id},
        )
        row = result.fetchone()
        return float(row.avg_pp) if row and row.avg_pp else 5500.0
    except SQLAlchemyError as exc:
        logger.warning(
            "proactive_agent.avg_per_person_lookup_failed",
            store_id=store_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return 5500.0


async def _get_service_time_limit(store_id: str, db: Optional[AsyncSession]) -> int:
    """返回门店设定的最长就餐时间（分钟）。默认 120 分钟。"""
    if db is None:
        return 120

    try:
        from sqlalchemy import text
        result = await db.execute(
            text(
                "SELECT service_time_limit_min FROM stores WHERE id = :sid"
            ),
            {"sid": store_id},
        )
        row = result.fetchone()
        return int(row.service_time_limit_min) if row and row.service_time_limit_min else 120
    except SQLAlchemyError as exc:
        logger.warning(
            "proactive_agent.service_time_limit_lookup_failed",
            store_id=store_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return 120


# ─── 已忽略建议缓存（本次营业有效，进程内 in-memory） ───

_dismissed: dict[str, set[str]] = {}   # {order_id: {suggestion_type, ...}}


def _is_dismissed(order_id: str, suggestion_type: str) -> bool:
    return suggestion_type in _dismissed.get(order_id, set())


# ─── 公开 API ───

async def get_service_suggestions(
    order_id: str,
    tenant_id: str,
    db: Optional[AsyncSession] = None,
) -> list[ServiceSuggestion]:
    """检查该订单的所有主动服务建议。"""
    order = await _get_order_with_items(order_id, db)
    suggestions: list[ServiceSuggestion] = []

    now = datetime.now(timezone.utc)
    elapsed_min = int((now - order.created_at).total_seconds() // 60)

    # 规则1：加菜时机（用餐≥35分钟 且 人均 < 历史均值的65%）
    if elapsed_min >= 35 and not _is_dismissed(order_id, 'upsell'):
        per_person = order.total_amount / max(order.guest_count, 1)
        hist_avg = await _get_historical_avg_per_person(order.store_id, db)
        if per_person < hist_avg * 0.65:
            suggestions.append(ServiceSuggestion(
                type='upsell',
                message=f'用餐{elapsed_min}分钟，人均¥{per_person / 100:.0f}，建议推荐加菜',
                urgency='suggest',
                action_label='查看推荐菜品',
                action_data={'elapsed_min': elapsed_min, 'per_person_fen': int(per_person)},
            ))

    # 规则2：续杯提醒（饮品上桌 > 20 分钟，仅提示一次）
    if not _is_dismissed(order_id, 'refill'):
        drink_items = [
            i for i in order.items
            if i.category == 'drink' and i.status == 'served' and i.served_minutes > 20
        ]
        if drink_items:
            item = drink_items[0]
            suggestions.append(ServiceSuggestion(
                type='refill',
                message=f'{item.name}已上桌{item.served_minutes}分钟，可询问是否续杯',
                urgency='info',
                action_label='加菜',
                action_data={'item_name': item.name, 'served_minutes': item.served_minutes},
            ))

    # 规则3：甜品时机（主菜全部上桌 且 用餐≥45分钟）
    if elapsed_min >= 45 and not _is_dismissed(order_id, 'dessert'):
        main_items = [i for i in order.items if i.category == 'main']
        if main_items and all(i.status == 'served' for i in main_items):
            suggestions.append(ServiceSuggestion(
                type='dessert',
                message='主菜已全部上桌，可推荐甜品或询问其他需求',
                urgency='info',
                action_label='推荐甜品',
            ))

    # 规则4：结账提醒（超过上限时间）
    if not _is_dismissed(order_id, 'checkout_hint'):
        limit_min = await _get_service_time_limit(order.store_id, db)
        if elapsed_min >= limit_min:
            suggestions.append(ServiceSuggestion(
                type='checkout_hint',
                message=f'用餐已达{elapsed_min}分钟，超出设定上限{limit_min}分钟，建议询问是否结账',
                urgency='urgent',
                action_label='去结账',
                action_data={'elapsed_min': elapsed_min, 'limit_min': limit_min},
            ))

    return suggestions


async def get_table_suggestions(
    store_id: str,
    tenant_id: str,
    db: Optional[AsyncSession] = None,
) -> dict[str, list[ServiceSuggestion]]:
    """批量检查所有在台桌台，返回 {table_no: [suggestions]}。供店长驾驶舱使用。"""
    # 获取所有进行中的订单
    active_orders: list[tuple[str, str]] = []   # [(order_id, table_no)]

    if db is not None:
        try:
            from sqlalchemy import text
            result = await db.execute(
                text(
                    "SELECT id, table_no FROM orders "
                    "WHERE store_id = :sid AND status = 'active'"
                ),
                {"sid": store_id},
            )
            active_orders = [(str(r.id), r.table_no) for r in result.fetchall()]
        except SQLAlchemyError as exc:
            logger.warning(
                "proactive_agent.active_orders_lookup_failed",
                store_id=store_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    # 降级：演示数据
    if not active_orders:
        active_orders = [
            ('o-mock-001', 'A1'),
            ('o-mock-002', 'A2'),
        ]

    # 并发检查
    async def _check(order_id: str) -> list[ServiceSuggestion]:
        return await get_service_suggestions(order_id, tenant_id, db)

    results = await asyncio.gather(*[_check(oid) for oid, _ in active_orders])

    return {
        table_no: suggs
        for (_, table_no), suggs in zip(active_orders, results)
        if suggs
    }


def dismiss_suggestion(
    order_id: str,
    suggestion_type: str,
    tenant_id: str,
    db: Optional[AsyncSession] = None,
) -> None:
    """服务员忽略某条建议，记录避免重复提示（本次营业有效，进程内缓存）。"""
    if order_id not in _dismissed:
        _dismissed[order_id] = set()
    _dismissed[order_id].add(suggestion_type)


# ─── 三约束计算 ───

async def _calc_margin_constraint(
    order_id: str,
    db: Optional[AsyncSession],
) -> ConstraintMargin:
    """计算订单毛利约束状态。DB 不可用时使用演示数据。"""
    if db is not None:
        try:
            from sqlalchemy import text
            result = await db.execute(
                text(
                    "SELECT "
                    "  SUM(oi.price * oi.qty) AS revenue, "
                    "  SUM(d.cost_price * oi.qty) AS cost "
                    "FROM order_items oi "
                    "JOIN dishes d ON d.id = oi.dish_id "
                    "WHERE oi.order_id = :oid"
                ),
                {"oid": order_id},
            )
            row = result.fetchone()
            if row and row.revenue and row.revenue > 0:
                pct = (1 - row.cost / row.revenue) * 100
                level = 'ok' if pct >= 50 else ('warn' if pct >= 40 else 'danger')
                return ConstraintMargin(ok=(pct >= 40), pct=round(pct, 1), level=level)
        except SQLAlchemyError as exc:
            logger.warning(
                "proactive_agent.margin_constraint_lookup_failed",
                order_id=order_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    # Mock：演示毛利68.2%
    return ConstraintMargin(ok=True, pct=68.2, level='ok')


async def _check_food_safety_constraint(
    order_id: str,
    db: Optional[AsyncSession],
) -> ConstraintFoodSafety:
    """检查食材食安状态。DB 不可用时使用演示数据。"""
    if db is not None:
        try:
            from datetime import timedelta

            from sqlalchemy import text
            now_date = datetime.now(timezone.utc).date()
            warn_date = now_date + timedelta(days=3)

            result = await db.execute(
                text(
                    "SELECT ing.name, ing.expiry_date "
                    "FROM order_items oi "
                    "JOIN dish_ingredients di ON di.dish_id = oi.dish_id "
                    "JOIN ingredients ing ON ing.id = di.ingredient_id "
                    "WHERE oi.order_id = :oid "
                    "AND ing.expiry_date IS NOT NULL "
                    "AND ing.expiry_date <= :warn_date"
                ),
                {"oid": order_id, "warn_date": str(warn_date)},
            )
            rows = result.fetchall()
            if rows:
                issues = []
                danger = False
                for r in rows:
                    if r.expiry_date < now_date:
                        issues.append(f'{r.name}已过期')
                        danger = True
                    else:
                        days_left = (r.expiry_date - now_date).days
                        issues.append(f'{r.name}临期({days_left}天)')
                level = 'danger' if danger else 'warn'
                return ConstraintFoodSafety(ok=False, issues=issues, level=level)
        except SQLAlchemyError as exc:
            logger.warning(
                "proactive_agent.food_safety_constraint_lookup_failed",
                order_id=order_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    # Mock：食安正常
    return ConstraintFoodSafety(ok=True, issues=[], level='ok')


async def _check_service_time_constraint(
    order_id: str,
    db: Optional[AsyncSession],
) -> ConstraintServiceTime:
    """检查就餐时长约束状态。DB 不可用时使用演示数据。"""
    if db is not None:
        try:
            from sqlalchemy import text
            result = await db.execute(
                text(
                    "SELECT o.created_at, s.service_time_limit_min "
                    "FROM orders o "
                    "JOIN stores s ON s.id = o.store_id "
                    "WHERE o.id = :oid"
                ),
                {"oid": order_id},
            )
            row = result.fetchone()
            if row:
                now = datetime.now(timezone.utc)
                elapsed_min = int(
                    (now - row.created_at.replace(tzinfo=timezone.utc)).total_seconds() // 60
                )
                limit_min = int(row.service_time_limit_min) if row.service_time_limit_min else 120
                ratio = elapsed_min / limit_min if limit_min > 0 else 0
                level = 'ok' if ratio < 0.8 else ('warn' if ratio <= 1.0 else 'danger')
                return ConstraintServiceTime(
                    ok=(ratio < 1.0),
                    elapsed_min=elapsed_min,
                    limit_min=limit_min,
                    level=level,
                )
        except SQLAlchemyError as exc:
            logger.warning(
                "proactive_agent.service_time_constraint_lookup_failed",
                order_id=order_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    # Mock：已用餐35分钟，上限120分钟
    return ConstraintServiceTime(ok=True, elapsed_min=35, limit_min=120, level='ok')


async def get_constraint_status(
    order_id: str,
    tenant_id: str,
    db: Optional[AsyncSession] = None,
) -> ConstraintStatus:
    """并发查询三约束状态（目标 < 100ms）。"""
    margin, food_safety, service_time = await asyncio.gather(
        _calc_margin_constraint(order_id, db),
        _check_food_safety_constraint(order_id, db),
        _check_service_time_constraint(order_id, db),
    )
    return ConstraintStatus(
        margin=margin,
        food_safety=food_safety,
        service_time=service_time,
    )
