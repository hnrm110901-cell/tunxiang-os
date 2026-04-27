"""食安巡检路由测试（共 12 个测试）

覆盖范围（safety_inspection_router）：
  POST /api/v1/ops/safety/inspections/                  — 开始巡检（正常 / DB 异常）
  GET  /api/v1/ops/safety/inspections/                  — 列表（正常 / 带状态过滤）
  GET  /api/v1/ops/safety/inspections/{id}              — 详情（正常 / 404）
  POST /api/v1/ops/safety/inspections/{id}/items/{item_id}/score — 打分（pass / fail）
  POST /api/v1/ops/safety/inspections/{id}/complete     — 完成巡检（合格 / 不合格 / 一票否决）
  POST /api/v1/ops/safety/inspections/{id}/items/{item_id}/correct — 提交整改
  GET  /api/v1/ops/safety/reports/monthly               — 月度报表
  GET  /api/v1/ops/safety/templates/                    — 模板列表

技术约束：
  - safety_inspection_router 使用 asyncpg.connect 直连 DB（不经过 Depends(get_db)）
  - 通过 patch("asyncpg.connect") 注入 mock asyncpg Connection
  - emit_event 通过 patch 屏蔽
  - asyncio.create_task 通过 patch 屏蔽
  - sys.modules 存根注入
"""

from __future__ import annotations

import sys
import types
import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── sys.modules 存根注入（必须在导入路由前完成） ────────────────────────────────


def _ensure_stub(module_path: str, attrs: dict | None = None) -> types.ModuleType:
    if module_path not in sys.modules:
        mod = types.ModuleType(module_path)
        if attrs:
            for k, v in attrs.items():
                setattr(mod, k, v)
        sys.modules[module_path] = mod
    return sys.modules[module_path]


# shared.*
_ensure_stub("shared")
_ensure_stub("shared.ontology")
_ensure_stub("shared.ontology.src")
_db_mod = _ensure_stub("shared.ontology.src.database")
if not hasattr(_db_mod, "get_db"):

    async def _placeholder_get_db():  # pragma: no cover
        yield None

    _db_mod.get_db = _placeholder_get_db

# shared.events.*
_ensure_stub("shared.events")
_ensure_stub("shared.events.src")
_ensure_stub("shared.events.src.emitter", {"emit_event": AsyncMock()})
_ev_types = _ensure_stub("shared.events.src.event_types")

if not hasattr(_ev_types, "SafetyInspectionEventType"):

    class _FakeSafetyInspectionEventType:
        INSPECTION_STARTED = "safety.inspection.started"
        INSPECTION_COMPLETED = "safety.inspection.completed"
        INSPECTION_FAILED = "safety.inspection.failed"
        CRITICAL_ITEM_FAILED = "safety.inspection.critical_item_failed"

    _ev_types.SafetyInspectionEventType = _FakeSafetyInspectionEventType

# structlog 存根
if "structlog" not in sys.modules:
    _sl = types.ModuleType("structlog")
    _sl.get_logger = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
    sys.modules["structlog"] = _sl
else:
    _existing_sl = sys.modules["structlog"]
    if not isinstance(getattr(_existing_sl, "get_logger", None), MagicMock):
        _existing_sl.get_logger = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]

# asyncpg 存根（占位，具体方法在测试中 patch）
if "asyncpg" not in sys.modules:
    _apg = types.ModuleType("asyncpg")
    _apg.connect = AsyncMock()  # type: ignore[attr-defined]
    sys.modules["asyncpg"] = _apg

# ── 导入路由 ────────────────────────────────────────────────────────────────────
from ..api.safety_inspection_router import router as safety_router  # noqa: E402

# ── FastAPI 应用 ────────────────────────────────────────────────────────────────
app = FastAPI()
app.include_router(safety_router)

# ── 常量 ────────────────────────────────────────────────────────────────────────
TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
INSPECTOR_ID = str(uuid.uuid4())
INSPECTION_ID = str(uuid.uuid4())
ITEM_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ── Mock asyncpg Connection 工厂 ─────────────────────────────────────────────


def _make_asyncpg_conn(
    fetchrow_return=None,
    fetch_return=None,
    execute_return="UPDATE 1",
) -> AsyncMock:
    """创建一个 mock asyncpg Connection。"""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=execute_return)
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    conn.fetch = AsyncMock(return_value=fetch_return or [])
    conn.close = AsyncMock()
    return conn


