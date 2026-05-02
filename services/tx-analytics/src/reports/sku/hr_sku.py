"""人效域固定报表SKU — 20个模板

覆盖：人效/出勤/工时/排班/薪资/绩效
"""

from __future__ import annotations
from typing import Any

_TF = "tenant_id = :tenant_id AND is_deleted = FALSE"

HR_SKUS: list[dict[str, Any]] = []


def _reg(sku_id: str, name: str, desc: str, cols: list[dict], sql: str,
         params: dict | None = None, domain: str = "hr") -> dict:
    return {
        "sku_id": f"{domain}_{sku_id}", "name": name, "description": desc,
        "domain": domain, "columns": cols, "sql": sql.strip(),
        "default_params": params or {},
    }


# ── 人效日报 (5) ──────────────────────────────────────────────────────
HR_SKUS += [
    _reg("efficiency_daily", "人效日报", "人均产出/人均服务桌数/人均销售额",
         [{"name":"store_name","label":"门店"},{"name":"staff_count","label":"在岗人数"},
          {"name":"total_revenue_fen","label":"销售额(分)"},{"name":"revenue_per_head","label":"人均产出(分)"},
          {"name":"tables_per_head","label":"人均桌数"}],
         """SELECT s.name AS store_name, COUNT(DISTINCT a.employee_id) AS staff_count,
            COALESCE(SUM(o.total_fen),0) AS total_revenue_fen,
            CASE WHEN COUNT(DISTINCT a.employee_id)>0 THEN COALESCE(SUM(o.total_fen),0)/COUNT(DISTINCT a.employee_id) ELSE 0 END AS revenue_per_head,
            CASE WHEN COUNT(DISTINCT a.employee_id)>0 THEN COUNT(*)*1.0/COUNT(DISTINCT a.employee_id) ELSE 0 END AS tables_per_head
            FROM attendances a JOIN orders o ON a.store_id=o.store_id AND o.created_at>=:date_start AND o.created_at<:date_end
            JOIN stores s ON a.store_id=s.id AND s.is_deleted=FALSE
            WHERE a.tenant_id=:tenant_id AND a.is_deleted=FALSE AND a.status='present'
            AND a.check_in>=:date_start AND a.check_in<:date_end
            GROUP BY s.id, s.name ORDER BY revenue_per_head DESC""",
         {"date_start":"today()","date_end":"tomorrow()"}),
]

# ── 出勤统计 (5) ──────────────────────────────────────────────────────
HR_SKUS += [
    _reg("attendance_summary", "出勤统计", "应到/实到/迟到/早退/缺勤",
         [{"name":"store_name","label":"门店"},{"name":"expected","label":"应到"},
          {"name":"actual","label":"实到"},{"name":"late","label":"迟到"},
          {"name":"early_leave","label":"早退"},{"name":"absent","label":"缺勤"},
          {"name":"attendance_rate","label":"出勤率","format":"0.0%"}],
         """SELECT s.name AS store_name,
            COUNT(DISTINCT sch.employee_id) AS expected,
            COUNT(DISTINCT a.employee_id) FILTER (WHERE a.status='present') AS actual,
            COUNT(DISTINCT a.employee_id) FILTER (WHERE a.is_late) AS late,
            COUNT(DISTINCT a.employee_id) FILTER (WHERE a.is_early_leave) AS early_leave,
            COUNT(DISTINCT sch.employee_id)-COUNT(DISTINCT a.employee_id) FILTER (WHERE a.status='present') AS absent,
            CASE WHEN COUNT(DISTINCT sch.employee_id)>0 THEN COUNT(DISTINCT a.employee_id) FILTER (WHERE a.status='present')*100.0/COUNT(DISTINCT sch.employee_id) ELSE 0 END AS attendance_rate
            FROM schedules sch LEFT JOIN attendances a ON sch.employee_id=a.employee_id AND a.check_in>=:date_start AND a.check_in<:date_end
            JOIN stores s ON sch.store_id=s.id AND s.is_deleted=FALSE
            WHERE sch.tenant_id=:tenant_id AND sch.is_deleted=FALSE AND sch.schedule_date>=:date_start AND sch.schedule_date<:date_end
            GROUP BY s.id, s.name ORDER BY attendance_rate ASC""",
         {"date_start":"today()","date_end":"tomorrow()"}),
    _reg("overtime_summary", "加班统计", "各岗位加班时长/加班费",
         [{"name":"role","label":"岗位"},{"name":"overtime_hours","label":"加班时长(h)"},
          {"name":"overtime_pay_fen","label":"加班费(分)"},{"name":"employee_count","label":"人数"}],
         """SELECT COALESCE(e.role,'其他') AS role,
            COALESCE(SUM(a.overtime_hours),0) AS overtime_hours,
            COALESCE(SUM(a.overtime_pay_fen),0) AS overtime_pay_fen,
            COUNT(DISTINCT a.employee_id) AS employee_count
            FROM attendances a JOIN employees e ON a.employee_id=e.id AND e.is_deleted=FALSE
            WHERE a.tenant_id=:tenant_id AND a.is_deleted=FALSE AND a.overtime_hours>0
            AND a.check_in>=:date_start AND a.check_in<:date_end
            GROUP BY e.role ORDER BY overtime_hours DESC""",
         {"date_start":"month_start()","date_end":"tomorrow()"}),
]

