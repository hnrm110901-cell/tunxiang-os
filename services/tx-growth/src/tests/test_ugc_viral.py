"""UGC裂变病毒引擎测试 — ugc_routes / ugc_service / photo_reviewer / viral_tracker

覆盖场景：
  TestUGCService:
    1.  提交UGC（正常） → pending_review
    2.  提交UGC（空媒体） → 400
    3.  审批通过 → published + 50积分
    4.  拒绝 → rejected + 拒绝原因
    5.  重复拒绝已审批UGC → 404
    6.  获取门店图墙 → published列表
    7.  获取我的投稿
    8.  编辑精选 → featured + 额外100积分

  TestPhotoReviewer:
    9.  AI评分>=0.7自动通过
    10. AI评分<0.7需人工审核
    11. 空媒体列表 → 异常

  TestViralTracker:
    12. 创建分享链接 → 8位短码
    13. 记录点击
    14. 记录转化
    15. 裂变链路深度追踪（A→B depth=0→1）
    16. 裂变统计聚合

  TestUGCRoutes:
    17. POST /submit → 200
    18. GET /gallery/{store_id} → 200
    19. POST /{ugc_id}/approve → 200
    20. POST /{ugc_id}/reject → 200
    21. GET /my → 200
    22. POST /{ugc_id}/share → 200
    23. GET /viral-stats → 200
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

# Stub httpx
_httpx_mod = types.ModuleType("httpx")
_httpx_mod.AsyncClient = MagicMock()
_httpx_mod.TimeoutException = type("TimeoutException", (Exception,), {})
_httpx_mod.HTTPStatusError = type(
    "HTTPStatusError",
    (Exception,),
    {
        "__init__": lambda self, *a, **kw: None,
        "response": MagicMock(status_code=500),
    },
)
sys.modules.setdefault("httpx", _httpx_mod)

from services.photo_reviewer import PhotoReviewer, PhotoReviewError
from services.ugc_service import POINTS_APPROVED, POINTS_FEATURED, UGCError, UGCService
from services.viral_tracker import ViralTracker, ViralTrackerError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TENANT_ID = uuid.uuid4()
CUSTOMER_ID = uuid.uuid4()
STORE_ID = uuid.uuid4()
UGC_ID = uuid.uuid4()
ORDER_ID = uuid.uuid4()
NOW = datetime(2026, 4, 25, 10, 0, tzinfo=timezone.utc)

SAMPLE_MEDIA = [
    {
        "url": "https://cdn.example.com/photo1.jpg",
        "type": "photo",
        "thumbnail_url": "https://cdn.example.com/photo1_thumb.jpg",
    },
    {
        "url": "https://cdn.example.com/photo2.jpg",
        "type": "photo",
        "thumbnail_url": "https://cdn.example.com/photo2_thumb.jpg",
    },
]


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
# TestUGCService
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestUGCService:
    @pytest.mark.asyncio
    async def test_submit_ok(self):
        """正常提交UGC，返回ugc_id和pending_review状态"""
        db = _make_mock_db()
        svc = UGCService()

        result = await svc.submit(
            tenant_id=TENANT_ID,
            customer_id=CUSTOMER_ID,
            store_id=STORE_ID,
            media_urls=SAMPLE_MEDIA,
            caption="好吃的红烧肉",
            db=db,
            order_id=ORDER_ID,
        )

        assert result["status"] == "pending_review"
        assert "ugc_id" in result
        db.execute.assert_called_once()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_submit_empty_media_raises(self):
        """提交空媒体列表 → UGCError"""
        db = _make_mock_db()
        svc = UGCService()

        with pytest.raises(UGCError) as exc_info:
            await svc.submit(
                tenant_id=TENANT_ID,
                customer_id=CUSTOMER_ID,
                store_id=STORE_ID,
                media_urls=[],
                caption="test",
                db=db,
            )
        assert exc_info.value.code == "EMPTY_MEDIA"

    @pytest.mark.asyncio
    async def test_approve_ok(self):
        """审批通过 → published状态 + 50积分"""
        db = _make_mock_db()
        mock_row = _make_row(
            id=UGC_ID,
            customer_id=CUSTOMER_ID,
            points_awarded=POINTS_APPROVED,
        )
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=mock_row))

        svc = UGCService()
        result = await svc.approve(tenant_id=TENANT_ID, ugc_id=UGC_ID, db=db)

        assert result["status"] == "published"
        assert result["points_awarded"] == POINTS_APPROVED

    @pytest.mark.asyncio
    async def test_approve_not_found(self):
        """审批不存在的UGC → UGCError"""
        db = _make_mock_db()
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=None))

        svc = UGCService()
        with pytest.raises(UGCError) as exc_info:
            await svc.approve(tenant_id=TENANT_ID, ugc_id=UGC_ID, db=db)
        assert exc_info.value.code == "UGC_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_reject_ok(self):
        """拒绝UGC → rejected状态 + 拒绝原因"""
        db = _make_mock_db()
        mock_row = _make_row(id=UGC_ID)
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=mock_row))

        svc = UGCService()
        result = await svc.reject(tenant_id=TENANT_ID, ugc_id=UGC_ID, reason="照片模糊", db=db)

        assert result["status"] == "rejected"
        assert result["rejection_reason"] == "照片模糊"

    @pytest.mark.asyncio
    async def test_reject_already_approved_raises(self):
        """拒绝已审批UGC → UGCError（状态不允许）"""
        db = _make_mock_db()
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=None))

        svc = UGCService()
        with pytest.raises(UGCError):
            await svc.reject(tenant_id=TENANT_ID, ugc_id=UGC_ID, reason="test", db=db)

    @pytest.mark.asyncio
    async def test_get_gallery(self):
        """获取门店图墙 → 返回published列表"""
        db = _make_mock_db()

        # 第一次调用返回count，第二次返回数据行
        mock_count = MagicMock(scalar_one=MagicMock(return_value=1))
        mock_row = _make_row(
            id=UGC_ID,
            customer_id=CUSTOMER_ID,
            media_urls=SAMPLE_MEDIA,
            caption="好吃",
            dish_ids=[],
            ai_quality_score=0.85,
            points_awarded=50,
            view_count=10,
            like_count=5,
            share_count=2,
            featured=False,
            published_at=NOW,
            created_at=NOW,
        )
        mock_data = MagicMock(fetchall=MagicMock(return_value=[mock_row]))
        db.execute.side_effect = [mock_count, mock_data]

        svc = UGCService()
        result = await svc.get_gallery(tenant_id=TENANT_ID, store_id=STORE_ID, db=db, page=1, size=20)

        assert result["total"] == 1
        assert len(result["items"]) == 1
        assert result["items"][0]["ugc_id"] == str(UGC_ID)

    @pytest.mark.asyncio
    async def test_get_my_submissions(self):
        """获取我的投稿列表"""
        db = _make_mock_db()
        mock_row = _make_row(
            id=UGC_ID,
            store_id=STORE_ID,
            media_urls=SAMPLE_MEDIA,
            caption="好吃",
            status="published",
            rejection_reason=None,
            points_awarded=50,
            view_count=10,
            like_count=5,
            share_count=2,
            featured=False,
            published_at=NOW,
            created_at=NOW,
        )
        db.execute.return_value = MagicMock(fetchall=MagicMock(return_value=[mock_row]))

        svc = UGCService()
        result = await svc.get_my_submissions(tenant_id=TENANT_ID, customer_id=CUSTOMER_ID, db=db)

        assert len(result) == 1
        assert result[0]["status"] == "published"

    @pytest.mark.asyncio
    async def test_feature_ok(self):
        """编辑精选 → featured=true + 额外100积分"""
        db = _make_mock_db()
        mock_row = _make_row(
            id=UGC_ID,
            customer_id=CUSTOMER_ID,
            points_awarded=POINTS_APPROVED + POINTS_FEATURED,
        )
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=mock_row))

        svc = UGCService()
        result = await svc.feature(tenant_id=TENANT_ID, ugc_id=UGC_ID, db=db)

        assert result["featured"] is True
        assert result["extra_points"] == POINTS_FEATURED


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TestPhotoReviewer
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestPhotoReviewer:
    @pytest.mark.asyncio
    async def test_auto_approve_high_score(self):
        """AI评分>=0.7 → 自动通过"""
        db = _make_mock_db()
        # mock _call_vision_api
        mock_check_row = _make_row()
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=mock_check_row))

        reviewer = PhotoReviewer()
        reviewer._call_vision_api = AsyncMock(
            return_value={
                "score": 0.85,
                "is_food": True,
                "quality": "high",
                "feedback": "很棒的美食照片",
            }
        )

        result = await reviewer.review_photo(
            tenant_id=TENANT_ID,
            ugc_id=UGC_ID,
            media_urls=SAMPLE_MEDIA,
            db=db,
        )

        assert result["auto_approved"] is True
        assert result["score"] == 0.85
        assert result["is_food"] is True

    @pytest.mark.asyncio
    async def test_manual_review_low_score(self):
        """AI评分<0.7 → 需人工审核"""
        db = _make_mock_db()
        mock_check_row = _make_row()
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=mock_check_row))

        reviewer = PhotoReviewer()
        reviewer._call_vision_api = AsyncMock(
            return_value={
                "score": 0.45,
                "is_food": True,
                "quality": "low",
                "feedback": "照片模糊",
            }
        )

        result = await reviewer.review_photo(
            tenant_id=TENANT_ID,
            ugc_id=UGC_ID,
            media_urls=SAMPLE_MEDIA,
            db=db,
        )

        assert result["auto_approved"] is False
        assert result["score"] == 0.45

    @pytest.mark.asyncio
    async def test_not_food_rejects(self):
        """非食物照片 → 不自动通过（即使分数高）"""
        db = _make_mock_db()
        mock_check_row = _make_row()
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=mock_check_row))

        reviewer = PhotoReviewer()
        reviewer._call_vision_api = AsyncMock(
            return_value={
                "score": 0.8,
                "is_food": False,
                "quality": "high",
                "feedback": "不是食物照片",
            }
        )

        result = await reviewer.review_photo(
            tenant_id=TENANT_ID,
            ugc_id=UGC_ID,
            media_urls=SAMPLE_MEDIA,
            db=db,
        )

        assert result["auto_approved"] is False
        assert result["is_food"] is False

    @pytest.mark.asyncio
    async def test_empty_media_raises(self):
        """空媒体列表 → PhotoReviewError"""
        db = _make_mock_db()
        reviewer = PhotoReviewer()

        with pytest.raises(PhotoReviewError) as exc_info:
            await reviewer.review_photo(
                tenant_id=TENANT_ID,
                ugc_id=UGC_ID,
                media_urls=[],
                db=db,
            )
        assert exc_info.value.code == "EMPTY_MEDIA"

    @pytest.mark.asyncio
    async def test_score_validation_range(self):
        """评分在0-1之间"""
        db = _make_mock_db()
        mock_check_row = _make_row()
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=mock_check_row))

        reviewer = PhotoReviewer()
        reviewer._call_vision_api = AsyncMock(
            return_value={
                "score": 0.72,
                "is_food": True,
                "quality": "medium",
                "feedback": "还行",
            }
        )

        result = await reviewer.review_photo(
            tenant_id=TENANT_ID,
            ugc_id=UGC_ID,
            media_urls=[SAMPLE_MEDIA[0]],
            db=db,
        )

        assert 0.0 <= result["score"] <= 1.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TestViralTracker
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestViralTracker:
    @pytest.mark.asyncio
    async def test_create_share_link(self):
        """创建分享链接 → 返回8位短码"""
        db = _make_mock_db()
        tracker = ViralTracker()

        result = await tracker.create_share_link(
            tenant_id=TENANT_ID,
            customer_id=CUSTOMER_ID,
            ugc_id=UGC_ID,
            channel="wechat",
            db=db,
        )

        assert "share_link_code" in result
        assert len(result["share_link_code"]) == 8
        assert result["depth"] == 0
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_chain_depth_tracking(self):
        """裂变链路深度追踪：A分享depth=0 → B转发depth=1"""
        db = _make_mock_db()
        tracker = ViralTracker()

        # A分享（depth=0）
        result_a = await tracker.create_share_link(
            tenant_id=TENANT_ID,
            customer_id=CUSTOMER_ID,
            ugc_id=UGC_ID,
            channel="wechat",
            db=db,
        )
        assert result_a["depth"] == 0

        # B转发（depth=1）— mock parent查询
        parent_row = _make_row(depth=0)
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=parent_row))

        customer_b = uuid.uuid4()
        result_b = await tracker.create_share_link(
            tenant_id=TENANT_ID,
            customer_id=customer_b,
            ugc_id=UGC_ID,
            channel="moments",
            db=db,
            parent_chain_id=uuid.uuid4(),
        )
        assert result_b["depth"] == 1

    @pytest.mark.asyncio
    async def test_record_click(self):
        """记录点击 → 更新clicked_at"""
        db = _make_mock_db()
        mock_row = _make_row(
            id=uuid.uuid4(),
            tenant_id=TENANT_ID,
            sharer_customer_id=CUSTOMER_ID,
        )
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=mock_row))

        tracker = ViralTracker()
        viewer = uuid.uuid4()
        result = await tracker.record_click(
            share_link_code="abc12345",
            viewer_customer_id=viewer,
            db=db,
        )

        assert result["share_link_code"] == "abc12345"
        assert "clicked_at" in result

    @pytest.mark.asyncio
    async def test_record_click_not_found(self):
        """点击不存在的短链 → ViralTrackerError"""
        db = _make_mock_db()
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=None))

        tracker = ViralTracker()
        with pytest.raises(ViralTrackerError) as exc_info:
            await tracker.record_click(
                share_link_code="notexist",
                viewer_customer_id=None,
                db=db,
            )
        assert exc_info.value.code == "LINK_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_record_conversion(self):
        """记录转化 → 更新订单+金额"""
        db = _make_mock_db()
        mock_row = _make_row(
            id=uuid.uuid4(),
            tenant_id=TENANT_ID,
            sharer_customer_id=CUSTOMER_ID,
        )
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=mock_row))

        tracker = ViralTracker()
        result = await tracker.record_conversion(
            share_link_code="abc12345",
            order_id=ORDER_ID,
            revenue_fen=8800,
            db=db,
        )

        assert result["converted_revenue_fen"] == 8800
        assert result["converted_order_id"] == str(ORDER_ID)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TestViralStats
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestViralStats:
    @pytest.mark.asyncio
    async def test_get_viral_stats(self):
        """裂变统计聚合"""
        db = _make_mock_db()
        mock_row = _make_row(
            total_shares=100,
            total_clicks=60,
            total_conversions=15,
            total_revenue_fen=150000,
            avg_chain_depth=1.2,
        )
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=mock_row))

        tracker = ViralTracker()
        result = await tracker.get_viral_stats(tenant_id=TENANT_ID, db=db, days=30)

        assert result["total_shares"] == 100
        assert result["total_clicks"] == 60
        assert result["total_conversions"] == 15
        assert result["total_revenue_fen"] == 150000
        assert result["conversion_rate"] == round(15 / 60, 4)

    @pytest.mark.asyncio
    async def test_get_top_sharers(self):
        """分享排行榜"""
        db = _make_mock_db()
        mock_rows = [
            _make_row(
                sharer_customer_id=uuid.uuid4(),
                total_shares=50,
                total_clicks=30,
                total_conversions=10,
                total_revenue_fen=80000,
            ),
            _make_row(
                sharer_customer_id=uuid.uuid4(),
                total_shares=30,
                total_clicks=20,
                total_conversions=5,
                total_revenue_fen=40000,
            ),
        ]
        db.execute.return_value = MagicMock(fetchall=MagicMock(return_value=mock_rows))

        tracker = ViralTracker()
        result = await tracker.get_top_sharers(tenant_id=TENANT_ID, db=db, limit=20)

        assert len(result) == 2
        assert result[0]["rank"] == 1
        assert result[0]["total_conversions"] == 10
        assert result[1]["rank"] == 2

    @pytest.mark.asyncio
    async def test_stats_zero_clicks_no_division_error(self):
        """零点击 → conversion_rate为0，不除零异常"""
        db = _make_mock_db()
        mock_row = _make_row(
            total_shares=0,
            total_clicks=0,
            total_conversions=0,
            total_revenue_fen=0,
            avg_chain_depth=0,
        )
        db.execute.return_value = MagicMock(fetchone=MagicMock(return_value=mock_row))

        tracker = ViralTracker()
        result = await tracker.get_viral_stats(tenant_id=TENANT_ID, db=db)

        assert result["conversion_rate"] == 0.0
        assert result["total_shares"] == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TestUGCRoutes (HTTP 层)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Stub service modules for route import
_ugc_svc_mod = types.ModuleType("services.ugc_service")
_ugc_svc_mod.UGCService = MagicMock(return_value=MagicMock())
_ugc_svc_mod.UGCError = UGCError
_svc_parent = sys.modules.get("services") or types.ModuleType("services")
sys.modules.setdefault("services", _svc_parent)
sys.modules["services.ugc_service"] = _ugc_svc_mod

_photo_mod = types.ModuleType("services.photo_reviewer")
_photo_mod.PhotoReviewer = MagicMock(return_value=MagicMock())
_photo_mod.PhotoReviewError = PhotoReviewError
sys.modules["services.photo_reviewer"] = _photo_mod

_viral_mod = types.ModuleType("services.viral_tracker")
_viral_mod.ViralTracker = MagicMock(return_value=MagicMock())
_viral_mod.ViralTrackerError = ViralTrackerError
sys.modules["services.viral_tracker"] = _viral_mod

from api.ugc_routes import _ugc_svc, _viral_tracker, router  # noqa: E402
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


def _build_app(mock_db):
    _app = FastAPI()

    @_app.middleware("http")
    async def inject_db(request: Request, call_next):
        request.state.db = mock_db
        response = await call_next(request)
        return response

    _app.include_router(router)
    return _app


_TENANT = str(uuid.uuid4())
_HEADERS = {"X-Tenant-ID": _TENANT}


class TestUGCRoutes:
    def test_submit_ok(self):
        """POST /submit → 200"""
        db = _make_mock_db()
        app = _build_app(db)
        c = TestClient(app, raise_server_exceptions=False)

        _ugc_svc.submit = AsyncMock(
            return_value={
                "ugc_id": str(uuid.uuid4()),
                "status": "pending_review",
            }
        )

        resp = c.post(
            "/api/v1/growth/ugc/submit",
            headers=_HEADERS,
            json={
                "customer_id": str(CUSTOMER_ID),
                "store_id": str(STORE_ID),
                "media_urls": [{"url": "https://cdn.example.com/p.jpg", "type": "photo"}],
                "caption": "好吃",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_gallery_ok(self):
        """GET /gallery/{store_id} → 200"""
        db = _make_mock_db()
        app = _build_app(db)
        c = TestClient(app, raise_server_exceptions=False)

        _ugc_svc.get_gallery = AsyncMock(return_value={"items": [], "total": 0})

        resp = c.get(
            f"/api/v1/growth/ugc/gallery/{STORE_ID}",
            headers=_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_approve_ok(self):
        """POST /{ugc_id}/approve → 200"""
        db = _make_mock_db()
        app = _build_app(db)
        c = TestClient(app, raise_server_exceptions=False)

        _ugc_svc.approve = AsyncMock(
            return_value={
                "ugc_id": str(UGC_ID),
                "status": "published",
                "points_awarded": 50,
            }
        )

        resp = c.post(
            f"/api/v1/growth/ugc/{UGC_ID}/approve",
            headers=_HEADERS,
        )
        assert resp.status_code == 200

    def test_reject_ok(self):
        """POST /{ugc_id}/reject → 200"""
        db = _make_mock_db()
        app = _build_app(db)
        c = TestClient(app, raise_server_exceptions=False)

        _ugc_svc.reject = AsyncMock(
            return_value={
                "ugc_id": str(UGC_ID),
                "status": "rejected",
                "rejection_reason": "模糊",
            }
        )

        resp = c.post(
            f"/api/v1/growth/ugc/{UGC_ID}/reject",
            headers=_HEADERS,
            json={"reason": "照片模糊"},
        )
        assert resp.status_code == 200

    def test_my_submissions_ok(self):
        """GET /my → 200"""
        db = _make_mock_db()
        app = _build_app(db)
        c = TestClient(app, raise_server_exceptions=False)

        _ugc_svc.get_my_submissions = AsyncMock(return_value=[])

        resp = c.get(
            f"/api/v1/growth/ugc/my?customer_id={CUSTOMER_ID}",
            headers=_HEADERS,
        )
        assert resp.status_code == 200

    def test_share_ok(self):
        """POST /{ugc_id}/share → 200"""
        db = _make_mock_db()
        app = _build_app(db)
        c = TestClient(app, raise_server_exceptions=False)

        _viral_tracker.create_share_link = AsyncMock(
            return_value={
                "chain_id": str(uuid.uuid4()),
                "share_link_code": "abcd1234",
                "depth": 0,
            }
        )

        resp = c.post(
            f"/api/v1/growth/ugc/{UGC_ID}/share",
            headers=_HEADERS,
            json={
                "customer_id": str(CUSTOMER_ID),
                "channel": "wechat",
            },
        )
        assert resp.status_code == 200

    def test_viral_stats_ok(self):
        """GET /viral-stats → 200"""
        db = _make_mock_db()
        app = _build_app(db)
        c = TestClient(app, raise_server_exceptions=False)

        _viral_tracker.get_viral_stats = AsyncMock(
            return_value={
                "total_shares": 100,
                "total_clicks": 60,
                "total_conversions": 15,
                "total_revenue_fen": 150000,
                "avg_chain_depth": 1.2,
                "conversion_rate": 0.25,
                "days": 30,
            }
        )
        _viral_tracker.get_top_sharers = AsyncMock(return_value=[])

        resp = c.get(
            "/api/v1/growth/ugc/viral-stats",
            headers=_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "stats" in data
        assert "top_sharers" in data
