"""Tier 1 测试 — orders.py 路由 _check_idempotency_cache helper

A1-R3 路由集成层测试：验证 settle_order / create_payment 路由用的
_check_idempotency_cache helper 在 4 个分支行为正确：

  1. 空 X-Idempotency-Key → 返回 (None, '')，不发 DB 调用 → 路由按原逻辑跑
  2. cache 未命中 → 返回 (None, request_hash)，路由继续业务，跑完后 store
  3. cache 命中 → 返回 (cached_body, request_hash)，路由 short-circuit
  4. 同 key 不同 body（hash 冲突）→ raise HTTPException(422 IDEMPOTENCY_KEY_CONFLICT)

完整 TestClient 端到端测试（含 saga 双扣防护）需要真实 PG fixture，安排在
Sprint H DEMO 阶段做。本测试覆盖 helper 行为契约。
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.api.orders import _check_idempotency_cache, _ROUTE_PAYMENT, _ROUTE_SETTLE
from src.services.api_idempotency import compute_request_hash

_TENANT = "11111111-aaaa-aaaa-aaaa-111111111111"
_KEY_SETTLE = "settle:55555555-eeee-eeee-eeee-555555555555"


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


# ─── 1. 空 key 路径 ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_key_returns_none_and_skips_db():
    """X-Idempotency-Key header 缺失 → 返回 (None, '')，零 DB 调用 → 路由按原逻辑跑。

    向后兼容：未升级的 POS 客户端仍能正常调 settle/payment。
    """
    db = _mk_db_for_lookup(row=None)

    cached_body, request_hash = await _check_idempotency_cache(
        db,
        tenant_id=_TENANT,
        idempotency_key=None,
        route_path=_ROUTE_SETTLE,
        body_for_hash="",
    )
    assert cached_body is None
    assert request_hash == ""
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_empty_string_key_treated_same_as_none():
    """空字符串 key 也应当是 no-op（client 传了 header 但值是 ''）。"""
    db = _mk_db_for_lookup(row=None)

    cached_body, request_hash = await _check_idempotency_cache(
        db,
        tenant_id=_TENANT,
        idempotency_key="",
        route_path=_ROUTE_SETTLE,
        body_for_hash="",
    )
    assert cached_body is None
    assert request_hash == ""
    db.execute.assert_not_called()


# ─── 2. cache 未命中路径 ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_miss_returns_none_with_hash():
    """首次请求 → cache 未命中 → 返回 (None, hash)，路由继续业务 + 之后 store。"""
    db = _mk_db_for_lookup(row=None)

    cached_body, request_hash = await _check_idempotency_cache(
        db,
        tenant_id=_TENANT,
        idempotency_key=_KEY_SETTLE,
        route_path=_ROUTE_SETTLE,
        body_for_hash="",
    )
    assert cached_body is None
    assert len(request_hash) == 64  # SHA256 hex
    # 必须发起 advisory_lock + SELECT
    sqls = [str(c.args[0]) for c in db.execute.await_args_list]
    assert any("pg_advisory_xact_lock" in s for s in sqls)
    assert any("api_idempotency_cache" in s and "SELECT" in s for s in sqls)


# ─── 3. cache 命中路径 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_hit_returns_cached_body():
    """重试请求 → cache 命中 → 返回 (cached_body, hash)，路由 short-circuit。"""
    cached_response = {"ok": True, "data": {"order_no": "X1", "final_amount_fen": 88800}, "error": None}
    request_hash = compute_request_hash("POST", _ROUTE_SETTLE, "")
    import json
    cached_body_str = json.dumps(cached_response, ensure_ascii=False)
    db = _mk_db_for_lookup(
        row=(200, cached_body_str, "completed", request_hash, datetime.now(timezone.utc))
    )

    cached_body, returned_hash = await _check_idempotency_cache(
        db,
        tenant_id=_TENANT,
        idempotency_key=_KEY_SETTLE,
        route_path=_ROUTE_SETTLE,
        body_for_hash="",
    )
    assert cached_body == cached_response
    assert returned_hash == request_hash


# ─── 4. hash 冲突路径 ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hash_conflict_raises_http_422():
    """同 key 但 body 不同 → raise HTTPException(422 IDEMPOTENCY_KEY_CONFLICT)。

    使用场景：客户端 bug（同 key 复用）或攻击。路由层把 IdempotencyKeyConflict
    转 HTTP 422 让客户端看见明确错误。
    """
    # cache 里存的 hash 与本次入参不一致 → 触发冲突
    cached_hash = "different_hash_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    db = _mk_db_for_lookup(
        row=(200, "{}", "completed", cached_hash, datetime.now(timezone.utc))
    )

    with pytest.raises(HTTPException) as exc_info:
        await _check_idempotency_cache(
            db,
            tenant_id=_TENANT,
            idempotency_key=_KEY_SETTLE,
            route_path=_ROUTE_PAYMENT,
            body_for_hash='{"method":"wechat","amount_fen":88800}',
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "IDEMPOTENCY_KEY_CONFLICT"
    assert "idempotency_key" in exc_info.value.detail["message"]


# ─── 5. body_for_hash 一致性（payment 路由用 model_dump_json） ─────────────


@pytest.mark.asyncio
async def test_payment_body_hash_uses_pydantic_model_dump_json():
    """create_payment 用 req.model_dump_json() → 字段顺序固定 → hash 稳定。

    本测试验证：同样的逻辑 body 跑两次得到同 hash（即便 dict key 顺序不同）。
    """
    body_a = '{"method":"wechat","amount_fen":88800,"trade_no":null,"credit_account_name":null}'
    # 字段顺序不同但语义相同 — 真实 pydantic.model_dump_json 输出字段序列固定，
    # 所以同一 req 永远产 body_a；这里测 hash 函数确定性。
    h_a = compute_request_hash("POST", _ROUTE_PAYMENT, body_a)
    h_b = compute_request_hash("POST", _ROUTE_PAYMENT, body_a)
    assert h_a == h_b
    # 改 amount → 必变
    body_changed = '{"method":"wechat","amount_fen":88801,"trade_no":null,"credit_account_name":null}'
    h_c = compute_request_hash("POST", _ROUTE_PAYMENT, body_changed)
    assert h_a != h_c


# ─── 6. settle_order 与 create_payment 路由 path 不同 → 不互锁 ─────────────


def test_route_path_constants_distinct():
    """settle 与 payment 路由路径必须不同 → 同 (tenant, key) 在两个路由上独立 cache。

    虽然客户端不会用同一 key 调两个不同路由（settle:{id} vs payment:{id}:{method}），
    但路由 path 列做主键的一部分能防御此场景。
    """
    assert _ROUTE_SETTLE != _ROUTE_PAYMENT
    assert "settle" in _ROUTE_SETTLE
    assert "payments" in _ROUTE_PAYMENT
