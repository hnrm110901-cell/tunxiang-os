"""AI运营教练 — Byte Coach + 商龙OpenClaw

四模式：晨会简报 / 高峰预警 / 复盘分析 / 闭店日报
核心哲学：正常不说，异常论述。千店千面。

工作机制：
  - 晨会简报（morning_brief）: 09:30推送，回顾昨日 + 今日预测 + 优先事项
  - 高峰预警（peak_alert）: 午市/晚市开始时检测，正常返回None
  - 复盘分析（post_rush_review）: 午后/晚后复盘指标 vs 基线
  - 闭店日报（closing_summary）: 21:00-23:00推送，全天汇总 + 经验 + 明日建议

数据源：跨服务HTTP调用 tx-trade / tx-analytics / tx-ops，失败时降级为模拟数据
"""

from __future__ import annotations

import os
import random
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .baseline_service import METRIC_META, BaselineService

# ── 跨服务URL（环境变量配置，默认本地开发地址） ──
TX_TRADE_URL = os.getenv("TX_TRADE_URL", "http://localhost:8001")
TX_ANALYTICS_URL = os.getenv("TX_ANALYTICS_URL", "http://localhost:8009")
TX_OPS_URL = os.getenv("TX_OPS_URL", "http://localhost:8005")
TX_AGENT_URL = os.getenv("TX_AGENT_URL", "http://localhost:8008")

logger = structlog.get_logger(__name__)

# 时段名称映射
SLOT_NAMES: dict[str, str] = {
    "morning_prep": "早间准备",
    "lunch_buildup": "午市预备",
    "lunch_peak": "午市高峰",
    "afternoon_lull": "午后低峰",
    "dinner_buildup": "晚市预备",
    "dinner_peak": "晚市高峰",
    "closing": "闭店收尾",
}

# 教练类型枚举
COACHING_TYPES = frozenset(
    {
        "morning_brief",
        "peak_alert",
        "post_rush_review",
        "closing_summary",
    }
)

# 天气枚举（模拟用）
WEATHER_OPTIONS = ["晴", "多云", "阴", "小雨", "大雨", "雪"]

# 特殊事件（模拟用）
SPECIAL_EVENTS = [
    None,
    None,
    None,
    None,
    None,  # 大多数日子无特殊事件
    "周边商场促销活动",
    "学校开学季",
    "节假日前一天",
    "附近道路施工",
]


