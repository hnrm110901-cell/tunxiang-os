"""SafetyComplianceProjector — 食品安全合规投影器（新模块⑧）

消费事件：
  safety.sample_logged         → 留样+1
  safety.inspection_done       → 检查完成，更新完成率
  safety.violation_found       → 违规+1，写入违规详情
  safety.expiry_alert          → 临期/过期食材预警
  safety.certificate_updated   → 证件更新（清除过期状态）
  safety.haccp_check_completed → HACCP检查完成，更新合格率统计
  safety.haccp_critical_failure→ HACCP关键控制点失控，记录critical告警

维护视图：mv_safety_compliance（按周聚合）
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from ..projector import ProjectorBase


def _iso_week_monday(dt: datetime) -> "datetime.date":
    """返回该日期所在ISO周的周一。"""
    d = dt.date()
    return d - timedelta(days=d.weekday())


class SafetyComplianceProjector(ProjectorBase):

    name = "safety_compliance"
    event_types = {
        "safety.sample_logged",
        "safety.temperature_recorded",
        "safety.inspection_done",
        "safety.violation_found",
        "safety.expiry_alert",
        "safety.certificate_updated",
        "safety.haccp_check_completed",
        "safety.haccp_critical_failure",
    }

    async def handle(self, event: dict[str, Any], conn: object) -> None:
        store_id = event.get("store_id")
        if not store_id:
            return

        occurred_at = event["occurred_at"]
        if isinstance(occurred_at, str):
            occurred_at = datetime.fromisoformat(occurred_at)
        stat_week = _iso_week_monday(occurred_at)

        payload = event.get("payload") or {}
        event_type = event["event_type"]

        # 确保行存在
        await conn.execute(  # type: ignore[union-attr]
            """
            INSERT INTO mv_safety_compliance
                (tenant_id, store_id, stat_week, inspection_required, updated_at)
            VALUES ($1, $2, $3, 0, NOW())
            ON CONFLICT (tenant_id, store_id, stat_week) DO NOTHING
            """,
            self.tenant_id, UUID(str(store_id)), stat_week,
        )

        if event_type == "safety.sample_logged":
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_safety_compliance
                SET sample_logged_count = sample_logged_count + 1,
                    last_event_id       = $4,
                    updated_at          = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_week = $3
                """,
                self.tenant_id, UUID(str(store_id)), stat_week,
                UUID(str(event["event_id"])),
            )

        elif event_type == "safety.inspection_done":
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_safety_compliance
                SET inspection_done     = inspection_done + 1,
                    inspection_required = GREATEST(inspection_required, inspection_done + 1),
                    last_event_id       = $4,
                    updated_at          = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_week = $3
                """,
                self.tenant_id, UUID(str(store_id)), stat_week,
                UUID(str(event["event_id"])),
            )
            await _recalc_compliance_score(conn, self.tenant_id, UUID(str(store_id)), stat_week)

        elif event_type == "safety.violation_found":
            violation = {
                "type": payload.get("violation_type", "unknown"),
                "description": payload.get("description", ""),
                "severity": payload.get("severity", "medium"),
                "found_at": occurred_at.isoformat(),
            }
            deduction = {"critical": 20, "high": 10, "medium": 5, "low": 2}.get(
                payload.get("severity", "medium"), 5
            )
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_safety_compliance
                SET violation_count    = violation_count + 1,
                    compliance_score   = GREATEST(0, compliance_score - $4),
                    last_event_id      = $5,
                    updated_at         = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_week = $3
                """,
                self.tenant_id, UUID(str(store_id)), stat_week,
                deduction, UUID(str(event["event_id"])),
            )

        elif event_type == "safety.expiry_alert":
            alert = {
                "ingredient_id": payload.get("ingredient_id"),
                "ingredient_name": payload.get("ingredient_name", ""),
                "expiry_date": payload.get("expiry_date"),
                "days_until_expiry": payload.get("days_until_expiry", 0),
                "alerted_at": occurred_at.isoformat(),
            }
            await conn.execute(  # type: ignore[union-attr]
                """
                UPDATE mv_safety_compliance
                SET expiry_alerts = expiry_alerts || $4::jsonb,
                    last_event_id = $5,
                    updated_at    = NOW()
                WHERE tenant_id = $1 AND store_id = $2 AND stat_week = $3
                """,
                self.tenant_id, UUID(str(store_id)), stat_week,
                json.dumps([alert]), UUID(str(event["event_id"])),
            )

        elif event_type == "safety.haccp_check_completed":
            await self._handle_haccp_check_completed(
                event, conn, stat_week, UUID(str(store_id))
            )

        elif event_type == "safety.haccp_critical_failure":
            await self._handle_haccp_critical_failure(
                event, conn, stat_week, UUID(str(store_id))
            )


    async def _handle_haccp_check_completed(
        self,
        event: dict[str, Any],
        conn: object,
        stat_week: Any,
        store_id: UUID,
    ) -> None:
        """更新 mv_safety_compliance 中的 HACCP 合格率统计。

        从 payload 中读取本次检查结果，用增量方式更新当周的
        haccp_pass_rate（通过 overall_passed 标志）和
        haccp_critical_failures（累加 critical_failures 字段）。
        """
        payload = event.get("payload") or {}
        overall_passed: bool = bool(payload.get("overall_passed", False))
        critical_failures: int = int(payload.get("critical_failures", 0))
        pass_delta: int = 1 if overall_passed else 0

        await conn.execute(  # type: ignore[union-attr]
            """
            UPDATE mv_safety_compliance
            SET haccp_total_checks       = haccp_total_checks + 1,
                haccp_passed_checks      = haccp_passed_checks + $4,
                haccp_critical_failures  = haccp_critical_failures + $5,
                haccp_pass_rate          = CASE
                    WHEN (haccp_total_checks + 1) > 0
                    THEN ROUND(
                        (haccp_passed_checks + $4)::NUMERIC
                        / (haccp_total_checks + 1) * 100,
                        2
                    )
                    ELSE 0
                END,
                last_event_id            = $6,
                updated_at               = NOW()
            WHERE tenant_id = $1 AND store_id = $2 AND stat_week = $3
            """,
            self.tenant_id, store_id, stat_week,
            pass_delta, critical_failures,
            UUID(str(event["event_id"])),
        )

    async def _handle_haccp_critical_failure(
        self,
        event: dict[str, Any],
        conn: object,
        stat_week: Any,
        store_id: UUID,
    ) -> None:
        """记录 HACCP 关键控制点失控事件到合规视图。

        额外递增 haccp_critical_alert_count（严重失控告警次数），
        同时将本次检查标记为未通过（haccp_passed_checks 不递增）。
        """
        payload = event.get("payload") or {}
        critical_failures: int = int(payload.get("critical_failures", 1))

        await conn.execute(  # type: ignore[union-attr]
            """
            UPDATE mv_safety_compliance
            SET haccp_total_checks          = haccp_total_checks + 1,
                haccp_critical_failures     = haccp_critical_failures + $4,
                haccp_critical_alert_count  = haccp_critical_alert_count + 1,
                haccp_pass_rate             = CASE
                    WHEN (haccp_total_checks + 1) > 0
                    THEN ROUND(
                        haccp_passed_checks::NUMERIC
                        / (haccp_total_checks + 1) * 100,
                        2
                    )
                    ELSE 0
                END,
                last_event_id               = $5,
                updated_at                  = NOW()
            WHERE tenant_id = $1 AND store_id = $2 AND stat_week = $3
            """,
            self.tenant_id, store_id, stat_week,
            critical_failures,
            UUID(str(event["event_id"])),
        )


async def _recalc_compliance_score(conn: object, tenant_id: UUID, store_id: UUID, stat_week) -> None:
    """重算检查完成率（不影响 compliance_score，由违规事件单独扣分）。"""
    await conn.execute(  # type: ignore[union-attr]
        """
        UPDATE mv_safety_compliance
        SET inspection_rate = CASE
            WHEN inspection_required > 0
            THEN ROUND(inspection_done::NUMERIC / inspection_required, 3)
            ELSE 0
        END
        WHERE tenant_id = $1 AND store_id = $2 AND stat_week = $3
        """,
        tenant_id, store_id, stat_week,
    )
