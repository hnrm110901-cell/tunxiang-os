"""社交裂变引擎测试 -- 覆盖6个核心功能

1. 创建拼单
2. 加入拼单
3. 请客送礼
4. 分享有礼
5. 推荐追踪
6. 社交统计
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from services.social_engine import (
    create_group_order,
    create_share_link,
    get_social_stats,
    join_group_order,
    send_gift,
    track_referral,
)

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
CUSTOMER_A = str(uuid.uuid4())
CUSTOMER_B = str(uuid.uuid4())
GROUP_ID = str(uuid.uuid4())


# ── Mock helpers ─────────────────────────────────────────────


class FakeMappingResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class FakeResult:
    def __init__(self, rows=None, scalar_val=None):
        self._rows = rows or []
        self._scalar_val = scalar_val

    def mappings(self):
        return FakeMappingResult(self._rows)

    def scalar(self):
        return self._scalar_val

    def fetchall(self):
        return self._rows


def make_db(side_effects=None):
    db = AsyncMock()
    if side_effects:
        db.execute = AsyncMock(side_effect=side_effects)
    return db


# ── 1. 创建拼单 ─────────────────────────────────────────────


class TestCreateGroupOrder:
    @pytest.mark.asyncio
    async def test_create_group(self):
        db = make_db(
            [
                FakeResult(),  # _set_tenant
                FakeResult(),  # INSERT group_orders
                FakeResult(),  # INSERT group_order_members
            ]
        )
        result = await create_group_order(
            initiator_id=CUSTOMER_A,
            store_id=STORE_ID,
            table_id="T01",
            tenant_id=TENANT_ID,
            db=db,
        )
        assert result["initiator_id"] == CUSTOMER_A
        assert result["store_id"] == STORE_ID
        assert result["status"] == "open"
        assert result["member_count"] == 1
        assert len(result["invite_code"]) == 8

    @pytest.mark.asyncio
    async def test_create_group_no_table(self):
        db = make_db([FakeResult(), FakeResult(), FakeResult()])
        result = await create_group_order(
            initiator_id=CUSTOMER_A,
            store_id=STORE_ID,
            table_id=None,
            tenant_id=TENANT_ID,
            db=db,
        )
        assert result["table_id"] is None


# ── 2. 加入拼单 ─────────────────────────────────────────────


class TestJoinGroupOrder:
    @pytest.mark.asyncio
    async def test_join_success(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        db = make_db(
            [
                FakeResult(),  # _set_tenant
                FakeResult(rows=[{"status": "open", "expires_at": future, "member_count": 1}]),
                FakeResult(scalar_val=None),  # not already in group
                FakeResult(),  # INSERT member
                FakeResult(),  # UPDATE count
            ]
        )
        result = await join_group_order(
            group_id=GROUP_ID,
            customer_id=CUSTOMER_B,
            tenant_id=TENANT_ID,
            db=db,
        )
        assert result["joined"] is True
        assert result["member_count"] == 2

    @pytest.mark.asyncio
    async def test_join_not_found(self):
        db = make_db(
            [
                FakeResult(),  # _set_tenant
                FakeResult(rows=[]),  # group not found
            ]
        )
        with pytest.raises(ValueError, match="group_order_not_found"):
            await join_group_order(GROUP_ID, CUSTOMER_B, TENANT_ID, db)

    @pytest.mark.asyncio
    async def test_join_already_member(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        db = make_db(
            [
                FakeResult(),
                FakeResult(rows=[{"status": "open", "expires_at": future, "member_count": 1}]),
                FakeResult(scalar_val="existing_id"),  # already in
            ]
        )
        with pytest.raises(ValueError, match="already_in_group"):
            await join_group_order(GROUP_ID, CUSTOMER_B, TENANT_ID, db)


# ── 3. 请客送礼 ─────────────────────────────────────────────


class TestSendGift:
    @pytest.mark.asyncio
    async def test_send_dish_gift(self):
        db = make_db([FakeResult(), FakeResult()])
        result = await send_gift(
            sender_id=CUSTOMER_A,
            receiver_phone="13800138000",
            gift_type="dish",
            gift_config={"dish_ids": ["d1", "d2"], "message": "请你吃饭"},
            tenant_id=TENANT_ID,
            db=db,
        )
        assert result["gift_type"] == "dish"
        assert result["status"] == "pending"
        assert "share_url" in result
        assert len(result["share_code"]) == 10

    @pytest.mark.asyncio
    async def test_send_card_gift(self):
        db = make_db([FakeResult(), FakeResult()])
        result = await send_gift(
            sender_id=CUSTOMER_A,
            receiver_phone="13900139000",
            gift_type="card",
            gift_config={"amount_fen": 10000},
            tenant_id=TENANT_ID,
            db=db,
        )
        assert result["gift_type"] == "card"

    @pytest.mark.asyncio
    async def test_invalid_gift_type(self):
        db = make_db([FakeResult()])
        with pytest.raises(ValueError, match="invalid_gift_type"):
            await send_gift(
                CUSTOMER_A,
                "13800138000",
                "invalid",
                {},
                TENANT_ID,
                db,
            )


# ── 4. 分享有礼 ─────────────────────────────────────────────


class TestShareLink:
    @pytest.mark.asyncio
    async def test_new_user_campaign(self):
        db = make_db([FakeResult(), FakeResult()])
        result = await create_share_link(
            customer_id=CUSTOMER_A,
            campaign_type="new_user",
            tenant_id=TENANT_ID,
            db=db,
        )
        assert result["campaign_type"] == "new_user"
        assert "share_url" in result
        assert "referral_code" in result
        assert "好友注册" in result["reward_description"]

    @pytest.mark.asyncio
    async def test_invalid_campaign(self):
        db = make_db([FakeResult()])
        with pytest.raises(ValueError, match="invalid_campaign_type"):
            await create_share_link(CUSTOMER_A, "bad_type", TENANT_ID, db)


# ── 5. 推荐追踪 ─────────────────────────────────────────────


class TestTrackReferral:
    @pytest.mark.asyncio
    async def test_track_success(self):
        db = make_db(
            [
                FakeResult(),  # _set_tenant
                FakeResult(scalar_val=None),  # no existing referral
                FakeResult(),  # INSERT referral
                FakeResult(),  # UPDATE referrer points
                FakeResult(),  # UPDATE referee points
            ]
        )
        result = await track_referral(
            referrer_id=CUSTOMER_A,
            new_customer_id=CUSTOMER_B,
            tenant_id=TENANT_ID,
            db=db,
        )
        assert result["referrer_id"] == CUSTOMER_A
        assert result["new_customer_id"] == CUSTOMER_B
        assert result["referrer_reward_points"] == 10
        assert result["referee_reward_points"] == 10

    @pytest.mark.asyncio
    async def test_duplicate_referral(self):
        db = make_db(
            [
                FakeResult(),
                FakeResult(scalar_val="existing"),
            ]
        )
        with pytest.raises(ValueError, match="referral_already_exists"):
            await track_referral(CUSTOMER_A, CUSTOMER_B, TENANT_ID, db)


# ── 6. 社交统计 ─────────────────────────────────────────────


class TestSocialStats:
    @pytest.mark.asyncio
    async def test_stats(self):
        db = make_db(
            [
                FakeResult(),  # _set_tenant
                FakeResult(rows=[{"cnt": 5, "reward": 50}]),  # referrals
                FakeResult(scalar_val=3),  # group orders
                FakeResult(scalar_val=2),  # gifts
            ]
        )
        result = await get_social_stats(CUSTOMER_A, TENANT_ID, db)
        assert result["customer_id"] == CUSTOMER_A
        assert result["referral_count"] == 5
        assert result["total_reward_points"] == 50
        assert result["group_order_count"] == 3
        assert result["gift_sent_count"] == 2
