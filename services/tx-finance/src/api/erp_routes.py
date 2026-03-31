"""ERP 对接 API — 财务凭证生成与推送

路由前缀: /api/v1/erp
认证: X-Tenant-ID header（RLS 强制隔离）

端点：
  POST /erp/vouchers/purchase/{order_id}   — 采购凭证生成+推送
  POST /erp/vouchers/daily-revenue         — 日收入凭证生成+推送
  GET  /erp/accounts                       — 科目表同步
  GET  /erp/health                         — ERP 连通性检查
  GET  /erp/queue                          — 待重试凭证队列（用友专用）
  POST /erp/queue/drain                    — 触发队列重试
"""
from __future__ import annotations

from datetime import date
from typing import Annotated

import httpx
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant
from shared.adapters.erp.src import (
    ERPType,
    get_erp_adapter,
)
from services.voucher_generator import VoucherGenerator

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/erp", tags=["erp"])

_generator = VoucherGenerator()


# ─── 依赖 ─────────────────────────────────────────────────────────────────────


async def _get_tenant_db(
    x_tenant_id: Annotated[str, Header(alias="X-Tenant-ID")],
) -> AsyncSession:  # type: ignore[misc]
    """从 header 提取 tenant_id 并返回带 RLS 的 DB session"""
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _parse_erp_type(erp_type: str) -> str:
    """校验 ERP 类型合法性"""
    valid = [e.value for e in ERPType]
    if erp_type not in valid:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的 ERP 类型: {erp_type!r}，支持: {valid}",
        )
    return erp_type


# ─── 采购凭证 ─────────────────────────────────────────────────────────────────


