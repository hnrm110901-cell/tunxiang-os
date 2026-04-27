"""tx-org 扩展路由测试 — test_org_extended.py

覆盖两个无测试且端点较多的路由文件（均使用绝对 import，可无依赖加载）：
  1. schedule_routes.py   (10 端点) — 排班管理（work_schedules 表）
  2. job_grade_routes.py  ( 7 端点) — 岗位职级管理

测试矩阵（每文件 5 个，共 10 个）：

  schedule_routes：
    [1] GET  /api/v1/schedules/week     — 正常返回周排班（DB 返回空行）
    [2] GET  /api/v1/schedules/week     — 缺少 X-Tenant-ID → 400
    [3] POST /api/v1/schedules          — 正常创建排班，返回 schedule_id
    [4] PUT  /api/v1/schedules/{id}     — 未找到记录 → 404
    [5] DELETE /api/v1/schedules/{id}   — 软删除成功

  job_grade_routes：
    [6]  GET    /api/v1/job-grades              — 列表查询，正常返回 items
    [7]  POST   /api/v1/job-grades              — 正常创建职级，返回 grade_id
    [8]  GET    /api/v1/job-grades/{id}         — 记录不存在 → 404
    [9]  PUT    /api/v1/job-grades/{id}         — 无更新字段 → 400
    [10] DELETE /api/v1/job-grades/{id}         — 有在职员工不允许删除 → 400

运行方式：
    cd /Users/lichun/tunxiang-os
    pytest services/tx-org/src/tests/test_org_extended.py -v
"""

from __future__ import annotations

import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

# ──────────────────────────────────────────────────────────────────────────────
# 路径注入（让 `api.*` 和 `shared.*` 可直接 import）
# ──────────────────────────────────────────────────────────────────────────────
_SRC = os.path.join(os.path.dirname(__file__), "..")
_ROOT = os.path.join(_SRC, "..", "..", "..", "..")
sys.path.insert(0, _SRC)
sys.path.insert(0, _ROOT)

# ──────────────────────────────────────────────────────────────────────────────
# 存根注入（必须在 import 被测模块之前完成）
# ──────────────────────────────────────────────────────────────────────────────

# ── structlog 存根 ─────────────────────────────────────────────────────────────
if "structlog" not in sys.modules:
    _slog = types.ModuleType("structlog")
    _slog.get_logger = lambda *a, **k: MagicMock(info=MagicMock(), error=MagicMock(), warning=MagicMock())
    _slog.stdlib = types.SimpleNamespace(BoundLogger=object)
    sys.modules["structlog"] = _slog

# ── sqlalchemy 系列存根 ────────────────────────────────────────────────────────
if "sqlalchemy" not in sys.modules:
    _sa = types.ModuleType("sqlalchemy")
    _sa.text = lambda s: s
    _sa_ext = types.ModuleType("sqlalchemy.ext")
    _sa_ext_async = types.ModuleType("sqlalchemy.ext.asyncio")
    _sa_ext_async.AsyncSession = MagicMock()
    sys.modules["sqlalchemy"] = _sa
    sys.modules["sqlalchemy.ext"] = _sa_ext
    sys.modules["sqlalchemy.ext.asyncio"] = _sa_ext_async

# ── shared.ontology.src.database 存根 ─────────────────────────────────────────
_shared_pkg = types.ModuleType("shared")
_onto_pkg = types.ModuleType("shared.ontology")
_onto_src_pkg = types.ModuleType("shared.ontology.src")
_db_mod = types.ModuleType("shared.ontology.src.database")


async def _stub_get_db():
    yield MagicMock()


_db_mod.get_db = _stub_get_db
_db_mod.async_session_factory = MagicMock()
sys.modules.setdefault("shared", _shared_pkg)
sys.modules.setdefault("shared.ontology", _onto_pkg)
sys.modules.setdefault("shared.ontology.src", _onto_src_pkg)
sys.modules["shared.ontology.src.database"] = _db_mod

# ──────────────────────────────────────────────────────────────────────────────
# 路由导入
# ──────────────────────────────────────────────────────────────────────────────
import pytest
from api.job_grade_routes import router as job_grade_router
from api.schedule_routes import router as schedule_router
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from shared.ontology.src.database import get_db

