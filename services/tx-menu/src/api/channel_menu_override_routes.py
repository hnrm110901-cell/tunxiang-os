"""
多渠道菜单发布完善 — 门店差异价/上下架覆盖
Y-C4

端点列表：
  GET    /api/v1/menu/channel-overrides               覆盖配置列表
  POST   /api/v1/menu/channel-overrides               创建/更新覆盖（UPSERT）
  DELETE /api/v1/menu/channel-overrides/{override_id} 删除覆盖
  GET    /api/v1/menu/channel-overrides/effective-menu 获取门店渠道实效菜单
  POST   /api/v1/menu/channel-overrides/batch         批量设置
  GET    /api/v1/menu/channel-overrides/conflicts      冲突检测
  GET    /api/v1/menu/channel-overrides/stats          发布统计
"""
from __future__ import annotations

import uuid as _uuid
from datetime import date, datetime, time
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/menu/channel-overrides", tags=["channel-menu"])

# ─── 有效渠道 ────────────────────────────────────────────────────────────────

_VALID_CHANNELS = frozenset({
    "dine_in", "takeaway", "meituan", "eleme", "douyin", "miniapp", "all",
})

_CHANNEL_DISPLAY = {
    "dine_in": "堂食",
    "takeaway": "外卖（自营）",
    "meituan": "外卖-美团",
    "eleme": "外卖-饿了么",
    "douyin": "抖音团购",
    "miniapp": "小程序",
    "all": "全渠道",
}

# ─── Mock 数据（3个门店不同渠道的差异配置） ────────────────────────────────────

MOCK_OVERRIDES = [
    {
        "id": "ov-001",
        "store_id": "store-wuyi",
        "store_name": "五一广场店",
        "dish_id": "dish-steam-fish",
        "dish_name": "招牌蒸鱼",
        "channel": "meituan",
        "channel_display": "外卖-美团",
        "brand_price_fen": 9800,
        "override_price_fen": 10800,
        "price_diff_fen": 1000,
        "price_diff_rate": 0.102,
        "is_available": True,
        "override_reason": "regional_price",
        "effective_date": "2026-01-01",
        "expires_date": None,
    },
    {
        "id": "ov-002",
        "store_id": "store-wuyi",
        "store_name": "五一广场店",
        "dish_id": "dish-white-shrimp",
        "dish_name": "白灼虾",
        "channel": "takeaway",
        "channel_display": "外卖（自营）",
        "brand_price_fen": 7800,
        "override_price_fen": None,
        "price_diff_fen": None,
        "price_diff_rate": None,
        "is_available": False,
        "override_reason": "stock",
        "note": "外卖不提供生猛海鲜",
        "effective_date": "2026-01-01",
        "expires_date": None,
    },
    {
        "id": "ov-003",
        "store_id": "store-guanggu",
        "store_name": "光谷店",
        "dish_id": "dish-steam-fish",
        "dish_name": "招牌蒸鱼",
        "channel": "meituan",
        "channel_display": "外卖-美团",
        "brand_price_fen": 9800,
        "override_price_fen": 9800,
        "price_diff_fen": 0,
        "price_diff_rate": 0.0,
        "is_available": True,
        "override_reason": None,
        "effective_date": "2026-01-01",
        "expires_date": None,
    },
    {
        "id": "ov-004",
        "store_id": "store-xintiandi",
        "store_name": "新天地店",
        "dish_id": "dish-steam-fish",
        "dish_name": "招牌蒸鱼",
        "channel": "meituan",
        "channel_display": "外卖-美团",
        "brand_price_fen": 9800,
        "override_price_fen": 13800,
        "price_diff_fen": 4000,
        "price_diff_rate": 0.408,
        "is_available": True,
        "override_reason": "regional_price",
        "effective_date": "2026-01-01",
        "expires_date": None,
    },
    {
        "id": "ov-005",
        "store_id": "store-xintiandi",
        "store_name": "新天地店",
        "dish_id": "dish-boiled-fish",
        "dish_name": "水煮鱼",
        "channel": "dine_in",
        "channel_display": "堂食",
        "brand_price_fen": 6800,
        "override_price_fen": 6800,
        "price_diff_fen": 0,
        "price_diff_rate": 0.0,
        "is_available": True,
        "override_reason": None,
        "effective_date": "2026-01-01",
        "expires_date": None,
    },
]

# ─── 工具函数 ────────────────────────────────────────────────────────────────


