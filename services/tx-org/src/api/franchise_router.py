"""加盟管理 API — V2 路由（仅保留独有端点，主 CRUD 已交给 v5）

裁决（2026-05-04，路由冲突清理）：
  本文件 V2 实现风格更现代（Query/UUID 校验、structlog），但 /franchisees
  的数据契约（franchisee_name/contact_name…）与前端真实使用的 v5 契约
  （name/region/store_name…）不兼容。为消除三家撞车，本次裁决：

    保留 v5（franchise_v5_routes.py）作为 /franchisees CRUD 的唯一实现，
    本文件**删除**以下端点：
      GET    /api/v1/franchise/franchisees             → 由 v5 提供
      POST   /api/v1/franchise/franchisees             → 由 v5 提供
      PUT    /api/v1/franchise/franchisees/{id}        → 由 v5 提供

端点清单（保留）：
  GET    /api/v1/franchise/franchisees/{id}              加盟商详情
  GET    /api/v1/franchise/franchisees/{id}/stores       旗下门店列表
  GET    /api/v1/franchise/franchisees/{id}/dashboard    经营看板

  GET    /api/v1/franchise/royalty/bills                 账单列表
  POST   /api/v1/franchise/royalty/generate-batch        批量生成月度账单
  POST   /api/v1/franchise/royalty/bills/{id}/pay        标记已付款
  GET    /api/v1/franchise/royalty/report                月度汇总报表
  POST   /api/v1/franchise/royalty/check-overdue         检查并标记逾期账单

  GET    /api/v1/franchise/audits                        巡店审计列表
  POST   /api/v1/franchise/audits                        新建审计记录
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from shared.security.src.error_handler import safe_http_exception

from ..services.franchise_service import FranchiseService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/franchise", tags=["franchise"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _parse_tenant_uuid(x_tenant_id: Optional[str]) -> UUID:
    """解析 X-Tenant-ID header 为 UUID，缺失或格式错误时抛出 400。"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="缺少必要 Header：X-Tenant-ID")
    try:
        return UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"X-Tenant-ID 格式无效：{x_tenant_id}")


def _parse_uuid(value: str, field_name: str) -> UUID:
    """解析路径参数为 UUID，格式错误时抛出 400。"""
    try:
        return UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field_name} 格式无效：{value}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型（Pydantic V2）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class GenerateBatchReq(BaseModel):
    year: int = Field(..., ge=2020, le=2099, description="账单年份")
    month: int = Field(..., ge=1, le=12, description="账单月份")


class CreateAuditReq(BaseModel):
    franchisee_id: str = Field(..., description="加盟商 UUID")
    store_id: str = Field(..., description="门店 UUID")
    audit_date: Optional[str] = Field(None, description="审计日期 YYYY-MM-DD，默认今天")
    score: Optional[float] = Field(None, ge=0, le=100, description="审计分数")
    findings: Optional[Dict[str, Any]] = Field(default_factory=dict, description="审计发现项 JSONB")
    auditor_id: Optional[str] = Field(None, description="审计人 UUID")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  加盟商管理端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# ── 已删除（2026-05-04 路由冲突裁决）────────────────────────────────────────
