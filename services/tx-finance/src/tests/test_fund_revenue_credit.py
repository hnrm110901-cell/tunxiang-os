"""
tx-finance 资金分账、收入分析、企业挂账路由测试
覆盖：
  - fund_settlement_routes (8 个端点): 8 个测试
  - revenue_routes         (3 个端点): 4 个测试
  - credit_account_routes  (8 个端点): 7 个测试
合计: 19 个测试

运行方式：
    cd /Users/lichun/tunxiang-os/services/tx-finance
    pytest src/tests/test_fund_revenue_credit.py -v
"""

from __future__ import annotations

import sys
import types
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

# ─── 存根工具 ─────────────────────────────────────────────────────────────────


def _make_stub(name: str, **attrs) -> types.ModuleType:
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


# ── structlog 存根 ────────────────────────────────────────────────────────────
if "structlog" not in sys.modules:
    _stub_log = MagicMock()
    _stub_log.get_logger.return_value = MagicMock(info=MagicMock(), error=MagicMock(), warning=MagicMock())
    sys.modules["structlog"] = _stub_log

# ── sqlalchemy 系列存根 ───────────────────────────────────────────────────────
if "sqlalchemy" not in sys.modules:
    sa_stub = _make_stub("sqlalchemy", text=lambda s: s, update=MagicMock())
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
else:
    from sqlalchemy.exc import SQLAlchemyError  # noqa: F401

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

# ── shared.events 存根 ────────────────────────────────────────────────────────
_events_stub = _make_stub("shared.events")
_events_src_stub = _make_stub("shared.events.src")
_emitter_stub = _make_stub("shared.events.src.emitter", emit_event=AsyncMock())

_credit_evt = types.SimpleNamespace(
    AGREEMENT_CREATED="credit.agreement_created",
    CHARGED="credit.charged",
    SUSPENDED="credit.suspended",
    BILL_PAID="credit.bill_paid",
    LIMIT_WARNING="credit.limit_warning",
)
_evt_types_stub = _make_stub(
    "shared.events.src.event_types",
    CreditEventType=_credit_evt,
    DepositEventType=MagicMock(),
)
sys.modules.setdefault("shared.events", _events_stub)
sys.modules.setdefault("shared.events.src", _events_src_stub)
sys.modules["shared.events.src.emitter"] = _emitter_stub
sys.modules["shared.events.src.event_types"] = _evt_types_stub

# ── services.fund_settlement_service 存根 ────────────────────────────────────
_FundSettlementServiceMock = MagicMock()
sys.modules.setdefault("services", _make_stub("services"))
sys.modules["services.fund_settlement_service"] = _make_stub(
    "services.fund_settlement_service",
    FundSettlementService=_FundSettlementServiceMock,
)

# ── services.pnl_engine 存根 ─────────────────────────────────────────────────
_PnLEngineMock = MagicMock()
sys.modules["services.pnl_engine"] = _make_stub(
    "services.pnl_engine",
    PnLEngine=_PnLEngineMock,
)

# ── src.services.fund_settlement_service (相对导入路径) ─────────────────────
# fund_settlement_routes 使用 from ..services.fund_settlement_service import ...
# 在 src 包下需要 src.services.fund_settlement_service
sys.modules.setdefault("src", _make_stub("src"))
sys.modules.setdefault("src.services", _make_stub("src.services"))
sys.modules["src.services.fund_settlement_service"] = _make_stub(
    "src.services.fund_settlement_service",
    FundSettlementService=_FundSettlementServiceMock,
)

# ─── 加载被测路由模块 ─────────────────────────────────────────────────────────

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import credit_account_routes, fund_settlement_routes, revenue_routes  # noqa: E402

# ─── 公共常量 ─────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
BRAND_ID = str(uuid.uuid4())
ORDER_ID = str(uuid.uuid4())
OPERATOR_ID = str(uuid.uuid4())
BATCH_ID = str(uuid.uuid4())
AGREEMENT_ID = str(uuid.uuid4())
BILL_ID = str(uuid.uuid4())

