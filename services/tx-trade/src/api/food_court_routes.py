"""
智慧商街/档口管理路由

美食广场多档口并行收银 + 独立核算
TC-P2-12
"""
import structlog
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
import uuid
from datetime import date, datetime

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/food-court", tags=["food-court"])

# ─────────────────────────────────────────────────────────────────────────────
# Mock 数据（模拟3个档口的美食广场）
# ─────────────────────────────────────────────────────────────────────────────

MOCK_OUTLETS: list[dict] = [
    {
        "id": "out-001",
        "tenant_id": "tenant-demo",
        "store_id": "store-demo-001",
        "name": "张记烤鱼",
        "outlet_code": "A01",
        "location": "A区1号",
        "owner_name": "张师傅",
        "owner_phone": "13800000001",
        "status": "active",
        "settlement_ratio": "1.0000",
        "is_deleted": False,
        "today_revenue_fen": 285600,
        "today_order_count": 23,
        "today_avg_order_fen": 12417,
        "created_at": "2026-01-01T00:00:00+08:00",
        "updated_at": "2026-04-06T00:00:00+08:00",
    },
    {
        "id": "out-002",
        "tenant_id": "tenant-demo",
        "store_id": "store-demo-001",
        "name": "李家粉面",
        "outlet_code": "A02",
        "location": "A区2号",
        "owner_name": "李老板",
        "owner_phone": "13800000002",
        "status": "active",
        "settlement_ratio": "1.0000",
        "is_deleted": False,
        "today_revenue_fen": 156800,
        "today_order_count": 41,
        "today_avg_order_fen": 3824,
        "created_at": "2026-01-01T00:00:00+08:00",
        "updated_at": "2026-04-06T00:00:00+08:00",
    },
    {
        "id": "out-003",
        "tenant_id": "tenant-demo",
        "store_id": "store-demo-001",
        "name": "老王串串",
        "outlet_code": "B01",
        "location": "B区1号",
        "owner_name": "王老板",
        "owner_phone": "13800000003",
        "status": "active",
        "settlement_ratio": "1.0000",
        "is_deleted": False,
        "today_revenue_fen": 198400,
        "today_order_count": 31,
        "today_avg_order_fen": 6400,
        "created_at": "2026-01-01T00:00:00+08:00",
        "updated_at": "2026-04-06T00:00:00+08:00",
    },
]

MOCK_OUTLET_ORDERS: list[dict] = [
    {
        "id": "oo-001",
        "tenant_id": "tenant-demo",
        "outlet_id": "out-001",
        "order_id": "order-demo-001",
        "subtotal_fen": 8800,
        "item_count": 2,
        "status": "completed",
        "notes": None,
        "created_at": "2026-04-06T10:30:00+08:00",
        "updated_at": "2026-04-06T10:45:00+08:00",
    },
    {
        "id": "oo-002",
        "tenant_id": "tenant-demo",
        "outlet_id": "out-002",
        "order_id": "order-demo-001",
        "subtotal_fen": 2400,
        "item_count": 2,
        "status": "completed",
        "notes": None,
        "created_at": "2026-04-06T10:30:00+08:00",
        "updated_at": "2026-04-06T10:45:00+08:00",
    },
    {
        "id": "oo-003",
        "tenant_id": "tenant-demo",
        "outlet_id": "out-003",
        "order_id": "order-demo-002",
        "subtotal_fen": 5600,
        "item_count": 4,
        "status": "pending",
        "notes": "多加辣",
        "created_at": "2026-04-06T11:00:00+08:00",
        "updated_at": "2026-04-06T11:00:00+08:00",
    },
]

