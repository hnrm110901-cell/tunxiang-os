"""Tier 1 测试 — A1-R3 / api_idempotency cache（HTTP 路由级 X-Idempotency-Key）

§19 R-A1-3 修复闭环：apps/web-pos R-补2-1（commit 48aba740）客户端在 replay
时携带 X-Idempotency-Key header；本模块负责服务端拦截 saga 双扣。

徐记 200 桌晚高峰真实场景：
  1. 收银员扫码 → POS 调 /api/v1/trade/orders/{id}/settle
  2. 网络抖动 / tx-trade 偶发 4s 处理延迟 → POS 在 3s 时 soft abort + retry
  3. 同 settle:{orderId} key 第二次到 server
  4. 服务端：第一次仍在跑（已扣会员储值 / 调起第三方支付）
  5. 第二次：advisory_lock 等第一次完成 → 读 cache → 返回原响应（不再扣）

8 个 Tier1 场景：
  T1 compute_request_hash 稳定（徐记 settle body）
  T2 compute_request_hash 变化（body 改 1 byte 即变）
  T3 _compute_lock_id 跨租户不碰撞
  T4 get_cached_response 命中且 hash 一致 → CachedResponse
  T5 get_cached_response hash 不一致 → IdempotencyKeyConflict
  T6 get_cached_response 未命中 → None
  T7 get_cached_response DB 错误 → None (fail-open)
  T8 store_cached_response 失败不抛 (fail-open)
  T9 store_cached_response 序列化包含中文 + 嵌套结构
  T10 acquire_idempotency_lock 空 key → no-op
  T11 acquire_idempotency_lock 超长 key → no-op + warning
  T12 集成场景 — 第一次 store + 第二次 get 同 key 命中
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from src.services.api_idempotency import (
    MAX_KEY_LENGTH,
    CachedResponse,
    IdempotencyKeyConflict,
    _compute_lock_id,
    _compute_request_hash,
    acquire_idempotency_lock,
    compute_request_hash,
    get_cached_response,
    store_cached_response,
)

# ─── 固定测试数据（徐记真实场景） ─────────────────────────────────────────

_TENANT_CHANGSHA = "11111111-aaaa-aaaa-aaaa-111111111111"
_TENANT_SHAOSHAN = "22222222-bbbb-bbbb-bbbb-222222222222"
_ORDER_ID = "55555555-eeee-eeee-eeee-555555555555"
_KEY_SETTLE = f"settle:{_ORDER_ID}"
_KEY_PAYMENT_WECHAT = f"payment:{_ORDER_ID}:wechat"
_ROUTE_SETTLE = "/api/v1/trade/orders/{order_id}/settle"

_REAL_SETTLE_BODY = json.dumps(
    {
        "payments": [
            {"method": "wechat", "amount_fen": 88800, "trade_no": "WX20260425160001"},
        ]
    },
    ensure_ascii=False,
)


# ─── T1-T2: compute_request_hash ──────────────────────────────────────────


def test_t1_request_hash_stable_for_xuji_settle_body():
    """徐记真实 settle body 跑两次哈希一致（确定性）。"""
    h1 = _compute_request_hash("POST", _ROUTE_SETTLE, _REAL_SETTLE_BODY)
    h2 = _compute_request_hash("post", _ROUTE_SETTLE, _REAL_SETTLE_BODY)  # 大小写 method 不影响
    assert h1 == h2
    assert len(h1) == 64
    assert all(c in "0123456789abcdef" for c in h1)


def test_t2_request_hash_changes_when_body_changes():
    """金额改 1 分 → hash 必变（防同 key 不同 body 攻击）。"""
    body1 = json.dumps({"payments": [{"method": "wechat", "amount_fen": 88800}]})
    body2 = json.dumps({"payments": [{"method": "wechat", "amount_fen": 88801}]})
    h1 = _compute_request_hash("POST", _ROUTE_SETTLE, body1)
    h2 = _compute_request_hash("POST", _ROUTE_SETTLE, body2)
    assert h1 != h2

    # 公开 API 等价
    assert compute_request_hash("POST", _ROUTE_SETTLE, body1) == h1


def test_t1b_request_hash_handles_none_and_bytes():
    """body=None 不抛；body=bytes / str 等价。"""
    h_none = _compute_request_hash("POST", _ROUTE_SETTLE, None)
    h_str = _compute_request_hash("POST", _ROUTE_SETTLE, _REAL_SETTLE_BODY)
    h_bytes = _compute_request_hash("POST", _ROUTE_SETTLE, _REAL_SETTLE_BODY.encode())
    assert h_none != h_str
    assert h_str == h_bytes


# ─── T3: _compute_lock_id 跨租户不碰撞 ────────────────────────────────────


def test_t3_lock_id_different_tenants_no_collision():
    """同 key 同 route 但不同租户 → lock_id 不同（避免跨租户串行）。"""
    lock_a = _compute_lock_id(_TENANT_CHANGSHA, _KEY_SETTLE, _ROUTE_SETTLE)
    lock_b = _compute_lock_id(_TENANT_SHAOSHAN, _KEY_SETTLE, _ROUTE_SETTLE)
    assert lock_a != lock_b
    # 都在 BIGINT 范围
    assert -(2**63) <= lock_a < 2**63
    assert -(2**63) <= lock_b < 2**63


def test_t3b_lock_id_same_tenant_same_key_same_route_stable():
    """同 (tenant, key, route) 多次调用 → lock_id 稳定（同一锁）。"""
    lock_1 = _compute_lock_id(_TENANT_CHANGSHA, _KEY_SETTLE, _ROUTE_SETTLE)
    lock_2 = _compute_lock_id(_TENANT_CHANGSHA, _KEY_SETTLE, _ROUTE_SETTLE)
    assert lock_1 == lock_2


def test_t3c_lock_id_different_routes_no_collision():
    """同 key 同租户但不同 route → lock_id 不同（settle 和 payment 不互锁）。"""
    lock_settle = _compute_lock_id(_TENANT_CHANGSHA, _KEY_SETTLE, _ROUTE_SETTLE)
    lock_payment = _compute_lock_id(_TENANT_CHANGSHA, _KEY_PAYMENT_WECHAT, "/api/v1/trade/orders/{order_id}/payments")
    assert lock_settle != lock_payment


# ─── T4-T7: get_cached_response ──────────────────────────────────────────


def _mk_db_with_select(*, row=None, raise_on_select=False) -> AsyncMock:
    """构造 db mock：set_config + SELECT。row=None → 未命中；row=tuple → 命中。"""
    db = AsyncMock()

    async def execute_side_effect(query, params=None):
        sql_text = str(query)
        if "set_config" in sql_text:
            return MagicMock()
        if "SELECT" in sql_text and "api_idempotency_cache" in sql_text:
            if raise_on_select:
                raise SQLAlchemyError("simulated DB error")
            mock_result = MagicMock()
            mock_result.first.return_value = row
            return mock_result
        return MagicMock()

    db.execute = AsyncMock(side_effect=execute_side_effect)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_t4_get_cached_hit_returns_response():
    """同 key 同 hash → 返回 CachedResponse 含原 status/body。"""
    request_hash = _compute_request_hash("POST", _ROUTE_SETTLE, _REAL_SETTLE_BODY)
    cached_body_str = json.dumps({"ok": True, "data": {"order_no": "X1", "final_amount_fen": 88800}, "error": None})
    db = _mk_db_with_select(row=(200, cached_body_str, "completed", request_hash, datetime.now(timezone.utc)))

    cached = await get_cached_response(
        db,
        tenant_id=_TENANT_CHANGSHA,
        idempotency_key=_KEY_SETTLE,
        route_path=_ROUTE_SETTLE,
        request_hash=request_hash,
    )
    assert isinstance(cached, CachedResponse)
    assert cached.status == 200
    assert cached.state == "completed"
    assert cached.body["ok"] is True
    assert cached.body["data"]["order_no"] == "X1"


@pytest.mark.asyncio
async def test_t5_get_cached_hash_mismatch_raises_conflict():
    """同 key 但 body 不同 → IdempotencyKeyConflict（防同 key 不同 body 攻击）。"""
    db = _mk_db_with_select(
        row=(200, json.dumps({"ok": True}), "completed", "different_hash_value_64chars", datetime.now(timezone.utc))
    )

    with pytest.raises(IdempotencyKeyConflict, match="idempotency_key"):
        await get_cached_response(
            db,
            tenant_id=_TENANT_CHANGSHA,
            idempotency_key=_KEY_SETTLE,
            route_path=_ROUTE_SETTLE,
            request_hash="incoming_hash_value_64chars___________________",
        )


@pytest.mark.asyncio
async def test_t6_get_cached_miss_returns_none():
    """未命中 → None（路由继续处理业务）。"""
    db = _mk_db_with_select(row=None)

    result = await get_cached_response(
        db,
        tenant_id=_TENANT_CHANGSHA,
        idempotency_key=_KEY_SETTLE,
        route_path=_ROUTE_SETTLE,
        request_hash=_compute_request_hash("POST", _ROUTE_SETTLE, _REAL_SETTLE_BODY),
    )
    assert result is None


@pytest.mark.asyncio
async def test_t7_get_cached_db_error_fails_open():
    """DB 错误 → None + structlog warning（fail-open，不阻塞业务）。"""
    db = _mk_db_with_select(raise_on_select=True)

    with patch("src.services.api_idempotency.logger") as mock_logger:
        result = await get_cached_response(
            db,
            tenant_id=_TENANT_CHANGSHA,
            idempotency_key=_KEY_SETTLE,
            route_path=_ROUTE_SETTLE,
            request_hash="any_hash",
        )
        assert result is None
        # 必须发出 warning，运维需要看见
        warns = [c for c in mock_logger.warning.call_args_list if c.args and c.args[0] == "api_idempotency_get_failed"]
        assert len(warns) == 1


@pytest.mark.asyncio
async def test_t6b_get_cached_empty_key_returns_none_no_db():
    """idempotency_key 为空 → None 且不发起 DB 查询（client 没传 header 的退化路径）。"""
    db = _mk_db_with_select(row=None)
    result = await get_cached_response(
        db,
        tenant_id=_TENANT_CHANGSHA,
        idempotency_key="",
        route_path=_ROUTE_SETTLE,
        request_hash="any",
    )
    assert result is None
    # 没有 set_config 也没有 SELECT
    assert db.execute.await_count == 0


# ─── T8-T9: store_cached_response ────────────────────────────────────────


@pytest.mark.asyncio
async def test_t8_store_db_error_does_not_raise():
    """落 cache 失败 → 不向上抛（业务已成功，cache 失败只是后续重试无防护）。"""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=SQLAlchemyError("constraint violation"))
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    with patch("src.services.api_idempotency.logger") as mock_logger:
        await store_cached_response(
            db,
            tenant_id=_TENANT_CHANGSHA,
            idempotency_key=_KEY_SETTLE,
            route_path=_ROUTE_SETTLE,
            request_hash="abc",
            response_status=200,
            response_body={"ok": True, "data": {}, "error": None},
        )
        # 错误必须 log warning
        warns = [
            c for c in mock_logger.warning.call_args_list if c.args and c.args[0] == "api_idempotency_store_failed"
        ]
        assert len(warns) == 1


@pytest.mark.asyncio
async def test_t9_store_serializes_chinese_and_nested():
    """response_body 含中文 + 嵌套 dict → JSON 序列化不报错（ensure_ascii=False）。"""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    body = {
        "ok": True,
        "data": {
            "order_no": "X-2026-001",
            "message": "结账成功",
            "items": [{"name": "毛氏红烧肉", "amount_fen": 8800}],
        },
        "error": None,
    }

    await store_cached_response(
        db,
        tenant_id=_TENANT_CHANGSHA,
        idempotency_key=_KEY_SETTLE,
        route_path=_ROUTE_SETTLE,
        request_hash="abc",
        response_status=200,
        response_body=body,
    )

    # 找到 INSERT 调用，检查 body 参数确实是 JSON 字符串且包含中文
    insert_calls = [c for c in db.execute.await_args_list if "INSERT INTO api_idempotency_cache" in str(c.args[0])]
    assert len(insert_calls) == 1
    params = insert_calls[0].args[1]
    assert "毛氏红烧肉" in params["body"]
    assert "结账成功" in params["body"]


# ─── T10-T11: acquire_idempotency_lock ────────────────────────────────────


@pytest.mark.asyncio
async def test_t10_acquire_lock_empty_key_is_noop():
    """空 / None key → 不发起 DB 调用（无幂等保护即可，client 没传 header）。"""
    db = AsyncMock()
    db.execute = AsyncMock()

    await acquire_idempotency_lock(
        db,
        tenant_id=_TENANT_CHANGSHA,
        idempotency_key=None,
        route_path=_ROUTE_SETTLE,
    )
    await acquire_idempotency_lock(
        db,
        tenant_id=_TENANT_CHANGSHA,
        idempotency_key="",
        route_path=_ROUTE_SETTLE,
    )

    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_t11_acquire_lock_oversize_key_is_noop_with_warning():
    """超长 key（>128 字符）→ no-op + warning。防止恶意客户端构造超长 key 拒绝服务。"""
    db = AsyncMock()
    db.execute = AsyncMock()
    overlong_key = "x" * (MAX_KEY_LENGTH + 1)

    with patch("src.services.api_idempotency.logger") as mock_logger:
        await acquire_idempotency_lock(
            db,
            tenant_id=_TENANT_CHANGSHA,
            idempotency_key=overlong_key,
            route_path=_ROUTE_SETTLE,
        )
        warns = [
            c for c in mock_logger.warning.call_args_list if c.args and c.args[0] == "api_idempotency_key_too_long"
        ]
        assert len(warns) == 1

    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_t11b_acquire_lock_db_error_fails_open():
    """advisory_lock 调用失败 → 不抛，warning。Tier1 cashier UX > 完美幂等。"""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=SQLAlchemyError("conn lost"))

    with patch("src.services.api_idempotency.logger") as mock_logger:
        await acquire_idempotency_lock(
            db,
            tenant_id=_TENANT_CHANGSHA,
            idempotency_key=_KEY_SETTLE,
            route_path=_ROUTE_SETTLE,
        )
        warns = [c for c in mock_logger.warning.call_args_list if c.args and c.args[0] == "api_idempotency_lock_failed"]
        assert len(warns) == 1


# ─── T12: 集成 — 徐记真实双扣防护场景 ────────────────────────────────────


@pytest.mark.asyncio
async def test_t12_xuji_settle_replay_first_stores_second_hits_cache():
    """徐记 200 桌晚高峰：
    1) 收银员扫码 settle → 服务端 store_cached_response
    2) 客户端 3s soft abort + retry 同 key
    3) 服务端 advisory_lock 等第一次完成 → 第二次 get_cached_response → 命中
    4) 第二次直接返回原响应（不再扣会员储值/不再调第三方支付）

    关键断言：第二次必须命中且 body 与第一次一致。
    """
    request_hash = _compute_request_hash("POST", _ROUTE_SETTLE, _REAL_SETTLE_BODY)
    first_response = {"ok": True, "data": {"order_no": "X-2026-001", "final_amount_fen": 88800}, "error": None}
    cached_body_str = json.dumps(first_response, ensure_ascii=False)

    # ── 第一次请求：cache miss，store
    db_first = _mk_db_with_select(row=None)
    cached = await get_cached_response(
        db_first,
        tenant_id=_TENANT_CHANGSHA,
        idempotency_key=_KEY_SETTLE,
        route_path=_ROUTE_SETTLE,
        request_hash=request_hash,
    )
    assert cached is None  # 首次未命中，业务正常处理

    # 业务处理完毕，store cache
    await store_cached_response(
        db_first,
        tenant_id=_TENANT_CHANGSHA,
        idempotency_key=_KEY_SETTLE,
        route_path=_ROUTE_SETTLE,
        request_hash=request_hash,
        response_status=200,
        response_body=first_response,
    )

    # ── 第二次请求（重试）：cache hit
    db_second = _mk_db_with_select(row=(200, cached_body_str, "completed", request_hash, datetime.now(timezone.utc)))
    cached2 = await get_cached_response(
        db_second,
        tenant_id=_TENANT_CHANGSHA,
        idempotency_key=_KEY_SETTLE,
        route_path=_ROUTE_SETTLE,
        request_hash=request_hash,
    )
    assert cached2 is not None
    assert cached2.status == 200
    assert cached2.body == first_response  # ★ 必须是同一响应，防双扣
    assert cached2.state == "completed"
