"""加盟管理 API（PB.1 兼容层 — 残留独有端点，主路由已迁移）

# ROUTER REGISTRATION:
# from .api.franchise_routes import router as franchise_router
# app.include_router(franchise_router, prefix="/api/v1/franchise")

裁决（2026-05-04，路由冲突清理）：
  本文件原是 PB.1 元-float 体系的薄基础版。当时为兼容 _fen 加了补丁，但
  数据契约（franchisee_name/contact_name…）与前端实际使用的 v5 契约
  （name/region/store_name…）冲突，且与 franchise_router.py、
  franchise_v5_routes.py 三家撞车。

  本次保留 v5（franchise_v5_routes.py）作为 /franchisees 的唯一实现，
  因此从本文件**删除**以下端点：
    GET    /franchise/franchisees                    → 由 v5 提供
    POST   /franchise/franchisees                    → 由 v5 提供
    GET    /franchise/franchisees/{id}/dashboard     → 由 router(V2) 提供

  保留的独有端点（无冲突）：
    POST   /franchise/franchisees/{id}/assign-store  - 分配门店
    POST   /franchise/bills/generate                 - 生成月度账单
    GET    /franchise/bills                          - 账单列表（?franchisee_id=）
    POST   /franchise/bills/{id}/confirm             - 确认账单
    POST   /franchise/bills/{id}/pay                 - 标记已付款
    GET    /franchise/overdue-alerts                 - 欠款预警
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from shared.security.src.error_handler import safe_http_exception

from ..services.franchise_service import FranchiseService
from ..services.royalty_calculator import RoyaltyCalculator

router = APIRouter(prefix="/api/v1/franchise", tags=["franchise"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  辅助
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _get_tenant(x_tenant_id: Optional[str]) -> str:
    """从 Header 提取 tenant_id，缺失时使用默认值。"""
    return x_tenant_id or "default_tenant"


def _parse_tenant_uuid(x_tenant_id: Optional[str]) -> UUID:
    """解析 tenant_id 为 UUID，格式错误时抛出 400。"""
    raw = _get_tenant(x_tenant_id)
    try:
        return UUID(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"X-Tenant-ID 格式无效：{raw}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class RoyaltyTierReq(BaseModel):
    """阶梯分润请求模型。

    金额单位约定（CLAUDE.md §10 Tier 1 财务红线）：
    - 新字段：min_revenue_fen（分，int）— 推荐
    - 旧字段：min_revenue（元，float）— 兼容保留，前端如已迁移可仅传 _fen
    - 二选一：传 _fen 优先；都未传时取 0；都传时以 _fen 为准
    """

    min_revenue: Optional[float] = Field(
        default=None, ge=0, description="[DEPRECATED] 元（float），改用 min_revenue_fen"
    )
    min_revenue_fen: Optional[int] = Field(default=None, ge=0, description="分（int，推荐）")
    rate: float = Field(..., gt=0, lt=1)

    def effective_min_revenue_yuan(self) -> float:
        """返回元（float）形态，供 model.RoyaltyTier 使用。

        优先级：min_revenue_fen > min_revenue > 0
        通过 fen → yuan 精确除法（×100 单位换算无误差）。
        """
        if self.min_revenue_fen is not None:
            return self.min_revenue_fen / 100.0
        if self.min_revenue is not None:
            return self.min_revenue
        return 0.0


class AssignStoreReq(BaseModel):
    store_id: str


class GenerateBillsReq(BaseModel):
    bill_month: str = Field(..., pattern=r"^\d{4}-\d{2}$", description="格式 YYYY-MM")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  加盟商管理端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# 已删除（2026-05-04 路由冲突裁决）：
#   GET    /franchisees                       → 由 franchise_v5_routes.py 提供
#   POST   /franchisees                       → 由 franchise_v5_routes.py 提供
#   GET    /franchisees/{id}/dashboard        → 由 franchise_router.py (V2) 提供
#
# 保留独有端点：
#   POST   /franchisees/{id}/assign-store     - 分配门店（无冲突）


@router.post("/franchisees/{franchisee_id}/assign-store")
async def assign_store(
    franchisee_id: str,
    req: AssignStoreReq,
    x_tenant_id: Optional[str] = Header(None),
):
    """分配门店给加盟商。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    try:
        link = await FranchiseService.assign_store(
            franchisee_id=UUID(franchisee_id),
            store_id=UUID(req.store_id),
            tenant_id=tenant_id,
            db=None,
        )
        return {"ok": True, "data": link.to_dict()}
    except ValueError as e:
        raise safe_http_exception(400, "请求参数无效", e) from e


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  账单管理端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("/bills/generate")
async def generate_bills(
    req: GenerateBillsReq,
    x_tenant_id: Optional[str] = Header(None),
):
    """生成指定月份的月度分润账单（批处理）。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    try:
        bills = await RoyaltyCalculator.generate_monthly_bills(
            tenant_id=tenant_id,
            bill_month=req.bill_month,
            db=None,
        )
        return {
            "ok": True,
            "data": {
                "bill_month": req.bill_month,
                "generated": len(bills),
                "bills": [b.to_dict() for b in bills],
            },
        }
    except ValueError as e:
        raise safe_http_exception(400, "请求参数无效", e) from e


@router.get("/bills")
async def list_bills(
    franchisee_id: Optional[str] = None,
    page: int = 1,
    size: int = 20,
    x_tenant_id: Optional[str] = Header(None),
):
    """账单列表（支持按加盟商过滤）。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    fid: Optional[UUID] = None
    if franchisee_id:
        try:
            fid = UUID(franchisee_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="franchisee_id 格式无效")

    result = await FranchiseService.list_bills(
        tenant_id=tenant_id,
        db=None,
        franchisee_id=fid,
        page=page,
        size=size,
    )
    return {"ok": True, "data": result}


