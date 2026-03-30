"""大厨到家服务 — 徐记海鲜高端到家业务

全流程: 选菜 → 选厨师 → 选时间 → 上门 → 烹饪 → 评价

所有金额单位：分（fen）。
服务费阶梯：4人以下60000分, 4-8人80000分, 8人以上120000分。
厨师状态：available / booked / on_service / off_duty。
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# ─── 内存存储（MVP阶段，后续迁移到 PostgreSQL） ───

_bookings: dict[str, dict] = {}
_chefs: dict[str, dict] = {}
_ratings: dict[str, list[dict]] = {}
_chef_schedules: dict[str, list[dict]] = {}


def _gen_id() -> str:
    return uuid.uuid4().hex[:12].upper()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── 服务费阶梯（分） ───

SERVICE_FEE_TIERS = [
    (4, 60000),    # 4人以下: 600元
    (8, 80000),    # 4-8人: 800元
    (999, 120000), # 8人以上: 1200元
]

# 食材费基数（分/人），实际应从菜品BOM计算
_DEFAULT_INGREDIENT_FEE_PER_GUEST_FEN = 15000  # 150元/人

# 交通费（分/公里）
_TRANSPORT_FEE_PER_KM_FEN = 500  # 5元/公里

CHEF_STATUSES = ("available", "booked", "on_service", "off_duty")

BOOKING_STATUSES = (
    "pending", "confirmed", "chef_departed", "chef_arrived",
    "cooking", "completed", "cancelled", "rated",
)


def _calc_service_fee_fen(guest_count: int) -> int:
    """按人数阶梯计算服务费（分）"""
    for threshold, fee in SERVICE_FEE_TIERS:
        if guest_count < threshold:
            return fee
    return SERVICE_FEE_TIERS[-1][1]


# ─── 初始化示例厨师数据 ───

def _ensure_sample_chefs(tenant_id: str) -> None:
    """确保有示例厨师数据（仅开发用）"""
    if any(c["tenant_id"] == tenant_id for c in _chefs.values()):
        return
    samples = [
        {
            "name": "王大厨", "title": "行政总厨",
            "cuisine_types": ["湘菜", "海鲜"],
            "specialties": ["剁椒鱼头", "清蒸龙虾", "蒜蓉粉丝蒸扇贝"],
            "years_experience": 18, "rating": 4.9, "total_services": 326,
            "avatar": "/static/chef-wang.jpg", "area": "长沙",
            "status": "available",
        },
        {
            "name": "李师傅", "title": "金牌厨师",
            "cuisine_types": ["粤菜", "海鲜"],
            "specialties": ["白灼海虾", "蒸石斑", "避风塘炒蟹"],
            "years_experience": 12, "rating": 4.8, "total_services": 218,
            "avatar": "/static/chef-li.jpg", "area": "长沙",
            "status": "available",
        },
        {
            "name": "陈大厨", "title": "资深厨师",
            "cuisine_types": ["湘菜", "川菜"],
            "specialties": ["口味虾", "辣椒炒肉", "水煮鱼"],
            "years_experience": 15, "rating": 4.7, "total_services": 189,
            "avatar": "/static/chef-chen.jpg", "area": "长沙",
            "status": "available",
        },
    ]
    for s in samples:
        chef_id = _gen_id()
        _chefs[chef_id] = {
            "id": chef_id,
            "tenant_id": tenant_id,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "is_deleted": False,
            "portfolio": [],
            **s,
        }


# ═══════════════════════════════════════════════════════════
# 核心业务函数
# ═══════════════════════════════════════════════════════════


async def create_booking(
    customer_id: str,
    dishes: list[dict],
    chef_id: str,
    service_datetime: str,
    address: str,
    guest_count: int,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """创建大厨到家预约

    Args:
        customer_id: 顾客ID
        dishes: 菜品列表 [{"dish_id": str, "name": str, "quantity": int, "price_fen": int}, ...]
        chef_id: 厨师ID
        service_datetime: 服务时间 ISO 格式
        address: 上门地址
        guest_count: 用餐人数
        tenant_id: 租户ID
        db: 数据库会话
    """
    _ensure_sample_chefs(tenant_id)

    if guest_count < 1:
        raise ValueError("用餐人数不能小于1")
    if not dishes:
        raise ValueError("至少选择一道菜品")
    if chef_id not in _chefs:
        raise ValueError("厨师不存在")

    chef = _chefs[chef_id]
    if chef["tenant_id"] != tenant_id:
        raise ValueError("厨师不存在")
    if chef["status"] != "available":
        raise ValueError(f"厨师当前不可预约，状态: {chef['status']}")

    # 计算价格（默认距离10km）
    price = await calculate_price(dishes, guest_count, 10.0, tenant_id, db)

    booking_id = _gen_id()
    booking = {
        "id": booking_id,
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "chef_id": chef_id,
        "chef_name": chef["name"],
        "dishes": dishes,
        "service_datetime": service_datetime,
        "address": address,
        "guest_count": guest_count,
        "status": "pending",
        "price_detail": price,
        "total_fen": price["total_fen"],
        "payment_id": None,
        "photos": [],
        "rating": None,
        "comment": None,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "is_deleted": False,
    }
    _bookings[booking_id] = booking

    logger.info(
        "chef_at_home.booking_created",
        tenant_id=tenant_id,
        booking_id=booking_id,
        chef_id=chef_id,
        guest_count=guest_count,
        total_fen=price["total_fen"],
    )
    return booking


async def list_available_chefs(
    date: str,
    area: str,
    cuisine_type: Optional[str],
    tenant_id: str,
    db: AsyncSession,
) -> list[dict]:
    """查询指定日期、区域可用的厨师列表"""
    _ensure_sample_chefs(tenant_id)

    results = []
    for chef in _chefs.values():
        if chef["tenant_id"] != tenant_id:
            continue
        if chef["is_deleted"]:
            continue
        if chef["status"] not in ("available",):
            continue
        if area and chef.get("area", "") != area:
            continue
        if cuisine_type and cuisine_type not in chef.get("cuisine_types", []):
            continue

        # 检查日期是否有排期冲突
        schedule = _chef_schedules.get(chef["id"], [])
        has_conflict = any(s["date"] == date and s["status"] != "cancelled" for s in schedule)
        if has_conflict:
            continue

        results.append({
            "id": chef["id"],
            "name": chef["name"],
            "title": chef["title"],
            "cuisine_types": chef["cuisine_types"],
            "specialties": chef["specialties"],
            "years_experience": chef["years_experience"],
            "rating": chef["rating"],
            "total_services": chef["total_services"],
            "avatar": chef["avatar"],
        })

    logger.info(
        "chef_at_home.chefs_listed",
        tenant_id=tenant_id,
        date=date,
        area=area,
        cuisine_type=cuisine_type,
        count=len(results),
    )
    return results


async def get_chef_profile(
    chef_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """获取厨师详细档案（擅长菜系/评分/作品集）"""
    _ensure_sample_chefs(tenant_id)

    if chef_id not in _chefs:
        raise ValueError("厨师不存在")
    chef = _chefs[chef_id]
    if chef["tenant_id"] != tenant_id:
        raise ValueError("厨师不存在")

    # 获取该厨师的评价列表
    chef_ratings = _ratings.get(chef_id, [])
    recent_ratings = sorted(chef_ratings, key=lambda r: r["created_at"], reverse=True)[:10]

    profile = {
        "id": chef["id"],
        "name": chef["name"],
        "title": chef["title"],
        "cuisine_types": chef["cuisine_types"],
        "specialties": chef["specialties"],
        "years_experience": chef["years_experience"],
        "rating": chef["rating"],
        "total_services": chef["total_services"],
        "avatar": chef["avatar"],
        "portfolio": chef.get("portfolio", []),
        "recent_ratings": recent_ratings,
        "status": chef["status"],
    }

    logger.info("chef_at_home.profile_viewed", tenant_id=tenant_id, chef_id=chef_id)
    return profile


async def calculate_price(
    dishes: list[dict],
    guest_count: int,
    distance_km: float,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """计算大厨到家价格（菜品费 + 服务费 + 食材费 + 交通费）

    所有金额单位：分（fen）
    """
    # 菜品费
    dish_total_fen = 0
    for dish in dishes:
        price_fen = dish.get("price_fen", 0)
        quantity = dish.get("quantity", 1)
        dish_total_fen += price_fen * quantity

    # 服务费（按人数阶梯）
    service_fee_fen = _calc_service_fee_fen(guest_count)

    # 食材费（按人数）
    ingredient_fee_fen = _DEFAULT_INGREDIENT_FEE_PER_GUEST_FEN * guest_count

    # 交通费（按距离）
    transport_fee_fen = int(distance_km * _TRANSPORT_FEE_PER_KM_FEN)

    total_fen = dish_total_fen + service_fee_fen + ingredient_fee_fen + transport_fee_fen

    logger.info(
        "chef_at_home.price_calculated",
        tenant_id=tenant_id,
        dish_total_fen=dish_total_fen,
        service_fee_fen=service_fee_fen,
        ingredient_fee_fen=ingredient_fee_fen,
        transport_fee_fen=transport_fee_fen,
        total_fen=total_fen,
    )

    return {
        "dish_total_fen": dish_total_fen,
        "service_fee_fen": service_fee_fen,
        "ingredient_fee_fen": ingredient_fee_fen,
        "transport_fee_fen": transport_fee_fen,
        "total_fen": total_fen,
        "guest_count": guest_count,
        "distance_km": distance_km,
    }


async def confirm_booking(
    booking_id: str,
    payment_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """确认预约（关联支付单）"""
    booking = _bookings.get(booking_id)
    if not booking or booking["tenant_id"] != tenant_id:
        raise ValueError("预约不存在")
    if booking["status"] != "pending":
        raise ValueError(f"预约状态不允许确认，当前: {booking['status']}")

    booking["status"] = "confirmed"
    booking["payment_id"] = payment_id
    booking["updated_at"] = _now_iso()

    # 更新厨师状态
    chef = _chefs.get(booking["chef_id"])
    if chef:
        chef["status"] = "booked"
        chef["updated_at"] = _now_iso()

    # 记录排期
    schedule_entry = {
        "booking_id": booking_id,
        "date": booking["service_datetime"][:10],
        "status": "confirmed",
    }
    _chef_schedules.setdefault(booking["chef_id"], []).append(schedule_entry)

    logger.info(
        "chef_at_home.booking_confirmed",
        tenant_id=tenant_id,
        booking_id=booking_id,
        payment_id=payment_id,
    )
    return booking


async def start_service(
    booking_id: str,
    chef_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """开始服务（厨师签到）"""
    booking = _bookings.get(booking_id)
    if not booking or booking["tenant_id"] != tenant_id:
        raise ValueError("预约不存在")
    if booking["chef_id"] != chef_id:
        raise ValueError("厨师ID不匹配")
    if booking["status"] != "confirmed":
        raise ValueError(f"预约状态不允许开始服务，当前: {booking['status']}")

    booking["status"] = "cooking"
    booking["service_started_at"] = _now_iso()
    booking["updated_at"] = _now_iso()

    chef = _chefs.get(chef_id)
    if chef:
        chef["status"] = "on_service"
        chef["updated_at"] = _now_iso()

    logger.info(
        "chef_at_home.service_started",
        tenant_id=tenant_id,
        booking_id=booking_id,
        chef_id=chef_id,
    )
    return booking


async def complete_service(
    booking_id: str,
    photos: list[str],
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """完成服务（上传出品照片）"""
    booking = _bookings.get(booking_id)
    if not booking or booking["tenant_id"] != tenant_id:
        raise ValueError("预约不存在")
    if booking["status"] != "cooking":
        raise ValueError(f"预约状态不允许完成服务，当前: {booking['status']}")

    booking["status"] = "completed"
    booking["photos"] = photos
    booking["service_completed_at"] = _now_iso()
    booking["updated_at"] = _now_iso()

    # 厨师恢复可用
    chef = _chefs.get(booking["chef_id"])
    if chef:
        chef["status"] = "available"
        chef["updated_at"] = _now_iso()
        chef["total_services"] = chef.get("total_services", 0) + 1

    logger.info(
        "chef_at_home.service_completed",
        tenant_id=tenant_id,
        booking_id=booking_id,
        photo_count=len(photos),
    )
    return booking


async def rate_service(
    booking_id: str,
    rating: int,
    comment: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """评价服务"""
    booking = _bookings.get(booking_id)
    if not booking or booking["tenant_id"] != tenant_id:
        raise ValueError("预约不存在")
    if booking["status"] != "completed":
        raise ValueError(f"预约状态不允许评价，当前: {booking['status']}")
    if rating < 1 or rating > 5:
        raise ValueError("评分范围: 1-5")

    booking["rating"] = rating
    booking["comment"] = comment
    booking["status"] = "rated"
    booking["updated_at"] = _now_iso()

    # 记录评价
    rating_record = {
        "booking_id": booking_id,
        "chef_id": booking["chef_id"],
        "customer_id": booking["customer_id"],
        "rating": rating,
        "comment": comment,
        "created_at": _now_iso(),
    }
    _ratings.setdefault(booking["chef_id"], []).append(rating_record)

    # 更新厨师平均评分
    chef = _chefs.get(booking["chef_id"])
    if chef:
        all_ratings = _ratings.get(booking["chef_id"], [])
        if all_ratings:
            avg = sum(r["rating"] for r in all_ratings) / len(all_ratings)
            chef["rating"] = round(avg, 1)
            chef["updated_at"] = _now_iso()

    logger.info(
        "chef_at_home.service_rated",
        tenant_id=tenant_id,
        booking_id=booking_id,
        rating=rating,
    )
    return booking


async def get_booking_history(
    customer_id: str,
    tenant_id: str,
    db: AsyncSession,
    page: int = 1,
    size: int = 20,
) -> dict:
    """获取顾客预约历史"""
    all_bookings = [
        b for b in _bookings.values()
        if b["tenant_id"] == tenant_id
        and b["customer_id"] == customer_id
        and not b["is_deleted"]
    ]
    all_bookings.sort(key=lambda b: b["created_at"], reverse=True)

    total = len(all_bookings)
    start = (page - 1) * size
    items = all_bookings[start:start + size]

    logger.info(
        "chef_at_home.history_listed",
        tenant_id=tenant_id,
        customer_id=customer_id,
        total=total,
        page=page,
    )
    return {"items": items, "total": total, "page": page, "size": size}


async def get_chef_schedule(
    chef_id: str,
    month: str,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    """获取厨师排期（按月）

    Args:
        chef_id: 厨师ID
        month: 月份 "YYYY-MM"
        tenant_id: 租户ID
        db: 数据库会话
    """
    _ensure_sample_chefs(tenant_id)

    if chef_id not in _chefs:
        raise ValueError("厨师不存在")
    chef = _chefs[chef_id]
    if chef["tenant_id"] != tenant_id:
        raise ValueError("厨师不存在")

    schedule = _chef_schedules.get(chef_id, [])
    month_entries = [s for s in schedule if s["date"].startswith(month)]

    # 生成该月所有日期的可用状态
    year, mon = int(month.split("-")[0]), int(month.split("-")[1])
    if mon == 12:
        next_month_first = datetime(year + 1, 1, 1)
    else:
        next_month_first = datetime(year, mon + 1, 1)
    days_in_month = (next_month_first - datetime(year, mon, 1)).days

    booked_dates = {s["date"] for s in month_entries if s["status"] != "cancelled"}
    calendar = []
    for day in range(1, days_in_month + 1):
        date_str = f"{month}-{day:02d}"
        calendar.append({
            "date": date_str,
            "available": date_str not in booked_dates,
        })

    logger.info(
        "chef_at_home.schedule_viewed",
        tenant_id=tenant_id,
        chef_id=chef_id,
        month=month,
        booked_count=len(booked_dates),
    )
    return {
        "chef_id": chef_id,
        "month": month,
        "calendar": calendar,
        "booked_dates": list(booked_dates),
    }
