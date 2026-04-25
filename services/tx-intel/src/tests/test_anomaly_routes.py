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
_fake_structlog.get_logger = lambda: types.SimpleNamespace(
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