# ──────────────────────────────────────────────────────────────────────────────
# 公共常量
# ──────────────────────────────────────────────────────────────────────────────
TENANT_ID = str(uuid4())
STORE_ID = str(uuid4())
EMP_ID = str(uuid4())
SCHEDULE_ID = str(uuid4())
GRADE_ID = str(uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ──────────────────────────────────────────────────────────────────────────────
# DB mock 工厂
# ──────────────────────────────────────────────────────────────────────────────


def _mock_db(
    mapping_first=None,
    fetchall_rows=None,
    fetchone_row=None,
    scalar_value=None,
):
    """通用 DB mock。

    execute 调用顺序：
      call 0 → set_config（返回空 MagicMock）
      call 1+ → 业务 SQL（返回按参数配置的结果）
    """
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    def _make_result():
        r = MagicMock()
        r.mappings.return_value.first.return_value = mapping_first
        r.mappings.return_value.fetchall.return_value = fetchall_rows or []
        r.fetchall.return_value = fetchall_rows or []
        r.fetchone.return_value = fetchone_row
        if scalar_value is not None:
            r.scalar.return_value = scalar_value
            r.scalar_one.return_value = scalar_value
        return r

    set_cfg_result = MagicMock()
    biz_result = _make_result()

    session.execute = AsyncMock(side_effect=[set_cfg_result, biz_result, biz_result, biz_result, biz_result])
    return session


# ════════════════════════════════════════════════════════════════════════════
# schedule_routes 测试（5 个）
# ════════════════════════════════════════════════════════════════════════════


class TestScheduleRoutes:
    """schedule_routes.py（排班管理）核心路径验证"""

    def _app(self, db):
        app = FastAPI()
        app.include_router(schedule_router)
        app.dependency_overrides[get_db] = lambda: db
        return app

    # ── 1. GET /api/v1/schedules/week — 正常返回，DB 空数据 ──────────────

    @pytest.mark.asyncio
    async def test_get_week_schedule_empty(self):
        """DB 无排班记录时，week 端点应返回 ok=True，employees=[]。"""
        db = _mock_db(fetchall_rows=[])
        async with AsyncClient(transport=ASGITransport(app=self._app(db)), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/schedules/week",
                params={"store_id": STORE_ID, "week_start": "2026-04-07"},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["employees"] == []
        assert body["data"]["store_id"] == STORE_ID
        assert len(body["data"]["dates"]) == 7

    # ── 2. GET /api/v1/schedules/week — 缺少 X-Tenant-ID → 400 ──────────

    @pytest.mark.asyncio
    async def test_get_week_schedule_missing_tenant(self):
        """不提供 X-Tenant-ID 时，应返回 400。"""
        db = _mock_db()
        async with AsyncClient(transport=ASGITransport(app=self._app(db)), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/schedules/week",
                params={"store_id": STORE_ID, "week_start": "2026-04-07"},
                # 不携带 X-Tenant-ID
            )

        assert resp.status_code == 400
        assert "X-Tenant-ID" in resp.json()["detail"]

    # ── 3. POST /api/v1/schedules — 正常创建排班 ─────────────────────────

    @pytest.mark.asyncio
    async def test_create_schedule_success(self):
        """正常 POST，DB INSERT 返回含 id 的行，应返回 ok=True 和 schedule_id。"""
        from datetime import date as _date

        fake_row = MagicMock()
        fake_row.__getitem__ = lambda self, k: {
            "id": SCHEDULE_ID,
            "shift_start": "09:00:00",
            "shift_end": "18:00:00",
            "status": "planned",
            "schedule_date": _date(2026, 4, 8),
        }[k]

        db = _mock_db(mapping_first=fake_row)

        async with AsyncClient(transport=ASGITransport(app=self._app(db)), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/schedules",
                json={
                    "employee_id": EMP_ID,
                    "store_id": STORE_ID,
                    "schedule_date": "2026-04-08",
                    "shift_start": "09:00",
                    "shift_end": "18:00",
                },
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "schedule_id" in body["data"]

    # ── 4. PUT /api/v1/schedules/{id} — 记录不存在 → 404 ─────────────────

    @pytest.mark.asyncio
    async def test_update_schedule_not_found(self):
        """PUT 更新不存在的排班 ID，DB RETURNING 返回 None，应返回 404。"""
        db = _mock_db(mapping_first=None)
        async with AsyncClient(transport=ASGITransport(app=self._app(db)), base_url="http://test") as client:
            resp = await client.put(
                f"/api/v1/schedules/{SCHEDULE_ID}",
                json={"status": "confirmed"},
                headers=HEADERS,
            )

        assert resp.status_code == 404
        assert "不存在" in resp.json()["detail"]

    # ── 5. DELETE /api/v1/schedules/{id} — 软删除成功 ────────────────────

    @pytest.mark.asyncio
    async def test_delete_schedule_success(self):
        """DELETE 软删除排班，DB RETURNING 返回行，应返回 ok=True，status=cancelled。"""
        from datetime import date as _date

        fake_row = MagicMock()
        fake_row.__getitem__ = lambda self, k: {
            "id": SCHEDULE_ID,
            "employee_id": EMP_ID,
            "schedule_date": _date(2026, 4, 8),
        }[k]

        db = _mock_db(mapping_first=fake_row)
        async with AsyncClient(transport=ASGITransport(app=self._app(db)), base_url="http://test") as client:
            resp = await client.delete(
                f"/api/v1/schedules/{SCHEDULE_ID}",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "cancelled"


# ════════════════════════════════════════════════════════════════════════════
# job_grade_routes 测试（5 个）
# ════════════════════════════════════════════════════════════════════════════


class TestJobGradeRoutes:
    """job_grade_routes.py（岗位职级）核心路径验证"""

    def _app(self, db):
        app = FastAPI()
        app.include_router(job_grade_router)
        app.dependency_overrides[get_db] = lambda: db
        return app

    # ── 6. GET /api/v1/job-grades — 列表查询正常返回 ──────────────────────

    @pytest.mark.asyncio
    async def test_list_job_grades_empty(self):
        """无职级数据时，列表端点应返回 ok=True，items=[]，total=0。"""
        db = AsyncMock()
        db.commit = AsyncMock()

        # execute 调用：[0] set_config, [1] COUNT query, [2] LIST query
        set_cfg = MagicMock()

        count_result = MagicMock()
        count_result.scalar.return_value = 0

        list_result = MagicMock()
        list_result.fetchall.return_value = []

        db.execute = AsyncMock(side_effect=[set_cfg, count_result, list_result])

        async with AsyncClient(transport=ASGITransport(app=self._app(db)), base_url="http://test") as client:
            resp = await client.get("/api/v1/job-grades", headers=HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["items"] == []
        assert body["data"]["total"] == 0

    # ── 7. POST /api/v1/job-grades — 正常创建职级 ─────────────────────────

    @pytest.mark.asyncio
    async def test_create_job_grade_success(self):
        """POST 创建职级，DB INSERT RETURNING 返回 grade_id，应返回 ok=True。"""
        fake_row = MagicMock()
        fake_row._mapping = {"grade_id": GRADE_ID}

        db = AsyncMock()
        db.commit = AsyncMock()

        set_cfg = MagicMock()
        insert_result = MagicMock()
        insert_result.fetchone.return_value = fake_row

        db.execute = AsyncMock(side_effect=[set_cfg, insert_result])

        async with AsyncClient(transport=ASGITransport(app=self._app(db)), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/job-grades",
                json={
                    "name": "高级服务员",
                    "category": "operations",
                    "level": 3,
                },
                headers=HEADERS,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "grade_id" in body["data"]

    # ── 8. GET /api/v1/job-grades/{id} — 职级不存在 → 404 ────────────────

    @pytest.mark.asyncio
    async def test_get_job_grade_not_found(self):
        """查询不存在的职级 ID，DB fetchone 返回 None，应返回 404。"""
        db = AsyncMock()
        db.commit = AsyncMock()

        set_cfg = MagicMock()
        detail_result = MagicMock()
        detail_result.fetchone.return_value = None

        db.execute = AsyncMock(side_effect=[set_cfg, detail_result])

        async with AsyncClient(transport=ASGITransport(app=self._app(db)), base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/job-grades/{GRADE_ID}",
                headers=HEADERS,
            )

        assert resp.status_code == 404
        assert "不存在" in resp.json()["detail"]

    # ── 9. PUT /api/v1/job-grades/{id} — 无更新字段 → 400 ────────────────

    @pytest.mark.asyncio
    async def test_update_job_grade_no_fields(self):
        """PUT 请求体全部字段为 None，路由应返回 400（没有需要更新的字段）。"""
        fake_check = MagicMock()
        fake_check.fetchone.return_value = MagicMock()  # 职级存在

        db = AsyncMock()
        db.commit = AsyncMock()

        set_cfg = MagicMock()
        db.execute = AsyncMock(side_effect=[set_cfg, fake_check])

        async with AsyncClient(transport=ASGITransport(app=self._app(db)), base_url="http://test") as client:
            resp = await client.put(
                f"/api/v1/job-grades/{GRADE_ID}",
                json={},  # 空 body，所有字段 None
                headers=HEADERS,
            )

        assert resp.status_code == 400
        assert "没有需要更新的字段" in resp.json()["detail"]

    # ── 10. DELETE /api/v1/job-grades/{id} — 有在职员工不允许删除 → 400 ──

    @pytest.mark.asyncio
    async def test_delete_job_grade_has_employees(self):
        """职级下还有在职员工时，DELETE 应返回 400，禁止删除。"""
        db = AsyncMock()
        db.commit = AsyncMock()

        set_cfg = MagicMock()

        # employee check：COUNT(*) = 5（有在职员工）
        emp_check_result = MagicMock()
        emp_check_result.scalar.return_value = 5

        db.execute = AsyncMock(side_effect=[set_cfg, emp_check_result])

        async with AsyncClient(transport=ASGITransport(app=self._app(db)), base_url="http://test") as client:
            resp = await client.delete(
                f"/api/v1/job-grades/{GRADE_ID}",
                headers=HEADERS,
            )

        assert resp.status_code == 400
        assert "在职员工" in resp.json()["detail"]
