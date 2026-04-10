"""HACCP 食安检查计划 API 测试 — Round 77

覆盖范围（10 个测试）：
  - GET  /plans   — 返回列表 / 空列表 / DB异常fallback
  - POST /plans   — 正常创建 / 缺必填422 / DB异常500
  - PATCH /plans/{id} — 正常更新 / 计划不存在404
  - POST /records — 正常提交（critical_failures自动计算）/ emit_event旁路调用 / DB异常
  - GET  /stats   — 返回统计结构
  - GET  /overdue — 返回逾期列表

技术约束：
  - FastAPI Dependency override 替换 get_db，完全隔离数据库
  - emit_event 通过 patch("asyncio.create_task") 拦截
  - 测试全部同步（TestClient）
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ..api.haccp_routes import router as haccp_router
from shared.ontology.src.database import get_db

# ── 应用组装 ──────────────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(haccp_router)

# ── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
PLAN_ID = str(uuid.uuid4())
RECORD_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ── DB Mock 工具 ──────────────────────────────────────────────────────────────

def _make_db_mock(
    scalar_value=0,
    execute_rows=None,
    first_row=None,
    rowcount=1,
):
    """构造 AsyncSession mock。

    参数：
      scalar_value  — execute(...).scalar() 返回值（用于 COUNT）
      execute_rows  — execute(...) 迭代返回的行列表（用于 SELECT）
      first_row     — mappings().first() 返回值（用于单行查询）
      rowcount      — result.rowcount（用于 UPDATE 影响行数）
    """
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    # 构造可迭代的 execute 结果（列表行）
    rows_result = MagicMock()
    rows_result.scalar = MagicMock(return_value=scalar_value)

    if execute_rows is not None:
        # 每个元素是 _mapping 模拟
        mock_rows = []
        for row_dict in execute_rows:
            row = MagicMock()
            row._mapping = row_dict
            mock_rows.append(row)
        rows_result.__iter__ = MagicMock(return_value=iter(mock_rows))
    else:
        rows_result.__iter__ = MagicMock(return_value=iter([]))

    rows_result.rowcount = rowcount

    # mappings().first() 路径
    mapping_mock = MagicMock()
    if first_row is not None:
        mapping_row = MagicMock()
        mapping_row.__getitem__ = MagicMock(side_effect=lambda k: first_row[k])
        mapping_row.__contains__ = MagicMock(side_effect=lambda k: k in first_row)
        mapping_mock.first = MagicMock(return_value=first_row)
    else:
        mapping_mock.first = MagicMock(return_value=None)
    rows_result.mappings = MagicMock(return_value=mapping_mock)

    db.execute = AsyncMock(return_value=rows_result)
    return db


def _override_db(db_mock):
    """返回一个替换 get_db 依赖的覆盖函数（生成器形式）。"""
    async def _override() -> AsyncGenerator:
        yield db_mock

    return _override


# ══════════════════════════════════════════════════════════════════════════════
#  GET /plans — 列出检查计划
# ══════════════════════════════════════════════════════════════════════════════


class TestListPlans:
    """GET /api/v1/ops/haccp/plans"""

    def test_returns_plan_list(self):
        """正常查询，返回计划列表和分页信息。"""
        plan_row = {
            "id": PLAN_ID,
            "tenant_id": TENANT_ID,
            "store_id": STORE_ID,
            "plan_name": "每日温度检查",
            "check_type": "temperature",
            "frequency": "daily",
            "responsible_role": "厨师长",
            "checklist": [],
            "is_active": True,
            "created_at": "2026-04-01T10:00:00+00:00",
            "updated_at": "2026-04-01T10:00:00+00:00",
        }
        db_mock = _make_db_mock(scalar_value=1, execute_rows=[plan_row])

        # execute 需要被调用两次（COUNT + SELECT），每次返回不同结果
        count_result = MagicMock()
        count_result.scalar = MagicMock(return_value=1)

        select_result = MagicMock()
        row = MagicMock()
        row._mapping = plan_row
        select_result.__iter__ = MagicMock(return_value=iter([row]))

        db_mock.execute = AsyncMock(side_effect=[count_result, select_result])

        app.dependency_overrides[get_db] = _override_db(db_mock)
        try:
            with TestClient(app) as client:
                resp = client.get("/api/v1/ops/haccp/plans", headers=HEADERS)
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "plans" in data["data"]
        assert data["data"]["total"] == 1
        assert data["data"]["page"] == 1

    def test_returns_empty_list_when_no_plans(self):
        """无数据时返回空列表，total=0。"""
        count_result = MagicMock()
        count_result.scalar = MagicMock(return_value=0)

        select_result = MagicMock()
        select_result.__iter__ = MagicMock(return_value=iter([]))

        db_mock = AsyncMock()
        db_mock.execute = AsyncMock(side_effect=[count_result, select_result])

        app.dependency_overrides[get_db] = _override_db(db_mock)
        try:
            with TestClient(app) as client:
                resp = client.get("/api/v1/ops/haccp/plans", headers=HEADERS)
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["plans"] == []
        assert data["data"]["total"] == 0

    def test_db_error_returns_empty_fallback(self):
        """DB异常时 fallback 返回空列表，ok=True（不暴露错误给前端）。"""
        from sqlalchemy.exc import SQLAlchemyError

        db_mock = AsyncMock()
        db_mock.execute = AsyncMock(side_effect=SQLAlchemyError("db error"))

        app.dependency_overrides[get_db] = _override_db(db_mock)
        try:
            with TestClient(app) as client:
                resp = client.get("/api/v1/ops/haccp/plans", headers=HEADERS)
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["plans"] == []


# ══════════════════════════════════════════════════════════════════════════════
#  POST /plans — 创建检查计划
# ══════════════════════════════════════════════════════════════════════════════


class TestCreatePlan:
    """POST /api/v1/ops/haccp/plans"""

    _valid_payload = {
        "store_id": STORE_ID,
        "plan_name": "每日卫生检查",
        "check_type": "hygiene",
        "frequency": "daily",
        "responsible_role": "卫生员",
        "checklist": [
            {"item": "地面清洁", "standard": "无油污无积水", "critical": False},
            {"item": "食材温度", "standard": "冷藏 ≤4℃", "critical": True},
        ],
        "is_active": True,
    }

    def test_creates_plan_successfully(self):
        """正常创建，返回 plan_id 和计划基本信息，状态码 201。"""
        db_mock = _make_db_mock()

        app.dependency_overrides[get_db] = _override_db(db_mock)
        try:
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/ops/haccp/plans",
                    json=self._valid_payload,
                    headers=HEADERS,
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 201
        data = resp.json()
        assert data["ok"] is True
        assert "plan_id" in data["data"]
        assert data["data"]["check_type"] == "hygiene"
        assert data["data"]["frequency"] == "daily"
        assert "created_at" in data["data"]
        db_mock.commit.assert_called_once()

    def test_missing_required_field_returns_422(self):
        """缺少必填字段 plan_name 时，Pydantic 返回 422。"""
        payload_missing_name = {k: v for k, v in self._valid_payload.items() if k != "plan_name"}

        db_mock = _make_db_mock()
        app.dependency_overrides[get_db] = _override_db(db_mock)
        try:
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/ops/haccp/plans",
                    json=payload_missing_name,
                    headers=HEADERS,
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 422

    def test_db_error_returns_ok_false(self):
        """DB 写入失败，返回 ok=False，并触发 rollback。"""
        from sqlalchemy.exc import SQLAlchemyError

        db_mock = AsyncMock()
        db_mock.execute = AsyncMock(side_effect=SQLAlchemyError("insert error"))
        db_mock.commit = AsyncMock()
        db_mock.rollback = AsyncMock()

        # _set_rls 会先 execute 一次成功，然后 INSERT 失败
        set_rls_result = AsyncMock()
        db_mock.execute = AsyncMock(side_effect=[set_rls_result, SQLAlchemyError("insert error")])

        app.dependency_overrides[get_db] = _override_db(db_mock)
        try:
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/ops/haccp/plans",
                    json=self._valid_payload,
                    headers=HEADERS,
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200  # FastAPI 不改 status，路由返回 ok=False
        data = resp.json()
        assert data["ok"] is False
        assert "message" in data["error"]
        db_mock.rollback.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
#  PATCH /plans/{plan_id} — 更新检查计划
# ══════════════════════════════════════════════════════════════════════════════


class TestUpdatePlan:
    """PATCH /api/v1/ops/haccp/plans/{plan_id}"""

    def test_updates_plan_successfully(self):
        """正常更新，rowcount=1，返回 plan_id 和 updated_at。"""
        update_result = MagicMock()
        update_result.rowcount = 1

        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()
        db_mock.rollback = AsyncMock()
        # execute 调用：第1次 _set_rls，第2次 UPDATE
        db_mock.execute = AsyncMock(side_effect=[AsyncMock(), update_result])

        app.dependency_overrides[get_db] = _override_db(db_mock)
        try:
            with TestClient(app) as client:
                resp = client.patch(
                    f"/api/v1/ops/haccp/plans/{PLAN_ID}",
                    json={"plan_name": "修改后的计划名", "is_active": False},
                    headers=HEADERS,
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["plan_id"] == PLAN_ID
        assert "updated_at" in data["data"]

    def test_plan_not_found_returns_not_found(self):
        """UPDATE 影响行数为0时，返回 ok=False，code=NOT_FOUND。"""
        update_result = MagicMock()
        update_result.rowcount = 0

        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()
        db_mock.rollback = AsyncMock()
        db_mock.execute = AsyncMock(side_effect=[AsyncMock(), update_result])

        app.dependency_overrides[get_db] = _override_db(db_mock)
        try:
            with TestClient(app) as client:
                resp = client.patch(
                    f"/api/v1/ops/haccp/plans/{PLAN_ID}",
                    json={"plan_name": "新名字"},
                    headers=HEADERS,
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


# ══════════════════════════════════════════════════════════════════════════════
#  POST /records — 提交检查记录
# ══════════════════════════════════════════════════════════════════════════════


class TestCreateRecord:
    """POST /api/v1/ops/haccp/records"""

    _valid_payload = {
        "store_id": STORE_ID,
        "plan_id": PLAN_ID,
        "operator_id": "op-001",
        "check_date": "2026-04-04",
        "results": [
            {"item": "食材温度", "passed": False, "value": "8℃", "note": "超标"},
            {"item": "地面清洁", "passed": True, "value": None, "note": None},
        ],
        "corrective_actions": "立即处理超温食材",
    }

    # 计划 checklist：食材温度是关键控制点
    _plan_checklist = [
        {"item": "食材温度", "standard": "冷藏 ≤4℃", "critical": True},
        {"item": "地面清洁", "standard": "无油污", "critical": False},
    ]

    def _make_plan_row_mock(self):
        """模拟查询计划 checklist 的 DB 返回。"""
        plan_mapping = MagicMock()
        plan_mapping.__getitem__ = MagicMock(
            side_effect=lambda k: self._plan_checklist if k == "checklist" else None
        )
        plan_mapping.__contains__ = MagicMock(side_effect=lambda k: k in {"checklist"})

        plan_result = MagicMock()
        mappings_mock = MagicMock()
        mappings_mock.first = MagicMock(return_value=plan_mapping)
        plan_result.mappings = MagicMock(return_value=mappings_mock)

        insert_result = AsyncMock()

        return plan_result, insert_result

    def test_critical_failures_auto_calculated(self):
        """提交记录时 critical_failures 自动从关键控制点计算（食材温度失控=1）。"""
        plan_result, insert_result = self._make_plan_row_mock()

        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()
        db_mock.rollback = AsyncMock()
        # execute 顺序：_set_rls, 查询计划checklist, INSERT
        db_mock.execute = AsyncMock(side_effect=[AsyncMock(), plan_result, insert_result])

        app.dependency_overrides[get_db] = _override_db(db_mock)
        try:
            with patch("asyncio.create_task"):
                with TestClient(app) as client:
                    resp = client.post(
                        "/api/v1/ops/haccp/records",
                        json=self._valid_payload,
                        headers=HEADERS,
                    )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 201
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["critical_failures"] == 1
        assert data["data"]["overall_passed"] is False

    def test_emit_event_called_twice_on_critical_failure(self):
        """critical_failures > 0 时，create_task 被调用2次
        （HACCP_CHECK_COMPLETED + HACCP_CRITICAL_FAILURE）。
        """
        plan_result, insert_result = self._make_plan_row_mock()

        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()
        db_mock.rollback = AsyncMock()
        db_mock.execute = AsyncMock(side_effect=[AsyncMock(), plan_result, insert_result])

        app.dependency_overrides[get_db] = _override_db(db_mock)
        try:
            with patch("asyncio.create_task") as mock_task:
                with TestClient(app) as client:
                    client.post(
                        "/api/v1/ops/haccp/records",
                        json=self._valid_payload,
                        headers=HEADERS,
                    )
            # HACCP_CHECK_COMPLETED + HACCP_CRITICAL_FAILURE = 2次
            assert mock_task.call_count == 2
        finally:
            app.dependency_overrides.clear()

    def test_db_error_returns_ok_false(self):
        """INSERT 失败时返回 ok=False，触发 rollback。"""
        from sqlalchemy.exc import SQLAlchemyError

        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()
        db_mock.rollback = AsyncMock()
        # _set_rls 成功，查询计划成功（返回 None），INSERT 失败
        plan_result_none = MagicMock()
        mappings_none = MagicMock()
        mappings_none.first = MagicMock(return_value=None)
        plan_result_none.mappings = MagicMock(return_value=mappings_none)

        db_mock.execute = AsyncMock(
            side_effect=[AsyncMock(), plan_result_none, SQLAlchemyError("insert failed")]
        )

        app.dependency_overrides[get_db] = _override_db(db_mock)
        try:
            with patch("asyncio.create_task"):
                with TestClient(app) as client:
                    resp = client.post(
                        "/api/v1/ops/haccp/records",
                        json=self._valid_payload,
                        headers=HEADERS,
                    )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        db_mock.rollback.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
#  GET /stats — 本月统计
# ══════════════════════════════════════════════════════════════════════════════


class TestGetStats:
    """GET /api/v1/ops/haccp/stats"""

    def test_returns_stats_structure(self):
        """返回包含 summary 和 by_type 的统计结构。"""
        # type_sql 返回行
        type_row = MagicMock()
        type_row._mapping = {
            "check_type": "temperature",
            "total_checks": 10,
            "passed_checks": 9,
            "pass_rate": 90.0,
            "total_critical_failures": 1,
        }
        type_result = MagicMock()
        type_result.__iter__ = MagicMock(return_value=iter([type_row]))

        # summary_sql 返回单行
        summary_mapping = {
            "total_checks": 10,
            "passed_checks": 9,
            "pass_rate": 90.0,
            "total_critical_failures": 1,
        }
        summary_result = MagicMock()
        mapping_mock = MagicMock()
        mapping_mock.first = MagicMock(return_value=summary_mapping)
        summary_result.mappings = MagicMock(return_value=mapping_mock)

        db_mock = AsyncMock()
        db_mock.execute = AsyncMock(side_effect=[AsyncMock(), type_result, summary_result])

        app.dependency_overrides[get_db] = _override_db(db_mock)
        try:
            with TestClient(app) as client:
                resp = client.get(
                    "/api/v1/ops/haccp/stats",
                    params={"store_id": STORE_ID},
                    headers=HEADERS,
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "summary" in data["data"]
        assert "by_type" in data["data"]
        summary = data["data"]["summary"]
        assert summary["total_checks"] == 10
        assert summary["passed_checks"] == 9
        assert summary["pass_rate"] == 90.0


# ══════════════════════════════════════════════════════════════════════════════
#  GET /overdue — 逾期未完成检查
# ══════════════════════════════════════════════════════════════════════════════


class TestGetOverdue:
    """GET /api/v1/ops/haccp/overdue"""

    def test_returns_overdue_list(self):
        """有逾期计划时，返回 overdue 列表及 total 计数。"""
        overdue_row = MagicMock()
        overdue_row._mapping = {
            "plan_id": PLAN_ID,
            "store_id": STORE_ID,
            "plan_name": "每日温度检查",
            "check_type": "temperature",
            "frequency": "daily",
            "responsible_role": "厨师长",
            "last_check_date": None,
            "required_since": date(2026, 4, 4),
        }
        overdue_result = MagicMock()
        overdue_result.__iter__ = MagicMock(return_value=iter([overdue_row]))

        db_mock = AsyncMock()
        # _set_rls + 逾期查询
        db_mock.execute = AsyncMock(side_effect=[AsyncMock(), overdue_result])

        app.dependency_overrides[get_db] = _override_db(db_mock)
        try:
            with TestClient(app) as client:
                resp = client.get(
                    "/api/v1/ops/haccp/overdue",
                    params={"store_id": STORE_ID},
                    headers=HEADERS,
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "overdue" in data["data"]
        assert data["data"]["total"] == 1
        assert data["data"]["overdue"][0]["plan_id"] == PLAN_ID
