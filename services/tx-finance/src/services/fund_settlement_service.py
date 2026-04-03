"""资金分账引擎服务

核心职责：
- 分账规则 CRUD（按门店配置平台费/品牌费/加盟商分成比例）
- 单笔订单分账计算（根据规则拆分金额到各方）
- 批量分账（按日期范围处理多笔订单）
- 结算批次生成与确认（汇总分账流水，生成结算单）
"""

from __future__ import annotations

import structlog
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# 合法的分账规则类型
VALID_RULE_TYPES = {"platform_fee", "brand_royalty", "franchise_share"}

# 合法的结算批次状态
VALID_BATCH_STATUSES = {"draft", "confirmed", "paid"}


class FundSettlementService:
    """资金分账引擎

    所有方法均为 async，通过 AsyncSession 操作数据库，
    所有查询均携带 tenant_id 以保证 RLS 隔离。
    """

    # ─── 分账规则 ──────────────────────────────────────────────────────

    async def create_split_rule(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID,
        rule_type: str,
        rate_permil: int,
        fixed_fee_fen: int,
        effective_from: date,
        effective_to: date | None = None,
    ) -> dict[str, Any]:
        """创建分账规则

        Args:
            rule_type: platform_fee / brand_royalty / franchise_share
            rate_permil: 费率千分比（50 = 5.0%）
            fixed_fee_fen: 每笔固定费用（分）
            effective_from: 生效起始日期
            effective_to: 生效截止日期（None表示长期有效）

        Returns:
            新建规则的完整数据
        """
        if rule_type not in VALID_RULE_TYPES:
            raise ValueError(f"rule_type 必须是: {', '.join(VALID_RULE_TYPES)}")
        if rate_permil < 0 or rate_permil > 1000:
            raise ValueError("rate_permil 必须在 0-1000 之间")
        if fixed_fee_fen < 0:
            raise ValueError("fixed_fee_fen 不能为负数")

        result = await db.execute(
            text("""
                INSERT INTO split_rules (
                    tenant_id, store_id, rule_type, rate_permil, fixed_fee_fen,
                    effective_from, effective_to, is_active
                ) VALUES (
                    :tenant_id::UUID, :store_id::UUID, :rule_type, :rate_permil,
                    :fixed_fee_fen, :effective_from, :effective_to, TRUE
                )
                RETURNING id, tenant_id, store_id, rule_type, rate_permil,
                          fixed_fee_fen, effective_from, effective_to,
                          is_active, created_at
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "rule_type": rule_type,
                "rate_permil": rate_permil,
                "fixed_fee_fen": fixed_fee_fen,
                "effective_from": effective_from,
                "effective_to": effective_to,
            },
        )
        row = result.mappings().first()
        await db.commit()

        logger.info(
            "split_rule.created",
            rule_id=str(row["id"]),
            store_id=str(store_id),
            rule_type=rule_type,
            rate_permil=rate_permil,
        )
        return _serialize_row(row)

    async def list_split_rules(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID | None = None,
        rule_type: str | None = None,
        active_only: bool = True,
    ) -> list[dict[str, Any]]:
        """查询分账规则列表

        Args:
            store_id: 可选，按门店筛选
            rule_type: 可选，按规则类型筛选
            active_only: 是否只返回启用的规则
        """
        where_clauses = ["tenant_id = :tenant_id::UUID", "is_deleted = FALSE"]
        params: dict[str, Any] = {"tenant_id": str(tenant_id)}

        if store_id:
            where_clauses.append("store_id = :store_id::UUID")
            params["store_id"] = str(store_id)

        if rule_type:
            if rule_type not in VALID_RULE_TYPES:
                raise ValueError(f"rule_type 必须是: {', '.join(VALID_RULE_TYPES)}")
            where_clauses.append("rule_type = :rule_type")
            params["rule_type"] = rule_type

        if active_only:
            where_clauses.append("is_active = TRUE")

        where_sql = " AND ".join(where_clauses)

        result = await db.execute(
            text(f"""
                SELECT id, tenant_id, store_id, rule_type, rate_permil,
                       fixed_fee_fen, effective_from, effective_to,
                       is_active, created_at, updated_at
                FROM split_rules
                WHERE {where_sql}
                ORDER BY created_at DESC
            """),
            params,
        )
        rows = result.mappings().all()
        return [_serialize_row(r) for r in rows]

    # ─── 单笔分账 ──────────────────────────────────────────────────────

    async def split_order(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        order_id: UUID,
    ) -> dict[str, Any]:
        """对单笔订单执行分账计算

        流程：
        1. 查询订单金额和门店信息
        2. 加载该门店当前生效的分账规则
        3. 按规则拆分金额
        4. 写入 split_ledgers

        Returns:
            分账流水记录
        """
        # 1. 查询订单
        order_result = await db.execute(
            text("""
                SELECT id, store_id, actual_amount_fen, payment_id
                FROM orders
                WHERE id = :order_id::UUID
                  AND tenant_id = :tenant_id::UUID
                  AND is_deleted = FALSE
            """),
            {"order_id": str(order_id), "tenant_id": str(tenant_id)},
        )
        order_row = order_result.mappings().first()
        if not order_row:
            raise ValueError(f"订单不存在: {order_id}")

        store_id = order_row["store_id"]
        total_amount_fen = order_row["actual_amount_fen"]
        payment_id = order_row.get("payment_id")

        # 2. 检查是否已分账
        existing = await db.execute(
            text("""
                SELECT id FROM split_ledgers
                WHERE order_id = :order_id::UUID
                  AND tenant_id = :tenant_id::UUID
                  AND is_deleted = FALSE
            """),
            {"order_id": str(order_id), "tenant_id": str(tenant_id)},
        )
        if existing.mappings().first():
            raise ValueError(f"订单已分账: {order_id}")

        # 3. 加载分账规则
        today = date.today()
        rules_result = await db.execute(
            text("""
                SELECT rule_type, rate_permil, fixed_fee_fen
                FROM split_rules
                WHERE store_id = :store_id::UUID
                  AND tenant_id = :tenant_id::UUID
                  AND is_active = TRUE
                  AND is_deleted = FALSE
                  AND effective_from <= :today
                  AND (effective_to IS NULL OR effective_to >= :today)
            """),
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "today": today,
            },
        )
        rules = rules_result.mappings().all()

        # 4. 计算分账
        split_amounts = _calculate_split(total_amount_fen, rules)

        # 5. 写入流水
        ledger_result = await db.execute(
            text("""
                INSERT INTO split_ledgers (
                    tenant_id, order_id, payment_id, store_id,
                    total_amount_fen, platform_fee_fen, brand_royalty_fen,
                    franchise_share_fen, net_settlement_fen, status
                ) VALUES (
                    :tenant_id::UUID, :order_id::UUID, :payment_id,
                    :store_id::UUID, :total_amount_fen, :platform_fee_fen,
                    :brand_royalty_fen, :franchise_share_fen,
                    :net_settlement_fen, 'pending'
                )
                RETURNING id, tenant_id, order_id, payment_id, store_id,
                          total_amount_fen, platform_fee_fen, brand_royalty_fen,
                          franchise_share_fen, net_settlement_fen, status,
                          created_at
            """),
            {
                "tenant_id": str(tenant_id),
                "order_id": str(order_id),
                "payment_id": str(payment_id) if payment_id else None,
                "store_id": str(store_id),
                "total_amount_fen": total_amount_fen,
                "platform_fee_fen": split_amounts["platform_fee_fen"],
                "brand_royalty_fen": split_amounts["brand_royalty_fen"],
                "franchise_share_fen": split_amounts["franchise_share_fen"],
                "net_settlement_fen": split_amounts["net_settlement_fen"],
            },
        )
        ledger_row = ledger_result.mappings().first()
        await db.commit()

        logger.info(
            "order.split_completed",
            order_id=str(order_id),
            total_amount_fen=total_amount_fen,
            platform_fee_fen=split_amounts["platform_fee_fen"],
            brand_royalty_fen=split_amounts["brand_royalty_fen"],
        )
        return _serialize_row(ledger_row)

    # ─── 批量分账 ──────────────────────────────────────────────────────

    async def batch_split(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        """批量分账：对指定门店、日期范围内未分账的订单执行分账

        Returns:
            批量处理结果摘要
        """
        if start_date > end_date:
            raise ValueError("start_date 不能晚于 end_date")

        # 查询未分账的订单
        orders_result = await db.execute(
            text("""
                SELECT o.id, o.store_id, o.actual_amount_fen, o.payment_id
                FROM orders o
                WHERE o.tenant_id = :tenant_id::UUID
                  AND o.store_id = :store_id::UUID
                  AND o.is_deleted = FALSE
                  AND o.created_at::DATE BETWEEN :start_date AND :end_date
                  AND NOT EXISTS (
                      SELECT 1 FROM split_ledgers sl
                      WHERE sl.order_id = o.id
                        AND sl.tenant_id = :tenant_id::UUID
                        AND sl.is_deleted = FALSE
                  )
                ORDER BY o.created_at
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        orders = orders_result.mappings().all()

        if not orders:
            return {
                "processed": 0,
                "skipped": 0,
                "failed": 0,
                "total_amount_fen": 0,
            }

        # 加载分账规则（批量共用同一门店规则）
        today = date.today()
        rules_result = await db.execute(
            text("""
                SELECT rule_type, rate_permil, fixed_fee_fen
                FROM split_rules
                WHERE store_id = :store_id::UUID
                  AND tenant_id = :tenant_id::UUID
                  AND is_active = TRUE
                  AND is_deleted = FALSE
                  AND effective_from <= :today
                  AND (effective_to IS NULL OR effective_to >= :today)
            """),
            {
                "store_id": str(store_id),
                "tenant_id": str(tenant_id),
                "today": today,
            },
        )
        rules = rules_result.mappings().all()

        processed = 0
        failed = 0
        total_amount_fen = 0

        for order in orders:
            try:
                split_amounts = _calculate_split(order["actual_amount_fen"], rules)

                await db.execute(
                    text("""
                        INSERT INTO split_ledgers (
                            tenant_id, order_id, payment_id, store_id,
                            total_amount_fen, platform_fee_fen, brand_royalty_fen,
                            franchise_share_fen, net_settlement_fen, status
                        ) VALUES (
                            :tenant_id::UUID, :order_id::UUID, :payment_id,
                            :store_id::UUID, :total_amount_fen, :platform_fee_fen,
                            :brand_royalty_fen, :franchise_share_fen,
                            :net_settlement_fen, 'pending'
                        )
                    """),
                    {
                        "tenant_id": str(tenant_id),
                        "order_id": str(order["id"]),
                        "payment_id": str(order["payment_id"]) if order.get("payment_id") else None,
                        "store_id": str(store_id),
                        "total_amount_fen": order["actual_amount_fen"],
                        "platform_fee_fen": split_amounts["platform_fee_fen"],
                        "brand_royalty_fen": split_amounts["brand_royalty_fen"],
                        "franchise_share_fen": split_amounts["franchise_share_fen"],
                        "net_settlement_fen": split_amounts["net_settlement_fen"],
                    },
                )
                processed += 1
                total_amount_fen += order["actual_amount_fen"]
            except (ValueError, KeyError) as exc:
                logger.warning(
                    "batch_split.order_failed",
                    order_id=str(order["id"]),
                    error=str(exc),
                )
                failed += 1

        await db.commit()

        logger.info(
            "batch_split.completed",
            store_id=str(store_id),
            processed=processed,
            failed=failed,
            total_amount_fen=total_amount_fen,
        )
        return {
            "processed": processed,
            "skipped": 0,
            "failed": failed,
            "total_amount_fen": total_amount_fen,
        }

    # ─── 结算批次 ──────────────────────────────────────────────────────

    async def create_settlement_batch(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID,
        period_start: date,
        period_end: date,
    ) -> dict[str, Any]:
        """生成结算批次

        汇总指定门店、周期内的分账流水，生成结算批次。
        同时将相关流水关联到此批次。
        """
        if period_start > period_end:
            raise ValueError("period_start 不能晚于 period_end")

        # 汇总待结算的分账流水
        summary_result = await db.execute(
            text("""
                SELECT COUNT(*) AS total_orders,
                       COALESCE(SUM(total_amount_fen), 0) AS total_amount_fen,
                       COALESCE(SUM(platform_fee_fen + brand_royalty_fen), 0) AS total_split_fen
                FROM split_ledgers
                WHERE tenant_id = :tenant_id::UUID
                  AND store_id = :store_id::UUID
                  AND status = 'pending'
                  AND batch_id IS NULL
                  AND is_deleted = FALSE
                  AND created_at::DATE BETWEEN :period_start AND :period_end
            """),
            {
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "period_start": period_start,
                "period_end": period_end,
            },
        )
        summary = summary_result.mappings().first()

        if not summary or summary["total_orders"] == 0:
            raise ValueError("该周期内没有待结算的分账流水")

        # 生成批次编号
        batch_no = f"SB{period_start.strftime('%Y%m%d')}{uuid4().hex[:6].upper()}"

        # 创建批次
        batch_result = await db.execute(
            text("""
                INSERT INTO settlement_batches (
                    tenant_id, batch_no, period_start, period_end, store_id,
                    total_orders, total_amount_fen, total_split_fen, status
                ) VALUES (
                    :tenant_id::UUID, :batch_no, :period_start, :period_end,
                    :store_id::UUID, :total_orders, :total_amount_fen,
                    :total_split_fen, 'draft'
                )
                RETURNING id, tenant_id, batch_no, period_start, period_end,
                          store_id, total_orders, total_amount_fen,
                          total_split_fen, status, created_at
            """),
            {
                "tenant_id": str(tenant_id),
                "batch_no": batch_no,
                "period_start": period_start,
                "period_end": period_end,
                "store_id": str(store_id),
                "total_orders": summary["total_orders"],
                "total_amount_fen": summary["total_amount_fen"],
                "total_split_fen": summary["total_split_fen"],
            },
        )
        batch_row = batch_result.mappings().first()
        batch_id = batch_row["id"]

        # 关联流水到批次
        await db.execute(
            text("""
                UPDATE split_ledgers
                SET batch_id = :batch_id::UUID, updated_at = NOW()
                WHERE tenant_id = :tenant_id::UUID
                  AND store_id = :store_id::UUID
                  AND status = 'pending'
                  AND batch_id IS NULL
                  AND is_deleted = FALSE
                  AND created_at::DATE BETWEEN :period_start AND :period_end
            """),
            {
                "batch_id": str(batch_id),
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "period_start": period_start,
                "period_end": period_end,
            },
        )
        await db.commit()

        logger.info(
            "settlement_batch.created",
            batch_id=str(batch_id),
            batch_no=batch_no,
            total_orders=summary["total_orders"],
            total_amount_fen=summary["total_amount_fen"],
        )
        return _serialize_row(batch_row)

    async def list_settlement_batches(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict[str, Any]:
        """结算批次列表"""
        where_clauses = ["tenant_id = :tenant_id::UUID", "is_deleted = FALSE"]
        params: dict[str, Any] = {"tenant_id": str(tenant_id)}

        if store_id:
            where_clauses.append("store_id = :store_id::UUID")
            params["store_id"] = str(store_id)

        if status:
            if status not in VALID_BATCH_STATUSES:
                raise ValueError(f"status 必须是: {', '.join(VALID_BATCH_STATUSES)}")
            where_clauses.append("status = :status")
            params["status"] = status

        where_sql = " AND ".join(where_clauses)
        offset = (page - 1) * size
        params["limit"] = size
        params["offset"] = offset

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM settlement_batches WHERE {where_sql}"),
            params,
        )
        total = count_result.scalar()

        items_result = await db.execute(
            text(f"""
                SELECT id, tenant_id, batch_no, period_start, period_end,
                       store_id, total_orders, total_amount_fen,
                       total_split_fen, status, created_at, updated_at
                FROM settlement_batches
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [_serialize_row(r) for r in items_result.mappings().all()]
        return {"items": items, "total": total, "page": page, "size": size}

    async def get_settlement_summary(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        batch_id: UUID,
    ) -> dict[str, Any]:
        """结算批次汇总详情

        返回批次信息 + 分账流水按类型汇总
        """
        # 批次基本信息
        batch_result = await db.execute(
            text("""
                SELECT id, tenant_id, batch_no, period_start, period_end,
                       store_id, total_orders, total_amount_fen,
                       total_split_fen, status, created_at
                FROM settlement_batches
                WHERE id = :batch_id::UUID
                  AND tenant_id = :tenant_id::UUID
                  AND is_deleted = FALSE
            """),
            {"batch_id": str(batch_id), "tenant_id": str(tenant_id)},
        )
        batch_row = batch_result.mappings().first()
        if not batch_row:
            raise ValueError(f"结算批次不存在: {batch_id}")

        # 汇总分账明细
        detail_result = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS ledger_count,
                    COALESCE(SUM(total_amount_fen), 0) AS sum_total_fen,
                    COALESCE(SUM(platform_fee_fen), 0) AS sum_platform_fee_fen,
                    COALESCE(SUM(brand_royalty_fen), 0) AS sum_brand_royalty_fen,
                    COALESCE(SUM(franchise_share_fen), 0) AS sum_franchise_share_fen,
                    COALESCE(SUM(net_settlement_fen), 0) AS sum_net_settlement_fen
                FROM split_ledgers
                WHERE batch_id = :batch_id::UUID
                  AND tenant_id = :tenant_id::UUID
                  AND is_deleted = FALSE
            """),
            {"batch_id": str(batch_id), "tenant_id": str(tenant_id)},
        )
        detail = detail_result.mappings().first()

        batch_data = _serialize_row(batch_row)
        batch_data["summary"] = {
            "ledger_count": detail["ledger_count"] if detail else 0,
            "sum_total_fen": detail["sum_total_fen"] if detail else 0,
            "sum_platform_fee_fen": detail["sum_platform_fee_fen"] if detail else 0,
            "sum_brand_royalty_fen": detail["sum_brand_royalty_fen"] if detail else 0,
            "sum_franchise_share_fen": detail["sum_franchise_share_fen"] if detail else 0,
            "sum_net_settlement_fen": detail["sum_net_settlement_fen"] if detail else 0,
        }
        return batch_data

    async def confirm_settlement(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        batch_id: UUID,
    ) -> dict[str, Any]:
        """确认结算批次

        将批次状态从 draft 更新为 confirmed，
        同时将关联的分账流水状态更新为 settled。
        """
        # 更新批次状态
        batch_result = await db.execute(
            text("""
                UPDATE settlement_batches
                SET status = 'confirmed', updated_at = NOW()
                WHERE id = :batch_id::UUID
                  AND tenant_id = :tenant_id::UUID
                  AND status = 'draft'
                  AND is_deleted = FALSE
                RETURNING id, batch_no, status
            """),
            {"batch_id": str(batch_id), "tenant_id": str(tenant_id)},
        )
        batch_row = batch_result.mappings().first()
        if not batch_row:
            raise ValueError(f"结算批次不存在或状态不是 draft: {batch_id}")

        # 更新关联流水状态
        await db.execute(
            text("""
                UPDATE split_ledgers
                SET status = 'settled', settled_at = NOW(), updated_at = NOW()
                WHERE batch_id = :batch_id::UUID
                  AND tenant_id = :tenant_id::UUID
                  AND status = 'pending'
                  AND is_deleted = FALSE
            """),
            {"batch_id": str(batch_id), "tenant_id": str(tenant_id)},
        )
        await db.commit()

        logger.info(
            "settlement_batch.confirmed",
            batch_id=str(batch_id),
            batch_no=batch_row["batch_no"],
        )
        return {
            "batch_id": str(batch_row["id"]),
            "batch_no": batch_row["batch_no"],
            "status": "confirmed",
        }


# ─── 内部工具函数 ──────────────────────────────────────────────────────

def _calculate_split(
    total_amount_fen: int,
    rules: list[Any],
) -> dict[str, int]:
    """根据分账规则计算各方金额

    计算逻辑：
    1. 每条规则按 rate_permil 计算比例金额 + fixed_fee_fen 固定费用
    2. 各方金额取整（向下取整，余额归属加盟商/门店）
    3. net_settlement = total - platform_fee - brand_royalty
    """
    platform_fee_fen = 0
    brand_royalty_fen = 0
    franchise_share_fen = 0

    for rule in rules:
        rule_type = rule["rule_type"]
        rate_permil = rule["rate_permil"]
        fixed_fee_fen = rule["fixed_fee_fen"]

        # 比例部分（千分比计算，向下取整）
        proportional = (total_amount_fen * rate_permil) // 1000
        amount = proportional + fixed_fee_fen

        if rule_type == "platform_fee":
            platform_fee_fen += amount
        elif rule_type == "brand_royalty":
            brand_royalty_fen += amount
        elif rule_type == "franchise_share":
            franchise_share_fen += amount

    # 净结算 = 总额 - 平台费 - 品牌费
    net_settlement_fen = total_amount_fen - platform_fee_fen - brand_royalty_fen

    return {
        "platform_fee_fen": platform_fee_fen,
        "brand_royalty_fen": brand_royalty_fen,
        "franchise_share_fen": franchise_share_fen,
        "net_settlement_fen": net_settlement_fen,
    }


def _serialize_row(row: Any) -> dict[str, Any]:
    """将数据库行转换为可序列化的 dict"""
    import uuid as _uuid

    data = dict(row)
    for k, v in data.items():
        if isinstance(v, _uuid.UUID):
            data[k] = str(v)
        elif hasattr(v, "isoformat"):
            data[k] = v.isoformat()
    return data
