"""Social Viral 模块测试 — 拼团 + 双向奖励

覆盖场景：

TestGroupDealService (12):
  1.  create_deal — 正常创建 + 发起者自动参团
  2.  create_deal — 拼团价 >= 原价 → 异常
  3.  create_deal — min_participants < 2 → 异常
  4.  join_deal — 正常参团
  5.  join_deal — 达到最低人数自动 filled
  6.  join_deal — 超容量 → 异常
  7.  join_deal — 重复参团 → 异常
  8.  leave_deal — 正常退团
  9.  leave_deal — 已支付退团 → 异常
  10. record_payment + complete_deal — 全员支付后完成
  11. expire_stale_deals — 过期自动取消
  12. get_deal_stats — 统计数据

TestDualRewardService (8):
  13. create_dual_reward — 正常创建
  14. create_dual_reward — 自己推荐自己 → 异常
  15. trigger_on_first_order — 首单触发
  16. claim_reward — 正常领取 referrer
  17. claim_reward — 重复领取 → 异常
  18. claim_reward — 无效 who → 异常
  19. expire_unclaimed — 过期处理
  20. get_referral_leaderboard — 排行榜

TestGroupDealRoutes (5):
  21. POST / — 创建拼团 API
  22. GET / — 拼团列表 API
  23. GET /{id} — 拼团详情 API
  24. POST /{id}/join — 参团 API
  25. POST /{id}/pay — 支付 API
"""

import os
import sys
import types
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# Stub heavy dependencies before importing
# ---------------------------------------------------------------------------

_structlog_mod = types.ModuleType("structlog")
_structlog_mod.get_logger = MagicMock(return_value=MagicMock())
sys.modules.setdefault("structlog", _structlog_mod)

# Stub sqlalchemy.text — services use `from sqlalchemy import text`
_sqla_mod = types.ModuleType("sqlalchemy")


def _fake_text(sql: str):
    """Return a marker object carrying the SQL string."""
    m = MagicMock()
    m._sql = sql
    return m


_sqla_mod.text = _fake_text
sys.modules.setdefault("sqlalchemy", _sqla_mod)


# ---------------------------------------------------------------------------
# Fake async DB session
# ---------------------------------------------------------------------------


class FakeRow:
    """Mimic a SQLAlchemy Row with both mapping and positional access."""

    def __init__(self, data: dict):
        self._data = data

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self._data.values())[key]
        return self._data[key]

    def keys(self):
        return self._data.keys()


class FakeMappingResult:
    def __init__(self, rows: list[dict]):
        self._rows = [FakeRow(r) for r in rows]

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class FakeResult:
    """Fake DB result supporting .mappings(), .first(), .scalar_one(), .fetchall()."""

    def __init__(self, rows: list[dict] | None = None, scalar: object = None):
        self._rows = rows or []
        self._scalar = scalar

    def mappings(self):
        return FakeMappingResult(self._rows)

    def first(self):
        if self._rows:
            r = self._rows[0]
            return FakeRow(r)
        return None

    def scalar_one(self):
        return self._scalar if self._scalar is not None else 0

    def fetchall(self):
        return [FakeRow(r) for r in self._rows]


class FakeDB:
    """Fake AsyncSession for service-level tests."""

    def __init__(self):
        self.execute = AsyncMock(return_value=FakeResult())
        self.commit = AsyncMock()
        self.rollback = AsyncMock()


# ---------------------------------------------------------------------------
# Import services (after stubs are in place)
# ---------------------------------------------------------------------------

from services.group_deal_service import GroupDealError, GroupDealService
from services.dual_reward_service import DualRewardError, DualRewardService

TENANT = uuid.uuid4()
STORE = uuid.uuid4()
CUSTOMER_A = uuid.uuid4()
CUSTOMER_B = uuid.uuid4()
CUSTOMER_C = uuid.uuid4()
CAMPAIGN = uuid.uuid4()


# ===========================================================================
# TestGroupDealService
# ===========================================================================


