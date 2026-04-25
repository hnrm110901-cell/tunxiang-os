"""offline_sync_routes — Sprint A3 离线订单号同步入口

POST /api/v1/offline-orders/sync
  请求体：{ store_id, device_id, offline_orders: [{offline_order_id, cloud_order_id?}...] }
  语义：
    - 前端（商米 POS / iPad）恢复联网后批量提交离线 order_id 列表
    - 服务端为每个 offline_order_id 生成 cloud_order_id（若未随行携带）
    - 写入 offline_order_mapping 表 state=synced
    - 返回 offline_id → cloud_id 映射表
  审计：每条 sync 调用写一条 trade_audit_logs（A4 write_audit）

A3 §19 P1 增补（本次工单）：
  GET  /api/v1/offline-orders/pending
       —— 列出 pending 条目（manager/admin），分页

  以及 sync 路径补 dead_letter 触发链路：每条 entry 同步失败 →
  increment_attempts → 达 DEAD_LETTER_MAX_ATTEMPTS=20 → mark_dead_letter
  （reason='max_attempts_exceeded'）。

RBAC：
  - require_role("cashier", "store_manager", "admin")
  - Mac mini Flusher 使用 edge_service JWT（role=cashier）
  - X-Tenant-ID header vs user.tenant_id 必须一致

关联：
  - v270_offline_order_mapping 迁移
  - v275_offline_order_mapping_attempts 迁移（last_error_message）
  - offline_order_mapping_service.OfflineOrderMappingService
  - A2 settle_retry 路由（idempotency_key=settle:{offline_order_id}）
"""

