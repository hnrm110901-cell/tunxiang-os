"""tx-ops Phase-2 路由单元测试

覆盖范围（12 个测试）：

performance_routes（4个）
  1. test_list_performance_success       — mock SELECT 返回2条 → 200
  2. test_performance_ranking_success    — mock COUNT+SELECT → 200，data 含排名
  3. test_calculate_performance_success  — mock INSERT（空员工列表）→ 200
  4. test_calculate_performance_db_error — mock SQLAlchemyError → 500

issues_routes（4个）
  5. test_create_issue_success           — mock INSERT RETURNING mappings().one() → 201，data 含 id
  6. test_list_issues_success            — mock COUNT+SELECT → 200，data.items 长度>0
  7. test_resolve_issue_success          — mock SELECT+UPDATE → 200
  8. test_resolve_issue_not_found        — mock SELECT 返回 None → 404

inspection_routes（4个）
  9. test_create_inspection_report_success  — mock INSERT RETURNING → 201，data 含 id
 10. test_list_inspection_reports_success   — mock COUNT+SELECT → 200
 11. test_get_inspection_report_success     — mock SELECT 返回1条 → 200
 12. test_submit_inspection_report_success  — mock SELECT 查状态+UPDATE → 200

技术约束：
  - app.dependency_overrides[get_db] 注入 mock，完全隔离 DB
  - db.execute 用 side_effect 列表按调用顺序排列（_set_tenant 消耗第一个）
  - 每个 mock result 支持 fetchone / fetchall / scalar_one / mappings()
  - 相对导入问题通过 sys.modules 注入存根解决（shared.ontology.src.database）
"""

from __future__ import annotations

import sys
import types
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

# ── sys.modules 存根注入（隔离 shared 包） ─────────────────────────────────────


def _ensure_stub(module_path: str, attrs: dict | None = None) -> types.ModuleType:
    """确保 module_path 在 sys.modules 中存在（若已存在则不覆盖），返回模块对象。"""
    if module_path not in sys.modules:
        mod = types.ModuleType(module_path)
        if attrs:
            for k, v in attrs.items():
                setattr(mod, k, v)
        sys.modules[module_path] = mod
    return sys.modules[module_path]


# 逐层注入 shared.ontology.src.database 的所有父包
_ensure_stub("shared")
_ensure_stub("shared.ontology")
_ensure_stub("shared.ontology.src")

# database 模块必须暴露真实可替换的 get_db 对象
_db_mod = _ensure_stub("shared.ontology.src.database")

# 若模块中还没有 get_db，创建一个占位 AsyncMock
if not hasattr(_db_mod, "get_db"):

    async def _placeholder_get_db():  # pragma: no cover
        yield None

    _db_mod.get_db = _placeholder_get_db

# structlog 存根（路由文件顶层调用 structlog.get_logger）
if "structlog" not in sys.modules:
    _sl = types.ModuleType("structlog")
    _sl.get_logger = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
    sys.modules["structlog"] = _sl

# ── 导入路由（必须在存根注入之后） ────────────────────────────────────────────

from shared.ontology.src.database import get_db  # noqa: E402

from ..api.inspection_routes import router as inspect_router  # noqa: E402
from ..api.issues_routes import router as issues_router  # noqa: E402
from ..api.performance_routes import router as perf_router  # noqa: E402

# ── 全局常量 ──────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
ISSUE_ID = str(uuid.uuid4())
REPORT_ID = str(uuid.uuid4())
EMPLOYEE_ID = str(uuid.uuid4())
INSPECTOR_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ── FastAPI 应用（三路由合一） ─────────────────────────────────────────────────

app = FastAPI()
app.include_router(perf_router)
app.include_router(issues_router)
app.include_router(inspect_router)


# ── Mock 工具函数 ──────────────────────────────────────────────────────────────