def _make_inspection_row(
    inspection_id: str = INSPECTION_ID,
    status: str = "in_progress",
    pass_threshold: float = 80.0,
    overall_score=None,
    is_passed=None,
) -> MagicMock:
    """构建 asyncpg 风格的巡检行 mock（支持 row["key"] 和 row.key）。"""
    data = {
        "id": uuid.UUID(inspection_id),
        "store_id": uuid.UUID(STORE_ID),
        "inspector_id": uuid.UUID(INSPECTOR_ID),
        "inspection_type": "daily_open",
        "inspection_date": date(2026, 4, 5),
        "started_at": datetime.now(timezone.utc),
        "completed_at": None,
        "overall_score": overall_score,
        "status": status,
        "pass_threshold": pass_threshold,
        "is_passed": is_passed,
        "notes": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    row = MagicMock()
    row.__getitem__ = lambda self, key: data[key]
    for k, v in data.items():
        setattr(row, k, v)
    return row


def _make_item_row(
    item_id: str = ITEM_ID,
    score=90.0,
    weight=1.0,
    result="pass",
    is_critical=False,
) -> MagicMock:
    """构建巡检项目行 mock。"""
    data = {
        "id": uuid.UUID(item_id),
        "item_code": "FS-001",
        "item_name": "冰箱温度",
        "category": "温度控制",
        "weight": weight,
        "score": score,
        "is_critical": is_critical,
        "result": result,
        "photo_url": None,
        "issue_description": None,
        "corrective_action": None,
        "corrected_at": None,
        "created_at": datetime.now(timezone.utc),
    }
    row = MagicMock()
    row.__getitem__ = lambda self, key: data[key]
    for k, v in data.items():
        setattr(row, k, v)
    return row


# ══════════════════════════════════════════════════════════════════════════════
#  start_inspection 测试（2个）
# ══════════════════════════════════════════════════════════════════════════════


class TestStartInspection:
    """POST /api/v1/ops/safety/inspections/"""

    def test_start_inspection_success(self):
        """正常开始巡检 → 201，返回 inspection_id 和 status=in_progress。"""
        conn = _make_asyncpg_conn()

        with patch("asyncpg.connect", return_value=conn):
            with patch("asyncio.create_task"):
                with TestClient(app) as client:
                    resp = client.post(
                        "/api/v1/ops/safety/inspections/",
                        json={
                            "store_id": STORE_ID,
                            "inspector_id": INSPECTOR_ID,
                            "inspection_type": "daily_open",
                            "inspection_date": "2026-04-05",
                            "pass_threshold": 80.0,
                        },
                        headers=HEADERS,
                    )

        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert "inspection_id" in data
        assert data["status"] == "in_progress"
        assert data["store_id"] == STORE_ID
        assert data["inspection_type"] == "daily_open"

    def test_start_inspection_db_error_500(self):
        """asyncpg.connect 抛出异常 → 服务端 500。"""
        with patch("asyncpg.connect", side_effect=OSError("DB connection refused")):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/v1/ops/safety/inspections/",
                    json={
                        "store_id": STORE_ID,
                        "inspector_id": INSPECTOR_ID,
                        "inspection_type": "daily_open",
                    },
                    headers=HEADERS,
                )

        assert resp.status_code == 500


# ══════════════════════════════════════════════════════════════════════════════
#  list_inspections 测试（2个）
# ══════════════════════════════════════════════════════════════════════════════


