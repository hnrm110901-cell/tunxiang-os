"""异常检测路由测试

覆盖：
  GET  /api/v1/intel/anomalies          — 当前异常列表（DB成功 / DB失败回落 mock / include_dismissed）
  POST /api/v1/intel/anomalies/{id}/dismiss — 标记已知悉（DB成功 / DB失败回落 mock）

测试策略：
  - 路由文件内部定义 get_db 依赖，通过 app.dependency_overrides 注入 mock
  - 所有 DB 调用均使用 AsyncMock 模拟
  - 覆盖 happy path + DB 异常回落 + 参数校验场景
"""

import sys
import types
import uuid

# ─── 注入假模块（路由文件顶层 import 所需）───────────────────────────────────

_fake_structlog = types.ModuleType("structlog")
_fake_structlog.get_logger = lambda *a, **kw: types.SimpleNamespace(
    warning=lambda *a, **kw: None,
    info=lambda *a, **kw: None,
)
sys.modules.setdefault("structlog", _fake_structlog)

# sqlalchemy 相关（路由只用 text / SQLAlchemyError / AsyncSession）
_fake_sa = types.ModuleType("sqlalchemy")
_fake_sa.text = lambda sql: sql
_fake_sa_exc = types.ModuleType("sqlalchemy.exc")


class _SQLAlchemyError(Exception):
    pass


_fake_sa_exc.SQLAlchemyError = _SQLAlchemyError
_fake_sa_async = types.ModuleType("sqlalchemy.ext.asyncio")
_fake_sa_async.AsyncSession = object
sys.modules.setdefault("sqlalchemy", _fake_sa)
sys.modules.setdefault("sqlalchemy.exc", _fake_sa_exc)
sys.modules.setdefault("sqlalchemy.ext", types.ModuleType("sqlalchemy.ext"))
sys.modules.setdefault("sqlalchemy.ext.asyncio", _fake_sa_async)

# ─── 正式导入 ─────────────────────────────────────────────────────────────────

import importlib

# 动态导入路由模块（路径通过文件系统而非包）
import importlib.util
import pathlib
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

_route_path = pathlib.Path(__file__).parent.parent / "api" / "anomaly_routes.py"
_spec = importlib.util.spec_from_file_location("anomaly_routes", _route_path)
_anomaly_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_anomaly_mod)

TENANT_ID = str(uuid.uuid4())
HEADERS = {"X-Tenant-ID": TENANT_ID}


def _make_app(mock_db: AsyncMock) -> TestClient:
    """创建挂载 anomaly_routes 的 FastAPI 测试 app，注入 mock_db 依赖"""
    app = FastAPI()
    app.include_router(_anomaly_mod.router)

    async def _override_get_db():
        yield mock_db

    app.dependency_overrides[_anomaly_mod.get_db] = _override_get_db
    return TestClient(app, raise_server_exceptions=False)


# ═══════════════════════════════════════════════════════════════════════════════
# 工具函数：构建 execute side_effect 队列
# ═══════════════════════════════════════════════════════════════════════════════


def _scalar_mock(value):
    m = MagicMock()
    m.scalar.return_value = value
    return m


def _fetchone_mock(row):
    m = MagicMock()
    m.fetchone.return_value = row
    return m


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/intel/anomalies — 异常列表
# ═══════════════════════════════════════════════════════════════════════════════


