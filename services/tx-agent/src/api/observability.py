"""Agent Observability API — Agent 可观测性中心

提供 KPI 汇总、实时事件流、决策追踪、效果分析、健康度监控等接口。
当前返回 mock 数据，生产环境替换为 EventBus + DecisionFeedbackService 真实数据。
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/v1/agent/observability", tags=["observability"])


# ─── Mock 数据 ───


def _ts(hour: int, minute: int) -> str:
    """生成今日指定时分的时间字符串"""
    return f"{hour:02d}:{minute:02d}"


MOCK_EVENTS = [
    {
        "event_id": str(uuid.uuid4()),
        "timestamp": _ts(8, 15),
        "source_agent": "inventory_alert",
        "event_type": "inventory_surplus",
        "store_id": "store-furong",
        "store_name": "芙蓉路店",
        "summary": "鲈鱼库存超预期+50%",
        "correlation_id": "chain-001",
        "data": {"ingredient": "鲈鱼", "surplus_pct": 50},
    },
    {
        "event_id": str(uuid.uuid4()),
        "timestamp": _ts(8, 15),
        "source_agent": "smart_menu",
        "event_type": "menu_adjustment",
        "store_id": "store-furong",
        "store_name": "芙蓉路店",
        "summary": "主推鲈鱼相关菜品",
        "correlation_id": "chain-001",
        "data": {"action": "push", "dishes": ["清蒸鲈鱼", "酸菜鲈鱼"]},
    },
    {
        "event_id": str(uuid.uuid4()),
        "timestamp": _ts(8, 16),
        "source_agent": "discount_guard",
        "event_type": "violation_blocked",
        "store_id": "store-furong",
        "store_name": "芙蓉路店",
        "summary": "拦截A05桌62%折扣(超毛利底线)",
        "correlation_id": "chain-002",
        "data": {"table": "A05", "discount_pct": 62, "reason": "超毛利底线"},
    },
    {
        "event_id": str(uuid.uuid4()),
        "timestamp": _ts(8, 20),
        "source_agent": "planner",
        "event_type": "plan_generated",
        "store_id": "store-furong",
        "store_name": "芙蓉路店",
        "summary": "芙蓉路店今日经营计划已生成(11条建议)",
        "correlation_id": "chain-003",
        "data": {"plan_items": 11},
    },
    {
        "event_id": str(uuid.uuid4()),
        "timestamp": _ts(8, 25),
        "source_agent": "serve_dispatch",
        "event_type": "dispatch_optimized",
        "store_id": "store-furong",
        "store_name": "芙蓉路店",
        "summary": "午高峰排班优化:增派1名服务员",
        "correlation_id": "chain-004",
        "data": {"shift": "11:00-14:00", "added_staff": 1},
    },
    {
        "event_id": str(uuid.uuid4()),
        "timestamp": _ts(8, 30),
        "source_agent": "member_insight",
        "event_type": "vip_alert",
        "store_id": "store-furong",
        "store_name": "芙蓉路店",
        "summary": "VIP客户张总预订午餐,偏好剁椒鱼头",
        "correlation_id": "chain-005",
        "data": {"customer": "张总", "preference": "剁椒鱼头"},
    },
    {
        "event_id": str(uuid.uuid4()),
        "timestamp": _ts(9, 0),
        "source_agent": "inventory_alert",
        "event_type": "inventory_shortage",
        "store_id": "store-wanjiali",
        "store_name": "万家丽店",
        "summary": "基围虾库存不足,建议紧急采购15kg",
        "correlation_id": "chain-006",
        "data": {"ingredient": "基围虾", "current_kg": 3, "needed_kg": 15},
    },
    {
        "event_id": str(uuid.uuid4()),
        "timestamp": _ts(9, 10),
        "source_agent": "finance_audit",
        "event_type": "anomaly_detected",
        "store_id": "store-furong",
        "store_name": "芙蓉路店",
        "summary": "检测到昨日原材料成本异常偏高+12%",
        "correlation_id": "chain-007",
        "data": {"cost_increase_pct": 12, "category": "原材料"},
    },
    {
        "event_id": str(uuid.uuid4()),
        "timestamp": _ts(9, 15),
        "source_agent": "private_ops",
        "event_type": "campaign_triggered",
        "store_id": "store-furong",
        "store_name": "芙蓉路店",
        "summary": "向156位30天未到店老客发送回归优惠券",
        "correlation_id": "chain-008",
        "data": {"audience": "30天未到店老客", "count": 156, "coupon": "满100减20"},
    },
    {
        "event_id": str(uuid.uuid4()),
        "timestamp": _ts(9, 20),
        "source_agent": "store_inspect",
        "event_type": "checklist_generated",
        "store_id": "store-wanjiali",
        "store_name": "万家丽店",
        "summary": "万家丽店午市前巡检清单已生成(8项)",
        "correlation_id": "chain-009",
        "data": {"checklist_items": 8},
    },
]

MOCK_DECISIONS = [
    {
        "decision_id": "dec-001",
        "agent": "smart_menu",
        "agent_name": "智能排菜",
        "decision": "主推剁椒鱼头",
        "reason": "近7天销量上升23%,毛利率62%,库存充足",
        "confidence": 0.92,
        "status": "adopted",
        "outcome_score": 87,
        "outcome_summary": "销量+18%",
        "store_name": "芙蓉路店",
        "created_at": "2026-03-26 08:00",
    },
    {
        "decision_id": "dec-002",
        "agent": "inventory_alert",
        "agent_name": "库存预警",
        "decision": "虾仁紧急采购15kg",
        "reason": "当前库存3kg,预测今日消耗18kg,缺口15kg",
        "confidence": 0.95,
        "status": "adopted",
        "outcome_score": 92,
        "outcome_summary": "无缺货",
        "store_name": "芙蓉路店",
        "created_at": "2026-03-26 08:10",
    },
    {
        "decision_id": "dec-003",
        "agent": "discount_guard",
        "agent_name": "折扣守护",
        "decision": "拦截62%折扣(A05桌)",
        "reason": "折扣率62%超过毛利底线阈值55%",
        "confidence": 0.98,
        "status": "auto_executed",
        "outcome_score": 95,
        "outcome_summary": "挽回毛利损失¥180",
        "store_name": "芙蓉路店",
        "created_at": "2026-03-26 08:16",
    },
    {
        "decision_id": "dec-004",
        "agent": "serve_dispatch",
        "agent_name": "出餐调度",
        "decision": "午高峰增派1名服务员",
        "reason": "预测今日午间客流+18%,当前排班不足",
        "confidence": 0.88,
        "status": "adopted",
        "outcome_score": 78,
        "outcome_summary": "人效+8%",
        "store_name": "芙蓉路店",
        "created_at": "2026-03-26 08:25",
    },
    {
        "decision_id": "dec-005",
        "agent": "member_insight",
        "agent_name": "会员洞察",
        "decision": "VIP张总偏好提醒",
        "reason": "张总近3次必点剁椒鱼头,提前备料",
        "confidence": 0.85,
        "status": "adopted",
        "outcome_score": 80,
        "outcome_summary": "客户满意度提升",
        "store_name": "芙蓉路店",
        "created_at": "2026-03-26 08:30",
    },
    {
        "decision_id": "dec-006",
        "agent": "smart_menu",
        "agent_name": "智能排菜",
        "decision": "减推外婆鸡",
        "reason": "鸡肉库存偏低,明日到货前需控制出品量",
        "confidence": 0.85,
        "status": "adopted",
        "outcome_score": 83,
        "outcome_summary": "库存节约2.5kg",
        "store_name": "芙蓉路店",
        "created_at": "2026-03-26 08:35",
    },
    {
        "decision_id": "dec-007",
        "agent": "private_ops",
        "agent_name": "私域运营",
        "decision": "发送回归优惠券",
        "reason": "156位30天未到店老客,预计回流率12%",
        "confidence": 0.76,
        "status": "adopted",
        "outcome_score": 72,
        "outcome_summary": "回流率9.5%",
        "store_name": "芙蓉路店",
        "created_at": "2026-03-26 09:15",
    },
    {
        "decision_id": "dec-008",
        "agent": "finance_audit",
        "agent_name": "财务稽核",
        "decision": "标记原材料成本异常",
        "reason": "昨日原材料成本同比+12%,超出正常波动范围",
        "confidence": 0.91,
        "status": "pending",
        "outcome_score": None,
        "outcome_summary": None,
        "store_name": "芙蓉路店",
        "created_at": "2026-03-26 09:10",
    },
    {
        "decision_id": "dec-009",
        "agent": "discount_guard",
        "agent_name": "折扣守护",
        "decision": "拦截B12桌员工餐滥用",
        "reason": "同一员工本周第4次员工餐折扣,超出限额",
        "confidence": 0.96,
        "status": "auto_executed",
        "outcome_score": 93,
        "outcome_summary": "阻止违规折扣¥85",
        "store_name": "万家丽店",
        "created_at": "2026-03-26 09:25",
    },
    {
        "decision_id": "dec-010",
        "agent": "store_inspect",
        "agent_name": "巡店质检",
        "decision": "生成午市前巡检清单",
        "reason": "万家丽店午市前需完成8项检查",
        "confidence": 0.90,
        "status": "adopted",
        "outcome_score": 85,
        "outcome_summary": "8项全部完成",
        "store_name": "万家丽店",
        "created_at": "2026-03-26 09:20",
    },
]

MOCK_EFFECTIVENESS = {
    "agents": [
        {
            "agent_id": "discount_guard",
            "agent_name": "折扣守护",
            "current_score": 95.0,
            "trend": "up",
            "scores_30d": [
                88, 89, 90, 91, 90, 92, 91, 93, 92, 93,
                94, 93, 94, 95, 94, 95, 94, 95, 96, 95,
                94, 95, 95, 96, 95, 95, 96, 95, 95, 95,
            ],
        },
        {
            "agent_id": "inventory_alert",
            "agent_name": "库存预警",
            "current_score": 87.3,
            "trend": "stable",
            "scores_30d": [
                85, 84, 86, 87, 86, 88, 87, 86, 87, 88,
                87, 86, 87, 88, 87, 88, 87, 86, 87, 88,
                87, 88, 87, 87, 88, 87, 87, 88, 87, 87,
            ],
        },
        {
            "agent_id": "smart_menu",
            "agent_name": "智能排菜",
            "current_score": 82.1,
            "trend": "up",
            "scores_30d": [
                72, 73, 74, 75, 74, 76, 77, 76, 78, 77,
                78, 79, 78, 79, 80, 79, 80, 81, 80, 81,
                80, 81, 82, 81, 82, 81, 82, 82, 82, 82,
            ],
        },
        {
            "agent_id": "member_insight",
            "agent_name": "会员洞察",
            "current_score": 78.5,
            "trend": "stable",
            "scores_30d": [
                76, 77, 76, 78, 77, 78, 77, 78, 79, 78,
                77, 78, 79, 78, 79, 78, 78, 79, 78, 79,
                78, 78, 79, 78, 79, 78, 79, 78, 79, 79,
            ],
        },
        {
            "agent_id": "serve_dispatch",
            "agent_name": "出餐调度",
            "current_score": 80.2,
            "trend": "up",
            "scores_30d": [
                70, 71, 72, 73, 74, 73, 75, 74, 76, 75,
                76, 77, 76, 78, 77, 78, 79, 78, 79, 80,
                79, 80, 79, 80, 80, 80, 80, 80, 80, 80,
            ],
        },
        {
            "agent_id": "finance_audit",
            "agent_name": "财务稽核",
            "current_score": 85.0,
            "trend": "stable",
            "scores_30d": [
                84, 84, 85, 84, 85, 85, 84, 85, 85, 85,
                84, 85, 85, 85, 84, 85, 85, 85, 85, 85,
                84, 85, 85, 85, 85, 85, 85, 85, 85, 85,
            ],
        },
        {
            "agent_id": "private_ops",
            "agent_name": "私域运营",
            "current_score": 72.8,
            "trend": "up",
            "scores_30d": [
                62, 63, 64, 65, 64, 66, 67, 66, 68, 67,
                68, 69, 68, 70, 69, 70, 71, 70, 71, 72,
                71, 72, 71, 72, 72, 72, 73, 72, 73, 73,
            ],
        },
        {
            "agent_id": "store_inspect",
            "agent_name": "巡店质检",
            "current_score": 76.5,
            "trend": "stable",
            "scores_30d": [
                75, 75, 76, 75, 76, 76, 75, 76, 76, 76,
                75, 76, 76, 76, 76, 76, 76, 77, 76, 77,
                76, 76, 77, 76, 77, 76, 76, 77, 76, 77,
            ],
        },
    ],
    "decision_type_distribution": [
        {"type": "menu_adjustment", "label": "排菜调整", "count": 45},
        {"type": "discount_block", "label": "折扣拦截", "count": 32},
        {"type": "inventory_alert", "label": "库存预警", "count": 28},
        {"type": "staffing", "label": "人员调度", "count": 22},
        {"type": "marketing", "label": "营销触发", "count": 18},
        {"type": "inspection", "label": "巡检质检", "count": 11},
    ],
    "agent_monthly_stats": [
        {"agent_name": "折扣守护", "suggestions": 234, "adopted": 228},
        {"agent_name": "智能排菜", "suggestions": 156, "adopted": 138},
        {"agent_name": "出餐调度", "suggestions": 189, "adopted": 172},
        {"agent_name": "库存预警", "suggestions": 98, "adopted": 91},
        {"agent_name": "会员洞察", "suggestions": 67, "adopted": 54},
        {"agent_name": "财务稽核", "suggestions": 45, "adopted": 42},
        {"agent_name": "私域运营", "suggestions": 38, "adopted": 29},
        {"agent_name": "巡店质检", "suggestions": 52, "adopted": 48},
    ],
}

MOCK_HEALTH = [
    {
        "agent_id": "discount_guard",
        "agent_name": "折扣守护",
        "status": "healthy",
        "today_calls": 234,
        "avg_latency_ms": 12,
        "error_rate": 0.001,
        "last_call": "2分钟前",
        "uptime_pct": 99.99,
    },
    {
        "agent_id": "smart_menu",
        "agent_name": "智能排菜",
        "status": "healthy",
        "today_calls": 89,
        "avg_latency_ms": 45,
        "error_rate": 0.002,
        "last_call": "5分钟前",
        "uptime_pct": 99.95,
    },
    {
        "agent_id": "serve_dispatch",
        "agent_name": "出餐调度",
        "status": "healthy",
        "today_calls": 156,
        "avg_latency_ms": 23,
        "error_rate": 0.0,
        "last_call": "30秒前",
        "uptime_pct": 100.0,
    },
    {
        "agent_id": "member_insight",
        "agent_name": "会员洞察",
        "status": "healthy",
        "today_calls": 67,
        "avg_latency_ms": 120,
        "error_rate": 0.005,
        "last_call": "8分钟前",
        "uptime_pct": 99.90,
    },
    {
        "agent_id": "inventory_alert",
        "agent_name": "库存预警",
        "status": "healthy",
        "today_calls": 98,
        "avg_latency_ms": 35,
        "error_rate": 0.001,
        "last_call": "3分钟前",
        "uptime_pct": 99.98,
    },
    {
        "agent_id": "finance_audit",
        "agent_name": "财务稽核",
        "status": "healthy",
        "today_calls": 45,
        "avg_latency_ms": 89,
        "error_rate": 0.002,
        "last_call": "15分钟前",
        "uptime_pct": 99.93,
    },
    {
        "agent_id": "store_inspect",
        "agent_name": "巡店质检",
        "status": "healthy",
        "today_calls": 52,
        "avg_latency_ms": 67,
        "error_rate": 0.0,
        "last_call": "20分钟前",
        "uptime_pct": 100.0,
    },
    {
        "agent_id": "private_ops",
        "agent_name": "私域运营",
        "status": "warning",
        "today_calls": 38,
        "avg_latency_ms": 210,
        "error_rate": 0.015,
        "last_call": "25分钟前",
        "uptime_pct": 99.50,
    },
    {
        "agent_id": "smart_cs",
        "agent_name": "智能客服",
        "status": "healthy",
        "today_calls": 23,
        "avg_latency_ms": 150,
        "error_rate": 0.003,
        "last_call": "12分钟前",
        "uptime_pct": 99.85,
    },
]

MOCK_EVENT_CHAIN = {
    "chain-001": [
        {
            "event_id": "evt-chain-001-a",
            "timestamp": _ts(8, 15),
            "source_agent": "inventory_alert",
            "event_type": "inventory_surplus",
            "summary": "检测到鲈鱼库存超预期+50%",
            "data": {"ingredient": "鲈鱼", "surplus_pct": 50},
        },
        {
            "event_id": "evt-chain-001-b",
            "timestamp": _ts(8, 15),
            "source_agent": "smart_menu",
            "event_type": "menu_adjustment",
            "summary": "响应库存预警,主推鲈鱼相关菜品",
            "data": {"action": "push", "dishes": ["清蒸鲈鱼", "酸菜鲈鱼"]},
        },
        {
            "event_id": "evt-chain-001-c",
            "timestamp": _ts(8, 16),
            "source_agent": "private_ops",
            "event_type": "campaign_triggered",
            "summary": "触发鲈鱼特价推送,目标120位周边会员",
            "data": {"audience": "周边3km会员", "count": 120, "content": "鲈鱼特惠"},
        },
    ],
}


# ─── API Endpoints ───


@router.get("/kpis")
async def get_kpis() -> dict:
    """KPI 汇总 — 今日决策数、采纳率、平均效果分、约束拦截数"""
    total_decisions = len(MOCK_DECISIONS)
    adopted = sum(
        1 for d in MOCK_DECISIONS
        if d["status"] in ("adopted", "auto_executed")
    )
    scored = [d for d in MOCK_DECISIONS if d.get("outcome_score") is not None]
    avg_score = round(sum(d["outcome_score"] for d in scored) / len(scored), 1) if scored else 0.0
    blocked = sum(1 for d in MOCK_DECISIONS if d["status"] == "auto_executed")

    return {
        "ok": True,
        "data": {
            "today_decisions": total_decisions,
            "adoption_rate": round(adopted / total_decisions * 100, 1) if total_decisions > 0 else 0.0,
            "avg_effectiveness_score": avg_score,
            "constraint_blocks": blocked,
            "active_agents": len(MOCK_HEALTH),
            "total_events_today": len(MOCK_EVENTS),
        },
    }


@router.get("/events")
async def get_events(
    agent: Optional[str] = Query(None, description="按来源Agent过滤"),
    event_type: Optional[str] = Query(None, description="按事件类型过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> dict:
    """实时事件流 — 最近事件列表(分页, 可按agent/type过滤)"""
    filtered = MOCK_EVENTS
    if agent:
        filtered = [e for e in filtered if e["source_agent"] == agent]
    if event_type:
        filtered = [e for e in filtered if e["event_type"] == event_type]

    total = len(filtered)
    start = (page - 1) * size
    end = start + size
    items = filtered[start:end]

    return {
        "ok": True,
        "data": {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        },
    }


@router.get("/decisions")
async def get_decisions(
    agent: Optional[str] = Query(None, description="按Agent过滤"),
    status: Optional[str] = Query(None, description="按状态过滤: adopted/pending/auto_executed"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> dict:
    """决策追踪 — 决策日志(可按agent/status/date过滤)"""
    filtered = MOCK_DECISIONS
    if agent:
        filtered = [d for d in filtered if d["agent"] == agent]
    if status:
        filtered = [d for d in filtered if d["status"] == status]

    total = len(filtered)
    start = (page - 1) * size
    end = start + size
    items = filtered[start:end]

    return {
        "ok": True,
        "data": {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
        },
    }


@router.get("/effectiveness")
async def get_effectiveness() -> dict:
    """效果分析 — 各Agent效果分趋势、决策类型分布、建议vs采纳统计"""
    return {
        "ok": True,
        "data": MOCK_EFFECTIVENESS,
    }


@router.get("/health")
async def get_health() -> dict:
    """Agent 健康度 — 各Agent运行状态、调用次数、延迟、错误率"""
    return {
        "ok": True,
        "data": {
            "agents": MOCK_HEALTH,
            "summary": {
                "total_agents": len(MOCK_HEALTH),
                "healthy": sum(1 for a in MOCK_HEALTH if a["status"] == "healthy"),
                "warning": sum(1 for a in MOCK_HEALTH if a["status"] == "warning"),
                "error": sum(1 for a in MOCK_HEALTH if a["status"] == "error"),
            },
        },
    }


@router.get("/event-chain/{correlation_id}")
async def get_event_chain(correlation_id: str) -> dict:
    """事件链路追踪 — 按correlation_id查看完整事件链"""
    chain = MOCK_EVENT_CHAIN.get(correlation_id, [])
    return {
        "ok": True,
        "data": {
            "correlation_id": correlation_id,
            "events": chain,
            "count": len(chain),
        },
    }
