"""sync_ingest_router.py — 云端边缘同步接收 API

端点：
  POST /api/v1/sync/ingest  — 接收边缘推送的 ChangeRecord 变更，验证并应用到云端 PG
  GET  /api/v1/sync/changes — 返回云端自 since 后的变更列表（供边缘拉取）

设计原则：
  - 多租户：所有操作通过 X-Tenant-ID 隔离，强制 tenant_id 过滤
  - 幂等性：通过 change_id 去重（UPSERT ON CONFLICT DO NOTHING）
  - 冲突检测：云端版本比边缘更新时，返回 conflict 而非覆盖
  - 分页：GET /changes 支持 since / page / size 参数
  - 错误处理：具体异常类型，不使用 broad except
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/sync", tags=["edge-sync"])

# 云端 sync_changelog 允许写入的表白名单
ALLOWED_TABLES: frozenset[str] = frozenset({
    "orders",
    "order_items",
    "members",
    "dishes",
    "inventory_records",
})


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
            response.error_messages.append(
                f"{change.change_id}: tenant_id mismatch"
            )
            continue

        # 表名白名单校验
        if change.table_name not in ALLOWED_TABLES:
            logger.warning(
                "sync_ingest.table_not_allowed",
                table=change.table_name,
                change_id=change.change_id,
            )
            response.errors.append(change.change_id)
            response.error_messages.append(
                f"{change.change_id}: table '{change.table_name}' not in allowlist"
            )
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
                is_conflict = await _check_cloud_version_newer(
                    db, change, changed_at
                )
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
            response.error_messages.append(
                f"{change.change_id}: db error — {type(exc).__name__}"
            )

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
            text("""
                SELECT change_id, table_name, record_id, operation,
                       data, tenant_id, changed_at
                FROM sync_cloud_changelog
                WHERE tenant_id = :tenant_id
                  AND changed_at > :since
                ORDER BY changed_at ASC
                LIMIT :size OFFSET :offset
            """),
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
        items.append(ChangeRecordOut(
            change_id=str(d.get("change_id", "")),
            table_name=d["table_name"],
            record_id=str(d["record_id"]),
            operation=d["operation"],
            data=data,
            tenant_id=d["tenant_id"],
            changed_at=changed_at_str,
        ))

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


# ─── 内部辅助函数 ─────────────────────────────────────────────────────────

async def _check_already_processed(db: AsyncSession, change_id: str) -> bool:
    """检查 change_id 是否已写入 sync_ingested_log（幂等去重）"""
    try:
        result = await db.execute(
            text("""
                SELECT 1 FROM sync_ingested_log
                WHERE change_id = :change_id
                LIMIT 1
            """),
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
    col_list = ", ".join(f'"{c}"' for c in columns)
    placeholders = ", ".join(f":{c}" for c in columns)
    update_set = ", ".join(
        f'"{c}" = EXCLUDED."{c}"' for c in columns if c != "id"
    )
    sql = (
        f'INSERT INTO "{change.table_name}" ({col_list}) '
        f"VALUES ({placeholders}) "
        f'ON CONFLICT (id) DO UPDATE SET {update_set}'
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
        text(f"""
            UPDATE "{change.table_name}"
            SET is_deleted = TRUE,
                updated_at = :updated_at
            WHERE id = :id
              AND tenant_id = :tenant_id
        """),
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
            text("""
                CREATE TABLE IF NOT EXISTS sync_ingested_log (
                    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    change_id   TEXT UNIQUE NOT NULL,
                    table_name  TEXT NOT NULL,
                    record_id   TEXT NOT NULL,
                    tenant_id   TEXT NOT NULL,
                    operation   TEXT NOT NULL,
                    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
        )
        await db.execute(
            text("""
                INSERT INTO sync_ingested_log
                    (change_id, table_name, record_id, tenant_id, operation, ingested_at)
                VALUES
                    (:change_id, :table_name, :record_id, :tenant_id, :operation, NOW())
                ON CONFLICT (change_id) DO NOTHING
            """),
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