from __future__ import annotations

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..security.rbac import UserContext, require_role
from ..services.offline_order_id import parse_offline_order_id
from ..services.offline_order_mapping_service import (
    DEAD_LETTER_MAX_ATTEMPTS,
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
    dead_lettered: list[str] = []  # 本批触发死信的 offline_order_id

    try:
        for entry in body.offline_orders:
            # ── A3 §19 致命级 #2 防双扣费：ACK 丢失重试场景 ──
            # 服务端首次 mark_synced 成功后响应在网络层丢失 → 客户端带原
            # offline_order_id 重试 → 若此处直接生成新 UUID 并 mark_synced，
            # 即便 service 层加了 state='pending' 守护，也会重新写一条
            # mapping（旧的 cloud_id_A 已落账，新 cloud_id_B 又生成一单）
            # → 同一离线单关联两个云端订单 → 资金双扣费。
            #
            # 正确做法：mark_synced 前先 SELECT 一次。如果条目已 synced，
            # 直接返回既有 cloud_order_id（**绝不**重新生成 UUID）。
            existing = await svc.get(entry.offline_order_id)
            if existing and existing.get("state") == "synced":
                existing_cloud_id = existing.get("cloud_order_id")
                if existing_cloud_id:
                    logger.info(
                        "offline_sync_idempotent_replay",
                        offline_order_id=entry.offline_order_id,
                        cloud_order_id=existing_cloud_id,
                        tenant_id=body.tenant_id,
                    )
                    results.append(
                        {
                            "offline_order_id": entry.offline_order_id,
                            "cloud_order_id": existing_cloud_id,
                            "state": "synced",
                        }
                    )
                    continue

            # ── A3 §19 致命级 #1 dead_letter 触发链路 ──
            # 单条 entry 已是 dead_letter 状态：跳过（不再覆盖 + 不重置计数）
            # 等待店长人工 resolve / retry 路径推回 pending
            if existing and existing.get("state") == "dead_letter":
                logger.warning(
                    "offline_sync_skipped_dead_letter",
                    offline_order_id=entry.offline_order_id,
                    tenant_id=body.tenant_id,
                )
                results.append(
                    {
                        "offline_order_id": entry.offline_order_id,
                        "cloud_order_id": existing.get("cloud_order_id") or "",
                        "state": "dead_letter",
                    }
                )
                continue

            # 服务端若未随行 cloud_order_id 则本地生成一枚 UUID v4
            cloud_id = entry.cloud_order_id or str(uuid.uuid4())

            # 按 entry 兜底捕 SQLAlchemyError（不含 IntegrityError；后者上抛
            # 至外层批级 catch 走幂等成功分支）。任一 entry 同步失败时：
            #   1) increment_attempts — sync_attempts +1，记录 last_error_message
            #   2) 阈值检查：sync_attempts >= DEAD_LETTER_MAX_ATTEMPTS 则
            #      mark_dead_letter('max_attempts_exceeded')
            #   3) 失败后**重新抛出**让外层 SQLAlchemyError handler 报 DB_ERROR
            #      （C2 OperationalError 测试场景行为不变）
            try:
                # upsert pending（幂等：重复 offline_order_id 保持既有状态）
                await svc.upsert_mapping(
                    store_id=body.store_id,
                    device_id=body.device_id,
                    offline_order_id=entry.offline_order_id,
                )
                # mark_synced：返回 False 说明并发竞争被另一个请求抢先 synced
                # 重新读取最新 cloud_order_id 复用（不报错、不再生成新 UUID）
                advanced = await svc.mark_synced(
                    offline_order_id=entry.offline_order_id,
                    cloud_order_id=cloud_id,
                )
            except IntegrityError:
                raise  # 让外层批级 IntegrityError handler 接（C1 测试）
            except SQLAlchemyError as exc:
                # 记录失败计数 + 必要时升级为死信。任一步本身再失败，
                # 用 best-effort try/except 兜底：计数链路绝不应因二次故障
                # 而吞掉主报错。
                attempts_now = await _record_sync_failure(
                    svc=svc,
                    offline_order_id=entry.offline_order_id,
                    error_summary=type(exc).__name__,
                )
                if attempts_now >= DEAD_LETTER_MAX_ATTEMPTS:
                    await _mark_dead_letter_safe(
                        svc=svc,
                        offline_order_id=entry.offline_order_id,
                        attempts=attempts_now,
                    )
                    dead_lettered.append(entry.offline_order_id)
                raise  # 让外层 SQLAlchemyError handler 接（C2 测试）

            if not advanced:
                latest = await svc.get(entry.offline_order_id)
                if latest and latest.get("cloud_order_id"):
                    cloud_id = latest["cloud_order_id"]
                    logger.info(
                        "offline_sync_lost_race_reuse_cloud_id",
                        offline_order_id=entry.offline_order_id,
                        cloud_order_id=cloud_id,
                        tenant_id=body.tenant_id,
                    )

            results.append(
                {
                    "offline_order_id": entry.offline_order_id,
                    "cloud_order_id": cloud_id,
                    "state": "synced",
                }
            )
    except IntegrityError as exc:
        # 唯一约束撞车（并发同 offline_order_id 提交）= 幂等成功
        # 不当作 DB_ERROR 报错；已写入的条目保留，下一轮重试将走"既有 synced"
        # 分支返回旧 cloud_order_id。这里给客户端 partial 让它带原参数重试。
        await db.rollback()
        logger.warning(
            "offline_sync_integrity_conflict",
            tenant_id=body.tenant_id,
            store_id=body.store_id,
            error=str(exc),
        )
        return OfflineSyncResponse(
            ok=True,
            data={
                "synced": len(results),
                "mappings": results,
                "partial": True,
                "reason": "INTEGRITY_CONFLICT_RETRY_SAFE",
            },
        )
    except SQLAlchemyError as exc:
        logger.error(
            "offline_sync_db_error",
            tenant_id=body.tenant_id,
            store_id=body.store_id,
            error=str(exc),
            dead_lettered_count=len(dead_lettered),
            exc_info=True,
        )
        # 已写入的条目保留（幂等），告知客户端 partial 需重试
        return OfflineSyncResponse(
            ok=False,
            error={
                "code": "DB_ERROR",
                "message": "部分条目落库失败，请重试（幂等安全）",
                "partial": results,
                "dead_lettered": dead_lettered,
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
        data={
            "synced": len(results),
            "mappings": results,
            "dead_lettered": dead_lettered,
        },
    )


# ─── 内部 helper：dead_letter 触发链路 ──────────────────────────────────────


async def _record_sync_failure(
    *,
    svc: OfflineOrderMappingService,
    offline_order_id: str,
    error_summary: str,
) -> int:
    """best-effort 累加 sync_attempts；记录 last_error_message。

    返回新的 sync_attempts 值（用于阈值判断）。
    任一步骤失败均吞掉日志（防御链路绝不能因二次故障而抢走主报错）。

    Returns:
        int: 累加后的 sync_attempts；二次故障兜底返回 0（不触发死信）
    """
    try:
        return await svc.increment_attempts(
            offline_order_id=offline_order_id,
            last_error=error_summary[:500],
        )
    except SQLAlchemyError as exc:
        logger.warning(
            "offline_sync_increment_attempts_failed_secondary",
            offline_order_id=offline_order_id,
            secondary_error=str(exc),
        )
        return 0


async def _mark_dead_letter_safe(
    *,
    svc: OfflineOrderMappingService,
    offline_order_id: str,
    attempts: int,
) -> None:
    """best-effort 把单条 entry 升级为死信。

    路由层只在 sync_attempts >= DEAD_LETTER_MAX_ATTEMPTS 时调用此 helper。
    reason='max_attempts_exceeded:{attempts}' 便于运维侧反查阈值触发瞬间。
    """
    reason = f"max_attempts_exceeded:{attempts}"
    try:
        await svc.mark_dead_letter(
            offline_order_id=offline_order_id,
            reason=reason,
        )
    except SQLAlchemyError as exc:
        logger.error(
            "offline_sync_mark_dead_letter_failed_secondary",
            offline_order_id=offline_order_id,
            attempts=attempts,
            secondary_error=str(exc),
        )


# ─── A3 §19 P1：dead_letter 人工面板 HTTP 入口 ──────────────────────────────


class OfflineMappingItem(BaseModel):
    """list_pending / list_dead_letter 单条返回结构（共享 schema）。"""

    offline_order_id: str
    cloud_order_id: Optional[str] = None
    store_id: str
    device_id: str
    state: str
    sync_attempts: int = 0
    dead_letter_reason: Optional[str] = None
    last_error_message: Optional[str] = None


class OfflineMappingPage(BaseModel):
    """分页响应负载。"""

    items: list[OfflineMappingItem]
    total: int
    page: int
    size: int


class OfflineMappingPageResponse(BaseModel):
    ok: bool
    data: Optional[OfflineMappingPage] = None
    error: Optional[dict] = None


def _enforce_query_tenant(
    *,
    query_tenant: str,
    header_tenant: str,
    user: UserContext,
    path: str,
) -> None:
    """GET 路径下的三方一致性（query string 替代 body）。"""
    if header_tenant != query_tenant:
        logger.warning(
            "offline_admin_tenant_mismatch_header",
            path=path,
            header_tenant=header_tenant,
            query_tenant=query_tenant,
            user_id=user.user_id,
        )
        raise HTTPException(status_code=403, detail="TENANT_MISMATCH")
    if user.tenant_id and user.tenant_id != query_tenant:
        logger.warning(
            "offline_admin_tenant_mismatch_user",
            path=path,
            user_tenant=user.tenant_id,
            query_tenant=query_tenant,
            user_id=user.user_id,
        )
        raise HTTPException(status_code=403, detail="USER_TENANT_MISMATCH")


def _row_to_item(row: dict) -> OfflineMappingItem:
    return OfflineMappingItem(
        offline_order_id=row.get("offline_order_id", ""),
        cloud_order_id=(str(row["cloud_order_id"]) if row.get("cloud_order_id") else None),
        store_id=str(row.get("store_id", "")),
        device_id=row.get("device_id", ""),
        state=row.get("state", ""),
        sync_attempts=int(row.get("sync_attempts") or 0),
        dead_letter_reason=row.get("dead_letter_reason"),
        last_error_message=row.get("last_error_message"),
    )


@router.get("/offline-orders/pending", response_model=OfflineMappingPageResponse)
async def list_pending_offline_orders(
    request: Request,
    tenant_id: str = Query(..., min_length=1),
    store_id: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
    user: UserContext = Depends(require_role("store_manager", "admin", "manager")),
) -> OfflineMappingPageResponse:
    """列出当前租户 + 门店下 state=pending 的离线映射条目。

    用于运营侧观测同步 backlog；店长/总部 admin 可查。
    """
    _enforce_query_tenant(
        query_tenant=tenant_id,
        header_tenant=x_tenant_id,
        user=user,
        path="/offline-orders/pending",
    )

    svc = OfflineOrderMappingService(db=db, tenant_id=tenant_id)
    try:
        # service.list_pending 用 limit；页面分页用 size*page 做近似 offset
        # （pending 数量通常小，无需复杂全表 count）
        all_rows = await svc.list_pending(store_id=store_id, limit=500)
    except SQLAlchemyError as exc:
        logger.error(
            "offline_orders_list_pending_db_error",
            tenant_id=tenant_id,
            store_id=store_id,
            error=str(exc),
        )
        return OfflineMappingPageResponse(
            ok=False,
            error={"code": "DB_ERROR", "message": "查询失败"},
        )

    total = len(all_rows)
    start = (page - 1) * size
    end = start + size
    page_rows = all_rows[start:end]

    return OfflineMappingPageResponse(
        ok=True,
        data=OfflineMappingPage(
            items=[_row_to_item(r) for r in page_rows],
            total=total,
            page=page,
            size=size,
        ),
    )