class TestListInspections:
    """GET /api/v1/ops/safety/inspections/"""

    def test_list_inspections_success(self):
        """正常返回巡检列表，total=1，items 含 inspection_id。"""
        inspection_row = _make_inspection_row()
        count_row = MagicMock()
        count_row.__getitem__ = lambda self, key: 1

        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="SELECT set_config ok")
        conn.fetchrow = AsyncMock(return_value=count_row)
        conn.fetch = AsyncMock(return_value=[inspection_row])
        conn.close = AsyncMock()

        with patch("asyncpg.connect", return_value=conn):
            with TestClient(app) as client:
                resp = client.get(
                    "/api/v1/ops/safety/inspections/",
                    headers=HEADERS,
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert "inspection_id" in data["items"][0]

    def test_list_inspections_with_status_filter(self):
        """GET /inspections/?status=completed — 状态过滤正常工作。"""
        count_row = MagicMock()
        count_row.__getitem__ = lambda self, key: 0

        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="ok")
        conn.fetchrow = AsyncMock(return_value=count_row)
        conn.fetch = AsyncMock(return_value=[])
        conn.close = AsyncMock()

        with patch("asyncpg.connect", return_value=conn):
            with TestClient(app) as client:
                resp = client.get(
                    "/api/v1/ops/safety/inspections/",
                    params={"status": "completed", "store_id": STORE_ID},
                    headers=HEADERS,
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["total"] == 0
        assert body["data"]["items"] == []


# ══════════════════════════════════════════════════════════════════════════════
#  get_inspection（详情）测试（2个）
# ══════════════════════════════════════════════════════════════════════════════


class TestGetInspection:
    """GET /api/v1/ops/safety/inspections/{inspection_id}"""

    def test_get_inspection_success(self):
        """正常返回巡检详情，含 items 数组。"""
        inspection_row = _make_inspection_row()
        item_row = _make_item_row()

        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="ok")
        # fetchrow 第一次返回巡检行（inspection detail）
        conn.fetchrow = AsyncMock(return_value=inspection_row)
        # fetch 返回巡检项目
        conn.fetch = AsyncMock(return_value=[item_row])
        conn.close = AsyncMock()

        with patch("asyncpg.connect", return_value=conn):
            with TestClient(app) as client:
                resp = client.get(
                    f"/api/v1/ops/safety/inspections/{INSPECTION_ID}",
                    headers=HEADERS,
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["inspection_id"] == INSPECTION_ID
        assert "items" in data
        assert len(data["items"]) == 1

    def test_get_inspection_404(self):
        """巡检记录不存在 → 404。"""
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="ok")
        conn.fetchrow = AsyncMock(return_value=None)  # 不存在
        conn.close = AsyncMock()

        with patch("asyncpg.connect", return_value=conn):
            with TestClient(app) as client:
                resp = client.get(
                    f"/api/v1/ops/safety/inspections/{INSPECTION_ID}",
                    headers=HEADERS,
                )

        assert resp.status_code == 404
        body = resp.json()
        assert "不存在" in body["detail"]


# ══════════════════════════════════════════════════════════════════════════════
#  score_item 测试（2个）
# ══════════════════════════════════════════════════════════════════════════════


class TestScoreItem:
    """POST /api/v1/ops/safety/inspections/{id}/items/{item_id}/score"""

    def test_score_item_pass(self):
        """正常打分 result=pass → 200，返回 score 和 result。"""
        conn = _make_asyncpg_conn(execute_return="UPDATE 1")

        with patch("asyncpg.connect", return_value=conn):
            with patch("asyncio.create_task"):
                with TestClient(app) as client:
                    resp = client.post(
                        f"/api/v1/ops/safety/inspections/{INSPECTION_ID}/items/{ITEM_ID}/score",
                        json={"score": 90.0, "result": "pass"},
                        headers=HEADERS,
                    )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["score"] == 90.0
        assert body["data"]["result"] == "pass"
        assert body["data"]["item_id"] == ITEM_ID

    def test_score_item_fail_critical_emits_event(self):
        """result=fail，非关键项 → 200，不触发 CRITICAL_ITEM_FAILED 事件（通过 create_task 屏蔽验证）。"""
        # 第一个 connect 用于 UPDATE，第二个 connect 用于查询 is_critical
        item_row = _make_item_row(is_critical=False, result="fail", score=30.0)
        conn1 = _make_asyncpg_conn(execute_return="UPDATE 1")
        conn2 = _make_asyncpg_conn(fetchrow_return=item_row)

        connect_calls = [conn1, conn2]
        with patch("asyncpg.connect", side_effect=connect_calls):
            with patch("asyncio.create_task") as mock_task:
                with TestClient(app) as client:
                    resp = client.post(
                        f"/api/v1/ops/safety/inspections/{INSPECTION_ID}/items/{ITEM_ID}/score",
                        json={"score": 30.0, "result": "fail", "issue_description": "温度偏高"},
                        headers=HEADERS,
                    )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["result"] == "fail"
        # 非关键项不应发射 CRITICAL_ITEM_FAILED 事件
        mock_task.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
