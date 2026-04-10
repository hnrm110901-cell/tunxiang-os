"""触达归因链路 API 路由测试 — api/touch_attribution_routes.py

覆盖场景：
1.  POST /api/v1/growth/attribution/track-click/{touch_id}    — 记录点击成功（counted=True）
2.  POST /api/v1/growth/attribution/track-click/{touch_id}    — touch_id 不存在（counted=False）
3.  POST /api/v1/growth/attribution/track-click/{touch_id}    — 无 Redis，降级正常处理
4.  GET  /api/v1/growth/attribution/touches                   — 正常返回触达列表
5.  GET  /api/v1/growth/attribution/touches                   — 非法 X-Tenant-ID → 422
6.  GET  /api/v1/growth/attribution/touches                   — 非法 campaign_id → 422
7.  GET  /api/v1/growth/attribution/conversions               — 正常返回转化列表
8.  GET  /api/v1/growth/attribution/conversions               — 非法日期格式 → 422
9.  GET  /api/v1/growth/attribution/campaigns/{id}/summary    — 命中缓存返回 source=cache
10. GET  /api/v1/growth/attribution/campaigns/{id}/summary    — 无缓存实时计算 source=realtime
11. GET  /api/v1/growth/attribution/campaigns/{id}/summary    — 非法 campaign_id → 422
12. GET  /api/v1/growth/attribution/performance/channels      — 正常返回渠道效果
13. GET  /api/v1/growth/attribution/performance/segments      — 正常返回人群效果
14. POST /api/v1/growth/attribution/touch-record              — 正常记录触达
15. POST /api/v1/growth/attribution/touch-record              — 非法 channel → 422
16. POST /api/v1/growth/attribution/touch-record              — 非法 customer_id → 422
17. POST /api/v1/growth/attribution/attribute-conversion      — 正常归因成功
18. POST /api/v1/growth/attribution/attribute-conversion      — 无触达记录 attributed=False
19. POST /api/v1/growth/attribution/attribute-conversion      — 非法 conversion_type → 422
"""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# Stub heavy dependencies before importing route module
# ---------------------------------------------------------------------------
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Stub structlog
_structlog_mod = types.ModuleType("structlog")
_structlog_mod.get_logger = MagicMock(return_value=MagicMock())
sys.modules.setdefault("structlog", _structlog_mod)

# Stub services.touch_tracker
_tracker_mod = types.ModuleType("services.touch_tracker")
_fake_tracker = MagicMock()
_tracker_mod.TouchTracker = MagicMock(return_value=_fake_tracker)
_svc_parent = types.ModuleType("services")
sys.modules.setdefault("services", _svc_parent)
sys.modules["services.touch_tracker"] = _tracker_mod

# Stub services.attribution_aggregator
_agg_mod = types.ModuleType("services.attribution_aggregator")
_fake_agg = MagicMock()
_agg_mod.AttributionAggregator = MagicMock(return_value=_fake_agg)
sys.modules["services.attribution_aggregator"] = _agg_mod

# Stub shared.ontology.src.database
_shared = types.ModuleType("shared")
_shared_onto = types.ModuleType("shared.ontology")
_shared_onto_src = types.ModuleType("shared.ontology.src")
_shared_onto_db = types.ModuleType("shared.ontology.src.database")
_fake_session_factory = MagicMock()
_shared_onto_db.async_session_factory = _fake_session_factory
sys.modules.setdefault("shared", _shared)
sys.modules.setdefault("shared.ontology", _shared_onto)
sys.modules.setdefault("shared.ontology.src", _shared_onto_src)
sys.modules["shared.ontology.src.database"] = _shared_onto_db

from api.touch_attribution_routes import router  # noqa: E402

app = FastAPI()
app.include_router(router)
client = TestClient(app, raise_server_exceptions=False)

