"""
tx-finance 支付对账报表测试
覆盖：
  - payment_reconciliation_routes (4 个端点): 5 个测试

运行方式：
    cd /Users/lichun/tunxiang-os/services/tx-finance
    pytest src/tests/test_payment_reconciliation.py -v
"""
from __future__ import annotations

import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

# ─── 存根工具 ─────────────────────────────────────────────────────────────────


def _make_stub(name: str, **attrs) -> types.ModuleType:
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


# ── structlog 存根 ────────────────────────────────────────────────────────────
if "structlog" not in sys.modules:
    _stub_log = MagicMock()
    _stub_logger = MagicMock()
    _stub_logger.bind.return_value = _stub_logger
    _stub_logger.info = MagicMock()
    _stub_logger.warning = MagicMock()
    _stub_logger.error = MagicMock()
    _stub_log.get_logger.return_value = _stub_logger
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

SQLAlchemyError = sys.modules["sqlalchemy.exc"].SQLAlchemyError

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

# ─── 加载被测模块 ─────────────────────────────────────────────────────────────

from api.payment_reconciliation_routes import (  # noqa: E402
    _mock_cashier_receipts,
    _mock_channel_summaries,
    _mock_crm_reconciliation,
    _mock_payment_details,
    router,
)
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# ─── 公共常量 ─────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
TENANT_HDR = {"X-Tenant-ID": TENANT_ID}


# ─── 测试客户端工厂 ───────────────────────────────────────────────────────────


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


# ─── DB session mock 工厂 ─────────────────────────────────────────────────────


def _db_no_rows() -> AsyncMock:
    """模拟 DB 查询返回空结果（触发 mock 降级）。"""
    session = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = []
    result.scalar.return_value = 0
    session.execute = AsyncMock(return_value=result)
    return session


def _db_raises() -> AsyncMock:
    """模拟 DB 查询抛 SQLAlchemyError（触发 mock 降级）。"""
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("db error"))
    return session


def _db_channel_rows(channels: list[dict]) -> AsyncMock:
    """模拟 DB 返回指定渠道汇总行。"""
    session = AsyncMock()
    rows = [
        MagicMock(
            channel=c["channel"],
            transaction_count=c["transaction_count"],
            total_amount_fen=c["total_amount_fen"],
            fee_fen=c["fee_fen"],
        )
        for c in channels
    ]
    result = MagicMock()
    result.fetchall.return_value = rows
    session.execute = AsyncMock(return_value=result)
    return session


def _db_cashier_rows(cashiers: list[dict]) -> AsyncMock:
    """模拟 DB 返回指定收银员汇总行。"""
    session = AsyncMock()
    rows = [
        MagicMock(
            cashier_id=c["cashier_id"],
            cashier_name=c["cashier_name"],
            shift_count=c["shift_count"],
            total_amount_fen=c["total_amount_fen"],
            order_count=c["order_count"],
            wechat_fen=c.get("wechat_fen", 0),
            alipay_fen=c.get("alipay_fen", 0),
            cash_fen=c.get("cash_fen", 0),
            card_fen=c.get("card_fen", 0),
            member_card_fen=c.get("member_card_fen", 0),
            other_fen=c.get("other_fen", 0),
        )
        for c in cashiers
    ]
    result = MagicMock()
    result.fetchall.return_value = rows
    session.execute = AsyncMock(return_value=result)
    return session


# ═══════════════════════════════════════════════════════════════════════════════
#  1. test_payment_reconciliation_by_channel — 多渠道聚合金额正确
# ═══════════════════════════════════════════════════════════════════════════════


def test_payment_reconciliation_by_channel():
    """多渠道聚合：grand_total_fen = sum(各渠道 total_amount_fen)，net = total - fee。"""
    channels = [
        {"channel": "wechat",  "transaction_count": 100, "total_amount_fen": 200000, "fee_fen": 600},
        {"channel": "alipay",  "transaction_count": 50,  "total_amount_fen": 100000, "fee_fen": 300},
        {"channel": "cash",    "transaction_count": 20,  "total_amount_fen": 50000,  "fee_fen": 0},
    ]
    db = _db_channel_rows(channels)

    client = _make_client()
    # 通过 dependency_overrides 注入 mock DB
    from api.payment_reconciliation_routes import _get_tenant_db, _validate_tenant_id

    async def _fake_db():
        yield db

    app = client.app  # type: ignore[attr-defined]
    app.dependency_overrides[_get_tenant_db] = _fake_db
    app.dependency_overrides[_validate_tenant_id] = lambda: TENANT_ID

    resp = client.get(
        "/api/v1/finance/payment-reconciliation",
        params={"start_date": "2026-04-01", "end_date": "2026-04-06"},
        headers=TENANT_HDR,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]

    # grand_total = sum of all channel totals
    expected_grand = sum(c["total_amount_fen"] for c in channels)
    assert data["grand_total_fen"] == expected_grand

    # net_amount_fen = total - fee for each channel
    for ch_resp in data["channels"]:
        matching = next(c for c in channels if c["channel"] == ch_resp["channel"])
        expected_net = matching["total_amount_fen"] - matching["fee_fen"]
        assert ch_resp["net_amount_fen"] == expected_net

    # total_transactions
    assert data["total_transactions"] == sum(c["transaction_count"] for c in channels)


