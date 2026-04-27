"""双向奖励服务 — Dual Rewards

社交裂变 S4W14-15：
  老带新双方均获奖励，支持积分/优惠券/储值三种奖励类型，
  新用户首单触发自动标记可领取，定时过期未领取记录。

核心流程：
  1. 创建双向奖励记录（create_dual_reward）— 关联推荐人+被推荐人
  2. 被推荐人首单触发（trigger_on_first_order）— 更新订单信息，标记可领取
  3. 双方分别领取（claim_reward）— 标记 claimed + 时间戳
  4. 定时过期（expire_unclaimed）— 超时未领取标记 expired
  5. 推荐人奖励列表 + 排行榜

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


class DualRewardError(Exception):
    """双向奖励业务异常"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# DualRewardService
# ---------------------------------------------------------------------------


class DualRewardService:
    """双向奖励核心服务"""

    # ------------------------------------------------------------------
    # 创建双向奖励
    # ------------------------------------------------------------------

    async def create_dual_reward(
        self,
        tenant_id: uuid.UUID,
        referrer_id: uuid.UUID,
        referee_id: uuid.UUID,
        campaign_id: Optional[uuid.UUID],
        referrer_reward: dict,
        referee_reward: dict,
        db: Any,
    ) -> dict:
        """创建双向奖励记录

        Args:
            tenant_id: 租户ID
            referrer_id: 推荐人ID
            referee_id: 被推荐人ID
            campaign_id: 关联活动ID（可选）
            referrer_reward: 推荐人奖励 {type, amount, coupon_id}
            referee_reward: 被推荐人奖励 {type, amount, coupon_id}
            db: AsyncSession

        Returns:
            {reward_id, referrer_reward_status, referee_reward_status}

        Raises:
            DualRewardError: 自己推荐自己
        """
        if str(referrer_id) == str(referee_id):
            raise DualRewardError("SELF_REFERRAL", "不能推荐自己")

        reward_id = uuid.uuid4()

        await db.execute(
            text("""
                INSERT INTO dual_rewards (
                    id, tenant_id, referrer_id, referee_id,
                    referral_campaign_id, referrer_reward, referee_reward
                ) VALUES (
                    :id, :tenant_id, :referrer_id, :referee_id,
                    :campaign_id,
                    :referrer_reward ::jsonb,
                    :referee_reward ::jsonb
                )
            """),
            {
                "id": str(reward_id),
                "tenant_id": str(tenant_id),
                "referrer_id": str(referrer_id),
                "referee_id": str(referee_id),
                "campaign_id": str(campaign_id) if campaign_id else None,
                "referrer_reward": json.dumps(referrer_reward),
                "referee_reward": json.dumps(referee_reward),
            },
        )
        await db.commit()

        log.info(
            "dual_reward.created",
            reward_id=str(reward_id),
            referrer_id=str(referrer_id),
            referee_id=str(referee_id),
            tenant_id=str(tenant_id),
        )

        return {
            "reward_id": str(reward_id),
            "referrer_reward_status": "pending",
            "referee_reward_status": "pending",
        }

    # ------------------------------------------------------------------
    # 首单触发
    # ------------------------------------------------------------------

    async def trigger_on_first_order(
        self,
        tenant_id: uuid.UUID,
        referee_id: uuid.UUID,
        order_id: uuid.UUID,
        order_amount_fen: int,
        db: Any,
    ) -> dict:
        """被推荐人首单触发，更新双向奖励为可领取

        Args:
            tenant_id: 租户ID
            referee_id: 被推荐人ID
            order_id: 触发订单ID
            order_amount_fen: 订单金额(分)
            db: AsyncSession

        Returns:
            {triggered_count}
        """
        result = await db.execute(
            text("""
                UPDATE dual_rewards
                SET trigger_order_id = :order_id,
                    trigger_order_amount_fen = :amount,
                    referrer_reward_status = 'claimed',
                    referee_reward_status = 'claimed',
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND referee_id = :referee_id
                  AND referrer_reward_status = 'pending'
                  AND referee_reward_status = 'pending'
                  AND is_deleted = false
                RETURNING id
            """),
            {
                "order_id": str(order_id),
                "amount": order_amount_fen,
                "tenant_id": str(tenant_id),
                "referee_id": str(referee_id),
            },
        )
        triggered_ids = result.fetchall()
        await db.commit()

        count = len(triggered_ids)
        log.info(
            "dual_reward.triggered",
            referee_id=str(referee_id),
            order_id=str(order_id),
            triggered_count=count,
            tenant_id=str(tenant_id),
        )

        return {"triggered_count": count}

    # ------------------------------------------------------------------
    # 领取奖励
    # ------------------------------------------------------------------

    async def claim_reward(
        self,
        tenant_id: uuid.UUID,
        reward_id: uuid.UUID,
        who: str,
        db: Any,
    ) -> dict:
        """领取奖励

        Args:
            tenant_id: 租户ID
            reward_id: 奖励记录ID
            who: 'referrer' 或 'referee'
            db: AsyncSession

        Returns:
            {reward_id, who, claimed_at}

        Raises:
            DualRewardError: 记录不存在/已领取/已过期/无效 who
        """
        if who not in ("referrer", "referee"):
            raise DualRewardError("INVALID_WHO", "who 必须是 referrer 或 referee")

        status_col = f"{who}_reward_status"
        claimed_col = f"{who}_claimed_at"

        result = await db.execute(
            text(f"""
                SELECT id, {status_col} AS reward_status
                FROM dual_rewards
                WHERE id = :reward_id AND tenant_id = :tenant_id AND is_deleted = false
            """),
            {"reward_id": str(reward_id), "tenant_id": str(tenant_id)},
        )
        row = result.mappings().first()
        if not row:
            raise DualRewardError("REWARD_NOT_FOUND", "奖励记录不存在")

        current_status = row["reward_status"]
        if current_status == "claimed":
            raise DualRewardError("ALREADY_CLAIMED", "奖励已领取")
        if current_status == "expired":
            raise DualRewardError("REWARD_EXPIRED", "奖励已过期")
        if current_status == "failed":
            raise DualRewardError("REWARD_FAILED", "奖励发放失败")

        now = datetime.now(timezone.utc)
        await db.execute(
            text(f"""
                UPDATE dual_rewards
                SET {status_col} = 'claimed',
                    {claimed_col} = :now,
                    updated_at = NOW()
                WHERE id = :reward_id AND tenant_id = :tenant_id
            """),
            {"now": now, "reward_id": str(reward_id), "tenant_id": str(tenant_id)},
        )
        await db.commit()

        log.info(
            "dual_reward.claimed",
            reward_id=str(reward_id),
            who=who,
            tenant_id=str(tenant_id),
        )

        return {
            "reward_id": str(reward_id),
            "who": who,
            "claimed_at": now.isoformat(),
        }

    # ------------------------------------------------------------------
    # 过期未领取
    # ------------------------------------------------------------------

    async def expire_unclaimed(
        self,
        tenant_id: uuid.UUID,
        db: Any,
        *,
        days: int = 30,
    ) -> dict:
        """将超过指定天数且仍为 pending 的奖励标记为 expired

        Returns:
            {expired_referrer_count, expired_referee_count}
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # 过期推荐人奖励
        r1 = await db.execute(
            text("""
                UPDATE dual_rewards
                SET referrer_reward_status = 'expired', updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND referrer_reward_status = 'pending'
                  AND created_at < :cutoff
                  AND is_deleted = false
                RETURNING id
            """),
            {"tenant_id": str(tenant_id), "cutoff": cutoff},
        )
        expired_referrer = len(r1.fetchall())

        # 过期被推荐人奖励
        r2 = await db.execute(
            text("""
                UPDATE dual_rewards
                SET referee_reward_status = 'expired', updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND referee_reward_status = 'pending'
                  AND created_at < :cutoff
                  AND is_deleted = false
                RETURNING id
            """),
            {"tenant_id": str(tenant_id), "cutoff": cutoff},
        )
        expired_referee = len(r2.fetchall())
        await db.commit()

        log.info(
            "dual_reward.expired_unclaimed",
            expired_referrer_count=expired_referrer,
            expired_referee_count=expired_referee,
            tenant_id=str(tenant_id),
        )

        return {
            "expired_referrer_count": expired_referrer,
            "expired_referee_count": expired_referee,
        }

    # ------------------------------------------------------------------
    # 推荐人奖励列表
    # ------------------------------------------------------------------

    async def get_referrer_rewards(
        self,
        tenant_id: uuid.UUID,
        referrer_id: uuid.UUID,
        db: Any,
    ) -> list[dict]:
        """获取推荐人的所有双向奖励记录

        Returns:
            [{reward_id, referee_id, referrer_reward, referee_reward, ...}]
        """
        result = await db.execute(
            text("""
                SELECT id, referee_id, referral_campaign_id,
                       referrer_reward, referee_reward,
                       trigger_order_id, trigger_order_amount_fen,
                       referrer_reward_status, referee_reward_status,
                       referrer_claimed_at, referee_claimed_at,
                       created_at
                FROM dual_rewards
                WHERE tenant_id = :tenant_id
                  AND referrer_id = :referrer_id
                  AND is_deleted = false
                ORDER BY created_at DESC
            """),
            {"tenant_id": str(tenant_id), "referrer_id": str(referrer_id)},
        )
        rows = result.mappings().all()

        return [
            {
                "reward_id": str(r["id"]),
                "referee_id": str(r["referee_id"]),
                "referral_campaign_id": str(r["referral_campaign_id"]) if r["referral_campaign_id"] else None,
                "referrer_reward": r["referrer_reward"],
                "referee_reward": r["referee_reward"],
                "trigger_order_id": str(r["trigger_order_id"]) if r["trigger_order_id"] else None,
                "trigger_order_amount_fen": r["trigger_order_amount_fen"],
                "referrer_reward_status": r["referrer_reward_status"],
                "referee_reward_status": r["referee_reward_status"],
                "referrer_claimed_at": r["referrer_claimed_at"].isoformat() if r["referrer_claimed_at"] else None,
                "referee_claimed_at": r["referee_claimed_at"].isoformat() if r["referee_claimed_at"] else None,
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # 推荐排行榜
    # ------------------------------------------------------------------

    async def get_referral_leaderboard(
        self,
        tenant_id: uuid.UUID,
        db: Any,
        *,
        limit: int = 20,
    ) -> list[dict]:
        """推荐排行榜 — 按成功推荐数排名

        Returns:
            [{referrer_id, successful_referrals, total_order_amount_fen}]
        """
        result = await db.execute(
            text("""
                SELECT
                    referrer_id,
                    COUNT(*) AS successful_referrals,
                    COALESCE(SUM(trigger_order_amount_fen), 0) AS total_order_amount_fen
                FROM dual_rewards
                WHERE tenant_id = :tenant_id
                  AND is_deleted = false
                  AND trigger_order_id IS NOT NULL
                GROUP BY referrer_id
                ORDER BY successful_referrals DESC
                LIMIT :limit
            """),
            {"tenant_id": str(tenant_id), "limit": limit},
        )
        rows = result.mappings().all()

        return [
            {
                "referrer_id": str(r["referrer_id"]),
                "successful_referrals": r["successful_referrals"],
                "total_order_amount_fen": int(r["total_order_amount_fen"]),
            }
            for r in rows
        ]
