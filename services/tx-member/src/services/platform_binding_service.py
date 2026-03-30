"""外卖平台用户 ↔ 屯象 Golden ID 绑定服务

支持美团外卖、抖音团购、饿了么三大外卖平台。
核销时通过手机号或平台 user_id 匹配/创建 Customer，
统计消费数据并触发 RFM 更新、首单旅程。

设计原则：
- 同一订单重复推送幂等（order_no 级别去重，通过 Customer.extra 记录已处理订单）
- 金额统一存分（fen）
- 禁止 broad except，异常分类处理
- structlog 记录 platform/customer_id/action
"""
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

import structlog
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Customer

logger = structlog.get_logger()

Platform = Literal["meituan", "douyin", "eleme"]

# 平台字段映射：platform → (user_id 列名, openid 列名)
_PLATFORM_FIELDS: dict[str, tuple[str, str | None]] = {
    "meituan": ("meituan_user_id", "meituan_openid"),
    "douyin": (None, "douyin_openid"),       # type: ignore[assignment]
    "eleme": ("eleme_user_id", None),        # type: ignore[assignment]
}


class PlatformBindingService:
    """外卖平台用户 ↔ 屯象 Golden ID 绑定服务"""

    # ─────────────────────────────────────────────────────────────
    # 公开入口
    # ─────────────────────────────────────────────────────────────

    async def bind_meituan_order(
        self,
        order_data: dict[str, Any],
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """美团外卖订单到店核销时触发

        order_data 必填字段：
          - order_no: str          美团订单号（幂等 key）
          - amount_fen: int        消费金额（分）
          - store_id: str          门店 ID
          - items: list[dict]      购买商品列表
        可选字段：
          - phone: str             顾客手机号（核销时可获取）
          - meituan_user_id: str   美团用户 ID
          - meituan_openid: str    美团小程序 openid
        """
        log = logger.bind(platform="meituan", order_no=order_data.get("order_no"), tenant_id=str(tenant_id))
        log.info("bind_meituan_order_start")

        result = await self.bind_platform_user(
            platform="meituan",
            platform_user_id=order_data.get("meituan_user_id", ""),
            phone=order_data.get("phone"),
            extra_data={
                "order_no": order_data.get("order_no", ""),
                "amount_fen": int(order_data.get("amount_fen", 0)),
                "store_id": order_data.get("store_id", ""),
                "items": order_data.get("items", []),
                "meituan_openid": order_data.get("meituan_openid"),
            },
            tenant_id=tenant_id,
            db=db,
        )

        if result["is_new_customer"]:
            asyncio.create_task(
                self._trigger_new_customer_journey(result["customer_id"], tenant_id, "meituan")
            )

        log.info(
            "bind_meituan_order_done",
            customer_id=result["customer_id"],
            action=result["action"],
            is_new=result["is_new_customer"],
        )
        return result

    async def bind_douyin_order(
        self,
        order_data: dict[str, Any],
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """抖音团购核销时触发

        order_data 必填字段：
          - order_no: str          抖音订单号（幂等 key）
          - amount_fen: int        消费金额（分）
          - store_id: str          门店 ID
          - items: list[dict]      购买商品列表
        可选字段：
          - phone: str             顾客手机号
          - douyin_openid: str     抖音 openid
        """
        log = logger.bind(platform="douyin", order_no=order_data.get("order_no"), tenant_id=str(tenant_id))
        log.info("bind_douyin_order_start")

        result = await self.bind_platform_user(
            platform="douyin",
            platform_user_id=order_data.get("douyin_openid", ""),
            phone=order_data.get("phone"),
            extra_data={
                "order_no": order_data.get("order_no", ""),
                "amount_fen": int(order_data.get("amount_fen", 0)),
                "store_id": order_data.get("store_id", ""),
                "items": order_data.get("items", []),
            },
            tenant_id=tenant_id,
            db=db,
        )

        if result["is_new_customer"]:
            asyncio.create_task(
                self._trigger_new_customer_journey(result["customer_id"], tenant_id, "douyin")
            )

        log.info(
            "bind_douyin_order_done",
            customer_id=result["customer_id"],
            action=result["action"],
            is_new=result["is_new_customer"],
        )
        return result

    async def bind_platform_user(
        self,
        platform: Platform,
        platform_user_id: str,
        phone: str | None,
        extra_data: dict[str, Any],
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """通用平台用户绑定（内部复用方法）

        查找优先级：
        1. 手机号匹配（primary_phone）
        2. 平台 user_id / openid 匹配
        3. 未找到 → 创建新 Customer

        幂等：同一 order_no 已处理则跳过消费统计，仅返回已有 customer_id。

        Returns:
            {
                customer_id: str,
                action: "bound" | "created" | "idempotent_skip",
                is_new_customer: bool,
            }
        """
        log = logger.bind(platform=platform, tenant_id=str(tenant_id))

        order_no: str = extra_data.get("order_no", "")
        amount_fen: int = int(extra_data.get("amount_fen", 0))

        await self._set_tenant(db, str(tenant_id))

        # 1. 手机号查找
        customer: Customer | None = None
        if phone:
            customer = await self._find_by_phone(db, tenant_id, phone)

        # 2. 平台 user_id / openid 查找
        if customer is None and platform_user_id:
            customer = await self._find_by_platform_id(db, tenant_id, platform, platform_user_id)

        is_new_customer = False

        if customer is not None:
            # 幂等检查：同一 order_no 已处理过
            processed_orders: list[str] = (customer.extra or {}).get("processed_order_nos", [])
            if order_no and order_no in processed_orders:
                log.info("bind_platform_user_idempotent", customer_id=str(customer.id), order_no=order_no)
                return {
                    "customer_id": str(customer.id),
                    "action": "idempotent_skip",
                    "is_new_customer": False,
                }

            await self._update_customer_platform(
                db=db,
                customer=customer,
                platform=platform,
                platform_user_id=platform_user_id,
                extra_data=extra_data,
                order_no=order_no,
                amount_fen=amount_fen,
            )
            action = "bound"

        else:
            # 创建新会员
            customer = await self._create_customer_from_platform(
                db=db,
                tenant_id=tenant_id,
                platform=platform,
                platform_user_id=platform_user_id,
                phone=phone,
                extra_data=extra_data,
                order_no=order_no,
                amount_fen=amount_fen,
            )
            is_new_customer = True
            action = "created"

        try:
            await db.flush()
        except IntegrityError as exc:
            log.error("bind_platform_user_integrity_error", error=str(exc.orig))
            raise

        log.info("bind_platform_user_ok", customer_id=str(customer.id), action=action)
        return {
            "customer_id": str(customer.id),
            "action": action,
            "is_new_customer": is_new_customer,
        }

    async def get_platform_binding_stats(
        self,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """各平台绑定情况统计

        Returns:
            {
                meituan: {total_bound, new_today, conversion_rate},
                douyin:  {total_bound, new_today, conversion_rate},
                eleme:   {total_bound, new_today, conversion_rate},
                total_cross_platform: int,  # 同时在两个以上平台消费的会员数
            }
        """
        await self._set_tenant(db, str(tenant_id))

        today_start = datetime.now(tz=timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        # 各平台总绑定数
        async def _count_bound(col_name: str) -> int:
            result = await db.execute(
                select(func.count(Customer.id))
                .where(Customer.tenant_id == tenant_id)
                .where(Customer.is_deleted.is_(False))
                .where(getattr(Customer, col_name).isnot(None))
            )
            return result.scalar() or 0

        async def _count_new_today(source_val: str) -> int:
            result = await db.execute(
                select(func.count(Customer.id))
                .where(Customer.tenant_id == tenant_id)
                .where(Customer.is_deleted.is_(False))
                .where(Customer.source == source_val)
                .where(Customer.created_at >= today_start)
            )
            return result.scalar() or 0

        async def _count_total_source(source_val: str) -> int:
            result = await db.execute(
                select(func.count(Customer.id))
                .where(Customer.tenant_id == tenant_id)
                .where(Customer.is_deleted.is_(False))
                .where(Customer.source == source_val)
            )
            return result.scalar() or 0

        # 汇总
        mt_bound = await _count_bound("meituan_user_id")
        dy_bound = await _count_bound("douyin_openid")
        ele_bound = await _count_bound("eleme_user_id")

        mt_new = await _count_new_today("meituan")
        dy_new = await _count_new_today("douyin")
        ele_new = await _count_new_today("eleme")

        mt_total = await _count_total_source("meituan")
        dy_total = await _count_total_source("douyin")
        ele_total = await _count_total_source("eleme")

        # 跨平台消费（meituan_user_id 和 douyin_openid 均有值）
        cross_result = await db.execute(
            select(func.count(Customer.id))
            .where(Customer.tenant_id == tenant_id)
            .where(Customer.is_deleted.is_(False))
            .where(Customer.meituan_user_id.isnot(None))
            .where(Customer.douyin_openid.isnot(None))
        )
        total_cross_platform = cross_result.scalar() or 0

        def _rate(bound: int, total: int) -> float:
            return round(bound / total, 4) if total > 0 else 0.0

        return {
            "meituan": {
                "total_bound": mt_bound,
                "new_today": mt_new,
                "conversion_rate": _rate(mt_bound, mt_total),
            },
            "douyin": {
                "total_bound": dy_bound,
                "new_today": dy_new,
                "conversion_rate": _rate(dy_bound, dy_total),
            },
            "eleme": {
                "total_bound": ele_bound,
                "new_today": ele_new,
                "conversion_rate": _rate(ele_bound, ele_total),
            },
            "total_cross_platform": total_cross_platform,
        }

    async def merge_platform_duplicates(
        self,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """合并平台重复会员（同手机号但不同来源）

        逻辑：
        1. 以 primary_phone 为 key，找出同手机号有多条档案的会员（is_merged=False）
        2. 按 created_at ASC 取最早创建的为主档案（primary）
        3. 将其余档案的消费数据合并到主档案（total 相加，取最大 rfm_level 数值）
        4. 合并平台身份字段（主档案无值则从副档案取）
        5. 标记副档案 is_merged=True, merged_into=主档案 ID

        Returns:
            {merged_pairs: int, skipped: int}
        """
        log = logger.bind(tenant_id=str(tenant_id))
        log.info("merge_platform_duplicates_start")

        await self._set_tenant(db, str(tenant_id))

        # 查找有重复手机号的 phone 集合
        dup_result = await db.execute(
            select(Customer.primary_phone, func.count(Customer.id).label("cnt"))
            .where(Customer.tenant_id == tenant_id)
            .where(Customer.is_deleted.is_(False))
            .where(Customer.is_merged.is_(False))
            .group_by(Customer.primary_phone)
            .having(func.count(Customer.id) > 1)
        )
        dup_phones = [row[0] for row in dup_result.all()]

        if not dup_phones:
            log.info("merge_platform_duplicates_no_duplicates")
            return {"merged_pairs": 0, "skipped": 0}

        merged_pairs = 0
        skipped = 0

        for phone in dup_phones:
            customers_result = await db.execute(
                select(Customer)
                .where(Customer.tenant_id == tenant_id)
                .where(Customer.primary_phone == phone)
                .where(Customer.is_deleted.is_(False))
                .where(Customer.is_merged.is_(False))
                .order_by(Customer.created_at.asc())
            )
            records: list[Customer] = list(customers_result.scalars().all())

            if len(records) < 2:
                skipped += 1
                continue

            primary = records[0]
            duplicates = records[1:]

            for dup in duplicates:
                # 合并消费统计
                primary.total_order_count = (primary.total_order_count or 0) + (dup.total_order_count or 0)
                primary.total_order_amount_fen = (primary.total_order_amount_fen or 0) + (dup.total_order_amount_fen or 0)
                primary.rfm_monetary_fen = (primary.rfm_monetary_fen or 0) + (dup.rfm_monetary_fen or 0)

                # 取更近的 last_order_at
                if dup.last_order_at and (
                    primary.last_order_at is None or dup.last_order_at > primary.last_order_at
                ):
                    primary.last_order_at = dup.last_order_at

                # 取更早的 first_order_at
                if dup.first_order_at and (
                    primary.first_order_at is None or dup.first_order_at < primary.first_order_at
                ):
                    primary.first_order_at = dup.first_order_at

                # 合并 rfm_level（取数字最小，即等级最高：S1 > S2 > ... > S5）
                primary.rfm_level = _higher_rfm_level(primary.rfm_level, dup.rfm_level)

                # 合并平台身份（主档案无值时取副档案的）
                if not primary.meituan_user_id and dup.meituan_user_id:
                    primary.meituan_user_id = dup.meituan_user_id
                if not primary.meituan_openid and dup.meituan_openid:
                    primary.meituan_openid = dup.meituan_openid
                if not primary.douyin_openid and dup.douyin_openid:
                    primary.douyin_openid = dup.douyin_openid
                if not primary.eleme_user_id and dup.eleme_user_id:
                    primary.eleme_user_id = dup.eleme_user_id

                # 合并微信身份
                if not primary.wechat_openid and dup.wechat_openid:
                    primary.wechat_openid = dup.wechat_openid
                if not primary.wechat_unionid and dup.wechat_unionid:
                    primary.wechat_unionid = dup.wechat_unionid

                # 标记副档案已合并
                dup.is_merged = True
                dup.merged_into = primary.id
                dup.updated_at = datetime.now(tz=timezone.utc)

                merged_pairs += 1
                log.info(
                    "merge_platform_duplicates_pair",
                    primary_id=str(primary.id),
                    dup_id=str(dup.id),
                    phone=phone,
                )

            primary.updated_at = datetime.now(tz=timezone.utc)

        await db.flush()
        log.info("merge_platform_duplicates_done", merged_pairs=merged_pairs, skipped=skipped)
        return {"merged_pairs": merged_pairs, "skipped": skipped}

    # ─────────────────────────────────────────────────────────────
    # 私有方法
    # ─────────────────────────────────────────────────────────────

    async def _set_tenant(self, db: AsyncSession, tenant_id: str) -> None:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

    async def _find_by_phone(
        self, db: AsyncSession, tenant_id: uuid.UUID, phone: str
    ) -> Customer | None:
        result = await db.execute(
            select(Customer)
            .where(Customer.tenant_id == tenant_id)
            .where(Customer.primary_phone == phone)
            .where(Customer.is_deleted.is_(False))
            .where(Customer.is_merged.is_(False))
        )
        return result.scalar_one_or_none()

    async def _find_by_platform_id(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        platform: Platform,
        platform_user_id: str,
    ) -> Customer | None:
        if not platform_user_id:
            return None

        user_id_col, openid_col = _PLATFORM_FIELDS.get(platform, (None, None))

        conditions = []
        if user_id_col:
            conditions.append(getattr(Customer, user_id_col) == platform_user_id)
        if openid_col:
            conditions.append(getattr(Customer, openid_col) == platform_user_id)

        if not conditions:
            return None

        result = await db.execute(
            select(Customer)
            .where(Customer.tenant_id == tenant_id)
            .where(Customer.is_deleted.is_(False))
            .where(Customer.is_merged.is_(False))
            .where(or_(*conditions))
        )
        return result.scalar_one_or_none()

    async def _update_customer_platform(
        self,
        db: AsyncSession,
        customer: Customer,
        platform: Platform,
        platform_user_id: str,
        extra_data: dict[str, Any],
        order_no: str,
        amount_fen: int,
    ) -> None:
        """更新已有会员的平台绑定信息和消费统计"""
        now = datetime.now(tz=timezone.utc)

        # 绑定平台 ID（无值时写入）
        user_id_col, openid_col = _PLATFORM_FIELDS.get(platform, (None, None))
        if user_id_col and platform_user_id and not getattr(customer, user_id_col):
            setattr(customer, user_id_col, platform_user_id)
        if openid_col and extra_data.get(openid_col) and not getattr(customer, openid_col):
            setattr(customer, openid_col, extra_data[openid_col])

        # 消费统计
        if amount_fen > 0:
            customer.total_order_count = (customer.total_order_count or 0) + 1
            customer.total_order_amount_fen = (customer.total_order_amount_fen or 0) + amount_fen
            customer.last_order_at = now
            if not customer.first_order_at:
                customer.first_order_at = now

        # 幂等记录：写入 extra.processed_order_nos
        if order_no:
            extra = dict(customer.extra or {})
            processed: list[str] = extra.get("processed_order_nos", [])
            if order_no not in processed:
                processed.append(order_no)
                # 最多保留最近 200 条
                if len(processed) > 200:
                    processed = processed[-200:]
                extra["processed_order_nos"] = processed
                customer.extra = extra

        customer.updated_at = now

    async def _create_customer_from_platform(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        platform: Platform,
        platform_user_id: str,
        phone: str | None,
        extra_data: dict[str, Any],
        order_no: str,
        amount_fen: int,
    ) -> Customer:
        """创建新会员（来源为外卖平台）"""
        now = datetime.now(tz=timezone.utc)

        extra: dict[str, Any] = {}
        if order_no:
            extra["processed_order_nos"] = [order_no]

        new_customer = Customer(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            primary_phone=phone or "",
            source=platform,
            rfm_level="S3",
            total_order_count=1 if amount_fen > 0 else 0,
            total_order_amount_fen=amount_fen if amount_fen > 0 else 0,
            first_order_at=now if amount_fen > 0 else None,
            last_order_at=now if amount_fen > 0 else None,
            tags=[],
            extra=extra,
        )

        # 写入平台 ID
        user_id_col, openid_col = _PLATFORM_FIELDS.get(platform, (None, None))
        if user_id_col and platform_user_id:
            setattr(new_customer, user_id_col, platform_user_id)
        if openid_col and extra_data.get(openid_col):
            setattr(new_customer, openid_col, extra_data[openid_col])

        db.add(new_customer)
        return new_customer

    async def _trigger_new_customer_journey(
        self,
        customer_id: str,
        tenant_id: uuid.UUID,
        platform: Platform,
    ) -> None:
        """异步通知 tx-growth 触发"新用户首单"旅程

        通过内部 HTTP 调用 tx-growth 的旅程触发接口（fire and forget）。
        失败时记录日志但不影响主流程。
        """
        import httpx

        log = logger.bind(customer_id=customer_id, tenant_id=str(tenant_id), platform=platform)
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    "http://tx-growth/api/v1/journeys/trigger",
                    json={
                        "customer_id": customer_id,
                        "journey_type": "new_customer_first_order",
                        "source_platform": platform,
                    },
                    headers={"X-Tenant-ID": str(tenant_id)},
                )
                resp.raise_for_status()
                log.info("trigger_new_customer_journey_ok")
        except httpx.HTTPStatusError as exc:
            log.warning(
                "trigger_new_customer_journey_http_error",
                status_code=exc.response.status_code,
            )
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            log.warning("trigger_new_customer_journey_network_error", error=str(exc))


# ─────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────

def _higher_rfm_level(level_a: str | None, level_b: str | None) -> str:
    """比较两个 RFM 等级，返回数字更小（等级更高）的。
    S1 > S2 > S3 > S4 > S5
    """
    default = "S3"
    a = level_a or default
    b = level_b or default
    # 取数字部分比较，数字小等级高
    try:
        num_a = int(a[1:]) if len(a) >= 2 and a[0] == "S" else 99
        num_b = int(b[1:]) if len(b) >= 2 and b[0] == "S" else 99
    except ValueError:
        return a
    return a if num_a <= num_b else b
