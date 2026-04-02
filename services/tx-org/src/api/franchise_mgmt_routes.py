"""加盟管理 API — v2 完整版

基于 v125 迁移（franchisees / franchise_stores / franchise_royalty_rules /
franchise_royalty_bills / franchise_kpi_records）实现完整的加盟管理功能。

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
金额单位：分（int）；比率：Decimal。

端点清单：
  ─ 加盟商管理 ─
  GET    /api/v1/org/franchise/franchisees              — 列表（多维过滤）
  POST   /api/v1/org/franchise/franchisees              — 新建（status=applying）
  GET    /api/v1/org/franchise/franchisees/{id}         — 详情（含旗下门店）
  PATCH  /api/v1/org/franchise/franchisees/{id}/status  — 状态推进

  ─ 加盟门店 & 门店复制 ─
  POST   /api/v1/org/franchise/franchise-stores                        — 创建加盟门店
  POST   /api/v1/org/franchise/franchise-stores/{store_id}/clone       — 触发门店复制
  GET    /api/v1/org/franchise/franchise-stores/{store_id}/clone-status — 查询复制进度

  ─ 分润规则 ─
  GET    /api/v1/org/franchise/royalty-rules            — 查询规则
  POST   /api/v1/org/franchise/royalty-rules            — 创建规则

  ─ 分润账单 ─
  POST   /api/v1/org/franchise/royalty-bills/generate   — 生成月度账单
  GET    /api/v1/org/franchise/royalty-bills            — 账单列表
  PATCH  /api/v1/org/franchise/royalty-bills/{id}/pay   — 标记已付款

  ─ 绩效考核 ─
  POST   /api/v1/org/franchise/kpi-records              — 录入月度KPI
  GET    /api/v1/org/franchise/kpi-records              — 查询历年KPI
  GET    /api/v1/org/franchise/kpi-dashboard            — 绩效看板
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..services.franchise_clone_service import clone_store, _update_clone_status

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/org/franchise", tags=["franchise-management"])

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_VALID_FRANCHISEE_STATUSES = {
    "applying", "signing", "preparing", "operating", "suspended", "terminated",
}
_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "applying":   {"signing", "terminated"},
    "signing":    {"preparing", "terminated"},
    "preparing":  {"operating", "terminated"},
    "operating":  {"suspended", "terminated"},
    "suspended":  {"operating", "terminated"},
    "terminated": set(),
}
_VALID_TIERS = {"standard", "premium", "flagship"}
_VALID_RULE_TYPES = {"revenue_pct", "fixed_monthly", "tiered_revenue"}
_VALID_APPLIES_TO = {"all", "dine_in", "takeaway", "retail"}


def _tenant_id(request: Request) -> str:
    tid = request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": None}


def _row_to_dict(row: Any) -> dict[str, Any]:
    """将 SQLAlchemy Row 转为可 JSON 序列化的 dict。"""
    d = dict(row._mapping)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif isinstance(v, Decimal):
            d[k] = float(v)
        elif not isinstance(v, (str, int, float, bool, dict, list, type(None))):
            d[k] = str(v)
    return d


def _rows_to_list(rows: Any) -> list[dict[str, Any]]:
    return [_row_to_dict(r) for r in rows]


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """为当前 DB 会话设置 RLS 上下文变量。"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class CreateFranchiseeReq(BaseModel):
    franchisee_no: str = Field(..., max_length=50, description="加盟商编号，租户内唯一")
    legal_name: str = Field(..., max_length=200, description="工商注册名称")
    brand_name: Optional[str] = Field(None, max_length=100)
    contact_name: Optional[str] = Field(None, max_length=50)
    contact_phone: Optional[str] = Field(None, max_length=20)
    contact_email: Optional[str] = Field(None, max_length=100)
    province: Optional[str] = Field(None, max_length=50)
    city: Optional[str] = Field(None, max_length=50)
    district: Optional[str] = Field(None, max_length=50)
    address: Optional[str] = Field(None, max_length=300)
    business_license_no: Optional[str] = Field(None, max_length=50)
    legal_person_name: Optional[str] = Field(None, max_length=50)
    tier: str = Field("standard", description="standard/premium/flagship")
    contract_start_date: Optional[str] = Field(None, description="YYYY-MM-DD")
    contract_end_date: Optional[str] = Field(None, description="YYYY-MM-DD")
    initial_fee_fen: int = Field(0, ge=0, description="入门费（分）")
    royalty_rate: Decimal = Field(Decimal("0.05"), description="特许经营费比率，如 0.05")
    notes: Optional[str] = None

    @field_validator("tier")
    @classmethod
    def validate_tier(cls, v: str) -> str:
        if v not in _VALID_TIERS:
            raise ValueError(f"tier 必须是 {_VALID_TIERS} 之一")
        return v

    @field_validator("royalty_rate")
    @classmethod
    def validate_royalty_rate(cls, v: Decimal) -> Decimal:
        if not (Decimal("0") < v < Decimal("1")):
            raise ValueError("royalty_rate 必须在 0~1 之间（不含边界）")
        return v


