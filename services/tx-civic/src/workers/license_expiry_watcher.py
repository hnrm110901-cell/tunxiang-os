"""证照到期监控 Worker — 每天检查证照和健康证到期情况

职责:
- 30天内到期的证照 -> 标记 expiring_soon
- 已过期的证照 -> 标记 expired
- 发射 LICENSE_EXPIRING / LICENSE_EXPIRED 事件
- 健康证同理（发射 HEALTH_CERT_EXPIRING 事件）
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.civic_events import CivicEventType

logger = structlog.get_logger(__name__)

# 到期预警阈值（天）
LICENSE_WARN_DAYS = 30
HEALTH_CERT_WARN_DAYS = 30


class LicenseExpiryWatcher:
    """证照到期监控器

    外部调用入口:
        watcher = LicenseExpiryWatcher()
        await watcher.run(db)
    """

    async def _fetch_tenant_ids(self, db: AsyncSession) -> list[str]:
        """获取所有租户 ID 列表。"""
        result = await db.execute(
            text(
                "SELECT DISTINCT tenant_id FROM civic_licenses WHERE is_deleted = FALSE "
                "UNION SELECT DISTINCT tenant_id FROM civic_health_certs WHERE is_deleted = FALSE"
            )
        )
        return [str(row[0]) for row in result.all()]

    async def _set_tenant(self, db: AsyncSession, tenant_id: str) -> None:
        """设置当前会话的租户上下文，以通过 RLS。"""
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

    async def run(self, db: AsyncSession) -> dict[str, Any]:
        """执行证照到期扫描，更新状态，发射事件。

        Args:
            db: 数据库异步会话

        Returns:
            {licenses_expiring, licenses_expired, health_certs_expiring, health_certs_expired}
        """
        started_at = datetime.now(timezone.utc)
        logger.info("license_expiry_watcher_started")

        # 获取所有租户，逐租户扫描（RLS 要求）
        tenant_ids = await self._fetch_tenant_ids(db)

        all_license = {"marked_expiring": 0, "marked_expired": 0, "expiring_items": [], "expired_items": []}
        all_health = {"marked_expiring": 0, "marked_expired": 0, "expiring_items": [], "expired_items": []}

        for tid in tenant_ids:
            await self._set_tenant(db, tid)
            lic_r = await self._scan_licenses(db)
            hc_r = await self._scan_health_certs(db)
            all_license["marked_expiring"] += lic_r.get("marked_expiring", 0)
            all_license["marked_expired"] += lic_r.get("marked_expired", 0)
            all_license["expiring_items"].extend(lic_r.get("expiring_items", []))
            all_license["expired_items"].extend(lic_r.get("expired_items", []))
            all_health["marked_expiring"] += hc_r.get("marked_expiring", 0)
            all_health["marked_expired"] += hc_r.get("marked_expired", 0)
            all_health["expiring_items"].extend(hc_r.get("expiring_items", []))
            all_health["expired_items"].extend(hc_r.get("expired_items", []))

        license_result = all_license
        health_result = all_health

        # 发射事件
        await self._emit_license_events(license_result)
        await self._emit_health_cert_events(health_result)

        elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()

        logger.info(
            "license_expiry_watcher_completed",
            licenses_marked_expiring=license_result["marked_expiring"],
            licenses_marked_expired=license_result["marked_expired"],
            health_certs_marked_expiring=health_result["marked_expiring"],
            health_certs_marked_expired=health_result["marked_expired"],
            elapsed_seconds=round(elapsed, 2),
        )

        return {
            "licenses_expiring": license_result["marked_expiring"],
            "licenses_expired": license_result["marked_expired"],
            "health_certs_expiring": health_result["marked_expiring"],
            "health_certs_expired": health_result["marked_expired"],
            "elapsed_seconds": round(elapsed, 2),
        }

    async def _scan_licenses(self, db: AsyncSession) -> dict[str, Any]:
        """扫描证照，标记 expiring_soon 和 expired。

        Args:
            db: 数据库异步会话

        Returns:
            {marked_expiring, marked_expired, expiring_items, expired_items}
        """
        today = date.today()
        warn_date = today + timedelta(days=LICENSE_WARN_DAYS)

        # 标记即将到期（valid -> expiring_soon）
        mark_expiring_sql = text("""
            UPDATE civic_licenses
            SET status = 'expiring_soon', updated_at = NOW()
            WHERE is_deleted = FALSE
              AND status = 'valid'
              AND expiry_date IS NOT NULL
              AND expiry_date > :today
              AND expiry_date <= :warn_date
            RETURNING id, tenant_id, store_id, license_type, license_name, expiry_date
        """)

        # 标记已过期（valid/expiring_soon -> expired）
        mark_expired_sql = text("""
            UPDATE civic_licenses
            SET status = 'expired', updated_at = NOW()
            WHERE is_deleted = FALSE
              AND status IN ('valid', 'expiring_soon')
              AND expiry_date IS NOT NULL
              AND expiry_date <= :today
            RETURNING id, tenant_id, store_id, license_type, license_name, expiry_date
        """)

        try:
            expiring_result = await db.execute(mark_expiring_sql, {"today": today, "warn_date": warn_date})
            expiring_rows = expiring_result.all()

            expired_result = await db.execute(mark_expired_sql, {"today": today})
            expired_rows = expired_result.all()

            await db.commit()
        except SQLAlchemyError as exc:
            await db.rollback()
            logger.error("license_scan_failed", error=str(exc), exc_info=True)
            return {
                "marked_expiring": 0,
                "marked_expired": 0,
                "expiring_items": [],
                "expired_items": [],
            }

        return {
            "marked_expiring": len(expiring_rows),
            "marked_expired": len(expired_rows),
            "expiring_items": [
                {
                    "id": str(r[0]),
                    "tenant_id": str(r[1]),
                    "store_id": str(r[2]),
                    "license_type": r[3],
                    "license_name": r[4],
                    "expiry_date": r[5].isoformat() if r[5] else None,
                }
                for r in expiring_rows
            ],
            "expired_items": [
                {
                    "id": str(r[0]),
                    "tenant_id": str(r[1]),
                    "store_id": str(r[2]),
                    "license_type": r[3],
                    "license_name": r[4],
                    "expiry_date": r[5].isoformat() if r[5] else None,
                }
                for r in expired_rows
            ],
        }

    async def _scan_health_certs(self, db: AsyncSession) -> dict[str, Any]:
        """扫描健康证，标记到期和过期。

        Args:
            db: 数据库异步会话

        Returns:
            {marked_expiring, marked_expired, expiring_items, expired_items}
        """
        today = date.today()
        warn_date = today + timedelta(days=HEALTH_CERT_WARN_DAYS)

        mark_expiring_sql = text("""
            UPDATE civic_health_certs
            SET status = 'expiring_soon', updated_at = NOW()
            WHERE is_deleted = FALSE
              AND status = 'valid'
              AND expiry_date IS NOT NULL
              AND expiry_date > :today
              AND expiry_date <= :warn_date
            RETURNING id, tenant_id, store_id, employee_id, employee_name, expiry_date
        """)

        mark_expired_sql = text("""
            UPDATE civic_health_certs
            SET status = 'expired', updated_at = NOW()
            WHERE is_deleted = FALSE
              AND status IN ('valid', 'expiring_soon')
              AND expiry_date IS NOT NULL
              AND expiry_date <= :today
            RETURNING id, tenant_id, store_id, employee_id, employee_name, expiry_date
        """)

        try:
            expiring_result = await db.execute(mark_expiring_sql, {"today": today, "warn_date": warn_date})
            expiring_rows = expiring_result.all()

            expired_result = await db.execute(mark_expired_sql, {"today": today})
            expired_rows = expired_result.all()

            await db.commit()
        except SQLAlchemyError as exc:
            await db.rollback()
            logger.error("health_cert_scan_failed", error=str(exc), exc_info=True)
            return {
                "marked_expiring": 0,
                "marked_expired": 0,
                "expiring_items": [],
                "expired_items": [],
            }

        return {
            "marked_expiring": len(expiring_rows),
            "marked_expired": len(expired_rows),
            "expiring_items": [
                {
                    "id": str(r[0]),
                    "tenant_id": str(r[1]),
                    "store_id": str(r[2]),
                    "employee_id": str(r[3]),
                    "employee_name": r[4],
                    "expiry_date": r[5].isoformat() if r[5] else None,
                }
                for r in expiring_rows
            ],
            "expired_items": [
                {
                    "id": str(r[0]),
                    "tenant_id": str(r[1]),
                    "store_id": str(r[2]),
                    "employee_id": str(r[3]),
                    "employee_name": r[4],
                    "expiry_date": r[5].isoformat() if r[5] else None,
                }
                for r in expired_rows
            ],
        }

    async def _emit_license_events(self, result: dict[str, Any]) -> None:
        """发射证照到期/过期事件。

        Args:
            result: 证照扫描结果
        """
        try:
            from shared.events.src.emitter import emit_event

            for item in result.get("expiring_items", []):
                asyncio.create_task(
                    emit_event(
                        event_type=CivicEventType.LICENSE_EXPIRING.value,
                        tenant_id=uuid.UUID(item["tenant_id"]),
                        stream_id=item["id"],
                        payload={
                            "store_id": item["store_id"],
                            "license_type": item["license_type"],
                            "license_name": item["license_name"],
                            "expiry_date": item["expiry_date"],
                        },
                        source_service="tx-civic",
                    )
                )

            for item in result.get("expired_items", []):
                asyncio.create_task(
                    emit_event(
                        event_type=CivicEventType.LICENSE_EXPIRED.value,
                        tenant_id=uuid.UUID(item["tenant_id"]),
                        stream_id=item["id"],
                        payload={
                            "store_id": item["store_id"],
                            "license_type": item["license_type"],
                            "license_name": item["license_name"],
                            "expiry_date": item["expiry_date"],
                        },
                        source_service="tx-civic",
                    )
                )

        except ImportError:
            logger.warning("event_emitter_not_available", hint="shared.events not installed")

    async def _emit_health_cert_events(self, result: dict[str, Any]) -> None:
        """发射健康证到期事件。

        Args:
            result: 健康证扫描结果
        """
        try:
            from shared.events.src.emitter import emit_event

            for item in result.get("expiring_items", []):
                asyncio.create_task(
                    emit_event(
                        event_type=CivicEventType.HEALTH_CERT_EXPIRING.value,
                        tenant_id=uuid.UUID(item["tenant_id"]),
                        stream_id=item["id"],
                        payload={
                            "store_id": item["store_id"],
                            "employee_id": item["employee_id"],
                            "employee_name": item["employee_name"],
                            "expiry_date": item["expiry_date"],
                        },
                        source_service="tx-civic",
                    )
                )

        except ImportError:
            logger.warning("event_emitter_not_available", hint="shared.events not installed")
