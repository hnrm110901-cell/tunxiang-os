"""
信号路由规则模型

解决的问题：
  signal_bus.py 只有 3 条硬编码路由规则，每次新增路由都需要改代码。
  本模型提供数据库驱动的可配置路由规则表，允许运营后台动态增删改路由。

字段说明：
  condition_type  — 触发条件类型（review_negative / inventory_near_expiry / large_table）
  condition_params — 条件参数 JSON（如 {"min_table_size": 6, "rating_threshold": 3}）
  action_type     — 触发动作类型（repair_journey / waste_push / referral_engine）
  action_params   — 动作参数 JSON（如 {"journey_template": "review_repair"}）
  priority        — 优先级，数字越小越优先（同 condition 多条规则时）
  enabled         — 是否生效
  created_by      — 创建人（审计）
"""
import enum
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String
from sqlalchemy import Enum as SQLEnum

from .base import Base


class SignalConditionType(str, enum.Enum):
    REVIEW_NEGATIVE       = "review_negative"        # 差评（评分 ≤ 阈值）
    INVENTORY_NEAR_EXPIRY = "inventory_near_expiry"  # 临期/低库存
    LARGE_TABLE_BOOKING   = "large_table_booking"    # 大桌预订
    REVENUE_DROP          = "revenue_drop"           # 营收骤降
    CHURN_RISK            = "churn_risk"             # 流失风险会员
    CUSTOM                = "custom"                 # 自定义（由 condition_params 描述）


class SignalActionType(str, enum.Enum):
    REPAIR_JOURNEY  = "repair_journey"   # 差评修复旅程
    WASTE_PUSH      = "waste_push"       # 废料预警推送
    REFERRAL_ENGINE = "referral_engine"  # 裂变识别
    WECHAT_ALERT    = "wechat_alert"     # 企业微信告警
    CELERY_TASK     = "celery_task"      # 触发 Celery 任务（灵活扩展）
    WEBHOOK         = "webhook"          # 调用外部 Webhook


class SignalRoutingRule(Base):
    """信号路由规则表"""
    __tablename__ = "signal_routing_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)

    condition_type   = Column(
        SQLEnum(SignalConditionType, values_callable=lambda x: [e.value for e in x]),
        nullable=False, index=True,
    )
    condition_params = Column(JSON, nullable=False, default=dict, comment="触发条件参数")

    action_type   = Column(
        SQLEnum(SignalActionType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    action_params = Column(JSON, nullable=False, default=dict, comment="行动参数")

    priority   = Column(Integer, nullable=False, default=100, comment="优先级，越小越先执行")
    enabled    = Column(Boolean, nullable=False, default=True, comment="是否生效")
    created_by = Column(String(64), nullable=True, comment="创建人")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    description = Column(String(256), nullable=True, comment="规则说明（运营可读）")