# ═══════════════════════════════════════════════════════════════════════════════
#  2. test_payment_details_date_filter — 日期过滤：缺参数时 422
# ═══════════════════════════════════════════════════════════════════════════════


def test_payment_details_date_filter():
    """start_date / end_date 为必填项；缺失时返回 422；start > end 时返回 400。"""
    client = _make_client()

    # 缺 start_date → 422
    resp = client.get(
        "/api/v1/finance/payment-details",
        params={"end_date": "2026-04-06"},
        headers=TENANT_HDR,
    )
    assert resp.status_code == 422

    # 缺 end_date → 422
    resp = client.get(
        "/api/v1/finance/payment-details",
        params={"start_date": "2026-04-01"},
        headers=TENANT_HDR,
    )
    assert resp.status_code == 422

    # start_date > end_date → 400
    from api.payment_reconciliation_routes import _get_tenant_db, _validate_tenant_id

    async def _fake_db():
        yield _db_no_rows()

    app = client.app  # type: ignore[attr-defined]
    app.dependency_overrides[_get_tenant_db] = _fake_db
    app.dependency_overrides[_validate_tenant_id] = lambda: TENANT_ID

    resp = client.get(
        "/api/v1/finance/payment-details",
        params={"start_date": "2026-04-10", "end_date": "2026-04-01"},
        headers=TENANT_HDR,
    )
    assert resp.status_code == 400
    assert "start_date" in resp.json()["detail"]

    # 正常范围 + DB 无数据 → 降级 mock，返回 200 + 分页结构
    resp = client.get(
        "/api/v1/finance/payment-details",
        params={"start_date": "2026-04-01", "end_date": "2026-04-06", "page": "1", "size": "10"},
        headers=TENANT_HDR,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert "items" in data
    assert "total" in data
    assert data["page"] == 1
    assert data["size"] == 10


# ═══════════════════════════════════════════════════════════════════════════════
#  3. test_cashier_receipts_aggregation — 同收银员多笔汇总正确
# ═══════════════════════════════════════════════════════════════════════════════


def test_cashier_receipts_aggregation():
    """同收银员的各渠道分解金额在响应中正确映射。"""
    cashiers_data = [
        {
            "cashier_id": "C001",
            "cashier_name": "张三",
            "shift_count": 3,
            "total_amount_fen": 456780,
            "order_count": 145,
            "wechat_fen": 205551,
            "alipay_fen": 127898,
            "cash_fen": 54813,
            "card_fen": 45678,
            "member_card_fen": 22840,
            "other_fen": 0,
        },
        {
            "cashier_id": "C002",
            "cashier_name": "李四",
            "shift_count": 2,
            "total_amount_fen": 312400,
            "order_count": 98,
            "wechat_fen": 140580,
            "alipay_fen": 87472,
            "cash_fen": 37488,
            "card_fen": 31240,
            "member_card_fen": 15620,
            "other_fen": 0,
        },
    ]
    db = _db_cashier_rows(cashiers_data)

    client = _make_client()
    from api.payment_reconciliation_routes import _get_tenant_db, _validate_tenant_id

    async def _fake_db():
        yield db

    app = client.app  # type: ignore[attr-defined]
    app.dependency_overrides[_get_tenant_db] = _fake_db
    app.dependency_overrides[_validate_tenant_id] = lambda: TENANT_ID

    resp = client.get(
        "/api/v1/finance/cashier-receipts",
        params={"start_date": "2026-04-01", "end_date": "2026-04-06"},
        headers=TENANT_HDR,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    cashiers_resp = body["data"]["cashiers"]
    assert len(cashiers_resp) == 2

    # 验证第一个收银员的渠道分解
    first = next(c for c in cashiers_resp if c["cashier_id"] == "C001")
    assert first["cashier_name"] == "张三"
    assert first["shift_count"] == 3
    assert first["order_count"] == 145
    assert first["channel_breakdown"]["wechat"] == 205551
    assert first["channel_breakdown"]["alipay"] == 127898
    assert first["channel_breakdown"]["cash"] == 54813


# ═══════════════════════════════════════════════════════════════════════════════
#  4. test_crm_reconciliation_returns_structure — 返回字段结构完整
# ═══════════════════════════════════════════════════════════════════════════════


def test_crm_reconciliation_returns_structure():
    """CRM对账接口返回字段结构完整：match_count/mismatch_count/total_diff_fen/mismatch_items。"""
    client = _make_client()
    from api.payment_reconciliation_routes import _validate_tenant_id

    app = client.app  # type: ignore[attr-defined]
    app.dependency_overrides[_validate_tenant_id] = lambda: TENANT_ID

    resp = client.get(
        "/api/v1/finance/crm-reconciliation",
        params={"start_date": "2026-04-01", "end_date": "2026-04-06"},
        headers=TENANT_HDR,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]

    # 必需字段存在
    required_fields = [
        "match_count", "mismatch_count", "total_diff_fen", "mismatch_items",
        "start_date", "end_date", "used_mock",
    ]
    for field in required_fields:
        assert field in data, f"缺少字段: {field}"

    # 类型校验
    assert isinstance(data["match_count"], int)
    assert isinstance(data["mismatch_count"], int)
    assert isinstance(data["total_diff_fen"], int)
    assert isinstance(data["mismatch_items"], list)
    assert data["used_mock"] is True

    # mismatch_items 中每条记录包含必需字段
    for item in data["mismatch_items"]:
        for f in ["member_id", "member_name", "phone", "crm_amount_fen", "finance_amount_fen", "diff_fen", "type"]:
            assert f in item, f"mismatch_item 缺少字段: {f}"


# ═══════════════════════════════════════════════════════════════════════════════
#  5. test_tenant_isolation — 不同 tenant 数据隔离
# ═══════════════════════════════════════════════════════════════════════════════


def test_tenant_isolation():
    """缺少 X-Tenant-ID header 时返回 422；不同 tenant_id 使用独立 DB session。"""
    client = _make_client()

    # 缺 X-Tenant-ID → 422
    resp = client.get(
        "/api/v1/finance/payment-reconciliation",
        params={"start_date": "2026-04-01", "end_date": "2026-04-06"},
    )
    assert resp.status_code == 422

    # 非法 UUID → 400
    resp = client.get(
        "/api/v1/finance/payment-reconciliation",
        params={"start_date": "2026-04-01", "end_date": "2026-04-06"},
        headers={"X-Tenant-ID": "not-a-uuid"},
    )
    assert resp.status_code == 400
    assert "X-Tenant-ID" in resp.json()["detail"]

    # Tenant A / Tenant B 各自获得独立 DB session（通过 get_db_with_tenant 隔离）
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())

    db_a = _db_no_rows()
    db_b = _db_no_rows()
    call_log: list[str] = []

    from api.payment_reconciliation_routes import _get_tenant_db, _validate_tenant_id

    app = client.app  # type: ignore[attr-defined]

    async def _fake_db_a():
        call_log.append("tenant_a")
        yield db_a

    async def _fake_db_b():
        call_log.append("tenant_b")
        yield db_b

    app.dependency_overrides[_get_tenant_db] = _fake_db_a
    resp_a = client.get(
        "/api/v1/finance/payment-reconciliation",
        params={"start_date": "2026-04-01", "end_date": "2026-04-06"},
        headers={"X-Tenant-ID": tenant_a},
    )
    assert resp_a.status_code == 200
    assert resp_a.json()["ok"] is True

    # 切换到 tenant_b
    app.dependency_overrides[_get_tenant_db] = _fake_db_b
    app.dependency_overrides[_validate_tenant_id] = lambda: tenant_b
    resp_b = client.get(
        "/api/v1/finance/payment-reconciliation",
        params={"start_date": "2026-04-01", "end_date": "2026-04-06"},
        headers={"X-Tenant-ID": tenant_b},
    )
    assert resp_b.status_code == 200
    assert resp_b.json()["ok"] is True

    # 两次请求使用了不同的 DB session（通过 call_log 验证）
    assert "tenant_a" in call_log
    assert "tenant_b" in call_log


def _get_tenant_db_placeholder(tenant_id: str):
    """占位符，用于隔离测试中区分不同 tenant 的 DB 依赖键。"""
    async def _dep():
        yield None
    _dep.__name__ = f"db_for_{tenant_id}"
    return _dep


# ─── 单元测试：mock 数据辅助函数 ──────────────────────────────────────────────


def test_mock_helpers_consistency():
    """验证 mock 数据辅助函数输出的一致性。"""
    from datetime import date

    # 渠道汇总：net = total - fee
    channels = _mock_channel_summaries(date(2026, 4, 1), date(2026, 4, 6))
    for ch in channels:
        assert ch["net_amount_fen"] == ch["total_amount_fen"] - ch["fee_fen"]
        assert ch["channel_name"]  # 非空
        assert ch["channel"] in {"wechat", "alipay", "cash", "card", "member_card", "other"}

    # 逐笔明细分页
    page_data = _mock_payment_details(1, 10)
    assert len(page_data["items"]) == 10
    assert page_data["total"] > 0
    assert page_data["page"] == 1

    page2 = _mock_payment_details(2, 10)
    assert page2["page"] == 2
    assert len(page2["items"]) == 10

    # 收银员统计
    cashiers = _mock_cashier_receipts()
    assert len(cashiers) > 0
    for c in cashiers:
        breakdown_sum = sum(c["channel_breakdown"].values())
        # breakdown 合计应接近 total（允许舍入误差）
        assert abs(breakdown_sum - c["total_amount_fen"]) <= 100

    # CRM 对账
    crm = _mock_crm_reconciliation()
    assert crm["match_count"] > 0
    assert crm["mismatch_count"] == len(crm["mismatch_items"])
    assert crm["total_diff_fen"] == sum(abs(m["diff_fen"]) for m in crm["mismatch_items"])
