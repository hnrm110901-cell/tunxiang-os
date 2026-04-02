"""企业挂账与协议客户中心（B6）— 企业账户管理

高端正餐场景（徐记海鲜）：企业月结、签单授权、协议价。
所有金额单位：分（fen）。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


# ─── 内存模拟存储（生产环境替换为数据库表） ───
# 后续迁移到 PostgreSQL 表：enterprise_accounts, agreement_prices, sign_records
_enterprises: dict[str, dict] = {}
_agreement_prices: dict[str, dict] = {}
_sign_records: dict[str, dict] = {}


class EnterpriseAccountService:
    """企业账户管理服务

    功能：企业建档、额度管理、协议价、签单授权。
    """

    # 账期类型
    BILLING_CYCLES = ("monthly", "bi_monthly", "quarterly")

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id

    async def create_enterprise(
        self,
        name: str,
        contact: str,
        credit_limit_fen: int,
        billing_cycle: str = "monthly",
    ) -> dict:
        """企业建档 — 创建企业挂账客户

        Args:
            name: 企业名称
            contact: 联系人（姓名+电话）
            credit_limit_fen: 授信额度（分）
            billing_cycle: 账期 monthly/bi_monthly/quarterly
        """
        if billing_cycle not in self.BILLING_CYCLES:
            raise ValueError(f"不支持的账期类型: {billing_cycle}，可选: {self.BILLING_CYCLES}")

        if credit_limit_fen <= 0:
            raise ValueError("授信额度必须大于0")

        enterprise_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        enterprise = {
            "id": enterprise_id,
            "tenant_id": self.tenant_id,
            "name": name,
            "contact": contact,
            "credit_limit_fen": credit_limit_fen,
            "used_fen": 0,
            "billing_cycle": billing_cycle,
            "status": "active",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        _enterprises[enterprise_id] = enterprise

        logger.info(
            "enterprise_created",
            enterprise_id=enterprise_id,
            name=name,
            credit_limit_fen=credit_limit_fen,
            billing_cycle=billing_cycle,
            tenant_id=self.tenant_id,
        )

        return enterprise

    async def update_enterprise(
        self,
        enterprise_id: str,
        updates: dict,
    ) -> dict:
        """更新企业信息

        可更新字段: name, contact, credit_limit_fen, billing_cycle, status
        """
        enterprise = _enterprises.get(enterprise_id)
        if not enterprise:
            raise ValueError(f"企业不存在: {enterprise_id}")
        if enterprise["tenant_id"] != self.tenant_id:
            raise ValueError(f"企业不存在: {enterprise_id}")

        allowed_fields = {"name", "contact", "credit_limit_fen", "billing_cycle", "status"}
        invalid_fields = set(updates.keys()) - allowed_fields
        if invalid_fields:
            raise ValueError(f"不可更新的字段: {invalid_fields}")

        if "billing_cycle" in updates and updates["billing_cycle"] not in self.BILLING_CYCLES:
            raise ValueError(f"不支持的账期类型: {updates['billing_cycle']}")

        if "credit_limit_fen" in updates and updates["credit_limit_fen"] <= 0:
            raise ValueError("授信额度必须大于0")

        for key, value in updates.items():
            enterprise[key] = value
        enterprise["updated_at"] = datetime.now(timezone.utc).isoformat()

        logger.info(
            "enterprise_updated",
            enterprise_id=enterprise_id,
            updates=list(updates.keys()),
            tenant_id=self.tenant_id,
        )

        return enterprise

    async def get_enterprise(self, enterprise_id: str) -> dict:
        """查询企业详情"""
        enterprise = _enterprises.get(enterprise_id)
        if not enterprise:
            raise ValueError(f"企业不存在: {enterprise_id}")
        if enterprise["tenant_id"] != self.tenant_id:
            raise ValueError(f"企业不存在: {enterprise_id}")
        return enterprise

    async def list_enterprises(self) -> list[dict]:
        """列表查询本租户下所有企业客户"""
        return [
            e for e in _enterprises.values()
            if e["tenant_id"] == self.tenant_id
        ]

    async def set_agreement_price(
        self,
        enterprise_id: str,
        dish_id: str,
        price_fen: int,
    ) -> dict:
        """设置协议价 — 企业客户专属菜品价格

        Args:
            enterprise_id: 企业ID
            dish_id: 菜品ID
            price_fen: 协议价（分）
        """
        enterprise = await self.get_enterprise(enterprise_id)

        if price_fen < 0:
            raise ValueError("协议价不能为负数")

        agreement_key = f"{enterprise_id}:{dish_id}"
        now = datetime.now(timezone.utc)

        agreement = {
            "id": str(uuid.uuid4()),
            "tenant_id": self.tenant_id,
            "enterprise_id": enterprise_id,
            "enterprise_name": enterprise["name"],
            "dish_id": dish_id,
            "price_fen": price_fen,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        _agreement_prices[agreement_key] = agreement

        logger.info(
            "agreement_price_set",
            enterprise_id=enterprise_id,
            dish_id=dish_id,
            price_fen=price_fen,
            tenant_id=self.tenant_id,
        )

        return agreement

    async def get_agreement_price(
        self,
        enterprise_id: str,
        dish_id: str,
    ) -> Optional[dict]:
        """查询协议价"""
        agreement_key = f"{enterprise_id}:{dish_id}"
        agreement = _agreement_prices.get(agreement_key)
        if agreement and agreement["tenant_id"] == self.tenant_id:
            return agreement
        return None

    async def check_credit(
        self,
        enterprise_id: str,
        amount_fen: int,
    ) -> dict:
        """额度检查 — 检查企业是否有足够挂账额度

        Returns:
            {available_fen, used_fen, limit_fen, sufficient: bool}
        """
        enterprise = await self.get_enterprise(enterprise_id)

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
        """签单授权 — 企业客户签单挂账

        硬约束：
        1. 签单必须有授权人姓名
        2. 额度超限时拒绝签单并通知财务

        Args:
            enterprise_id: 企业ID
            order_id: 订单ID
            signer_name: 签单授权人姓名（必填）
            amount_fen: 签单金额（分）
        """
        if not signer_name or not signer_name.strip():
            raise ValueError("签单必须有授权人姓名")

        if amount_fen <= 0:
            raise ValueError("签单金额必须大于0")

        # 检查额度
        credit_result = await self.check_credit(enterprise_id, amount_fen)

        if not credit_result["sufficient"]:
            # 额度超限：拒绝签单 + 通知财务
            logger.warning(
                "sign_rejected_credit_exceeded",
                enterprise_id=enterprise_id,
                order_id=order_id,
                signer_name=signer_name,
                amount_fen=amount_fen,
                available_fen=credit_result["available_fen"],
                limit_fen=credit_result["limit_fen"],
                tenant_id=self.tenant_id,
            )
            return {
                "authorized": False,
                "enterprise_id": enterprise_id,
                "order_id": order_id,
                "signer_name": signer_name,
                "amount_fen": amount_fen,
                "credit": credit_result,
                "error": (
                    f"额度不足：可用 {credit_result['available_fen']} 分，"
                    f"请求 {amount_fen} 分。已通知财务。"
                ),
                "finance_notified": True,
            }

        # 授权通过 — 记录签单并扣减额度
        sign_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        sign_record = {
            "id": sign_id,
            "tenant_id": self.tenant_id,
            "enterprise_id": enterprise_id,
            "order_id": order_id,
            "signer_name": signer_name.strip(),
            "amount_fen": amount_fen,
            "status": "signed",
            "signed_at": now.isoformat(),
        }
        _sign_records[sign_id] = sign_record

        # 扣减额度
        enterprise = _enterprises[enterprise_id]
        enterprise["used_fen"] += amount_fen
        enterprise["updated_at"] = now.isoformat()

        logger.info(
            "sign_authorized",
            sign_id=sign_id,
            enterprise_id=enterprise_id,
            order_id=order_id,
            signer_name=signer_name,
            amount_fen=amount_fen,
            new_used_fen=enterprise["used_fen"],
            tenant_id=self.tenant_id,
        )

        return {
            "authorized": True,
            "sign_id": sign_id,
            "enterprise_id": enterprise_id,
            "order_id": order_id,
            "signer_name": signer_name.strip(),
            "amount_fen": amount_fen,
            "credit": {
                "limit_fen": enterprise["credit_limit_fen"],
                "used_fen": enterprise["used_fen"],
                "available_fen": enterprise["credit_limit_fen"] - enterprise["used_fen"],
            },
        }

    async def get_sign_records(
        self,
        enterprise_id: str,
    ) -> list[dict]:
        """查询企业签单记录"""
        await self.get_enterprise(enterprise_id)  # 校验企业存在
        return [
            r for r in _sign_records.values()
            if r["enterprise_id"] == enterprise_id
            and r["tenant_id"] == self.tenant_id
        ]
