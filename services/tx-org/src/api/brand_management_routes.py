"""
多品牌管理路由 — 真实DB路径，禁止内存存储
Y-H1

品牌层是屯象OS四层治理（集团→品牌→业态→门店）的核心枢纽。
首批客户：尝在一起（CZ）、最黔线（ZQ）、尚宫厨（SG）。

所有查询强制传入 tenant_id，配合 RLS NULLIF 策略实现多租户隔离。
strategy_config 字段统一存储品牌策略（JSONB），禁止使用内存 dict。
"""

from __future__ import annotations

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

from ..services import brand_management_service as svc

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/org/brands", tags=["brand-management"])


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


def _get_tenant_id(x_tenant_id: str = Header(..., alias="X-Tenant-ID")) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return x_tenant_id


def _ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _generate_brand_code(name: str) -> str:
    """从品牌名自动生成首字母缩写（最多4位）"""
    ascii_code = ""
    for ch in name:
        if ch.isalpha() and ch.isascii():
            ascii_code += ch.upper()
    if ascii_code:
        return ascii_code[:4]
    # 汉字 fallback：取前3字
    cjk = [ch for ch in name if "\u4e00" <= ch <= "\u9fff"]
    return "".join(cjk[:3]).upper() if cjk else name[:4].upper()


# ── 请求模型 ──────────────────────────────────────────────────────────────────


class CreateBrandReq(BaseModel):
    name: str = Field(..., description="品牌名称", max_length=100)
    brand_code: Optional[str] = Field(None, description="品牌编码（留空自动生成）", max_length=20)
    brand_type: Optional[str] = Field(None, description="seafood/hotpot/canteen/quick_service/banquet")
    logo_url: Optional[str] = Field(None, description="品牌Logo URL")
    primary_color: str = Field(default="#FF6B35", description="品牌主色调（Hex）")
    description: Optional[str] = Field(None, description="品牌描述")
    hq_store_id: Optional[str] = Field(None, description="总店/旗舰店ID")


class UpdateBrandReq(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    brand_type: Optional[str] = None
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    hq_store_id: Optional[str] = None
    strategy_config: Optional[dict] = Field(None, description="品牌策略配置JSONB（全量覆盖）")


class UpdateStrategyReq(BaseModel):
    strategy_config: dict = Field(..., description="品牌策略配置（JSONB全量写入DB）")


class AssignStoresReq(BaseModel):
    store_ids: list[str] = Field(..., description="要分配到该品牌的门店ID列表")


# ── 端点 ──────────────────────────────────────────────────────────────────────


@router.get("")
async def list_brands(
    brand_type: Optional[str] = Query(None, description="按品牌类型筛选"),
    status: Optional[str] = Query(None, description="按状态筛选：active/inactive/archived"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    tenant_id: str = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """品牌列表（支持 brand_type/status 过滤，含门店数统计）。全程走DB，禁止内存降级。"""
    data = await svc.list_brands(
        db=db,
        tenant_id=tenant_id,
        brand_type=brand_type,
        status=status,
        page=page,
        size=size,
    )
    return _ok(data)


@router.get("/{brand_id}")
async def get_brand_detail(
    brand_id: str,
    tenant_id: str = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """品牌详情（含门店数/区域数统计）"""
    data = await svc.get_brand(db=db, tenant_id=tenant_id, brand_id=brand_id)
    return _ok(data)


@router.post("")
async def create_brand(
    req: CreateBrandReq,
    tenant_id: str = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """创建品牌（自动生成 brand_code：品牌名首字母缩写）"""
    brand_code = req.brand_code or _generate_brand_code(req.name)
    data = await svc.create_brand(
        db=db,
        tenant_id=tenant_id,
        name=req.name,
        brand_code=brand_code,
        brand_type=req.brand_type,
        logo_url=req.logo_url,
        primary_color=req.primary_color,
        description=req.description,
        hq_store_id=req.hq_store_id,
    )
    return _ok(data)


@router.put("/{brand_id}")
async def update_brand(
    brand_id: str,
    req: UpdateBrandReq,
    tenant_id: str = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """更新品牌（含 strategy_config JSONB 字段）"""
    updates = req.model_dump(exclude_none=True)
    data = await svc.update_brand(
        db=db,
        tenant_id=tenant_id,
        brand_id=brand_id,
        updates=updates,
    )
    return _ok(data)


@router.put("/{brand_id}/stores")
async def assign_stores_to_brand(
    brand_id: str,
    req: AssignStoresReq,
    tenant_id: str = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """批量将门店归属到指定品牌（更新 stores.brand_id）。
    传入 store_ids 列表，服务层会验证门店租户归属，防止跨租户操作。
    """
    data = await svc.assign_stores_to_brand(
        db=db,
        tenant_id=tenant_id,
        brand_id=brand_id,
        store_ids=req.store_ids,
    )
    return _ok(data)


@router.get("/{brand_id}/stores")
async def get_brand_stores(
    brand_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    tenant_id: str = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """品牌下的门店列表（分页）"""
    data = await svc.get_brand_stores(
        db=db,
        tenant_id=tenant_id,
        brand_id=brand_id,
        page=page,
        size=size,
    )
    return _ok(data)


@router.get("/{brand_id}/strategy")
async def get_brand_strategy(
    brand_id: str,
    tenant_id: str = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """获取品牌策略配置（从 DB strategy_config JSONB 字段读取）"""
    await _set_tenant(db, tenant_id)

    result = await db.execute(
        text("""
            SELECT strategy_config
            FROM brands
            WHERE id = :bid AND tenant_id = :tid AND is_deleted = FALSE
        """),
        {"bid": brand_id, "tid": tenant_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="品牌不存在")

    strategy = row._mapping["strategy_config"] or {}
    logger.info("get_brand_strategy", tenant_id=tenant_id, brand_id=brand_id)
    return _ok({"brand_id": brand_id, "strategy_config": strategy})


@router.put("/{brand_id}/strategy")
async def update_brand_strategy(
    brand_id: str,
    req: UpdateStrategyReq,
    tenant_id: str = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """更新品牌策略配置（写入 DB strategy_config JSONB，全量覆盖）"""
    updates = {"strategy_config": req.strategy_config}
    await svc.update_brand(
        db=db,
        tenant_id=tenant_id,
        brand_id=brand_id,
        updates=updates,
    )
    logger.info(
        "update_brand_strategy",
        tenant_id=tenant_id,
        brand_id=brand_id,
        config_keys=list(req.strategy_config.keys()),
    )
    return _ok(
        {
            "brand_id": brand_id,
            "strategy_config": req.strategy_config,
            "updated": True,
        }
    )
