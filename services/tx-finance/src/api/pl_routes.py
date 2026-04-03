"""P&L报表 API 路由

# ROUTER REGISTRATION (在tx-finance/src/main.py中添加):
# from .api.cost_routes import router as cost_router
# from .api.pl_routes import router as pl_router
# app.include_router(cost_router, prefix="/api/v1/costs")
# app.include_router(pl_router, prefix="/api/v1/pl")

端点：
  GET  /pl/daily?store_id=&date=           - 日P&L
  GET  /pl/period?store_id=&start=&end=    - 期间P&L
  GET  /pl/stores?date=                    - 多店对比
  GET  /pl/vouchers?store_id=&date=        - 凭证列表
  POST /pl/vouchers/generate               - 生成凭证
"""
import uuid
from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from services.tx_finance.src.services.pl_report import PLReportService
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["pl"])

_pl_service = PLReportService()


# ─── 请求模型 ─────────────────────────────────────────────────────────────────

class VoucherGenerateRequest(BaseModel):
    store_id: str
    biz_date: str
    voucher_type: str = "sales"      # sales/cost/payment/receipt
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    entries: list[dict] = []         # 可选：手动指定分录；空则自动生成


# ─── 依赖注入 ─────────────────────────────────────────────────────────────────

async def _get_tenant_db(x_tenant_id: str = Header(..., alias="X-Tenant-ID")):
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


def _parse_date_param(d: str) -> date:
    if d == "today":
        return date.today()
    try:
        return date.fromisoformat(d)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"日期格式错误: {d}，请使用 YYYY-MM-DD") from exc


def _parse_uuid(val: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(val)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"无效的 {field_name}: {val}") from exc


# ─── GET /pl/daily ────────────────────────────────────────────────────────────

