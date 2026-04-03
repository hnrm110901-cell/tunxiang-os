"""档口路由规则引擎 — 多品牌/多渠道/时段路由

按优先级遍历规则，返回目标档口ID和可选打印机ID。
无匹配时fallback到DishDeptMapping默认映射。

缓存策略：每个 (tenant_id, store_id) 的规则列表缓存5分钟，
规则增删改时通过 invalidate_store_cache() 失效。
"""
import uuid
from datetime import datetime
from typing import Optional

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.dispatch_rule import DispatchRule
from ..models.production_dept import DishDeptMapping

logger = structlog.get_logger()

# ── 简单内存缓存（key → (rules, expire_ts)） ──
_rule_cache: dict[str, tuple[list[DispatchRule], float]] = {}
_CACHE_TTL_SECONDS = 300  # 5分钟


def _cache_key(tenant_id: str, store_id: str) -> str:
    return f"{tenant_id}:{store_id}"


def invalidate_store_cache(tenant_id: str, store_id: str) -> None:
    """规则变更时调用，立即失效对应门店的规则缓存。

    不影响其他门店的缓存，也不中断正在进行中的 KDS 任务。
    """
    key = _cache_key(tenant_id, store_id)
    _rule_cache.pop(key, None)
    logger.info("dispatch_rule_engine.cache_invalidated", tenant_id=tenant_id, store_id=store_id)


def _is_cache_valid(key: str) -> bool:
    import time as _time
    if key not in _rule_cache:
        return False
    _, expire_ts = _rule_cache[key]
    return _time.monotonic() < expire_ts


async def _load_rules(
    tenant_id: str,
    store_id: str,
    db: AsyncSession,
) -> list[DispatchRule]:
    """加载门店所有启用规则（按 priority DESC），优先从缓存读取。"""
    import time as _time
    key = _cache_key(tenant_id, store_id)

    if _is_cache_valid(key):
        rules, _ = _rule_cache[key]
        logger.debug("dispatch_rule_engine.cache_hit", key=key)
        return rules

    tid = uuid.UUID(tenant_id)
    sid = uuid.UUID(store_id)

    stmt = (
        select(DispatchRule)
        .where(
            and_(
                DispatchRule.tenant_id == tid,
                DispatchRule.store_id == sid,
                DispatchRule.is_active == True,  # noqa: E712
                DispatchRule.is_deleted == False,  # noqa: E712
            )
        )
        .order_by(DispatchRule.priority.desc())
    )
    result = await db.execute(stmt)
    rules = list(result.scalars().all())

    expire_ts = _time.monotonic() + _CACHE_TTL_SECONDS
    _rule_cache[key] = (rules, expire_ts)
    logger.debug("dispatch_rule_engine.cache_miss", key=key, rule_count=len(rules))
    return rules


def _rule_matches(
    rule: DispatchRule,
    dish_id: Optional[uuid.UUID],
    dish_category: Optional[str],
    brand_id: Optional[uuid.UUID],
    channel: Optional[str],
    order_time: datetime,
) -> bool:
    """检查单条规则是否与给定上下文完全匹配（NULL条件=通配）。"""
    # 菜品ID精确匹配
    if rule.match_dish_id is not None:
        if dish_id is None or rule.match_dish_id != dish_id:
            return False

    # 菜品分类匹配
    if rule.match_dish_category is not None:
        if dish_category is None or rule.match_dish_category != dish_category:
            return False

    # 品牌匹配
    if rule.match_brand_id is not None:
        if brand_id is None or rule.match_brand_id != brand_id:
            return False

    # 渠道匹配
    if rule.match_channel is not None:
        if channel is None or rule.match_channel != channel:
            return False

    # 时段匹配（match_time_start 和 match_time_end 必须同时有值才生效）
    if rule.match_time_start is not None and rule.match_time_end is not None:
        current_time = order_time.time().replace(tzinfo=None)
        start = rule.match_time_start
        end = rule.match_time_end

        if start <= end:
            # 普通时段，如 11:00-14:00
            if not (start <= current_time <= end):
                return False
        else:
            # 跨午夜时段，如 22:00-02:00
            if not (current_time >= start or current_time <= end):
                return False

    # 工作日类型匹配
    if rule.match_day_type is not None:
        weekday = order_time.weekday()  # 0=周一 … 6=周日
        if rule.match_day_type == "weekday" and weekday >= 5 or rule.match_day_type == "weekend" and weekday < 5:
            return False
        # holiday 类型需要外部维护节假日表，此处跳过（不拦截）

    return True