# 模拟档口菜品数据（用于收银下单）
MOCK_OUTLET_MENU: dict[str, list[dict]] = {
    "out-001": [
        {"id": "dish-001", "name": "招牌烤鱼", "price_fen": 6800, "category": "烤鱼"},
        {"id": "dish-002", "name": "香辣烤鱼", "price_fen": 7200, "category": "烤鱼"},
        {"id": "dish-003", "name": "豆腐", "price_fen": 800, "category": "配菜"},
        {"id": "dish-004", "name": "粉丝", "price_fen": 600, "category": "配菜"},
    ],
    "out-002": [
        {"id": "dish-005", "name": "牛肉粉", "price_fen": 1800, "category": "粉面"},
        {"id": "dish-006", "name": "猪脚粉", "price_fen": 1600, "category": "粉面"},
        {"id": "dish-007", "name": "肥肠面", "price_fen": 1400, "category": "粉面"},
        {"id": "dish-008", "name": "卤蛋", "price_fen": 200, "category": "小料"},
    ],
    "out-003": [
        {"id": "dish-009", "name": "牛肉串", "price_fen": 600, "category": "荤串"},
        {"id": "dish-010", "name": "羊肉串", "price_fen": 500, "category": "荤串"},
        {"id": "dish-011", "name": "脑花", "price_fen": 1200, "category": "特色"},
        {"id": "dish-012", "name": "青笋", "price_fen": 300, "category": "素串"},
    ],
}

# 内存中的临时订单存储（mock用）
_mock_orders: dict[str, dict] = {}
_mock_outlet_orders: list[dict] = list(MOCK_OUTLET_ORDERS)


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


