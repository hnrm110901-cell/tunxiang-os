"""直播活动服务 — 直播全生命周期管理 + 实时指标 + 经营仪表盘

核心流程：
  1. 创建活动（create_event） → scheduled
  2. 开播（start_event） → live，记录 started_at
  3. 更新实时指标（update_metrics） → 观看/点赞/评论
  4. 结束（end_event） → ended，汇总数据
  5. 取消（cancel_event） → cancelled

仪表盘：
  - 总场次 / 总观看 / 总营收 / 转化率
  - 分平台统计（微信视频号/抖音/快手/小红书）

金额单位：分(fen)
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 内部异常
# ---------------------------------------------------------------------------


class LiveStreamingError(Exception):
    """直播业务异常"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# 合法平台/状态
# ---------------------------------------------------------------------------

VALID_PLATFORMS = {"wechat_video", "douyin", "kuaishou", "xiaohongshu"}
VALID_STATUSES = {"scheduled", "live", "ended", "cancelled"}


# ---------------------------------------------------------------------------
# LiveStreamingService
# ---------------------------------------------------------------------------


class LiveStreamingService:
    """直播活动核心服务"""

    # ------------------------------------------------------------------
    # 创建直播活动
    # ------------------------------------------------------------------

    async def create_event(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        title: str,
        platform: str,
        scheduled_at: datetime,
        db: Any,
        *,
        description: Optional[str] = None,
        cover_image_url: Optional[str] = None,
        host_employee_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """创建直播活动

        Args:
            tenant_id: 租户ID
            store_id: 门店ID
            title: 直播标题
            platform: 平台 (wechat_video/douyin/kuaishou/xiaohongshu)
            scheduled_at: 计划开播时间
            db: AsyncSession
            description: 直播描述
            cover_image_url: 封面图URL
            host_employee_id: 主播员工ID

        Returns:
            {event_id, status}
        """
        if not title or not title.strip():
            raise LiveStreamingError("EMPTY_TITLE", "直播标题不能为空")
        if platform not in VALID_PLATFORMS:
            raise LiveStreamingError(
                "INVALID_PLATFORM",
                f"平台必须是 {', '.join(sorted(VALID_PLATFORMS))} 之一",
            )

        event_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        await db.execute(
            text("""
                INSERT INTO live_events (
                    id, tenant_id, store_id, platform, title,
                    description, cover_image_url, host_employee_id,
                    status, scheduled_at,
                    created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :store_id, :platform, :title,
                    :description, :cover_image_url, :host_employee_id,
                    'scheduled', :scheduled_at,
                    :now, :now
                )
            """),
            {
                "id": str(event_id),
                "tenant_id": str(tenant_id),
                "store_id": str(store_id),
                "platform": platform,
                "title": title.strip(),
                "description": description or "",
                "cover_image_url": cover_image_url,
                "host_employee_id": str(host_employee_id) if host_employee_id else None,
                "scheduled_at": scheduled_at,
                "now": now,
            },
        )
        await db.commit()

        log.info(
            "live_event.created",
            event_id=str(event_id),
            platform=platform,
            title=title,
            tenant_id=str(tenant_id),
        )

        return {"event_id": str(event_id), "status": "scheduled"}

    # ------------------------------------------------------------------
    # 开始直播
    # ------------------------------------------------------------------

    async def start_event(
        self,
        tenant_id: uuid.UUID,
        event_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """开始直播，将状态切换为 live

        Returns:
            {event_id, status, started_at}
        """
        now = datetime.now(timezone.utc)

        result = await db.execute(
            text("""
                UPDATE live_events
                SET status = 'live',
                    started_at = :now,
                    updated_at = :now
                WHERE id = :event_id
                  AND tenant_id = :tenant_id
                  AND status = 'scheduled'
                  AND is_deleted = false
                RETURNING id
            """),
            {
                "event_id": str(event_id),
                "tenant_id": str(tenant_id),
                "now": now,
            },
        )
        row = result.fetchone()
        if not row:
            raise LiveStreamingError(
                "EVENT_NOT_FOUND",
                "直播活动不存在或当前状态不允许开播",
            )

        await db.commit()

        log.info(
            "live_event.started",
            event_id=str(event_id),
            tenant_id=str(tenant_id),
        )

        return {
            "event_id": str(event_id),
            "status": "live",
            "started_at": now.isoformat(),
        }

    # ------------------------------------------------------------------
    # 结束直播
    # ------------------------------------------------------------------

    async def end_event(
        self,
        tenant_id: uuid.UUID,
        event_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """结束直播，汇总优惠券数据并更新营收

        Returns:
            {event_id, status, ended_at, summary}
        """
        now = datetime.now(timezone.utc)

        # 先汇总该直播的优惠券统计
        coupon_result = await db.execute(
            text("""
                SELECT
                    COALESCE(COUNT(*) FILTER (WHERE status IN ('claimed', 'redeemed')), 0) AS total_distributed,
                    COALESCE(COUNT(*) FILTER (WHERE status = 'redeemed'), 0) AS total_redeemed,
                    COALESCE(SUM(revenue_fen) FILTER (WHERE status = 'redeemed'), 0) AS total_revenue_fen
                FROM live_coupons
                WHERE live_event_id = :event_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = false
            """),
            {
                "event_id": str(event_id),
                "tenant_id": str(tenant_id),
            },
        )
        coupon_row = coupon_result.fetchone()

        total_distributed = coupon_row.total_distributed if coupon_row else 0
        total_redeemed = coupon_row.total_redeemed if coupon_row else 0
        total_revenue_fen = coupon_row.total_revenue_fen if coupon_row else 0

        result = await db.execute(
            text("""
                UPDATE live_events
                SET status = 'ended',
                    ended_at = :now,
                    coupon_total_distributed = :total_distributed,
                    coupon_total_redeemed = :total_redeemed,
                    revenue_attributed_fen = :total_revenue_fen,
                    updated_at = :now
                WHERE id = :event_id
                  AND tenant_id = :tenant_id
                  AND status = 'live'
                  AND is_deleted = false
                RETURNING id, viewer_count, peak_viewer_count, like_count, comment_count
            """),
            {
                "event_id": str(event_id),
                "tenant_id": str(tenant_id),
                "now": now,
                "total_distributed": total_distributed,
                "total_redeemed": total_redeemed,
                "total_revenue_fen": total_revenue_fen,
            },
        )
        row = result.fetchone()
        if not row:
            raise LiveStreamingError(
                "EVENT_NOT_FOUND",
                "直播活动不存在或当前状态不允许结束",
            )

        await db.commit()

        log.info(
            "live_event.ended",
            event_id=str(event_id),
            viewer_count=row.viewer_count,
            revenue_fen=total_revenue_fen,
            tenant_id=str(tenant_id),
        )

        return {
            "event_id": str(event_id),
            "status": "ended",
            "ended_at": now.isoformat(),
            "summary": {
                "viewer_count": row.viewer_count,
                "peak_viewer_count": row.peak_viewer_count,
                "like_count": row.like_count,
                "comment_count": row.comment_count,
                "coupon_total_distributed": total_distributed,
                "coupon_total_redeemed": total_redeemed,
                "revenue_attributed_fen": total_revenue_fen,
            },
        }

    # ------------------------------------------------------------------
    # 更新实时指标
    # ------------------------------------------------------------------

    async def update_metrics(
        self,
        tenant_id: uuid.UUID,
        event_id: uuid.UUID,
        db: Any,
        *,
        viewer_count: Optional[int] = None,
        like_count: Optional[int] = None,
        comment_count: Optional[int] = None,
        new_followers_count: Optional[int] = None,
    ) -> dict:
        """更新直播间实时指标

        Args:
            viewer_count: 当前观看人数
            like_count: 点赞数
            comment_count: 评论数
            new_followers_count: 新增粉丝数

        Returns:
            {event_id, updated_fields}
        """
        now = datetime.now(timezone.utc)

        set_clauses = ["updated_at = :now"]
        params: dict[str, Any] = {
            "event_id": str(event_id),
            "tenant_id": str(tenant_id),
            "now": now,
        }

        updated_fields: list[str] = []

        if viewer_count is not None:
            set_clauses.append("viewer_count = :viewer_count")
            set_clauses.append("peak_viewer_count = GREATEST(peak_viewer_count, :viewer_count)")
            params["viewer_count"] = viewer_count
            updated_fields.append("viewer_count")

        if like_count is not None:
            set_clauses.append("like_count = :like_count")
            params["like_count"] = like_count
            updated_fields.append("like_count")

        if comment_count is not None:
            set_clauses.append("comment_count = :comment_count")
            params["comment_count"] = comment_count
            updated_fields.append("comment_count")

        if new_followers_count is not None:
            set_clauses.append("new_followers_count = :new_followers_count")
            params["new_followers_count"] = new_followers_count
            updated_fields.append("new_followers_count")

        if not updated_fields:
            raise LiveStreamingError("NO_METRICS", "至少需要提供一个指标进行更新")

        sql = f"""
            UPDATE live_events
            SET {", ".join(set_clauses)}
            WHERE id = :event_id
              AND tenant_id = :tenant_id
              AND status = 'live'
              AND is_deleted = false
            RETURNING id
        """

        result = await db.execute(text(sql), params)
        row = result.fetchone()
        if not row:
            raise LiveStreamingError(
                "EVENT_NOT_FOUND",
                "直播活动不存在或未在直播中",
            )

        await db.commit()

        log.info(
            "live_event.metrics_updated",
            event_id=str(event_id),
            updated_fields=updated_fields,
            tenant_id=str(tenant_id),
        )

        return {"event_id": str(event_id), "updated_fields": updated_fields}

    # ------------------------------------------------------------------
    # 获取单个活动详情
    # ------------------------------------------------------------------

    async def get_event(
        self,
        tenant_id: uuid.UUID,
        event_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """获取直播活动详情

        Returns:
            活动完整信息字典
        """
        result = await db.execute(
            text("""
                SELECT
                    id, tenant_id, store_id, platform, live_room_id,
                    title, description, cover_image_url, host_employee_id,
                    status, scheduled_at, started_at, ended_at,
                    viewer_count, peak_viewer_count, like_count, comment_count,
                    coupon_total_distributed, coupon_total_redeemed,
                    revenue_attributed_fen, new_followers_count,
                    recording_url, created_at, updated_at
                FROM live_events
                WHERE id = :event_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = false
            """),
            {
                "event_id": str(event_id),
                "tenant_id": str(tenant_id),
            },
        )
        row = result.fetchone()
        if not row:
            raise LiveStreamingError("EVENT_NOT_FOUND", "直播活动不存在")

        return {
            "event_id": str(row.id),
            "store_id": str(row.store_id) if row.store_id else None,
            "platform": row.platform,
            "live_room_id": row.live_room_id,
            "title": row.title,
            "description": row.description,
            "cover_image_url": row.cover_image_url,
            "host_employee_id": str(row.host_employee_id) if row.host_employee_id else None,
            "status": row.status,
            "scheduled_at": row.scheduled_at.isoformat() if row.scheduled_at else None,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "ended_at": row.ended_at.isoformat() if row.ended_at else None,
            "viewer_count": row.viewer_count,
            "peak_viewer_count": row.peak_viewer_count,
            "like_count": row.like_count,
            "comment_count": row.comment_count,
            "coupon_total_distributed": row.coupon_total_distributed,
            "coupon_total_redeemed": row.coupon_total_redeemed,
            "revenue_attributed_fen": row.revenue_attributed_fen,
            "new_followers_count": row.new_followers_count,
            "recording_url": row.recording_url,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    # ------------------------------------------------------------------
    # 列表查询（分页）
    # ------------------------------------------------------------------

    async def list_events(
        self,
        tenant_id: uuid.UUID,
        db: Any,
        *,
        status: Optional[str] = None,
        platform: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页查询直播活动列表

        Args:
            status: 状态筛选
            platform: 平台筛选
            page: 页码(从1开始)
            size: 每页条数

        Returns:
            {items: [...], total: int}
        """
        where_clauses = [
            "tenant_id = :tenant_id",
            "is_deleted = false",
        ]
        params: dict[str, Any] = {"tenant_id": str(tenant_id)}

        if status:
            if status not in VALID_STATUSES:
                raise LiveStreamingError("INVALID_STATUS", f"状态必须是 {', '.join(sorted(VALID_STATUSES))} 之一")
            where_clauses.append("status = :status")
            params["status"] = status

        if platform:
            if platform not in VALID_PLATFORMS:
                raise LiveStreamingError("INVALID_PLATFORM", f"平台必须是 {', '.join(sorted(VALID_PLATFORMS))} 之一")
            where_clauses.append("platform = :platform")
            params["platform"] = platform

        where_sql = " AND ".join(where_clauses)

        # 计算总数
        count_result = await db.execute(
            text(f"SELECT COUNT(*) AS cnt FROM live_events WHERE {where_sql}"),
            params,
        )
        total = count_result.fetchone().cnt

        # 查询分页数据
        offset = (page - 1) * size
        params["limit"] = size
        params["offset"] = offset

        result = await db.execute(
            text(f"""
                SELECT
                    id, store_id, platform, title, status,
                    scheduled_at, started_at, ended_at,
                    viewer_count, peak_viewer_count,
                    revenue_attributed_fen, created_at
                FROM live_events
                WHERE {where_sql}
                ORDER BY scheduled_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = result.fetchall()

        items = [
            {
                "event_id": str(r.id),
                "store_id": str(r.store_id) if r.store_id else None,
                "platform": r.platform,
                "title": r.title,
                "status": r.status,
                "scheduled_at": r.scheduled_at.isoformat() if r.scheduled_at else None,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "ended_at": r.ended_at.isoformat() if r.ended_at else None,
                "viewer_count": r.viewer_count,
                "peak_viewer_count": r.peak_viewer_count,
                "revenue_attributed_fen": r.revenue_attributed_fen,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

        return {"items": items, "total": total}

    # ------------------------------------------------------------------
    # 经营仪表盘
    # ------------------------------------------------------------------

    async def get_live_dashboard(
        self,
        tenant_id: uuid.UUID,
        db: Any,
        *,
        days: int = 30,
    ) -> dict:
        """直播经营仪表盘

        Returns:
            {
                total_events, total_viewers, total_revenue_fen,
                conversion_rate, per_platform: [...]
            }
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)

        # 总体统计
        result = await db.execute(
            text("""
                SELECT
                    COUNT(*)                                        AS total_events,
                    COALESCE(SUM(viewer_count), 0)                  AS total_viewers,
                    COALESCE(SUM(revenue_attributed_fen), 0)        AS total_revenue_fen,
                    COALESCE(SUM(coupon_total_distributed), 0)      AS total_distributed,
                    COALESCE(SUM(coupon_total_redeemed), 0)         AS total_redeemed
                FROM live_events
                WHERE tenant_id = :tenant_id
                  AND is_deleted = false
                  AND status IN ('live', 'ended')
                  AND scheduled_at >= :since
            """),
            {"tenant_id": str(tenant_id), "since": since},
        )
        row = result.fetchone()

        total_distributed = row.total_distributed if row else 0
        total_redeemed = row.total_redeemed if row else 0
        conversion_rate = round(total_redeemed / total_distributed, 4) if total_distributed > 0 else 0.0

        # 分平台统计
        platform_result = await db.execute(
            text("""
                SELECT
                    platform,
                    COUNT(*)                                    AS event_count,
                    COALESCE(SUM(viewer_count), 0)              AS viewers,
                    COALESCE(SUM(revenue_attributed_fen), 0)    AS revenue_fen
                FROM live_events
                WHERE tenant_id = :tenant_id
                  AND is_deleted = false
                  AND status IN ('live', 'ended')
                  AND scheduled_at >= :since
                GROUP BY platform
                ORDER BY revenue_fen DESC
            """),
            {"tenant_id": str(tenant_id), "since": since},
        )
        platform_rows = platform_result.fetchall()

        per_platform = [
            {
                "platform": p.platform,
                "event_count": p.event_count,
                "viewers": p.viewers,
                "revenue_fen": p.revenue_fen,
            }
            for p in platform_rows
        ]

        return {
            "days": days,
            "total_events": row.total_events if row else 0,
            "total_viewers": row.total_viewers if row else 0,
            "total_revenue_fen": row.total_revenue_fen if row else 0,
            "total_distributed": total_distributed,
            "total_redeemed": total_redeemed,
            "conversion_rate": conversion_rate,
            "per_platform": per_platform,
        }

    # ------------------------------------------------------------------
    # 取消直播
    # ------------------------------------------------------------------

    async def cancel_event(
        self,
        tenant_id: uuid.UUID,
        event_id: uuid.UUID,
        db: Any,
    ) -> dict:
        """取消直播活动（仅 scheduled 状态可取消）

        Returns:
            {event_id, status}
        """
        now = datetime.now(timezone.utc)

        result = await db.execute(
            text("""
                UPDATE live_events
                SET status = 'cancelled',
                    updated_at = :now
                WHERE id = :event_id
                  AND tenant_id = :tenant_id
                  AND status = 'scheduled'
                  AND is_deleted = false
                RETURNING id
            """),
            {
                "event_id": str(event_id),
                "tenant_id": str(tenant_id),
                "now": now,
            },
        )
        row = result.fetchone()
        if not row:
            raise LiveStreamingError(
                "EVENT_NOT_FOUND",
                "直播活动不存在或当前状态不允许取消",
            )

        await db.commit()

        log.info(
            "live_event.cancelled",
            event_id=str(event_id),
            tenant_id=str(tenant_id),
        )

        return {"event_id": str(event_id), "status": "cancelled"}