# ── 排班分析 (4) ──────────────────────────────────────────────────────
HR_SKUS += [
    _reg("schedule_execution", "排班执行率", "各门店排班vs实际出勤对比",
         [{"name":"store_name","label":"门店"},{"name":"scheduled_hours","label":"排班工时(h)"},
          {"name":"actual_hours","label":"实际工时(h)"},{"name":"execution_rate","label":"执行率","format":"0.0%"}],
         """SELECT s.name AS store_name,
            COALESCE(SUM(sch.scheduled_hours),0) AS scheduled_hours,
            COALESCE(SUM(a.worked_hours),0) AS actual_hours,
            CASE WHEN COALESCE(SUM(sch.scheduled_hours),0)>0 THEN COALESCE(SUM(a.worked_hours),0)*100.0/COALESCE(SUM(sch.scheduled_hours),0) ELSE 0 END AS execution_rate
            FROM schedules sch LEFT JOIN attendances a ON sch.employee_id=a.employee_id AND a.check_in>=:date_start AND a.check_in<:date_end
            JOIN stores s ON sch.store_id=s.id AND s.is_deleted=FALSE
            WHERE sch.tenant_id=:tenant_id AND sch.is_deleted=FALSE AND sch.schedule_date>=:date_start AND sch.schedule_date<:date_end
            GROUP BY s.id, s.name ORDER BY execution_rate DESC""",
         {"date_start":"today()","date_end":"tomorrow()"}),
    _reg("peak_staffing", "高峰期人力配置", "午市/晚市高峰期在岗人数vs需求",
         [{"name":"store_name","label":"门店"},{"name":"daypart","label":"时段"},
          {"name":"actual_staff","label":"实际人数"},{"name":"required_staff","label":"需求人数"},
          {"name":"gap","label":"缺口"}],
         """SELECT s.name AS store_name,
            CASE WHEN EXTRACT(HOUR FROM a.check_in)<14 THEN '午市' ELSE '晚市' END AS daypart,
            COUNT(DISTINCT a.employee_id) AS actual_staff,
            COALESCE(s.peak_staff_required,0) AS required_staff,
            COALESCE(s.peak_staff_required,0)-COUNT(DISTINCT a.employee_id) AS gap
            FROM attendances a JOIN stores s ON a.store_id=s.id AND s.is_deleted=FALSE
            WHERE a.tenant_id=:tenant_id AND a.is_deleted=FALSE AND a.status='present'
            AND a.check_in>=:date_start AND a.check_in<:date_end
            GROUP BY s.id, s.name, daypart, s.peak_staff_required HAVING COALESCE(s.peak_staff_required,0)>COUNT(DISTINCT a.employee_id)
            ORDER BY gap DESC""",
         {"date_start":"today()","date_end":"tomorrow()"}),
]

# ── 薪资汇总 (3) ──────────────────────────────────────────────────────
HR_SKUS += [
    _reg("payroll_summary", "薪资汇总", "各岗位薪资总额/人均/福利",
         [{"name":"role","label":"岗位"},{"name":"employee_count","label":"人数"},
          {"name":"total_salary_fen","label":"薪资总额(分)"},{"name":"avg_salary_fen","label":"人均薪资(分)"},
          {"name":"bonus_fen","label":"奖金(分)"}],
         """SELECT COALESCE(e.role,'其他') AS role, COUNT(DISTINCT e.id) AS employee_count,
            COALESCE(SUM(pr.salary_fen),0) AS total_salary_fen,
            CASE WHEN COUNT(DISTINCT e.id)>0 THEN COALESCE(SUM(pr.salary_fen),0)/COUNT(DISTINCT e.id) ELSE 0 END AS avg_salary_fen,
            COALESCE(SUM(pr.bonus_fen),0) AS bonus_fen
            FROM employees e JOIN payroll_records pr ON e.id=pr.employee_id AND pr.pay_period>=:period_start AND pr.pay_period<:period_end
            WHERE e.tenant_id=:tenant_id AND e.is_deleted=FALSE
            GROUP BY e.role ORDER BY total_salary_fen DESC""",
         {"period_start":"month_start()","period_end":"tomorrow()"}),
]

# ── 绩效排名 (3) ──────────────────────────────────────────────────────
HR_SKUS += [
    _reg("performance_ranking", "员工绩效排名", "各门店员工绩效得分排名",
         [{"name":"store_name","label":"门店"},{"name":"employee_name","label":"员工"},
          {"name":"role","label":"岗位"},{"name":"score","label":"绩效分"},
          {"name":"revenue_contribution_fen","label":"销售贡献(分)"}],
         """SELECT s.name AS store_name, e.name AS employee_name, COALESCE(e.role,'-') AS role,
            COALESCE(perf.score,0) AS score, COALESCE(SUM(o.total_fen),0) AS revenue_contribution_fen
            FROM employees e JOIN performance_reviews perf ON e.id=perf.employee_id AND perf.review_period>=:period_start
            LEFT JOIN orders o ON e.id=o.employee_id AND o.created_at>=:period_start AND o.created_at<:period_end
            JOIN stores s ON e.store_id=s.id AND s.is_deleted=FALSE
            WHERE e.tenant_id=:tenant_id AND e.is_deleted=FALSE AND e.is_active=TRUE
            GROUP BY s.name, e.id, e.name, e.role, perf.score ORDER BY score DESC LIMIT 50""",
         {"period_start":"month_start()","period_end":"tomorrow()"}),
]
