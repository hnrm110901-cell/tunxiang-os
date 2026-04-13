"""
多区域管理路由 — 区域主数据CRUD + 层级树
Y-H2
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/org/regions", tags=["region-management"])


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


def _build_region_tree(flat_rows: list[dict]) -> list[dict]:
    """将扁平区域列表构建为嵌套树结构"""
    node_map: dict[str, dict] = {}
    roots: list[dict] = []

    for row in flat_rows:
        row["children"] = []
        node_map[row["region_id"]] = row

    for row in flat_rows:
        parent_id = row.get("parent_id")
        if parent_id and parent_id in node_map:
            node_map[parent_id]["children"].append(row)
        else:
            roots.append(row)

    return roots


# ── 请求模型 ──────────────────────────────────────────────────────────────────


class CreateRegionReq(BaseModel):
    name: str = Field(..., description="区域名称", max_length=50)
    parent_id: Optional[str] = Field(None, description="父区域ID（NULL=顶级大区）")
    region_code: Optional[str] = Field(None, description="区域编码", max_length=20)
    level: int = Field(default=1, description="1=大区 2=省 3=城市")
    brand_id: Optional[str] = Field(None, description="绑定品牌ID（可选）")
    manager_id: Optional[str] = Field(None, description="区域负责人员工ID")
    tax_rate: float = Field(default=0.06, ge=0, le=1, description="区域默认税率")
    freight_template: dict = Field(default_factory=dict, description="运费模板配置")


class UpdateRegionReq(BaseModel):
    name: Optional[str] = Field(None, max_length=50)
    region_code: Optional[str] = Field(None, max_length=20)
    brand_id: Optional[str] = None
    manager_id: Optional[str] = None
    tax_rate: Optional[float] = Field(None, ge=0, le=1)
    freight_template: Optional[dict] = None
    is_active: Optional[bool] = None


class UpdateTaxRateReq(BaseModel):
    tax_rate: float = Field(..., ge=0, le=1, description="新税率，例如0.09表示9%")


# ── 端点 ──────────────────────────────────────────────────────────────────────


@router.get("")
async def list_regions(
    tree: bool = Query(False, description="tree=true 返回嵌套树形结构，false 返回平铺列表"),
    brand_id: Optional[str] = Query(None, description="按品牌筛选"),
    level: Optional[int] = Query(None, description="按层级筛选：1=大区 2=省 3=城市"),
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=200),
    tenant_id: str = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """区域列表（支持树形/平铺两种格式，tree=true 返回嵌套结构）"""
    try:
        await _set_tenant(db, tenant_id)

        conditions = ["r.tenant_id = :tenant_id", "r.is_active = TRUE"]
        params: dict[str, Any] = {"tenant_id": tenant_id}

        if brand_id:
            conditions.append("r.brand_id = :brand_id")
            params["brand_id"] = brand_id
        if level is not None:
            conditions.append("r.level = :level")
            params["level"] = level

        where = " AND ".join(conditions)

        if not tree:
            params["limit"] = size
            params["offset"] = (page - 1) * size

            count_result = await db.execute(
                text(f"SELECT COUNT(*) FROM regions r WHERE {where}"), params
            )
            total = count_result.scalar() or 0

        sql = text(f"""
            SELECT
                r.id::text AS region_id,
                r.parent_id::text AS parent_id,
                r.name,
                r.region_code,
                r.level,
                r.brand_id::text,
                r.manager_id::text,
                r.tax_rate,
                r.freight_template,
                r.is_active,
                r.created_at,
                r.updated_at,
                e.emp_name AS manager_name,
                (
                    SELECT COUNT(*)
                    FROM stores s
                    WHERE s.region_id = r.id AND s.is_deleted = FALSE
                ) AS store_count,
                (
                    SELECT COUNT(*)
                    FROM regions sub
                    WHERE sub.parent_id = r.id AND sub.is_active = TRUE
                ) AS child_count
            FROM regions r
            LEFT JOIN employees e ON e.id = r.manager_id AND e.is_deleted = FALSE
            WHERE {where}
            ORDER BY r.level ASC, r.name ASC
            {"LIMIT :limit OFFSET :offset" if not tree else ""}
        """)
        result = await db.execute(sql, params)
        flat_rows = []
        for row in result.fetchall():
            d = dict(row._mapping)
            for key in ("created_at", "updated_at"):
                if d.get(key):
                    d[key] = str(d[key])
            d["store_count"] = int(d.get("store_count") or 0)
            d["child_count"] = int(d.get("child_count") or 0)
            if d.get("tax_rate") is not None:
                d["tax_rate"] = float(d["tax_rate"])
            flat_rows.append(d)

        if tree:
            tree_data = _build_region_tree(flat_rows)
            logger.info("list_regions_tree", tenant_id=tenant_id, total_nodes=len(flat_rows))
            return _ok({"tree": tree_data, "total_nodes": len(flat_rows)})
        else:
            logger.info("list_regions_flat", tenant_id=tenant_id, total=total)
            return _ok({"items": flat_rows, "total": total, "page": page, "size": size})

    except (SQLAlchemyError, OSError, RuntimeError, ValueError) as exc:
        logger.warning("list_regions_db_unavailable", error=str(exc))
        if tree:
            return _ok({"tree": [], "total_nodes": 0, "degraded": True})
        return _ok({"items": [], "total": 0, "page": page, "size": size, "degraded": True})


@router.get("/{region_id}")
async def get_region_detail(
    region_id: str,
    tenant_id: str = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """区域详情（含子区域数/门店数）"""
    try:
        await _set_tenant(db, tenant_id)

        sql = text("""
            SELECT
                r.id::text AS region_id,
                r.parent_id::text,
                r.name,
                r.region_code,
                r.level,
                r.brand_id::text,
                r.manager_id::text,
                r.tax_rate,
                r.freight_template,
                r.is_active,
                r.created_at,
                r.updated_at,
                e.emp_name AS manager_name,
                pr.name AS parent_name,
                (
                    SELECT COUNT(*) FROM stores s
                    WHERE s.region_id = r.id AND s.is_deleted = FALSE
                ) AS store_count,
                (
                    SELECT COUNT(*) FROM regions sub
                    WHERE sub.parent_id = r.id AND sub.is_active = TRUE
                ) AS child_count
            FROM regions r
            LEFT JOIN employees e ON e.id = r.manager_id AND e.is_deleted = FALSE
            LEFT JOIN regions pr ON pr.id = r.parent_id AND pr.is_active = TRUE
            WHERE r.id = :region_id
              AND r.tenant_id = :tenant_id
              AND r.is_active = TRUE
        """)
        result = await db.execute(sql, {"region_id": region_id, "tenant_id": tenant_id})
        row = result.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="区域不存在")

        data = dict(row._mapping)
        for key in ("created_at", "updated_at"):
            if data.get(key):
                data[key] = str(data[key])
        data["store_count"] = int(data.get("store_count") or 0)
        data["child_count"] = int(data.get("child_count") or 0)
        if data.get("tax_rate") is not None:
            data["tax_rate"] = float(data["tax_rate"])

        logger.info("get_region_detail", tenant_id=tenant_id, region_id=region_id)
        return _ok(data)

    except HTTPException:
        raise
    except (SQLAlchemyError, OSError, RuntimeError, ValueError) as exc:
        logger.warning("get_region_detail_db_unavailable", error=str(exc))
        return _ok({
            "region_id": region_id,
            "name": "未知区域",
            "level": 1,
            "tax_rate": 0.06,
            "store_count": 0,
            "child_count": 0,
            "degraded": True,
        })


@router.post("")
async def create_region(
    req: CreateRegionReq,
    tenant_id: str = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """创建区域（支持 parent_id 指定父区域，实现树形结构）"""
    await _set_tenant(db, tenant_id)

    if req.parent_id:
        parent_check = await db.execute(
            text("SELECT id, level FROM regions WHERE id = :pid AND tenant_id = :tid AND is_active = TRUE"),
            {"pid": req.parent_id, "tid": tenant_id},
        )
        parent_row = parent_check.fetchone()
        if not parent_row:
            raise HTTPException(status_code=404, detail="父区域不存在")

    region_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    sql = text("""
        INSERT INTO regions (
            id, tenant_id, parent_id, name, region_code,
            level, brand_id, manager_id, tax_rate,
            freight_template, is_active, created_at, updated_at
        ) VALUES (
            :id, :tenant_id, :parent_id, :name, :region_code,
            :level, :brand_id, :manager_id, :tax_rate,
            :freight_template, TRUE, :now, :now
        )
        RETURNING id::text AS region_id, name, level
    """)

    result = await db.execute(sql, {
        "id": region_id,
        "tenant_id": tenant_id,
        "parent_id": req.parent_id,
        "name": req.name,
        "region_code": req.region_code,
        "level": req.level,
        "brand_id": req.brand_id,
        "manager_id": req.manager_id,
        "tax_rate": str(req.tax_rate),
        "freight_template": json.dumps(req.freight_template),
        "now": now,
    })
    await db.commit()
    row = result.fetchone()

    logger.info("create_region", tenant_id=tenant_id, region_id=region_id, name=req.name)
    return _ok({
        "region_id": row._mapping["region_id"] if row else region_id,
        "name": req.name,
        "level": req.level,
        "parent_id": req.parent_id,
    })


@router.put("/{region_id}")
async def update_region(
    region_id: str,
    req: UpdateRegionReq,
    tenant_id: str = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """更新区域（含税率/运费模板）"""
    await _set_tenant(db, tenant_id)

    check = await db.execute(
        text("SELECT id FROM regions WHERE id = :rid AND tenant_id = :tid AND is_active = TRUE"),
        {"rid": region_id, "tid": tenant_id},
    )
    if not check.fetchone():
        raise HTTPException(status_code=404, detail="区域不存在")

    update_fields: list[str] = []
    params: dict[str, Any] = {
        "region_id": region_id,
        "now": datetime.now(timezone.utc),
    }

    scalar_fields = {
        "name": req.name,
        "region_code": req.region_code,
        "brand_id": req.brand_id,
        "manager_id": req.manager_id,
        "is_active": req.is_active,
    }
    for field_name, value in scalar_fields.items():
        if value is not None:
            update_fields.append(f"{field_name} = :{field_name}")
            params[field_name] = value

    if req.tax_rate is not None:
        update_fields.append("tax_rate = :tax_rate")
        params["tax_rate"] = str(req.tax_rate)
    if req.freight_template is not None:
        update_fields.append("freight_template = :freight_template")
        params["freight_template"] = json.dumps(req.freight_template)

    if not update_fields:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")

    update_fields.append("updated_at = :now")
    set_clause = ", ".join(update_fields)

    await db.execute(
        text(f"UPDATE regions SET {set_clause} WHERE id = :region_id AND is_active = TRUE"),
        params,
    )
    await db.commit()

    logger.info("update_region", tenant_id=tenant_id, region_id=region_id)
    return _ok({"region_id": region_id, "updated": True})


@router.get("/{region_id}/stores")
async def get_region_stores(
    region_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    tenant_id: str = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """区域下的门店列表"""
    try:
        await _set_tenant(db, tenant_id)

        region_check = await db.execute(
            text("SELECT id FROM regions WHERE id = :rid AND tenant_id = :tid AND is_active = TRUE"),
            {"rid": region_id, "tid": tenant_id},
        )
        if not region_check.fetchone():
            raise HTTPException(status_code=404, detail="区域不存在")

        count_result = await db.execute(
            text("SELECT COUNT(*) FROM stores WHERE region_id = :rid AND is_deleted = FALSE"),
            {"rid": region_id},
        )
        total = count_result.scalar() or 0

        result = await db.execute(
            text("""
                SELECT
                    id::text AS store_id,
                    name AS store_name,
                    address,
                    status,
                    created_at
                FROM stores
                WHERE region_id = :rid AND is_deleted = FALSE
                ORDER BY name ASC
                LIMIT :limit OFFSET :offset
            """),
            {"rid": region_id, "limit": size, "offset": (page - 1) * size},
        )
        items = []
        for row in result.fetchall():
            d = dict(row._mapping)
            if d.get("created_at"):
                d["created_at"] = str(d["created_at"])
            items.append(d)

        logger.info("get_region_stores", tenant_id=tenant_id, region_id=region_id, total=total)
        return _ok({"items": items, "total": total, "page": page, "size": size})

    except HTTPException:
        raise
    except (SQLAlchemyError, OSError, RuntimeError, ValueError) as exc:
        logger.warning("get_region_stores_db_unavailable", error=str(exc))
        return _ok({"items": [], "total": 0, "page": page, "size": size, "degraded": True})


@router.get("/{region_id}/performance")
async def get_region_performance(
    region_id: str,
    date_from: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    tenant_id: str = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """区域经营对比（各门店营业额/增长率，按区域聚合）"""
    try:
        await _set_tenant(db, tenant_id)

        region_check = await db.execute(
            text("SELECT id, name FROM regions WHERE id = :rid AND tenant_id = :tid AND is_active = TRUE"),
            {"rid": region_id, "tid": tenant_id},
        )
        region_row = region_check.fetchone()
        if not region_row:
            raise HTTPException(status_code=404, detail="区域不存在")

        region_name = region_row._mapping["name"]

        date_filter = ""
        params: dict[str, Any] = {"rid": region_id}
        if date_from:
            date_filter += " AND DATE(o.created_at) >= :date_from"
            params["date_from"] = date_from
        if date_to:
            date_filter += " AND DATE(o.created_at) <= :date_to"
            params["date_to"] = date_to

        sql = text(f"""
            SELECT
                s.id::text AS store_id,
                s.name AS store_name,
                COUNT(o.id) AS order_count,
                COALESCE(SUM(o.total_fen), 0) AS total_revenue_fen,
                ROUND(
                    COALESCE(AVG(o.total_fen), 0)
                ) AS avg_order_fen
            FROM stores s
            LEFT JOIN orders o ON o.store_id = s.id
                AND o.status = 'paid'
                {date_filter}
            WHERE s.region_id = :rid AND s.is_deleted = FALSE
            GROUP BY s.id, s.name
            ORDER BY total_revenue_fen DESC
        """)
        result = await db.execute(sql, params)
        store_stats = []
        total_revenue_fen = 0
        for row in result.fetchall():
            d = dict(row._mapping)
            d["order_count"] = int(d.get("order_count") or 0)
            d["total_revenue_fen"] = int(d.get("total_revenue_fen") or 0)
            d["avg_order_fen"] = int(d.get("avg_order_fen") or 0)
            total_revenue_fen += d["total_revenue_fen"]
            store_stats.append(d)

        logger.info("get_region_performance", tenant_id=tenant_id, region_id=region_id,
                    stores=len(store_stats))
        return _ok({
            "region_id": region_id,
            "region_name": region_name,
            "total_revenue_fen": total_revenue_fen,
            "store_count": len(store_stats),
            "stores": store_stats,
        })

    except HTTPException:
        raise
    except (SQLAlchemyError, OSError, RuntimeError, ValueError) as exc:
        logger.warning("get_region_performance_db_unavailable", error=str(exc))
        return _ok({
            "region_id": region_id,
            "region_name": "未知区域",
            "total_revenue_fen": 0,
            "store_count": 0,
            "stores": [],
            "degraded": True,
        })


@router.put("/{region_id}/tax-rate")
async def update_region_tax_rate(
    region_id: str,
    req: UpdateTaxRateReq,
    tenant_id: str = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """更新区域税率（影响该区域所有门店的发票税率）"""
    await _set_tenant(db, tenant_id)

    check = await db.execute(
        text("SELECT id, name FROM regions WHERE id = :rid AND tenant_id = :tid AND is_active = TRUE"),
        {"rid": region_id, "tid": tenant_id},
    )
    row = check.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="区域不存在")

    region_name = row._mapping["name"]

    await db.execute(
        text("""
            UPDATE regions
            SET tax_rate = :tax_rate, updated_at = :now
            WHERE id = :rid AND is_active = TRUE
        """),
        {
            "rid": region_id,
            "tax_rate": str(req.tax_rate),
            "now": datetime.now(timezone.utc),
        },
    )
    await db.commit()

    logger.info("update_region_tax_rate", tenant_id=tenant_id, region_id=region_id,
                tax_rate=req.tax_rate, region_name=region_name)
    return _ok({
        "region_id": region_id,
        "region_name": region_name,
        "tax_rate": req.tax_rate,
        "updated": True,
        "note": f"区域 [{region_name}] 税率已更新为 {req.tax_rate * 100:.2f}%，影响该区域所有门店发票税率",
    })
