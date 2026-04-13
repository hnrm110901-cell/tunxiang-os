"""智慧商街/档口管理路由

美食广场多档口并行收银 + 独立核算（TC-P2-12）

DB 表（v189）：outlets / outlet_orders
"""
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/food-court", tags=["food-court"])


# ─────────────────────────────────────────────────────────────────────────────
# RLS 辅助
# ─────────────────────────────────────────────────────────────────────────────

async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic 模型
# ─────────────────────────────────────────────────────────────────────────────

class OutletCreateRequest(BaseModel):
    store_id: str = Field(..., description="所属美食广场门店ID")
    name: str = Field(..., min_length=1, max_length=100, description="档口名称")
    outlet_code: Optional[str] = Field(None, max_length=20, description="档口编号")
    location: Optional[str] = Field(None, max_length=100, description="区位描述")
    owner_name: Optional[str] = Field(None, max_length=50, description="负责人姓名")
    owner_phone: Optional[str] = Field(None, max_length=20, description="负责人电话")
    settlement_ratio: Optional[float] = Field(1.0, ge=0.0, le=1.0, description="结算分成比例")


class OutletUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    outlet_code: Optional[str] = Field(None, max_length=20)
    location: Optional[str] = Field(None, max_length=100)
    owner_name: Optional[str] = Field(None, max_length=50)
    owner_phone: Optional[str] = Field(None, max_length=20)
    status: Optional[str] = Field(None, pattern='^(active|inactive|suspended)$')
    settlement_ratio: Optional[float] = Field(None, ge=0.0, le=1.0)


class FoodCourtOrderCreateRequest(BaseModel):
    outlet_id: str = Field(..., description="开单档口ID")
    store_id: str = Field(..., description="门店ID")
    items: list[dict] = Field(default_factory=list, description="品项列表")
    table_no: Optional[str] = Field(None, description="桌号（可选）")
    notes: Optional[str] = Field(None, description="备注")


class AddItemsRequest(BaseModel):
    outlet_id: str = Field(..., description="品项所属档口ID")
    items: list[dict] = Field(..., description="追加品项列表")


class CheckoutRequest(BaseModel):
    payment_method: str = Field(..., description="支付方式: cash/wechat/alipay/card")
    amount_tendered_fen: Optional[int] = Field(None, description="实收金额（分），现金支付时必填")


class SettlementSplitRequest(BaseModel):
    store_id: str = Field(..., description="门店ID")
    settlement_date: Optional[date] = Field(None, description="结算日期，默认今日")
    outlet_ids: Optional[list[str]] = Field(None, description="指定档口ID列表，默认全部")


