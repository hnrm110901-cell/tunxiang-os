"""商户经营目标配置 — 单数据源

所有服务从此处导入商户 KPI 目标配置，避免多份定义漂移。
"""

# 三商户默认 KPI 目标配置
DEFAULT_TARGETS: dict[str, dict] = {
    "czyz": {
        "merchant_name": "尝在一起",
        "focus": "翻台率优先",
        "targets": {
            "table_turnover_rate": 4.5,  # 次/天
            "avg_dish_time_minutes": 18,  # 分钟
            "seat_utilization_pct": 75,  # %
            "avg_ticket_fen": 8500,  # 分
            "member_repurchase_rate_pct": 35,  # %
            "monthly_revenue_growth_pct": 8,  # %
            "gross_margin_pct": 62,  # %
        },
    },
    "zqx": {
        "merchant_name": "最黔线",
        "focus": "客单+复购优先",
        "targets": {
            "table_turnover_rate": 2.8,
            "avg_dish_time_minutes": 25,
            "seat_utilization_pct": 65,
            "avg_ticket_fen": 18000,
            "member_repurchase_rate_pct": 55,
            "monthly_revenue_growth_pct": 12,
            "gross_margin_pct": 58,
        },
    },
    "sgc": {
        "merchant_name": "尚宫厨",
        "focus": "宴席+客单优先",
        "targets": {
            "table_turnover_rate": 1.5,
            "avg_dish_time_minutes": 35,
            "seat_utilization_pct": 60,
            "avg_ticket_fen": 45000,
            "member_repurchase_rate_pct": 30,
            "monthly_revenue_growth_pct": 15,
            "gross_margin_pct": 65,
            "banquet_deposit_rate_pct": 80,
        },
    },
}

# KPI 中文标签
KPI_LABELS: dict[str, str] = {
    "table_turnover_rate": "翻台率（次/天）",
    "avg_dish_time_minutes": "平均出餐时间（分钟）",
    "seat_utilization_pct": "座位利用率（%）",
    "avg_ticket_fen": "客单价（分）",
    "member_repurchase_rate_pct": "会员复购率（%）",
    "monthly_revenue_growth_pct": "月营收增长率（%）",
    "gross_margin_pct": "毛利率（%）",
    "banquet_deposit_rate_pct": "宴席定金率（%）",
}

# 越低越好的 KPI（反向 KPI）
LOWER_IS_BETTER: set[str] = {"avg_dish_time_minutes"}

# 支持的商户代码
SUPPORTED_MERCHANTS: list[str] = ["czyz", "zqx", "sgc"]