def _tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ─── 请求模型 ─────────────────────────────────────────────────────────────────


class UpsertOverrideReq(BaseModel):
    store_id: str = Field(..., description="门店ID")
    dish_id: str = Field(..., description="菜品ID")
    channel: str = Field(..., description="渠道：dine_in/takeaway/meituan/eleme/douyin/miniapp/all")
    price_fen: Optional[int] = Field(None, ge=0, description="覆盖价格（分），NULL=使用品牌标准价")
    is_available: bool = Field(True, description="是否在该渠道该门店可见")
    available_from: Optional[str] = Field(None, description="时段起始 HH:MM，NULL=全天")
    available_until: Optional[str] = Field(None, description="时段结束 HH:MM")
    override_reason: Optional[str] = Field(None, max_length=100,
                                           description="regional_price/stock/promotion")
    approved_by: Optional[str] = None
    effective_date: Optional[date] = None
    expires_date: Optional[date] = None


class BatchOverrideReq(BaseModel):
    store_ids: list[str] = Field(..., min_length=1, max_length=50, description="门店ID列表")
    dish_ids: list[str] = Field(..., min_length=1, max_length=200, description="菜品ID列表")
    channel: str = Field(..., description="渠道")
    override: dict = Field(..., description="{price_fen?: int, is_available?: bool}")


# ─── 1. 覆盖配置列表 ─────────────────────────────────────────────────────────


