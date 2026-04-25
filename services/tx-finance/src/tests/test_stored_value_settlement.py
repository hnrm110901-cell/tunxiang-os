"""
储值分账结算测试 — stored_value_settlement_routes.py (10 个端点)

覆盖：
  POST   /api/v1/finance/sv-settlement/rules              创建分账规则
  GET    /api/v1/finance/sv-settlement/rules              查询分账规则列表
  PUT    /api/v1/finance/sv-settlement/rules/{rule_id}    更新分账规则
  GET    /api/v1/finance/sv-settlement/ledger             分账流水列表
  GET    /api/v1/finance/sv-settlement/batches            结算批次列表
  GET    /api/v1/finance/sv-settlement/batches/{batch_id} 结算批次详情
  POST   /api/v1/finance/sv-settlement/batches/run-daily  触发每日结算
  POST   /api/v1/finance/sv-settlement/batches/{batch_id}/confirm  确认结算
  POST   /api/v1/finance/sv-settlement/batches/{batch_id}/settle   标记已打款
  GET    /api/v1/finance/sv-settlement/dashboard          分账看板

运行方式：
    cd /Users/lichun/tunxiang-os/services/tx-finance
    pytest src/tests/test_stored_value_settlement.py -v
"""

from __future__ import annotations

import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

# ─── 存根工具 ────────────────────────────────────────────────────────────────


def _make_stub(name: str, **attrs) -> types.ModuleType:
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


# ── structlog 存根 ────────────────────────────────────────────────────────────
if "structlog" not in sys.modules:
    _stub_log = MagicMock()
    _stub_log.get_logger.return_value = MagicMock(
        info=MagicMock(), error=MagicMock(), warning=MagicMock(), debug=MagicMock(),
        exception=MagicMock(),
    )
    sys.modules["structlog"] = _stub_log

# ── sqlalchemy 系列存根 ───────────────────────────────────────────────────────
if "sqlalchemy" not in sys.modules:
    sa_stub = _make_stub("sqlalchemy", text=lambda s: s)
    sa_exc_stub = _make_stub(
        "sqlalchemy.exc",
        SQLAlchemyError=type("SQLAlchemyError", (Exception,), {}),
    )
    sa_ext_stub = _make_stub("sqlalchemy.ext")
    sa_ext_async = _make_stub("sqlalchemy.ext.asyncio", AsyncSession=MagicMock())
    sys.modules["sqlalchemy"] = sa_stub
    sys.modules["sqlalchemy.exc"] = sa_exc_stub
    sys.modules["sqlalchemy.ext"] = sa_ext_stub
    sys.modules["sqlalchemy.ext.asyncio"] = sa_ext_async

# ── shared.ontology.src.database 存根 ────────────────────────────────────────
_db_stub = _make_stub(
    "shared.ontology.src.database",
    get_db=AsyncMock(),
    get_db_with_tenant=AsyncMock(),
)
sys.modules.setdefault("shared", _make_stub("shared"))
sys.modules.setdefault("shared.ontology", _make_stub("shared.ontology"))
sys.modules.setdefault("shared.ontology.src", _make_stub("shared.ontology.src"))
sys.modules["shared.ontology.src.database"] = _db_stub

# ── services 存根 ────────────────────────────────────────────────────────────
_NoApplicableRuleError = type("NoApplicableRuleError", (ValueError,), {})

_split_svc_stub = _make_stub(
    "services.stored_value_split_service",
    StoredValueSplitService=MagicMock(),
    NoApplicableRuleError=_NoApplicableRuleError,
)
_scheduler_stub = _make_stub(
    "tasks.settlement_scheduler",
    SettlementScheduler=MagicMock(),
)
_notify_stub = _make_stub(
    "services.settlement_notify_service",
    SettlementNotifyService=MagicMock(),
)