#   GET  /franchisees  → 由 franchise_v5_routes.py 提供（v240 表 / 分 int / 前端契约）
#   POST /franchisees  → 由 franchise_v5_routes.py 提供
#   PUT  /franchisees/{id} → 由 franchise_v5_routes.py 提供
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/franchisees/{franchisee_id}")
async def get_franchisee(
    franchisee_id: str,
    x_tenant_id: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """加盟商详情。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    fid = _parse_uuid(franchisee_id, "franchisee_id")
    franchisee = await FranchiseService.get_franchisee(fid, tenant_id, db=None)
    if franchisee is None:
        raise HTTPException(status_code=404, detail=f"加盟商 {franchisee_id} 不存在")
    return {"ok": True, "data": franchisee.to_dict()}


@router.get("/franchisees/{franchisee_id}/stores")
async def list_franchisee_stores(
    franchisee_id: str,
    x_tenant_id: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """加盟商旗下门店列表（含运营数据）。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    fid = _parse_uuid(franchisee_id, "franchisee_id")
    stores = await FranchiseService.list_franchisee_stores(
        tenant_id=tenant_id,
        franchisee_id=fid,
        db=None,
    )
    return {"ok": True, "data": {"franchisee_id": franchisee_id, "stores": stores}}


@router.get("/franchisees/{franchisee_id}/dashboard")
async def get_franchisee_dashboard(
    franchisee_id: str,
    x_tenant_id: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """加盟商经营看板：营收/环比/同比/待缴费用/门店/审计分数。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    fid = _parse_uuid(franchisee_id, "franchisee_id")
    try:
        dashboard = await FranchiseService.get_franchisee_dashboard(
            franchisee_id=fid,
            tenant_id=tenant_id,
            db=None,
        )
        return {"ok": True, "data": dashboard}
    except ValueError as e:
        raise safe_http_exception(400, "请求参数无效", e) from e


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  特许权费用账单端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/royalty/bills")
async def list_royalty_bills(
    franchisee_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="pending/paid/overdue"),
    year: Optional[int] = Query(None, ge=2020, le=2099),
    month: Optional[int] = Query(None, ge=1, le=12),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """账单列表（支持按加盟商/状态/月份过滤）。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    fid: Optional[UUID] = None
    if franchisee_id:
        fid = _parse_uuid(franchisee_id, "franchisee_id")

    result = await FranchiseService.list_bills(
        tenant_id=tenant_id,
        db=None,
        franchisee_id=fid,
        status=status,
        year=year,
        month=month,
        page=page,
        size=size,
    )
    return {"ok": True, "data": result}


@router.post("/royalty/generate-batch", status_code=201)
async def generate_royalty_batch(
    req: GenerateBatchReq,
    x_tenant_id: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """批量生成指定月份所有活跃加盟商的特许权费用账单。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    try:
        result = await FranchiseService.create_royalty_bill_batch(
            tenant_id=tenant_id,
            year=req.year,
            month=req.month,
            db=None,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise safe_http_exception(400, "请求参数无效", e) from e


@router.post("/royalty/bills/{bill_id}/pay")
async def mark_royalty_bill_paid(
    bill_id: str,
    x_tenant_id: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """标记账单已付款（pending/overdue → paid）。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    bid = _parse_uuid(bill_id, "bill_id")
    try:
        bill = await FranchiseService.mark_bill_paid(
            bill_id=bid,
            tenant_id=tenant_id,
            db=None,
        )
        return {"ok": True, "data": bill.to_dict()}
    except ValueError as e:
        raise safe_http_exception(400, "请求参数无效", e) from e


@router.get("/royalty/report")
async def get_royalty_report(
    year: int = Query(..., ge=2020, le=2099),
    month: int = Query(..., ge=1, le=12),
    x_tenant_id: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """月度特许权费用汇总报表。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    report = await FranchiseService.get_royalty_report(
        tenant_id=tenant_id,
        year=year,
        month=month,
        db=None,
    )
    return {"ok": True, "data": report.to_dict()}


@router.post("/royalty/check-overdue")
async def check_overdue_bills(
    x_tenant_id: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """检查所有账单，将逾期未付的账单标记为 overdue。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    marked_count = await FranchiseService.check_overdue_bills(
        tenant_id=tenant_id,
        db=None,
    )
    return {"ok": True, "data": {"marked_overdue": marked_count}}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  巡店审计端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/audits")
async def list_audits(
    franchisee_id: Optional[str] = Query(None),
    store_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """巡店审计列表（支持按加盟商/门店过滤）。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    fid: Optional[UUID] = None
    sid: Optional[UUID] = None
    if franchisee_id:
        fid = _parse_uuid(franchisee_id, "franchisee_id")
    if store_id:
        sid = _parse_uuid(store_id, "store_id")

    result = await FranchiseService.list_audits(
        tenant_id=tenant_id,
        db=None,
        franchisee_id=fid,
        store_id=sid,
        page=page,
        size=size,
    )
    return {"ok": True, "data": result}


@router.post("/audits", status_code=201)
async def create_audit(
    req: CreateAuditReq,
    x_tenant_id: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """新建巡店审计记录。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    try:
        record = await FranchiseService.create_audit(
            tenant_id=tenant_id,
            data=req.model_dump(),
            db=None,
        )
        return {"ok": True, "data": record}
    except ValueError as e:
        raise safe_http_exception(400, "请求参数无效", e) from e
