"""屯象OS tx-agent 合规预警 Agent：证件到期、连续低绩效、考勤异常的扫描与预警摘要。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any, Optional

import structlog
from constraints.decorator import with_constraint_check
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from ..base import ActionConfig, AgentResult, SkillAgent

logger = structlog.get_logger(__name__)


def _severity_for_document_expiry(expiry: date | None, today: date) -> str:
    if expiry is None:
        return "low"
    days = (expiry - today).days
    if days < 0:
        return "critical"
    if days <= 7:
        return "critical"
    if days <= 30:
        return "high"
    if days <= 60:
        return "medium"
    return "low"


def _document_alert_from_row(
    row: dict[str, Any],
    today: date,
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    emp_id = row.get("employee_id") or ""
    name = row.get("emp_name") or ""
    sid = row.get("store_id") or ""
    for field, label in (
        ("health_cert_expiry", "健康证"),
        ("id_card_expiry", "身份证"),
    ):
        exp = row.get(field)
        if exp is None:
            continue
        if isinstance(exp, datetime):
            exp_d = exp.date()
        elif isinstance(exp, date):
            exp_d = exp
        else:
            continue
        if exp_d > today + timedelta(days=90):
            continue
        sev = _severity_for_document_expiry(exp_d, today)
        alerts.append(
            {
                "alert_id": f"doc:{emp_id}:{field}",
                "category": "document",
                "severity": sev,
                "title": f"{label}即将或已经到期",
                "detail": f"{name} 的{label}将于 {exp_d.isoformat()} 到期",
                "employee_id": emp_id,
                "employee_name": name,
                "store_id": sid,
                "meta": {"document_type": label, "expiry_date": exp_d.isoformat()},
            }
        )
    return alerts


def _bind_store(
    store_id: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    if not store_id or not str(store_id).strip():
        return None, None
    s = str(store_id).strip()
    return s, s


async def _svc_scan_documents(
    db: Any,
    tenant_id: str,
    store_id: Optional[str],
) -> list[dict[str, Any]]:
    today = date.today()
    bound_uuid, _ = _bind_store(store_id)
    q = text("""
        SELECT e.id::text AS employee_id, e.emp_name, e.store_id::text AS store_id,
               e.health_cert_expiry, e.id_card_expiry
        FROM employees e
        WHERE e.tenant_id = CAST(:tenant_id AS uuid)
          AND e.is_deleted = false
          AND COALESCE(e.is_active, true) = true
          AND (
            (e.health_cert_expiry IS NOT NULL
             AND e.health_cert_expiry <= CURRENT_DATE + INTERVAL '90 days')
            OR (e.id_card_expiry IS NOT NULL
                AND e.id_card_expiry <= CURRENT_DATE + INTERVAL '90 days')
          )
          AND (
            CAST(:bound_uuid AS text) IS NULL
            OR e.store_id = CAST(:bound_uuid AS uuid)
          )
        ORDER BY LEAST(
            COALESCE(e.health_cert_expiry, DATE '9999-12-31'),
            COALESCE(e.id_card_expiry, DATE '9999-12-31')
        )
        LIMIT 200
    """)
    try:
        result = await db.execute(
            q,
            {"tenant_id": tenant_id, "bound_uuid": bound_uuid},
        )
        rows = [dict(r) for r in result.mappings()]
    except (OperationalError, ProgrammingError) as exc:
        logger.warning(
            "compliance_scan_documents_failed",
            error=str(exc),
            tenant_id=tenant_id,
        )
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        out.extend(_document_alert_from_row(row, today))
    return out


def _performance_severity(score: str) -> str:
    s = (score or "").strip().upper()
    if s in ("F", "E", "1"):
        return "critical"
    if s in ("D", "2"):
        return "high"
    return "medium"


async def _svc_scan_performance(
    db: Any,
    tenant_id: str,
    store_id: Optional[str],
) -> list[dict[str, Any]]:
    bound_uuid, _ = _bind_store(store_id)
    q = text("""
        SELECT e.id::text AS employee_id, e.emp_name, e.store_id::text AS store_id,
               e.performance_score
        FROM employees e
        WHERE e.tenant_id = CAST(:tenant_id AS uuid)
          AND e.is_deleted = false
          AND COALESCE(e.is_active, true) = true
          AND e.performance_score IS NOT NULL
          AND TRIM(e.performance_score) <> ''
          AND (
            e.performance_score ~ '^[12]$'
            OR UPPER(TRIM(e.performance_score)) IN ('D', 'E', 'F')
          )
          AND (
            CAST(:bound_uuid AS text) IS NULL
            OR e.store_id = CAST(:bound_uuid AS uuid)
          )
        ORDER BY e.performance_score
        LIMIT 200
    """)
    try:
        result = await db.execute(
            q,
            {"tenant_id": tenant_id, "bound_uuid": bound_uuid},
        )
        rows = [dict(r) for r in result.mappings()]
    except (OperationalError, ProgrammingError) as exc:
        logger.warning(
            "compliance_scan_performance_failed",
            error=str(exc),
            tenant_id=tenant_id,
        )
        return []
    alerts: list[dict[str, Any]] = []
    for row in rows:
        score = str(row.get("performance_score") or "")
        sev = _performance_severity(score)
        alerts.append(
            {
                "alert_id": f"perf:{row.get('employee_id')}:{score}",
                "category": "performance",
                "severity": sev,
                "title": "连续低绩效",
                "detail": f"{row.get('emp_name') or ''} 当前绩效档为 {score}，需关注改进",
                "employee_id": row.get("employee_id") or "",
                "employee_name": row.get("emp_name") or "",
                "store_id": row.get("store_id") or "",
                "meta": {"performance_score": score},
            }
        )
    return alerts


def _attendance_severity(status: str, late_minutes: Any, early_leave: Any) -> str:
    st = (status or "").lower()
    if st == "absent":
        return "critical"
    if st == "missing_clock_out":
        return "high"
    if st == "late":
        late = int(late_minutes or 0)
        return "high" if late > 30 else "medium"
    if st == "early_leave":
        return "medium"
    return "low"


async def _svc_scan_attendance(
    db: Any,
    tenant_id: str,
    store_id: Optional[str],
) -> list[dict[str, Any]]:
    _, bound_store_text = _bind_store(store_id)
    q = text("""
        SELECT da.id::text AS attendance_id, da.employee_id,
               da.store_id::text AS store_id, da.date, da.status,
               COALESCE(da.late_minutes, 0) AS late_minutes,
               COALESCE(da.early_leave_minutes, 0) AS early_leave_minutes,
               e.emp_name
        FROM daily_attendance da
        LEFT JOIN employees e
          ON e.tenant_id = da.tenant_id
         AND e.id::text = da.employee_id
         AND e.is_deleted = false
        WHERE da.tenant_id = CAST(:tenant_id AS uuid)
          AND COALESCE(da.is_deleted, false) = false
          AND da.date >= CURRENT_DATE - INTERVAL '14 days'
          AND da.status IN ('absent', 'late', 'missing_clock_out', 'early_leave')
          AND (
            CAST(:bound_store_text AS text) IS NULL
            OR da.store_id = CAST(:bound_store_text AS text)
          )
        ORDER BY da.date DESC, da.status
        LIMIT 300
    """)
    try:
        result = await db.execute(
            q,
            {"tenant_id": tenant_id, "bound_store_text": bound_store_text},
        )
        rows = [dict(r) for r in result.mappings()]
    except (OperationalError, ProgrammingError) as exc:
        logger.warning(
            "compliance_scan_attendance_failed",
            error=str(exc),
            tenant_id=tenant_id,
        )
        return []
    alerts: list[dict[str, Any]] = []
    for row in rows:
        st = str(row.get("status") or "")
        sev = _attendance_severity(st, row.get("late_minutes"), row.get("early_leave_minutes"))
        d = row.get("date")
        d_str = d.isoformat() if hasattr(d, "isoformat") else str(d)
        name = row.get("emp_name") or row.get("employee_id") or ""
        alerts.append(
            {
                "alert_id": f"att:{row.get('attendance_id')}",
                "category": "attendance",
                "severity": sev,
                "title": f"考勤异常：{st}",
                "detail": f"{name} 在 {d_str} 状态为 {st}",
                "employee_id": str(row.get("employee_id") or ""),
                "employee_name": name if isinstance(name, str) else str(name),
                "store_id": str(row.get("store_id") or ""),
                "meta": {
                    "date": d_str,
                    "status": st,
                    "late_minutes": row.get("late_minutes"),
                    "early_leave_minutes": row.get("early_leave_minutes"),
                },
            }
        )
    return alerts


def _svc_summarize_severities(alerts: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"total": len(alerts), "critical": 0, "high": 0, "medium": 0, "low": 0}
    buckets = ("critical", "high", "medium", "low")
    for a in alerts:
        sev = (a.get("severity") or "low").lower()
        if sev in buckets:
            counts[sev] += 1
        else:
            counts["low"] += 1
    return counts


def _svc_merge_summaries(
    documents: list[dict[str, Any]],
    performance: list[dict[str, Any]],
    attendance: list[dict[str, Any]],
) -> dict[str, int]:
    merged = documents + performance + attendance
    return _svc_summarize_severities(merged)


async def _svc_get_alert_summary(
    db: Any,
    tenant_id: str,
    store_id: Optional[str],
) -> dict[str, Any]:
    documents = await _svc_scan_documents(db, tenant_id, store_id)
    performance = await _svc_scan_performance(db, tenant_id, store_id)
    attendance = await _svc_scan_attendance(db, tenant_id, store_id)
    summary = _svc_merge_summaries(documents, performance, attendance)
    return {
        "summary": summary,
        "counts_by_category": {
            "documents": len(documents),
            "performance": len(performance),
            "attendance": len(attendance),
        },
        "documents": documents,
        "performance": performance,
        "attendance": attendance,
    }


compliance_alert_service = SimpleNamespace(
    scan_documents=_svc_scan_documents,
    scan_performance=_svc_scan_performance,
    scan_attendance=_svc_scan_attendance,
    summarize_severities=_svc_summarize_severities,
    merge_summaries=_svc_merge_summaries,
    get_alert_summary=_svc_get_alert_summary,
)


class ComplianceAlertAgent(SkillAgent):
    """合规预警 Skill：证件、绩效、考勤三类扫描与汇总。"""

    agent_id = "compliance_alert"
    agent_name = "合规预警"
    description = "证件到期、连续低绩效、考勤异常的自动扫描与预警推送"
    priority = "P1"
    run_location = "cloud"

    # Sprint D1 / PR 批次 5：合规预警只扫描+推送告警，不决策资金/食材/出餐，豁免三约束
    constraint_scope = set()
    constraint_waived_reason = (
        "合规预警纯扫描与告警推送（HR 证件/绩效/考勤异常），"
        "不触发毛利/食安/出餐体验维度的业务决策，属于观察类 Skill"
    )

    def get_supported_actions(self) -> list[str]:
        return [
            "scan_all",
            "scan_documents",
            "scan_performance",
            "scan_attendance",
            "get_alert_summary",
        ]

    def get_action_config(self, action: str) -> ActionConfig:
        """合规预警 Agent 的 action 级会话策略"""
        configs = {
            # 全量扫描耗时较长，允许重试
            "scan_all": ActionConfig(
                max_retries=2,
                risk_level="medium",
            ),
            # 各分项扫描可重试
            "scan_documents": ActionConfig(max_retries=2, risk_level="medium"),
            "scan_performance": ActionConfig(max_retries=1, risk_level="medium"),
            "scan_attendance": ActionConfig(max_retries=1, risk_level="medium"),
            # 预警摘要低风险
            "get_alert_summary": ActionConfig(max_retries=1, risk_level="low"),
        }
        return configs.get(action, ActionConfig())

    def _store_scope(self, params: dict[str, Any]) -> Optional[str]:
        sid = params.get("store_id")
        if sid is not None and str(sid).strip():
            return str(sid).strip()
        if self.store_id is not None and str(self.store_id).strip():
            return str(self.store_id).strip()
        return None

    # Sprint D1：硬阻断装饰器 — Skill 类级 constraint_scope=set() 已声明豁免，
    # 装饰器仅作为 CI 覆盖标记；run_checks 因 payload 中无 price/safety/serve 字段全部 skipped
    @with_constraint_check(skill_name="compliance_alert")
    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch: dict[str, Any] = {
            "scan_all": self._scan_all,
            "scan_documents": self._scan_documents,
            "scan_performance": self._scan_performance,
            "scan_attendance": self._scan_attendance,
            "get_alert_summary": self._get_alert_summary,
        }
        handler = dispatch.get(action)
        if handler is None:
            return AgentResult(
                success=False,
                action=action,
                error=f"Unsupported: {action}",
            )
        return await handler(params)

    async def _scan_all(self, params: dict[str, Any]) -> AgentResult:
        store_id = self._store_scope(params)
        if self._db:
            documents = await compliance_alert_service.scan_documents(self._db, self.tenant_id, store_id)
            performance = await compliance_alert_service.scan_performance(self._db, self.tenant_id, store_id)
            attendance = await compliance_alert_service.scan_attendance(self._db, self.tenant_id, store_id)
        else:
            logger.warning("compliance_scan_all_no_db", tenant_id=self.tenant_id)
            documents = []
            performance = []
            attendance = []
        summary = compliance_alert_service.merge_summaries(documents, performance, attendance)
        n = summary["total"]
        m = summary["critical"]
        return AgentResult(
            success=True,
            action="scan_all",
            data={
                "documents": documents,
                "performance": performance,
                "attendance": attendance,
                "summary": summary,
            },
            reasoning=f"合规扫描完成: {n}项预警，其中{m}项紧急",
            confidence=0.95,
        )

    async def _scan_documents(self, params: dict[str, Any]) -> AgentResult:
        store_id = self._store_scope(params)
        if self._db:
            documents = await compliance_alert_service.scan_documents(self._db, self.tenant_id, store_id)
        else:
            logger.warning("compliance_scan_documents_no_db", tenant_id=self.tenant_id)
            documents = []
        summary = compliance_alert_service.summarize_severities(documents)
        return AgentResult(
            success=True,
            action="scan_documents",
            data={"documents": documents, "summary": summary},
            reasoning=f"证件扫描完成，共 {len(documents)} 条预警",
            confidence=0.92,
        )

    async def _scan_performance(self, params: dict[str, Any]) -> AgentResult:
        store_id = self._store_scope(params)
        if self._db:
            performance = await compliance_alert_service.scan_performance(self._db, self.tenant_id, store_id)
        else:
            logger.warning("compliance_scan_performance_no_db", tenant_id=self.tenant_id)
            performance = []
        summary = compliance_alert_service.summarize_severities(performance)
        return AgentResult(
            success=True,
            action="scan_performance",
            data={"performance": performance, "summary": summary},
            reasoning=f"低绩效扫描完成，共 {len(performance)} 条预警",
            confidence=0.9,
        )

    async def _scan_attendance(self, params: dict[str, Any]) -> AgentResult:
        store_id = self._store_scope(params)
        if self._db:
            attendance = await compliance_alert_service.scan_attendance(self._db, self.tenant_id, store_id)
        else:
            logger.warning("compliance_scan_attendance_no_db", tenant_id=self.tenant_id)
            attendance = []
        summary = compliance_alert_service.summarize_severities(attendance)
        return AgentResult(
            success=True,
            action="scan_attendance",
            data={"attendance": attendance, "summary": summary},
            reasoning=f"考勤异常扫描完成，共 {len(attendance)} 条预警",
            confidence=0.88,
        )

    async def _get_alert_summary(self, params: dict[str, Any]) -> AgentResult:
        store_id = self._store_scope(params)
        if self._db:
            payload = await compliance_alert_service.get_alert_summary(self._db, self.tenant_id, store_id)
        else:
            logger.warning("compliance_alert_summary_no_db", tenant_id=self.tenant_id)
            payload = {
                "summary": {"total": 0, "critical": 0, "high": 0, "medium": 0, "low": 0},
                "counts_by_category": {
                    "documents": 0,
                    "performance": 0,
                    "attendance": 0,
                },
                "documents": [],
                "performance": [],
                "attendance": [],
            }
        return AgentResult(
            success=True,
            action="get_alert_summary",
            data=payload,
            reasoning=(f"预警摘要：合计 {payload['summary']['total']} 项，紧急 {payload['summary']['critical']} 项"),
            confidence=0.93,
        )