TENANT_HDR = {"X-Tenant-ID": TENANT_ID}
OP_HDR = {"X-Tenant-ID": TENANT_ID, "X-Operator-ID": OPERATOR_ID}


# ─── mock DB session 工厂 ─────────────────────────────────────────────────────


def _mock_db_single(first_val: Any = None, scalar_val: Any = 0) -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.first.return_value = first_val
    result.mappings.return_value.all.return_value = [first_val] if first_val else []
    result.scalar.return_value = scalar_val
    result.fetchall.return_value = []
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    return session


# ═══════════════════════════════════════════════════════════════════════════════
#  1. fund_settlement_routes 测试
# ═══════════════════════════════════════════════════════════════════════════════


def _make_fund_client():
    app = FastAPI()
    app.include_router(fund_settlement_routes.router)
    return TestClient(app, raise_server_exceptions=False)


class TestFundSettlementRoutes:
    """资金分账路由测试（8 个测试）"""

    def test_create_split_rule_success(self):
        """POST /api/v1/finance/split-rules — 正常创建分账规则"""
        client = _make_fund_client()
        svc_inst = MagicMock()
        svc_inst.create_split_rule = AsyncMock(
            return_value={
                "rule_id": str(uuid.uuid4()),
                "rule_type": "platform_fee",
                "rate_permil": 50,
            }
        )
        mock_db = _mock_db_single()

        with (
            patch.object(fund_settlement_routes, "_service", svc_inst),
            patch.object(fund_settlement_routes, "_get_tenant_db", return_value=mock_db),
        ):
            resp = client.post(
                "/api/v1/finance/split-rules",
                json={
                    "store_id": STORE_ID,
                    "rule_type": "platform_fee",
                    "rate_permil": 50,
                    "fixed_fee_fen": 0,
                    "effective_from": "2026-01-01",
                },
                headers=TENANT_HDR,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["rule_type"] == "platform_fee"

    def test_create_split_rule_invalid_date(self):
        """POST /api/v1/finance/split-rules — 400 日期格式错误"""
        client = _make_fund_client()
        resp = client.post(
            "/api/v1/finance/split-rules",
            json={
                "store_id": STORE_ID,
                "rule_type": "platform_fee",
                "rate_permil": 50,
                "fixed_fee_fen": 0,
                "effective_from": "not-a-date",
            },
            headers=TENANT_HDR,
        )
        assert resp.status_code == 400

    def test_list_split_rules_success(self):
        """GET /api/v1/finance/split-rules — 正常返回规则列表"""
        client = _make_fund_client()
        svc_inst = MagicMock()
        svc_inst.list_split_rules = AsyncMock(
            return_value=[{"rule_id": str(uuid.uuid4()), "rule_type": "brand_royalty", "rate_permil": 30}]
        )
        mock_db = _mock_db_single()

        with (
            patch.object(fund_settlement_routes, "_service", svc_inst),
            patch.object(fund_settlement_routes, "_get_tenant_db", return_value=mock_db),
        ):
            resp = client.get(
                f"/api/v1/finance/split-rules?store_id={STORE_ID}&active_only=true",
                headers=TENANT_HDR,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 1

    def test_split_order_success(self):
        """POST /api/v1/finance/split/order/{order_id} — 单笔订单分账"""
        client = _make_fund_client()
        svc_inst = MagicMock()
        svc_inst.split_order = AsyncMock(
            return_value={
                "order_id": ORDER_ID,
                "splits": [{"party": "platform", "amount_fen": 500}],
            }
        )
        mock_db = _mock_db_single()

        with (
            patch.object(fund_settlement_routes, "_service", svc_inst),
            patch.object(fund_settlement_routes, "_get_tenant_db", return_value=mock_db),
        ):
            resp = client.post(
                f"/api/v1/finance/split/order/{ORDER_ID}",
                headers=TENANT_HDR,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "splits" in body["data"]

    def test_batch_split_success(self):
        """POST /api/v1/finance/split/batch — 批量分账"""
        client = _make_fund_client()
        svc_inst = MagicMock()
        svc_inst.batch_split = AsyncMock(return_value={"processed": 10, "skipped": 0, "total_split_fen": 5000})
        mock_db = _mock_db_single()

        with (
            patch.object(fund_settlement_routes, "_service", svc_inst),
            patch.object(fund_settlement_routes, "_get_tenant_db", return_value=mock_db),
        ):
            resp = client.post(
                "/api/v1/finance/split/batch",
                json={"store_id": STORE_ID, "start_date": "2026-03-01", "end_date": "2026-03-31"},
                headers=TENANT_HDR,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["processed"] == 10

    def test_create_settlement_success(self):
        """POST /api/v1/finance/settlements — 生成结算批次"""
        client = _make_fund_client()
        svc_inst = MagicMock()
        svc_inst.create_settlement_batch = AsyncMock(
            return_value={"batch_id": BATCH_ID, "status": "draft", "total_split_fen": 80000}
        )
        mock_db = _mock_db_single()

        with (
            patch.object(fund_settlement_routes, "_service", svc_inst),
            patch.object(fund_settlement_routes, "_get_tenant_db", return_value=mock_db),
        ):
            resp = client.post(
                "/api/v1/finance/settlements",
                json={"store_id": STORE_ID, "period_start": "2026-03-01", "period_end": "2026-03-31"},
                headers=TENANT_HDR,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "draft"

    def test_get_settlement_summary_success(self):
        """GET /api/v1/finance/settlements/{batch_id}/summary — 结算汇总"""
        client = _make_fund_client()
        svc_inst = MagicMock()
        svc_inst.get_settlement_summary = AsyncMock(
            return_value={
                "batch_id": BATCH_ID,
                "status": "draft",
                "platform_fee_fen": 4000,
                "brand_royalty_fen": 3000,
                "franchise_share_fen": 2000,
            }
        )
        mock_db = _mock_db_single()

        with (
            patch.object(fund_settlement_routes, "_service", svc_inst),
            patch.object(fund_settlement_routes, "_get_tenant_db", return_value=mock_db),
        ):
            resp = client.get(
                f"/api/v1/finance/settlements/{BATCH_ID}/summary",
                headers=TENANT_HDR,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "platform_fee_fen" in body["data"]

    def test_confirm_settlement_success(self):
        """POST /api/v1/finance/settlements/{batch_id}/confirm — 确认结算"""
        client = _make_fund_client()
        svc_inst = MagicMock()
        svc_inst.confirm_settlement = AsyncMock(
            return_value={"batch_id": BATCH_ID, "status": "confirmed", "confirmed_at": "2026-04-01T10:00:00"}
        )
        mock_db = _mock_db_single()

        with (
            patch.object(fund_settlement_routes, "_service", svc_inst),
            patch.object(fund_settlement_routes, "_get_tenant_db", return_value=mock_db),
        ):
            resp = client.post(
                f"/api/v1/finance/settlements/{BATCH_ID}/confirm",
                headers=TENANT_HDR,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "confirmed"


# ═══════════════════════════════════════════════════════════════════════════════
#  2. revenue_routes 测试
# ═══════════════════════════════════════════════════════════════════════════════


def _make_revenue_client():
    app = FastAPI()
    app.include_router(revenue_routes.router, prefix="/api/v1/finance")
    return TestClient(app, raise_server_exceptions=False)


class TestRevenueRoutes:
    """收入分析路由测试（4 个测试）"""

    def test_get_daily_revenue_empty(self):
        """GET /api/v1/finance/revenue/daily — 无数据时走 fallback 查 orders"""
        client = _make_revenue_client()
        # 第一次（revenue_records）返回空，第二次（orders fallback）也返回空
        session = AsyncMock()
        empty_result = MagicMock()
        empty_result.fetchall.return_value = []
        empty_result.mappings.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=empty_result)
        session.commit = AsyncMock()

        with patch.object(revenue_routes, "_get_tenant_db", return_value=session):
            resp = client.get(
                f"/api/v1/finance/revenue/daily?store_id={STORE_ID}&date=2026-03-01",
                headers=TENANT_HDR,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "channels" in body["data"]

    def test_get_daily_revenue_invalid_date(self):
        """GET /api/v1/finance/revenue/daily — 400 日期格式错误"""
        client = _make_revenue_client()
        session = _mock_db_single()

        with patch.object(revenue_routes, "_get_tenant_db", return_value=session):
            resp = client.get(
                f"/api/v1/finance/revenue/daily?store_id={STORE_ID}&date=bad-date",
                headers=TENANT_HDR,
            )
        assert resp.status_code == 400

    def test_get_channel_mix_trend(self):
        """GET /api/v1/finance/revenue/channel-mix — 渠道趋势空数据"""
        client = _make_revenue_client()
        session = AsyncMock()
        empty = MagicMock()
        empty.fetchall.return_value = []
        session.execute = AsyncMock(return_value=empty)
        session.commit = AsyncMock()

        with patch.object(revenue_routes, "_get_tenant_db", return_value=session):
            resp = client.get(
                f"/api/v1/finance/revenue/channel-mix?store_id={STORE_ID}&days=30",
                headers=TENANT_HDR,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "trend" in body["data"]

    def test_get_hourly_revenue(self):
        """GET /api/v1/finance/revenue/hourly — 小时收入分布"""
        client = _make_revenue_client()
        session = AsyncMock()
        empty = MagicMock()
        empty.fetchall.return_value = []
        session.execute = AsyncMock(return_value=empty)
        session.commit = AsyncMock()

        with patch.object(revenue_routes, "_get_tenant_db", return_value=session):
            resp = client.get(
                f"/api/v1/finance/revenue/hourly?store_id={STORE_ID}&date=2026-03-01",
                headers=TENANT_HDR,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True


# ═══════════════════════════════════════════════════════════════════════════════
#  3. credit_account_routes 测试
# ═══════════════════════════════════════════════════════════════════════════════


def _make_credit_client():
    app = FastAPI()
    app.include_router(credit_account_routes.router)
    return TestClient(app, raise_server_exceptions=False)


def _agreement_row(
    agreement_id: str = AGREEMENT_ID,
    status: str = "active",
    credit_limit_fen: int = 1_000_000,
    used_amount_fen: int = 0,
):
    return {
        "id": uuid.UUID(agreement_id),
        "brand_id": uuid.UUID(BRAND_ID),
        "company_name": "测试公司",
        "company_tax_no": "91430100XXXXXXXXXX",
        "credit_limit_fen": credit_limit_fen,
        "used_amount_fen": used_amount_fen,
        "billing_cycle": "monthly",
        "due_day": 15,
        "status": status,
        "created_by": uuid.UUID(OPERATOR_ID),
        "remark": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


class TestCreditAccountRoutes:
    """企业挂账路由测试（7 个测试）"""

    def test_create_agreement_small_limit_active(self):
        """POST /api/v1/credit/agreements/ — 小额度直接生效"""
        client = _make_credit_client()
        row = _agreement_row(status="active", credit_limit_fen=100_000)
        mock_db = _mock_db_single(first_val=row)

        with (
            patch.object(credit_account_routes, "_get_tenant_db", return_value=mock_db),
            patch("credit_account_routes.asyncio.create_task", MagicMock()),
        ):
            resp = client.post(
                "/api/v1/credit/agreements/",
                json={
                    "brand_id": BRAND_ID,
                    "company_name": "测试公司",
                    "credit_limit_fen": 100_000,
                    "billing_cycle": "monthly",
                    "due_day": 15,
                },
                headers=OP_HDR,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "active"
        assert body["data"]["requires_approval"] is False

    def test_create_agreement_large_limit_pending(self):
        """POST /api/v1/credit/agreements/ — 大额度需审批"""
        client = _make_credit_client()
        row = _agreement_row(status="pending_approval", credit_limit_fen=5_000_000)
        mock_db = _mock_db_single(first_val=row)

        with (
            patch.object(credit_account_routes, "_get_tenant_db", return_value=mock_db),
            patch("credit_account_routes.asyncio.create_task", MagicMock()),
        ):
            resp = client.post(
                "/api/v1/credit/agreements/",
                json={
                    "brand_id": BRAND_ID,
                    "company_name": "大客户公司",
                    "credit_limit_fen": 5_000_000,
                    "billing_cycle": "monthly",
                    "due_day": 15,
                },
                headers=OP_HDR,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "pending_approval"
        assert body["data"]["requires_approval"] is True

    def test_create_agreement_invalid_cycle(self):
        """POST /api/v1/credit/agreements/ — 400 非法账期"""
        client = _make_credit_client()
        resp = client.post(
            "/api/v1/credit/agreements/",
            json={
                "brand_id": BRAND_ID,
                "company_name": "测试",
                "credit_limit_fen": 100_000,
                "billing_cycle": "quarterly",  # 非法值
                "due_day": 15,
            },
            headers=OP_HDR,
        )
        assert resp.status_code == 400
        assert "billing_cycle" in resp.json()["detail"]

    def test_list_agreements_success(self):
        """GET /api/v1/credit/agreements/ — 返回协议列表"""
        client = _make_credit_client()
        row = _agreement_row()
        session = AsyncMock()
        count_res = MagicMock()
        count_res.scalar.return_value = 1
        items_res = MagicMock()
        items_res.mappings.return_value.all.return_value = [row]
        session.execute = AsyncMock(side_effect=[count_res, items_res])
        session.commit = AsyncMock()

        with patch.object(credit_account_routes, "_get_tenant_db", return_value=session):
            resp = client.get("/api/v1/credit/agreements/", headers=TENANT_HDR)

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 1

    def test_get_agreement_detail_success(self):
        """GET /api/v1/credit/agreements/{id} — 协议详情"""
        client = _make_credit_client()
        row = _agreement_row()
        mock_db = _mock_db_single(first_val=row)

        with patch.object(credit_account_routes, "_get_tenant_db", return_value=mock_db):
            resp = client.get(
                f"/api/v1/credit/agreements/{AGREEMENT_ID}",
                headers=TENANT_HDR,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["company_name"] == "测试公司"

    def test_get_agreement_detail_not_found(self):
        """GET /api/v1/credit/agreements/{id} — 404 不存在"""
        client = _make_credit_client()
        mock_db = _mock_db_single(first_val=None)

        with patch.object(credit_account_routes, "_get_tenant_db", return_value=mock_db):
            resp = client.get(
                f"/api/v1/credit/agreements/{AGREEMENT_ID}",
                headers=TENANT_HDR,
            )
        assert resp.status_code == 404

    def test_suspend_agreement_success(self):
        """POST /api/v1/credit/agreements/{id}/suspend — 暂停协议"""
        client = _make_credit_client()
        fetch_row = _agreement_row(status="active")
        updated_row = _agreement_row(status="suspended")

        session = AsyncMock()
        fetch_result = MagicMock()
        fetch_result.mappings.return_value.first.return_value = fetch_row
        update_result = MagicMock()
        update_result.mappings.return_value.first.return_value = updated_row
        session.execute = AsyncMock(side_effect=[fetch_result, update_result])
        session.commit = AsyncMock()

        with (
            patch.object(credit_account_routes, "_get_tenant_db", return_value=session),
            patch("credit_account_routes.asyncio.create_task", MagicMock()),
        ):
            resp = client.post(
                f"/api/v1/credit/agreements/{AGREEMENT_ID}/suspend",
                json={"remark": "风控触发暂停"},
                headers=OP_HDR,
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "suspended"
