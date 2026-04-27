"""AI动态定价引擎 — 时段x客群x库存x天气 → 智能价格

五维度定价策略:
1. 时段定价: 午市折扣/晚市溢价/闲时特惠
2. 需求定价: 上座率>80%不降价，<40%触发折扣
3. 库存定价: 临期食材菜品降价清货
4. 天气定价: 雨天→外卖加权/堂食减价
5. 会员定价: VIP专属价/新客引流价

硬约束: 调整后价格不得低于BOM成本x1.3(毛利底线30%)

本服务是 pricing_engine.py 的增强层，不替代标准定价逻辑。
标准售价(时价/渠道价/促销价)仍走 PricingEngine，
本引擎在标准售价之上叠加AI维度的动态调整。
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


class DynamicPricingAIService:
    """AI动态定价引擎"""

    # 时段默认调整(无规则时的fallback)
    DEFAULT_DAYPART_ADJUSTMENTS: dict[str, dict[str, Any]] = {
        "lunch": {"adjustment_pct": -5, "reason": "午市引流"},
        "afternoon": {"adjustment_pct": -15, "reason": "下午茶特惠"},
        "dinner": {"adjustment_pct": 0, "reason": "晚市标准价"},
        "late": {"adjustment_pct": -10, "reason": "夜宵折扣"},
    }

    MIN_MARGIN_RATE: float = 0.30  # 毛利底线30%

    # ─── 内部工具 ───────────────────────────────────────────────────

    @staticmethod
    async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
        """设置 RLS tenant context"""
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )

    @staticmethod
    def _current_daypart() -> str:
        """根据当前时间判定时段"""
        hour = datetime.now(timezone.utc).hour + 8  # 简单UTC+8
        if hour >= 24:
            hour -= 24
        if 11 <= hour < 14:
            return "lunch"
        if 14 <= hour < 17:
            return "afternoon"
        if 17 <= hour < 21:
            return "dinner"
        return "late"

    # ─── 1. 单品动态价格计算 ─────────────────────────────────────────

    async def calculate_dynamic_price(
        self,
        db: AsyncSession,
        store_id: str,
        tenant_id: str,
        dish_id: str,
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """计算单品动态价格

        流程:
        1. 查询dish基础售价+BOM成本
        2. 查询匹配的pricing_rules(按priority DESC排序)
        3. 逐条规则评估condition是否满足
        4. 叠加所有满足条件的调整(percent优先于fixed)
        5. 校验毛利底线(adjusted_price >= cost * 1.3)
        6. 写入pricing_logs

        Returns:
            {
                "original_price_fen": int,
                "original_price_yuan": float,
                "adjusted_price_fen": int,
                "adjusted_price_yuan": float,
                "adjustments": [{"rule_id": str, "rule_type": str, "reason": str, "delta_fen": int}],
                "margin_rate": float,
                "margin_floor_applied": bool,
            }
        """
        await self._set_tenant(db, tenant_id)
        ctx = context or {}
        daypart = ctx.get("daypart") or self._current_daypart()
        ctx["daypart"] = daypart

        store_uuid = uuid.UUID(store_id)
        tenant_uuid = uuid.UUID(tenant_id)
        dish_uuid = uuid.UUID(dish_id)
        today = date.today()

        # 1) 查询基础售价 + BOM 成本
        dish_row = await self._get_dish_price_and_cost(db, dish_uuid, tenant_uuid)
        if dish_row is None:
            raise ValueError(f"Dish not found: {dish_id}")

        base_price_fen: int = int(dish_row["price_fen"])
        cost_fen: int = int(dish_row["cost_fen"]) if dish_row["cost_fen"] else 0

        # 2) 查询匹配规则
        rules = await self._get_active_rules(
            db, store_uuid, tenant_uuid, dish_uuid, daypart, today
        )

        # 3+4) 评估并叠加调整
        adjustments: list[dict[str, Any]] = []
        percent_deltas: list[float] = []
        fixed_deltas: list[int] = []

        for rule in rules:
            condition = rule["condition"] or {}
            satisfied = await self.evaluate_condition(
                db, store_id, tenant_id, condition, ctx
            )
            if not satisfied:
                continue

            adj_type: str = rule["adjustment_type"]
            adj_value: int = int(rule["adjustment_value"])
            rule_type: str = rule["rule_type"]

            if adj_type == "percent":
                delta_fen = int(round(base_price_fen * adj_value / 100))
                percent_deltas.append(adj_value)
            else:  # fixed
                delta_fen = adj_value
                fixed_deltas.append(adj_value)

            reason = self._build_reason(rule_type, adj_type, adj_value)
            adjustments.append(
                {
                    "rule_id": str(rule["id"]),
                    "rule_type": rule_type,
                    "reason": reason,
                    "delta_fen": delta_fen,
                }
            )

        # 计算调整后价格: percent先叠加，fixed后叠加
        adjusted = base_price_fen
        for pct in percent_deltas:
            adjusted += int(round(base_price_fen * pct / 100))
        for fix in fixed_deltas:
            adjusted += fix

        # 5) 毛利底线校验
        margin_floor_applied = False
        if cost_fen > 0:
            min_price = int(round(cost_fen / (1 - self.MIN_MARGIN_RATE)))
            # 地板价/天花板价约束(来自规则)
            rule_min = self._extract_price_bound(rules, "min_price_fen")
            rule_max = self._extract_price_bound(rules, "max_price_fen")
            if rule_min is not None:
                min_price = max(min_price, rule_min)

            if adjusted < min_price:
                log.warning(
                    "dynamic_pricing_margin_floor",
                    dish_id=dish_id,
                    attempted_fen=adjusted,
                    floor_fen=min_price,
                    cost_fen=cost_fen,
                )
                adjusted = min_price
                margin_floor_applied = True

            if rule_max is not None and adjusted > rule_max:
                adjusted = rule_max

        # 确保至少1分
        adjusted = max(adjusted, 1)

        # 毛利率
        margin_rate = (adjusted - cost_fen) / adjusted if adjusted > 0 else 0.0

        # 6) 写入pricing_logs
        await self._write_pricing_log(
            db,
            tenant_uuid=tenant_uuid,
            store_uuid=store_uuid,
            dish_uuid=dish_uuid,
            pricing_date=today,
            original_price_fen=base_price_fen,
            adjusted_price_fen=adjusted,
            adjustment_reason="; ".join(a["reason"] for a in adjustments) if adjustments else "无调整",
            rules_applied=adjustments,
            context=ctx,
        )

        log.info(
            "dynamic_price_calculated",
            dish_id=dish_id,
            store_id=store_id,
            original_fen=base_price_fen,
            adjusted_fen=adjusted,
            rules_matched=len(adjustments),
            margin_rate=round(margin_rate, 4),
        )

        return {
            "dish_id": dish_id,
            "original_price_fen": base_price_fen,
            "original_price_yuan": round(base_price_fen / 100, 2),
            "adjusted_price_fen": adjusted,
            "adjusted_price_yuan": round(adjusted / 100, 2),
            "adjustments": adjustments,
            "margin_rate": round(margin_rate, 4),
            "margin_floor_applied": margin_floor_applied,
            "daypart": daypart,
        }

    # ─── 2. 批量计算门店价格 ─────────────────────────────────────────

    async def calculate_store_prices(
        self,
        db: AsyncSession,
        store_id: str,
        tenant_id: str,
        target_date: Optional[date] = None,
    ) -> list[dict[str, Any]]:
        """批量计算门店所有菜品的动态价格

        用于每日开市前批量刷新价格。
        """
        await self._set_tenant(db, tenant_id)
        tenant_uuid = uuid.UUID(tenant_id)

        # 获取门店所有在售菜品
        result = await db.execute(
            text("""
                SELECT id FROM dishes
                WHERE tenant_id = :tid
                  AND is_deleted = false
                  AND is_available = true
                ORDER BY dish_name
            """),
            {"tid": tenant_uuid},
        )
        dish_ids = [str(row[0]) for row in result.fetchall()]

        if not dish_ids:
            return []

        ctx: dict[str, Any] = {}
        if target_date:
            ctx["target_date"] = target_date.isoformat()

        results: list[dict[str, Any]] = []
        for did in dish_ids:
            try:
                price_result = await self.calculate_dynamic_price(
                    db, store_id, tenant_id, did, context=ctx
                )
                results.append(price_result)
            except (ValueError, SQLAlchemyError) as exc:
                log.error("batch_price_error", dish_id=did, error=str(exc))
                results.append(
                    {
                        "dish_id": did,
                        "error": str(exc),
                        "original_price_fen": 0,
                        "adjusted_price_fen": 0,
                    }
                )

        log.info(
            "store_prices_calculated",
            store_id=store_id,
            total=len(results),
            adjusted_count=sum(1 for r in results if r.get("adjustments")),
        )
        return results

    # ─── 3. 条件评估引擎 ────────────────────────────────────────────

    async def evaluate_condition(
        self,
        db: AsyncSession,
        store_id: str,
        tenant_id: str,
        condition: dict[str, Any],
        context: dict[str, Any],
    ) -> bool:
        """评估规则条件是否满足

        支持的条件key:
        - occupancy_rate_gt/lt: 上座率阈值
        - weather_in: 天气条件列表
        - inventory_days_lt: 食材剩余天数
        - member_tier_in: 会员等级列表
        - daypart_in: 时段列表
        - is_holiday: 是否节假日
        """
        if not condition:
            return True  # 无条件 = 始终匹配

        for key, threshold in condition.items():
            if key == "occupancy_rate_gt":
                occ = context.get("occupancy_rate")
                if occ is None:
                    occ = await self.get_current_occupancy(db, store_id, tenant_id)
                    context["occupancy_rate"] = occ
                if occ <= float(threshold):
                    return False

            elif key == "occupancy_rate_lt":
                occ = context.get("occupancy_rate")
                if occ is None:
                    occ = await self.get_current_occupancy(db, store_id, tenant_id)
                    context["occupancy_rate"] = occ
                if occ >= float(threshold):
                    return False

            elif key == "weather_in":
                weather = context.get("weather")
                if weather is None:
                    weather = await self._get_current_weather(db, store_id, tenant_id)
                    context["weather"] = weather
                if weather not in threshold:
                    return False

            elif key == "inventory_days_lt":
                inv_days = context.get("inventory_days")
                if inv_days is None:
                    continue  # 无库存数据时跳过此条件
                if int(inv_days) >= int(threshold):
                    return False

            elif key == "member_tier_in":
                member_tier = context.get("member_tier")
                if member_tier is None:
                    continue  # 无会员信息时跳过
                if member_tier not in threshold:
                    return False

            elif key == "daypart_in":
                daypart = context.get("daypart", self._current_daypart())
                if daypart not in threshold:
                    return False

            elif key == "is_holiday":
                is_holiday = context.get("is_holiday", False)
                if bool(threshold) != bool(is_holiday):
                    return False

        return True

    # ─── 4. 实时上座率 ──────────────────────────────────────────────

    async def get_current_occupancy(
        self,
        db: AsyncSession,
        store_id: str,
        tenant_id: str,
    ) -> float:
        """实时上座率 = 当前occupied桌数/总桌数"""
        await self._set_tenant(db, tenant_id)
        store_uuid = uuid.UUID(store_id)
        tenant_uuid = uuid.UUID(tenant_id)

        result = await db.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'occupied') AS occupied,
                    COUNT(*) AS total
                FROM tables
                WHERE store_id = :sid
                  AND tenant_id = :tid
                  AND is_deleted = false
            """),
            {"sid": store_uuid, "tid": tenant_uuid},
        )
        row = result.mappings().first()
        if not row or int(row["total"]) == 0:
            return 0.0

        return round(int(row["occupied"]) / int(row["total"]), 4)

    # ─── 5. 规则CRUD ────────────────────────────────────────────────

    async def manage_rules(
        self,
        db: AsyncSession,
        store_id: str,
        tenant_id: str,
        rules: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """规则批量创建/更新

        每条rule包含: dish_id, rule_type, daypart, condition, adjustment_type,
        adjustment_value, min_price_fen, max_price_fen, priority, is_active,
        effective_from, effective_until
        """
        await self._set_tenant(db, tenant_id)
        store_uuid = uuid.UUID(store_id)
        tenant_uuid = uuid.UUID(tenant_id)

        created = 0
        updated = 0
        errors: list[dict[str, str]] = []

        for rule in rules:
            try:
                dish_uuid = uuid.UUID(rule["dish_id"])
                rule_type = rule["rule_type"]
                daypart = rule.get("daypart")

                result = await db.execute(
                    text("""
                        INSERT INTO dynamic_pricing_rules (
                            tenant_id, store_id, dish_id,
                            rule_type, daypart, condition,
                            adjustment_type, adjustment_value,
                            min_price_fen, max_price_fen,
                            priority, is_active,
                            effective_from, effective_until
                        ) VALUES (
                            :tid, :sid, :did,
                            :rule_type, :daypart, :condition::JSONB,
                            :adj_type, :adj_value,
                            :min_price, :max_price,
                            :priority, :is_active,
                            :eff_from, :eff_until
                        )
                        ON CONFLICT (tenant_id, store_id, dish_id, rule_type, daypart)
                        DO UPDATE SET
                            condition        = EXCLUDED.condition,
                            adjustment_type  = EXCLUDED.adjustment_type,
                            adjustment_value = EXCLUDED.adjustment_value,
                            min_price_fen    = EXCLUDED.min_price_fen,
                            max_price_fen    = EXCLUDED.max_price_fen,
                            priority         = EXCLUDED.priority,
                            is_active        = EXCLUDED.is_active,
                            effective_from   = EXCLUDED.effective_from,
                            effective_until  = EXCLUDED.effective_until,
                            updated_at       = NOW()
                        RETURNING (xmax = 0) AS is_insert
                    """),
                    {
                        "tid": tenant_uuid,
                        "sid": store_uuid,
                        "did": dish_uuid,
                        "rule_type": rule_type,
                        "daypart": daypart,
                        "condition": _json_dumps(rule.get("condition", {})),
                        "adj_type": rule["adjustment_type"],
                        "adj_value": int(rule["adjustment_value"]),
                        "min_price": rule.get("min_price_fen"),
                        "max_price": rule.get("max_price_fen"),
                        "priority": int(rule.get("priority", 0)),
                        "is_active": rule.get("is_active", True),
                        "eff_from": rule.get("effective_from"),
                        "eff_until": rule.get("effective_until"),
                    },
                )
                row = result.fetchone()
                if row and row[0]:
                    created += 1
                else:
                    updated += 1

            except (ValueError, SQLAlchemyError) as exc:
                errors.append(
                    {"dish_id": rule.get("dish_id", "?"), "error": str(exc)}
                )

        await db.flush()
        log.info(
            "rules_managed",
            store_id=store_id,
            created=created,
            updated=updated,
            errors=len(errors),
        )
        return {"created": created, "updated": updated, "errors": errors}

    async def create_rule(
        self,
        db: AsyncSession,
        store_id: str,
        tenant_id: str,
        rule: dict[str, Any],
    ) -> dict[str, Any]:
        """创建单条规则"""
        await self._set_tenant(db, tenant_id)
        store_uuid = uuid.UUID(store_id)
        tenant_uuid = uuid.UUID(tenant_id)
        dish_uuid = uuid.UUID(rule["dish_id"])

        result = await db.execute(
            text("""
                INSERT INTO dynamic_pricing_rules (
                    tenant_id, store_id, dish_id,
                    rule_type, daypart, condition,
                    adjustment_type, adjustment_value,
                    min_price_fen, max_price_fen,
                    priority, is_active,
                    effective_from, effective_until
                ) VALUES (
                    :tid, :sid, :did,
                    :rule_type, :daypart, :condition::JSONB,
                    :adj_type, :adj_value,
                    :min_price, :max_price,
                    :priority, :is_active,
                    :eff_from, :eff_until
                )
                RETURNING id, rule_type, daypart, condition,
                          adjustment_type, adjustment_value,
                          min_price_fen, max_price_fen,
                          priority, is_active,
                          effective_from, effective_until,
                          created_at
            """),
            {
                "tid": tenant_uuid,
                "sid": store_uuid,
                "did": dish_uuid,
                "rule_type": rule["rule_type"],
                "daypart": rule.get("daypart"),
                "condition": _json_dumps(rule.get("condition", {})),
                "adj_type": rule["adjustment_type"],
                "adj_value": int(rule["adjustment_value"]),
                "min_price": rule.get("min_price_fen"),
                "max_price": rule.get("max_price_fen"),
                "priority": int(rule.get("priority", 0)),
                "is_active": rule.get("is_active", True),
                "eff_from": rule.get("effective_from"),
                "eff_until": rule.get("effective_until"),
            },
        )
        row = result.mappings().first()
        await db.flush()

        log.info("rule_created", dish_id=rule["dish_id"], rule_type=rule["rule_type"])
        return _rule_row_to_dict(row, str(dish_uuid), store_id)

    async def update_rule(
        self,
        db: AsyncSession,
        tenant_id: str,
        rule_id: str,
        updates: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """更新单条规则"""
        await self._set_tenant(db, tenant_id)
        tenant_uuid = uuid.UUID(tenant_id)
        rule_uuid = uuid.UUID(rule_id)

        # 构建动态SET子句
        allowed_fields = {
            "condition", "adjustment_type", "adjustment_value",
            "min_price_fen", "max_price_fen", "priority",
            "is_active", "effective_from", "effective_until", "daypart",
        }
        set_parts: list[str] = ["updated_at = NOW()"]
        params: dict[str, Any] = {"tid": tenant_uuid, "rid": rule_uuid}

        for field_name, value in updates.items():
            if field_name not in allowed_fields:
                continue
            param_key = f"u_{field_name}"
            if field_name == "condition":
                set_parts.append(f"condition = :{param_key}::JSONB")
                params[param_key] = _json_dumps(value)
            elif field_name == "adjustment_value":
                set_parts.append(f"adjustment_value = :{param_key}")
                params[param_key] = int(value)
            elif field_name == "priority":
                set_parts.append(f"priority = :{param_key}")
                params[param_key] = int(value)
            else:
                set_parts.append(f"{field_name} = :{param_key}")
                params[param_key] = value

        if len(set_parts) <= 1:
            raise ValueError("No valid fields to update")

        set_clause = ", ".join(set_parts)
        result = await db.execute(
            text(f"""
                UPDATE dynamic_pricing_rules
                SET {set_clause}
                WHERE id = :rid AND tenant_id = :tid AND is_deleted = false
                RETURNING id, dish_id, store_id, rule_type, daypart,
                          condition, adjustment_type, adjustment_value,
                          min_price_fen, max_price_fen, priority,
                          is_active, effective_from, effective_until,
                          created_at, updated_at
            """),
            params,
        )
        row = result.mappings().first()
        if not row:
            return None

        await db.flush()
        log.info("rule_updated", rule_id=rule_id)
        return _rule_row_to_dict(row, str(row["dish_id"]), str(row["store_id"]))

    async def delete_rule(
        self,
        db: AsyncSession,
        tenant_id: str,
        rule_id: str,
    ) -> bool:
        """软删除规则"""
        await self._set_tenant(db, tenant_id)
        tenant_uuid = uuid.UUID(tenant_id)
        rule_uuid = uuid.UUID(rule_id)

        result = await db.execute(
            text("""
                UPDATE dynamic_pricing_rules
                SET is_deleted = true, updated_at = NOW()
                WHERE id = :rid AND tenant_id = :tid AND is_deleted = false
            """),
            {"rid": rule_uuid, "tid": tenant_uuid},
        )
        await db.flush()
        deleted = result.rowcount > 0
        log.info("rule_deleted", rule_id=rule_id, success=deleted)
        return deleted

    async def list_rules(
        self,
        db: AsyncSession,
        store_id: str,
        tenant_id: str,
        dish_id: Optional[str] = None,
        rule_type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """查询规则列表"""
        await self._set_tenant(db, tenant_id)
        store_uuid = uuid.UUID(store_id)
        tenant_uuid = uuid.UUID(tenant_id)

        where_parts = [
            "tenant_id = :tid",
            "store_id = :sid",
            "is_deleted = false",
        ]
        params: dict[str, Any] = {"tid": tenant_uuid, "sid": store_uuid}

        if dish_id:
            where_parts.append("dish_id = :did")
            params["did"] = uuid.UUID(dish_id)
        if rule_type:
            where_parts.append("rule_type = :rtype")
            params["rtype"] = rule_type

        where_clause = " AND ".join(where_parts)
        result = await db.execute(
            text(f"""
                SELECT id, dish_id, store_id, rule_type, daypart,
                       condition, adjustment_type, adjustment_value,
                       min_price_fen, max_price_fen, priority,
                       is_active, effective_from, effective_until,
                       created_at, updated_at
                FROM dynamic_pricing_rules
                WHERE {where_clause}
                ORDER BY priority DESC, rule_type, daypart
            """),
            params,
        )
        rows = result.mappings().all()
        return [
            _rule_row_to_dict(r, str(r["dish_id"]), str(r["store_id"]))
            for r in rows
        ]

    # ─── 6. 定价历史查询 ────────────────────────────────────────────

    async def get_pricing_history(
        self,
        db: AsyncSession,
        store_id: str,
        tenant_id: str,
        dish_id: str,
        days: int = 7,
    ) -> list[dict[str, Any]]:
        """查询菜品定价历史"""
        await self._set_tenant(db, tenant_id)
        store_uuid = uuid.UUID(store_id)
        tenant_uuid = uuid.UUID(tenant_id)
        dish_uuid = uuid.UUID(dish_id)
        since = date.today() - timedelta(days=days)

        result = await db.execute(
            text("""
                SELECT id, pricing_date,
                       original_price_fen, adjusted_price_fen,
                       adjustment_reason, rules_applied, context,
                       created_at
                FROM dynamic_pricing_logs
                WHERE tenant_id = :tid
                  AND store_id = :sid
                  AND dish_id = :did
                  AND pricing_date >= :since
                  AND is_deleted = false
                ORDER BY pricing_date DESC, created_at DESC
            """),
            {"tid": tenant_uuid, "sid": store_uuid, "did": dish_uuid, "since": since},
        )
        rows = result.mappings().all()
        return [
            {
                "id": str(r["id"]),
                "pricing_date": r["pricing_date"].isoformat() if r["pricing_date"] else None,
                "original_price_fen": int(r["original_price_fen"]),
                "original_price_yuan": round(int(r["original_price_fen"]) / 100, 2),
                "adjusted_price_fen": int(r["adjusted_price_fen"]),
                "adjusted_price_yuan": round(int(r["adjusted_price_fen"]) / 100, 2),
                "adjustment_reason": r["adjustment_reason"],
                "rules_applied": r["rules_applied"],
                "context": r["context"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]

    # ─── 7. What-if 模拟定价 ─────────────────────────────────────────

    async def simulate_pricing(
        self,
        db: AsyncSession,
        store_id: str,
        tenant_id: str,
        dish_id: str,
        mock_context: dict[str, Any],
    ) -> dict[str, Any]:
        """模拟定价(What-if): 给定假设条件，预览定价结果

        与 calculate_dynamic_price 逻辑相同，但不写入 pricing_logs。
        """
        await self._set_tenant(db, tenant_id)
        ctx = dict(mock_context)
        daypart = ctx.get("daypart") or self._current_daypart()
        ctx["daypart"] = daypart

        store_uuid = uuid.UUID(store_id)
        tenant_uuid = uuid.UUID(tenant_id)
        dish_uuid = uuid.UUID(dish_id)
        today = date.today()

        dish_row = await self._get_dish_price_and_cost(db, dish_uuid, tenant_uuid)
        if dish_row is None:
            raise ValueError(f"Dish not found: {dish_id}")

        base_price_fen = int(dish_row["price_fen"])
        cost_fen = int(dish_row["cost_fen"]) if dish_row["cost_fen"] else 0

        rules = await self._get_active_rules(
            db, store_uuid, tenant_uuid, dish_uuid, daypart, today
        )

        adjustments: list[dict[str, Any]] = []
        percent_deltas: list[float] = []
        fixed_deltas: list[int] = []

        for rule in rules:
            condition = rule["condition"] or {}
            satisfied = await self.evaluate_condition(
                db, store_id, tenant_id, condition, ctx
            )
            if not satisfied:
                continue

            adj_type = rule["adjustment_type"]
            adj_value = int(rule["adjustment_value"])
            rule_type = rule["rule_type"]

            if adj_type == "percent":
                delta_fen = int(round(base_price_fen * adj_value / 100))
                percent_deltas.append(adj_value)
            else:
                delta_fen = adj_value
                fixed_deltas.append(adj_value)

            adjustments.append(
                {
                    "rule_id": str(rule["id"]),
                    "rule_type": rule_type,
                    "reason": self._build_reason(rule_type, adj_type, adj_value),
                    "delta_fen": delta_fen,
                }
            )

        adjusted = base_price_fen
        for pct in percent_deltas:
            adjusted += int(round(base_price_fen * pct / 100))
        for fix in fixed_deltas:
            adjusted += fix

        margin_floor_applied = False
        if cost_fen > 0:
            min_price = int(round(cost_fen / (1 - self.MIN_MARGIN_RATE)))
            rule_min = self._extract_price_bound(rules, "min_price_fen")
            rule_max = self._extract_price_bound(rules, "max_price_fen")
            if rule_min is not None:
                min_price = max(min_price, rule_min)
            if adjusted < min_price:
                adjusted = min_price
                margin_floor_applied = True
            if rule_max is not None and adjusted > rule_max:
                adjusted = rule_max

        adjusted = max(adjusted, 1)
        margin_rate = (adjusted - cost_fen) / adjusted if adjusted > 0 else 0.0

        log.info(
            "dynamic_price_simulated",
            dish_id=dish_id,
            original_fen=base_price_fen,
            adjusted_fen=adjusted,
            mock_context=mock_context,
        )

        return {
            "dish_id": dish_id,
            "simulation": True,
            "mock_context": mock_context,
            "original_price_fen": base_price_fen,
            "original_price_yuan": round(base_price_fen / 100, 2),
            "adjusted_price_fen": adjusted,
            "adjusted_price_yuan": round(adjusted / 100, 2),
            "adjustments": adjustments,
            "margin_rate": round(margin_rate, 4),
            "margin_floor_applied": margin_floor_applied,
            "daypart": daypart,
        }

    # ─── 内部方法 ────────────────────────────────────────────────────

    async def _get_dish_price_and_cost(
        self,
        db: AsyncSession,
        dish_uuid: uuid.UUID,
        tenant_uuid: uuid.UUID,
    ) -> Optional[Any]:
        """查询菜品基础售价和BOM成本"""
        result = await db.execute(
            text("""
                SELECT d.price_fen,
                       COALESCE(
                           (SELECT SUM(
                               bi.standard_qty * (1 + COALESCE(bi.waste_factor, 0))
                               * COALESCE(bi.unit_cost_fen, i.unit_price_fen, 0)
                           ) / NULLIF(bt.yield_rate, 0)
                           FROM bom_templates bt
                           JOIN bom_items bi ON bi.bom_id = bt.id
                               AND bi.tenant_id = bt.tenant_id
                               AND bi.is_deleted = false
                           LEFT JOIN ingredients i ON i.id = bi.ingredient_id
                               AND i.tenant_id = bi.tenant_id
                               AND i.is_deleted = false
                           WHERE bt.dish_id = d.id
                             AND bt.tenant_id = d.tenant_id
                             AND bt.is_active = true
                             AND bt.is_deleted = false
                           ),
                           d.cost_fen,
                           0
                       ) AS cost_fen
                FROM dishes d
                WHERE d.id = :did
                  AND d.tenant_id = :tid
                  AND d.is_deleted = false
            """),
            {"did": dish_uuid, "tid": tenant_uuid},
        )
        return result.mappings().first()

    async def _get_active_rules(
        self,
        db: AsyncSession,
        store_uuid: uuid.UUID,
        tenant_uuid: uuid.UUID,
        dish_uuid: uuid.UUID,
        daypart: str,
        target_date: date,
    ) -> list[Any]:
        """获取匹配的活跃规则(按priority DESC)"""
        result = await db.execute(
            text("""
                SELECT id, rule_type, daypart, condition,
                       adjustment_type, adjustment_value,
                       min_price_fen, max_price_fen, priority
                FROM dynamic_pricing_rules
                WHERE tenant_id = :tid
                  AND store_id = :sid
                  AND dish_id = :did
                  AND is_active = true
                  AND is_deleted = false
                  AND (daypart IS NULL OR daypart = :daypart)
                  AND (effective_from IS NULL OR effective_from <= :td)
                  AND (effective_until IS NULL OR effective_until >= :td)
                ORDER BY priority DESC
            """),
            {
                "tid": tenant_uuid,
                "sid": store_uuid,
                "did": dish_uuid,
                "daypart": daypart,
                "td": target_date,
            },
        )
        return list(result.mappings().all())

    async def _write_pricing_log(
        self,
        db: AsyncSession,
        tenant_uuid: uuid.UUID,
        store_uuid: uuid.UUID,
        dish_uuid: uuid.UUID,
        pricing_date: date,
        original_price_fen: int,
        adjusted_price_fen: int,
        adjustment_reason: str,
        rules_applied: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> None:
        """写入定价日志"""
        await db.execute(
            text("""
                INSERT INTO dynamic_pricing_logs (
                    tenant_id, store_id, dish_id, pricing_date,
                    original_price_fen, adjusted_price_fen,
                    adjustment_reason, rules_applied, context
                ) VALUES (
                    :tid, :sid, :did, :pd,
                    :orig, :adj,
                    :reason, :rules::JSONB, :ctx::JSONB
                )
            """),
            {
                "tid": tenant_uuid,
                "sid": store_uuid,
                "did": dish_uuid,
                "pd": pricing_date,
                "orig": original_price_fen,
                "adj": adjusted_price_fen,
                "reason": adjustment_reason,
                "rules": _json_dumps(rules_applied),
                "ctx": _json_dumps(context),
            },
        )

    async def _get_current_weather(
        self,
        db: AsyncSession,
        store_id: str,
        tenant_id: str,
    ) -> Optional[str]:
        """从需求预测表获取当前天气(fallback: None)"""
        store_uuid = uuid.UUID(store_id)
        tenant_uuid = uuid.UUID(tenant_id)
        today = date.today()

        try:
            result = await db.execute(
                text("""
                    SELECT weather_condition
                    FROM demand_forecast_enhanced
                    WHERE store_id = :sid
                      AND tenant_id = :tid
                      AND forecast_date = :td
                      AND is_deleted = false
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {"sid": store_uuid, "tid": tenant_uuid, "td": today},
            )
            row = result.scalar_one_or_none()
            return str(row) if row else None
        except SQLAlchemyError:
            log.warning("weather_query_failed", store_id=store_id)
            return None

    @staticmethod
    def _build_reason(rule_type: str, adj_type: str, adj_value: int) -> str:
        """生成调整原因描述"""
        type_names: dict[str, str] = {
            "time_based": "时段定价",
            "demand_based": "需求定价",
            "inventory_based": "库存清货",
            "weather_based": "天气调价",
            "member_tier": "会员专价",
        }
        name = type_names.get(rule_type, rule_type)
        if adj_type == "percent":
            direction = "加" if adj_value > 0 else "减"
            return f"{name}: {direction}{abs(adj_value)}%"
        direction = "加" if adj_value > 0 else "减"
        return f"{name}: {direction}{abs(adj_value)/100:.2f}元"

    @staticmethod
    def _extract_price_bound(
        rules: list[Any],
        field: str,
    ) -> Optional[int]:
        """从所有规则中提取价格边界(取最严格值)"""
        values = [
            int(r[field]) for r in rules if r.get(field) is not None
        ]
        if not values:
            return None
        if field == "min_price_fen":
            return max(values)  # 取最高地板价
        return min(values)  # 取最低天花板价


# ─── 模块级工具函数 ──────────────────────────────────────────────────


def _json_dumps(obj: Any) -> str:
    """安全JSON序列化"""
    import json
    return json.dumps(obj, ensure_ascii=False, default=str)


def _rule_row_to_dict(row: Any, dish_id: str, store_id: str) -> dict[str, Any]:
    """将规则行转为字典"""
    return {
        "id": str(row["id"]),
        "dish_id": dish_id,
        "store_id": store_id,
        "rule_type": row["rule_type"],
        "daypart": row["daypart"],
        "condition": row["condition"],
        "adjustment_type": row["adjustment_type"],
        "adjustment_value": int(row["adjustment_value"]),
        "min_price_fen": int(row["min_price_fen"]) if row["min_price_fen"] is not None else None,
        "max_price_fen": int(row["max_price_fen"]) if row["max_price_fen"] is not None else None,
        "priority": int(row["priority"]),
        "is_active": row["is_active"],
        "effective_from": row["effective_from"].isoformat() if row.get("effective_from") else None,
        "effective_until": row["effective_until"].isoformat() if row.get("effective_until") else None,
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }
