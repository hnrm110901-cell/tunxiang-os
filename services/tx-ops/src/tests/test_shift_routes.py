"""shift_routes.py FastAPI 路由单元测试

测试范围：
  1. test_start_shift_success         — INSERT RETURNING → 200，data 含 shift_id
  2. test_start_shift_db_error        — SQLAlchemyError → 500 错误响应
  3. test_handover_success            — SELECT 有记录 + UPDATE RETURNING → 200
  4. test_handover_not_found          — SELECT 空记录 → 404
  5. test_confirm_success             — SELECT 有记录 + UPDATE → 200，status="confirmed"
  6. test_confirm_disputed            — SELECT 有记录 + UPDATE → 200，disputed=True
  7. test_list_shifts_success         — SELECT 返回2条 → 200，data.items 长度=2
  8. test_get_summary_success         — SELECT shift + SELECT checklist → 200，cash_balanced 字段

技术约束：
  - FastAPI TestClient + unittest.mock 覆盖 get_db 依赖
  - 不连接真实 PostgreSQL
  - AsyncSession 以 AsyncMock 替代
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from ..api.shift_routes import router as shift_router
from shared.ontology.src.database import get_db

# ── 最小化 FastAPI 应用 ────────────────────────────────────────────────────────

app = FastAPI()
app.include_router(shift_router)

# ── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
SHIFT_ID = str(uuid.uuid4())
EMPLOYEE_A = str(uuid.uuid4())
EMPLOYEE_B = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ── 工具函数 ──────────────────────────────────────────────────────────────────


def _make_shift_row(
    shift_id: str = SHIFT_ID,
    status: str = "pending",
    disputed: bool = False,
    cash_counted_fen: int = 10000,
    pos_cash_fen: int = 10000,
    cash_diff_fen: int = 0,
    received_by: str | None = None,
) -> dict:
    """构造一条班次记录字典（模拟 DB row）。"""
    return {
        "id": shift_id,
        "tenant_id": TENANT_ID,
        "store_id": STORE_ID,
        "shift_date": date(2026, 4, 4),
        "shift_type": "morning",
        "start_time": datetime(2026, 4, 4, 8, 0, tzinfo=timezone.utc),
        "end_time": datetime(2026, 4, 4, 16, 0, tzinfo=timezone.utc),
        "handover_by": EMPLOYEE_A,
        "received_by": received_by,
        "cash_counted_fen": cash_counted_fen,
        "pos_cash_fen": pos_cash_fen,
        "cash_diff_fen": cash_diff_fen,
        "notes": None,
        "status": status,
        "disputed": disputed,
        "dispute_reason": None,
        "created_at": datetime(2026, 4, 4, 8, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 4, 4, 8, 0, tzinfo=timezone.utc),
        "is_deleted": False,
    }


def _mappings_result(row_dict: dict) -> MagicMock:
    """返回支持 .mappings().one() 和 .mappings().first() 的 mock result。"""
    result = MagicMock()
    mappings_obj = MagicMock()
    mappings_obj.one.return_value = row_dict
    mappings_obj.first.return_value = row_dict
    mappings_obj.all.return_value = [row_dict]
    result.mappings.return_value = mappings_obj
    result.first.return_value = row_dict  # check.first() 用于 None 检测
    return result


def _mappings_result_list(rows: list[dict]) -> MagicMock:
    """返回支持 .mappings().all() 的 mock result（多条记录）。"""
    result = MagicMock()
    mappings_obj = MagicMock()
    mappings_obj.all.return_value = rows
    result.mappings.return_value = mappings_obj
    return result


def _empty_check_result() -> MagicMock:
    """返回 .first() = None 的 mock result（模拟记录不存在）。"""
    result = MagicMock()
    result.first.return_value = None
    return result


def _set_config_result() -> MagicMock:
    """set_config RLS 调用返回的无实际意义 result。"""
    result = MagicMock()
    result.first.return_value = None
    return result


def _override_get_db(mock_db: AsyncMock):
    """替换 get_db 依赖，注入 mock AsyncSession。"""
    async def _dep():
        yield mock_db
    return _dep


# ══════════════════════════════════════════════════════════════════════════════
#  1. test_start_shift_success
# ══════════════════════════════════════════════════════════════════════════════


class TestStartShift:
    """POST /api/v1/ops/shifts — 开始新班次。"""

    def test_start_shift_success(self):
        """INSERT RETURNING 成功 → 201，data 含 shift_id（即 id 字段）。"""
        row = _make_shift_row()

        # execute 调用序列：
        #   call 0 — _set_tenant (set_config RLS)
        #   call 1 — INSERT RETURNING
        db = AsyncMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _set_config_result(),
            _mappings_result(row),
        ])

        app.dependency_overrides[get_db] = _override_get_db(db)
        try:
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/ops/shifts",
                    json={
                        "store_id": STORE_ID,
                        "shift_date": "2026-04-04",
                        "shift_type": "morning",
                        "handover_by": EMPLOYEE_A,
                    },
                    headers=HEADERS,
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        # shift 主键字段存在（路由返回整条记录，key 为 "id"）
        assert "id" in body["data"]
        assert body["data"]["status"] == "pending"
        assert body["data"]["shift_type"] == "morning"

    def test_start_shift_db_error(self):
        """INSERT 抛 SQLAlchemyError → 500，响应包含错误描述。"""
        db = AsyncMock()
        db.commit = AsyncMock()

        # call 0 — set_config 正常；call 1 — INSERT 抛异常
        async def _side_effect(*args, **kwargs):
            if not hasattr(_side_effect, "_called"):
                _side_effect._called = True
                return _set_config_result()
            raise SQLAlchemyError("connection refused")

        db.execute = AsyncMock(side_effect=_side_effect)

        app.dependency_overrides[get_db] = _override_get_db(db)
        try:
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/ops/shifts",
                    json={
                        "store_id": STORE_ID,
                        "shift_date": "2026-04-04",
                        "shift_type": "morning",
                        "handover_by": EMPLOYEE_A,
                    },
                    headers=HEADERS,
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 500
        body = resp.json()
        # FastAPI 默认将 HTTPException.detail 放到 "detail" 字段
        assert "detail" in body or body.get("ok") is False


# ══════════════════════════════════════════════════════════════════════════════
#  3 & 4. test_handover_success / test_handover_not_found
# ══════════════════════════════════════════════════════════════════════════════


class TestHandover:
    """POST /api/v1/ops/shifts/{id}/handover — 发起交班。"""

    def test_handover_success(self):
        """SELECT 有记录 + UPDATE RETURNING → 200，data 含交班信息。"""
        row = _make_shift_row(received_by=EMPLOYEE_B, cash_counted_fen=10500, pos_cash_fen=10000, cash_diff_fen=500)

        # execute 调用序列：
        #   call 0 — _set_tenant
        #   call 1 — SELECT check (check.first() 不为 None)
        #   call 2 — UPDATE RETURNING
        #   call 3 — DELETE checklist
        #   （无设备清单条目，无额外 INSERT）
        check_result = MagicMock()
        check_result.first.return_value = {"id": SHIFT_ID}  # 非 None，表示记录存在

        db = AsyncMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _set_config_result(),   # call 0: set_config
            check_result,           # call 1: SELECT check
            _mappings_result(row),  # call 2: UPDATE RETURNING
            MagicMock(),            # call 3: DELETE checklist
        ])

        app.dependency_overrides[get_db] = _override_get_db(db)
        try:
            with TestClient(app) as client:
                resp = client.post(
                    f"/api/v1/ops/shifts/{SHIFT_ID}/handover",
                    json={
                        "received_by": EMPLOYEE_B,
                        "cash_counted_fen": 10500,
                        "pos_cash_fen": 10000,
                        "device_checklist": [],
                        "notes": None,
                    },
                    headers=HEADERS,
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["cash_diff_fen"] == 500

    def test_handover_not_found(self):
        """SELECT 返回空 → 404。"""
        db = AsyncMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _set_config_result(),    # call 0: set_config
            _empty_check_result(),   # call 1: SELECT check → first()=None
        ])

        app.dependency_overrides[get_db] = _override_get_db(db)
        try:
            with TestClient(app) as client:
                resp = client.post(
                    f"/api/v1/ops/shifts/{SHIFT_ID}/handover",
                    json={
                        "received_by": EMPLOYEE_B,
                        "cash_counted_fen": 10000,
                        "pos_cash_fen": 10000,
                        "device_checklist": [],
                    },
                    headers=HEADERS,
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
#  5 & 6. test_confirm_success / test_confirm_disputed
# ══════════════════════════════════════════════════════════════════════════════


class TestConfirmHandover:
    """POST /api/v1/ops/shifts/{id}/confirm — 确认交班。"""

    def test_confirm_success(self):
        """无争议确认 → 200，data.status="confirmed"，data.disputed=False。"""
        row = _make_shift_row(status="confirmed", disputed=False, received_by=EMPLOYEE_B)

        check_result = MagicMock()
        check_result.first.return_value = {"id": SHIFT_ID}

        db = AsyncMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _set_config_result(),   # call 0: set_config
            check_result,           # call 1: SELECT check
            _mappings_result(row),  # call 2: UPDATE RETURNING
        ])

        app.dependency_overrides[get_db] = _override_get_db(db)
        try:
            with TestClient(app) as client:
                resp = client.post(
                    f"/api/v1/ops/shifts/{SHIFT_ID}/confirm",
                    json={
                        "received_by": EMPLOYEE_B,
                        "disputed": False,
                    },
                    headers=HEADERS,
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "confirmed"
        assert body["data"]["disputed"] is False

    def test_confirm_disputed(self):
        """标记争议 → 200，data.status="disputed"，data.disputed=True。"""
        row = _make_shift_row(
            status="disputed",
            disputed=True,
            received_by=EMPLOYEE_B,
        )
        # 手动加 dispute_reason
        row["dispute_reason"] = "现金不符"

        check_result = MagicMock()
        check_result.first.return_value = {"id": SHIFT_ID}

        db = AsyncMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _set_config_result(),
            check_result,
            _mappings_result(row),
        ])

        app.dependency_overrides[get_db] = _override_get_db(db)
        try:
            with TestClient(app) as client:
                resp = client.post(
                    f"/api/v1/ops/shifts/{SHIFT_ID}/confirm",
                    json={
                        "received_by": EMPLOYEE_B,
                        "disputed": True,
                        "dispute_reason": "现金不符",
                    },
                    headers=HEADERS,
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["disputed"] is True
        assert body["data"]["status"] == "disputed"


# ══════════════════════════════════════════════════════════════════════════════
#  7. test_list_shifts_success
# ══════════════════════════════════════════════════════════════════════════════


class TestListShifts:
    """GET /api/v1/ops/shifts — 查询班次列表。"""

    def test_list_shifts_success(self):
        """SELECT 返回2条记录 → 200，data.items 长度=2，data.total=2。"""
        row1 = _make_shift_row(shift_id=str(uuid.uuid4()), status="pending")
        row2 = _make_shift_row(shift_id=str(uuid.uuid4()), status="confirmed")

        # list 端点：execute 序列
        #   call 0 — set_config
        #   call 1 — SELECT ... FROM shift_records
        list_result = _mappings_result_list([row1, row2])

        db = AsyncMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _set_config_result(),
            list_result,
        ])

        app.dependency_overrides[get_db] = _override_get_db(db)
        try:
            with TestClient(app) as client:
                resp = client.get(
                    "/api/v1/ops/shifts",
                    params={"store_id": STORE_ID},
                    headers=HEADERS,
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert len(body["data"]["items"]) == 2
        assert body["data"]["total"] == 2


# ══════════════════════════════════════════════════════════════════════════════
#  8. test_get_summary_success
# ══════════════════════════════════════════════════════════════════════════════


class TestGetSummary:
    """GET /api/v1/ops/shifts/{id}/summary — 班次汇总。"""

    def test_get_summary_success(self):
        """SELECT shift + SELECT checklist → 200，data 含 cash_balanced 字段。"""
        shift_row = _make_shift_row(
            cash_counted_fen=10000,
            pos_cash_fen=10000,
            cash_diff_fen=0,
            received_by=EMPLOYEE_B,
            status="confirmed",
        )
        checklist_rows = [
            {
                "id": str(uuid.uuid4()),
                "shift_id": SHIFT_ID,
                "tenant_id": TENANT_ID,
                "item": "收银机",
                "status": "ok",
                "note": None,
                "created_at": datetime(2026, 4, 4, 8, 0, tzinfo=timezone.utc),
            },
            {
                "id": str(uuid.uuid4()),
                "shift_id": SHIFT_ID,
                "tenant_id": TENANT_ID,
                "item": "打印机",
                "status": "failed",
                "note": "卡纸",
                "created_at": datetime(2026, 4, 4, 8, 0, tzinfo=timezone.utc),
            },
        ]

        # summary 端点：execute 序列
        #   call 0 — set_config
        #   call 1 — SELECT shift_records (mappings().first())
        #   call 2 — SELECT shift_device_checklist (mappings().all())

        shift_result = MagicMock()
        shift_mappings = MagicMock()
        shift_mappings.first.return_value = shift_row
        shift_result.mappings.return_value = shift_mappings

        checklist_result = MagicMock()
        checklist_mappings = MagicMock()
        checklist_mappings.all.return_value = checklist_rows
        checklist_result.mappings.return_value = checklist_mappings

        db = AsyncMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _set_config_result(),   # call 0: set_config
            shift_result,           # call 1: SELECT shift
            checklist_result,       # call 2: SELECT checklist
        ])

        app.dependency_overrides[get_db] = _override_get_db(db)
        try:
            with TestClient(app) as client:
                resp = client.get(
                    f"/api/v1/ops/shifts/{SHIFT_ID}/summary",
                    headers=HEADERS,
                )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]

        # 核心字段断言
        assert "cash_balanced" in data
        assert data["cash_balanced"] is True   # cash_diff_fen == 0
        assert data["device_total"] == 2
        assert data["device_failed"] == 1
        assert len(data["failed_devices"]) == 1
        assert data["failed_devices"][0]["item"] == "打印机"
        assert data["status"] == "confirmed"
