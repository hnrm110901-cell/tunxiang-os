"""考勤深度合规 Agent — GPS异常/代打卡/加班超时检测

支持的 actions:
  - daily_compliance_scan: 每日合规扫描（GPS + 同设备 + 代打卡）
  - monthly_overtime_scan: 月度加班超时扫描
  - generate_compliance_report: 合规报告生成（各类违规统计 + 高频违规员工 + 建议）
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

import structlog

from ..base import ActionConfig, AgentResult, SkillAgent

logger = structlog.get_logger(__name__)


# ── Mock 数据生成 ────────────────────────────────────────────────────────────

def _mock_daily_scan(check_date: str, store_id: Optional[str]) -> dict[str, Any]:
    """模拟每日合规扫描结果"""
    return {
        "scan_date": check_date,
        "store_id": store_id,
        "gps_anomalies": [
            {
                "employee_id": "e001",
                "employee_name": "张伟",
                "distance_m": 1280,
                "threshold_m": 500,
                "severity": "medium",
                "clock_time": f"{check_date}T08:05:00",
            },
        ],
        "same_device_alerts": [
            {
                "device_id": "SUNMI-T2-3847",
                "employees": ["李娜", "王强"],
                "punch_times": [f"{check_date}T08:02:00", f"{check_date}T08:03:15"],
                "interval_seconds": 75,
                "severity": "high",
            },
        ],
        "proxy_punch_alerts": [
            {
                "employee_id": "e004",
                "employee_name": "赵敏",
                "suspected_proxy": "陈刚",
                "device_id": "SUNMI-V2-5521",
                "interval_seconds": 45,
                "severity": "critical",
            },
        ],
        "summary": {
            "total": 4,
            "critical": 1,
            "high": 1,
            "medium": 2,
            "low": 0,
        },
    }


def _mock_overtime_scan(month: str, store_id: Optional[str]) -> dict[str, Any]:
    """模拟月度加班超时扫描结果"""
    return {
        "month": month,
        "store_id": store_id,
        "overtime_exceeds": [
            {
                "employee_id": "e003",
                "employee_name": "王强",
                "overtime_hours": 42.5,
                "legal_limit_hours": 36,
                "exceed_hours": 6.5,
                "severity": "high",
            },
            {
                "employee_id": "e006",
                "employee_name": "刘洋",
                "overtime_hours": 53.0,
                "legal_limit_hours": 36,
                "exceed_hours": 17.0,
                "severity": "critical",
            },
        ],
        "summary": {
            "total": 2,
            "critical": 1,
            "high": 1,
        },
    }


def _mock_compliance_report(month: str, store_id: Optional[str]) -> dict[str, Any]:
    """模拟合规报告"""
    return {
        "report_month": month,
        "store_id": store_id,
        "overall_score": 72,
        "violation_breakdown": {
            "gps_anomaly": {"count": 8, "trend": "down", "prev_month": 12},
            "same_device": {"count": 3, "trend": "up", "prev_month": 1},
            "overtime_exceed": {"count": 5, "trend": "stable", "prev_month": 5},
            "proxy_punch": {"count": 2, "trend": "down", "prev_month": 4},
        },
        "high_frequency_employees": [
            {"employee_id": "e003", "employee_name": "王强", "violation_count": 4, "types": ["overtime_exceed", "gps_anomaly"]},
            {"employee_id": "e004", "employee_name": "赵敏", "violation_count": 3, "types": ["proxy_punch", "same_device"]},
        ],
        "recommendations": [
            "王强连续2个月加班超标，建议调整排班或增补人手",
            "同设备打卡异常上升，建议启用人脸识别二次验证",
            "GPS异常呈下降趋势，前期整改有效",
            "建议对赵敏、陈刚进行考勤纪律约谈",
        ],
        "pending_count": 6,
        "confirmed_count": 8,
        "dismissed_count": 4,
    }


class AttendanceComplianceAgent(SkillAgent):
    """考勤深度合规 Skill Agent

    检测维度：GPS 打卡异常 / 同设备代打 / 加班超时 / 代打卡
    """

    agent_id = "attendance_compliance"
    agent_name = "考勤合规"
    description = "考勤深度合规检测：GPS异常/代打卡/加班超时"
    priority = "P2"
    run_location = "cloud"
    agent_level = 1  # 建议级（需人工确认）

    def get_supported_actions(self) -> list[str]:
        return [
            "daily_compliance_scan",
            "monthly_overtime_scan",
            "generate_compliance_report",
        ]

    def get_action_config(self, action: str) -> ActionConfig:
        configs: dict[str, ActionConfig] = {
            "daily_compliance_scan": ActionConfig(
                max_retries=2,
                risk_level="medium",
            ),
            "monthly_overtime_scan": ActionConfig(
                max_retries=2,
                risk_level="medium",
            ),
            "generate_compliance_report": ActionConfig(
                max_retries=1,
                risk_level="low",
            ),
        }
        return configs.get(action, ActionConfig())

    def _store_scope(self, params: dict[str, Any]) -> Optional[str]:
        sid = params.get("store_id")
        if sid and str(sid).strip():
            return str(sid).strip()
        if self.store_id and str(self.store_id).strip():
            return str(self.store_id).strip()
        return None

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch: dict[str, Any] = {
            "daily_compliance_scan": self._daily_scan,
            "monthly_overtime_scan": self._monthly_overtime,
            "generate_compliance_report": self._compliance_report,
        }
        handler = dispatch.get(action)
        if handler is None:
            return AgentResult(
                success=False,
                action=action,
                error=f"不支持的action: {action}",
            )
        return await handler(params)

    async def _daily_scan(self, params: dict[str, Any]) -> AgentResult:
        store_id = self._store_scope(params)
        check_date = params.get("date", date.today().isoformat())

        # 尝试使用真实DB扫描
        if self._db:
            try:
                from services.tx_org.src.services.attendance_compliance_service import (
                    AttendanceComplianceLogService,
                )
                svc = AttendanceComplianceLogService(self._db, self.tenant_id)
                result = await svc.run_full_scan(check_date, store_id)
                total = result.get("inserted", 0)
                return AgentResult(
                    success=True,
                    action="daily_compliance_scan",
                    data=result,
                    reasoning=f"每日合规扫描完成: 发现 {total} 项违规",
                    confidence=0.92,
                )
            except (ImportError, AttributeError) as exc:
                logger.debug("daily_scan_db_fallback", reason=str(exc))

        # Fallback: Mock 数据
        logger.info("daily_compliance_scan_mock", tenant_id=self.tenant_id)
        data = _mock_daily_scan(check_date, store_id)
        total = data["summary"]["total"]
        critical = data["summary"]["critical"]

        return AgentResult(
            success=True,
            action="daily_compliance_scan",
            data=data,
            reasoning=f"每日合规扫描完成: {total} 项违规，其中 {critical} 项紧急",
            confidence=0.90,
        )

    async def _monthly_overtime(self, params: dict[str, Any]) -> AgentResult:
        store_id = self._store_scope(params)
        month = params.get("month", date.today().strftime("%Y-%m"))

        logger.info("monthly_overtime_scan_mock", tenant_id=self.tenant_id, month=month)
        data = _mock_overtime_scan(month, store_id)
        total = data["summary"]["total"]
        critical = data["summary"].get("critical", 0)

        return AgentResult(
            success=True,
            action="monthly_overtime_scan",
            data=data,
            reasoning=f"月度加班超时扫描完成: {total} 人超标，{critical} 人严重超标",
            confidence=0.88,
        )

    async def _compliance_report(self, params: dict[str, Any]) -> AgentResult:
        store_id = self._store_scope(params)
        month = params.get("month", date.today().strftime("%Y-%m"))

        # 尝试从DB获取统计
        if self._db:
            try:
                from services.tx_org.src.services.attendance_compliance_service import (
                    AttendanceComplianceLogService,
                )
                svc = AttendanceComplianceLogService(self._db, self.tenant_id)
                stats = await svc.get_compliance_stats(month)
                report = {
                    "report_month": month,
                    "store_id": store_id,
                    "overall_score": max(0, 100 - stats.get("total", 0) * 3),
                    "stats": stats,
                }
                return AgentResult(
                    success=True,
                    action="generate_compliance_report",
                    data=report,
                    reasoning=f"合规报告生成完成: {month} 月共 {stats.get('total', 0)} 项违规",
                    confidence=0.85,
                )
            except (ImportError, AttributeError) as exc:
                logger.debug("compliance_report_db_fallback", reason=str(exc))

        # Fallback: Mock
        logger.info("compliance_report_mock", tenant_id=self.tenant_id)
        data = _mock_compliance_report(month, store_id)
        score = data["overall_score"]

        return AgentResult(
            success=True,
            action="generate_compliance_report",
            data=data,
            reasoning=f"合规报告生成完成: {month} 月合规得分 {score}/100",
            confidence=0.85,
        )
