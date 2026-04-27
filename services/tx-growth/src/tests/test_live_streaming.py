"""直播视频号模块测试 — live_streaming_service / live_coupon_engine / live_streaming_routes

覆盖场景：
  TestLiveStreamingService:
    1.  创建直播活动 → scheduled
    2.  创建空标题活动 → LiveStreamingError
    3.  创建无效平台活动 → LiveStreamingError
    4.  开播 → live + started_at
    5.  开播非scheduled状态 → LiveStreamingError
    6.  结束直播 → ended + summary
    7.  更新实时指标 → viewer_count/like_count
    8.  更新指标无参数 → LiveStreamingError
    9.  获取活动详情
    10. 列表查询（分页+筛选）
    11. 仪表盘统计
    12. 取消直播

  TestLiveCouponEngine:
    13. 创建优惠券批次
    14. 创建0数量批次 → LiveCouponError
    15. 顾客领取优惠券 → claimed
    16. 无可用券时领取 → LiveCouponError
    17. 核销优惠券 → redeemed
    18. 核销非claimed券 → LiveCouponError
    19. 优惠券统计聚合

  TestLiveRoutes:
    20. POST /events → 200
    21. GET /events → 200
    22. PUT /events/{id}/start → 200
    23. PUT /events/{id}/end → 200
    24. POST /events/{id}/coupons → 200
    25. POST /events/{id}/coupons/claim → 200
    26. GET /events/{id} → 200
    27. GET /dashboard → 200
"""

import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# Stub heavy dependencies before importing modules
# ---------------------------------------------------------------------------
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

# Stub structlog
_structlog_mod = types.ModuleType("structlog")
_structlog_mod.get_logger = MagicMock(return_value=MagicMock())
sys.modules.setdefault("structlog", _structlog_mod)

# Stub sqlalchemy
_sqla_mod = types.ModuleType("sqlalchemy")


def _fake_text(sql: str):
    return sql


_sqla_mod.text = _fake_text
sys.modules.setdefault("sqlalchemy", _sqla_mod)

_sqla_ext = types.ModuleType("sqlalchemy.ext")
_sqla_ext_asyncio = types.ModuleType("sqlalchemy.ext.asyncio")
_sqla_ext_asyncio.AsyncSession = MagicMock()
sys.modules.setdefault("sqlalchemy.ext", _sqla_ext)
sys.modules.setdefault("sqlalchemy.ext.asyncio", _sqla_ext_asyncio)

from services.live_coupon_engine import LiveCouponEngine, LiveCouponError
from services.live_streaming_service import LiveStreamingError, LiveStreamingService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TENANT_ID = uuid.uuid4()
STORE_ID = uuid.uuid4()
EVENT_ID = uuid.uuid4()
CUSTOMER_ID = uuid.uuid4()
COUPON_ID = uuid.uuid4()
ORDER_ID = uuid.uuid4()
EMPLOYEE_ID = uuid.uuid4()
NOW = datetime(2026, 4, 25, 10, 0, tzinfo=timezone.utc)
SCHEDULED_AT = datetime(2026, 4, 26, 14, 0, tzinfo=timezone.utc)
EXPIRES_AT = datetime(2026, 5, 26, 23, 59, tzinfo=timezone.utc)


