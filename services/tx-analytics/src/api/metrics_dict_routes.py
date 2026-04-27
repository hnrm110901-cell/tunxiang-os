"""指标口径字典 API — 所有经营分析指标定义及数据溯源

端点：
  GET /api/v1/analytics/metrics-dict              — 全量指标字典
  GET /api/v1/analytics/metrics-dict/{metric_key} — 单个指标详情
  GET /api/v1/analytics/metrics-dict/domains       — 指标域列表

Week 2 P0 验收物：指标口径字典（可追溯到字段）
每个指标包含：中英文名称 / 计算公式 / 数据来源表+字段 / 更新频率 / 统计口径说明
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/v1/analytics/metrics-dict", tags=["metrics-dict"])

# ─── 指标字典定义 ─────────────────────────────────────────────────────────────
# 格式：key → {name_zh, name_en, domain, formula, sources, refresh_sla, note}

METRICS_DICT: dict[str, dict] = {
    # ── 营收域 ────────────────────────────────────────────────────────────────
    "revenue_fen": {
        "name_zh": "营业收入",
        "name_en": "Revenue",
        "domain": "revenue",
        "unit": "分（整数）",
        "formula": "SUM(orders.total_amount_fen) WHERE status='completed'",
        "sources": [
            {"table": "orders", "fields": ["total_amount_fen", "status", "created_at", "tenant_id"]},
        ],
        "refresh_sla": "交易类 ≤5分钟",
        "note": "仅统计 status=completed 的订单，不含 cancelled/refunded",
    },
    "order_count": {
        "name_zh": "订单笔数",
        "name_en": "Order Count",
        "domain": "revenue",
        "unit": "笔",
        "formula": "COUNT(*) FROM orders WHERE status='completed'",
        "sources": [
            {"table": "orders", "fields": ["id", "status", "created_at", "tenant_id"]},
        ],
        "refresh_sla": "交易类 ≤5分钟",
        "note": "含堂食/外卖/外带全渠道，可按 order_type 拆分",
    },
    "avg_ticket_yuan": {
        "name_zh": "客单价",
        "name_en": "Average Ticket",
        "domain": "revenue",
        "unit": "元（保留2位小数）",
        "formula": "AVG(orders.total_amount_fen) / 100.0 WHERE status='completed'",
        "sources": [
            {"table": "orders", "fields": ["total_amount_fen", "status", "created_at"]},
        ],
        "refresh_sla": "分析类 ≤15分钟",
        "note": "按完成订单均值计算，外卖订单客单价与堂食差异显著时建议分渠道展示",
    },
    "daily_avg_revenue_yuan": {
        "name_zh": "日均营收",
        "name_en": "Daily Average Revenue",
        "domain": "revenue",
        "unit": "元",
        "formula": "SUM(revenue_fen) / COUNT(DISTINCT business_date) / 100.0",
        "sources": [
            {"table": "orders", "fields": ["total_amount_fen", "status", "created_at"]},
        ],
        "refresh_sla": "分析类 ≤15分钟",
        "note": "按自然日（Asia/Shanghai时区）统计，非自然月按实际营业天数除",
    },
    # ── 毛利域 ────────────────────────────────────────────────────────────────
    "margin_rate": {
        "name_zh": "综合毛利率",
        "name_en": "Gross Margin Rate",
        "domain": "margin",
        "unit": "%",
        "formula": "(SUM(total_amount_fen) - SUM(cost_amount_fen)) / SUM(total_amount_fen) * 100",
        "sources": [
            {"table": "orders", "fields": ["total_amount_fen", "cost_amount_fen", "status"]},
        ],
        "refresh_sla": "分析类 ≤15分钟",
        "note": "cost_amount_fen 来自订单行 BOM 成本展开，需 tx-supply 完成成本核算后才精确",
    },
    "discount_fen": {
        "name_zh": "折扣总额",
        "name_en": "Total Discount",
        "domain": "margin",
        "unit": "分（整数）",
        "formula": "SUM(orders.discount_amount_fen) WHERE status='completed'",
        "sources": [
            {"table": "orders", "fields": ["discount_amount_fen", "status", "created_at"]},
        ],
        "refresh_sla": "交易类 ≤5分钟",
        "note": "包含整单折扣、品项折扣、优惠券抵扣，不含免单（免单计入 cancelled）",
    },
    "discount_exception_rate": {
        "name_zh": "折扣异常率",
        "name_en": "Discount Exception Rate",
        "domain": "margin",
        "unit": "%",
        "formula": "COUNT(*) FILTER (discount_amount_fen/total_amount_fen > 0.3) / COUNT(*) * 100",
        "sources": [
            {"table": "orders", "fields": ["discount_amount_fen", "total_amount_fen", "status"]},
        ],
        "refresh_sla": "分析类 ≤15分钟",
        "note": "折扣超过订单总额 30% 视为异常，阈值可在 agent_kpi_configs 中调整",
    },
    # ── 客流域 ────────────────────────────────────────────────────────────────
    "table_turnover_rate": {
        "name_zh": "翻台率",
        "name_en": "Table Turnover Rate",
        "domain": "traffic",
        "unit": "次/台/天",
        "formula": "COUNT(DISTINCT session_id) / COUNT(DISTINCT table_id) / business_days",
        "sources": [
            {"table": "dining_sessions", "fields": ["id", "table_id", "opened_at", "closed_at", "store_id"]},
            {"table": "tables", "fields": ["id", "store_id"]},
        ],
        "refresh_sla": "分析类 ≤15分钟",
        "note": "仅统计 status=closed 的台次，同一餐桌同一天开台≥2次即计翻台",
    },
    "member_order_rate": {
        "name_zh": "会员订单占比",
        "name_en": "Member Order Rate",
        "domain": "traffic",
        "unit": "%",
        "formula": "COUNT(*) FILTER (member_id IS NOT NULL) / COUNT(*) * 100",
        "sources": [
            {"table": "orders", "fields": ["member_id", "status", "created_at"]},
        ],
        "refresh_sla": "分析类 ≤15分钟",
        "note": "含储值卡会员 + 积分会员 + 小程序注册会员，通过 orders.member_id 关联",
    },
    "member_repurchase_rate": {
        "name_zh": "会员复购率",
        "name_en": "Member Repurchase Rate",
        "domain": "traffic",
        "unit": "%",
        "formula": "COUNT(DISTINCT member_id) FILTER (order_count >= 2) / COUNT(DISTINCT member_id) * 100 (30日滚动窗口)",
        "sources": [
            {"table": "orders", "fields": ["member_id", "status", "created_at"]},
        ],
        "refresh_sla": "分析类 ≤15分钟",
        "note": "统计周期：滚动30天，统计范围：当月有消费记录的会员中，有2次及以上消费的比例",
    },
    # ── 出餐域 ────────────────────────────────────────────────────────────────
    "avg_dish_time_seconds": {
        "name_zh": "平均出餐时间",
        "name_en": "Average Dish Time",
        "domain": "kds",
        "unit": "秒",
        "formula": "AVG(EXTRACT(EPOCH FROM (served_at - called_at))) FROM banquet_kds_dishes WHERE serve_status='served'",
        "sources": [
            {"table": "banquet_kds_dishes", "fields": ["called_at", "served_at", "serve_status", "session_id"]},
            {"table": "kds_order_items", "fields": ["called_at", "served_at", "status"]},
        ],
        "refresh_sla": "交易类 ≤5分钟",
        "note": "从后厨收到叫菜指令（called_at）到出品确认（served_at）的时间差，超过 10 分钟视为异常",
    },
    "on_time_rate": {
        "name_zh": "准时出餐率",
        "name_en": "On-Time Dish Rate",
        "domain": "kds",
        "unit": "%",
        "formula": "COUNT(*) FILTER (served_at - called_at <= interval '10 minutes') / COUNT(*) * 100",
        "sources": [
            {"table": "banquet_kds_dishes", "fields": ["called_at", "served_at", "serve_status"]},
        ],
        "refresh_sla": "交易类 ≤5分钟",
        "note": "10分钟为默认上限，可在门店设置中调整；宴会场次另有独立超时阈值",
    },
    # ── 会员域 ────────────────────────────────────────────────────────────────
    "stored_value_balance_fen": {
        "name_zh": "储值卡余额",
        "name_en": "Stored Value Balance",
        "domain": "member",
        "unit": "分（整数）",
        "formula": "SUM(balance_fen) FROM stored_value_accounts WHERE is_active=TRUE",
        "sources": [
            {"table": "stored_value_accounts", "fields": ["balance_fen", "member_id", "is_active", "tenant_id"]},
        ],
        "refresh_sla": "交易类 ≤5分钟",
        "note": "门店层面的负债指标，代表已收但未消费的储值金额",
    },
    "clv_growth_rate": {
        "name_zh": "会员生命周期价值增长率",
        "name_en": "CLV Growth Rate",
        "domain": "member",
        "unit": "%",
        "formula": "(本期AVG(member_lifetime_value) - 上期) / 上期 * 100",
        "sources": [
            {"table": "mv_member_clv", "fields": ["member_id", "ltv_fen", "snapshot_date"]},
            {"table": "orders", "fields": ["member_id", "total_amount_fen", "created_at"]},
        ],
        "refresh_sla": "分析类 ≤15分钟",
        "note": "来自物化视图 mv_member_clv（v148建立），每15分钟由投影器刷新",
    },
    # ── 库存域 ────────────────────────────────────────────────────────────────
    "waste_rate": {
        "name_zh": "食材损耗率",
        "name_en": "Ingredient Waste Rate",
        "domain": "inventory",
        "unit": "%",
        "formula": "SUM(waste_qty * unit_cost_fen) / SUM(total_consumed_cost_fen) * 100",
        "sources": [
            {
                "table": "inventory_transactions",
                "fields": ["transaction_type", "quantity", "ingredient_id", "created_at"],
            },
            {"table": "ingredients", "fields": ["id", "unit_cost_fen", "name"]},
        ],
        "refresh_sla": "分析类 ≤15分钟",
        "note": "transaction_type='waste' 的记录，损耗率超过 3% 触发预警",
    },
    "stockout_rate": {
        "name_zh": "缺货率",
        "name_en": "Stockout Rate",
        "domain": "inventory",
        "unit": "%",
        "formula": "COUNT(DISTINCT dish_id) FILTER (status='out_of_stock') / COUNT(DISTINCT dish_id) * 100",
        "sources": [
            {"table": "dish_availability", "fields": ["dish_id", "status", "store_id", "updated_at"]},
        ],
        "refresh_sla": "交易类 ≤5分钟",
        "note": "实时菜品可用状态，从 dish_availability 表读取，由收银/KDS触发更新",
    },
    # ── 合规域 ────────────────────────────────────────────────────────────────
    "daily_settlement_rate": {
        "name_zh": "日结合规率",
        "name_en": "Daily Settlement Compliance Rate",
        "domain": "compliance",
        "unit": "%",
        "formula": "COUNT(DISTINCT settlement_date) FILTER (status='completed') / COUNT(DISTINCT business_date) * 100",
        "sources": [
            {"table": "daily_settlements", "fields": ["settlement_date", "status", "store_id", "tenant_id"]},
        ],
        "refresh_sla": "分析类 ≤15分钟",
        "note": "每日 22:00 前完成日结视为合规，超时未结触发总部预警通知",
    },
    "compliance_score": {
        "name_zh": "合规评分",
        "name_en": "Compliance Score",
        "domain": "compliance",
        "unit": "分（0-100）",
        "formula": "100 - COUNT(open_compliance_alerts) * 5（下限0）",
        "sources": [
            {"table": "compliance_alerts", "fields": ["id", "status", "created_at", "tenant_id"]},
        ],
        "refresh_sla": "分析类 ≤15分钟",
        "note": "每个未处理告警扣5分，来自食安/环保/证照等合规检查模块",
    },
    # ── 财务域 ────────────────────────────────────────────────────────────────
    "gross_profit_fen": {
        "name_zh": "毛利润",
        "name_en": "Gross Profit",
        "domain": "finance",
        "unit": "分（整数）",
        "formula": "SUM(total_amount_fen - cost_amount_fen) FROM orders WHERE status='completed'",
        "sources": [
            {"table": "orders", "fields": ["total_amount_fen", "cost_amount_fen", "status"]},
            {"table": "mv_store_pnl", "fields": ["gross_profit_fen", "store_id", "date"]},
        ],
        "refresh_sla": "分析类 ≤15分钟",
        "note": "实时版来自 orders 表聚合；预计算版来自物化视图 mv_store_pnl（v148建立）",
    },
    "pl_net_profit_fen": {
        "name_zh": "净利润（P&L）",
        "name_en": "Net Profit (P&L)",
        "domain": "finance",
        "unit": "分（整数）",
        "formula": "毛利润 - 人工成本 - 租金 - 水电 - 其他费用",
        "sources": [
            {"table": "mv_store_pnl", "fields": ["net_profit_fen", "store_id", "period"]},
            {"table": "cost_allocations", "fields": ["cost_type", "amount_fen", "store_id", "period"]},
        ],
        "refresh_sla": "分析类 ≤15分钟",
        "note": "需 tx-finance PLService 完成成本归集后才精确，月度数据 T+3 日确认",
    },
    # ── 宴会域 ────────────────────────────────────────────────────────────────
    "banquet_deposit_rate": {
        "name_zh": "宴会定金回收率",
        "name_en": "Banquet Deposit Collection Rate",
        "domain": "banquet",
        "unit": "%",
        "formula": "SUM(balance_fen) FILTER (status IN ('active','applied')) / SUM(amount_fen) * 100",
        "sources": [
            {"table": "banquet_session_deposits", "fields": ["amount_fen", "balance_fen", "status", "session_id"]},
            {"table": "banquet_sessions", "fields": ["id", "status", "tenant_id"]},
        ],
        "refresh_sla": "交易类 ≤5分钟",
        "note": "统计有效定金（active+applied）占已收总定金的比例，退款后分母不变",
    },
}

# ─── 指标域说明 ────────────────────────────────────────────────────────────────

DOMAIN_DESCRIPTIONS = {
    "revenue": {"name_zh": "营收域", "sla": "交易类≤5分钟 / 分析类≤15分钟"},
    "margin": {"name_zh": "毛利域", "sla": "分析类≤15分钟"},
    "traffic": {"name_zh": "客流域", "sla": "分析类≤15分钟"},
    "kds": {"name_zh": "出餐域", "sla": "交易类≤5分钟"},
    "member": {"name_zh": "会员域", "sla": "分析类≤15分钟"},
    "inventory": {"name_zh": "库存域", "sla": "分析类≤15分钟"},
    "compliance": {"name_zh": "合规域", "sla": "分析类≤15分钟"},
    "finance": {"name_zh": "财务域", "sla": "分析类≤15分钟"},
    "banquet": {"name_zh": "宴会域", "sla": "交易类≤5分钟"},
}

# ─── 端点 ─────────────────────────────────────────────────────────────────────


@router.get("/domains", summary="获取指标域列表")
async def list_domains():
    """返回所有指标域及其 SLA 口径说明"""
    return {
        "ok": True,
        "data": [
            {"domain_key": k, **v, "metric_count": sum(1 for m in METRICS_DICT.values() if m["domain"] == k)}
            for k, v in DOMAIN_DESCRIPTIONS.items()
        ],
    }


@router.get("", summary="获取全量指标字典")
async def list_metrics(
    domain: str | None = Query(None, description="按域过滤，如 revenue / margin / traffic"),
    refresh_sla: str | None = Query(None, description="按更新频率过滤：交易类 / 分析类"),
):
    """
    返回所有经营分析指标的定义，包含计算公式、数据来源表+字段、更新频率、统计口径说明。
    Week 2 P0 验收物：指标口径字典（可追溯到字段）。
    """
    result = []
    for key, meta in METRICS_DICT.items():
        if domain and meta["domain"] != domain:
            continue
        if refresh_sla and refresh_sla not in meta["refresh_sla"]:
            continue
        result.append({"metric_key": key, **meta})

    return {
        "ok": True,
        "data": {
            "total": len(result),
            "metrics": result,
            "sla_policy": {
                "transaction_class": "交易类指标（营收/订单/出餐/库存实时状态）更新延迟 ≤5分钟",
                "analytics_class": "分析类指标（毛利/客流/会员/合规/财务）更新延迟 ≤15分钟",
                "note": "延迟从事件发生到指标可查询的端到端时间，含DB写入+投影器刷新+缓存失效",
            },
        },
    }


@router.get("/{metric_key}", summary="获取单个指标详情")
async def get_metric(metric_key: str):
    """返回指定指标的完整定义，含追溯链（来源表 → 字段 → 计算公式）"""
    if metric_key not in METRICS_DICT:
        raise HTTPException(status_code=404, detail=f"指标 {metric_key!r} 不存在，请先查询 /metrics-dict 获取完整列表")
    meta = METRICS_DICT[metric_key]
    domain_info = DOMAIN_DESCRIPTIONS.get(meta["domain"], {})
    return {
        "ok": True,
        "data": {
            "metric_key": metric_key,
            **meta,
            "domain_info": domain_info,
        },
    }