@router.post("/bills/{bill_id}/confirm")
async def confirm_bill(
    bill_id: str,
    x_tenant_id: Optional[str] = Header(None),
):
    """总部确认账单（pending → confirmed）。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    try:
        bill = await FranchiseService.confirm_bill(
            bill_id=UUID(bill_id),
            tenant_id=tenant_id,
            db=None,
        )
        return {"ok": True, "data": bill.to_dict()}
    except ValueError as e:
        raise safe_http_exception(400, "请求参数无效", e) from e


@router.post("/bills/{bill_id}/pay")
async def mark_bill_paid(
    bill_id: str,
    x_tenant_id: Optional[str] = Header(None),
):
    """标记账单已付款（confirmed/overdue → paid）。"""
    tenant_id = _parse_tenant_uuid(x_tenant_id)
    try:
        bill = await FranchiseService.mark_bill_paid(
            bill_id=UUID(bill_id),
            tenant_id=tenant_id,
            db=None,
        )
        return {"ok": True, "data": bill.to_dict()}
    except ValueError as e:
        raise safe_http_exception(400, "请求参数无效", e) from e


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  欠款预警端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/overdue-alerts")
async def get_overdue_alerts(
    threshold_fen: Optional[int] = None,
    threshold: Optional[float] = None,
    x_tenant_id: Optional[str] = Header(None),
):
    """欠款预警：累计欠款超阈值的加盟商列表。

    阈值字段兼容（CLAUDE.md §10 — 金额一律分）：
    - 推荐：threshold_fen（分，int）
    - 兼容：threshold（元，float）— 未来弃用
    - 都未传：默认 5 万元（5_000_000 分）
    """
    tenant_id = _parse_tenant_uuid(x_tenant_id)

    # 优先 _fen，再回退 yuan，最后默认 5 万元
    if threshold_fen is not None:
        threshold_yuan = threshold_fen / 100.0
    elif threshold is not None:
        threshold_yuan = threshold
    else:
        threshold_yuan = 50_000.0

    alerts = await FranchiseService.check_overdue_alerts(
        tenant_id=tenant_id,
        db=None,
        threshold=threshold_yuan,
    )
    return {
        "ok": True,
        "data": {
            "alerts": alerts,
            "count": len(alerts),
            "threshold_fen": int(threshold_yuan * 100),
            # 旧字段保留，便于前端逐步迁移
            "threshold": threshold_yuan,
        },
    }
