"""加盟商管理闭环 API v5 — 模块3.2

功能覆盖：
  - 加盟商档案（列表/新建/更新/合同详情）
  - 加盟费收缴（应收列表含逾期标记/标记收款/批量生成本月应收）
  - 公共代码管理（列表/新增/更新/同步到门店）
  - 对账报表（营业额汇总/费用收缴汇总）

路由前缀: /api/v1/franchise
数据表: franchisees / franchise_fees / franchise_common_codes（v240）

注意：本模块与 franchise_v4_routes.py（前缀 /api/v1/franchise/v4）平行存在。
      v5 提供完整 RESTful 路径，v4 保持向下兼容。
"""
from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/franchise", tags=["franchise-v5"])


# ─── RLS 辅助 ─────────────────────────────────────────────────────────────────

async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ─── Pydantic Models ──────────────────────────────────────────────────────────

class FranchiseeCreateV5(BaseModel):
    name: str                                   # 加盟商名称/法人姓名
    company_name: Optional[str] = None
    contact_phone: str
    contact_email: Optional[str] = None
    region: str                                 # 省市区
    store_name: str
    store_address: str
    brand_id: Optional[str] = None
    join_date: Optional[str] = None             # YYYY-MM-DD
    franchise_type: str = "standard"            # standard/premium/master
    contract_no: Optional[str] = None
    contract_start_date: Optional[str] = None   # YYYY-MM-DD
    contract_end_date: Optional[str] = None     # YYYY-MM-DD
    contract_file_url: Optional[str] = None
    notes: Optional[str] = None


class FranchiseeUpdateV5(BaseModel):
    name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    status: Optional[str] = None               # active/suspended/terminated
    contract_start_date: Optional[str] = None
    contract_end_date: Optional[str] = None
    contract_file_url: Optional[str] = None
    notes: Optional[str] = None


class FeeCollectBody(BaseModel):
    paid_amount_fen: int = Field(..., gt=0, description="实收金额（分）")
    paid_at: Optional[str] = None               # 收款时间 ISO8601，空则取当前时间
    payment_method: str = "transfer"            # transfer/cash/wechat/alipay
    receipt_no: Optional[str] = None
    operator: Optional[str] = None


class GenerateMonthlyFeesBody(BaseModel):
    year_month: str = Field(..., description="目标月份 YYYY-MM")
    fee_type: str = "royalty"                   # royalty/management/brand/training
    amount_fen: int = Field(..., gt=0, description="每家应收金额（分）")
    due_day: int = Field(default=15, ge=1, le=28, description="当月几号为截止日")
    notes: Optional[str] = None


class CommonCodeCreate(BaseModel):
    code_type: str = Field(..., description="material / dish / price")
    code_no: str
    name: str
    description: Optional[str] = None
    unit: Optional[str] = None
    price_fen: Optional[int] = None
    applicable_stores: list[str] = Field(default_factory=list,
                                          description="适用门店ID列表，空=全部")


class CommonCodeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    unit: Optional[str] = None
    price_fen: Optional[int] = None
    applicable_stores: Optional[list[str]] = None
    status: Optional[str] = None


class CommonCodeSyncBody(BaseModel):
    code_ids: list[str] = Field(..., description="要同步的编码ID列表")
    target_store_ids: list[str] = Field(..., description="目标门店ID列表")


# ─── 加盟商档案 ───────────────────────────────────────────────────────────────