def _make_result(
    *,
    scalar_one_value=0,
    fetchall_rows=None,
    fetchone_row=None,
    mappings_first=None,
    mappings_one=None,
    mappings_one_or_none=None,
    mappings_all=None,
    keys_list=None,
) -> MagicMock:
    """构造一个通用的 SQLAlchemy execute() 返回值 mock。

    支持所有常见访问路径：
      .scalar_one()
      .fetchall()  → 返回 (key,…) 元组列表（配合 rows.keys()）
      .fetchone()
      .keys()
      .mappings().one()
      .mappings().first()
      .mappings().one_or_none()
      .mappings().all()
      .mappings().__iter__()
    """
    result = MagicMock()

    # scalar_one / scalar_one_or_none
    result.scalar_one = MagicMock(return_value=scalar_one_value)
    result.scalar_one_or_none = MagicMock(return_value=scalar_one_value)
    result.scalar = MagicMock(return_value=scalar_one_value)

    # keys()
    if keys_list:
        result.keys = MagicMock(return_value=keys_list)
    else:
        result.keys = MagicMock(return_value=[])

    # fetchall() — 返回 tuple 列表（与 rows.keys() 配合 dict(zip(keys, row))）
    if fetchall_rows is not None:
        result.fetchall = MagicMock(return_value=fetchall_rows)
    else:
        result.fetchall = MagicMock(return_value=[])

    # fetchone()
    result.fetchone = MagicMock(return_value=fetchone_row)

    # mappings()
    mapping_mock = MagicMock()
    mapping_mock.one = MagicMock(return_value=mappings_one or {})
    mapping_mock.first = MagicMock(return_value=mappings_first)
    mapping_mock.one_or_none = MagicMock(return_value=mappings_one_or_none)
    mapping_mock.all = MagicMock(return_value=mappings_all or [])
    # 支持 for r in rows_result.mappings() 迭代（list_issues 路径）
    _iter_items = mappings_all or ([mappings_one] if mappings_one else ([mappings_first] if mappings_first else []))
    mapping_mock.__iter__ = MagicMock(return_value=iter(_iter_items))
    result.mappings = MagicMock(return_value=mapping_mock)

    return result


def _make_db(side_effects: list) -> AsyncMock:
    """构造一个 AsyncSession mock，execute 按 side_effects 列表依次返回。"""
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(side_effect=side_effects)
    return db


def _override(db_mock: AsyncMock):
    """返回 get_db 覆盖函数（生成器形式）。"""

    async def _dep() -> AsyncGenerator:
        yield db_mock

    return _dep


# ══════════════════════════════════════════════════════════════════════════════
#  performance_routes 测试
# ══════════════════════════════════════════════════════════════════════════════


class TestListPerformance:
    """GET /api/v1/ops/performance"""

    def test_list_performance_success(self):
        """mock _set_tenant + COUNT + SELECT，返回 2 条记录 → 200。"""
        keys = [
            "id",
            "tenant_id",
            "store_id",
            "stat_date",
            "employee_id",
            "employee_name",
            "role",
            "orders_handled",
            "revenue_generated_fen",
            "dishes_completed",
            "tables_served",
            "avg_service_score",
            "base_commission_fen",
            "created_at",
            "updated_at",
        ]
        row1 = (
            str(uuid.uuid4()),
            TENANT_ID,
            STORE_ID,
            "2026-04-04",
            str(uuid.uuid4()),
            "张三",
            "cashier",
            10,
            50000,
            0,
            0,
            None,
            50,
            "2026-04-04T08:00:00",
            "2026-04-04T08:00:00",
        )
        row2 = (
            str(uuid.uuid4()),
            TENANT_ID,
            STORE_ID,
            "2026-04-04",
            str(uuid.uuid4()),
            "李四",
            "chef",
            0,
            0,
            8,
            0,
            None,
            4000,
            "2026-04-04T08:00:00",
            "2026-04-04T08:00:00",
        )

        tenant_result = _make_result()  # _set_tenant
        count_result = _make_result(scalar_one_value=2)  # COUNT
        list_result = _make_result(  # SELECT
            keys_list=keys,
            fetchall_rows=[row1, row2],
        )

        db = _make_db([tenant_result, count_result, list_result])
        app.dependency_overrides[get_db] = _override(db)

        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/ops/performance",
                params={"store_id": STORE_ID, "perf_date": "2026-04-04"},
                headers=HEADERS,
            )

        app.dependency_overrides.clear()
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 2
        assert len(body["data"]["items"]) == 2


