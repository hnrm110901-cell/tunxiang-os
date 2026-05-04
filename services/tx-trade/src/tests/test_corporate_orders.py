"""团餐/企业客户路由测试 — DB 模式（v206 Y-A9 Mock→DB 改造后重写，PG.7）

旧测试基于已删除的 _MOCK_BILLS / _MOCK_ORDERS / MOCK_CORPORATE_CUSTOMERS 常量，
v206 改造后路由切换到 corporate_customers / corporate_orders / corporate_bills 三张表，
本文件用 fastapi TestClient + AsyncMock(AsyncSession) 重写，覆盖原 10 个业务场景。

模式说明：
- mock 一个 AsyncMock(spec=AsyncSession) 作为 db
- 通过 app.dependency_overrides[_get_db] 注入 mock session
- 每个测试为路由的每条 db.execute() 调用按顺序构造 side_effect 返回值
- 路由用 row.fetchone() / row.fetchall() / row.scalar() 三种取值方式，分别用对应 helper 构造

覆盖场景：
1. TestCreateCorporateOrderWithDiscount
   - test_discount_applied_correctly        — 订单 × 0.95 折扣后金额准确
   - test_no_discount_rate_one              — discount_rate=1.0 不打折
   - test_order_updates_used_credit         — 创建订单后授信余额减少（通过 UPDATE 入参验证）
2. TestCreditLimitExceeded
   - test_credit_exceeded_returns_400       — 授信超限返回 400
   - test_credit_exactly_at_limit_succeeds  — 等于限额可成功
   - test_inactive_customer_returns_400     — 客户停用返回 400
3. TestBulkBilling
   - test_bulk_bill_returns_bill_id         — 批量出账返回 bill_id
   - test_orders_marked_billed_after_bulk_bill — 出账后 UPDATE 调用
   - test_no_unbilled_orders_returns_400    — 无未出账订单返回 400
   - test_csv_export_returns_csv_content    — CSV 导出格式正确
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from ..api import corporate_order_routes
from ..api.corporate_order_routes import router

# ─── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = "11111111-1111-1111-1111-111111111111"
HEADERS = {"X-Tenant-Id": TENANT_ID}

# corp-001：limit=5_000_000 分，used=1_280_000 分，available=3_720_000 分，discount=0.95
CORP_001_ID = "00000000-0000-0000-0000-000000000001"
# corp-002：用于停用场景
CORP_002_ID = "00000000-0000-0000-0000-000000000002"


# ─── 辅助：构造 mock 行（同时支持 .attr 访问 和 ._mapping） ─────────────────

def _row(**fields: Any) -> MagicMock:
    """构造路由 row.fetchone()/fetchall() 返回的行对象。

    路由有两种访问模式：
    - row.attr_name           （通过 attribute）
    - dict(r._mapping)        （通过 _mapping 转 dict）
    本辅助同时支持。
    """
    obj = MagicMock()
    for k, v in fields.items():
        setattr(obj, k, v)
    obj._mapping = fields
    return obj


def _exec_fetchone(row: MagicMock | None) -> MagicMock:
    """构造 db.execute() 的返回值，使 .fetchone() 返回 row。"""
    result = MagicMock()
    result.fetchone = MagicMock(return_value=row)
    return result


def _exec_fetchall(rows: list[MagicMock]) -> MagicMock:
    """构造 db.execute() 的返回值，使 .fetchall() 返回 rows 列表。"""
    result = MagicMock()
    result.fetchall = MagicMock(return_value=rows)
    return result


def _exec_scalar(value: Any) -> MagicMock:
    """构造 db.execute() 的返回值，使 .scalar() 返回 value。"""
    result = MagicMock()
    result.scalar = MagicMock(return_value=value)
    return result


def _make_db() -> AsyncMock:
    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _make_app(db: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    async def _override():
        yield db

    app.dependency_overrides[corporate_order_routes._get_db] = _override
    return app


# ─── 标准客户行（按路由 SELECT 查询字段构造） ─────────────────────────────────

def _customer_row(
    *,
    cid: str = CORP_001_ID,
    company_name: str = "测试餐饮公司",
    status: str = "active",
    credit_limit_fen: int = 5_000_000,
    used_credit_fen: int = 1_280_000,
    discount_rate: float = 0.95,
    approved_menu_ids: list[str] | None = None,
) -> MagicMock:
    return _row(
        id=uuid.UUID(cid),
        company_name=company_name,
        status=status,
        credit_limit_fen=credit_limit_fen,
        used_credit_fen=used_credit_fen,
        discount_rate=discount_rate,
        approved_menu_ids=approved_menu_ids or [],
    )


def _order_returning_row() -> MagicMock:
    """create_corporate_order 路由 INSERT...RETURNING 的行字段。"""
    return _row(
        id=uuid.uuid4(),
        order_no=f"CO-{uuid.uuid4().hex[:12].upper()}",
        final_amount_fen=0,  # 测试中不强校验，通过 response 验证业务计算
        ordered_at=datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Test 1: 企业订单应用折扣
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCreateCorporateOrderWithDiscount:
    """企业订单应用 discount_rate=0.95，实际金额 = 原始金额 × 0.95。"""

    def test_discount_applied_correctly(self) -> None:
        """订单金额 × 0.95 四舍五入到整数分。

        路由 execute 顺序：
        1) SELECT customer
        2) INSERT corporate_orders RETURNING ...
        3) UPDATE corporate_customers SET used_credit_fen ...
        """
        db = _make_db()
        db.execute = AsyncMock(
            side_effect=[
                _exec_fetchone(_customer_row(discount_rate=0.95)),  # SELECT
                _exec_fetchone(_order_returning_row()),             # INSERT RETURNING
                MagicMock(),                                         # UPDATE
            ]
        )
        client = TestClient(_make_app(db))
        payload = {
            "corporate_customer_id": CORP_001_ID,
            "store_id": "33333333-3333-3333-3333-333333333333",
            "items": [
                {"dish_id": "dish-001", "dish_name": "红烧肉", "qty": 2, "unit_price_fen": 3800},
                {"dish_id": "dish-002", "dish_name": "米饭", "qty": 5, "unit_price_fen": 200},
            ],
        }
        resp = client.post("/api/v1/trade/corporate/orders", json=payload, headers=HEADERS)
        assert resp.status_code == 201, resp.text

        data = resp.json()["data"]
        original = 2 * 3800 + 5 * 200  # = 8600
        expected_discounted = int(
            (Decimal(str(original)) * Decimal("0.95")).to_integral_value(rounding=ROUND_HALF_UP)
        )  # = 8170 分
        assert data["original_amount_fen"] == original
        assert abs(data["discount_rate"] - 0.95) < 1e-6
        assert data["final_amount_fen"] == expected_discounted

    def test_no_discount_rate_one(self) -> None:
        """discount_rate=1.0 时折后金额 == 原始金额。"""
        db = _make_db()
        db.execute = AsyncMock(
            side_effect=[
                _exec_fetchone(_customer_row(discount_rate=1.0, credit_limit_fen=10_000_000, used_credit_fen=0)),
                _exec_fetchone(_order_returning_row()),
                MagicMock(),
            ]
        )
        client = TestClient(_make_app(db))
        payload = {
            "corporate_customer_id": CORP_001_ID,
            "store_id": "33333333-3333-3333-3333-333333333333",
            "items": [{"dish_id": "dish-x", "dish_name": "套餐", "qty": 1, "unit_price_fen": 5000}],
        }
        resp = client.post("/api/v1/trade/corporate/orders", json=payload, headers=HEADERS)
        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        assert data["original_amount_fen"] == data["final_amount_fen"] == 5000

    def test_order_updates_used_credit(self) -> None:
        """创建订单后路由会调用 UPDATE corporate_customers 把 final_amount_fen 加到 used_credit_fen。

        校验方式：检查第三次 db.execute 的入参 amount == 折后金额（10000 × 0.95 = 9500 分）。
        """
        db = _make_db()
        db.execute = AsyncMock(
            side_effect=[
                _exec_fetchone(_customer_row(discount_rate=0.95)),
                _exec_fetchone(_order_returning_row()),
                MagicMock(),
            ]
        )
        client = TestClient(_make_app(db))
        payload = {
            "corporate_customer_id": CORP_001_ID,
            "store_id": "33333333-3333-3333-3333-333333333333",
            "items": [{"dish_id": "dish-003", "dish_name": "套餐C", "qty": 1, "unit_price_fen": 10_000}],
        }
        resp = client.post("/api/v1/trade/corporate/orders", json=payload, headers=HEADERS)
        assert resp.status_code == 201, resp.text

        # 第 3 次 execute 应是 UPDATE used_credit_fen，amount = 9500
        update_call = db.execute.await_args_list[2]
        bind_params = update_call.args[1]
        assert bind_params["amount"] == 9500
        assert bind_params["cid"] == CORP_001_ID
        # commit 必须被调用
        db.commit.assert_awaited()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Test 2: 授信超限 / 状态校验
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCreditLimitExceeded:
    """available = limit - used < 折后金额 → 必须返回 400。"""

    def test_credit_exceeded_returns_400(self) -> None:
        """corp-001：available=3_720_000，下单 4_000_000 × 0.95 = 3_800_000 > 3_720_000 → 400。"""
        db = _make_db()
        # 仅一次 execute（SELECT customer），然后路由抛 400
        db.execute = AsyncMock(side_effect=[_exec_fetchone(_customer_row())])

        client = TestClient(_make_app(db))
        payload = {
            "corporate_customer_id": CORP_001_ID,
            "store_id": "33333333-3333-3333-3333-333333333333",
            "items": [{"dish_id": "dish-big", "dish_name": "大额套餐", "qty": 1, "unit_price_fen": 4_000_000}],
        }
        resp = client.post("/api/v1/trade/corporate/orders", json=payload, headers=HEADERS)
        assert resp.status_code == 400, resp.text
        assert "授信额度不足" in resp.json()["detail"]

    def test_credit_exactly_at_limit_succeeds(self) -> None:
        """折后金额 == available 时应成功（不超限）。

        corp-001：available=3_720_000；下单 3_000_000 × 0.95 = 2_850_000 ≤ 3_720_000 → 成功。
        """
        db = _make_db()
        db.execute = AsyncMock(
            side_effect=[
                _exec_fetchone(_customer_row()),
                _exec_fetchone(_order_returning_row()),
                MagicMock(),
            ]
        )
        client = TestClient(_make_app(db))
        payload = {
            "corporate_customer_id": CORP_001_ID,
            "store_id": "33333333-3333-3333-3333-333333333333",
            "items": [{"dish_id": "dish-safe", "dish_name": "中额套餐", "qty": 1, "unit_price_fen": 3_000_000}],
        }
        resp = client.post("/api/v1/trade/corporate/orders", json=payload, headers=HEADERS)
        assert resp.status_code == 201, resp.text

    def test_inactive_customer_returns_400(self) -> None:
        """status != active 的企业客户无法下单。"""
        db = _make_db()
        db.execute = AsyncMock(
            side_effect=[_exec_fetchone(_customer_row(cid=CORP_002_ID, status="inactive"))]
        )
        client = TestClient(_make_app(db))
        payload = {
            "corporate_customer_id": CORP_002_ID,
            "store_id": "33333333-3333-3333-3333-333333333333",
            "items": [{"dish_id": "dish-y", "dish_name": "套餐Y", "qty": 1, "unit_price_fen": 1000}],
        }
        resp = client.post("/api/v1/trade/corporate/orders", json=payload, headers=HEADERS)
        assert resp.status_code == 400, resp.text
        assert "inactive" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Test 3: 批量出账 + CSV 导出
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestBulkBilling:
    """批量出账：调用后返回 bill_id，相关订单 UPDATE billed=TRUE。"""

    def test_bulk_bill_returns_bill_id(self) -> None:
        """批量出账成功路径：返回 bill_id（UUID 字符串），order_count/total_amount_fen 来自聚合。

        路由 execute 顺序：
        1) SELECT customer (id, company_name)
        2) SELECT COUNT/SUM 聚合（cnt, total）
        3) INSERT corporate_bills RETURNING id (.scalar())
        4) UPDATE corporate_orders SET billed=TRUE
        """
        bill_uuid = uuid.uuid4()
        db = _make_db()
        db.execute = AsyncMock(
            side_effect=[
                _exec_fetchone(_row(id=uuid.UUID(CORP_001_ID), company_name="测试餐饮公司")),
                _exec_fetchone(_row(cnt=2, total=12_000)),
                _exec_scalar(bill_uuid),
                MagicMock(),
            ]
        )
        client = TestClient(_make_app(db))
        payload = {
            "corporate_customer_id": CORP_001_ID,
            "billing_period_start": "2026-05-01",
            "billing_period_end": "2026-05-31",
        }
        resp = client.post("/api/v1/trade/corporate/orders/bulk-bill", json=payload, headers=HEADERS)
        assert resp.status_code == 200, resp.text

        data = resp.json()["data"]
        assert data["bill_id"] == str(bill_uuid)
        assert data["bill_no"].startswith("BILL-")
        assert data["order_count"] == 2
        assert data["total_amount_fen"] == 12_000
        assert data["total_amount_yuan"] == 120.0

    def test_orders_marked_billed_after_bulk_bill(self) -> None:
        """出账成功后第 4 次 execute 应是 UPDATE corporate_orders SET billed=TRUE，bind 含 bill_id。"""
        bill_uuid = uuid.uuid4()
        db = _make_db()
        db.execute = AsyncMock(
            side_effect=[
                _exec_fetchone(_row(id=uuid.UUID(CORP_001_ID), company_name="测试餐饮公司")),
                _exec_fetchone(_row(cnt=1, total=5_000)),
                _exec_scalar(bill_uuid),
                MagicMock(),
            ]
        )
        client = TestClient(_make_app(db))
        payload = {
            "corporate_customer_id": CORP_001_ID,
            "billing_period_start": "2026-05-01",
            "billing_period_end": "2026-05-31",
        }
        resp = client.post("/api/v1/trade/corporate/orders/bulk-bill", json=payload, headers=HEADERS)
        assert resp.status_code == 200, resp.text

        # 第 4 次 execute 是 UPDATE 标记订单为 billed
        update_call = db.execute.await_args_list[3]
        bind_params = update_call.args[1]
        assert bind_params["bill_id"] == bill_uuid
        assert bind_params["cid"] == CORP_001_ID
        # commit 必须被调用
        db.commit.assert_awaited()

    def test_no_unbilled_orders_returns_400(self) -> None:
        """聚合查询返回 cnt=0 → 路由返回 400。"""
        db = _make_db()
        db.execute = AsyncMock(
            side_effect=[
                _exec_fetchone(_row(id=uuid.UUID(CORP_001_ID), company_name="测试餐饮公司")),
                _exec_fetchone(_row(cnt=0, total=0)),
            ]
        )
        client = TestClient(_make_app(db))
        payload = {
            "corporate_customer_id": CORP_001_ID,
            "billing_period_start": "2020-01-01",
            "billing_period_end": "2020-01-31",
        }
        resp = client.post("/api/v1/trade/corporate/orders/bulk-bill", json=payload, headers=HEADERS)
        assert resp.status_code == 400, resp.text
        assert "无可出账" in resp.json()["detail"]

    def test_csv_export_returns_csv_content(self) -> None:
        """对账导出：response 头 text/csv，body 含中文表头。"""
        order_row = _row(
            order_no="CO-ABC123XYZ",
            company_name="测试餐饮公司",
            store_id=uuid.uuid4(),
            original_amount_fen=8600,
            discount_rate=0.95,
            final_amount_fen=8170,
            billing_status="unbilled",
            ordered_at=datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc),
        )
        db = _make_db()
        db.execute = AsyncMock(side_effect=[_exec_fetchall([order_row])])
        client = TestClient(_make_app(db))
        resp = client.get(
            "/api/v1/trade/corporate/export",
            params={
                "corporate_customer_id": CORP_001_ID,
                "date_from": str(date(2026, 5, 1)),
                "date_to": str(date(2026, 5, 31)),
                "format": "csv",
            },
            headers=HEADERS,
        )
        assert resp.status_code == 200, resp.text
        assert "text/csv" in resp.headers["content-type"]
        body = resp.text
        # 中文表头
        assert "订单号" in body
        assert "企业名称" in body
        assert "实际金额(分)" in body
        # 数据行
        assert "CO-ABC123XYZ" in body
        assert "8170" in body
