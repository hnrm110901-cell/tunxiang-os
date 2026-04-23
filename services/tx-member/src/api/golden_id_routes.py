"""全渠道会员 Golden ID 映射 API — Y-D9

端点列表：
  POST   /api/v1/member/golden-id/bind                   绑定渠道 openid 到 Golden ID（手机号优先匹配）
  DELETE /api/v1/member/golden-id/unbind                 解绑渠道
  POST   /api/v1/member/golden-id/merge                  手动合并两个 Golden ID
  GET    /api/v1/member/golden-id/conflicts               列出未解决冲突（分页）
  POST   /api/v1/member/golden-id/conflicts/{id}/resolve 解决单个冲突
  GET    /api/v1/member/golden-id/stats                  各渠道绑定数量统计
  GET    /api/v1/member/golden-id/{customer_id}/channels  某顾客的所有渠道绑定
  POST   /api/v1/member/golden-id/batch-import           批量导入渠道绑定（最多 500 条/次）

关键逻辑：
  - 手机号优先合并：bind 时先查 phone_hash，有则合并到同一 Golden ID
  - 冲突处理：同一 openid 对应多个 phone_hash，标记为 conflict，需人工解决
  - 幂等性：重复绑定同一 openid 返回现有记录（不报错）
  - 隐私保护：存储 phone_hash = sha256(phone+SALT)，不明文存电话号
"""

import hashlib
import os
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ..db import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/member/golden-id", tags=["golden-id"])

# 手机号哈希盐（生产环境从环境变量注入）
_PHONE_HASH_SALT: str = os.environ.get("PHONE_HASH_SALT", "tx-member-phone-salt-v1")

# 支持的渠道类型
VALID_CHANNEL_TYPES = {"meituan", "eleme", "douyin", "wechat"}


# ── 工具函数 ─────────────────────────────────────────────────────────────────


