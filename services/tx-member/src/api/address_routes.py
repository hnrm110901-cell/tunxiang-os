"""收货地址管理 API

数据表：customer_addresses（v133 迁移）
"""

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/member", tags=["address"])


# ── 请求模型 ──────────────────────────────────────────────────


class AddressReq(BaseModel):
    customer_id: str
    name: str
    phone: str
    province: str = ""
    city: str = ""
    district: str = ""
    detail: str = ""  # 详细地址（前端字段名，映射到 detail_address）
    tag: str = "home"
    is_default: bool = False
    location: Optional[dict] = None  # {"lng": float, "lat": float}


# ── 辅助函数 ──────────────────────────────────────────────────


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _row_to_addr(row: Any) -> dict[str, Any]:
    loc = None
    if row[8] is not None and row[9] is not None:
        loc = {"lng": float(row[8]), "lat": float(row[9])}
    return {
        "id": str(row[0]),
        "customer_id": str(row[1]),
        "name": row[2],
        "phone": row[3],
        "province": row[4] or "",
        "city": row[5] or "",
        "district": row[6] or "",
        "detail": row[7] or "",
        "location_lng": float(row[8]) if row[8] is not None else None,
        "location_lat": float(row[9]) if row[9] is not None else None,
        "location": loc,
        "tag": row[10] or "home",
        "is_default": row[11],
    }


async def _clear_default(db: AsyncSession, tenant_id: str, customer_id: str) -> None:
    """清除同一顾客的所有默认地址标记"""
    await db.execute(
        text("""
            UPDATE customer_addresses
            SET is_default = false, updated_at = NOW()
            WHERE tenant_id = :tid AND customer_id = :cid AND is_deleted = false
        """),
        {"tid": tenant_id, "cid": customer_id},
    )


# ── 端点 ──────────────────────────────────────────────────────


@router.get("/addresses")
async def list_addresses(
    customer_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """获取顾客的收货地址列表（默认地址排在最前）"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")

    try:
        await _set_rls(db, x_tenant_id)

        rows = await db.execute(
            text("""
                SELECT id, customer_id, name, phone,
                       province, city, district, detail_address,
                       location_lng, location_lat, tag, is_default
                FROM customer_addresses
                WHERE tenant_id = :tid AND customer_id = :cid AND is_deleted = false
                ORDER BY is_default DESC, created_at DESC
            """),
            {"tid": x_tenant_id, "cid": customer_id},
        )
        items = [_row_to_addr(r) for r in rows.all()]

        logger.info("address.list", customer_id=customer_id, count=len(items))
        return {"ok": True, "data": {"items": items, "total": len(items)}}

    except SQLAlchemyError as exc:
        logger.error("address.list.db_error", exc_info=True, error=str(exc))
        return {"ok": True, "data": {"items": [], "total": 0}}


@router.post("/addresses")
async def create_address(
    req: AddressReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """新增收货地址"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")

    try:
        await _set_rls(db, x_tenant_id)

        if req.is_default:
            await _clear_default(db, x_tenant_id, req.customer_id)

        lng = req.location.get("lng") if req.location else None
        lat = req.location.get("lat") if req.location else None

        result = await db.execute(
            text("""
                INSERT INTO customer_addresses
                    (tenant_id, customer_id, name, phone,
                     province, city, district, detail_address,
                     location_lng, location_lat, tag, is_default)
                VALUES
                    (:tid, :cid, :name, :phone,
                     :province, :city, :district, :detail,
                     :lng, :lat, :tag, :is_default)
                RETURNING id, customer_id, name, phone,
                          province, city, district, detail_address,
                          location_lng, location_lat, tag, is_default
            """),
            {
                "tid": x_tenant_id,
                "cid": req.customer_id,
                "name": req.name,
                "phone": req.phone,
                "province": req.province,
                "city": req.city,
                "district": req.district,
                "detail": req.detail,
                "lng": lng,
                "lat": lat,
                "tag": req.tag,
                "is_default": req.is_default,
            },
        )
        addr = _row_to_addr(result.first())
        await db.commit()

        logger.info("address.create", address_id=addr["id"], customer_id=req.customer_id)
        return {"ok": True, "data": addr}

    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("address.create.db_error", exc_info=True, error=str(exc))
        raise HTTPException(status_code=500, detail="服务暂时不可用")


