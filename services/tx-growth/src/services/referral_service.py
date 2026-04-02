"""裂变拉新服务 — 邀请有礼（老带新）

核心流程：
  1. 老会员生成邀请链接（generate_invite_link）
  2. 新用户通过邀请码注册（register_via_invite）
  3. 新用户首单触发邀请人奖励（process_first_order）

防刷机制：
  - 同设备：同一 campaign 内，相同 device_id 只能被邀请注册一次
  - 同手机前7位：同一 campaign 内，手机号前7位相同拒绝（家庭套现防范）
  - 同IP（可选）：移动端不可靠，由活动配置控制是否启用
  - 不能邀请自己
  - 只有真正的新用户（total_order_count == 0）才能使用邀请码

金额单位：分(fen)
环境变量：MINIAPP_BASE_URL（默认 https://miniapp.tunxiang.com）
"""
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
import structlog

log = structlog.get_logger(__name__)

MINIAPP_BASE_URL: str = os.environ.get("MINIAPP_BASE_URL", "https://miniapp.tunxiang.com")

# tx-member 服务地址
TX_MEMBER_BASE_URL: str = os.environ.get("TX_MEMBER_BASE_URL", "http://tx-member:8000")

# ---------------------------------------------------------------------------
# 内部异常
# ---------------------------------------------------------------------------


