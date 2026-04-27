"""Forge 收入服务 — 流水记录、分润计算、提现管理

职责：
  1. record_revenue()        — 记录交易流水 + 分润计算
  2. get_developer_revenue()  — 开发者收入汇总
  3. get_app_revenue()        — 单应用收入明细
  4. request_payout()         — 申请提现
  5. get_payout_history()     — 提现历史
"""

from __future__ import annotations

from uuid import uuid4

import structlog
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import PRICING_MODELS

logger = structlog.get_logger(__name__)


class ForgeRevenueService:
    """开发者收入分润与提现管理"""

    async def record_revenue(
        self,
        db: AsyncSession,
        *,
        app_id: str,
        payer_tenant_id: str,
        amount_fen: int,
    ) -> dict:
        """记录一笔收入流水，自动计算平台抽成。"""
        # 查应用定价模型
        app_result = await db.execute(
            text("""
                SELECT app_id, app_name, pricing_model, developer_id
                FROM forge_apps
                WHERE app_id = :app_id
            """),
            {"app_id": app_id},
        )
        app_row = app_result.mappings().first()
        if not app_row:
            raise HTTPException(status_code=404, detail="应用不存在")

        pricing_model = app_row["pricing_model"]
        model_cfg = PRICING_MODELS.get(pricing_model, PRICING_MODELS["free"])
        fee_rate = model_cfg["platform_fee_rate"]

        platform_fee_fen = int(amount_fen * fee_rate)
        developer_payout_fen = amount_fen - platform_fee_fen

        # 插入流水
        result = await db.execute(
            text("""
                INSERT INTO forge_revenue_entries
                    (app_id, payer_tenant_id, amount_fen, platform_fee_fen,
                     developer_payout_fen, fee_rate, pricing_model)
                VALUES
                    (:app_id, :payer_tenant_id, :amount_fen, :platform_fee_fen,
                     :developer_payout_fen, :fee_rate, :pricing_model)
                RETURNING id, app_id, amount_fen, platform_fee_fen,
                          developer_payout_fen, fee_rate, pricing_model, created_at
            """),
            {
                "app_id": app_id,
                "payer_tenant_id": payer_tenant_id,
                "amount_fen": amount_fen,
                "platform_fee_fen": platform_fee_fen,
                "developer_payout_fen": developer_payout_fen,
                "fee_rate": fee_rate,
                "pricing_model": pricing_model,
            },
        )
        entry = dict(result.mappings().one())

        # 累加应用总收入
        await db.execute(
            text("""
                UPDATE forge_apps
                SET revenue_total_fen = revenue_total_fen + :amount_fen
                WHERE app_id = :app_id
            """),
            {"amount_fen": amount_fen, "app_id": app_id},
        )
        await db.commit()

        logger.info(
            "revenue_recorded",
            app_id=app_id,
            amount_fen=amount_fen,
            platform_fee_fen=platform_fee_fen,
        )
        return entry

    async def get_developer_revenue(
        self,
        db: AsyncSession,
        developer_id: str,
        *,
        period: str = "month",
    ) -> dict:
        """汇总开发者名下所有应用的收入。"""
        result = await db.execute(
            text("""
                SELECT
                    a.app_id,
                    a.app_name,
                    a.pricing_model,
                    COALESCE(SUM(r.amount_fen), 0)          AS app_revenue_fen,
                    COALESCE(SUM(r.platform_fee_fen), 0)    AS app_fee_fen,
                    COALESCE(SUM(r.developer_payout_fen), 0) AS app_payout_fen,
                    COUNT(r.id)                              AS transaction_count
                FROM forge_apps a
                LEFT JOIN forge_revenue_entries r ON r.app_id = a.app_id
                WHERE a.developer_id = :developer_id
                GROUP BY a.app_id, a.app_name, a.pricing_model
                ORDER BY app_revenue_fen DESC
            """),
            {"developer_id": developer_id},
        )
        app_breakdown = [dict(r) for r in result.mappings().all()]

        total_revenue_fen = sum(a["app_revenue_fen"] for a in app_breakdown)
        platform_fee_fen = sum(a["app_fee_fen"] for a in app_breakdown)
        developer_payout_fen = sum(a["app_payout_fen"] for a in app_breakdown)
        platform_fee_rate = round(platform_fee_fen / total_revenue_fen, 4) if total_revenue_fen > 0 else 0.0

        return {
            "developer_id": developer_id,
            "period": period,
            "total_revenue_fen": total_revenue_fen,
            "platform_fee_fen": platform_fee_fen,
            "developer_payout_fen": developer_payout_fen,
            "platform_fee_rate": platform_fee_rate,
            "app_breakdown": app_breakdown,
        }

    async def get_app_revenue(
        self,
        db: AsyncSession,
        app_id: str,
        *,
        period: str = "month",
    ) -> dict:
        """单应用收入汇总。"""
        result = await db.execute(
            text("""
                SELECT
                    a.app_name,
                    a.pricing_model,
                    a.install_count,
                    COALESCE(SUM(r.amount_fen), 0)           AS total_revenue_fen,
                    COALESCE(SUM(r.platform_fee_fen), 0)     AS platform_fee_fen,
                    COALESCE(SUM(r.developer_payout_fen), 0) AS developer_payout_fen,
                    COUNT(r.id)                               AS transaction_count
                FROM forge_apps a
                LEFT JOIN forge_revenue_entries r ON r.app_id = a.app_id
                WHERE a.app_id = :app_id
                GROUP BY a.app_name, a.pricing_model, a.install_count
            """),
            {"app_id": app_id},
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="应用不存在")

        return {
            "app_id": app_id,
            "period": period,
            **dict(row),
        }

    async def request_payout(
        self,
        db: AsyncSession,
        *,
        developer_id: str,
        amount_fen: int,
        bank_account: str,
    ) -> dict:
        """申请提现，校验可用余额。"""
        # 可用余额 = 累计分润 - 已完成提现
        balance_result = await db.execute(
            text("""
                SELECT
                    COALESCE(
                        (SELECT SUM(r.developer_payout_fen)
                         FROM forge_revenue_entries r
                         JOIN forge_apps a ON a.app_id = r.app_id
                         WHERE a.developer_id = :developer_id), 0
                    ) -
                    COALESCE(
                        (SELECT SUM(p.amount_fen)
                         FROM forge_payouts p
                         WHERE p.developer_id = :developer_id
                           AND p.status IN ('pending', 'processing', 'completed')), 0
                    ) AS available_balance_fen
            """),
            {"developer_id": developer_id},
        )
        available = int(balance_result.scalar_one())

        if amount_fen > available:
            raise HTTPException(
                status_code=400,
                detail=f"余额不足：可提现 {available} 分，申请 {amount_fen} 分",
            )

        payout_id = f"pay_{uuid4().hex[:12]}"

        result = await db.execute(
            text("""
                INSERT INTO forge_payouts
                    (payout_id, developer_id, amount_fen, bank_account,
                     status, requested_at)
                VALUES
                    (:payout_id, :developer_id, :amount_fen, :bank_account,
                     'pending', NOW())
                RETURNING payout_id, developer_id, amount_fen,
                          bank_account, status, requested_at
            """),
            {
                "payout_id": payout_id,
                "developer_id": developer_id,
                "amount_fen": amount_fen,
                "bank_account": bank_account,
            },
        )
        row = dict(result.mappings().one())
        await db.commit()

        logger.info(
            "payout_requested",
            payout_id=payout_id,
            developer_id=developer_id,
            amount_fen=amount_fen,
        )
        return row

    async def get_payout_history(self, db: AsyncSession, developer_id: str) -> list[dict]:
        """查询开发者提现历史。"""
        result = await db.execute(
            text("""
                SELECT payout_id, amount_fen, bank_account, status,
                       requested_at, completed_at, failure_reason
                FROM forge_payouts
                WHERE developer_id = :developer_id
                ORDER BY requested_at DESC
            """),
            {"developer_id": developer_id},
        )
        return [dict(r) for r in result.mappings().all()]