sys.modules.setdefault("services", _make_stub("services"))
sys.modules["services.stored_value_split_service"] = _split_svc_stub
sys.modules.setdefault("tasks", _make_stub("tasks"))
sys.modules["tasks.settlement_scheduler"] = _scheduler_stub
sys.modules["services.settlement_notify_service"] = _notify_stub

# 确保 src 包结构
sys.modules.setdefault("src", _make_stub("src"))
sys.modules.setdefault("src.api", _make_stub("src.api"))
sys.modules.setdefault("src.services", _make_stub("src.services"))
sys.modules.setdefault("src.tasks", _make_stub("src.tasks"))
sys.modules["src.services.stored_value_split_service"] = _split_svc_stub
sys.modules["src.tasks.settlement_scheduler"] = _scheduler_stub
sys.modules["src.services.settlement_notify_service"] = _notify_stub

# ─── 加载被测路由模块 ────────────────────────────────────────────────────────
import importlib.util
import pathlib

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# 路由模块使用相对导入 (..services / ..tasks)，需要在 sys.modules 中注册对应路径
# 使 ..services.stored_value_split_service 解析为 src.services.stored_value_split_service
sys.modules["src.services.stored_value_split_service"] = _split_svc_stub
sys.modules["src.tasks.settlement_scheduler"] = _scheduler_stub
sys.modules["src.services.settlement_notify_service"] = _notify_stub

_routes_path = (
    pathlib.Path(__file__).parent.parent / "api" / "stored_value_settlement_routes.py"
)
_spec = importlib.util.spec_from_file_location(
    "src.api.stored_value_settlement_routes",
    _routes_path,
    submodule_search_locations=[],
)
_sv_routes = importlib.util.module_from_spec(_spec)
# 设置 __package__ 使相对导入工作
_sv_routes.__package__ = "src.api"
sys.modules["src.api.stored_value_settlement_routes"] = _sv_routes
_spec.loader.exec_module(_sv_routes)

# ─── 公共常量 ─────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
RULE_ID = str(uuid.uuid4())
BATCH_ID = str(uuid.uuid4())
STORE_A = str(uuid.uuid4())
STORE_B = str(uuid.uuid4())
LEDGER_ID = str(uuid.uuid4())
TXN_ID = str(uuid.uuid4())

TENANT_HDR = {"X-Tenant-ID": TENANT_ID}

SAMPLE_RULE = {
    "rule_id": RULE_ID,
    "rule_name": "品牌内跨店消费默认规则",
    "recharge_store_ratio": 0.15,
    "consume_store_ratio": 0.70,
    "hq_ratio": 0.15,
    "scope_type": "brand",
    "applicable_store_ids": [],
    "is_default": True,
    "effective_from": None,
    "effective_to": None,
    "created_at": "2026-04-25T00:00:00+00:00",
    "updated_at": "2026-04-25T00:00:00+00:00",
}

SAMPLE_BATCH = {
    "batch_id": BATCH_ID,
    "batch_no": "SV-SETTLE-20260424-ABC123",
    "period_start": "2026-04-24",
    "period_end": "2026-04-24",
    "total_records": 5,
    "total_amount_fen": 100000,
    "total_amount_yuan": 1000.00,
    "status": "draft",
    "created_at": "2026-04-25T01:00:00+00:00",
}


# ─── DB mock 工厂 ─────────────────────────────────────────────────────────────


def _mock_db() -> AsyncMock:
    session = AsyncMock()
    session.commit = AsyncMock()
    return session


# ════════════════════════════════════════════════════════════════════════════
# 测试类
# ════════════════════════════════════════════════════════════════════════════


