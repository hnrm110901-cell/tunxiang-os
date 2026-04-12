"""品牌管理服务层（Brand Management Service）

职责：
  - 品牌 CRUD（list / get / create / update）
  - 门店品牌分配（批量更新 stores.brand_id）
  - 品牌门店列表查询

设计原则：
  - tenant_id 强制传入每个查询，配合 RLS 实现多租户隔离
  - 所有方法 async/await，不阻塞事件循环
  - 禁止 except Exception，使用具体异常类型
  - 金额用分（整数），此模块暂无金额字段

首批品牌客户：尝在一起（CZ）、最黔线（ZQ）、尚宫厨（SG）
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: str) -> None:
    """设置 RLS 会话变量（app.tenant_id）"""
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ──────────────────────────────────────────────────────────────────────────────
# 查询
# ──────────────────────────────────────────────────────────────────────────────


async def list_brands(
    db: AsyncSession,
    tenant_id: str,
    brand_type: str | None = None,
    status: str | None = None,
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """品牌列表，支持 brand_type / status 过滤，含门店数统计。"""
    await _set_tenant(db, tenant_id)

    conditions = ["b.is_deleted = FALSE", "b.tenant_id = :tenant_id"]
    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "limit": size,
        "offset": (page - 1) * size,
    }

    if brand_type:
        conditions.append("b.brand_type = :brand_type")
        params["brand_type"] = brand_type
    if status:
        conditions.append("b.status = :status")
        params["status"] = status

    where = " AND ".join(conditions)

    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM brands b WHERE {where}"), params
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        text(f"""
            SELECT
                b.id::text          AS brand_id,
                b.name,
                b.brand_code,
                b.brand_type,
                b.logo_url,
                b.primary_color,
                b.description,
                b.status,
                b.hq_store_id::text,
                b.strategy_config,
                b.created_at,
                b.updated_at,
                (
                    SELECT COUNT(*)
                    FROM stores s
                    WHERE s.brand_id = b.id::text
                      AND s.is_deleted = FALSE
                ) AS store_count
            FROM brands b
            WHERE {where}
            ORDER BY b.created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )

    items = []
    for row in result.fetchall():
        d = dict(row._mapping)
        for key in ("created_at", "updated_at"):
            if d.get(key):
                d[key] = str(d[key])
        d["store_count"] = int(d.get("store_count") or 0)
        items.append(d)

    logger.info("list_brands", tenant_id=tenant_id, total=total, page=page)
    return {"items": items, "total": total, "page": page, "size": size}


async def get_brand(
    db: AsyncSession,
    tenant_id: str,
    brand_id: str,
) -> dict[str, Any]:
    """品牌详情，含门店数与区域数统计。"""
    await _set_tenant(db, tenant_id)

    result = await db.execute(
        text("""
            SELECT
                b.id::text          AS brand_id,
                b.name,
                b.brand_code,
                b.brand_type,
                b.logo_url,
                b.primary_color,
                b.description,
                b.status,
                b.hq_store_id::text,
                b.strategy_config,
                b.created_at,
                b.updated_at,
                (
                    SELECT COUNT(*)
                    FROM stores s
                    WHERE s.brand_id = b.id::text AND s.is_deleted = FALSE
                ) AS store_count,
                (
                    SELECT COUNT(*)
                    FROM regions r
                    WHERE r.brand_id = b.id AND r.is_active = TRUE
                ) AS region_count
            FROM brands b
            WHERE b.id = :brand_id
              AND b.tenant_id = :tenant_id
              AND b.is_deleted = FALSE
        """),
        {"brand_id": brand_id, "tenant_id": tenant_id},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="品牌不存在")

    data = dict(row._mapping)
    for key in ("created_at", "updated_at"):
        if data.get(key):
            data[key] = str(data[key])
    data["store_count"] = int(data.get("store_count") or 0)
    data["region_count"] = int(data.get("region_count") or 0)

    logger.info("get_brand", tenant_id=tenant_id, brand_id=brand_id)
    return data


