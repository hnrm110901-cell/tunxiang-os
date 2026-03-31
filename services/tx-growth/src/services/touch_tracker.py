"""触达追踪服务 — 生成 touch_id 短码，记录触达/点击事件，驱动归因逻辑

核心职责：
  1. record_touch()       — 记录一次营销触达，生成唯一 touch_id（"tx_" + 8位短码）
  2. generate_tracked_url() — 生成嵌入 touch_id 的追踪链接（小程序/H5）
  3. record_click()       — 记录点击事件，更新 clicked_at / click_count
  4. check_and_attribute() — 核心归因逻辑：查找归因窗口内的触点，写入 attribution_conversions

归因模型（默认 last_touch）：
  last_touch  — 归因给归因窗口内最近一次触达
  first_touch — 归因给归因窗口内最早一次触达

金额单位：元（conversion_value 使用 NUMERIC(12,2)）
"""
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urlencode, urlparse, urlunparse, parse_qs

import structlog
from sqlalchemy import select, update, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 配置常量
# ---------------------------------------------------------------------------

ATTRIBUTION_WINDOW_HOURS: int = 72
TOUCH_ID_PREFIX: str = "tx_"

# 同一 touch_id + 同一 IP 防刷窗口（秒）—— Redis TTL 由 router 层控制
CLICK_DEDUP_TTL_SECONDS: int = 60


# ---------------------------------------------------------------------------
# 内部数据类（避免循环导入 SQLAlchemy models）
# ---------------------------------------------------------------------------


@dataclass
class TouchEvent:
    id: uuid.UUID
    tenant_id: uuid.UUID
    touch_id: str
    channel: str
    campaign_id: Optional[uuid.UUID]
    journey_enrollment_id: Optional[uuid.UUID]
    customer_id: uuid.UUID
    phone: Optional[str]
    content_type: str
    content_snapshot: dict
    sent_at: datetime
    delivered_at: Optional[datetime]
    clicked_at: Optional[datetime]
    click_count: int
    created_at: datetime


@dataclass
class AttributionConversion:
    id: uuid.UUID
    tenant_id: uuid.UUID
    touch_id: str
    customer_id: uuid.UUID
    conversion_type: str
    conversion_id: uuid.UUID
    conversion_value: float
    converted_at: datetime
    attribution_window_hours: int
    is_first_conversion: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# TouchTracker
# ---------------------------------------------------------------------------


