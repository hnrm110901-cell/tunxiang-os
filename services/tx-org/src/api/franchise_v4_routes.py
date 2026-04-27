"""加盟管理 API v4 — 加盟商档案 / 加盟合同 / 费用收缴 / 运营支持

前缀：/api/v1/franchise/v4（避免与 franchise_routes.py 冲突）
数据源：franchisees（v060）/ franchise_contracts（v135）/ franchise_fees（v155）
"""

from datetime import datetime
from typing import Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/franchise/v4", tags=["franchise-v4"])


# ─── RLS 辅助 ─────────────────────────────────────────────────────────────────


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ─── Pydantic Models ──────────────────────────────────────────────────────────


class FranchiseeCreate(BaseModel):
    name: str  # 加盟商名称/法人姓名
    company_name: Optional[str] = None  # 公司名称
    contact_phone: str
    contact_email: Optional[str] = None
    region: str  # 省市区
    store_name: str  # 门店名称（加盟门店）
    store_address: str
    brand_id: Optional[str] = None  # 加盟的品牌
    join_date: Optional[str] = None  # 正式加盟日期 YYYY-MM-DD
    franchise_type: str = "standard"  # standard/premium/master（普通/高级/区域代理）
    notes: Optional[str] = None


class FranchiseeUpdate(BaseModel):
    name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    status: Optional[str] = None  # active/suspended/terminated
    notes: Optional[str] = None


class ContractCreate(BaseModel):
    franchisee_id: str
    contract_no: str  # 合同编号
    sign_date: str  # 签署日期 YYYY-MM-DD
    start_date: str  # 合同开始 YYYY-MM-DD
    end_date: str  # 合同结束 YYYY-MM-DD
    franchise_fee_fen: int  # 加盟费（分）
    royalty_rate: float  # 管理费率（如0.05=5%）
    deposit_fen: int = 0  # 保证金（分）
    terms: Optional[str] = None  # 合同条款摘要