TENANT_ID = str(uuid.uuid4())
_HEADERS = {"X-Tenant-ID": TENANT_ID}
_BAD_HEADERS = {"X-Tenant-ID": "not-a-uuid"}
_CAMPAIGN_ID = str(uuid.uuid4())
_CUSTOMER_ID = str(uuid.uuid4())
_TOUCH_ID = "TOUCH_" + str(uuid.uuid4()).replace("-", "")[:12]
_NOW = datetime(2026, 4, 6, 10, 0, tzinfo=timezone.utc)


def _make_async_ctx(execute_side_effects):
    """构造一个支持 async with 的 mock DB 上下文"""
    mock_db = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)
    mock_db.execute = AsyncMock(side_effect=list(execute_side_effects))
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    return mock_db


def _count_row(n=0):
    r = MagicMock()
    r.fetchone = MagicMock(return_value=[n])
    return r


def _rows_result(rows):
    r = MagicMock()
    r.fetchall = MagicMock(return_value=rows)
    return r


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1-3: POST /track-click/{touch_id}
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_track_click_ok():
    """记录点击成功，counted=True"""
    event = MagicMock()
    event.touch_id = _TOUCH_ID
    event.click_count = 1
    event.clicked_at = _NOW
    _fake_tracker.record_click = AsyncMock(return_value=event)

    mock_db = _make_async_ctx([])
    _fake_session_factory.return_value = mock_db

    with patch("api.touch_attribution_routes._get_redis", new=AsyncMock(return_value=None)):
        resp = client.post(f"/api/v1/growth/attribution/track-click/{_TOUCH_ID}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["counted"] is True
    assert body["data"]["touch_id"] == _TOUCH_ID


def test_track_click_not_found():
    """touch_id 不存在时 counted=False, reason=not_found"""
    _fake_tracker.record_click = AsyncMock(return_value=None)

    mock_db = _make_async_ctx([])
    _fake_session_factory.return_value = mock_db

    with patch("api.touch_attribution_routes._get_redis", new=AsyncMock(return_value=None)):
        resp = client.post(f"/api/v1/growth/attribution/track-click/{_TOUCH_ID}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["counted"] is False
    assert body["data"]["reason"] == "not_found"


def test_track_click_redis_dedup():
    """Redis 去重：set 返回 False 时 counted=False, reason=dedup"""
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=False)  # already exists

    with patch("api.touch_attribution_routes._get_redis", new=AsyncMock(return_value=mock_redis)):
        resp = client.post(f"/api/v1/growth/attribution/track-click/{_TOUCH_ID}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["counted"] is False
    assert body["data"]["reason"] == "dedup"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4-6: GET /touches
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_list_touches_ok():
    """正常返回触达列表"""
    touch_row = MagicMock()
    touch_row.id = uuid.uuid4()
    touch_row.touch_id = _TOUCH_ID
    touch_row.channel = "wecom"
    touch_row.campaign_id = uuid.UUID(_CAMPAIGN_ID)
    touch_row.customer_id = uuid.UUID(_CUSTOMER_ID)
    touch_row.phone = "138****8888"
    touch_row.content_type = "coupon"
    touch_row.sent_at = _NOW
    touch_row.delivered_at = _NOW
    touch_row.clicked_at = _NOW
    touch_row.click_count = 2

    count_r = _count_row(1)
    rows_r = _rows_result([touch_row])

    mock_db = _make_async_ctx([count_r, rows_r])
    _fake_session_factory.return_value = mock_db

    resp = client.get("/api/v1/growth/attribution/touches", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 1
    assert len(body["data"]["items"]) == 1


def test_list_touches_bad_tenant():
    """非法 X-Tenant-ID → 422"""
    resp = client.get("/api/v1/growth/attribution/touches", headers=_BAD_HEADERS)
    assert resp.status_code == 422


def test_list_touches_invalid_campaign_id():
    """非法 campaign_id UUID 格式 → 422"""
    resp = client.get(
        "/api/v1/growth/attribution/touches",
        headers=_HEADERS,
        params={"campaign_id": "not-a-uuid"},
    )
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7-8: GET /conversions
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_list_conversions_ok():
    """正常返回空转化列表"""
    count_r = _count_row(0)
    rows_r = _rows_result([])
    mock_db = _make_async_ctx([count_r, rows_r])
    _fake_session_factory.return_value = mock_db

    resp = client.get("/api/v1/growth/attribution/conversions", headers=_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 0
    assert body["data"]["items"] == []


def test_list_conversions_invalid_date():
    """非法日期格式 → 422"""
    resp = client.get(
        "/api/v1/growth/attribution/conversions",
        headers=_HEADERS,
        params={"start": "not-a-date"},
    )
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 9-11: GET /campaigns/{id}/summary
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_get_campaign_summary_from_cache():
    """命中预聚合缓存，返回 source=cache"""
    cached_row = MagicMock()
    cached_row.campaign_name = "春季活动"
    cached_row.total_touches = 100
    cached_row.delivered_count = 90
    cached_row.clicked_count = 30
    cached_row.reservations_attributed = 10
    cached_row.orders_attributed = 8
    cached_row.revenue_attributed = 50000.0
    cached_row.cac = 125.0
    cached_row.roi = 4.0
    cached_row.top_segments = ["vip", "new_customer"]
    cached_row.updated_at = _NOW

    cache_result = MagicMock()
    cache_result.fetchone = MagicMock(return_value=cached_row)
    mock_db = _make_async_ctx([cache_result])
    _fake_session_factory.return_value = mock_db

    resp = client.get(
        f"/api/v1/growth/attribution/campaigns/{_CAMPAIGN_ID}/summary",
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["source"] == "cache"
    assert body["data"]["campaign_name"] == "春季活动"


def test_get_campaign_summary_realtime():
    """无缓存时实时计算，返回 source=realtime"""
    no_cache_result = MagicMock()
    no_cache_result.fetchone = MagicMock(return_value=None)

    summary = MagicMock()
    summary.campaign_name = "春季活动"
    summary.total_touches = 100
    summary.delivered_count = 90
    summary.clicked_count = 30
    summary.click_rate = 0.33
    summary.delivery_rate = 0.90
    summary.reservations_attributed = 10
    summary.orders_attributed = 8
    summary.revenue_attributed = 50000.0
    summary.cac = 125.0
    summary.roi = 4.0
    summary.top_segments = ["vip"]

    _fake_agg.compute_campaign_summary = AsyncMock(return_value=summary)

    mock_db = _make_async_ctx([no_cache_result])
    _fake_session_factory.return_value = mock_db

    resp = client.get(
        f"/api/v1/growth/attribution/campaigns/{_CAMPAIGN_ID}/summary",
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["source"] == "realtime"


def test_get_campaign_summary_invalid_id():
    """非法 campaign_id UUID 格式 → 422"""
    resp = client.get(
        "/api/v1/growth/attribution/campaigns/not-a-uuid/summary",
        headers=_HEADERS,
    )
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 12: GET /performance/channels
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_get_channel_performance_ok():
    """正常返回各渠道效果对比数据"""
    ch = MagicMock()
    ch.channel = "wecom"
    ch.total_touches = 200
    ch.delivered_count = 180
    ch.clicked_count = 60
    ch.click_rate = 0.33
    ch.conversions = 20
    ch.revenue = 30000.0
    ch.conversion_rate = 0.11

    _fake_agg.compute_channel_performance = AsyncMock(return_value=[ch])
    mock_db = _make_async_ctx([])
    _fake_session_factory.return_value = mock_db

    resp = client.get(
        "/api/v1/growth/attribution/performance/channels",
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 1
    assert body["data"]["items"][0]["channel"] == "wecom"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 13: GET /performance/segments
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_get_segment_performance_ok():
    """正常返回各人群效果对比数据"""
    seg = MagicMock()
    seg.segment_name = "coupon"
    seg.total_touches = 100
    seg.conversions = 15
    seg.revenue = 12000.0
    seg.conversion_rate = 0.15
    seg.avg_order_value = 800.0

    _fake_agg.compute_segment_performance = AsyncMock(return_value=[seg])
    mock_db = _make_async_ctx([])
    _fake_session_factory.return_value = mock_db

    resp = client.get(
        "/api/v1/growth/attribution/performance/segments",
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["total"] == 1
    assert body["data"]["items"][0]["segment_name"] == "coupon"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 14-16: POST /touch-record
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_record_touch_ok():
    """正常记录营销触达，返回 touch_id"""
    event = MagicMock()
    event.touch_id = _TOUCH_ID
    event.customer_id = uuid.UUID(_CUSTOMER_ID)
    event.channel = "wecom"
    event.sent_at = _NOW

    _fake_tracker.record_touch = AsyncMock(return_value=event)
    _fake_tracker.generate_tracked_url = MagicMock(
        return_value="https://t.tunxiang.com/c/abc123"
    )

    mock_db = _make_async_ctx([])
    _fake_session_factory.return_value = mock_db

    resp = client.post(
        "/api/v1/growth/attribution/touch-record",
        headers=_HEADERS,
        json={
            "channel": "wecom",
            "customer_id": _CUSTOMER_ID,
            "content_type": "coupon",
            "content": {"landing_url": "https://example.com"},
            "campaign_id": _CAMPAIGN_ID,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["touch_id"] == _TOUCH_ID
    assert body["data"]["channel"] == "wecom"


def test_record_touch_invalid_channel():
    """非法 channel 值 → 422"""
    resp = client.post(
        "/api/v1/growth/attribution/touch-record",
        headers=_HEADERS,
        json={
            "channel": "invalid_channel",
            "customer_id": _CUSTOMER_ID,
            "content_type": "coupon",
        },
    )
    assert resp.status_code == 422


def test_record_touch_invalid_customer_id():
    """非法 customer_id UUID → 422"""
    resp = client.post(
        "/api/v1/growth/attribution/touch-record",
        headers=_HEADERS,
        json={
            "channel": "wecom",
            "customer_id": "not-a-uuid",
            "content_type": "coupon",
        },
    )
    assert resp.status_code == 422


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 17-19: POST /attribute-conversion
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_ORDER_ID = str(uuid.uuid4())


def test_attribute_conversion_ok():
    """正常归因成功，返回 attributed=True"""
    result = MagicMock()
    result.touch_id = _TOUCH_ID
    result.conversion_type = "order"
    result.conversion_value = 8800.0
    result.is_first_conversion = True
    result.created_at = _NOW

    _fake_tracker.check_and_attribute = AsyncMock(return_value=result)
    mock_db = _make_async_ctx([])
    _fake_session_factory.return_value = mock_db

    resp = client.post(
        "/api/v1/growth/attribution/attribute-conversion",
        headers=_HEADERS,
        json={
            "customer_id": _CUSTOMER_ID,
            "conversion_type": "order",
            "conversion_id": _ORDER_ID,
            "conversion_value": 8800.0,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["attributed"] is True
    assert body["data"]["touch_id"] == _TOUCH_ID


def test_attribute_conversion_no_touch():
    """无触达记录，返回 attributed=False, reason=no_touch_in_window"""
    _fake_tracker.check_and_attribute = AsyncMock(return_value=None)
    mock_db = _make_async_ctx([])
    _fake_session_factory.return_value = mock_db

    resp = client.post(
        "/api/v1/growth/attribution/attribute-conversion",
        headers=_HEADERS,
        json={
            "customer_id": _CUSTOMER_ID,
            "conversion_type": "order",
            "conversion_id": _ORDER_ID,
            "conversion_value": 8800.0,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["attributed"] is False
    assert body["data"]["reason"] == "no_touch_in_window"


def test_attribute_conversion_invalid_type():
    """非法 conversion_type → 422"""
    resp = client.post(
        "/api/v1/growth/attribution/attribute-conversion",
        headers=_HEADERS,
        json={
            "customer_id": _CUSTOMER_ID,
            "conversion_type": "invalid_type",
            "conversion_id": _ORDER_ID,
            "conversion_value": 8800.0,
        },
    )
    assert resp.status_code == 422
