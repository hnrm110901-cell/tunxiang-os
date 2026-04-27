"""每日合规巡检 Worker — 每天早上 6:00 执行

职责:
- 扫描所有门店的证照到期情况（30天内到期）
- 检查员工健康证到期情况
- 检查消防设备待检情况
- 计算所有门店合规评分
- 生成巡检摘要（哪些门店有风险、最紧急的待办）
- 发射事件通知 IM 工作台
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.civic_enums import (
    RiskLevel,
)
from ..models.civic_events import CivicEventType

logger = structlog.get_logger(__name__)

# 到期预警阈值（天）
LICENSE_WARN_DAYS = 30
HEALTH_CERT_WARN_DAYS = 30
FIRE_EQUIPMENT_OVERDUE_DAYS = 0


class DailyComplianceChecker:
    """每日合规巡检器

    外部调用入口:
        checker = DailyComplianceChecker()
        await checker.run(db)
    """

    async def _fetch_tenant_ids(self, db: AsyncSession) -> list[str]:
        """获取所有租户 ID 列表。"""
        result = await db.execute(
            text(
                "SELECT DISTINCT tenant_id FROM civic_licenses WHERE is_deleted = FALSE "
                "UNION SELECT DISTINCT tenant_id FROM civic_health_certs WHERE is_deleted = FALSE "
                "UNION SELECT DISTINCT tenant_id FROM civic_fire_equipment WHERE is_deleted = FALSE"
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
        """执行全量合规巡检，返回巡检摘要。

        Args:
            db: 数据库异步会话

        Returns:
            巡检摘要 dict，包含各维度统计和风险门店列表
        """
        started_at = datetime.now(timezone.utc)
        logger.info("daily_compliance_check_started")

        # 获取所有租户，逐租户执行巡检（RLS 要求）
        tenant_ids = await self._fetch_tenant_ids(db)

        all_license = {"expiring_count": 0, "expired_count": 0, "expiring_items": [], "expired_items": []}
        all_health = {"expiring_count": 0, "expired_count": 0, "expiring_items": [], "expired_items": []}
        all_fire = {"overdue_count": 0, "overdue_items": []}

        for tid in tenant_ids:
            await self._set_tenant(db, tid)
            license_r, health_r, fire_r = await asyncio.gather(
                self._check_licenses(db),
                self._check_health_certs(db),
                self._check_fire_equipment(db),
            )
            # 合并结果
            all_license["expiring_count"] += license_r.get("expiring_count", 0)
            all_license["expired_count"] += license_r.get("expired_count", 0)
            all_license["expiring_items"].extend(license_r.get("expiring_items", []))
            all_license["expired_items"].extend(license_r.get("expired_items", []))
            all_health["expiring_count"] += health_r.get("expiring_count", 0)
            all_health["expired_count"] += health_r.get("expired_count", 0)
            all_health["expiring_items"].extend(health_r.get("expiring_items", []))
            all_health["expired_items"].extend(health_r.get("expired_items", []))
            all_fire["overdue_count"] += fire_r.get("overdue_count", 0)
            all_fire["overdue_items"].extend(fire_r.get("overdue_items", []))

        license_result = all_license
        health_result = all_health
        fire_result = all_fire

        # 计算门店合规评分
        score_result = await self._calculate_store_scores(db, license_result, health_result, fire_result)

        # 汇总巡检摘要
        elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()

        summary = {
            "check_date": date.today().isoformat(),
            "licenses": license_result,
            "health_certs": health_result,
            "fire_equipment": fire_result,
            "store_scores": score_result,
            "elapsed_seconds": round(elapsed, 2),
        }

        # 发射事件通知 IM 工作台
        await self._emit_summary_events(summary)

        logger.info(
            "daily_compliance_check_completed",
            expiring_licenses=license_result.get("expiring_count", 0),
            expired_licenses=license_result.get("expired_count", 0),
            expiring_health_certs=health_result.get("expiring_count", 0),
            overdue_fire_equipment=fire_result.get("overdue_count", 0),
            red_stores=score_result.get("red_count", 0),
            yellow_stores=score_result.get("yellow_count", 0),
            elapsed_seconds=round(elapsed, 2),
        )

        return summary

    async def _check_licenses(self, db: AsyncSession) -> dict[str, Any]:
        """扫描30天内到期和已过期的证照。

        Args:
            db: 数据库异步会话

        Returns:
            {expiring_count, expired_count, expiring_items, expired_items}
        """
        from sqlalchemy import text

        today = date.today()
        warn_date = today + timedelta(days=LICENSE_WARN_DAYS)

        # 查询即将到期的证照
        expiring_sql = text("""
            SELECT id, tenant_id, store_id, license_type, license_name,
                   expiry_date, status
            FROM civic_licenses
            WHERE is_deleted = FALSE
              AND expiry_date IS NOT NULL
              AND expiry_date > :today
              AND expiry_date <= :warn_date
              AND status NOT IN ('renewing')
            ORDER BY expiry_date ASC
        """)

        expired_sql = text("""
            SELECT id, tenant_id, store_id, license_type, license_name,
                   expiry_date, status
            FROM civic_licenses
            WHERE is_deleted = FALSE
              AND expiry_date IS NOT NULL
              AND expiry_date <= :today
              AND status NOT IN ('renewing')
            ORDER BY expiry_date ASC
        """)

        try:
            expiring_result = await db.execute(expiring_sql, {"today": today, "warn_date": warn_date})
            expiring_rows = expiring_result.all()

            expired_result = await db.execute(expired_sql, {"today": today})
            expired_rows = expired_result.all()
        except SQLAlchemyError as exc:
            logger.error("license_check_failed", error=str(exc), exc_info=True)
            return {"expiring_count": 0, "expired_count": 0, "error": str(exc)}

        # 更新状态
        if expiring_rows:
            update_expiring_sql = text("""
                UPDATE civic_licenses
                SET status = 'expiring_soon', updated_at = NOW()
                WHERE id = ANY(:ids)
                  AND status = 'valid'
            """)
            expiring_ids = [row[0] for row in expiring_rows]
            await db.execute(update_expiring_sql, {"ids": expiring_ids})

        if expired_rows:
            update_expired_sql = text("""
                UPDATE civic_licenses
                SET status = 'expired', updated_at = NOW()
                WHERE id = ANY(:ids)
                  AND status != 'expired'
            """)
            expired_ids = [row[0] for row in expired_rows]
            await db.execute(update_expired_sql, {"ids": expired_ids})

        await db.commit()

        return {
            "expiring_count": len(expiring_rows),
            "expired_count": len(expired_rows),
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

    async def _check_health_certs(self, db: AsyncSession) -> dict[str, Any]:
        """检查员工健康证到期情况。

        Args:
            db: 数据库异步会话

        Returns:
            {expiring_count, expired_count, expiring_items}
        """
        from sqlalchemy import text

        today = date.today()
        warn_date = today + timedelta(days=HEALTH_CERT_WARN_DAYS)

        sql = text("""
            SELECT id, tenant_id, store_id, employee_id, employee_name,
                   expiry_date
            FROM civic_health_certs
            WHERE is_deleted = FALSE
              AND expiry_date IS NOT NULL
              AND expiry_date <= :warn_date
            ORDER BY expiry_date ASC
        """)

        try:
            result = await db.execute(sql, {"warn_date": warn_date})
            rows = result.all()
        except SQLAlchemyError as exc:
            logger.error("health_cert_check_failed", error=str(exc), exc_info=True)
            return {"expiring_count": 0, "expired_count": 0, "error": str(exc)}

        expiring = [r for r in rows if r[5] and r[5] > today]
        expired = [r for r in rows if r[5] and r[5] <= today]

        return {
            "expiring_count": len(expiring),
            "expired_count": len(expired),
            "expiring_items": [
                {
                    "id": str(r[0]),
                    "tenant_id": str(r[1]),
                    "store_id": str(r[2]),
                    "employee_id": str(r[3]),
                    "employee_name": r[4],
                    "expiry_date": r[5].isoformat() if r[5] else None,
                }
                for r in expiring
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
                for r in expired
            ],
        }

    async def _check_fire_equipment(self, db: AsyncSession) -> dict[str, Any]:
        """检查消防设备待检情况。

        Args:
            db: 数据库异步会话

        Returns:
            {overdue_count, overdue_items}
        """
        from sqlalchemy import text

        today = date.today()

        sql = text("""
            SELECT id, tenant_id, store_id, equipment_type, equipment_name,
                   next_inspection_date, location_desc
            FROM civic_fire_equipment
            WHERE is_deleted = FALSE
              AND next_inspection_date IS NOT NULL
              AND next_inspection_date <= :today
            ORDER BY next_inspection_date ASC
        """)

        try:
            result = await db.execute(sql, {"today": today})
            rows = result.all()
        except SQLAlchemyError as exc:
            logger.error("fire_equipment_check_failed", error=str(exc), exc_info=True)
            return {"overdue_count": 0, "error": str(exc)}

        return {
            "overdue_count": len(rows),
            "overdue_items": [
                {
                    "id": str(r[0]),
                    "tenant_id": str(r[1]),
                    "store_id": str(r[2]),
                    "equipment_type": r[3],
                    "equipment_name": r[4],
                    "next_inspection_date": r[5].isoformat() if r[5] else None,
                    "location_desc": r[6],
                }
                for r in rows
            ],
        }

    async def _calculate_store_scores(
        self,
        db: AsyncSession,
        license_result: dict[str, Any],
        health_result: dict[str, Any],
        fire_result: dict[str, Any],
    ) -> dict[str, Any]:
        """计算各门店合规评分。

        评分规则（满分100）:
        - 证照合规: 40分（每个过期证照扣10分，即将到期扣5分）
        - 健康证合规: 20分（每个过期扣5分，即将到期扣2分）
        - 消防合规: 20分（每个逾期设备扣5分）
        - 基础分: 20分

        Args:
            db: 数据库异步会话
            license_result: 证照检查结果
            health_result: 健康证检查结果
            fire_result: 消防设备检查结果

        Returns:
            {scores: [{store_id, score, risk_level}], red_count, yellow_count, green_count}
        """
        store_deductions: dict[str, dict[str, int]] = {}

        # 证照扣分
        for item in license_result.get("expired_items", []):
            sid = item["store_id"]
            store_deductions.setdefault(sid, {"license": 0, "health": 0, "fire": 0})
            store_deductions[sid]["license"] += 10

        for item in license_result.get("expiring_items", []):
            sid = item["store_id"]
            store_deductions.setdefault(sid, {"license": 0, "health": 0, "fire": 0})
            store_deductions[sid]["license"] += 5

        # 健康证扣分
        for item in health_result.get("expired_items", []):
            sid = item["store_id"]
            store_deductions.setdefault(sid, {"license": 0, "health": 0, "fire": 0})
            store_deductions[sid]["health"] += 5

        for item in health_result.get("expiring_items", []):
            sid = item["store_id"]
            store_deductions.setdefault(sid, {"license": 0, "health": 0, "fire": 0})
            store_deductions[sid]["health"] += 2

        # 消防扣分
        for item in fire_result.get("overdue_items", []):
            sid = item["store_id"]
            store_deductions.setdefault(sid, {"license": 0, "health": 0, "fire": 0})
            store_deductions[sid]["fire"] += 5

        # 计算最终评分
        scores: list[dict[str, Any]] = []
        red_count = 0
        yellow_count = 0
        green_count = 0

        for store_id, deductions in store_deductions.items():
            license_score = max(0, 40 - deductions["license"])
            health_score = max(0, 20 - deductions["health"])
            fire_score = max(0, 20 - deductions["fire"])
            base_score = 20
            total = license_score + health_score + fire_score + base_score

            if total >= 80:
                risk_level = RiskLevel.green
                green_count += 1
            elif total >= 60:
                risk_level = RiskLevel.yellow
                yellow_count += 1
            else:
                risk_level = RiskLevel.red
                red_count += 1

            scores.append(
                {
                    "store_id": store_id,
                    "score": total,
                    "risk_level": risk_level.value,
                    "license_score": license_score,
                    "health_score": health_score,
                    "fire_score": fire_score,
                }
            )

        # 按评分升序排列（最差的在前面）
        scores.sort(key=lambda s: s["score"])

        return {
            "scores": scores,
            "red_count": red_count,
            "yellow_count": yellow_count,
            "green_count": green_count,
            "total_checked": len(scores),
        }

    async def _emit_summary_events(self, summary: dict[str, Any]) -> None:
        """发射巡检摘要事件，通知 IM 工作台。

        Args:
            summary: 巡检摘要
        """
        try:
            from shared.events.src.emitter import emit_event

            # 发射评分更新事件
            score_result = summary.get("store_scores", {})
            if score_result.get("red_count", 0) > 0 or score_result.get("yellow_count", 0) > 0:
                asyncio.create_task(
                    emit_event(
                        event_type=CivicEventType.SCORE_UPDATED.value,
                        tenant_id=None,
                        stream_id="daily_compliance_check",
                        payload={
                            "check_date": summary["check_date"],
                            "red_count": score_result.get("red_count", 0),
                            "yellow_count": score_result.get("yellow_count", 0),
                            "green_count": score_result.get("green_count", 0),
                            "risk_stores": [
                                s for s in score_result.get("scores", []) if s["risk_level"] in ("red", "yellow")
                            ],
                        },
                        source_service="tx-civic",
                    )
                )

            # 发射证照到期事件
            license_result = summary.get("licenses", {})
            if license_result.get("expiring_count", 0) > 0:
                asyncio.create_task(
                    emit_event(
                        event_type=CivicEventType.LICENSE_EXPIRING.value,
                        tenant_id=None,
                        stream_id="daily_compliance_check",
                        payload={
                            "expiring_count": license_result["expiring_count"],
                            "items": license_result.get("expiring_items", []),
                        },
                        source_service="tx-civic",
                    )
                )

        except ImportError:
            logger.warning("event_emitter_not_available", hint="shared.events not installed")