#  complete_inspection 测试（3个）
# ══════════════════════════════════════════════════════════════════════════════


class TestCompleteInspection:
    """POST /api/v1/ops/safety/inspections/{id}/complete"""

    def _make_item_rows(self, items_data: list[dict]) -> list[MagicMock]:
        rows = []
        for d in items_data:
            row = MagicMock()
            row.__getitem__ = lambda self, key, _d=d: _d[key]
            for k, v in d.items():
                setattr(row, k, v)
            rows.append(row)
        return rows

    def test_complete_inspection_passed(self):
        """全部 pass，平均分 90 >= 80 阈值 → is_passed=True，status=completed。"""
        inspection_row = _make_inspection_row(status="in_progress", pass_threshold=80.0)
        items = self._make_item_rows(
            [
                {"score": 90.0, "weight": 1.0, "is_critical": False, "result": "pass"},
                {"score": 85.0, "weight": 1.0, "is_critical": False, "result": "pass"},
            ]
        )

        conn1 = AsyncMock()
        conn1.execute = AsyncMock(return_value="ok")
        conn1.fetchrow = AsyncMock(return_value=inspection_row)
        conn1.fetch = AsyncMock(return_value=items)
        conn1.close = AsyncMock()

        conn2 = AsyncMock()
        conn2.execute = AsyncMock(return_value="UPDATE 1")
        conn2.close = AsyncMock()

        connect_side_effects = [conn1, conn2]

        with patch("asyncpg.connect", side_effect=connect_side_effects):
            with patch("asyncio.create_task"):
                with TestClient(app) as client:
                    resp = client.post(
                        f"/api/v1/ops/safety/inspections/{INSPECTION_ID}/complete",
                        headers=HEADERS,
                    )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["is_passed"] is True
        assert data["status"] == "completed"
        assert data["has_critical_fail"] is False
        assert data["overall_score"] == 87.5

    def test_complete_inspection_failed_low_score(self):
        """得分 60 < 80 阈值 → is_passed=False，status=failed。"""
        inspection_row = _make_inspection_row(status="in_progress", pass_threshold=80.0)
        items = self._make_item_rows(
            [
                {"score": 60.0, "weight": 1.0, "is_critical": False, "result": "pass"},
            ]
        )

        conn1 = AsyncMock()
        conn1.execute = AsyncMock(return_value="ok")
        conn1.fetchrow = AsyncMock(return_value=inspection_row)
        conn1.fetch = AsyncMock(return_value=items)
        conn1.close = AsyncMock()

        conn2 = AsyncMock()
        conn2.execute = AsyncMock(return_value="UPDATE 1")
        conn2.close = AsyncMock()

        with patch("asyncpg.connect", side_effect=[conn1, conn2]):
            with patch("asyncio.create_task"):
                with TestClient(app) as client:
                    resp = client.post(
                        f"/api/v1/ops/safety/inspections/{INSPECTION_ID}/complete",
                        headers=HEADERS,
                    )

        assert resp.status_code == 200
        body = resp.json()
        data = body["data"]
        assert data["is_passed"] is False
        assert data["status"] == "failed"

    def test_complete_inspection_critical_fail_veto(self):
        """关键项 fail → 一票否决，即使平均分 >= 阈值也 is_passed=False。"""
        inspection_row = _make_inspection_row(status="in_progress", pass_threshold=80.0)
        items = self._make_item_rows(
            [
                {"score": 95.0, "weight": 1.0, "is_critical": True, "result": "fail"},  # 关键项不合格
                {"score": 90.0, "weight": 1.0, "is_critical": False, "result": "pass"},
            ]
        )

        conn1 = AsyncMock()
        conn1.execute = AsyncMock(return_value="ok")
        conn1.fetchrow = AsyncMock(return_value=inspection_row)
        conn1.fetch = AsyncMock(return_value=items)
        conn1.close = AsyncMock()

        conn2 = AsyncMock()
        conn2.execute = AsyncMock(return_value="UPDATE 1")
        conn2.close = AsyncMock()

        with patch("asyncpg.connect", side_effect=[conn1, conn2]):
            with patch("asyncio.create_task"):
                with TestClient(app) as client:
                    resp = client.post(
                        f"/api/v1/ops/safety/inspections/{INSPECTION_ID}/complete",
                        headers=HEADERS,
                    )

        assert resp.status_code == 200
        body = resp.json()
        data = body["data"]
        assert data["has_critical_fail"] is True
        assert data["is_passed"] is False
        assert data["status"] == "failed"


