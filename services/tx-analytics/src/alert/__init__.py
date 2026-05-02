"""
预警闭环引擎（Alert Closed-Loop Engine）— BI-2.2

将基础异常检测升级为完整闭环：
  预警检测 → 推送通知 → 认领分发 → 处理 → 验证 → 关闭

核心组件：
  - AlertRule / Alert / AlertSeverity / AlertStatus — 数据模型
  - AlertEngine — 规则评估 + 告警触发 + 生命周期管理 + SLA 追踪
  - AlertNotifier — 多渠道推送（应用内/企微/短信）
  - DEFAULT_ALERT_RULES — 30+ 条预置预警规则

API（alert_routes.py）：
  GET    /api/v1/analytics/alerts/rules              — 列出所有预警规则
  PUT    /api/v1/analytics/alerts/rules/{rule_id}     — 更新规则
  GET    /api/v1/analytics/alerts/active              — 活跃告警列表
  GET    /api/v1/analytics/alerts/{alert_id}          — 告警详情
  POST   /api/v1/analytics/alerts/{alert_id}/acknowledge — 认领
  POST   /api/v1/analytics/alerts/{alert_id}/resolve     — 解决
  POST   /api/v1/analytics/alerts/{alert_id}/close       — 关闭
  GET    /api/v1/analytics/alerts/stats                — 告警统计
"""

from .models import Alert, AlertRule, AlertSeverity, AlertStatus
from .engine import AlertEngine
from .notifier import AlertNotifier
from .rules_registry import DEFAULT_ALERT_RULES

__all__ = [
    "Alert",
    "AlertRule",
    "AlertSeverity",
    "AlertStatus",
    "AlertEngine",
    "AlertNotifier",
    "DEFAULT_ALERT_RULES",
]