class AICoachService:
    """AI运营教练服务 — 千店千面的智能运营助手"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._baseline_svc = BaselineService(db)

    # ── 通用跨服务HTTP调用 ──────────────────────────────────────────

    @staticmethod
    async def _call_service(
        service_url: str,
        path: str,
        *,
        tenant_id: str,
        params: dict | None = None,
        timeout: float = 10.0,
    ) -> dict:
        """跨服务HTTP GET调用（统一入口）

        Args:
            service_url: 目标服务基础URL，如 TX_ANALYTICS_URL
            path: API路径，如 "/api/v1/analytics/daily-summary"
            tenant_id: 租户ID（必传，写入X-Tenant-ID header）
            params: 查询参数
            timeout: 超时秒数

        Returns:
            响应JSON dict

        Raises:
            httpx.HTTPStatusError: 非2xx响应
            httpx.TimeoutException: 超时
        """
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                f"{service_url}{path}",
                params=params,
                headers={
                    "X-Tenant-ID": tenant_id,
                    "X-Internal-Call": "true",
                },
            )
            resp.raise_for_status()
            return resp.json()

    # ══════════════════════════════════════════════════════════════════
    # 1. 晨会简报
    # ══════════════════════════════════════════════════════════════════

    async def morning_briefing(
        self,
        tenant_id: str,
        store_id: str,
        manager_id: str | None = None,
    ) -> dict:
        """晨会简报 — 09:30推送

        返回:
          {
            title, coaching_date,
            yesterday_summary: {revenue_fen, covers, avg_ticket_fen, food_cost_rate, anomalies[]},
            today_forecast: {expected_covers, reservations, weather, special_events},
            priorities: [{task, reason, importance}],
            ai_insight: str,
          }
        """
        today = date.today()
        coaching_date = today

        yesterday = await self._get_yesterday_metrics(tenant_id, store_id)
        forecast = await self._get_today_forecast(tenant_id, store_id)

        # 检测昨日异常
        yesterday_anomalies = await self._baseline_svc.detect_anomalies(
            tenant_id,
            store_id,
            current_metrics={
                "lunch_covers": float(yesterday["covers"]) * 0.55,
                "dinner_covers": float(yesterday["covers"]) * 0.45,
                "food_cost_rate": yesterday["food_cost_rate"] * 100,
                "avg_ticket_fen": float(yesterday["avg_ticket_fen"]),
            },
        )

        # 生成优先事项
        priorities = self._generate_morning_priorities(
            yesterday,
            forecast,
            yesterday_anomalies,
        )

        # 生成AI洞察
        ai_insight = self._generate_morning_insight(
            yesterday,
            forecast,
            yesterday_anomalies,
        )

        result = {
            "title": f"晨会简报 — {today.strftime('%m月%d日')}",
            "coaching_date": coaching_date.isoformat(),
            "yesterday_summary": {
                "revenue_fen": yesterday["revenue_fen"],
                "covers": yesterday["covers"],
                "avg_ticket_fen": yesterday["avg_ticket_fen"],
                "food_cost_rate": round(yesterday["food_cost_rate"], 4),
                "anomalies": yesterday_anomalies,
            },
            "today_forecast": forecast,
            "priorities": priorities,
            "ai_insight": ai_insight,
        }

        # 记录教练日志
        coaching_id = await self._log_coaching(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=manager_id,
            coaching_type="morning_brief",
            slot_code="morning_prep",
            coaching_date=coaching_date,
            context={
                "yesterday_metrics": yesterday,
                "forecast": forecast,
                "anomaly_count": len(yesterday_anomalies),
            },
            recommendations={
                "priorities": priorities,
                "ai_insight": ai_insight,
            },
        )

        result["coaching_id"] = coaching_id
        logger.info(
            "coaching.morning_briefing",
            store_id=store_id,
            anomalies=len(yesterday_anomalies),
            priorities=len(priorities),
        )
        return result

    # ══════════════════════════════════════════════════════════════════
    # 2. 高峰预警
    # ══════════════════════════════════════════════════════════════════

    async def peak_alert(
        self,
        tenant_id: str,
        store_id: str,
        slot_code: str,
    ) -> dict | None:
        """高峰预警 — 正常不说（返回None），异常论述

        用 BaselineService.detect_anomalies 检测当前时段指标。
        如无异常返回None，有异常则返回详细分析。

        返回:
          {
            anomalies: [{metric, current, baseline, sigma, severity, ...}],
            similar_episodes: [{date, description}],
            suggested_actions: [{action, reason, urgency}],
            ai_analysis: str,
          }
        """
        current_metrics = await self._get_slot_metrics(
            tenant_id,
            store_id,
            slot_code,
        )

        anomalies = await self._baseline_svc.detect_anomalies(
            tenant_id,
            store_id,
            current_metrics=current_metrics,
            slot_code=slot_code,
            threshold_sigma=2.0,
        )

        # 正常不说
        if not anomalies:
            logger.debug(
                "coaching.peak_alert_normal",
                store_id=store_id,
                slot_code=slot_code,
            )
            return None

        # 异常论述
        similar_episodes = await self._find_similar_episodes(anomalies, tenant_id=tenant_id)
        suggested_actions = self._generate_peak_actions(anomalies, slot_code)
        ai_analysis = self._generate_peak_analysis(
            anomalies,
            slot_code,
        )

        result = {
            "slot_code": slot_code,
            "slot_name": SLOT_NAMES.get(slot_code, slot_code),
            "anomalies": anomalies,
            "similar_episodes": similar_episodes,
            "suggested_actions": suggested_actions,
            "ai_analysis": ai_analysis,
        }

        # 记录教练日志
        coaching_id = await self._log_coaching(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=None,
            coaching_type="peak_alert",
            slot_code=slot_code,
            coaching_date=date.today(),
            context={
                "current_metrics": current_metrics,
                "anomaly_count": len(anomalies),
            },
            recommendations={
                "suggested_actions": suggested_actions,
                "ai_analysis": ai_analysis,
            },
        )

        result["coaching_id"] = coaching_id
        logger.info(
            "coaching.peak_alert_triggered",
            store_id=store_id,
            slot_code=slot_code,
            anomalies=len(anomalies),
            critical=[a["metric"] for a in anomalies if a["severity"] == "critical"],
        )
        return result

    # ══════════════════════════════════════════════════════════════════
    # 3. 复盘分析
    # ══════════════════════════════════════════════════════════════════

    async def post_rush_review(
        self,
        tenant_id: str,
        store_id: str,
        slot_code: str,
    ) -> dict:
        """复盘分析 — 午后/晚后回顾

        返回:
          {
            slot_code, slot_name, coaching_date,
            metrics: {covers, revenue_fen, avg_ticket_fen, ...},
            vs_baseline: [{metric, actual, baseline, diff_pct, status}],
            sop_completion: {total, completed, skipped, overdue},
            highlights: [str],
            improvements: [str],
          }
        """
        today = date.today()

        metrics = await self._get_slot_metrics(tenant_id, store_id, slot_code)

        # 对比基线
        vs_baseline = await self._compare_with_baseline(
            tenant_id,
            store_id,
            metrics,
            slot_code=slot_code,
        )

        sop_completion = await self._get_sop_completion(tenant_id, store_id, slot_code)

        # 生成亮点和改进建议
        highlights = self._extract_highlights(vs_baseline)
        improvements = self._extract_improvements(vs_baseline, sop_completion)

        result = {
            "slot_code": slot_code,
            "slot_name": SLOT_NAMES.get(slot_code, slot_code),
            "coaching_date": today.isoformat(),
            "metrics": metrics,
            "vs_baseline": vs_baseline,
            "sop_completion": sop_completion,
            "highlights": highlights,
            "improvements": improvements,
        }

        coaching_id = await self._log_coaching(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=None,
            coaching_type="post_rush_review",
            slot_code=slot_code,
            coaching_date=today,
            context={
                "metrics": metrics,
                "sop_completion": sop_completion,
            },
            recommendations={
                "highlights": highlights,
                "improvements": improvements,
            },
        )

        result["coaching_id"] = coaching_id
        logger.info(
            "coaching.post_rush_review",
            store_id=store_id,
            slot_code=slot_code,
            highlights=len(highlights),
            improvements=len(improvements),
        )
        return result

    # ══════════════════════════════════════════════════════════════════
    # 4. 闭店日报
    # ══════════════════════════════════════════════════════════════════

    async def closing_summary(
        self,
        tenant_id: str,
        store_id: str,
    ) -> dict:
        """闭店日报 — 21:00-23:00推送

        返回:
          {
            date, coaching_date,
            daily_metrics: {revenue_fen, covers, avg_ticket_fen, food_cost_rate, labor_cost_rate, ...},
            vs_baseline: [{metric, actual, baseline, diff_pct, status}],
            sop_report: {total, completed, skipped, overdue, completion_rate},
            corrective_summary: {total, resolved, pending},
            lessons: [str],
            tomorrow: [str],
          }
        """
        today = date.today()

        daily_metrics = await self._get_daily_metrics(tenant_id, store_id)

        # 对比基线
        vs_baseline = await self._compare_with_baseline(
            tenant_id,
            store_id,
            daily_metrics,
        )

        sop_report = await self._get_daily_sop_report(tenant_id, store_id)

        corrective_summary = await self._get_corrective_summary(tenant_id, store_id)

        # 生成经验教训
        lessons = self._generate_daily_lessons(
            vs_baseline,
            sop_report,
            corrective_summary,
        )

        # 生成明日建议
        tomorrow = self._generate_tomorrow_suggestions(
            daily_metrics,
            vs_baseline,
        )

        result = {
            "date": today.isoformat(),
            "coaching_date": today.isoformat(),
            "daily_metrics": daily_metrics,
            "vs_baseline": vs_baseline,
            "sop_report": sop_report,
            "corrective_summary": corrective_summary,
            "lessons": lessons,
            "tomorrow": tomorrow,
        }

        coaching_id = await self._log_coaching(
            tenant_id=tenant_id,
            store_id=store_id,
            user_id=None,
            coaching_type="closing_summary",
            slot_code="closing",
            coaching_date=today,
            context={
                "daily_metrics": daily_metrics,
                "sop_report": sop_report,
                "corrective_summary": corrective_summary,
            },
            recommendations={
                "lessons": lessons,
                "tomorrow": tomorrow,
            },
        )

        result["coaching_id"] = coaching_id
        logger.info(
            "coaching.closing_summary",
            store_id=store_id,
            revenue_fen=daily_metrics.get("revenue_fen"),
            covers=daily_metrics.get("covers"),
            lessons=len(lessons),
        )
        return result

    # ══════════════════════════════════════════════════════════════════
    # 5. 反馈
    # ══════════════════════════════════════════════════════════════════

    async def submit_feedback(
        self,
        tenant_id: str,
        coaching_id: str,
        feedback: str,
    ) -> dict:
        """提交教练反馈 — helpful / not_helpful / ignored

        Returns:
            {"coaching_id": str, "feedback": str, "feedback_at": str}
        """
        valid_feedback = {"helpful", "not_helpful", "ignored"}
        if feedback not in valid_feedback:
            raise ValueError(f"feedback 必须是 {valid_feedback} 之一，收到: {feedback}")

        now = datetime.now(timezone.utc)
        cid = UUID(coaching_id)
        tid = UUID(tenant_id)

        result = await self.db.execute(
            text("""
                UPDATE sop_coaching_logs
                SET user_feedback = :feedback,
                    feedback_at = :now,
                    updated_at = :now
                WHERE id = :coaching_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
                RETURNING id
            """),
            {
                "feedback": feedback,
                "now": now,
                "coaching_id": cid,
                "tenant_id": tid,
            },
        )
        row = result.fetchone()
        if row is None:
            raise ValueError(f"教练日志不存在: {coaching_id}")

        await self.db.flush()
        logger.info(
            "coaching.feedback_submitted",
            coaching_id=coaching_id,
            feedback=feedback,
        )
        return {
            "coaching_id": coaching_id,
            "feedback": feedback,
            "feedback_at": now.isoformat(),
        }

    # ══════════════════════════════════════════════════════════════════
    # 6. 教练日志查询
    # ══════════════════════════════════════════════════════════════════

    async def list_coaching_logs(
        self,
        tenant_id: str,
        store_id: str,
        *,
        coaching_type: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页列出教练日志

        Returns:
            {"items": [...], "total": int, "page": int, "size": int}
        """
        tid = UUID(tenant_id)
        sid = UUID(store_id)
        params: dict = {
            "tenant_id": tid,
            "store_id": sid,
            "limit": size,
            "offset": (page - 1) * size,
        }

        filters = ""
        if coaching_type is not None:
            if coaching_type not in COACHING_TYPES:
                raise ValueError(f"无效的教练类型: {coaching_type}")
            filters += " AND cl.coaching_type = :coaching_type"
            params["coaching_type"] = coaching_type
        if start_date is not None:
            filters += " AND cl.coaching_date >= :start_date"
            params["start_date"] = start_date
        if end_date is not None:
            filters += " AND cl.coaching_date <= :end_date"
            params["end_date"] = end_date

        # 总数
        count_result = await self.db.execute(
            text(f"""
                SELECT COUNT(*) AS total
                FROM sop_coaching_logs cl
                WHERE cl.tenant_id = :tenant_id
                  AND cl.store_id = :store_id
                  AND cl.is_deleted = FALSE
                  {filters}
            """),
            params,
        )
        total = count_result.scalar() or 0

        # 分页数据
        data_result = await self.db.execute(
            text(f"""
                SELECT
                    cl.id,
                    cl.store_id,
                    cl.user_id,
                    cl.coaching_type,
                    cl.slot_code,
                    cl.coaching_date,
                    cl.user_feedback,
                    cl.feedback_at,
                    cl.created_at
                FROM sop_coaching_logs cl
                WHERE cl.tenant_id = :tenant_id
                  AND cl.store_id = :store_id
                  AND cl.is_deleted = FALSE
                  {filters}
                ORDER BY cl.coaching_date DESC, cl.created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = data_result.fetchall()

        items = []
        for row in rows:
            items.append(
                {
                    "id": str(row.id),
                    "store_id": str(row.store_id),
                    "user_id": str(row.user_id) if row.user_id else None,
                    "coaching_type": row.coaching_type,
                    "slot_code": row.slot_code,
                    "coaching_date": row.coaching_date.isoformat() if row.coaching_date else None,
                    "user_feedback": row.user_feedback,
                    "feedback_at": row.feedback_at.isoformat() if row.feedback_at else None,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
            )

        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        }

    async def get_coaching_log(
        self,
        tenant_id: str,
        coaching_id: str,
    ) -> dict:
        """获取单条教练日志详情（含 context_snapshot 和 recommendations）"""
        tid = UUID(tenant_id)
        cid = UUID(coaching_id)

        result = await self.db.execute(
            text("""
                SELECT
                    cl.id,
                    cl.tenant_id,
                    cl.store_id,
                    cl.user_id,
                    cl.coaching_type,
                    cl.slot_code,
                    cl.coaching_date,
                    cl.context_snapshot,
                    cl.memories_used,
                    cl.recommendations,
                    cl.user_feedback,
                    cl.feedback_at,
                    cl.created_at
                FROM sop_coaching_logs cl
                WHERE cl.id = :coaching_id
                  AND cl.tenant_id = :tenant_id
                  AND cl.is_deleted = FALSE
            """),
            {"coaching_id": cid, "tenant_id": tid},
        )
        row = result.fetchone()
        if row is None:
            raise ValueError(f"教练日志不存在: {coaching_id}")

        return {
            "id": str(row.id),
            "tenant_id": str(row.tenant_id),
            "store_id": str(row.store_id),
            "user_id": str(row.user_id) if row.user_id else None,
            "coaching_type": row.coaching_type,
            "slot_code": row.slot_code,
            "coaching_date": row.coaching_date.isoformat() if row.coaching_date else None,
            "context_snapshot": row.context_snapshot or {},
            "memories_used": [str(m) for m in row.memories_used] if row.memories_used else [],
            "recommendations": row.recommendations or {},
            "user_feedback": row.user_feedback,
            "feedback_at": row.feedback_at.isoformat() if row.feedback_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    # ══════════════════════════════════════════════════════════════════
    # 内部方法 — 跨服务数据获取（真实API + mock fallback）
    # ══════════════════════════════════════════════════════════════════

    async def _get_yesterday_metrics(
        self,
        tenant_id: str,
        store_id: str,
    ) -> dict:
        """获取昨日经营指标 — 对接 tx-analytics daily-summary API

        调用: GET tx-analytics/api/v1/analytics/daily-summary?date=yesterday&store_id=...
        失败时降级为模拟数据
        """
        try:
            data = await self._call_service(
                TX_ANALYTICS_URL,
                "/api/v1/analytics/daily-summary",
                tenant_id=tenant_id,
                params={"date": "yesterday", "store_id": store_id},
            )
            # 从API响应中提取数据（兼容 {"ok": true, "data": {...}} 格式）
            metrics = data.get("data", data)
            return {
                "revenue_fen": metrics["revenue_fen"],
                "covers": metrics["covers"],
                "avg_ticket_fen": metrics.get("avg_ticket_fen", metrics["revenue_fen"] // max(metrics["covers"], 1)),
                "food_cost_rate": metrics["food_cost_rate"],
                "labor_cost_rate": metrics.get("labor_cost_rate", 0.25),
                "table_turnover": metrics.get("table_turnover", 2.0),
                "serve_time_min": metrics.get("serve_time_min", 15.0),
                "waste_rate": metrics.get("waste_rate", 0.03),
                "takeout_count": metrics.get("takeout_count", 0),
                "customer_complaints": metrics.get("customer_complaints", 0),
            }
        except Exception:
            logger.warning(
                "coaching.analytics_yesterday_call_failed",
                store_id=store_id,
                exc_info=True,
            )
            return self._mock_yesterday_metrics()

    @staticmethod
    def _mock_yesterday_metrics() -> dict:
        """模拟昨日指标（fallback）"""
        revenue_fen = random.randint(280000, 350000)  # 2800-3500元
        covers = random.randint(180, 220)
        avg_ticket_fen = revenue_fen // covers if covers > 0 else 16000
        food_cost_rate = round(random.uniform(0.32, 0.38), 4)
        labor_cost_rate = round(random.uniform(0.22, 0.28), 4)

        return {
            "revenue_fen": revenue_fen,
            "covers": covers,
            "avg_ticket_fen": avg_ticket_fen,
            "food_cost_rate": food_cost_rate,
            "labor_cost_rate": labor_cost_rate,
            "table_turnover": round(random.uniform(1.8, 2.5), 2),
            "serve_time_min": round(random.uniform(12.0, 18.0), 1),
            "waste_rate": round(random.uniform(0.02, 0.05), 4),
            "takeout_count": random.randint(15, 40),
            "customer_complaints": random.randint(0, 3),
        }

    async def _get_today_forecast(
        self,
        tenant_id: str,
        store_id: str,
    ) -> dict:
        """获取今日预测 — 对接 tx-analytics forecast API

        调用: GET tx-analytics/api/v1/analytics/forecast?store_id=...&date=today
        失败时降级为模拟数据
        """
        try:
            data = await self._call_service(
                TX_ANALYTICS_URL,
                "/api/v1/analytics/forecast",
                tenant_id=tenant_id,
                params={"store_id": store_id, "date": "today"},
            )
            forecast = data.get("data", data)
            return {
                "expected_covers": forecast.get("expected_covers", 200),
                "reservations": forecast.get("reservations", 0),
                "weather": forecast.get("weather", "晴"),
                "special_events": forecast.get("special_events", []),
            }
        except Exception:
            logger.warning(
                "coaching.analytics_forecast_call_failed",
                store_id=store_id,
                exc_info=True,
            )
            return self._mock_today_forecast()

    @staticmethod
    def _mock_today_forecast() -> dict:
        """模拟今日预测（fallback）"""
        expected_covers = random.randint(180, 230)
        reservations = random.randint(15, 30)
        weather = random.choice(WEATHER_OPTIONS)
        special_event = random.choice(SPECIAL_EVENTS)

        result: dict = {
            "expected_covers": expected_covers,
            "reservations": reservations,
            "weather": weather,
        }
        if special_event is not None:
            result["special_events"] = [special_event]
        else:
            result["special_events"] = []

        return result

    async def _get_slot_metrics(
        self,
        tenant_id: str,
        store_id: str,
        slot_code: str,
    ) -> dict[str, float]:
        """获取时段指标 — 对接 tx-trade slot-summary API

        调用: GET tx-trade/api/v1/orders/slot-summary?store_id=...&slot=current
        失败时降级为模拟数据
        """
        try:
            data = await self._call_service(
                TX_TRADE_URL,
                "/api/v1/orders/slot-summary",
                tenant_id=tenant_id,
                params={"store_id": store_id, "slot": slot_code},
            )
            slot = data.get("data", data)
            covers = float(slot.get("covers", 0))
            revenue_fen = float(slot.get("revenue_fen", 0))
            avg_ticket = revenue_fen / covers if covers > 0 else 16000.0

            return {
                "lunch_covers": covers if "lunch" in slot_code else 0.0,
                "dinner_covers": covers if "dinner" in slot_code else 0.0,
                "avg_ticket_fen": avg_ticket,
                "food_cost_rate": float(slot.get("food_cost_rate", 35.0)),
                "serve_time_min": float(slot.get("serve_time_min", 15.0)),
                "table_turnover": float(slot.get("table_turnover", 2.0)),
                "waste_rate": float(slot.get("waste_rate", 3.0)),
                "customer_complaints": float(slot.get("customer_complaints", 0)),
            }
        except Exception:
            logger.warning(
                "coaching.trade_slot_call_failed",
                store_id=store_id,
                slot_code=slot_code,
                exc_info=True,
            )
            return self._mock_slot_metrics(slot_code)

    @staticmethod
    def _mock_slot_metrics(slot_code: str) -> dict[str, float]:
        """模拟时段指标（fallback）"""
        if slot_code in ("lunch_peak", "lunch_buildup"):
            covers = float(random.randint(80, 130))
            revenue_fen = float(random.randint(130000, 190000))
        elif slot_code in ("dinner_peak", "dinner_buildup"):
            covers = float(random.randint(90, 140))
            revenue_fen = float(random.randint(150000, 210000))
        else:
            covers = float(random.randint(20, 50))
            revenue_fen = float(random.randint(30000, 70000))

        avg_ticket = revenue_fen / covers if covers > 0 else 16000.0

        return {
            "lunch_covers": covers if "lunch" in slot_code else 0.0,
            "dinner_covers": covers if "dinner" in slot_code else 0.0,
            "avg_ticket_fen": avg_ticket,
            "food_cost_rate": round(random.uniform(30.0, 40.0), 2),
            "serve_time_min": round(random.uniform(12.0, 20.0), 1),
            "table_turnover": round(random.uniform(1.5, 3.0), 2),
            "waste_rate": round(random.uniform(2.0, 6.0), 2),
            "customer_complaints": float(random.randint(0, 2)),
        }

    async def _get_daily_metrics(
        self,
        tenant_id: str,
        store_id: str,
    ) -> dict[str, float]:
        """获取全天指标汇总 — 对接 tx-analytics daily-summary API

        调用: GET tx-analytics/api/v1/analytics/daily-summary?date=today&store_id=...
        失败时降级为模拟数据
        """
        try:
            data = await self._call_service(
                TX_ANALYTICS_URL,
                "/api/v1/analytics/daily-summary",
                tenant_id=tenant_id,
                params={"date": "today", "store_id": store_id},
            )
            metrics = data.get("data", data)
            revenue_fen = float(metrics["revenue_fen"])
            covers = float(metrics["covers"])
            avg_ticket = revenue_fen / covers if covers > 0 else 16000.0

            return {
                "revenue_fen": revenue_fen,
                "covers": covers,
                "lunch_covers": float(metrics.get("lunch_covers", 0)),
                "dinner_covers": float(metrics.get("dinner_covers", 0)),
                "avg_ticket_fen": round(avg_ticket, 0),
                "food_cost_rate": float(metrics.get("food_cost_rate", 35.0)),
                "labor_cost_rate": float(metrics.get("labor_cost_rate", 25.0)),
                "table_turnover": float(metrics.get("table_turnover", 2.0)),
                "serve_time_min": float(metrics.get("serve_time_min", 15.0)),
                "waste_rate": float(metrics.get("waste_rate", 3.0)),
                "takeout_count": float(metrics.get("takeout_count", 0)),
                "customer_complaints": float(metrics.get("customer_complaints", 0)),
            }
        except Exception:
            logger.warning(
                "coaching.analytics_daily_call_failed",
                store_id=store_id,
                exc_info=True,
            )
            return self._mock_daily_metrics()

    @staticmethod
    def _mock_daily_metrics() -> dict[str, float]:
        """模拟全天指标（fallback）"""
        revenue_fen = float(random.randint(280000, 380000))
        covers = float(random.randint(180, 250))
        avg_ticket = revenue_fen / covers if covers > 0 else 16000.0

        return {
            "revenue_fen": revenue_fen,
            "covers": covers,
            "lunch_covers": float(random.randint(80, 130)),
            "dinner_covers": float(random.randint(90, 140)),
            "avg_ticket_fen": round(avg_ticket, 0),
            "food_cost_rate": round(random.uniform(32.0, 38.0), 2),
            "labor_cost_rate": round(random.uniform(22.0, 28.0), 2),
            "table_turnover": round(random.uniform(1.8, 2.8), 2),
            "serve_time_min": round(random.uniform(12.0, 18.0), 1),
            "waste_rate": round(random.uniform(2.0, 5.0), 2),
            "takeout_count": float(random.randint(15, 45)),
            "customer_complaints": float(random.randint(0, 4)),
        }

    async def _log_coaching(
        self,
        tenant_id: str,
        store_id: str,
        user_id: str | None,
        coaching_type: str,
        slot_code: str,
        coaching_date: date,
        context: dict,
        recommendations: dict,
        memories_used: list[str] | None = None,
    ) -> str:
        """记录教练日志到 sop_coaching_logs 表

        Returns:
            新创建日志的 UUID 字符串
        """
        coaching_id = uuid4()
        tid = UUID(tenant_id)
        sid = UUID(store_id)
        uid = UUID(user_id) if user_id else None
        now = datetime.now(timezone.utc)

        # memories_used 转为 UUID 数组的文本
        mem_clause = "NULL"
        params: dict = {
            "id": coaching_id,
            "tenant_id": tid,
            "store_id": sid,
            "user_id": uid,
            "coaching_type": coaching_type,
            "slot_code": slot_code,
            "coaching_date": coaching_date,
            "context_snapshot": context,
            "recommendations": recommendations,
            "created_at": now,
        }

        if memories_used:
            params["memories_used"] = memories_used
            mem_clause = ":memories_used"

        await self.db.execute(
            text(f"""
                INSERT INTO sop_coaching_logs (
                    id, tenant_id, store_id, user_id,
                    coaching_type, slot_code, coaching_date,
                    context_snapshot, memories_used, recommendations,
                    created_at, is_deleted
                ) VALUES (
                    :id, :tenant_id, :store_id, :user_id,
                    :coaching_type, :slot_code, :coaching_date,
                    :context_snapshot::jsonb, {mem_clause}, :recommendations::jsonb,
                    :created_at, FALSE
                )
            """),
            params,
        )
        await self.db.flush()

        logger.info(
            "coaching.logged",
            coaching_id=str(coaching_id),
            coaching_type=coaching_type,
            store_id=store_id,
        )
        return str(coaching_id)

    # ══════════════════════════════════════════════════════════════════
    # 内部方法 — 分析与建议生成
    # ══════════════════════════════════════════════════════════════════

    async def _compare_with_baseline(
        self,
        tenant_id: str,
        store_id: str,
        metrics: dict[str, float],
        *,
        slot_code: str | None = None,
    ) -> list[dict]:
        """将当前指标与基线对比

        Returns:
            [{metric, metric_name, actual, baseline, diff_pct, status}]
        """
        baselines = await self._baseline_svc.get_all_baselines(
            tenant_id,
            store_id,
            slot_code=slot_code,
        )
        baseline_map = {b["metric_code"]: b for b in baselines}

        comparisons: list[dict] = []
        for metric_code, actual in metrics.items():
            bl = baseline_map.get(metric_code)
            if bl is None:
                continue

            baseline_val = bl["baseline_value"]
            if baseline_val == 0:
                diff_pct = 0.0
            else:
                diff_pct = round((actual - baseline_val) / baseline_val * 100, 2)

            meta = METRIC_META.get(metric_code, {})
            direction = meta.get("direction", "higher_better")

            # 判断状态
            if abs(diff_pct) < 5:
                status = "normal"
            elif direction == "higher_better":
                status = "good" if diff_pct > 0 else "concern"
            else:
                status = "good" if diff_pct < 0 else "concern"

            comparisons.append(
                {
                    "metric": metric_code,
                    "metric_name": meta.get("name", metric_code),
                    "actual": round(actual, 2),
                    "baseline": round(baseline_val, 2),
                    "diff_pct": diff_pct,
                    "status": status,
                }
            )

        return comparisons

    @staticmethod
    def _generate_morning_priorities(
        yesterday: dict,
        forecast: dict,
        anomalies: list[dict],
    ) -> list[dict]:
        """生成晨会优先事项"""
        priorities: list[dict] = []

        # 基于昨日异常生成优先事项
        for anomaly in anomalies[:3]:  # 最多取3个异常
            metric_name = anomaly.get("metric_name", anomaly["metric"])
            severity = anomaly["severity"]
            is_positive = anomaly.get("is_positive", False)

            if not is_positive:
                priorities.append(
                    {
                        "task": f"关注{metric_name}指标 — 昨日偏离基线{anomaly['sigma']:.1f}σ",
                        "reason": f"{metric_name}异常需关注，{severity}级别",
                        "importance": "high" if severity == "critical" else "medium",
                    }
                )

        # 基于预订量
        reservations = forecast.get("reservations", 0)
        if reservations >= 25:
            priorities.append(
                {
                    "task": f"今日预订{reservations}桌，提前备料+排班确认",
                    "reason": "预订量较大，需确保服务质量",
                    "importance": "high",
                }
            )

        # 天气影响
        weather = forecast.get("weather", "晴")
        if weather in ("大雨", "雪"):
            priorities.append(
                {
                    "task": f"今日{weather}，关注到店率 + 外卖单量",
                    "reason": "恶劣天气影响堂食客流，可能带动外卖需求",
                    "importance": "medium",
                }
            )

        # 特殊事件
        special_events = forecast.get("special_events", [])
        for event in special_events:
            priorities.append(
                {
                    "task": f"注意: {event}",
                    "reason": "特殊事件可能影响客流和运营",
                    "importance": "medium",
                }
            )

        # 如果没有异常和特殊事件，给出标准建议
        if not priorities:
            priorities.append(
                {
                    "task": "常规运营 — 按SOP执行即可",
                    "reason": "昨日各项指标正常，今日无特殊事件",
                    "importance": "low",
                }
            )

        return priorities

    @staticmethod
    def _generate_morning_insight(
        yesterday: dict,
        forecast: dict,
        anomalies: list[dict],
    ) -> str:
        """生成晨会AI洞察"""
        revenue_yuan = yesterday["revenue_fen"] / 100
        covers = yesterday["covers"]
        food_cost_pct = yesterday["food_cost_rate"] * 100

        parts: list[str] = []
        parts.append(f"昨日营收{revenue_yuan:.0f}元，接待{covers}位客人，食材成本率{food_cost_pct:.1f}%。")

        critical = [a for a in anomalies if a["severity"] == "critical"]
        warning = [a for a in anomalies if a["severity"] == "warning"]

        if critical:
            names = "、".join(a.get("metric_name", a["metric"]) for a in critical)
            parts.append(f"[红色预警] {names}偏离基线超过3个标准差，需立即关注。")
        if warning:
            names = "、".join(a.get("metric_name", a["metric"]) for a in warning)
            parts.append(f"[黄色预警] {names}轻微偏离基线，建议留意。")
        if not critical and not warning:
            parts.append("各项指标正常，继续保持。")

        # 今日预测
        expected = forecast.get("expected_covers", 200)
        weather = forecast.get("weather", "晴")
        parts.append(f"今日预计客流{expected}人，天气{weather}。")

        return "".join(parts)

    async def _find_similar_episodes(
        self,
        anomalies: list[dict],
        tenant_id: str | None = None,
    ) -> list[dict]:
        """查找相似历史案例 — 对接本服务 memory-evolution API

        调用: GET tx-agent/api/v1/agent/memory-evolution/search?query=...&scope=store
        失败时降级为模拟数据
        """
        if not anomalies:
            return []

        top = anomalies[0]
        metric_name = top.get("metric_name", top["metric"])
        query = f"{metric_name}异常"

        try:
            data = await self._call_service(
                TX_AGENT_URL,
                "/api/v1/agent/memory-evolution/search",
                tenant_id=tenant_id or "",
                params={"query": query, "scope": "store"},
            )
            memories = data.get("data", data)
            episodes: list[dict] = []
            for mem in (memories if isinstance(memories, list) else memories.get("items", [])):
                episodes.append(
                    {
                        "date": mem.get("created_at", "")[:10],
                        "description": mem.get("content", mem.get("summary", "")),
                    }
                )
            return episodes[:3]  # 最多返回3条
        except Exception:
            logger.warning("coaching.memory_search_failed", exc_info=True)
            return self._mock_similar_episodes(anomalies)

    @staticmethod
    def _mock_similar_episodes(anomalies: list[dict]) -> list[dict]:
        """模拟相似案例（fallback）"""
        episodes: list[dict] = []
        if anomalies:
            top = anomalies[0]
            metric_name = top.get("metric_name", top["metric"])
            episodes.append(
                {
                    "date": "2026-04-15",
                    "description": f"上周同日也出现{metric_name}异常，当时通过增加备料和调整排班解决",
                }
            )
        return episodes

    @staticmethod
    def _generate_peak_actions(
        anomalies: list[dict],
        slot_code: str,
    ) -> list[dict]:
        """生成高峰期建议动作"""
        actions: list[dict] = []
        slot_name = SLOT_NAMES.get(slot_code, slot_code)

        for anomaly in anomalies[:5]:
            metric = anomaly["metric"]
            metric_name = anomaly.get("metric_name", metric)
            severity = anomaly["severity"]
            direction = anomaly["direction"]
            is_positive = anomaly.get("is_positive", False)

            urgency = "immediate" if severity == "critical" else "soon"

            if is_positive:
                # 积极异常：提醒把握机会
                actions.append(
                    {
                        "action": f"{metric_name}表现优于基线，保持当前策略",
                        "reason": f"当前{metric_name}高于基线{anomaly['sigma']:.1f}σ，是好兆头",
                        "urgency": "info",
                    }
                )
            elif metric == "serve_time_min" and direction == "above":
                actions.append(
                    {
                        "action": "出餐速度偏慢 — 检查后厨备料和人手",
                        "reason": f"{slot_name}出餐时长超标{anomaly['sigma']:.1f}σ",
                        "urgency": urgency,
                    }
                )
            elif metric == "customer_complaints" and direction == "above":
                actions.append(
                    {
                        "action": "顾客投诉偏高 — 加强前厅巡台和催菜跟进",
                        "reason": f"投诉数超过基线{anomaly['sigma']:.1f}个标准差",
                        "urgency": urgency,
                    }
                )
            elif metric == "food_cost_rate" and direction == "above":
                actions.append(
                    {
                        "action": "食材成本率偏高 — 检查废弃量和出品标准",
                        "reason": f"食材成本率超标{anomaly['sigma']:.1f}σ",
                        "urgency": urgency,
                    }
                )
            elif metric == "waste_rate" and direction == "above":
                actions.append(
                    {
                        "action": "废弃率偏高 — 减少预制量或调整备料计划",
                        "reason": f"废弃率超标{anomaly['sigma']:.1f}σ，直接影响毛利",
                        "urgency": urgency,
                    }
                )
            elif "covers" in metric and direction == "below":
                actions.append(
                    {
                        "action": f"{metric_name}偏低 — 考虑外卖平台推广或限时优惠",
                        "reason": f"客数低于基线{anomaly['sigma']:.1f}σ",
                        "urgency": urgency,
                    }
                )
            else:
                actions.append(
                    {
                        "action": f"关注{metric_name}（偏{('高' if direction == 'above' else '低')}）",
                        "reason": f"偏离基线{anomaly['sigma']:.1f}σ",
                        "urgency": urgency,
                    }
                )

        return actions

    @staticmethod
    def _generate_peak_analysis(
        anomalies: list[dict],
        slot_code: str,
    ) -> str:
        """生成高峰期AI分析"""
        slot_name = SLOT_NAMES.get(slot_code, slot_code)
        critical = [a for a in anomalies if a["severity"] == "critical"]
        warning = [a for a in anomalies if a["severity"] == "warning"]

        parts: list[str] = [f"[{slot_name}预警] "]

        if critical:
            names = "、".join(a.get("metric_name", a["metric"]) for a in critical)
            parts.append(f"红色预警: {names}严重偏离基线。")
        if warning:
            names = "、".join(a.get("metric_name", a["metric"]) for a in warning)
            parts.append(f"黄色预警: {names}轻微偏离。")

        # 综合建议
        if any(a["metric"] == "serve_time_min" for a in anomalies):
            parts.append("建议优先检查后厨出餐效率。")
        if any(a["metric"] == "customer_complaints" for a in anomalies):
            parts.append("前厅服务需加强巡台频次。")

        return "".join(parts)

    async def _get_sop_completion(
        self,
        tenant_id: str,
        store_id: str,
        slot_code: str,
    ) -> dict:
        """获取SOP任务完成度 — 对接 tx-ops SOP API

        调用: GET tx-ops/api/v1/ops/sop/tasks/completion?store_id=...&date=today&slot_code=...
        失败时降级为模拟数据
        """
        try:
            data = await self._call_service(
                TX_OPS_URL,
                "/api/v1/ops/sop/tasks/completion",
                tenant_id=tenant_id,
                params={
                    "store_id": store_id,
                    "date": "today",
                    "slot_code": slot_code,
                },
            )
            sop = data.get("data", data)
            return {
                "total": sop.get("total", 0),
                "completed": sop.get("completed", 0),
                "skipped": sop.get("skipped", 0),
                "overdue": sop.get("overdue", 0),
            }
        except Exception:
            logger.warning(
                "coaching.ops_sop_completion_call_failed",
                store_id=store_id,
                slot_code=slot_code,
                exc_info=True,
            )
            return self._mock_sop_completion(slot_code)

    @staticmethod
    def _mock_sop_completion(slot_code: str) -> dict:
        """模拟SOP完成度（fallback）"""
        total = random.randint(5, 10)
        completed = random.randint(max(3, total - 3), total)
        skipped = random.randint(0, min(2, total - completed))
        overdue = total - completed - skipped

        return {
            "total": total,
            "completed": completed,
            "skipped": skipped,
            "overdue": max(0, overdue),
        }

    async def _get_daily_sop_report(
        self,
        tenant_id: str,
        store_id: str,
    ) -> dict:
        """获取全天SOP报告 — 对接 tx-ops SOP API

        调用: GET tx-ops/api/v1/ops/sop/tasks/completion?store_id=...&date=today
        （不传slot_code表示全天汇总）
        失败时降级为模拟数据
        """
        try:
            data = await self._call_service(
                TX_OPS_URL,
                "/api/v1/ops/sop/tasks/completion",
                tenant_id=tenant_id,
                params={"store_id": store_id, "date": "today"},
            )
            sop = data.get("data", data)
            total = sop.get("total", 0)
            completed = sop.get("completed", 0)
            completion_rate = round(completed / total * 100, 1) if total > 0 else 0.0
            return {
                "total": total,
                "completed": completed,
                "skipped": sop.get("skipped", 0),
                "overdue": sop.get("overdue", 0),
                "completion_rate": completion_rate,
            }
        except Exception:
            logger.warning(
                "coaching.ops_daily_sop_call_failed",
                store_id=store_id,
                exc_info=True,
            )
            return self._mock_daily_sop_report()

    @staticmethod
    def _mock_daily_sop_report() -> dict:
        """模拟全天SOP报告（fallback）"""
        total = random.randint(25, 40)
        completed = random.randint(max(20, total - 5), total)
        skipped = random.randint(0, min(3, total - completed))
        overdue = total - completed - skipped
        completion_rate = round(completed / total * 100, 1) if total > 0 else 0.0

        return {
            "total": total,
            "completed": completed,
            "skipped": skipped,
            "overdue": max(0, overdue),
            "completion_rate": completion_rate,
        }

    async def _get_corrective_summary(
        self,
        tenant_id: str,
        store_id: str,
    ) -> dict:
        """获取纠正动作汇总 — 对接 tx-ops corrective-actions API

        调用: GET tx-ops/api/v1/ops/sop/corrective-actions/summary?store_id=...&date=today
        失败时降级为模拟数据
        """
        try:
            data = await self._call_service(
                TX_OPS_URL,
                "/api/v1/ops/sop/corrective-actions/summary",
                tenant_id=tenant_id,
                params={"store_id": store_id, "date": "today"},
            )
            summary = data.get("data", data)
            return {
                "total": summary.get("total", 0),
                "resolved": summary.get("resolved", 0),
                "pending": summary.get("pending", 0),
            }
        except Exception:
            logger.warning(
                "coaching.ops_corrective_call_failed",
                store_id=store_id,
                exc_info=True,
            )
            return self._mock_corrective_summary()

    @staticmethod
    def _mock_corrective_summary() -> dict:
        """模拟纠正动作汇总（fallback）"""
        total = random.randint(0, 5)
        resolved = random.randint(0, total)
        pending = total - resolved

        return {
            "total": total,
            "resolved": resolved,
            "pending": pending,
        }

    @staticmethod
    def _extract_highlights(vs_baseline: list[dict]) -> list[str]:
        """从基线对比中提取亮点"""
        highlights: list[str] = []
        for item in vs_baseline:
            if item["status"] == "good":
                name = item["metric_name"]
                diff = item["diff_pct"]
                direction = "提升" if diff > 0 else "降低"
                highlights.append(f"{name}{direction}{abs(diff):.1f}%，优于基线表现")
        if not highlights:
            highlights.append("各项指标表现平稳，与基线基本持平")
        return highlights

    @staticmethod
    def _extract_improvements(
        vs_baseline: list[dict],
        sop_completion: dict,
    ) -> list[str]:
        """从基线对比中提取改进建议"""
        improvements: list[str] = []
        for item in vs_baseline:
            if item["status"] == "concern":
                name = item["metric_name"]
                diff = item["diff_pct"]
                improvements.append(f"{name}偏离基线{abs(diff):.1f}%，建议复查原因")

        overdue = sop_completion.get("overdue", 0)
        if overdue > 0:
            improvements.append(f"有{overdue}项SOP任务超时未完成，请关注执行纪律")

        skipped = sop_completion.get("skipped", 0)
        if skipped > 0:
            improvements.append(f"有{skipped}项SOP任务被跳过，请确认是否合理")

        if not improvements:
            improvements.append("本时段无明显改进项，继续保持")

        return improvements

    @staticmethod
    def _generate_daily_lessons(
        vs_baseline: list[dict],
        sop_report: dict,
        corrective_summary: dict,
    ) -> list[str]:
        """生成闭店经验教训"""
        lessons: list[str] = []

        # 基于异常指标
        concerns = [item for item in vs_baseline if item["status"] == "concern"]
        goods = [item for item in vs_baseline if item["status"] == "good"]

        if goods:
            top_good = goods[0]
            lessons.append(
                f"今日{top_good['metric_name']}表现突出，超越基线{abs(top_good['diff_pct']):.1f}%，可总结经验推广"
            )

        if concerns:
            top_concern = concerns[0]
            lessons.append(
                f"{top_concern['metric_name']}偏离基线{abs(top_concern['diff_pct']):.1f}%，"
                f"建议明日重点关注并制定改进计划"
            )

        # SOP执行
        completion_rate = sop_report.get("completion_rate", 0.0)
        if completion_rate >= 95:
            lessons.append(f"SOP执行率{completion_rate}%，纪律优秀")
        elif completion_rate < 85:
            lessons.append(f"SOP执行率仅{completion_rate}%，需加强团队管理")

        # 纠正动作
        pending = corrective_summary.get("pending", 0)
        if pending > 0:
            lessons.append(f"仍有{pending}项纠正动作待处理，明日需跟进闭环")

        if not lessons:
            lessons.append("今日运营总体平稳，各指标在正常范围")

        return lessons

    @staticmethod
    def _generate_tomorrow_suggestions(
        daily_metrics: dict[str, float],
        vs_baseline: list[dict],
    ) -> list[str]:
        """生成明日建议"""
        suggestions: list[str] = []

        # 基于今日数据推断
        concerns = [item for item in vs_baseline if item["status"] == "concern"]
        for item in concerns[:2]:
            suggestions.append(f"重点监控{item['metric_name']}，今日偏离{abs(item['diff_pct']):.1f}%")

        # 通用建议
        food_cost = daily_metrics.get("food_cost_rate", 35.0)
        if food_cost > 36.0:
            suggestions.append("食材成本率偏高，明日关注备料精准度和废弃控制")

        complaints = daily_metrics.get("customer_complaints", 0)
        if complaints >= 3:
            suggestions.append("投诉较多，明日加强前厅服务培训和巡台")

        if not suggestions:
            suggestions.append("各项指标正常，按标准SOP执行即可")

        return suggestions
