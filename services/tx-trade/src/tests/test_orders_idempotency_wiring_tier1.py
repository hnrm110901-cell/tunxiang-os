"""Tier 1 测试 — orders.py 路由 _check_idempotency_cache helper

A1-R3 路由集成层测试：验证 settle_order / create_payment 路由用的
_check_idempotency_cache helper 在 4 个分支行为正确：

  1. 空 X-Idempotency-Key → 返回 (None, '', route_path)，不发 DB 调用 → 路由按原逻辑跑
  2. cache 未命中 → 返回 (None, request_hash, route_path)，路由继续业务
  3. cache 命中 → 返回 (cached_body, request_hash, route_path)，路由 short-circuit
  4. 同 key 不同 body（hash 冲突）→ raise HTTPException(422 IDEMPOTENCY_KEY_CONFLICT)

P1 修复（PR #111 chatgpt-codex-connector review 第 2 条）：
  helper 现在接 route_template + order_id 两个参数，内部 .format(order_id=...)
  得到 concrete route_path 用于 advisory_lock + cache PK + request_hash。
  这样即便客户端 bug 让两个不同 order 共用同一 X-Idempotency-Key（典型场景：
  settle 空 body + 同 key），cache 也按 order 隔离，不会跨 order 串扰。

完整 TestClient 端到端测试（含 saga 双扣防护）需要真实 PG fixture，安排在
Sprint H DEMO 阶段做。本测试覆盖 helper 行为契约 + P1 修复回归保护。
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.api.orders import (
    _ROUTE_PAYMENT_TEMPLATE,
    _ROUTE_SETTLE_TEMPLATE,
    _check_idempotency_cache,
    _concrete_route,
)
from src.services.api_idempotency import compute_request_hash

_TENANT = "11111111-aaaa-aaaa-aaaa-111111111111"
_ORDER_A = "55555555-eeee-eeee-eeee-555555555555"
_ORDER_B = "66666666-ffff-ffff-ffff-666666666666"
_KEY_SETTLE = f"settle:{_ORDER_A}"


def _mk_db_for_lookup(*, row=None) -> AsyncMock:
    """构造 db mock — set_config / advisory_lock / SELECT 都成功。"""
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql = str(query)
        if "set_config" in sql:
            return MagicMock()
        if "pg_advisory_xact_lock" in sql:
            return MagicMock()
        if "api_idempotency_cache" in sql and "SELECT" in sql:
            r = MagicMock()
            r.first.return_value = row
            return r
        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    db.commit = AsyncMock()
    return db


# ─── 0. _concrete_route helper 单元测试（P1 修复核心） ────────────────────


def test_concrete_route_injects_order_id():
    """模板 → 含具体 order_id 的路径。"""
    path = _concrete_route(_ROUTE_SETTLE_TEMPLATE, _ORDER_A)
    assert _ORDER_A in path
    assert "{order_id}" not in path
    assert path == f"/api/v1/trade/orders/{_ORDER_A}/settle"


def test_concrete_route_different_orders_produce_different_paths():
    """两个不同 order_id → 不同 concrete route_path（cache 隔离的基础）。

    P1 修复回归保护：原代码 route_path 是 templated（含 {order_id} 字面量），
    所以 order A 和 order B 的 cache PK 相同 → 同 X-Idempotency-Key 跨 order 串扰。
    修复后 concrete route_path 包含实际 UUID，cache PK 自然按 order 隔离。
    """
    path_a = _concrete_route(_ROUTE_SETTLE_TEMPLATE, _ORDER_A)
    path_b = _concrete_route(_ROUTE_SETTLE_TEMPLATE, _ORDER_B)
    assert path_a != path_b
    assert _ORDER_A in path_a
    assert _ORDER_B in path_b


# ─── 1. 空 key 路径 ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_key_returns_none_and_skips_db():
    """X-Idempotency-Key header 缺失 → 返回 (None, '', route_path)，零 DB 调用 → 路由按原逻辑跑。

    向后兼容：未升级的 POS 客户端仍能正常调 settle/payment。
    """
    db = _mk_db_for_lookup(row=None)

    cached_body, request_hash, route_path = await _check_idempotency_cache(
        db,
        tenant_id=_TENANT,
        idempotency_key=None,
        route_template=_ROUTE_SETTLE_TEMPLATE,
        order_id=_ORDER_A,
        body_for_hash="",
    )
    assert cached_body is None
    assert request_hash == ""
    # route_path 在空 key 路径下也已计算好，便于调用方一致使用
    assert route_path == f"/api/v1/trade/orders/{_ORDER_A}/settle"
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_empty_string_key_treated_same_as_none():
    """空字符串 key 也应当是 no-op（client 传了 header 但值是 ''）。"""
    db = _mk_db_for_lookup(row=None)

    cached_body, request_hash, route_path = await _check_idempotency_cache(
        db,
        tenant_id=_TENANT,
        idempotency_key="",
        route_template=_ROUTE_SETTLE_TEMPLATE,
        order_id=_ORDER_A,
        body_for_hash="",
    )
    assert cached_body is None
    assert request_hash == ""
    assert _ORDER_A in route_path
    db.execute.assert_not_called()


# ─── 2. cache 未命中路径 ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_miss_returns_none_with_hash():
    """首次请求 → cache 未命中 → 返回 (None, hash, route_path)。"""
    db = _mk_db_for_lookup(row=None)

    cached_body, request_hash, route_path = await _check_idempotency_cache(
        db,
        tenant_id=_TENANT,
        idempotency_key=_KEY_SETTLE,
        route_template=_ROUTE_SETTLE_TEMPLATE,
        order_id=_ORDER_A,
        body_for_hash="",
    )
    assert cached_body is None
    assert len(request_hash) == 64  # SHA256 hex
    assert _ORDER_A in route_path
    # 必须发起 advisory_lock + SELECT
    sqls = [str(c.args[0]) for c in db.execute.await_args_list]
    assert any("pg_advisory_xact_lock" in s for s in sqls)
    assert any("api_idempotency_cache" in s and "SELECT" in s for s in sqls)


# ─── 3. cache 命中路径 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_hit_returns_cached_body():
    """重试请求 → cache 命中 → 返回 (cached_body, hash, route_path)，路由 short-circuit。"""
    cached_response = {"ok": True, "data": {"order_no": "X1", "final_amount_fen": 88800}, "error": None}
    concrete_path = f"/api/v1/trade/orders/{_ORDER_A}/settle"
    request_hash = compute_request_hash("POST", concrete_path, "")
    import json

    cached_body_str = json.dumps(cached_response, ensure_ascii=False)
    db = _mk_db_for_lookup(row=(200, cached_body_str, "completed", request_hash, datetime.now(timezone.utc)))

    cached_body, returned_hash, route_path = await _check_idempotency_cache(
        db,
        tenant_id=_TENANT,
        idempotency_key=_KEY_SETTLE,
        route_template=_ROUTE_SETTLE_TEMPLATE,
        order_id=_ORDER_A,
        body_for_hash="",
    )
    assert cached_body == cached_response
    assert returned_hash == request_hash
    assert route_path == concrete_path


# ─── 3b. P1 修复回归保护：跨 order 同 key 不串扰 ───────────────────────────


@pytest.mark.asyncio
async def test_p1_cross_order_same_key_does_not_collide():
    """同 X-Idempotency-Key 在两个不同 order 上 → request_hash / route_path 必须不同。

    P1 修复回归保护：客户端 bug 误用同 key 调 order_A 和 order_B 时，server
    必须按 order 隔离 cache（不能把 A 的响应返回给 B 的请求）。

    本测试不直接断言 cache 命中行为（需要 stateful mock），而是验证
    helper 的关键中间产物（request_hash + route_path）按 order 隔离。
    """
    db_a = _mk_db_for_lookup(row=None)
    db_b = _mk_db_for_lookup(row=None)

    _, hash_a, path_a = await _check_idempotency_cache(
        db_a,
        tenant_id=_TENANT,
        idempotency_key="reused-by-bug",
        route_template=_ROUTE_SETTLE_TEMPLATE,
        order_id=_ORDER_A,
        body_for_hash="",
    )
    _, hash_b, path_b = await _check_idempotency_cache(
        db_b,
        tenant_id=_TENANT,
        idempotency_key="reused-by-bug",
        route_template=_ROUTE_SETTLE_TEMPLATE,
        order_id=_ORDER_B,
        body_for_hash="",
    )
    assert path_a != path_b, "concrete route_path 必须按 order 隔离"
    assert hash_a != hash_b, "request_hash 必须按 order 隔离（含 route_path）"
    assert _ORDER_A in path_a and _ORDER_B in path_b


# ─── 4. hash 冲突路径 ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hash_conflict_raises_http_422():
    """同 key 同 order 但 body 不同 → raise HTTPException(422 IDEMPOTENCY_KEY_CONFLICT)。"""
    cached_hash = "different_hash_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    db = _mk_db_for_lookup(row=(200, "{}", "completed", cached_hash, datetime.now(timezone.utc)))

    with pytest.raises(HTTPException) as exc_info:
        await _check_idempotency_cache(
            db,
            tenant_id=_TENANT,
            idempotency_key=_KEY_SETTLE,
            route_template=_ROUTE_PAYMENT_TEMPLATE,
            order_id=_ORDER_A,
            body_for_hash='{"method":"wechat","amount_fen":88800}',
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "IDEMPOTENCY_KEY_CONFLICT"
    assert "idempotency_key" in exc_info.value.detail["message"]


# ─── 5. body_for_hash 一致性（payment 路由用 model_dump_json） ─────────────


def test_payment_body_hash_uses_pydantic_model_dump_json():
    """create_payment 用 req.model_dump_json() → 字段顺序固定 → hash 稳定。"""
    concrete_path = f"/api/v1/trade/orders/{_ORDER_A}/payments"
    body_a = '{"method":"wechat","amount_fen":88800,"trade_no":null,"credit_account_name":null}'
    h_a = compute_request_hash("POST", concrete_path, body_a)
    h_b = compute_request_hash("POST", concrete_path, body_a)
    assert h_a == h_b
    body_changed = '{"method":"wechat","amount_fen":88801,"trade_no":null,"credit_account_name":null}'
    h_c = compute_request_hash("POST", concrete_path, body_changed)
    assert h_a != h_c


# ─── 6. settle_order 与 create_payment 路由模板不同 → 不互锁 ────────────


def test_route_path_templates_distinct():
    """settle 与 payment 路由模板必须不同 → 同 key + 同 order 在两路由上独立 cache。"""
    assert _ROUTE_SETTLE_TEMPLATE != _ROUTE_PAYMENT_TEMPLATE
    assert "settle" in _ROUTE_SETTLE_TEMPLATE
    assert "payments" in _ROUTE_PAYMENT_TEMPLATE


def test_concrete_routes_distinct_for_settle_vs_payment_same_order():
    """同 order_id 在 settle 与 payment 模板下产 → concrete path 必须不同。"""
    settle_path = _concrete_route(_ROUTE_SETTLE_TEMPLATE, _ORDER_A)
    payment_path = _concrete_route(_ROUTE_PAYMENT_TEMPLATE, _ORDER_A)
    assert settle_path != payment_path
    assert settle_path.endswith("/settle")
    assert payment_path.endswith("/payments")
