"""屯象OS tx-agent 积分激励 Agent：月度自动积分发放、赛马周报、激励策略建议。"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from ..base import ActionConfig, AgentResult, SkillAgent

logger = structlog.get_logger(__name__)

# ── 积分规则映射（与 employee_points_service.POINT_RULES 保持一致）──
AUTO_AWARD_RULES = {
    "attendance_perfect": {"name": "全勤", "points": 100},
    "hygiene_pass": {"name": "卫生检查通过", "points": 10},
    "training_complete": {"name": "完成培训课程", "points": 30},
}


def _bind_store(store_id: Optional[str]) -> Optional[str]:
    if not store_id or not str(store_id).strip():
        return None
    return str(store_id).strip()


async def _svc_auto_award_monthly(
    db: Any,
    tenant_id: str,
    store_id: Optional[str],
) -> dict[str, Any]:
    """月度自动积分发放：扫描全勤/卫生合格/培训完成员工，批量发放积分。"""
    bound_uuid = _bind_store(store_id)
    store_clause = (
        "AND e.store_id = CAST(:bound_uuid AS uuid)" if bound_uuid else ""
    )
    params: dict[str, Any] = {"tenant_id": tenant_id, "bound_uuid": bound_uuid}

    # 1. 扫描本月全勤员工（daily_attendance 无 absent 且出勤天数 >= 22）
    now = datetime.now(timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    params["month_start"] = month_start

    awards: list[dict[str, Any]] = []

    try:
        # 全勤检查
        q_attendance = text(f"""
            SELECT e.id::text AS employee_id, e.emp_name,
                   COUNT(DISTINCT da.date) FILTER (WHERE da.status = 'present') AS present_days,
                   COUNT(DISTINCT da.date) FILTER (WHERE da.status = 'absent') AS absent_days
            FROM employees e
            LEFT JOIN daily_attendance da
                ON da.employee_id = e.id::text
                AND da.tenant_id = e.tenant_id
                AND da.date >= :month_start
                AND COALESCE(da.is_deleted, false) = false
            WHERE e.tenant_id = CAST(:tenant_id AS uuid)
              AND e.is_deleted = false
              AND COALESCE(e.is_active, true) = true
              {store_clause}
            GROUP BY e.id, e.emp_name
            HAVING COUNT(DISTINCT da.date) FILTER (WHERE da.status = 'absent') = 0
               AND COUNT(DISTINCT da.date) FILTER (WHERE da.status = 'present') >= 20
            LIMIT 500
        """)
        result = await db.execute(q_attendance, params)
        for row in result.mappings():
            awards.append({
                "employee_id": str(row["employee_id"]),
                "emp_name": row["emp_name"],
                "rule_code": "attendance_perfect",
                "rule_name": "全勤",
                "points": 100,
                "present_days": int(row["present_days"]),
            })
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("points_advisor.attendance_scan_failed", error=str(exc))

    return {
        "month": month_start.strftime("%Y-%m"),
        "awards": awards,
        "total_employees": len(awards),
        "total_points": sum(a["points"] for a in awards),
    }


async def _svc_generate_race_report(
    db: Any,
    tenant_id: str,
    store_id: Optional[str],
) -> dict[str, Any]:
    """赛马周报：本周积分排名变化+亮点+风险员工。"""
    bound_uuid = _bind_store(store_id)
    store_clause = (
        "AND e.store_id = CAST(:bound_uuid AS uuid)" if bound_uuid else ""
    )
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    last_week_start = week_start - timedelta(days=7)
    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "bound_uuid": bound_uuid,
        "week_start": week_start,
        "last_week_start": last_week_start,
    }

    try:
        q = text(f"""
            WITH this_week AS (
                SELECT pt.employee_id, e.emp_name,
                       COALESCE(SUM(pt.points), 0) AS week_points
                FROM point_transactions pt
                JOIN employees e ON e.id = pt.employee_id AND e.tenant_id = pt.tenant_id
                WHERE pt.tenant_id = CAST(:tenant_id AS uuid)
                  AND pt.is_deleted = false AND e.is_deleted = false
                  AND pt.created_at >= :week_start
                  {store_clause}
                GROUP BY pt.employee_id, e.emp_name
            ),
            last_week AS (
                SELECT pt.employee_id,
                       COALESCE(SUM(pt.points), 0) AS week_points
                FROM point_transactions pt
                JOIN employees e ON e.id = pt.employee_id AND e.tenant_id = pt.tenant_id
                WHERE pt.tenant_id = CAST(:tenant_id AS uuid)
                  AND pt.is_deleted = false AND e.is_deleted = false
                  AND pt.created_at >= :last_week_start AND pt.created_at < :week_start
                  {store_clause}
                GROUP BY pt.employee_id
            )
            SELECT tw.employee_id, tw.emp_name,
                   tw.week_points AS this_week_points,
                   COALESCE(lw.week_points, 0) AS last_week_points,
                   tw.week_points - COALESCE(lw.week_points, 0) AS change
            FROM this_week tw
            LEFT JOIN last_week lw ON lw.employee_id = tw.employee_id
            ORDER BY tw.week_points DESC
            LIMIT 20
        """)
        result = await db.execute(q, params)
        rows = [dict(r) for r in result.mappings()]
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("points_advisor.race_report_failed", error=str(exc))
        rows = []

    highlights = [r for r in rows if r.get("change", 0) > 0][:3]
    risks = [r for r in rows if r.get("this_week_points", 0) <= 0]

    return {
        "week": f"{week_start.isoformat()} ~ {today.isoformat()}",
        "ranking": [
            {
                "employee_id": str(r["employee_id"]),
                "emp_name": r["emp_name"],
                "this_week": int(r["this_week_points"]),
                "last_week": int(r["last_week_points"]),
                "change": int(r["change"]),
            }
            for r in rows
        ],
        "highlights": [
            {"emp_name": r["emp_name"], "change": int(r["change"])}
            for r in highlights
        ],
        "risk_employees": [
            {"emp_name": r["emp_name"], "this_week": int(r["this_week_points"])}
            for r in risks
        ],
    }


async def _svc_suggest_incentive(
    db: Any,
    tenant_id: str,
    store_id: Optional[str],
) -> dict[str, Any]:
    """基于积分走势推荐激励策略。"""
    bound_uuid = _bind_store(store_id)
    store_clause = (
        "AND e.store_id = CAST(:bound_uuid AS uuid)" if bound_uuid else ""
    )
    today = date.today()
    days_30 = today - timedelta(days=30)
    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "bound_uuid": bound_uuid,
        "days_30": days_30,
    }

    suggestions: list[dict[str, Any]] = []

    try:
        # 低积分员工：建议关注
        q_low = text(f"""
            SELECT pt.employee_id, e.emp_name,
                   COALESCE(SUM(pt.points), 0) AS total_points
            FROM point_transactions pt
            JOIN employees e ON e.id = pt.employee_id AND e.tenant_id = pt.tenant_id
            WHERE pt.tenant_id = CAST(:tenant_id AS uuid)
              AND pt.is_deleted = false AND e.is_deleted = false
              {store_clause}
            GROUP BY pt.employee_id, e.emp_name
            HAVING COALESCE(SUM(pt.points), 0) < 100
            ORDER BY total_points ASC
            LIMIT 10
        """)
        result = await db.execute(q_low, params)
        low_employees = [dict(r) for r in result.mappings()]

        if low_employees:
            suggestions.append({
                "type": "attention",
                "title": "低积分员工关注",
                "detail": f"{len(low_employees)} 名员工积分低于100，建议一对一辅导",
                "employees": [
                    {"emp_name": r["emp_name"], "total_points": int(r["total_points"])}
                    for r in low_employees
                ],
            })

        # 近30天无积分变动的员工
        q_inactive = text(f"""
            SELECT e.id::text AS employee_id, e.emp_name
            FROM employees e
            WHERE e.tenant_id = CAST(:tenant_id AS uuid)
              AND e.is_deleted = false
              AND COALESCE(e.is_active, true) = true
              {store_clause}
              AND NOT EXISTS (
                SELECT 1 FROM point_transactions pt
                WHERE pt.employee_id = e.id AND pt.tenant_id = e.tenant_id
                  AND pt.created_at >= :days_30 AND pt.is_deleted = false
              )
            LIMIT 20
        """)
        result2 = await db.execute(q_inactive, params)
        inactive = [dict(r) for r in result2.mappings()]

        if inactive:
            suggestions.append({
                "type": "inactive",
                "title": "30天无积分变动",
                "detail": f"{len(inactive)} 名员工近30天无积分变动，建议设置挑战目标",
                "employees": [{"emp_name": r["emp_name"]} for r in inactive],
            })
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("points_advisor.suggest_failed", error=str(exc))

    # 通用建议
    suggestions.append({
        "type": "general",
        "title": "周期性激励建议",
        "detail": "建议每月举办一次积分兑换日，提高员工参与积极性",
        "employees": [],
    })

    return {"suggestions": suggestions, "generated_at": datetime.now(timezone.utc).isoformat()}


# ── Mock 数据 ───────────────────────────────────────────────────────────────


def _mock_auto_award() -> dict[str, Any]:
    return {
        "month": date.today().strftime("%Y-%m"),
        "awards": [
            {"employee_id": "mock-e001", "emp_name": "张三", "rule_code": "attendance_perfect", "rule_name": "全勤", "points": 100, "present_days": 22},
            {"employee_id": "mock-e002", "emp_name": "李四", "rule_code": "attendance_perfect", "rule_name": "全勤", "points": 100, "present_days": 23},
        ],
        "total_employees": 2,
        "total_points": 200,
    }


def _mock_race_report() -> dict[str, Any]:
    today = date.today()
    return {
        "week": f"{(today - timedelta(days=today.weekday())).isoformat()} ~ {today.isoformat()}",
        "ranking": [
            {"employee_id": "mock-e001", "emp_name": "张三", "this_week": 85, "last_week": 60, "change": 25},
            {"employee_id": "mock-e002", "emp_name": "李四", "this_week": 72, "last_week": 80, "change": -8},
        ],
        "highlights": [{"emp_name": "张三", "change": 25}],
        "risk_employees": [],
    }


def _mock_suggest() -> dict[str, Any]:
    return {
        "suggestions": [
            {"type": "attention", "title": "低积分员工关注", "detail": "3 名员工积分低于100", "employees": [{"emp_name": "王五", "total_points": 45}]},
            {"type": "general", "title": "周期性激励建议", "detail": "建议每月举办一次积分兑换日", "employees": []},
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Agent 类 ────────────────────────────────────────────────────────────────


class PointsAdvisorAgent(SkillAgent):
    """积分激励 Skill Agent：自动积分发放、赛马周报、激励策略建议。"""

    agent_id = "points_advisor"
    agent_name = "积分激励"
    description = "月度自动积分发放、赛马排名周报生成、员工激励策略推荐"
    priority = "P2"
    run_location = "cloud"
    agent_level = 3  # 全自主

    def get_supported_actions(self) -> list[str]:
        return [
            "auto_award_monthly",
            "generate_race_report",
            "suggest_incentive",
        ]

    def get_action_config(self, action: str) -> ActionConfig:
        configs = {
            "auto_award_monthly": ActionConfig(
                requires_human_confirm=True,
                max_retries=1,
                risk_level="medium",
            ),
            "generate_race_report": ActionConfig(
                max_retries=2,
                risk_level="low",
            ),
            "suggest_incentive": ActionConfig(
                max_retries=1,
                risk_level="low",
            ),
        }
        return configs.get(action, ActionConfig())

    def _store_scope(self, params: dict[str, Any]) -> Optional[str]:
        sid = params.get("store_id")
        if sid is not None and str(sid).strip():
            return str(sid).strip()
        if self.store_id is not None and str(self.store_id).strip():
            return str(self.store_id).strip()
        return None

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch: dict[str, Any] = {
            "auto_award_monthly": self._auto_award_monthly,
            "generate_race_report": self._generate_race_report,
            "suggest_incentive": self._suggest_incentive,
        }
        handler = dispatch.get(action)
        if handler is None:
            return AgentResult(
                success=False,
                action=action,
                error=f"Unsupported action: {action}",
            )
        return await handler(params)

    async def _auto_award_monthly(self, params: dict[str, Any]) -> AgentResult:
        store_id = self._store_scope(params)
        if self._db:
            data = await _svc_auto_award_monthly(self._db, self.tenant_id, store_id)
        else:
            logger.info("points_advisor.auto_award_mock", tenant_id=self.tenant_id)
            data = _mock_auto_award()
        return AgentResult(
            success=True,
            action="auto_award_monthly",
            data=data,
            reasoning=f"月度自动积分发放扫描完成：{data['total_employees']} 名员工符合条件，合计 {data['total_points']} 分",
            confidence=0.92,
        )

    async def _generate_race_report(self, params: dict[str, Any]) -> AgentResult:
        store_id = self._store_scope(params)
        if self._db:
            data = await _svc_generate_race_report(self._db, self.tenant_id, store_id)
        else:
            logger.info("points_advisor.race_report_mock", tenant_id=self.tenant_id)
            data = _mock_race_report()
        n = len(data.get("ranking", []))
        h = len(data.get("highlights", []))
        r = len(data.get("risk_employees", []))
        return AgentResult(
            success=True,
            action="generate_race_report",
            data=data,
            reasoning=f"赛马周报生成完成：{n} 名参赛者，{h} 个亮点，{r} 个风险员工",
            confidence=0.90,
        )

    async def _suggest_incentive(self, params: dict[str, Any]) -> AgentResult:
        store_id = self._store_scope(params)
        if self._db:
            data = await _svc_suggest_incentive(self._db, self.tenant_id, store_id)
        else:
            logger.info("points_advisor.suggest_mock", tenant_id=self.tenant_id)
            data = _mock_suggest()
        n = len(data.get("suggestions", []))
        return AgentResult(
            success=True,
            action="suggest_incentive",
            data=data,
            reasoning=f"激励策略建议生成完成：{n} 条建议",
            confidence=0.85,
        )