class TestPerformanceRanking:
    """GET /api/v1/ops/performance/ranking"""

    def test_performance_ranking_success(self):
        """mock COUNT + SELECT ranking → 200，data 含 ranking 列表（含 rank 字段）。"""
        keys = [
            "id",
            "tenant_id",
            "store_id",
            "stat_date",
            "employee_id",
            "employee_name",
            "role",
            "orders_handled",
            "revenue_generated_fen",
            "dishes_completed",
            "tables_served",
            "avg_service_score",
            "base_commission_fen",
            "created_at",
            "updated_at",
        ]
        row = (
            str(uuid.uuid4()),
            TENANT_ID,
            STORE_ID,
            "2026-04-04",
            str(uuid.uuid4()),
            "王五",
            "waiter",
            0,
            0,
            0,
            5,
            4.8,
            5000,
            "2026-04-04T08:00:00",
            "2026-04-04T08:00:00",
        )

        tenant_result = _make_result()  # _set_tenant
        count_result = _make_result(scalar_one_value=1)  # COUNT
        rank_result = _make_result(  # SELECT ranking
            keys_list=keys,
            fetchall_rows=[row],
        )

        db = _make_db([tenant_result, count_result, rank_result])
        app.dependency_overrides[get_db] = _override(db)

        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/ops/performance/ranking",
                params={"perf_date": "2026-04-04", "store_id": STORE_ID},
                headers=HEADERS,
            )

        app.dependency_overrides.clear()
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["total_employees"] == 1
        assert len(data["ranking"]) == 1
        assert data["ranking"][0]["rank"] == 1


class TestCalculatePerformance:
    """POST /api/v1/ops/performance/calculate"""

    def test_calculate_performance_success(self):
        """聚合函数返回空列表（无员工），仅调用 _set_tenant → commit → 200。"""
        tenant_result = _make_result()  # _set_tenant

        db = _make_db([tenant_result])
        app.dependency_overrides[get_db] = _override(db)

        payload = {
            "store_id": STORE_ID,
            "perf_date": "2026-04-04",
            "recalculate": False,
        }
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/ops/performance/calculate",
                json=payload,
                headers=HEADERS,
            )

        app.dependency_overrides.clear()
        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["store_id"] == STORE_ID
        assert body["data"]["employee_count"] == 0

    def test_calculate_performance_db_error(self):
        """_set_tenant 抛出 SQLAlchemyError → 500。"""
        db = _make_db([SQLAlchemyError("DB error")])
        app.dependency_overrides[get_db] = _override(db)

        payload = {
            "store_id": STORE_ID,
            "perf_date": "2026-04-04",
            "recalculate": False,
        }
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/ops/performance/calculate",
                json=payload,
                headers=HEADERS,
            )

        app.dependency_overrides.clear()
        assert resp.status_code == 500
        body = resp.json()
        assert "detail" in body


# ══════════════════════════════════════════════════════════════════════════════
#  issues_routes 测试
# ══════════════════════════════════════════════════════════════════════════════


def _issue_row(issue_id: str | None = None) -> dict:
    """构造一个模拟的 ops_issues 行 dict。"""
    _id = issue_id or str(uuid.uuid4())
    return {
        "id": _id,
        "tenant_id": TENANT_ID,
        "store_id": STORE_ID,
        "issue_date": "2026-04-04",
        "issue_type": "food_safety",
        "severity": "medium",
        "title": "厨房卫生问题",
        "description": "发现过期食材",
        "evidence_urls": [],
        "assigned_to": None,
        "due_at": "2026-04-05T10:00:00+00:00",
        "resolved_at": None,
        "resolution_notes": None,
        "resolved_by": None,
        "status": "open",
        "created_by": None,
        "created_at": "2026-04-04T08:00:00+00:00",
        "updated_at": "2026-04-04T08:00:00+00:00",
        "is_deleted": False,
    }


