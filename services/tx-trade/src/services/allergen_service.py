"""过敏原 Service

职责：
  1. check_allergens_for_order()  — 检查订单所有菜品是否含有会员过敏原
  2. check_dish_for_member()      — 检查单个菜品是否触发过敏/忌口
  3. set_dish_allergens()         — 设置菜品过敏原标签（后台管理用）
  4. get_allergen_summary()       — 获取所有过敏原代码和中文标签
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# 过敏原主数据（14种中国餐饮常见过敏原）
# ──────────────────────────────────────────────────────────────────────────────

ALLERGEN_CATALOG: dict[str, str] = {
    "peanut": "花生",
    "shellfish": "贝壳海鲜",
    "fish": "鱼",
    "egg": "鸡蛋",
    "milk": "牛奶",
    "soy": "大豆",
    "wheat": "小麦/面筋",
    "sesame": "芝麻",
    "tree_nut": "坚果",
    "pork": "猪肉",
    "beef": "牛肉",
    "spicy": "辣",
    "msg": "味精",
    "sulfite": "亚硫酸盐",
}

# 忌口偏好类（非真性过敏，severity=warning）
PREFERENCE_ALLERGENS = frozenset({"spicy", "msg", "pork", "beef"})


class AllergenAlert:
    """单条过敏/忌口预警"""

    def __init__(
        self,
        dish_id: str,
        dish_name: str,
        allergen_code: str,
        allergen_label: str,
        severity: str,  # "danger" | "warning"
    ) -> None:
        self.dish_id = dish_id
        self.dish_name = dish_name
        self.allergen_code = allergen_code
        self.allergen_label = allergen_label
        self.severity = severity

    def to_dict(self) -> dict[str, Any]:
        return {
            "dish_id": self.dish_id,
            "dish_name": self.dish_name,
            "allergen_code": self.allergen_code,
            "allergen_label": self.allergen_label,
            "severity": self.severity,
        }


class AllergenService:
    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = uuid.UUID(tenant_id)
        self._tenant_str = tenant_id

    # ──────────────────────────────────────────────────────────────────────
    #  内部辅助
    # ──────────────────────────────────────────────────────────────────────

    async def _get_member_allergens(self, member_id: str) -> list[str]:
        """从 members 表读取 allergens JSONB 字段"""
        try:
            row = await self.db.execute(
                text("SELECT allergens FROM members WHERE id = :mid AND tenant_id = :tid AND is_deleted = FALSE"),
                {"mid": uuid.UUID(member_id), "tid": self.tenant_id},
            )
            result = row.fetchone()
            if result and result[0]:
                return list(result[0])
            return []
        except SQLAlchemyError as exc:
            logger.error(
                "allergen_service.get_member_allergens_failed",
                member_id=member_id,
                error=str(exc),
            )
            return []

    async def _get_dish_allergen_codes(self, dish_id: str) -> list[dict[str, str]]:
        """获取菜品已标注的过敏原代码列表"""
        try:
            rows = await self.db.execute(
                text(
                    "SELECT allergen_code, allergen_label FROM dish_allergens "
                    "WHERE dish_id = :did AND tenant_id = :tid AND is_deleted = FALSE"
                ),
                {"did": uuid.UUID(dish_id), "tid": self.tenant_id},
            )
            return [{"code": r[0], "label": r[1]} for r in rows.fetchall()]
        except SQLAlchemyError as exc:
            logger.error(
                "allergen_service.get_dish_allergens_failed",
                dish_id=dish_id,
                error=str(exc),
            )
            return []

    def _compute_severity(self, allergen_code: str) -> str:
        """判断严重程度：忌口偏好=warning，真性过敏=danger"""
        return "warning" if allergen_code in PREFERENCE_ALLERGENS else "danger"

    # ──────────────────────────────────────────────────────────────────────
    #  公开接口
    # ──────────────────────────────────────────────────────────────────────

    async def check_dish_for_member(
        self,
        dish_id: str,
        dish_name: str,
        member_id: str,
    ) -> list[AllergenAlert]:
        """检查单个菜品是否触发该会员的过敏/忌口。返回 AllergenAlert 列表（可能为空）。"""
        member_allergens = set(await self._get_member_allergens(member_id))
        if not member_allergens:
            return []

        dish_allergen_entries = await self._get_dish_allergen_codes(dish_id)
        if not dish_allergen_entries:
            return []

        alerts: list[AllergenAlert] = []
        for entry in dish_allergen_entries:
            code = entry["code"]
            if code in member_allergens:
                alerts.append(
                    AllergenAlert(
                        dish_id=dish_id,
                        dish_name=dish_name,
                        allergen_code=code,
                        allergen_label=entry["label"],
                        severity=self._compute_severity(code),
                    )
                )

        if alerts:
            logger.info(
                "allergen_service.dish_alert",
                dish_id=dish_id,
                member_id=member_id,
                alert_count=len(alerts),
            )
        return alerts

    async def check_allergens_for_order(
        self,
        order_id: str,
        member_id: str,
    ) -> list[AllergenAlert]:
        """检查订单中所有菜品是否含有该会员的过敏原。

        Returns:
            list[AllergenAlert] — 每条对应一个<菜品, 过敏原>组合
        """
        member_allergens = set(await self._get_member_allergens(member_id))
        if not member_allergens:
            return []

        # 查询订单中的所有菜品
        try:
            rows = await self.db.execute(
                text(
                    "SELECT oi.dish_id, oi.dish_name "
                    "FROM order_items oi "
                    "JOIN orders o ON o.id = oi.order_id "
                    "WHERE oi.order_id = :oid AND o.tenant_id = :tid "
                    "  AND oi.is_deleted = FALSE AND oi.status != 'returned'"
                ),
                {"oid": uuid.UUID(order_id), "tid": self.tenant_id},
            )
            order_dishes = rows.fetchall()
        except SQLAlchemyError as exc:
            logger.error(
                "allergen_service.get_order_dishes_failed",
                order_id=order_id,
                error=str(exc),
            )
            return []

        all_alerts: list[AllergenAlert] = []
        for dish_id, dish_name in order_dishes:
            dish_alerts = await self.check_dish_for_member(
                dish_id=str(dish_id),
                dish_name=dish_name,
                member_id=member_id,
            )
            all_alerts.extend(dish_alerts)

        return all_alerts

    async def set_dish_allergens(
        self,
        dish_id: str,
        allergen_codes: list[str],
    ) -> dict[str, Any]:
        """设置菜品过敏原标签（全量替换）。供后台管理调用。"""
        invalid_codes = [c for c in allergen_codes if c not in ALLERGEN_CATALOG]
        if invalid_codes:
            raise ValueError(f"无效的过敏原代码: {invalid_codes}。支持的代码: {sorted(ALLERGEN_CATALOG.keys())}")

        dish_uuid = uuid.UUID(dish_id)

        try:
            # 软删除旧标签
            await self.db.execute(
                text(
                    "UPDATE dish_allergens SET is_deleted = TRUE "
                    "WHERE dish_id = :did AND tenant_id = :tid AND is_deleted = FALSE"
                ),
                {"did": dish_uuid, "tid": self.tenant_id},
            )

            # 写入新标签（UPSERT）
            for code in allergen_codes:
                label = ALLERGEN_CATALOG[code]
                await self.db.execute(
                    text(
                        "INSERT INTO dish_allergens (tenant_id, dish_id, allergen_code, allergen_label) "
                        "VALUES (:tid, :did, :code, :label) "
                        "ON CONFLICT (tenant_id, dish_id, allergen_code) "
                        "DO UPDATE SET allergen_label = EXCLUDED.allergen_label, is_deleted = FALSE"
                    ),
                    {
                        "tid": self.tenant_id,
                        "did": dish_uuid,
                        "code": code,
                        "label": label,
                    },
                )

            await self.db.commit()

            logger.info(
                "allergen_service.set_dish_allergens",
                dish_id=dish_id,
                codes=allergen_codes,
            )
            return {
                "dish_id": dish_id,
                "allergen_codes": allergen_codes,
                "count": len(allergen_codes),
            }
        except SQLAlchemyError as exc:
            await self.db.rollback()
            logger.error(
                "allergen_service.set_dish_allergens_failed",
                dish_id=dish_id,
                error=str(exc),
            )
            raise

    async def get_dish_allergens(self, dish_id: str) -> list[dict[str, str]]:
        """获取菜品过敏原列表，返回 [{allergen_code, allergen_label}]。"""
        entries = await self._get_dish_allergen_codes(dish_id)
        return [{"allergen_code": e["code"], "allergen_label": e["label"]} for e in entries]

    async def check_dishes_for_member(
        self,
        dish_ids: list[str],
        dish_names: dict[str, str],
        member_id: str,
    ) -> list[dict[str, Any]]:
        """批量检查多个菜品对某会员的过敏风险。

        Args:
            dish_ids:   菜品 ID 列表
            dish_names: {dish_id -> dish_name} 映射
            member_id:  会员 ID

        Returns:
            [{dish_id, dish_name, alerts: [{allergen_code, allergen_label, severity}]}]
            仅返回有预警的菜品。
        """
        member_allergens = set(await self._get_member_allergens(member_id))
        if not member_allergens:
            return []

        results: list[dict[str, Any]] = []
        for dish_id in dish_ids:
            dish_name = dish_names.get(dish_id, dish_id)
            alerts = await self.check_dish_for_member(
                dish_id=dish_id,
                dish_name=dish_name,
                member_id=member_id,
            )
            if alerts:
                results.append(
                    {
                        "dish_id": dish_id,
                        "dish_name": dish_name,
                        "alerts": [
                            {
                                "allergen_code": a.allergen_code,
                                "allergen_label": a.allergen_label,
                                "severity": a.severity,
                            }
                            for a in alerts
                        ],
                    }
                )
        return results

    @staticmethod
    def get_allergen_summary() -> dict[str, Any]:
        """返回所有支持的过敏原代码与中文标签。前端选择器使用。"""
        return {
            "items": [
                {
                    "allergen_code": code,
                    "allergen_label": label,
                    "severity_hint": "warning" if code in PREFERENCE_ALLERGENS else "danger",
                }
                for code, label in ALLERGEN_CATALOG.items()
            ],
            "total": len(ALLERGEN_CATALOG),
        }