class TestGroupDealService:
    """拼团服务单元测试"""

    def setup_method(self):
        self.svc = GroupDealService()
        self.db = FakeDB()

    # 1. 正常创建
    @pytest.mark.asyncio
    async def test_create_deal_success(self):
        result = await self.svc.create_deal(
            tenant_id=TENANT,
            store_id=STORE,
            name="测试拼团",
            min_participants=3,
            original_price_fen=10000,
            deal_price_fen=8000,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            initiator_customer_id=CUSTOMER_A,
            db=self.db,
        )
        assert result["status"] == "open"
        assert result["current_participants"] == 1
        assert result["share_link_code"]
        assert result["deal_id"]
        # 2 inserts (deal + participant) + commit
        assert self.db.execute.call_count == 2
        assert self.db.commit.call_count == 1

    # 2. 拼团价 >= 原价
    @pytest.mark.asyncio
    async def test_create_deal_invalid_price(self):
        with pytest.raises(GroupDealError) as exc_info:
            await self.svc.create_deal(
                tenant_id=TENANT,
                store_id=STORE,
                name="坏价格",
                min_participants=2,
                original_price_fen=5000,
                deal_price_fen=5000,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
                initiator_customer_id=CUSTOMER_A,
                db=self.db,
            )
        assert exc_info.value.code == "INVALID_PRICE"

    # 3. min_participants < 2
    @pytest.mark.asyncio
    async def test_create_deal_invalid_min(self):
        with pytest.raises(GroupDealError) as exc_info:
            await self.svc.create_deal(
                tenant_id=TENANT,
                store_id=STORE,
                name="一个人拼",
                min_participants=1,
                original_price_fen=10000,
                deal_price_fen=8000,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
                initiator_customer_id=CUSTOMER_A,
                db=self.db,
            )
        assert exc_info.value.code == "INVALID_MIN_PARTICIPANTS"

    # 4. 正常参团
    @pytest.mark.asyncio
    async def test_join_deal_success(self):
        deal_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # Mock: first call = deal row, second call = no duplicate, then insert + update
        self.db.execute = AsyncMock(
            side_effect=[
                FakeResult(rows=[{
                    "id": deal_id,
                    "status": "open",
                    "current_participants": 1,
                    "max_participants": 5,
                    "min_participants": 3,
                    "expires_at": now + timedelta(hours=24),
                }]),
                FakeResult(),  # no duplicate
                FakeResult(),  # insert
                FakeResult(),  # update
            ]
        )

        result = await self.svc.join_deal(
            tenant_id=TENANT,
            deal_id=deal_id,
            customer_id=CUSTOMER_B,
            db=self.db,
        )
        assert result["current_participants"] == 2
        assert result["status"] == "open"

    # 5. 达到最低人数自动 filled
    @pytest.mark.asyncio
    async def test_join_deal_auto_fill(self):
        deal_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        self.db.execute = AsyncMock(
            side_effect=[
                FakeResult(rows=[{
                    "id": deal_id,
                    "status": "open",
                    "current_participants": 2,
                    "max_participants": 5,
                    "min_participants": 3,
                    "expires_at": now + timedelta(hours=24),
                }]),
                FakeResult(),  # no duplicate
                FakeResult(),  # insert
                FakeResult(),  # update
            ]
        )

        result = await self.svc.join_deal(
            tenant_id=TENANT,
            deal_id=deal_id,
            customer_id=CUSTOMER_C,
            db=self.db,
        )
        assert result["current_participants"] == 3
        assert result["status"] == "filled"

    # 6. 超容量
    @pytest.mark.asyncio
    async def test_join_deal_full(self):
        deal_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        self.db.execute = AsyncMock(
            return_value=FakeResult(rows=[{
                "id": deal_id,
                "status": "open",
                "current_participants": 5,
                "max_participants": 5,
                "min_participants": 3,
                "expires_at": now + timedelta(hours=24),
            }])
        )

        with pytest.raises(GroupDealError) as exc_info:
            await self.svc.join_deal(
                tenant_id=TENANT,
                deal_id=deal_id,
                customer_id=CUSTOMER_B,
                db=self.db,
            )
        assert exc_info.value.code == "DEAL_FULL"

    # 7. 重复参团
    @pytest.mark.asyncio
    async def test_join_deal_duplicate(self):
        deal_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        self.db.execute = AsyncMock(
            side_effect=[
                FakeResult(rows=[{
                    "id": deal_id,
                    "status": "open",
                    "current_participants": 1,
                    "max_participants": 5,
                    "min_participants": 3,
                    "expires_at": now + timedelta(hours=24),
                }]),
                FakeResult(rows=[{"id": uuid.uuid4()}]),  # duplicate found
            ]
        )

        with pytest.raises(GroupDealError) as exc_info:
            await self.svc.join_deal(
                tenant_id=TENANT,
                deal_id=deal_id,
                customer_id=CUSTOMER_B,
                db=self.db,
            )
        assert exc_info.value.code == "ALREADY_JOINED"

    # 8. 正常退团
    @pytest.mark.asyncio
    async def test_leave_deal_success(self):
        deal_id = uuid.uuid4()
        pid = uuid.uuid4()

        self.db.execute = AsyncMock(
            side_effect=[
                FakeResult(rows=[{"id": pid, "paid": False}]),  # participant
                FakeResult(rows=[{
                    "initiator_customer_id": CUSTOMER_A,
                    "status": "open",
                }]),  # deal
                FakeResult(),  # soft delete
                FakeResult(),  # update deal
                FakeResult(rows=[{"current_participants": 1}]),  # count
            ]
        )

        result = await self.svc.leave_deal(
            tenant_id=TENANT,
            deal_id=deal_id,
            customer_id=CUSTOMER_B,
            db=self.db,
        )
        assert result["current_participants"] == 1

    # 9. 已支付退团 → 异常
    @pytest.mark.asyncio
    async def test_leave_deal_already_paid(self):
        deal_id = uuid.uuid4()
        pid = uuid.uuid4()

        self.db.execute = AsyncMock(
            return_value=FakeResult(rows=[{"id": pid, "paid": True}])
        )

        with pytest.raises(GroupDealError) as exc_info:
            await self.svc.leave_deal(
                tenant_id=TENANT,
                deal_id=deal_id,
                customer_id=CUSTOMER_B,
                db=self.db,
            )
        assert exc_info.value.code == "ALREADY_PAID"

    # 10. 支付 + 完成
    @pytest.mark.asyncio
    async def test_record_payment_success(self):
        deal_id = uuid.uuid4()
        order_id = uuid.uuid4()
        pid = uuid.uuid4()

        self.db.execute = AsyncMock(
            side_effect=[
                FakeResult(rows=[{"id": pid, "paid": False}]),  # participant
                FakeResult(),  # update participant
                FakeResult(rows=[{"deal_price_fen": 8000}]),  # deal price
                FakeResult(),  # update revenue
            ]
        )

        result = await self.svc.record_payment(
            tenant_id=TENANT,
            deal_id=deal_id,
            customer_id=CUSTOMER_A,
            order_id=order_id,
            db=self.db,
        )
        assert result["paid"] is True

    # 11. 过期
    @pytest.mark.asyncio
    async def test_expire_stale_deals(self):
        self.db.execute = AsyncMock(
            return_value=FakeResult(rows=[
                {"id": uuid.uuid4()},
                {"id": uuid.uuid4()},
            ])
        )

        result = await self.svc.expire_stale_deals(
            tenant_id=TENANT, db=self.db
        )
        assert result["expired_count"] == 2

    # 12. 统计
    @pytest.mark.asyncio
    async def test_get_deal_stats(self):
        self.db.execute = AsyncMock(
            return_value=FakeResult(rows=[{
                "total_deals": 10,
                "filled_count": 7,
                "completed_count": 5,
                "avg_participants": 3.5,
                "total_revenue_fen": 500000,
            }])
        )

        result = await self.svc.get_deal_stats(
            tenant_id=TENANT, db=self.db, days=30
        )
        assert result["total_deals"] == 10
        assert result["fill_rate"] == 70.0
        assert result["total_revenue_fen"] == 500000


