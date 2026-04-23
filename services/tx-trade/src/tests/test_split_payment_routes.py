"""分摊结账路由测试 — split_payment_routes.py DB版

覆盖场景（共 8 个）：
1. POST /api/v1/orders/{order_id}/split-pay/init       — 正常初始化，订单存在，无历史分摊 → 200，splits 列表
2. POST /api/v1/orders/{order_id}/split-pay/init       — 订单不存在 → 404
3. POST /api/v1/orders/{order_id}/split-pay/init       — 已存在进行中分摊 → 400
4. GET  /api/v1/orders/{order_id}/split-pay            — 正常查询，返回 2 条记录 → 200，splits 长度=2
5. GET  /api/v1/orders/{order_id}/split-pay            — 无分摊记录 → 200，splits 为空列表
6. POST /api/v1/orders/{order_id}/split-pay/{no}/settle — UPDATE 成功，剩余未付=0 → 200，all_paid=True
7. POST /api/v1/orders/{order_id}/split-pay/{no}/settle — UPDATE RETURNING 无行 → 404
8. POST /api/v1/orders/{order_id}/split-pay/{no}/settle — UPDATE 成功，剩余未付=1 → 200，all_paid=False
"""

import os
import sys
import types
import uuid

# ─── 路径准备 ─────────────────────────────────────────────────────────────────
_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR = os.path.join(_TESTS_DIR, "..")
_ROOT_DIR = os.path.abspath(os.path.join(_TESTS_DIR, "..", "..", "..", ".."))

