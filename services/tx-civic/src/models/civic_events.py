"""tx-civic 事件类型定义 — 接入屯象OS统一事件总线"""

from enum import Enum


class CivicEventType(str, Enum):
    """合规事件类型"""

    # 追溯事件
    INBOUND_RECORDED = "civic.trace.inbound_recorded"
    SUPPLIER_REGISTERED = "civic.trace.supplier_registered"
    SUPPLIER_CERT_EXPIRING = "civic.trace.supplier_cert_expiring"
    TRACE_INCOMPLETE = "civic.trace.incomplete"

    # 明厨亮灶事件
    DEVICE_REGISTERED = "civic.kitchen.device_registered"
    DEVICE_OFFLINE = "civic.kitchen.device_offline"
    AI_ALERT_TRIGGERED = "civic.kitchen.ai_alert_triggered"
    AI_ALERT_RESOLVED = "civic.kitchen.ai_alert_resolved"

    # 环保事件
    EMISSION_RECORDED = "civic.env.emission_recorded"
    EMISSION_EXCEEDED = "civic.env.emission_exceeded"
    WASTE_DISPOSED = "civic.env.waste_disposed"

    # 消防事件
    INSPECTION_COMPLETED = "civic.fire.inspection_completed"
    EQUIPMENT_OVERDUE = "civic.fire.equipment_overdue"

    # 证照事件
    LICENSE_REGISTERED = "civic.license.registered"
    LICENSE_EXPIRING = "civic.license.expiring"
    LICENSE_EXPIRED = "civic.license.expired"
    HEALTH_CERT_EXPIRING = "civic.license.health_cert_expiring"

    # 上报事件
    SUBMISSION_SUCCESS = "civic.submission.success"
    SUBMISSION_FAILED = "civic.submission.failed"

    # 评分事件
    SCORE_UPDATED = "civic.score.updated"
    RISK_LEVEL_CHANGED = "civic.score.risk_level_changed"