class PatchStatusReq(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in _VALID_FRANCHISEE_STATUSES:
            raise ValueError(f"status 无效，允许值：{_VALID_FRANCHISEE_STATUSES}")
        return v


class CreateFranchiseStoreReq(BaseModel):
    franchisee_id: str = Field(..., description="加盟商 UUID")
    store_id: str = Field(..., max_length=100, description="关联 stores.id")
    store_name: str = Field(..., max_length=200)
    open_date: Optional[str] = Field(None, description="YYYY-MM-DD")
    template_store_id: Optional[str] = Field(
        None, max_length=100,
        description="若填写则创建后自动触发门店复制",
    )


class CreateRoyaltyRuleReq(BaseModel):
    franchisee_id: str
    rule_type: str = Field(..., description="revenue_pct/fixed_monthly/tiered_revenue")
    revenue_pct: Optional[Decimal] = Field(None, description="如 0.05 = 5%")
    monthly_fee_fen: Optional[int] = Field(None, ge=0, description="固定月费（分）")
    tiers: Optional[list[dict]] = Field(
        None,
        description="分档规则，如 [{min:0,max:100000,rate:0.08},{min:100000,rate:0.05}]",
    )
    applies_to: str = Field("all", description="all/dine_in/takeaway/retail")
    effective_from: str = Field(..., description="YYYY-MM-DD")
    effective_to: Optional[str] = Field(None, description="YYYY-MM-DD，空=长期有效")

    @field_validator("rule_type")
    @classmethod
    def validate_rule_type(cls, v: str) -> str:
        if v not in _VALID_RULE_TYPES:
            raise ValueError(f"rule_type 必须是 {_VALID_RULE_TYPES} 之一")
        return v

    @field_validator("applies_to")
    @classmethod
    def validate_applies_to(cls, v: str) -> str:
        if v not in _VALID_APPLIES_TO:
            raise ValueError(f"applies_to 必须是 {_VALID_APPLIES_TO} 之一")
        return v


class GenerateBillReq(BaseModel):
    franchisee_id: str
    store_id: str
    bill_period: str = Field(..., pattern=r"^\d{4}-\d{2}$", description="YYYY-MM")
    revenue_fen: int = Field(..., ge=0, description="当期营收（分）")
    initial_fee_fen: int = Field(0, ge=0, description="首期入门费（分），首期才填写")
    other_fee_fen: int = Field(0, ge=0, description="其他杂项费用（分）")
    due_date: Optional[str] = Field(None, description="YYYY-MM-DD")
    notes: Optional[str] = None


class CreateKpiRecordReq(BaseModel):
    franchisee_id: str
    store_id: str
    kpi_period: str = Field(..., pattern=r"^\d{4}-\d{2}$", description="YYYY-MM")
    revenue_target_fen: int = Field(0, ge=0)
    revenue_actual_fen: int = Field(0, ge=0)
    order_count_target: int = Field(0, ge=0)
    order_count_actual: int = Field(0, ge=0)
    customer_satisfaction_score: Optional[Decimal] = Field(None, ge=0, le=10)
    food_safety_score: Optional[Decimal] = Field(None, ge=0, le=10)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  加盟商管理
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/franchisees")
async def list_franchisees(
    request: Request,
    status: Optional[str] = Query(None, description="状态过滤"),
    tier: Optional[str] = Query(None, description="层级过滤"),
    city: Optional[str] = Query(None, description="城市过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """加盟商列表，支持 status / tier / city 多维过滤，含分页。"""
    tenant_id = _tenant_id(request)
    await _set_tenant(db, tenant_id)

    conditions = ["tenant_id = :tenant_id", "is_deleted = false"]
    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "limit": size,
        "offset": (page - 1) * size,
    }

    if status:
        if status not in _VALID_FRANCHISEE_STATUSES:
            raise HTTPException(status_code=400, detail=f"status 无效：{status}")
        conditions.append("status = :status")
        params["status"] = status

    if tier:
        if tier not in _VALID_TIERS:
            raise HTTPException(status_code=400, detail=f"tier 无效：{tier}")
        conditions.append("tier = :tier")
        params["tier"] = tier

    if city:
        conditions.append("city = :city")
        params["city"] = city

    where = " AND ".join(conditions)
    total_row = await db.execute(
        text(f"SELECT count(*) FROM franchisees WHERE {where}"),
        params,
    )
    total: int = total_row.scalar_one()

    rows = await db.execute(
        text(f"""
            SELECT * FROM franchisees
             WHERE {where}
             ORDER BY created_at DESC
             LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = _rows_to_list(rows)
    return _ok({"items": items, "total": total, "page": page, "size": size})


@router.post("/franchisees", status_code=201)
async def create_franchisee(
    req: CreateFranchiseeReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """新建加盟商，初始 status=applying。"""
    tenant_id = _tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 校验编号唯一性
    dup = await db.execute(
        text("""
            SELECT id FROM franchisees
             WHERE tenant_id = :tid AND franchisee_no = :no AND is_deleted = false
        """),
        {"tid": tenant_id, "no": req.franchisee_no},
    )
    if dup.first():
        raise HTTPException(
            status_code=409,
            detail=f"加盟商编号 {req.franchisee_no} 已存在",
        )

    row = await db.execute(
        text("""
            INSERT INTO franchisees (
                tenant_id, franchisee_no, legal_name, brand_name,
                contact_name, contact_phone, contact_email,
                province, city, district, address,
                business_license_no, legal_person_name,
                status, tier,
                contract_start_date, contract_end_date,
                initial_fee_fen, royalty_rate, notes
            ) VALUES (
                :tenant_id, :franchisee_no, :legal_name, :brand_name,
                :contact_name, :contact_phone, :contact_email,
                :province, :city, :district, :address,
                :business_license_no, :legal_person_name,
                'applying', :tier,
                :contract_start_date, :contract_end_date,
                :initial_fee_fen, :royalty_rate, :notes
            )
            RETURNING *
        """),
        {
            "tenant_id": tenant_id,
            "franchisee_no": req.franchisee_no,
            "legal_name": req.legal_name,
            "brand_name": req.brand_name,
            "contact_name": req.contact_name,
            "contact_phone": req.contact_phone,
            "contact_email": req.contact_email,
            "province": req.province,
            "city": req.city,
            "district": req.district,
            "address": req.address,
            "business_license_no": req.business_license_no,
            "legal_person_name": req.legal_person_name,
            "tier": req.tier,
            "contract_start_date": req.contract_start_date,
            "contract_end_date": req.contract_end_date,
            "initial_fee_fen": req.initial_fee_fen,
            "royalty_rate": str(req.royalty_rate),
            "notes": req.notes,
        },
    )
    await db.commit()
    created = _row_to_dict(row.one())
    log.info("franchisee.created", tenant_id=tenant_id, id=created.get("id"))
    return _ok(created)


@router.get("/franchisees/{franchisee_id}")
async def get_franchisee(
    franchisee_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """加盟商详情，含旗下门店列表。"""
    tenant_id = _tenant_id(request)
    await _set_tenant(db, tenant_id)

    row = await db.execute(
        text("""
            SELECT * FROM franchisees
             WHERE id = :id AND tenant_id = :tid AND is_deleted = false
        """),
        {"id": franchisee_id, "tid": tenant_id},
    )
    franchisee = row.first()
    if not franchisee:
        raise HTTPException(status_code=404, detail="加盟商不存在")

    stores_rows = await db.execute(
        text("""
            SELECT * FROM franchise_stores
             WHERE franchisee_id = :fid AND tenant_id = :tid
             ORDER BY created_at DESC
        """),
        {"fid": franchisee_id, "tid": tenant_id},
    )
    franchisee_dict = _row_to_dict(franchisee)
    franchisee_dict["stores"] = _rows_to_list(stores_rows)
    return _ok(franchisee_dict)


@router.patch("/franchisees/{franchisee_id}/status")
async def patch_franchisee_status(
    franchisee_id: str,
    req: PatchStatusReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """推进加盟商状态（applying→signing→preparing→operating 等）。"""
    tenant_id = _tenant_id(request)
    await _set_tenant(db, tenant_id)

    row = await db.execute(
        text("""
            SELECT id, status FROM franchisees
             WHERE id = :id AND tenant_id = :tid AND is_deleted = false
        """),
        {"id": franchisee_id, "tid": tenant_id},
    )
    record = row.first()
    if not record:
        raise HTTPException(status_code=404, detail="加盟商不存在")

    current_status: str = record.status
    allowed: set[str] = _STATUS_TRANSITIONS.get(current_status, set())
    if req.status not in allowed:
        raise HTTPException(
            status_code=422,
            detail=(
                f"当前状态 '{current_status}' 不允许转换到 '{req.status}'。"
                f"允许的目标状态：{allowed or '（无可转换状态）'}"
            ),
        )

    await db.execute(
        text("""
            UPDATE franchisees
               SET status = :status, updated_at = now()
             WHERE id = :id AND tenant_id = :tid
        """),
        {"status": req.status, "id": franchisee_id, "tid": tenant_id},
    )
    await db.commit()
    log.info(
        "franchisee.status_changed",
        tenant_id=tenant_id,
        id=franchisee_id,
        from_status=current_status,
        to_status=req.status,
    )
    return _ok({"id": franchisee_id, "status": req.status})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  加盟门店 & 门店复制
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/franchise-stores", status_code=201)
async def create_franchise_store(
    req: CreateFranchiseStoreReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建加盟门店。若填写 template_store_id，则自动触发异步门店复制。"""
    tenant_id = _tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 校验加盟商存在
    franchisee_row = await db.execute(
        text("""
            SELECT id FROM franchisees
             WHERE id = :fid AND tenant_id = :tid AND is_deleted = false
        """),
        {"fid": req.franchisee_id, "tid": tenant_id},
    )
    if not franchisee_row.first():
        raise HTTPException(status_code=404, detail="加盟商不存在")

    clone_status = "pending" if req.template_store_id else None

    row = await db.execute(
        text("""
            INSERT INTO franchise_stores (
                tenant_id, franchisee_id, store_id, store_name,
                open_date, status, template_store_id, clone_status
            ) VALUES (
                :tenant_id, :franchisee_id, :store_id, :store_name,
                :open_date, 'preparing', :template_store_id, :clone_status
            )
            RETURNING *
        """),
        {
            "tenant_id": tenant_id,
            "franchisee_id": req.franchisee_id,
            "store_id": req.store_id,
            "store_name": req.store_name,
            "open_date": req.open_date,
            "template_store_id": req.template_store_id,
            "clone_status": clone_status,
        },
    )
    await db.commit()
    created = _row_to_dict(row.one())

    # 若填写了模板门店则异步触发复制（非阻塞）
    if req.template_store_id:
        asyncio.create_task(
            _run_clone_async(
                tenant_id=tenant_id,
                template_store_id=req.template_store_id,
                target_store_id=req.store_id,
            )
        )
        log.info(
            "franchise_store.clone_triggered",
            tenant_id=tenant_id,
            target_store_id=req.store_id,
            template_store_id=req.template_store_id,
        )

    return _ok(created)


async def _run_clone_async(
    tenant_id: str,
    template_store_id: str,
    target_store_id: str,
) -> None:
    """后台异步执行门店复制，完成后更新 clone_status。"""
    from shared.ontology.src.database import async_session_factory  # 延迟导入避免循环

    async with async_session_factory() as db:
        try:
            await _update_clone_status(db, tenant_id, target_store_id, "cloning")
            result = await clone_store(db, tenant_id, template_store_id, target_store_id)
            final = result["status"]  # "completed" | "failed"
            await _update_clone_status(db, tenant_id, target_store_id, final)
        except (OSError, RuntimeError, ValueError) as exc:
            log.error(
                "franchise_clone.async_error",
                tenant_id=tenant_id,
                target_store_id=target_store_id,
                exc=str(exc),
            )
            try:
                await _update_clone_status(db, tenant_id, target_store_id, "failed")
            except (OSError, RuntimeError) as inner_exc:
                log.error(
                    "franchise_clone.status_update_failed",
                    exc=str(inner_exc),
                )


@router.post("/franchise-stores/{store_id}/clone")
async def trigger_store_clone(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """手动触发门店复制（已有 template_store_id 的门店）。异步执行，立即返回。"""
    tenant_id = _tenant_id(request)
    await _set_tenant(db, tenant_id)

    row = await db.execute(
        text("""
            SELECT store_id, template_store_id, clone_status
              FROM franchise_stores
             WHERE store_id = :store_id AND tenant_id = :tid
        """),
        {"store_id": store_id, "tid": tenant_id},
    )
    fs = row.first()
    if not fs:
        raise HTTPException(status_code=404, detail="加盟门店不存在")
    if not fs.template_store_id:
        raise HTTPException(status_code=422, detail="该门店未设置 template_store_id，无法触发复制")
    if fs.clone_status == "cloning":
        raise HTTPException(status_code=409, detail="门店复制正在进行中，请勿重复触发")

    await _update_clone_status(db, tenant_id, store_id, "pending")

    asyncio.create_task(
        _run_clone_async(
            tenant_id=tenant_id,
            template_store_id=fs.template_store_id,
            target_store_id=store_id,
        )
    )
    log.info(
        "franchise_store.clone_manually_triggered",
        tenant_id=tenant_id,
        store_id=store_id,
    )
    return _ok({"store_id": store_id, "clone_status": "cloning", "message": "门店复制已触发，请轮询状态"})


@router.get("/franchise-stores/{store_id}/clone-status")
async def get_clone_status(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询门店复制进度。"""
    tenant_id = _tenant_id(request)
    await _set_tenant(db, tenant_id)

    row = await db.execute(
        text("""
            SELECT store_id, store_name, template_store_id, clone_status, updated_at
              FROM franchise_stores
             WHERE store_id = :store_id AND tenant_id = :tid
        """),
        {"store_id": store_id, "tid": tenant_id},
    )
    fs = row.first()
    if not fs:
        raise HTTPException(status_code=404, detail="加盟门店不存在")

    return _ok(_row_to_dict(fs))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  分润规则
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/royalty-rules")
async def list_royalty_rules(
    franchisee_id: Optional[str] = Query(None),
    request: Request = ...,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询分润规则。"""
    tenant_id = _tenant_id(request)
    await _set_tenant(db, tenant_id)

    conditions = ["tenant_id = :tid"]
    params: dict[str, Any] = {"tid": tenant_id}

    if franchisee_id:
        conditions.append("franchisee_id = :fid")
        params["fid"] = franchisee_id

    where = " AND ".join(conditions)
    rows = await db.execute(
        text(f"SELECT * FROM franchise_royalty_rules WHERE {where} ORDER BY effective_from DESC"),
        params,
    )
    return _ok({"items": _rows_to_list(rows)})


@router.post("/royalty-rules", status_code=201)
async def create_royalty_rule(
    req: CreateRoyaltyRuleReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建分润规则。"""
    tenant_id = _tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 校验加盟商存在
    frow = await db.execute(
        text("SELECT id FROM franchisees WHERE id = :fid AND tenant_id = :tid AND is_deleted = false"),
        {"fid": req.franchisee_id, "tid": tenant_id},
    )
    if not frow.first():
        raise HTTPException(status_code=404, detail="加盟商不存在")

    # 业务校验：各 rule_type 对应字段必须填写
    if req.rule_type == "revenue_pct" and req.revenue_pct is None:
        raise HTTPException(status_code=422, detail="rule_type=revenue_pct 时 revenue_pct 必填")
    if req.rule_type == "fixed_monthly" and req.monthly_fee_fen is None:
        raise HTTPException(status_code=422, detail="rule_type=fixed_monthly 时 monthly_fee_fen 必填")
    if req.rule_type == "tiered_revenue" and not req.tiers:
        raise HTTPException(status_code=422, detail="rule_type=tiered_revenue 时 tiers 必填")

    import json
    tiers_json = json.dumps(req.tiers) if req.tiers else None

    row = await db.execute(
        text("""
            INSERT INTO franchise_royalty_rules (
                tenant_id, franchisee_id, rule_type,
                revenue_pct, monthly_fee_fen, tiers,
                applies_to, effective_from, effective_to, is_active
            ) VALUES (
                :tenant_id, :franchisee_id, :rule_type,
                :revenue_pct, :monthly_fee_fen, :tiers::jsonb,
                :applies_to, :effective_from, :effective_to, true
            )
            RETURNING *
        """),
        {
            "tenant_id": tenant_id,
            "franchisee_id": req.franchisee_id,
            "rule_type": req.rule_type,
            "revenue_pct": str(req.revenue_pct) if req.revenue_pct is not None else None,
            "monthly_fee_fen": req.monthly_fee_fen,
            "tiers": tiers_json,
            "applies_to": req.applies_to,
            "effective_from": req.effective_from,
            "effective_to": req.effective_to,
        },
    )
    await db.commit()
    created = _row_to_dict(row.one())
    return _ok(created)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  分润账单
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _calculate_royalty(
    rule_type: str,
    revenue_fen: int,
    revenue_pct: Optional[Decimal],
    monthly_fee_fen: Optional[int],
    tiers: Optional[list],
) -> tuple[Decimal, int]:
    """按规则类型计算分润金额，返回 (rate_applied, royalty_amount_fen)。"""
    if rule_type == "revenue_pct":
        rate = revenue_pct or Decimal("0")
        amount = int(Decimal(revenue_fen) * rate)
        return rate, amount

    if rule_type == "fixed_monthly":
        fee = monthly_fee_fen or 0
        # 固定月费时比率快照设为 0
        return Decimal("0"), fee

    if rule_type == "tiered_revenue" and tiers:
        # 按分档逐段累计
        remaining = revenue_fen
        total_royalty = 0
        effective_rate = Decimal("0")
        sorted_tiers = sorted(tiers, key=lambda t: t.get("min", 0))
        for tier_item in sorted_tiers:
            t_min = tier_item.get("min", 0)
            t_max = tier_item.get("max")
            t_rate = Decimal(str(tier_item.get("rate", 0)))
            if remaining <= 0:
                break
            if t_max is not None:
                segment = min(remaining, t_max - t_min)
            else:
                segment = remaining
            segment = max(segment, 0)
            total_royalty += int(Decimal(segment) * t_rate)
            remaining -= segment
            effective_rate = t_rate  # 最后一段的 rate 作为快照
        return effective_rate, total_royalty

    return Decimal("0"), 0


@router.post("/royalty-bills/generate", status_code=201)
async def generate_royalty_bill(
    req: GenerateBillReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """生成月度分润账单（upsert，同期重新生成覆盖）。

    按 franchisee 的激活规则计算：
      revenue_pct    → 营收 × 比率
      fixed_monthly  → 固定月费
      tiered_revenue → 分档累计
    """
    tenant_id = _tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 查激活规则（优先精确期间匹配，再取最近生效的）
    rule_row = await db.execute(
        text("""
            SELECT rule_type, revenue_pct, monthly_fee_fen, tiers
              FROM franchise_royalty_rules
             WHERE franchisee_id = :fid
               AND tenant_id    = :tid
               AND is_active    = true
               AND effective_from <= :period_end
               AND (effective_to IS NULL OR effective_to >= :period_start)
             ORDER BY effective_from DESC
             LIMIT 1
        """),
        {
            "fid": req.franchisee_id,
            "tid": tenant_id,
            "period_start": f"{req.bill_period}-01",
            "period_end": f"{req.bill_period}-28",  # 保守取 28 日，总在月内
        },
    )
    rule = rule_row.first()
    if not rule:
        raise HTTPException(
            status_code=422,
            detail=f"加盟商 {req.franchisee_id} 在 {req.bill_period} 无有效分润规则",
        )

    import json as _json
    tiers = _json.loads(rule.tiers) if rule.tiers else None
    rate_applied, royalty_amount_fen = _calculate_royalty(
        rule_type=rule.rule_type,
        revenue_fen=req.revenue_fen,
        revenue_pct=Decimal(str(rule.revenue_pct)) if rule.revenue_pct else None,
        monthly_fee_fen=rule.monthly_fee_fen,
        tiers=tiers,
    )
    total_due_fen = royalty_amount_fen + req.initial_fee_fen + req.other_fee_fen

    # upsert：同加盟商 + 同门店 + 同账期 → 覆盖
    row = await db.execute(
        text("""
            INSERT INTO franchise_royalty_bills (
                tenant_id, franchisee_id, store_id, bill_period,
                revenue_fen, royalty_rate_applied, royalty_amount_fen,
                initial_fee_fen, other_fee_fen, total_due_fen,
                status, due_date, notes
            ) VALUES (
                :tenant_id, :franchisee_id, :store_id, :bill_period,
                :revenue_fen, :royalty_rate_applied, :royalty_amount_fen,
                :initial_fee_fen, :other_fee_fen, :total_due_fen,
                'pending', :due_date, :notes
            )
            ON CONFLICT (franchisee_id, store_id, bill_period)
            DO UPDATE SET
                revenue_fen          = EXCLUDED.revenue_fen,
                royalty_rate_applied = EXCLUDED.royalty_rate_applied,
                royalty_amount_fen   = EXCLUDED.royalty_amount_fen,
                initial_fee_fen      = EXCLUDED.initial_fee_fen,
                other_fee_fen        = EXCLUDED.other_fee_fen,
                total_due_fen        = EXCLUDED.total_due_fen,
                status               = 'pending',
                due_date             = EXCLUDED.due_date,
                notes                = EXCLUDED.notes
            RETURNING *
        """),
        {
            "tenant_id": tenant_id,
            "franchisee_id": req.franchisee_id,
            "store_id": req.store_id,
            "bill_period": req.bill_period,
            "revenue_fen": req.revenue_fen,
            "royalty_rate_applied": str(rate_applied),
            "royalty_amount_fen": royalty_amount_fen,
            "initial_fee_fen": req.initial_fee_fen,
            "other_fee_fen": req.other_fee_fen,
            "total_due_fen": total_due_fen,
            "due_date": req.due_date,
            "notes": req.notes,
        },
    )
    await db.commit()
    bill = _row_to_dict(row.one())
    log.info(
        "royalty_bill.generated",
        tenant_id=tenant_id,
        franchisee_id=req.franchisee_id,
        bill_period=req.bill_period,
        total_due_fen=total_due_fen,
    )
    return _ok(bill)


@router.get("/royalty-bills")
async def list_royalty_bills(
    request: Request,
    franchisee_id: Optional[str] = Query(None),
    period: Optional[str] = Query(None, description="YYYY-MM"),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """账单列表，支持 franchisee_id / period / status 过滤。"""
    tenant_id = _tenant_id(request)
    await _set_tenant(db, tenant_id)

    conditions = ["tenant_id = :tid"]
    params: dict[str, Any] = {"tid": tenant_id, "limit": size, "offset": (page - 1) * size}

    if franchisee_id:
        conditions.append("franchisee_id = :fid")
        params["fid"] = franchisee_id
    if period:
        conditions.append("bill_period = :period")
        params["period"] = period
    if status:
        conditions.append("status = :status")
        params["status"] = status

    where = " AND ".join(conditions)
    total_row = await db.execute(
        text(f"SELECT count(*) FROM franchise_royalty_bills WHERE {where}"), params
    )
    total: int = total_row.scalar_one()

    rows = await db.execute(
        text(f"""
            SELECT * FROM franchise_royalty_bills
             WHERE {where}
             ORDER BY bill_period DESC, created_at DESC
             LIMIT :limit OFFSET :offset
        """),
        params,
    )
    return _ok({"items": _rows_to_list(rows), "total": total, "page": page, "size": size})


@router.patch("/royalty-bills/{bill_id}/pay")
async def pay_royalty_bill(
    bill_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """标记账单已付款（pending/invoiced/overdue → paid）。"""
    tenant_id = _tenant_id(request)
    await _set_tenant(db, tenant_id)

    row = await db.execute(
        text("SELECT id, status FROM franchise_royalty_bills WHERE id = :id AND tenant_id = :tid"),
        {"id": bill_id, "tid": tenant_id},
    )
    bill = row.first()
    if not bill:
        raise HTTPException(status_code=404, detail="账单不存在")
    if bill.status == "paid":
        raise HTTPException(status_code=409, detail="账单已标记为已付款")
    if bill.status not in {"pending", "invoiced", "overdue"}:
        raise HTTPException(status_code=422, detail=f"当前状态 '{bill.status}' 不支持付款操作")

    await db.execute(
        text("""
            UPDATE franchise_royalty_bills
               SET status = 'paid', paid_at = now()
             WHERE id = :id AND tenant_id = :tid
        """),
        {"id": bill_id, "tid": tenant_id},
    )
    await db.commit()
    log.info("royalty_bill.paid", tenant_id=tenant_id, bill_id=bill_id)
    return _ok({"id": bill_id, "status": "paid"})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  绩效考核
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _compute_overall_score(
    revenue_target: int,
    revenue_actual: int,
    order_target: int,
    order_actual: int,
    satisfaction: Optional[Decimal],
    food_safety: Optional[Decimal],
) -> tuple[Decimal, str]:
    """
    综合评分计算规则（加权）：
      营收完成率  40%
      订单完成率  30%
      顾客满意度  15%（满分 10 分，折算为 0~1）
      食安得分   15%（满分 10 分，折算为 0~1）

    返回 (overall_score: 0~100, tier_recommendation)
    """
    rev_rate = min(Decimal(revenue_actual) / Decimal(max(revenue_target, 1)), Decimal("1.5"))
    ord_rate = min(Decimal(order_actual) / Decimal(max(order_target, 1)), Decimal("1.5"))
    sat_rate = (satisfaction / Decimal("10")) if satisfaction else Decimal("0.7")
    fs_rate = (food_safety / Decimal("10")) if food_safety else Decimal("0.7")

    score = (
        rev_rate * Decimal("40")
        + ord_rate * Decimal("30")
        + sat_rate * Decimal("15")
        + fs_rate * Decimal("15")
    ).quantize(Decimal("0.01"))

    # 层级建议
    if score >= Decimal("90"):
        tier_rec = "flagship"
    elif score >= Decimal("75"):
        tier_rec = "premium"
    elif score >= Decimal("60"):
        tier_rec = "standard"
    else:
        tier_rec = "downgrade"

    return score, tier_rec


@router.post("/kpi-records", status_code=201)
async def create_kpi_record(
    req: CreateKpiRecordReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """录入月度 KPI 数据，自动计算综合评分和层级建议。"""
    tenant_id = _tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 校验加盟商存在
    frow = await db.execute(
        text("SELECT id FROM franchisees WHERE id = :fid AND tenant_id = :tid AND is_deleted = false"),
        {"fid": req.franchisee_id, "tid": tenant_id},
    )
    if not frow.first():
        raise HTTPException(status_code=404, detail="加盟商不存在")

    overall_score, tier_recommendation = _compute_overall_score(
        revenue_target=req.revenue_target_fen,
        revenue_actual=req.revenue_actual_fen,
        order_target=req.order_count_target,
        order_actual=req.order_count_actual,
        satisfaction=req.customer_satisfaction_score,
        food_safety=req.food_safety_score,
    )

    kpi_month = f"{req.kpi_period}-01"

    row = await db.execute(
        text("""
            INSERT INTO franchise_kpi_records (
                tenant_id, franchisee_id, store_id,
                kpi_period, kpi_month,
                revenue_target_fen, revenue_actual_fen,
                order_count_target, order_count_actual,
                customer_satisfaction_score, food_safety_score,
                overall_score, tier_recommendation
            ) VALUES (
                :tenant_id, :franchisee_id, :store_id,
                :kpi_period, :kpi_month,
                :revenue_target_fen, :revenue_actual_fen,
                :order_count_target, :order_count_actual,
                :customer_satisfaction_score, :food_safety_score,
                :overall_score, :tier_recommendation
            )
            RETURNING *
        """),
        {
            "tenant_id": tenant_id,
            "franchisee_id": req.franchisee_id,
            "store_id": req.store_id,
            "kpi_period": req.kpi_period,
            "kpi_month": kpi_month,
            "revenue_target_fen": req.revenue_target_fen,
            "revenue_actual_fen": req.revenue_actual_fen,
            "order_count_target": req.order_count_target,
            "order_count_actual": req.order_count_actual,
            "customer_satisfaction_score": (
                str(req.customer_satisfaction_score)
                if req.customer_satisfaction_score is not None else None
            ),
            "food_safety_score": (
                str(req.food_safety_score)
                if req.food_safety_score is not None else None
            ),
            "overall_score": str(overall_score),
            "tier_recommendation": tier_recommendation,
        },
    )
    await db.commit()
    return _ok(_row_to_dict(row.one()))


@router.get("/kpi-records")
async def list_kpi_records(
    request: Request,
    franchisee_id: Optional[str] = Query(None),
    year: Optional[int] = Query(None, description="查询年份，如 2026"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询历年 KPI 记录。"""
    tenant_id = _tenant_id(request)
    await _set_tenant(db, tenant_id)

    conditions = ["tenant_id = :tid"]
    params: dict[str, Any] = {"tid": tenant_id, "limit": size, "offset": (page - 1) * size}

    if franchisee_id:
        conditions.append("franchisee_id = :fid")
        params["fid"] = franchisee_id
    if year:
        conditions.append("kpi_period LIKE :year_prefix")
        params["year_prefix"] = f"{year}-%"

    where = " AND ".join(conditions)
    total_row = await db.execute(
        text(f"SELECT count(*) FROM franchise_kpi_records WHERE {where}"), params
    )
    total: int = total_row.scalar_one()

    rows = await db.execute(
        text(f"""
            SELECT * FROM franchise_kpi_records
             WHERE {where}
             ORDER BY kpi_month DESC
             LIMIT :limit OFFSET :offset
        """),
        params,
    )
    return _ok({"items": _rows_to_list(rows), "total": total, "page": page, "size": size})


@router.get("/kpi-dashboard")
async def kpi_dashboard(
    request: Request,
    franchisee_id: str = Query(..., description="加盟商 UUID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """加盟商绩效看板：近 12 个月营收完成率 / 订单完成率 / 综合评分趋势 / 层级建议。"""
    tenant_id = _tenant_id(request)
    await _set_tenant(db, tenant_id)

    # 查加盟商基本信息
    frow = await db.execute(
        text("""
            SELECT id, legal_name, brand_name, tier, status
              FROM franchisees
             WHERE id = :fid AND tenant_id = :tid AND is_deleted = false
        """),
        {"fid": franchisee_id, "tid": tenant_id},
    )
    franchisee = frow.first()
    if not franchisee:
        raise HTTPException(status_code=404, detail="加盟商不存在")

    # 近 12 个月 KPI
    kpi_rows = await db.execute(
        text("""
            SELECT kpi_period, kpi_month,
                   revenue_target_fen, revenue_actual_fen,
                   order_count_target, order_count_actual,
                   customer_satisfaction_score, food_safety_score,
                   overall_score, tier_recommendation
              FROM franchise_kpi_records
             WHERE franchisee_id = :fid AND tenant_id = :tid
               AND kpi_month >= (now() - interval '12 months')::date
             ORDER BY kpi_month DESC
        """),
        {"fid": franchisee_id, "tid": tenant_id},
    )
    kpi_list = _rows_to_list(kpi_rows)

    # 聚合摘要
    if kpi_list:
        latest = kpi_list[0]
        rev_target = sum(r["revenue_target_fen"] for r in kpi_list)
        rev_actual = sum(r["revenue_actual_fen"] for r in kpi_list)
        rev_completion_rate = round(rev_actual / max(rev_target, 1) * 100, 2)

        ord_target = sum(r["order_count_target"] for r in kpi_list)
        ord_actual = sum(r["order_count_actual"] for r in kpi_list)
        ord_completion_rate = round(ord_actual / max(ord_target, 1) * 100, 2)

        avg_score = round(
            sum(float(r["overall_score"]) for r in kpi_list if r["overall_score"]) / len(kpi_list),
            2,
        )
        latest_tier_rec = latest.get("tier_recommendation", "standard")
    else:
        rev_completion_rate = 0.0
        ord_completion_rate = 0.0
        avg_score = 0.0
        latest_tier_rec = franchisee.tier

    # 未付账单汇总
    bill_row = await db.execute(
        text("""
            SELECT coalesce(sum(total_due_fen), 0) AS overdue_total_fen,
                   count(*) AS overdue_count
              FROM franchise_royalty_bills
             WHERE franchisee_id = :fid AND tenant_id = :tid
               AND status IN ('pending', 'overdue')
        """),
        {"fid": franchisee_id, "tid": tenant_id},
    )
    bill_summary = dict(bill_row.one()._mapping)

    return _ok({
        "franchisee": {
            "id": str(franchisee.id),
            "legal_name": franchisee.legal_name,
            "brand_name": franchisee.brand_name,
            "current_tier": franchisee.tier,
            "status": franchisee.status,
        },
        "summary": {
            "revenue_completion_rate_pct": rev_completion_rate,
            "order_completion_rate_pct": ord_completion_rate,
            "avg_overall_score": avg_score,
            "tier_recommendation": latest_tier_rec,
            "overdue_total_fen": int(bill_summary.get("overdue_total_fen", 0)),
            "overdue_bill_count": int(bill_summary.get("overdue_count", 0)),
        },
        "kpi_trend": kpi_list,
    })
