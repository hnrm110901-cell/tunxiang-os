"""sync_ingest_router.py — 云端边缘同步接收 API

端点：
  POST /api/v1/sync/ingest  — 接收边缘推送的 ChangeRecord 变更，验证并应用到云端 PG
  GET  /api/v1/sync/changes — 返回云端自 since 后的变更列表（供边缘拉取，旧契约）
  GET  /api/v1/sync/pull    — SyncToken (ts+seq) 双键增量拉取（v147 events 表，新契约）

设计原则：
  - 多租户：所有操作通过 X-Tenant-ID 隔离，强制 tenant_id 过滤
  - 幂等性：通过 change_id 去重（UPSERT ON CONFLICT DO NOTHING）
  - 冲突检测：云端版本比边缘更新时，返回 conflict 而非覆盖
  - 分页：GET /changes 支持 since / page / size 参数
  - 错误处理：具体异常类型，不使用 broad except
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/sync", tags=["edge-sync"])


# ─── 审计 S-03（P0）：edge sync 强制 per-store 鉴权 ─────────────────────────
# 原本 edge sync-engine ↔ 云仅靠 Tailscale 网络层信任 + X-Tenant-ID header；
# 任一 Mac mini 被攻陷或 Tailscale ACL 漂移即可任意写。
# 此处增加 per-store HMAC token：边缘端启动时由 ops 注入 EDGE_STORE_SYNC_KEY，
# 每次请求附 X-Edge-Store-Token = HMAC_SHA256(secret, f"{store_id}.{tenant_id}.{ts}.{nonce}")
# 头部同时附 X-Edge-Store-Id / X-Edge-Tenant-Id / X-Edge-Sync-Ts / X-Edge-Sync-Nonce。
# 服务侧从 EDGE_SYNC_HMAC_SECRET（K8s Secret）读密钥校验。
#
# Rollout：
#   - 环境变量 EDGE_SYNC_HMAC_SECRET 未配置 → 仅 warn 不阻断（dev/staging 过渡期）
#   - 配置后 → 缺 token / 校验失败 / 时钟偏差 > 300s / nonce 重放 → 401

_EDGE_SYNC_TS_SKEW_SECONDS = 300
_EDGE_SYNC_RECENT_NONCES: dict[str, float] = {}  # nonce → timestamp，5min 窗口


def _edge_sync_secret() -> str:
    return os.environ.get("EDGE_SYNC_HMAC_SECRET", "").strip()


def _edge_sync_required() -> bool:
    """True = 必须带合法 token；False = 仅 warn（dev 过渡期）。"""
    if _edge_sync_secret():
        return True
    env = (os.environ.get("TX_ENV") or os.environ.get("ENVIRONMENT") or "").strip().lower()
    return env in ("production", "prod", "gray")


def _gc_old_nonces(now: float) -> None:
    """清理 5 分钟外的 nonce。"""
    threshold = now - _EDGE_SYNC_TS_SKEW_SECONDS
    expired = [k for k, v in _EDGE_SYNC_RECENT_NONCES.items() if v < threshold]
    for k in expired:
        _EDGE_SYNC_RECENT_NONCES.pop(k, None)


async def verify_edge_sync_auth(
    x_edge_store_id: Optional[str] = Header(default=None, alias="X-Edge-Store-Id"),
    x_edge_tenant_id: Optional[str] = Header(default=None, alias="X-Edge-Tenant-Id"),
    x_edge_sync_ts: Optional[str] = Header(default=None, alias="X-Edge-Sync-Ts"),
    x_edge_sync_nonce: Optional[str] = Header(default=None, alias="X-Edge-Sync-Nonce"),
    x_edge_store_token: Optional[str] = Header(default=None, alias="X-Edge-Store-Token"),
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
) -> str:
    """校验 edge sync 请求；返回校验通过的 tenant_id。"""
    secret = _edge_sync_secret()
    required = _edge_sync_required()

    # 兼容 dev：未配置 secret 且非生产环境 — 仅 warn 不阻
    if not secret:
        if required:
            logger.error("edge_sync_secret_missing_in_production")
            raise HTTPException(status_code=500, detail="edge sync auth misconfigured")
        logger.warning(
            "edge_sync_auth_skipped_dev_mode",
            note="EDGE_SYNC_HMAC_SECRET 未配置；生产必须配置",
        )
        # dev 模式回退到原 X-Tenant-ID 信任
        if not x_tenant_id:
            raise HTTPException(status_code=400, detail="X-Tenant-ID required (dev mode)")
        return x_tenant_id

    # 强制校验
    if not all([x_edge_store_id, x_edge_tenant_id, x_edge_sync_ts, x_edge_sync_nonce, x_edge_store_token]):
        logger.warning("edge_sync_auth_missing_headers", store=x_edge_store_id)
        raise HTTPException(status_code=401, detail="edge sync auth headers missing")

    # 时间戳防重放
    try:
        ts = int(x_edge_sync_ts)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="invalid X-Edge-Sync-Ts") from None
    now = time.time()
    if abs(now - ts) > _EDGE_SYNC_TS_SKEW_SECONDS:
        logger.warning("edge_sync_auth_ts_skew", store=x_edge_store_id, skew=int(now - ts))
        raise HTTPException(status_code=401, detail="edge sync timestamp skew")

    # nonce 防重放
    nonce_key = f"{x_edge_store_id}:{x_edge_sync_nonce}"
    _gc_old_nonces(now)
    if nonce_key in _EDGE_SYNC_RECENT_NONCES:
        logger.warning("edge_sync_auth_nonce_replay", store=x_edge_store_id, nonce=x_edge_sync_nonce)
        raise HTTPException(status_code=401, detail="edge sync nonce replay")

    # HMAC 校验
    msg = f"{x_edge_store_id}.{x_edge_tenant_id}.{x_edge_sync_ts}.{x_edge_sync_nonce}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, x_edge_store_token or ""):
        logger.warning("edge_sync_auth_signature_invalid", store=x_edge_store_id)
        raise HTTPException(status_code=401, detail="edge sync signature invalid")

    # tenant_id 一致性
    if x_tenant_id and x_tenant_id != x_edge_tenant_id:
        logger.warning(
            "edge_sync_auth_tenant_mismatch",
            store=x_edge_store_id,
            header_tenant=x_tenant_id,
            claim_tenant=x_edge_tenant_id,
        )
        raise HTTPException(status_code=401, detail="X-Tenant-ID claim mismatch")

    _EDGE_SYNC_RECENT_NONCES[nonce_key] = now
    logger.debug("edge_sync_auth_ok", store=x_edge_store_id, tenant=x_edge_tenant_id)
    return x_edge_tenant_id  # type: ignore[return-value]

# 云端 sync_changelog 允许写入的表白名单
ALLOWED_TABLES: frozenset[str] = frozenset(
    {
        "orders",
        "order_items",
        "members",
        "dishes",
        "inventory_records",
    }
)

# 审计 Tier1 F3（P0）：列名安全正则 — snake_case 字母数字下划线，最长 63
# （PG identifier 上限 64）。防止 JSON key 含 `"`、`;`、`)` 等字符
# 在 `f'"{c}"'` 处突破双引号标识符注入 SQL（如 `id") SELECT pg_sleep(10);--`）。
# TODO（强烈建议）：改为按表的显式列白名单，详见
# docs/audit-2026-05/03-tier1-critical-paths.md F3 修复建议。
_SAFE_COL_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _validate_columns(columns: list[str], table_name: str) -> None:
    """校验全部列名形式安全；任一非法即 raise HTTPException(400)。"""
    for c in columns:
        if not _SAFE_COL_NAME_RE.match(c):
            logger.warning(
                "sync_ingest.unsafe_column_name",
                column=c,
                table=table_name,
            )
            raise HTTPException(
                status_code=400,
                detail=f"unsafe column name in sync payload: {c!r}",
            )


# ─── 请求/响应模型 ────────────────────────────────────────────────────────


class ChangeRecordIn(BaseModel):
    """边缘推送的单条变更记录"""

    change_id: str = Field(description="变更唯一 ID（边缘生成，用于去重）")
    table_name: str = Field(description="目标表名")
    record_id: str = Field(description="记录主键")
    operation: str = Field(description="INSERT | UPDATE | DELETE")
    data: dict[str, Any] = Field(default_factory=dict, description="记录完整数据（DELETE 时可为空）")
    tenant_id: str = Field(description="租户 ID")
    changed_at: str = Field(description="变更时间戳 ISO 8601")


class IngestRequest(BaseModel):
    """批量变更推送请求体"""

    changes: List[ChangeRecordIn] = Field(min_length=1, max_length=500)


class IngestResponse(BaseModel):
    accepted: List[str] = Field(description="成功处理的 change_id 列表")
    conflicts: List[str] = Field(description="云端版本更新、未覆盖的 change_id 列表")
    errors: List[str] = Field(description="处理失败的 change_id 列表")
    error_messages: List[str] = Field(default_factory=list)


class ChangeRecordOut(BaseModel):
    """云端返回给边缘的变更记录"""

    change_id: str
    table_name: str
    record_id: str
    operation: str
    data: dict[str, Any]
    tenant_id: str
    changed_at: str


class ChangesResponse(BaseModel):
    items: List[ChangeRecordOut]
    total: int
    page: int
    size: int


class PullEventOut(BaseModel):
    """v147 events 表事件（边缘 SyncToken 消费契约）

    字段命名与 edge.SyncToken.filter_unseen 对齐：
      - seq: events.sequence_num（BIGINT）
      - ts:  events.recorded_at（ISO 8601）
      - 其他字段透传，供边缘业务投影器消费
    """

    seq: int
    ts: str
    event_id: str
    event_type: str
    stream_id: str
    stream_type: str
    store_id: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PullResponse(BaseModel):
    items: List[PullEventOut]
    count: int
    max_seq: int
    # PJ.1: event_id 作为复合游标第三键，消除 (ts, seq) 重复时的数据丢失
    # v147 events.event_id 是 UUID PK 全局唯一，永远可作为最终 tiebreaker
    max_event_id: str = "00000000-0000-0000-0000-000000000000"


# ─── 依赖：获取租户 ID ────────────────────────────────────────────────────


def _require_tenant(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return x_tenant_id


# ─── 路由实现 ─────────────────────────────────────────────────────────────


@router.post(
    "/ingest",
    summary="接收边缘推送的变更记录",
    description=(
        "边缘 Mac mini 将本地变更批量推送到云端。\n\n"
        "- 验证表名白名单和 tenant_id 匹配\n"
        "- 幂等：change_id 重复则跳过\n"
        "- 冲突：云端记录的 updated_at 比变更更新 → 返回 conflicts，不覆盖\n"
        "- 成功：写入 sync_ingested_log 并 UPSERT 到目标表"
    ),
)
async def ingest_changes(
    req: IngestRequest,
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response = IngestResponse(accepted=[], conflicts=[], errors=[], error_messages=[])

    for change in req.changes:
        # 租户 ID 校验
        if change.tenant_id != tenant_id:
            logger.warning(
                "sync_ingest.tenant_mismatch",
                change_id=change.change_id,
                header_tenant=tenant_id,
                payload_tenant=change.tenant_id,
            )
            response.errors.append(change.change_id)
            response.error_messages.append(f"{change.change_id}: tenant_id mismatch")
            continue

        # 表名白名单校验
        if change.table_name not in ALLOWED_TABLES:
            logger.warning(
                "sync_ingest.table_not_allowed",
                table=change.table_name,
                change_id=change.change_id,
            )
            response.errors.append(change.change_id)
            response.error_messages.append(f"{change.change_id}: table '{change.table_name}' not in allowlist")
            continue

        try:
            changed_at = datetime.fromisoformat(change.changed_at)
            if changed_at.tzinfo is None:
                changed_at = changed_at.replace(tzinfo=timezone.utc)

            # 幂等检查：change_id 是否已处理
            already = await _check_already_processed(db, change.change_id)
            if already:
                response.accepted.append(change.change_id)
                continue

            if change.operation == "DELETE":
                await _apply_soft_delete(db, change, changed_at)
                await _log_ingested(db, change, tenant_id)
                response.accepted.append(change.change_id)

            else:
                # INSERT / UPDATE：先检查云端版本是否更新
                is_conflict = await _check_cloud_version_newer(db, change, changed_at)
                if is_conflict:
                    logger.info(
                        "sync_ingest.conflict_cloud_newer",
                        table=change.table_name,
                        record_id=change.record_id,
                        change_id=change.change_id,
                    )
                    response.conflicts.append(change.change_id)
                    continue

                await _upsert_record(db, change)
                await _log_ingested(db, change, tenant_id)
                response.accepted.append(change.change_id)

        except (ValueError, TypeError) as exc:
            logger.error(
                "sync_ingest.validation_error",
                change_id=change.change_id,
                error=str(exc),
            )
            response.errors.append(change.change_id)
            response.error_messages.append(f"{change.change_id}: {str(exc)[:200]}")
        except SQLAlchemyError as exc:
            logger.error(
                "sync_ingest.db_error",
                change_id=change.change_id,
                error=str(exc),
                exc_info=True,
            )
            response.errors.append(change.change_id)
            response.error_messages.append(f"{change.change_id}: db error — {type(exc).__name__}")

    await db.commit()

    logger.info(
        "sync_ingest.done",
        tenant_id=tenant_id,
        total=len(req.changes),
        accepted=len(response.accepted),
        conflicts=len(response.conflicts),
        errors=len(response.errors),
    )
    return {"ok": True, "data": response.model_dump()}


@router.get(
    "/changes",
    summary="返回云端变更列表（供边缘拉取）",
    description=(
        "边缘 Mac mini 定期拉取云端自 `since` 后产生的变更。\n\n"
        "- 来源：sync_cloud_changelog 表（由云端业务写入触发）\n"
        "- 支持分页：page / size（最大 500）\n"
        "- 包含菜单更新、会员充值、配置下发等总部变更"
    ),
)
async def get_cloud_changes(
    since: str = Query(
        default="1970-01-01T00:00:00+00:00",
        description="ISO 8601 时间戳，返回该时间之后的变更",
    ),
    page: int = Query(default=1, ge=1, description="页码"),
    size: int = Query(default=500, ge=1, le=500, description="每页条数"),
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        since_dt = datetime.fromisoformat(since)
        if since_dt.tzinfo is None:
            since_dt = since_dt.replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid 'since' timestamp: {exc}",
        )

    offset = (page - 1) * size

    try:
        result = await db.execute(
            text(
                """
                SELECT change_id, table_name, record_id, operation,
                       data, tenant_id, changed_at
                FROM sync_cloud_changelog
                WHERE tenant_id = :tenant_id
                  AND changed_at > :since
                ORDER BY changed_at ASC
                LIMIT :size OFFSET :offset
            """
            ),
            {
                "tenant_id": tenant_id,
                "since": since_dt,
                "size": size,
                "offset": offset,
            },
        )
        keys = list(result.keys())
        rows = result.all()
    except OperationalError:
        # sync_cloud_changelog 表不存在（尚未创建）
        logger.warning(
            "sync_ingest.cloud_changelog_missing",
            msg="sync_cloud_changelog table not found, returning empty list",
        )
        return {
            "ok": True,
            "data": ChangesResponse(items=[], total=0, page=page, size=size).model_dump(),
        }
    except SQLAlchemyError as exc:
        logger.error(
            "sync_ingest.get_changes_db_error",
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Database error")

    items: List[ChangeRecordOut] = []
    for row in rows:
        d = dict(zip(keys, row))
        data = d.get("data") or {}
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, ValueError):
                data = {}
        changed_at = d["changed_at"]
        if isinstance(changed_at, datetime):
            changed_at_str = changed_at.isoformat()
        else:
            changed_at_str = str(changed_at)
        items.append(
            ChangeRecordOut(
                change_id=str(d.get("change_id", "")),
                table_name=d["table_name"],
                record_id=str(d["record_id"]),
                operation=d["operation"],
                data=data,
                tenant_id=d["tenant_id"],
                changed_at=changed_at_str,
            )
        )

    response = ChangesResponse(
        items=items,
        total=len(items),  # 简化：不额外 COUNT(*)，前端根据 len < size 判断是否最后一页
        page=page,
        size=size,
    )

    logger.info(
        "sync_ingest.changes_returned",
        tenant_id=tenant_id,
        since=since,
        page=page,
        count=len(items),
    )
    return {"ok": True, "data": response.model_dump()}


@router.get(
    "/pull",
    summary="SyncToken 双键增量拉取（v147 events 表）",
    description=(
        "边缘 Mac mini 通过 (since_ts, since_seq) 复合游标增量拉取云端事件。\n\n"
        "- 数据源：v147 `events` 表（Event Sourcing）\n"
        "- 游标语义：返回 (recorded_at > since_ts) OR (recorded_at = since_ts AND sequence_num > since_seq)\n"
        "- 同租户 + 同门店强制过滤；store_id 为空只返回租户级事件\n"
        "- LIMIT 500（边缘按 max_seq/last_ts 持久化 SyncToken，下一轮续传）"
    ),
)
async def pull_events(
    store_id: str = Query(description="门店 ID（UUID）"),
    since_ts: str = Query(
        default="1970-01-01T00:00:00+00:00",
        description="ISO 8601 时间戳，复合游标的时间分量",
    ),
    since_seq: int = Query(
        default=0,
        ge=0,
        description="复合游标的序列号分量，用于同 ts 内事件的 tiebreaker",
    ),
    since_id: str = Query(
        default="00000000-0000-0000-0000-000000000000",
        description=(
            "复合游标的 event_id 分量（PJ.1 三键 tiebreaker）— 旧客户端缺省走零 UUID 即可，"
            "events.event_id 是 UUID PK 全局唯一，最终消除 (ts, seq) 重复时的数据丢失"
        ),
    ),
    limit: int = Query(default=500, ge=1, le=500),
    tenant_id: str = Depends(_require_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        since_dt = datetime.fromisoformat(since_ts)
        if since_dt.tzinfo is None:
            since_dt = since_dt.replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid 'since_ts' timestamp: {exc}",
        )

    try:
        # PJ.1: 三键 tiebreaker (recorded_at, sequence_num, event_id)
        # 旧二元组 cursor 兼容：since_id 缺省零 UUID，配合 event_id > zero UUID
        # 等价于"任意 event_id"，行为退化为原二键比较
        result = await db.execute(
            text(
                """
                SELECT event_id, sequence_num, recorded_at,
                       event_type, stream_id, stream_type,
                       store_id, payload, metadata
                FROM events
                WHERE tenant_id = :tenant_id
                  AND store_id = :store_id
                  AND (
                    recorded_at > :since_ts
                    OR (recorded_at = :since_ts AND sequence_num > :since_seq)
                    OR (
                      recorded_at = :since_ts
                      AND sequence_num = :since_seq
                      AND event_id > CAST(:since_id AS UUID)
                    )
                  )
                ORDER BY recorded_at ASC, sequence_num ASC, event_id ASC
                LIMIT :limit
                """
            ),
            {
                "tenant_id": tenant_id,
                "store_id": store_id,
                "since_ts": since_dt,
                "since_seq": since_seq,
                "since_id": since_id,
                "limit": limit,
            },
        )
        keys = list(result.keys())
        rows = result.all()
    except OperationalError as exc:
        # PJ.1: 收窄 OperationalError 兜底范围 — 只接 "events does not exist"，
        # 其他 OperationalError（连接断/磁盘满/lock timeout/无权限等）必须 raise，
        # 否则客户端拿到空响应误判同步完成 → 静默丢失大批事件
        err_msg = str(exc.orig) if exc.orig is not None else str(exc)
        if "events" not in err_msg or "does not exist" not in err_msg:
            logger.error(
                "sync_ingest.pull_operational_error_propagated",
                error=err_msg,
                exc_info=True,
            )
            raise
        logger.warning(
            "sync_ingest.events_table_missing",
            msg="events table not found, returning empty list",
        )
        return {
            "ok": True,
            "data": PullResponse(
                items=[],
                count=0,
                max_seq=since_seq,
                max_event_id=since_id,
            ).model_dump(),
        }
    except SQLAlchemyError as exc:
        logger.error(
            "sync_ingest.pull_db_error",
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Database error")

    items: List[PullEventOut] = []
    max_seq = since_seq
    max_event_id = since_id
    for row in rows:
        d = dict(zip(keys, row))
        seq_val = int(d.get("sequence_num", 0))
        if seq_val > max_seq:
            max_seq = seq_val

        recorded_at = d["recorded_at"]
        ts_str = recorded_at.isoformat() if isinstance(recorded_at, datetime) else str(recorded_at)

        payload = d.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, ValueError):
                payload = {}
        meta = d.get("metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (json.JSONDecodeError, ValueError):
                meta = {}

        eid = str(d["event_id"])
        # 行已按 (recorded_at, sequence_num, event_id) 排序，最后一行就是最大 cursor
        max_event_id = eid

        items.append(
            PullEventOut(
                seq=seq_val,
                ts=ts_str,
                event_id=eid,
                event_type=str(d["event_type"]),
                stream_id=str(d["stream_id"]),
                stream_type=str(d["stream_type"]),
                store_id=str(d["store_id"]) if d.get("store_id") else None,
                payload=payload,
                metadata=meta,
            )
        )

    response = PullResponse(
        items=items,
        count=len(items),
        max_seq=max_seq,
        max_event_id=max_event_id,
    )

    logger.info(
        "sync_ingest.pull_done",
        tenant_id=tenant_id,
        store_id=store_id,
        since_ts=since_ts,
        since_seq=since_seq,
        since_id=since_id,
        returned=len(items),
        max_seq=max_seq,
        max_event_id=max_event_id,
    )
    return {"ok": True, "data": response.model_dump()}


# ─── 内部辅助函数 ─────────────────────────────────────────────────────────


async def _check_already_processed(db: AsyncSession, change_id: str) -> bool:
    """检查 change_id 是否已写入 sync_ingested_log（幂等去重）"""
    try:
        result = await db.execute(
            text(
                """
                SELECT 1 FROM sync_ingested_log
                WHERE change_id = :change_id
                LIMIT 1
            """
            ),
            {"change_id": change_id},
        )
        return result.one_or_none() is not None
    except OperationalError:
        # 表不存在（首次运行），视为未处理
        return False


async def _check_cloud_version_newer(
    db: AsyncSession,
    change: ChangeRecordIn,
    changed_at: datetime,
) -> bool:
    """检查云端记录的 updated_at 是否比边缘变更更新（云端为主，拒绝旧变更覆盖）"""
    try:
        result = await db.execute(
            text(f'SELECT updated_at FROM "{change.table_name}" WHERE id = :id AND tenant_id = :tid'),
            {"id": change.record_id, "tid": change.tenant_id},
        )
        row = result.one_or_none()
    except (OperationalError, SQLAlchemyError):
        return False

    if row is None:
        return False  # 记录不存在，不冲突

    cloud_ts = row[0]
    if cloud_ts is None:
        return False
    if isinstance(cloud_ts, str):
        cloud_ts = datetime.fromisoformat(cloud_ts)
    if cloud_ts.tzinfo is None:
        cloud_ts = cloud_ts.replace(tzinfo=timezone.utc)

    # 云端比边缘新超过 1 秒才视为冲突（允许微小时钟偏差）
    return (cloud_ts - changed_at).total_seconds() > 1.0


async def _upsert_record(db: AsyncSession, change: ChangeRecordIn) -> None:
    """UPSERT 单条记录到目标表（边缘推送，云端应用）"""
    data = change.data
    if not data or "id" not in data:
        logger.warning(
            "sync_ingest.upsert_no_id",
            table=change.table_name,
            record_id=change.record_id,
        )
        return

    # 强制 tenant_id = 请求 tenant_id（防止篡改）
    data["tenant_id"] = change.tenant_id

    columns = list(data.keys())
    # 审计 Tier1 F3（P0）：在拼 SQL 前严格校验列名形式，防 JSON key 注入。
    _validate_columns(columns, change.table_name)
    col_list = ", ".join(f'"{c}"' for c in columns)
    placeholders = ", ".join(f":{c}" for c in columns)
    update_set = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in columns if c != "id")
    sql = (
        f'INSERT INTO "{change.table_name}" ({col_list}) '
        f"VALUES ({placeholders}) "
        f"ON CONFLICT (id) DO UPDATE SET {update_set}"
    )
    row = {c: data.get(c) for c in columns}
    await db.execute(text(sql), row)


async def _apply_soft_delete(
    db: AsyncSession,
    change: ChangeRecordIn,
    changed_at: datetime,
) -> None:
    """软删除：设置 is_deleted=TRUE"""
    await db.execute(
        text(
            f"""
            UPDATE "{change.table_name}"
            SET is_deleted = TRUE,
                updated_at = :updated_at
            WHERE id = :id
              AND tenant_id = :tenant_id
        """
        ),
        {
            "id": change.record_id,
            "tenant_id": change.tenant_id,
            "updated_at": changed_at,
        },
    )


async def _log_ingested(
    db: AsyncSession,
    change: ChangeRecordIn,
    tenant_id: str,
) -> None:
    """记录已处理的 change_id 到 sync_ingested_log（幂等去重 + 审计）"""
    try:
        await db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS sync_ingested_log (
                    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    change_id   TEXT UNIQUE NOT NULL,
                    table_name  TEXT NOT NULL,
                    record_id   TEXT NOT NULL,
                    tenant_id   TEXT NOT NULL,
                    operation   TEXT NOT NULL,
                    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """
            )
        )
        await db.execute(
            text(
                """
                INSERT INTO sync_ingested_log
                    (change_id, table_name, record_id, tenant_id, operation, ingested_at)
                VALUES
                    (:change_id, :table_name, :record_id, :tenant_id, :operation, NOW())
                ON CONFLICT (change_id) DO NOTHING
            """
            ),
            {
                "change_id": change.change_id,
                "table_name": change.table_name,
                "record_id": change.record_id,
                "tenant_id": tenant_id,
                "operation": change.operation,
            },
        )
    except SQLAlchemyError as exc:
        # 日志写入失败不阻塞主流程
        logger.warning(
            "sync_ingest.log_write_error",
            change_id=change.change_id,
            error=str(exc),
        )