@router.post(
    "/vouchers/purchase/{order_id}",
    summary="采购凭证生成+推送",
    response_model=dict,
)
async def push_purchase_voucher(
    order_id: str,
    db: Annotated[AsyncSession, Depends(_get_tenant_db)],
    x_tenant_id: Annotated[str, Header(alias="X-Tenant-ID")],
    erp_type: Annotated[str, Query(description="ERP类型: kingdee / yonyou")] = "kingdee",
) -> dict:
    """生成采购结算凭证并推送到指定 ERP

    - 借: 原材料
    - 贷: 应付账款
    - ERP 推送失败时用友会写本地队列，金蝶返回 FAILED 状态
    - 主业务流程不受 ERP 推送失败影响
    """
    erp_type = _parse_erp_type(erp_type)
    log.info(
        "api.erp.purchase_voucher",
        order_id=order_id,
        tenant_id=x_tenant_id,
        erp_type=erp_type,
    )
    try:
        voucher = await _generator.generate_from_purchase_order(
            purchase_order_id=order_id,
            tenant_id=x_tenant_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    result = await _generator.push_to_erp(
        voucher=voucher,
        tenant_id=x_tenant_id,
        erp_type=erp_type,
        db=db,
    )
    return {
        "ok": True,
        "data": {
            "voucher_id": voucher.voucher_id,
            "total_yuan": voucher.total_yuan,
            "business_date": voucher.business_date.isoformat(),
            "erp_type": erp_type,
            "push_status": result.status.value,
            "erp_voucher_id": result.erp_voucher_id,
            "error_message": result.error_message,
        },
    }


# ─── 日收入凭证 ───────────────────────────────────────────────────────────────


@router.post(
    "/vouchers/daily-revenue",
    summary="日收入凭证生成+推送",
    response_model=dict,
)
async def push_daily_revenue_voucher(
    db: Annotated[AsyncSession, Depends(_get_tenant_db)],
    x_tenant_id: Annotated[str, Header(alias="X-Tenant-ID")],
    store_id: Annotated[str, Query(description="门店ID")],
    business_date: Annotated[date, Query(description="业务日期 YYYY-MM-DD")],
    erp_type: Annotated[str, Query(description="ERP类型: kingdee / yonyou")] = "kingdee",
) -> dict:
    """生成日营收凭证并推送到指定 ERP

    按支付方式生成借方分录：
    - 借: 现金/微信/支付宝/银行存款（各方式分录）
    - 贷: 主营业务收入（合计）
    """
    erp_type = _parse_erp_type(erp_type)
    log.info(
        "api.erp.daily_revenue_voucher",
        store_id=store_id,
        business_date=business_date,
        tenant_id=x_tenant_id,
        erp_type=erp_type,
    )
    try:
        voucher = await _generator.generate_from_daily_revenue(
            store_id=store_id,
            business_date=business_date,
            tenant_id=x_tenant_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    result = await _generator.push_to_erp(
        voucher=voucher,
        tenant_id=x_tenant_id,
        erp_type=erp_type,
        db=db,
    )
    return {
        "ok": True,
        "data": {
            "voucher_id": voucher.voucher_id,
            "total_yuan": voucher.total_yuan,
            "entry_count": len(voucher.entries),
            "business_date": voucher.business_date.isoformat(),
            "erp_type": erp_type,
            "push_status": result.status.value,
            "erp_voucher_id": result.erp_voucher_id,
            "error_message": result.error_message,
        },
    }


# ─── 科目表同步 ───────────────────────────────────────────────────────────────


@router.get(
    "/accounts",
    summary="从 ERP 同步科目表",
    response_model=dict,
)
async def sync_chart_of_accounts(
    erp_type: Annotated[str, Query(description="ERP类型: kingdee / yonyou")] = "kingdee",
) -> dict:
    """从 ERP 拉取科目表（金蝶降级返回内置默认科目表）"""
    erp_type = _parse_erp_type(erp_type)
    log.info("api.erp.accounts", erp_type=erp_type)
    adapter = get_erp_adapter(erp_type)
    try:
        accounts = await adapter.sync_chart_of_accounts()
        return {
            "ok": True,
            "data": {
                "erp_type": erp_type,
                "count": len(accounts),
                "accounts": [a.model_dump() for a in accounts],
            },
        }
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        log.error("api.erp.accounts.error", erp_type=erp_type, error=str(exc))
        raise HTTPException(status_code=502, detail=f"科目表同步失败: {exc}") from exc
    finally:
        await adapter.close()


# ─── 连通性检查 ───────────────────────────────────────────────────────────────


@router.get(
    "/health",
    summary="ERP 连通性检查",
    response_model=dict,
)
async def erp_health_check(
    erp_type: Annotated[str, Query(description="ERP类型: kingdee / yonyou")] = "kingdee",
) -> dict:
    """检查 ERP 系统连通性"""
    erp_type = _parse_erp_type(erp_type)
    adapter = get_erp_adapter(erp_type)
    try:
        ok = await adapter.health_check()
        return {
            "ok": True,
            "data": {
                "erp_type": erp_type,
                "reachable": ok,
                "message": "ERP 连通正常" if ok else "ERP 不可达",
            },
        }
    finally:
        await adapter.close()


# ─── 用友离线队列 ─────────────────────────────────────────────────────────────


@router.get(
    "/queue",
    summary="查询待重试凭证队列（用友专用）",
    response_model=dict,
)
async def get_push_queue() -> dict:
    """返回用友离线队列中待重试的凭证条目数"""
    from shared.adapters.erp.src import YonyouAdapter
    import os

    adapter = YonyouAdapter.__new__(YonyouAdapter)
    import pathlib
    queue_path = os.environ.get("YONYOU_QUEUE_PATH", "/tmp/yonyou_push_queue.jsonl")
    adapter._queue_path = pathlib.Path(queue_path)

    size = adapter.queue_size()
    log.info("api.erp.queue", size=size)
    return {
        "ok": True,
        "data": {
            "erp_type": ERPType.YONYOU.value,
            "pending_count": size,
            "queue_path": queue_path,
        },
    }


@router.post(
    "/queue/drain",
    summary="触发用友离线队列重试",
    response_model=dict,
)
async def drain_push_queue() -> dict:
    """消费用友离线队列，对其中凭证执行重试推送"""
    from shared.adapters.erp.src import YonyouAdapter

    adapter = YonyouAdapter()
    try:
        results = await adapter.drain_queue()
        success_count = sum(1 for r in results if r.status.value == "success")
        return {
            "ok": True,
            "data": {
                "total": len(results),
                "success": success_count,
                "remaining": len(results) - success_count,
                "results": [r.model_dump(mode="json") for r in results],
            },
        }
    finally:
        await adapter.close()