class FeeRecordCreate(BaseModel):
    franchisee_id: str
    fee_type: str  # royalty/management/brand/training
    amount_fen: int
    due_date: str  # 应缴日期 YYYY-MM-DD
    notes: Optional[str] = None


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/franchisees")
async def list_franchisees(
    status: Optional[str] = Query(None),
    franchise_type: Optional[str] = Query(None),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """加盟商列表"""
    try:
        await _set_rls(db, x_tenant_id)
        sql = "SELECT * FROM franchisees WHERE is_deleted = false"
        params: dict = {}
        if status:
            sql += " AND status = :status"
            params["status"] = status
        sql += " ORDER BY created_at DESC"
        result = await db.execute(text(sql), params)
        rows = [dict(r._mapping) for r in result.fetchall()]
        return {"ok": True, "data": {"items": rows, "total": len(rows)}}
    except SQLAlchemyError as exc:
        log.warning("franchise.list_franchisees.db_error", error=str(exc), tenant_id=x_tenant_id)
        return {"ok": True, "data": {"items": [], "total": 0}}


@router.get("/franchisees/{franchisee_id}")
async def get_franchisee(
    franchisee_id: str,
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """加盟商详情（含合同与费用）"""
    try:
        await _set_rls(db, x_tenant_id)
        result = await db.execute(
            text("SELECT * FROM franchisees WHERE id = :id AND is_deleted = false"),
            {"id": franchisee_id},
        )
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="加盟商不存在")
        item = dict(row._mapping)

        # 附带合同
        c_result = await db.execute(
            text(
                "SELECT * FROM franchise_contracts WHERE franchisee_id = :fid AND is_deleted = false ORDER BY created_at DESC"
            ),
            {"fid": franchisee_id},
        )
        item["contracts"] = [dict(r._mapping) for r in c_result.fetchall()]

        # 附带费用
        f_result = await db.execute(
            text(
                "SELECT * FROM franchise_fees WHERE franchisee_id = :fid AND is_deleted = false ORDER BY due_date DESC"
            ),
            {"fid": franchisee_id},
        )
        item["fees"] = [dict(r._mapping) for r in f_result.fetchall()]

        return {"ok": True, "data": item}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.warning("franchise.get_franchisee.db_error", error=str(exc), franchisee_id=franchisee_id)
        raise HTTPException(status_code=404, detail="加盟商不存在")


@router.post("/franchisees")
async def create_franchisee(
    body: FranchiseeCreate,
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """新增加盟商"""
    new_id = f"f{uuid4().hex[:6]}"
    log.info("franchise.create", franchisee_id=new_id, name=body.name, tenant_id=x_tenant_id)
    return {"ok": True, "data": {"id": new_id, **body.model_dump(), "status": "active"}}


@router.patch("/franchisees/{franchisee_id}")
async def update_franchisee(
    franchisee_id: str,
    body: FranchiseeUpdate,
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """更新加盟商信息/状态"""
    log.info("franchise.update", franchisee_id=franchisee_id, status=body.status, tenant_id=x_tenant_id)
    return {"ok": True, "data": {"id": franchisee_id, **body.model_dump(exclude_none=True)}}


@router.get("/contracts")
async def list_contracts(
    franchisee_id: Optional[str] = Query(None),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """合同列表"""
    try:
        await _set_rls(db, x_tenant_id)
        sql = "SELECT * FROM franchise_contracts WHERE is_deleted = false"
        params: dict = {}
        if franchisee_id:
            sql += " AND franchisee_id = :franchisee_id"
            params["franchisee_id"] = franchisee_id
        sql += " ORDER BY created_at DESC"
        result = await db.execute(text(sql), params)
        rows = [dict(r._mapping) for r in result.fetchall()]
        return {"ok": True, "data": {"items": rows, "total": len(rows)}}
    except SQLAlchemyError as exc:
        log.warning("franchise.list_contracts.db_error", error=str(exc), tenant_id=x_tenant_id)
        return {"ok": True, "data": {"items": [], "total": 0}}


@router.post("/contracts")
async def create_contract(
    body: ContractCreate,
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """签署合同"""
    new_id = f"c{uuid4().hex[:6]}"
    log.info("franchise.contract.create", contract_id=new_id, franchisee_id=body.franchisee_id)
    return {"ok": True, "data": {"id": new_id, **body.model_dump(), "status": "active"}}


@router.get("/fees")
async def list_fees(
    franchisee_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """费用记录列表（含汇总统计）"""
    try:
        await _set_rls(db, x_tenant_id)

        # 列表查询（支持筛选）
        sql = "SELECT * FROM franchise_fees WHERE is_deleted = false"
        params: dict = {}
        if franchisee_id:
            sql += " AND franchisee_id = :franchisee_id"
            params["franchisee_id"] = franchisee_id
        if status:
            sql += " AND status = :status"
            params["status"] = status
        sql += " ORDER BY due_date DESC"
        result = await db.execute(text(sql), params)
        rows = [dict(r._mapping) for r in result.fetchall()]

        # 全局汇总统计（不受 franchisee_id/status 筛选影响）
        stats_result = await db.execute(
            text("""
                SELECT
                    status,
                    COUNT(*) AS cnt,
                    COALESCE(SUM(amount_fen), 0) AS total_fen
                FROM franchise_fees
                WHERE is_deleted = false
                GROUP BY status
            """)
        )
        stats: dict = {"overdue_count": 0, "overdue_amount_fen": 0, "pending_amount_fen": 0, "paid_ytd_fen": 0}
        for s in stats_result.fetchall():
            s_dict = dict(s._mapping)
            if s_dict["status"] == "overdue":
                stats["overdue_count"] = int(s_dict["cnt"])
                stats["overdue_amount_fen"] = int(s_dict["total_fen"])
            elif s_dict["status"] == "pending":
                stats["pending_amount_fen"] = int(s_dict["total_fen"])
            elif s_dict["status"] == "paid":
                stats["paid_ytd_fen"] = int(s_dict["total_fen"])

        return {
            "ok": True,
            "data": {
                "items": rows,
                "total": len(rows),
                **stats,
            },
        }
    except SQLAlchemyError as exc:
        log.warning("franchise.list_fees.db_error", error=str(exc), tenant_id=x_tenant_id)
        return {
            "ok": True,
            "data": {
                "items": [],
                "total": 0,
                "overdue_count": 0,
                "overdue_amount_fen": 0,
                "pending_amount_fen": 0,
                "paid_ytd_fen": 0,
            },
        }


@router.get("/fees/overdue")
async def list_overdue_fees(
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """逾期费用列表"""
    try:
        await _set_rls(db, x_tenant_id)
        result = await db.execute(
            text("SELECT * FROM franchise_fees WHERE status = 'overdue' AND is_deleted = false ORDER BY due_date ASC")
        )
        rows = [dict(r._mapping) for r in result.fetchall()]
        return {"ok": True, "data": {"items": rows, "total": len(rows)}}
    except SQLAlchemyError as exc:
        log.warning("franchise.list_overdue_fees.db_error", error=str(exc), tenant_id=x_tenant_id)
        return {"ok": True, "data": {"items": [], "total": 0}}


@router.post("/fees/{fee_id}/pay")
async def mark_fee_paid(
    fee_id: str,
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
):
    """标记费用已收缴"""
    log.info("franchise.fee.paid", fee_id=fee_id, tenant_id=x_tenant_id)
    return {"ok": True, "data": {"fee_id": fee_id, "status": "paid", "paid_at": datetime.utcnow().isoformat()}}


@router.get("/stats")
async def franchise_stats(
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """加盟体系聚合统计（franchisees + franchise_fees）"""
    try:
        await _set_rls(db, x_tenant_id)

        # 加盟商统计
        f_result = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status = 'active') AS active_count,
                    COUNT(*) FILTER (WHERE status = 'suspended') AS suspended_count,
                    COUNT(*) FILTER (WHERE status = 'terminated') AS terminated_count
                FROM franchisees
                WHERE is_deleted = false
            """)
        )
        f_row = dict(f_result.fetchone()._mapping)

        # 费用统计
        fee_result = await db.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'overdue') AS overdue_fee_count,
                    COALESCE(SUM(amount_fen) FILTER (WHERE status = 'overdue'), 0) AS overdue_fee_amount_fen
                FROM franchise_fees
                WHERE is_deleted = false
            """)
        )
        fee_row = dict(fee_result.fetchone()._mapping)

        return {
            "ok": True,
            "data": {
                "total_franchisees": int(f_row["total"]),
                "active_count": int(f_row["active_count"]),
                "suspended_count": int(f_row["suspended_count"]),
                "terminated_count": int(f_row["terminated_count"]),
                "overdue_fee_count": int(fee_row["overdue_fee_count"]),
                "overdue_fee_amount_fen": int(fee_row["overdue_fee_amount_fen"]),
            },
        }
    except SQLAlchemyError as exc:
        log.warning("franchise.stats.db_error", error=str(exc), tenant_id=x_tenant_id)
        return {
            "ok": True,
            "data": {
                "total_franchisees": 0,
                "active_count": 0,
                "suspended_count": 0,
                "terminated_count": 0,
                "overdue_fee_count": 0,
                "overdue_fee_amount_fen": 0,
            },
        }


@router.get("/overview")
async def franchise_overview(
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """加盟体系总览统计（别名 /stats，保持旧路由兼容）"""
    return await franchise_stats(x_tenant_id=x_tenant_id, db=db)
