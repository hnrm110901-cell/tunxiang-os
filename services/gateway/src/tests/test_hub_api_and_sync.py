"""
Gateway — Hub API 写接口 + Sync 健康端点 + sync_scheduler 单元测试

覆盖（共 14 个测试）：

hub_api 写接口（通过 app.dependency_overrides 替换 get_db_no_rls）：
  1. POST /api/v1/hub/merchants — 正常创建，返回 merchant_id
  2. POST /api/v1/hub/merchants — 缺必填字段 422
  3. POST /api/v1/hub/merchants — plan_template 枚举非法 422
  4. POST /api/v1/hub/merchants — IntegrityError → 409
  5. PATCH /api/v1/hub/merchants/{id} — 正常更新
  6. PATCH /api/v1/hub/merchants/{id} — 商户不存在 404
  7. POST /api/v1/hub/tickets — 正常创建，返回 ticket_id
  8. POST /api/v1/hub/tickets — 缺必填字段 422
  9. POST /api/v1/hub/tickets — priority 枚举非法 422
 10. POST /api/v1/hub/tickets — DB ProgrammingError → 503

sync health 端点：
 11. GET /api/v1/sync/health — 有数据行返回列表
 12. GET /api/v1/sync/health — 空视图返回空列表

sync_scheduler 单元测试（纯逻辑，不经过 HTTP）：
 13. _with_retry — 首次成功，retry_count=0
 14. _with_retry — 三次全失败，指数退避（sleep 次数 + 时长）
"""

from __future__ import annotations

import os
import sys
import unittest.mock as _um

# ── 路径修正 + apscheduler mock（必须在所有被测模块导入之前执行）────────────────
_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

for _mod in (
    "apscheduler",
    "apscheduler.schedulers",
    "apscheduler.schedulers.asyncio",
):
    if _mod not in sys.modules:
        sys.modules[_mod] = _um.MagicMock()

# ── 业务导入 ──────────────────────────────────────────────────────────────────
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# 导入被测路由
from services.gateway.src.hub_api import router as hub_router
from services.gateway.src.sync_scheduler import sync_router as sync_health_router

# 导入真实的 get_db_no_rls 引用，供 dependency_overrides 使用
from shared.ontology.src.database import get_db_no_rls

# ════════════════════════════════════════════════════════════════════════════
#  辅助：构建不含中间件的最小测试 app
# ════════════════════════════════════════════════════════════════════════════


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(hub_router)
    app.include_router(sync_health_router)
    return app


# ════════════════════════════════════════════════════════════════════════════
#  辅助：mock db session + dependency override
# ════════════════════════════════════════════════════════════════════════════


def _make_db_mock() -> AsyncMock:
    """最小 AsyncSession mock（commit、execute 均为 AsyncMock）。"""
    db = AsyncMock()
    db.commit = AsyncMock()
    result = MagicMock()
    result.scalar_one = MagicMock(return_value=None)
    result.scalar = MagicMock(return_value=None)
    result.rowcount = 0
    result.mappings.return_value.all.return_value = []
    result.fetchone.return_value = None
    result.fetchall.return_value = []
    db.execute = AsyncMock(return_value=result)
    return db


def _override_db(app: FastAPI, db_mock: AsyncMock) -> None:
    """通过 dependency_overrides 将 get_db_no_rls 替换为返回 mock session 的生成器。"""

    async def _fake_db() -> AsyncGenerator[AsyncMock, None]:
        yield db_mock

    app.dependency_overrides[get_db_no_rls] = _fake_db


