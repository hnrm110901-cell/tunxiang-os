"""POS数据同步路由 — 品智POS拉取 + 回填 + 状态查询

路由前缀：/api/v1/integrations/pos-sync

功能：
  POST /backfill              — 手动触发POS数据回填
  GET  /status/{merchant_code} — 查询同步状态
  POST /sync-today/{merchant_code} — 同步今日数据
  POST /sync-menu/{merchant_code}/{store_id} — 同步菜品数据
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends

from shared.tenant_registry import MERCHANT_CODE_TO_TENANT_UUID

from ...modules.gateway.integrations.pos_sync_schemas import (
    BackfillRequest,
    SyncTodayRequest,
)
from ...modules.gateway.integrations.pos_sync_service import POSSyncService
from ...shared.core.exceptions import POSAdapterError
from ...shared.response import err, ok

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/integrations/pos-sync",
    tags=["POS同步"],
)

# 单例服务
_sync_service = POSSyncService()


def _get_tenant_id(merchant_code: str) -> UUID:
    """从商户编码获取租户 UUID（与 Gateway DEMO 用户 tenant_id 单一事实源，见 shared/tenant_registry.py）"""
    key = (merchant_code or "").strip().lower()
    tid = MERCHANT_CODE_TO_TENANT_UUID.get(key)
    if not tid:
        raise POSAdapterError(
            f"未知商户编码: {merchant_code}",
            context={"merchant_code": merchant_code},
        )
    return UUID(tid)


# ── 依赖注入：数据库会话 ──────────────────────────────────────────────────────
# 使用 shared/ontology 提供的统一数据库连接
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

# ── 路由 ──────────────────────────────────────────────────────────────────────


@router.post("/backfill")
async def backfill_pos_data(
    req: BackfillRequest,
    db: AsyncSession = Depends(get_db),
):
    """手动触发POS数据回填

    按日期范围从品智API拉取历史订单数据并写入数据库。
    最大允许90天，建议单次不超过31天。
    """
    # 校验日期范围
    days = (req.end_date - req.start_date).days + 1
    if days < 1:
        return err("结束日期必须大于等于开始日期", code="INVALID_DATE_RANGE")
    if days > req.max_days:
        return err(
            f"日期范围({days}天)超过最大限制({req.max_days}天)",
            code="DATE_RANGE_TOO_LARGE",
        )

    tenant_id = _get_tenant_id(req.merchant_code)

    try:
        result = await _sync_service.backfill(
            merchant_code=req.merchant_code,
            start_date=req.start_date,
            end_date=req.end_date,
            tenant_id=tenant_id,
            db=db,
            store_ids=req.store_ids,
        )
        return ok(result.model_dump())
    except POSAdapterError as e:
        logger.error("pos_sync.backfill_failed", error=str(e), context=e.context)
        return err(e.message, code="POS_SYNC_ERROR", status_code=502)


@router.get("/status/{merchant_code}")
async def get_sync_status(
    merchant_code: str,
    db: AsyncSession = Depends(get_db),
):
    """查询同步状态

    返回指定商户的最近同步时间、今日订单数等信息。
    """
    try:
        _get_tenant_id(merchant_code)  # 校验商户存在
    except POSAdapterError as e:
        return err(e.message, code="UNKNOWN_MERCHANT", status_code=404)

    status = await _sync_service.get_sync_status(merchant_code, db)
    return ok(status.model_dump())


@router.post("/sync-today/{merchant_code}")
async def sync_today(
    merchant_code: str,
    req: SyncTodayRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    """同步今日数据

    拉取今日品智POS订单数据并写入数据库。
    """
    tenant_id = _get_tenant_id(merchant_code)
    today = date.today()
    store_ids = req.store_ids if req else None

    try:
        result = await _sync_service.backfill(
            merchant_code=merchant_code,
            start_date=today,
            end_date=today,
            tenant_id=tenant_id,
            db=db,
            store_ids=store_ids,
        )
        return ok(result.model_dump())
    except POSAdapterError as e:
        logger.error("pos_sync.today_failed", error=str(e), context=e.context)
        return err(e.message, code="POS_SYNC_ERROR", status_code=502)


@router.post("/sync-menu/{merchant_code}/{store_id}")
async def sync_menu(
    merchant_code: str,
    store_id: str,
    db: AsyncSession = Depends(get_db),
):
    """同步菜品数据

    从品智POS拉取指定门店的菜品列表并写入dishes表。
    """
    tenant_id = _get_tenant_id(merchant_code)

    try:
        result = await _sync_service.sync_menu(
            merchant_code=merchant_code,
            store_id=store_id,
            tenant_id=tenant_id,
            db=db,
        )
        return ok(result)
    except POSAdapterError as e:
        logger.error("pos_sync.menu_failed", error=str(e))
        return err(e.message, code="POS_SYNC_ERROR", status_code=502)