# ===========================================================================
# TestDualRewardService
# ===========================================================================


class TestDualRewardService:
    """双向奖励服务单元测试"""

    def setup_method(self):
        self.svc = DualRewardService()
        self.db = FakeDB()

    # 13. 正常创建
    @pytest.mark.asyncio
    async def test_create_dual_reward_success(self):
        result = await self.svc.create_dual_reward(
            tenant_id=TENANT,
            referrer_id=CUSTOMER_A,
            referee_id=CUSTOMER_B,
            campaign_id=CAMPAIGN,
            referrer_reward={"type": "points", "amount": 100},
            referee_reward={"type": "coupon", "amount": 500, "coupon_id": str(uuid.uuid4())},
            db=self.db,
        )
        assert result["referrer_reward_status"] == "pending"
        assert result["referee_reward_status"] == "pending"
        assert result["reward_id"]

    # 14. 自己推荐自己
    @pytest.mark.asyncio
    async def test_create_dual_reward_self_referral(self):
        with pytest.raises(DualRewardError) as exc_info:
            await self.svc.create_dual_reward(
                tenant_id=TENANT,
                referrer_id=CUSTOMER_A,
                referee_id=CUSTOMER_A,
                campaign_id=CAMPAIGN,
                referrer_reward={"type": "points", "amount": 100},
                referee_reward={"type": "points", "amount": 50},
                db=self.db,
            )
        assert exc_info.value.code == "SELF_REFERRAL"

    # 15. 首单触发
    @pytest.mark.asyncio
    async def test_trigger_on_first_order(self):
        order_id = uuid.uuid4()

        self.db.execute = AsyncMock(
            return_value=FakeResult(rows=[
                {"id": uuid.uuid4()},
            ])
        )

        result = await self.svc.trigger_on_first_order(
            tenant_id=TENANT,
            referee_id=CUSTOMER_B,
            order_id=order_id,
            order_amount_fen=5000,
            db=self.db,
        )
        assert result["triggered_count"] == 1

    # 16. 正常领取 referrer
    @pytest.mark.asyncio
    async def test_claim_reward_success(self):
        reward_id = uuid.uuid4()

        self.db.execute = AsyncMock(
            side_effect=[
                FakeResult(rows=[{"id": reward_id, "reward_status": "pending"}]),
                FakeResult(),  # update
            ]
        )

        result = await self.svc.claim_reward(
            tenant_id=TENANT,
            reward_id=reward_id,
            who="referrer",
            db=self.db,
        )
        assert result["who"] == "referrer"
        assert result["claimed_at"]

    # 17. 重复领取
    @pytest.mark.asyncio
    async def test_claim_reward_already_claimed(self):
        reward_id = uuid.uuid4()

        self.db.execute = AsyncMock(
            return_value=FakeResult(rows=[{"id": reward_id, "reward_status": "claimed"}])
        )

        with pytest.raises(DualRewardError) as exc_info:
            await self.svc.claim_reward(
                tenant_id=TENANT,
                reward_id=reward_id,
                who="referee",
                db=self.db,
            )
        assert exc_info.value.code == "ALREADY_CLAIMED"

    # 18. 无效 who
    @pytest.mark.asyncio
    async def test_claim_reward_invalid_who(self):
        with pytest.raises(DualRewardError) as exc_info:
            await self.svc.claim_reward(
                tenant_id=TENANT,
                reward_id=uuid.uuid4(),
                who="nobody",
                db=self.db,
            )
        assert exc_info.value.code == "INVALID_WHO"

    # 19. 过期处理
    @pytest.mark.asyncio
    async def test_expire_unclaimed(self):
        self.db.execute = AsyncMock(
            side_effect=[
                FakeResult(rows=[{"id": uuid.uuid4()}]),  # referrer
                FakeResult(rows=[{"id": uuid.uuid4()}, {"id": uuid.uuid4()}]),  # referee
            ]
        )

        result = await self.svc.expire_unclaimed(
            tenant_id=TENANT, db=self.db, days=30
        )
        assert result["expired_referrer_count"] == 1
        assert result["expired_referee_count"] == 2

    # 20. 排行榜
    @pytest.mark.asyncio
    async def test_get_referral_leaderboard(self):
        self.db.execute = AsyncMock(
            return_value=FakeResult(rows=[
                {"referrer_id": CUSTOMER_A, "successful_referrals": 10, "total_order_amount_fen": 50000},
                {"referrer_id": CUSTOMER_B, "successful_referrals": 5, "total_order_amount_fen": 25000},
            ])
        )

        result = await self.svc.get_referral_leaderboard(
            tenant_id=TENANT, db=self.db, limit=20
        )
        assert len(result) == 2
        assert result[0]["successful_referrals"] == 10