@router.get("", summary="渠道覆盖配置列表")
async def list_overrides(
    store_id: Optional[str] = Query(None, description="按门店过滤"),
    channel: Optional[str] = Query(None, description="按渠道过滤"),
    dish_id: Optional[str] = Query(None, description="按菜品过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询渠道覆盖配置列表，支持按门店/渠道/菜品过滤，分页返回。"""
    tenant_id = _tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        _tid = _uuid.UUID(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"tenant_id 格式错误: {tenant_id}") from exc

    conditions = ["cmo.tenant_id = :tid", "cmo.is_deleted = false"]
    params: dict = {"tid": _tid}

    if store_id:
        try:
            params["sid"] = _uuid.UUID(store_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"store_id 格式错误: {store_id}") from exc
        conditions.append("cmo.store_id = :sid")

    if channel:
        if channel not in _VALID_CHANNELS:
            raise HTTPException(status_code=400, detail=f"不支持的渠道: {channel}")
        conditions.append("cmo.channel = :channel")
        params["channel"] = channel

    if dish_id:
        try:
            params["did"] = _uuid.UUID(dish_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"dish_id 格式错误: {dish_id}") from exc
        conditions.append("cmo.dish_id = :did")

    where_clause = " AND ".join(conditions)
    offset = (page - 1) * size

    count_result = await db.execute(
        text(f"""
            SELECT COUNT(*)
            FROM channel_menu_overrides cmo
            WHERE {where_clause}
        """),
        params,
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        text(f"""
            SELECT
                cmo.id,
                cmo.store_id,
                cmo.dish_id,
                cmo.channel,
                cmo.price_fen,
                cmo.is_available,
                cmo.available_from,
                cmo.available_until,
                cmo.override_reason,
                cmo.effective_date,
                cmo.expires_date,
                cmo.created_at,
                cmo.updated_at
            FROM channel_menu_overrides cmo
            WHERE {where_clause}
            ORDER BY cmo.updated_at DESC
            LIMIT :size OFFSET :offset
        """),
        {**params, "size": size, "offset": offset},
    )
    rows = result.fetchall()
    items = [
        {
            "id": str(r[0]),
            "store_id": str(r[1]),
            "dish_id": str(r[2]),
            "channel": r[3],
            "channel_display": _CHANNEL_DISPLAY.get(r[3], r[3]),
            "price_fen": r[4],
            "is_available": r[5],
            "available_from": str(r[6]) if r[6] else None,
            "available_until": str(r[7]) if r[7] else None,
            "override_reason": r[8],
            "effective_date": str(r[9]) if r[9] else None,
            "expires_date": str(r[10]) if r[10] else None,
            "created_at": r[11].isoformat() if r[11] else None,
            "updated_at": r[12].isoformat() if r[12] else None,
        }
        for r in rows
    ]

    log.info("channel_overrides.list", tenant_id=tenant_id, total=total, page=page)
    return {
        "ok": True,
        "data": {"items": items, "total": total, "page": page, "size": size},
        "error": None,
    }


# ─── 2. 创建/更新覆盖（UPSERT by store+dish+channel） ─────────────────────────


@router.post("", summary="创建或更新渠道覆盖配置（UPSERT）", status_code=201)
async def upsert_override(
    req: UpsertOverrideReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建或更新渠道覆盖配置。
    同一门店+菜品+渠道只允许存在一条记录，重复 POST 则更新现有记录（UPSERT）。
    """
    tenant_id = _tenant_id(request)

    if req.channel not in _VALID_CHANNELS:
        raise HTTPException(status_code=400, detail=f"不支持的渠道: {req.channel}，有效值: {sorted(_VALID_CHANNELS)}")

    try:
        _tid = _uuid.UUID(tenant_id)
        _sid = _uuid.UUID(req.store_id)
        _did = _uuid.UUID(req.dish_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {exc}") from exc

    await _set_rls(db, tenant_id)

    approved_by_val = None
    if req.approved_by:
        try:
            approved_by_val = _uuid.UUID(req.approved_by)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"approved_by 格式错误: {exc}") from exc

    result = await db.execute(
        text("""
            INSERT INTO channel_menu_overrides (
                tenant_id, store_id, dish_id, channel,
                price_fen, is_available, available_from, available_until,
                override_reason, approved_by, effective_date, expires_date,
                is_deleted
            ) VALUES (
                :tid, :sid, :did, :channel,
                :price_fen, :is_available, :available_from, :available_until,
                :override_reason, :approved_by, :effective_date, :expires_date,
                false
            )
            ON CONFLICT (tenant_id, store_id, dish_id, channel) DO UPDATE SET
                price_fen       = EXCLUDED.price_fen,
                is_available    = EXCLUDED.is_available,
                available_from  = EXCLUDED.available_from,
                available_until = EXCLUDED.available_until,
                override_reason = EXCLUDED.override_reason,
                approved_by     = EXCLUDED.approved_by,
                effective_date  = EXCLUDED.effective_date,
                expires_date    = EXCLUDED.expires_date,
                is_deleted      = false,
                updated_at      = NOW()
            RETURNING id, created_at, updated_at
        """),
        {
            "tid": _tid,
            "sid": _sid,
            "did": _did,
            "channel": req.channel,
            "price_fen": req.price_fen,
            "is_available": req.is_available,
            "available_from": req.available_from,
            "available_until": req.available_until,
            "override_reason": req.override_reason,
            "approved_by": approved_by_val,
            "effective_date": req.effective_date,
            "expires_date": req.expires_date,
        },
    )
    row = result.fetchone()
    await db.commit()

    log.info(
        "channel_override.upserted",
        tenant_id=tenant_id,
        store_id=req.store_id,
        dish_id=req.dish_id,
        channel=req.channel,
    )
    return {
        "ok": True,
        "data": {
            "id": str(row[0]),
            "store_id": req.store_id,
            "dish_id": req.dish_id,
            "channel": req.channel,
            "channel_display": _CHANNEL_DISPLAY.get(req.channel, req.channel),
            "price_fen": req.price_fen,
            "is_available": req.is_available,
            "override_reason": req.override_reason,
            "created_at": row[1].isoformat() if row[1] else None,
            "updated_at": row[2].isoformat() if row[2] else None,
        },
        "error": None,
    }


# ─── 3. 删除覆盖（恢复品牌标准配置） ──────────────────────────────────────────


@router.delete("/{override_id}", summary="删除渠道覆盖（恢复品牌标准配置）")
async def delete_override(
    override_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """软删除指定覆盖配置，该门店该渠道该菜品将恢复使用品牌标准配置。"""
    tenant_id = _tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        _oid = _uuid.UUID(override_id)
        _tid = _uuid.UUID(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {exc}") from exc

    result = await db.execute(
        text("""
            UPDATE channel_menu_overrides
            SET is_deleted = true, updated_at = NOW()
            WHERE id = :oid AND tenant_id = :tid AND is_deleted = false
            RETURNING id, store_id, dish_id, channel
        """),
        {"oid": _oid, "tid": _tid},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"覆盖配置不存在: {override_id}")

    await db.commit()
    log.info("channel_override.deleted", override_id=override_id, tenant_id=tenant_id)
    return {
        "ok": True,
        "data": {
            "id": str(row[0]),
            "store_id": str(row[1]),
            "dish_id": str(row[2]),
            "channel": row[3],
            "deleted": True,
        },
        "error": None,
    }


# ─── 4. 获取门店渠道实效菜单 ──────────────────────────────────────────────────


@router.get("/effective-menu", summary="获取门店渠道实效菜单（品牌标准+覆盖合并）")
async def get_effective_menu(
    store_id: str = Query(..., description="门店ID"),
    channel: str = Query(..., description="渠道"),
    current_time: Optional[str] = Query(None, description="当前时间 HH:MM，默认now()"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取指定门店渠道的最终实效菜单：品牌标准菜单 + 该门店该渠道的覆盖配置合并后的结果。

    合并规则：
    - price_fen: override有值则用override，否则用品牌标准价
    - is_available: override.is_available=false则不可见，否则遵循标准
    - 时段限制: available_from/available_until过滤当前时间
    - expires_date: 已过期的覆盖不生效
    """
    tenant_id = _tenant_id(request)
    if channel not in _VALID_CHANNELS:
        raise HTTPException(status_code=400, detail=f"不支持的渠道: {channel}")

    try:
        _tid = _uuid.UUID(tenant_id)
        _sid = _uuid.UUID(store_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {exc}") from exc

    await _set_rls(db, tenant_id)

    now_time = current_time or datetime.now().strftime("%H:%M")
    today = date.today()

    # 查询品牌菜单（基准），联合该门店该渠道的有效覆盖
    result = await db.execute(
        text("""
            SELECT
                d.id                                      AS dish_id,
                d.dish_name,
                d.price_fen                               AS brand_price_fen,
                d.is_deleted                              AS dish_deleted,
                cmo.id                                    AS override_id,
                cmo.price_fen                             AS override_price_fen,
                cmo.is_available                          AS override_is_available,
                cmo.available_from,
                cmo.available_until,
                cmo.override_reason,
                cmo.expires_date
            FROM dishes d
            LEFT JOIN channel_menu_overrides cmo
              ON  cmo.tenant_id = d.tenant_id
              AND cmo.dish_id   = d.id
              AND cmo.store_id  = :sid
              AND cmo.channel   IN (:channel, 'all')
              AND cmo.is_deleted = false
              AND (cmo.expires_date IS NULL OR cmo.expires_date >= :today)
            WHERE d.tenant_id  = :tid
              AND d.is_deleted = false
            ORDER BY d.dish_name
        """),
        {"tid": _tid, "sid": _sid, "channel": channel, "today": today},
    )
    rows = result.fetchall()

    menu_items = []
    for r in rows:
        brand_price = r[2]
        override_price = r[5]
        override_available = r[6]
        available_from = r[7]
        available_until = r[8]

        # 计算实效价格
        effective_price = override_price if override_price is not None else brand_price

        # 计算实效可见性
        is_available = True
        if override_available is not None:
            is_available = override_available

        # 时段限制检查
        if is_available and available_from and available_until:
            try:
                h, m = now_time.split(":")
                current_minutes = int(h) * 60 + int(m)
                from_h, from_m = str(available_from).split(":")[:2]
                until_h, until_m = str(available_until).split(":")[:2]
                from_minutes = int(from_h) * 60 + int(from_m)
                until_minutes = int(until_h) * 60 + int(until_m)
                if not (from_minutes <= current_minutes <= until_minutes):
                    is_available = False
            except (ValueError, AttributeError):
                pass

        menu_items.append({
            "dish_id": str(r[0]),
            "dish_name": r[1],
            "brand_price_fen": brand_price,
            "effective_price_fen": effective_price,
            "has_override": r[4] is not None,
            "override_id": str(r[4]) if r[4] else None,
            "price_overridden": override_price is not None,
            "is_available": is_available,
            "override_reason": r[9],
            "time_restricted": bool(available_from and available_until),
        })

    log.info(
        "effective_menu.fetched",
        store_id=store_id,
        channel=channel,
        item_count=len(menu_items),
    )
    return {
        "ok": True,
        "data": {
            "store_id": store_id,
            "channel": channel,
            "channel_display": _CHANNEL_DISPLAY.get(channel, channel),
            "current_time": now_time,
            "items": menu_items,
            "total": len(menu_items),
            "available_count": sum(1 for i in menu_items if i["is_available"]),
            "overridden_count": sum(1 for i in menu_items if i["has_override"]),
        },
        "error": None,
    }


# ─── 5. 批量设置（总部下发同类型调整到多个门店） ──────────────────────────────


@router.post("/batch", summary="批量设置渠道覆盖（总部下发）")
async def batch_set_overrides(
    req: BatchOverrideReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """批量将同一覆盖配置下发到多个门店的多道菜品。
    常用场景：总部调整外卖整体涨价/某类菜统一下线/节假日特定渠道上线。
    """
    tenant_id = _tenant_id(request)

    if req.channel not in _VALID_CHANNELS:
        raise HTTPException(status_code=400, detail=f"不支持的渠道: {req.channel}")
    if not req.override:
        raise HTTPException(status_code=400, detail="override 不可为空")

    allowed_override_keys = {"price_fen", "is_available", "override_reason", "expires_date"}
    unknown_keys = set(req.override.keys()) - allowed_override_keys
    if unknown_keys:
        raise HTTPException(status_code=400, detail=f"override 包含未知字段: {unknown_keys}")

    try:
        _tid = _uuid.UUID(tenant_id)
        store_uuids = [_uuid.UUID(sid) for sid in req.store_ids]
        dish_uuids = [_uuid.UUID(did) for did in req.dish_ids]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"UUID 格式错误: {exc}") from exc

    await _set_rls(db, tenant_id)

    price_fen = req.override.get("price_fen")
    is_available = req.override.get("is_available", True)
    override_reason = req.override.get("override_reason")

    saved_count = 0
    for _sid in store_uuids:
        for _did in dish_uuids:
            await db.execute(
                text("""
                    INSERT INTO channel_menu_overrides (
                        tenant_id, store_id, dish_id, channel,
                        price_fen, is_available, override_reason, is_deleted
                    ) VALUES (
                        :tid, :sid, :did, :channel,
                        :price_fen, :is_available, :override_reason, false
                    )
                    ON CONFLICT (tenant_id, store_id, dish_id, channel) DO UPDATE SET
                        price_fen       = EXCLUDED.price_fen,
                        is_available    = EXCLUDED.is_available,
                        override_reason = EXCLUDED.override_reason,
                        is_deleted      = false,
                        updated_at      = NOW()
                """),
                {
                    "tid": _tid,
                    "sid": _sid,
                    "did": _did,
                    "channel": req.channel,
                    "price_fen": price_fen,
                    "is_available": is_available,
                    "override_reason": override_reason,
                },
            )
            saved_count += 1

    await db.commit()
    log.info(
        "channel_override.batch_set",
        tenant_id=tenant_id,
        channel=req.channel,
        stores=len(req.store_ids),
        dishes=len(req.dish_ids),
        saved=saved_count,
    )
    return {
        "ok": True,
        "data": {
            "channel": req.channel,
            "store_count": len(req.store_ids),
            "dish_count": len(req.dish_ids),
            "saved_count": saved_count,
            "override_applied": req.override,
        },
        "error": None,
    }


# ─── 6. 冲突检测 ──────────────────────────────────────────────────────────────


@router.get("/conflicts", summary="渠道价格冲突检测")
async def detect_conflicts(
    store_id: Optional[str] = Query(None, description="门店ID，不传则检查所有门店"),
    threshold_rate: float = Query(0.30, ge=0.01, le=2.0,
                                  description="价差阈值：外卖比堂食高X%则告警，默认0.30=30%"),
    request: Request = None,
    _db: AsyncSession = Depends(get_db),
) -> dict:
    """检测渠道间价格冲突。
    规则：若某菜品在外卖渠道(meituan/eleme/douyin/takeaway)的价格比堂食(dine_in)高于阈值，则告警。
    使用Mock数据演示冲突检测逻辑。
    """
    tenant_id = _tenant_id(request)

    # 以Mock数据演示冲突检测
    conflict_dishes = []

    # 构建菜品-渠道价格映射
    dish_channel_prices: dict[str, dict] = {}
    for ov in MOCK_OVERRIDES:
        if store_id and ov["store_id"] != store_id:
            continue
        key = f"{ov['store_id']}:{ov['dish_id']}"
        if key not in dish_channel_prices:
            dish_channel_prices[key] = {
                "store_name": ov["store_name"],
                "dish_name": ov["dish_name"],
                "dish_id": ov["dish_id"],
                "brand_price_fen": ov["brand_price_fen"],
                "channels": {},
            }
        effective_price = ov.get("override_price_fen") or ov["brand_price_fen"]
        dish_channel_prices[key]["channels"][ov["channel"]] = effective_price

    # 检测冲突
    _delivery_channels = {"meituan", "eleme", "douyin", "takeaway"}
    for _key, dish_info in dish_channel_prices.items():
        channels = dish_info["channels"]
        dine_in_price = channels.get("dine_in", dish_info["brand_price_fen"])

        for ch, ch_price in channels.items():
            if ch in _delivery_channels and dine_in_price and ch_price:
                diff_rate = (ch_price - dine_in_price) / dine_in_price
                if diff_rate > threshold_rate:
                    conflict_dishes.append({
                        "store_name": dish_info["store_name"],
                        "dish_name": dish_info["dish_name"],
                        "dish_id": dish_info["dish_id"],
                        "conflict_channel": ch,
                        "conflict_channel_display": _CHANNEL_DISPLAY.get(ch, ch),
                        "dine_in_price_fen": dine_in_price,
                        "delivery_price_fen": ch_price,
                        "diff_rate": round(diff_rate, 4),
                        "diff_rate_pct": f"{diff_rate * 100:.1f}%",
                        "severity": "critical" if diff_rate > 0.5 else "warning",
                        "suggestion": (
                            f"外卖价比堂食高{diff_rate * 100:.0f}%，"
                            f"建议调整至¥{dine_in_price * (1 + threshold_rate) / 100:.0f}以内"
                        ),
                    })

    log.info(
        "conflict_detection.done",
        tenant_id=tenant_id,
        conflict_count=len(conflict_dishes),
        threshold_rate=threshold_rate,
    )
    return {
        "ok": True,
        "data": {
            "threshold_rate": threshold_rate,
            "threshold_pct": f"{threshold_rate * 100:.0f}%",
            "conflict_count": len(conflict_dishes),
            "conflict_dishes": conflict_dishes,
            "has_critical": any(d["severity"] == "critical" for d in conflict_dishes),
        },
        "error": None,
    }


# ─── 7. 发布统计 ──────────────────────────────────────────────────────────────


@router.get("/stats", summary="渠道发布统计")
async def get_override_stats(
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """统计各渠道上架菜品数/差价菜品数/近7天变更次数。"""
    tenant_id = _tenant_id(request)
    await _set_rls(db, tenant_id)

    try:
        _tid = _uuid.UUID(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"tenant_id 格式错误: {tenant_id}") from exc

    # 各渠道覆盖数量统计
    channel_stats_result = await db.execute(
        text("""
            SELECT
                channel,
                COUNT(*) FILTER (WHERE is_available = true)  AS available_count,
                COUNT(*) FILTER (WHERE is_available = false) AS unavailable_count,
                COUNT(*) FILTER (WHERE price_fen IS NOT NULL) AS price_overridden_count,
                COUNT(*) FILTER (WHERE updated_at >= NOW() - INTERVAL '7 days') AS changed_7d
            FROM channel_menu_overrides
            WHERE tenant_id = :tid
              AND is_deleted = false
            GROUP BY channel
            ORDER BY channel
        """),
        {"tid": _tid},
    )
    channel_rows = channel_stats_result.fetchall()
    channel_stats = [
        {
            "channel": r[0],
            "channel_display": _CHANNEL_DISPLAY.get(r[0], r[0]),
            "available_count": int(r[1]),
            "unavailable_count": int(r[2]),
            "price_overridden_count": int(r[3]),
            "changed_7d": int(r[4]),
        }
        for r in channel_rows
    ]

    # 总体统计
    total_result = await db.execute(
        text("""
            SELECT
                COUNT(*)                                                  AS total_overrides,
                COUNT(DISTINCT store_id)                                  AS store_count,
                COUNT(*) FILTER (WHERE is_available = false)              AS total_unavailable,
                COUNT(*) FILTER (WHERE price_fen IS NOT NULL)             AS total_price_overridden,
                COUNT(*) FILTER (WHERE updated_at >= NOW() - INTERVAL '7 days') AS changed_7d
            FROM channel_menu_overrides
            WHERE tenant_id = :tid
              AND is_deleted = false
        """),
        {"tid": _tid},
    )
    t = total_result.fetchone()

    log.info("channel_override_stats.fetched", tenant_id=tenant_id)
    return {
        "ok": True,
        "data": {
            "total_overrides": int(t[0]),
            "store_count": int(t[1]),
            "total_unavailable": int(t[2]),
            "total_price_overridden": int(t[3]),
            "changed_7d": int(t[4]),
            "channel_stats": channel_stats,
        },
        "error": None,
    }
