"""
安全合规报告服务 — 生成安全报告，供运维和审计使用。

提供:
  - generate_weekly_report  — 周度安全报告汇总
  - check_compliance_status — 合规检查清单（实时）
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .audit_log_service import AuditAction

logger = structlog.get_logger(__name__)

# 合规基准
_AUDIT_LOG_RETENTION_DAYS = 90
_UNUSED_APP_THRESHOLD_DAYS = 30
_TOKEN_MAX_AGE_DAYS = 90


class SecurityReportService:
    """
    生成安全合规报告，供运维和审计使用。

    所有方法均为 async，操作数据库时严格使用租户隔离（app.tenant_id）。
    """

    async def generate_weekly_report(
        self,
        tenant_id: UUID,
        week_start: date,
        db: AsyncSession,
    ) -> dict:
        """
        生成指定周的安全报告。

        汇总内容:
          - 登录失败次数（按 actor 分组）
          - API 调用量（按 app 分组）
          - 数据导出次数
          - 异常事件列表（severity = critical）
          - 合规检查项状态

        参数:
            tenant_id:  租户 UUID
            week_start: 周开始日期（含），自动计算到 week_start + 7天
            db:         异步数据库会话

        返回:
            结构化的周报字典
        """
        week_end = week_start + timedelta(days=7)
        ts_start = datetime.combine(week_start, datetime.min.time()).replace(tzinfo=timezone.utc)
        ts_end = datetime.combine(week_end, datetime.min.time()).replace(tzinfo=timezone.utc)

        tenant_str = str(tenant_id)

        # 1. 登录失败次数（按 actor 分组）
        login_fail_rows = await db.execute(
            text("""
                SELECT actor_id, COUNT(*) AS cnt
                FROM audit_logs
                WHERE tenant_id = :tenant_id
                  AND action = :action
                  AND created_at >= :ts_start
                  AND created_at < :ts_end
                GROUP BY actor_id
                ORDER BY cnt DESC
                LIMIT 20
            """),
            {
                "tenant_id": tenant_str,
                "action": AuditAction.LOGIN_FAILED.value,
                "ts_start": ts_start,
                "ts_end": ts_end,
            },
        )
        login_failures = [
            {"actor_id": row["actor_id"], "count": row["cnt"]} for row in login_fail_rows.mappings().all()
        ]

        # 2. API 调用量（actor_type = api_app，按 actor_id 分组）
        api_call_rows = await db.execute(
            text("""
                SELECT actor_id, COUNT(*) AS cnt
                FROM audit_logs
                WHERE tenant_id = :tenant_id
                  AND actor_type = 'api_app'
                  AND created_at >= :ts_start
                  AND created_at < :ts_end
                GROUP BY actor_id
                ORDER BY cnt DESC
                LIMIT 20
            """),
            {
                "tenant_id": tenant_str,
                "ts_start": ts_start,
                "ts_end": ts_end,
            },
        )
        api_calls_by_app = [
            {"app_id": row["actor_id"], "call_count": row["cnt"]} for row in api_call_rows.mappings().all()
        ]

        # 3. 数据导出次数
        export_row = await db.execute(
            text("""
                SELECT COUNT(*) AS cnt
                FROM audit_logs
                WHERE tenant_id = :tenant_id
                  AND action = :action
                  AND created_at >= :ts_start
                  AND created_at < :ts_end
            """),
            {
                "tenant_id": tenant_str,
                "action": AuditAction.DATA_EXPORT.value,
                "ts_start": ts_start,
                "ts_end": ts_end,
            },
        )
        data_export_count: int = export_row.scalar_one()

        # 4. 异常事件（severity = critical）
        critical_rows = await db.execute(
            text("""
                SELECT id, action, actor_id, actor_type,
                       resource_type, resource_id, created_at, extra
                FROM audit_logs
                WHERE tenant_id = :tenant_id
                  AND severity = 'critical'
                  AND created_at >= :ts_start
                  AND created_at < :ts_end
                ORDER BY created_at DESC
                LIMIT 100
            """),
            {
                "tenant_id": tenant_str,
                "ts_start": ts_start,
                "ts_end": ts_end,
            },
        )
        critical_events = [
            {
                "id": str(row["id"]),
                "action": row["action"],
                "actor_id": row["actor_id"],
                "actor_type": row["actor_type"],
                "resource_type": row["resource_type"],
                "resource_id": row["resource_id"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }
            for row in critical_rows.mappings().all()
        ]

        # 5. 合规检查状态
        compliance = await self.check_compliance_status(tenant_id, db)

        report = {
            "tenant_id": tenant_str,
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "login_failures": login_failures,
            "api_calls_by_app": api_calls_by_app,
            "data_export_count": data_export_count,
            "critical_events": critical_events,
            "critical_event_count": len(critical_events),
            "compliance": compliance,
        }

        logger.info(
            "security_report.weekly_generated",
            tenant_id=tenant_str,
            week_start=week_start.isoformat(),
            critical_events=len(critical_events),
        )
        return report

    async def check_compliance_status(
        self,
        tenant_id: UUID,
        db: AsyncSession,
    ) -> dict:
        """
        实时合规检查清单。

        检查项:
          - rls_enabled: audit_logs 表是否启用 RLS
          - audit_log_retention_days: 合规要求的日志保留天数（常量90天）
          - has_expired_tokens: 是否存在超过90天的 token（TOKEN_ISSUED 未被 TOKEN_REVOKED 的）
          - has_unused_apps: 是否存在超30天未使用的 api_app
          - health_cert_alerts: 健康证即将过期的员工数（从 employees 表查询，如不存在则返回0）
          - overall_score: 0-100 合规分

        返回示例:
            {
                "rls_enabled": true,
                "audit_log_retention_days": 90,
                "has_expired_tokens": false,
                "has_unused_apps": false,
                "health_cert_alerts": 2,
                "overall_score": 85,
                "checked_at": "2026-03-31T12:00:00+00:00"
            }
        """
        tenant_str = str(tenant_id)
        now = datetime.now(timezone.utc)
        deductions = 0

        # 1. RLS 是否启用（查询 pg_class + pg_tables）
        rls_row = await db.execute(
            text("""
                SELECT relrowsecurity
                FROM pg_class
                WHERE relname = 'audit_logs'
                  AND relnamespace = (
                      SELECT oid FROM pg_namespace WHERE nspname = current_schema()
                  )
            """),
        )
        rls_result = rls_row.scalar_one_or_none()
        rls_enabled: bool = bool(rls_result) if rls_result is not None else False
        if not rls_enabled:
            deductions += 30  # RLS 未开启扣30分

        # 2. 过期 token：TOKEN_ISSUED 但 TOKEN_REVOKED 未记录且超过90天
        expired_token_row = await db.execute(
            text("""
                SELECT COUNT(*) AS cnt
                FROM audit_logs issued
                WHERE issued.tenant_id = :tenant_id
                  AND issued.action = :issued_action
                  AND issued.created_at < NOW() - INTERVAL ':days days'
                  AND NOT EXISTS (
                      SELECT 1 FROM audit_logs revoked
                      WHERE revoked.tenant_id = issued.tenant_id
                        AND revoked.action = :revoked_action
                        AND revoked.actor_id = issued.actor_id
                        AND revoked.resource_id = issued.resource_id
                        AND revoked.created_at > issued.created_at
                  )
            """),
            {
                "tenant_id": tenant_str,
                "issued_action": AuditAction.TOKEN_ISSUED.value,
                "revoked_action": AuditAction.TOKEN_REVOKED.value,
                "days": _TOKEN_MAX_AGE_DAYS,
            },
        )
        expired_token_count: int = expired_token_row.scalar_one()
        has_expired_tokens = expired_token_count > 0
        if has_expired_tokens:
            deductions += 15

        # 3. 超30天未使用的 api_app
        unused_app_row = await db.execute(
            text("""
                SELECT COUNT(DISTINCT actor_id) AS cnt
                FROM audit_logs first_seen
                WHERE tenant_id = :tenant_id
                  AND actor_type = 'api_app'
                  AND NOT EXISTS (
                      SELECT 1 FROM audit_logs recent
                      WHERE recent.tenant_id = first_seen.tenant_id
                        AND recent.actor_id = first_seen.actor_id
                        AND recent.actor_type = 'api_app'
                        AND recent.created_at >= NOW() - INTERVAL ':days days'
                  )
            """),
            {
                "tenant_id": tenant_str,
                "days": _UNUSED_APP_THRESHOLD_DAYS,
            },
        )
        unused_app_count: int = unused_app_row.scalar_one()
        has_unused_apps = unused_app_count > 0
        if has_unused_apps:
            deductions += 10

        # 4. 健康证即将过期的员工数（30天内到期）
        health_cert_alerts = 0
        try:
            health_row = await db.execute(
                text("""
                    SELECT COUNT(*) AS cnt
                    FROM employees
                    WHERE tenant_id = :tenant_id
                      AND is_deleted = FALSE
                      AND health_cert_expire_date IS NOT NULL
                      AND health_cert_expire_date <= CURRENT_DATE + INTERVAL '30 days'
                      AND health_cert_expire_date >= CURRENT_DATE
                """),
                {"tenant_id": tenant_str},
            )
            health_cert_alerts = health_row.scalar_one()
        except Exception as exc:  # noqa: BLE001 — 最外层兜底，防止 employees 表列不存在
            # employees.health_cert_expire_date 列尚未在所有部署环境中存在，
            # 查询失败时退化为0，不影响整体合规评分。
            logger.warning(
                "compliance_check.health_cert_query_failed",
                error=str(exc),
                exc_info=True,
            )
            health_cert_alerts = 0
        if health_cert_alerts > 0:
            deductions += min(health_cert_alerts * 2, 10)  # 每人扣2分，最多扣10分

        overall_score = max(0, 100 - deductions)

        return {
            "rls_enabled": rls_enabled,
            "audit_log_retention_days": _AUDIT_LOG_RETENTION_DAYS,
            "has_expired_tokens": has_expired_tokens,
            "expired_token_count": expired_token_count,
            "has_unused_apps": has_unused_apps,
            "unused_app_count": unused_app_count,
            "health_cert_alerts": health_cert_alerts,
            "overall_score": overall_score,
            "checked_at": now.isoformat(),
        }
