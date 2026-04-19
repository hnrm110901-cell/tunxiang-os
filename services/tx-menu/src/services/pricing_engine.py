"""定价与时价中心

正餐场景定价引擎：标准售价、时价菜(海鲜/活鲜)、称重计价、套餐组合定价、
多渠道差异价、促销价、毛利底线校验、调价审批。

金额单位: 分(fen), int 类型。
重量单位: 克(g), int 类型。
"""

import asyncio
import uuid
from datetime import datetime
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events import MenuEventType, UniversalPublisher

log = structlog.get_logger(__name__)

# 默认毛利底线 30%（可门店级配置覆盖）
DEFAULT_MIN_MARGIN_RATE = 0.30


class PricingEngine:
    """定价与时价中心"""

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self._tenant_uuid = uuid.UUID(tenant_id)

    async def _set_tenant(self) -> None:
        """设置 RLS tenant context"""
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self.tenant_id},
        )

    async def _get_store_margin_rate(self, store_id: Optional[str] = None) -> float:
        """获取门店级毛利底线配置，未配置则返回默认值"""
        if not store_id:
            return DEFAULT_MIN_MARGIN_RATE

        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT config_value
                FROM store_configs
                WHERE store_id = :store_id
                  AND tenant_id = :tenant_id
                  AND config_key = 'min_margin_rate'
                  AND is_deleted = false
                LIMIT 1
            """),
            {"store_id": uuid.UUID(store_id), "tenant_id": self._tenant_uuid},
        )
        row = result.scalar_one_or_none()
        if row is not None:
            return float(row)
        return DEFAULT_MIN_MARGIN_RATE

    # ─── 1. 标准售价查询 ───

    async def get_standard_price(
        self,
        dish_id: str,
        channel: str = "dine_in",
        tenant_id: Optional[str] = None,
        db: Optional[AsyncSession] = None,
    ) -> dict:
        """查询菜品标准售价（分）

        优先级：渠道价 > 促销价(有效期内) > 基础售价

        Args:
            dish_id: 菜品 ID
            channel: 渠道 (dine_in / takeaway / delivery / miniapp)

        Returns:
            {
                "dish_id": str,
                "price_fen": int,
                "price_type": str,  # "base" | "channel" | "promotion" | "market"
                "channel": str,
            }
        """
        await self._set_tenant()
        dish_uuid = uuid.UUID(dish_id)
        now = datetime.utcnow()

        # 1) 检查是否有生效中的时价（海鲜/活鲜）
        market_result = await self.db.execute(
            text("""
                SELECT price_fen, effective_from
                FROM dish_market_prices
                WHERE dish_id = :dish_id
                  AND tenant_id = :tenant_id
                  AND effective_from <= :now
                  AND is_deleted = false
                ORDER BY effective_from DESC
                LIMIT 1
            """),
            {"dish_id": dish_uuid, "tenant_id": self._tenant_uuid, "now": now},
        )
        market_row = market_result.mappings().first()
        if market_row:
            log.info("price_resolved_market", dish_id=dish_id, price_fen=market_row["price_fen"])
            return {
                "dish_id": dish_id,
                "price_fen": int(market_row["price_fen"]),
                "price_type": "market",
                "channel": channel,
            }

        # 2) 检查渠道差异价
        channel_result = await self.db.execute(
            text("""
                SELECT price_fen
                FROM dish_channel_prices
                WHERE dish_id = :dish_id
                  AND tenant_id = :tenant_id
                  AND channel = :channel
                  AND is_deleted = false
                LIMIT 1
            """),
            {"dish_id": dish_uuid, "tenant_id": self._tenant_uuid, "channel": channel},
        )
        channel_row = channel_result.scalar_one_or_none()
        if channel_row is not None:
            log.info("price_resolved_channel", dish_id=dish_id, channel=channel, price_fen=channel_row)
            return {
                "dish_id": dish_id,
                "price_fen": int(channel_row),
                "price_type": "channel",
                "channel": channel,
            }

        # 3) 检查促销价（有效期内）
        promo_result = await self.db.execute(
            text("""
                SELECT promo_price_fen
                FROM dish_promotions
                WHERE dish_id = :dish_id
                  AND tenant_id = :tenant_id
                  AND start_time <= :now
                  AND end_time > :now
                  AND is_deleted = false
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {"dish_id": dish_uuid, "tenant_id": self._tenant_uuid, "now": now},
        )
        promo_row = promo_result.scalar_one_or_none()
        if promo_row is not None:
            log.info("price_resolved_promotion", dish_id=dish_id, price_fen=promo_row)
            return {
                "dish_id": dish_id,
                "price_fen": int(promo_row),
                "price_type": "promotion",
                "channel": channel,
            }

        # 4) 基础售价
        base_result = await self.db.execute(
            text("""
                SELECT price_fen
                FROM dishes
                WHERE id = :dish_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = false
            """),
            {"dish_id": dish_uuid, "tenant_id": self._tenant_uuid},
        )
        base_price = base_result.scalar_one_or_none()
        if base_price is None:
            log.warning("dish_not_found_for_pricing", dish_id=dish_id)
            raise ValueError(f"Dish not found: {dish_id}")

        log.info("price_resolved_base", dish_id=dish_id, price_fen=base_price)
        return {
            "dish_id": dish_id,
            "price_fen": int(base_price),
            "price_type": "base",
            "channel": channel,
        }

    # ─── 2. 设置时价（海鲜/活鲜） ───

    async def set_market_price(
        self,
        dish_id: str,
        price_fen: int,
        effective_from: datetime,
        tenant_id: Optional[str] = None,
        db: Optional[AsyncSession] = None,
    ) -> dict:
        """设置时价菜价格（每日按市场价浮动）

        Args:
            dish_id: 菜品 ID
            price_fen: 时价（分）
            effective_from: 生效时间

        Returns:
            {"id": str, "dish_id": str, "price_fen": int, "effective_from": str}
        """
        if price_fen <= 0:
            raise ValueError("price_fen must be positive")

        await self._set_tenant()
        record_id = uuid.uuid4()

        await self.db.execute(
            text("""
                INSERT INTO dish_market_prices
                    (id, dish_id, tenant_id, price_fen, effective_from, is_deleted)
                VALUES
                    (:id, :dish_id, :tenant_id, :price_fen, :effective_from, false)
            """),
            {
                "id": record_id,
                "dish_id": uuid.UUID(dish_id),
                "tenant_id": self._tenant_uuid,
                "price_fen": price_fen,
                "effective_from": effective_from,
            },
        )
        await self.db.flush()

        log.info(
            "market_price_set",
            dish_id=dish_id,
            price_fen=price_fen,
            effective_from=effective_from.isoformat(),
        )

        return {
            "id": str(record_id),
            "dish_id": dish_id,
            "price_fen": price_fen,
            "effective_from": effective_from.isoformat(),
        }

    # ─── 3. 称重计价 ───

    async def calculate_weighing_price(
        self,
        dish_id: str,
        weight_g: int,
        tenant_id: Optional[str] = None,
        db: Optional[AsyncSession] = None,
    ) -> dict:
        """称重计价：单价(分/500g) x 重量(g)

        Args:
            dish_id: 菜品 ID
            weight_g: 称重重量（克）

        Returns:
            {
                "dish_id": str,
                "weight_g": int,
                "unit_price_fen_per_500g": int,
                "total_price_fen": int,
            }
        """
        if weight_g <= 0:
            raise ValueError("weight_g must be positive")

        await self._set_tenant()

        # 查询称重菜单价（按500g计价）
        result = await self.db.execute(
            text("""
                SELECT price_fen, unit
                FROM dishes
                WHERE id = :dish_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = false
            """),
            {"dish_id": uuid.UUID(dish_id), "tenant_id": self._tenant_uuid},
        )
        row = result.mappings().first()
        if not row:
            raise ValueError(f"Dish not found: {dish_id}")

        unit_price_fen_per_500g = int(row["price_fen"])
        # 计算总价：单价(分/500g) * 重量(g) / 500g，四舍五入到分
        total_price_fen = int(round(unit_price_fen_per_500g * weight_g / 500))

        log.info(
            "weighing_price_calculated",
            dish_id=dish_id,
            weight_g=weight_g,
            unit_price_fen_per_500g=unit_price_fen_per_500g,
            total_price_fen=total_price_fen,
        )

        return {
            "dish_id": dish_id,
            "weight_g": weight_g,
            "unit_price_fen_per_500g": unit_price_fen_per_500g,
            "total_price_fen": total_price_fen,
        }

    # ─── 4. 套餐组合定价 ───

    async def create_combo_price(
        self,
        dishes_with_qty: list[dict],
        discount_rate: float,
        tenant_id: Optional[str] = None,
        db: Optional[AsyncSession] = None,
    ) -> dict:
        """套餐组合定价

        Args:
            dishes_with_qty: [{"dish_id": str, "quantity": int}, ...]
            discount_rate: 折扣率 (0-1)，例如 0.85 = 85折

        Returns:
            {
                "items": [...],
                "original_total_fen": int,
                "discount_rate": float,
                "combo_price_fen": int,
                "saving_fen": int,
            }
        """
        if not (0 < discount_rate <= 1.0):
            raise ValueError("discount_rate must be in (0, 1]")

        await self._set_tenant()

        items = []
        original_total_fen = 0

        for entry in dishes_with_qty:
            dish_id = entry["dish_id"]
            quantity = entry.get("quantity", 1)

            result = await self.db.execute(
                text("""
                    SELECT price_fen, dish_name
                    FROM dishes
                    WHERE id = :dish_id
                      AND tenant_id = :tenant_id
                      AND is_deleted = false
                """),
                {"dish_id": uuid.UUID(dish_id), "tenant_id": self._tenant_uuid},
            )
            row = result.mappings().first()
            if not row:
                raise ValueError(f"Dish not found: {dish_id}")

            unit_price = int(row["price_fen"])
            subtotal = unit_price * quantity
            original_total_fen += subtotal

            items.append(
                {
                    "dish_id": dish_id,
                    "dish_name": row["dish_name"],
                    "quantity": quantity,
                    "unit_price_fen": unit_price,
                    "subtotal_fen": subtotal,
                }
            )

        combo_price_fen = int(round(original_total_fen * discount_rate))
        saving_fen = original_total_fen - combo_price_fen

        log.info(
            "combo_price_created",
            item_count=len(items),
            original_total_fen=original_total_fen,
            combo_price_fen=combo_price_fen,
            discount_rate=discount_rate,
        )

        return {
            "items": items,
            "original_total_fen": original_total_fen,
            "discount_rate": discount_rate,
            "combo_price_fen": combo_price_fen,
            "saving_fen": saving_fen,
        }

    # ─── 5. 多渠道差异价 ───

    async def set_channel_price(
        self,
        dish_id: str,
        channel_prices: dict,
        tenant_id: Optional[str] = None,
        db: Optional[AsyncSession] = None,
    ) -> dict:
        """设置多渠道差异价

        Args:
            dish_id: 菜品 ID
            channel_prices: {"dine_in": 5800, "takeaway": 5500, "delivery": 6200}

        Returns:
            {"dish_id": str, "channels": dict}
        """
        await self._set_tenant()
        dish_uuid = uuid.UUID(dish_id)

        for channel, price_fen in channel_prices.items():
            if price_fen <= 0:
                raise ValueError(f"price_fen must be positive for channel {channel}")

            # UPSERT: 存在则更新，不存在则插入
            await self.db.execute(
                text("""
                    INSERT INTO dish_channel_prices
                        (id, dish_id, tenant_id, channel, price_fen, is_deleted)
                    VALUES
                        (:id, :dish_id, :tenant_id, :channel, :price_fen, false)
                    ON CONFLICT (dish_id, tenant_id, channel)
                    DO UPDATE SET price_fen = :price_fen, is_deleted = false
                """),
                {
                    "id": uuid.uuid4(),
                    "dish_id": dish_uuid,
                    "tenant_id": self._tenant_uuid,
                    "channel": channel,
                    "price_fen": price_fen,
                },
            )

        await self.db.flush()

        log.info(
            "channel_prices_set",
            dish_id=dish_id,
            channels=list(channel_prices.keys()),
        )

        return {"dish_id": dish_id, "channels": channel_prices}

    # ─── 6. 促销价 ───

    async def set_promotion_price(
        self,
        dish_id: str,
        promo_price_fen: int,
        start: datetime,
        end: datetime,
        tenant_id: Optional[str] = None,
        db: Optional[AsyncSession] = None,
    ) -> dict:
        """设置促销价（限时）

        Args:
            dish_id: 菜品 ID
            promo_price_fen: 促销价（分）
            start: 促销开始时间
            end: 促销结束时间

        Returns:
            {"id": str, "dish_id": str, "promo_price_fen": int, ...}
        """
        if promo_price_fen <= 0:
            raise ValueError("promo_price_fen must be positive")
        if end <= start:
            raise ValueError("end must be after start")

        await self._set_tenant()
        record_id = uuid.uuid4()

        await self.db.execute(
            text("""
                INSERT INTO dish_promotions
                    (id, dish_id, tenant_id, promo_price_fen, start_time, end_time, is_deleted)
                VALUES
                    (:id, :dish_id, :tenant_id, :promo_price_fen, :start_time, :end_time, false)
            """),
            {
                "id": record_id,
                "dish_id": uuid.UUID(dish_id),
                "tenant_id": self._tenant_uuid,
                "promo_price_fen": promo_price_fen,
                "start_time": start,
                "end_time": end,
            },
        )
        await self.db.flush()

        log.info(
            "promotion_price_set",
            dish_id=dish_id,
            promo_price_fen=promo_price_fen,
            start=start.isoformat(),
            end=end.isoformat(),
        )

        return {
            "id": str(record_id),
            "dish_id": dish_id,
            "promo_price_fen": promo_price_fen,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        }

    # ─── 7. 毛利底线校验 ───

    async def validate_margin(
        self,
        dish_id: str,
        proposed_price_fen: int,
        tenant_id: Optional[str] = None,
        db: Optional[AsyncSession] = None,
        store_id: Optional[str] = None,
    ) -> dict:
        """毛利底线校验 — 联动 BOM 成本

        通过 tx-supply 的 CostCalculator 获取菜品理论成本，
        校验提议售价是否满足毛利底线要求。

        Args:
            dish_id: 菜品 ID
            proposed_price_fen: 提议售价（分）
            store_id: 门店 ID（用于获取门店级毛利配置）

        Returns:
            {
                "dish_id": str,
                "proposed_price_fen": int,
                "theoretical_cost_fen": int,
                "margin_rate": float,
                "min_margin_rate": float,
                "passed": bool,
                "min_price_fen": int,  # 满足毛利底线的最低售价
            }
        """
        if proposed_price_fen <= 0:
            return {
                "dish_id": dish_id,
                "proposed_price_fen": proposed_price_fen,
                "theoretical_cost_fen": 0,
                "margin_rate": 0.0,
                "min_margin_rate": DEFAULT_MIN_MARGIN_RATE,
                "passed": False,
                "min_price_fen": 0,
            }

        await self._set_tenant()

        # 获取 BOM 理论成本
        cost_fen = await self._get_dish_cost(dish_id)
        min_margin_rate = await self._get_store_margin_rate(store_id)

        # 毛利率 = (售价 - 成本) / 售价
        if proposed_price_fen > 0:
            margin_rate = (proposed_price_fen - cost_fen) / proposed_price_fen
        else:
            margin_rate = 0.0

        passed = margin_rate >= min_margin_rate

        # 满足毛利底线的最低售价 = 成本 / (1 - 最低毛利率)
        if min_margin_rate < 1.0:
            min_price_fen = int(round(cost_fen / (1 - min_margin_rate)))
        else:
            min_price_fen = 0

        log.info(
            "margin_validated",
            dish_id=dish_id,
            proposed_price_fen=proposed_price_fen,
            cost_fen=cost_fen,
            margin_rate=round(margin_rate, 4),
            min_margin_rate=min_margin_rate,
            passed=passed,
        )

        return {
            "dish_id": dish_id,
            "proposed_price_fen": proposed_price_fen,
            "theoretical_cost_fen": cost_fen,
            "margin_rate": round(margin_rate, 4),
            "min_margin_rate": min_margin_rate,
            "passed": passed,
            "min_price_fen": min_price_fen,
        }

    async def _get_dish_cost(self, dish_id: str) -> int:
        """获取菜品 BOM 理论成本（分）

        查询激活的 BOM 模板，计算理论成本。
        与 tx-supply CostCalculator 逻辑一致。
        """
        dish_uuid = uuid.UUID(dish_id)

        # 查找激活的 BOM 模板
        bom_result = await self.db.execute(
            text("""
                SELECT id, yield_rate
                FROM bom_templates
                WHERE dish_id = :dish_id
                  AND tenant_id = :tenant_id
                  AND is_active = true
                  AND is_deleted = false
                ORDER BY effective_date DESC
                LIMIT 1
            """),
            {"dish_id": dish_uuid, "tenant_id": self._tenant_uuid},
        )
        bom_row = bom_result.mappings().first()

        if not bom_row:
            # 无 BOM 时回退到 dishes.cost_fen
            fallback = await self.db.execute(
                text("""
                    SELECT cost_fen
                    FROM dishes
                    WHERE id = :dish_id
                      AND tenant_id = :tenant_id
                      AND is_deleted = false
                """),
                {"dish_id": dish_uuid, "tenant_id": self._tenant_uuid},
            )
            cost = fallback.scalar_one_or_none()
            return int(cost) if cost else 0

        bom_id = bom_row["id"]
        yield_rate = float(bom_row["yield_rate"]) if bom_row["yield_rate"] else 1.0

        # 计算 BOM 成本
        items_result = await self.db.execute(
            text("""
                SELECT bi.standard_qty,
                       bi.unit_cost_fen AS bom_unit_cost_fen,
                       bi.waste_factor,
                       i.unit_price_fen AS ingredient_unit_price_fen
                FROM bom_items bi
                LEFT JOIN ingredients i
                  ON i.id = bi.ingredient_id
                  AND i.tenant_id = bi.tenant_id
                  AND i.is_deleted = false
                WHERE bi.bom_id = :bom_id
                  AND bi.tenant_id = :tenant_id
                  AND bi.is_deleted = false
            """),
            {"bom_id": bom_id, "tenant_id": self._tenant_uuid},
        )

        raw_total_fen = 0
        for row in items_result.mappings().all():
            standard_qty = float(row["standard_qty"])
            waste_factor = float(row["waste_factor"]) if row["waste_factor"] else 0.0
            unit_cost = row["bom_unit_cost_fen"] or row["ingredient_unit_price_fen"]

            if unit_cost is not None:
                effective_qty = standard_qty * (1 + waste_factor)
                raw_total_fen += int(round(effective_qty * unit_cost))

        if yield_rate > 0:
            return int(round(raw_total_fen / yield_rate))
        return raw_total_fen

    # ─── 8. 调价审批 ───

    async def approve_price_change(
        self,
        change_id: str,
        approver_id: str,
        tenant_id: Optional[str] = None,
        db: Optional[AsyncSession] = None,
    ) -> dict:
        """审批调价申请

        Args:
            change_id: 调价申请 ID
            approver_id: 审批人 ID

        Returns:
            {"change_id": str, "status": str, "approver_id": str, "approved_at": str}
        """
        await self._set_tenant()
        change_uuid = uuid.UUID(change_id)
        now = datetime.utcnow()

        # 查询调价申请
        result = await self.db.execute(
            text("""
                SELECT id, dish_id, old_price_fen, new_price_fen, status
                FROM price_change_requests
                WHERE id = :change_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = false
            """),
            {"change_id": change_uuid, "tenant_id": self._tenant_uuid},
        )
        row = result.mappings().first()
        if not row:
            raise ValueError(f"Price change request not found: {change_id}")

        if row["status"] != "pending":
            raise ValueError(f"Price change request is not pending: status={row['status']}")

        # 审批前做毛利校验
        margin_result = await self.validate_margin(
            dish_id=str(row["dish_id"]),
            proposed_price_fen=int(row["new_price_fen"]),
        )
        if not margin_result["passed"]:
            # 审批拒绝 — 毛利不达标
            await self.db.execute(
                text("""
                    UPDATE price_change_requests
                    SET status = 'rejected',
                        approver_id = :approver_id,
                        approved_at = :now,
                        reject_reason = '毛利底线不达标'
                    WHERE id = :change_id AND tenant_id = :tenant_id
                """),
                {
                    "change_id": change_uuid,
                    "tenant_id": self._tenant_uuid,
                    "approver_id": uuid.UUID(approver_id),
                    "now": now,
                },
            )
            await self.db.flush()

            log.warning(
                "price_change_rejected_margin",
                change_id=change_id,
                margin_rate=margin_result["margin_rate"],
            )

            return {
                "change_id": change_id,
                "status": "rejected",
                "approver_id": approver_id,
                "approved_at": now.isoformat(),
                "reject_reason": "毛利底线不达标",
                "margin_detail": margin_result,
            }

        # 审批通过 — 更新菜品价格
        await self.db.execute(
            text("""
                UPDATE price_change_requests
                SET status = 'approved',
                    approver_id = :approver_id,
                    approved_at = :now
                WHERE id = :change_id AND tenant_id = :tenant_id
            """),
            {
                "change_id": change_uuid,
                "tenant_id": self._tenant_uuid,
                "approver_id": uuid.UUID(approver_id),
                "now": now,
            },
        )

        # 生效新价格
        await self.db.execute(
            text("""
                UPDATE dishes
                SET price_fen = :new_price_fen
                WHERE id = :dish_id AND tenant_id = :tenant_id
            """),
            {
                "new_price_fen": int(row["new_price_fen"]),
                "dish_id": row["dish_id"],
                "tenant_id": self._tenant_uuid,
            },
        )
        await self.db.flush()

        log.info(
            "price_change_approved",
            change_id=change_id,
            approver_id=approver_id,
            dish_id=str(row["dish_id"]),
            new_price_fen=int(row["new_price_fen"]),
        )

        asyncio.create_task(
            UniversalPublisher.publish(
                event_type=MenuEventType.DISH_PRICE_CHANGED,
                tenant_id=self._tenant_uuid,
                store_id=None,
                entity_id=row["dish_id"],
                event_data={
                    "dish_id": str(row["dish_id"]),
                    "old_price_fen": int(row["old_price_fen"]) if row["old_price_fen"] is not None else None,
                    "new_price_fen": int(row["new_price_fen"]),
                },
                source_service="tx-menu",
            )
        )

        return {
            "change_id": change_id,
            "status": "approved",
            "approver_id": approver_id,
            "approved_at": now.isoformat(),
        }
