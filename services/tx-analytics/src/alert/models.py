"""预警数据模型 — Pydantic V2

所有金额字段使用分（integer），后缀 _fen。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AlertSeverity(str, Enum):
    """预警严重级别"""

    P0_CRITICAL = "P0"  # 紧急 — 需2小时内处理
    P1_IMPORTANT = "P1"  # 重要 — 需4小时内处理
    P2_NORMAL = "P2"  # 一般 — 需次日（24小时内）处理
    P3_INFO = "P3"  # 提示 — 无需紧急处理

    @property
    def sla_hours(self) -> int:
        mapping: dict[str, int] = {"P0": 2, "P1": 4, "P2": 24, "P3": 72}
        return mapping.get(self.value, 72)

    @property
    def label_cn(self) -> str:
        mapping: dict[str, str] = {"P0": "紧急", "P1": "重要", "P2": "一般", "P3": "提示"}
        return mapping.get(self.value, "未知")


class AlertStatus(str, Enum):
    """预警处理状态"""

    FIRED = "fired"
    ACKNOWLEDGED = "acknowledged"
    PROCESSING = "processing"
    RESOLVED = "resolved"
    CLOSED = "closed"
    IGNORED = "ignored"

    @property
    def label_cn(self) -> str:
        mapping: dict[str, str] = {
            "fired": "已触发", "acknowledged": "已认领", "processing": "处理中",
            "resolved": "已解决", "closed": "已关闭", "ignored": "已忽略",
        }
        return mapping.get(self.value, "未知")


class AlertRule(BaseModel):
    """预警规则定义"""

    rule_id: str = Field(...)
    name: str = Field(...)
    description: str = Field("")
    domain: str = Field(...)
    severity: AlertSeverity = Field(...)
    metric_field: str = Field(...)
    condition: str = Field(...)
    threshold: float = Field(...)
    lookback_period: str = Field("1d")
    cooldown_minutes: int = Field(60, ge=0)
    enabled: bool = Field(True)
    notify_roles: list[str] = Field(default_factory=list)
    notify_channels: list[str] = Field(default_factory=lambda: ["in_app"])
    auto_escalation_minutes: Optional[int] = Field(None)
    escalate_to_roles: list[str] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)


class Alert(BaseModel):
    """预警实例"""

    alert_id: str = Field(default="")
    rule_id: str = Field(...)
    tenant_id: str = Field(...)
    store_id: Optional[str] = Field(None)
    severity: AlertSeverity = Field(default=AlertSeverity.P2_NORMAL)
    status: AlertStatus = Field(default=AlertStatus.FIRED)
    title: str = Field(...)
    description: str = Field("")
    metric_name: str = Field(...)
    metric_value: float = Field(...)
    baseline_value: Optional[float] = Field(None)
    deviation_pct: Optional[float] = Field(None)
    fired_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    acknowledged_at: Optional[str] = Field(None)
    acknowledged_by: Optional[str] = Field(None)
    assigned_to: Optional[str] = Field(None)
    resolved_at: Optional[str] = Field(None)
    resolved_by: Optional[str] = Field(None)
    closed_at: Optional[str] = Field(None)
    sla_deadline: Optional[str] = Field(None)
    sla_breached: bool = Field(False)
    handler_notes: str = Field("")
    resolution_notes: str = Field("")
    resolution_type: Optional[str] = Field(None)
    meta: dict = Field(default_factory=dict)

    def mark_acknowledged(self, user_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.status = AlertStatus.ACKNOWLEDGED
        self.acknowledged_at = now
        self.acknowledged_by = user_id
        self.assigned_to = user_id

    def mark_processing(self) -> None:
        self.status = AlertStatus.PROCESSING

    def mark_resolved(self, user_id: str, notes: str, resolution_type: str = "fixed") -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.status = AlertStatus.RESOLVED
        self.resolved_at = now
        self.resolved_by = user_id
        self.resolution_notes = notes
        self.resolution_type = resolution_type

    def mark_closed(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.status = AlertStatus.CLOSED
        self.closed_at = now

    def mark_ignored(self, notes: str) -> None:
        self.status = AlertStatus.IGNORED
        self.handler_notes = notes

    def compute_sla_deadline(self) -> None:
        deadline = datetime.now(timezone.utc) + timedelta(hours=self.severity.sla_hours)
        self.sla_deadline = deadline.isoformat()

    def check_sla(self) -> bool:
        if not self.sla_deadline:
            self.compute_sla_deadline()
        if not self.sla_deadline:
            return False
        deadline = datetime.fromisoformat(self.sla_deadline)
        self.sla_breached = datetime.now(timezone.utc) > deadline
        return self.sla_breached

    def to_row(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "tenant_id": self.tenant_id,
            "store_id": self.store_id,
            "severity": self.severity.value,
            "status": self.status.value,
            "title": self.title,
            "description": self.description,
            "metric_name": self.metric_name,
            "metric_value": self.metric_value,
            "baseline_value": self.baseline_value,
            "deviation_pct": self.deviation_pct,
            "fired_at": self.fired_at,
            "acknowledged_at": self.acknowledged_at,
            "acknowledged_by": self.acknowledged_by,
            "assigned_to": self.assigned_to,
            "resolved_at": self.resolved_at,
            "resolved_by": self.resolved_by,
            "closed_at": self.closed_at,
            "sla_deadline": self.sla_deadline,
            "sla_breached": self.sla_breached,
            "handler_notes": self.handler_notes,
            "resolution_notes": self.resolution_notes,
            "resolution_type": self.resolution_type,
            "meta": self.meta,
        }

    @classmethod
    def from_row(cls, row: dict) -> "Alert":
        return cls(
            alert_id=str(row.get("alert_id", "")),
            rule_id=str(row.get("rule_id", "")),
            tenant_id=str(row.get("tenant_id", "")),
            store_id=str(row["store_id"]) if row.get("store_id") else None,
            severity=AlertSeverity(row.get("severity", "P2")),
            status=AlertStatus(row.get("status", "fired")),
            title=str(row.get("title", "")),
            description=str(row.get("description", "")),
            metric_name=str(row.get("metric_name", "")),
            metric_value=float(row.get("metric_value", 0)),
            baseline_value=float(row["baseline_value"]) if row.get("baseline_value") is not None else None,
            deviation_pct=float(row["deviation_pct"]) if row.get("deviation_pct") is not None else None,
            fired_at=str(row.get("fired_at", "")),
            acknowledged_at=str(row["acknowledged_at"]) if row.get("acknowledged_at") else None,
            acknowledged_by=str(row["acknowledged_by"]) if row.get("acknowledged_by") else None,
            assigned_to=str(row["assigned_to"]) if row.get("assigned_to") else None,
            resolved_at=str(row["resolved_at"]) if row.get("resolved_at") else None,
            resolved_by=str(row["resolved_by"]) if row.get("resolved_by") else None,
            closed_at=str(row["closed_at"]) if row.get("closed_at") else None,
            sla_deadline=str(row["sla_deadline"]) if row.get("sla_deadline") else None,
            sla_breached=bool(row.get("sla_breached", False)),
            handler_notes=str(row.get("handler_notes", "")),
            resolution_notes=str(row.get("resolution_notes", "")),
            resolution_type=str(row["resolution_type"]) if row.get("resolution_type") else None,
            meta=row.get("meta", {}) or {},
        )


class AlertStats(BaseModel):
    """告警统计"""

    total: int = 0
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)
    by_domain: dict[str, int] = Field(default_factory=dict)
    sla_breached_count: int = 0
    avg_resolution_minutes: Optional[float] = None
