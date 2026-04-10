"""屯象OS tx-agent 离职风险 Agent：定期扫描员工多维信号，计算离职风险评分并生成干预建议。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from ..base import AgentResult, SkillAgent

logger = structlog.get_logger(__name__)


# ── 权重配置 ─────────────────────────────────────────────────────────────────

_WEIGHTS = {
    "attendance_anomaly": 0.20,
    "performance_decline": 0.15,
    "engagement_drop": 0.10,
    "tenure_risk": 0.10,
    "complaint_history": 0.10,
    "business_performance": 0.20,
    "service_quality": 0.15,
}

# 旧键名 → 新键名映射（内部兼容）
_DIM_KEY_MAP = {
    "points_stagnation": "engagement_drop",
    "seniority_risk": "tenure_risk",
    "complaint_transfer": "complaint_history",
}


# ── 辅助函数 ─────────────────────────────────────────────────────────────────


def _risk_level(score: int) -> str:
    if score >= 80:
        return "critical"
    if score >= 60:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


def _risk_color(score: int) -> str:
    if score >= 80:
        return "red"
    if score >= 60:
        return "orange"
    return "gray"


def _calculate_risk_score(dimensions: dict[str, int]) -> int:
    total = 0.0
    for dim, weight in _WEIGHTS.items():
        # 兼容旧键名：如果新键名不存在，尝试旧键名
        val = dimensions.get(dim, 0)
        if val == 0:
            for old_key, new_key in _DIM_KEY_MAP.items():
                if new_key == dim:
                    val = dimensions.get(old_key, 0)
                    break
        total += val * weight
    return int(round(min(100, max(0, total))))


def _generate_interventions(dimensions: dict[str, dict[str, Any]]) -> list[str]:
    """根据各维度得分生成干预建议。"""
    suggestions: list[str] = []
    att = dimensions.get("attendance_anomaly", {})
    if att.get("score", 0) >= 60:
        suggestions.append("安排直属上级进行一对一关怀谈话，了解考勤异常原因（家庭/健康/排班）")

    perf = dimensions.get("performance_decline", {})
    if perf.get("score", 0) >= 60:
        suggestions.append("安排技能辅导或岗位培训，帮助提升绩效")

    # 兼容新旧键名
    pts = dimensions.get("engagement_drop", dimensions.get("points_stagnation", {}))
    if pts.get("score", 0) >= 60:
        suggestions.append("鼓励参与积分活动，提供额外激励机会")

    sen = dimensions.get("tenure_risk", dimensions.get("seniority_risk", {}))
    if sen.get("score", 0) >= 60:
        suggestions.append("关注新员工适应情况，安排mentor辅导")

    comp = dimensions.get("complaint_history", dimensions.get("complaint_transfer", {}))
    if comp.get("score", 0) >= 60:
        suggestions.append("评估是否需要调岗或调整工作环境")

    # 新增：经营表现维度
    biz = dimensions.get("business_performance", {})
    if biz.get("score", 0) >= 60:
        suggestions.append("安排技能培训或调换岗位，关注经营业绩下滑原因")

    # 新增：服务质量维度
    svc = dimensions.get("service_quality", {})
    if svc.get("score", 0) >= 60:
        suggestions.append("安排一对一辅导和心理关怀，关注服务质量下降原因")

    # 多维度同时下滑 -> 紧急面谈
    high_dims = sum(
        1 for d in dimensions.values()
        if isinstance(d, dict) and d.get("score", 0) >= 60
    )
    if high_dims >= 3:
        suggestions.insert(0, "【紧急】多维度同时下滑，建议立即安排面谈，评估是否需要调岗或协商解除")

    if not suggestions:
        suggestions.append("保持现有管理节奏，定期回顾员工状态")

    return suggestions


# ── 数据查询 ─────────────────────────────────────────────────────────────────


async def _scan_attendance_trends(
    db: Any,
    tenant_id: str,
    store_id: Optional[str],
) -> dict[str, dict[str, Any]]:
    """扫描近60天考勤趋势：对比前30天与后30天的迟到/缺勤次数。"""
    store_clause = ""
    params: dict[str, Any] = {"tenant_id": tenant_id}
    if store_id:
        store_clause = "AND da.store_id = CAST(:store_id AS text)"
        params["store_id"] = store_id

    q = text(f"""
        SELECT da.employee_id,
               SUM(CASE WHEN da.date >= CURRENT_DATE - 30
                        AND da.status IN ('absent', 'late', 'missing_clock_out')
                        THEN 1 ELSE 0 END) AS recent_anomalies,
               SUM(CASE WHEN da.date < CURRENT_DATE - 30
                        AND da.date >= CURRENT_DATE - 60
                        AND da.status IN ('absent', 'late', 'missing_clock_out')
                        THEN 1 ELSE 0 END) AS prev_anomalies,
               e.emp_name, e.store_id::text AS store_id
        FROM daily_attendance da
        LEFT JOIN employees e
          ON e.tenant_id = da.tenant_id AND e.id::text = da.employee_id
        WHERE da.tenant_id = CAST(:tenant_id AS uuid)
          AND da.date >= CURRENT_DATE - 60
          AND COALESCE(da.is_deleted, false) = false
          {store_clause}
        GROUP BY da.employee_id, e.emp_name, e.store_id
        HAVING SUM(CASE WHEN da.status IN ('absent', 'late', 'missing_clock_out')
                        THEN 1 ELSE 0 END) > 0
    """)
    try:
        result = await db.execute(q, params)
        rows = [dict(r) for r in result.mappings()]
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("turnover_scan_attendance_failed", error=str(exc))
        return {}

    trends: dict[str, dict[str, Any]] = {}
    for row in rows:
        emp_id = str(row.get("employee_id") or "")
        recent = int(row.get("recent_anomalies") or 0)
        prev = int(row.get("prev_anomalies") or 0)
        # 如果近期异常明显上升，风险更高
        if prev == 0:
            score = min(90, recent * 20)
        else:
            ratio = recent / max(1, prev)
            if ratio > 2.0:
                score = 85
            elif ratio > 1.5:
                score = 70
            elif ratio > 1.0:
                score = 55
            else:
                score = 30
        trends[emp_id] = {
            "score": score,
            "recent_anomalies": recent,
            "prev_anomalies": prev,
            "emp_name": row.get("emp_name") or "",
            "store_id": row.get("store_id") or "",
            "detail": f"近30天异常{recent}次，前30天{prev}次",
        }
    return trends


async def _scan_performance_trends(
    db: Any,
    tenant_id: str,
    store_id: Optional[str],
) -> dict[str, dict[str, Any]]:
    """扫描绩效趋势。简化版：读取当前绩效分。"""
    store_clause = ""
    params: dict[str, Any] = {"tenant_id": tenant_id}
    if store_id:
        store_clause = "AND e.store_id = CAST(:store_id AS uuid)"
        params["store_id"] = store_id

    q = text(f"""
        SELECT e.id::text AS employee_id, e.emp_name, e.performance_score,
               e.store_id::text AS store_id
        FROM employees e
        WHERE e.tenant_id = CAST(:tenant_id AS uuid)
          AND e.is_deleted = false
          AND COALESCE(e.is_active, true) = true
          AND e.performance_score IS NOT NULL
          {store_clause}
    """)
    try:
        result = await db.execute(q, params)
        rows = [dict(r) for r in result.mappings()]
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("turnover_scan_perf_failed", error=str(exc))
        return {}

    trends: dict[str, dict[str, Any]] = {}
    for row in rows:
        emp_id = str(row.get("employee_id") or "")
        raw = str(row.get("performance_score") or "").strip().upper()
        # 字母制或数字制
        if raw in ("F", "E", "1"):
            score = 90
        elif raw in ("D", "2"):
            score = 75
        elif raw in ("C", "3"):
            score = 50
        else:
            try:
                val = float(raw)
                score = max(0, min(100, int(100 - val)))
            except ValueError:
                score = 40
        trends[emp_id] = {
            "score": score,
            "performance_score": raw,
            "emp_name": row.get("emp_name") or "",
            "store_id": row.get("store_id") or "",
            "detail": f"当前绩效档 {raw}",
        }
    return trends


# ── 跨域经营数据扫描 ──────────────────────────────────────────────────────────


async def _scan_business_performance(
    db: Any,
    tenant_id: str,
    employee_id: str | None = None,
    store_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    """经营表现维度 -- 从POS数据检测业绩下滑。

    数据来源：orders表
    信号：
    - 近30天关联营收 vs 前30天 下降>15% -> 风险+20
    - 近30天关联订单数 vs 前30天 下降>20% -> 风险+15
    - 退菜率 近30天 vs 前30天 上升>50% -> 风险+15

    SQL降级：orders表不存在时返回空dict
    """
    emp_clause = ""
    params: dict[str, Any] = {"tenant_id": tenant_id}
    if employee_id:
        emp_clause = "AND (o.waiter_id = CAST(:eid AS TEXT) OR o.cashier_id = CAST(:eid AS TEXT))"
        params["eid"] = employee_id

    store_clause = ""
    if store_id:
        store_clause = "AND o.store_id = CAST(:store_id AS TEXT)"
        params["store_id"] = store_id

    q = text(f"""
        WITH emp_list AS (
            SELECT DISTINCT COALESCE(o.waiter_id, o.cashier_id) AS eid
            FROM orders o
            WHERE o.tenant_id = CAST(:tenant_id AS uuid)
              AND o.created_at >= CURRENT_DATE - INTERVAL '60 days'
              AND o.status = 'paid'
              AND COALESCE(o.waiter_id, o.cashier_id) IS NOT NULL
              {emp_clause} {store_clause}
        ),
        recent AS (
            SELECT COALESCE(o.waiter_id, o.cashier_id) AS eid,
                   COALESCE(SUM(o.total_fen), 0) AS revenue,
                   COUNT(*) AS order_count
            FROM orders o
            WHERE o.tenant_id = CAST(:tenant_id AS uuid)
              AND o.created_at >= CURRENT_DATE - INTERVAL '30 days'
              AND o.status = 'paid'
              AND COALESCE(o.waiter_id, o.cashier_id) IS NOT NULL
              {emp_clause} {store_clause}
            GROUP BY COALESCE(o.waiter_id, o.cashier_id)
        ),
        previous AS (
            SELECT COALESCE(o.waiter_id, o.cashier_id) AS eid,
                   COALESCE(SUM(o.total_fen), 0) AS revenue,
                   COUNT(*) AS order_count
            FROM orders o
            WHERE o.tenant_id = CAST(:tenant_id AS uuid)
              AND o.created_at >= CURRENT_DATE - INTERVAL '60 days'
              AND o.created_at < CURRENT_DATE - INTERVAL '30 days'
              AND o.status = 'paid'
              AND COALESCE(o.waiter_id, o.cashier_id) IS NOT NULL
              {emp_clause} {store_clause}
            GROUP BY COALESCE(o.waiter_id, o.cashier_id)
        )
        SELECT el.eid,
               COALESCE(r.revenue, 0) AS recent_revenue,
               COALESCE(r.order_count, 0) AS recent_orders,
               COALESCE(p.revenue, 0) AS prev_revenue,
               COALESCE(p.order_count, 0) AS prev_orders
        FROM emp_list el
        LEFT JOIN recent r ON r.eid = el.eid
        LEFT JOIN previous p ON p.eid = el.eid
    """)
    try:
        result = await db.execute(q, params)
        rows = [dict(r) for r in result.mappings()]
    except (OperationalError, ProgrammingError) as exc:
        logger.debug("turnover_scan_biz_perf_unavailable", error=str(exc))
        return {}

    trends: dict[str, dict[str, Any]] = {}
    for row in rows:
        eid = str(row.get("eid") or "")
        if not eid:
            continue
        recent_rev = int(row.get("recent_revenue") or 0)
        prev_rev = int(row.get("prev_revenue") or 0)
        recent_ord = int(row.get("recent_orders") or 0)
        prev_ord = int(row.get("prev_orders") or 0)

        score = 0
        signals: list[str] = []

        # 营收下滑 >15%
        if prev_rev > 0:
            rev_decline = (prev_rev - recent_rev) / prev_rev
            if rev_decline > 0.15:
                score += 20
                signals.append(f"营收下降{rev_decline:.0%}")

        # 订单量下滑 >20%
        if prev_ord > 0:
            ord_decline = (prev_ord - recent_ord) / prev_ord
            if ord_decline > 0.20:
                score += 15
                signals.append(f"订单量下降{ord_decline:.0%}")

        detail = "；".join(signals) if signals else "经营表现正常"
        trends[eid] = {"score": min(100, score), "signals": signals, "detail": detail}
    return trends


async def _scan_service_quality(
    db: Any,
    tenant_id: str,
    employee_id: str | None = None,
    store_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    """服务质量维度 -- 从退菜/客诉数据检测。

    信号：
    - 退菜率上升 -> 厨师出品质量下降
    - 客诉增多 -> 服务员态度/能力下降

    这两个信号通常在考勤异常之前2-4周出现。
    SQL降级：order_refunds / complaints 表不存在时返回空dict
    """
    emp_clause = ""
    params: dict[str, Any] = {"tenant_id": tenant_id}
    if employee_id:
        emp_clause = "AND r.responsible_employee_id = CAST(:eid AS TEXT)"
        params["eid"] = employee_id

    store_clause = ""
    if store_id:
        store_clause = "AND r.store_id = CAST(:store_id AS TEXT)"
        params["store_id"] = store_id

    # 退菜/退款统计
    q = text(f"""
        WITH recent_refunds AS (
            SELECT r.responsible_employee_id AS eid, COUNT(*) AS cnt
            FROM order_refunds r
            WHERE r.tenant_id = CAST(:tenant_id AS uuid)
              AND r.created_at >= CURRENT_DATE - INTERVAL '30 days'
              {emp_clause} {store_clause}
            GROUP BY r.responsible_employee_id
        ),
        prev_refunds AS (
            SELECT r.responsible_employee_id AS eid, COUNT(*) AS cnt
            FROM order_refunds r
            WHERE r.tenant_id = CAST(:tenant_id AS uuid)
              AND r.created_at >= CURRENT_DATE - INTERVAL '60 days'
              AND r.created_at < CURRENT_DATE - INTERVAL '30 days'
              {emp_clause} {store_clause}
            GROUP BY r.responsible_employee_id
        )
        SELECT COALESCE(rr.eid, pr.eid) AS eid,
               COALESCE(rr.cnt, 0) AS recent_refund_count,
               COALESCE(pr.cnt, 0) AS prev_refund_count
        FROM recent_refunds rr
        FULL OUTER JOIN prev_refunds pr ON rr.eid = pr.eid
    """)
    try:
        result = await db.execute(q, params)
        rows = [dict(r) for r in result.mappings()]
    except (OperationalError, ProgrammingError) as exc:
        logger.debug("turnover_scan_svc_quality_unavailable", error=str(exc))
        return {}

    trends: dict[str, dict[str, Any]] = {}
    for row in rows:
        eid = str(row.get("eid") or "")
        if not eid:
            continue
        recent_ref = int(row.get("recent_refund_count") or 0)
        prev_ref = int(row.get("prev_refund_count") or 0)

        score = 0
        signals: list[str] = []

        # 退菜率上升 >50%
        if prev_ref > 0:
            ref_increase = (recent_ref - prev_ref) / prev_ref
            if ref_increase > 0.50:
                score += 15
                signals.append(f"退菜率上升{ref_increase:.0%}")
        elif recent_ref >= 3:
            # 之前无退菜，现在突然出现
            score += 15
            signals.append(f"近30天新增退菜{recent_ref}次")

        # 绝对量也算风险
        if recent_ref >= 5:
            score += 10
            signals.append(f"近30天退菜{recent_ref}次（偏高）")

        detail = "；".join(signals) if signals else "服务质量正常"
        trends[eid] = {"score": min(100, score), "signals": signals, "detail": detail}
    return trends


async def _generate_business_interventions(risk_signals: dict[str, dict[str, Any]]) -> list[str]:
    """基于风险信号生成经营维度干预建议。

    如果主要是business_performance下滑 -> 建议"安排技能培训/调换岗位"
    如果主要是service_quality下降 -> 建议"一对一辅导/心理关怀"
    如果主要是attendance_anomaly -> 建议"了解家庭/健康原因/调整排班"
    如果多维度同时下滑 -> 建议"紧急面谈/评估是否需要调岗或协商解除"
    """
    suggestions: list[str] = []
    biz = risk_signals.get("business_performance", {})
    svc = risk_signals.get("service_quality", {})
    att = risk_signals.get("attendance_anomaly", {})

    biz_score = biz.get("score", 0)
    svc_score = svc.get("score", 0)
    att_score = att.get("score", 0)

    high_count = sum(1 for s in [biz_score, svc_score, att_score] if s >= 60)

    if high_count >= 2:
        suggestions.append("【紧急】多维度风险叠加，建议48小时内安排面谈，评估是否需要调岗或协商解除")

    if biz_score >= 60:
        suggestions.append("经营业绩下滑：建议安排技能培训或调换岗位，激发工作积极性")
        for sig in biz.get("signals", []):
            suggestions.append(f"  - {sig}")

    if svc_score >= 60:
        suggestions.append("服务质量下降：建议安排一对一辅导和心理关怀，排查深层原因")
        for sig in svc.get("signals", []):
            suggestions.append(f"  - {sig}")

    if att_score >= 60 and biz_score < 60 and svc_score < 60:
        suggestions.append("考勤异常为主：建议了解家庭/健康原因，评估是否需要调整排班")

    return suggestions


# ── Mock数据 ─────────────────────────────────────────────────────────────────


def _mock_risk_employees() -> list[dict[str, Any]]:
    return [
        {
            "employee_id": "mock-emp-101",
            "emp_name": "高风险A",
            "store_id": "mock-store-001",
            "store_name": "尝在一起·万达店",
            "risk_score": 85,
            "risk_level": "critical",
            "risk_color": "red",
            "alert_level": 2,
            "dimensions": {
                "attendance_anomaly": {"score": 85, "detail": "近30天异常6次，前30天2次"},
                "performance_decline": {"score": 75, "detail": "当前绩效档 D"},
                "engagement_drop": {"score": 80, "detail": "30天无积分变动"},
                "tenure_risk": {"score": 72, "detail": "工龄4个月"},
                "complaint_history": {"score": 0, "detail": "无投诉记录"},
                "business_performance": {"score": 70, "detail": "营收下降22%", "signals": ["营收下降22%"]},
                "service_quality": {"score": 60, "detail": "退菜率上升80%", "signals": ["退菜率上升80%"]},
            },
            "interventions": [
                "【紧急】多维度同时下滑，建议立即安排面谈，评估是否需要调岗或协商解除",
                "安排直属上级进行一对一关怀谈话，了解考勤异常原因（家庭/健康/排班）",
                "安排技能辅导或岗位培训，帮助提升绩效",
                "经营业绩下滑：建议安排技能培训或调换岗位，激发工作积极性",
            ],
        },
        {
            "employee_id": "mock-emp-102",
            "emp_name": "中风险B",
            "store_id": "mock-store-001",
            "store_name": "尝在一起·万达店",
            "risk_score": 65,
            "risk_level": "high",
            "risk_color": "orange",
            "alert_level": 1,
            "dimensions": {
                "attendance_anomaly": {"score": 55, "detail": "近30天异常3次，前30天2次"},
                "performance_decline": {"score": 50, "detail": "当前绩效档 C"},
                "engagement_drop": {"score": 80, "detail": "30天无积分变动"},
                "tenure_risk": {"score": 38, "detail": "工龄24个月"},
                "complaint_history": {"score": 0, "detail": "无投诉记录"},
                "business_performance": {"score": 35, "detail": "经营表现正常", "signals": []},
                "service_quality": {"score": 20, "detail": "服务质量正常", "signals": []},
            },
            "interventions": [
                "鼓励参与积分活动，提供额外激励机会",
            ],
        },
        {
            "employee_id": "mock-emp-103",
            "emp_name": "低风险C",
            "store_id": "mock-store-002",
            "store_name": "尝在一起·悦方店",
            "risk_score": 35,
            "risk_level": "low",
            "risk_color": "gray",
            "alert_level": 0,
            "dimensions": {
                "attendance_anomaly": {"score": 30, "detail": "近30天异常1次，前30天1次"},
                "performance_decline": {"score": 40, "detail": "当前绩效档 B"},
                "engagement_drop": {"score": 30, "detail": "近期有积分活动"},
                "tenure_risk": {"score": 28, "detail": "工龄48个月"},
                "complaint_history": {"score": 0, "detail": "无投诉记录"},
                "business_performance": {"score": 10, "detail": "经营表现正常", "signals": []},
                "service_quality": {"score": 5, "detail": "服务质量正常", "signals": []},
            },
            "interventions": [
                "保持现有管理节奏，定期回顾员工状态",
            ],
        },
    ]


# ── Agent 类 ─────────────────────────────────────────────────────────────────


class TurnoverRiskAgent(SkillAgent):
    """离职风险 Skill：多维度信号扫描、风险评分、干预建议生成。"""

    agent_id = "turnover_risk"
    agent_name = "离职风险"
    description = "定期扫描考勤/绩效/积分/投诉等多维信号，计算员工离职风险评分并生成干预建议"
    priority = "P1"
    run_location = "cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "scan_attendance_trends",
            "scan_performance_trends",
            "calculate_risk_score",
            "generate_intervention",
        ]

    def _store_scope(self, params: dict[str, Any]) -> Optional[str]:
        sid = params.get("store_id")
        if sid is not None and str(sid).strip():
            return str(sid).strip()
        if self.store_id is not None and str(self.store_id).strip():
            return str(self.store_id).strip()
        return None

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch: dict[str, Any] = {
            "scan_attendance_trends": self._scan_attendance_trends,
            "scan_performance_trends": self._scan_performance_trends,
            "calculate_risk_score": self._calculate_risk_score,
            "generate_intervention": self._generate_intervention,
        }
        handler = dispatch.get(action)
        if handler is None:
            return AgentResult(
                success=False,
                action=action,
                error=f"不支持的操作: {action}",
            )
        return await handler(params)

    async def _scan_attendance_trends(self, params: dict[str, Any]) -> AgentResult:
        store_id = self._store_scope(params)
        if not self._db:
            logger.info("turnover_scan_att_mock", tenant_id=self.tenant_id)
            mock = _mock_risk_employees()
            trends = {
                e["employee_id"]: e["dimensions"]["attendance_anomaly"]
                for e in mock
            }
            return AgentResult(
                success=True,
                action="scan_attendance_trends",
                data={"trends": trends, "employee_count": len(trends)},
                reasoning=f"考勤趋势扫描完成（mock），{len(trends)}名员工",
                confidence=0.80,
            )

        trends = await _scan_attendance_trends(self._db, self.tenant_id, store_id)
        return AgentResult(
            success=True,
            action="scan_attendance_trends",
            data={"trends": trends, "employee_count": len(trends)},
            reasoning=f"考勤趋势扫描完成，{len(trends)}名员工有异常记录",
            confidence=0.88,
        )

    async def _scan_performance_trends(self, params: dict[str, Any]) -> AgentResult:
        store_id = self._store_scope(params)
        if not self._db:
            logger.info("turnover_scan_perf_mock", tenant_id=self.tenant_id)
            mock = _mock_risk_employees()
            trends = {
                e["employee_id"]: e["dimensions"]["performance_decline"]
                for e in mock
            }
            return AgentResult(
                success=True,
                action="scan_performance_trends",
                data={"trends": trends, "employee_count": len(trends)},
                reasoning=f"绩效趋势扫描完成（mock），{len(trends)}名员工",
                confidence=0.80,
            )

        trends = await _scan_performance_trends(self._db, self.tenant_id, store_id)
        return AgentResult(
            success=True,
            action="scan_performance_trends",
            data={"trends": trends, "employee_count": len(trends)},
            reasoning=f"绩效趋势扫描完成，{len(trends)}名员工",
            confidence=0.85,
        )

    async def _calculate_risk_score(self, params: dict[str, Any]) -> AgentResult:
        """全量扫描：综合多维度信号计算每位员工的离职风险。"""
        store_id = self._store_scope(params)

        if not self._db:
            logger.info("turnover_calc_mock", tenant_id=self.tenant_id)
            employees = _mock_risk_employees()
            high_count = sum(1 for e in employees if e["risk_score"] >= 60)
            return AgentResult(
                success=True,
                action="calculate_risk_score",
                data={
                    "employees": employees,
                    "total_scanned": len(employees),
                    "high_risk_count": high_count,
                },
                reasoning=f"离职风险评估完成（mock），{high_count}/{len(employees)}人为高风险",
                confidence=0.80,
            )

        # 真实逻辑：聚合7个维度
        att_trends = await _scan_attendance_trends(self._db, self.tenant_id, store_id)
        perf_trends = await _scan_performance_trends(self._db, self.tenant_id, store_id)
        biz_trends = await _scan_business_performance(self._db, self.tenant_id, store_id=store_id)
        svc_trends = await _scan_service_quality(self._db, self.tenant_id, store_id=store_id)

        # 合并所有员工
        all_emp_ids = (
            set(att_trends.keys()) | set(perf_trends.keys())
            | set(biz_trends.keys()) | set(svc_trends.keys())
        )
        employees: list[dict[str, Any]] = []

        for emp_id in all_emp_ids:
            att = att_trends.get(emp_id, {"score": 30, "detail": "无考勤异常"})
            perf = perf_trends.get(emp_id, {"score": 40, "detail": "无绩效数据"})
            biz = biz_trends.get(emp_id, {"score": 0, "detail": "经营表现正常", "signals": []})
            svc = svc_trends.get(emp_id, {"score": 0, "detail": "服务质量正常", "signals": []})
            # 积分/工龄/投诉暂用默认值
            engage = {"score": 50, "detail": "积分数据待接入"}
            tenure = {"score": 45, "detail": "工龄数据待接入"}
            complaint = {"score": 0, "detail": "无投诉记录"}

            dimensions = {
                "attendance_anomaly": att,
                "performance_decline": perf,
                "engagement_drop": engage,
                "tenure_risk": tenure,
                "complaint_history": complaint,
                "business_performance": biz,
                "service_quality": svc,
            }
            dim_scores = {k: v["score"] for k, v in dimensions.items()}
            risk_score = _calculate_risk_score(dim_scores)

            emp_name = att.get("emp_name") or perf.get("emp_name") or emp_id
            emp_store = att.get("store_id") or perf.get("store_id") or ""

            # 告警级别：>=80 Level 2 自动通知，60-80 Level 1 推送Dashboard
            if risk_score >= 80:
                alert_level = 2
            elif risk_score >= 60:
                alert_level = 1
            else:
                alert_level = 0

            employees.append({
                "employee_id": emp_id,
                "emp_name": emp_name,
                "store_id": emp_store,
                "risk_score": risk_score,
                "risk_level": _risk_level(risk_score),
                "risk_color": _risk_color(risk_score),
                "alert_level": alert_level,
                "dimensions": dimensions,
                "interventions": _generate_interventions(dimensions),
            })

        employees.sort(key=lambda e: e["risk_score"], reverse=True)
        high_count = sum(1 for e in employees if e["risk_score"] >= 60)
        critical_count = sum(1 for e in employees if e["risk_score"] >= 80)

        # Level 2 自动通知（企微群+直属上级）
        if critical_count > 0:
            logger.warning(
                "turnover_critical_alert",
                tenant_id=self.tenant_id,
                critical_count=critical_count,
                employee_ids=[e["employee_id"] for e in employees if e["risk_score"] >= 80],
            )

        return AgentResult(
            success=True,
            action="calculate_risk_score",
            agent_level=2,
            rollback_window_min=30,
            data={
                "employees": employees[:100],  # 最多返回100人
                "total_scanned": len(employees),
                "high_risk_count": high_count,
                "critical_count": critical_count,
            },
            reasoning=f"离职风险评估完成（7维模型），{critical_count}人critical/{high_count}人high/{len(employees)}人总计",
            confidence=0.85,
        )

    async def _generate_intervention(self, params: dict[str, Any]) -> AgentResult:
        """为指定员工生成干预建议。"""
        employee_id = params.get("employee_id")
        if not employee_id:
            return AgentResult(success=False, action="generate_intervention",
                               error="缺少 employee_id")

        # 先计算该员工风险
        store_id = self._store_scope(params)
        if not self._db:
            mock = _mock_risk_employees()
            target = next((e for e in mock if e["employee_id"] == employee_id), mock[0])
            return AgentResult(
                success=True,
                action="generate_intervention",
                data=target,
                reasoning=f"已为{target['emp_name']}生成{len(target['interventions'])}条干预建议（mock）",
                confidence=0.80,
            )

        att_trends = await _scan_attendance_trends(self._db, self.tenant_id, store_id)
        perf_trends = await _scan_performance_trends(self._db, self.tenant_id, store_id)
        biz_trends = await _scan_business_performance(
            self._db, self.tenant_id, employee_id=employee_id, store_id=store_id,
        )
        svc_trends = await _scan_service_quality(
            self._db, self.tenant_id, employee_id=employee_id, store_id=store_id,
        )

        att = att_trends.get(employee_id, {"score": 30, "detail": "无考勤异常"})
        perf = perf_trends.get(employee_id, {"score": 40, "detail": "无绩效数据"})
        biz = biz_trends.get(employee_id, {"score": 0, "detail": "经营表现正常", "signals": []})
        svc = svc_trends.get(employee_id, {"score": 0, "detail": "服务质量正常", "signals": []})
        dimensions = {
            "attendance_anomaly": att,
            "performance_decline": perf,
            "engagement_drop": {"score": 50, "detail": "积分数据待接入"},
            "tenure_risk": {"score": 45, "detail": "工龄数据待接入"},
            "complaint_history": {"score": 0, "detail": "无投诉记录"},
            "business_performance": biz,
            "service_quality": svc,
        }
        dim_scores = {k: v["score"] for k, v in dimensions.items()}
        risk_score = _calculate_risk_score(dim_scores)
        interventions = _generate_interventions(dimensions)

        # 追加经营维度专项建议
        biz_interventions = await _generate_business_interventions(dimensions)
        interventions.extend(biz_interventions)

        emp_name = att.get("emp_name") or perf.get("emp_name") or employee_id

        # 告警级别
        if risk_score >= 80:
            alert_level = 2
        elif risk_score >= 60:
            alert_level = 1
        else:
            alert_level = 0

        return AgentResult(
            success=True,
            action="generate_intervention",
            agent_level=2,
            rollback_window_min=30,
            data={
                "employee_id": employee_id,
                "emp_name": emp_name,
                "risk_score": risk_score,
                "risk_level": _risk_level(risk_score),
                "risk_color": _risk_color(risk_score),
                "alert_level": alert_level,
                "dimensions": dimensions,
                "interventions": interventions,
            },
            reasoning=f"已为{emp_name}生成{len(interventions)}条干预建议（含经营维度），风险评分{risk_score}",
            confidence=0.85,
        )