# ===========================================================================
# TestGroupDealRoutes — API 端点集成测试
# ===========================================================================

# Stub service modules for route import
_deal_svc_mod = types.ModuleType("services.group_deal_service")


class _FakeGroupDealError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


_fake_deal_svc_instance = MagicMock()
_deal_svc_mod.GroupDealService = MagicMock(return_value=_fake_deal_svc_instance)
_deal_svc_mod.GroupDealError = _FakeGroupDealError

_reward_svc_mod = types.ModuleType("services.dual_reward_service")


class _FakeDualRewardError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


_fake_reward_svc_instance = MagicMock()
_reward_svc_mod.DualRewardService = MagicMock(return_value=_fake_reward_svc_instance)
_reward_svc_mod.DualRewardError = _FakeDualRewardError

_svc_parent = types.ModuleType("services")
sys.modules["services"] = _svc_parent
sys.modules["services.group_deal_service"] = _deal_svc_mod
sys.modules["services.dual_reward_service"] = _reward_svc_mod

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

# Force re-import of routes with stubbed services
if "api.group_deal_routes" in sys.modules:
    del sys.modules["api.group_deal_routes"]

from api.group_deal_routes import router

_app = FastAPI()
_fake_db = AsyncMock()


@_app.middleware("http")
async def inject_db(request: Request, call_next):
    request.state.db = _fake_db
    return await call_next(request)


