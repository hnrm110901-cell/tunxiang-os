"""小红书团购券核销适配器

核销流程：
  1. POS 扫码 → 获取券码
  2. 调用小红书 API 验证券码有效性
  3. 写入核销记录到 xhs_coupon_verifications
  4. 关联屯象订单
  5. 每日批量对账

金额单位：分(fen)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .xhs_client import XHSClient

logger = structlog.get_logger(__name__)


class XHSCouponAdapter:
    """小红书团购券核销适配器"""

    def __init__(self, app_id: str, app_secret: str) -> None:
        self.client = XHSClient(app_id=app_id, app_secret=app_secret)

    async def verify_and_record(
        self,
        coupon_code: str,
        store_id: str,
        order_id: str,
        verified_by: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """核销并记录

        Args:
            coupon_code: 小红书团购券码
            store_id: 核销门店ID
            order_id: 关联的屯象订单ID
            verified_by: 操作员ID
            tenant_id: 租户ID
            db: 数据库会话
        """
        tid = uuid.UUID(tenant_id)
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        # 1. 检查是否已核销
        dup = await db.execute(
            text("""
                SELECT id FROM xhs_coupon_verifications
                WHERE coupon_code = :code AND is_deleted = false
            """),
            {"code": coupon_code},
        )
        if dup.fetchone():
            return {"verified": False, "error": "coupon_already_verified"}

        # 2. 查询小红书 POI 映射
        poi_row = await db.execute(
            text("""
                SELECT xhs_poi_id FROM xhs_poi_mappings
                WHERE tenant_id = :tid AND store_id = :sid AND is_deleted = false
            """),
            {"tid": tid, "sid": uuid.UUID(store_id)},
        )
        poi = poi_row.fetchone()
        xhs_shop_id = poi.xhs_poi_id if poi else ""

        # 3. 调用小红书 API 核销
        verify_result = await self.client.verify_coupon(coupon_code, xhs_shop_id)
        if not verify_result.get("verified"):
            return {
                "verified": False,
                "error": verify_result.get("error", "xhs_verify_failed"),
            }

        coupon_info = verify_result.get("coupon_info", {})
        now = datetime.now(timezone.utc)

        # 4. 写入核销记录
        record_id = uuid.uuid4()
        await db.execute(
            text("""
                INSERT INTO xhs_coupon_verifications
                    (id, tenant_id, store_id, order_id, coupon_code, coupon_type,
                     original_fen, paid_fen, platform_fee_fen, settle_fen,
                     status, xhs_order_id, xhs_verify_time, verified_by,
                     created_at, updated_at)
                VALUES
                    (:id, :tid, :sid, :oid, :code, :ctype,
                     :orig, :paid, :fee, :settle,
                     'verified', :xhs_oid, :now, :vby,
                     :now, :now)
            """),
            {
                "id": record_id,
                "tid": tid,
                "sid": uuid.UUID(store_id),
                "oid": uuid.UUID(order_id) if order_id else None,
                "code": coupon_code,
                "ctype": coupon_info.get("type", "group_buy"),
                "orig": coupon_info.get("original_fen", 0),
                "paid": coupon_info.get("paid_fen", 0),
                "fee": coupon_info.get("platform_fee_fen", 0),
                "settle": coupon_info.get("settle_fen", 0),
                "xhs_oid": coupon_info.get("xhs_order_id", ""),
                "now": now,
                "vby": uuid.UUID(verified_by) if verified_by else None,
            },
        )
        await db.flush()

        logger.info(
            "xhs.coupon_verified",
            coupon_code=coupon_code,
            store_id=store_id,
            record_id=str(record_id),
        )
        return {
            "verified": True,
            "record_id": str(record_id),
            "coupon_code": coupon_code,
            "coupon_info": coupon_info,
        }

    async def list_verifications(
        self,
        store_id: str,
        tenant_id: str,
        db: AsyncSession,
        status: str = "verified",
        page: int = 1,
        size: int = 20,
    ) -> dict[str, Any]:
        """查询核销记录"""
        tid = uuid.UUID(tenant_id)
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )
        offset = (page - 1) * size

        rows = await db.execute(
            text("""
                SELECT id, coupon_code, coupon_type, original_fen, paid_fen,
                       settle_fen, status, xhs_order_id, xhs_verify_time, created_at
                FROM xhs_coupon_verifications
                WHERE tenant_id = :tid AND store_id = :sid AND status = :status
                  AND is_deleted = false
                ORDER BY created_at DESC
                LIMIT :lim OFFSET :off
            """),
            {
                "tid": tid,
                "sid": uuid.UUID(store_id),
                "status": status,
                "lim": size,
                "off": offset,
            },
        )

        items = [
            {
                "record_id": str(r.id),
                "coupon_code": r.coupon_code,
                "original_fen": r.original_fen,
                "paid_fen": r.paid_fen,
                "settle_fen": r.settle_fen,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
        return {"items": items, "page": page, "size": size}