for _p in [_SRC_DIR, _ROOT_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ─── 建立 src 包层级 ──────────────────────────────────────────────────────────


def _ensure_pkg(name: str, path: str) -> None:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod


_ensure_pkg("src", _SRC_DIR)
_ensure_pkg("src.api", os.path.join(_SRC_DIR, "api"))

# ─── 导入 ─────────────────────────────────────────────────────────────────────

from unittest.mock import AsyncMock, MagicMock  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from shared.ontology.src.database import get_db  # noqa: E402
from src.api.split_payment_routes import router  # type: ignore[import]  # noqa: E402

# ─── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = "11111111-1111-1111-1111-111111111111"
ORDER_ID = str(uuid.uuid4())
SPLIT_ID = str(uuid.uuid4())

HEADERS = {"X-Tenant-ID": TENANT_ID}

# ─── 工具函数 ──────────────────────────────────────────────────────────────────


def _make_mock_db() -> AsyncMock:
    """创建最小化的 mock AsyncSession。"""
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _fake_row(**attrs) -> MagicMock:
    """创建带属性访问的假行对象。"""
    row = MagicMock()
    for k, v in attrs.items():
        setattr(row, k, v)
    return row


def _make_exec_result(
    fetchone=None,
    fetchall=None,
    rowcount: int = 0,
) -> MagicMock:
    """构造 db.execute() 返回的 mock result 对象。"""
    result = MagicMock()
    result.fetchone.return_value = fetchone
    result.fetchall.return_value = fetchall if fetchall is not None else []
    result.rowcount = rowcount
    return result


def _make_app_with_db(db: AsyncMock) -> FastAPI:
    """创建绑定了 mock DB 的独立测试 app。"""
    app = FastAPI()
    app.include_router(router)

    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    return app


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 1: init — 正常初始化成功
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_init_split_success():
    """订单存在（final_amount_fen=10000），无历史分摊，初始化 2 份 → 200，返回 splits 列表。"""
    db = _make_mock_db()

    # 执行顺序：
    #   [0] set_config
    #   [1] SELECT orders → 返回订单行
    #   [2] SELECT order_split_payments → 无历史记录
    #   [3] INSERT split_no=1 RETURNING
    #   [4] INSERT split_no=2 RETURNING

    order_row = _fake_row(final_amount_fen=10000)
    insert_row_1 = _fake_row(split_no=1, amount_fen=5000, status="pending")
    insert_row_2 = _fake_row(split_no=2, amount_fen=5000, status="pending")

    db.execute = AsyncMock(
        side_effect=[
            _make_exec_result(),  # set_config
            _make_exec_result(fetchone=order_row),  # SELECT orders
            _make_exec_result(fetchall=[]),  # SELECT existing splits
            _make_exec_result(fetchone=insert_row_1),  # INSERT split 1
            _make_exec_result(fetchone=insert_row_2),  # INSERT split 2
        ]
    )

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        f"/api/v1/orders/{ORDER_ID}/split-pay/init",
        json={"total_splits": 2},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["order_id"] == ORDER_ID
    assert data["total_splits"] == 2
    assert data["total_fen"] == 10000
    assert len(data["splits"]) == 2
    assert data["splits"][0]["split_no"] == 1
    assert data["splits"][0]["amount_fen"] == 5000
    assert data["splits"][0]["status"] == "pending"
    db.commit.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 2: init — 订单不存在 → 404
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_init_split_order_not_found():
    """SELECT orders 返回 None → 404 订单不存在。"""
    db = _make_mock_db()

    db.execute = AsyncMock(
        side_effect=[
            _make_exec_result(),  # set_config
            _make_exec_result(fetchone=None),  # SELECT orders → 空
        ]
    )

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        f"/api/v1/orders/{ORDER_ID}/split-pay/init",
        json={"total_splits": 2},
        headers=HEADERS,
    )

    assert resp.status_code == 404
    assert "订单不存在" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 3: init — 已存在进行中分摊 → 400
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_init_split_duplicate():
    """SELECT order_split_payments 返回 status=pending 的记录 → 400 已存在进行中的分摊。"""
    db = _make_mock_db()

    order_row = _fake_row(final_amount_fen=10000)
    existing_1 = _fake_row(status="pending")  # 非 cancelled，触发冲突检测

    db.execute = AsyncMock(
        side_effect=[
            _make_exec_result(),  # set_config
            _make_exec_result(fetchone=order_row),  # SELECT orders
            _make_exec_result(fetchall=[existing_1]),  # SELECT existing → 有 pending 记录
        ]
    )

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        f"/api/v1/orders/{ORDER_ID}/split-pay/init",
        json={"total_splits": 3},
        headers=HEADERS,
    )

    assert resp.status_code == 400
    assert "已存在进行中的分摊" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 4: list — 正常查询，返回 2 条记录
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_list_splits_success():
    """SELECT 返回 2 条分摊记录 → 200，data.splits 长度=2。"""
    db = _make_mock_db()

    row1 = _fake_row(
        id=uuid.UUID(SPLIT_ID),
        split_no=1,
        amount_fen=5000,
        payer_name="",
        status="paid",
        tenant_id=TENANT_ID,
        created_at=None,
    )
    row2 = _fake_row(
        id=uuid.UUID(SPLIT_ID),
        split_no=2,
        amount_fen=5000,
        payer_name="",
        status="pending",
        tenant_id=TENANT_ID,
        created_at=None,
    )

    db.execute = AsyncMock(
        side_effect=[
            _make_exec_result(),  # set_config
            _make_exec_result(fetchall=[row1, row2]),  # SELECT order_split_payments
        ]
    )

    client = TestClient(_make_app_with_db(db))
    resp = client.get(
        f"/api/v1/orders/{ORDER_ID}/split-pay",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["order_id"] == ORDER_ID
    assert data["total_splits"] == 2
    assert data["paid_count"] == 1
    assert data["all_paid"] is False
    assert len(data["splits"]) == 2


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 5: list — 无分摊记录 → 200，splits 为空列表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_list_splits_empty():
    """SELECT 返回空 → 200，splits=[]，total_splits=0，all_paid=False。"""
    db = _make_mock_db()

    db.execute = AsyncMock(
        side_effect=[
            _make_exec_result(),  # set_config
            _make_exec_result(fetchall=[]),  # SELECT → 空
        ]
    )

    client = TestClient(_make_app_with_db(db))
    resp = client.get(
        f"/api/v1/orders/{ORDER_ID}/split-pay",
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["splits"] == []
    assert data["total_splits"] == 0
    assert data["all_paid"] is False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 6: settle — UPDATE 成功，剩余未付=0 → 200，all_paid=True
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_settle_split_success():
    """UPDATE RETURNING 返回1行，COUNT 未付剩余=0 → 200，all_paid=True，order_closed=True。"""
    db = _make_mock_db()

    updated_row = _fake_row(id=SPLIT_ID)
    unpaid_row = _fake_row(cnt=0)

    db.execute = AsyncMock(
        side_effect=[
            _make_exec_result(),  # set_config
            _make_exec_result(fetchone=updated_row),  # UPDATE RETURNING
            _make_exec_result(fetchone=unpaid_row),  # SELECT COUNT unpaid
        ]
    )

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        f"/api/v1/orders/{ORDER_ID}/split-pay/1/settle",
        json={"payment_method": "wechat"},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["order_id"] == ORDER_ID
    assert data["split_no"] == 1
    assert data["status"] == "paid"
    assert data["payment_method"] == "wechat"
    assert data["order_closed"] is True
    db.commit.assert_awaited_once()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 7: settle — UPDATE RETURNING 无行 → 404
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_settle_split_not_found():
    """UPDATE RETURNING fetchone()=None → 404 分摊记录不存在。"""
    db = _make_mock_db()

    db.execute = AsyncMock(
        side_effect=[
            _make_exec_result(),  # set_config
            _make_exec_result(fetchone=None),  # UPDATE RETURNING → 无命中
        ]
    )

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        f"/api/v1/orders/{ORDER_ID}/split-pay/9/settle",
        json={"payment_method": "cash"},
        headers=HEADERS,
    )

    assert resp.status_code == 404
    assert "分摊记录不存在" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 场景 8: settle — UPDATE 成功，剩余未付=1 → 200，all_paid=False
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_settle_split_partial():
    """UPDATE 成功，SELECT COUNT 未付=1 → 200，all_paid=False，order_closed=False。"""
    db = _make_mock_db()

    updated_row = _fake_row(id=SPLIT_ID)
    unpaid_row = _fake_row(cnt=1)

    db.execute = AsyncMock(
        side_effect=[
            _make_exec_result(),  # set_config
            _make_exec_result(fetchone=updated_row),  # UPDATE RETURNING
            _make_exec_result(fetchone=unpaid_row),  # SELECT COUNT unpaid → 仍有1份未付
        ]
    )

    client = TestClient(_make_app_with_db(db))
    resp = client.post(
        f"/api/v1/orders/{ORDER_ID}/split-pay/1/settle",
        json={"payment_method": "alipay", "member_id": "mem-001"},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["order_closed"] is False
    assert data["payment_method"] == "alipay"
    assert data["member_id"] == "mem-001"
    db.commit.assert_awaited_once()