@router.get("/addresses/{address_id}")
async def get_address(
    address_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """获取单个地址详情"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")

    try:
        await _set_rls(db, x_tenant_id)

        row = await db.execute(
            text("""
                SELECT id, customer_id, name, phone,
                       province, city, district, detail_address,
                       location_lng, location_lat, tag, is_default
                FROM customer_addresses
                WHERE id = :aid AND tenant_id = :tid AND is_deleted = false
                LIMIT 1
            """),
            {"aid": address_id, "tid": x_tenant_id},
        )
        addr = row.first()
        if not addr:
            return {"ok": False, "error": {"message": "地址不存在"}}

        return {"ok": True, "data": _row_to_addr(addr)}

    except SQLAlchemyError as exc:
        logger.error("address.get.db_error", exc_info=True, error=str(exc))
        raise HTTPException(status_code=500, detail="服务暂时不可用")


@router.put("/addresses/{address_id}")
async def update_address(
    address_id: str,
    req: AddressReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """更新收货地址"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")

    try:
        await _set_rls(db, x_tenant_id)

        if req.is_default:
            await _clear_default(db, x_tenant_id, req.customer_id)

        lng = req.location.get("lng") if req.location else None
        lat = req.location.get("lat") if req.location else None

        result = await db.execute(
            text("""
                UPDATE customer_addresses
                SET name = :name, phone = :phone,
                    province = :province, city = :city, district = :district,
                    detail_address = :detail,
                    location_lng = :lng, location_lat = :lat,
                    tag = :tag, is_default = :is_default,
                    updated_at = NOW()
                WHERE id = :aid AND tenant_id = :tid AND is_deleted = false
                RETURNING id, customer_id, name, phone,
                          province, city, district, detail_address,
                          location_lng, location_lat, tag, is_default
            """),
            {
                "aid": address_id,
                "tid": x_tenant_id,
                "name": req.name,
                "phone": req.phone,
                "province": req.province,
                "city": req.city,
                "district": req.district,
                "detail": req.detail,
                "lng": lng,
                "lat": lat,
                "tag": req.tag,
                "is_default": req.is_default,
            },
        )
        updated = result.first()
        if not updated:
            return {"ok": False, "error": {"message": "地址不存在"}}

        await db.commit()
        logger.info("address.update", address_id=address_id)
        return {"ok": True, "data": _row_to_addr(updated)}

    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("address.update.db_error", exc_info=True, error=str(exc))
        raise HTTPException(status_code=500, detail="服务暂时不可用")


@router.delete("/addresses/{address_id}")
async def delete_address(
    address_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """软删除收货地址"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")

    try:
        await _set_rls(db, x_tenant_id)

        await db.execute(
            text("""
                UPDATE customer_addresses
                SET is_deleted = true, updated_at = NOW()
                WHERE id = :aid AND tenant_id = :tid
            """),
            {"aid": address_id, "tid": x_tenant_id},
        )
        await db.commit()

        logger.info("address.delete", address_id=address_id)
        return {"ok": True, "data": None}

    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("address.delete.db_error", exc_info=True, error=str(exc))
        raise HTTPException(status_code=500, detail="服务暂时不可用")


@router.put("/addresses/{address_id}/default")
async def set_default_address(
    address_id: str,
    customer_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """设为默认地址"""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")

    try:
        await _set_rls(db, x_tenant_id)

        # 清除旧默认
        await _clear_default(db, x_tenant_id, customer_id)

        # 设置新默认
        result = await db.execute(
            text("""
                UPDATE customer_addresses
                SET is_default = true, updated_at = NOW()
                WHERE id = :aid AND tenant_id = :tid AND is_deleted = false
                RETURNING id
            """),
            {"aid": address_id, "tid": x_tenant_id},
        )
        if not result.first():
            raise HTTPException(status_code=404, detail="地址不存在")

        await db.commit()

        logger.info("address.set_default", address_id=address_id)
        return {"ok": True, "data": None}

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("address.set_default.db_error", exc_info=True, error=str(exc))
        raise HTTPException(status_code=500, detail="服务暂时不可用")
