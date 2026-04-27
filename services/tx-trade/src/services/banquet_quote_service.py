"""宴会智能报价服务 — 套餐模板/报价生成/菜单定制/多版本对比

从模板一键生成报价 → 灵活定制菜单 → 自动计算价格 → 多版本对比 → 发送客户。
金额单位: 分(fen)。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


# ─── 常量 ───────────────────────────────────────────────────────────────────

QUOTE_STATUSES = ("draft", "sent", "accepted", "rejected", "expired")

VALID_QUOTE_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"sent", "expired"},
    "sent": {"accepted", "rejected", "expired"},
    # accepted / rejected / expired 为终态
}

TEMPLATE_TIERS = ("standard", "premium", "luxury")


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def _safe_json(val: object) -> str:
    """安全序列化为 JSON 字符串。"""
    if isinstance(val, str):
        return val
    return json.dumps(val, ensure_ascii=False, default=str)


def _parse_json(val: object) -> object:
    """安全解析 JSON。"""
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        return json.loads(val)
    return val


# ─── Service ────────────────────────────────────────────────────────────────


class BanquetQuoteService:
    """宴会报价全流程管理"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self._db = db
        self._tenant_id = tenant_id

    # ── 套餐模板 ──────────────────────────────────────────────────────────

    async def create_template(
        self,
        store_id: str,
        name: str,
        event_type: str,
        tier: str,
        per_table_price_fen: int,
        dishes_json: list[dict],
        description: Optional[str] = None,
        min_tables: Optional[int] = None,
        max_tables: Optional[int] = None,
        beverage_per_table_fen: int = 0,
        service_fee_rate: float = 0.0,
    ) -> dict:
        """创建报价套餐模板。

        Args:
            store_id: 门店ID
            name: 套餐名称
            event_type: 宴会类型
            tier: 档次 (standard/premium/luxury)
            per_table_price_fen: 每桌价格（分）
            dishes_json: 菜品列表 [{name, category, unit_price_fen, qty}]
            description: 套餐描述
            min_tables: 最低桌数
            max_tables: 最高桌数
            beverage_per_table_fen: 每桌酒水费（分）
            service_fee_rate: 服务费率 (0.0 ~ 1.0)
        """
        if not name or not name.strip():
            raise ValueError("套餐名称不能为空")
        if tier not in TEMPLATE_TIERS:
            raise ValueError(f"无效档次: {tier}，可选: {TEMPLATE_TIERS}")
        if per_table_price_fen <= 0:
            raise ValueError("每桌价格必须大于0")
        if not dishes_json:
            raise ValueError("菜品列表不能为空")
        if service_fee_rate < 0 or service_fee_rate > 1:
            raise ValueError("服务费率必须在 0 ~ 1 之间")

        template_id = str(uuid.uuid4())
        now = _now_utc()

        await self._db.execute(
            text("""
                INSERT INTO banquet_quote_templates (
                    id, tenant_id, store_id, name, event_type, tier,
                    per_table_price_fen, dishes_json, description,
                    min_tables, max_tables, beverage_per_table_fen,
                    service_fee_rate, is_active,
                    created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :store_id, :name, :event_type, :tier,
                    :per_table_price_fen, :dishes_json, :description,
                    :min_tables, :max_tables, :beverage_per_table_fen,
                    :service_fee_rate, TRUE,
                    :now, :now
                )
            """),
            {
                "id": template_id,
                "tenant_id": self._tenant_id,
                "store_id": store_id,
                "name": name.strip(),
                "event_type": event_type,
                "tier": tier,
                "per_table_price_fen": per_table_price_fen,
                "dishes_json": _safe_json(dishes_json),
                "description": description,
                "min_tables": min_tables,
                "max_tables": max_tables,
                "beverage_per_table_fen": beverage_per_table_fen,
                "service_fee_rate": service_fee_rate,
                "now": now,
            },
        )
        await self._db.flush()

        logger.info(
            "banquet_quote_template_created",
            tenant_id=self._tenant_id,
            template_id=template_id,
            name=name,
            tier=tier,
            per_table_price_fen=per_table_price_fen,
        )

        return {
            "id": template_id,
            "store_id": store_id,
            "name": name.strip(),
            "event_type": event_type,
            "tier": tier,
            "per_table_price_fen": per_table_price_fen,
            "dishes_json": dishes_json,
            "description": description,
            "min_tables": min_tables,
            "max_tables": max_tables,
            "beverage_per_table_fen": beverage_per_table_fen,
            "service_fee_rate": service_fee_rate,
            "is_active": True,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }

    async def list_templates(
        self,
        store_id: Optional[str] = None,
        event_type: Optional[str] = None,
        tier: Optional[str] = None,
        is_active: Optional[bool] = True,
    ) -> list:
        """查询套餐模板列表。"""
        conditions = ["tenant_id = :tenant_id"]
        params: dict = {"tenant_id": self._tenant_id}

        if store_id:
            conditions.append("store_id = :store_id")
            params["store_id"] = store_id
        if event_type:
            conditions.append("event_type = :event_type")
            params["event_type"] = event_type
        if tier:
            conditions.append("tier = :tier")
            params["tier"] = tier
        if is_active is not None:
            conditions.append("is_active = :is_active")
            params["is_active"] = is_active

        where = " AND ".join(conditions)

        result = await self._db.execute(
            text(f"""
                SELECT id, store_id, name, event_type, tier,
                       per_table_price_fen, description, min_tables, max_tables,
                       beverage_per_table_fen, service_fee_rate, is_active,
                       created_at, updated_at
                FROM banquet_quote_templates
                WHERE {where}
                ORDER BY tier, per_table_price_fen ASC
            """),
            params,
        )
        rows = result.mappings().all()

        return [
            {
                "id": str(r["id"]),
                "store_id": str(r["store_id"]),
                "name": r["name"],
                "event_type": r["event_type"],
                "tier": r["tier"],
                "per_table_price_fen": r["per_table_price_fen"],
                "description": r["description"],
                "min_tables": r["min_tables"],
                "max_tables": r["max_tables"],
                "beverage_per_table_fen": r["beverage_per_table_fen"],
                "service_fee_rate": float(r["service_fee_rate"]) if r["service_fee_rate"] else 0.0,
                "is_active": r["is_active"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            }
            for r in rows
        ]

    async def get_template(self, template_id: str) -> dict:
        """获取单个套餐模板详情（含菜品列表）。"""
        result = await self._db.execute(
            text("""
                SELECT * FROM banquet_quote_templates
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {"id": template_id, "tenant_id": self._tenant_id},
        )
        row = result.mappings().first()
        if not row:
            raise ValueError(f"套餐模板不存在: {template_id}")

        return {
            "id": str(row["id"]),
            "store_id": str(row["store_id"]),
            "name": row["name"],
            "event_type": row["event_type"],
            "tier": row["tier"],
            "per_table_price_fen": row["per_table_price_fen"],
            "dishes_json": _parse_json(row["dishes_json"]),
            "description": row["description"],
            "min_tables": row["min_tables"],
            "max_tables": row["max_tables"],
            "beverage_per_table_fen": row["beverage_per_table_fen"],
            "service_fee_rate": float(row["service_fee_rate"]) if row["service_fee_rate"] else 0.0,
            "is_active": row["is_active"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }

    async def update_template(self, template_id: str, **kwargs: object) -> dict:
        """更新套餐模板。"""
        allowed = {
            "name",
            "event_type",
            "tier",
            "per_table_price_fen",
            "dishes_json",
            "description",
            "min_tables",
            "max_tables",
            "beverage_per_table_fen",
            "service_fee_rate",
            "is_active",
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            raise ValueError("没有有效的更新字段")

        # 验证存在
        check = await self._db.execute(
            text("""
                SELECT id FROM banquet_quote_templates
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {"id": template_id, "tenant_id": self._tenant_id},
        )
        if not check.first():
            raise ValueError(f"套餐模板不存在: {template_id}")

        # dishes_json 需序列化
        if "dishes_json" in updates and not isinstance(updates["dishes_json"], str):
            updates["dishes_json"] = _safe_json(updates["dishes_json"])

        set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
        updates["updated_at"] = _now_utc()
        set_clauses += ", updated_at = :updated_at"
        updates["id"] = template_id
        updates["tenant_id"] = self._tenant_id

        await self._db.execute(
            text(f"""
                UPDATE banquet_quote_templates
                SET {set_clauses}
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            updates,
        )
        await self._db.flush()

        logger.info(
            "banquet_quote_template_updated",
            tenant_id=self._tenant_id,
            template_id=template_id,
            fields=list(kwargs.keys()),
        )

        return await self.get_template(template_id)

    # ── 报价单 ────────────────────────────────────────────────────────────

    async def generate_quote(
        self,
        lead_id: str,
        template_id: str,
        table_count: int,
        guest_count: int,
        customizations: Optional[list[dict]] = None,
    ) -> dict:
        """从模板一键生成报价单。

        Args:
            lead_id: 线索ID
            template_id: 套餐模板ID
            table_count: 桌数
            guest_count: 宾客人数
            customizations: 定制项 [{action: "add"|"remove"|"replace", ...}]
        """
        if table_count <= 0:
            raise ValueError("桌数必须大于0")
        if guest_count <= 0:
            raise ValueError("宾客人数必须大于0")

        # 获取模板
        template = await self.get_template(template_id)

        # 验证桌数范围
        if template["min_tables"] and table_count < template["min_tables"]:
            raise ValueError(f"桌数不能少于 {template['min_tables']}")
        if template["max_tables"] and table_count > template["max_tables"]:
            raise ValueError(f"桌数不能超过 {template['max_tables']}")

        # 复制菜品并应用定制
        menu_json = list(template["dishes_json"]) if template["dishes_json"] else []
        if customizations:
            menu_json = self._apply_customizations(menu_json, customizations)

        # 计算费用
        food_subtotal_fen = template["per_table_price_fen"] * table_count
        beverage_total_fen = (template["beverage_per_table_fen"] or 0) * table_count
        subtotal_fen = food_subtotal_fen + beverage_total_fen
        service_fee_fen = int(subtotal_fen * (template["service_fee_rate"] or 0.0))
        total_fen = subtotal_fen + service_fee_fen

        # 确定版本号
        version_row = await self._db.execute(
            text("""
                SELECT COALESCE(MAX(version), 0) AS max_ver
                FROM banquet_quotes
                WHERE lead_id = :lead_id AND tenant_id = :tenant_id
            """),
            {"lead_id": lead_id, "tenant_id": self._tenant_id},
        )
        version = (version_row.scalar() or 0) + 1

        quote_id = str(uuid.uuid4())
        quote_no = _gen_id("BQT")
        now = _now_utc()

        await self._db.execute(
            text("""
                INSERT INTO banquet_quotes (
                    id, tenant_id, quote_no, lead_id, template_id, version,
                    table_count, guest_count, menu_json,
                    food_subtotal_fen, beverage_total_fen, service_fee_fen,
                    subtotal_fen, discount_fen, total_fen,
                    status, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :quote_no, :lead_id, :template_id, :version,
                    :table_count, :guest_count, :menu_json,
                    :food_subtotal_fen, :beverage_total_fen, :service_fee_fen,
                    :subtotal_fen, 0, :total_fen,
                    'draft', :now, :now
                )
            """),
            {
                "id": quote_id,
                "tenant_id": self._tenant_id,
                "quote_no": quote_no,
                "lead_id": lead_id,
                "template_id": template_id,
                "version": version,
                "table_count": table_count,
                "guest_count": guest_count,
                "menu_json": _safe_json(menu_json),
                "food_subtotal_fen": food_subtotal_fen,
                "beverage_total_fen": beverage_total_fen,
                "service_fee_fen": service_fee_fen,
                "subtotal_fen": subtotal_fen,
                "total_fen": total_fen,
                "now": now,
            },
        )

        # 插入报价明细行
        for idx, dish in enumerate(menu_json):
            item_id = str(uuid.uuid4())
            unit_price = dish.get("unit_price_fen", 0)
            qty = dish.get("qty", 1)
            line_total = unit_price * qty

            await self._db.execute(
                text("""
                    INSERT INTO banquet_quote_items (
                        id, tenant_id, quote_id, seq, dish_name, category,
                        unit_price_fen, qty, line_total_fen, created_at
                    ) VALUES (
                        :id, :tenant_id, :quote_id, :seq, :dish_name, :category,
                        :unit_price_fen, :qty, :line_total_fen, :now
                    )
                """),
                {
                    "id": item_id,
                    "tenant_id": self._tenant_id,
                    "quote_id": quote_id,
                    "seq": idx + 1,
                    "dish_name": dish.get("name", ""),
                    "category": dish.get("category", ""),
                    "unit_price_fen": unit_price,
                    "qty": qty,
                    "line_total_fen": line_total,
                    "now": now,
                },
            )

        await self._db.flush()

        logger.info(
            "banquet_quote_generated",
            tenant_id=self._tenant_id,
            quote_id=quote_id,
            quote_no=quote_no,
            lead_id=lead_id,
            template_id=template_id,
            version=version,
            table_count=table_count,
            total_fen=total_fen,
        )

        return {
            "id": quote_id,
            "quote_no": quote_no,
            "lead_id": lead_id,
            "template_id": template_id,
            "version": version,
            "table_count": table_count,
            "guest_count": guest_count,
            "menu_json": menu_json,
            "food_subtotal_fen": food_subtotal_fen,
            "beverage_total_fen": beverage_total_fen,
            "service_fee_fen": service_fee_fen,
            "subtotal_fen": subtotal_fen,
            "discount_fen": 0,
            "total_fen": total_fen,
            "status": "draft",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }

    def _apply_customizations(
        self,
        menu: list[dict],
        customizations: list[dict],
    ) -> list[dict]:
        """应用菜单定制：添加/删除/替换菜品。"""
        result = list(menu)

        for c in customizations:
            action = c.get("action")
            if action == "add":
                result.append(
                    {
                        "name": c["name"],
                        "category": c.get("category", ""),
                        "unit_price_fen": c.get("unit_price_fen", 0),
                        "qty": c.get("qty", 1),
                    }
                )
            elif action == "remove":
                target = c.get("name")
                result = [d for d in result if d.get("name") != target]
            elif action == "replace":
                target = c.get("original_name")
                for i, d in enumerate(result):
                    if d.get("name") == target:
                        result[i] = {
                            "name": c["name"],
                            "category": c.get("category", d.get("category", "")),
                            "unit_price_fen": c.get("unit_price_fen", d.get("unit_price_fen", 0)),
                            "qty": c.get("qty", d.get("qty", 1)),
                        }
                        break
            else:
                raise ValueError(f"无效的定制操作: {action}，可选: add/remove/replace")

        return result

    async def customize_menu(
        self,
        quote_id: str,
        menu_changes: list[dict],
    ) -> dict:
        """对已有报价单进行菜单定制，自动重新计算价格并递增版本。"""
        row = await self._db.execute(
            text("""
                SELECT id, lead_id, template_id, menu_json, table_count,
                       guest_count, version, status,
                       beverage_total_fen, service_fee_fen
                FROM banquet_quotes
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {"id": quote_id, "tenant_id": self._tenant_id},
        )
        quote = row.mappings().first()
        if not quote:
            raise ValueError(f"报价单不存在: {quote_id}")
        if quote["status"] not in ("draft",):
            raise ValueError(f"仅草稿状态可定制菜单，当前: {quote['status']}")

        current_menu = _parse_json(quote["menu_json"]) or []
        new_menu = self._apply_customizations(current_menu, menu_changes)

        # 获取模板以重算费率
        tmpl_row = await self._db.execute(
            text("""
                SELECT service_fee_rate FROM banquet_quote_templates
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {"id": str(quote["template_id"]), "tenant_id": self._tenant_id},
        )
        tmpl = tmpl_row.mappings().first()
        svc_rate = float(tmpl["service_fee_rate"]) if tmpl and tmpl["service_fee_rate"] else 0.0

        # 重算价格
        food_subtotal_fen = sum(d.get("unit_price_fen", 0) * d.get("qty", 1) for d in new_menu) * quote["table_count"]
        beverage_total_fen = quote["beverage_total_fen"] or 0
        subtotal_fen = food_subtotal_fen + beverage_total_fen
        service_fee_fen = int(subtotal_fen * svc_rate)
        total_fen = subtotal_fen + service_fee_fen

        new_version = quote["version"] + 1
        now = _now_utc()

        await self._db.execute(
            text("""
                UPDATE banquet_quotes
                SET menu_json = :menu_json,
                    food_subtotal_fen = :food_subtotal_fen,
                    subtotal_fen = :subtotal_fen,
                    service_fee_fen = :service_fee_fen,
                    total_fen = :total_fen,
                    version = :version,
                    updated_at = :now
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {
                "id": quote_id,
                "tenant_id": self._tenant_id,
                "menu_json": _safe_json(new_menu),
                "food_subtotal_fen": food_subtotal_fen,
                "subtotal_fen": subtotal_fen,
                "service_fee_fen": service_fee_fen,
                "total_fen": total_fen,
                "version": new_version,
                "now": now,
            },
        )

        # 重建明细行
        await self._db.execute(
            text("""
                DELETE FROM banquet_quote_items
                WHERE quote_id = :quote_id AND tenant_id = :tenant_id
            """),
            {"quote_id": quote_id, "tenant_id": self._tenant_id},
        )

        for idx, dish in enumerate(new_menu):
            item_id = str(uuid.uuid4())
            unit_price = dish.get("unit_price_fen", 0)
            qty = dish.get("qty", 1)

            await self._db.execute(
                text("""
                    INSERT INTO banquet_quote_items (
                        id, tenant_id, quote_id, seq, dish_name, category,
                        unit_price_fen, qty, line_total_fen, created_at
                    ) VALUES (
                        :id, :tenant_id, :quote_id, :seq, :dish_name, :category,
                        :unit_price_fen, :qty, :line_total_fen, :now
                    )
                """),
                {
                    "id": item_id,
                    "tenant_id": self._tenant_id,
                    "quote_id": quote_id,
                    "seq": idx + 1,
                    "dish_name": dish.get("name", ""),
                    "category": dish.get("category", ""),
                    "unit_price_fen": unit_price,
                    "qty": qty,
                    "line_total_fen": unit_price * qty,
                    "now": now,
                },
            )

        await self._db.flush()

        logger.info(
            "banquet_quote_menu_customized",
            tenant_id=self._tenant_id,
            quote_id=quote_id,
            version=new_version,
            changes_count=len(menu_changes),
            total_fen=total_fen,
        )

        return await self.get_quote_detail(quote_id)

    async def update_quote_status(self, quote_id: str, new_status: str) -> dict:
        """更新报价单状态，校验合法流转。"""
        if new_status not in QUOTE_STATUSES:
            raise ValueError(f"无效状态: {new_status}，可选: {QUOTE_STATUSES}")

        row = await self._db.execute(
            text("""
                SELECT id, status FROM banquet_quotes
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {"id": quote_id, "tenant_id": self._tenant_id},
        )
        quote = row.mappings().first()
        if not quote:
            raise ValueError(f"报价单不存在: {quote_id}")

        current = quote["status"]
        valid_next = VALID_QUOTE_TRANSITIONS.get(current, set())
        if new_status not in valid_next:
            raise ValueError(f"报价状态流转非法: {current} → {new_status}，允许: {valid_next}")

        now = _now_utc()
        await self._db.execute(
            text("""
                UPDATE banquet_quotes
                SET status = :new_status, updated_at = :now
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {
                "id": quote_id,
                "tenant_id": self._tenant_id,
                "new_status": new_status,
                "now": now,
            },
        )
        await self._db.flush()

        logger.info(
            "banquet_quote_status_updated",
            tenant_id=self._tenant_id,
            quote_id=quote_id,
            from_status=current,
            to_status=new_status,
        )

        return await self.get_quote_detail(quote_id)

    async def list_quotes(self, lead_id: str) -> list:
        """查询线索的所有报价单，按版本降序。"""
        result = await self._db.execute(
            text("""
                SELECT id, quote_no, lead_id, template_id, version,
                       table_count, guest_count,
                       food_subtotal_fen, beverage_total_fen,
                       service_fee_fen, subtotal_fen, discount_fen, total_fen,
                       status, created_at, updated_at
                FROM banquet_quotes
                WHERE lead_id = :lead_id AND tenant_id = :tenant_id
                ORDER BY version DESC
            """),
            {"lead_id": lead_id, "tenant_id": self._tenant_id},
        )
        rows = result.mappings().all()

        return [
            {
                "id": str(r["id"]),
                "quote_no": r["quote_no"],
                "lead_id": str(r["lead_id"]),
                "template_id": str(r["template_id"]),
                "version": r["version"],
                "table_count": r["table_count"],
                "guest_count": r["guest_count"],
                "food_subtotal_fen": r["food_subtotal_fen"],
                "beverage_total_fen": r["beverage_total_fen"],
                "service_fee_fen": r["service_fee_fen"],
                "subtotal_fen": r["subtotal_fen"],
                "discount_fen": r["discount_fen"],
                "total_fen": r["total_fen"],
                "status": r["status"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            }
            for r in rows
        ]

    async def compare_quotes(self, quote_ids: list[str]) -> dict:
        """多报价单横向对比。"""
        if len(quote_ids) < 2:
            raise ValueError("至少需要2个报价单进行对比")
        if len(quote_ids) > 5:
            raise ValueError("最多支持5个报价单对比")

        quotes = []
        for qid in quote_ids:
            detail = await self.get_quote_detail(qid)
            quotes.append(detail)

        # 提取对比维度
        comparison = {
            "quotes": quotes,
            "summary": {
                "price_range_fen": {
                    "min": min(q["total_fen"] for q in quotes),
                    "max": max(q["total_fen"] for q in quotes),
                },
                "table_counts": [q["table_count"] for q in quotes],
                "guest_counts": [q["guest_count"] for q in quotes],
                "versions": [q["version"] for q in quotes],
                "dish_counts": [len(q.get("menu_json") or []) for q in quotes],
            },
        }

        logger.info(
            "banquet_quotes_compared",
            tenant_id=self._tenant_id,
            quote_ids=quote_ids,
        )

        return comparison

    async def get_quote_detail(self, quote_id: str) -> dict:
        """获取报价单详情（含菜品明细行）。"""
        row = await self._db.execute(
            text("""
                SELECT * FROM banquet_quotes
                WHERE id = :id AND tenant_id = :tenant_id
            """),
            {"id": quote_id, "tenant_id": self._tenant_id},
        )
        quote = row.mappings().first()
        if not quote:
            raise ValueError(f"报价单不存在: {quote_id}")

        # 获取明细行
        items_result = await self._db.execute(
            text("""
                SELECT id, seq, dish_name, category,
                       unit_price_fen, qty, line_total_fen
                FROM banquet_quote_items
                WHERE quote_id = :quote_id AND tenant_id = :tenant_id
                ORDER BY seq ASC
            """),
            {"quote_id": quote_id, "tenant_id": self._tenant_id},
        )
        items = items_result.mappings().all()

        return {
            "id": str(quote["id"]),
            "quote_no": quote["quote_no"],
            "lead_id": str(quote["lead_id"]),
            "template_id": str(quote["template_id"]),
            "version": quote["version"],
            "table_count": quote["table_count"],
            "guest_count": quote["guest_count"],
            "menu_json": _parse_json(quote["menu_json"]),
            "food_subtotal_fen": quote["food_subtotal_fen"],
            "beverage_total_fen": quote["beverage_total_fen"],
            "service_fee_fen": quote["service_fee_fen"],
            "subtotal_fen": quote["subtotal_fen"],
            "discount_fen": quote["discount_fen"],
            "total_fen": quote["total_fen"],
            "status": quote["status"],
            "items": [
                {
                    "id": str(it["id"]),
                    "seq": it["seq"],
                    "dish_name": it["dish_name"],
                    "category": it["category"],
                    "unit_price_fen": it["unit_price_fen"],
                    "qty": it["qty"],
                    "line_total_fen": it["line_total_fen"],
                }
                for it in items
            ],
            "created_at": quote["created_at"].isoformat() if quote["created_at"] else None,
            "updated_at": quote["updated_at"].isoformat() if quote["updated_at"] else None,
        }