class TouchTracker:
    """营销触达追踪器 — 管理 touch_events 和 attribution_conversions 表"""

    # ------------------------------------------------------------------
    # 公共：生成 touch_id
    # ------------------------------------------------------------------

    @staticmethod
    def _new_touch_id() -> str:
        """生成唯一追踪短码，格式 tx_xxxxxxxx（11位）。"""
        return TOUCH_ID_PREFIX + secrets.token_urlsafe(8)

    # ------------------------------------------------------------------
    # A. 记录触达
    # ------------------------------------------------------------------

    async def record_touch(
        self,
        tenant_id: uuid.UUID,
        channel: str,
        customer_id: uuid.UUID,
        content_type: str,
        content: dict,
        *,
        campaign_id: Optional[uuid.UUID] = None,
        enrollment_id: Optional[uuid.UUID] = None,
        phone: Optional[str] = None,
        sent_at: Optional[datetime] = None,
        db: AsyncSession,
    ) -> TouchEvent:
        """记录一次营销触达事件，返回含 touch_id 的 TouchEvent。

        Args:
            tenant_id:      租户 UUID
            channel:        渠道（wecom / sms / miniapp_push / poster_qr）
            customer_id:    客户 UUID
            content_type:   内容类型（coupon / invitation / product_recommend / recall）
            content:        发送内容快照 dict（title、body、offer_id 等）
            campaign_id:    关联活动 UUID（可选）
            enrollment_id:  关联旅程步骤 UUID（可选）
            phone:          手机号（可选，冗余字段）
            sent_at:        触达时间（默认 now()）
            db:             AsyncSession

        Returns:
            TouchEvent dataclass
        """
        _valid_channels = {"wecom", "sms", "miniapp_push", "poster_qr"}
        if channel not in _valid_channels:
            raise ValueError(f"channel 无效：{channel!r}，必须是 {_valid_channels}")

        _valid_content_types = {"coupon", "invitation", "product_recommend", "recall"}
        if content_type not in _valid_content_types:
            raise ValueError(f"content_type 无效：{content_type!r}，必须是 {_valid_content_types}")

        touch_id = self._new_touch_id()
        now = sent_at or datetime.now(timezone.utc)
        event_id = uuid.uuid4()

        await db.execute(
            """
            INSERT INTO touch_events
              (id, tenant_id, touch_id, channel, campaign_id, journey_enrollment_id,
               customer_id, phone, content_type, content_snapshot, sent_at, created_at)
            VALUES
              (:id, :tenant_id, :touch_id, :channel, :campaign_id, :enrollment_id,
               :customer_id, :phone, :content_type, :content_snapshot::jsonb, :sent_at, :created_at)
            """,
            {
                "id": event_id,
                "tenant_id": tenant_id,
                "touch_id": touch_id,
                "channel": channel,
                "campaign_id": campaign_id,
                "enrollment_id": enrollment_id,
                "customer_id": customer_id,
                "phone": phone,
                "content_type": content_type,
                "content_snapshot": __import__("json").dumps(content, ensure_ascii=False),
                "sent_at": now,
                "created_at": now,
            },
        )

        log.info(
            "touch_recorded",
            touch_id=touch_id,
            channel=channel,
            customer_id=str(customer_id),
            campaign_id=str(campaign_id) if campaign_id else None,
            tenant_id=str(tenant_id),
        )

        return TouchEvent(
            id=event_id,
            tenant_id=tenant_id,
            touch_id=touch_id,
            channel=channel,
            campaign_id=campaign_id,
            journey_enrollment_id=enrollment_id,
            customer_id=customer_id,
            phone=phone,
            content_type=content_type,
            content_snapshot=content,
            sent_at=now,
            delivered_at=None,
            clicked_at=None,
            click_count=0,
            created_at=now,
        )

    # ------------------------------------------------------------------
    # B. 生成追踪链接
    # ------------------------------------------------------------------

    @staticmethod
    def generate_tracked_url(touch_id: str, destination_url: str) -> str:
        """将 touch_id 作为 query 参数嵌入目标链接，用于小程序/H5 跳转追踪。

        示例：
            destination_url = "https://wx.example.com/coupon?id=123"
            → "https://wx.example.com/coupon?id=123&_txid=tx_abc12345"

        Args:
            touch_id:        触达短码（tx_xxxxxxxx）
            destination_url: 原始目标链接

        Returns:
            含 _txid 参数的追踪链接
        """
        parsed = urlparse(destination_url)
        existing = parse_qs(parsed.query, keep_blank_values=True)
        existing["_txid"] = [touch_id]
        new_query = urlencode(
            {k: v[0] if len(v) == 1 else v for k, v in existing.items()},
            doseq=True,
        )
        tracked = parsed._replace(query=new_query)
        return urlunparse(tracked)

    # ------------------------------------------------------------------
    # C. 记录点击
    # ------------------------------------------------------------------

    async def record_click(
        self,
        touch_id: str,
        db: AsyncSession,
    ) -> Optional[TouchEvent]:
        """记录一次点击事件：更新 clicked_at（首次）和 click_count（每次）。

        Args:
            touch_id: 触达短码
            db:       AsyncSession

        Returns:
            更新后的 TouchEvent，如果 touch_id 不存在则返回 None
        """
        now = datetime.now(timezone.utc)

        result = await db.execute(
            """
            UPDATE touch_events
            SET
                clicked_at  = COALESCE(clicked_at, :now),
                click_count = click_count + 1
            WHERE touch_id = :touch_id
            RETURNING
                id, tenant_id, touch_id, channel, campaign_id, journey_enrollment_id,
                customer_id, phone, content_type, content_snapshot,
                sent_at, delivered_at, clicked_at, click_count, created_at
            """,
            {"now": now, "touch_id": touch_id},
        )

        row = result.fetchone()
        if row is None:
            log.warning("record_click_touch_not_found", touch_id=touch_id)
            return None

        log.info(
            "touch_click_recorded",
            touch_id=touch_id,
            click_count=row.click_count,
        )

        return TouchEvent(
            id=row.id,
            tenant_id=row.tenant_id,
            touch_id=row.touch_id,
            channel=row.channel,
            campaign_id=row.campaign_id,
            journey_enrollment_id=row.journey_enrollment_id,
            customer_id=row.customer_id,
            phone=row.phone,
            content_type=row.content_type,
            content_snapshot=row.content_snapshot if isinstance(row.content_snapshot, dict) else {},
            sent_at=row.sent_at,
            delivered_at=row.delivered_at,
            clicked_at=row.clicked_at,
            click_count=row.click_count,
            created_at=row.created_at,
        )

    # ------------------------------------------------------------------
    # D. 核心归因逻辑
    # ------------------------------------------------------------------

    async def check_and_attribute(
        self,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        conversion_type: str,
        conversion_id: uuid.UUID,
        conversion_value: float,
        db: AsyncSession,
        *,
        converted_at: Optional[datetime] = None,
        attribution_window_hours: int = ATTRIBUTION_WINDOW_HOURS,
        model: str = "last_touch",
    ) -> Optional[AttributionConversion]:
        """核心归因逻辑：查找归因窗口内的触点，写入 attribution_conversions。

        流程：
          1. 查找该客户在 [converted_at - attribution_window_hours, converted_at] 内
             所有 touch_events（按 sent_at）
          2. 按模型选择归因触点：
               last_touch  → 最近一次（sent_at 最大）
               first_touch → 最早一次（sent_at 最小）
          3. 检查 (touch_id, conversion_id) 是否已归因（幂等）
          4. 写入 attribution_conversions，返回结果

        Args:
            tenant_id:                 租户 UUID
            customer_id:               发生转化的客户 UUID
            conversion_type:           转化类型（reservation/order/repurchase/referral）
            conversion_id:             关联业务实体 UUID（预订 ID 或订单 ID）
            conversion_value:          转化金额（元）
            db:                        AsyncSession
            converted_at:              转化时间（默认 now()）
            attribution_window_hours:  归因窗口小时数（默认 72）
            model:                     归因模型（last_touch / first_touch）

        Returns:
            创建的 AttributionConversion，未找到触点时返回 None
        """
        _valid_types = {"reservation", "order", "repurchase", "referral"}
        if conversion_type not in _valid_types:
            raise ValueError(f"conversion_type 无效：{conversion_type!r}，必须是 {_valid_types}")

        if model not in ("last_touch", "first_touch"):
            raise ValueError(f"model 无效：{model!r}，支持 last_touch / first_touch")

        now = converted_at or datetime.now(timezone.utc)
        window_start = now - timedelta(hours=attribution_window_hours)

        # 1. 查找归因窗口内所有触点
        order_by = "DESC" if model == "last_touch" else "ASC"
        rows = await db.execute(
            f"""
            SELECT touch_id, sent_at, channel, campaign_id
            FROM touch_events
            WHERE tenant_id   = :tenant_id
              AND customer_id = :customer_id
              AND sent_at     >= :window_start
              AND sent_at     <= :now
            ORDER BY sent_at {order_by}
            LIMIT 1
            """,
            {
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "window_start": window_start,
                "now": now,
            },
        )
        touch_row = rows.fetchone()

        if touch_row is None:
            log.info(
                "attribution_no_touch_found",
                customer_id=str(customer_id),
                conversion_type=conversion_type,
                window_hours=attribution_window_hours,
                tenant_id=str(tenant_id),
            )
            return None

        selected_touch_id = touch_row.touch_id

        # 2. 检查是否已有同 (touch_id, conversion_id) 的归因记录（幂等）
        existing = await db.execute(
            """
            SELECT id FROM attribution_conversions
            WHERE touch_id = :touch_id AND conversion_id = :conversion_id
            LIMIT 1
            """,
            {"touch_id": selected_touch_id, "conversion_id": conversion_id},
        )
        if existing.fetchone() is not None:
            log.info(
                "attribution_already_exists",
                touch_id=selected_touch_id,
                conversion_id=str(conversion_id),
            )
            return None

        # 3. 判断是否为该触达的首次转化
        prior_count_row = await db.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM attribution_conversions
            WHERE touch_id = :touch_id
            """,
            {"touch_id": selected_touch_id},
        )
        prior_count = (prior_count_row.fetchone() or [0])[0]
        is_first = prior_count == 0

        # 4. 写入归因记录
        conv_id = uuid.uuid4()
        created_at = datetime.now(timezone.utc)

        await db.execute(
            """
            INSERT INTO attribution_conversions
              (id, tenant_id, touch_id, customer_id, conversion_type, conversion_id,
               conversion_value, converted_at, attribution_window_hours, is_first_conversion, created_at)
            VALUES
              (:id, :tenant_id, :touch_id, :customer_id, :conversion_type, :conversion_id,
               :conversion_value, :converted_at, :window_hours, :is_first, :created_at)
            """,
            {
                "id": conv_id,
                "tenant_id": tenant_id,
                "touch_id": selected_touch_id,
                "customer_id": customer_id,
                "conversion_type": conversion_type,
                "conversion_id": conversion_id,
                "conversion_value": conversion_value,
                "converted_at": now,
                "window_hours": attribution_window_hours,
                "is_first": is_first,
                "created_at": created_at,
            },
        )

        log.info(
            "attribution_recorded",
            touch_id=selected_touch_id,
            conversion_type=conversion_type,
            conversion_id=str(conversion_id),
            conversion_value=conversion_value,
            model=model,
            is_first=is_first,
            tenant_id=str(tenant_id),
        )

        return AttributionConversion(
            id=conv_id,
            tenant_id=tenant_id,
            touch_id=selected_touch_id,
            customer_id=customer_id,
            conversion_type=conversion_type,
            conversion_id=conversion_id,
            conversion_value=conversion_value,
            converted_at=now,
            attribution_window_hours=attribution_window_hours,
            is_first_conversion=is_first,
            created_at=created_at,
        )

    # ------------------------------------------------------------------
    # E. 标记已送达
    # ------------------------------------------------------------------

    async def mark_delivered(
        self,
        touch_id: str,
        db: AsyncSession,
        delivered_at: Optional[datetime] = None,
    ) -> None:
        """更新触达的 delivered_at 时间戳（收到运营商/微信回调时调用）。"""
        ts = delivered_at or datetime.now(timezone.utc)
        await db.execute(
            """
            UPDATE touch_events
            SET delivered_at = :ts
            WHERE touch_id = :touch_id AND delivered_at IS NULL
            """,
            {"ts": ts, "touch_id": touch_id},
        )
        log.info("touch_marked_delivered", touch_id=touch_id)
