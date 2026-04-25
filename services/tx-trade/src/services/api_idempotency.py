"""api_idempotency — HTTP 路由级 X-Idempotency-Key replay cache（A1-R3 / Tier1）

§19 R-A1-3 修复：apps/web-pos R-补2-1（commit 48aba740）客户端在 replay 时
携带 `X-Idempotency-Key` header，本模块负责服务端拦截：

  - 首次请求：处理业务 → 落 cache（24h TTL）→ 返回响应
  - 同 key 重试：直接读 cache → 返回原响应（不再处理业务）
  - 同 key 不同 body：返回 422 IDEMPOTENCY_KEY_CONFLICT（客户端 bug 信号）
  - 并发同 key：PG advisory_xact_lock 串行化，第二个请求自动读到第一个的 cache

依赖：v296_api_idempotency_cache 迁移 + RLS。

设计要点：
  1. PG advisory_xact_lock：lock_id = SHA256(tenant_id|key|route)[:8] (signed BIGINT)
     → 路由内部事务 hold 锁直到 commit/rollback 自动释放，无需显式 unlock
  2. request_hash = SHA256(method + path + body) → 检测同 key 不同 payload 攻击
  3. response_body 以 JSONB 存原响应；cache 命中时 dict 直接返回（FastAPI 序列化）
  4. fail-safe：cache 读写失败 → 路由继续执行业务（fail-open）但记 structlog
     warning。设计原则：cache 是"防双扣的优化层"，不是"业务必经路径"
  5. TTL 默认 24h：覆盖 POS 离线队列回放窗口（IndexedDB 默认 7 天但 24h 已够
     长，足以覆盖一个营业日）
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = structlog.get_logger(__name__)


# ─── 常量 ──────────────────────────────────────────────────────────────────

DEFAULT_TTL_HOURS = 24
MAX_KEY_LENGTH = 128       # v296 schema 一致
MAX_ROUTE_LENGTH = 128


# ─── 异常 ──────────────────────────────────────────────────────────────────


class IdempotencyKeyConflict(Exception):
    """同 idempotency_key 上次请求 body 与本次不一致 → 客户端 bug 或攻击。

    路由层应转换为 HTTP 422 IDEMPOTENCY_KEY_CONFLICT，让客户端报错而不是
    模糊的 500。
    """


# ─── 数据结构 ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CachedResponse:
    """命中 cache 时返回的快照（无 mutation 风险）。"""

    status: int
    body: dict[str, Any]
    state: str  # 'completed' / 'processing' / 'failed'
    created_at: datetime


# ─── 私有：哈希工具 ────────────────────────────────────────────────────────


def _compute_request_hash(method: str, path: str, body: bytes | str | None) -> str:
    """SHA256(method.upper() + '\\n' + path + '\\n' + body)，不区分大小写 method。"""
    h = hashlib.sha256()
    h.update((method or "").upper().encode())
    h.update(b"\n")
    h.update((path or "").encode())
    h.update(b"\n")
    if body is not None:
        h.update(body if isinstance(body, bytes) else body.encode())
    return h.hexdigest()


def _compute_lock_id(tenant_id: str, key: str, route: str) -> int:
    """PG advisory_xact_lock 接 BIGINT；从 SHA256 取前 8 字节转 signed int64。

    跨租户 / 跨 key / 跨路由的并发不会互相阻塞（hash 几乎不碰撞）。
    同 (tenant, key, route) 的并发自动串行。
    """
    h = hashlib.sha256(f"{tenant_id}|{key}|{route}".encode()).digest()
    return int.from_bytes(h[:8], "big", signed=True)


# ─── 私有：DB 操作 ─────────────────────────────────────────────────────────


async def _set_rls(db, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


async def _acquire_advisory_lock(
    db, *, tenant_id: str, key: str, route: str
) -> None:
    """事务级 advisory lock；commit/rollback 自动释放。

    注意：必须与读 cache + 写 cache 在同一事务内调用，否则锁脱节。
    路由层应在事务一开始就调用本函数。
    """
    lock_id = _compute_lock_id(tenant_id, key, route)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:id)"),
        {"id": lock_id},
    )


# ─── 公共 API ──────────────────────────────────────────────────────────────


async def get_cached_response(
    db,
    *,
    tenant_id: str,
    idempotency_key: str,
    route_path: str,
    request_hash: str,
) -> CachedResponse | None:
    """读 cache。命中且 hash 一致 → 返回 CachedResponse；
    命中但 hash 不一致 → raise IdempotencyKeyConflict；
    未命中 / DB 错误 → 返回 None（路由继续处理业务）。

    前置：调用方应先 acquire_idempotency_lock 拿到事务级锁。
    """
    if not idempotency_key:
        return None

    try:
        await _set_rls(db, tenant_id)
        result = await db.execute(
            text(
                """
                SELECT response_status, response_body, state, request_hash, created_at
                FROM api_idempotency_cache
                WHERE tenant_id = CAST(:tid AS UUID)
                  AND idempotency_key = :key
                  AND route_path = :route
                  AND expires_at > NOW()
                LIMIT 1
                """
            ),
            {"tid": str(tenant_id), "key": idempotency_key, "route": route_path},
        )
        row = result.first()
    except SQLAlchemyError as exc:
        logger.warning(
            "api_idempotency_get_failed",
            tenant_id=str(tenant_id),
            key=idempotency_key,
            route=route_path,
            error=str(exc),
        )
        return None

    if row is None:
        return None

    # 兼容真实 PG row（_mapping）和 mock 序列
    try:
        cached_status = int(row[0])
        cached_body_raw = row[1]
        cached_state = str(row[2])
        cached_hash = str(row[3])
        cached_ctime = row[4]
    except (TypeError, IndexError, ValueError) as exc:
        logger.warning(
            "api_idempotency_row_decode_failed",
            tenant_id=str(tenant_id),
            key=idempotency_key,
            error=str(exc),
        )
        return None

    if cached_hash != request_hash:
        # 同 key 不同 body — 客户端 bug 或攻击
        raise IdempotencyKeyConflict(
            f"idempotency_key={idempotency_key!r} 已用过相同 route 但 body 不同; "
            f"existing_hash={cached_hash[:8]}... new_hash={request_hash[:8]}..."
        )

    # JSONB 在 SQLAlchemy 中可能反序列化为 dict 或保留 str；统一为 dict
    if isinstance(cached_body_raw, str):
        try:
            cached_body = json.loads(cached_body_raw)
        except (json.JSONDecodeError, ValueError):
            cached_body = {}
    elif isinstance(cached_body_raw, dict):
        cached_body = cached_body_raw
    else:
        cached_body = {}

    return CachedResponse(
        status=cached_status,
        body=cached_body,
        state=cached_state,
        created_at=cached_ctime if isinstance(cached_ctime, datetime) else datetime.now(timezone.utc),
    )


async def store_cached_response(
    db,
    *,
    tenant_id: str,
    idempotency_key: str,
    route_path: str,
    request_hash: str,
    response_status: int,
    response_body: dict[str, Any],
    store_id: str | None = None,
    user_id: str | None = None,
    state: str = "completed",
    ttl_hours: int = DEFAULT_TTL_HOURS,
) -> None:
    """写 cache。INSERT ON CONFLICT DO UPDATE 保证幂等（重复写覆盖最新）。

    state='completed' 表示业务已成功处理；'failed' 表示业务失败但仍想缓存
    错误响应（避免重复触发同样错误）；'processing' 仅用于罕见的"占位"
    场景（与 advisory_lock 配合）。
    """
    if not idempotency_key:
        return

    expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)

    try:
        await _set_rls(db, tenant_id)
        await db.execute(
            text(
                """
                INSERT INTO api_idempotency_cache (
                    tenant_id, idempotency_key, route_path, request_hash,
                    response_status, response_body, state, store_id, user_id,
                    expires_at
                ) VALUES (
                    CAST(:tid AS UUID), :key, :route, :hash,
                    :status, CAST(:body AS JSONB), :state,
                    CAST(:sid AS UUID), CAST(:uid AS UUID),
                    :exp
                )
                ON CONFLICT (tenant_id, idempotency_key, route_path)
                DO UPDATE SET
                    request_hash = EXCLUDED.request_hash,
                    response_status = EXCLUDED.response_status,
                    response_body = EXCLUDED.response_body,
                    state = EXCLUDED.state,
                    updated_at = NOW(),
                    expires_at = EXCLUDED.expires_at
                """
            ),
            {
                "tid": str(tenant_id),
                "key": idempotency_key,
                "route": route_path,
                "hash": request_hash,
                "status": int(response_status),
                "body": json.dumps(response_body, ensure_ascii=False),
                "state": state,
                "sid": str(store_id) if store_id else None,
                "uid": str(user_id) if user_id else None,
                "exp": expires_at,
            },
        )
    except SQLAlchemyError as exc:
        logger.warning(
            "api_idempotency_store_failed",
            tenant_id=str(tenant_id),
            key=idempotency_key,
            route=route_path,
            error=str(exc),
        )


# ─── 高层 helper：路由级一行集成 ───────────────────────────────────────────


async def acquire_idempotency_lock(
    db,
    *,
    tenant_id: str,
    idempotency_key: str | None,
    route_path: str,
) -> None:
    """路由开始时调用。idempotency_key 为空时 no-op。

    前置：调用方应已 begin transaction（FastAPI Depends(get_db) 自动 begin）。
    """
    if not idempotency_key:
        return
    if len(idempotency_key) > MAX_KEY_LENGTH:
        logger.warning(
            "api_idempotency_key_too_long",
            tenant_id=str(tenant_id),
            key_prefix=idempotency_key[:32],
            length=len(idempotency_key),
        )
        return  # 超长 key 不取锁，不读 cache，自动 fail-open
    if len(route_path) > MAX_ROUTE_LENGTH:
        return

    try:
        await _set_rls(db, tenant_id)
        await _acquire_advisory_lock(db, tenant_id=tenant_id, key=idempotency_key, route=route_path)
    except SQLAlchemyError as exc:
        # 锁失败 → 不取锁，但路由仍正常处理（防双扣劣化为"高并发偶尔双扣"，
        # 而不是"全部 500"）。Tier1 cashier UX > 完美幂等
        logger.warning(
            "api_idempotency_lock_failed",
            tenant_id=str(tenant_id),
            key=idempotency_key,
            route=route_path,
            error=str(exc),
        )


def compute_request_hash(method: str, path: str, body: bytes | str | None) -> str:
    """暴露给路由层；与 _compute_request_hash 等价（仅作为公开 API 名）。"""
    return _compute_request_hash(method, path, body)
