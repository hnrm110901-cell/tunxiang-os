from __future__ import annotations

from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..schemas.alliance_schemas import AllianceListingCreate

router = APIRouter(prefix="/api/v1/forge/alliance", tags=["跨品牌联盟"])
log = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id})


# ---------------------------------------------------------------------------
# POST /listings — 创建联盟上架
# ---------------------------------------------------------------------------
@router.post("/listings")
async def create_listing(
    body: AllianceListingCreate,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """创建联盟上架."""
    await _set_tenant(db, x_tenant_id)
    result = await db.execute(
        text("""INSERT INTO forge.alliance_listings
                (tenant_id, app_id, owner_tenant_id, sharing_mode,
                 shared_tenants, revenue_share_rate)
                VALUES (:tid, :app_id, :tid, :sharing_mode,
                        :shared_tenants::jsonb, :revenue_share_rate)
                RETURNING *"""),
        {
            "tid": x_tenant_id,
            "app_id": body.app_id,
            "sharing_mode": body.sharing_mode,
            "shared_tenants": str(body.shared_tenants),
            "revenue_share_rate": body.revenue_share_rate,
        },
    )
    await db.commit()
    return dict(result.mappings().one())


# ---------------------------------------------------------------------------
# GET /listings — 联盟列表
# ---------------------------------------------------------------------------
@router.get("/listings")
async def list_listings(
    owner_tenant_id: Optional[str] = Query(None),
    sharing_mode: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """联盟列表."""
    await _set_tenant(db, x_tenant_id)
    clauses = ["tenant_id = :tid"]
    params: Dict[str, Any] = {"tid": x_tenant_id, "limit": size, "offset": (page - 1) * size}
    if owner_tenant_id:
        clauses.append("owner_tenant_id = :owner_tenant_id")
        params["owner_tenant_id"] = owner_tenant_id
    if sharing_mode:
        clauses.append("sharing_mode = :sharing_mode")
        params["sharing_mode"] = sharing_mode
    where = " AND ".join(clauses)

    total_row = await db.execute(
        text(f"SELECT COUNT(*) FROM forge.alliance_listings WHERE {where}"), params
    )
    total = total_row.scalar() or 0

    rows = await db.execute(
        text(f"""SELECT * FROM forge.alliance_listings
                WHERE {where}
                ORDER BY created_at DESC LIMIT :limit OFFSET :offset"""),
        params,
    )
    return {"items": [dict(r) for r in rows.mappings().all()], "total": total}


# ---------------------------------------------------------------------------
# GET /listings/{listing_id} — 联盟详情
# ---------------------------------------------------------------------------
@router.get("/listings/{listing_id}")
async def get_listing(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """获取联盟详情."""
    await _set_tenant(db, x_tenant_id)
    result = await db.execute(
        text("""SELECT * FROM forge.alliance_listings
                WHERE tenant_id = :tid AND listing_id = :listing_id"""),
        {"tid": x_tenant_id, "listing_id": listing_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="alliance listing not found")
    return dict(row)


# ---------------------------------------------------------------------------
# POST /listings/{listing_id}/install — 安装联盟应用
# ---------------------------------------------------------------------------
@router.post("/listings/{listing_id}/install")
async def install_alliance_app(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """安装联盟应用."""
    await _set_tenant(db, x_tenant_id)
    # 查询 listing
    listing = await db.execute(
        text("""SELECT * FROM forge.alliance_listings
                WHERE listing_id = :listing_id AND is_active = true"""),
        {"listing_id": listing_id},
    )
    listing_row = listing.mappings().first()
    if not listing_row:
        raise HTTPException(status_code=404, detail="alliance listing not found or inactive")

    # 记录安装
    result = await db.execute(
        text("""INSERT INTO forge.alliance_installs
                (tenant_id, listing_id, installed_tenant_id)
                VALUES (:tid, :listing_id, :tid)
                RETURNING *"""),
        {"tid": x_tenant_id, "listing_id": listing_id},
    )
    # 更新安装计数
    await db.execute(
        text("""UPDATE forge.alliance_listings
                SET install_count = install_count + 1
                WHERE listing_id = :listing_id"""),
        {"listing_id": listing_id},
    )
    await db.commit()
    return dict(result.mappings().one())


# ---------------------------------------------------------------------------
# GET /revenue — 联盟收入
# ---------------------------------------------------------------------------
@router.get("/revenue")
async def alliance_revenue(
    listing_id: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    x_tenant_id: str = Header(...),
) -> Dict[str, Any]:
    """联盟收入."""
    await _set_tenant(db, x_tenant_id)
    clauses = ["tenant_id = :tid", "created_at >= NOW() - :days * INTERVAL '1 day'"]
    params: Dict[str, Any] = {"tid": x_tenant_id, "days": days}
    if listing_id:
        clauses.append("listing_id = :listing_id")
        params["listing_id"] = listing_id
    where = " AND ".join(clauses)

    rows = await db.execute(
        text(f"""SELECT * FROM forge.alliance_revenue
                WHERE {where}
                ORDER BY created_at DESC"""),
        params,
    )
    transactions = [dict(r) for r in rows.mappings().all()]
    total_revenue = sum(t.get("amount_fen", 0) for t in transactions)
    owner_share = sum(t.get("owner_share_fen", 0) for t in transactions)
    platform_share = sum(t.get("platform_share_fen", 0) for t in transactions)

    return {
        "total_revenue_fen": total_revenue,
        "owner_share_fen": owner_share,
        "platform_share_fen": platform_share,
        "transactions": transactions,
    }
