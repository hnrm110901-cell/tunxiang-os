"""合规预警 API 测试 — compliance_routes.py（Round 73 Mock→DB 改造）

覆盖端点：
  GET  /api/v1/org/compliance/alerts             - 合规预警列表
  POST /api/v1/org/compliance/scan               - 手动触发合规扫描
  GET  /api/v1/org/compliance/documents/expiring - 即将到期证件
  GET  /api/v1/org/compliance/performance/low    - 低绩效员工
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from api.compliance_routes import router as compliance_router
from shared.ontology.src.database import get_db

app = FastAPI()
app.include_router(compliance_router)

TENANT_ID = str(uuid4())


@pytest.fixture
def headers():
    return {
        "X-Tenant-ID": TENANT_ID,
        "Authorization": "Bearer test-token",
    }


def _make_mock_session():
    return AsyncMock()


def _override_db(mock_session):
    async def _mock_get_db():
        yield mock_session
    return _mock_get_db


def _make_row(data: dict):
    row = MagicMock()
    row._mapping = data
    return row


# ─── GET /alerts ──────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_get_compliance_alerts_ok(headers):
    """正常路径：所有子查询有数据，返回汇总预警。"""
    mock_session = _make_mock_session()

    # days_remaining=6 → high 级别
    cert_row = _make_row({
        "document_id": "cert-001", "employee_id": "emp-001",
        "document_type": "健康证", "expiry_date": "2026-04-10",
        "status": "active", "days_remaining": 6,
    })
    cert_result = MagicMock()
    cert_result.fetchall.return_value = [cert_row]

    perf_row = _make_row({
        "employee_id": "emp-002", "month_count": 3,
        "avg_score": "4500.00", "global_avg": "6000.00",
    })
    perf_result = MagicMock()
    perf_result.fetchall.return_value = [perf_row]

    att_row = _make_row({
        "employee_id": "emp-003", "absent_days": 5, "late_days": 2, "total_days": 25,
    })
    att_result = MagicMock()
    att_result.fetchall.return_value = [att_row]

    # 调用顺序：RLS、证件查询、绩效查询、考勤查询
    mock_session.execute = AsyncMock(
        side_effect=[MagicMock(), cert_result, perf_result, att_result]
    )

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/v1/org/compliance/alerts", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["summary"]["total"] == 3
    assert len(data["documents"]) == 1
    assert data["documents"][0]["severity"] == "high"
    assert len(data["performance"]) == 1
    assert len(data["attendance"]) == 1


@pytest.mark.anyio
async def test_get_compliance_alerts_db_error_returns_empty(headers):
    """子查询 DB 异常时，各子查询 fallback 空列表，summary total=0。
    注意：_set_rls 必须成功；SQLAlchemyError 从第二次 execute 开始抛出。
    """
    from sqlalchemy.exc import SQLAlchemyError

    mock_session = _make_mock_session()
    # 第一次 execute 是 _set_rls 的 set_config，必须成功；之后的子查询全部抛异常
    mock_session.execute = AsyncMock(
        side_effect=[MagicMock(), SQLAlchemyError("db unavailable"),
                     SQLAlchemyError("db unavailable"), SQLAlchemyError("db unavailable")]
    )

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/v1/org/compliance/alerts", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["summary"]["total"] == 0
    assert body["data"]["documents"] == []


@pytest.mark.anyio
async def test_get_compliance_alerts_severity_filter(headers):
    """severity=critical 过滤：days_remaining=-1 的证件保留，其余被过滤。"""
    mock_session = _make_mock_session()

    cert_row = _make_row({
        "document_id": "cert-001", "employee_id": "emp-001",
        "document_type": "营业执照", "expiry_date": "2026-04-03",
        "status": "active", "days_remaining": -1,  # → critical
    })
    cert_result = MagicMock()
    cert_result.fetchall.return_value = [cert_row]

    empty_result = MagicMock()
    empty_result.fetchall.return_value = []

    mock_session.execute = AsyncMock(
        side_effect=[MagicMock(), cert_result, empty_result, empty_result]
    )

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(
                "/api/v1/org/compliance/alerts",
                headers=headers,
                params={"severity": "critical"},
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert len(body["data"]["documents"]) == 1
    assert body["data"]["documents"][0]["severity"] == "critical"


# ─── POST /scan ───────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_post_compliance_scan_all_ok(headers):
    """scan_type=all 正常扫描，返回完整合规结果。"""
    mock_session = _make_mock_session()

    empty_result = MagicMock()
    empty_result.fetchall.return_value = []

    mock_session.execute = AsyncMock(
        side_effect=[MagicMock(), empty_result, empty_result, empty_result]
    )

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/api/v1/org/compliance/scan",
                headers=headers,
                json={"scan_type": "all"},
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "documents" in body["data"]
    assert "performance" in body["data"]
    assert "attendance" in body["data"]


@pytest.mark.anyio
async def test_post_compliance_scan_documents_only(headers):
    """scan_type=documents 只扫描证件，不调绩效/考勤。"""
    mock_session = _make_mock_session()

    cert_row = _make_row({
        "document_id": "cert-001", "employee_id": "emp-001",
        "document_type": "健康证", "expiry_date": "2026-04-20",
        "status": "active", "days_remaining": 16,
    })
    cert_result = MagicMock()
    cert_result.fetchall.return_value = [cert_row]

    mock_session.execute = AsyncMock(side_effect=[MagicMock(), cert_result])

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/api/v1/org/compliance/scan",
                headers=headers,
                json={"scan_type": "documents"},
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert len(body["data"]["documents"]) == 1
    assert body["data"]["performance"] == []
    assert body["data"]["attendance"] == []


@pytest.mark.anyio
async def test_post_compliance_scan_invalid_type(headers):
    """scan_type 无效时返回 400 错误。"""
    mock_session = _make_mock_session()

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/api/v1/org/compliance/scan",
                headers=headers,
                json={"scan_type": "invalid_type"},
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 400
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "invalid_scan_type"


# ─── GET /documents/expiring ──────────────────────────────────────────────────

@pytest.mark.anyio
async def test_get_expiring_documents_ok(headers):
    """正常路径：返回即将到期证件列表，带 threshold_days 和 scanned_at。"""
    mock_session = _make_mock_session()

    cert_row = _make_row({
        "document_id": "cert-001", "employee_id": "emp-001",
        "document_type": "食品经营许可证", "expiry_date": "2026-04-25",
        "status": "active", "days_remaining": 21,
    })
    cert_result = MagicMock()
    cert_result.fetchall.return_value = [cert_row]

    mock_session.execute = AsyncMock(side_effect=[MagicMock(), cert_result])

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(
                "/api/v1/org/compliance/documents/expiring",
                headers=headers,
                params={"threshold_days": 30},
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["threshold_days"] == 30
    assert len(body["data"]["items"]) == 1
    assert "scanned_at" in body["data"]
    assert body["data"]["items"][0]["severity"] == "low"  # days_remaining=21 → low


@pytest.mark.anyio
async def test_get_expiring_documents_db_error_returns_empty(headers):
    """子查询 DB 异常时返回空列表。_set_rls 成功，证件查询失败。"""
    from sqlalchemy.exc import SQLAlchemyError

    mock_session = _make_mock_session()
    # 第一次成功（_set_rls），第二次抛异常（证件查询）
    mock_session.execute = AsyncMock(
        side_effect=[MagicMock(), SQLAlchemyError("timeout")]
    )

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(
                "/api/v1/org/compliance/documents/expiring", headers=headers
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["items"] == []


# ─── GET /performance/low ─────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_get_low_performance_ok(headers):
    """正常路径：返回低绩效员工列表，含 severity=high 和 avg_score。"""
    mock_session = _make_mock_session()

    perf_row = _make_row({
        "employee_id": "emp-007", "month_count": 4,
        "avg_score": "3800.00", "global_avg": "6000.00",
    })
    perf_result = MagicMock()
    perf_result.fetchall.return_value = [perf_row]

    mock_session.execute = AsyncMock(side_effect=[MagicMock(), perf_result])

    app.dependency_overrides[get_db] = _override_db(mock_session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(
                "/api/v1/org/compliance/performance/low",
                headers=headers,
                params={"consecutive_months": 3},
            )
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["consecutive_months"] == 3
    assert len(body["data"]["items"]) == 1
    item = body["data"]["items"][0]
    assert item["employee_id"] == "emp-007"
    assert item["category"] == "performance"
    assert item["severity"] == "high"
    assert item["avg_score"] == 3800.0
