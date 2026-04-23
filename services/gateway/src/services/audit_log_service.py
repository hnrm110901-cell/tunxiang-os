"""
操作审计日志 — 记录所有关键业务操作。

合规要求:
  - 日志不可删除/不可修改（audit_logs表仅有SELECT/INSERT RLS策略）
  - 至少保留90天
  - 敏感字段写入前自动脱敏

数据库表: audit_logs（见 v070_audit_logs 迁移）
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class AuditAction(str, Enum):
    """所有受审计的业务操作类型。"""

    # 认证
    LOGIN = "auth.login"
    LOGOUT = "auth.logout"
    LOGIN_FAILED = "auth.login_failed"
    TOKEN_ISSUED = "auth.token_issued"
    TOKEN_REVOKED = "auth.token_revoked"
    # 数据操作
    DATA_EXPORT = "data.export"
    DATA_DELETE = "data.delete"
    DATA_BULK_UPDATE = "data.bulk_update"
    # 配置变更
    CONFIG_CHANGE = "config.change"
    RLS_POLICY_CHANGE = "config.rls_policy"
    # 财务
    SETTLEMENT_APPROVE = "finance.settlement_approve"
    VOUCHER_PUSH = "finance.voucher_push"
    DISCOUNT_OVERRIDE = "finance.discount_override"
    # Agent决策
    AGENT_DECISION = "agent.decision"
    CONSTRAINT_OVERRIDE = "agent.constraint_override"  # 突破硬约束（极高风险）


@dataclass
class AuditEntry:
    """一条审计日志的完整信息。"""

    tenant_id: UUID
    action: AuditAction
    actor_id: str  # 操作人ID（user_id / app_key / agent_id）
    actor_type: str  # user / api_app / agent / system
    resource_type: str  # customer / order / employee / config …
    resource_id: str | None = None
    before_state: dict | None = None  # 变更前状态（敏感字段自动脱敏）
    after_state: dict | None = None  # 变更后状态（敏感字段自动脱敏）
    ip_address: str | None = None
    user_agent: str | None = None
    severity: str = "info"  # info / warning / critical
    extra: dict = field(default_factory=dict)


# 敏感字段脱敏规则（独立于 DataMasker，保持 service 自洽）
_SENSITIVE_FIELDS: set[str] = {
    "id_card_no",
    "bank_account",
    "phone",
    "mobile",
    "email",
    "password",
    "secret",
    "token",
    "app_secret",
}

# action 到 severity 的自动映射（可被 entry.severity 显式覆盖）
_ACTION_DEFAULT_SEVERITY: dict[AuditAction, str] = {
    AuditAction.CONSTRAINT_OVERRIDE: "critical",
    AuditAction.DATA_DELETE: "warning",
    AuditAction.DATA_EXPORT: "warning",
    AuditAction.DATA_BULK_UPDATE: "warning",
    AuditAction.DISCOUNT_OVERRIDE: "warning",
    AuditAction.SETTLEMENT_APPROVE: "warning",
    AuditAction.RLS_POLICY_CHANGE: "critical",
    AuditAction.LOGIN_FAILED: "warning",
}

_VALID_ACTOR_TYPES = {"user", "api_app", "agent", "system"}
_VALID_SEVERITIES = {"info", "warning", "critical"}


def _mask_value(key: str, value: Any) -> Any:
    """对单个字段值执行脱敏。"""
    if value is None:
        return None
    if key in ("phone", "mobile"):
        s = str(value)
        if len(s) >= 7:
            return s[:3] + "****" + s[-4:]
        return "****"
    if key == "id_card_no":
        s = str(value)
        if len(s) <= 7:
            return "*" * len(s)
        return s[:3] + "*" * (len(s) - 7) + s[-4:]
    if key == "email":
        s = str(value)
        at = s.find("@")
        if at < 0:
            return "***"
        return s[0] + "***" + s[at:]
    if key == "bank_account":
        s = str(value)
        return "****" + s[-4:] if len(s) > 4 else "****"
    # password / secret / token / app_secret — 完全遮盖
    return "***REDACTED***"


def _mask_sensitive(data: dict | None) -> dict | None:
    """
    递归脱敏字典中的敏感字段。
    不修改原始 data（深度复制语义由调用方保证传入副本）。
    """
    if data is None:
        return None
    result: dict = {}
    for key, value in data.items():
        if key in _SENSITIVE_FIELDS:
            result[key] = _mask_value(key, value)
        elif isinstance(value, dict):
            result[key] = _mask_sensitive(value)
        elif isinstance(value, list):
            result[key] = [_mask_sensitive(item) if isinstance(item, dict) else item for item in value]
        else:
            result[key] = value
    return result


class AuditLogService:
    """
    操作审计日志服务。

    写入规则:
      1. before_state / after_state 自动脱敏后写入
      2. CONSTRAINT_OVERRIDE 操作强制设为 critical 级别
      3. 所有操作同步输出到 structlog（JSON格式）
    """

    # 供外部引用
    SENSITIVE_FIELDS: set[str] = _SENSITIVE_FIELDS

    async def log(self, entry: AuditEntry, db: AsyncSession) -> None:
        """
        写入 audit_logs 表，同时通过 structlog 输出结构化日志。

        注意: audit_logs 表只有 INSERT 策略，不支持 UPDATE/DELETE（合规要求）。
        """
        # 参数校验
        if entry.actor_type not in _VALID_ACTOR_TYPES:
            raise ValueError(f"actor_type 必须是 {_VALID_ACTOR_TYPES}，得到: {entry.actor_type!r}")

        # CONSTRAINT_OVERRIDE 强制 critical
        effective_severity = entry.severity
        if entry.action == AuditAction.CONSTRAINT_OVERRIDE:
            effective_severity = "critical"
        elif effective_severity not in _VALID_SEVERITIES:
            effective_severity = "info"

        # 若未显式设置 severity，使用 action 默认映射
        if entry.severity == "info" and entry.action in _ACTION_DEFAULT_SEVERITY:
            effective_severity = _ACTION_DEFAULT_SEVERITY[entry.action]

        # 敏感字段脱敏
        masked_before = _mask_sensitive(entry.before_state)
        masked_after = _mask_sensitive(entry.after_state)

        now = datetime.now(timezone.utc)
        row_id = uuid.uuid4()

        await db.execute(
            text("""
                INSERT INTO audit_logs (
                    id, tenant_id, action, actor_id, actor_type,
                    resource_type, resource_id,
                    before_state, after_state,
                    ip_address, user_agent,
                    severity, extra, created_at
                ) VALUES (
                    :id, :tenant_id, :action, :actor_id, :actor_type,
                    :resource_type, :resource_id,
                    :before_state::jsonb, :after_state::jsonb,
                    :ip_address, :user_agent,
                    :severity, :extra::jsonb, :created_at
                )
            """),
            {
                "id": str(row_id),
                "tenant_id": str(entry.tenant_id),
                "action": entry.action.value,
                "actor_id": entry.actor_id,
                "actor_type": entry.actor_type,
                "resource_type": entry.resource_type,
                "resource_id": entry.resource_id,
                "before_state": _json_dumps(masked_before),
                "after_state": _json_dumps(masked_after),
                "ip_address": entry.ip_address,
                "user_agent": entry.user_agent,
                "severity": effective_severity,
                "extra": _json_dumps(entry.extra),
                "created_at": now,
            },
        )

        log = logger.bind(
            audit_log_id=str(row_id),
            tenant_id=str(entry.tenant_id),
            action=entry.action.value,
            actor_id=entry.actor_id,
            actor_type=entry.actor_type,
            resource_type=entry.resource_type,
            resource_id=entry.resource_id,
            severity=effective_severity,
        )
        if effective_severity == "critical":
            log.critical("audit_log.critical_action")
        elif effective_severity == "warning":
            log.warning("audit_log.warning_action")
        else:
            log.info("audit_log.info_action")

    async def query_logs(
        self,
        tenant_id: UUID,
        actor_id: str | None,
        action: str | None,
        resource_type: str | None,
        severity: str | None,
        start_time: datetime | None,
        end_time: datetime | None,
        page: int,
        size: int,
        db: AsyncSession,
    ) -> dict:
        """
        分页查询审计日志。

        返回:
            {
                "items": [...],
                "total": int,
                "page": int,
                "size": int,
            }
        """
        if page < 1:
            page = 1
        if size < 1:
            size = 20
        if size > 200:
            size = 200
        offset = (page - 1) * size

        # 构建过滤条件
        conditions = ["tenant_id = :tenant_id"]
        params: dict[str, Any] = {"tenant_id": str(tenant_id)}

        if actor_id:
            conditions.append("actor_id = :actor_id")
            params["actor_id"] = actor_id
        if action:
            conditions.append("action = :action")
            params["action"] = action
        if resource_type:
            conditions.append("resource_type = :resource_type")
            params["resource_type"] = resource_type
        if severity:
            conditions.append("severity = :severity")
            params["severity"] = severity
        if start_time:
            conditions.append("created_at >= :start_time")
            params["start_time"] = start_time
        if end_time:
            conditions.append("created_at <= :end_time")
            params["end_time"] = end_time

        where_clause = " AND ".join(conditions)

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM audit_logs WHERE {where_clause}"),
            params,
        )
        total: int = count_result.scalar_one()

        rows_result = await db.execute(
            text(
                f"""
                SELECT id, tenant_id, action, actor_id, actor_type,
                       resource_type, resource_id,
                       before_state, after_state,
                       ip_address, user_agent,
                       severity, extra, created_at
                FROM audit_logs
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {**params, "limit": size, "offset": offset},
        )
        rows = rows_result.mappings().all()

        items = [dict(row) for row in rows]
        # 将 datetime 转为 ISO 字符串，UUID 转为字符串
        for item in items:
            for k, v in item.items():
                if isinstance(v, datetime):
                    item[k] = v.isoformat()
                elif isinstance(v, UUID):
                    item[k] = str(v)

        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        }

    async def get_security_alerts(
        self,
        tenant_id: UUID,
        hours: int = 24,
        db: AsyncSession = None,  # type: ignore[assignment]
    ) -> list[dict]:
        """
        返回最近 N 小时内的安全告警，包括:
          - LOGIN_FAILED > 5次/小时（同一 actor）
          - CONSTRAINT_OVERRIDE 任意一次
          - DATA_EXPORT > 3次/小时
          - 凌晨 2-5 点（服务器UTC+8本地时间）的 LOGIN 事件
        """
        alerts: list[dict] = []

        # 1. 登录失败 > 5次/小时，同一 actor
        fail_rows = await db.execute(
            text("""
                SELECT actor_id,
                       date_trunc('hour', created_at AT TIME ZONE 'Asia/Shanghai') AS hour_bucket,
                       COUNT(*) AS cnt
                FROM audit_logs
                WHERE tenant_id = :tenant_id
                  AND action = :action
                  AND created_at >= NOW() - INTERVAL ':hours hours'
                GROUP BY actor_id, hour_bucket
                HAVING COUNT(*) > 5
                ORDER BY cnt DESC
            """),
            {
                "tenant_id": str(tenant_id),
                "action": AuditAction.LOGIN_FAILED.value,
                "hours": hours,
            },
        )
        for row in fail_rows.mappings().all():
            alerts.append(
                {
                    "type": "excessive_login_failures",
                    "severity": "critical",
                    "actor_id": row["actor_id"],
                    "hour_bucket": str(row["hour_bucket"]),
                    "count": row["cnt"],
                    "message": f"actor {row['actor_id']} 在1小时内登录失败 {row['cnt']} 次",
                }
            )

        # 2. CONSTRAINT_OVERRIDE（任意一次即告警）
        override_rows = await db.execute(
            text("""
                SELECT id, actor_id, actor_type, resource_type, resource_id,
                       created_at, extra
                FROM audit_logs
                WHERE tenant_id = :tenant_id
                  AND action = :action
                  AND created_at >= NOW() - INTERVAL ':hours hours'
                ORDER BY created_at DESC
            """),
            {
                "tenant_id": str(tenant_id),
                "action": AuditAction.CONSTRAINT_OVERRIDE.value,
                "hours": hours,
            },
        )
        for row in override_rows.mappings().all():
            alerts.append(
                {
                    "type": "constraint_override",
                    "severity": "critical",
                    "actor_id": row["actor_id"],
                    "actor_type": row["actor_type"],
                    "resource_type": row["resource_type"],
                    "resource_id": row["resource_id"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "message": f"Agent 突破硬约束: {row['actor_id']} on {row['resource_type']}/{row['resource_id']}",
                }
            )

        # 3. DATA_EXPORT > 3次/小时
        export_rows = await db.execute(
            text("""
                SELECT actor_id,
                       date_trunc('hour', created_at AT TIME ZONE 'Asia/Shanghai') AS hour_bucket,
                       COUNT(*) AS cnt
                FROM audit_logs
                WHERE tenant_id = :tenant_id
                  AND action = :action
                  AND created_at >= NOW() - INTERVAL ':hours hours'
                GROUP BY actor_id, hour_bucket
                HAVING COUNT(*) > 3
                ORDER BY cnt DESC
            """),
            {
                "tenant_id": str(tenant_id),
                "action": AuditAction.DATA_EXPORT.value,
                "hours": hours,
            },
        )
        for row in export_rows.mappings().all():
            alerts.append(
                {
                    "type": "excessive_data_export",
                    "severity": "warning",
                    "actor_id": row["actor_id"],
                    "hour_bucket": str(row["hour_bucket"]),
                    "count": row["cnt"],
                    "message": f"actor {row['actor_id']} 在1小时内导出数据 {row['cnt']} 次",
                }
            )

        # 4. 凌晨 2-5 点的 LOGIN 事件（按本地时区 Asia/Shanghai）
        night_rows = await db.execute(
            text("""
                SELECT id, actor_id, actor_type, ip_address, created_at
                FROM audit_logs
                WHERE tenant_id = :tenant_id
                  AND action = :action
                  AND created_at >= NOW() - INTERVAL ':hours hours'
                  AND EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Shanghai') BETWEEN 2 AND 4
                ORDER BY created_at DESC
            """),
            {
                "tenant_id": str(tenant_id),
                "action": AuditAction.LOGIN.value,
                "hours": hours,
            },
        )
        for row in night_rows.mappings().all():
            alerts.append(
                {
                    "type": "nighttime_login",
                    "severity": "warning",
                    "actor_id": row["actor_id"],
                    "actor_type": row["actor_type"],
                    "ip_address": row["ip_address"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "message": f"凌晨异常登录: actor {row['actor_id']} at {row['created_at']}",
                }
            )

        return alerts

    def _mask_sensitive(self, data: dict | None) -> dict | None:
        """公开方法: 递归脱敏字典中的敏感字段（供外部测试验证）。"""
        return _mask_sensitive(data)


# ────────────────────────────────────────────────────────────────────
# 内部工具函数
# ────────────────────────────────────────────────────────────────────


def _json_dumps(obj: Any) -> str | None:
    """将 dict 序列化为 JSON 字符串，None 返回 None。"""
    if obj is None:
        return None
    import json

    return json.dumps(obj, ensure_ascii=False, default=str)