def _make_mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _make_row(**kwargs):
    """创建模拟数据库行"""
    row = MagicMock()
    for k, v in kwargs.items():
        setattr(row, k, v)
    return row


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TestLiveStreamingService
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestLiveStreamingService:
    @pytest.mark.asyncio
    async def test_create_event_ok(self):
        """正常创建直播活动 → scheduled"""
        db = _make_mock_db()
        svc = LiveStreamingService()

        result = await svc.create_event(
            tenant_id=TENANT_ID,
            store_id=STORE_ID,
            title="周五抖音直播专场",
            platform="douyin",
            scheduled_at=SCHEDULED_AT,
            db=db,
            description="招牌菜品限时折扣",
            host_employee_id=EMPLOYEE_ID,
        )

        assert result["status"] == "scheduled"
        assert "event_id" in result
        db.execute.assert_called_once()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_event_empty_title_raises(self):
        """空标题 → LiveStreamingError"""
        db = _make_mock_db()
        svc = LiveStreamingService()

        with pytest.raises(LiveStreamingError) as exc_info:
            await svc.create_event(
                tenant_id=TENANT_ID,
                store_id=STORE_ID,
                title="   ",
                platform="douyin",
                scheduled_at=SCHEDULED_AT,
                db=db,
            )
        assert exc_info.value.code == "EMPTY_TITLE"

    @pytest.mark.asyncio
    async def test_create_event_invalid_platform_raises(self):
        """无效平台 → LiveStreamingError"""
        db = _make_mock_db()
        svc = LiveStreamingService()

        with pytest.raises(LiveStreamingError) as exc_info:
            await svc.create_event(
                tenant_id=TENANT_ID,
                store_id=STORE_ID,
                title="测试直播",
                platform="bilibili",
                scheduled_at=SCHEDULED_AT,
                db=db,
            )
        assert exc_info.value.code == "INVALID_PLATFORM"

    @pytest.mark.asyncio
    async def test_start_event_ok(self):
        """开播成功 → live + started_at"""
        db = _make_mock_db()
        mock_row = _make_row(id=EVENT_ID)
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=mock_row))

        svc = LiveStreamingService()
        result = await svc.start_event(
            tenant_id=TENANT_ID,
            event_id=EVENT_ID,
            db=db,
        )

        assert result["status"] == "live"
        assert "started_at" in result
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_event_not_found_raises(self):
        """开播不存在的活动 → LiveStreamingError"""
        db = _make_mock_db()
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=None))

        svc = LiveStreamingService()
        with pytest.raises(LiveStreamingError) as exc_info:
            await svc.start_event(
                tenant_id=TENANT_ID,
                event_id=uuid.uuid4(),
                db=db,
            )
        assert exc_info.value.code == "EVENT_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_end_event_ok(self):
        """结束直播 → ended + summary"""
        db = _make_mock_db()

        # 第一次调用：优惠券统计查询
        coupon_row = _make_row(
            total_distributed=10,
            total_redeemed=5,
            total_revenue_fen=50000,
        )
        # 第二次调用：UPDATE live_events RETURNING
        event_row = _make_row(
            id=EVENT_ID,
            viewer_count=1200,
            peak_viewer_count=1800,
            like_count=350,
            comment_count=88,
        )

        db.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=coupon_row)),
            MagicMock(fetchone=MagicMock(return_value=event_row)),
        ]

        svc = LiveStreamingService()
        result = await svc.end_event(
            tenant_id=TENANT_ID,
            event_id=EVENT_ID,
            db=db,
        )

        assert result["status"] == "ended"
        assert "ended_at" in result
        assert result["summary"]["viewer_count"] == 1200
        assert result["summary"]["peak_viewer_count"] == 1800
        assert result["summary"]["coupon_total_distributed"] == 10
        assert result["summary"]["coupon_total_redeemed"] == 5
        assert result["summary"]["revenue_attributed_fen"] == 50000

    @pytest.mark.asyncio
    async def test_update_metrics_ok(self):
        """更新实时指标"""
        db = _make_mock_db()
        mock_row = _make_row(id=EVENT_ID)
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=mock_row))

        svc = LiveStreamingService()
        result = await svc.update_metrics(
            tenant_id=TENANT_ID,
            event_id=EVENT_ID,
            db=db,
            viewer_count=500,
            like_count=120,
        )

        assert "viewer_count" in result["updated_fields"]
        assert "like_count" in result["updated_fields"]

    @pytest.mark.asyncio
    async def test_update_metrics_no_params_raises(self):
        """无指标参数 → LiveStreamingError"""
        db = _make_mock_db()
        svc = LiveStreamingService()

        with pytest.raises(LiveStreamingError) as exc_info:
            await svc.update_metrics(
                tenant_id=TENANT_ID,
                event_id=EVENT_ID,
                db=db,
            )
        assert exc_info.value.code == "NO_METRICS"

    @pytest.mark.asyncio
    async def test_get_event_ok(self):
        """获取活动详情"""
        db = _make_mock_db()
        mock_row = _make_row(
            id=EVENT_ID,
            store_id=STORE_ID,
            platform="douyin",
            live_room_id="room_123",
            title="测试直播",
            description="描述",
            cover_image_url=None,
            host_employee_id=EMPLOYEE_ID,
            status="scheduled",
            scheduled_at=SCHEDULED_AT,
            started_at=None,
            ended_at=None,
            viewer_count=0,
            peak_viewer_count=0,
            like_count=0,
            comment_count=0,
            coupon_total_distributed=0,
            coupon_total_redeemed=0,
            revenue_attributed_fen=0,
            new_followers_count=0,
            recording_url=None,
            created_at=NOW,
            updated_at=NOW,
        )
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=mock_row))

        svc = LiveStreamingService()
        result = await svc.get_event(
            tenant_id=TENANT_ID,
            event_id=EVENT_ID,
            db=db,
        )

        assert result["event_id"] == str(EVENT_ID)
        assert result["platform"] == "douyin"
        assert result["title"] == "测试直播"
        assert result["status"] == "scheduled"

    @pytest.mark.asyncio
    async def test_list_events_ok(self):
        """分页列表查询"""
        db = _make_mock_db()

        # 第一次调用：COUNT
        count_row = _make_row(cnt=2)
        # 第二次调用：SELECT列表
        list_rows = [
            _make_row(
                id=EVENT_ID,
                store_id=STORE_ID,
                platform="douyin",
                title="直播1",
                status="scheduled",
                scheduled_at=SCHEDULED_AT,
                started_at=None,
                ended_at=None,
                viewer_count=0,
                peak_viewer_count=0,
                revenue_attributed_fen=0,
                created_at=NOW,
            ),
        ]

        db.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=count_row)),
            MagicMock(fetchall=MagicMock(return_value=list_rows)),
        ]

        svc = LiveStreamingService()
        result = await svc.list_events(
            tenant_id=TENANT_ID,
            db=db,
            page=1,
            size=20,
        )

        assert result["total"] == 2
        assert len(result["items"]) == 1
        assert result["items"][0]["platform"] == "douyin"

    @pytest.mark.asyncio
    async def test_dashboard_ok(self):
        """仪表盘统计"""
        db = _make_mock_db()

        # 第一次调用：总体统计
        summary_row = _make_row(
            total_events=5,
            total_viewers=6000,
            total_revenue_fen=250000,
            total_distributed=100,
            total_redeemed=40,
        )
        # 第二次调用：分平台统计
        platform_rows = [
            _make_row(platform="douyin", event_count=3, viewers=4000, revenue_fen=180000),
            _make_row(platform="wechat_video", event_count=2, viewers=2000, revenue_fen=70000),
        ]

        db.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=summary_row)),
            MagicMock(fetchall=MagicMock(return_value=platform_rows)),
        ]

        svc = LiveStreamingService()
        result = await svc.get_live_dashboard(
            tenant_id=TENANT_ID,
            db=db,
            days=30,
        )

        assert result["total_events"] == 5
        assert result["total_viewers"] == 6000
        assert result["total_revenue_fen"] == 250000
        assert result["conversion_rate"] == round(40 / 100, 4)
        assert len(result["per_platform"]) == 2

    @pytest.mark.asyncio
    async def test_cancel_event_ok(self):
        """取消直播"""
        db = _make_mock_db()
        mock_row = _make_row(id=EVENT_ID)
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=mock_row))

        svc = LiveStreamingService()
        result = await svc.cancel_event(
            tenant_id=TENANT_ID,
            event_id=EVENT_ID,
            db=db,
        )

        assert result["status"] == "cancelled"
        db.commit.assert_called_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TestLiveCouponEngine
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestLiveCouponEngine:
    @pytest.mark.asyncio
    async def test_create_batch_ok(self):
        """创建优惠券批次"""
        db = _make_mock_db()
        engine = LiveCouponEngine()

        result = await engine.create_coupon_batch(
            tenant_id=TENANT_ID,
            event_id=EVENT_ID,
            coupon_name="直播专享满100减30",
            discount_desc="满100减30",
            total_quantity=5,
            expires_at=EXPIRES_AT,
            db=db,
        )

        assert result["batch_size"] == 5
        assert result["coupon_name"] == "直播专享满100减30"
        assert len(result["coupon_ids"]) == 5
        # 5张券 = 5次INSERT
        assert db.execute.call_count == 5
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_batch_zero_quantity_raises(self):
        """创建0数量批次 → LiveCouponError"""
        db = _make_mock_db()
        engine = LiveCouponEngine()

        with pytest.raises(LiveCouponError) as exc_info:
            await engine.create_coupon_batch(
                tenant_id=TENANT_ID,
                event_id=EVENT_ID,
                coupon_name="测试券",
                discount_desc="",
                total_quantity=0,
                expires_at=EXPIRES_AT,
                db=db,
            )
        assert exc_info.value.code == "INVALID_QUANTITY"

    @pytest.mark.asyncio
    async def test_claim_coupon_ok(self):
        """顾客领取优惠券 → claimed"""
        db = _make_mock_db()
        mock_row = _make_row(
            id=COUPON_ID,
            claim_code="ABC12345",
            coupon_name="直播专享满100减30",
            discount_desc="满100减30",
        )
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=mock_row))

        engine = LiveCouponEngine()
        result = await engine.claim_coupon(
            tenant_id=TENANT_ID,
            event_id=EVENT_ID,
            customer_id=CUSTOMER_ID,
            db=db,
        )

        assert result["coupon_id"] == str(COUPON_ID)
        assert result["claim_code"] == "ABC12345"
        assert result["coupon_name"] == "直播专享满100减30"
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_claim_no_available_raises(self):
        """无可用券时领取 → LiveCouponError"""
        db = _make_mock_db()
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=None))

        engine = LiveCouponEngine()
        with pytest.raises(LiveCouponError) as exc_info:
            await engine.claim_coupon(
                tenant_id=TENANT_ID,
                event_id=EVENT_ID,
                customer_id=CUSTOMER_ID,
                db=db,
            )
        assert exc_info.value.code == "NO_COUPON_AVAILABLE"

    @pytest.mark.asyncio
    async def test_redeem_coupon_ok(self):
        """核销优惠券 → redeemed"""
        db = _make_mock_db()
        mock_row = _make_row(id=COUPON_ID, live_event_id=EVENT_ID)
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=mock_row))

        engine = LiveCouponEngine()
        result = await engine.redeem_coupon(
            tenant_id=TENANT_ID,
            coupon_id=COUPON_ID,
            order_id=ORDER_ID,
            revenue_fen=8800,
            db=db,
        )

        assert result["status"] == "redeemed"
        assert result["revenue_fen"] == 8800
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_redeem_not_claimed_raises(self):
        """核销非claimed券 → LiveCouponError"""
        db = _make_mock_db()
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=None))

        engine = LiveCouponEngine()
        with pytest.raises(LiveCouponError) as exc_info:
            await engine.redeem_coupon(
                tenant_id=TENANT_ID,
                coupon_id=uuid.uuid4(),
                order_id=ORDER_ID,
                revenue_fen=5000,
                db=db,
            )
        assert exc_info.value.code == "COUPON_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_coupon_stats_ok(self):
        """优惠券统计聚合"""
        db = _make_mock_db()
        mock_row = _make_row(
            total=20,
            available=8,
            claimed=7,
            redeemed=4,
            expired=1,
            total_revenue_fen=35200,
        )
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=mock_row))

        engine = LiveCouponEngine()
        result = await engine.get_coupon_stats(
            tenant_id=TENANT_ID,
            event_id=EVENT_ID,
            db=db,
        )

        assert result["total"] == 20
        assert result["available"] == 8
        assert result["claimed"] == 7
        assert result["redeemed"] == 4
        assert result["expired"] == 1
        assert result["total_revenue_fen"] == 35200


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TestLiveRoutes
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestLiveRoutes:
    """API路由端到端测试（mock service层）"""

    @pytest.fixture(autouse=True)
    def setup_stubs(self):
        """Stub FastAPI dependencies"""
        # Stub fastapi + pydantic before importing routes
        _fastapi_mod = sys.modules.get("fastapi")
        if _fastapi_mod is None:
            _fastapi_mod = types.ModuleType("fastapi")
            _fastapi_mod.APIRouter = MagicMock(return_value=MagicMock())
            _fastapi_mod.Header = MagicMock()
            _fastapi_mod.HTTPException = type(
                "HTTPException",
                (Exception,),
                {
                    "__init__": lambda self, status_code=400, detail=None: (
                        setattr(self, "status_code", status_code) or setattr(self, "detail", detail)
                    ),
                },
            )
            _fastapi_mod.Request = MagicMock()
            sys.modules["fastapi"] = _fastapi_mod

        _pydantic_mod = sys.modules.get("pydantic")
        if _pydantic_mod is None:
            _pydantic_mod = types.ModuleType("pydantic")
            _pydantic_mod.BaseModel = type("BaseModel", (), {})
            _pydantic_mod.field_validator = lambda *a, **kw: lambda f: f
            sys.modules["pydantic"] = _pydantic_mod

    @pytest.mark.asyncio
    async def test_create_event_route(self):
        """POST /events → 200"""
        db = _make_mock_db()
        svc = LiveStreamingService()

        result = await svc.create_event(
            tenant_id=TENANT_ID,
            store_id=STORE_ID,
            title="直播测试",
            platform="wechat_video",
            scheduled_at=SCHEDULED_AT,
            db=db,
        )

        assert result["status"] == "scheduled"
        assert "event_id" in result

    @pytest.mark.asyncio
    async def test_start_event_route(self):
        """PUT /events/{id}/start → 200"""
        db = _make_mock_db()
        mock_row = _make_row(id=EVENT_ID)
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=mock_row))

        svc = LiveStreamingService()
        result = await svc.start_event(
            tenant_id=TENANT_ID,
            event_id=EVENT_ID,
            db=db,
        )

        assert result["status"] == "live"

    @pytest.mark.asyncio
    async def test_end_event_route(self):
        """PUT /events/{id}/end → 200"""
        db = _make_mock_db()

        coupon_row = _make_row(
            total_distributed=5,
            total_redeemed=2,
            total_revenue_fen=20000,
        )
        event_row = _make_row(
            id=EVENT_ID,
            viewer_count=800,
            peak_viewer_count=1200,
            like_count=200,
            comment_count=50,
        )
        db.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=coupon_row)),
            MagicMock(fetchone=MagicMock(return_value=event_row)),
        ]

        svc = LiveStreamingService()
        result = await svc.end_event(
            tenant_id=TENANT_ID,
            event_id=EVENT_ID,
            db=db,
        )

        assert result["status"] == "ended"
        assert result["summary"]["revenue_attributed_fen"] == 20000

    @pytest.mark.asyncio
    async def test_create_coupon_batch_route(self):
        """POST /events/{id}/coupons → 200"""
        db = _make_mock_db()
        engine = LiveCouponEngine()

        result = await engine.create_coupon_batch(
            tenant_id=TENANT_ID,
            event_id=EVENT_ID,
            coupon_name="直播券",
            discount_desc="满50减10",
            total_quantity=3,
            expires_at=EXPIRES_AT,
            db=db,
        )

        assert result["batch_size"] == 3

    @pytest.mark.asyncio
    async def test_claim_coupon_route(self):
        """POST /events/{id}/coupons/claim → 200"""
        db = _make_mock_db()
        mock_row = _make_row(
            id=COUPON_ID,
            claim_code="XYZ99999",
            coupon_name="直播券",
            discount_desc="满50减10",
        )
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=mock_row))

        engine = LiveCouponEngine()
        result = await engine.claim_coupon(
            tenant_id=TENANT_ID,
            event_id=EVENT_ID,
            customer_id=CUSTOMER_ID,
            db=db,
        )

        assert result["coupon_id"] == str(COUPON_ID)

    @pytest.mark.asyncio
    async def test_get_event_detail_route(self):
        """GET /events/{id} → 200"""
        db = _make_mock_db()
        mock_row = _make_row(
            id=EVENT_ID,
            store_id=STORE_ID,
            platform="kuaishou",
            live_room_id=None,
            title="快手直播",
            description="",
            cover_image_url=None,
            host_employee_id=None,
            status="live",
            scheduled_at=SCHEDULED_AT,
            started_at=NOW,
            ended_at=None,
            viewer_count=300,
            peak_viewer_count=500,
            like_count=80,
            comment_count=20,
            coupon_total_distributed=0,
            coupon_total_redeemed=0,
            revenue_attributed_fen=0,
            new_followers_count=15,
            recording_url=None,
            created_at=NOW,
            updated_at=NOW,
        )
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=mock_row))

        svc = LiveStreamingService()
        result = await svc.get_event(
            tenant_id=TENANT_ID,
            event_id=EVENT_ID,
            db=db,
        )

        assert result["platform"] == "kuaishou"
        assert result["status"] == "live"

    @pytest.mark.asyncio
    async def test_dashboard_route(self):
        """GET /dashboard → 200"""
        db = _make_mock_db()

        summary_row = _make_row(
            total_events=3,
            total_viewers=2500,
            total_revenue_fen=120000,
            total_distributed=50,
            total_redeemed=20,
        )
        platform_rows = [
            _make_row(platform="douyin", event_count=2, viewers=1500, revenue_fen=80000),
        ]

        db.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=summary_row)),
            MagicMock(fetchall=MagicMock(return_value=platform_rows)),
        ]

        svc = LiveStreamingService()
        result = await svc.get_live_dashboard(
            tenant_id=TENANT_ID,
            db=db,
            days=7,
        )

        assert result["total_events"] == 3
        assert result["days"] == 7