# ════════════════════════════════════════════════════════════════════════════
#  测试 1-4：POST /api/v1/hub/merchants
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_create_merchant_success():
    """正常创建商户，返回 merchant_id + status='created'。"""
    new_uuid = str(uuid4())
    app = _build_app()
    _override_db(app, _make_db_mock())

    with patch(
        "services.gateway.src.hub_service.hub_create_merchant",
        new=AsyncMock(return_value=new_uuid),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/hub/merchants",
                json={"name": "测试商户", "plan_template": "standard"},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["merchant_id"] == new_uuid
    assert body["data"]["status"] == "created"


@pytest.mark.asyncio
async def test_create_merchant_missing_required_field():
    """缺少 plan_template → Pydantic 422（不调用 DB）。"""
    app = _build_app()
    _override_db(app, _make_db_mock())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/v1/hub/merchants",
            json={"name": "缺字段商户"},
        )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_merchant_invalid_plan_template():
    """plan_template 非法值 enterprise → 422。"""
    app = _build_app()
    _override_db(app, _make_db_mock())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/v1/hub/merchants",
            json={"name": "非法模板", "plan_template": "enterprise"},
        )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_merchant_conflict_409():
    """hub_create_merchant 抛 IntegrityError → 409 Conflict。"""
    from sqlalchemy.exc import IntegrityError

    app = _build_app()
    _override_db(app, _make_db_mock())

    with patch(
        "services.gateway.src.hub_service.hub_create_merchant",
        new=AsyncMock(side_effect=IntegrityError("dup", None, None)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/hub/merchants",
                json={"name": "重复商户", "plan_template": "lite", "merchant_code": "DUP001"},
            )

    assert resp.status_code == 409
    assert "已存在" in resp.json()["detail"]


# ════════════════════════════════════════════════════════════════════════════
#  测试 5-6：PATCH /api/v1/hub/merchants/{merchant_id}
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_update_merchant_success():
    """正常更新，返回 updated=True。"""
    merchant_id = str(uuid4())
    app = _build_app()
    _override_db(app, _make_db_mock())

    with patch(
        "services.gateway.src.hub_service.hub_update_merchant",
        new=AsyncMock(return_value=True),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.patch(
                f"/api/v1/hub/merchants/{merchant_id}",
                json={"status": "suspended"},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["merchant_id"] == merchant_id
    assert body["data"]["updated"] is True


@pytest.mark.asyncio
async def test_update_merchant_not_found_404():
    """hub_update_merchant 返回 False → 404，detail 包含 merchant_id。"""
    merchant_id = str(uuid4())
    app = _build_app()
    _override_db(app, _make_db_mock())

    with patch(
        "services.gateway.src.hub_service.hub_update_merchant",
        new=AsyncMock(return_value=False),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.patch(
                f"/api/v1/hub/merchants/{merchant_id}",
                json={"status": "churned"},
            )

    assert resp.status_code == 404
    assert merchant_id in resp.json()["detail"]


# ════════════════════════════════════════════════════════════════════════════
#  测试 7-10：POST /api/v1/hub/tickets
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_create_ticket_success():
    """正常创建工单，返回 ticket_id='T001'。"""
    app = _build_app()
    _override_db(app, _make_db_mock())

    with patch(
        "services.gateway.src.hub_service.hub_create_ticket",
        new=AsyncMock(return_value="T001"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/hub/tickets",
                json={"merchant_name": "尝在一起", "title": "POS 崩溃", "priority": "high"},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["ticket_id"] == "T001"


@pytest.mark.asyncio
async def test_create_ticket_missing_title_422():
    """缺少 title → 422。"""
    app = _build_app()
    _override_db(app, _make_db_mock())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/v1/hub/tickets",
            json={"merchant_name": "尝在一起", "priority": "low"},
        )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_ticket_invalid_priority_422():
    """priority='critical'（非法值）→ 422。"""
    app = _build_app()
    _override_db(app, _make_db_mock())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/v1/hub/tickets",
            json={"merchant_name": "尝在一起", "title": "问题", "priority": "critical"},
        )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_ticket_db_programming_error_503():
    """hub_create_ticket 抛 ProgrammingError（schema 未就绪）→ 503。"""
    from sqlalchemy.exc import ProgrammingError

    app = _build_app()
    _override_db(app, _make_db_mock())

    with patch(
        "services.gateway.src.hub_service.hub_create_ticket",
        new=AsyncMock(side_effect=ProgrammingError("schema missing", None, None)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/hub/tickets",
                json={"merchant_name": "尝在一起", "title": "DB 异常", "priority": "medium"},
            )

    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert "未就绪" in detail or "alembic" in detail.lower()


# ════════════════════════════════════════════════════════════════════════════
#  测试 11-12：GET /api/v1/sync/health
# ════════════════════════════════════════════════════════════════════════════


def _make_sync_health_session(rows: list[dict]) -> tuple[MagicMock, AsyncMock]:
    """构造 sync_health 使用的 async_session_factory context manager mock。"""
    row_mocks = []
    for row in rows:
        m = MagicMock()
        m.keys = MagicMock(return_value=list(row.keys()))
        m.__iter__ = MagicMock(return_value=iter(row.items()))
        m.__getitem__ = MagicMock(side_effect=row.__getitem__)
        row_mocks.append(m)

    result_mock = MagicMock()
    result_mock.mappings.return_value.all.return_value = row_mocks

    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=result_mock)

    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=db_mock)
    session_cm.__aexit__ = AsyncMock(return_value=False)

    return session_cm, db_mock


@pytest.mark.asyncio
async def test_sync_health_with_data():
    """视图有数据 → ok=True，data 含 1 条记录，merchant_code 正确。"""
    fake_row = {
        "merchant_code": "czyz",
        "sync_type": "dishes",
        "total_runs": 7,
        "success_runs": 7,
        "failed_runs": 0,
        "success_rate": "1.0000",
        "avg_records": 120,
        "last_run_at": "2026-04-04T02:03:12Z",
        "last_status": "success",
        "window_start": "2026-03-28T00:00:00Z",
    }
    session_cm, _ = _make_sync_health_session([fake_row])

    # async_session_factory 在函数内部 lazy import，需 patch 源模块
    with patch(
        "shared.ontology.src.database.async_session_factory",
        return_value=session_cm,
    ):
        app = _build_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/sync/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert isinstance(body["data"], list)
    assert len(body["data"]) == 1
    assert body["data"][0]["merchant_code"] == "czyz"


@pytest.mark.asyncio
async def test_sync_health_empty_view():
    """视图为空 → ok=True，data=[]。"""
    session_cm, _ = _make_sync_health_session([])

    with patch(
        "shared.ontology.src.database.async_session_factory",
        return_value=session_cm,
    ):
        app = _build_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/v1/sync/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"] == []


# ════════════════════════════════════════════════════════════════════════════
#  测试 13-14：sync_scheduler._with_retry 单元测试
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_with_retry_first_attempt_success():
    """首次即成功 → retry_count=0，asyncio.sleep 不被调用。"""
    from services.gateway.src.sync_scheduler import _with_retry

    call_count = 0

    async def _factory():
        nonlocal call_count
        call_count += 1
        return {"status": "success", "records_synced": 42, "error_msg": None}

    with patch(
        "services.gateway.src.sync_scheduler.asyncio.sleep",
        new=AsyncMock(),
    ) as mock_sleep:
        result = await _with_retry(_factory, sync_type="dishes", merchant_code="czyz")

    assert result["status"] == "success"
    assert result["records_synced"] == 42
    assert result["retry_count"] == 0
    assert result["next_retry_at"] is None
    mock_sleep.assert_not_called()
    assert call_count == 1


@pytest.mark.asyncio
async def test_with_retry_all_attempts_fail_exponential_backoff():
    """三次全部失败 → 指数退避 sleep(300, 600)，retry_count=RETRY_TIMES-1。"""
    from services.gateway.src.sync_scheduler import RETRY_DELAY_SECONDS, RETRY_TIMES, _with_retry

    async def _failing_factory():
        return {"status": "failed", "records_synced": 0, "error_msg": "upstream timeout"}

    sleep_calls: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    with patch("services.gateway.src.sync_scheduler.asyncio.sleep", new=_fake_sleep):
        result = await _with_retry(
            _failing_factory,
            sync_type="orders_incremental",
            merchant_code="zqx",
        )

    assert result["status"] == "failed"
    assert result["retry_count"] == RETRY_TIMES - 1
    assert result["next_retry_at"] is None  # 已用尽，不再调度

    # 睡眠次数 = RETRY_TIMES - 1（最后一次失败后不再等待）
    assert len(sleep_calls) == RETRY_TIMES - 1

    # 指数退避：第1次 300s，第2次 600s
    assert sleep_calls[0] == RETRY_DELAY_SECONDS * (2**0)  # 300
    assert sleep_calls[1] == RETRY_DELAY_SECONDS * (2**1)  # 600
