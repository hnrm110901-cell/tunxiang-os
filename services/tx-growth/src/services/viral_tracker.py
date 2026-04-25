"""裂变链路追踪服务 — 分享链接生成 + 点击/转化记录 + 链路树 + 统计

核心流程：
  1. 分享者生成短链（create_share_link） → 8位hex短码
  2. 浏览者点击短链（record_click） → 记录viewer + clicked_at
  3. 浏览者下单转化（record_conversion） → 记录订单+金额
  4. 裂变链路追踪（get_viral_chain） → A→B→C深度链路
  5. 统计仪表盘（get_viral_stats） → 分享数/点击数/转化数/收入

短码生成规则：uuid4().hex[:8]（8位十六进制）
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


class ViralTrackerError(Exception):
    """裂变追踪业务异常"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# ViralTracker
# ---------------------------------------------------------------------------


class ViralTracker:
    """裂变链路追踪核心服务"""

    # ------------------------------------------------------------------
    # 创建分享链接
    # ------------------------------------------------------------------

    async def create_share_link(
        self,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        ugc_id: Optional[uuid.UUID],
        channel: str,
        db: Any,
        *,
        campaign_id: Optional[uuid.UUID] = None,
        parent_chain_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """生成分享短链并插入viral_invite_chains

        Args:
            tenant_id: 租户ID
            customer_id: 分享者顾客ID
            ugc_id: 关联UGC ID（可选）
            channel: 分享渠道(wechat/moments/wecom/douyin/xiaohongshu/link)
            db: AsyncSession
            campaign_id: 关联活动ID（可选）
            parent_chain_id: 父级链路ID（用于二次转发追踪）

        Returns:
            {chain_id, share_link_code, depth}
        """
        chain_id = uuid.uuid4()
        share_link_code = uuid.uuid4().hex[:8]

        # 计算链路深度
        depth = 0
        if parent_chain_id:
            parent_result = await db.execute(
                text("""
                    SELECT depth FROM viral_invite_chains
                    WHERE id = :parent_id
                      AND tenant_id = :tenant_id
                      AND is_deleted = false
                """),
                {"parent_id": str(parent_chain_id), "tenant_id": str(tenant_id)},
            )
            parent_row = parent_result.fetchone()
            if parent_row:
                depth = parent_row.depth + 1

        now = datetime.now(timezone.utc)

        await db.execute(
            text("""
                INSERT INTO viral_invite_chains (
                    id, tenant_id, ugc_id, campaign_id,
                    sharer_customer_id, share_channel, share_link_code,
                    depth, parent_chain_id,
                    created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :ugc_id, :campaign_id,
                    :sharer_customer_id, :share_channel, :share_link_code,
                    :depth, :parent_chain_id,
                    :now, :now
                )
            """),
            {
                "id": str(chain_id),
                "tenant_id": str(tenant_id),
                "ugc_id": str(ugc_id) if ugc_id else None,
                "campaign_id": str(campaign_id) if campaign_id else None,
                "sharer_customer_id": str(customer_id),
                "share_channel": channel,
                "share_link_code": share_link_code,
                "depth": depth,
                "parent_chain_id": str(parent_chain_id) if parent_chain_id else None,
                "now": now,
            },
        )
        await db.commit()

        log.info(
            "viral.share_link_created",
            chain_id=str(chain_id),
            share_link_code=share_link_code,
            channel=channel,
            depth=depth,
            tenant_id=str(tenant_id),
        )

        return {
            "chain_id": str(chain_id),
            "share_link_code": share_link_code,
            "depth": depth,
        }

    # ------------------------------------------------------------------
    # 记录点击
    # ------------------------------------------------------------------

    async def record_click(
        self,
        share_link_code: str,
        viewer_customer_id: Optional[uuid.UUID],
        db: Any,
    ) -> dict:
        """记录分享链接被点击

        Returns:
            {chain_id, share_link_code, clicked_at}
        """
        now = datetime.now(timezone.utc)

        result = await db.execute(
            text("""
                UPDATE viral_invite_chains
                SET clicked_at = COALESCE(clicked_at, :now),
                    viewer_customer_id = COALESCE(viewer_customer_id, :viewer_id),
                    updated_at = :now
                WHERE share_link_code = :code
                  AND is_deleted = false
                RETURNING id, tenant_id, sharer_customer_id
            """),
            {
                "code": share_link_code,
                "viewer_id": str(viewer_customer_id) if viewer_customer_id else None,
                "now": now,
            },
        )
        row = result.fetchone()
        if not row:
            raise ViralTrackerError("LINK_NOT_FOUND", "分享链接不存在")

        await db.commit()

        log.info(
            "viral.link_clicked",
            chain_id=str(row.id),
            share_link_code=share_link_code,
            viewer_customer_id=str(viewer_customer_id) if viewer_customer_id else None,
            tenant_id=str(row.tenant_id),
        )

        return {
            "chain_id": str(row.id),
            "share_link_code": share_link_code,
            "clicked_at": now.isoformat(),
        }

    # ------------------------------------------------------------------
    # 记录转化
    # ------------------------------------------------------------------

    async def record_conversion(
        self,
        share_link_code: str,
        order_id: uuid.UUID,
        revenue_fen: int,
        db: Any,
    ) -> dict:
        """记录分享链接带来的订单转化

        Returns:
            {chain_id, converted_order_id, converted_revenue_fen}
        """
        now = datetime.now(timezone.utc)

        result = await db.execute(
            text("""
                UPDATE viral_invite_chains
                SET converted_order_id = :order_id,
                    converted_revenue_fen = :revenue_fen,
                    converted_at = :now,
                    viewer_registered = true,
                    updated_at = :now
                WHERE share_link_code = :code
                  AND is_deleted = false
                RETURNING id, tenant_id, sharer_customer_id
            """),
            {
                "code": share_link_code,
                "order_id": str(order_id),
                "revenue_fen": revenue_fen,
                "now": now,
            },
        )
        row = result.fetchone()
        if not row:
            raise ViralTrackerError("LINK_NOT_FOUND", "分享链接不存在")

        await db.commit()

        log.info(
            "viral.conversion_recorded",
            chain_id=str(row.id),
            share_link_code=share_link_code,
            order_id=str(order_id),
            revenue_fen=revenue_fen,
            tenant_id=str(row.tenant_id),
        )

        return {
            "chain_id": str(row.id),
            "converted_order_id": str(order_id),
            "converted_revenue_fen": revenue_fen,
        }

    # ------------------------------------------------------------------
    # 裂变链路树
    # ------------------------------------------------------------------

    async def get_viral_chain(
        self,
        tenant_id: uuid.UUID,
        ugc_id: uuid.UUID,
        db: Any,
    ) -> list[dict]:
        """获取UGC对应的完整裂变链路树（A→B→C）

        Returns:
            [{chain_id, sharer, viewer, depth, clicked, converted, children: [...]}]
        """
        result = await db.execute(
            text("""
                SELECT id, sharer_customer_id, viewer_customer_id,
                       share_channel, share_link_code, depth,
                       parent_chain_id, clicked_at, converted_at,
                       converted_revenue_fen, viewer_registered
                FROM viral_invite_chains
                WHERE tenant_id = :tenant_id
                  AND ugc_id = :ugc_id
                  AND is_deleted = false
                ORDER BY depth ASC, created_at ASC
            """),
            {"tenant_id": str(tenant_id), "ugc_id": str(ugc_id)},
        )
        rows = result.fetchall()

        # 构建树结构
        nodes: dict[str, dict] = {}
        roots: list[dict] = []

        for r in rows:
            node = {
                "chain_id": str(r.id),
                "sharer_customer_id": str(r.sharer_customer_id),
                "viewer_customer_id": str(r.viewer_customer_id) if r.viewer_customer_id else None,
                "share_channel": r.share_channel,
                "share_link_code": r.share_link_code,
                "depth": r.depth,
                "clicked_at": r.clicked_at.isoformat() if r.clicked_at else None,
                "converted_at": r.converted_at.isoformat() if r.converted_at else None,
                "converted_revenue_fen": r.converted_revenue_fen or 0,
                "viewer_registered": r.viewer_registered or False,
                "children": [],
            }
            nodes[str(r.id)] = node

            parent_id = str(r.parent_chain_id) if r.parent_chain_id else None
            if parent_id and parent_id in nodes:
                nodes[parent_id]["children"].append(node)
            else:
                roots.append(node)

        return roots

    # ------------------------------------------------------------------
    # 裂变统计
    # ------------------------------------------------------------------

    async def get_viral_stats(
        self,
        tenant_id: uuid.UUID,
        db: Any,
        *,
        days: int = 30,
    ) -> dict:
        """裂变统计仪表盘

        Returns:
            {total_shares, total_clicks, total_conversions,
             total_revenue_fen, avg_chain_depth, conversion_rate}
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)

        result = await db.execute(
            text("""
                SELECT
                    COUNT(*) AS total_shares,
                    COUNT(clicked_at) AS total_clicks,
                    COUNT(converted_order_id) AS total_conversions,
                    COALESCE(SUM(converted_revenue_fen), 0) AS total_revenue_fen,
                    COALESCE(AVG(depth), 0) AS avg_chain_depth
                FROM viral_invite_chains
                WHERE tenant_id = :tenant_id
                  AND created_at >= :since
                  AND is_deleted = false
            """),
            {"tenant_id": str(tenant_id), "since": since},
        )
        row = result.fetchone()

        total_shares = row.total_shares or 0
        total_clicks = row.total_clicks or 0
        total_conversions = row.total_conversions or 0
        total_revenue_fen = int(row.total_revenue_fen or 0)
        avg_chain_depth = round(float(row.avg_chain_depth or 0), 2)

        conversion_rate = round(total_conversions / total_clicks, 4) if total_clicks > 0 else 0.0

        return {
            "total_shares": total_shares,
            "total_clicks": total_clicks,
            "total_conversions": total_conversions,
            "total_revenue_fen": total_revenue_fen,
            "avg_chain_depth": avg_chain_depth,
            "conversion_rate": conversion_rate,
            "days": days,
        }

    # ------------------------------------------------------------------
    # 分享排行榜
    # ------------------------------------------------------------------

    async def get_top_sharers(
        self,
        tenant_id: uuid.UUID,
        db: Any,
        *,
        limit: int = 20,
    ) -> list[dict]:
        """分享转化排行榜（按转化数排名）

        Returns:
            [{rank, sharer_customer_id, total_shares, total_clicks,
              total_conversions, total_revenue_fen}]
        """
        result = await db.execute(
            text("""
                SELECT
                    sharer_customer_id,
                    COUNT(*) AS total_shares,
                    COUNT(clicked_at) AS total_clicks,
                    COUNT(converted_order_id) AS total_conversions,
                    COALESCE(SUM(converted_revenue_fen), 0) AS total_revenue_fen
                FROM viral_invite_chains
                WHERE tenant_id = :tenant_id
                  AND is_deleted = false
                GROUP BY sharer_customer_id
                ORDER BY total_conversions DESC, total_revenue_fen DESC
                LIMIT :limit
            """),
            {"tenant_id": str(tenant_id), "limit": limit},
        )
        rows = result.fetchall()

        return [
            {
                "rank": idx + 1,
                "sharer_customer_id": str(r.sharer_customer_id),
                "total_shares": r.total_shares,
                "total_clicks": r.total_clicks,
                "total_conversions": r.total_conversions,
                "total_revenue_fen": int(r.total_revenue_fen or 0),
            }
            for idx, r in enumerate(rows)
        ]