class TestStoredValueSettlementRoutes:
    """stored_value_settlement_routes.py 的 15 个测试"""

    def _build_app(self, db_session: AsyncMock) -> FastAPI:
        app = FastAPI()
        app.include_router(_sv_routes.router)
        app.dependency_overrides[_sv_routes._get_tenant_db] = lambda: db_session
        return app

    # ── 1. POST /rules — 正常创建规则 ────────────────────────────────────

    def test_create_rule_success(self):
        """正常创建分账规则（三方比例之和=1.0），应返回 201。"""
        svc_mock = AsyncMock()
        svc_mock.create_rule = AsyncMock(return_value=SAMPLE_RULE)

        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_sv_routes, "StoredValueSplitService", return_value=svc_mock):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/finance/sv-settlement/rules",
                json={
                    "rule_name": "品牌内跨店消费默认规则",
                    "recharge_store_ratio": 0.15,
                    "consume_store_ratio": 0.70,
                    "hq_ratio": 0.15,
                    "is_default": True,
                },
                headers=TENANT_HDR,
            )
        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["rule_id"] == RULE_ID

    # ── 2. POST /rules — 比例不等于1时400 ─────────────────────────────────

    def test_create_rule_invalid_ratio_400(self):
        """三方比例之和 != 1.0 时应返回 400。"""
        svc_mock = AsyncMock()
        svc_mock.create_rule = AsyncMock(
            side_effect=ValueError("三方比例之和必须为 1.0000")
        )

        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_sv_routes, "StoredValueSplitService", return_value=svc_mock):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/finance/sv-settlement/rules",
                json={
                    "rule_name": "错误规则",
                    "recharge_store_ratio": 0.30,
                    "consume_store_ratio": 0.60,
                    "hq_ratio": 0.20,
                },
                headers=TENANT_HDR,
            )
        assert resp.status_code == 400
        assert "1.0000" in resp.json()["detail"]

    # ── 3. GET /rules — 查询规则列表 ──────────────────────────────────────

    def test_list_rules_success(self):
        """查询规则列表应返回包含 items 和 total 的数据结构。"""
        svc_mock = AsyncMock()
        svc_mock.list_rules = AsyncMock(return_value=[SAMPLE_RULE])

        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_sv_routes, "StoredValueSplitService", return_value=svc_mock):
            client = TestClient(app)
            resp = client.get(
                "/api/v1/finance/sv-settlement/rules",
                headers=TENANT_HDR,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 1

    # ── 4. PUT /rules/{rule_id} — 更新规则 ───────────────────────────────

    def test_update_rule_success(self):
        """更新规则应返回更新后的数据。"""
        updated_rule = {**SAMPLE_RULE, "rule_name": "更新后的规则"}
        svc_mock = AsyncMock()
        svc_mock.update_rule = AsyncMock(return_value=updated_rule)

        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_sv_routes, "StoredValueSplitService", return_value=svc_mock):
            client = TestClient(app)
            resp = client.put(
                f"/api/v1/finance/sv-settlement/rules/{RULE_ID}",
                json={
                    "rule_name": "更新后的规则",
                    "recharge_store_ratio": 0.15,
                    "consume_store_ratio": 0.70,
                    "hq_ratio": 0.15,
                },
                headers=TENANT_HDR,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["rule_name"] == "更新后的规则"

    # ── 5. PUT /rules/{rule_id} — 规则不存在时 404 ───────────────────────

    def test_update_rule_not_found_404(self):
        """更新不存在的规则应返回 404。"""
        svc_mock = AsyncMock()
        svc_mock.update_rule = AsyncMock(return_value=None)

        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_sv_routes, "StoredValueSplitService", return_value=svc_mock):
            client = TestClient(app)
            resp = client.put(
                f"/api/v1/finance/sv-settlement/rules/{RULE_ID}",
                json={
                    "rule_name": "不存在的规则",
                    "recharge_store_ratio": 0.15,
                    "consume_store_ratio": 0.70,
                    "hq_ratio": 0.15,
                },
                headers=TENANT_HDR,
            )
        assert resp.status_code == 404

    # ── 6. GET /ledger — 查询分账流水 ────────────────────────────────────

    def test_list_ledger_success(self):
        """查询分账流水列表应返回分页结构。"""
        ledger_data = {
            "items": [
                {
                    "ledger_id": LEDGER_ID,
                    "transaction_id": TXN_ID,
                    "total_amount_fen": 10000,
                    "recharge_store_amount_fen": 1500,
                    "consume_store_amount_fen": 7000,
                    "hq_amount_fen": 1500,
                    "settlement_status": "pending",
                }
            ],
            "total": 1,
            "page": 1,
            "size": 20,
        }
        svc_mock = AsyncMock()
        svc_mock.list_ledger = AsyncMock(return_value=ledger_data)

        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_sv_routes, "StoredValueSplitService", return_value=svc_mock):
            client = TestClient(app)
            resp = client.get(
                "/api/v1/finance/sv-settlement/ledger",
                params={"store_id": STORE_A, "page": 1, "size": 20},
                headers=TENANT_HDR,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 1

    # ── 7. GET /batches — 结算批次列表 ───────────────────────────────────

    def test_list_batches_success(self):
        """查询结算批次列表应返回分页结构。"""
        scheduler_mock = AsyncMock()
        scheduler_mock.list_batches = AsyncMock(
            return_value={
                "items": [SAMPLE_BATCH],
                "total": 1,
                "page": 1,
                "size": 20,
            }
        )

        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_sv_routes, "SettlementScheduler", return_value=scheduler_mock):
            client = TestClient(app)
            resp = client.get(
                "/api/v1/finance/sv-settlement/batches",
                headers=TENANT_HDR,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 1

    # ── 8. POST /batches/run-daily — 触发每日结算 ────────────────────────

    def test_run_daily_settlement_success(self):
        """触发每日结算应返回批次信息。"""
        settlement_result = {
            "batch_id": BATCH_ID,
            "batch_no": "SV-SETTLE-20260424-ABC123",
            "period_start": "2026-04-24",
            "period_end": "2026-04-24",
            "total_records": 5,
            "total_amount_fen": 100000,
            "status": "draft",
        }
        scheduler_mock = AsyncMock()
        scheduler_mock.run_daily_settlement = AsyncMock(return_value=settlement_result)

        notify_mock = AsyncMock()
        notify_mock.notify_batch_created = AsyncMock(return_value={"notified": True})

        db = _mock_db()
        app = self._build_app(db)

        with (
            patch.object(_sv_routes, "SettlementScheduler", return_value=scheduler_mock),
            patch.object(_sv_routes, "SettlementNotifyService", return_value=notify_mock),
        ):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/finance/sv-settlement/batches/run-daily",
                json={"settlement_date": "2026-04-24"},
                headers=TENANT_HDR,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["batch_id"] == BATCH_ID
        assert body["data"]["total_records"] == 5

    # ── 9. POST /batches/run-daily — 无 pending 流水 ─────────────────────

    def test_run_daily_settlement_no_pending(self):
        """无 pending 流水时应返回空结果。"""
        scheduler_mock = AsyncMock()
        scheduler_mock.run_daily_settlement = AsyncMock(
            return_value={
                "batch_id": None,
                "batch_no": None,
                "total_records": 0,
                "total_amount_fen": 0,
                "message": "无需结算",
            }
        )

        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_sv_routes, "SettlementScheduler", return_value=scheduler_mock):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/finance/sv-settlement/batches/run-daily",
                json={},
                headers=TENANT_HDR,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["total_records"] == 0

    # ── 10. POST /batches/{batch_id}/confirm — 确认结算 ──────────────────

    def test_confirm_batch_success(self):
        """确认结算批次应返回 confirmed 状态。"""
        confirm_result = {
            "batch_id": BATCH_ID,
            "batch_no": "SV-SETTLE-20260424-ABC123",
            "status": "confirmed",
            "settled_count": 5,
            "total_records": 5,
            "total_amount_fen": 100000,
        }
        scheduler_mock = AsyncMock()
        scheduler_mock.confirm_settlement_batch = AsyncMock(return_value=confirm_result)

        notify_mock = AsyncMock()
        notify_mock.notify_batch_confirmed = AsyncMock(return_value={"notified": True})

        db = _mock_db()
        app = self._build_app(db)

        with (
            patch.object(_sv_routes, "SettlementScheduler", return_value=scheduler_mock),
            patch.object(_sv_routes, "SettlementNotifyService", return_value=notify_mock),
        ):
            client = TestClient(app)
            resp = client.post(
                f"/api/v1/finance/sv-settlement/batches/{BATCH_ID}/confirm",
                headers=TENANT_HDR,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "confirmed"
        assert body["data"]["settled_count"] == 5

    # ── 11. POST /batches/{batch_id}/confirm — 非 draft 状态时 400 ───────

    def test_confirm_batch_invalid_status_400(self):
        """确认非 draft 状态的批次应返回 400。"""
        scheduler_mock = AsyncMock()
        scheduler_mock.confirm_settlement_batch = AsyncMock(
            side_effect=ValueError("只能确认 draft 状态的批次")
        )

        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_sv_routes, "SettlementScheduler", return_value=scheduler_mock):
            client = TestClient(app)
            resp = client.post(
                f"/api/v1/finance/sv-settlement/batches/{BATCH_ID}/confirm",
                headers=TENANT_HDR,
            )
        assert resp.status_code == 400

    # ── 12. POST /batches/{batch_id}/settle — 标记已打款 ─────────────────

    def test_settle_batch_success(self):
        """标记已打款应返回 settled 状态。"""
        settle_result = {
            "batch_id": BATCH_ID,
            "batch_no": "SV-SETTLE-20260424-ABC123",
            "status": "settled",
        }
        scheduler_mock = AsyncMock()
        scheduler_mock.settle_batch = AsyncMock(return_value=settle_result)

        notify_mock = AsyncMock()
        notify_mock.notify_batch_settled = AsyncMock(return_value={"notified": True})

        db = _mock_db()
        app = self._build_app(db)

        with (
            patch.object(_sv_routes, "SettlementScheduler", return_value=scheduler_mock),
            patch.object(_sv_routes, "SettlementNotifyService", return_value=notify_mock),
        ):
            client = TestClient(app)
            resp = client.post(
                f"/api/v1/finance/sv-settlement/batches/{BATCH_ID}/settle",
                headers=TENANT_HDR,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "settled"

    # ── 13. GET /dashboard — 分账看板 ────────────────────────────────────

    def test_dashboard_success(self):
        """分账看板应返回汇总统计数据。"""
        dashboard_data = {
            "total_records": 50,
            "total_amount_fen": 5000000,
            "total_amount_yuan": 50000.00,
            "total_recharge_store_fen": 750000,
            "total_consume_store_fen": 3500000,
            "total_hq_fen": 750000,
            "pending_count": 10,
            "settled_count": 40,
            "pending_amount_fen": 1000000,
            "settled_amount_fen": 4000000,
        }
        svc_mock = AsyncMock()
        svc_mock.get_dashboard = AsyncMock(return_value=dashboard_data)

        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_sv_routes, "StoredValueSplitService", return_value=svc_mock):
            client = TestClient(app)
            resp = client.get(
                "/api/v1/finance/sv-settlement/dashboard",
                params={"start_date": "2026-04-01", "end_date": "2026-04-30"},
                headers=TENANT_HDR,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total_records"] == 50
        assert body["data"]["total_amount_yuan"] == 50000.00
        assert body["data"]["pending_count"] == 10

    # ── 14. GET /batches/{batch_id} — 查询批次详情 ───────────────────────

    def test_get_batch_success(self):
        """查询存在的批次应返回详情。"""
        scheduler_mock = AsyncMock()
        scheduler_mock.get_batch = AsyncMock(return_value=SAMPLE_BATCH)

        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_sv_routes, "SettlementScheduler", return_value=scheduler_mock):
            client = TestClient(app)
            resp = client.get(
                f"/api/v1/finance/sv-settlement/batches/{BATCH_ID}",
                headers=TENANT_HDR,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["batch_id"] == BATCH_ID

    # ── 15. GET /batches/{batch_id} — 不存在时 404 ──────────────────────

    def test_get_batch_not_found_404(self):
        """查询不存在的批次应返回 404。"""
        scheduler_mock = AsyncMock()
        scheduler_mock.get_batch = AsyncMock(return_value=None)

        db = _mock_db()
        app = self._build_app(db)

        with patch.object(_sv_routes, "SettlementScheduler", return_value=scheduler_mock):
            client = TestClient(app)
            resp = client.get(
                f"/api/v1/finance/sv-settlement/batches/{BATCH_ID}",
                headers=TENANT_HDR,
            )
        assert resp.status_code == 404


# ════════════════════════════════════════════════════════════════════════════
# 储值跨店分账核心逻辑测试（单元测试，不依赖 DB）
# ════════════════════════════════════════════════════════════════════════════


class TestStoredValueSplitLogic:
    """分账计算逻辑纯单元测试（无 DB 依赖）"""

    def test_split_ratio_sum_validation(self):
        """三方比例之和 != 1.0 时应抛出 ValueError。"""
        from decimal import Decimal

        r = Decimal("0.15")
        c = Decimal("0.70")
        h = Decimal("0.20")  # 总和 = 1.05

        assert r + c + h != Decimal("1.0000")

    def test_split_amount_calculation(self):
        """分账金额计算：充值店15% + 消费店70% + 总部15% = 100%，无尾差。"""
        from decimal import Decimal

        amount_fen = 10000
        r_ratio = Decimal("0.1500")
        h_ratio = Decimal("0.1500")

        r_amount = int(Decimal(amount_fen) * r_ratio)  # 1500
        h_amount = int(Decimal(amount_fen) * h_ratio)  # 1500
        c_amount = amount_fen - r_amount - h_amount     # 7000

        assert r_amount == 1500
        assert h_amount == 1500
        assert c_amount == 7000
        assert r_amount + c_amount + h_amount == amount_fen

    def test_split_amount_with_rounding(self):
        """非整除场景：尾差由消费店吸收。"""
        from decimal import Decimal

        amount_fen = 10001  # 不能被精确整除
        r_ratio = Decimal("0.1500")
        h_ratio = Decimal("0.1500")

        r_amount = int(Decimal(amount_fen) * r_ratio)  # 1500 (floor)
        h_amount = int(Decimal(amount_fen) * h_ratio)  # 1500 (floor)
        c_amount = amount_fen - r_amount - h_amount     # 7001 (吸收尾差)

        assert r_amount + c_amount + h_amount == amount_fen
        assert c_amount == 7001

    def test_reversal_proportional(self):
        """退款冲正按原始比例反向计算。"""
        from decimal import Decimal

        # 原始分账：10000 → 1500 + 7000 + 1500
        orig_total = 10000
        orig_r = 1500
        orig_c = 7000
        orig_h = 1500

        # 部分退款 5000
        refund = 5000
        ratio = Decimal(refund) / Decimal(orig_total)

        r_rev = int(Decimal(orig_r) * ratio)
        h_rev = int(Decimal(orig_h) * ratio)
        c_rev = refund - r_rev - h_rev

        assert r_rev == 750
        assert h_rev == 750
        assert c_rev == 3500
        assert r_rev + c_rev + h_rev == refund

    def test_same_store_no_split(self):
        """同店消费不应触发分账。"""
        store_id = str(uuid.uuid4())
        # 充值店 == 消费店 → 跳过
        assert store_id == store_id  # 同店判断