class DispatchRuleEngine:
    """多品牌/多渠道档口路由规则引擎。"""

    async def resolve_dept(
        self,
        dish_id: Optional[str],
        dish_category: Optional[str],
        brand_id: Optional[str],
        channel: Optional[str],
        order_time: datetime,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> tuple[Optional[uuid.UUID], Optional[uuid.UUID]]:
        """解析档口路由，返回 (dept_id, printer_id)。

        Args:
            dish_id: 菜品UUID字符串，可None
            dish_category: 菜品分类名称，可None
            brand_id: 品牌UUID字符串，可None
            channel: 渠道类型 dine_in/takeaway/delivery/reservation，可None
            order_time: 下单时间（带时区）
            store_id: 门店UUID字符串
            tenant_id: 租户UUID字符串（必须显式传入，不从会话变量读取）
            db: 数据库会话

        Returns:
            (target_dept_id, target_printer_id)，若无匹配则从DishDeptMapping
            fallback，若DishDeptMapping也无映射则返回 (None, None)。
        """
        log = logger.bind(
            tenant_id=tenant_id, store_id=store_id,
            dish_id=dish_id, channel=channel,
        )

        dish_uuid = uuid.UUID(dish_id) if dish_id else None
        brand_uuid = uuid.UUID(brand_id) if brand_id else None

        # ── 1. 按优先级遍历规则 ──
        try:
            rules = await _load_rules(tenant_id, store_id, db)
        except (ValueError, AttributeError) as exc:
            log.error("dispatch_rule_engine.load_rules_failed", error=str(exc), exc_info=True)
            rules = []

        for rule in rules:
            if _rule_matches(rule, dish_uuid, dish_category, brand_uuid, channel, order_time):
                log.info(
                    "dispatch_rule_engine.rule_matched",
                    rule_id=str(rule.id),
                    rule_name=rule.name,
                    target_dept_id=str(rule.target_dept_id),
                )
                return rule.target_dept_id, rule.target_printer_id

        # ── 2. Fallback到DishDeptMapping ──
        if dish_uuid is not None:
            tid = uuid.UUID(tenant_id)
            stmt = select(
                DishDeptMapping.production_dept_id,
                DishDeptMapping.printer_id,
            ).where(
                and_(
                    DishDeptMapping.tenant_id == tid,
                    DishDeptMapping.dish_id == dish_uuid,
                    DishDeptMapping.is_deleted == False,  # noqa: E712
                )
            )
            result = await db.execute(stmt)
            row = result.one_or_none()
            if row:
                log.info(
                    "dispatch_rule_engine.fallback_dish_dept_mapping",
                    dept_id=str(row[0]),
                )
                return row[0], row[1]

        log.info("dispatch_rule_engine.no_mapping_found")
        return None, None

    async def test_rule(
        self,
        rule_id: str,
        test_context: dict,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """管理员测试某条规则是否匹配给定上下文。

        Args:
            rule_id: 规则UUID字符串
            test_context: {
                "dish_id": str | None,
                "dish_category": str | None,
                "brand_id": str | None,
                "channel": str | None,
                "order_time": str (ISO8601),
            }
            tenant_id: 租户ID（安全隔离）
            db: 数据库会话

        Returns:
            {"matched": bool, "reason": str}
        """
        tid = uuid.UUID(tenant_id)
        rid = uuid.UUID(rule_id)

        stmt = select(DispatchRule).where(
            and_(
                DispatchRule.id == rid,
                DispatchRule.tenant_id == tid,
                DispatchRule.is_deleted == False,  # noqa: E712
            )
        )
        result = await db.execute(stmt)
        rule = result.scalar_one_or_none()

        if rule is None:
            return {"matched": False, "reason": "rule_not_found"}

        # 解析测试上下文
        dish_id_str = test_context.get("dish_id")
        dish_category = test_context.get("dish_category")
        brand_id_str = test_context.get("brand_id")
        channel = test_context.get("channel")
        order_time_str = test_context.get("order_time")

        dish_uuid = uuid.UUID(dish_id_str) if dish_id_str else None
        brand_uuid = uuid.UUID(brand_id_str) if brand_id_str else None

        if order_time_str:
            order_time = datetime.fromisoformat(order_time_str)
        else:
            from datetime import timezone
            order_time = datetime.now(timezone.utc)

        matched = _rule_matches(rule, dish_uuid, dish_category, brand_uuid, channel, order_time)
        reason = "matched" if matched else "conditions_not_met"

        logger.info(
            "dispatch_rule_engine.test_rule",
            rule_id=rule_id,
            matched=matched,
            tenant_id=tenant_id,
        )
        return {
            "matched": matched,
            "reason": reason,
            "rule_name": rule.name,
            "target_dept_id": str(rule.target_dept_id),
            "target_printer_id": str(rule.target_printer_id) if rule.target_printer_id else None,
        }


# 全局单例
dispatch_rule_engine = DispatchRuleEngine()