# ══════════════════════════════════════════════════════════════════════════════
#  correct_item 测试（1个）
# ══════════════════════════════════════════════════════════════════════════════


class TestCorrectItem:
    """POST /api/v1/ops/safety/inspections/{id}/items/{item_id}/correct"""

    def test_correct_item_success(self):
        """正常提交整改 → 200，返回 corrective_action 和 corrected_at。"""
        conn = _make_asyncpg_conn(execute_return="UPDATE 1")

        with patch("asyncpg.connect", return_value=conn):
            with TestClient(app) as client:
                resp = client.post(
                    f"/api/v1/ops/safety/inspections/{INSPECTION_ID}/items/{ITEM_ID}/correct",
                    json={"corrective_action": "已调整冰箱温度至4℃以下"},
                    headers=HEADERS,
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["corrective_action"] == "已调整冰箱温度至4℃以下"
        assert "corrected_at" in data
        assert data["item_id"] == ITEM_ID


# ══════════════════════════════════════════════════════════════════════════════
#  monthly_report 测试（1个）
# ══════════════════════════════════════════════════════════════════════════════


class TestMonthlyReport:
    """GET /api/v1/ops/safety/reports/monthly"""

    def test_monthly_report_success(self):
        """正常返回月度报表统计数据。"""
        summary_row = MagicMock()
        summary_data = {
            "total_inspections": 10,
            "passed_count": 8,
            "failed_count": 2,
            "avg_score": 85.5,
            "completed_count": 10,
        }
        summary_row.__getitem__ = lambda self, key: summary_data.get(key)
        for k, v in summary_data.items():
            setattr(summary_row, k, v)

        correction_row = MagicMock()
        correction_data = {"total_fail_items": 5, "corrected_items": 4}
        correction_row.__getitem__ = lambda self, key: correction_data.get(key)
        for k, v in correction_data.items():
            setattr(correction_row, k, v)

        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="ok")
        conn.fetchrow = AsyncMock(side_effect=[summary_row, correction_row])
        conn.close = AsyncMock()

        with patch("asyncpg.connect", return_value=conn):
            with TestClient(app) as client:
                resp = client.get(
                    "/api/v1/ops/safety/reports/monthly",
                    params={"store_id": STORE_ID, "year": 2026, "month": 4},
                    headers=HEADERS,
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["total_inspections"] == 10
        assert data["passed_count"] == 8
        assert data["failed_count"] == 2
        assert data["pass_rate"] == pytest.approx(0.8, abs=1e-4)
        assert data["avg_score"] == pytest.approx(85.5, abs=0.01)
        assert data["correction_rate"] == pytest.approx(0.8, abs=1e-4)


# ══════════════════════════════════════════════════════════════════════════════
#  list_templates 测试（1个）
# ══════════════════════════════════════════════════════════════════════════════


class TestListTemplates:
    """GET /api/v1/ops/safety/templates/"""

    def test_list_templates_success(self):
        """正常返回模板列表，total=1，含 item_count。"""

        tpl_items = [{"code": "FS-001", "name": "冰箱温度", "weight": 1.0}]
        tpl_row = MagicMock()
        tpl_data = {
            "id": uuid.UUID(str(uuid.uuid4())),
            "brand_id": uuid.UUID(str(uuid.uuid4())),
            "name": "日常开店巡检模板",
            "inspection_type": "daily_open",
            "items": tpl_items,
            "created_at": datetime.now(timezone.utc),
        }
        tpl_row.__getitem__ = lambda self, key: tpl_data[key]
        for k, v in tpl_data.items():
            setattr(tpl_row, k, v)

        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="ok")
        conn.fetch = AsyncMock(return_value=[tpl_row])
        conn.close = AsyncMock()

        with patch("asyncpg.connect", return_value=conn):
            with TestClient(app) as client:
                resp = client.get(
                    "/api/v1/ops/safety/templates/",
                    headers=HEADERS,
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["total"] == 1
        assert len(data["items"]) == 1
        tpl = data["items"][0]
        assert tpl["name"] == "日常开店巡检模板"
        assert tpl["item_count"] == 1
        assert tpl["inspection_type"] == "daily_open"
