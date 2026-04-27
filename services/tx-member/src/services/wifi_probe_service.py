"""WiFi探针服务 — S2W5

采集门店WiFi AP上报的MAC地址探针数据，哈希存储后进行：
- OUI厂商识别（简化前缀映射）
- 访问会话合并（30分钟窗口内视为同一次访问）
- 到店热力图统计（按小时分布）
- 访问概览（总访次/独立MAC/匹配率/平均停留）
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ── OUI 厂商前缀映射（简化版） ─────────────────────────────────────────────────

OUI_VENDORS: dict[str, str] = {
    "00:1A:11": "Google",
    "3C:06:30": "Apple",
    "AC:CF:85": "Huawei",
    "00:26:AB": "Samsung",
    "00:1E:8C": "Xiaomi",
    "F4:F5:D8": "Google",
    "A4:83:E7": "Apple",
    "DC:A6:32": "Raspberry Pi",
}

# 30分钟内的重复探测视为同一次访问
SESSION_MERGE_WINDOW_SEC = 30 * 60


def _hash_mac(mac_address: str) -> str:
    """SHA-256 哈希 MAC 地址，绝不存储明文"""
    normalized = mac_address.strip().upper()
    return hashlib.sha256(normalized.encode()).hexdigest()


def _detect_vendor(mac_address: str) -> str | None:
    """根据 OUI 前缀检测设备厂商"""
    normalized = mac_address.strip().upper()
    prefix = normalized[:8]  # "XX:XX:XX"
    return OUI_VENDORS.get(prefix)


class WiFiProbeService:
    """WiFi探针数据采集与分析"""

    async def ingest_probe(
        self,
        tenant_id: str,
        store_id: str,
        mac_address: str,
        signal_strength: int | None,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """
        处理单条探针数据：
        1. 哈希 MAC
        2. OUI 厂商检测
        3. 合并30分钟内的访问会话（upsert）
        4. 标记新访客
        """
        mac_hash = _hash_mac(mac_address)
        vendor = _detect_vendor(mac_address)
        now = datetime.now(timezone.utc)
        merge_threshold = now - timedelta(seconds=SESSION_MERGE_WINDOW_SEC)

        # 查找30分钟内同MAC的活跃会话
        result = await db.execute(
            text("""
                SELECT id, first_seen_at, last_seen_at
                FROM wifi_visit_logs
                WHERE tenant_id = :tid AND store_id = :sid
                  AND mac_hash = :mh AND is_deleted = false
                  AND last_seen_at >= :threshold
                ORDER BY last_seen_at DESC
                LIMIT 1
            """),
            {
                "tid": tenant_id,
                "sid": store_id,
                "mh": mac_hash,
                "threshold": merge_threshold,
            },
        )
        existing = result.mappings().first()

        if existing:
            # 合并到已有会话
            visit_id = str(existing["id"])
            first_seen = existing["first_seen_at"]
            duration = int((now - first_seen).total_seconds())
            await db.execute(
                text("""
                    UPDATE wifi_visit_logs
                    SET last_seen_at = :now,
                        visit_duration_sec = :dur,
                        signal_strength = COALESCE(:sig, signal_strength),
                        updated_at = NOW()
                    WHERE id = :vid
                """),
                {"now": now, "dur": duration, "sig": signal_strength, "vid": visit_id},
            )
            await db.commit()
            logger.info(
                "wifi_probe.session_merged",
                tenant_id=tenant_id,
                store_id=store_id,
                visit_id=visit_id,
                duration_sec=duration,
            )
            return {"visit_id": visit_id, "merged": True, "duration_sec": duration}

        # 判断是否新访客（该MAC在此门店从未出现过）
        prev = await db.execute(
            text("""
                SELECT 1 FROM wifi_visit_logs
                WHERE tenant_id = :tid AND store_id = :sid
                  AND mac_hash = :mh AND is_deleted = false
                LIMIT 1
            """),
            {"tid": tenant_id, "sid": store_id, "mh": mac_hash},
        )
        is_new = prev.first() is None

        # 插入新会话
        row = await db.execute(
            text("""
                INSERT INTO wifi_visit_logs
                    (tenant_id, store_id, mac_hash, device_vendor,
                     first_seen_at, last_seen_at, signal_strength, is_new_visitor)
                VALUES (:tid, :sid, :mh, :vendor, :now, :now, :sig, :is_new)
                RETURNING id
            """),
            {
                "tid": tenant_id,
                "sid": store_id,
                "mh": mac_hash,
                "vendor": vendor,
                "now": now,
                "sig": signal_strength,
                "is_new": is_new,
            },
        )
        visit_id = str(row.scalar_one())
        await db.commit()
        logger.info(
            "wifi_probe.new_session",
            tenant_id=tenant_id,
            store_id=store_id,
            visit_id=visit_id,
            vendor=vendor,
            is_new_visitor=is_new,
        )
        return {"visit_id": visit_id, "merged": False, "is_new_visitor": is_new}

    async def get_store_visits(
        self,
        tenant_id: str,
        store_id: str,
        db: AsyncSession,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """按小时统计访问热力图"""
        params: dict[str, Any] = {"tid": tenant_id, "sid": store_id}
        where_extra = ""
        if date_from:
            where_extra += " AND first_seen_at >= :dfrom"
            params["dfrom"] = date_from
        if date_to:
            where_extra += " AND first_seen_at < :dto"
            params["dto"] = date_to

        result = await db.execute(
            text(f"""
                SELECT EXTRACT(HOUR FROM first_seen_at)::int AS hour,
                       COUNT(*)::int AS visit_count,
                       COUNT(DISTINCT mac_hash)::int AS unique_visitors,
                       AVG(visit_duration_sec)::int AS avg_duration_sec
                FROM wifi_visit_logs
                WHERE tenant_id = :tid AND store_id = :sid
                  AND is_deleted = false
                  {where_extra}
                GROUP BY hour
                ORDER BY hour
            """),
            params,
        )
        rows = result.mappings().all()
        return [dict(r) for r in rows]

    async def get_visit_stats(
        self,
        tenant_id: str,
        store_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """门店访问概览统计"""
        result = await db.execute(
            text("""
                SELECT
                    COUNT(*)::int AS total_visits,
                    COUNT(DISTINCT mac_hash)::int AS unique_macs,
                    COUNT(*) FILTER (WHERE matched_customer_id IS NOT NULL)::int AS matched_count,
                    ROUND(
                        COUNT(*) FILTER (WHERE matched_customer_id IS NOT NULL) * 100.0
                        / GREATEST(COUNT(*), 1), 1
                    ) AS matched_pct,
                    COALESCE(AVG(visit_duration_sec), 0)::int AS avg_duration_sec
                FROM wifi_visit_logs
                WHERE tenant_id = :tid AND store_id = :sid
                  AND is_deleted = false
            """),
            {"tid": tenant_id, "sid": store_id},
        )
        row = result.mappings().first()
        if not row:
            return {
                "total_visits": 0,
                "unique_macs": 0,
                "matched_count": 0,
                "matched_pct": 0.0,
                "avg_duration_sec": 0,
            }
        return dict(row)
