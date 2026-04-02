"""test_stored_value.py — 储值充值路由测试

覆盖范围：
  GET  /api/v1/members/{member_id}/stored-value
  POST /api/v1/members/{member_id}/stored-value/recharge
  POST /api/v1/members/{member_id}/stored-value/consume
  POST /api/v1/members/{member_id}/stored-value/refund
  GET  /api/v1/members/{member_id}/stored-value（calc-bonus 辅助函数）

充值赠送档位（均以"分"为单位）：
  ≥ 300_000 分 (3000元) → 赠 50_000 分
  ≥ 200_000 分 (2000元) → 赠 30_000 分
  ≥ 100_000 分 (1000元) → 赠 15_000 分
  ≥  50_000 分  (500元) → 赠  5_000 分
  <  50_000 分          → 赠  0

DB 层通过 app.dependency_overrides[get_db] 注入 AsyncMock，
避免真实数据库连接，并精确控制 SELECT / UPDATE / INSERT 的返回值。
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")),
)

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from src.api.stored_value_routes import router as stored_value_router, _calc_bonus
from shared.ontology.src.database import get_db

# ─── 测试 app ─────────────────────────────────────────────────────────────────

_app = FastAPI(title="stored-value-test")
_app.include_router(stored_value_router)

TENANT_ID = "00000000-0000-0000-0000-000000000001"
TENANT_HEADERS = {"X-Tenant-ID": TENANT_ID}

MEMBER_A = str(uuid.uuid4())


# ─── Mock DB 工厂 ─────────────────────────────────────────────────────────────


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    return db


def _exec_result_with_row(row_dict: dict | None) -> MagicMock:
    """模拟 db.execute() 返回单行 mapping。"""
    result = MagicMock()
    mapping = MagicMock()
    mapping.first = MagicMock(return_value=row_dict)
    result.mappings = MagicMock(return_value=mapping)
    return result


def _exec_result_multi(rows: list[dict]) -> MagicMock:
    """模拟 db.execute() 返回多行 mapping（用于流水查询）。"""
    result = MagicMock()
    mapping = MagicMock()
    mapping.first = MagicMock(return_value=rows[0] if rows else None)

    class _Rows:
        def __iter__(self):
            return iter([MagicMock(**{k: v for k, v in r.items()}) for r in rows])

    result.mappings = MagicMock(return_value=_Rows())
    return result


def _make_account(balance: int = 0, frozen: int = 0) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "balance_fen": balance,
        "frozen_fen": frozen,
        "total_recharged_fen": 0,
        "total_consumed_fen": 0,
    }


# ─── DB override 上下文 ───────────────────────────────────────────────────────


class _DBOverride:
    """上下文管理器：临时将 get_db 替换为返回指定 mock_db 的生成器。"""

    def __init__(self, mock_db: AsyncMock):
        self._mock_db = mock_db

    def __enter__(self):
        async def _override():
            yield self._mock_db

        _app.dependency_overrides[get_db] = _override
        return self._mock_db

    def __exit__(self, *args):
        _app.dependency_overrides.pop(get_db, None)


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=_app), base_url="http://test"
    ) as ac:
        yield ac


# ─── 单元测试：_calc_bonus 纯函数 ─────────────────────────────────────────────


class TestCalcBonus:
    """直接测试 _calc_bonus 纯函数，无需 HTTP 请求。"""

    def test_no_bonus_below_50000(self):
        """充值不足 50_000 分 → 赠送 0。"""
        assert _calc_bonus(10_000) == 0
        assert _calc_bonus(49_999) == 0

    def test_bonus_at_50000(self):
        """充值 50_000 分（500元）→ 赠 5_000 分。"""
        assert _calc_bonus(50_000) == 5_000

    def test_bonus_at_100000(self):
        """充值 100_000 分（1000元）→ 赠 15_000 分。"""
        assert _calc_bonus(100_000) == 15_000

    def test_bonus_at_200000(self):
        """充值 200_000 分（2000元）→ 赠 30_000 分。"""
        assert _calc_bonus(200_000) == 30_000

    def test_bonus_at_300000(self):
        """充值 300_000 分（3000元）→ 赠 50_000 分。"""
        assert _calc_bonus(300_000) == 50_000

    def test_bonus_above_300000(self):
        """充值超过 300_000 分 → 仍取最高档 50_000 分。"""
        assert _calc_bonus(500_000) == 50_000

    def test_bonus_100_yuan(self):
        """充值 10_000 分（100元）→ 不满 50_000 档位，赠 0。"""
        assert _calc_bonus(10_000) == 0

    def test_bonus_500_yuan(self):
        """充值 50_000 分（500元）→ 赠 5_000 分（≥50元）。"""
        assert _calc_bonus(50_000) == 5_000

    def test_bonus_1000_yuan(self):
        """充值 100_000 分（1000元）→ 赠 15_000 分（≥150元）。"""
        assert _calc_bonus(100_000) == 15_000


# ─── HTTP 路由测试 ────────────────────────────────────────────────────────────


class TestGetStoredValue:
    @pytest.mark.asyncio
    async def test_get_stored_value_not_found_creates_account(self, client: AsyncClient):
        """不存在的 member_id → 自动创建账户并返回 balance=0。"""
        mock_db = _make_db()
        # 第一次 execute（SELECT）返回空 → 触发 INSERT（创建账户）
        # 第二次 execute（SET LOCAL）直接返回
        # 第三次 execute（SELECT transactions）返回空列表
        select_no_row = _exec_result_with_row(None)
        select_txn_empty = _exec_result_multi([])

        mock_db.execute.side_effect = [
            MagicMock(),             # SET LOCAL app.tenant_id
            select_no_row,           # SELECT stored_value_accounts → 不存在
            MagicMock(),             # INSERT 新账户
            MagicMock(),             # commit（账户创建）
            select_txn_empty,        # SELECT stored_value_transactions
        ]

        with _DBOverride(mock_db):
            resp = await client.get(
                f"/api/v1/members/{MEMBER_A}/stored-value",
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["balance_fen"] == 0
        assert data["data"]["member_id"] == MEMBER_A


class TestRecharge:
    @pytest.mark.asyncio
    async def test_recharge_100_yuan_no_bonus(self, client: AsyncClient):
        """充值 10_000 分（100元）→ bonus_fen=0，balance 增加 10_000。"""
        mock_db = _make_db()
        account = _make_account(balance=0)

        mock_db.execute.side_effect = [
            MagicMock(),                         # SET LOCAL
            _exec_result_with_row(account),      # SELECT account（已存在）
            MagicMock(),                         # UPDATE balance
            MagicMock(),                         # INSERT transaction
        ]

        body = {
            "amount_fen": 10_000,
            "payment_method": "wechat",
            "operator_id": "op-001",
        }
        with _DBOverride(mock_db):
            resp = await client.post(
                f"/api/v1/members/{MEMBER_A}/stored-value/recharge",
                json=body,
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["bonus_fen"] == 0
        assert data["data"]["amount_fen"] == 10_000
        assert data["data"]["balance_after_fen"] == 10_000

    @pytest.mark.asyncio
    async def test_recharge_500_yuan_with_bonus(self, client: AsyncClient):
        """充值 50_000 分（500元）→ bonus_fen=5_000，balance_after=55_000。"""
        mock_db = _make_db()
        account = _make_account(balance=0)

        mock_db.execute.side_effect = [
            MagicMock(),
            _exec_result_with_row(account),
            MagicMock(),
            MagicMock(),
        ]

        body = {
            "amount_fen": 50_000,
            "payment_method": "alipay",
            "operator_id": "op-001",
        }
        with _DBOverride(mock_db):
            resp = await client.post(
                f"/api/v1/members/{MEMBER_A}/stored-value/recharge",
                json=body,
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["bonus_fen"] == 5_000
        assert data["data"]["balance_after_fen"] == 55_000
        assert data["data"]["total_credited_fen"] == 55_000

    @pytest.mark.asyncio
    async def test_recharge_1000_yuan_with_bonus(self, client: AsyncClient):
        """充值 100_000 分（1000元）→ bonus_fen=15_000，balance_after=115_000。"""
        mock_db = _make_db()
        account = _make_account(balance=0)

        mock_db.execute.side_effect = [
            MagicMock(),
            _exec_result_with_row(account),
            MagicMock(),
            MagicMock(),
        ]

        body = {
            "amount_fen": 100_000,
            "payment_method": "cash",
            "operator_id": "op-002",
        }
        with _DBOverride(mock_db):
            resp = await client.post(
                f"/api/v1/members/{MEMBER_A}/stored-value/recharge",
                json=body,
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["bonus_fen"] == 15_000
        assert data["data"]["balance_after_fen"] == 115_000

    @pytest.mark.asyncio
    async def test_recharge_invalid_payment_method(self, client: AsyncClient):
        """payment_method 不在白名单 → HTTP 422。"""
        body = {
            "amount_fen": 10_000,
            "payment_method": "bitcoin",
            "operator_id": "op-001",
        }
        resp = await client.post(
            f"/api/v1/members/{MEMBER_A}/stored-value/recharge",
            json=body,
            headers=TENANT_HEADERS,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_recharge_too_small_amount(self, client: AsyncClient):
        """充值 50 分（< 100分最低限）→ HTTP 422。"""
        body = {
            "amount_fen": 50,
            "payment_method": "cash",
            "operator_id": "op-001",
        }
        resp = await client.post(
            f"/api/v1/members/{MEMBER_A}/stored-value/recharge",
            json=body,
            headers=TENANT_HEADERS,
        )
        assert resp.status_code == 422


class TestConsume:
    @pytest.mark.asyncio
    async def test_consume_reduces_balance(self, client: AsyncClient):
        """先设余额 50_000，消费 10_000 → balance_after=40_000，success=True。"""
        mock_db = _make_db()
        account = _make_account(balance=50_000, frozen=0)

        mock_db.execute.side_effect = [
            MagicMock(),
            _exec_result_with_row(account),
            MagicMock(),
            MagicMock(),
        ]

        body = {
            "amount_fen": 10_000,
            "order_id": "order-consume-001",
            "operator_id": "op-001",
        }
        with _DBOverride(mock_db):
            resp = await client.post(
                f"/api/v1/members/{MEMBER_A}/stored-value/consume",
                json=body,
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["success"] is True
        assert data["data"]["balance_after_fen"] == 40_000
        assert data["data"]["insufficient_fen"] == 0

    @pytest.mark.asyncio
    async def test_consume_insufficient_balance(self, client: AsyncClient):
        """消费金额 > 余额 → success=False，返回 insufficient_fen。"""
        mock_db = _make_db()
        # 余额 5_000，消费 10_000
        account = _make_account(balance=5_000, frozen=0)

        mock_db.execute.side_effect = [
            MagicMock(),
            _exec_result_with_row(account),
        ]

        body = {
            "amount_fen": 10_000,
            "order_id": "order-consume-002",
            "operator_id": "op-001",
        }
        with _DBOverride(mock_db):
            resp = await client.post(
                f"/api/v1/members/{MEMBER_A}/stored-value/consume",
                json=body,
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["success"] is False
        assert data["data"]["insufficient_fen"] == 5_000   # 10_000 - 5_000

    @pytest.mark.asyncio
    async def test_consume_exactly_balance(self, client: AsyncClient):
        """消费金额 == 余额 → success=True，balance_after=0。"""
        mock_db = _make_db()
        account = _make_account(balance=20_000, frozen=0)

        mock_db.execute.side_effect = [
            MagicMock(),
            _exec_result_with_row(account),
            MagicMock(),
            MagicMock(),
        ]

        body = {
            "amount_fen": 20_000,
            "order_id": "order-exact-001",
            "operator_id": "op-001",
        }
        with _DBOverride(mock_db):
            resp = await client.post(
                f"/api/v1/members/{MEMBER_A}/stored-value/consume",
                json=body,
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["success"] is True
        assert data["data"]["balance_after_fen"] == 0

    @pytest.mark.asyncio
    async def test_consume_zero_amount_rejected(self, client: AsyncClient):
        """消费金额 = 0 → HTTP 422（field validator 拒绝）。"""
        body = {
            "amount_fen": 0,
            "order_id": "order-zero",
            "operator_id": "op-001",
        }
        resp = await client.post(
            f"/api/v1/members/{MEMBER_A}/stored-value/consume",
            json=body,
            headers=TENANT_HEADERS,
        )
        assert resp.status_code == 422


class TestRefund:
    @pytest.mark.asyncio
    async def test_refund_to_stored_value_increases_balance(self, client: AsyncClient):
        """退款到储值 → balance_after 增加 refunded_fen。"""
        mock_db = _make_db()

        txn_id = str(uuid.uuid4())
        account_id = str(uuid.uuid4())

        # 模拟原始消费流水
        orig_txn = MagicMock()
        orig_txn.__getitem__ = lambda self, k: {
            "id": txn_id,
            "account_id": account_id,
            "amount_fen": -20_000,   # 消费是负数
            "type": "consume",
        }[k]

        # 模拟账户
        acc = MagicMock()
        acc.__getitem__ = lambda self, k: {
            "balance_fen": 30_000,
        }[k]

        # 原始流水查询
        orig_result = MagicMock()
        orig_mapping = MagicMock()
        orig_mapping.first = MagicMock(return_value=orig_txn)
        orig_result.mappings = MagicMock(return_value=orig_mapping)

        # 账户查询
        acc_result = MagicMock()
        acc_mapping = MagicMock()
        acc_mapping.first = MagicMock(return_value=acc)
        acc_result.mappings = MagicMock(return_value=acc_mapping)

        mock_db.execute.side_effect = [
            MagicMock(),       # SET LOCAL
            orig_result,       # SELECT stored_value_transactions
            acc_result,        # SELECT stored_value_accounts
            MagicMock(),       # UPDATE balance
            MagicMock(),       # INSERT refund transaction
        ]

        body = {
            "transaction_id": txn_id,
            "amount_fen": 10_000,
            "reason": "顾客退菜",
            "operator_id": "op-001",
        }
        with _DBOverride(mock_db):
            resp = await client.post(
                f"/api/v1/members/{MEMBER_A}/stored-value/refund",
                json=body,
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["refunded_fen"] == 10_000
        assert data["data"]["balance_after_fen"] == 40_000   # 30_000 + 10_000

    @pytest.mark.asyncio
    async def test_refund_transaction_not_found(self, client: AsyncClient):
        """退款时原始流水不存在 → HTTP 404。"""
        mock_db = _make_db()

        # 查询原始流水返回 None
        no_row = MagicMock()
        no_row_mapping = MagicMock()
        no_row_mapping.first = MagicMock(return_value=None)
        no_row.mappings = MagicMock(return_value=no_row_mapping)

        mock_db.execute.side_effect = [
            MagicMock(),   # SET LOCAL
            no_row,        # SELECT transaction → 不存在
        ]

        body = {
            "transaction_id": str(uuid.uuid4()),
            "amount_fen": 5_000,
            "reason": "测试退款",
            "operator_id": "op-001",
        }
        with _DBOverride(mock_db):
            resp = await client.post(
                f"/api/v1/members/{MEMBER_A}/stored-value/refund",
                json=body,
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_refund_exceeds_original_amount(self, client: AsyncClient):
        """退款金额 > 原消费金额 → HTTP 400。"""
        mock_db = _make_db()
        txn_id = str(uuid.uuid4())
        account_id = str(uuid.uuid4())

        orig_txn = MagicMock()
        orig_txn.__getitem__ = lambda self, k: {
            "id": txn_id,
            "account_id": account_id,
            "amount_fen": -5_000,   # 原消费 5_000
            "type": "consume",
        }[k]

        orig_result = MagicMock()
        orig_mapping = MagicMock()
        orig_mapping.first = MagicMock(return_value=orig_txn)
        orig_result.mappings = MagicMock(return_value=orig_mapping)

        mock_db.execute.side_effect = [
            MagicMock(),
            orig_result,
        ]

        body = {
            "transaction_id": txn_id,
            "amount_fen": 10_000,   # 超过原消费 5_000
            "reason": "超额退款测试",
            "operator_id": "op-001",
        }
        with _DBOverride(mock_db):
            resp = await client.post(
                f"/api/v1/members/{MEMBER_A}/stored-value/refund",
                json=body,
                headers=TENANT_HEADERS,
            )

        assert resp.status_code == 400