# ─────────────────────────────────────────────────────────────────────────────
# 档口管理端点（DB 真实接入）
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/outlets")
async def list_outlets(
    store_id: Optional[str] = Query(None, description="按门店过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取档口列表（含今日营业额统计）"""
    try:
        await _set_rls(db, x_tenant_id)

        conditions = ["o.tenant_id = :tid", "o.is_deleted = FALSE"]
        params: dict = {"tid": x_tenant_id, "offset": (page - 1) * size, "limit": size}

        if store_id:
            conditions.append("o.store_id = :store_id")
            params["store_id"] = store_id
        if status:
            conditions.append("o.status = :status")
            params["status"] = status

        where = " AND ".join(conditions)

        count_res = await db.execute(
            text(f"SELECT COUNT(*) FROM outlets o WHERE {where}"), params
        )
        total = count_res.scalar() or 0

        rows = await db.execute(
            text(f"""
                SELECT o.id::text, o.tenant_id::text, o.store_id::text,
                       o.name, o.outlet_code, o.location,
                       o.owner_name, o.owner_phone, o.status,
                       o.settlement_ratio::float,
                       o.is_deleted, o.created_at, o.updated_at,
                       COALESCE(s.revenue_fen, 0)  AS today_revenue_fen,
                       COALESCE(s.order_count, 0)  AS today_order_count,
                       COALESCE(s.avg_order_fen, 0) AS today_avg_order_fen
                FROM outlets o
                LEFT JOIN (
                    SELECT outlet_id,
                           SUM(subtotal_fen)::bigint            AS revenue_fen,
                           COUNT(DISTINCT order_id)::int        AS order_count,
                           (CASE WHEN COUNT(DISTINCT order_id) > 0
                                 THEN SUM(subtotal_fen) / COUNT(DISTINCT order_id)
                                 ELSE 0 END)::bigint            AS avg_order_fen
                    FROM outlet_orders
                    WHERE tenant_id = :tid
                      AND DATE(created_at AT TIME ZONE 'Asia/Shanghai') = CURRENT_DATE
                      AND status = 'completed'
                    GROUP BY outlet_id
                ) s ON s.outlet_id = o.id
                WHERE {where}
                ORDER BY o.created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )

        items = [dict(r) for r in rows.mappings().all()]
        for item in items:
            if item.get("created_at"):
                item["created_at"] = item["created_at"].isoformat()
            if item.get("updated_at"):
                item["updated_at"] = item["updated_at"].isoformat()

        return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}

    except SQLAlchemyError as exc:
        logger.error("list_outlets_db_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询档口列表失败") from exc


@router.get("/outlets/{outlet_id}")
async def get_outlet(
    outlet_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取档口详情"""
    try:
        await _set_rls(db, x_tenant_id)
        row = await db.execute(
            text("""
                SELECT id::text, tenant_id::text, store_id::text,
                       name, outlet_code, location,
                       owner_name, owner_phone, status,
                       settlement_ratio::float, is_deleted,
                       created_at, updated_at
                FROM outlets
                WHERE id = :oid AND tenant_id = :tid AND is_deleted = FALSE
            """),
            {"oid": outlet_id, "tid": x_tenant_id},
        )
        outlet = row.mappings().first()
        if not outlet:
            raise HTTPException(status_code=404, detail=f"档口 {outlet_id} 不存在")

        data = dict(outlet)
        for k in ("created_at", "updated_at"):
            if data.get(k):
                data[k] = data[k].isoformat()

        return {"ok": True, "data": data}

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.error("get_outlet_db_error", outlet_id=outlet_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询档口详情失败") from exc


@router.post("/outlets")
async def create_outlet(
    req: OutletCreateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """创建档口（验证outlet_code唯一性）"""
    try:
        await _set_rls(db, x_tenant_id)

        # outlet_code 唯一性校验（同门店内）
        if req.outlet_code:
            dup = await db.execute(
                text("""
                    SELECT 1 FROM outlets
                    WHERE tenant_id = :tid
                      AND store_id  = :sid
                      AND outlet_code = :code
                      AND is_deleted = FALSE
                    LIMIT 1
                """),
                {"tid": x_tenant_id, "sid": req.store_id, "code": req.outlet_code},
            )
            if dup.first():
                raise HTTPException(
                    status_code=422,
                    detail=f"档口编号 {req.outlet_code} 在该门店已存在",
                )

        new_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        await db.execute(
            text("""
                INSERT INTO outlets
                    (id, tenant_id, store_id, name, outlet_code, location,
                     owner_name, owner_phone, status, settlement_ratio,
                     is_deleted, created_at, updated_at)
                VALUES
                    (:id, :tid, :sid, :name, :code, :location,
                     :owner_name, :owner_phone, 'active', :ratio,
                     FALSE, :now, :now)
            """),
            {
                "id": new_id,
                "tid": x_tenant_id,
                "sid": req.store_id,
                "name": req.name,
                "code": req.outlet_code,
                "location": req.location,
                "owner_name": req.owner_name,
                "owner_phone": req.owner_phone,
                "ratio": req.settlement_ratio or 1.0,
                "now": now,
            },
        )
        await db.commit()

        logger.info("outlet_created", outlet_id=new_id, name=req.name, tenant_id=x_tenant_id)
        return {"ok": True, "data": {
            "id": new_id, "tenant_id": x_tenant_id, "store_id": req.store_id,
            "name": req.name, "outlet_code": req.outlet_code, "location": req.location,
            "owner_name": req.owner_name, "owner_phone": req.owner_phone,
            "status": "active", "settlement_ratio": req.settlement_ratio or 1.0,
            "is_deleted": False, "created_at": now.isoformat(), "updated_at": now.isoformat(),
        }}

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("create_outlet_db_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="创建档口失败") from exc


@router.put("/outlets/{outlet_id}")
async def update_outlet(
    outlet_id: str,
    req: OutletUpdateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """更新档口信息"""
    try:
        await _set_rls(db, x_tenant_id)

        updates = {k: v for k, v in req.model_dump().items() if v is not None}
        if not updates:
            raise HTTPException(status_code=400, detail="没有提供任何更新字段")

        # outlet_code 唯一性校验
        if "outlet_code" in updates:
            dup = await db.execute(
                text("""
                    SELECT 1 FROM outlets o
                    JOIN outlets me ON me.id = :oid AND me.tenant_id = :tid
                    WHERE o.tenant_id  = :tid
                      AND o.store_id   = me.store_id
                      AND o.outlet_code = :code
                      AND o.id        != :oid
                      AND o.is_deleted = FALSE
                    LIMIT 1
                """),
                {"tid": x_tenant_id, "oid": outlet_id, "code": updates["outlet_code"]},
            )
            if dup.first():
                raise HTTPException(
                    status_code=422,
                    detail=f"档口编号 {updates['outlet_code']} 在该门店已存在",
                )

        set_parts = ", ".join(f"{col} = :{col}" for col in updates)
        params = {**updates, "id": outlet_id, "tid": x_tenant_id,
                  "updated_at": datetime.now(timezone.utc)}

        result = await db.execute(
            text(f"""
                UPDATE outlets
                SET {set_parts}, updated_at = :updated_at
                WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE
                RETURNING id::text, name, status, settlement_ratio::float, updated_at
            """),
            params,
        )
        row = result.mappings().first()
        await db.commit()

        if not row:
            raise HTTPException(status_code=404, detail=f"档口 {outlet_id} 不存在")

        logger.info("outlet_updated", outlet_id=outlet_id, tenant_id=x_tenant_id)
        r = dict(row)
        if r.get("updated_at"):
            r["updated_at"] = r["updated_at"].isoformat()
        return {"ok": True, "data": r}

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("update_outlet_db_error", outlet_id=outlet_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="更新档口失败") from exc


@router.delete("/outlets/{outlet_id}")
async def deactivate_outlet(
    outlet_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """停用档口（软删除）"""
    try:
        await _set_rls(db, x_tenant_id)
        result = await db.execute(
            text("""
                UPDATE outlets
                SET is_deleted = TRUE, status = 'inactive', updated_at = NOW()
                WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE
                RETURNING id
            """),
            {"id": outlet_id, "tid": x_tenant_id},
        )
        if not result.first():
            raise HTTPException(status_code=404, detail=f"档口 {outlet_id} 不存在")
        await db.commit()

        logger.info("outlet_deactivated", outlet_id=outlet_id, tenant_id=x_tenant_id)
        return {"ok": True, "data": {"outlet_id": outlet_id, "status": "deactivated"}}

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("deactivate_outlet_db_error", outlet_id=outlet_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="停用档口失败") from exc


# ─────────────────────────────────────────────────────────────────────────────
# 商户别名端点（/merchants → /outlets 语义别名）
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/merchants")
async def list_merchants(
    store_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取商户（档口）列表 —— /outlets GET 的语义别名。"""
    return await list_outlets(store_id=store_id, status=status, page=page, size=size,
                               x_tenant_id=x_tenant_id, db=db)


@router.post("/merchants")
async def create_merchant(
    req: OutletCreateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """新建档口商户 —— /outlets POST 的语义别名。"""
    return await create_outlet(req=req, x_tenant_id=x_tenant_id, db=db)


@router.put("/merchants/{merchant_id}")
async def update_merchant(
    merchant_id: str,
    req: OutletUpdateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """更新档口商户信息 —— /outlets PUT 的语义别名。"""
    return await update_outlet(outlet_id=merchant_id, req=req,
                                x_tenant_id=x_tenant_id, db=db)


# ─────────────────────────────────────────────────────────────────────────────
# 报表统计端点（DB 真实接入）
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/stats/daily")
async def get_daily_stats(
    store_id: Optional[str] = Query(None, description="门店ID"),
    stat_date: Optional[date] = Query(None, description="统计日期，默认今日"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """当日各档口汇总（营业额/订单数/客单价）"""
    try:
        await _set_rls(db, x_tenant_id)
        target_date = stat_date or date.today()

        outlet_filter = "AND o.store_id = :store_id" if store_id else ""
        params: dict = {"tid": x_tenant_id, "date": target_date}
        if store_id:
            params["store_id"] = store_id

        rows = await db.execute(
            text(f"""
                SELECT o.id::text   AS outlet_id,
                       o.name       AS outlet_name,
                       o.outlet_code,
                       o.location,
                       o.status,
                       COALESCE(s.revenue_fen, 0)   AS revenue_fen,
                       COALESCE(s.order_count, 0)   AS order_count,
                       COALESCE(s.item_count, 0)    AS item_count,
                       COALESCE(s.avg_order_fen, 0) AS avg_order_fen
                FROM outlets o
                LEFT JOIN (
                    SELECT oo.outlet_id,
                           SUM(oo.subtotal_fen)::bigint          AS revenue_fen,
                           COUNT(DISTINCT oo.order_id)::int      AS order_count,
                           SUM(oo.item_count)::int               AS item_count,
                           (CASE WHEN COUNT(DISTINCT oo.order_id) > 0
                                 THEN SUM(oo.subtotal_fen) / COUNT(DISTINCT oo.order_id)
                                 ELSE 0 END)::bigint             AS avg_order_fen
                    FROM outlet_orders oo
                    WHERE oo.tenant_id = :tid
                      AND DATE(oo.created_at AT TIME ZONE 'Asia/Shanghai') = :date
                      AND oo.status = 'completed'
                    GROUP BY oo.outlet_id
                ) s ON s.outlet_id = o.id
                WHERE o.tenant_id = :tid AND o.is_deleted = FALSE
                {outlet_filter}
                ORDER BY revenue_fen DESC
            """),
            params,
        )
        stats = [dict(r) for r in rows.mappings().all()]
        total_revenue = sum(r["revenue_fen"] for r in stats)
        total_orders = sum(r["order_count"] for r in stats)

        return {"ok": True, "data": {
            "stat_date": str(target_date),
            "store_id": store_id,
            "total_revenue_fen": total_revenue,
            "total_order_count": total_orders,
            "outlet_count": len(stats),
            "outlets": stats,
        }}

    except SQLAlchemyError as exc:
        logger.error("daily_stats_db_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询日统计失败") from exc


@router.get("/stats/compare")
async def get_outlet_compare(
    store_id: Optional[str] = Query(None, description="门店ID"),
    start_date: Optional[date] = Query(None, description="开始日期"),
    end_date: Optional[date] = Query(None, description="结束日期"),
    outlet_ids: Optional[str] = Query(None, description="档口ID列表，逗号分隔"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """档口对比报表（日期范围内各档口营业额趋势）"""
    try:
        await _set_rls(db, x_tenant_id)
        _start = start_date or date.today()
        _end = end_date or date.today()
        days = min((_end - _start).days + 1, 30)

        outlet_id_list = [oid.strip() for oid in outlet_ids.split(",")] if outlet_ids else []

        # 查询范围内逐日逐档口汇总
        outlet_filter = ""
        params: dict = {"tid": x_tenant_id, "start": _start, "end": _end}
        if store_id:
            outlet_filter += " AND o.store_id = :store_id"
            params["store_id"] = store_id
        if outlet_id_list:
            outlet_filter += " AND oo.outlet_id = ANY(:outlet_ids)"
            params["outlet_ids"] = outlet_id_list

        rows = await db.execute(
            text(f"""
                SELECT DATE(oo.created_at AT TIME ZONE 'Asia/Shanghai') AS biz_date,
                       oo.outlet_id::text,
                       o.name AS outlet_name,
                       o.outlet_code,
                       SUM(oo.subtotal_fen)::bigint         AS revenue_fen,
                       COUNT(DISTINCT oo.order_id)::int     AS order_count
                FROM outlet_orders oo
                JOIN outlets o ON o.id = oo.outlet_id AND o.is_deleted = FALSE
                WHERE oo.tenant_id = :tid
                  AND DATE(oo.created_at AT TIME ZONE 'Asia/Shanghai')
                        BETWEEN :start AND :end
                  AND oo.status = 'completed'
                  {outlet_filter}
                GROUP BY biz_date, oo.outlet_id, o.name, o.outlet_code
                ORDER BY biz_date, oo.outlet_id
            """),
            params,
        )
        db_rows = rows.mappings().all()

        # 构建趋势结构
        outlet_meta: dict[str, dict] = {}
        trend_map: dict[str, dict] = {}
        for r in db_rows:
            oid = r["outlet_id"]
            outlet_meta[oid] = {"outlet_name": r["outlet_name"], "outlet_code": r["outlet_code"]}
            day_str = str(r["biz_date"])
            if day_str not in trend_map:
                trend_map[day_str] = {"date": day_str}
            trend_map[day_str][oid] = {
                "revenue_fen": r["revenue_fen"],
                "order_count": r["order_count"],
                "outlet_name": r["outlet_name"],
            }

        trend_data = [trend_map[str(_start + timedelta(days=i))]
                      for i in range(days)
                      if str(_start + timedelta(days=i)) in trend_map]

        compare_summary = [
            {
                "outlet_id": oid,
                "outlet_name": meta["outlet_name"],
                "outlet_code": meta["outlet_code"],
                "total_revenue_fen": sum(
                    d.get(oid, {}).get("revenue_fen", 0) for d in trend_data
                ),
                "total_order_count": sum(
                    d.get(oid, {}).get("order_count", 0) for d in trend_data
                ),
            }
            for oid, meta in outlet_meta.items()
        ]
        for item in compare_summary:
            item["avg_daily_revenue_fen"] = (
                item["total_revenue_fen"] // days if days > 0 else 0
            )

        return {"ok": True, "data": {
            "start_date": str(_start), "end_date": str(_end), "days": days,
            "outlets": compare_summary, "trend": trend_data,
        }}

    except SQLAlchemyError as exc:
        logger.error("outlet_compare_db_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询对比报表失败") from exc


# ─────────────────────────────────────────────────────────────────────────────
# 日结结算端点（DB 真实接入）
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/settlement/daily")
async def get_daily_settlement(
    store_id: Optional[str] = Query(None, description="门店ID"),
    settlement_date: Optional[date] = Query(None, description="结算日期，默认今日"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """按档口拆分日结（各商户营业额/订单数/应结金额）"""
    try:
        await _set_rls(db, x_tenant_id)
        target_date = settlement_date or date.today()

        store_filter = "AND o.store_id = :store_id" if store_id else ""
        params: dict = {"tid": x_tenant_id, "date": target_date}
        if store_id:
            params["store_id"] = store_id

        rows = await db.execute(
            text(f"""
                SELECT o.id::text      AS outlet_id,
                       o.name          AS outlet_name,
                       o.outlet_code,
                       o.location,
                       o.owner_name,
                       o.status,
                       o.settlement_ratio::float,
                       COALESCE(s.revenue_fen, 0)  AS revenue_fen,
                       COALESCE(s.order_count, 0)  AS order_count
                FROM outlets o
                LEFT JOIN (
                    SELECT oo.outlet_id,
                           SUM(oo.subtotal_fen)::bigint       AS revenue_fen,
                           COUNT(DISTINCT oo.order_id)::int   AS order_count
                    FROM outlet_orders oo
                    WHERE oo.tenant_id = :tid
                      AND DATE(oo.created_at AT TIME ZONE 'Asia/Shanghai') = :date
                      AND oo.status = 'completed'
                    GROUP BY oo.outlet_id
                ) s ON s.outlet_id = o.id
                WHERE o.tenant_id = :tid AND o.is_deleted = FALSE
                {store_filter}
                ORDER BY revenue_fen DESC
            """),
            params,
        )

        settlement_items: list[dict] = []
        total_revenue = total_orders = total_settlement = 0

        for r in rows.mappings().all():
            revenue = r["revenue_fen"]
            order_count = r["order_count"]
            ratio = float(r["settlement_ratio"] or 1.0)
            settlement_amount = int(revenue * ratio)

            total_revenue += revenue
            total_orders += order_count
            total_settlement += settlement_amount

            settlement_items.append({
                "outlet_id": r["outlet_id"],
                "outlet_name": r["outlet_name"],
                "outlet_code": r["outlet_code"],
                "location": r["location"],
                "owner_name": r["owner_name"],
                "revenue_fen": revenue,
                "order_count": order_count,
                "avg_order_fen": revenue // order_count if order_count > 0 else 0,
                "settlement_ratio": ratio,
                "settlement_amount_fen": settlement_amount,
                "status": r["status"],
            })

        return {"ok": True, "data": {
            "settlement_date": str(target_date),
            "store_id": store_id,
            "total_revenue_fen": total_revenue,
            "total_order_count": total_orders,
            "total_settlement_fen": total_settlement,
            "outlet_count": len(settlement_items),
            "outlets": settlement_items,
        }}

    except SQLAlchemyError as exc:
        logger.error("daily_settlement_db_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询日结失败") from exc


@router.post("/settlement/split")
async def settlement_split(
    req: SettlementSplitRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """日结时按商户分账汇总（基于 outlets.settlement_ratio 真实字段）。"""
    try:
        await _set_rls(db, x_tenant_id)
        target_date = req.settlement_date or date.today()

        outlet_filter = ""
        params: dict = {"tid": x_tenant_id, "date": target_date}
        if req.outlet_ids:
            outlet_filter = "AND o.id = ANY(:outlet_ids)"
            params["outlet_ids"] = req.outlet_ids
        if req.store_id:
            outlet_filter += " AND o.store_id = :store_id"
            params["store_id"] = req.store_id

        rows = await db.execute(
            text(f"""
                SELECT o.id::text      AS outlet_id,
                       o.name          AS outlet_name,
                       o.outlet_code,
                       o.owner_name,
                       o.owner_phone,
                       o.settlement_ratio::float,
                       COALESCE(s.revenue_fen, 0)  AS revenue_fen,
                       COALESCE(s.order_count, 0)  AS order_count
                FROM outlets o
                LEFT JOIN (
                    SELECT oo.outlet_id,
                           SUM(oo.subtotal_fen)::bigint       AS revenue_fen,
                           COUNT(DISTINCT oo.order_id)::int   AS order_count
                    FROM outlet_orders oo
                    WHERE oo.tenant_id = :tid
                      AND DATE(oo.created_at AT TIME ZONE 'Asia/Shanghai') = :date
                      AND oo.status = 'completed'
                    GROUP BY oo.outlet_id
                ) s ON s.outlet_id = o.id
                WHERE o.tenant_id = :tid AND o.is_deleted = FALSE
                {outlet_filter}
                ORDER BY revenue_fen DESC
            """),
            params,
        )

        split_results: list[dict] = []
        grand_total_fen = 0

        for r in rows.mappings().all():
            revenue = r["revenue_fen"]
            ratio = float(r["settlement_ratio"] or 1.0)
            settlement_amount = int(revenue * ratio)
            platform_fee = int(revenue * 0.005)  # 0.5% 平台服务费
            net_payout = settlement_amount - platform_fee
            grand_total_fen += net_payout

            split_results.append({
                "outlet_id": r["outlet_id"],
                "outlet_name": r["outlet_name"],
                "outlet_code": r["outlet_code"],
                "owner_name": r["owner_name"],
                "owner_phone": r["owner_phone"],
                "settlement_date": str(target_date),
                "revenue_fen": revenue,
                "order_count": r["order_count"],
                "settlement_ratio": ratio,
                "gross_settlement_fen": settlement_amount,
                "platform_fee_fen": platform_fee,
                "net_payout_fen": net_payout,
                "status": "settled",
                "settled_at": datetime.now(timezone.utc).isoformat(),
            })

        logger.info(
            "settlement_split_completed",
            store_id=req.store_id,
            outlet_count=len(split_results),
            grand_total_fen=grand_total_fen,
            date=str(target_date),
        )

        return {"ok": True, "data": {
            "store_id": req.store_id,
            "settlement_date": str(target_date),
            "outlet_count": len(split_results),
            "grand_total_payout_fen": grand_total_fen,
            "split_details": split_results,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }}

    except SQLAlchemyError as exc:
        logger.error("settlement_split_db_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="分账结算失败") from exc


# ─────────────────────────────────────────────────────────────────────────────
# 档口订单查询（DB 真实接入）
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/orders")
async def list_outlet_orders(
    outlet_id: Optional[str] = Query(None, description="按档口过滤"),
    order_date: Optional[date] = Query(None, description="按日期过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """档口订单查询（outlet_orders 表，支持多条件过滤+分页）"""
    try:
        await _set_rls(db, x_tenant_id)

        conditions = ["oo.tenant_id = :tid"]
        params: dict = {"tid": x_tenant_id, "offset": (page - 1) * size, "limit": size}

        if outlet_id:
            conditions.append("oo.outlet_id = :outlet_id")
            params["outlet_id"] = outlet_id
        if status:
            conditions.append("oo.status = :status")
            params["status"] = status
        if order_date:
            conditions.append("DATE(oo.created_at AT TIME ZONE 'Asia/Shanghai') = :order_date")
            params["order_date"] = order_date

        where = " AND ".join(conditions)

        count_res = await db.execute(
            text(f"SELECT COUNT(*) FROM outlet_orders oo WHERE {where}"), params
        )
        total = count_res.scalar() or 0

        rows = await db.execute(
            text(f"""
                SELECT oo.id::text, oo.outlet_id::text, oo.order_id::text,
                       oo.subtotal_fen, oo.item_count, oo.status, oo.notes,
                       oo.created_at, oo.updated_at,
                       o.name AS outlet_name, o.outlet_code
                FROM outlet_orders oo
                LEFT JOIN outlets o ON o.id = oo.outlet_id
                WHERE {where}
                ORDER BY oo.created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )

        items = []
        for r in rows.mappings().all():
            row = dict(r)
            for k in ("created_at", "updated_at"):
                if row.get(k):
                    row[k] = row[k].isoformat()
            items.append(row)

        return {"ok": True, "data": {"items": items, "total": total, "page": page, "size": size}}

    except SQLAlchemyError as exc:
        logger.error("list_outlet_orders_db_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="查询档口订单失败") from exc


# ─────────────────────────────────────────────────────────────────────────────
# 档口收银端点（TODO: 待与 cashier_engine 深度集成）
# 当前实现为轻量占位，创建真实 outlet_orders 记录但不创建完整 orders 行
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/orders")
async def create_food_court_order(
    req: FoodCourtOrderCreateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """档口开单（写入 outlet_orders，正式 orders 行由 cashier_engine 创建）"""
    try:
        await _set_rls(db, x_tenant_id)

        # 校验档口存在且活跃
        outlet_row = await db.execute(
            text("""
                SELECT id::text, name, status
                FROM outlets
                WHERE id = :oid AND tenant_id = :tid AND is_deleted = FALSE
            """),
            {"oid": req.outlet_id, "tid": x_tenant_id},
        )
        outlet = outlet_row.mappings().first()
        if not outlet:
            raise HTTPException(status_code=404, detail=f"档口 {req.outlet_id} 不存在或已停用")
        if outlet["status"] != "active":
            raise HTTPException(
                status_code=422,
                detail=f"档口 {outlet['name']} 当前状态为 {outlet['status']}，无法开单",
            )

        order_id = str(uuid.uuid4())
        outlet_order_id = str(uuid.uuid4())
        subtotal_fen = sum(
            item.get("price_fen", 0) * item.get("qty", 1) for item in req.items
        )
        item_count = sum(item.get("qty", 1) for item in req.items)
        now = datetime.now(timezone.utc)

        await db.execute(
            text("""
                INSERT INTO outlet_orders
                    (id, tenant_id, outlet_id, order_id, subtotal_fen,
                     item_count, status, notes, created_at, updated_at)
                VALUES
                    (:id, :tid, :outlet_id, :order_id, :subtotal_fen,
                     :item_count, 'pending', :notes, :now, :now)
            """),
            {
                "id": outlet_order_id,
                "tid": x_tenant_id,
                "outlet_id": req.outlet_id,
                "order_id": order_id,
                "subtotal_fen": subtotal_fen,
                "item_count": item_count,
                "notes": req.notes,
                "now": now,
            },
        )
        await db.commit()

        logger.info("food_court_order_created", order_id=order_id, outlet_id=req.outlet_id)
        return {"ok": True, "data": {
            "order_id": order_id,
            "outlet_order_id": outlet_order_id,
            "outlet_id": req.outlet_id,
            "outlet_name": outlet["name"],
            "store_id": req.store_id,
            "table_no": req.table_no,
            "items": req.items,
            "subtotal_fen": subtotal_fen,
            "total_fen": subtotal_fen,
            "status": "pending",
            "created_at": now.isoformat(),
        }}

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("create_food_court_order_db_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="开单失败") from exc


@router.post("/orders/{order_id}/add-items")
async def add_items_to_order(
    order_id: str,
    req: AddItemsRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """追加品项（更新或新增对应档口的 outlet_order 记录）"""
    try:
        await _set_rls(db, x_tenant_id)

        outlet_row = await db.execute(
            text("SELECT id::text, name FROM outlets WHERE id = :oid AND tenant_id = :tid AND is_deleted = FALSE"),
            {"oid": req.outlet_id, "tid": x_tenant_id},
        )
        outlet = outlet_row.mappings().first()
        if not outlet:
            raise HTTPException(status_code=404, detail=f"档口 {req.outlet_id} 不存在")

        added_subtotal = sum(item.get("price_fen", 0) * item.get("qty", 1) for item in req.items)
        added_count = sum(item.get("qty", 1) for item in req.items)

        # 查找该订单中是否已有该档口的 outlet_order
        existing = await db.execute(
            text("""
                SELECT id, subtotal_fen, item_count FROM outlet_orders
                WHERE order_id = :oid AND outlet_id = :outlet_id AND tenant_id = :tid
                LIMIT 1
            """),
            {"oid": order_id, "outlet_id": req.outlet_id, "tid": x_tenant_id},
        )
        existing_row = existing.mappings().first()

        if existing_row:
            new_subtotal = existing_row["subtotal_fen"] + added_subtotal
            new_count = (existing_row["item_count"] or 0) + added_count
            await db.execute(
                text("""
                    UPDATE outlet_orders
                    SET subtotal_fen = :sub, item_count = :cnt, updated_at = NOW()
                    WHERE id = :id AND tenant_id = :tid
                """),
                {"sub": new_subtotal, "cnt": new_count, "id": existing_row["id"], "tid": x_tenant_id},
            )
        else:
            await db.execute(
                text("""
                    INSERT INTO outlet_orders
                        (id, tenant_id, outlet_id, order_id, subtotal_fen,
                         item_count, status, created_at, updated_at)
                    VALUES
                        (:id, :tid, :outlet_id, :order_id, :sub, :cnt, 'pending', NOW(), NOW())
                """),
                {
                    "id": str(uuid.uuid4()),
                    "tid": x_tenant_id,
                    "outlet_id": req.outlet_id,
                    "order_id": order_id,
                    "sub": added_subtotal,
                    "cnt": added_count,
                },
            )

        await db.commit()

        logger.info("items_added_to_order", order_id=order_id, outlet_id=req.outlet_id, count=added_count)
        return {"ok": True, "data": {
            "order_id": order_id,
            "outlet_id": req.outlet_id,
            "outlet_name": outlet["name"],
            "added_items": req.items,
            "added_subtotal_fen": added_subtotal,
        }}

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("add_items_db_error", order_id=order_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="追加品项失败") from exc


@router.post("/orders/{order_id}/checkout")
async def checkout_food_court_order(
    order_id: str,
    req: CheckoutRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """统一结算（将该订单所有 outlet_orders 标记为 completed）"""
    try:
        await _set_rls(db, x_tenant_id)

        # 查询该订单所有档口子单
        rows = await db.execute(
            text("""
                SELECT oo.id, oo.outlet_id::text, oo.subtotal_fen, oo.item_count,
                       o.name AS outlet_name, o.outlet_code
                FROM outlet_orders oo
                LEFT JOIN outlets o ON o.id = oo.outlet_id
                WHERE oo.order_id = :oid AND oo.tenant_id = :tid
            """),
            {"oid": order_id, "tid": x_tenant_id},
        )
        oo_rows = rows.mappings().all()
        if not oo_rows:
            raise HTTPException(status_code=404, detail=f"订单 {order_id} 无对应档口记录")

        total_fen = sum(r["subtotal_fen"] for r in oo_rows)
        if not total_fen:
            raise HTTPException(status_code=422, detail="订单金额为0，无法结算")

        change_fen = 0
        if req.payment_method == "cash":
            if not req.amount_tendered_fen:
                raise HTTPException(status_code=422, detail="现金支付必须提供实收金额")
            if req.amount_tendered_fen < total_fen:
                raise HTTPException(
                    status_code=422,
                    detail=f"实收金额 {req.amount_tendered_fen} 分不足，应收 {total_fen} 分",
                )
            change_fen = req.amount_tendered_fen - total_fen

        await db.execute(
            text("""
                UPDATE outlet_orders
                SET status = 'completed', updated_at = NOW()
                WHERE order_id = :oid AND tenant_id = :tid
            """),
            {"oid": order_id, "tid": x_tenant_id},
        )
        await db.commit()

        outlet_breakdown = [
            {
                "outlet_id": r["outlet_id"],
                "outlet_name": r["outlet_name"],
                "outlet_code": r["outlet_code"],
                "subtotal_fen": r["subtotal_fen"],
                "item_count": r["item_count"],
            }
            for r in oo_rows
        ]

        logger.info("food_court_checkout_completed", order_id=order_id, total_fen=total_fen)
        return {"ok": True, "data": {
            "order_id": order_id,
            "total_fen": total_fen,
            "payment_method": req.payment_method,
            "amount_tendered_fen": req.amount_tendered_fen,
            "change_fen": change_fen,
            "outlet_breakdown": outlet_breakdown,
            "paid_at": datetime.now(timezone.utc).isoformat(),
        }}

    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.error("checkout_db_error", order_id=order_id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="结算失败") from exc