async def create_brand(
    db: AsyncSession,
    tenant_id: str,
    name: str,
    brand_code: str,
    brand_type: str | None = None,
    logo_url: str | None = None,
    primary_color: str = "#FF6B35",
    description: str | None = None,
    hq_store_id: str | None = None,
) -> dict[str, Any]:
    """创建品牌，自动检查 brand_code 唯一性。"""
    await _set_tenant(db, tenant_id)

    brand_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    # brand_code 唯一性检查
    dup = await db.execute(
        text("SELECT id FROM brands WHERE brand_code = :code AND is_deleted = FALSE"),
        {"code": brand_code},
    )
    if dup.fetchone():
        raise HTTPException(
            status_code=400,
            detail=f"品牌编码 {brand_code} 已存在，请指定唯一编码",
        )

    try:
        result = await db.execute(
            text("""
                INSERT INTO brands (
                    id, tenant_id, name, brand_code, brand_type,
                    logo_url, primary_color, description, hq_store_id,
                    strategy_config, status, is_deleted, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :name, :brand_code, :brand_type,
                    :logo_url, :primary_color, :description, :hq_store_id,
                    :strategy_config, 'active', FALSE, :now, :now
                )
                RETURNING id::text AS brand_id, name, brand_code
            """),
            {
                "id": brand_id,
                "tenant_id": tenant_id,
                "name": name,
                "brand_code": brand_code,
                "brand_type": brand_type,
                "logo_url": logo_url,
                "primary_color": primary_color,
                "description": description,
                "hq_store_id": hq_store_id,
                "strategy_config": json.dumps({}),
                "now": now,
            },
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        logger.warning("create_brand_integrity_error", tenant_id=tenant_id, error=str(exc))
        raise HTTPException(status_code=400, detail="品牌编码已存在或数据约束冲突") from exc

    row = result.fetchone()
    logger.info("create_brand", tenant_id=tenant_id, brand_id=brand_id, brand_code=brand_code)
    return {
        "brand_id": row._mapping["brand_id"] if row else brand_id,
        "name": name,
        "brand_code": brand_code,
    }


async def update_brand(
    db: AsyncSession,
    tenant_id: str,
    brand_id: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """更新品牌字段（含 strategy_config JSONB）。updates 只包含需要变更的字段。"""
    await _set_tenant(db, tenant_id)

    check = await db.execute(
        text("""
            SELECT id FROM brands
            WHERE id = :brand_id AND tenant_id = :tenant_id AND is_deleted = FALSE
        """),
        {"brand_id": brand_id, "tenant_id": tenant_id},
    )
    if not check.fetchone():
        raise HTTPException(status_code=404, detail="品牌不存在")

    allowed_fields = {
        "name", "brand_type", "logo_url", "primary_color",
        "description", "status", "hq_store_id",
    }
    update_parts: list[str] = []
    params: dict[str, Any] = {
        "brand_id": brand_id,
        "now": datetime.now(timezone.utc),
    }

    for field, value in updates.items():
        if field in allowed_fields and value is not None:
            update_parts.append(f"{field} = :{field}")
            params[field] = value

    if "strategy_config" in updates and updates["strategy_config"] is not None:
        update_parts.append("strategy_config = :strategy_config")
        params["strategy_config"] = json.dumps(updates["strategy_config"])

    if not update_parts:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")

    update_parts.append("updated_at = :now")
    set_clause = ", ".join(update_parts)

    try:
        await db.execute(
            text(f"UPDATE brands SET {set_clause} WHERE id = :brand_id AND is_deleted = FALSE"),
            params,
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("update_brand_db_error", tenant_id=tenant_id, brand_id=brand_id, error=str(exc))
        raise HTTPException(status_code=500, detail="品牌更新失败") from exc

    logger.info("update_brand", tenant_id=tenant_id, brand_id=brand_id, fields=list(update_parts))
    return {"brand_id": brand_id, "updated": True}


# ──────────────────────────────────────────────────────────────────────────────
# 门店分配
# ──────────────────────────────────────────────────────────────────────────────


async def assign_stores_to_brand(
    db: AsyncSession,
    tenant_id: str,
    brand_id: str,
    store_ids: list[str],
) -> dict[str, Any]:
    """批量将门店归属到指定品牌（更新 stores.brand_id）。

    - 先验证品牌存在且属于当前租户
    - 验证所有 store_id 均属于当前租户
    - 批量 UPDATE stores SET brand_id = :brand_id
    - 返回实际更新的门店数量
    """
    await _set_tenant(db, tenant_id)

    # 验证品牌归属
    brand_check = await db.execute(
        text("""
            SELECT id FROM brands
            WHERE id = :brand_id AND tenant_id = :tenant_id AND is_deleted = FALSE
        """),
        {"brand_id": brand_id, "tenant_id": tenant_id},
    )
    if not brand_check.fetchone():
        raise HTTPException(status_code=404, detail="品牌不存在")

    if not store_ids:
        return {"brand_id": brand_id, "assigned_count": 0, "store_ids": []}

    # 验证门店都属于该租户（防止跨租户分配）
    store_check = await db.execute(
        text("""
            SELECT COUNT(*) FROM stores
            WHERE id::text = ANY(:store_ids)
              AND tenant_id = :tenant_id
              AND is_deleted = FALSE
        """),
        {"store_ids": store_ids, "tenant_id": tenant_id},
    )
    valid_count = store_check.scalar() or 0
    if valid_count != len(store_ids):
        raise HTTPException(
            status_code=400,
            detail=f"部分门店不存在或不属于当前租户（传入 {len(store_ids)} 个，有效 {valid_count} 个）",
        )

    try:
        result = await db.execute(
            text("""
                UPDATE stores
                SET brand_id = :brand_id,
                    updated_at = NOW()
                WHERE id::text = ANY(:store_ids)
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
            """),
            {"brand_id": brand_id, "store_ids": store_ids, "tenant_id": tenant_id},
        )
        await db.commit()
        assigned_count = result.rowcount or 0
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error(
            "assign_stores_to_brand_db_error",
            tenant_id=tenant_id,
            brand_id=brand_id,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail="门店分配失败") from exc

    logger.info(
        "assign_stores_to_brand",
        tenant_id=tenant_id,
        brand_id=brand_id,
        assigned_count=assigned_count,
    )
    return {
        "brand_id": brand_id,
        "assigned_count": assigned_count,
        "store_ids": store_ids,
    }


async def get_brand_stores(
    db: AsyncSession,
    tenant_id: str,
    brand_id: str,
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """获取品牌下的门店列表（分页）。"""
    await _set_tenant(db, tenant_id)

    # 验证品牌归属
    brand_check = await db.execute(
        text("""
            SELECT id FROM brands
            WHERE id = :brand_id AND tenant_id = :tenant_id AND is_deleted = FALSE
        """),
        {"brand_id": brand_id, "tenant_id": tenant_id},
    )
    if not brand_check.fetchone():
        raise HTTPException(status_code=404, detail="品牌不存在")

    count_result = await db.execute(
        text("""
            SELECT COUNT(*) FROM stores
            WHERE brand_id = :brand_id AND is_deleted = FALSE
        """),
        {"brand_id": brand_id},
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        text("""
            SELECT
                id::text        AS store_id,
                name            AS store_name,
                address,
                status,
                created_at
            FROM stores
            WHERE brand_id = :brand_id AND is_deleted = FALSE
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        {"brand_id": brand_id, "limit": size, "offset": (page - 1) * size},
    )

    items = []
    for row in result.fetchall():
        d = dict(row._mapping)
        if d.get("created_at"):
            d["created_at"] = str(d["created_at"])
        items.append(d)

    logger.info("get_brand_stores", tenant_id=tenant_id, brand_id=brand_id, total=total)
    return {"items": items, "total": total, "page": page, "size": size}
