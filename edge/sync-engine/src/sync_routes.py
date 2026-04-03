"""sync_routes.py — 离线同步 API 路由

端点：
  POST /sync/push         — 推送本地离线订单到云端
  GET  /sync/pull         — 拉取云端变更（菜单/会员/配置）
  GET  /sync/status       — 查询设备同步状态
  POST /sync/checkpoint   — 更新同步检查点

所有端点要求 X-Tenant-ID header。
统一响应格式：{"ok": bool, "data": {}, "error": {}}
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Request
from offline_sync_service import OfflineSyncService, SyncResult, SyncStatus
from pydantic import BaseModel, Field, field_validator

logger = structlog.get_logger()

router = APIRouter(prefix="/sync", tags=["sync"])

# ─── 依赖：获取 OfflineSyncService 实例 ───────────────────────────────────

def _get_service(request: Request) -> OfflineSyncService:
    """从 app.state 获取已初始化的 OfflineSyncService 实例"""
    svc: OfflineSyncService | None = getattr(request.app.state, "offline_sync_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="OfflineSyncService not initialized")
    return svc


def _require_tenant(x_tenant_id: str | None) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return x_tenant_id


# ─── 请求/响应模型 ────────────────────────────────────────────────────────

class OrderItemPayload(BaseModel):
    item_name: str
    quantity: int
    unit_price_fen: int = Field(ge=0, description="单价（分）")
    subtotal_fen: int = Field(ge=0, description="小计（分）")
    dish_id: Optional[str] = None
    notes: Optional[str] = None
    customizations: Optional[dict[str, Any]] = None


class PaymentPayload(BaseModel):
    method: str = Field(description="cash/wechat/alipay/card/etc.")
    amount_fen: int = Field(ge=0, description="支付金额（分）")
    trade_no: Optional[str] = None


class PushOrderReq(BaseModel):
    """单条离线订单推送请求"""
    store_id: str
    order_data: dict[str, Any] = Field(description="完整订单快照，金额字段单位：分")
    items_data: list[OrderItemPayload]
    payments_data: Optional[list[PaymentPayload]] = None

    @field_validator("items_data")
    @classmethod
    def items_not_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("items_data must contain at least one item")
        return v


class PushBatchReq(BaseModel):
    """批量推送请求"""
    store_id: str
    orders: list[PushOrderReq] = Field(min_length=1, max_length=100)


class PushOrderResp(BaseModel):
    local_order_id: str
    status: str  # queued | synced | conflict | failed
    server_order_id: Optional[str] = None
    error: Optional[str] = None


class PushBatchResp(BaseModel):
    success_count: int
    failed_count: int
    conflict_count: int
    results: list[PushOrderResp]
    errors: list[str]


class PullResp(BaseModel):
    items: list[dict[str, Any]]
    count: int
    max_seq: int


class SyncStatusResp(BaseModel):
    is_connected: bool
    pending_orders: int
    last_sync_at: Optional[datetime]
    last_pull_at: Optional[datetime]


class CheckpointUpdateReq(BaseModel):
    store_id: str
    device_id: str
    last_pull_seq: int = Field(ge=0)
    last_push_at: Optional[datetime] = None
    last_pull_at: Optional[datetime] = None


class CheckpointResp(BaseModel):
    store_id: str
    device_id: str
    last_pull_seq: int
    updated: bool


# ─── 路由实现 ─────────────────────────────────────────────────────────────

@router.post(
    "/push",
    response_model=dict,
    summary="推送离线订单到云端",
    description=(
        "将本地离线队列中的订单批量推送到云端。"
        "若已有网络则直接同步；若仍离线则存入本地队列并返回 local_order_id。"
    ),
)
async def push_offline_orders(
    req: PushBatchReq,
    request: Request,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict[str, Any]:
    tenant_id = _require_tenant(x_tenant_id)
    svc = _get_service(request)

    raw_results: list[PushOrderResp] = []
    sync_result = SyncResult()

    # 先将所有订单入队
    local_ids: list[str] = []
    for order_req in req.orders:
        try:
            local_id = await svc.queue_offline_order(
                order_data=order_req.order_data,
                items_data=[i.model_dump() for i in order_req.items_data],
                payments_data=[p.model_dump() for p in order_req.payments_data] if order_req.payments_data else None,
                tenant_id=tenant_id,
                store_id=order_req.store_id,
            )
            local_ids.append(local_id)
            raw_results.append(PushOrderResp(local_order_id=local_id, status="queued"))
        except (ValueError, RuntimeError) as exc:
            logger.error("sync_routes.push.queue_error", error=str(exc), exc_info=True)
            sync_result.failed_count += 1
            sync_result.errors.append(str(exc))
            raw_results.append(PushOrderResp(local_order_id="", status="failed", error=str(exc)))

    # 尝试立即同步
    if local_ids:
        try:
            batch_result = await svc.sync_pending_orders(
                store_id=req.store_id, tenant_id=tenant_id
            )
            sync_result.success_count += batch_result.success_count
            sync_result.failed_count += batch_result.failed_count
            sync_result.conflict_count += batch_result.conflict_count
            sync_result.errors.extend(batch_result.errors)
        except (ValueError, RuntimeError, ConnectionError) as exc:
            logger.warning("sync_routes.push.sync_skipped", reason=str(exc))
            # 断网时静默跳过，订单已入队

    resp = PushBatchResp(
        success_count=sync_result.success_count,
        failed_count=sync_result.failed_count,
        conflict_count=sync_result.conflict_count,
        results=raw_results,
        errors=sync_result.errors,
    )

    logger.info(
        "sync_routes.push.done",
        tenant_id=tenant_id,
        store_id=req.store_id,
        total=len(req.orders),
        success=sync_result.success_count,
    )
    return {"ok": True, "data": resp.model_dump()}


@router.get(
    "/pull",
    response_model=dict,
    summary="拉取云端变更",
    description="从云端拉取菜单变更、会员信息、系统配置等最新数据。",
)
async def pull_updates(
    store_id: str,
    device_id: str,
    since_seq: int = 0,
    request: Request = None,  # type: ignore[assignment]
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict[str, Any]:
    tenant_id = _require_tenant(x_tenant_id)
    svc = _get_service(request)

    items = await svc.pull_updates(
        store_id=store_id,
        device_id=device_id,
        since_seq=since_seq,
        tenant_id=tenant_id,
    )

    max_seq = max((i.get("seq", 0) for i in items), default=since_seq)
    resp = PullResp(items=items, count=len(items), max_seq=max_seq)

    logger.info(
        "sync_routes.pull.done",
        tenant_id=tenant_id,
        store_id=store_id,
        device_id=device_id,
        since_seq=since_seq,
        received=len(items),
    )
    return {"ok": True, "data": resp.model_dump()}


@router.get(
    "/status",
    response_model=dict,
    summary="查询同步状态",
    description="返回设备当前同步状态：网络连通性、待同步订单数、上次同步时间。",
)
async def get_sync_status(
    store_id: str,
    device_id: str,
    request: Request = None,  # type: ignore[assignment]
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict[str, Any]:
    tenant_id = _require_tenant(x_tenant_id)
    svc = _get_service(request)

    status: SyncStatus = await svc.get_sync_status(
        store_id=store_id,
        device_id=device_id,
        tenant_id=tenant_id,
    )

    resp = SyncStatusResp(
        is_connected=status.is_connected,
        pending_orders=status.pending_orders,
        last_sync_at=status.last_sync_at,
        last_pull_at=status.last_pull_at,
    )

    return {"ok": True, "data": resp.model_dump()}


@router.post(
    "/checkpoint",
    response_model=dict,
    summary="更新同步检查点",
    description="记录设备最新的同步序列号，供断线续传使用。",
)
async def update_checkpoint(
    req: CheckpointUpdateReq,
    request: Request,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> dict[str, Any]:
    tenant_id = _require_tenant(x_tenant_id)
    svc = _get_service(request)

    # 通过 pull_updates 的 since_seq=last_pull_seq 机制触发 UPSERT
    # 这里直接调用内部 _update_checkpoint_pull 以明确更新序列号
    await svc._update_checkpoint_pull(
        store_id=req.store_id,
        device_id=req.device_id,
        tenant_id=tenant_id,
        last_seq=req.last_pull_seq,
    )

    resp = CheckpointResp(
        store_id=req.store_id,
        device_id=req.device_id,
        last_pull_seq=req.last_pull_seq,
        updated=True,
    )

    logger.info(
        "sync_routes.checkpoint.updated",
        tenant_id=tenant_id,
        store_id=req.store_id,
        device_id=req.device_id,
        last_pull_seq=req.last_pull_seq,
    )
    return {"ok": True, "data": resp.model_dump()}
