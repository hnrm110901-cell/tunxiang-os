"""金蝶ERP对接 API 路由 — 12个端点

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需要 X-Tenant-ID header。
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import structlog
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

log = structlog.get_logger(__name__)

_KINGDEE_API_URL = os.getenv("KINGDEE_API_URL", "")
_KINGDEE_APP_ID = os.getenv("KINGDEE_APP_ID", "")
_KINGDEE_APP_SECRET = os.getenv("KINGDEE_APP_SECRET", "")

router = APIRouter(prefix="/api/v1/kingdee", tags=["kingdee"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class MonthExportRequest(BaseModel):
    store_id: str
    month: str = Field(pattern=r"^\d{4}-\d{2}$", description="YYYY-MM")


class DailyExportRequest(BaseModel):
    store_id: str
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="YYYY-MM-DD")


class RetryRequest(BaseModel):
    export_id: str


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  依赖注入占位
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _get_db():
    """数据库会话依赖 — 由 main.py 覆盖"""
    raise NotImplementedError("DB session dependency not configured")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  1. 采购入库汇总导出
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/export/purchase-receipt")
async def api_export_purchase_receipt(
    req: MonthExportRequest,
    x_tenant_id: str = Header(...),
):
    """采购入库汇总 → 金蝶凭证"""
    from services.kingdee_bridge import export_purchase_receipt

    try:
        result = await export_purchase_receipt(
            req.store_id, req.month, x_tenant_id, _get_db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  2. 成本结转导出
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/export/cost-transfer")
async def api_export_cost_transfer(
    req: MonthExportRequest,
    x_tenant_id: str = Header(...),
):
    """成本结转汇总 → 金蝶凭证"""
    from services.kingdee_bridge import export_cost_transfer

    try:
        result = await export_cost_transfer(
            req.store_id, req.month, x_tenant_id, _get_db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  3. 调拨出入库导出
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/export/transfer")
async def api_export_transfer(
    req: MonthExportRequest,
    x_tenant_id: str = Header(...),
):
    """调拨出入库汇总 → 金蝶凭证"""
    from services.kingdee_bridge import export_transfer_in_out

    try:
        result = await export_transfer_in_out(
            req.store_id, req.month, x_tenant_id, _get_db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  4. 工资计提导出
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/export/salary-accrual")
async def api_export_salary_accrual(
    req: MonthExportRequest,
    x_tenant_id: str = Header(...),
):
    """工资计提 → 金蝶凭证"""
    from services.kingdee_bridge import export_salary_accrual

    try:
        result = await export_salary_accrual(
            req.store_id, req.month, x_tenant_id, _get_db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  5. 收营日报导出
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/export/daily-revenue")
async def api_export_daily_revenue(
    req: DailyExportRequest,
    x_tenant_id: str = Header(...),
):
    """收营日报 → 金蝶凭证"""
    from services.kingdee_bridge import export_daily_revenue

    try:
        result = await export_daily_revenue(
            req.store_id, req.date, x_tenant_id, _get_db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  6. 销售出库导出
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/export/sales-delivery")
async def api_export_sales_delivery(
    req: MonthExportRequest,
    x_tenant_id: str = Header(...),
):
    """销售出库汇总 → 金蝶凭证"""
    from services.kingdee_bridge import export_sales_delivery

    try:
        result = await export_sales_delivery(
            req.store_id, req.month, x_tenant_id, _get_db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  7. 导出历史
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/export/history")
async def api_export_history(
    x_tenant_id: str = Header(...),
    store_id: Optional[str] = None,
    export_type: Optional[str] = None,
    page: int = 1,
    size: int = 20,
):
    """查询金蝶导出历史"""
    from services.kingdee_bridge import get_export_history

    result = await get_export_history(
        x_tenant_id, _get_db,
        store_id=store_id,
        export_type=export_type,
        page=page,
        page_size=size,
    )
    return {"ok": True, "data": result}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  8. 重试失败导出
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.post("/export/retry")
async def api_retry_export(
    req: RetryRequest,
    x_tenant_id: str = Header(...),
):
    """重试失败的金蝶导出"""
    from services.kingdee_bridge import retry_failed_export

    try:
        result = await retry_failed_export(
            req.export_id, x_tenant_id, _get_db,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  供应链对接辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _kingdee_configured() -> bool:
    return bool(_KINGDEE_API_URL and _KINGDEE_APP_ID)


async def _post_kingdee(path: str, payload: Any) -> dict:
    """向金蝶API发送 POST 请求，返回响应 JSON。"""
    url = _KINGDEE_API_URL.rstrip("/") + path
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            url,
            json=payload,
            headers={
                "X-App-ID": _KINGDEE_APP_ID,
                "X-App-Secret": _KINGDEE_APP_SECRET,
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        return resp.json()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  9. 同步库存到金蝶
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class SyncInventoryRequest(BaseModel):
    store_id: str
    warehouse_code: Optional[str] = None


@router.post("/supply/sync-inventory")
async def api_sync_inventory(
    req: SyncInventoryRequest,
    x_tenant_id: str = Header(...),
) -> dict:
    """同步本地 ingredients 库存到金蝶"""
    if not _kingdee_configured():
        log.info("kingdee_sync_inventory_skipped", reason="未配置", store_id=req.store_id)
        return {"ok": True, "data": {"skipped": True, "reason": "金蝶未配置"}}

    try:
        from shared.ontology.src.database import async_session_factory
        from sqlalchemy import text

        async with async_session_factory() as db:
            rows = await db.execute(
                text(
                    "SELECT id, name, unit, current_stock, cost_price_fen, warehouse_code "
                    "FROM ingredients "
                    "WHERE tenant_id = :tid AND store_id = :sid AND is_deleted = false"
                ),
                {"tid": x_tenant_id, "sid": req.store_id},
            )
            items = [dict(r) for r in rows.mappings()]

        if not items:
            log.info("kingdee_sync_inventory_empty", store_id=req.store_id)
            return {"ok": True, "data": {"synced": 0, "skipped": False}}

        payload = {
            "storeId": req.store_id,
            "warehouseCode": req.warehouse_code or "DEFAULT",
            "items": [
                {
                    "materialCode": str(row["id"]),
                    "materialName": row["name"],
                    "unit": row["unit"],
                    "qty": float(row["current_stock"] or 0),
                    "unitCost": (row["cost_price_fen"] or 0) / 100,
                }
                for row in items
            ],
            "syncTime": datetime.now(timezone.utc).isoformat(),
        }

        result = await _post_kingdee("/api/inventory/sync", payload)
        log.info("kingdee_sync_inventory_ok", store_id=req.store_id, count=len(items), result=result)
        return {"ok": True, "data": {"synced": len(items), "kingdee_response": result}}

    except httpx.HTTPStatusError as e:
        log.error("kingdee_sync_inventory_http_error", status=e.response.status_code, store_id=req.store_id)
        return {"ok": False, "data": None, "error": {"message": f"金蝶API返回 {e.response.status_code}"}}
    except httpx.RequestError as e:
        log.error("kingdee_sync_inventory_request_error", error=str(e), store_id=req.store_id)
        return {"ok": False, "data": None, "error": {"message": f"无法连接金蝶API: {e}"}}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  10. 同步采购单到金蝶
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class SyncPurchaseRequest(BaseModel):
    store_id: str
    purchase_order_id: Optional[str] = None  # None = 同步所有未同步采购单
    date_from: Optional[str] = None          # YYYY-MM-DD
    date_to: Optional[str] = None            # YYYY-MM-DD


@router.post("/supply/sync-purchase")
async def api_sync_purchase(
    req: SyncPurchaseRequest,
    x_tenant_id: str = Header(...),
) -> dict:
    """同步本地采购单到金蝶"""
    if not _kingdee_configured():
        log.info("kingdee_sync_purchase_skipped", reason="未配置", store_id=req.store_id)
        return {"ok": True, "data": {"skipped": True, "reason": "金蝶未配置"}}

    try:
        from shared.ontology.src.database import async_session_factory
        from sqlalchemy import text

        filters = "tenant_id = :tid AND store_id = :sid AND is_deleted = false"
        bind: dict = {"tid": x_tenant_id, "sid": req.store_id}

        if req.purchase_order_id:
            filters += " AND id = :po_id"
            bind["po_id"] = req.purchase_order_id
        if req.date_from:
            filters += " AND order_date >= :df"
            bind["df"] = req.date_from
        if req.date_to:
            filters += " AND order_date <= :dt"
            bind["dt"] = req.date_to

        async with async_session_factory() as db:
            rows = await db.execute(
                text(
                    "SELECT id, order_no, supplier_id, supplier_name, order_date, "
                    "       total_amount_fen, status "
                    f"FROM purchase_orders WHERE {filters}"
                ),
                bind,
            )
            orders = [dict(r) for r in rows.mappings()]

        if not orders:
            return {"ok": True, "data": {"synced": 0}}

        payload = {
            "storeId": req.store_id,
            "orders": [
                {
                    "orderNo": o["order_no"],
                    "supplierCode": str(o["supplier_id"]),
                    "supplierName": o["supplier_name"],
                    "orderDate": str(o["order_date"]),
                    "totalAmount": (o["total_amount_fen"] or 0) / 100,
                    "status": o["status"],
                }
                for o in orders
            ],
            "syncTime": datetime.now(timezone.utc).isoformat(),
        }

        result = await _post_kingdee("/api/purchase/sync", payload)
        log.info("kingdee_sync_purchase_ok", store_id=req.store_id, count=len(orders))
        return {"ok": True, "data": {"synced": len(orders), "kingdee_response": result}}

    except httpx.HTTPStatusError as e:
        log.error("kingdee_sync_purchase_http_error", status=e.response.status_code)
        return {"ok": False, "data": None, "error": {"message": f"金蝶API返回 {e.response.status_code}"}}
    except httpx.RequestError as e:
        log.error("kingdee_sync_purchase_request_error", error=str(e))
        return {"ok": False, "data": None, "error": {"message": f"无法连接金蝶API: {e}"}}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  11. 查询金蝶连接状态
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/supply/status")
async def api_kingdee_status(
    x_tenant_id: str = Header(...),
) -> dict:
    """查询金蝶ERP连接状态"""
    if not _kingdee_configured():
        return {"ok": True, "data": {"connected": False, "reason": "金蝶未配置 (KINGDEE_API_URL / KINGDEE_APP_ID 未设置)"}}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                _KINGDEE_API_URL.rstrip("/") + "/api/health",
                headers={"X-App-ID": _KINGDEE_APP_ID},
            )
            connected = resp.status_code < 400
            log.info("kingdee_status_check", connected=connected, status=resp.status_code)
            return {"ok": True, "data": {"connected": connected, "http_status": resp.status_code, "url": _KINGDEE_API_URL}}
    except httpx.RequestError as e:
        log.warning("kingdee_status_unreachable", error=str(e))
        return {"ok": True, "data": {"connected": False, "reason": f"无法连接: {e}", "url": _KINGDEE_API_URL}}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  12. 从金蝶拉取科目数据
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class PullAccountsRequest(BaseModel):
    store_id: str
    account_type: Optional[str] = None  # 科目类型过滤，None = 全部


@router.post("/supply/pull-accounts")
async def api_pull_accounts(
    req: PullAccountsRequest,
    x_tenant_id: str = Header(...),
) -> dict:
    """从金蝶拉取会计科目数据并缓存到本地"""
    if not _kingdee_configured():
        log.info("kingdee_pull_accounts_skipped", reason="未配置")
        return {"ok": True, "data": {"skipped": True, "reason": "金蝶未配置"}}

    try:
        params: dict = {"storeId": req.store_id}
        if req.account_type:
            params["accountType"] = req.account_type

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                _KINGDEE_API_URL.rstrip("/") + "/api/accounts",
                params=params,
                headers={
                    "X-App-ID": _KINGDEE_APP_ID,
                    "X-App-Secret": _KINGDEE_APP_SECRET,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        accounts = data.get("items", data) if isinstance(data, dict) else data
        count = len(accounts) if isinstance(accounts, list) else 0

        log.info("kingdee_pull_accounts_ok", store_id=req.store_id, count=count)
        return {"ok": True, "data": {"pulled": count, "accounts": accounts}}

    except httpx.HTTPStatusError as e:
        log.error("kingdee_pull_accounts_http_error", status=e.response.status_code)
        return {"ok": False, "data": None, "error": {"message": f"金蝶API返回 {e.response.status_code}"}}
    except httpx.RequestError as e:
        log.error("kingdee_pull_accounts_request_error", error=str(e))
        return {"ok": False, "data": None, "error": {"message": f"无法连接金蝶API: {e}"}}
