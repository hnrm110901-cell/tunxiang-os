"""外卖聚合统一接单 API — 美团/饿了么/抖音 webhook + 接单面板

ROUTER REGISTRATION (在tx-trade/src/main.py中添加):
    from .api.omni_channel_routes import router as omni_channel_router
    app.include_router(omni_channel_router, prefix="/api/v1")
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid as _uuid_module
from datetime import date, datetime, timedelta
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db
from ..services.omni_channel_service import (
    OmniChannelService,
    OmniChannelError,
    UnsupportedPlatformError,
    omni_order_match_clause,
    row_omni_platform_key,
    row_omni_platform_order_id,
)
from ..services.unified_order_hub import list_unified_orders

logger = structlog.get_logger()
router = APIRouter(prefix="/omni", tags=["omni-channel"])

# ─── 签名验证 secret（从环境变量读取，不硬编码） ────────────────────────────────

_PLATFORM_SECRETS: dict[str, str] = {
    "meituan": os.environ.get("MEITUAN_WEBHOOK_SECRET", ""),
    "eleme": os.environ.get("ELEME_WEBHOOK_SECRET", ""),
    "douyin": os.environ.get("DOUYIN_WEBHOOK_SECRET", ""),
}


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


def _verify_meituan_signature(body: bytes, signature: str, secret: str) -> bool:
    """美团签名验证：MD5(body + secret)"""
    if not secret:
        logger.warning("omni_channel.webhook.no_secret", platform="meituan")
        return True  # 无secret时放行（开发模式），生产应返回False
    expected = hashlib.md5(body + secret.encode()).hexdigest().lower()
    return hmac.compare_digest(expected, signature.lower())


def _verify_eleme_signature(body: bytes, signature: str, secret: str) -> bool:
    """饿了么签名验证：HMAC-SHA256"""
    if not secret:
        logger.warning("omni_channel.webhook.no_secret", platform="eleme")
        return True
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


def _verify_douyin_signature(body: bytes, signature: str, secret: str) -> bool:
    """抖音签名验证：HMAC-SHA256"""
    if not secret:
        logger.warning("omni_channel.webhook.no_secret", platform="douyin")
        return True
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


_SIGNATURE_VERIFIERS = {
    "meituan": _verify_meituan_signature,
    "eleme": _verify_eleme_signature,
    "douyin": _verify_douyin_signature,
}


def _verify_platform_signature(platform: str, body: bytes, request: Request) -> bool:
    """统一签名验证入口"""
    secret = _PLATFORM_SECRETS.get(platform, "")
    verifier = _SIGNATURE_VERIFIERS.get(platform)
    if verifier is None:
        return False

    # 各平台签名header名称
    sig_header_map = {
        "meituan": "X-Meituan-Signature",
        "eleme": "X-Eleme-Signature",
        "douyin": "X-Douyin-Signature",
    }
    signature = request.headers.get(sig_header_map.get(platform, "X-Signature"), "")
    if not signature:
        logger.warning("omni_channel.webhook.missing_signature", platform=platform)
        return not secret  # 无secret时允许无签名请求（开发模式）

    return verifier(body, signature, secret)


# ─── 请求/响应模型 ────────────────────────────────────────────────────────────


class AcceptOrderReq(BaseModel):
    estimated_minutes: int = 20


class RejectOrderReq(BaseModel):
    reason_code: int = 1


# ─── 路由 ─────────────────────────────────────────────────────────────────────


@router.post("/webhook/{platform}", summary="平台推单回调（美团/饿了么/抖音）")
async def webhook_receive_order(
    platform: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """接收各平台外卖推单回调。

    - 验证平台签名（secret从环境变量读取）
    - 标准化为内部Order格式写库
    - 自动推送到KDS
    - 平台回调失败只记录日志，不影响内部流程
    """
    if platform not in OmniChannelService.PLATFORMS:
        raise HTTPException(status_code=400, detail=f"不支持的平台: {platform}")

    body = await request.body()
    log = logger.bind(platform=platform)

    # 签名验证
    if not _verify_platform_signature(platform, body, request):
        log.warning("omni_channel.webhook.signature_invalid")
        raise HTTPException(status_code=401, detail="签名验证失败")

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError) as exc:
        log.error("omni_channel.webhook.invalid_json", error=str(exc))
        raise HTTPException(status_code=400, detail="无效的JSON payload") from exc

    tenant_id = _get_tenant_id(request)
    store_id = payload.get("store_id") or request.headers.get("X-Store-ID", "")
    if not store_id:
        raise HTTPException(status_code=400, detail="store_id required in payload or X-Store-ID header")

    try:
        svc = OmniChannelService()
        order = await svc.receive_order(
            platform=platform,
            raw_payload=payload,
            store_id=store_id,
            tenant_id=tenant_id,
            db=db,
        )

        # 映射增强：查询 platform_dish_mappings 并为未映射条目创建占位记录
        await _enrich_order_with_mappings(
            platform=platform,
            store_id=store_id,
            tenant_id=tenant_id,
            order=order,
            db=db,
        )

        await db.commit()
        log.info("omni_channel.webhook.ok", platform_order_id=order.platform_order_id)
        return {"ok": True, "data": {"order_id": order.internal_order_id, "platform": platform}, "error": None}
    except UnsupportedPlatformError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OmniChannelError as exc:
        log.error("omni_channel.webhook.failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/orders/pending", summary="待接单列表（所有平台混合）")
async def get_pending_orders(
    store_id: str = Query(..., description="门店ID"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询当前所有平台待接单订单，按下单时间升序排列。"""
    tenant_id = _get_tenant_id(request)
    svc = OmniChannelService()
    orders = await svc.get_pending_orders(store_id=store_id, tenant_id=tenant_id, db=db)

    return {
        "ok": True,
        "data": [
            {
                "order_id": o.internal_order_id,
                "platform": o.platform,
                "platform_order_id": o.platform_order_id,
                "status": o.status,
                "total_fen": o.total_fen,
                "notes": o.notes,
                "customer_phone": o.customer_phone,
                "delivery_address": o.delivery_address,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "items": [
                    {
                        "name": item.name,
                        "quantity": item.quantity,
                        "price_fen": item.price_fen,
                        "notes": item.notes,
                    }
                    for item in o.items
                ],
            }
            for o in orders
        ],
        "error": None,
    }