# ─────────────────────────────────────────────────────────────────────────────
# 档口管理端点
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/outlets")
async def list_outlets(
    store_id: Optional[str] = Query(None, description="按门店过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    """获取档口列表（支持store_id过滤，返回含今日统计）"""
    try:
        items = [o for o in MOCK_OUTLETS if not o["is_deleted"]]

        if store_id:
            items = [o for o in items if o["store_id"] == store_id]
        if status:
            items = [o for o in items if o["status"] == status]

        total = len(items)
        start = (page - 1) * size
        paginated = items[start: start + size]

        return {
            "ok": True,
            "data": {
                "items": paginated,
                "total": total,
                "page": page,
                "size": size,
            },
        }
    except (KeyError, IndexError) as exc:
        logger.error("list_outlets_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/outlets/{outlet_id}")
async def get_outlet(outlet_id: str):
    """获取档口详情"""
    try:
        outlet = next((o for o in MOCK_OUTLETS if o["id"] == outlet_id and not o["is_deleted"]), None)
        if not outlet:
            raise HTTPException(status_code=404, detail=f"档口 {outlet_id} 不存在")

        # 补充菜单数据
        menu = MOCK_OUTLET_MENU.get(outlet_id, [])
        detail = {**outlet, "menu_items": menu}

        return {"ok": True, "data": detail}
    except HTTPException:
        raise
    except KeyError as exc:
        logger.error("get_outlet_failed", outlet_id=outlet_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/outlets")
async def create_outlet(req: OutletCreateRequest):
    """创建档口（验证outlet_code唯一性）"""
    try:
        # outlet_code 唯一性校验（同一门店内）
        if req.outlet_code:
            existing = next(
                (o for o in MOCK_OUTLETS
                 if o["store_id"] == req.store_id
                 and o.get("outlet_code") == req.outlet_code
                 and not o["is_deleted"]),
                None,
            )
            if existing:
                raise ValueError(f"档口编号 {req.outlet_code} 在该门店已存在")

        new_outlet: dict = {
            "id": f"out-{str(uuid.uuid4())[:8]}",
            "tenant_id": "tenant-demo",
            "store_id": req.store_id,
            "name": req.name,
            "outlet_code": req.outlet_code,
            "location": req.location,
            "owner_name": req.owner_name,
            "owner_phone": req.owner_phone,
            "status": "active",
            "settlement_ratio": str(req.settlement_ratio or 1.0),
            "is_deleted": False,
            "today_revenue_fen": 0,
            "today_order_count": 0,
            "today_avg_order_fen": 0,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        MOCK_OUTLETS.append(new_outlet)

        logger.info("outlet_created", outlet_id=new_outlet["id"], name=req.name)
        return {"ok": True, "data": new_outlet}

    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/outlets/{outlet_id}")
async def update_outlet(outlet_id: str, req: OutletUpdateRequest):
    """更新档口信息"""
    try:
        outlet = next((o for o in MOCK_OUTLETS if o["id"] == outlet_id and not o["is_deleted"]), None)
        if not outlet:
            raise HTTPException(status_code=404, detail=f"档口 {outlet_id} 不存在")

        # outlet_code 唯一性校验
        if req.outlet_code and req.outlet_code != outlet.get("outlet_code"):
            existing = next(
                (o for o in MOCK_OUTLETS
                 if o["store_id"] == outlet["store_id"]
                 and o.get("outlet_code") == req.outlet_code
                 and o["id"] != outlet_id
                 and not o["is_deleted"]),
                None,
            )
            if existing:
                raise ValueError(f"档口编号 {req.outlet_code} 在该门店已存在")

        update_data = req.model_dump(exclude_none=True)
        outlet.update(update_data)
        outlet["updated_at"] = datetime.now().isoformat()

        logger.info("outlet_updated", outlet_id=outlet_id)
        return {"ok": True, "data": outlet}

    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/outlets/{outlet_id}")
async def deactivate_outlet(outlet_id: str):
    """停用档口（软删除）"""
    try:
        outlet = next((o for o in MOCK_OUTLETS if o["id"] == outlet_id and not o["is_deleted"]), None)
        if not outlet:
            raise HTTPException(status_code=404, detail=f"档口 {outlet_id} 不存在")

        outlet["is_deleted"] = True
        outlet["status"] = "inactive"
        outlet["updated_at"] = datetime.now().isoformat()

        logger.info("outlet_deactivated", outlet_id=outlet_id)
        return {"ok": True, "data": {"outlet_id": outlet_id, "status": "deactivated"}}

    except HTTPException:
        raise


# ─────────────────────────────────────────────────────────────────────────────
# 档口收银端点
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/orders")
async def create_food_court_order(req: FoodCourtOrderCreateRequest):
    """档口开单（创建含档口ID的订单）"""
    try:
        outlet = next((o for o in MOCK_OUTLETS if o["id"] == req.outlet_id and not o["is_deleted"]), None)
        if not outlet:
            raise HTTPException(status_code=404, detail=f"档口 {req.outlet_id} 不存在或已停用")

        if outlet["status"] != "active":
            raise ValueError(f"档口 {outlet['name']} 当前状态为 {outlet['status']}，无法开单")

        order_id = f"fc-order-{str(uuid.uuid4())[:8]}"
        subtotal_fen = sum(
            item.get("price_fen", 0) * item.get("qty", 1)
            for item in req.items
        )

        outlet_order_id = f"oo-{str(uuid.uuid4())[:8]}"
        outlet_order: dict = {
            "id": outlet_order_id,
            "tenant_id": "tenant-demo",
            "outlet_id": req.outlet_id,
            "order_id": order_id,
            "subtotal_fen": subtotal_fen,
            "item_count": sum(item.get("qty", 1) for item in req.items),
            "status": "pending",
            "notes": req.notes,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        _mock_outlet_orders.append(outlet_order)

        new_order: dict = {
            "id": order_id,
            "store_id": req.store_id,
            "table_no": req.table_no,
            "status": "open",
            "outlet_id": req.outlet_id,
            "outlet_name": outlet["name"],
            "items": req.items,
            "subtotal_fen": subtotal_fen,
            "total_fen": subtotal_fen,
            "outlet_orders": [outlet_order],
            "created_at": datetime.now().isoformat(),
        }
        _mock_orders[order_id] = new_order

        logger.info("food_court_order_created", order_id=order_id, outlet_id=req.outlet_id)
        return {"ok": True, "data": new_order}

    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/orders/{order_id}/add-items")
async def add_items_to_order(order_id: str, req: AddItemsRequest):
    """追加品项（可跨档口加单）"""
    try:
        order = _mock_orders.get(order_id)
        if not order:
            # fallback mock
            order = {
                "id": order_id,
                "status": "open",
                "items": [],
                "outlet_orders": [],
                "total_fen": 0,
            }
            _mock_orders[order_id] = order

        if order.get("status") not in ("open", "pending"):
            raise ValueError(f"订单 {order_id} 状态为 {order.get('status')}，无法追加品项")

        outlet = next((o for o in MOCK_OUTLETS if o["id"] == req.outlet_id and not o["is_deleted"]), None)
        if not outlet:
            raise HTTPException(status_code=404, detail=f"档口 {req.outlet_id} 不存在")

        added_subtotal = sum(
            item.get("price_fen", 0) * item.get("qty", 1)
            for item in req.items
        )
        added_count = sum(item.get("qty", 1) for item in req.items)

        # 查找该订单中是否已有该档口的outlet_order
        existing_oo = next(
            (oo for oo in _mock_outlet_orders
             if oo["order_id"] == order_id and oo["outlet_id"] == req.outlet_id),
            None,
        )
        if existing_oo:
            existing_oo["subtotal_fen"] = existing_oo["subtotal_fen"] + added_subtotal
            existing_oo["item_count"] = (existing_oo["item_count"] or 0) + added_count
            existing_oo["updated_at"] = datetime.now().isoformat()
        else:
            new_oo: dict = {
                "id": f"oo-{str(uuid.uuid4())[:8]}",
                "tenant_id": "tenant-demo",
                "outlet_id": req.outlet_id,
                "order_id": order_id,
                "subtotal_fen": added_subtotal,
                "item_count": added_count,
                "status": "pending",
                "notes": None,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            }
            _mock_outlet_orders.append(new_oo)

        # 更新主订单
        order["items"] = order.get("items", []) + [
            {**item, "outlet_id": req.outlet_id, "outlet_name": outlet["name"]}
            for item in req.items
        ]
        order["total_fen"] = order.get("total_fen", 0) + added_subtotal

        logger.info("items_added_to_order", order_id=order_id, outlet_id=req.outlet_id, count=added_count)
        return {
            "ok": True,
            "data": {
                "order_id": order_id,
                "outlet_id": req.outlet_id,
                "outlet_name": outlet["name"],
                "added_items": req.items,
                "added_subtotal_fen": added_subtotal,
                "new_total_fen": order["total_fen"],
            },
        }

    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/orders/{order_id}/checkout")
async def checkout_food_court_order(order_id: str, req: CheckoutRequest):
    """统一结算（按各档口分配金额）"""
    try:
        order = _mock_orders.get(order_id)
        if not order:
            # fallback: 模拟一笔已存在的订单
            order = {
                "id": order_id,
                "status": "open",
                "total_fen": 11200,
                "items": [
                    {"outlet_id": "out-001", "name": "招牌烤鱼", "price_fen": 6800, "qty": 1},
                    {"outlet_id": "out-002", "name": "牛肉粉", "price_fen": 1800, "qty": 1},
                    {"outlet_id": "out-003", "name": "牛肉串", "price_fen": 600, "qty": 4},
                ],
            }

        total_fen: int = order.get("total_fen", 0)
        if not total_fen:
            raise ValueError("订单金额为0，无法结算")

        # 计算找零（现金支付）
        change_fen = 0
        if req.payment_method == "cash":
            if not req.amount_tendered_fen:
                raise ValueError("现金支付必须提供实收金额")
            if req.amount_tendered_fen < total_fen:
                raise ValueError(f"实收金额 {req.amount_tendered_fen} 分不足，应收 {total_fen} 分")
            change_fen = req.amount_tendered_fen - total_fen

        # 按档口分配金额
        order_outlet_orders = [oo for oo in _mock_outlet_orders if oo["order_id"] == order_id]
        outlet_breakdown: list[dict] = []
        for oo in order_outlet_orders:
            outlet_info = next((o for o in MOCK_OUTLETS if o["id"] == oo["outlet_id"]), None)
            oo["status"] = "completed"
            oo["updated_at"] = datetime.now().isoformat()
            outlet_breakdown.append({
                "outlet_id": oo["outlet_id"],
                "outlet_name": outlet_info["name"] if outlet_info else oo["outlet_id"],
                "outlet_code": outlet_info.get("outlet_code") if outlet_info else None,
                "subtotal_fen": oo["subtotal_fen"],
                "item_count": oo["item_count"],
            })

        # 若无outlet_order记录，按items分组
        if not outlet_breakdown:
            outlet_map: dict[str, int] = {}
            for item in order.get("items", []):
                oid = item.get("outlet_id", "unknown")
                item_total = item.get("price_fen", 0) * item.get("qty", 1)
                outlet_map[oid] = outlet_map.get(oid, 0) + item_total
            for oid, sub in outlet_map.items():
                outlet_info = next((o for o in MOCK_OUTLETS if o["id"] == oid), None)
                outlet_breakdown.append({
                    "outlet_id": oid,
                    "outlet_name": outlet_info["name"] if outlet_info else oid,
                    "outlet_code": outlet_info.get("outlet_code") if outlet_info else None,
                    "subtotal_fen": sub,
                    "item_count": None,
                })

        if order_id in _mock_orders:
            _mock_orders[order_id]["status"] = "paid"

        logger.info("food_court_checkout_completed", order_id=order_id, total_fen=total_fen)
        return {
            "ok": True,
            "data": {
                "order_id": order_id,
                "total_fen": total_fen,
                "payment_method": req.payment_method,
                "amount_tendered_fen": req.amount_tendered_fen,
                "change_fen": change_fen,
                "outlet_breakdown": outlet_breakdown,
                "paid_at": datetime.now().isoformat(),
            },
        }

    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ─────────────────────────────────────────────────────────────────────────────
# 报表统计端点
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/stats/daily")
async def get_daily_stats(
    store_id: Optional[str] = Query(None, description="门店ID"),
    stat_date: Optional[date] = Query(None, description="统计日期，默认今日"),
):
    """当日档口汇总（各档口：营业额/客单数/品项数）"""
    try:
        outlets = [o for o in MOCK_OUTLETS if not o["is_deleted"]]
        if store_id:
            outlets = [o for o in outlets if o["store_id"] == store_id]

        target_date = stat_date or date.today()

        stats: list[dict] = []
        total_revenue = 0
        total_orders = 0

        for outlet in outlets:
            revenue = outlet.get("today_revenue_fen", 0)
            order_count = outlet.get("today_order_count", 0)
            avg_order = revenue // order_count if order_count > 0 else 0
            total_revenue += revenue
            total_orders += order_count

            stats.append({
                "outlet_id": outlet["id"],
                "outlet_name": outlet["name"],
                "outlet_code": outlet.get("outlet_code"),
                "location": outlet.get("location"),
                "revenue_fen": revenue,
                "order_count": order_count,
                "avg_order_fen": avg_order,
                "item_count": order_count * 3,  # mock: 平均3个品项/单
                "status": outlet["status"],
            })

        return {
            "ok": True,
            "data": {
                "stat_date": str(target_date),
                "store_id": store_id,
                "total_revenue_fen": total_revenue,
                "total_order_count": total_orders,
                "outlet_count": len(stats),
                "outlets": stats,
            },
        }
    except (KeyError, TypeError) as exc:
        logger.error("daily_stats_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/stats/compare")
async def get_outlet_compare(
    store_id: Optional[str] = Query(None, description="门店ID"),
    start_date: Optional[date] = Query(None, description="开始日期"),
    end_date: Optional[date] = Query(None, description="结束日期"),
    outlet_ids: Optional[str] = Query(None, description="档口ID列表，逗号分隔"),
):
    """档口对比报表（支持日期范围，多档口营业额对比）"""
    try:
        outlets = [o for o in MOCK_OUTLETS if not o["is_deleted"]]
        if store_id:
            outlets = [o for o in outlets if o["store_id"] == store_id]

        # 过滤指定档口
        if outlet_ids:
            id_list = [oid.strip() for oid in outlet_ids.split(",")]
            outlets = [o for o in outlets if o["id"] in id_list]

        _start = start_date or date.today()
        _end = end_date or date.today()

        # Mock: 生成7天的趋势数据
        from datetime import timedelta
        days = (_end - _start).days + 1
        days = min(days, 30)  # 最多30天

        trend_data: list[dict] = []
        for i in range(days):
            day = _start + timedelta(days=i)
            day_data: dict = {"date": str(day)}
            for outlet in outlets:
                base = outlet.get("today_revenue_fen", 100000)
                # 模拟波动（周末高峰）
                weekday = day.weekday()
                multiplier = 1.3 if weekday >= 5 else 1.0
                simulated = int(base * multiplier * (0.8 + (i % 5) * 0.08))
                day_data[outlet["id"]] = {
                    "revenue_fen": simulated,
                    "order_count": int(simulated / (base // max(outlet.get("today_order_count", 1), 1))),
                    "outlet_name": outlet["name"],
                }
            trend_data.append(day_data)

        compare_summary: list[dict] = []
        for outlet in outlets:
            total_rev = sum(
                d[outlet["id"]]["revenue_fen"]
                for d in trend_data
                if outlet["id"] in d
            )
            total_ord = sum(
                d[outlet["id"]]["order_count"]
                for d in trend_data
                if outlet["id"] in d
            )
            compare_summary.append({
                "outlet_id": outlet["id"],
                "outlet_name": outlet["name"],
                "outlet_code": outlet.get("outlet_code"),
                "total_revenue_fen": total_rev,
                "total_order_count": total_ord,
                "avg_daily_revenue_fen": total_rev // days if days > 0 else 0,
            })

        return {
            "ok": True,
            "data": {
                "start_date": str(_start),
                "end_date": str(_end),
                "days": days,
                "outlets": compare_summary,
                "trend": trend_data,
            },
        }
    except (KeyError, TypeError, ZeroDivisionError) as exc:
        logger.error("outlet_compare_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ─────────────────────────────────────────────────────────────────────────────
# 商户别名端点（/merchants 别名 → /outlets，保持 API 语义一致）
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/merchants")
async def list_merchants(
    store_id: Optional[str] = Query(None, description="按门店过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    """获取商户（档口）列表（含当日营业额）—— /outlets 的语义别名。"""
    return await list_outlets(store_id=store_id, status=status, page=page, size=size)


@router.post("/merchants")
async def create_merchant(req: OutletCreateRequest):
    """新建档口商户 —— /outlets POST 的语义别名。"""
    return await create_outlet(req=req)


@router.put("/merchants/{merchant_id}")
async def update_merchant(merchant_id: str, req: OutletUpdateRequest):
    """更新档口商户信息 —— /outlets PUT 的语义别名。"""
    return await update_outlet(outlet_id=merchant_id, req=req)


# ─────────────────────────────────────────────────────────────────────────────
# 日结结算端点
# ─────────────────────────────────────────────────────────────────────────────

class SettlementSplitRequest(BaseModel):
    store_id: str = Field(..., description="门店ID")
    settlement_date: Optional[date] = Field(None, description="结算日期，默认今日")
    outlet_ids: Optional[list[str]] = Field(None, description="指定档口ID列表，默认全部")


@router.get("/settlement/daily")
async def get_daily_settlement(
    store_id: Optional[str] = Query(None, description="门店ID"),
    settlement_date: Optional[date] = Query(None, description="结算日期，默认今日"),
):
    """按档口拆分日结（各商户营业额/订单数/应结金额）。"""
    try:
        outlets = [o for o in MOCK_OUTLETS if not o["is_deleted"]]
        if store_id:
            outlets = [o for o in outlets if o["store_id"] == store_id]

        target_date = settlement_date or date.today()

        settlement_items: list[dict] = []
        total_revenue = 0
        total_orders = 0
        total_settlement = 0

        for outlet in outlets:
            revenue = outlet.get("today_revenue_fen", 0)
            order_count = outlet.get("today_order_count", 0)
            ratio = float(outlet.get("settlement_ratio", "1.0"))
            settlement_amount = int(revenue * ratio)

            total_revenue += revenue
            total_orders += order_count
            total_settlement += settlement_amount

            settlement_items.append({
                "outlet_id": outlet["id"],
                "outlet_name": outlet["name"],
                "outlet_code": outlet.get("outlet_code"),
                "location": outlet.get("location"),
                "owner_name": outlet.get("owner_name"),
                "revenue_fen": revenue,
                "order_count": order_count,
                "avg_order_fen": revenue // order_count if order_count > 0 else 0,
                "settlement_ratio": ratio,
                "settlement_amount_fen": settlement_amount,
                "status": outlet["status"],
            })

        return {
            "ok": True,
            "data": {
                "settlement_date": str(target_date),
                "store_id": store_id,
                "total_revenue_fen": total_revenue,
                "total_order_count": total_orders,
                "total_settlement_fen": total_settlement,
                "outlet_count": len(settlement_items),
                "outlets": settlement_items,
            },
        }
    except (KeyError, TypeError, ZeroDivisionError) as exc:
        logger.error("daily_settlement_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/settlement/split")
async def settlement_split(req: SettlementSplitRequest):
    """日结时按商户分账汇总（生成各档口结算单）。"""
    try:
        target_date = req.settlement_date or date.today()

        outlets = [o for o in MOCK_OUTLETS if not o["is_deleted"]]
        if req.outlet_ids:
            outlets = [o for o in outlets if o["id"] in req.outlet_ids]

        split_results: list[dict] = []
        grand_total_fen = 0

        for outlet in outlets:
            revenue = outlet.get("today_revenue_fen", 0)
            order_count = outlet.get("today_order_count", 0)
            ratio = float(outlet.get("settlement_ratio", "1.0"))
            settlement_amount = int(revenue * ratio)
            platform_fee = int(revenue * 0.005)  # 模拟 0.5% 平台服务费
            net_payout = settlement_amount - platform_fee

            grand_total_fen += net_payout

            split_results.append({
                "outlet_id": outlet["id"],
                "outlet_name": outlet["name"],
                "outlet_code": outlet.get("outlet_code"),
                "owner_name": outlet.get("owner_name"),
                "owner_phone": outlet.get("owner_phone"),
                "settlement_date": str(target_date),
                "revenue_fen": revenue,
                "order_count": order_count,
                "settlement_ratio": ratio,
                "gross_settlement_fen": settlement_amount,
                "platform_fee_fen": platform_fee,
                "net_payout_fen": net_payout,
                "status": "settled",
                "settled_at": datetime.now().isoformat(),
            })

        logger.info(
            "settlement_split_completed",
            store_id=req.store_id,
            outlet_count=len(split_results),
            grand_total_fen=grand_total_fen,
            date=str(target_date),
        )

        return {
            "ok": True,
            "data": {
                "store_id": req.store_id,
                "settlement_date": str(target_date),
                "outlet_count": len(split_results),
                "grand_total_payout_fen": grand_total_fen,
                "split_details": split_results,
                "generated_at": datetime.now().isoformat(),
            },
        }
    except (KeyError, TypeError) as exc:
        logger.error("settlement_split_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/orders")
async def list_outlet_orders(
    outlet_id: Optional[str] = Query(None, description="按档口过滤"),
    order_date: Optional[date] = Query(None, description="按日期过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    """档口订单查询（支持outlet_id/date/status过滤，分页）"""
    try:
        items = list(_mock_outlet_orders)

        if outlet_id:
            items = [oo for oo in items if oo["outlet_id"] == outlet_id]

        if status:
            items = [oo for oo in items if oo["status"] == status]

        # 日期过滤（简单匹配created_at前10字符）
        if order_date:
            date_str = str(order_date)
            items = [oo for oo in items if oo["created_at"][:10] == date_str]

        # 补充档口名称
        enriched: list[dict] = []
        for oo in items:
            outlet_info = next((o for o in MOCK_OUTLETS if o["id"] == oo["outlet_id"]), None)
            enriched.append({
                **oo,
                "outlet_name": outlet_info["name"] if outlet_info else oo["outlet_id"],
                "outlet_code": outlet_info.get("outlet_code") if outlet_info else None,
            })

        total = len(enriched)
        start = (page - 1) * size
        paginated = enriched[start: start + size]

        return {
            "ok": True,
            "data": {
                "items": paginated,
                "total": total,
                "page": page,
                "size": size,
            },
        }
    except (KeyError, IndexError) as exc:
        logger.error("list_outlet_orders_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