@router.get("/daily", summary="日P&L报表")
async def get_daily_pl(
    store_id: str = Query(..., description="门店ID"),
    date: str = Query("today", description="业务日期 YYYY-MM-DD 或 today"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """门店日度P&L报表

    返回：
    - revenue_fen: 当天收入（分）
    - raw_material_cost_fen: 原料成本（分）
    - gross_profit_fen: 毛利（分）
    - gross_margin_rate: 毛利率
    - net_profit_fen: 净利润（含期间费用扣除）
    - net_margin_rate: 净利润率
    """
    sid = _parse_uuid(store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    biz_date = _parse_date_param(date)

    try:
        report = await _pl_service.get_daily_pl(sid, biz_date, tid, db)
    except Exception as exc:
        logger.error("get_daily_pl.failed", store_id=store_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="日P&L计算失败") from exc

    return {"ok": True, "data": report.to_dict()}


# ─── GET /pl/period ───────────────────────────────────────────────────────────

@router.get("/period", summary="期间P&L报表")
async def get_period_pl(
    store_id: str = Query(..., description="门店ID"),
    start: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end: str = Query(..., description="结束日期 YYYY-MM-DD"),
    comparison: Optional[str] = Query(None, description="对比模式: yoy（同比）| mom（环比）"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """期间P&L报表（周/月/自定义区间）

    可选 comparison 参数：
    - yoy: 同比（去年同期）
    - mom: 环比（上一自然周期）
    - 不传: 仅返回当期数据
    """
    sid = _parse_uuid(store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    start_date = _parse_date_param(start)
    end_date = _parse_date_param(end)

    if start_date > end_date:
        raise HTTPException(status_code=400, detail="start 不能晚于 end")

    try:
        if comparison in ("yoy", "mom"):
            data = await _pl_service.get_period_pl_with_comparison(
                sid, start_date, end_date, tid, db, comparison=comparison
            )
            return {"ok": True, "data": data}

        report = await _pl_service.get_period_pl(sid, start_date, end_date, tid, db)
    except Exception as exc:
        logger.error("get_period_pl.failed", store_id=store_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="期间P&L计算失败") from exc

    return {"ok": True, "data": report.to_dict()}


# ─── GET /pl/stores ───────────────────────────────────────────────────────────

@router.get("/stores", summary="多店P&L对比")
async def get_stores_pl_comparison(
    date: str = Query("today", description="业务日期 YYYY-MM-DD 或 today"),
    store_ids: Optional[str] = Query(None, description="逗号分隔的门店ID，空则查当前租户所有门店"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """多店当日P&L对比

    按毛利率降序返回，便于快速识别经营优良/待改善门店。
    """
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    biz_date = _parse_date_param(date)

    if store_ids:
        sid_list = [_parse_uuid(s.strip(), "store_id") for s in store_ids.split(",") if s.strip()]
    else:
        # 查询当前租户所有门店
        from sqlalchemy import select

        from shared.ontology.src.entities import Store
        result = await db.execute(
            select(Store.id).where(Store.tenant_id == tid).where(Store.is_deleted == False)
        )
        sid_list = [row[0] for row in result.all()]

    if not sid_list:
        return {"ok": True, "data": {"stores": [], "biz_date": str(biz_date)}}

    try:
        reports = await _pl_service.get_stores_pl(sid_list, biz_date, tid, db)
    except Exception as exc:
        logger.error("get_stores_pl.failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="多店P&L对比失败") from exc

    return {
        "ok": True,
        "data": {
            "biz_date": str(biz_date),
            "store_count": len(reports),
            "stores": [r.to_dict() for r in reports],
        },
    }


# ─── GET /pl/vouchers ────────────────────────────────────────────────────────

@router.get("/vouchers", summary="凭证列表")
async def list_vouchers(
    store_id: str = Query(..., description="门店ID"),
    date: str = Query("today", description="凭证日期 YYYY-MM-DD 或 today"),
    status: Optional[str] = Query(None, description="状态过滤: draft/confirmed/exported"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """门店凭证列表

    支持按状态过滤，返回当日所有财务凭证。
    凭证状态：draft(草稿) → confirmed(已确认) → exported(已导出ERP)
    """
    sid = _parse_uuid(store_id, "store_id")
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    biz_date = _parse_date_param(date)

    valid_statuses = {"draft", "confirmed", "exported"}
    if status and status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"status 必须是: {', '.join(valid_statuses)}"
        )

    try:
        vouchers = await _pl_service.get_vouchers(sid, biz_date, tid, db, status)
    except Exception as exc:
        logger.error("list_vouchers.failed", store_id=store_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询凭证失败") from exc

    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "biz_date": str(biz_date),
            "total": len(vouchers),
            "items": vouchers,
        },
    }


# ─── POST /pl/vouchers/generate ──────────────────────────────────────────────

@router.post("/vouchers/generate", summary="生成财务凭证")
async def generate_voucher(
    body: VoucherGenerateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_tenant_db),
):
    """生成财务凭证（销售/成本结转/收款/付款）

    若 entries 为空，系统自动根据 voucher_type 和当日P&L数据生成分录。
    若提供 entries，则使用指定分录（适用于手动调整场景）。

    生成后凭证处于 draft 状态，需财务人员确认后方可导出ERP。
    """
    tid = _parse_uuid(x_tenant_id, "X-Tenant-ID")
    sid = _parse_uuid(body.store_id, "store_id")
    biz_date = _parse_date_param(body.biz_date)

    valid_types = {"sales", "cost", "payment", "receipt"}
    if body.voucher_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"voucher_type 必须是: {', '.join(valid_types)}"
        )

    try:
        voucher_data = await _generate_voucher_internal(
            store_id=sid,
            biz_date=biz_date,
            voucher_type=body.voucher_type,
            tenant_id=tid,
            source_type=body.source_type,
            source_id=body.source_id,
            manual_entries=body.entries,
            db=db,
        )
    except Exception as exc:
        logger.error(
            "generate_voucher.failed",
            store_id=body.store_id,
            voucher_type=body.voucher_type,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="凭证生成失败") from exc

    return {"ok": True, "data": voucher_data}


async def _generate_voucher_internal(
    store_id: uuid.UUID,
    biz_date: date,
    voucher_type: str,
    tenant_id: uuid.UUID,
    source_type: Optional[str],
    source_id: Optional[str],
    manual_entries: list,
    db: AsyncSession,
) -> dict:
    """凭证生成内部实现

    当前实现：基于日P&L数据自动生成分录骨架。
    生产中可扩展接入金蝶/用友科目体系。
    """
    import secrets

    # 生成凭证编号（格式：V{YYYYMMDD}{8位随机hex}）
    voucher_no = f"V{biz_date.strftime('%Y%m%d')}{secrets.token_hex(4).upper()}"

    # 若无手动分录，根据类型生成默认骨架分录
    if not manual_entries:
        if voucher_type == "sales":
            pl_report = await _pl_service.get_daily_pl(store_id, biz_date, tenant_id, db)
            total_yuan = round(pl_report.revenue_fen / 100, 2)
            manual_entries = [
                {
                    "account_code": "1002.01",
                    "account_name": "银行存款-微信",
                    "debit": total_yuan,
                    "credit": 0,
                    "summary": f"{biz_date}销售收入",
                },
                {
                    "account_code": "6001",
                    "account_name": "主营业务收入-餐饮",
                    "debit": 0,
                    "credit": total_yuan,
                    "summary": f"{biz_date}销售收入",
                },
            ]
        else:
            manual_entries = []

    total_debit = sum(e.get("debit", 0) for e in manual_entries)
    total_credit = sum(e.get("credit", 0) for e in manual_entries)

    # 持久化到 financial_vouchers 表（骨架实现）
    from sqlalchemy import text

    await db.execute(
        text("""
            INSERT INTO financial_vouchers (
                tenant_id, store_id, voucher_no, voucher_date,
                voucher_type, total_amount, entries,
                source_type, source_id, status
            ) VALUES (
                :tenant_id::UUID, :store_id::UUID, :voucher_no, :voucher_date::DATE,
                :voucher_type, :total_amount, :entries::JSONB,
                :source_type, :source_id::UUID, 'draft'
            )
            ON CONFLICT (voucher_no) DO NOTHING
        """),
        {
            "tenant_id": str(tenant_id),
            "store_id": str(store_id),
            "voucher_no": voucher_no,
            "voucher_date": str(biz_date),
            "voucher_type": voucher_type,
            "total_amount": total_debit,
            "entries": __import__("json").dumps(manual_entries, ensure_ascii=False),
            "source_type": source_type,
            "source_id": source_id,
        },
    )
    await db.commit()

    logger.info(
        "voucher_generated",
        voucher_no=voucher_no,
        store_id=str(store_id),
        voucher_type=voucher_type,
        total_debit=total_debit,
        total_credit=total_credit,
        is_balanced=abs(total_debit - total_credit) < 0.001,
    )

    return {
        "voucher_no": voucher_no,
        "voucher_date": str(biz_date),
        "voucher_type": voucher_type,
        "total_amount": total_debit,
        "entries": manual_entries,
        "entry_count": len(manual_entries),
        "is_balanced": abs(total_debit - total_credit) < 0.001,
        "status": "draft",
    }