def _hash_phone(phone: str) -> str:
    """sha256(phone + salt)，隐私保护"""
    raw = f"{phone}{_PHONE_HASH_SALT}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def _set_tenant(db, tenant_id: str) -> None:
    """设置 RLS app.tenant_id"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ── 请求/响应模型 ─────────────────────────────────────────────────────────────


class BindChannelReq(BaseModel):
    customer_id: Optional[str] = Field(None, description="可为空，若提供 phone 则优先按手机号查找已有 customer")
    channel_type: str = Field(description="meituan/eleme/douyin/wechat")
    channel_openid: str = Field(min_length=1, max_length=128)
    phone: Optional[str] = Field(None, description="手机号（明文，服务端哈希后存储）")
    extra: Optional[dict] = None

    @field_validator("channel_type")
    @classmethod
    def validate_channel_type(cls, v: str) -> str:
        if v not in VALID_CHANNEL_TYPES:
            raise ValueError(f"channel_type 必须是 {VALID_CHANNEL_TYPES} 之一")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and (len(v) < 7 or len(v) > 20):
            raise ValueError("手机号长度不合法")
        return v


class UnbindChannelReq(BaseModel):
    channel_type: str
    channel_openid: str

    @field_validator("channel_type")
    @classmethod
    def validate_channel_type(cls, v: str) -> str:
        if v not in VALID_CHANNEL_TYPES:
            raise ValueError(f"channel_type 必须是 {VALID_CHANNEL_TYPES} 之一")
        return v


class MergeGoldenIDReq(BaseModel):
    source_customer_id: str = Field(description="被合并方（将被废弃的 ID）")
    target_customer_id: str = Field(description="保留方（合并目标）")
    operator_id: Optional[str] = None
    merge_reason: str = Field(default="manual", description="phone_match/manual/auto_rule")


class ResolveConflictReq(BaseModel):
    keep_customer_id: str = Field(description="冲突解决后保留的 customer_id")
    operator_id: Optional[str] = None


class BatchImportItem(BaseModel):
    channel_type: str
    channel_openid: str = Field(min_length=1, max_length=128)
    phone: Optional[str] = None
    extra: Optional[dict] = None

    @field_validator("channel_type")
    @classmethod
    def validate_channel_type(cls, v: str) -> str:
        if v not in VALID_CHANNEL_TYPES:
            raise ValueError(f"channel_type 必须是 {VALID_CHANNEL_TYPES} 之一")
        return v


class BatchImportReq(BaseModel):
    items: list[BatchImportItem] = Field(max_length=500)


# ── 端点实现 ──────────────────────────────────────────────────────────────────


@router.post("/bind")
async def bind_channel(
    req: BindChannelReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """绑定渠道 openid 到 Golden ID（手机号优先匹配合并）

    流程：
    1. 幂等检查：若 openid 已绑定，直接返回现有记录
    2. 手机号优先：若提供 phone，查找已有相同 phone_hash 的 customer_id
    3. 若找到同 phone 的 customer，发起自动合并
    4. 否则使用传入 customer_id 或新建
    """
    try:
        tenant_uuid = uuid.UUID(x_tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"X-Tenant-ID 格式错误: {x_tenant_id}") from e

    phone_hash: Optional[str] = _hash_phone(req.phone) if req.phone else None

    async for db in get_db():
        try:
            await _set_tenant(db, x_tenant_id)

            # ── 1. 幂等检查 ──────────────────────────────────────────────────
            existing = await db.execute(
                text("""
                    SELECT id, customer_id, binding_status, phone_hash
                    FROM member_channel_bindings
                    WHERE tenant_id = :tenant_id
                      AND channel_type = :channel_type
                      AND channel_openid = :channel_openid
                """),
                {
                    "tenant_id": str(tenant_uuid),
                    "channel_type": req.channel_type,
                    "channel_openid": req.channel_openid,
                },
            )
            row = existing.fetchone()
            if row:
                logger.info(
                    "golden_id_bind_idempotent",
                    tenant_id=x_tenant_id,
                    channel_type=req.channel_type,
                    binding_id=str(row.id),
                )
                return {
                    "ok": True,
                    "data": {
                        "binding_id": str(row.id),
                        "customer_id": str(row.customer_id),
                        "binding_status": row.binding_status,
                        "idempotent": True,
                    },
                    "error": {},
                }

            # ── 2. 手机号优先合并 ─────────────────────────────────────────────
            resolved_customer_id: Optional[uuid.UUID] = None
            merge_happened = False

            if phone_hash:
                phone_match = await db.execute(
                    text("""
                        SELECT customer_id, COUNT(DISTINCT customer_id) AS cnt
                        FROM member_channel_bindings
                        WHERE tenant_id = :tenant_id
                          AND phone_hash = :phone_hash
                          AND binding_status = 'active'
                        GROUP BY customer_id
                        LIMIT 2
                    """),
                    {"tenant_id": str(tenant_uuid), "phone_hash": phone_hash},
                )
                phone_rows = phone_match.fetchall()

                if len(phone_rows) == 1:
                    # 唯一匹配：直接复用该 customer_id
                    resolved_customer_id = phone_rows[0].customer_id
                    merge_happened = True
                    logger.info(
                        "golden_id_phone_match_merge",
                        tenant_id=x_tenant_id,
                        merged_into=str(resolved_customer_id),
                    )
                elif len(phone_rows) > 1:
                    # 多个匹配：标记为冲突，稍后写入 conflict 状态
                    logger.warning(
                        "golden_id_phone_conflict",
                        tenant_id=x_tenant_id,
                        phone_hash=phone_hash,
                        matched_count=len(phone_rows),
                    )

            # ── 3. 确定最终 customer_id ──────────────────────────────────────
            if resolved_customer_id is None:
                if req.customer_id:
                    try:
                        resolved_customer_id = uuid.UUID(req.customer_id)
                    except ValueError as e:
                        raise HTTPException(status_code=400, detail=f"customer_id 格式错误: {req.customer_id}") from e
                else:
                    resolved_customer_id = uuid.uuid4()

            # 判断是否需要标记为冲突（phone_hash 已存在不同 customer_id）
            binding_status = "active"
            if phone_hash and not merge_happened:
                conflict_check = await db.execute(
                    text("""
                        SELECT COUNT(*) AS cnt
                        FROM member_channel_bindings
                        WHERE tenant_id = :tenant_id
                          AND phone_hash = :phone_hash
                          AND customer_id != :customer_id
                          AND binding_status = 'active'
                    """),
                    {
                        "tenant_id": str(tenant_uuid),
                        "phone_hash": phone_hash,
                        "customer_id": str(resolved_customer_id),
                    },
                )
                if (conflict_check.scalar() or 0) > 0:
                    binding_status = "conflict"

            # ── 4. 写入绑定记录 ───────────────────────────────────────────────
            insert_result = await db.execute(
                text("""
                    INSERT INTO member_channel_bindings
                        (tenant_id, customer_id, channel_type, channel_openid,
                         phone_hash, binding_status, extra)
                    VALUES
                        (:tenant_id, :customer_id, :channel_type, :channel_openid,
                         :phone_hash, :binding_status, :extra::jsonb)
                    RETURNING id, customer_id, binding_status
                """),
                {
                    "tenant_id": str(tenant_uuid),
                    "customer_id": str(resolved_customer_id),
                    "channel_type": req.channel_type,
                    "channel_openid": req.channel_openid,
                    "phone_hash": phone_hash,
                    "binding_status": binding_status,
                    "extra": str(req.extra) if req.extra else "null",
                },
            )
            new_row = insert_result.fetchone()
            await db.commit()

            logger.info(
                "golden_id_bound",
                tenant_id=x_tenant_id,
                binding_id=str(new_row.id),
                channel_type=req.channel_type,
                binding_status=binding_status,
                merge_happened=merge_happened,
            )
            return {
                "ok": True,
                "data": {
                    "binding_id": str(new_row.id),
                    "customer_id": str(new_row.customer_id),
                    "binding_status": new_row.binding_status,
                    "merge_happened": merge_happened,
                    "idempotent": False,
                },
                "error": {},
            }

        except (SQLAlchemyError, ValueError) as e:
            await db.rollback()
            logger.error("golden_id_bind_error", error=str(e), exc_info=True)
            raise HTTPException(status_code=500, detail="绑定失败") from e


@router.delete("/unbind")
async def unbind_channel(
    req: UnbindChannelReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """解绑渠道 openid"""
    try:
        tenant_uuid = uuid.UUID(x_tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"X-Tenant-ID 格式错误: {x_tenant_id}") from e

    async for db in get_db():
        try:
            await _set_tenant(db, x_tenant_id)

            result = await db.execute(
                text("""
                    UPDATE member_channel_bindings
                    SET binding_status = 'unbound',
                        updated_at = NOW()
                    WHERE tenant_id = :tenant_id
                      AND channel_type = :channel_type
                      AND channel_openid = :channel_openid
                      AND binding_status != 'unbound'
                    RETURNING id
                """),
                {
                    "tenant_id": str(tenant_uuid),
                    "channel_type": req.channel_type,
                    "channel_openid": req.channel_openid,
                },
            )
            row = result.fetchone()
            await db.commit()

            if not row:
                raise HTTPException(status_code=404, detail="绑定记录不存在或已解绑")

            logger.info(
                "golden_id_unbound",
                tenant_id=x_tenant_id,
                binding_id=str(row.id),
            )
            return {"ok": True, "data": {"binding_id": str(row.id)}, "error": {}}

        except SQLAlchemyError as e:
            await db.rollback()
            logger.error("golden_id_unbind_error", error=str(e), exc_info=True)
            raise HTTPException(status_code=500, detail="解绑失败") from e


@router.post("/merge")
async def merge_golden_ids(
    req: MergeGoldenIDReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """手动合并两个 Golden ID：将 source_customer_id 的所有渠道绑定迁移到 target_customer_id"""
    try:
        tenant_uuid = uuid.UUID(x_tenant_id)
        source_uuid = uuid.UUID(req.source_customer_id)
        target_uuid = uuid.UUID(req.target_customer_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {e}") from e

    if source_uuid == target_uuid:
        raise HTTPException(status_code=400, detail="source 和 target 不能相同")

    async for db in get_db():
        try:
            await _set_tenant(db, x_tenant_id)

            # 迁移 source → target 的所有绑定
            migrate_result = await db.execute(
                text("""
                    UPDATE member_channel_bindings
                    SET customer_id = :target_customer_id,
                        updated_at = NOW()
                    WHERE tenant_id = :tenant_id
                      AND customer_id = :source_customer_id
                      AND binding_status = 'active'
                    RETURNING id
                """),
                {
                    "tenant_id": str(tenant_uuid),
                    "source_customer_id": str(source_uuid),
                    "target_customer_id": str(target_uuid),
                },
            )
            migrated_ids = [str(r.id) for r in migrate_result.fetchall()]

            # 写合并日志
            await db.execute(
                text("""
                    INSERT INTO golden_id_merge_logs
                        (tenant_id, source_customer_id, target_customer_id,
                         merge_reason, merge_metadata, operator_id)
                    VALUES
                        (:tenant_id, :source, :target, :reason,
                         :metadata::jsonb, :operator_id)
                """),
                {
                    "tenant_id": str(tenant_uuid),
                    "source": str(source_uuid),
                    "target": str(target_uuid),
                    "reason": req.merge_reason,
                    "metadata": f'{{"migrated_binding_count": {len(migrated_ids)}}}',
                    "operator_id": req.operator_id,
                },
            )
            await db.commit()

            logger.info(
                "golden_id_merged",
                tenant_id=x_tenant_id,
                source=str(source_uuid),
                target=str(target_uuid),
                migrated_count=len(migrated_ids),
                reason=req.merge_reason,
            )
            return {
                "ok": True,
                "data": {
                    "source_customer_id": str(source_uuid),
                    "target_customer_id": str(target_uuid),
                    "migrated_binding_count": len(migrated_ids),
                },
                "error": {},
            }

        except SQLAlchemyError as e:
            await db.rollback()
            logger.error("golden_id_merge_error", error=str(e), exc_info=True)
            raise HTTPException(status_code=500, detail="合并失败") from e


@router.get("/conflicts")
async def list_conflicts(
    page: int = 1,
    size: int = 20,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """列出未解决的渠道绑定冲突（分页）"""
    try:
        tenant_uuid = uuid.UUID(x_tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"X-Tenant-ID 格式错误: {x_tenant_id}") from e

    if size > 100:
        raise HTTPException(status_code=400, detail="size 最大 100")
    offset = (page - 1) * size

    async for db in get_db():
        try:
            await _set_tenant(db, x_tenant_id)

            total_result = await db.execute(
                text("""
                    SELECT COUNT(*) AS total
                    FROM member_channel_bindings
                    WHERE tenant_id = :tenant_id
                      AND binding_status = 'conflict'
                """),
                {"tenant_id": str(tenant_uuid)},
            )
            total = total_result.scalar() or 0

            items_result = await db.execute(
                text("""
                    SELECT id, customer_id, channel_type, channel_openid,
                           phone_hash, created_at
                    FROM member_channel_bindings
                    WHERE tenant_id = :tenant_id
                      AND binding_status = 'conflict'
                    ORDER BY created_at DESC
                    LIMIT :size OFFSET :offset
                """),
                {"tenant_id": str(tenant_uuid), "size": size, "offset": offset},
            )
            items = [
                {
                    "id": str(r.id),
                    "customer_id": str(r.customer_id),
                    "channel_type": r.channel_type,
                    "channel_openid": r.channel_openid,
                    "phone_hash": r.phone_hash,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in items_result.fetchall()
            ]

            return {
                "ok": True,
                "data": {"items": items, "total": total, "page": page, "size": size},
                "error": {},
            }

        except SQLAlchemyError as e:
            logger.error("golden_id_list_conflicts_error", error=str(e), exc_info=True)
            raise HTTPException(status_code=500, detail="查询冲突失败") from e


@router.post("/conflicts/{conflict_id}/resolve")
async def resolve_conflict(
    conflict_id: str,
    req: ResolveConflictReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """解决单个冲突：指定保留哪个 customer_id，其余同 openid 的绑定标记为 unbound"""
    try:
        tenant_uuid = uuid.UUID(x_tenant_id)
        conflict_uuid = uuid.UUID(conflict_id)
        keep_uuid = uuid.UUID(req.keep_customer_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {e}") from e

    async for db in get_db():
        try:
            await _set_tenant(db, x_tenant_id)

            # 查冲突记录
            conflict_row_result = await db.execute(
                text("""
                    SELECT id, channel_type, channel_openid
                    FROM member_channel_bindings
                    WHERE id = :conflict_id
                      AND tenant_id = :tenant_id
                      AND binding_status = 'conflict'
                """),
                {"conflict_id": str(conflict_uuid), "tenant_id": str(tenant_uuid)},
            )
            conflict_row = conflict_row_result.fetchone()
            if not conflict_row:
                raise HTTPException(status_code=404, detail="冲突记录不存在或已解决")

            # 将同 openid 的其他冲突绑定设为 unbound，保留的设为 active
            await db.execute(
                text("""
                    UPDATE member_channel_bindings
                    SET binding_status = CASE
                            WHEN customer_id = :keep_customer_id THEN 'active'
                            ELSE 'unbound'
                        END,
                        conflict_resolved_at = NOW(),
                        conflict_resolved_by = :operator_id,
                        updated_at = NOW()
                    WHERE tenant_id = :tenant_id
                      AND channel_type = :channel_type
                      AND channel_openid = :channel_openid
                      AND binding_status = 'conflict'
                """),
                {
                    "tenant_id": str(tenant_uuid),
                    "keep_customer_id": str(keep_uuid),
                    "channel_type": conflict_row.channel_type,
                    "channel_openid": conflict_row.channel_openid,
                    "operator_id": req.operator_id,
                },
            )
            await db.commit()

            logger.info(
                "golden_id_conflict_resolved",
                tenant_id=x_tenant_id,
                conflict_id=conflict_id,
                kept_customer_id=str(keep_uuid),
                operator_id=req.operator_id,
            )
            return {
                "ok": True,
                "data": {
                    "conflict_id": conflict_id,
                    "kept_customer_id": str(keep_uuid),
                },
                "error": {},
            }

        except SQLAlchemyError as e:
            await db.rollback()
            logger.error("golden_id_resolve_conflict_error", error=str(e), exc_info=True)
            raise HTTPException(status_code=500, detail="解决冲突失败") from e


@router.get("/stats")
async def get_channel_stats(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """各渠道绑定数量统计"""
    try:
        tenant_uuid = uuid.UUID(x_tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"X-Tenant-ID 格式错误: {x_tenant_id}") from e

    async for db in get_db():
        try:
            await _set_tenant(db, x_tenant_id)

            result = await db.execute(
                text("""
                    SELECT
                        channel_type,
                        COUNT(*) FILTER (WHERE binding_status = 'active') AS active_count,
                        COUNT(*) FILTER (WHERE binding_status = 'conflict') AS conflict_count,
                        COUNT(*) FILTER (WHERE binding_status = 'unbound') AS unbound_count,
                        COUNT(DISTINCT customer_id) FILTER (WHERE binding_status = 'active') AS unique_customers
                    FROM member_channel_bindings
                    WHERE tenant_id = :tenant_id
                    GROUP BY channel_type
                    ORDER BY channel_type
                """),
                {"tenant_id": str(tenant_uuid)},
            )
            rows = result.fetchall()

            stats_by_channel = {
                r.channel_type: {
                    "active_count": r.active_count,
                    "conflict_count": r.conflict_count,
                    "unbound_count": r.unbound_count,
                    "unique_customers": r.unique_customers,
                }
                for r in rows
            }

            # 补全所有渠道（即使为 0）
            for ch in VALID_CHANNEL_TYPES:
                if ch not in stats_by_channel:
                    stats_by_channel[ch] = {
                        "active_count": 0,
                        "conflict_count": 0,
                        "unbound_count": 0,
                        "unique_customers": 0,
                    }

            total_active = sum(v["active_count"] for v in stats_by_channel.values())
            total_conflicts = sum(v["conflict_count"] for v in stats_by_channel.values())

            return {
                "ok": True,
                "data": {
                    "by_channel": stats_by_channel,
                    "total_active_bindings": total_active,
                    "total_conflicts": total_conflicts,
                },
                "error": {},
            }

        except SQLAlchemyError as e:
            logger.error("golden_id_stats_error", error=str(e), exc_info=True)
            raise HTTPException(status_code=500, detail="统计失败") from e


@router.get("/{customer_id}/channels")
async def get_customer_channels(
    customer_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """查询某顾客的所有渠道绑定"""
    try:
        tenant_uuid = uuid.UUID(x_tenant_id)
        customer_uuid = uuid.UUID(customer_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {e}") from e

    async for db in get_db():
        try:
            await _set_tenant(db, x_tenant_id)

            result = await db.execute(
                text("""
                    SELECT id, channel_type, channel_openid, binding_status,
                           created_at, updated_at
                    FROM member_channel_bindings
                    WHERE tenant_id = :tenant_id
                      AND customer_id = :customer_id
                    ORDER BY created_at DESC
                """),
                {"tenant_id": str(tenant_uuid), "customer_id": str(customer_uuid)},
            )
            rows = result.fetchall()
            channels = [
                {
                    "id": str(r.id),
                    "channel_type": r.channel_type,
                    "channel_openid": r.channel_openid,
                    "binding_status": r.binding_status,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in rows
            ]

            return {
                "ok": True,
                "data": {
                    "customer_id": str(customer_uuid),
                    "channels": channels,
                    "total": len(channels),
                },
                "error": {},
            }

        except SQLAlchemyError as e:
            logger.error("golden_id_get_channels_error", error=str(e), exc_info=True)
            raise HTTPException(status_code=500, detail="查询渠道绑定失败") from e


@router.post("/batch-import")
async def batch_import_bindings(
    req: BatchImportReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
):
    """批量导入渠道绑定（最多 500 条/次）

    每条记录独立处理：成功/跳过（幂等）/失败分别计数
    """
    try:
        tenant_uuid = uuid.UUID(x_tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"X-Tenant-ID 格式错误: {x_tenant_id}") from e

    if not req.items:
        raise HTTPException(status_code=400, detail="items 不能为空")

    success_count = 0
    skipped_count = 0
    failed_items: list[dict] = []

    async for db in get_db():
        try:
            await _set_tenant(db, x_tenant_id)

            for idx, item in enumerate(req.items):
                phone_hash: Optional[str] = _hash_phone(item.phone) if item.phone else None
                try:
                    # 幂等检查
                    existing = await db.execute(
                        text("""
                            SELECT id FROM member_channel_bindings
                            WHERE tenant_id = :tenant_id
                              AND channel_type = :channel_type
                              AND channel_openid = :channel_openid
                        """),
                        {
                            "tenant_id": str(tenant_uuid),
                            "channel_type": item.channel_type,
                            "channel_openid": item.channel_openid,
                        },
                    )
                    if existing.fetchone():
                        skipped_count += 1
                        continue

                    # 手机号查已有 customer
                    resolved_customer_id = uuid.uuid4()
                    if phone_hash:
                        phone_match = await db.execute(
                            text("""
                                SELECT customer_id
                                FROM member_channel_bindings
                                WHERE tenant_id = :tenant_id
                                  AND phone_hash = :phone_hash
                                  AND binding_status = 'active'
                                LIMIT 1
                            """),
                            {"tenant_id": str(tenant_uuid), "phone_hash": phone_hash},
                        )
                        phone_row = phone_match.fetchone()
                        if phone_row:
                            resolved_customer_id = phone_row.customer_id

                    await db.execute(
                        text("""
                            INSERT INTO member_channel_bindings
                                (tenant_id, customer_id, channel_type, channel_openid,
                                 phone_hash, binding_status, extra)
                            VALUES
                                (:tenant_id, :customer_id, :channel_type, :channel_openid,
                                 :phone_hash, 'active', :extra::jsonb)
                        """),
                        {
                            "tenant_id": str(tenant_uuid),
                            "customer_id": str(resolved_customer_id),
                            "channel_type": item.channel_type,
                            "channel_openid": item.channel_openid,
                            "phone_hash": phone_hash,
                            "extra": str(item.extra) if item.extra else "null",
                        },
                    )
                    success_count += 1

                except SQLAlchemyError as e:
                    failed_items.append({"index": idx, "error": str(e)})
                    logger.warning(
                        "batch_import_item_failed",
                        index=idx,
                        channel_type=item.channel_type,
                        error=str(e),
                    )

            await db.commit()

            logger.info(
                "golden_id_batch_import_done",
                tenant_id=x_tenant_id,
                total=len(req.items),
                success=success_count,
                skipped=skipped_count,
                failed=len(failed_items),
            )
            return {
                "ok": True,
                "data": {
                    "total": len(req.items),
                    "success_count": success_count,
                    "skipped_count": skipped_count,
                    "failed_count": len(failed_items),
                    "failed_items": failed_items,
                },
                "error": {},
            }

        except SQLAlchemyError as e:
            await db.rollback()
            logger.error("golden_id_batch_import_error", error=str(e), exc_info=True)
            raise HTTPException(status_code=500, detail="批量导入失败") from e
