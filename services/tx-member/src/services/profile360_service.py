"""360° 会员画像聚合服务 — 为企微侧边栏提供一站式数据

从 customers / orders / order_items / dishes / stored_value_accounts /
member_points_balance / coupons / member_level_configs / coupon_send_logs
等多张表聚合数据, 生成完整的客户画像供导购使用.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


def _mask_phone(phone: Optional[str]) -> Optional[str]:
    """手机号脱敏: 138****1234"""
    if not phone or len(phone) < 7:
        return phone
    return phone[:3] + "****" + phone[-4:]


def _safe_iso(val: object) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, date):
        return val.isoformat()
    return str(val)


def _birthday_coming(birth_date: Optional[date], today: Optional[date] = None) -> bool:
    """判断7天内是否生日"""
    if not birth_date:
        return False
    today = today or date.today()
    this_year_bday = birth_date.replace(year=today.year)
    if this_year_bday < today:
        this_year_bday = birth_date.replace(year=today.year + 1)
    return (this_year_bday - today).days <= 7


class Profile360Service:
    """360° 会员画像聚合服务 — 为企微侧边栏提供一站式数据"""

    # ─── 核心画像查询 ──────────────────────────────────────────

    async def get_full_profile(
        self,
        tenant_id: str,
        customer_id: str,
        db: AsyncSession,
    ) -> Optional[dict]:
        """通过 customer_id 查询完整 360° 画像"""
        log = logger.bind(tenant_id=tenant_id, customer_id=customer_id)

        # 1. 基础信息
        member = await self._fetch_member(tenant_id, customer_id, db)
        if member is None:
            log.info("profile360_member_not_found")
            return None

        # 2-9 并行聚合(实际按序执行, 每个都是轻量查询)
        consumption = await self._fetch_consumption(tenant_id, customer_id, db)
        recent_30d = await self._fetch_recent_30d(tenant_id, customer_id, db)
        frequent_store = await self._fetch_frequent_store(tenant_id, customer_id, db)
        dish_prefs = await self._fetch_dish_preferences(tenant_id, customer_id, db)
        stored_value = await self._fetch_stored_value(tenant_id, customer_id, db)
        points = await self._fetch_points(tenant_id, customer_id, db)
        member_card = await self._fetch_member_card(tenant_id, customer_id, db)
        available_coupons = await self._fetch_available_coupons(tenant_id, customer_id, db)
        coupon_sends = await self._fetch_recent_coupon_sends(tenant_id, customer_id, db)

        # 组装画像
        birth = member.get("birth_date")
        bd_coming = _birthday_coming(birth)

        last_order_at = consumption.get("last_order_at")
        last_order_days = None
        if last_order_at:
            last_order_days = (datetime.now(tz=timezone.utc) - last_order_at).days

        # 推算消费间隔
        total_count = consumption.get("total_count", 0)
        first_order_at = member.get("first_order_at")
        avg_interval_days = None
        if total_count > 1 and first_order_at and last_order_at:
            span = (last_order_at - first_order_at).days
            avg_interval_days = round(span / (total_count - 1), 1)

        # 时段偏好
        time_preference = await self._fetch_time_preference(tenant_id, customer_id, db)

        # 口味标签(从 tags 中提取口味类)
        tags = member.get("tags") or []
        taste_tags = [t for t in tags if any(k in t for k in ["辣", "甜", "酸", "咸", "海鲜", "素", "清淡", "重口", "尝新"])]
        scene_tags = [t for t in tags if any(k in t for k in ["商务", "家庭", "约会", "朋友", "聚餐", "宴请", "独食"])]
        other_tags = [t for t in tags if t not in taste_tags and t not in scene_tags]

        profile = {
            # 基础信息
            "customer_id": customer_id,
            "display_name": member.get("display_name"),
            "phone": _mask_phone(member.get("primary_phone")),
            "wechat_avatar_url": member.get("wechat_avatar_url"),
            "wechat_nickname": member.get("wechat_nickname"),
            "gender": member.get("gender"),
            "birthday": _safe_iso(birth),
            "birthday_coming": bd_coming,
            "member_since": _safe_iso(member.get("created_at")),
            "member_level": member.get("rfm_level"),
            "wecom_external_userid": member.get("wecom_external_userid"),
            "wecom_remark": member.get("wecom_remark"),
            "channel_source": member.get("source"),
            # RFM
            "rfm_level": member.get("rfm_level"),
            "r_score": member.get("r_score"),
            "f_score": member.get("f_score"),
            "m_score": member.get("m_score"),
            "risk_score": member.get("risk_score"),
            # 消费洞察
            "consumption": {
                "total_amount_fen": consumption.get("total_amount_fen", 0),
                "total_count": total_count,
                "avg_amount_fen": consumption.get("avg_amount_fen", 0),
                "max_amount_fen": consumption.get("max_amount_fen"),
                "min_amount_fen": consumption.get("min_amount_fen"),
                "last_order_at": _safe_iso(last_order_at),
                "last_order_days": last_order_days,
                "last_store_name": consumption.get("last_store_name"),
                "frequent_store": frequent_store,
                "avg_interval_days": avg_interval_days,
                "recent_30d_count": recent_30d.get("count", 0),
                "recent_30d_amount_fen": recent_30d.get("amount_fen", 0),
            },
            # 菜品偏好 Top5
            "dish_preferences": dish_prefs,
            # 口味标签
            "taste_tags": taste_tags,
            # 消费时段偏好
            "time_preference": time_preference,
            # 储值
            "stored_value": stored_value,
            # 积分
            "points": points,
            # 会员卡
            "member_card": member_card,
            # 可用券
            "available_coupons": available_coupons,
            "available_coupon_count": len(available_coupons),
            # 标签
            "tags": other_tags,
            "scene_tags": scene_tags,
            # 发券记录
            "recent_coupon_sends": coupon_sends,
            # 话术
            "greeting_hint": "",
        }

        # 生成话术建议
        profile["greeting_hint"] = self._generate_greeting_hint(profile)

        log.info("profile360_assembled", customer_id=customer_id)
        return profile

    # ─── 多入口查询 ──────────────────────────────────────────

    async def get_profile_by_phone(
        self, tenant_id: str, phone: str, db: AsyncSession
    ) -> Optional[dict]:
        """通过手机号查询(到店场景: 前台输入手机号)"""
        result = await db.execute(
            text(
                "SELECT id::text FROM customers"
                " WHERE tenant_id = :tid AND primary_phone = :phone"
                " AND is_deleted = false AND is_merged = false"
                " LIMIT 1"
            ),
            {"tid": tenant_id, "phone": phone},
        )
        row = result.first()
        if not row:
            return None
        return await self.get_full_profile(tenant_id, str(row[0]), db)

    async def get_profile_by_wecom(
        self, tenant_id: str, wecom_external_userid: str, db: AsyncSession
    ) -> Optional[dict]:
        """通过企微 external_userid 查询(侧边栏场景)"""
        result = await db.execute(
            text(
                "SELECT id::text FROM customers"
                " WHERE tenant_id = :tid AND wecom_external_userid = :eid"
                " AND is_deleted = false AND is_merged = false"
                " LIMIT 1"
            ),
            {"tid": tenant_id, "eid": wecom_external_userid},
        )
        row = result.first()
        if not row:
            return None
        return await self.get_full_profile(tenant_id, str(row[0]), db)

    async def get_profile_by_card(
        self, tenant_id: str, card_no: str, db: AsyncSession
    ) -> Optional[dict]:
        """通过会员卡号查询(扫码场景)

        查 member_level_history 或 customers.extra->'card_no' 定位客户.
        回退策略: 尝试 primary_phone 匹配.
        """
        # 尝试 extra->card_no
        result = await db.execute(
            text(
                "SELECT id::text FROM customers"
                " WHERE tenant_id = :tid"
                " AND extra->>'card_no' = :card_no"
                " AND is_deleted = false AND is_merged = false"
                " LIMIT 1"
            ),
            {"tid": tenant_id, "card_no": card_no},
        )
        row = result.first()
        if not row:
            return None
        return await self.get_full_profile(tenant_id, str(row[0]), db)

    # ─── 消费明细(分页) ──────────────────────────────────────

    async def get_consumption_detail(
        self,
        tenant_id: str,
        customer_id: str,
        page: int,
        size: int,
        db: AsyncSession,
    ) -> dict:
        """消费明细: 最近 N 笔订单详情(分页)"""
        offset = (page - 1) * size

        count_result = await db.execute(
            text(
                "SELECT COUNT(*) FROM orders"
                " WHERE tenant_id = :tid AND customer_id = :cid"
                " AND status = 'completed' AND is_deleted = false"
            ),
            {"tid": tenant_id, "cid": customer_id},
        )
        total = count_result.scalar() or 0

        rows_result = await db.execute(
            text(
                "SELECT o.id, o.order_no, o.store_id, s.store_name,"
                " o.total_amount_fen, o.final_amount_fen,"
                " o.discount_amount_fen, o.order_type, o.order_time, o.guest_count"
                " FROM orders o"
                " LEFT JOIN stores s ON s.id = o.store_id AND s.tenant_id = o.tenant_id"
                " WHERE o.tenant_id = :tid AND o.customer_id = :cid"
                " AND o.status = 'completed' AND o.is_deleted = false"
                " ORDER BY o.order_time DESC"
                " LIMIT :limit OFFSET :offset"
            ),
            {"tid": tenant_id, "cid": customer_id, "limit": size, "offset": offset},
        )
        items = [
            {
                "order_id": str(r["id"]),
                "order_no": r["order_no"],
                "store_id": str(r["store_id"]) if r["store_id"] else None,
                "store_name": r["store_name"],
                "total_amount_fen": r["total_amount_fen"],
                "final_amount_fen": r["final_amount_fen"],
                "discount_amount_fen": r["discount_amount_fen"],
                "order_type": r["order_type"],
                "order_time": _safe_iso(r["order_time"]),
                "guest_count": r["guest_count"],
            }
            for r in rows_result.mappings()
        ]
        return {"items": items, "total": total, "page": page, "size": size}

    # ─── 菜品偏好详情(全量) ──────────────────────────────────

    async def get_dish_preferences_full(
        self,
        tenant_id: str,
        customer_id: str,
        db: AsyncSession,
    ) -> list[dict]:
        """菜品偏好全量(不限 Top5)"""
        total_result = await db.execute(
            text(
                "SELECT COUNT(*) FROM order_items oi"
                " JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id"
                " WHERE oi.tenant_id = :tid AND o.customer_id = :cid"
                " AND o.status = 'completed' AND o.is_deleted = false"
            ),
            {"tid": tenant_id, "cid": customer_id},
        )
        total_items = total_result.scalar() or 1

        result = await db.execute(
            text(
                "SELECT oi.dish_name, COUNT(*) as order_times"
                " FROM order_items oi"
                " JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id"
                " WHERE oi.tenant_id = :tid AND o.customer_id = :cid"
                " AND o.status = 'completed' AND o.is_deleted = false"
                " GROUP BY oi.dish_name"
                " ORDER BY order_times DESC"
                " LIMIT 50"
            ),
            {"tid": tenant_id, "cid": customer_id},
        )
        return [
            {
                "dish_name": r["dish_name"],
                "order_times": r["order_times"],
                "percentage": round(r["order_times"] / total_items, 2),
            }
            for r in result.mappings()
        ]

    # ─── 可用券列表 ──────────────────────────────────────────

    async def get_customer_coupons(
        self,
        tenant_id: str,
        customer_id: str,
        db: AsyncSession,
    ) -> list[dict]:
        """客户可用券完整列表"""
        return await self._fetch_available_coupons(tenant_id, customer_id, db, limit=100)

    # ─── 发券操作 ──────────────────────────────────────────

    async def record_coupon_send(
        self,
        tenant_id: str,
        send_data: dict,
        db: AsyncSession,
    ) -> dict:
        """记录 1v1 发券"""
        log = logger.bind(tenant_id=tenant_id, employee_id=send_data.get("employee_id"))
        send_id = str(uuid.uuid4())
        now = datetime.now(tz=timezone.utc)

        await db.execute(
            text(
                "INSERT INTO coupon_send_logs"
                " (id, tenant_id, store_id, employee_id, customer_id,"
                "  coupon_batch_id, coupon_instance_id, coupon_name, discount_desc,"
                "  channel, send_status, sent_at, created_at, updated_at)"
                " VALUES"
                " (:id, :tid, :store_id, :employee_id, :customer_id,"
                "  :coupon_batch_id, :coupon_instance_id, :coupon_name, :discount_desc,"
                "  :channel, 'sent', :sent_at, :sent_at, :sent_at)"
            ),
            {
                "id": send_id,
                "tid": tenant_id,
                "store_id": send_data.get("store_id"),
                "employee_id": send_data["employee_id"],
                "customer_id": send_data["customer_id"],
                "coupon_batch_id": send_data.get("coupon_batch_id"),
                "coupon_instance_id": send_data.get("coupon_instance_id"),
                "coupon_name": send_data.get("coupon_name", ""),
                "discount_desc": send_data.get("discount_desc", ""),
                "channel": send_data.get("channel", "wecom_sidebar"),
                "sent_at": now,
            },
        )
        await db.commit()

        log.info("coupon_send_recorded", send_id=send_id)
        return {
            "send_id": send_id,
            "send_status": "sent",
            "sent_at": now.isoformat(),
        }

    async def get_coupon_send_history(
        self,
        tenant_id: str,
        customer_id: str,
        page: int,
        size: int,
        db: AsyncSession,
    ) -> dict:
        """客户发券历史(分页)"""
        offset = (page - 1) * size

        count_result = await db.execute(
            text(
                "SELECT COUNT(*) FROM coupon_send_logs"
                " WHERE tenant_id = :tid AND customer_id = :cid AND is_deleted = false"
            ),
            {"tid": tenant_id, "cid": customer_id},
        )
        total = count_result.scalar() or 0

        rows_result = await db.execute(
            text(
                "SELECT id, coupon_name, discount_desc, channel, send_status,"
                " employee_id, sent_at, used_at, revenue_fen"
                " FROM coupon_send_logs"
                " WHERE tenant_id = :tid AND customer_id = :cid AND is_deleted = false"
                " ORDER BY sent_at DESC"
                " LIMIT :limit OFFSET :offset"
            ),
            {"tid": tenant_id, "cid": customer_id, "limit": size, "offset": offset},
        )
        items = [
            {
                "send_id": str(r["id"]),
                "coupon_name": r["coupon_name"],
                "discount_desc": r["discount_desc"],
                "channel": r["channel"],
                "send_status": r["send_status"],
                "employee_id": str(r["employee_id"]),
                "sent_at": _safe_iso(r["sent_at"]),
                "used_at": _safe_iso(r["used_at"]),
                "revenue_fen": r["revenue_fen"] or 0,
            }
            for r in rows_result.mappings()
        ]
        return {"items": items, "total": total, "page": page, "size": size}

    async def get_employee_send_stats(
        self,
        tenant_id: str,
        employee_id: str,
        start_date: str,
        end_date: str,
        db: AsyncSession,
    ) -> dict:
        """员工发券统计: 发放数/核销数/核销率/GMV"""
        result = await db.execute(
            text(
                "SELECT"
                " COUNT(*) as total_sent,"
                " COUNT(*) FILTER (WHERE send_status = 'used') as total_used,"
                " COUNT(*) FILTER (WHERE send_status = 'received') as total_received,"
                " COUNT(*) FILTER (WHERE send_status = 'expired') as total_expired,"
                " COUNT(*) FILTER (WHERE send_status = 'failed') as total_failed,"
                " COALESCE(SUM(revenue_fen) FILTER (WHERE send_status = 'used'), 0) as total_revenue_fen"
                " FROM coupon_send_logs"
                " WHERE tenant_id = :tid AND employee_id = :eid"
                " AND sent_at >= :start_date::timestamptz"
                " AND sent_at < :end_date::timestamptz + interval '1 day'"
                " AND is_deleted = false"
            ),
            {
                "tid": tenant_id,
                "eid": employee_id,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        row = result.mappings().first()
        if not row:
            return {
                "employee_id": employee_id,
                "total_sent": 0,
                "total_used": 0,
                "use_rate": 0.0,
                "total_revenue_fen": 0,
            }

        total_sent = row["total_sent"]
        total_used = row["total_used"]
        use_rate = round(total_used / total_sent, 4) if total_sent > 0 else 0.0

        return {
            "employee_id": employee_id,
            "period": {"start_date": start_date, "end_date": end_date},
            "total_sent": total_sent,
            "total_used": total_used,
            "total_received": row["total_received"],
            "total_expired": row["total_expired"],
            "total_failed": row["total_failed"],
            "use_rate": use_rate,
            "total_revenue_fen": row["total_revenue_fen"],
        }

    async def get_store_send_stats(
        self,
        tenant_id: str,
        store_id: str,
        start_date: str,
        end_date: str,
        db: AsyncSession,
    ) -> dict:
        """门店发券统计"""
        result = await db.execute(
            text(
                "SELECT"
                " COUNT(*) as total_sent,"
                " COUNT(*) FILTER (WHERE send_status = 'used') as total_used,"
                " COUNT(*) FILTER (WHERE send_status = 'received') as total_received,"
                " COUNT(*) FILTER (WHERE send_status = 'expired') as total_expired,"
                " COUNT(*) FILTER (WHERE send_status = 'failed') as total_failed,"
                " COALESCE(SUM(revenue_fen) FILTER (WHERE send_status = 'used'), 0) as total_revenue_fen,"
                " COUNT(DISTINCT employee_id) as employee_count,"
                " COUNT(DISTINCT customer_id) as customer_count"
                " FROM coupon_send_logs"
                " WHERE tenant_id = :tid AND store_id = :sid"
                " AND sent_at >= :start_date::timestamptz"
                " AND sent_at < :end_date::timestamptz + interval '1 day'"
                " AND is_deleted = false"
            ),
            {
                "tid": tenant_id,
                "sid": store_id,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        row = result.mappings().first()
        if not row:
            return {
                "store_id": store_id,
                "total_sent": 0,
                "total_used": 0,
                "use_rate": 0.0,
                "total_revenue_fen": 0,
            }

        total_sent = row["total_sent"]
        total_used = row["total_used"]
        use_rate = round(total_used / total_sent, 4) if total_sent > 0 else 0.0

        return {
            "store_id": store_id,
            "period": {"start_date": start_date, "end_date": end_date},
            "total_sent": total_sent,
            "total_used": total_used,
            "total_received": row["total_received"],
            "total_expired": row["total_expired"],
            "total_failed": row["total_failed"],
            "use_rate": use_rate,
            "total_revenue_fen": row["total_revenue_fen"],
            "employee_count": row["employee_count"],
            "customer_count": row["customer_count"],
        }

    # ─── 话术生成(规则引擎) ──────────────────────────────────

    def _generate_greeting_hint(self, profile: dict) -> str:
        """基于画像数据生成服务话术建议(简单规则, 不调用AI)"""
        parts: list[str] = []
        display_name = profile.get("display_name") or ""

        # 称呼
        name_prefix = ""
        if display_name:
            gender = profile.get("gender")
            if gender == "female":
                name_prefix = f"{display_name}姐"
            elif gender == "male":
                name_prefix = f"{display_name}哥"
            else:
                name_prefix = display_name

        # 高价值会员 VIP 称呼
        rfm_level = profile.get("rfm_level") or ""
        if rfm_level in ("S1", "S2"):
            if name_prefix:
                parts.append(f"{name_prefix}，欢迎光临！")
            else:
                parts.append("欢迎光临！")
        else:
            if name_prefix:
                parts.append(f"{name_prefix}，您好！")
            else:
                parts.append("您好，欢迎光临！")

        # 生日提醒
        if profile.get("birthday_coming"):
            parts.append("看到您本周生日，我们特意准备了小礼物。")

        # 常点菜品推荐
        dish_prefs = profile.get("dish_preferences") or []
        if dish_prefs:
            top_dish = dish_prefs[0].get("dish_name", "")
            if top_dish:
                parts.append(f"今天{top_dish}特别新鲜，推荐您尝尝。")

        # 可用券提醒
        coupon_count = profile.get("available_coupon_count", 0)
        if coupon_count > 0:
            parts.append(f"您账户里有{coupon_count}张券可以使用哦。")

        # 储值余额低提醒
        sv = profile.get("stored_value") or {}
        balance = sv.get("balance_fen", 0)
        total_recharged = sv.get("total_recharged_fen", 0)
        if total_recharged > 0 and balance < 5000:
            parts.append("您的储值余额不多了，今天有充值优惠活动。")

        # 回访提醒
        consumption = profile.get("consumption") or {}
        last_days = consumption.get("last_order_days")
        if last_days is not None and last_days > 30:
            parts.append("好久没见您了，今天有不少新菜品。")

        return "".join(parts)

    # ─── 内部数据获取方法 ────────────────────────────────────

    async def _fetch_member(
        self, tenant_id: str, customer_id: str, db: AsyncSession
    ) -> Optional[dict]:
        """获取客户基础信息"""
        try:
            result = await db.execute(
                text(
                    "SELECT id, primary_phone, display_name, gender, birth_date,"
                    " wechat_avatar_url, wechat_nickname, source,"
                    " wecom_external_userid, wecom_remark,"
                    " rfm_level, r_score, f_score, m_score, risk_score,"
                    " total_order_count, total_order_amount_fen,"
                    " first_order_at, last_order_at,"
                    " tags, created_at"
                    " FROM customers"
                    " WHERE tenant_id = :tid AND id = :cid"
                    " AND is_deleted = false AND is_merged = false"
                    " LIMIT 1"
                ),
                {"tid": tenant_id, "cid": customer_id},
            )
            row = result.mappings().first()
            if not row:
                return None
            return dict(row)
        except SQLAlchemyError as exc:
            logger.error("profile360_fetch_member_error", error=str(exc))
            return None

    async def _fetch_consumption(
        self, tenant_id: str, customer_id: str, db: AsyncSession
    ) -> dict:
        """消费聚合统计"""
        try:
            result = await db.execute(
                text(
                    "SELECT"
                    " COUNT(*) as total_count,"
                    " COALESCE(SUM(o.total_amount_fen), 0) as total_amount_fen,"
                    " COALESCE(AVG(o.total_amount_fen), 0)::int as avg_amount_fen,"
                    " MAX(o.total_amount_fen) as max_amount_fen,"
                    " MIN(o.total_amount_fen) as min_amount_fen,"
                    " MAX(o.order_time) as last_order_at,"
                    " (SELECT s.store_name FROM orders o2"
                    "  JOIN stores s ON s.id = o2.store_id AND s.tenant_id = o2.tenant_id"
                    "  WHERE o2.tenant_id = :tid AND o2.customer_id = :cid"
                    "  AND o2.status = 'completed' AND o2.is_deleted = false"
                    "  ORDER BY o2.order_time DESC LIMIT 1) as last_store_name"
                    " FROM orders o"
                    " WHERE o.tenant_id = :tid AND o.customer_id = :cid"
                    " AND o.status = 'completed' AND o.is_deleted = false"
                ),
                {"tid": tenant_id, "cid": customer_id},
            )
            row = result.mappings().first()
            return dict(row) if row else {}
        except SQLAlchemyError as exc:
            logger.error("profile360_fetch_consumption_error", error=str(exc))
            return {}

    async def _fetch_recent_30d(
        self, tenant_id: str, customer_id: str, db: AsyncSession
    ) -> dict:
        """最近30天消费统计"""
        try:
            result = await db.execute(
                text(
                    "SELECT COUNT(*) as count,"
                    " COALESCE(SUM(total_amount_fen), 0) as amount_fen"
                    " FROM orders"
                    " WHERE tenant_id = :tid AND customer_id = :cid"
                    " AND status = 'completed' AND is_deleted = false"
                    " AND order_time >= NOW() - interval '30 days'"
                ),
                {"tid": tenant_id, "cid": customer_id},
            )
            row = result.mappings().first()
            return dict(row) if row else {"count": 0, "amount_fen": 0}
        except SQLAlchemyError as exc:
            logger.error("profile360_fetch_recent_30d_error", error=str(exc))
            return {"count": 0, "amount_fen": 0}

    async def _fetch_frequent_store(
        self, tenant_id: str, customer_id: str, db: AsyncSession
    ) -> Optional[dict]:
        """最常去门店"""
        try:
            result = await db.execute(
                text(
                    "SELECT o.store_id, s.store_name, COUNT(*) as visit_count"
                    " FROM orders o"
                    " LEFT JOIN stores s ON s.id = o.store_id AND s.tenant_id = o.tenant_id"
                    " WHERE o.tenant_id = :tid AND o.customer_id = :cid"
                    " AND o.status = 'completed' AND o.is_deleted = false"
                    " GROUP BY o.store_id, s.store_name"
                    " ORDER BY visit_count DESC LIMIT 1"
                ),
                {"tid": tenant_id, "cid": customer_id},
            )
            row = result.mappings().first()
            if not row:
                return None
            return {
                "store_id": str(row["store_id"]),
                "store_name": row["store_name"],
                "visit_count": row["visit_count"],
            }
        except SQLAlchemyError as exc:
            logger.error("profile360_fetch_frequent_store_error", error=str(exc))
            return None

    async def _fetch_dish_preferences(
        self, tenant_id: str, customer_id: str, db: AsyncSession
    ) -> list[dict]:
        """Top5 菜品偏好"""
        try:
            # 先拿总点菜次数用于百分比计算
            total_result = await db.execute(
                text(
                    "SELECT COUNT(*) FROM order_items oi"
                    " JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id"
                    " WHERE oi.tenant_id = :tid AND o.customer_id = :cid"
                    " AND o.status = 'completed' AND o.is_deleted = false"
                ),
                {"tid": tenant_id, "cid": customer_id},
            )
            total_items = total_result.scalar() or 1

            result = await db.execute(
                text(
                    "SELECT oi.dish_name, COUNT(*) as order_times"
                    " FROM order_items oi"
                    " JOIN orders o ON o.id = oi.order_id AND o.tenant_id = oi.tenant_id"
                    " WHERE oi.tenant_id = :tid AND o.customer_id = :cid"
                    " AND o.status = 'completed' AND o.is_deleted = false"
                    " GROUP BY oi.dish_name"
                    " ORDER BY order_times DESC"
                    " LIMIT 5"
                ),
                {"tid": tenant_id, "cid": customer_id},
            )
            return [
                {
                    "dish_name": r["dish_name"],
                    "order_times": r["order_times"],
                    "percentage": round(r["order_times"] / total_items, 2),
                }
                for r in result.mappings()
            ]
        except SQLAlchemyError as exc:
            logger.error("profile360_fetch_dish_prefs_error", error=str(exc))
            return []

    async def _fetch_time_preference(
        self, tenant_id: str, customer_id: str, db: AsyncSession
    ) -> Optional[str]:
        """消费时段偏好: lunch(11-14) / dinner(17-21) / late_night(21-02)"""
        try:
            result = await db.execute(
                text(
                    "SELECT"
                    " CASE"
                    "   WHEN EXTRACT(HOUR FROM order_time) BETWEEN 11 AND 13 THEN 'lunch'"
                    "   WHEN EXTRACT(HOUR FROM order_time) BETWEEN 17 AND 20 THEN 'dinner'"
                    "   WHEN EXTRACT(HOUR FROM order_time) >= 21 OR EXTRACT(HOUR FROM order_time) < 2 THEN 'late_night'"
                    "   ELSE 'other'"
                    " END as period,"
                    " COUNT(*) as cnt"
                    " FROM orders"
                    " WHERE tenant_id = :tid AND customer_id = :cid"
                    " AND status = 'completed' AND is_deleted = false"
                    " GROUP BY period ORDER BY cnt DESC LIMIT 1"
                ),
                {"tid": tenant_id, "cid": customer_id},
            )
            row = result.mappings().first()
            if not row:
                return None
            return row["period"] if row["period"] != "other" else None
        except SQLAlchemyError as exc:
            logger.error("profile360_fetch_time_pref_error", error=str(exc))
            return None

    async def _fetch_stored_value(
        self, tenant_id: str, customer_id: str, db: AsyncSession
    ) -> dict:
        """储值账户信息"""
        try:
            result = await db.execute(
                text(
                    "SELECT balance_fen, total_recharged_fen, total_consumed_fen,"
                    " created_at"
                    " FROM stored_value_accounts"
                    " WHERE tenant_id = :tid AND member_id = :cid"
                    " AND is_deleted = false"
                    " LIMIT 1"
                ),
                {"tid": tenant_id, "cid": customer_id},
            )
            row = result.mappings().first()
            if not row:
                return {"balance_fen": 0, "total_recharged_fen": 0, "recharge_count": 0}

            # 充值次数
            recharge_result = await db.execute(
                text(
                    "SELECT COUNT(*) as cnt, MAX(created_at) as last_recharge_at"
                    " FROM stored_value_transactions"
                    " WHERE tenant_id = :tid AND member_id = :cid"
                    " AND type = 'recharge'"
                ),
                {"tid": tenant_id, "cid": customer_id},
            )
            recharge_row = recharge_result.mappings().first()

            return {
                "balance_fen": row["balance_fen"],
                "total_recharged_fen": row["total_recharged_fen"],
                "recharge_count": recharge_row["cnt"] if recharge_row else 0,
                "last_recharge_at": _safe_iso(
                    recharge_row["last_recharge_at"] if recharge_row else None
                ),
            }
        except SQLAlchemyError as exc:
            logger.error("profile360_fetch_stored_value_error", error=str(exc))
            return {"balance_fen": 0, "total_recharged_fen": 0, "recharge_count": 0}

    async def _fetch_points(
        self, tenant_id: str, customer_id: str, db: AsyncSession
    ) -> dict:
        """积分余额"""
        try:
            result = await db.execute(
                text(
                    "SELECT points FROM member_points_balance"
                    " WHERE tenant_id = :tid AND member_id = :cid"
                ),
                {"tid": tenant_id, "cid": customer_id},
            )
            row = result.first()
            balance = row[0] if row else 0

            return {
                "balance": balance,
                "total_earned": 0,
                "total_used": 0,
            }
        except SQLAlchemyError as exc:
            logger.error("profile360_fetch_points_error", error=str(exc))
            return {"balance": 0, "total_earned": 0, "total_used": 0}

    async def _fetch_member_card(
        self, tenant_id: str, customer_id: str, db: AsyncSession
    ) -> Optional[dict]:
        """会员卡/等级信息"""
        try:
            # 从 customers 取当前等级, 从 member_level_configs 取等级详情
            result = await db.execute(
                text(
                    "SELECT c.rfm_level, c.total_order_amount_fen, c.extra,"
                    " mlc.level_name, mlc.level_code,"
                    " mlc.min_annual_spend_fen, mlc.discount_rate"
                    " FROM customers c"
                    " LEFT JOIN member_level_configs mlc"
                    "   ON mlc.tenant_id = c.tenant_id"
                    "   AND mlc.level_code = c.rfm_level"
                    "   AND mlc.is_deleted = false"
                    " WHERE c.tenant_id = :tid AND c.id = :cid"
                    " AND c.is_deleted = false"
                    " LIMIT 1"
                ),
                {"tid": tenant_id, "cid": customer_id},
            )
            row = result.mappings().first()
            if not row:
                return None

            # 查下一级所需消费
            next_level_result = await db.execute(
                text(
                    "SELECT level_code, level_name, min_annual_spend_fen"
                    " FROM member_level_configs"
                    " WHERE tenant_id = :tid AND is_deleted = false"
                    " AND min_annual_spend_fen > COALESCE(:current_spend, 0)"
                    " ORDER BY min_annual_spend_fen ASC LIMIT 1"
                ),
                {"tid": tenant_id, "current_spend": row["total_order_amount_fen"] or 0},
            )
            next_row = next_level_result.mappings().first()

            upgrade_progress = None
            next_level = None
            if next_row and next_row["min_annual_spend_fen"] > 0:
                spent = row["total_order_amount_fen"] or 0
                target = next_row["min_annual_spend_fen"]
                upgrade_progress = round(min(spent / target, 1.0), 2)
                next_level = next_row["level_code"]

            extra = row["extra"] or {}
            return {
                "card_no": extra.get("card_no", ""),
                "level": row["rfm_level"],
                "level_name": row["level_name"] or row["rfm_level"],
                "expire_at": extra.get("card_expire_at"),
                "upgrade_progress": upgrade_progress,
                "next_level": next_level,
            }
        except SQLAlchemyError as exc:
            logger.error("profile360_fetch_member_card_error", error=str(exc))
            return None

    async def _fetch_available_coupons(
        self, tenant_id: str, customer_id: str, db: AsyncSession, limit: int = 10
    ) -> list[dict]:
        """可用优惠券(从 coupons 表查该租户下可用券, 简化版)"""
        try:
            result = await db.execute(
                text(
                    "SELECT id, name, coupon_type, cash_amount_fen,"
                    " discount_rate, min_order_fen, end_date, description"
                    " FROM coupons"
                    " WHERE tenant_id = :tid"
                    " AND is_active = true AND is_deleted = false"
                    " AND (end_date IS NULL OR end_date >= CURRENT_DATE)"
                    " ORDER BY end_date ASC NULLS LAST"
                    " LIMIT :limit"
                ),
                {"tid": tenant_id, "limit": limit},
            )
            items = []
            for r in result.mappings():
                # 组装折扣描述
                desc = r.get("description") or ""
                if not desc:
                    if r["coupon_type"] == "full_reduction" and r["cash_amount_fen"]:
                        threshold = r["min_order_fen"] or 0
                        desc = f"满{threshold // 100}减{r['cash_amount_fen'] // 100}"
                    elif r["coupon_type"] == "discount" and r["discount_rate"]:
                        desc = f"{float(r['discount_rate']) * 10:.1f}折券"

                items.append({
                    "coupon_id": str(r["id"]),
                    "name": r["name"],
                    "discount_desc": desc,
                    "expire_at": _safe_iso(r["end_date"]),
                    "status": "available",
                })
            return items
        except SQLAlchemyError as exc:
            logger.error("profile360_fetch_coupons_error", error=str(exc))
            return []

    async def _fetch_recent_coupon_sends(
        self, tenant_id: str, customer_id: str, db: AsyncSession
    ) -> list[dict]:
        """最近10条发券记录"""
        try:
            result = await db.execute(
                text(
                    "SELECT coupon_name, sent_at, send_status, employee_id"
                    " FROM coupon_send_logs"
                    " WHERE tenant_id = :tid AND customer_id = :cid AND is_deleted = false"
                    " ORDER BY sent_at DESC LIMIT 10"
                ),
                {"tid": tenant_id, "cid": customer_id},
            )
            return [
                {
                    "coupon_name": r["coupon_name"],
                    "sent_at": _safe_iso(r["sent_at"]),
                    "send_status": r["send_status"],
                    "employee_id": str(r["employee_id"]),
                }
                for r in result.mappings()
            ]
        except SQLAlchemyError as exc:
            logger.error("profile360_fetch_coupon_sends_error", error=str(exc))
            return []
