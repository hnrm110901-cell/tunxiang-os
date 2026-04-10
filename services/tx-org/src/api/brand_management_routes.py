"""
多品牌管理路由 — DB统一路径，废弃内存双轨
Y-H1

注意：如有历史文件中存在内存存储如
  _BRAND_STRATEGY_CACHE = {}  或  brand_strategies = {}
这些已废弃，请使用本文件的 DB 路径（strategy_config JSONB 字段）。
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
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/org/brands", tags=["brand-management"])

# ── Mock 数据（DB不可用时降级，显式标注 degraded=True） ────────────────────────

MOCK_BRANDS = [
    {
        "id": "brand-001",
        "name": "徐记海鲜",
        "brand_code": "XJ",
        "brand_type": "seafood",
        "store_count": 12,
        "status": "active",
        "primary_color": "#FF6B35",
        "strategy_config": {},
    },
    {
        "id": "brand-002",
        "name": "尝在一起",
        "brand_code": "CZ",
        "brand_type": "canteen",
        "store_count": 8,
        "status": "active",
        "primary_color": "#FF6B35",
        "strategy_config": {},
    },
    {
        "id": "brand-003",
        "name": "尚宫厨",
        "brand_code": "SG",
        "brand_type": "hotpot",
        "store_count": 5,
        "status": "active",
        "primary_color": "#FF6B35",
        "strategy_config": {},
    },
]

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
    """从品牌名自动生成首字母缩写（拼音首字母，最多4位）"""
    # 简单取汉字首字母缩写（实际生产可引入pypinyin，此处用稳健的截取方案）
    import unicodedata
    code = ""
    for ch in name:
        if '\u4e00' <= ch <= '\u9fff':
            # CJK字符：取顺序，最多取前4字
            code += ch
        elif ch.isalpha():
            code += ch.upper()
        if len(code) >= 4:
            break
    # 若结果为汉字则取前2字的拼音首字母（fallback：直接取前2字拼成）
    # 为避免依赖问题，直接截取前2-4个字符的大写ASCII或汉字拼音首字母缩写
    ascii_code = ""
    for ch in name:
        if ch.isalpha() and ch.isascii():
            ascii_code += ch.upper()
    if ascii_code:
        return ascii_code[:4]
    # 汉字 fallback：取前3字
    cjk = [ch for ch in name if '\u4e00' <= ch <= '\u9fff']
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
    """品牌列表（支持 brand_type/status 过滤）。全部走 DB 路径，禁止内存降级为数据源。"""
    try:
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

        list_sql = text(f"""
            SELECT
                b.id::text AS brand_id,
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
                    WHERE s.brand_id = b.id
                      AND s.is_deleted = FALSE
                ) AS store_count
            FROM brands b
            WHERE {where}
            ORDER BY b.created_at DESC
            LIMIT :limit OFFSET :offset
        """)
        result = await db.execute(list_sql, params)
        items = []
        for row in result.fetchall():
            d = dict(row._mapping)
            for key in ("created_at", "updated_at"):
                if d.get(key):
                    d[key] = str(d[key])
            d["store_count"] = int(d.get("store_count") or 0)
            items.append(d)

        logger.info("list_brands", tenant_id=tenant_id, total=total)
        return _ok({"items": items, "total": total, "page": page, "size": size})

    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("list_brands_db_unavailable", error=str(exc),
                       note="DB不可用，返回降级mock数据（degraded=True）")
        filtered = MOCK_BRANDS
        if brand_type:
            filtered = [b for b in filtered if b.get("brand_type") == brand_type]
        if status:
            filtered = [b for b in filtered if b.get("status") == status]
        return _ok({"items": filtered, "total": len(filtered), "page": 1, "size": len(filtered),
                    "degraded": True})


@router.get("/{brand_id}")
async def get_brand_detail(
    brand_id: str,
    tenant_id: str = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """品牌详情（含门店数/区域数统计）"""
    try:
        await _set_tenant(db, tenant_id)

        sql = text("""
            SELECT
                b.id::text AS brand_id,
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
                    WHERE s.brand_id = b.id AND s.is_deleted = FALSE
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
        """)
        result = await db.execute(sql, {"brand_id": brand_id, "tenant_id": tenant_id})
        row = result.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="品牌不存在")

        data = dict(row._mapping)
        for key in ("created_at", "updated_at"):
            if data.get(key):
                data[key] = str(data[key])
        data["store_count"] = int(data.get("store_count") or 0)
        data["region_count"] = int(data.get("region_count") or 0)

        logger.info("get_brand_detail", tenant_id=tenant_id, brand_id=brand_id)
        return _ok(data)

    except HTTPException:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("get_brand_detail_db_unavailable", error=str(exc))
        mock = next((b for b in MOCK_BRANDS if b["id"] == brand_id), None)
        if not mock:
            raise HTTPException(status_code=404, detail="品牌不存在")
        return _ok({**mock, "region_count": 2, "degraded": True})


@router.post("")
async def create_brand(
    req: CreateBrandReq,
    tenant_id: str = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """创建品牌（自动生成 brand_code：品牌名首字母缩写）"""
    await _set_tenant(db, tenant_id)

    brand_id = str(uuid.uuid4())
    brand_code = req.brand_code or _generate_brand_code(req.name)
    now = datetime.now(timezone.utc)

    # 检查 brand_code 唯一性
    dup_check = await db.execute(
        text("SELECT id FROM brands WHERE brand_code = :code AND is_deleted = FALSE"),
        {"code": brand_code},
    )
    if dup_check.fetchone():
        raise HTTPException(
            status_code=400,
            detail=f"品牌编码 {brand_code} 已存在，请指定唯一编码",
        )

    sql = text("""
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
    """)

    result = await db.execute(sql, {
        "id": brand_id,
        "tenant_id": tenant_id,
        "name": req.name,
        "brand_code": brand_code,
        "brand_type": req.brand_type,
        "logo_url": req.logo_url,
        "primary_color": req.primary_color,
        "description": req.description,
        "hq_store_id": req.hq_store_id,
        "strategy_config": json.dumps({}),
        "now": now,
    })
    await db.commit()
    row = result.fetchone()

    logger.info("create_brand", tenant_id=tenant_id, brand_id=brand_id, brand_code=brand_code)
    return _ok({
        "brand_id": row._mapping["brand_id"] if row else brand_id,
        "name": req.name,
        "brand_code": brand_code,
    })


@router.put("/{brand_id}")
async def update_brand(
    brand_id: str,
    req: UpdateBrandReq,
    tenant_id: str = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """更新品牌（含 strategy_config JSONB 字段更新）"""
    await _set_tenant(db, tenant_id)

    check = await db.execute(
        text("SELECT id FROM brands WHERE id = :brand_id AND tenant_id = :tenant_id AND is_deleted = FALSE"),
        {"brand_id": brand_id, "tenant_id": tenant_id},
    )
    if not check.fetchone():
        raise HTTPException(status_code=404, detail="品牌不存在")

    update_fields: list[str] = []
    params: dict[str, Any] = {
        "brand_id": brand_id,
        "now": datetime.now(timezone.utc),
    }

    field_map = {
        "name": req.name,
        "brand_type": req.brand_type,
        "logo_url": req.logo_url,
        "primary_color": req.primary_color,
        "description": req.description,
        "status": req.status,
        "hq_store_id": req.hq_store_id,
    }
    for field_name, value in field_map.items():
        if value is not None:
            update_fields.append(f"{field_name} = :{field_name}")
            params[field_name] = value

    if req.strategy_config is not None:
        update_fields.append("strategy_config = :strategy_config")
        params["strategy_config"] = json.dumps(req.strategy_config)

    if not update_fields:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")

    update_fields.append("updated_at = :now")
    set_clause = ", ".join(update_fields)

    await db.execute(
        text(f"UPDATE brands SET {set_clause} WHERE id = :brand_id AND is_deleted = FALSE"),
        params,
    )
    await db.commit()

    logger.info("update_brand", tenant_id=tenant_id, brand_id=brand_id)
    return _ok({"brand_id": brand_id, "updated": True})


@router.get("/{brand_id}/stores")
async def get_brand_stores(
    brand_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    tenant_id: str = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """品牌下的门店列表"""
    try:
        await _set_tenant(db, tenant_id)

        # 验证品牌存在
        brand_check = await db.execute(
            text("SELECT id FROM brands WHERE id = :bid AND tenant_id = :tid AND is_deleted = FALSE"),
            {"bid": brand_id, "tid": tenant_id},
        )
        if not brand_check.fetchone():
            raise HTTPException(status_code=404, detail="品牌不存在")

        count_result = await db.execute(
            text("SELECT COUNT(*) FROM stores WHERE brand_id = :bid AND is_deleted = FALSE"),
            {"bid": brand_id},
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
                WHERE brand_id = :bid AND is_deleted = FALSE
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {"bid": brand_id, "limit": size, "offset": (page - 1) * size},
        )
        items = []
        for row in result.fetchall():
            d = dict(row._mapping)
            if d.get("created_at"):
                d["created_at"] = str(d["created_at"])
            items.append(d)

        logger.info("get_brand_stores", tenant_id=tenant_id, brand_id=brand_id, total=total)
        return _ok({"items": items, "total": total, "page": page, "size": size})

    except HTTPException:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("get_brand_stores_db_unavailable", error=str(exc))
        return _ok({"items": [], "total": 0, "page": page, "size": size, "degraded": True})


@router.get("/{brand_id}/strategy")
async def get_brand_strategy(
    brand_id: str,
    tenant_id: str = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """获取品牌策略配置（从 DB strategy_config JSONB 字段读取，不走内存）"""
    try:
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

    except HTTPException:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("get_brand_strategy_db_unavailable", error=str(exc))
        return _ok({"brand_id": brand_id, "strategy_config": {}, "degraded": True})


@router.put("/{brand_id}/strategy")
async def update_brand_strategy(
    brand_id: str,
    req: UpdateStrategyReq,
    tenant_id: str = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """更新品牌策略配置（写入 DB strategy_config JSONB，不再用内存dict）"""
    await _set_tenant(db, tenant_id)

    check = await db.execute(
        text("SELECT id FROM brands WHERE id = :bid AND tenant_id = :tid AND is_deleted = FALSE"),
        {"bid": brand_id, "tid": tenant_id},
    )
    if not check.fetchone():
        raise HTTPException(status_code=404, detail="品牌不存在")

    await db.execute(
        text("""
            UPDATE brands
            SET strategy_config = :config, updated_at = :now
            WHERE id = :bid AND is_deleted = FALSE
        """),
        {
            "bid": brand_id,
            "config": json.dumps(req.strategy_config),
            "now": datetime.now(timezone.utc),
        },
    )
    await db.commit()

    logger.info("update_brand_strategy", tenant_id=tenant_id, brand_id=brand_id,
                config_keys=list(req.strategy_config.keys()))
    return _ok({
        "brand_id": brand_id,
        "strategy_config": req.strategy_config,
        "updated": True,
    })
