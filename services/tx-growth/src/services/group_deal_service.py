"""拼团服务 — Group Deals

社交裂变 S4W14-15：
  拼团活动创建、参团、支付、完成、过期处理，
  以及拼团统计仪表盘。

核心流程：
  1. 发起者创建拼团（create_deal）→ 自动加入为首位参与者
  2. 其他用户通过分享链接参团（join_deal）
  3. 达到最低人数后自动标记为 filled
  4. 参与者逐一支付（record_payment）
  5. 全部支付完成后标记 completed（complete_deal）
  6. 定时任务过期未成团的活动（expire_stale_deals）

金额单位：分(fen)
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 内部异常
# ---------------------------------------------------------------------------


class GroupDealError(Exception):
    """拼团业务异常"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# GroupDealService
# ---------------------------------------------------------------------------


class GroupDealService:
    """拼团核心服务"""

    # ------------------------------------------------------------------
    # 创建拼团
    # ------------------------------------------------------------------

    async def create_deal(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        name: str,
        min_participants: int,
        original_price_fen: int,
        deal_price_fen: int,
        expires_at: datetime,
        initiator_customer_id: uuid.UUID,
        db: Any,
        *,
        dish_id: Optional[uuid.UUID] = None,
        description: Optional[str] = None,
        max_participants: int = 10,
    ) -> dict:
        """创建拼团活动并将发起者加入为首位参与者

        Args:
            tenant_id: 租户ID
            store_id: 门店ID
            name: 拼团名称
            min_participants: 最少参团人数 (>=2)
            original_price_fen: 原价(分)
            deal_price_fen: 拼团价(分)
            expires_at: 过期时间
            initiator_customer_id: 发起者客户ID
            db: AsyncSession
            dish_id: 关联菜品ID（可选）
            description: 拼团描述（可选）
            max_participants: 最大参团人数，默认10

        Returns:
            {deal_id, share_link_code, status, current_participants}

        Raises:
            GroupDealError: 参数校验失败
        """
        if min_participants < 2:
            raise GroupDealError("INVALID_MIN_PARTICIPANTS", "最少参团人数不能小于2")
        if deal_price_fen >= original_price_fen:
            raise GroupDealError("INVALID_PRICE", "拼团价必须低于原价")
        if max_participants < min_participants:
            raise GroupDealError("INVALID_MAX_PARTICIPANTS", "最大人数不能小于最少人数")

        deal_id = uuid.uuid4()
        share_link_code = uuid.uuid4().hex[:8]

        await db.execute(
            text("""
                INSERT INTO group_deals (
                    id, tenant_id, store_id, name, description, dish_id,
                    min_participants, max_participants, current_participants,
                    original_price_fen, deal_price_fen, status,
                    expires_at, initiator_customer_id, share_link_code
                ) VALUES (
                    :id, :tenant_id, :store_id, :name, :description, :dish_id,
                    :min_participants, :max_participants, 1,
                    :original_price_fen, :deal_price_fen, 'open',
                    :expires_at, :initiator_customer_id, :share_link_code
                )
            """),
            {
                "id": str(deal_id),
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "name": name,
                "description": description,
                "dish_id": str(dish_id) if dish_id else None,
                "min_participants": min_participants,
                "max_participants": max_participants,
                "original_price_fen": original_price_fen,
                "deal_price_fen": deal_price_fen,
                "expires_at": expires_at,
                "initiator_customer_id": str(initiator_customer_id),
                "share_link_code": share_link_code,
            },
        )

        # 发起者自动成为首位参与者
        participant_id = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO group_deal_participants (
                    id, tenant_id, deal_id, customer_id
                ) VALUES (:id, :tenant_id, :deal_id, :customer_id)
            """),
            {
                "id": str(participant_id),
                "tenant_id": str(tenant_id),
                "deal_id": str(deal_id),
                "customer_id": str(initiator_customer_id),
            },
        )
        await db.commit()

        log.info(
            "group_deal.created",
            deal_id=str(deal_id),
            store_id=str(store_id),
            initiator=str(initiator_customer_id),
            share_link_code=share_link_code,
            tenant_id=str(tenant_id),
        )

        return {
            "deal_id": str(deal_id),
            "share_link_code": share_link_code,
            "status": "open",
            "current_participants": 1,
        }

    # ------------------------------------------------------------------
    # 参团
    # ------------------------------------------------------------------

    async def join_deal(
        self,
        tenant_id: uuid.UUID,
        deal_id: uuid.UUID,
        customer_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """加入拼团

        Args:
            tenant_id: 租户ID
            deal_id: 拼团ID
            customer_id: 参团者客户ID
            db: AsyncSession

        Returns:
            {deal_id, current_participants, status}

        Raises:
            GroupDealError: 拼团不存在/已满/已过期/重复参团
        """
        # 查拼团信息
        result = await db.execute(
            text("""
                SELECT id, status, current_participants, max_participants,
                       min_participants, expires_at
                FROM group_deals
                WHERE id = :deal_id AND tenant_id = :tenant_id AND is_deleted = false
            """),
            {"deal_id": str(deal_id), "tenant_id": str(tenant_id)},
        )
        deal = result.mappings().first()
        if not deal:
            raise GroupDealError("DEAL_NOT_FOUND", "拼团活动不存在")

        if deal["status"] != "open":
            raise GroupDealError("DEAL_NOT_OPEN", f"拼团状态为 {deal['status']}，无法参团")

        now = datetime.now(timezone.utc)
        if deal["expires_at"] and deal["expires_at"] <= now:
            raise GroupDealError("DEAL_EXPIRED", "拼团已过期")

        if deal["current_participants"] >= deal["max_participants"]:
            raise GroupDealError("DEAL_FULL", "拼团人数已满")

        # 检查重复参团
        dup_result = await db.execute(
            text("""
                SELECT id FROM group_deal_participants
                WHERE deal_id = :deal_id AND customer_id = :customer_id
                  AND tenant_id = :tenant_id AND is_deleted = false
            """),
            {
                "deal_id": str(deal_id),
                "customer_id": str(customer_id),
                "tenant_id": str(tenant_id),
            },
        )
        if dup_result.first():
            raise GroupDealError("ALREADY_JOINED", "已参加此拼团")

        # 加入
        participant_id = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO group_deal_participants (
                    id, tenant_id, deal_id, customer_id
                ) VALUES (:id, :tenant_id, :deal_id, :customer_id)
            """),
            {
                "id": str(participant_id),
                "tenant_id": str(tenant_id),
                "deal_id": str(deal_id),
                "customer_id": str(customer_id),
            },
        )

        new_count = deal["current_participants"] + 1
        new_status = "open"
        filled_at = None

        if new_count >= deal["min_participants"]:
            new_status = "filled"
            filled_at = now

        await db.execute(
            text("""
                UPDATE group_deals
                SET current_participants = :count,
                    status = :status,
                    filled_at = :filled_at,
                    updated_at = NOW()
                WHERE id = :deal_id AND tenant_id = :tenant_id
            """),
            {
                "count": new_count,
                "status": new_status,
                "filled_at": filled_at,
                "deal_id": str(deal_id),
                "tenant_id": str(tenant_id),
            },
        )
        await db.commit()

        log.info(
            "group_deal.joined",
            deal_id=str(deal_id),
            customer_id=str(customer_id),
            new_count=new_count,
            new_status=new_status,
            tenant_id=str(tenant_id),
        )

        return {
            "deal_id": str(deal_id),
            "current_participants": new_count,
            "status": new_status,
        }

    # ------------------------------------------------------------------
    # 退出拼团
    # ------------------------------------------------------------------

    async def leave_deal(
        self,
        tenant_id: uuid.UUID,
        deal_id: uuid.UUID,
        customer_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """退出拼团（已支付者不可退出）

        Returns:
            {deal_id, current_participants}

        Raises:
            GroupDealError: 不存在/已支付/是发起者
        """
        # 查参与记录
        result = await db.execute(
            text("""
                SELECT id, paid FROM group_deal_participants
                WHERE deal_id = :deal_id AND customer_id = :customer_id
                  AND tenant_id = :tenant_id AND is_deleted = false
            """),
            {
                "deal_id": str(deal_id),
                "customer_id": str(customer_id),
                "tenant_id": str(tenant_id),
            },
        )
        participant = result.mappings().first()
        if not participant:
            raise GroupDealError("NOT_IN_DEAL", "未参加此拼团")

        if participant["paid"]:
            raise GroupDealError("ALREADY_PAID", "已支付，无法退出拼团")

        # 检查是否为发起者
        deal_result = await db.execute(
            text("""
                SELECT initiator_customer_id, status
                FROM group_deals
                WHERE id = :deal_id AND tenant_id = :tenant_id AND is_deleted = false
            """),
            {"deal_id": str(deal_id), "tenant_id": str(tenant_id)},
        )
        deal = deal_result.mappings().first()
        if not deal:
            raise GroupDealError("DEAL_NOT_FOUND", "拼团活动不存在")

        if str(deal["initiator_customer_id"]) == str(customer_id):
            raise GroupDealError("INITIATOR_CANNOT_LEAVE", "发起者不能退出拼团")

        # 软删除参与者记录
        await db.execute(
            text("""
                UPDATE group_deal_participants
                SET is_deleted = true, updated_at = NOW()
                WHERE id = :pid AND tenant_id = :tenant_id
            """),
            {"pid": str(participant["id"]), "tenant_id": str(tenant_id)},
        )

        # 更新拼团人数和状态
        await db.execute(
            text("""
                UPDATE group_deals
                SET current_participants = current_participants - 1,
                    status = CASE
                        WHEN status = 'filled' THEN 'open'
                        ELSE status
                    END,
                    filled_at = CASE
                        WHEN status = 'filled' THEN NULL
                        ELSE filled_at
                    END,
                    updated_at = NOW()
                WHERE id = :deal_id AND tenant_id = :tenant_id
            """),
            {"deal_id": str(deal_id), "tenant_id": str(tenant_id)},
        )
        await db.commit()

        # 查更新后人数
        cnt_result = await db.execute(
            text("""
                SELECT current_participants FROM group_deals
                WHERE id = :deal_id AND tenant_id = :tenant_id
            """),
            {"deal_id": str(deal_id), "tenant_id": str(tenant_id)},
        )
        row = cnt_result.first()
        new_count = row[0] if row else 0

        log.info(
            "group_deal.left",
            deal_id=str(deal_id),
            customer_id=str(customer_id),
            new_count=new_count,
            tenant_id=str(tenant_id),
        )

        return {
            "deal_id": str(deal_id),
            "current_participants": new_count,
        }

    # ------------------------------------------------------------------
    # 记录支付
    # ------------------------------------------------------------------

    async def record_payment(
        self,
        tenant_id: uuid.UUID,
        deal_id: uuid.UUID,
        customer_id: uuid.UUID,
        order_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """标记参与者已支付

        Returns:
            {deal_id, customer_id, paid}

        Raises:
            GroupDealError: 未参团/已支付
        """
        result = await db.execute(
            text("""
                SELECT id, paid FROM group_deal_participants
                WHERE deal_id = :deal_id AND customer_id = :customer_id
                  AND tenant_id = :tenant_id AND is_deleted = false
            """),
            {
                "deal_id": str(deal_id),
                "customer_id": str(customer_id),
                "tenant_id": str(tenant_id),
            },
        )
        participant = result.mappings().first()
        if not participant:
            raise GroupDealError("NOT_IN_DEAL", "未参加此拼团")

        if participant["paid"]:
            raise GroupDealError("ALREADY_PAID", "已支付，请勿重复操作")

        now = datetime.now(timezone.utc)
        await db.execute(
            text("""
                UPDATE group_deal_participants
                SET paid = true, paid_at = :paid_at, order_id = :order_id,
                    updated_at = NOW()
                WHERE id = :pid AND tenant_id = :tenant_id
            """),
            {
                "paid_at": now,
                "order_id": str(order_id),
                "pid": str(participant["id"]),
                "tenant_id": str(tenant_id),
            },
        )

        # 查拼团价并更新收入
        deal_result = await db.execute(
            text("""
                SELECT deal_price_fen FROM group_deals
                WHERE id = :deal_id AND tenant_id = :tenant_id
            """),
            {"deal_id": str(deal_id), "tenant_id": str(tenant_id)},
        )
        deal_row = deal_result.first()
        price_fen = deal_row[0] if deal_row else 0

        await db.execute(
            text("""
                UPDATE group_deals
                SET total_revenue_fen = total_revenue_fen + :price_fen,
                    updated_at = NOW()
                WHERE id = :deal_id AND tenant_id = :tenant_id
            """),
            {
                "price_fen": price_fen,
                "deal_id": str(deal_id),
                "tenant_id": str(tenant_id),
            },
        )
        await db.commit()

        log.info(
            "group_deal.payment_recorded",
            deal_id=str(deal_id),
            customer_id=str(customer_id),
            order_id=str(order_id),
            tenant_id=str(tenant_id),
        )

        return {
            "deal_id": str(deal_id),
            "customer_id": str(customer_id),
            "paid": True,
        }

    # ------------------------------------------------------------------
    # 完成拼团
    # ------------------------------------------------------------------

    async def complete_deal(
        self,
        tenant_id: uuid.UUID,
        deal_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """当所有参与者都已支付时完成拼团

        Returns:
            {deal_id, status, total_revenue_fen}

        Raises:
            GroupDealError: 拼团不存在/状态不对/仍有未支付
        """
        result = await db.execute(
            text("""
                SELECT id, status, current_participants, total_revenue_fen
                FROM group_deals
                WHERE id = :deal_id AND tenant_id = :tenant_id AND is_deleted = false
            """),
            {"deal_id": str(deal_id), "tenant_id": str(tenant_id)},
        )
        deal = result.mappings().first()
        if not deal:
            raise GroupDealError("DEAL_NOT_FOUND", "拼团活动不存在")

        if deal["status"] not in ("filled", "open"):
            raise GroupDealError(
                "INVALID_STATUS", f"拼团状态为 {deal['status']}，无法完成"
            )

        # 检查是否全部支付
        unpaid_result = await db.execute(
            text("""
                SELECT COUNT(*) FROM group_deal_participants
                WHERE deal_id = :deal_id AND tenant_id = :tenant_id
                  AND is_deleted = false AND paid = false
            """),
            {"deal_id": str(deal_id), "tenant_id": str(tenant_id)},
        )
        unpaid_count = unpaid_result.scalar_one()
        if unpaid_count > 0:
            raise GroupDealError(
                "UNPAID_PARTICIPANTS", f"仍有 {unpaid_count} 位参与者未支付"
            )

        now = datetime.now(timezone.utc)
        await db.execute(
            text("""
                UPDATE group_deals
                SET status = 'completed', completed_at = :now, updated_at = NOW()
                WHERE id = :deal_id AND tenant_id = :tenant_id
            """),
            {"now": now, "deal_id": str(deal_id), "tenant_id": str(tenant_id)},
        )
        await db.commit()

        log.info(
            "group_deal.completed",
            deal_id=str(deal_id),
            total_revenue_fen=deal["total_revenue_fen"],
            tenant_id=str(tenant_id),
        )

        return {
            "deal_id": str(deal_id),
            "status": "completed",
            "total_revenue_fen": deal["total_revenue_fen"],
        }

    # ------------------------------------------------------------------
    # 过期未成团
    # ------------------------------------------------------------------

    async def expire_stale_deals(
        self,
        tenant_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """将过期且仍为 open 的拼团标记为 expired

        Returns:
            {expired_count}
        """
        now = datetime.now(timezone.utc)
        result = await db.execute(
            text("""
                UPDATE group_deals
                SET status = 'expired', updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND status = 'open'
                  AND expires_at <= :now
                  AND is_deleted = false
                RETURNING id
            """),
            {"tenant_id": str(tenant_id), "now": now},
        )
        expired_ids = result.fetchall()
        await db.commit()

        count = len(expired_ids)
        log.info(
            "group_deal.expired_stale",
            expired_count=count,
            tenant_id=str(tenant_id),
        )

        return {"expired_count": count}

    # ------------------------------------------------------------------
    # 查询拼团详情（含参与者列表）
    # ------------------------------------------------------------------

    async def get_deal(
        self,
        tenant_id: uuid.UUID,
        deal_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """获取拼团详情+参与者列表

        Returns:
            {deal detail + participants list}

        Raises:
            GroupDealError: 拼团不存在
        """
        result = await db.execute(
            text("""
                SELECT id, tenant_id, store_id, name, description, dish_id,
                       min_participants, max_participants, current_participants,
                       original_price_fen, deal_price_fen, discount_fen,
                       status, expires_at, filled_at, completed_at,
                       initiator_customer_id, share_link_code,
                       total_revenue_fen, created_at
                FROM group_deals
                WHERE id = :deal_id AND tenant_id = :tenant_id AND is_deleted = false
            """),
            {"deal_id": str(deal_id), "tenant_id": str(tenant_id)},
        )
        deal = result.mappings().first()
        if not deal:
            raise GroupDealError("DEAL_NOT_FOUND", "拼团活动不存在")

        # 查参与者
        p_result = await db.execute(
            text("""
                SELECT id, customer_id, joined_at, order_id, paid, paid_at
                FROM group_deal_participants
                WHERE deal_id = :deal_id AND tenant_id = :tenant_id AND is_deleted = false
                ORDER BY joined_at ASC
            """),
            {"deal_id": str(deal_id), "tenant_id": str(tenant_id)},
        )
        participants = [
            {
                "id": str(p["id"]),
                "customer_id": str(p["customer_id"]),
                "joined_at": p["joined_at"].isoformat() if p["joined_at"] else None,
                "order_id": str(p["order_id"]) if p["order_id"] else None,
                "paid": p["paid"],
                "paid_at": p["paid_at"].isoformat() if p["paid_at"] else None,
            }
            for p in p_result.mappings().all()
        ]

        return {
            "id": str(deal["id"]),
            "store_id": str(deal["store_id"]),
            "name": deal["name"],
            "description": deal["description"],
            "dish_id": str(deal["dish_id"]) if deal["dish_id"] else None,
            "min_participants": deal["min_participants"],
            "max_participants": deal["max_participants"],
            "current_participants": deal["current_participants"],
            "original_price_fen": deal["original_price_fen"],
            "deal_price_fen": deal["deal_price_fen"],
            "discount_fen": deal["discount_fen"],
            "status": deal["status"],
            "expires_at": deal["expires_at"].isoformat() if deal["expires_at"] else None,
            "filled_at": deal["filled_at"].isoformat() if deal["filled_at"] else None,
            "completed_at": deal["completed_at"].isoformat() if deal["completed_at"] else None,
            "initiator_customer_id": str(deal["initiator_customer_id"]),
            "share_link_code": deal["share_link_code"],
            "total_revenue_fen": deal["total_revenue_fen"],
            "created_at": deal["created_at"].isoformat() if deal["created_at"] else None,
            "participants": participants,
        }

    # ------------------------------------------------------------------
    # 列表
    # ------------------------------------------------------------------

    async def list_deals(
        self,
        tenant_id: uuid.UUID,
        db: Any,
        *,
        store_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页查询拼团列表

        Returns:
            {items: [...], total: int}
        """
        conditions = ["tenant_id = :tenant_id", "is_deleted = false"]
        params: dict[str, Any] = {"tenant_id": str(tenant_id)}

        if store_id:
            conditions.append("store_id = :store_id")
            params["store_id"] = str(store_id)
        if status:
            conditions.append("status = :status")
            params["status"] = status

        where_clause = " AND ".join(conditions)

        # 总数
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM group_deals WHERE {where_clause}"),
            params,
        )
        total = count_result.scalar_one()

        # 分页
        offset = (page - 1) * size
        params["limit"] = size
        params["offset"] = offset

        rows_result = await db.execute(
            text(f"""
                SELECT id, store_id, name, min_participants, max_participants,
                       current_participants, original_price_fen, deal_price_fen,
                       discount_fen, status, expires_at, share_link_code,
                       total_revenue_fen, created_at
                FROM group_deals
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [
            {
                "id": str(r["id"]),
                "store_id": str(r["store_id"]),
                "name": r["name"],
                "min_participants": r["min_participants"],
                "max_participants": r["max_participants"],
                "current_participants": r["current_participants"],
                "original_price_fen": r["original_price_fen"],
                "deal_price_fen": r["deal_price_fen"],
                "discount_fen": r["discount_fen"],
                "status": r["status"],
                "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
                "share_link_code": r["share_link_code"],
                "total_revenue_fen": r["total_revenue_fen"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows_result.mappings().all()
        ]

        return {"items": items, "total": total}

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    async def get_deal_stats(
        self,
        tenant_id: uuid.UUID,
        db: Any,
        *,
        days: int = 30,
    ) -> dict:
        """拼团统计：总数、成团率、平均人数、总收入

        Returns:
            {total_deals, filled_count, fill_rate, avg_participants,
             total_revenue_fen, completed_count}
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        result = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS total_deals,
                    COUNT(*) FILTER (WHERE status IN ('filled', 'completed')) AS filled_count,
                    COUNT(*) FILTER (WHERE status = 'completed') AS completed_count,
                    COALESCE(AVG(current_participants), 0) AS avg_participants,
                    COALESCE(SUM(total_revenue_fen), 0) AS total_revenue_fen
                FROM group_deals
                WHERE tenant_id = :tenant_id
                  AND is_deleted = false
                  AND created_at >= :cutoff
            """),
            {"tenant_id": str(tenant_id), "cutoff": cutoff},
        )
        row = result.mappings().first()

        total = row["total_deals"] if row else 0
        filled = row["filled_count"] if row else 0
        fill_rate = round(filled / total * 100, 1) if total > 0 else 0.0

        return {
            "total_deals": total,
            "filled_count": filled,
            "completed_count": row["completed_count"] if row else 0,
            "fill_rate": fill_rate,
            "avg_participants": round(float(row["avg_participants"]), 1) if row else 0.0,
            "total_revenue_fen": int(row["total_revenue_fen"]) if row else 0,
        }