class TestCreateIssue:
    """POST /api/v1/ops/issues"""

    def test_create_issue_success(self):
        """mock _set_tenant + INSERT RETURNING mappings().one() → 201，data 含 id。"""
        row = _issue_row(ISSUE_ID)

        tenant_result = _make_result()  # _set_tenant
        insert_result = _make_result(mappings_one=row)  # INSERT RETURNING

        db = _make_db([tenant_result, insert_result])
        app.dependency_overrides[get_db] = _override(db)

        payload = {
            "store_id": STORE_ID,
            "issue_date": "2026-04-04",
            "issue_type": "food_safety",
            "severity": "medium",
            "title": "厨房卫生问题",
        }
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/ops/issues",
                json=payload,
                headers=HEADERS,
            )

        app.dependency_overrides.clear()
        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["id"] == ISSUE_ID


class TestListIssues:
    """GET /api/v1/ops/issues"""

    def test_list_issues_success(self):
        """mock _set_tenant + COUNT + SELECT → 200，data.items 长度 > 0。"""
        row = _issue_row()

        tenant_result = _make_result()  # _set_tenant
        count_result = _make_result(scalar_one_value=1)  # COUNT
        list_result = _make_result(mappings_all=[row])  # SELECT

        db = _make_db([tenant_result, count_result, list_result])
        app.dependency_overrides[get_db] = _override(db)

        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/ops/issues",
                headers=HEADERS,
            )

        app.dependency_overrides.clear()
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert len(body["data"]["items"]) > 0
        assert body["data"]["total"] == 1


class TestResolveIssue:
    """POST /api/v1/ops/issues/{issue_id}/resolve"""

    def test_resolve_issue_success(self):
        """mock _set_tenant + SELECT(open) + UPDATE RETURNING → 200。"""
        check_row = {"id": ISSUE_ID, "status": "open"}
        updated_row = {**_issue_row(ISSUE_ID), "status": "resolved"}

        tenant_result = _make_result()  # _set_tenant
        check_result = _make_result(mappings_first=check_row)  # SELECT check
        update_result = _make_result(mappings_first=updated_row)  # UPDATE RETURNING

        db = _make_db([tenant_result, check_result, update_result])
        app.dependency_overrides[get_db] = _override(db)

        payload = {
            "resolved_by": str(uuid.uuid4()),
            "resolution_notes": "已更换过期食材并做清洁",
        }
        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/ops/issues/{ISSUE_ID}/resolve",
                json=payload,
                headers=HEADERS,
            )

        app.dependency_overrides.clear()
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "resolved"

    def test_resolve_issue_not_found(self):
        """mock _set_tenant + SELECT 返回 None → 404。"""
        tenant_result = _make_result()  # _set_tenant
        check_result = _make_result(mappings_first=None)  # SELECT 找不到

        db = _make_db([tenant_result, check_result])
        app.dependency_overrides[get_db] = _override(db)

        payload = {
            "resolved_by": str(uuid.uuid4()),
            "resolution_notes": "测试说明",
        }
        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/ops/issues/{uuid.uuid4()}/resolve",
                json=payload,
                headers=HEADERS,
            )

        app.dependency_overrides.clear()
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
#  inspection_routes 测试
# ══════════════════════════════════════════════════════════════════════════════


