"""身份解析引擎 — S2W5 CDP多源数据融合

支持三种匹配策略：
1. phone_hash 精确匹配（置信度 1.0）
2. 时间关联匹配 — WiFi到店时间与订单时间重叠（置信度 0.6-0.9）
3. 手动匹配（管理后台人工指定）

批量解析：定时任务（nightly batch）遍历所有未匹配记录
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# 时间关联窗口：WiFi 访问时间与订单时间的最大差距
TIME_CORRELATION_WINDOW_HOURS = 2


class IdentityResolver:
    """多源身份解析"""

    async def resolve_wifi_visit(
        self,
        tenant_id: str,
        wifi_visit_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """
        解析单条WiFi访问记录的身份：
        1. 先尝试 phone_hash 精确匹配（通过 mac_hash 历史关联）
        2. 再尝试时间关联：同门店、时间窗口内有订单的已知客户
        """
        # 获取WiFi访问记录
        row = await db.execute(
            text("""
                SELECT id, store_id, mac_hash, first_seen_at, last_seen_at,
                       matched_customer_id
                FROM wifi_visit_logs
                WHERE id = :vid AND tenant_id = :tid AND is_deleted = false
            """),
            {"vid": wifi_visit_id, "tid": tenant_id},
        )
        visit = row.mappings().first()
        if not visit:
            raise ValueError(f"WiFi visit {wifi_visit_id} not found")

        if visit["matched_customer_id"]:
            return {
                "visit_id": wifi_visit_id,
                "already_matched": True,
                "customer_id": str(visit["matched_customer_id"]),
            }

        store_id = str(visit["store_id"])
        mac_hash = visit["mac_hash"]
        first_seen = visit["first_seen_at"]

        # 策略1: 查找同mac_hash的历史已匹配记录 → phone_hash 精确匹配
        prev = await db.execute(
            text("""
                SELECT matched_customer_id
                FROM wifi_visit_logs
                WHERE tenant_id = :tid AND mac_hash = :mh
                  AND matched_customer_id IS NOT NULL
                  AND is_deleted = false
                ORDER BY last_seen_at DESC
                LIMIT 1
            """),
            {"tid": tenant_id, "mh": mac_hash},
        )
        prev_match = prev.mappings().first()
        if prev_match:
            customer_id = str(prev_match["matched_customer_id"])
            await self._update_wifi_match(
                db,
                wifi_visit_id,
                customer_id,
                1.0,
                "phone_hash",
            )
            logger.info(
                "identity.wifi_phone_hash_match",
                tenant_id=tenant_id,
                visit_id=wifi_visit_id,
                customer_id=customer_id,
            )
            return {
                "visit_id": wifi_visit_id,
                "matched": True,
                "customer_id": customer_id,
                "confidence": 1.0,
                "method": "phone_hash",
            }

        # 策略2: 时间关联 — 同门店、同时间段内有订单的客户
        window_start = first_seen - timedelta(hours=TIME_CORRELATION_WINDOW_HOURS)
        window_end = first_seen + timedelta(hours=TIME_CORRELATION_WINDOW_HOURS)

        corr = await db.execute(
            text("""
                SELECT o.customer_id, COUNT(*)::int AS order_count
                FROM orders o
                WHERE o.tenant_id = :tid AND o.store_id = :sid
                  AND o.created_at >= :ws AND o.created_at <= :we
                  AND o.customer_id IS NOT NULL
                  AND o.is_deleted = false AND o.status = 'paid'
                GROUP BY o.customer_id
                ORDER BY order_count DESC
                LIMIT 1
            """),
            {
                "tid": tenant_id,
                "sid": store_id,
                "ws": window_start,
                "we": window_end,
            },
        )
        corr_match = corr.mappings().first()
        if corr_match:
            customer_id = str(corr_match["customer_id"])
            # 置信度基于订单数量：1单=0.6, 2单=0.75, 3+单=0.9
            order_count = corr_match["order_count"]
            if order_count >= 3:
                confidence = 0.9
            elif order_count >= 2:
                confidence = 0.75
            else:
                confidence = 0.6

            await self._update_wifi_match(
                db,
                wifi_visit_id,
                customer_id,
                confidence,
                "mac_correlation",
            )
            logger.info(
                "identity.wifi_time_correlation",
                tenant_id=tenant_id,
                visit_id=wifi_visit_id,
                customer_id=customer_id,
                confidence=confidence,
            )
            return {
                "visit_id": wifi_visit_id,
                "matched": True,
                "customer_id": customer_id,
                "confidence": confidence,
                "method": "mac_correlation",
            }

        return {"visit_id": wifi_visit_id, "matched": False}

    async def resolve_external_order(
        self,
        tenant_id: str,
        import_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """
        解析外部订单的身份 — 通过 phone_hash 与 golden_id 映射精确匹配
        """
        row = await db.execute(
            text("""
                SELECT id, customer_phone_hash, matched_customer_id, source
                FROM external_order_imports
                WHERE id = :iid AND tenant_id = :tid AND is_deleted = false
            """),
            {"iid": import_id, "tid": tenant_id},
        )
        imp = row.mappings().first()
        if not imp:
            raise ValueError(f"External order import {import_id} not found")

        if imp["matched_customer_id"]:
            return {
                "import_id": import_id,
                "already_matched": True,
                "customer_id": str(imp["matched_customer_id"]),
            }

        phone_hash = imp["customer_phone_hash"]
        if not phone_hash:
            return {"import_id": import_id, "matched": False, "reason": "no_phone_hash"}

        # 通过 golden_id 映射查找 phone_hash 对应的 customer
        cust = await db.execute(
            text("""
                SELECT customer_id
                FROM golden_id_mappings
                WHERE tenant_id = :tid
                  AND channel_type = 'phone_hash'
                  AND channel_openid = :ph
                  AND is_deleted = false
                LIMIT 1
            """),
            {"tid": tenant_id, "ph": phone_hash},
        )
        match = cust.mappings().first()
        if match:
            customer_id = str(match["customer_id"])
            await db.execute(
                text("""
                    UPDATE external_order_imports
                    SET matched_customer_id = :cid,
                        match_confidence = 1.0,
                        updated_at = NOW()
                    WHERE id = :iid
                """),
                {"cid": customer_id, "iid": import_id},
            )
            await db.commit()
            logger.info(
                "identity.external_phone_hash_match",
                tenant_id=tenant_id,
                import_id=import_id,
                customer_id=customer_id,
                source=imp["source"],
            )
            return {
                "import_id": import_id,
                "matched": True,
                "customer_id": customer_id,
                "confidence": 1.0,
                "method": "phone_hash",
            }

        return {"import_id": import_id, "matched": False, "reason": "phone_hash_not_found"}

    async def batch_resolve(
        self,
        tenant_id: str,
        db: AsyncSession,
        source: str = "wifi",
    ) -> dict[str, Any]:
        """批量解析所有未匹配记录"""
        resolved = 0
        failed = 0

        if source == "wifi":
            rows = await db.execute(
                text("""
                    SELECT id FROM wifi_visit_logs
                    WHERE tenant_id = :tid
                      AND matched_customer_id IS NULL
                      AND is_deleted = false
                    ORDER BY created_at DESC
                    LIMIT 1000
                """),
                {"tid": tenant_id},
            )
            ids = [str(r["id"]) for r in rows.mappings().all()]
            for vid in ids:
                try:
                    result = await self.resolve_wifi_visit(tenant_id, vid, db)
                    if result.get("matched") or result.get("already_matched"):
                        resolved += 1
                    else:
                        failed += 1
                except (ValueError, RuntimeError) as exc:
                    logger.warning("identity.batch_wifi_error", visit_id=vid, error=str(exc))
                    failed += 1

        elif source == "external":
            rows = await db.execute(
                text("""
                    SELECT id FROM external_order_imports
                    WHERE tenant_id = :tid
                      AND matched_customer_id IS NULL
                      AND is_deleted = false
                    ORDER BY created_at DESC
                    LIMIT 1000
                """),
                {"tid": tenant_id},
            )
            ids = [str(r["id"]) for r in rows.mappings().all()]
            for iid in ids:
                try:
                    result = await self.resolve_external_order(tenant_id, iid, db)
                    if result.get("matched") or result.get("already_matched"):
                        resolved += 1
                    else:
                        failed += 1
                except (ValueError, RuntimeError) as exc:
                    logger.warning("identity.batch_ext_error", import_id=iid, error=str(exc))
                    failed += 1

        logger.info(
            "identity.batch_resolve_done",
            tenant_id=tenant_id,
            source=source,
            resolved=resolved,
            failed=failed,
        )
        return {"source": source, "resolved": resolved, "unmatched": failed, "total": resolved + failed}

    async def get_coverage_stats(
        self,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """各数据源的身份匹配率统计"""
        # WiFi 匹配率
        wifi = await db.execute(
            text("""
                SELECT
                    COUNT(*)::int AS total,
                    COUNT(*) FILTER (WHERE matched_customer_id IS NOT NULL)::int AS matched
                FROM wifi_visit_logs
                WHERE tenant_id = :tid AND is_deleted = false
            """),
            {"tid": tenant_id},
        )
        w = wifi.mappings().first()
        wifi_total = w["total"] if w else 0
        wifi_matched = w["matched"] if w else 0

        # 外部订单按 source 分组
        ext = await db.execute(
            text("""
                SELECT source,
                    COUNT(*)::int AS total,
                    COUNT(*) FILTER (WHERE matched_customer_id IS NOT NULL)::int AS matched
                FROM external_order_imports
                WHERE tenant_id = :tid AND is_deleted = false
                GROUP BY source
            """),
            {"tid": tenant_id},
        )
        ext_rows = ext.mappings().all()

        sources: dict[str, Any] = {
            "wifi": {
                "total": wifi_total,
                "matched": wifi_matched,
                "match_rate": round(wifi_matched / max(wifi_total, 1) * 100, 1),
            },
        }
        for r in ext_rows:
            sources[r["source"]] = {
                "total": r["total"],
                "matched": r["matched"],
                "match_rate": round(r["matched"] / max(r["total"], 1) * 100, 1),
            }

        return sources

    async def _update_wifi_match(
        self,
        db: AsyncSession,
        visit_id: str,
        customer_id: str,
        confidence: float,
        method: str,
    ) -> None:
        await db.execute(
            text("""
                UPDATE wifi_visit_logs
                SET matched_customer_id = :cid,
                    match_confidence = :conf,
                    match_method = :method,
                    is_new_visitor = false,
                    updated_at = NOW()
                WHERE id = :vid
            """),
            {"cid": customer_id, "conf": confidence, "method": method, "vid": visit_id},
        )
        await db.commit()
