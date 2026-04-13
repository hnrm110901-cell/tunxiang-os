"""企业挂账与协议客户中心（B6）— 企业账户管理

高端正餐场景（徐记海鲜）：企业月结、签单授权、协议价。
所有金额单位：分（fen）。

v251 迁移后全部操作持久化到 DB（enterprise_accounts / enterprise_sign_records /
enterprise_agreement_prices），内存存储已完全移除。
"""
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


class EnterpriseAccountService:
    """企业账户管理服务

    功能：企业建档、额度管理、协议价、签单授权。
    所有方法通过 self.db（AsyncSession）直接操作 DB。
    """

    BILLING_CYCLES = ("monthly", "bi_monthly", "quarterly")

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id

    # ── 私有辅助 ────────────────────────────────────────────────────────────

    async def _get_enterprise_row(self, enterprise_id: str) -> dict:
        """按 ID 查询企业行，不存在或非本租户时抛 ValueError。"""
        result = await self.db.execute(
            text("""
                SELECT id::text, tenant_id::text, name, contact,
                       credit_limit_fen, used_fen, billing_cycle, status,
                       created_at, updated_at
                FROM enterprise_accounts
                WHERE id = :eid::uuid
                  AND tenant_id = :tid::uuid
                  AND is_deleted = FALSE
            """),
            {"eid": enterprise_id, "tid": self.tenant_id},
        )
        row = result.mappings().fetchone()
        if row is None:
            raise ValueError(f"企业不存在: {enterprise_id}")
        return dict(row)

    # ── 企业 CRUD ────────────────────────────────────────────────────────────

    async def create_enterprise(
        self,
        name: str,
        contact: str,
        credit_limit_fen: int,
        billing_cycle: str = "monthly",
    ) -> dict:
        """企业建档 — 创建企业挂账客户"""
        if billing_cycle not in self.BILLING_CYCLES:
            raise ValueError(f"不支持的账期类型: {billing_cycle}，可选: {self.BILLING_CYCLES}")
        if credit_limit_fen <= 0:
            raise ValueError("授信额度必须大于0")

        try:
            result = await self.db.execute(
                text("""
                    INSERT INTO enterprise_accounts
                        (tenant_id, name, contact, credit_limit_fen, billing_cycle)
                    VALUES
                        (:tid::uuid, :name, :contact, :limit_fen, :cycle)
                    RETURNING id::text, tenant_id::text, name, contact,
                              credit_limit_fen, used_fen, billing_cycle, status,
                              created_at, updated_at
                """),
                {
                    "tid": self.tenant_id,
                    "name": name,
                    "contact": contact,
                    "limit_fen": credit_limit_fen,
                    "cycle": billing_cycle,
                },
            )
            row = dict(result.mappings().fetchone())
            await self.db.commit()
            logger.info(
                "enterprise_created",
                enterprise_id=row["id"],
                name=name,
                credit_limit_fen=credit_limit_fen,
                tenant_id=self.tenant_id,
            )
            return row
        except SQLAlchemyError as exc:
            await self.db.rollback()
            logger.error("enterprise_create_failed", error=str(exc), exc_info=True)
            raise ValueError(f"企业建档失败: {exc}") from exc

    async def update_enterprise(self, enterprise_id: str, updates: dict) -> dict:
        """更新企业信息（只更新有值字段）"""
        allowed_fields = {"name", "contact", "credit_limit_fen", "billing_cycle", "status"}
        invalid_fields = set(updates.keys()) - allowed_fields
        if invalid_fields:
            raise ValueError(f"不可更新的字段: {invalid_fields}")
        if "billing_cycle" in updates and updates["billing_cycle"] not in self.BILLING_CYCLES:
            raise ValueError(f"不支持的账期类型: {updates['billing_cycle']}")
        if "credit_limit_fen" in updates and updates["credit_limit_fen"] <= 0:
            raise ValueError("授信额度必须大于0")

        set_clauses = [f"{k} = :{k}" for k in updates]
        set_clauses.append("updated_at = NOW()")
        params = {**updates, "eid": enterprise_id, "tid": self.tenant_id}

        try:
            result = await self.db.execute(
                text(f"""
                    UPDATE enterprise_accounts
                    SET {', '.join(set_clauses)}
                    WHERE id = :eid::uuid
                      AND tenant_id = :tid::uuid
                      AND is_deleted = FALSE
                    RETURNING id::text, tenant_id::text, name, contact,
                              credit_limit_fen, used_fen, billing_cycle, status,
                              created_at, updated_at
                """),
                params,
            )
            row = result.mappings().fetchone()
            if row is None:
                raise ValueError(f"企业不存在: {enterprise_id}")
            await self.db.commit()
            logger.info(
                "enterprise_updated",
                enterprise_id=enterprise_id,
                updates=list(updates.keys()),
                tenant_id=self.tenant_id,
            )
            return dict(row)
        except SQLAlchemyError as exc:
            await self.db.rollback()
            logger.error("enterprise_update_failed", error=str(exc), exc_info=True)
            raise ValueError(f"企业更新失败: {exc}") from exc

    async def get_enterprise(self, enterprise_id: str) -> dict:
        """查询企业详情"""
        return await self._get_enterprise_row(enterprise_id)

    async def list_enterprises(self) -> list[dict]:
        """列表查询本租户下所有活跃企业客户"""
        result = await self.db.execute(
            text("""
                SELECT id::text, tenant_id::text, name, contact,
                       credit_limit_fen, used_fen, billing_cycle, status,
                       created_at, updated_at
                FROM enterprise_accounts
                WHERE tenant_id = :tid::uuid AND is_deleted = FALSE
                ORDER BY name
            """),
            {"tid": self.tenant_id},
        )
        return [dict(row) for row in result.mappings().all()]

    # ── 协议价 ───────────────────────────────────────────────────────────────

    async def set_agreement_price(
        self,
        enterprise_id: str,
        dish_id: str,
        price_fen: int,
    ) -> dict:
        """设置协议价 — 企业客户专属菜品价格（UPSERT）"""
        enterprise = await self._get_enterprise_row(enterprise_id)
        if price_fen < 0:
            raise ValueError("协议价不能为负数")

        try:
            result = await self.db.execute(
                text("""
                    INSERT INTO enterprise_agreement_prices
                        (tenant_id, enterprise_id, dish_id, price_fen)
                    VALUES
                        (:tid::uuid, :eid::uuid, :dish, :price)
                    ON CONFLICT (tenant_id, enterprise_id, dish_id)
                    DO UPDATE SET price_fen = EXCLUDED.price_fen, updated_at = NOW()
                    RETURNING id::text, tenant_id::text, enterprise_id::text,
                              dish_id, price_fen, created_at, updated_at
                """),
                {
                    "tid": self.tenant_id,
                    "eid": enterprise_id,
                    "dish": dish_id,
                    "price": price_fen,
                },
            )
            row = dict(result.mappings().fetchone())
            row["enterprise_name"] = enterprise["name"]
            await self.db.commit()
            logger.info(
                "agreement_price_set",
                enterprise_id=enterprise_id,
                dish_id=dish_id,
                price_fen=price_fen,
                tenant_id=self.tenant_id,
            )
            return row
        except SQLAlchemyError as exc:
            await self.db.rollback()
            logger.error("agreement_price_set_failed", error=str(exc), exc_info=True)
            raise ValueError(f"协议价设置失败: {exc}") from exc

    async def get_agreement_price(
        self,
        enterprise_id: str,
        dish_id: str,
    ) -> Optional[dict]:
        """查询协议价，不存在返回 None"""
        result = await self.db.execute(
            text("""
                SELECT id::text, tenant_id::text, enterprise_id::text,
                       dish_id, price_fen, created_at, updated_at
                FROM enterprise_agreement_prices
                WHERE tenant_id = :tid::uuid
                  AND enterprise_id = :eid::uuid
                  AND dish_id = :dish
            """),
            {"tid": self.tenant_id, "eid": enterprise_id, "dish": dish_id},
        )
        row = result.mappings().fetchone()
        return dict(row) if row else None

    # ── 额度 / 签单 ──────────────────────────────────────────────────────────

    async def check_credit(self, enterprise_id: str, amount_fen: int) -> dict:
        """额度检查 — 检查企业是否有足够挂账额度"""
        enterprise = await self._get_enterprise_row(enterprise_id)
        limit_fen = enterprise["credit_limit_fen"]
        used_fen = enterprise["used_fen"]
        available_fen = limit_fen - used_fen
        sufficient = available_fen >= amount_fen

        logger.info(
            "credit_checked",
            enterprise_id=enterprise_id,
            amount_fen=amount_fen,
            available_fen=available_fen,
            sufficient=sufficient,
            tenant_id=self.tenant_id,
        )
        return {
            "enterprise_id": enterprise_id,
            "limit_fen": limit_fen,
            "used_fen": used_fen,
            "available_fen": available_fen,
            "requested_fen": amount_fen,
            "sufficient": sufficient,
        }

    async def authorize_sign(
        self,
        enterprise_id: str,
        order_id: str,
        signer_name: str,
        amount_fen: int,
    ) -> dict:
        """签单授权 — 企业客户签单挂账（DB原子操作，消除并发竞态）

        硬约束：
        1. 签单必须有授权人姓名
        2. 额度超限时拒绝签单并通知财务
        """
        if not signer_name or not signer_name.strip():
            raise ValueError("签单必须有授权人姓名")
        if amount_fen <= 0:
            raise ValueError("签单金额必须大于0")

        # 幂等检查：同一订单不重复签单
        existing = await self.db.execute(
            text("""
                SELECT id FROM enterprise_sign_records
                WHERE tenant_id = :tid::uuid AND order_id = :oid::uuid
            """),
            {"tid": self.tenant_id, "oid": order_id},
        )
        if existing.fetchone():
            return {"authorized": True, "idempotent": True, "order_id": order_id}

        # 原子扣额度 + 写签单记录
        result = await self.db.execute(
            text("""
                UPDATE enterprise_accounts
                SET used_fen   = used_fen + :amount,
                    updated_at = NOW()
                WHERE id = :eid::uuid
                  AND tenant_id = :tid::uuid
                  AND status = 'active'
                  AND (credit_limit_fen - used_fen) >= :amount
                RETURNING id, credit_limit_fen, used_fen
            """),
            {"amount": amount_fen, "eid": enterprise_id, "tid": self.tenant_id},
        )
        row = result.fetchone()
        if row is None:
            check = await self.db.execute(
                text("""
                    SELECT credit_limit_fen, used_fen FROM enterprise_accounts
                    WHERE id = :eid::uuid AND tenant_id = :tid::uuid
                """),
                {"eid": enterprise_id, "tid": self.tenant_id},
            )
            acct = check.fetchone()
            if acct is None:
                raise ValueError(f"企业不存在: {enterprise_id}")
            available = acct.credit_limit_fen - acct.used_fen
            return {
                "authorized": False,
                "error": f"额度不足：可用 {available} 分，请求 {amount_fen} 分",
                "enterprise_id": enterprise_id,
                "order_id": order_id,
            }

        await self.db.execute(
            text("""
                INSERT INTO enterprise_sign_records
                    (id, tenant_id, enterprise_id, order_id, signer_name, amount_fen)
                VALUES
                    (gen_random_uuid(), :tid::uuid, :eid::uuid, :oid::uuid, :signer, :amount)
            """),
            {
                "tid": self.tenant_id, "eid": enterprise_id,
                "oid": order_id, "signer": signer_name, "amount": amount_fen,
            },
        )
        await self.db.commit()

        return {
            "authorized": True,
            "enterprise_id": enterprise_id,
            "order_id": order_id,
            "signer_name": signer_name,
            "amount_fen": amount_fen,
            "remaining_credit_fen": row.credit_limit_fen - row.used_fen,
        }

    async def get_sign_records(self, enterprise_id: str) -> list[dict]:
        """查询企业签单记录"""
        await self._get_enterprise_row(enterprise_id)  # 校验企业存在
        result = await self.db.execute(
            text("""
                SELECT id::text, tenant_id::text, enterprise_id::text,
                       order_id::text, signer_name, amount_fen, status,
                       settled_at, created_at, updated_at
                FROM enterprise_sign_records
                WHERE tenant_id = :tid::uuid AND enterprise_id = :eid::uuid
                ORDER BY created_at DESC
            """),
            {"tid": self.tenant_id, "eid": enterprise_id},
        )
        return [dict(row) for row in result.mappings().all()]