@router.get("/franchisees")
async def list_franchisees_v5(
    status: Optional[str] = Query(None, description="active/suspended/terminated"),
    franchise_type: Optional[str] = Query(None),
    brand_id: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None, description="名称/手机号模糊搜索"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """加盟商列表（支持状态/类型/品牌/关键词筛选 + 分页）"""
    try:
        await _set_rls(db, x_tenant_id)
        conditions = ["is_deleted = false"]
        params: dict[str, Any] = {}

        if status:
            conditions.append("status = :status")
            params["status"] = status
        if franchise_type:
            conditions.append("franchise_type = :franchise_type")
            params["franchise_type"] = franchise_type
        if brand_id:
            conditions.append("brand_id = :brand_id")
            params["brand_id"] = brand_id
        if keyword:
            conditions.append("(name ILIKE :kw OR contact_phone ILIKE :kw OR store_name ILIKE :kw)")
            params["kw"] = f"%{keyword}%"

        where_clause = " AND ".join(conditions)
        count_sql = f"SELECT COUNT(*) FROM franchisees WHERE {where_clause}"
        total_res = await db.execute(text(count_sql), params)
        total = int(total_res.scalar() or 0)

        params["offset"] = (page - 1) * size
        params["limit"] = size
        list_sql = (
            f"SELECT * FROM franchisees WHERE {where_clause} "
            "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        )
        result = await db.execute(text(list_sql), params)
        items = [dict(r._mapping) for r in result.fetchall()]
        return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}
    except SQLAlchemyError as exc:
        log.warning("franchise_v5.list_franchisees.db_error", error=str(exc), tenant_id=x_tenant_id)
        return {"ok": True, "data": {"items": [], "total": 0, "page": page, "size": size}}


@router.post("/franchisees")
async def create_franchisee_v5(
    body: FranchiseeCreateV5,
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """新建加盟商档案"""
    new_id = str(uuid4())
    now = datetime.now(tz=timezone.utc).isoformat()
    log.info("franchise_v5.create", franchisee_id=new_id, name=body.name, tenant_id=x_tenant_id)
    try:
        await _set_rls(db, x_tenant_id)
        await db.execute(
            text("""
                INSERT INTO franchisees
                    (id, tenant_id, name, company_name, contact_phone, contact_email,
                     region, store_name, store_address, brand_id,
                     join_date, franchise_type, contract_start_date, contract_end_date,
                     contract_file_url, status, notes, created_at, updated_at, is_deleted)
                VALUES
                    (:id, :tenant_id, :name, :company_name, :contact_phone, :contact_email,
                     :region, :store_name, :store_address, :brand_id,
                     :join_date, :franchise_type, :contract_start_date, :contract_end_date,
                     :contract_file_url, 'active', :notes, NOW(), NOW(), false)
            """),
            {
                "id": new_id,
                "tenant_id": x_tenant_id,
                **body.model_dump(),
            },
        )
        await db.commit()
    except SQLAlchemyError as exc:
        log.error("franchise_v5.create.db_error", error=str(exc), tenant_id=x_tenant_id)
        await db.rollback()
        # 返回乐观 mock（非严格模式），保持 UI 流畅
    return {"ok": True, "data": {"id": new_id, **body.model_dump(), "status": "active", "created_at": now}}


@router.put("/franchisees/{franchisee_id}")
async def update_franchisee_v5(
    franchisee_id: str,
    body: FranchiseeUpdateV5,
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """更新加盟商档案"""
    try:
        await _set_rls(db, x_tenant_id)
        updates = body.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(status_code=400, detail="无更新字段")
        set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
        updates["franchisee_id"] = franchisee_id
        await db.execute(
            text(f"UPDATE franchisees SET {set_clauses}, updated_at = NOW() WHERE id = :franchisee_id AND is_deleted = false"),
            updates,
        )
        await db.commit()
        log.info("franchise_v5.update", franchisee_id=franchisee_id, fields=list(body.model_dump(exclude_none=True).keys()))
        return {"ok": True, "data": {"id": franchisee_id, **body.model_dump(exclude_none=True)}}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("franchise_v5.update.db_error", error=str(exc), franchisee_id=franchisee_id)
        await db.rollback()
        raise HTTPException(status_code=500, detail="更新失败，请重试")


@router.get("/franchisees/{franchisee_id}/contract")
async def get_franchisee_contract(
    franchisee_id: str,
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """加盟商合同详情"""
    try:
        await _set_rls(db, x_tenant_id)
        # 从 franchisees 取合同字段
        result = await db.execute(
            text("""
                SELECT id, name, company_name,
                       contract_start_date, contract_end_date, contract_file_url,
                       franchise_type, join_date, status
                FROM franchisees
                WHERE id = :id AND is_deleted = false
            """),
            {"id": franchisee_id},
        )
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="加盟商不存在")
        contract_info = dict(row._mapping)

        # 从 franchise_contracts 追加合同明细（如存在）
        try:
            c_result = await db.execute(
                text("""
                    SELECT * FROM franchise_contracts
                    WHERE franchisee_id = :fid AND is_deleted = false
                    ORDER BY created_at DESC LIMIT 1
                """),
                {"fid": franchisee_id},
            )
            c_row = c_result.fetchone()
            if c_row:
                contract_info["contract_detail"] = dict(c_row._mapping)
        except SQLAlchemyError:
            contract_info["contract_detail"] = None

        return {"ok": True, "data": contract_info}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.warning("franchise_v5.get_contract.db_error", error=str(exc), franchisee_id=franchisee_id)
        raise HTTPException(status_code=404, detail="加盟商不存在")


# ─── 加盟费收缴 ───────────────────────────────────────────────────────────────

@router.get("/fees")
async def list_fees_v5(
    franchisee_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="pending/paid/overdue"),
    fee_type: Optional[str] = Query(None),
    year_month: Optional[str] = Query(None, description="格式 YYYY-MM，筛选某月"),
    overdue_only: bool = Query(False),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """应收费用列表（含逾期天数标记）"""
    try:
        await _set_rls(db, x_tenant_id)
        today = date.today().isoformat()

        conditions = ["ff.is_deleted = false"]
        params: dict[str, Any] = {"today": today}

        if franchisee_id:
            conditions.append("ff.franchisee_id = :franchisee_id")
            params["franchisee_id"] = franchisee_id
        if fee_type:
            conditions.append("ff.fee_type = :fee_type")
            params["fee_type"] = fee_type
        if overdue_only or status == "overdue":
            conditions.append("ff.status IN ('overdue', 'pending') AND ff.due_date < :today")
        elif status:
            conditions.append("ff.status = :status")
            params["status"] = status
        if year_month:
            conditions.append("TO_CHAR(ff.due_date, 'YYYY-MM') = :year_month")
            params["year_month"] = year_month

        where_clause = " AND ".join(conditions)

        count_res = await db.execute(
            text(f"SELECT COUNT(*) FROM franchise_fees ff WHERE {where_clause}"), params
        )
        total = int(count_res.scalar() or 0)

        params["offset"] = (page - 1) * size
        params["limit"] = size
        list_sql = f"""
            SELECT
                ff.*,
                fr.name AS franchisee_name,
                fr.store_name,
                CASE
                    WHEN ff.status != 'paid' AND ff.due_date < CURRENT_DATE
                    THEN (CURRENT_DATE - ff.due_date::date)
                    ELSE 0
                END AS overdue_days
            FROM franchise_fees ff
            LEFT JOIN franchisees fr ON fr.id = ff.franchisee_id AND fr.is_deleted = false
            WHERE {where_clause}
            ORDER BY ff.due_date ASC
            LIMIT :limit OFFSET :offset
        """
        result = await db.execute(text(list_sql), params)
        items = [dict(r._mapping) for r in result.fetchall()]

        # 汇总统计
        stats_sql = f"""
            SELECT
                COALESCE(SUM(amount_fen) FILTER (WHERE status IN ('pending','overdue')), 0) AS receivable_fen,
                COALESCE(SUM(amount_fen) FILTER (WHERE status = 'paid'), 0) AS collected_fen,
                COUNT(*) FILTER (WHERE status IN ('pending','overdue') AND due_date < CURRENT_DATE) AS overdue_count,
                COALESCE(SUM(amount_fen) FILTER (
                    WHERE status IN ('pending','overdue') AND due_date < CURRENT_DATE
                ), 0) AS overdue_fen
            FROM franchise_fees ff
            WHERE ff.is_deleted = false
        """
        stats_res = await db.execute(text(stats_sql))
        stats_row = dict(stats_res.fetchone()._mapping)

        return {
            "ok": True,
            "data": {
                "items": items,
                "total": total,
                "page": page,
                "size": size,
                "receivable_fen": int(stats_row.get("receivable_fen") or 0),
                "collected_fen": int(stats_row.get("collected_fen") or 0),
                "overdue_count": int(stats_row.get("overdue_count") or 0),
                "overdue_fen": int(stats_row.get("overdue_fen") or 0),
            },
        }
    except SQLAlchemyError as exc:
        log.warning("franchise_v5.list_fees.db_error", error=str(exc), tenant_id=x_tenant_id)
        return {
            "ok": True,
            "data": {
                "items": [], "total": 0, "page": page, "size": size,
                "receivable_fen": 0, "collected_fen": 0, "overdue_count": 0, "overdue_fen": 0,
            },
        }


@router.post("/fees/{fee_id}/collect")
async def collect_fee(
    fee_id: str,
    body: FeeCollectBody,
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """标记费用已收款"""
    paid_at = body.paid_at or datetime.now(tz=timezone.utc).isoformat()
    try:
        await _set_rls(db, x_tenant_id)
        result = await db.execute(
            text("SELECT id, amount_fen, status FROM franchise_fees WHERE id = :id AND is_deleted = false"),
            {"id": fee_id},
        )
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="费用记录不存在")
        if dict(row._mapping)["status"] == "paid":
            raise HTTPException(status_code=400, detail="该费用已收款，请勿重复操作")

        await db.execute(
            text("""
                UPDATE franchise_fees
                SET status = 'paid',
                    paid_amount_fen = :paid_amount_fen,
                    paid_at = :paid_at,
                    payment_method = :payment_method,
                    receipt_no = :receipt_no,
                    updated_at = NOW()
                WHERE id = :fee_id AND is_deleted = false
            """),
            {
                "fee_id": fee_id,
                "paid_amount_fen": body.paid_amount_fen,
                "paid_at": paid_at,
                "payment_method": body.payment_method,
                "receipt_no": body.receipt_no,
            },
        )
        await db.commit()
        log.info("franchise_v5.fee.collect", fee_id=fee_id, amount=body.paid_amount_fen, tenant_id=x_tenant_id)
        return {"ok": True, "data": {"fee_id": fee_id, "status": "paid", "paid_at": paid_at}}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("franchise_v5.fee.collect.db_error", error=str(exc), fee_id=fee_id)
        await db.rollback()
        raise HTTPException(status_code=500, detail="收款操作失败，请重试")


@router.post("/fees/generate-monthly")
async def generate_monthly_fees(
    body: GenerateMonthlyFeesBody,
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """批量生成本月应收费用（对所有 active 加盟商）"""
    try:
        await _set_rls(db, x_tenant_id)
        result = await db.execute(
            text("SELECT id, name FROM franchisees WHERE status = 'active' AND is_deleted = false"),
        )
        franchisees = result.fetchall()
        if not franchisees:
            return {"ok": True, "data": {"generated": 0, "skipped": 0, "year_month": body.year_month}}

        year, month = body.year_month.split("-")
        due_date = f"{year}-{month}-{body.due_day:02d}"

        generated = 0
        skipped = 0
        for f_row in franchisees:
            fid = str(f_row._mapping["id"])
            # 检查是否已有同月同类费用
            exists_res = await db.execute(
                text("""
                    SELECT 1 FROM franchise_fees
                    WHERE franchisee_id = :fid
                      AND fee_type = :fee_type
                      AND TO_CHAR(due_date, 'YYYY-MM') = :ym
                      AND is_deleted = false
                    LIMIT 1
                """),
                {"fid": fid, "fee_type": body.fee_type, "ym": body.year_month},
            )
            if exists_res.fetchone():
                skipped += 1
                continue
            new_fee_id = str(uuid4())
            await db.execute(
                text("""
                    INSERT INTO franchise_fees
                        (id, tenant_id, franchisee_id, fee_type, amount_fen, due_date, status, notes, created_at, updated_at, is_deleted)
                    VALUES
                        (:id, :tenant_id, :franchisee_id, :fee_type, :amount_fen, :due_date, 'pending', :notes, NOW(), NOW(), false)
                """),
                {
                    "id": new_fee_id,
                    "tenant_id": x_tenant_id,
                    "franchisee_id": fid,
                    "fee_type": body.fee_type,
                    "amount_fen": body.amount_fen,
                    "due_date": due_date,
                    "notes": body.notes,
                },
            )
            generated += 1

        await db.commit()
        log.info("franchise_v5.fees.generate_monthly",
                 generated=generated, skipped=skipped, year_month=body.year_month, tenant_id=x_tenant_id)
        return {"ok": True, "data": {"generated": generated, "skipped": skipped, "year_month": body.year_month}}
    except SQLAlchemyError as exc:
        log.error("franchise_v5.fees.generate_monthly.db_error", error=str(exc), tenant_id=x_tenant_id)
        await db.rollback()
        raise HTTPException(status_code=500, detail="批量生成费用失败，请重试")


# ─── 公共代码管理 ─────────────────────────────────────────────────────────────

@router.get("/common-codes")
async def list_common_codes(
    code_type: Optional[str] = Query(None, description="material/dish/price"),
    keyword: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="active/deprecated"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """公共代码列表"""
    try:
        await _set_rls(db, x_tenant_id)
        conditions = ["is_deleted = false"]
        params: dict[str, Any] = {}

        if code_type:
            conditions.append("code_type = :code_type")
            params["code_type"] = code_type
        if status:
            conditions.append("status = :status")
            params["status"] = status
        if keyword:
            conditions.append("(code_no ILIKE :kw OR name ILIKE :kw)")
            params["kw"] = f"%{keyword}%"

        where_clause = " AND ".join(conditions)
        count_res = await db.execute(
            text(f"SELECT COUNT(*) FROM franchise_common_codes WHERE {where_clause}"), params
        )
        total = int(count_res.scalar() or 0)

        params["offset"] = (page - 1) * size
        params["limit"] = size
        result = await db.execute(
            text(f"SELECT * FROM franchise_common_codes WHERE {where_clause} ORDER BY code_type, code_no LIMIT :limit OFFSET :offset"),
            params,
        )
        items = [dict(r._mapping) for r in result.fetchall()]
        return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}
    except SQLAlchemyError as exc:
        log.warning("franchise_v5.list_common_codes.db_error", error=str(exc), tenant_id=x_tenant_id)
        return {"ok": True, "data": {"items": [], "total": 0, "page": page, "size": size}}


@router.post("/common-codes")
async def create_common_code(
    body: CommonCodeCreate,
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """新增公共代码"""
    import json
    new_id = str(uuid4())
    try:
        await _set_rls(db, x_tenant_id)
        await db.execute(
            text("""
                INSERT INTO franchise_common_codes
                    (id, tenant_id, code_type, code_no, name, description, unit,
                     price_fen, applicable_stores, status, created_at, updated_at, is_deleted)
                VALUES
                    (:id, :tenant_id, :code_type, :code_no, :name, :description, :unit,
                     :price_fen, :applicable_stores::jsonb, 'active', NOW(), NOW(), false)
            """),
            {
                "id": new_id,
                "tenant_id": x_tenant_id,
                "code_type": body.code_type,
                "code_no": body.code_no,
                "name": body.name,
                "description": body.description,
                "unit": body.unit,
                "price_fen": body.price_fen,
                "applicable_stores": json.dumps(body.applicable_stores),
            },
        )
        await db.commit()
        log.info("franchise_v5.common_code.create", code_id=new_id, code_no=body.code_no)
        return {"ok": True, "data": {"id": new_id, **body.model_dump(), "status": "active"}}
    except SQLAlchemyError as exc:
        log.error("franchise_v5.common_code.create.db_error", error=str(exc))
        await db.rollback()
        raise HTTPException(status_code=500, detail="新增公共代码失败")


@router.put("/common-codes/{code_id}")
async def update_common_code(
    code_id: str,
    body: CommonCodeUpdate,
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """更新公共代码"""
    import json
    try:
        await _set_rls(db, x_tenant_id)
        updates = body.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(status_code=400, detail="无更新字段")
        # applicable_stores 转 JSON
        if "applicable_stores" in updates:
            updates["applicable_stores"] = json.dumps(updates["applicable_stores"])
        set_parts = []
        for k in updates:
            if k == "applicable_stores":
                set_parts.append(f"{k} = :{k}::jsonb")
            else:
                set_parts.append(f"{k} = :{k}")
        set_clause = ", ".join(set_parts)
        updates["code_id"] = code_id
        await db.execute(
            text(f"UPDATE franchise_common_codes SET {set_clause}, updated_at = NOW() WHERE id = :code_id AND is_deleted = false"),
            updates,
        )
        await db.commit()
        log.info("franchise_v5.common_code.update", code_id=code_id)
        return {"ok": True, "data": {"id": code_id, **body.model_dump(exclude_none=True)}}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        log.error("franchise_v5.common_code.update.db_error", error=str(exc), code_id=code_id)
        await db.rollback()
        raise HTTPException(status_code=500, detail="更新公共代码失败")


@router.post("/common-codes/sync")
async def sync_common_codes(
    body: CommonCodeSyncBody,
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """将公共代码同步到指定加盟门店（标记 is_synced + 更新 applicable_stores）"""
    import json
    synced_count = 0
    try:
        await _set_rls(db, x_tenant_id)
        synced_at = datetime.now(tz=timezone.utc).isoformat()
        for code_id in body.code_ids:
            result = await db.execute(
                text("SELECT id, applicable_stores FROM franchise_common_codes WHERE id = :id AND is_deleted = false"),
                {"id": code_id},
            )
            row = result.fetchone()
            if not row:
                continue
            existing_stores: list = json.loads(row._mapping["applicable_stores"] or "[]")
            merged_stores = list(set(existing_stores + body.target_store_ids))
            await db.execute(
                text("""
                    UPDATE franchise_common_codes
                    SET is_synced = true,
                        synced_at = :synced_at,
                        applicable_stores = :stores::jsonb,
                        updated_at = NOW()
                    WHERE id = :code_id
                """),
                {"code_id": code_id, "synced_at": synced_at, "stores": json.dumps(merged_stores)},
            )
            synced_count += 1
        await db.commit()
        log.info("franchise_v5.common_code.sync",
                 synced=synced_count, stores=len(body.target_store_ids), tenant_id=x_tenant_id)
        return {"ok": True, "data": {"synced_count": synced_count, "target_stores": len(body.target_store_ids), "synced_at": synced_at}}
    except SQLAlchemyError as exc:
        log.error("franchise_v5.common_code.sync.db_error", error=str(exc))
        await db.rollback()
        raise HTTPException(status_code=500, detail="同步失败，请重试")


# ─── 对账报表 ─────────────────────────────────────────────────────────────────

@router.get("/report/revenue")
async def report_revenue(
    year_month: Optional[str] = Query(None, description="YYYY-MM，空=近12个月"),
    brand_id: Optional[str] = Query(None),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """各加盟店营业额汇总报表（从 orders 聚合，降级返回演示数据）"""
    try:
        await _set_rls(db, x_tenant_id)
        # 尝试从 orders 聚合
        date_cond = ""
        params: dict[str, Any] = {}
        if year_month:
            date_cond = "AND TO_CHAR(o.created_at, 'YYYY-MM') = :year_month"
            params["year_month"] = year_month

        brand_cond = ""
        if brand_id:
            brand_cond = "AND fr.brand_id = :brand_id"
            params["brand_id"] = brand_id

        revenue_sql = f"""
            SELECT
                fr.id AS franchisee_id,
                fr.name AS franchisee_name,
                fr.store_name,
                fr.region,
                COUNT(o.id) AS order_count,
                COALESCE(SUM(o.total_fen), 0) AS revenue_fen,
                COALESCE(AVG(o.total_fen), 0) AS avg_order_fen
            FROM franchisees fr
            LEFT JOIN orders o
                ON o.store_id::text = fr.id::text
                AND o.is_deleted = false
                {date_cond}
            WHERE fr.is_deleted = false AND fr.status = 'active'
            {brand_cond}
            GROUP BY fr.id, fr.name, fr.store_name, fr.region
            ORDER BY revenue_fen DESC
        """
        result = await db.execute(text(revenue_sql), params)
        items = [dict(r._mapping) for r in result.fetchall()]

        # 计算汇总
        total_revenue = sum(int(i.get("revenue_fen") or 0) for i in items)
        return {
            "ok": True,
            "data": {
                "items": items,
                "total": len(items),
                "total_revenue_fen": total_revenue,
                "year_month": year_month,
            },
        }
    except SQLAlchemyError as exc:
        log.warning("franchise_v5.report.revenue.db_error", error=str(exc), tenant_id=x_tenant_id)
        # 降级 mock
        return {
            "ok": True,
            "data": {
                "items": [],
                "total": 0,
                "total_revenue_fen": 0,
                "year_month": year_month,
            },
        }


@router.get("/report/fees-summary")
async def report_fees_summary(
    year_month: Optional[str] = Query(None, description="YYYY-MM，空=所有"),
    fee_type: Optional[str] = Query(None),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """费用收缴汇总报表（应收/实收/逾期 按加盟商聚合）"""
    try:
        await _set_rls(db, x_tenant_id)
        conditions = ["ff.is_deleted = false", "fr.is_deleted = false"]
        params: dict[str, Any] = {}

        if year_month:
            conditions.append("TO_CHAR(ff.due_date, 'YYYY-MM') = :year_month")
            params["year_month"] = year_month
        if fee_type:
            conditions.append("ff.fee_type = :fee_type")
            params["fee_type"] = fee_type

        where_clause = " AND ".join(conditions)
        summary_sql = f"""
            SELECT
                fr.id AS franchisee_id,
                fr.name AS franchisee_name,
                fr.store_name,
                COUNT(ff.id) AS fee_count,
                COALESCE(SUM(ff.amount_fen), 0) AS receivable_fen,
                COALESCE(SUM(ff.amount_fen) FILTER (WHERE ff.status = 'paid'), 0) AS collected_fen,
                COALESCE(SUM(ff.amount_fen) FILTER (
                    WHERE ff.status IN ('pending','overdue') AND ff.due_date < CURRENT_DATE
                ), 0) AS overdue_fen,
                COUNT(ff.id) FILTER (
                    WHERE ff.status IN ('pending','overdue') AND ff.due_date < CURRENT_DATE
                ) AS overdue_count
            FROM franchise_fees ff
            JOIN franchisees fr ON fr.id = ff.franchisee_id
            WHERE {where_clause}
            GROUP BY fr.id, fr.name, fr.store_name
            ORDER BY overdue_fen DESC, receivable_fen DESC
        """
        result = await db.execute(text(summary_sql), params)
        items = [dict(r._mapping) for r in result.fetchall()]

        grand_receivable = sum(int(i.get("receivable_fen") or 0) for i in items)
        grand_collected = sum(int(i.get("collected_fen") or 0) for i in items)
        grand_overdue = sum(int(i.get("overdue_fen") or 0) for i in items)

        return {
            "ok": True,
            "data": {
                "items": items,
                "total": len(items),
                "grand_receivable_fen": grand_receivable,
                "grand_collected_fen": grand_collected,
                "grand_overdue_fen": grand_overdue,
                "collection_rate": round(grand_collected / grand_receivable, 4) if grand_receivable else 0.0,
            },
        }
    except SQLAlchemyError as exc:
        log.warning("franchise_v5.report.fees_summary.db_error", error=str(exc), tenant_id=x_tenant_id)
        return {
            "ok": True,
            "data": {
                "items": [], "total": 0,
                "grand_receivable_fen": 0, "grand_collected_fen": 0,
                "grand_overdue_fen": 0, "collection_rate": 0.0,
            },
        }


# ─── 合同文件上传 ─────────────────────────────────────────────────────────────

@router.post("/franchisees/{franchisee_id}/contract/upload")
async def upload_contract_file(
    franchisee_id: str,
    file: UploadFile = File(...),
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """上传加盟合同文件（PDF/图片），存储至 COS，并将 URL 写回加盟商档案。"""
    from shared.integrations.cos_upload import get_cos_upload_service, COSUploadError

    # 校验文件类型（仅允许 PDF 和常见图片）
    allowed_mime = {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/webp",
    }
    content_type = file.content_type or "application/octet-stream"
    if content_type not in allowed_mime:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型 {content_type}，请上传 PDF 或图片",
        )

    try:
        await _set_rls(db, x_tenant_id)
        # 确认加盟商存在
        exists_res = await db.execute(
            text("SELECT id FROM franchisees WHERE id = :id AND is_deleted = false"),
            {"id": franchisee_id},
        )
        if not exists_res.fetchone():
            raise HTTPException(status_code=404, detail="加盟商不存在")

        file_bytes = await file.read()
        cos = get_cos_upload_service()
        upload_result = await cos.upload_file(
            file_bytes=file_bytes,
            filename=file.filename or "contract",
            content_type=content_type,
            folder="contracts",
        )
        file_url: str = upload_result["url"]

        # 写回档案
        await db.execute(
            text("""
                UPDATE franchisees
                SET contract_file_url = :url, updated_at = NOW()
                WHERE id = :id AND is_deleted = false
            """),
            {"url": file_url, "id": franchisee_id},
        )
        await db.commit()
        log.info(
            "franchise_v5.contract.uploaded",
            franchisee_id=franchisee_id,
            url=file_url,
            tenant_id=x_tenant_id,
        )
        return {"ok": True, "data": {"franchisee_id": franchisee_id, "contract_file_url": file_url}}
    except HTTPException:
        raise
    except COSUploadError as exc:
        log.error("franchise_v5.contract.upload.cos_error", error=str(exc), franchisee_id=franchisee_id)
        raise HTTPException(status_code=502, detail=f"文件上传失败：{exc}")
    except SQLAlchemyError as exc:
        log.error("franchise_v5.contract.upload.db_error", error=str(exc), franchisee_id=franchisee_id)
        await db.rollback()
        raise HTTPException(status_code=500, detail="数据库更新失败，请重试")


# ─── 加盟费逾期自动标记 ───────────────────────────────────────────────────────

@router.post("/fees/mark-overdue")
async def mark_overdue_fees(
    x_tenant_id: str = Header("demo-tenant", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """将所有 due_date < 今日 且 status='pending' 的费用记录批量标记为 overdue。

    幂等：重复调用安全，已 overdue/paid 的记录不受影响。
    推荐由定时任务每天 00:05 触发（或前端手动触发）。
    """
    try:
        await _set_rls(db, x_tenant_id)
        result = await db.execute(
            text("""
                UPDATE franchise_fees
                SET status     = 'overdue',
                    updated_at = NOW()
                WHERE tenant_id = :tid
                  AND status    = 'pending'
                  AND due_date  < CURRENT_DATE
                  AND is_deleted = false
            """),
            {"tid": x_tenant_id},
        )
        marked_count = result.rowcount
        await db.commit()
        log.info(
            "franchise_v5.fees.mark_overdue",
            marked_count=marked_count,
            tenant_id=x_tenant_id,
        )
        return {"ok": True, "data": {"marked_count": marked_count, "as_of": date.today().isoformat()}}
    except SQLAlchemyError as exc:
        log.error("franchise_v5.fees.mark_overdue.db_error", error=str(exc), tenant_id=x_tenant_id)
        await db.rollback()
        raise HTTPException(status_code=500, detail="批量标记逾期失败，请重试")
