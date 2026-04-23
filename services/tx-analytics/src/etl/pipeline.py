"""ETL Pipeline — 从品智Adapter拉取数据 → 标准化映射 → 写入Ontology表

职责:
- 订单数据 → Order + OrderItem 表
- 会员数据 → Customer 表（Golden ID 去重）
- 库存数据 → Ingredient + IngredientTransaction 表

规则:
- 所有写入必须带 tenant_id
- 幂等性：相同 external_order_id 不重复插入
- 单条记录失败不影响批次
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import select, text

from shared.adapters.pinzhi.src.adapter import PinzhiAdapter
from shared.adapters.pinzhi.src.inventory_sync import PinzhiInventorySync
from shared.adapters.pinzhi.src.member_sync import PinzhiMemberSync
from shared.adapters.pinzhi.src.order_sync import PinzhiOrderSync
from shared.ontology.src.database import async_session_factory
from shared.ontology.src.entities import (
    Customer,
    Ingredient,
    Order,
    OrderItem,
)

from .tenant_config import PinzhiTenantConfig

logger = structlog.get_logger()


class SyncStats:
    """同步统计收集器"""

    def __init__(self, tenant_name: str, sync_type: str) -> None:
        self.tenant_name = tenant_name
        self.sync_type = sync_type
        self.total = 0
        self.inserted = 0
        self.skipped = 0
        self.failed = 0
        self.errors: list[str] = []
        self.started_at = datetime.now(timezone.utc)
        self.finished_at: datetime | None = None

    def finish(self) -> dict[str, Any]:
        self.finished_at = datetime.now(timezone.utc)
        duration = (self.finished_at - self.started_at).total_seconds()
        return {
            "tenant_name": self.tenant_name,
            "sync_type": self.sync_type,
            "total": self.total,
            "inserted": self.inserted,
            "skipped": self.skipped,
            "failed": self.failed,
            "duration_seconds": round(duration, 2),
            "errors": self.errors[:20],
        }


class ETLPipeline:
    """品智 → 屯象 ETL 管道"""

    def __init__(self, tenant_config: PinzhiTenantConfig) -> None:
        self.tenant_config = tenant_config
        self.tenant_id = tenant_config.tenant_id
        self.adapter: PinzhiAdapter | None = None
        self.order_sync: PinzhiOrderSync | None = None
        self.member_sync: PinzhiMemberSync | None = None
        self.inventory_sync: PinzhiInventorySync | None = None

    async def _ensure_adapter(self) -> None:
        if self.adapter is None:
            self.adapter = PinzhiAdapter(self.tenant_config.to_adapter_config())
            self.order_sync = PinzhiOrderSync(self.adapter)
            self.member_sync = PinzhiMemberSync(self.adapter)
            self.inventory_sync = PinzhiInventorySync(self.adapter)

    async def close(self) -> None:
        if self.adapter is not None:
            await self.adapter.close()
            self.adapter = None

    async def sync_orders(self, start_date: str, end_date: str) -> dict[str, Any]:
        await self._ensure_adapter()
        assert self.order_sync is not None
        stats = SyncStats(self.tenant_config.tenant_name, "orders")
        for store_ognid in self.tenant_config.store_ognids:
            try:
                result = await self.order_sync.sync_orders(store_ognid, start_date)
                mapped_orders = result.get("orders", [])
                stats.total += result.get("total", 0)
                stats.failed += result.get("failed", 0)
                if start_date != end_date:
                    current = datetime.strptime(start_date, "%Y-%m-%d") + timedelta(days=1)
                    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
                    while current <= end_dt:
                        day_str = current.strftime("%Y-%m-%d")
                        day_result = await self.order_sync.sync_orders(store_ognid, day_str)
                        mapped_orders.extend(day_result.get("orders", []))
                        stats.total += day_result.get("total", 0)
                        stats.failed += day_result.get("failed", 0)
                        current += timedelta(days=1)
                await self._write_orders(mapped_orders, store_ognid, stats)
            except (ConnectionError, TimeoutError, ValueError) as exc:
                logger.error("order_sync_store_failed", store_ognid=store_ognid, error=str(exc))
                stats.errors.append(f"门店{store_ognid}订单同步失败: {exc}")
                stats.failed += 1
        result = stats.finish()
        logger.info("order_sync_completed", **result)
        return result

    async def _write_orders(self, mapped_orders: list[dict[str, Any]], store_ognid: str, stats: SyncStats) -> None:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(self.tenant_id)})
            for order_data in mapped_orders:
                try:
                    external_order_id = order_data.get("order_id", "")
                    if not external_order_id:
                        stats.failed += 1
                        continue
                    order_no = order_data.get("order_number", external_order_id)
                    existing = await session.execute(
                        select(Order.id).where(
                            Order.tenant_id == self.tenant_id, Order.order_no == order_no, Order.is_deleted == False
                        )  # noqa: E712
                    )
                    if existing.scalar_one_or_none() is not None:
                        stats.skipped += 1
                        continue
                    order_time = _parse_datetime(order_data.get("created_at"))
                    completed_at = _parse_datetime(order_data.get("completed_at"))
                    order = Order(
                        tenant_id=self.tenant_id,
                        order_no=order_no,
                        store_id=uuid.uuid4(),
                        order_type=order_data.get("order_type", "dine_in"),
                        total_amount_fen=order_data.get("subtotal_fen", 0),
                        discount_amount_fen=order_data.get("discount_fen", 0),
                        final_amount_fen=order_data.get("total_fen", 0),
                        status=order_data.get("order_status", "pending"),
                        order_time=order_time or datetime.now(timezone.utc),
                        completed_at=completed_at,
                        guest_count=order_data.get("head_count"),
                        order_metadata={
                            "external_order_id": external_order_id,
                            "source_system": "pinzhi",
                            "store_ognid": store_ognid,
                        },
                    )
                    session.add(order)
                    await session.flush()
                    for item_data in order_data.get("items", []):
                        order_item = OrderItem(
                            tenant_id=self.tenant_id,
                            order_id=order.id,
                            item_name=item_data.get("dish_name", ""),
                            quantity=item_data.get("quantity", 1),
                            unit_price_fen=item_data.get("unit_price_fen", 0),
                            subtotal_fen=item_data.get("subtotal_fen", 0),
                        )
                        session.add(order_item)
                    stats.inserted += 1
                except (KeyError, ValueError, TypeError) as exc:
                    logger.warning("order_write_failed", error=str(exc))
                    stats.errors.append(f"订单写入失败 {order_data.get('order_id', '?')}: {exc}")
                    stats.failed += 1
            await session.commit()

    async def sync_members(self) -> dict[str, Any]:
        await self._ensure_adapter()
        assert self.member_sync is not None
        stats = SyncStats(self.tenant_config.tenant_name, "members")
        for store_ognid in self.tenant_config.store_ognids:
            try:
                result = await self.member_sync.sync_members(store_ognid)
                mapped_members = result.get("members", [])
                stats.total += result.get("total", 0)
                await self._write_members(mapped_members, stats)
            except (ConnectionError, TimeoutError, ValueError) as exc:
                logger.error("member_sync_store_failed", store_ognid=store_ognid, error=str(exc))
                stats.errors.append(f"门店{store_ognid}会员同步失败: {exc}")
                stats.failed += 1
        result = stats.finish()
        logger.info("member_sync_completed", **result)
        return result

    async def _write_members(self, mapped_members: list[dict[str, Any]], stats: SyncStats) -> None:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(self.tenant_id)})
            for member_data in mapped_members:
                try:
                    phone = _extract_phone(member_data)
                    if not phone:
                        stats.skipped += 1
                        continue
                    existing_result = await session.execute(
                        select(Customer).where(
                            Customer.tenant_id == self.tenant_id,
                            Customer.primary_phone == phone,
                            Customer.is_deleted == False,
                        )  # noqa: E712
                    )
                    existing_customer = existing_result.scalar_one_or_none()
                    if existing_customer is not None:
                        _update_customer_from_member(existing_customer, member_data)
                        stats.skipped += 1
                        continue
                    customer = Customer(
                        tenant_id=self.tenant_id,
                        primary_phone=phone,
                        display_name=member_data.get("name", ""),
                        gender=member_data.get("gender"),
                        total_order_count=member_data.get("visit_count", 0),
                        total_order_amount_fen=member_data.get("total_consumption_fen", 0),
                        source="pinzhi",
                        extra={
                            "source_id": member_data.get("source_id", ""),
                            "level": member_data.get("level", "normal"),
                        },
                    )
                    session.add(customer)
                    stats.inserted += 1
                except (KeyError, ValueError, TypeError) as exc:
                    logger.warning("member_write_failed", error=str(exc))
                    stats.errors.append(f"会员写入失败: {exc}")
                    stats.failed += 1
            await session.commit()

    async def sync_inventory(self) -> dict[str, Any]:
        await self._ensure_adapter()
        assert self.inventory_sync is not None
        stats = SyncStats(self.tenant_config.tenant_name, "inventory")
        for store_ognid in self.tenant_config.store_ognids:
            try:
                result = await self.inventory_sync.sync_inventory(store_ognid)
                mapped_ingredients = result.get("ingredients", [])
                stats.total += result.get("total", 0)
                await self._write_ingredients(mapped_ingredients, store_ognid, stats)
            except (ConnectionError, TimeoutError, ValueError) as exc:
                logger.error("inventory_sync_store_failed", store_ognid=store_ognid, error=str(exc))
                stats.errors.append(f"门店{store_ognid}库存同步失败: {exc}")
                stats.failed += 1
        result = stats.finish()
        logger.info("inventory_sync_completed", **result)
        return result

    async def _write_ingredients(
        self, mapped_ingredients: list[dict[str, Any]], store_ognid: str, stats: SyncStats
    ) -> None:
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(self.tenant_id)})
            for ing_data in mapped_ingredients:
                try:
                    ingredient_name = ing_data.get("ingredient_name", "")
                    if not ingredient_name:
                        stats.skipped += 1
                        continue
                    existing_result = await session.execute(
                        select(Ingredient).where(
                            Ingredient.tenant_id == self.tenant_id,
                            Ingredient.ingredient_name == ingredient_name,
                            Ingredient.is_deleted == False,
                        )  # noqa: E712
                    )
                    if existing_result.scalar_one_or_none() is not None:
                        stats.skipped += 1
                        continue
                    ingredient = Ingredient(
                        tenant_id=self.tenant_id,
                        store_id=uuid.uuid4(),
                        ingredient_name=ingredient_name,
                        category=ing_data.get("category", ""),
                        unit=ing_data.get("unit", "g"),
                        current_quantity=ing_data.get("stock_qty", 0),
                        min_quantity=ing_data.get("alert_qty", 0),
                        status=ing_data.get("status", "normal"),
                    )
                    session.add(ingredient)
                    stats.inserted += 1
                except (KeyError, ValueError, TypeError) as exc:
                    logger.warning("ingredient_write_failed", error=str(exc))
                    stats.errors.append(f"食材写入失败: {exc}")
                    stats.failed += 1
            await session.commit()

    async def run_full_sync(self, start_date: str, end_date: str) -> dict[str, Any]:
        await self._ensure_adapter()
        logger.info(
            "full_sync_started", tenant=self.tenant_config.tenant_name, start_date=start_date, end_date=end_date
        )
        results: dict[str, Any] = {}
        try:
            results["orders"] = await self.sync_orders(start_date, end_date)
        except (ConnectionError, TimeoutError, RuntimeError) as exc:
            results["orders"] = {"error": str(exc)}
        try:
            results["members"] = await self.sync_members()
        except (ConnectionError, TimeoutError, RuntimeError) as exc:
            results["members"] = {"error": str(exc)}
        try:
            results["inventory"] = await self.sync_inventory()
        except (ConnectionError, TimeoutError, RuntimeError) as exc:
            results["inventory"] = {"error": str(exc)}
        await self.close()
        logger.info("full_sync_completed", tenant=self.tenant_config.tenant_name, results=results)
        return results


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("T", " "))
    except (ValueError, TypeError):
        return None


def _extract_phone(member_data: dict[str, Any]) -> str | None:
    for ident in member_data.get("identities", []):
        if ident.get("type") == "phone":
            return ident.get("value")
    return None


def _update_customer_from_member(customer: Customer, member_data: dict[str, Any]) -> None:
    name = member_data.get("name")
    if name:
        customer.display_name = name
    visit_count = member_data.get("visit_count", 0)
    if visit_count > (customer.total_order_count or 0):
        customer.total_order_count = visit_count