class TestListAnomalies:
    """GET /api/v1/intel/anomalies"""

    def _db_with_no_anomalies(self) -> AsyncMock:
        """构建返回零值的 mock DB，不触发任何阈值"""
        mock_db = AsyncMock()
        # 检测顺序：
        #   _set_rls (1次)
        #   _detect_revenue_drop: 每天 2次 execute (this + yoy) × min(days,7) = 14次
        #   _detect_cost_spike:   每天 2次 execute × min(days,7) = 14次
        #   _detect_high_refund:  1次
        #   _detect_slow_kitchen: 1次
        #   _detect_expiry_risk:  1次
        # 总计 = 1 + 14 + 14 + 1 + 1 + 1 = 32 次 (days=7 默认)
        side_effects = []
        # set_config
        side_effects.append(MagicMock())
        # revenue_drop: 7天, 每天 this=0, yoy=0 → 不触发
        for _ in range(7):
            side_effects.append(_scalar_mock(0))  # this_rev
            side_effects.append(_scalar_mock(0))  # yoy_rev
        # cost_spike: 7天, 每天 revenue=0, cost=0 → 不触发
        for _ in range(7):
            side_effects.append(_scalar_mock(0))  # revenue
            side_effects.append(_scalar_mock(0))  # cost
        # high_refund: completed=100, refunded=0 → rate=0 → 不触发
        side_effects.append(_fetchone_mock((100, 0)))
        # slow_kitchen: avg_min=18 ≤ 30 → 不触发
        side_effects.append(_scalar_mock(18))
        # expiry_risk: count=5 ≤ 10 → 不触发
        side_effects.append(_scalar_mock(5))

        mock_db.execute = AsyncMock(side_effect=side_effects)
        mock_db.commit = AsyncMock()
        return mock_db

    def test_list_anomalies_happy_path_no_anomalies(self):
        """正常场景：DB 无触发阈值，返回空列表"""
        mock_db = self._db_with_no_anomalies()
        client = _make_app(mock_db)
        resp = client.get("/api/v1/intel/anomalies", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 0
        assert body["data"]["_is_mock"] is False
        assert isinstance(body["data"]["anomalies"], list)

    def test_list_anomalies_with_expiry_risk_triggered(self):
        """库存临期数超阈值 → 返回 expiry_risk 异常"""
        mock_db = AsyncMock()
        side_effects = [MagicMock()]  # set_config
        for _ in range(7):  # revenue_drop: yoy=0 → 不触发
            side_effects += [_scalar_mock(0), _scalar_mock(0)]
        for _ in range(7):  # cost_spike: revenue=0 → 不触发
            side_effects += [_scalar_mock(0), _scalar_mock(0)]
        side_effects.append(_fetchone_mock((100, 0)))  # high_refund: 不触发
        side_effects.append(_scalar_mock(18))  # slow_kitchen: 不触发
        side_effects.append(_scalar_mock(15))  # expiry_risk: 15 > 10 → 触发

        mock_db.execute = AsyncMock(side_effect=side_effects)
        client = _make_app(mock_db)
        resp = client.get("/api/v1/intel/anomalies", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["total"] >= 1
        types_ = {a["type"] for a in body["data"]["anomalies"]}
        assert "expiry_risk" in types_

    def test_list_anomalies_with_slow_kitchen_triggered(self):
        """出餐时间超30分钟 → 返回 slow_kitchen 异常"""
        mock_db = AsyncMock()
        side_effects = [MagicMock()]  # set_config
        for _ in range(7):
            side_effects += [_scalar_mock(0), _scalar_mock(0)]  # revenue_drop
        for _ in range(7):
            side_effects += [_scalar_mock(0), _scalar_mock(0)]  # cost_spike
        side_effects.append(_fetchone_mock((100, 0)))  # high_refund
        side_effects.append(_scalar_mock(35))  # slow_kitchen: 35 > 30 触发
        side_effects.append(_scalar_mock(5))  # expiry_risk

        mock_db.execute = AsyncMock(side_effect=side_effects)
        client = _make_app(mock_db)
        resp = client.get("/api/v1/intel/anomalies", headers=HEADERS)
        body = resp.json()
        types_ = {a["type"] for a in body["data"]["anomalies"]}
        assert "slow_kitchen" in types_

    def test_list_anomalies_with_high_refund_triggered(self):
        """退单率超5% → 返回 high_refund 异常"""
        mock_db = AsyncMock()
        side_effects = [MagicMock()]
        for _ in range(7):
            side_effects += [_scalar_mock(0), _scalar_mock(0)]
        for _ in range(7):
            side_effects += [_scalar_mock(0), _scalar_mock(0)]
        # completed=90, refunded=10 → rate=10%>5% 触发
        side_effects.append(_fetchone_mock((90, 10)))
        side_effects.append(_scalar_mock(18))
        side_effects.append(_scalar_mock(5))

        mock_db.execute = AsyncMock(side_effect=side_effects)
        client = _make_app(mock_db)
        resp = client.get("/api/v1/intel/anomalies", headers=HEADERS)
        body = resp.json()
        types_ = {a["type"] for a in body["data"]["anomalies"]}
        assert "high_refund" in types_

    def test_list_anomalies_db_error_returns_mock(self):
        """DB 抛出异常 → 回落 mock 数据，_is_mock=True"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=_SQLAlchemyError("connection failed"))
        client = _make_app(mock_db)
        resp = client.get("/api/v1/intel/anomalies", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["_is_mock"] is True
        assert body["data"]["total"] > 0

    def test_list_anomalies_include_dismissed_false_by_default(self):
        """默认不包含 dismissed=True 的异常（mock回落场景验证）"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=_SQLAlchemyError("db down"))
        client = _make_app(mock_db)
        resp = client.get("/api/v1/intel/anomalies", headers=HEADERS)
        body = resp.json()
        # mock 数据中 mock-003 是 dismissed=True，默认不返回
        dismissed_items = [a for a in body["data"]["anomalies"] if a.get("dismissed") is True]
        assert len(dismissed_items) == 0

    def test_list_anomalies_include_dismissed_true(self):
        """include_dismissed=true → 包含已知悉的异常"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=_SQLAlchemyError("db down"))
        client = _make_app(mock_db)
        resp = client.get("/api/v1/intel/anomalies?include_dismissed=true", headers=HEADERS)
        body = resp.json()
        dismissed_items = [a for a in body["data"]["anomalies"] if a.get("dismissed") is True]
        assert len(dismissed_items) >= 1

    def test_list_anomalies_missing_tenant_header(self):
        """缺少 X-Tenant-ID → 422"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        client = _make_app(mock_db)
        resp = client.get("/api/v1/intel/anomalies")
        assert resp.status_code == 422

    def test_list_anomalies_invalid_tenant_id(self):
        """X-Tenant-ID 格式无效 → 400"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        client = _make_app(mock_db)
        resp = client.get("/api/v1/intel/anomalies", headers={"X-Tenant-ID": "not-a-uuid"})
        assert resp.status_code == 400

    def test_list_anomalies_severity_counts_correct(self):
        """critical_count 和 warning_count 字段正确统计"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=_SQLAlchemyError("db down"))
        client = _make_app(mock_db)
        resp = client.get("/api/v1/intel/anomalies", headers=HEADERS)
        body = resp.json()
        data = body["data"]
        anomalies = data["anomalies"]
        expected_critical = sum(1 for a in anomalies if a.get("severity") == "critical")
        expected_warning = sum(1 for a in anomalies if a.get("severity") == "warning")
        assert data["critical_count"] == expected_critical
        assert data["warning_count"] == expected_warning

    def test_list_anomalies_revenue_drop_triggered(self):
        """营收同比下滑超20% → 返回 revenue_drop 异常"""
        mock_db = AsyncMock()
        side_effects = [MagicMock()]  # set_config
        # revenue_drop: 第0天 this=8000, yoy=12000 → drop=33%>20% → 触发
        side_effects += [_scalar_mock(8000), _scalar_mock(12000)]
        # 剩余6天不触发
        for _ in range(6):
            side_effects += [_scalar_mock(0), _scalar_mock(0)]
        # cost_spike: 7天不触发
        for _ in range(7):
            side_effects += [_scalar_mock(0), _scalar_mock(0)]
        side_effects.append(_fetchone_mock((100, 0)))
        side_effects.append(_scalar_mock(18))
        side_effects.append(_scalar_mock(5))

        mock_db.execute = AsyncMock(side_effect=side_effects)
        client = _make_app(mock_db)
        resp = client.get("/api/v1/intel/anomalies", headers=HEADERS)
        body = resp.json()
        types_ = {a["type"] for a in body["data"]["anomalies"]}
        assert "revenue_drop" in types_

    def test_list_anomalies_cost_spike_triggered(self):
        """食材成本占比超60% → 返回 cost_spike 异常"""
        mock_db = AsyncMock()
        side_effects = [MagicMock()]  # set_config
        # revenue_drop: 不触发
        for _ in range(7):
            side_effects += [_scalar_mock(0), _scalar_mock(0)]
        # cost_spike: 第0天 revenue=10000, cost=7000 → ratio=70%>60% → 触发
        side_effects += [_scalar_mock(10000), _scalar_mock(7000)]
        for _ in range(6):
            side_effects += [_scalar_mock(0), _scalar_mock(0)]
        side_effects.append(_fetchone_mock((100, 0)))
        side_effects.append(_scalar_mock(18))
        side_effects.append(_scalar_mock(5))

        mock_db.execute = AsyncMock(side_effect=side_effects)
        client = _make_app(mock_db)
        resp = client.get("/api/v1/intel/anomalies", headers=HEADERS)
        body = resp.json()
        types_ = {a["type"] for a in body["data"]["anomalies"]}
        assert "cost_spike" in types_


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/v1/intel/anomalies/{id}/dismiss — 标记异常已知悉
# ═══════════════════════════════════════════════════════════════════════════════


class TestDismissAnomaly:
    """POST /api/v1/intel/anomalies/{id}/dismiss"""

    def test_dismiss_anomaly_happy_path(self):
        """正常标记已知悉 → 返回 dismissed=True"""
        mock_db = AsyncMock()
        # side_effect: set_config + INSERT ON CONFLICT
        mock_db.execute = AsyncMock(side_effect=[MagicMock(), MagicMock()])
        mock_db.commit = AsyncMock()
        client = _make_app(mock_db)

        anomaly_id = "test-anomaly-001"
        resp = client.post(
            f"/api/v1/intel/anomalies/{anomaly_id}/dismiss",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["dismissed"] is True
        assert body["data"]["anomaly_id"] == anomaly_id
        assert "dismissed_at" in body["data"]

    def test_dismiss_anomaly_db_error_returns_mock(self):
        """DB 异常 → 回落 mock 成功响应，_is_mock=True"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=_SQLAlchemyError("insert failed"))
        mock_db.commit = AsyncMock()
        client = _make_app(mock_db)

        resp = client.post(
            "/api/v1/intel/anomalies/mock-001/dismiss",
            headers=HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["dismissed"] is True
        assert body["data"].get("_is_mock") is True

    def test_dismiss_anomaly_missing_tenant_header(self):
        """缺少 X-Tenant-ID → 422"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        client = _make_app(mock_db)
        resp = client.post("/api/v1/intel/anomalies/mock-001/dismiss")
        assert resp.status_code == 422

    def test_dismiss_anomaly_invalid_tenant_id(self):
        """X-Tenant-ID 格式无效 → 400"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        client = _make_app(mock_db)
        resp = client.post(
            "/api/v1/intel/anomalies/mock-001/dismiss",
            headers={"X-Tenant-ID": "bad-id"},
        )
        assert resp.status_code == 400

    def test_dismiss_anomaly_commit_called(self):
        """正常流程中 db.commit() 必须被调用"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[MagicMock(), MagicMock()])
        mock_db.commit = AsyncMock()
        client = _make_app(mock_db)

        client.post("/api/v1/intel/anomalies/some-id/dismiss", headers=HEADERS)
        mock_db.commit.assert_awaited_once()

    def test_dismiss_anomaly_response_schema(self):
        """返回结构符合 {ok, data, error} 规范"""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[MagicMock(), MagicMock()])
        mock_db.commit = AsyncMock()
        client = _make_app(mock_db)
        resp = client.post("/api/v1/intel/anomalies/abc-123/dismiss", headers=HEADERS)
        body = resp.json()
        assert "ok" in body
        assert "data" in body
        assert "error" in body


# ═══════════════════════════════════════════════════════════════════════════════
# Regression: 5 detector per-detector try (issue #701)
#   单 detector 失败不应短路其他 4, 200 桌并发场景防驾驶舱"假空白"误判
# ═══════════════════════════════════════════════════════════════════════════════


class TestPerDetectorTry:
    """单 detector 失败 graceful skip, 其他 4 detector 数据照常返回 (issue #701)"""

    def test_single_detector_failure_others_succeed(self, monkeypatch):
        """mock cost_spike 抛 SQLAlchemyError, 其他 4 detector 返 fixture → 不短路"""
        # 给其他 4 detector 各注入 1 条假 anomaly, cost_spike 失败
        fake_revenue = [{"type": "revenue_drop", "severity": "critical", "occurred_at": "2026-05-16T00:00:00Z"}]
        fake_refund = [{"type": "high_refund", "severity": "warning", "occurred_at": "2026-05-16T00:00:00Z"}]
        fake_slow = [{"type": "slow_kitchen", "severity": "warning", "occurred_at": "2026-05-16T00:00:00Z"}]
        fake_expiry = [{"type": "expiry_risk", "severity": "warning", "occurred_at": "2026-05-16T00:00:00Z"}]

        async def _ok_revenue(*a, **kw):
            return fake_revenue

        async def _fail_cost(*a, **kw):
            raise _SQLAlchemyError("cost_records table not exist")

        async def _ok_refund(*a, **kw):
            return fake_refund

        async def _ok_slow(*a, **kw):
            return fake_slow

        async def _ok_expiry(*a, **kw):
            return fake_expiry

        monkeypatch.setattr(_anomaly_mod, "_detect_revenue_drop", _ok_revenue)
        monkeypatch.setattr(_anomaly_mod, "_detect_cost_spike", _fail_cost)
        monkeypatch.setattr(_anomaly_mod, "_detect_high_refund", _ok_refund)
        monkeypatch.setattr(_anomaly_mod, "_detect_slow_kitchen", _ok_slow)
        monkeypatch.setattr(_anomaly_mod, "_detect_expiry_risk", _ok_expiry)

        mock_db = AsyncMock()
        # _set_rls + _fetch_anomalies_from_db (compliance_alerts + orders 2次 execute)
        mock_db.execute = AsyncMock(return_value=MagicMock(fetchall=lambda: []))
        client = _make_app(mock_db)
        resp = client.get("/api/v1/intel/anomalies", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        types_ = {a["type"] for a in body["data"]["anomalies"]}
        # cost_spike 失败 graceful skip, 其他 4 都应回来
        assert "revenue_drop" in types_
        assert "high_refund" in types_
        assert "slow_kitchen" in types_
        assert "expiry_risk" in types_
        # cost_spike 未返
        assert "cost_spike" not in types_
        # 至少 4 (cost_spike skip 但其他 4 都在)
        assert body["data"]["total"] >= 4

    def test_logger_includes_detector_name(self, monkeypatch):
        """单 detector fail 时 log 事件含 detector 名便于排查"""
        captured: list[dict] = []

        def _capture_warning(event: str, **kwargs):
            captured.append({"event": event, **kwargs})

        # 替换模块 logger 为 capture stub
        fake_logger = types.SimpleNamespace(
            warning=_capture_warning,
            info=lambda *a, **kw: None,
        )
        monkeypatch.setattr(_anomaly_mod, "logger", fake_logger)

        async def _ok_empty(*a, **kw):
            return []

        async def _fail_cost(*a, **kw):
            raise _SQLAlchemyError("boom")

        monkeypatch.setattr(_anomaly_mod, "_detect_revenue_drop", _ok_empty)
        monkeypatch.setattr(_anomaly_mod, "_detect_cost_spike", _fail_cost)
        monkeypatch.setattr(_anomaly_mod, "_detect_high_refund", _ok_empty)
        monkeypatch.setattr(_anomaly_mod, "_detect_slow_kitchen", _ok_empty)
        monkeypatch.setattr(_anomaly_mod, "_detect_expiry_risk", _ok_empty)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(fetchall=lambda: []))
        client = _make_app(mock_db)
        resp = client.get("/api/v1/intel/anomalies", headers=HEADERS)
        assert resp.status_code == 200

        # 验证至少 1 条 anomaly_detector_db_error log 含 detector="cost_spike"
        detector_logs = [c for c in captured if c.get("event") == "anomaly_detector_db_error"]
        assert len(detector_logs) >= 1
        assert detector_logs[0].get("detector") == "cost_spike"

    def test_session_pollution_recovers_after_rollback(self, monkeypatch):
        """detector 1 fail 后 rollback+RLS 重设, session 恢复, detector 2 能成功跑

        验证 feedback_asyncpg_rollback_after_integrity_error.md 描述的 session
        污染问题已修复: SELECT 失败 → rollback → _set_rls → 后续 detector 可继续执行.
        """
        mock_set_rls = AsyncMock()
        monkeypatch.setattr(_anomaly_mod, "_set_rls", mock_set_rls)

        call_count = 0

        async def _fail_first_then_ok(*a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _SQLAlchemyError("table not exist: cost_records")
            return []

        fake_result = [{"type": "high_refund", "severity": "warning", "occurred_at": "2026-05-16T00:00:00Z"}]

        async def _ok_refund(*a, **kw):
            return fake_result

        async def _ok_empty(*a, **kw):
            return []

        monkeypatch.setattr(_anomaly_mod, "_detect_revenue_drop", _fail_first_then_ok)
        monkeypatch.setattr(_anomaly_mod, "_detect_cost_spike", _ok_empty)
        monkeypatch.setattr(_anomaly_mod, "_detect_high_refund", _ok_refund)
        monkeypatch.setattr(_anomaly_mod, "_detect_slow_kitchen", _ok_empty)
        monkeypatch.setattr(_anomaly_mod, "_detect_expiry_risk", _ok_empty)

        mock_db = AsyncMock()
        mock_db.rollback = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(fetchall=lambda: []))
        client = _make_app(mock_db)
        resp = client.get("/api/v1/intel/anomalies", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()

        # revenue_drop fail → rollback + RLS 重设 → 后续 detector 继续
        mock_db.rollback.assert_awaited()
        # _set_rls 应被调用至少 2 次: 1 次初始 + 1 次 rollback 后重设
        assert mock_set_rls.await_count >= 2
        # high_refund (detector 3) 正常返回数据
        types_ = {a["type"] for a in body["data"]["anomalies"]}
        assert "high_refund" in types_


# ═══════════════════════════════════════════════════════════════════════════════
# Regression: _fetch_anomalies_from_db 每 sub-fetch 独立 try (issue #716)
#   compliance/revenue 任一 fail 不短路另一; rollback + RLS 重设防事务污染
# ═══════════════════════════════════════════════════════════════════════════════


class TestSubFetchTry:
    """_fetch_anomalies_from_db 每 sub-fetch 独立 try, 单 fail 不短路另一 (issue #716)."""

    def test_sub_fetch_compliance_failure_revenue_succeeds(self, monkeypatch):
        """compliance sub-fetch SQLAlchemyError → rollback + 重设 RLS, revenue 数据仍返回."""
        import asyncio

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        mock_db.rollback = AsyncMock()

        revenue_fixture = [
            {
                "id": "rev-1",
                "type": "revenue_drop",
                "severity": "warning",
                "description": "store-X 营收下滑",
                "detail": {"store_id": "store-X"},
                "occurred_at": "2026-05-16T00:00:00+00:00",
                "dismissed": False,
            }
        ]

        compliance_calls = {"n": 0}
        revenue_calls = {"n": 0}

        async def _fail_compliance(*a, **kw):
            compliance_calls["n"] += 1
            raise _SQLAlchemyError("compliance_alerts not found")

        async def _ok_revenue(*a, **kw):
            revenue_calls["n"] += 1
            return revenue_fixture

        monkeypatch.setattr(_anomaly_mod, "_fetch_compliance_anomalies", _fail_compliance)
        monkeypatch.setattr(_anomaly_mod, "_fetch_revenue_anomalies", _ok_revenue)

        tid = uuid.UUID(TENANT_ID)
        result = asyncio.get_event_loop().run_until_complete(
            _anomaly_mod._fetch_anomalies_from_db(mock_db, tid, None, 7)
        )

        # compliance fail 后 revenue 仍跑且返
        assert compliance_calls["n"] == 1
        assert revenue_calls["n"] == 1
        assert len(result) == 1
        assert result[0]["id"] == "rev-1"
        # AsyncSession rollback + _set_rls 重调
        mock_db.rollback.assert_awaited_once()
        # _set_rls 通过 db.execute(set_config) 实现; 验证至少有一次 execute (重设 RLS)
        assert mock_db.execute.await_count >= 1

    def test_sub_fetch_revenue_failure_compliance_already_collected(self, monkeypatch):
        """compliance 先成功收集, revenue fail → compliance 数据保住."""
        import asyncio

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        mock_db.rollback = AsyncMock()

        compliance_fixture = [
            {
                "id": "comp-1",
                "type": "compliance_alert",
                "severity": "critical",
                "description": "证件过期",
                "detail": {},
                "occurred_at": "2026-05-16T00:00:00+00:00",
                "dismissed": False,
            }
        ]

        async def _ok_compliance(*a, **kw):
            return compliance_fixture

        async def _fail_revenue(*a, **kw):
            raise _SQLAlchemyError("orders table missing total_fen column")

        monkeypatch.setattr(_anomaly_mod, "_fetch_compliance_anomalies", _ok_compliance)
        monkeypatch.setattr(_anomaly_mod, "_fetch_revenue_anomalies", _fail_revenue)

        tid = uuid.UUID(TENANT_ID)
        result = asyncio.get_event_loop().run_until_complete(
            _anomaly_mod._fetch_anomalies_from_db(mock_db, tid, None, 7)
        )

        # compliance 保住, revenue fail 不短路
        assert len(result) == 1
        assert result[0]["id"] == "comp-1"
        mock_db.rollback.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════════════════
# Regression: 外层 except 保留 inner 已收集数据 (issue #716)
#   原 anomalies=[] 覆盖丢弃 detector + sub-fetch 已 extend; 应保留并返回
# ═══════════════════════════════════════════════════════════════════════════════


class TestOuterExceptPreserves:
    """list_anomalies 外层 except 保留 inner 已收集 detector + sub-fetch 数据 (issue #716)."""

    def test_outer_except_preserves_partial_anomalies(self, monkeypatch):
        """detector 收集 N 条 → 外层 except 触发时仍返回 N 条 (非空数组)."""
        # detector 收集 1 条 expiry_risk; _fetch_anomalies_from_db 抛 → 外层 except 接住
        fake_expiry = [
            {
                "id": "exp-1",
                "type": "expiry_risk",
                "severity": "critical",
                "description": "7天内临期食材10种",
                "detail": {},
                "occurred_at": "2026-05-16T00:00:00+00:00",
                "dismissed": False,
            }
        ]

        async def _ok_empty(*a, **kw):
            return []

        async def _ok_expiry(*a, **kw):
            return fake_expiry

        async def _fail_fetch(*a, **kw):
            raise _SQLAlchemyError("compliance + revenue 全死")

        monkeypatch.setattr(_anomaly_mod, "_detect_revenue_drop", _ok_empty)
        monkeypatch.setattr(_anomaly_mod, "_detect_cost_spike", _ok_empty)
        monkeypatch.setattr(_anomaly_mod, "_detect_high_refund", _ok_empty)
        monkeypatch.setattr(_anomaly_mod, "_detect_slow_kitchen", _ok_empty)
        monkeypatch.setattr(_anomaly_mod, "_detect_expiry_risk", _ok_expiry)
        monkeypatch.setattr(_anomaly_mod, "_fetch_anomalies_from_db", _fail_fetch)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        client = _make_app(mock_db)
        resp = client.get("/api/v1/intel/anomalies", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        # 关键: 不是空数组. detector 已 extend 的 expiry_risk 必保留
        assert body["data"]["total"] >= 1
        types_ = {a["type"] for a in body["data"]["anomalies"]}
        assert "expiry_risk" in types_
        # 不是 mock 数据
        assert body["data"]["_is_mock"] is False

    def test_outer_except_empty_when_set_rls_fails_first(self, monkeypatch):
        """_set_rls 自己 fail → anomalies 仍空 list (空安全, 不 NameError)."""

        async def _fail_set_rls(*a, **kw):
            raise _SQLAlchemyError("RLS set_config fail")

        monkeypatch.setattr(_anomaly_mod, "_set_rls", _fail_set_rls)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        client = _make_app(mock_db)
        resp = client.get("/api/v1/intel/anomalies", headers=HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        # 空 list, 非 NameError
        assert body["data"]["total"] == 0
        assert body["data"]["anomalies"] == []
        assert body["data"]["_is_mock"] is False

    def test_outer_except_logger_includes_partial_count(self, monkeypatch):
        """外层 except log 含 partial_count 便于排查 (data is preserved, not silently lost)."""
        captured: list[dict] = []

        def _capture_warning(event: str, **kwargs):
            captured.append({"event": event, **kwargs})

        fake_logger = types.SimpleNamespace(
            warning=_capture_warning,
            info=lambda *a, **kw: None,
        )
        monkeypatch.setattr(_anomaly_mod, "logger", fake_logger)

        fake_anomaly = [
            {
                "id": "a-1",
                "type": "expiry_risk",
                "severity": "critical",
                "description": "test",
                "detail": {},
                "occurred_at": "2026-05-16T00:00:00+00:00",
                "dismissed": False,
            }
        ]

        async def _ok_empty(*a, **kw):
            return []

        async def _ok_one(*a, **kw):
            return fake_anomaly

        async def _fail_fetch(*a, **kw):
            raise _SQLAlchemyError("force outer except")

        monkeypatch.setattr(_anomaly_mod, "_detect_revenue_drop", _ok_empty)
        monkeypatch.setattr(_anomaly_mod, "_detect_cost_spike", _ok_empty)
        monkeypatch.setattr(_anomaly_mod, "_detect_high_refund", _ok_empty)
        monkeypatch.setattr(_anomaly_mod, "_detect_slow_kitchen", _ok_empty)
        monkeypatch.setattr(_anomaly_mod, "_detect_expiry_risk", _ok_one)
        monkeypatch.setattr(_anomaly_mod, "_fetch_anomalies_from_db", _fail_fetch)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        client = _make_app(mock_db)
        resp = client.get("/api/v1/intel/anomalies", headers=HEADERS)
        assert resp.status_code == 200

        # 验证 anomalies.outer_db_error log 含 partial_count=1
        outer_logs = [c for c in captured if c.get("event") == "anomalies.outer_db_error"]
        assert len(outer_logs) >= 1
        assert outer_logs[0].get("partial_count") == 1