class ReferralError(Exception):
    """裂变业务异常（携带 code 用于 API 层区分）"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# ReferralService
# ---------------------------------------------------------------------------


class ReferralService:
    """邀请有礼裂变活动服务"""

    # ------------------------------------------------------------------
    # 生成邀请链接
    # ------------------------------------------------------------------

    async def generate_invite_link(
        self,
        campaign_id: uuid.UUID,
        referrer_customer_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """老会员生成专属邀请链接

        Args:
            campaign_id: 裂变活动 ID
            referrer_customer_id: 邀请人（老会员）客户 ID
            tenant_id: 租户 ID
            db: 数据库 Session（SQLAlchemy AsyncSession）

        Returns:
            {invite_code, invite_url, valid_until, campaign_name}

        Raises:
            ReferralError: 活动不存在/已结束/超出邀请上限
        """
        from models.referral import ReferralRecord
        from sqlalchemy import func, select

        # 1. 查活动并验证状态
        campaign = await self._get_active_campaign(campaign_id, tenant_id, db)

        # 2. 检查该用户邀请数是否达到上限
        max_referrals = campaign.max_referrals_per_user
        if max_referrals > 0:
            count_result = await db.execute(
                select(func.count(ReferralRecord.id)).where(
                    ReferralRecord.campaign_id == campaign_id,
                    ReferralRecord.referrer_customer_id == referrer_customer_id,
                    ReferralRecord.tenant_id == tenant_id,
                    ReferralRecord.is_deleted == False,  # noqa: E712
                )
            )
            current_count: int = count_result.scalar_one()
            if current_count >= max_referrals:
                raise ReferralError(
                    "REFERRAL_LIMIT_EXCEEDED",
                    f"已达邀请上限（{max_referrals}人）",
                )

        # 3. 生成唯一邀请码（8位大写字母数字，使用 uuid4 前8位）
        invite_code = self._generate_invite_code()

        # 4. 生成邀请链接
        invite_url = f"{MINIAPP_BASE_URL}/invite?code={invite_code}"

        # 5. 计算过期时间
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=campaign.valid_days)

        # 6. 写入邀请记录
        record = ReferralRecord(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            referrer_customer_id=referrer_customer_id,
            invite_code=invite_code,
            invite_url=invite_url,
            status="pending",
            invited_at=now,
            expires_at=expires_at,
            referrer_rewarded=False,
            invitee_rewarded=False,
        )
        db.add(record)
        await db.commit()

        log.info(
            "referral.invite_link_generated",
            campaign_id=str(campaign_id),
            referrer_customer_id=str(referrer_customer_id),
            invite_code=invite_code,
            tenant_id=str(tenant_id),
        )

        return {
            "invite_code": invite_code,
            "invite_url": invite_url,
            "valid_until": expires_at.isoformat(),
            "campaign_name": campaign.name,
        }

    # ------------------------------------------------------------------
    # 新用户通过邀请码注册
    # ------------------------------------------------------------------

    async def register_via_invite(
        self,
        invite_code: str,
        new_customer_id: uuid.UUID,
        device_id: Optional[str],
        ip: Optional[str],
        phone: Optional[str],
        tenant_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """新用户通过邀请码完成注册绑定

        防刷检查（幂等：同一邀请码重复调用直接返回已有结果）：
          - invite_code 状态必须是 pending 且未过期
          - new_customer_id 必须是新用户（total_order_count == 0）
          - 不能邀请自己
          - 同设备（device_id）在同 campaign 内仅允许一次（可配置）
          - 同手机前7位在同 campaign 内仅允许一次（可配置）

        Args:
            invite_code: 邀请码
            new_customer_id: 新用户客户 ID
            device_id: 设备 ID（小程序环境）
            ip: 注册时客户端 IP
            phone: 新用户手机号
            tenant_id: 租户 ID
            db: 数据库 Session

        Returns:
            {success, invitee_reward, referrer_rewarded}
        """
        from models.referral import ReferralCampaign, ReferralRecord
        from sqlalchemy import select

        now = datetime.now(timezone.utc)

        # 1. 查邀请记录
        record_result = await db.execute(
            select(ReferralRecord).where(
                ReferralRecord.invite_code == invite_code,
                ReferralRecord.tenant_id == tenant_id,
                ReferralRecord.is_deleted == False,  # noqa: E712
            )
        )
        record: Optional[ReferralRecord] = record_result.scalar_one_or_none()

        if record is None:
            raise ReferralError("INVITE_CODE_NOT_FOUND", "邀请码不存在")

        # 幂等：已注册则直接返回
        if record.status == "registered" and record.invitee_customer_id == new_customer_id:
            return {
                "success": True,
                "invitee_reward": record.invitee_rewarded,
                "referrer_rewarded": record.referrer_rewarded,
                "message": "已通过此邀请码注册",
            }

        if record.status not in ("pending",):
            raise ReferralError(
                "INVITE_CODE_INVALID",
                f"邀请码状态异常（当前: {record.status}）",
            )

        # 验证未过期
        if now > record.expires_at:
            record.status = "expired"
            await db.commit()
            raise ReferralError("INVITE_CODE_EXPIRED", "邀请码已过期")

        # 2. 验证是否为真正新用户
        await self._assert_new_customer(new_customer_id, tenant_id, db)

        # 3. 防刷检查
        campaign_result = await db.execute(
            select(ReferralCampaign).where(
                ReferralCampaign.id == record.campaign_id,
                ReferralCampaign.tenant_id == tenant_id,
            )
        )
        campaign: Optional[ReferralCampaign] = campaign_result.scalar_one_or_none()
        if campaign is None:
            raise ReferralError("CAMPAIGN_NOT_FOUND", "活动不存在")

        # 不能邀请自己
        if new_customer_id == record.referrer_customer_id:
            record.status = "fraud_detected"
            await db.commit()
            raise ReferralError("FRAUD_SELF_REFERRAL", "不能邀请自己")

        # 同设备防刷
        if campaign.anti_fraud_same_device and device_id:
            fraud_device = await self._check_fraud_device(
                record.campaign_id, device_id, tenant_id, db
            )
            if fraud_device:
                record.status = "fraud_detected"
                record.invitee_device_id = device_id
                record.invitee_ip = ip
                record.invitee_phone = phone
                await db.commit()
                log.warning(
                    "referral.fraud_detected",
                    reason="same_device",
                    campaign_id=str(record.campaign_id),
                    device_id=device_id,
                    tenant_id=str(tenant_id),
                )
                raise ReferralError("FRAUD_SAME_DEVICE", "同设备已参与过此活动")

        # 同手机前7位防刷
        if campaign.anti_fraud_same_phone_prefix and phone and len(phone) >= 7:
            phone_prefix = phone[:7]
            fraud_phone = await self._check_fraud_phone_prefix(
                record.campaign_id, phone_prefix, tenant_id, db
            )
            if fraud_phone:
                record.status = "fraud_detected"
                record.invitee_device_id = device_id
                record.invitee_ip = ip
                record.invitee_phone = phone
                await db.commit()
                log.warning(
                    "referral.fraud_detected",
                    reason="same_phone_prefix",
                    campaign_id=str(record.campaign_id),
                    phone_prefix=phone_prefix,
                    tenant_id=str(tenant_id),
                )
                raise ReferralError("FRAUD_SAME_PHONE_PREFIX", "该手机号段已参与过此活动")

        # 同IP防刷（可选，移动端不可靠）
        if campaign.anti_fraud_same_ip and ip:
            fraud_ip = await self._check_fraud_ip(
                record.campaign_id, ip, tenant_id, db
            )
            if fraud_ip:
                record.status = "fraud_detected"
                record.invitee_device_id = device_id
                record.invitee_ip = ip
                record.invitee_phone = phone
                await db.commit()
                log.warning(
                    "referral.fraud_detected",
                    reason="same_ip",
                    campaign_id=str(record.campaign_id),
                    ip=ip,
                    tenant_id=str(tenant_id),
                )
                raise ReferralError("FRAUD_SAME_IP", "同IP已参与过此活动")

        # 4. 更新邀请记录
        record.invitee_customer_id = new_customer_id
        record.status = "registered"
        record.registered_at = now
        record.invitee_device_id = device_id
        record.invitee_ip = ip
        record.invitee_phone = phone

        # 5. 发放被邀请人奖励（注册即得）
        invitee_rewarded = await self._issue_reward(
            customer_id=new_customer_id,
            reward_type=campaign.invitee_reward_type,
            reward_value=campaign.invitee_reward_value,
            tenant_id=tenant_id,
        )
        if invitee_rewarded:
            record.invitee_rewarded = True

        # 6. 如果邀请人奖励条件是"新人注册即得"，立即发放
        referrer_rewarded = False
        if campaign.referrer_reward_condition == "new_register":
            referrer_rewarded = await self._issue_reward(
                customer_id=record.referrer_customer_id,
                reward_type=campaign.referrer_reward_type,
                reward_value=campaign.referrer_reward_value,
                tenant_id=tenant_id,
            )
            if referrer_rewarded:
                record.referrer_rewarded = True
                record.rewarded_at = now

        await db.commit()

        log.info(
            "referral.registered",
            invite_code=invite_code,
            invitee_customer_id=str(new_customer_id),
            referrer_customer_id=str(record.referrer_customer_id),
            invitee_rewarded=invitee_rewarded,
            referrer_rewarded=referrer_rewarded,
            tenant_id=str(tenant_id),
        )

        return {
            "success": True,
            "invitee_reward": invitee_rewarded,
            "referrer_rewarded": referrer_rewarded,
        }

    # ------------------------------------------------------------------
    # 新用户首单触发奖励
    # ------------------------------------------------------------------

    async def process_first_order(
        self,
        order_id: str,
        customer_id: uuid.UUID,
        order_amount_fen: int,
        tenant_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """新用户首单完成后触发邀请人奖励

        由 tx-trade 下单成功事件或旅程节点调用。

        Args:
            order_id: 订单 ID（用于日志追溯）
            customer_id: 下单客户 ID
            order_amount_fen: 订单金额（分）
            tenant_id: 租户 ID
            db: 数据库 Session

        Returns:
            {rewarded, referrer_customer_id, reward_details}
        """
        from models.referral import ReferralCampaign, ReferralRecord
        from sqlalchemy import select

        now = datetime.now(timezone.utc)

        # 1. 查该用户有无 status="registered" 的邀请记录
        record_result = await db.execute(
            select(ReferralRecord).where(
                ReferralRecord.invitee_customer_id == customer_id,
                ReferralRecord.status == "registered",
                ReferralRecord.tenant_id == tenant_id,
                ReferralRecord.is_deleted == False,  # noqa: E712
            ).order_by(ReferralRecord.registered_at.desc()).limit(1)
        )
        record: Optional[ReferralRecord] = record_result.scalar_one_or_none()

        if record is None:
            # 该用户没有未完成的邀请记录，正常情况，无需处理
            return {
                "rewarded": False,
                "referrer_customer_id": None,
                "reward_details": None,
                "reason": "no_pending_referral",
            }

        # 查活动配置
        campaign_result = await db.execute(
            select(ReferralCampaign).where(
                ReferralCampaign.id == record.campaign_id,
                ReferralCampaign.tenant_id == tenant_id,
            )
        )
        campaign: Optional[ReferralCampaign] = campaign_result.scalar_one_or_none()
        if campaign is None:
            return {
                "rewarded": False,
                "referrer_customer_id": None,
                "reward_details": None,
                "reason": "campaign_not_found",
            }

        # 2. 验证订单金额
        if campaign.min_order_amount_fen > 0 and order_amount_fen < campaign.min_order_amount_fen:
            log.info(
                "referral.first_order_amount_insufficient",
                order_id=order_id,
                order_amount_fen=order_amount_fen,
                min_required_fen=campaign.min_order_amount_fen,
                tenant_id=str(tenant_id),
            )
            return {
                "rewarded": False,
                "referrer_customer_id": str(record.referrer_customer_id),
                "reward_details": None,
                "reason": "order_amount_insufficient",
            }

        # 3. 如果邀请人奖励条件是"first_order"，发放邀请人奖励
        referrer_rewarded = False
        reward_details: Optional[dict] = None

        if campaign.referrer_reward_condition == "first_order" and not record.referrer_rewarded:
            referrer_rewarded = await self._issue_reward(
                customer_id=record.referrer_customer_id,
                reward_type=campaign.referrer_reward_type,
                reward_value=campaign.referrer_reward_value,
                tenant_id=tenant_id,
            )
            if referrer_rewarded:
                record.referrer_rewarded = True
                record.rewarded_at = now
                reward_details = {
                    "reward_type": campaign.referrer_reward_type,
                    "reward_value": campaign.referrer_reward_value,
                }

        # 4. 更新记录：首单时间 + 状态
        record.first_order_at = now
        record.status = "rewarded"
        await db.commit()

        log.info(
            "referral.first_order_processed",
            order_id=order_id,
            customer_id=str(customer_id),
            referrer_customer_id=str(record.referrer_customer_id),
            referrer_rewarded=referrer_rewarded,
            tenant_id=str(tenant_id),
        )

        return {
            "rewarded": referrer_rewarded,
            "referrer_customer_id": str(record.referrer_customer_id),
            "reward_details": reward_details,
        }

    # ------------------------------------------------------------------
    # 统一奖励发放
    # ------------------------------------------------------------------

    async def _issue_reward(
        self,
        customer_id: uuid.UUID,
        reward_type: str,
        reward_value: int,
        tenant_id: uuid.UUID,
    ) -> bool:
        """统一奖励发放入口（调用 tx-member 服务）

        发放失败时记录 error 日志，返回 False，不抛异常。
        调用方负责后续重试。

        Args:
            customer_id: 奖励接受人客户 ID
            reward_type: coupon | points | stored_value
            reward_value: 优惠券ID / 积分数 / 储值分
            tenant_id: 租户 ID

        Returns:
            True=发放成功，False=发放失败
        """
        url_map = {
            "coupon": f"{TX_MEMBER_BASE_URL}/api/v1/member/coupons/issue",
            "points": f"{TX_MEMBER_BASE_URL}/api/v1/member/points/add",
            "stored_value": f"{TX_MEMBER_BASE_URL}/api/v1/member/stored-value/gift-add",
        }

        url = url_map.get(reward_type)
        if not url:
            log.error(
                "referral.issue_reward_unknown_type",
                reward_type=reward_type,
                customer_id=str(customer_id),
                tenant_id=str(tenant_id),
            )
            return False

        payload: dict = {
            "customer_id": str(customer_id),
        }
        if reward_type == "coupon":
            payload["coupon_id"] = str(reward_value)
        elif reward_type == "points":
            payload["points"] = reward_value
        elif reward_type == "stored_value":
            payload["amount_fen"] = reward_value

        headers = {
            "X-Tenant-ID": str(tenant_id),
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                log.info(
                    "referral.reward_issued",
                    reward_type=reward_type,
                    reward_value=reward_value,
                    customer_id=str(customer_id),
                    tenant_id=str(tenant_id),
                )
                return True
            else:
                log.error(
                    "referral.issue_reward_failed",
                    reward_type=reward_type,
                    customer_id=str(customer_id),
                    status_code=resp.status_code,
                    response_body=resp.text[:200],
                    tenant_id=str(tenant_id),
                )
                return False
        except httpx.HTTPError as exc:
            log.error(
                "referral.issue_reward_http_error",
                reward_type=reward_type,
                customer_id=str(customer_id),
                error=str(exc),
                tenant_id=str(tenant_id),
                exc_info=exc,
            )
            return False

    # ------------------------------------------------------------------
    # 活动统计
    # ------------------------------------------------------------------

    async def get_referral_stats(
        self,
        campaign_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """获取裂变活动统计数据

        Returns:
            {
                total_invites, total_registered, total_rewarded,
                fraud_detected, conversion_rate, top_referrers
            }
        """
        from models.referral import ReferralRecord
        from sqlalchemy import func, select

        # 验证活动归属
        await self._assert_campaign_ownership(campaign_id, tenant_id, db)

        base_q = select(ReferralRecord).where(
            ReferralRecord.campaign_id == campaign_id,
            ReferralRecord.tenant_id == tenant_id,
            ReferralRecord.is_deleted == False,  # noqa: E712
        )

        # 统计各状态数量
        counts_result = await db.execute(
            select(ReferralRecord.status, func.count(ReferralRecord.id))
            .where(
                ReferralRecord.campaign_id == campaign_id,
                ReferralRecord.tenant_id == tenant_id,
                ReferralRecord.is_deleted == False,  # noqa: E712
            )
            .group_by(ReferralRecord.status)
        )
        status_counts: dict[str, int] = {row[0]: row[1] for row in counts_result.fetchall()}

        total_invites = sum(status_counts.values())
        total_registered = (
            status_counts.get("registered", 0) + status_counts.get("rewarded", 0)
        )
        total_rewarded = status_counts.get("rewarded", 0)
        fraud_detected = status_counts.get("fraud_detected", 0)
        conversion_rate = round(total_registered / total_invites, 4) if total_invites > 0 else 0.0

        # Top 10 邀请人（按邀请成功数量）
        top_result = await db.execute(
            select(
                ReferralRecord.referrer_customer_id,
                func.count(ReferralRecord.id).label("invite_count"),
            )
            .where(
                ReferralRecord.campaign_id == campaign_id,
                ReferralRecord.tenant_id == tenant_id,
                ReferralRecord.is_deleted == False,  # noqa: E712
                ReferralRecord.status.in_(["registered", "rewarded"]),
            )
            .group_by(ReferralRecord.referrer_customer_id)
            .order_by(func.count(ReferralRecord.id).desc())
            .limit(10)
        )
        top_referrers = [
            {"customer_id": str(row[0]), "invite_count": row[1]}
            for row in top_result.fetchall()
        ]

        return {
            "total_invites": total_invites,
            "total_registered": total_registered,
            "total_rewarded": total_rewarded,
            "fraud_detected": fraud_detected,
            "conversion_rate": conversion_rate,
            "top_referrers": top_referrers,
        }

    # ------------------------------------------------------------------
    # 我的邀请记录（小程序端）
    # ------------------------------------------------------------------

    async def get_my_referrals(
        self,
        customer_id: uuid.UUID,
        campaign_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """获取我的邀请记录（小程序端展示）

        Returns:
            {invite_url, total_invited, total_rewarded, records: [...]}
        """
        from models.referral import ReferralRecord
        from sqlalchemy import select

        result = await db.execute(
            select(ReferralRecord).where(
                ReferralRecord.campaign_id == campaign_id,
                ReferralRecord.referrer_customer_id == customer_id,
                ReferralRecord.tenant_id == tenant_id,
                ReferralRecord.is_deleted == False,  # noqa: E712
            ).order_by(ReferralRecord.invited_at.desc())
        )
        records: list[ReferralRecord] = list(result.scalars().all())

        total_invited = len([r for r in records if r.status != "fraud_detected"])
        total_rewarded = len([r for r in records if r.referrer_rewarded])

        # 最近一条 pending 记录的链接，若无则返回空
        invite_url: Optional[str] = None
        for rec in records:
            if rec.status == "pending" and datetime.now(timezone.utc) <= rec.expires_at:
                invite_url = rec.invite_url
                break

        return {
            "invite_url": invite_url,
            "total_invited": total_invited,
            "total_rewarded": total_rewarded,
            "records": [
                {
                    "invite_code": r.invite_code,
                    "status": r.status,
                    "invited_at": r.invited_at.isoformat() if r.invited_at else None,
                    "registered_at": r.registered_at.isoformat() if r.registered_at else None,
                    "rewarded_at": r.rewarded_at.isoformat() if r.rewarded_at else None,
                    "referrer_rewarded": r.referrer_rewarded,
                }
                for r in records
            ],
        }

    # ------------------------------------------------------------------
    # 私有辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_invite_code() -> str:
        """生成 8 位大写字母数字邀请码（取 uuid4 前 8 位并转大写）"""
        return uuid.uuid4().hex[:8].upper()

    async def _get_active_campaign(
        self,
        campaign_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: Any,
    ):
        """查询并验证活动处于 active 状态且在有效期内"""
        from models.referral import ReferralCampaign
        from sqlalchemy import select

        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(ReferralCampaign).where(
                ReferralCampaign.id == campaign_id,
                ReferralCampaign.tenant_id == tenant_id,
                ReferralCampaign.is_deleted == False,  # noqa: E712
            )
        )
        campaign = result.scalar_one_or_none()

        if campaign is None:
            raise ReferralError("CAMPAIGN_NOT_FOUND", "裂变活动不存在")
        if campaign.status != "active":
            raise ReferralError(
                "CAMPAIGN_NOT_ACTIVE",
                f"活动未在进行中（当前状态: {campaign.status}）",
            )
        if now < campaign.valid_from:
            raise ReferralError("CAMPAIGN_NOT_STARTED", "活动尚未开始")
        if campaign.valid_until and now > campaign.valid_until:
            raise ReferralError("CAMPAIGN_ENDED", "活动已结束")

        return campaign

    async def _assert_campaign_ownership(
        self,
        campaign_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: Any,
    ) -> None:
        """验证活动归属于当前租户"""
        from models.referral import ReferralCampaign
        from sqlalchemy import select

        result = await db.execute(
            select(ReferralCampaign.id).where(
                ReferralCampaign.id == campaign_id,
                ReferralCampaign.tenant_id == tenant_id,
                ReferralCampaign.is_deleted == False,  # noqa: E712
            )
        )
        if result.scalar_one_or_none() is None:
            raise ReferralError("CAMPAIGN_NOT_FOUND", "活动不存在或无权访问")

    async def _assert_new_customer(
        self,
        customer_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: Any,
    ) -> None:
        """验证 customer_id 为真正的新用户（total_order_count == 0）"""
        from sqlalchemy import select, text

        # 查 customers 表（共享 ontology）
        result = await db.execute(
            select(text("total_order_count")).select_from(text("customers")).where(
                text("id = :cid AND tenant_id = :tid AND is_deleted = FALSE")
            ).bindparams(cid=customer_id, tid=tenant_id)
        )
        row = result.fetchone()
        if row is None:
            raise ReferralError("CUSTOMER_NOT_FOUND", "用户不存在")
        if row[0] > 0:
            raise ReferralError("NOT_NEW_CUSTOMER", "该用户已有消费记录，不符合新人资格")

    async def _check_fraud_device(
        self,
        campaign_id: uuid.UUID,
        device_id: str,
        tenant_id: uuid.UUID,
        db: Any,
    ) -> bool:
        """检查同设备在同 campaign 内是否已被使用（防刷）"""
        from models.referral import ReferralRecord
        from sqlalchemy import func, select

        result = await db.execute(
            select(func.count(ReferralRecord.id)).where(
                ReferralRecord.campaign_id == campaign_id,
                ReferralRecord.tenant_id == tenant_id,
                ReferralRecord.invitee_device_id == device_id,
                ReferralRecord.status.in_(["registered", "rewarded"]),
                ReferralRecord.is_deleted == False,  # noqa: E712
            )
        )
        return (result.scalar_one() or 0) > 0

    async def _check_fraud_phone_prefix(
        self,
        campaign_id: uuid.UUID,
        phone_prefix: str,
        tenant_id: uuid.UUID,
        db: Any,
    ) -> bool:
        """检查同手机前7位在同 campaign 内是否已注册（防家庭套现）"""
        from models.referral import ReferralRecord
        from sqlalchemy import func, select

        result = await db.execute(
            select(func.count(ReferralRecord.id)).where(
                ReferralRecord.campaign_id == campaign_id,
                ReferralRecord.tenant_id == tenant_id,
                ReferralRecord.invitee_phone.like(f"{phone_prefix}%"),
                ReferralRecord.status.in_(["registered", "rewarded"]),
                ReferralRecord.is_deleted == False,  # noqa: E712
            )
        )
        return (result.scalar_one() or 0) > 0

    async def _check_fraud_ip(
        self,
        campaign_id: uuid.UUID,
        ip: str,
        tenant_id: uuid.UUID,
        db: Any,
    ) -> bool:
        """检查同IP在同 campaign 内是否已注册（可选，移动端不可靠）"""
        from models.referral import ReferralRecord
        from sqlalchemy import func, select

        result = await db.execute(
            select(func.count(ReferralRecord.id)).where(
                ReferralRecord.campaign_id == campaign_id,
                ReferralRecord.tenant_id == tenant_id,
                ReferralRecord.invitee_ip == ip,
                ReferralRecord.status.in_(["registered", "rewarded"]),
                ReferralRecord.is_deleted == False,  # noqa: E712
            )
        )
        return (result.scalar_one() or 0) > 0
