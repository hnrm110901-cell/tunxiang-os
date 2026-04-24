"""offline_sync_routes — Sprint A3 离线订单号同步入口

POST /api/v1/offline-orders/sync
  请求体：{ store_id, device_id, offline_orders: [{offline_order_id, cloud_order_id?}...] }
  语义：
    - 前端（商米 POS / iPad）恢复联网后批量提交离线 order_id 列表
    - 服务端为每个 offline_order_id 生成 cloud_order_id（若未随行携带）
    - 写入 offline_order_mapping 表 state=synced
    - 返回 offline_id → cloud_id 映射表
  审计：每条 sync 调用写一条 trade_audit_logs（A4 write_audit）

RBAC：
  - require_role("cashier", "store_manager", "admin")
  - Mac mini Flusher 使用 edge_service JWT（role=cashier）
  - X-Tenant-ID header vs user.tenant_id 必须一致

关联：
  - v270_offline_order_mapping 迁移
  - offline_order_mapping_service.OfflineOrderMappingService
  - A2 settle_retry 路由（idempotency_key=settle:{offline_order_id}）
"""

from __future__ import annotations

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..security.rbac import UserContext, require_role
from ..services.offline_order_id import parse_offline_order_id
from ..services.offline_order_mapping_service import (
    OfflineOrderMappingService,
)
from ..services.trade_audit_log import write_audit

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["offline-sync"])


# ─── Schema ──────────────────────────────────────────────────────────────────


class OfflineOrderEntry(BaseModel):
    """单条离线订单提交结构。"""

    offline_order_id: str = Field(..., min_length=1, max_length=128)
    cloud_order_id: Optional[str] = Field(None, max_length=64)


class OfflineSyncRequest(BaseModel):
    """批量提交离线订单请求体。"""

    tenant_id: str = Field(..., min_length=1)
    store_id: str = Field(..., min_length=1)
    device_id: str = Field(..., min_length=1, max_length=64)
    offline_orders: list[OfflineOrderEntry] = Field(..., min_length=1, max_length=100)


class OfflineSyncMappingOut(BaseModel):
    offline_order_id: str
    cloud_order_id: str
    state: str


class OfflineSyncResponse(BaseModel):
    ok: bool
    data: Optional[dict] = None
    error: Optional[dict] = None


# ─── 路由 ────────────────────────────────────────────────────────────────────


@router.post("/offline-orders/sync", response_model=OfflineSyncResponse)
async def sync_offline_orders(
    body: OfflineSyncRequest,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(require_role("cashier", "store_manager", "admin")),
) -> OfflineSyncResponse:
    """批量同步离线订单号到云端。

    行为：
      1. X-Tenant-ID / body.tenant_id / user.tenant_id 三方校验一致
      2. 逐条校验 offline_order_id 格式（`device_id:ms_epoch:counter`）
      3. 每条 upsert_mapping（pending）→ mark_synced（生成 cloud_order_id）
      4. 写 trade_audit_logs（整批一条 action=offline_sync.batch）
      5. 返回 offline → cloud 映射列表

    失败策略：
      - 任一条格式非法 → 400 INVALID_ORDER_ID（不部分提交，防错位映射）
      - 任一条 DB 失败 → 500 DB_ERROR，已写入的条目保留（幂等再试）
    """
    # ── 1. 租户一致性校验 ──────────────────────────────────────────────
    if x_tenant_id != body.tenant_id:
        logger.warning(
            "offline_sync_tenant_mismatch_header",
            header_tenant=x_tenant_id,
            body_tenant=body.tenant_id,
            user_id=user.user_id,
        )
        raise HTTPException(status_code=403, detail="TENANT_MISMATCH")

    if user.tenant_id and user.tenant_id != body.tenant_id:
        logger.warning(
            "offline_sync_tenant_mismatch_user",
            user_tenant=user.tenant_id,
            body_tenant=body.tenant_id,
            user_id=user.user_id,
        )
        raise HTTPException(status_code=403, detail="USER_TENANT_MISMATCH")

    # ── 2. 批量校验 offline_order_id 格式 ──────────────────────────────
    for entry in body.offline_orders:
        try:
            parsed = parse_offline_order_id(entry.offline_order_id)
        except ValueError as exc:
            logger.warning(
                "offline_sync_invalid_order_id",
                offline_order_id=entry.offline_order_id,
                error=str(exc),
            )
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_ORDER_ID", "message": str(exc)},
            )
        # device_id 必须与请求体 device_id 一致（防伪造）
        if parsed["device_id"] != body.device_id:
            logger.warning(
                "offline_sync_device_id_mismatch",
                parsed_device=parsed["device_id"],
                body_device=body.device_id,
            )
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "DEVICE_ID_MISMATCH",
                    "message": "offline_order_id 的 device_id 与请求不一致",
                },
            )

    # ── 3. 写入映射 ──────────────────────────────────────────────────
    svc = OfflineOrderMappingService(db=db, tenant_id=body.tenant_id)
    results: list[dict] = []

    try:
        for entry in body.offline_orders:
            # 服务端若未随行 cloud_order_id 则本地生成一枚 UUID v4
            cloud_id = entry.cloud_order_id or str(uuid.uuid4())

            # upsert pending（幂等：重复 offline_order_id 保持既有状态）
            await svc.upsert_mapping(
                store_id=body.store_id,
                device_id=body.device_id,
                offline_order_id=entry.offline_order_id,
            )
            # mark_synced
            await svc.mark_synced(
                offline_order_id=entry.offline_order_id,
                cloud_order_id=cloud_id,
            )
            results.append(
                {
                    "offline_order_id": entry.offline_order_id,
                    "cloud_order_id": cloud_id,
                    "state": "synced",
                }
            )
    except SQLAlchemyError as exc:
        logger.error(
            "offline_sync_db_error",
            tenant_id=body.tenant_id,
            store_id=body.store_id,
            error=str(exc),
            exc_info=True,
        )
        # 已写入的条目保留（幂等），告知客户端 partial 需重试
        return OfflineSyncResponse(
            ok=False,
            error={
                "code": "DB_ERROR",
                "message": "部分条目落库失败，请重试（幂等安全）",
                "partial": results,
            },
        )

    # ── 4. 审计留痕 ──────────────────────────────────────────────────
    try:
        await write_audit(
            db,
            tenant_id=body.tenant_id,
            store_id=body.store_id,
            user_id=user.user_id,
            user_role=user.role,
            action="offline_sync.batch",
            target_type="offline_order_mapping",
            target_id=str(len(results)),
            amount_fen=None,
            client_ip=user.client_ip,
        )
    except (SQLAlchemyError, ValueError) as exc:
        # 审计不阻塞主业务；记录但不回滚已 synced 的映射
        logger.error(
            "offline_sync_audit_write_failed",
            tenant_id=body.tenant_id,
            error=str(exc),
        )

    logger.info(
        "offline_sync_done",
        tenant_id=body.tenant_id,
        store_id=body.store_id,
        device_id=body.device_id,
        count=len(results),
    )

    return OfflineSyncResponse(
        ok=True,
        data={"synced": len(results), "mappings": results},
    )