def _inspect_row(report_id: str | None = None) -> dict:
    """构造一个模拟的 inspection_reports 行 dict。"""
    _id = report_id or str(uuid.uuid4())
    return {
        "id": _id,
        "tenant_id": TENANT_ID,
        "store_id": STORE_ID,
        "inspection_date": "2026-04-04",
        "inspector_id": INSPECTOR_ID,
        "overall_score": 88.5,
        "dimensions": [],
        "photos": [],
        "action_items": [],
        "notes": None,
        "ack_notes": None,
        "status": "draft",
        "acknowledged_by": None,
        "acknowledged_at": None,
        "created_at": "2026-04-04T08:00:00+00:00",
        "updated_at": "2026-04-04T08:00:00+00:00",
        "is_deleted": False,
    }


class TestCreateInspectionReport:
    """POST /api/v1/ops/inspections"""

    def test_create_inspection_report_success(self):
        """mock _set_tenant + INSERT RETURNING mappings().one() → 201，data 含 id。"""
        row = _inspect_row(REPORT_ID)

        tenant_result = _make_result()  # _set_tenant
        insert_result = _make_result(mappings_one=row)  # INSERT RETURNING

        db = _make_db([tenant_result, insert_result])
        app.dependency_overrides[get_db] = _override(db)

        payload = {
            "store_id": STORE_ID,
            "inspection_date": "2026-04-04",
            "inspector_id": INSPECTOR_ID,
            "dimensions": [
                {"name": "卫生", "score": 45, "max_score": 50, "issues": []},
            ],
            "photos": [],
            "action_items": [],
        }
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/ops/inspections",
                json=payload,
                headers=HEADERS,
            )

        app.dependency_overrides.clear()
        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["id"] == REPORT_ID


class TestListInspectionReports:
    """GET /api/v1/ops/inspections"""

    def test_list_inspection_reports_success(self):
        """mock _set_tenant + COUNT + SELECT → 200，data 含 items 和 total。"""
        row = _inspect_row()

        tenant_result = _make_result()  # _set_tenant
        count_result = _make_result(scalar_one_value=1)  # COUNT
        list_result = _make_result(mappings_all=[row])  # SELECT

        db = _make_db([tenant_result, count_result, list_result])
        app.dependency_overrides[get_db] = _override(db)

        with TestClient(app) as client:
            resp = client.get(
                "/api/v1/ops/inspections",
                params={"store_id": STORE_ID},
                headers=HEADERS,
            )

        app.dependency_overrides.clear()
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 1
        assert len(body["data"]["items"]) == 1


class TestGetInspectionReport:
    """GET /api/v1/ops/inspections/{report_id}"""

    def test_get_inspection_report_success(self):
        """mock _set_tenant + SELECT mappings().one_or_none() → 200。"""
        row = _inspect_row(REPORT_ID)

        tenant_result = _make_result()  # _set_tenant
        select_result = _make_result(mappings_one_or_none=row)  # SELECT

        db = _make_db([tenant_result, select_result])
        app.dependency_overrides[get_db] = _override(db)

        with TestClient(app) as client:
            resp = client.get(
                f"/api/v1/ops/inspections/{REPORT_ID}",
                headers=HEADERS,
            )

        app.dependency_overrides.clear()
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["id"] == REPORT_ID


class TestSubmitInspectionReport:
    """POST /api/v1/ops/inspections/{report_id}/submit"""

    def test_submit_inspection_report_success(self):
        """mock _set_tenant + SELECT(draft) + UPDATE RETURNING → 200，status=submitted。"""
        check_row = {"status": "draft"}
        updated_row = {**_inspect_row(REPORT_ID), "status": "submitted"}

        tenant_result = _make_result()  # _set_tenant
        check_result = _make_result(mappings_one_or_none=check_row)  # SELECT check
        update_result = _make_result(mappings_one=updated_row)  # UPDATE RETURNING

        db = _make_db([tenant_result, check_result, update_result])
        app.dependency_overrides[get_db] = _override(db)

        payload = {"final_notes": "巡检确认，请门店整改"}
        with TestClient(app) as client:
            resp = client.post(
                f"/api/v1/ops/inspections/{REPORT_ID}/submit",
                json=payload,
                headers=HEADERS,
            )

        app.dependency_overrides.clear()
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "submitted"
