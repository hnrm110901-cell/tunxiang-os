"""品牌→门店菜品三级发布体系 Service 层

业务逻辑：
  - 发布方案 CRUD + 执行（品牌→门店 store_dish_overrides）
  - 门店菜品微调（上下架/改价/改名/改图）
  - 生效价格计算（五级优先级）
  - 调价规则管理

核心规则：
  1. 执行发布时，若门店已存在手动微调（is_available / local_price 等），
     不覆盖，只创建缺失记录。
  2. 生效价格优先级：门店时段/渠道规则 > 门店覆盖价 > 发布方案价 > 品牌标准价
"""
import uuid as _uuid
from datetime import datetime
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .brand_publish_repository import BrandPublishRepository

log = structlog.get_logger(__name__)

_VALID_TARGET_TYPES = {"all_stores", "region", "stores"}
_VALID_RULE_TYPES = {"time_period", "channel", "date_range", "holiday"}
_VALID_ADJ_TYPES = {"percentage", "fixed_add", "fixed_price"}
_VALID_CHANNELS = {"dine_in", "delivery", "takeout", "self_order"}


class BrandPublishService:
    """品牌发布体系 Service"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self._repo = BrandPublishRepository(db, tenant_id)

    # ══════════════════════════════════════════════════════
    # A. 发布方案
    # ══════════════════════════════════════════════════════

    async def create_publish_plan(
        self,
        plan_name: str,
        target_type: str,
        target_ids: Optional[list[str]] = None,
        brand_id: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> dict:
        if not plan_name or not plan_name.strip():
            raise ValueError("plan_name 不能为空")
        if target_type not in _VALID_TARGET_TYPES:
            raise ValueError(
                f"target_type 必须为 {_VALID_TARGET_TYPES} 之一，收到: {target_type!r}"
            )
        if target_type in ("region", "stores") and not target_ids:
            raise ValueError(f"target_type={target_type!r} 时 target_ids 不能为空")

        plan = await self._repo.create_publish_plan(
            plan_name=plan_name.strip(),
            target_type=target_type,
            target_ids=target_ids,
            brand_id=brand_id,
            created_by=created_by,
        )
        await self.db.commit()
        log.info("publish_plan.created", plan_id=plan["id"], plan_name=plan_name)
        return plan

    async def get_publish_plan(self, plan_id: str) -> dict:
        plan = await self._repo.get_publish_plan(plan_id)
        if not plan:
            raise ValueError(f"发布方案不存在: {plan_id}")
        items = await self._repo.get_plan_items(plan_id)
        plan["items"] = items
        return plan

    async def list_publish_plans(
        self,
        page: int = 1,
        size: int = 20,
        brand_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> dict:
        return await self._repo.list_publish_plans(
            page=page, size=size, brand_id=brand_id, status=status
        )

    async def add_items_to_plan(
        self, plan_id: str, items: list[dict]
    ) -> list[dict]:
        """向发布方案添加菜品（含可选覆盖价）。草稿状态才可修改。"""
        plan = await self._repo.get_publish_plan(plan_id)
        if not plan:
            raise ValueError(f"发布方案不存在: {plan_id}")
        if plan["status"] != "draft":
            raise ValueError(f"方案状态为 {plan['status']!r}，只有草稿状态可以修改菜品")
        if not items:
            raise ValueError("items 不能为空")

        for i, item in enumerate(items):
            if "dish_id" not in item:
                raise ValueError(f"items[{i}] 缺少 dish_id")
            if "override_price_fen" in item and item["override_price_fen"] is not None:
                if not isinstance(item["override_price_fen"], int) or item["override_price_fen"] < 0:
                    raise ValueError(f"items[{i}].override_price_fen 必须为非负整数（分）")

        result = await self._repo.add_plan_items(plan_id, items)
        await self.db.commit()
        log.info("publish_plan.items_added", plan_id=plan_id, count=len(result))
        return result

    async def execute_publish_plan(self, plan_id: str) -> dict:
        """执行发布方案：将菜品推送到目标门店的 store_dish_overrides。

        核心逻辑：
        - 解析目标门店列表
        - 获取方案内所有菜品
        - 为每个(门店, 菜品)创建 store_dish_overrides 记录
        - 已存在的记录：仅在 is_available 字段有值时不覆盖（保留门店主动下架决策）
        """
        plan = await self._repo.get_publish_plan(plan_id)
        if not plan:
            raise ValueError(f"发布方案不存在: {plan_id}")
        if plan["status"] == "archived":
            raise ValueError("已归档的方案无法执行")

        # 获取目标门店
        store_ids = await self._repo.get_target_store_ids(plan_id)
        if not store_ids:
            raise ValueError("发布方案没有找到有效的目标门店")

        # 获取方案菜品
        items = await self._repo.get_plan_items(plan_id)
        if not items:
            raise ValueError("发布方案中没有菜品，请先添加菜品")

        success_stores: list[str] = []
        failed_stores: list[dict] = []
        total_dishes_published = 0

        for store_id in store_ids:
            store_dish_count = 0
            try:
                for item in items:
                    dish_id = item["dish_id"]
                    # 检查门店是否已有该菜品的微调记录
                    existing = await self._repo.get_store_dish_override(
                        store_id=store_id, dish_id=dish_id
                    )
                    if existing:
                        # 已有记录：不覆盖门店的 is_available 决策
                        # 只在没有 local_price 时同步方案中的 override_price
                        if (existing["local_price_fen"] is None
                                and item.get("override_price_fen") is not None):
                            await self._repo.upsert_store_dish_override(
                                store_id=store_id,
                                dish_id=dish_id,
                                data={"local_price_fen": item["override_price_fen"]},
                            )
                        # 不动 is_available（门店自主决策）
                    else:
                        # 新建记录
                        init_data: dict = {
                            "is_available": True,
                            "sort_order": 0,
                        }
                        if item.get("override_price_fen") is not None:
                            init_data["local_price_fen"] = item["override_price_fen"]
                        await self._repo.upsert_store_dish_override(
                            store_id=store_id,
                            dish_id=dish_id,
                            data=init_data,
                        )
                    store_dish_count += 1
                success_stores.append(store_id)
                total_dishes_published += store_dish_count
            except (ValueError, KeyError) as exc:
                log.warning(
                    "publish_plan.store_failed",
                    plan_id=plan_id,
                    store_id=store_id,
                    error=str(exc),
                )
                failed_stores.append({"store_id": store_id, "error": str(exc)})

        # 更新方案状态
        updated_plan = await self._repo.update_plan_status(
            plan_id=plan_id,
            status="published",
            published_at=datetime.utcnow(),
        )
        await self.db.commit()

        log.info(
            "publish_plan.executed",
            plan_id=plan_id,
            success_stores=len(success_stores),
            failed_stores=len(failed_stores),
            total_dishes=total_dishes_published,
        )
        return {
            "plan_id": plan_id,
            "plan_name": plan["plan_name"],
            "status": "published",
            "total_stores": len(store_ids),
            "success_stores": len(success_stores),
            "failed_stores": len(failed_stores),
            "failed_details": failed_stores,
            "total_dish_records": total_dishes_published,
            "executed_at": datetime.utcnow().isoformat(),
        }

    # ══════════════════════════════════════════════════════
    # B. 门店菜品微调
    # ══════════════════════════════════════════════════════

    async def get_store_dishes(self, store_id: str) -> list[dict]:
        """获取门店生效菜单（品牌菜品 + 门店微调合并）。"""
        return await self._repo.list_store_overrides(store_id)

    async def override_store_dish(
        self,
        store_id: str,
        dish_id: str,
        data: dict,
        updated_by: Optional[str] = None,
    ) -> dict:
        """门店对品牌菜品进行微调（改价/改名/上下架等）。"""
        allowed_keys = {
            "local_price_fen", "local_name", "local_description",
            "local_image_url", "is_available", "sort_order",
        }
        update_data = {k: v for k, v in data.items() if k in allowed_keys}
        if not update_data:
            raise ValueError(f"没有有效的更新字段，支持字段：{allowed_keys}")

        if "local_price_fen" in update_data:
            price = update_data["local_price_fen"]
            if price is not None and (not isinstance(price, int) or price < 0):
                raise ValueError("local_price_fen 必须为非负整数（分）")

        result = await self._repo.upsert_store_dish_override(
            store_id=store_id,
            dish_id=dish_id,
            data=update_data,
            updated_by=updated_by,
        )
        await self.db.commit()
        log.info(
            "store_dish.overridden",
            store_id=store_id,
            dish_id=dish_id,
            fields=list(update_data.keys()),
        )
        return result

    async def batch_toggle_dishes(
        self,
        store_id: str,
        dish_ids: list[str],
        is_available: bool,
        updated_by: Optional[str] = None,
    ) -> dict:
        """批量上下架门店菜品。"""
        if not dish_ids:
            raise ValueError("dish_ids 不能为空")
        count = await self._repo.batch_toggle_availability(
            store_id=store_id,
            dish_ids=dish_ids,
            is_available=is_available,
            updated_by=updated_by,
        )
        await self.db.commit()
        log.info(
            "store_dish.batch_toggled",
            store_id=store_id,
            count=count,
            is_available=is_available,
        )
        return {
            "store_id": store_id,
            "updated_count": count,
            "is_available": is_available,
        }

    # ══════════════════════════════════════════════════════
    # C. 价格调整规则
    # ══════════════════════════════════════════════════════

    async def create_price_rule(self, data: dict) -> dict:
        rule_type = data.get("rule_type", "")
        if rule_type not in _VALID_RULE_TYPES:
            raise ValueError(
                f"rule_type 必须为 {_VALID_RULE_TYPES} 之一，收到: {rule_type!r}"
            )
        adj_type = data.get("adjustment_type", "")
        if adj_type not in _VALID_ADJ_TYPES:
            raise ValueError(
                f"adjustment_type 必须为 {_VALID_ADJ_TYPES} 之一，收到: {adj_type!r}"
            )
        if not data.get("rule_name", "").strip():
            raise ValueError("rule_name 不能为空")
        channel = data.get("channel")
        if channel and channel not in _VALID_CHANNELS:
            raise ValueError(
                f"channel 必须为 {_VALID_CHANNELS} 之一，收到: {channel!r}"
            )

        rule = await self._repo.create_price_rule(data)
        await self.db.commit()
        log.info("price_rule.created", rule_id=rule["id"], rule_type=rule_type)
        return rule

    async def list_price_rules(
        self,
        store_id: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> list[dict]:
        return await self._repo.list_price_rules(store_id=store_id, is_active=is_active)

    async def update_price_rule(self, rule_id: str, data: dict) -> dict:
        existing = await self._repo.get_price_rule(rule_id)
        if not existing:
            raise ValueError(f"调价规则不存在: {rule_id}")
        result = await self._repo.update_price_rule(rule_id, data)
        await self.db.commit()
        return result

    async def bind_dishes_to_rule(
        self, rule_id: str, dish_ids: list[str]
    ) -> list[dict]:
        if not dish_ids:
            raise ValueError("dish_ids 不能为空")
        existing = await self._repo.get_price_rule(rule_id)
        if not existing:
            raise ValueError(f"调价规则不存在: {rule_id}")
        result = await self._repo.bind_dishes_to_rule(rule_id, dish_ids)
        await self.db.commit()
        log.info("price_rule.dishes_bound", rule_id=rule_id, count=len(result))
        return result

    # ══════════════════════════════════════════════════════
    # D. 生效价格计算（核心逻辑）
    # ══════════════════════════════════════════════════════

    async def get_effective_price(
        self,
        dish_id: str,
        store_id: str,
        channel: str,
        at_datetime: Optional[datetime] = None,
    ) -> dict:
        """计算某菜品在指定门店/渠道/时间点的生效价格。

        价格优先级（从高到低）：
          1. 门店时段/渠道/日期调价规则（取最高优先级命中规则）
          2. 门店覆盖价（store_dish_overrides.local_price_fen）
          3. 发布方案覆盖价（最新已发布方案中的 override_price_fen）
          4. 品牌标准价（dishes.price_fen）
        """
        if at_datetime is None:
            at_datetime = datetime.utcnow()

        if channel not in _VALID_CHANNELS:
            raise ValueError(
                f"channel 必须为 {_VALID_CHANNELS} 之一，收到: {channel!r}"
            )

        # 1. 获取品牌标准价
        await self._repo._set_tenant()
        dish_result = await self.db.execute(
            text("""
                SELECT price_fen, dish_name
                FROM dishes
                WHERE id = :dish_id
                  AND tenant_id = :tid
                  AND is_deleted = false
            """),
            {"dish_id": _uuid.UUID(dish_id), "tid": self._repo._tid},
        )
        dish_row = dish_result.fetchone()
        if not dish_row:
            raise ValueError(f"菜品不存在: {dish_id}")

        brand_price: int = int(dish_row[0])
        dish_name: str = dish_row[1]
        base_price: int = brand_price
        price_source = "brand_standard"

        # 2. 发布方案覆盖价
        plan_override = await self._repo.get_plan_override_for_dish(
            dish_id=dish_id, store_id=store_id
        )
        if plan_override and plan_override.get("override_price_fen") is not None:
            base_price = int(plan_override["override_price_fen"])
            price_source = "publish_plan"

        # 3. 门店微调覆盖价
        store_override = await self._repo.get_store_dish_override(
            store_id=store_id, dish_id=dish_id
        )
        if store_override and store_override.get("local_price_fen") is not None:
            base_price = int(store_override["local_price_fen"])
            price_source = "store_override"

        # 4. 应用调价规则（最高优先级的命中规则）
        rules = await self._repo.get_active_rules_for_dish(
            dish_id=dish_id,
            store_id=store_id,
            channel=channel,
            at_datetime=at_datetime,
        )

        applied_rule = None
        final_price = base_price
        if rules:
            rule = rules[0]  # 已按优先级降序，取第一个
            final_price = self._apply_rule(base_price, rule)
            applied_rule = rule
            price_source = "adjustment_rule"

        return {
            "dish_id": dish_id,
            "dish_name": dish_name,
            "store_id": store_id,
            "channel": channel,
            "at_datetime": at_datetime.isoformat(),
            "brand_price_fen": brand_price,
            "effective_price_fen": final_price,
            "price_source": price_source,
            "applied_rule": applied_rule,
            "store_override": store_override,
        }

    @staticmethod
    def _apply_rule(base_price: int, rule: dict) -> int:
        """根据调价规则计算最终价格。"""
        adj_type: str = rule["adjustment_type"]
        adj_value: float = float(rule["adjustment_value"])

        if adj_type == "percentage":
            # adj_value 为百分比，如 10 = 加价 10%，-5 = 降价 5%
            new_price = int(round(base_price * (1 + adj_value / 100)))
        elif adj_type == "fixed_add":
            # adj_value 为分，可正可负
            new_price = base_price + int(adj_value)
        else:  # "fixed_price"
            # 直接固定价格（分）
            new_price = int(adj_value)

        return max(1, new_price)  # 至少 1 分，防止零/负价格
