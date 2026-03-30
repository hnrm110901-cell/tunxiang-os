"""会员生命周期事件模型

# SCHEMA SQL:
#
# -- 在 members/customers 表上添加 lifecycle_stage 列
# ALTER TABLE members ADD COLUMN IF NOT EXISTS lifecycle_stage VARCHAR(20) DEFAULT 'new';
# -- lifecycle_stage 枚举值: new / active / dormant / churned / reactivated
#
# -- 生命周期事件历史表（记录每次阶段变更）
# CREATE TABLE lifecycle_events (
#     id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#     tenant_id       UUID NOT NULL,
#     member_id       UUID NOT NULL,
#     from_stage      VARCHAR(20),
#     to_stage        VARCHAR(20) NOT NULL,
#     trigger_reason  VARCHAR(100),   -- 例：days_since_last_visit=45
#     action_taken    VARCHAR(100),   -- 例：coupon_sent / wecom_pushed / none
#     created_at      TIMESTAMPTZ DEFAULT NOW()
# );
# CREATE INDEX idx_lifecycle_events_tenant_member
#     ON lifecycle_events(tenant_id, member_id);
# CREATE INDEX idx_lifecycle_events_tenant_created
#     ON lifecycle_events(tenant_id, created_at DESC);
#
# -- RLS
# ALTER TABLE lifecycle_events ENABLE ROW LEVEL SECURITY;
# CREATE POLICY lifecycle_events_tenant_isolation ON lifecycle_events
#     USING (tenant_id = (current_setting('app.tenant_id', true))::uuid);
#
# -- 生命周期阶段配置表（每个阶段的阈值和自动触发动作）
# CREATE TABLE lifecycle_configs (
#     id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
#     tenant_id           UUID NOT NULL,
#     stage               VARCHAR(20) NOT NULL,   -- new/active/dormant/churned
#     days_threshold      INTEGER,                -- 判断天数阈值
#     auto_action         VARCHAR(50),            -- coupon / wecom_message / sms / none
#     coupon_template_id  UUID,
#     message_template    TEXT,
#     is_active           BOOLEAN DEFAULT TRUE,
#     created_at          TIMESTAMPTZ DEFAULT NOW(),
#     updated_at          TIMESTAMPTZ DEFAULT NOW(),
#     UNIQUE(tenant_id, stage)
# );
# CREATE INDEX idx_lifecycle_configs_tenant
#     ON lifecycle_configs(tenant_id, is_active);
#
# -- RLS
# ALTER TABLE lifecycle_configs ENABLE ROW LEVEL SECURITY;
# CREATE POLICY lifecycle_configs_tenant_isolation ON lifecycle_configs
#     USING (tenant_id = (current_setting('app.tenant_id', true))::uuid);
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID


# ── 枚举值常量（与 DB VARCHAR 对应） ──────────────────────────

LIFECYCLE_STAGES = ("new", "active", "dormant", "churned", "reactivated")


@dataclass
class LifecycleEvent:
    """lifecycle_events 行的 Python 表示（无 ORM 依赖）。

    字段说明：
    - from_stage: 变更前阶段（首次分类时为 None）
    - to_stage: 变更后阶段
    - trigger_reason: 人类可读的触发原因，如 "days_since_last_visit=45"
    - action_taken: 已执行的营销动作，如 "coupon_sent" / "wecom_pushed" / "none"
    """

    tenant_id: UUID
    member_id: UUID
    to_stage: str
    from_stage: Optional[str] = None
    trigger_reason: Optional[str] = None
    action_taken: str = "none"
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        if self.to_stage not in LIFECYCLE_STAGES:
            raise ValueError(
                f"to_stage 必须是 {LIFECYCLE_STAGES} 之一，got: {self.to_stage!r}"
            )
        if self.from_stage is not None and self.from_stage not in LIFECYCLE_STAGES:
            raise ValueError(
                f"from_stage 必须是 {LIFECYCLE_STAGES} 之一，got: {self.from_stage!r}"
            )

    def to_dict(self) -> dict:
        return {
            "tenant_id": str(self.tenant_id),
            "member_id": str(self.member_id),
            "from_stage": self.from_stage,
            "to_stage": self.to_stage,
            "trigger_reason": self.trigger_reason,
            "action_taken": self.action_taken,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class LifecycleConfig:
    """lifecycle_configs 行的 Python 表示。

    字段说明：
    - stage: 所属阶段（new/active/dormant/churned）
    - days_threshold: 判断阈值（天数）。None 表示该阶段不使用天数判断
    - auto_action: 自动触发动作（coupon / wecom_message / sms / none）
    - coupon_template_id: 发券时使用的模板 ID
    - message_template: 推送消息模板文本
    - is_active: 该规则是否启用
    """

    tenant_id: UUID
    stage: str
    days_threshold: Optional[int] = None
    auto_action: str = "none"
    coupon_template_id: Optional[UUID] = None
    message_template: Optional[str] = None
    is_active: bool = True

    def __post_init__(self) -> None:
        if self.stage not in LIFECYCLE_STAGES:
            raise ValueError(
                f"stage 必须是 {LIFECYCLE_STAGES} 之一，got: {self.stage!r}"
            )
        valid_actions = ("coupon", "wecom_message", "sms", "none")
        if self.auto_action not in valid_actions:
            raise ValueError(
                f"auto_action 必须是 {valid_actions} 之一，got: {self.auto_action!r}"
            )

    def to_dict(self) -> dict:
        return {
            "tenant_id": str(self.tenant_id),
            "stage": self.stage,
            "days_threshold": self.days_threshold,
            "auto_action": self.auto_action,
            "coupon_template_id": (
                str(self.coupon_template_id) if self.coupon_template_id else None
            ),
            "message_template": self.message_template,
            "is_active": self.is_active,
        }