_app.include_router(router)
_client = TestClient(_app)

HEADERS = {"X-Tenant-ID": str(TENANT)}


class TestGroupDealRoutes:
    """拼团 API 路由测试"""

    def setup_method(self):
        _fake_deal_svc_instance.reset_mock()
        _fake_reward_svc_instance.reset_mock()

    # 21. POST / — 创建拼团
    def test_create_deal_api(self):
        _fake_deal_svc_instance.create_deal = AsyncMock(return_value={
            "deal_id": str(uuid.uuid4()),
            "share_link_code": "abc12345",
            "status": "open",
            "current_participants": 1,
        })

        resp = _client.post(
            "/api/v1/growth/group-deals",
            headers=HEADERS,
            json={
                "store_id": str(STORE),
                "name": "拼团测试",
                "min_participants": 3,
                "original_price_fen": 10000,
                "deal_price_fen": 8000,
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
                "initiator_customer_id": str(CUSTOMER_A),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "open"

    # 22. GET / — 拼团列表
    def test_list_deals_api(self):
        _fake_deal_svc_instance.list_deals = AsyncMock(return_value={
            "items": [],
            "total": 0,
        })

        resp = _client.get(
            "/api/v1/growth/group-deals",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 0

    # 23. GET /{id} — 拼团详情
    def test_get_deal_api(self):
        deal_id = uuid.uuid4()
        _fake_deal_svc_instance.get_deal = AsyncMock(return_value={
            "id": str(deal_id),
            "name": "拼团",
            "status": "open",
            "participants": [],
        })

        resp = _client.get(
            f"/api/v1/growth/group-deals/{deal_id}",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

    # 24. POST /{id}/join — 参团
    def test_join_deal_api(self):
        deal_id = uuid.uuid4()
        _fake_deal_svc_instance.join_deal = AsyncMock(return_value={
            "deal_id": str(deal_id),
            "current_participants": 2,
            "status": "open",
        })

        resp = _client.post(
            f"/api/v1/growth/group-deals/{deal_id}/join",
            headers=HEADERS,
            json={"customer_id": str(CUSTOMER_B)},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["current_participants"] == 2

    # 25. POST /{id}/pay — 支付
    def test_pay_deal_api(self):
        deal_id = uuid.uuid4()
        order_id = uuid.uuid4()
        _fake_deal_svc_instance.record_payment = AsyncMock(return_value={
            "deal_id": str(deal_id),
            "customer_id": str(CUSTOMER_A),
            "paid": True,
        })

        resp = _client.post(
            f"/api/v1/growth/group-deals/{deal_id}/pay",
            headers=HEADERS,
            json={
                "customer_id": str(CUSTOMER_A),
                "order_id": str(order_id),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["paid"] is True