@router.post("/orders/{order_id}/accept", summary="接单")
async def accept_order(
    order_id: str,
    req: AcceptOrderReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """接单：更新状态为confirmed，并回调平台接单接口。

    平台回调失败只记录structlog日志，不影响接单结果。
    """
    tenant_id = _get_tenant_id(request)
    svc = OmniChannelService()
    try:
        result = await svc.accept_order(
            order_id=order_id,
            estimated_minutes=req.estimated_minutes,
            tenant_id=tenant_id,
            db=db,
        )
        await db.commit()
        return {"ok": True, "data": result, "error": None}
    except OmniChannelError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/orders/{order_id}/reject", summary="拒单")
async def reject_order(
    order_id: str,
    req: RejectOrderReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """拒单：更新状态为rejected，并回调平台拒单接口。

    平台回调失败只记录structlog日志，不影响拒单结果。
    """
    tenant_id = _get_tenant_id(request)
    svc = OmniChannelService()
    try:
        result = await svc.reject_order(
            order_id=order_id,
            reason_code=req.reason_code,
            tenant_id=tenant_id,
            db=db,
        )
        await db.commit()
        return {"ok": True, "data": result, "error": None}
    except OmniChannelError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/orders", summary="历史订单（含渠道）")
async def get_orders(
    store_id: str = Query(..., description="门店ID"),
    order_date: Optional[date] = Query(None, alias="date", description="查询日期（YYYY-MM-DD），不传则今日"),
    platform: Optional[str] = Query(None, description="平台筛选: meituan/eleme/douyin"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询门店历史外卖订单（含渠道信息），支持按平台筛选，分页返回。"""
    import uuid as _uuid
    from shared.ontology.src.entities import Order as OrderModel
    from sqlalchemy import select, and_, func, or_

    tenant_id = _get_tenant_id(request)
    tid = _uuid.UUID(tenant_id)
    sid = _uuid.UUID(store_id)

    target_date = order_date or datetime.now().date()
    local_tz = datetime.now().astimezone().tzinfo
    day_start = datetime(
        target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=local_tz
    )
    day_end = datetime(
        target_date.year, target_date.month, target_date.day, 23, 59, 59, tzinfo=local_tz
    )

    conditions = [
        OrderModel.tenant_id == tid,
        OrderModel.store_id == sid,
        omni_order_match_clause(OrderModel, OmniChannelService.PLATFORMS),
        OrderModel.created_at >= day_start,
        OrderModel.created_at <= day_end,
        OrderModel.is_deleted == False,  # noqa: E712
    ]
    if platform and platform in OmniChannelService.PLATFORMS:
        conditions.append(
            or_(
                OrderModel.sales_channel_id == platform,
                OrderModel.order_metadata["omni"]["platform"].astext == platform,
            )
        )

    total_stmt = select(func.count()).select_from(OrderModel).where(and_(*conditions))
    total_result = await db.execute(total_stmt)
    total = total_result.scalar() or 0

    stmt = (
        select(OrderModel)
        .where(and_(*conditions))
        .order_by(OrderModel.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    items = [
        {
            "order_id": str(row.id),
            "platform": row_omni_platform_key(row, OmniChannelService.PLATFORMS)
            or (row.sales_channel_id or ""),
            "platform_order_id": row_omni_platform_order_id(row) or row.order_no,
            "status": row.status,
            "total_fen": getattr(row, "total_amount_fen", 0),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]

    return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}, "error": None}


@router.get("/unified-orders", summary="全渠道订单统一列表（总部/HQ）")
async def get_unified_orders_hq(
    request: Request,
    db: AsyncSession = Depends(get_db),
    store_id: Optional[str] = Query(
        None,
        description="门店 ID；不传则租户下全部门店",
    ),
    date_from: Optional[date] = Query(None, description="开始日期，默认 date_to-7 天"),
    date_to: Optional[date] = Query(None, description="结束日期，默认今天"),
    source: str = Query(
        "hq_all",
        description="hq_all=orders+未关联外卖；internal_only=仅 orders；delivery_unlinked=仅未关联 delivery_orders",
    ),
    status: Optional[str] = Query(
        None,
        description="订单状态筛选，逗号分隔（如 pending,confirmed），与各源表 status 列匹配",
    ),
    channel_key: Optional[str] = Query(
        None,
        description="精确匹配统一列 channel_key（如 meituan、dine_in、delivery）",
    ),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> dict:
    """Y-A12 骨架：``orders`` 与尚未写入 ``internal_order_id`` 的 ``delivery_orders`` 合并时间线。

    已与 omni 落库到 ``orders`` 的外卖单只出现在 internal 侧，避免与 ``delivery_orders`` 双计。
    """
    tenant_id = _get_tenant_id(request)
    if date_to is None:
        date_to = datetime.now().astimezone().date()
    if date_from is None:
        date_from = date_to - timedelta(days=7)
    try:
        data = await list_unified_orders(
            db,
            tenant_id,
            date_from=date_from,
            date_to=date_to,
            store_id=store_id,
            source=source,
            status=status,
            channel_key=channel_key,
            page=page,
            size=size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "data": data, "error": None}


@router.get("/stats", summary="渠道统计（GMV/单量/接单率）")
async def get_channel_stats(
    store_id: str = Query(..., description="门店ID"),
    stat_date: Optional[date] = Query(None, alias="date", description="统计日期，不传则今日"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """按平台统计当日GMV、订单量、接单率。"""
    import uuid as _uuid
    from shared.ontology.src.entities import Order as OrderModel
    from sqlalchemy import select, and_, func, case, or_

    tenant_id = _get_tenant_id(request)
    tid = _uuid.UUID(tenant_id)
    sid = _uuid.UUID(store_id)

    target_date = stat_date or datetime.now().date()
    local_tz = datetime.now().astimezone().tzinfo
    day_start = datetime(
        target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=local_tz
    )
    day_end = datetime(
        target_date.year, target_date.month, target_date.day, 23, 59, 59, tzinfo=local_tz
    )

    stats_by_platform = {}
    for platform in OmniChannelService.PLATFORMS:
        stmt = select(
            func.count().label("total_orders"),
            func.sum(
                case(
                    (OrderModel.status.in_(["confirmed", "completed"]), 1),
                    else_=0,
                )
            ).label("accepted_orders"),
            func.sum(
                case(
                    (OrderModel.status == "completed", getattr(OrderModel, "total_amount_fen", 0)),
                    else_=0,
                )
            ).label("gmv_fen"),
        ).where(
            and_(
                OrderModel.tenant_id == tid,
                OrderModel.store_id == sid,
                or_(
                    OrderModel.sales_channel_id == platform,
                    OrderModel.order_metadata["omni"]["platform"].astext == platform,
                ),
                OrderModel.created_at >= day_start,
                OrderModel.created_at <= day_end,
                OrderModel.is_deleted == False,  # noqa: E712
            )
        )
        result = await db.execute(stmt)
        row = result.one_or_none()
        total = int(row[0] or 0) if row else 0
        accepted = int(row[1] or 0) if row else 0
        gmv_fen = int(row[2] or 0) if row else 0
        accept_rate = round(accepted / total, 4) if total > 0 else 0.0

        stats_by_platform[platform] = {
            "platform": platform,
            "total_orders": total,
            "accepted_orders": accepted,
            "gmv_fen": gmv_fen,
            "accept_rate": accept_rate,
        }

    return {"ok": True, "data": {"date": str(target_date), "platforms": stats_by_platform}, "error": None}


# ─── 接单增强：映射查询与未映射记录落库 ─────────────────────────────────────────


async def _enrich_order_with_mappings(
    platform: str,
    store_id: str,
    tenant_id: str,
    order,
    db: AsyncSession,
) -> None:
    """查询 platform_dish_mappings，为每个订单菜品丰富 internal_dish_id。

    - 找到映射的：写入 item.internal_dish_id
    - 未找到映射的：创建 is_active=false 的占位记录（便于后续批量处理）
    """
    if not order.items:
        return

    tid = _uuid_module.UUID(tenant_id)
    sid = _uuid_module.UUID(store_id)

    # 设置 RLS context
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )

    for item in order.items:
        if not item.sku_id:
            continue

        mapping_result = await db.execute(
            text("""
                SELECT dish_id
                FROM platform_dish_mappings
                WHERE tenant_id       = :tid
                  AND store_id        = :sid
                  AND platform        = :platform
                  AND platform_item_id = :platform_item_id
                  AND is_active       = true
                LIMIT 1
            """),
            {
                "tid": tid,
                "sid": sid,
                "platform": platform,
                "platform_item_id": item.sku_id,
            },
        )
        row = mapping_result.fetchone()

        if row and row[0]:
            # 已映射：填入 internal_dish_id
            item.internal_dish_id = str(row[0])
        else:
            # 未映射：upsert 占位记录（is_active=false，待人工处理）
            try:
                await db.execute(
                    text("""
                        INSERT INTO platform_dish_mappings
                            (tenant_id, store_id, platform, platform_item_id,
                             platform_item_name, dish_id, is_active, updated_at)
                        VALUES
                            (:tid, :sid, :platform, :platform_item_id,
                             :platform_item_name, NULL, false, NOW())
                        ON CONFLICT (tenant_id, store_id, platform, platform_item_id)
                        DO UPDATE SET
                            platform_item_name = COALESCE(
                                EXCLUDED.platform_item_name,
                                platform_dish_mappings.platform_item_name
                            ),
                            updated_at = NOW()
                        WHERE platform_dish_mappings.dish_id IS NULL
                    """),
                    {
                        "tid": tid,
                        "sid": sid,
                        "platform": platform,
                        "platform_item_id": item.sku_id,
                        "platform_item_name": item.name,
                    },
                )
            except Exception as exc:  # noqa: BLE001 — MLPS3-P0: 单条upsert失败不阻断整批，最外层兜底
                logger.warning(
                    "omni_channel.enrich.upsert_placeholder_failed",
                    platform_item_id=item.sku_id,
                    error=str(exc),
                )


@router.get("/unmapped-items", summary="汇总所有平台未映射菜品（带自动匹配建议）")
async def get_unmapped_items(
    store_id: str = Query(..., description="门店ID"),
    platform: Optional[str] = Query(None, description="平台筛选（meituan/eleme/douyin），不传则查所有平台"),
    include_suggestions: bool = Query(True, description="是否包含自动匹配建议"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """汇总所有平台未映射菜品列表，可选带自动匹配建议（编辑距离算法）。

    需要先安装 tx-menu 的 channel_mapping_service（可通过依赖注入或直接在同库中引用）。
    为避免跨服务依赖，此处直接操作 platform_dish_mappings 表。
    """
    tenant_id = _get_tenant_id(request)
    tid = _uuid_module.UUID(tenant_id)
    sid = _uuid_module.UUID(store_id)

    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )

    platforms_to_check = (
        [platform] if platform and platform in OmniChannelService.PLATFORMS
        else OmniChannelService.PLATFORMS
    )

    all_unmapped: list[dict] = []
    for plat in platforms_to_check:
        result = await db.execute(
            text("""
                SELECT platform_item_id, platform_item_name, created_at, updated_at
                FROM platform_dish_mappings
                WHERE tenant_id = :tid
                  AND store_id  = :sid
                  AND platform  = :platform
                  AND dish_id IS NULL
                ORDER BY updated_at DESC
            """),
            {"tid": tid, "sid": sid, "platform": plat},
        )
        for row in result.fetchall():
            all_unmapped.append({
                "platform": plat,
                "platform_item_id": row[0],
                "platform_item_name": row[1],
                "first_seen_at": row[2].isoformat() if row[2] else None,
                "last_seen_at": row[3].isoformat() if row[3] else None,
                "suggestions": [],
            })

    # 自动匹配建议（仅当 include_suggestions=True 且有未映射条目时）
    if include_suggestions and all_unmapped:
        # 获取内部菜品候选
        dish_result = await db.execute(
            text("""
                SELECT id, dish_name
                FROM dishes
                WHERE tenant_id = :tid
                  AND (store_id = :sid OR store_id IS NULL)
                  AND is_available = true
                  AND is_deleted = false
                ORDER BY dish_name
            """),
            {"tid": tid, "sid": sid},
        )
        dish_rows = dish_result.fetchall()

        if dish_rows:
            from ..services.omni_channel_service import OmniChannelService as _OCS

            def _levenshtein(a: str, b: str) -> int:
                if a == b:
                    return 0
                la, lb = len(a), len(b)
                if la == 0:
                    return lb
                if lb == 0:
                    return la
                prev = list(range(lb + 1))
                for i, ca in enumerate(a, 1):
                    curr = [i] + [0] * lb
                    for j, cb in enumerate(b, 1):
                        cost = 0 if ca == cb else 1
                        curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
                    prev = curr
                return prev[lb]

            for entry in all_unmapped:
                name = entry["platform_item_name"] or ""
                if not name:
                    continue
                best_conf = 0.0
                best_dish_id = None
                best_dish_name = ""
                for d_id, d_name in dish_rows:
                    a, b = name.strip().lower(), d_name.strip().lower()
                    max_len = max(len(a), len(b), 1)
                    conf = max(0.0, 1.0 - _levenshtein(a, b) / max_len)
                    if conf > best_conf:
                        best_conf = conf
                        best_dish_id = d_id
                        best_dish_name = d_name
                if best_conf >= 0.60 and best_dish_id:
                    entry["suggestions"] = [
                        {
                            "dish_id": str(best_dish_id),
                            "dish_name": best_dish_name,
                            "confidence": round(best_conf, 4),
                        }
                    ]

    return {
        "ok": True,
        "data": {
            "unmapped_items": all_unmapped,
            "total": len(all_unmapped),
        },
        "error": None,
    }


@router.post("/auto-reject/run", summary="触发超时自动拒单")
async def run_auto_reject(
    store_id: str = Query(..., description="门店ID"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """手动触发或定时调用：对超时未接单的外卖订单执行自动拒单。

    超时时限从 OmniChannelService.auto_reject_minutes 读取（默认3分钟）。
    生产环境应通过定时任务（cron / Celery beat）自动调用此接口。
    """
    tenant_id = _get_tenant_id(request)
    svc = OmniChannelService()
    result = await svc.auto_reject_overdue(
        store_id=store_id,
        tenant_id=tenant_id,
        db=db,
    )
    if result["rejected_count"] > 0:
        await db.commit()

    return {"ok": True, "data": result, "error": None}
