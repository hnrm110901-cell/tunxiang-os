"""Agent Registry - maps MCP tool names to agent_id + action with JSON Schema definitions.

Contains all 73 Skill Agent actions + Master Agent actions + Planner actions + EventBus actions.
Each entry defines: agent_id, action, description (Chinese), and inputSchema.
"""

from typing import Any

# Type alias for a registry entry
ToolEntry = dict[str, Any]

# ---------------------------------------------------------------------------
# Helper to build a registry entry
# ---------------------------------------------------------------------------

def _entry(
    agent_id: str,
    action: str,
    description: str,
    input_schema: dict[str, Any],
) -> ToolEntry:
    return {
        "agent_id": agent_id,
        "action": action,
        "description": description,
        "inputSchema": {
            "type": "object",
            **input_schema,
        },
    }


# ===========================================================================
# TOOL REGISTRY - 73 Skill Agent actions + Master + Planner + EventBus
# ===========================================================================

TOOL_REGISTRY: dict[str, ToolEntry] = {}


def _register(tool_name: str, entry: ToolEntry) -> None:
    TOOL_REGISTRY[tool_name] = entry


# ---------------------------------------------------------------------------
# #1 discount_guard (6 actions)
# ---------------------------------------------------------------------------

_register("discount_guard__detect_discount_anomaly", _entry(
    agent_id="discount_guard",
    action="detect_discount_anomaly",
    description="折扣异常检测 - 实时检测订单折扣是否异常（边缘优先）",
    input_schema={
        "properties": {
            "order": {
                "type": "object",
                "description": "订单数据，包含 total_amount_fen, discount_amount_fen, cost_fen, waiter_discount_count 等字段",
                "properties": {
                    "total_amount_fen": {"type": "integer", "description": "订单总金额（分）"},
                    "discount_amount_fen": {"type": "integer", "description": "折扣金额（分）"},
                    "cost_fen": {"type": "integer", "description": "成本（分）"},
                    "waiter_discount_count": {"type": "integer", "description": "同一服务员打折次数"},
                },
            },
            "threshold": {
                "type": "number",
                "description": "折扣率异常阈值，默认 0.5",
                "default": 0.5,
            },
        },
        "required": ["order"],
    },
))

_register("discount_guard__scan_store_licenses", _entry(
    agent_id="discount_guard",
    action="scan_store_licenses",
    description="单门店证照扫描 - 检查证照过期、即将过期状态",
    input_schema={
        "properties": {
            "licenses": {
                "type": "array",
                "description": "证照列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "证照名称"},
                        "expiry_date": {"type": "string", "description": "过期日期"},
                        "remaining_days": {"type": "integer", "description": "剩余天数"},
                    },
                },
            },
        },
        "required": ["licenses"],
    },
))

_register("discount_guard__scan_all_licenses", _entry(
    agent_id="discount_guard",
    action="scan_all_licenses",
    description="全品牌证照扫描 - 扫描所有门店的证照合规状态",
    input_schema={
        "properties": {
            "stores": {
                "type": "array",
                "description": "门店列表，每个门店包含 name 和 licenses 数组",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "门店名称"},
                        "licenses": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "remaining_days": {"type": "integer"},
                                },
                            },
                        },
                    },
                },
            },
        },
        "required": ["stores"],
    },
))

_register("discount_guard__get_financial_report", _entry(
    agent_id="discount_guard",
    action="get_financial_report",
    description="财务报表查询 - 生成7种类型的财务报表",
    input_schema={
        "properties": {
            "report_type": {
                "type": "string",
                "description": "报表类型",
                "enum": ["period_summary", "aggregate", "trend", "by_entity", "by_region", "comparison", "plan_vs_actual"],
                "default": "period_summary",
            },
        },
    },
))

_register("discount_guard__explain_voucher", _entry(
    agent_id="discount_guard",
    action="explain_voucher",
    description="凭证解释 - 解释财务凭证的含义和构成",
    input_schema={
        "properties": {
            "voucher_id": {
                "type": "string",
                "description": "凭证ID",
            },
        },
        "required": ["voucher_id"],
    },
))

_register("discount_guard__reconciliation_status", _entry(
    agent_id="discount_guard",
    action="reconciliation_status",
    description="对账状态查询 - 查询指定日期的对账结果",
    input_schema={
        "properties": {
            "date": {
                "type": "string",
                "description": "日期，默认 today",
                "default": "today",
            },
        },
    },
))

# ---------------------------------------------------------------------------
# #2 smart_menu (8 actions)
# ---------------------------------------------------------------------------

_register("smart_menu__simulate_cost", _entry(
    agent_id="smart_menu",
    action="simulate_cost",
    description="BOM成本仿真 - 计算菜品BOM成本、多定价方案、涨价压力测试",
    input_schema={
        "properties": {
            "bom_items": {
                "type": "array",
                "description": "BOM物料列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "物料名称"},
                        "cost_fen": {"type": "integer", "description": "单价（分）"},
                        "quantity": {"type": "number", "description": "用量"},
                    },
                },
            },
            "target_price_fen": {
                "type": "integer",
                "description": "目标售价（分）",
            },
        },
        "required": ["bom_items", "target_price_fen"],
    },
))

_register("smart_menu__recommend_pilot_stores", _entry(
    agent_id="smart_menu",
    action="recommend_pilot_stores",
    description="试点门店推荐 - 根据门店特征推荐新品试点门店",
    input_schema={
        "properties": {
            "stores": {
                "type": "array",
                "description": "候选门店列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "customer_base": {"type": "integer", "description": "客户基数"},
                        "popular_categories": {"type": "array", "items": {"type": "string"}},
                        "staff_skill_avg": {"type": "number", "description": "员工平均技能分"},
                    },
                },
            },
            "dish_category": {
                "type": "string",
                "description": "菜品类目",
            },
        },
        "required": ["stores"],
    },
))

_register("smart_menu__run_dish_review", _entry(
    agent_id="smart_menu",
    action="run_dish_review",
    description="菜品复盘 - 判断菜品 keep/optimize/monitor/retire",
    input_schema={
        "properties": {
            "total_sales": {"type": "integer", "description": "总销量"},
            "return_count": {"type": "integer", "description": "退菜次数"},
            "bad_review_count": {"type": "integer", "description": "差评数"},
            "margin_rate": {"type": "number", "description": "毛利率（0-1）"},
            "category_avg_sales": {"type": "integer", "description": "品类平均销量", "default": 100},
        },
        "required": ["total_sales", "margin_rate"],
    },
))

_register("smart_menu__check_launch_readiness", _entry(
    agent_id="smart_menu",
    action="check_launch_readiness",
    description="上市就绪检查 - 检查新菜品上市前的8项清单",
    input_schema={
        "properties": {
            "completed_items": {
                "type": "array",
                "description": "已完成项目列表（可选项：配方定版/成本核算/SOP文档/试点测试/培训完成/审批通过/物料备齐/定价确认）",
                "items": {"type": "string"},
            },
        },
        "required": ["completed_items"],
    },
))

_register("smart_menu__scan_dish_risks", _entry(
    agent_id="smart_menu",
    action="scan_dish_risks",
    description="菜品风险扫描 - 品牌级扫描所有菜品的成本/评分/退菜/差评风险",
    input_schema={
        "properties": {
            "dishes": {
                "type": "array",
                "description": "菜品列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "菜品名称"},
                        "cost_over_target_pct": {"type": "number", "description": "成本超标百分比"},
                        "pilot_score": {"type": "number", "description": "试点评分"},
                        "return_rate_pct": {"type": "number", "description": "退菜率百分比"},
                        "bad_review_pct": {"type": "number", "description": "差评率百分比"},
                    },
                },
            },
        },
        "required": ["dishes"],
    },
))

_register("smart_menu__inspect_dish_quality", _entry(
    agent_id="smart_menu",
    action="inspect_dish_quality",
    description="菜品图片质检 - 视觉AI对菜品图片进行质量评分",
    input_schema={
        "properties": {
            "image_url": {"type": "string", "description": "菜品图片URL"},
            "dish_name": {"type": "string", "description": "菜品名称"},
            "threshold": {"type": "integer", "description": "合格阈值，默认75", "default": 75},
            "mock_score": {"type": "integer", "description": "模拟评分（测试用）", "default": 82},
        },
        "required": ["image_url", "dish_name"],
    },
))

_register("smart_menu__classify_quadrant", _entry(
    agent_id="smart_menu",
    action="classify_quadrant",
    description="四象限分类 - 将菜品按销量和毛利分为star/cash_cow/question/dog",
    input_schema={
        "properties": {
            "total_sales": {"type": "integer", "description": "总销量"},
            "margin_rate": {"type": "number", "description": "毛利率（0-1）"},
            "avg_sales": {"type": "integer", "description": "平均销量", "default": 100},
            "avg_margin": {"type": "number", "description": "平均毛利率", "default": 0.3},
        },
        "required": ["total_sales", "margin_rate"],
    },
))

_register("smart_menu__optimize_menu", _entry(
    agent_id="smart_menu",
    action="optimize_menu",
    description="菜单结构优化 - 分析所有菜品四象限分布并给出优化建议",
    input_schema={
        "properties": {
            "dishes": {
                "type": "array",
                "description": "菜品列表，每个包含 name, total_sales, margin_rate",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "total_sales": {"type": "integer"},
                        "margin_rate": {"type": "number"},
                    },
                },
            },
        },
        "required": ["dishes"],
    },
))

# ---------------------------------------------------------------------------
# #3 serve_dispatch (7 actions)
# ---------------------------------------------------------------------------

_register("serve_dispatch__predict_serve_time", _entry(
    agent_id="serve_dispatch",
    action="predict_serve_time",
    description="出餐时间预测 - 边缘Core ML预测菜品出餐时间",
    input_schema={
        "properties": {
            "dish_count": {"type": "integer", "description": "菜品数量", "default": 1},
            "has_complex_dish": {"type": "boolean", "description": "是否包含复杂菜品", "default": False},
            "kitchen_queue_size": {"type": "integer", "description": "厨房当前排队数", "default": 0},
        },
    },
))

_register("serve_dispatch__optimize_schedule", _entry(
    agent_id="serve_dispatch",
    action="optimize_schedule",
    description="排班优化 - 基于客流预测的多目标排班优化",
    input_schema={
        "properties": {
            "employees": {
                "type": "array",
                "description": "员工列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "role": {"type": "string"},
                    },
                },
            },
            "traffic_forecast": {
                "type": "array",
                "description": "24小时客流预测数组",
                "items": {"type": "number"},
            },
            "budget_fen": {"type": "integer", "description": "预算（分）", "default": 0},
        },
        "required": ["employees", "traffic_forecast"],
    },
))

_register("serve_dispatch__analyze_traffic", _entry(
    agent_id="serve_dispatch",
    action="analyze_traffic",
    description="客流分析 - 识别客流峰谷时段",
    input_schema={
        "properties": {
            "hourly_customers": {
                "type": "array",
                "description": "每小时客流数据（至少12小时）",
                "items": {"type": "number"},
            },
        },
        "required": ["hourly_customers"],
    },
))

_register("serve_dispatch__predict_staffing_needs", _entry(
    agent_id="serve_dispatch",
    action="predict_staffing_needs",
    description="人力需求预测 - 根据客流预测计算所需人力",
    input_schema={
        "properties": {
            "forecast_customers": {
                "type": "array",
                "description": "各时段预测客流",
                "items": {"type": "number"},
            },
            "service_ratio": {
                "type": "integer",
                "description": "每人服务客户数，默认15",
                "default": 15,
            },
        },
        "required": ["forecast_customers"],
    },
))

_register("serve_dispatch__detect_order_anomaly", _entry(
    agent_id="serve_dispatch",
    action="detect_order_anomaly",
    description="订单异常检测 - 检测超时、退菜、大额折扣等异常",
    input_schema={
        "properties": {
            "order": {
                "type": "object",
                "description": "订单数据",
                "properties": {
                    "elapsed_minutes": {"type": "number", "description": "已用时间（分钟）"},
                    "return_count": {"type": "integer", "description": "退菜次数"},
                    "discount_rate": {"type": "number", "description": "折扣率（0-1）"},
                },
            },
        },
        "required": ["order"],
    },
))

_register("serve_dispatch__trigger_chain_alert", _entry(
    agent_id="serve_dispatch",
    action="trigger_chain_alert",
    description="链式告警 - 一个事件触发三层联动告警",
    input_schema={
        "properties": {
            "event": {
                "type": "object",
                "description": "触发事件",
                "properties": {
                    "type": {"type": "string", "description": "事件类型，如 kitchen_delay, complaint"},
                    "source": {"type": "string", "description": "事件来源"},
                },
            },
        },
        "required": ["event"],
    },
))

_register("serve_dispatch__balance_workload", _entry(
    agent_id="serve_dispatch",
    action="balance_workload",
    description="工作量平衡 - 分析员工负载并建议工单转移",
    input_schema={
        "properties": {
            "staff_loads": {
                "type": "array",
                "description": "员工负载列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "员工姓名"},
                        "current_orders": {"type": "integer", "description": "当前订单数"},
                    },
                },
            },
        },
        "required": ["staff_loads"],
    },
))

# ---------------------------------------------------------------------------
# #4 member_insight (9 actions)
# ---------------------------------------------------------------------------

_register("member_insight__analyze_rfm", _entry(
    agent_id="member_insight",
    action="analyze_rfm",
    description="RFM分层分析 - 对会员进行RFM价值分层（S1-S5）",
    input_schema={
        "properties": {
            "members": {
                "type": "array",
                "description": "会员列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "string"},
                        "recency_days": {"type": "integer", "description": "最近消费距今天数"},
                        "frequency": {"type": "integer", "description": "消费频次"},
                        "monetary_fen": {"type": "integer", "description": "总消费金额（分）"},
                    },
                },
            },
        },
        "required": ["members"],
    },
))

_register("member_insight__detect_signals", _entry(
    agent_id="member_insight",
    action="detect_signals",
    description="行为信号检测 - 检测会员流失预警、生日等行为信号",
    input_schema={
        "properties": {
            "members": {
                "type": "array",
                "description": "会员列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "string"},
                        "recency_days": {"type": "integer"},
                        "birth_date": {"type": "string", "description": "生日日期"},
                    },
                },
            },
        },
        "required": ["members"],
    },
))

_register("member_insight__detect_competitor", _entry(
    agent_id="member_insight",
    action="detect_competitor",
    description="竞对动态监控 - 检测竞争对手降价、新活动等信号",
    input_schema={
        "properties": {
            "competitors": {
                "type": "array",
                "description": "竞对列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "竞对名称"},
                        "price_change_pct": {"type": "number", "description": "价格变动百分比"},
                        "new_campaign": {"type": "string", "description": "新活动描述"},
                    },
                },
            },
        },
        "required": ["competitors"],
    },
))

_register("member_insight__trigger_journey", _entry(
    agent_id="member_insight",
    action="trigger_journey",
    description="触发会员旅程 - 触发 new_customer/vip_retention/reactivation/review_repair/birthday 旅程",
    input_schema={
        "properties": {
            "journey_type": {
                "type": "string",
                "description": "旅程类型",
                "enum": ["new_customer", "vip_retention", "reactivation", "review_repair", "birthday"],
            },
            "customer_id": {"type": "string", "description": "客户ID"},
        },
        "required": ["journey_type", "customer_id"],
    },
))

_register("member_insight__get_churn_risks", _entry(
    agent_id="member_insight",
    action="get_churn_risks",
    description="流失风险检测 - 识别有流失风险的会员并推荐挽留动作",
    input_schema={
        "properties": {
            "members": {
                "type": "array",
                "description": "会员列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "string"},
                        "name": {"type": "string"},
                        "recency_days": {"type": "integer"},
                        "frequency": {"type": "integer"},
                        "monetary_fen": {"type": "integer"},
                    },
                },
            },
            "risk_threshold": {"type": "number", "description": "风险阈值（0-1），默认0.5", "default": 0.5},
        },
        "required": ["members"],
    },
))

_register("member_insight__process_bad_review", _entry(
    agent_id="member_insight",
    action="process_bad_review",
    description="差评处理 - 分析差评情感、生成回复、触发挽留旅程",
    input_schema={
        "properties": {
            "review_text": {"type": "string", "description": "差评内容"},
            "rating": {"type": "integer", "description": "评分（1-5）"},
            "customer_id": {"type": "string", "description": "客户ID"},
        },
        "required": ["review_text", "rating"],
    },
))

_register("member_insight__monitor_service_quality", _entry(
    agent_id="member_insight",
    action="monitor_service_quality",
    description="服务质量监控 - 统计评分分布和差评率",
    input_schema={
        "properties": {
            "feedbacks": {
                "type": "array",
                "description": "反馈列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "rating": {"type": "integer", "description": "评分（1-5）"},
                    },
                },
            },
        },
        "required": ["feedbacks"],
    },
))

_register("member_insight__handle_complaint", _entry(
    agent_id="member_insight",
    action="handle_complaint",
    description="投诉处理 - 按投诉类型分配优先级和处理人",
    input_schema={
        "properties": {
            "type": {
                "type": "string",
                "description": "投诉类型",
                "enum": ["food_quality", "service", "hygiene", "other"],
            },
        },
        "required": ["type"],
    },
))

_register("member_insight__collect_feedback", _entry(
    agent_id="member_insight",
    action="collect_feedback",
    description="收集反馈 - 记录顾客反馈信息",
    input_schema={
        "properties": {
            "feedback": {
                "type": "object",
                "description": "反馈数据",
                "properties": {
                    "rating": {"type": "integer", "description": "评分"},
                    "category": {"type": "string", "description": "分类"},
                    "comment": {"type": "string", "description": "评论"},
                },
            },
        },
        "required": ["feedback"],
    },
))

# ---------------------------------------------------------------------------
# #5 inventory_alert (9 actions)
# ---------------------------------------------------------------------------

_register("inventory_alert__monitor_inventory", _entry(
    agent_id="inventory_alert",
    action="monitor_inventory",
    description="实时库存监控 - 监控所有品项库存状态（正常/偏低/严重不足/缺货）",
    input_schema={
        "properties": {
            "items": {
                "type": "array",
                "description": "库存品项列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "current_qty": {"type": "number", "description": "当前库存量"},
                        "min_qty": {"type": "number", "description": "最低库存量"},
                    },
                },
            },
        },
        "required": ["items"],
    },
))

_register("inventory_alert__predict_consumption", _entry(
    agent_id="inventory_alert",
    action="predict_consumption",
    description="消耗预测 - 4种算法自动选择最优预测未来消耗量",
    input_schema={
        "properties": {
            "daily_usage": {
                "type": "array",
                "description": "每日消耗历史数据（至少3天）",
                "items": {"type": "number"},
            },
            "days_ahead": {"type": "integer", "description": "预测天数，默认7", "default": 7},
            "current_stock": {"type": "number", "description": "当前库存量", "default": 0},
        },
        "required": ["daily_usage"],
    },
))

_register("inventory_alert__generate_restock_alerts", _entry(
    agent_id="inventory_alert",
    action="generate_restock_alerts",
    description="生成补货告警 - 按紧急程度生成分级补货告警",
    input_schema={
        "properties": {
            "items": {
                "type": "array",
                "description": "库存品项列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "current_qty": {"type": "number"},
                        "min_qty": {"type": "number"},
                        "daily_usage": {"type": "number", "description": "日均消耗"},
                    },
                },
            },
        },
        "required": ["items"],
    },
))

_register("inventory_alert__check_expiration", _entry(
    agent_id="inventory_alert",
    action="check_expiration",
    description="保质期预警 - 检查食材保质期状态",
    input_schema={
        "properties": {
            "items": {
                "type": "array",
                "description": "食材列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "remaining_hours": {"type": "number", "description": "剩余保质时间（小时）"},
                    },
                },
            },
        },
        "required": ["items"],
    },
))

_register("inventory_alert__optimize_stock_levels", _entry(
    agent_id="inventory_alert",
    action="optimize_stock_levels",
    description="库存水位优化 - 基于历史数据优化安全库存/最低/最高三个水位线",
    input_schema={
        "properties": {
            "daily_usage": {
                "type": "array",
                "description": "每日消耗历史数据（至少7天）",
                "items": {"type": "number"},
            },
            "lead_days": {"type": "integer", "description": "采购提前期（天），默认3", "default": 3},
        },
        "required": ["daily_usage"],
    },
))

_register("inventory_alert__compare_supplier_prices", _entry(
    agent_id="inventory_alert",
    action="compare_supplier_prices",
    description="供应商比价 - 比较多个供应商的报价并推荐最优选择",
    input_schema={
        "properties": {
            "quotes": {
                "type": "array",
                "description": "供应商报价列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "supplier": {"type": "string", "description": "供应商名称"},
                        "price_fen": {"type": "integer", "description": "报价（分）"},
                        "quality_score": {"type": "number", "description": "质量评分"},
                    },
                },
            },
        },
        "required": ["quotes"],
    },
))

_register("inventory_alert__evaluate_supplier", _entry(
    agent_id="inventory_alert",
    action="evaluate_supplier",
    description="供应商评级 - 综合评估供应商（准时率/质量/价格稳定性/响应时间）",
    input_schema={
        "properties": {
            "on_time_rate": {"type": "number", "description": "准时交付率（0-1）"},
            "quality_rate": {"type": "number", "description": "质量合格率（0-1）"},
            "price_stability": {"type": "number", "description": "价格稳定性（0-1）"},
            "avg_response_hours": {"type": "number", "description": "平均响应时间（小时）", "default": 24},
        },
        "required": ["on_time_rate", "quality_rate", "price_stability"],
    },
))

_register("inventory_alert__scan_contract_risks", _entry(
    agent_id="inventory_alert",
    action="scan_contract_risks",
    description="合同风险扫描 - 扫描供应商合同的到期和单一来源风险",
    input_schema={
        "properties": {
            "contracts": {
                "type": "array",
                "description": "合同列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "supplier": {"type": "string"},
                        "remaining_days": {"type": "integer", "description": "剩余天数"},
                        "single_source": {"type": "boolean", "description": "是否单一来源"},
                    },
                },
            },
        },
        "required": ["contracts"],
    },
))

_register("inventory_alert__analyze_waste", _entry(
    agent_id="inventory_alert",
    action="analyze_waste",
    description="损耗分析 - 分析食材损耗事件和原因",
    input_schema={
        "properties": {
            "events": {
                "type": "array",
                "description": "损耗事件列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "cause": {"type": "string", "description": "原因"},
                        "cost_fen": {"type": "integer", "description": "损耗金额（分）"},
                    },
                },
            },
        },
        "required": ["events"],
    },
))

# ---------------------------------------------------------------------------
# #6 finance_audit (7 actions)
# ---------------------------------------------------------------------------

_register("finance_audit__get_financial_report", _entry(
    agent_id="finance_audit",
    action="get_financial_report",
    description="财务报表 - 生成财务报表",
    input_schema={
        "properties": {
            "report_type": {
                "type": "string",
                "description": "报表类型",
                "default": "period_summary",
            },
        },
    },
))

_register("finance_audit__detect_revenue_anomaly", _entry(
    agent_id="finance_audit",
    action="detect_revenue_anomaly",
    description="营收异常检测 - 使用Z-score检测营收是否偏离历史基线",
    input_schema={
        "properties": {
            "actual_revenue_fen": {"type": "integer", "description": "今日实际营收（分）"},
            "history_daily_fen": {
                "type": "array",
                "description": "历史每日营收数据（分）",
                "items": {"type": "integer"},
            },
        },
        "required": ["actual_revenue_fen", "history_daily_fen"],
    },
))

_register("finance_audit__snapshot_kpi", _entry(
    agent_id="finance_audit",
    action="snapshot_kpi",
    description="KPI健康度快照 - 查看各KPI指标的达成率",
    input_schema={
        "properties": {
            "kpis": {
                "type": "object",
                "description": "KPI实际值字典，如 {revenue: 80000, orders: 120}",
            },
            "targets": {
                "type": "object",
                "description": "KPI目标值字典，如 {revenue: 100000, orders: 150}",
            },
        },
        "required": ["kpis", "targets"],
    },
))

_register("finance_audit__forecast_orders", _entry(
    agent_id="finance_audit",
    action="forecast_orders",
    description="订单量预测 - 基于周期性和趋势预测未来N天订单量",
    input_schema={
        "properties": {
            "daily_orders": {
                "type": "array",
                "description": "每日订单数历史数据（至少7天）",
                "items": {"type": "integer"},
            },
            "days_ahead": {"type": "integer", "description": "预测天数，默认7", "default": 7},
        },
        "required": ["daily_orders"],
    },
))

_register("finance_audit__generate_biz_insight", _entry(
    agent_id="finance_audit",
    action="generate_biz_insight",
    description="经营洞察 - 基于经营指标自动生成经营洞察建议",
    input_schema={
        "properties": {
            "metrics": {
                "type": "object",
                "description": "经营指标，如 {cost_rate_pct, revenue_change_pct}",
                "properties": {
                    "cost_rate_pct": {"type": "number", "description": "成本率百分比"},
                    "revenue_change_pct": {"type": "number", "description": "营收变化百分比"},
                },
            },
        },
        "required": ["metrics"],
    },
))

_register("finance_audit__match_scenario", _entry(
    agent_id="finance_audit",
    action="match_scenario",
    description="场景识别 - 识别当前经营场景（成本超标/损耗异常/节假日/营收下滑等）",
    input_schema={
        "properties": {
            "cost_rate_pct": {"type": "number", "description": "成本率百分比", "default": 30},
            "waste_rate_pct": {"type": "number", "description": "损耗率百分比", "default": 2},
            "is_holiday": {"type": "boolean", "description": "是否节假日", "default": False},
            "is_weekend": {"type": "boolean", "description": "是否周末", "default": False},
            "revenue_change_pct": {"type": "number", "description": "营收变化百分比", "default": 0},
            "has_new_dish": {"type": "boolean", "description": "是否有新菜上市", "default": False},
        },
    },
))

_register("finance_audit__analyze_order_trend", _entry(
    agent_id="finance_audit",
    action="analyze_order_trend",
    description="订单趋势分析 - 分析订单量趋势和客单价",
    input_schema={
        "properties": {
            "daily_orders": {
                "type": "array",
                "description": "每日订单数（至少2天）",
                "items": {"type": "integer"},
            },
            "daily_revenue_fen": {
                "type": "array",
                "description": "每日营收（分）",
                "items": {"type": "integer"},
            },
        },
        "required": ["daily_orders"],
    },
))

# ---------------------------------------------------------------------------
# #7 store_inspect (7 actions)
# ---------------------------------------------------------------------------

_register("store_inspect__health_check", _entry(
    agent_id="store_inspect",
    action="health_check",
    description="门店健康检查 - 三域（软件/硬件/网络）健康度评分",
    input_schema={
        "properties": {
            "devices": {
                "type": "object",
                "description": "设备状态字典",
                "properties": {
                    "mac_station_running": {"type": "boolean"},
                    "sync_engine_running": {"type": "boolean"},
                    "coreml_running": {"type": "boolean"},
                    "printer_ok": {"type": "boolean"},
                    "scale_ok": {"type": "boolean"},
                    "cash_box_ok": {"type": "boolean"},
                    "kds_ok": {"type": "boolean"},
                    "internet_ok": {"type": "boolean"},
                    "tailscale_ok": {"type": "boolean"},
                    "lan_ok": {"type": "boolean"},
                },
            },
        },
        "required": ["devices"],
    },
))

_register("store_inspect__diagnose_fault", _entry(
    agent_id="store_inspect",
    action="diagnose_fault",
    description="故障诊断 - 根据症状和错误日志自动诊断故障根因",
    input_schema={
        "properties": {
            "symptom": {"type": "string", "description": "故障症状描述"},
            "error_log": {"type": "string", "description": "错误日志内容"},
        },
        "required": ["symptom"],
    },
))

_register("store_inspect__suggest_runbook", _entry(
    agent_id="store_inspect",
    action="suggest_runbook",
    description="Runbook建议 - 根据故障类型提供标准化修复步骤",
    input_schema={
        "properties": {
            "fault_id": {
                "type": "string",
                "description": "故障类型ID",
                "enum": ["printer_jam", "network_down", "pos_crash", "db_connection", "scale_error"],
            },
        },
        "required": ["fault_id"],
    },
))

_register("store_inspect__predict_maintenance", _entry(
    agent_id="store_inspect",
    action="predict_maintenance",
    description="预测性维护 - 根据设备使用时间预测维护需求",
    input_schema={
        "properties": {
            "devices": {
                "type": "array",
                "description": "设备列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "description": "设备类型",
                            "enum": ["printer", "scale", "kds_tablet", "router", "ups"],
                        },
                        "last_maintained_days_ago": {"type": "integer", "description": "上次维护距今天数"},
                    },
                },
            },
        },
        "required": ["devices"],
    },
))

_register("store_inspect__security_advice", _entry(
    agent_id="store_inspect",
    action="security_advice",
    description="安全建议 - 检查安全风险（弱密码/未授权设备/固件/VPN）",
    input_schema={
        "properties": {
            "weak_passwords": {"type": "boolean", "description": "是否有弱密码", "default": False},
            "unauthorized_devices": {"type": "boolean", "description": "是否有未授权设备", "default": False},
            "firmware_outdated": {"type": "boolean", "description": "固件是否过期", "default": False},
            "vpn_enabled": {"type": "boolean", "description": "VPN是否启用", "default": True},
        },
    },
))

_register("store_inspect__food_safety_status", _entry(
    agent_id="store_inspect",
    action="food_safety_status",
    description="食安合规状态 - 查看食品安全检查合规率和违规详情",
    input_schema={
        "properties": {
            "violations": {
                "type": "array",
                "description": "违规记录列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "description": "违规类型"},
                        "resolved": {"type": "boolean", "description": "是否已解决"},
                    },
                },
            },
            "total_inspections": {"type": "integer", "description": "总检查次数"},
        },
        "required": ["violations", "total_inspections"],
    },
))

_register("store_inspect__store_dashboard", _entry(
    agent_id="store_inspect",
    action="store_dashboard",
    description="门店健康总览 - 获取门店软件/硬件/网络综合评分",
    input_schema={
        "properties": {
            "sw": {"type": "integer", "description": "软件评分（0-100）", "default": 100},
            "hw": {"type": "integer", "description": "硬件评分（0-100）", "default": 100},
            "net": {"type": "integer", "description": "网络评分（0-100）", "default": 100},
        },
    },
))

# ---------------------------------------------------------------------------
# #8 smart_service (9 actions)
# ---------------------------------------------------------------------------

_register("smart_service__analyze_feedback", _entry(
    agent_id="smart_service",
    action="analyze_feedback",
    description="反馈分析 - 统计反馈的正面/负面比例",
    input_schema={
        "properties": {
            "feedbacks": {
                "type": "array",
                "description": "反馈列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "rating": {"type": "integer", "description": "评分（1-5）"},
                        "comment": {"type": "string"},
                    },
                },
            },
        },
        "required": ["feedbacks"],
    },
))

_register("smart_service__handle_complaint", _entry(
    agent_id="smart_service",
    action="handle_complaint",
    description="投诉处理闭环 - 按投诉类型分配优先级、解决方案和补偿",
    input_schema={
        "properties": {
            "type": {
                "type": "string",
                "description": "投诉类型",
                "enum": ["food_quality", "service_attitude", "wait_time", "hygiene", "billing", "other"],
            },
            "description": {"type": "string", "description": "投诉描述"},
            "customer_id": {"type": "string", "description": "客户ID"},
        },
        "required": ["type"],
    },
))

_register("smart_service__generate_improvements", _entry(
    agent_id="smart_service",
    action="generate_improvements",
    description="改进建议 - 基于高频问题生成服务改进建议",
    input_schema={
        "properties": {
            "top_issues": {
                "type": "array",
                "description": "高频问题列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "description": "问题类型"},
                        "count": {"type": "integer", "description": "发生次数"},
                    },
                },
            },
        },
        "required": ["top_issues"],
    },
))

_register("smart_service__assess_training_needs", _entry(
    agent_id="smart_service",
    action="assess_training_needs",
    description="培训需求评估 - 评估员工技能差距和培训紧急度",
    input_schema={
        "properties": {
            "employees": {
                "type": "array",
                "description": "员工列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "role": {"type": "string", "enum": ["waiter", "chef", "cashier", "manager"]},
                        "skills": {"type": "array", "items": {"type": "string"}, "description": "已有技能"},
                        "performance_score": {"type": "integer", "description": "绩效分（0-100）"},
                    },
                },
            },
        },
        "required": ["employees"],
    },
))

_register("smart_service__generate_training_plan", _entry(
    agent_id="smart_service",
    action="generate_training_plan",
    description="培训计划生成 - 根据技能差距生成周度培训计划",
    input_schema={
        "properties": {
            "role": {"type": "string", "description": "岗位", "enum": ["waiter", "chef", "cashier", "manager"]},
            "skill_gaps": {
                "type": "array",
                "description": "技能差距列表",
                "items": {"type": "string"},
            },
        },
        "required": ["role", "skill_gaps"],
    },
))

_register("smart_service__track_training_progress", _entry(
    agent_id="smart_service",
    action="track_training_progress",
    description="培训进度追踪 - 查看培训完成率",
    input_schema={
        "properties": {
            "records": {
                "type": "array",
                "description": "培训记录",
                "items": {
                    "type": "object",
                    "properties": {
                        "course": {"type": "string"},
                        "completed": {"type": "boolean"},
                    },
                },
            },
        },
        "required": ["records"],
    },
))

_register("smart_service__evaluate_effectiveness", _entry(
    agent_id="smart_service",
    action="evaluate_effectiveness",
    description="培训效果评估 - 比较培训前后评分计算提升效果",
    input_schema={
        "properties": {
            "pre_scores": {
                "type": "array",
                "description": "培训前评分",
                "items": {"type": "number"},
            },
            "post_scores": {
                "type": "array",
                "description": "培训后评分",
                "items": {"type": "number"},
            },
            "attendance_rate": {"type": "number", "description": "出勤率（0-100）"},
        },
        "required": ["pre_scores", "post_scores"],
    },
))

_register("smart_service__analyze_skill_gaps", _entry(
    agent_id="smart_service",
    action="analyze_skill_gaps",
    description="技能差距分析 - 评估岗位技能差距和潜在损失",
    input_schema={
        "properties": {
            "role": {"type": "string", "description": "岗位", "enum": ["waiter", "chef", "cashier", "manager"]},
            "skill_scores": {
                "type": "object",
                "description": "各技能评分，如 {服务礼仪: 80, 点菜推荐: 60}",
            },
        },
        "required": ["role", "skill_scores"],
    },
))

_register("smart_service__manage_certificates", _entry(
    agent_id="smart_service",
    action="manage_certificates",
    description="证书管理 - 检查员工证书过期和即将过期状态",
    input_schema={
        "properties": {
            "certificates": {
                "type": "array",
                "description": "证书列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "证书名称"},
                        "employee": {"type": "string", "description": "持证人"},
                        "remaining_days": {"type": "integer", "description": "剩余天数"},
                    },
                },
            },
        },
        "required": ["certificates"],
    },
))

# ---------------------------------------------------------------------------
# #9 private_ops (11 actions)
# ---------------------------------------------------------------------------

_register("private_ops__get_private_domain_dashboard", _entry(
    agent_id="private_ops",
    action="get_private_domain_dashboard",
    description="私域总览 - 查看会员总数、活跃率、流失风险、活跃旅程等概览",
    input_schema={
        "properties": {
            "total_members": {"type": "integer", "description": "总会员数"},
            "active_pct": {"type": "number", "description": "活跃率百分比"},
            "churn_risk_count": {"type": "integer", "description": "流失风险数"},
            "active_journeys": {"type": "integer", "description": "活跃旅程数"},
        },
        "required": ["total_members"],
    },
))

_register("private_ops__trigger_campaign", _entry(
    agent_id="private_ops",
    action="trigger_campaign",
    description="触发营销活动 - 触发指定类型的营销活动",
    input_schema={
        "properties": {
            "type": {"type": "string", "description": "活动类型"},
            "target_count": {"type": "integer", "description": "目标人数"},
        },
        "required": ["type"],
    },
))

_register("private_ops__advance_journey", _entry(
    agent_id="private_ops",
    action="advance_journey",
    description="推进旅程 - 将会员旅程推进到下一步",
    input_schema={
        "properties": {
            "journey_id": {"type": "string", "description": "旅程ID"},
            "current_step": {"type": "integer", "description": "当前步骤索引"},
        },
        "required": ["journey_id", "current_step"],
    },
))

_register("private_ops__optimize_shift", _entry(
    agent_id="private_ops",
    action="optimize_shift",
    description="排班优化 - 根据客流预测优化排班",
    input_schema={
        "properties": {
            "employees": {
                "type": "array",
                "description": "员工列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "role": {"type": "string"},
                    },
                },
            },
            "traffic_forecast": {
                "type": "array",
                "description": "各时段客流预测",
                "items": {"type": "number"},
            },
        },
        "required": ["employees"],
    },
))

_register("private_ops__score_performance", _entry(
    agent_id="private_ops",
    action="score_performance",
    description="员工绩效评分 - 加权多指标评分+红线处罚+提成计算",
    input_schema={
        "properties": {
            "role": {
                "type": "string",
                "description": "岗位",
                "enum": ["manager", "waiter", "chef", "cashier"],
            },
            "metrics": {
                "type": "object",
                "description": "绩效指标，不同岗位字段不同。如 waiter: {service_count, tips, complaints, upsell, attendance}",
            },
            "base_salary_fen": {"type": "integer", "description": "基本工资（分），默认500000", "default": 500000},
        },
        "required": ["role", "metrics"],
    },
))

_register("private_ops__analyze_labor_cost", _entry(
    agent_id="private_ops",
    action="analyze_labor_cost",
    description="人力成本分析 - 分析人力成本率、人均工资和预算偏差",
    input_schema={
        "properties": {
            "total_wage_fen": {"type": "integer", "description": "总工资（分）"},
            "revenue_fen": {"type": "integer", "description": "总营收（分）"},
            "staff_count": {"type": "integer", "description": "员工人数"},
            "target_rate": {"type": "number", "description": "目标人力成本率（0-1），默认0.25", "default": 0.25},
        },
        "required": ["total_wage_fen", "revenue_fen", "staff_count"],
    },
))

_register("private_ops__warn_attendance", _entry(
    agent_id="private_ops",
    action="warn_attendance",
    description="出勤异常预警 - 检测迟到、旷工、早退等出勤异常",
    input_schema={
        "properties": {
            "records": {
                "type": "array",
                "description": "考勤记录列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "员工姓名"},
                        "late_count": {"type": "integer", "description": "迟到次数"},
                        "absent_count": {"type": "integer", "description": "旷工次数"},
                        "early_leave_count": {"type": "integer", "description": "早退次数"},
                    },
                },
            },
        },
        "required": ["records"],
    },
))

_register("private_ops__create_reservation", _entry(
    agent_id="private_ops",
    action="create_reservation",
    description="创建预订 - 新建餐位预订",
    input_schema={
        "properties": {
            "customer_name": {"type": "string", "description": "顾客姓名"},
            "guest_count": {"type": "integer", "description": "就餐人数"},
            "date": {"type": "string", "description": "预订日期"},
        },
        "required": ["customer_name", "guest_count", "date"],
    },
))

_register("private_ops__manage_banquet", _entry(
    agent_id="private_ops",
    action="manage_banquet",
    description="宴会管理 - 管理宴会流转状态（lead->confirmed->executing->review）",
    input_schema={
        "properties": {
            "event_name": {"type": "string", "description": "宴会名称"},
            "stage": {
                "type": "string",
                "description": "当前阶段",
                "enum": ["lead", "confirmed", "executing", "review"],
            },
        },
        "required": ["event_name", "stage"],
    },
))

_register("private_ops__generate_beo", _entry(
    agent_id="private_ops",
    action="generate_beo",
    description="生成宴会执行单(BEO) - 包含菜单、时间线、特殊要求",
    input_schema={
        "properties": {
            "event_name": {"type": "string", "description": "宴会名称"},
            "guest_count": {"type": "integer", "description": "宾客人数"},
            "event_date": {"type": "string", "description": "活动日期"},
            "menu_items": {
                "type": "array",
                "description": "菜单",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "price_fen": {"type": "integer"},
                        "quantity": {"type": "integer"},
                    },
                },
            },
            "special_requests": {
                "type": "array",
                "description": "特殊要求",
                "items": {"type": "string"},
            },
        },
        "required": ["event_name", "guest_count", "event_date"],
    },
))

_register("private_ops__allocate_seating", _entry(
    agent_id="private_ops",
    action="allocate_seating",
    description="智能座位分配 - 根据人数和偏好推荐最佳桌台",
    input_schema={
        "properties": {
            "guest_count": {"type": "integer", "description": "就餐人数"},
            "preferences": {
                "type": "array",
                "description": "偏好列表，如 ['包间', '靠窗']",
                "items": {"type": "string"},
            },
            "available_tables": {
                "type": "array",
                "description": "可用桌台",
                "items": {
                    "type": "object",
                    "properties": {
                        "table_no": {"type": "string"},
                        "area": {"type": "string"},
                        "type": {"type": "string"},
                        "seats": {"type": "integer"},
                    },
                },
            },
        },
        "required": ["guest_count", "available_tables"],
    },
))

# ---------------------------------------------------------------------------
# Master Agent (3 actions)
# ---------------------------------------------------------------------------

_register("master__dispatch", _entry(
    agent_id="master",
    action="dispatch",
    description="Master调度 - 路由请求到指定 Skill Agent 执行",
    input_schema={
        "properties": {
            "agent_id": {"type": "string", "description": "目标Agent ID"},
            "action": {"type": "string", "description": "动作名称"},
            "params": {"type": "object", "description": "执行参数"},
        },
        "required": ["agent_id", "action", "params"],
    },
))

_register("master__route_intent", _entry(
    agent_id="master",
    action="route_intent",
    description="意图路由 - 基于意图前缀自动路由到合适的 Agent",
    input_schema={
        "properties": {
            "intent": {"type": "string", "description": "意图标识，如 discount_check, menu_optimize"},
            "params": {"type": "object", "description": "执行参数"},
        },
        "required": ["intent", "params"],
    },
))

_register("master__multi_agent_execute", _entry(
    agent_id="master",
    action="multi_agent_execute",
    description="多Agent并行执行 - 协调多个Agent同时执行任务",
    input_schema={
        "properties": {
            "tasks": {
                "type": "array",
                "description": "任务列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string"},
                        "action": {"type": "string"},
                        "params": {"type": "object"},
                    },
                    "required": ["agent_id", "action"],
                },
            },
        },
        "required": ["tasks"],
    },
))

# ---------------------------------------------------------------------------
# Planner Agent (2 actions)
# ---------------------------------------------------------------------------

_register("planner__generate_daily_plan", _entry(
    agent_id="planner",
    action="generate_daily_plan",
    description="生成日计划 - 每日自动生成5维经营计划（排菜/采购/排班/营销/风险）",
    input_schema={
        "properties": {
            "date": {"type": "string", "description": "日期，默认today", "default": "today"},
        },
    },
))

_register("planner__approve_plan", _entry(
    agent_id="planner",
    action="approve_plan",
    description="审批日计划 - 批准或拒绝日计划中的项目",
    input_schema={
        "properties": {
            "plan": {"type": "object", "description": "计划对象（来自 generate_daily_plan 的返回值）"},
            "approved_items": {
                "type": "array",
                "description": "批准的项目索引列表",
                "items": {"type": "integer"},
            },
            "rejected_items": {
                "type": "array",
                "description": "拒绝的项目索引列表",
                "items": {"type": "integer"},
            },
            "notes": {"type": "string", "description": "审批备注"},
        },
        "required": ["plan", "approved_items", "rejected_items"],
    },
))

# ---------------------------------------------------------------------------
# EventBus (5 actions)
# ---------------------------------------------------------------------------

_register("event_bus__publish_event", _entry(
    agent_id="event_bus",
    action="publish_event",
    description="发布事件 - 发布事件到EventBus触发处理器",
    input_schema={
        "properties": {
            "event_type": {"type": "string", "description": "事件类型"},
            "source_agent": {"type": "string", "description": "来源Agent"},
            "store_id": {"type": "string", "description": "门店ID"},
            "data": {"type": "object", "description": "事件数据"},
        },
        "required": ["event_type", "source_agent", "store_id"],
    },
))

_register("event_bus__get_event_chain", _entry(
    agent_id="event_bus",
    action="get_event_chain",
    description="事件链路追踪 - 获取同一关联ID的所有事件链路",
    input_schema={
        "properties": {
            "correlation_id": {"type": "string", "description": "事件关联ID"},
        },
        "required": ["correlation_id"],
    },
))

_register("event_bus__get_stream", _entry(
    agent_id="event_bus",
    action="get_stream",
    description="查询事件流 - 获取某类事件的最近N条",
    input_schema={
        "properties": {
            "event_type": {"type": "string", "description": "事件类型"},
            "limit": {"type": "integer", "description": "最大返回条数，默认100", "default": 100},
        },
        "required": ["event_type"],
    },
))

_register("event_bus__register_handler", _entry(
    agent_id="event_bus",
    action="register_handler",
    description="注册事件处理器 - 为事件类型注册处理器",
    input_schema={
        "properties": {
            "event_type": {"type": "string", "description": "事件类型"},
            "agent_id": {"type": "string", "description": "处理器所属Agent"},
        },
        "required": ["event_type", "agent_id"],
    },
))

_register("event_bus__get_all_event_types", _entry(
    agent_id="event_bus",
    action="get_all_event_types",
    description="获取所有事件类型 - 列出所有已注册的事件类型",
    input_schema={
        "properties": {},
    },
))


# ===========================================================================
# TX-BRAIN AGENT TOOLS — 直接调用 tx-brain agents（不经过 tx-agent 体系）
# ===========================================================================
# 这些工具对应 services/tx-brain/src/agents/ 下的新版 Agent 实现。
# 命名规则：{agent_name}__{method_name}
# ===========================================================================

# ---------------------------------------------------------------------------
# tx-brain: discount_guardian (1 action)
# ---------------------------------------------------------------------------

_register("discount_guardian__analyze", _entry(
    agent_id="discount_guardian",
    action="analyze",
    description="折扣守护分析 - 分析折扣事件是否合规，校验毛利底线/权限/行为模式三条硬约束",
    input_schema={
        "properties": {
            "event": {
                "type": "object",
                "description": "折扣事件，包含 operator_id/operator_role/dish_name/original_price_fen/discount_type/discount_rate/table_no/order_id/store_id/margin_rate",
                "properties": {
                    "operator_id": {"type": "string", "description": "操作员ID"},
                    "operator_role": {"type": "string", "description": "操作员角色（employee/manager/gm）"},
                    "dish_name": {"type": "string", "description": "菜品名称"},
                    "original_price_fen": {"type": "integer", "description": "原价（分）"},
                    "discount_type": {"type": "string", "description": "折扣类型"},
                    "discount_rate": {"type": "number", "description": "折扣率（0.0-1.0，如0.9=九折）"},
                    "table_no": {"type": "string", "description": "桌号"},
                    "order_id": {"type": "string", "description": "订单ID"},
                    "store_id": {"type": "string", "description": "门店ID"},
                    "margin_rate": {"type": "number", "description": "菜品毛利率（可选）"},
                },
                "required": ["operator_id", "operator_role", "discount_rate"],
            },
            "history": {
                "type": "array",
                "description": "近30条同操作员的折扣记录",
                "items": {"type": "object"},
            },
        },
        "required": ["event", "history"],
    },
))

# ---------------------------------------------------------------------------
# tx-brain: finance_auditor (1 action)
# ---------------------------------------------------------------------------

_register("finance_auditor__analyze", _entry(
    agent_id="finance_auditor",
    action="analyze",
    description="财务稽核分析 - 检测门店财务异常，输出风险评级与审计建议（校验毛利/作废率/现金差异）",
    input_schema={
        "properties": {
            "payload": {
                "type": "object",
                "description": "门店财务数据快照",
                "properties": {
                    "tenant_id": {"type": "string", "description": "租户ID"},
                    "store_id": {"type": "string", "description": "门店ID"},
                    "date": {"type": "string", "description": "日期（YYYY-MM-DD）"},
                    "revenue_fen": {"type": "integer", "description": "当日营收（分）"},
                    "cost_fen": {"type": "integer", "description": "当日成本（分）"},
                    "discount_total_fen": {"type": "integer", "description": "当日折扣合计（分）"},
                    "void_count": {"type": "integer", "description": "当日作废单数"},
                    "void_amount_fen": {"type": "integer", "description": "当日作废金额（分）"},
                    "cash_actual_fen": {"type": "integer", "description": "实际现金盘点（分）"},
                    "cash_expected_fen": {"type": "integer", "description": "系统预期现金（分）"},
                    "high_discount_orders": {"type": "array", "description": "高折扣订单列表", "items": {"type": "object"}},
                },
                "required": ["tenant_id", "store_id", "date", "revenue_fen", "cost_fen"],
            },
        },
        "required": ["payload"],
    },
))

# ---------------------------------------------------------------------------
# tx-brain: inventory_sentinel (1 action)
# ---------------------------------------------------------------------------

_register("inventory_sentinel__analyze", _entry(
    agent_id="inventory_sentinel",
    action="analyze",
    description="库存预警分析 - 预测食材缺货风险，生成采购建议（食安合规硬约束：临期食材强制预警）",
    input_schema={
        "properties": {
            "store_id": {"type": "string", "description": "门店ID"},
            "tenant_id": {"type": "string", "description": "租户ID"},
            "inventory": {
                "type": "array",
                "description": "当前库存列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "ingredient_name": {"type": "string"},
                        "current_qty": {"type": "number"},
                        "unit": {"type": "string"},
                        "min_qty": {"type": "number"},
                        "expiry_date": {"type": "string", "description": "效期（ISO格式）"},
                        "unit_cost_fen": {"type": "integer"},
                    },
                },
            },
            "sales_history": {
                "type": "array",
                "description": "近7天每日消耗量",
                "items": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string"},
                        "ingredient_name": {"type": "string"},
                        "consumed_qty": {"type": "number"},
                    },
                },
            },
        },
        "required": ["store_id", "tenant_id", "inventory", "sales_history"],
    },
))

# ---------------------------------------------------------------------------
# tx-brain: member_insight (1 action)
# ---------------------------------------------------------------------------

_register("member_insight__analyze_member", _entry(
    agent_id="member_insight",
    action="analyze",
    description="会员洞察分析 - 分析会员消费行为，生成个性化洞察、推荐菜品和回访预测",
    input_schema={
        "properties": {
            "member": {
                "type": "object",
                "description": "会员信息",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "phone_masked": {"type": "string"},
                    "level": {"type": "string"},
                    "total_spend_fen": {"type": "integer", "description": "累计消费（分）"},
                    "visit_count": {"type": "integer"},
                    "last_visit_date": {"type": "string"},
                    "points": {"type": "integer"},
                },
                "required": ["id"],
            },
            "orders": {
                "type": "array",
                "description": "近12个月订单列表（含 items 菜品明细）",
                "items": {"type": "object"},
            },
        },
        "required": ["member", "orders"],
    },
))

# ---------------------------------------------------------------------------
# tx-brain: patrol_inspector (3 actions)
# ---------------------------------------------------------------------------

_register("patrol_inspector__analyze", _entry(
    agent_id="patrol_inspector",
    action="analyze",
    description="巡店质检分析 - 分析门店巡检数据，识别违规项，生成整改建议（食安/消防违规强制标critical）",
    input_schema={
        "properties": {
            "payload": {
                "type": "object",
                "description": "巡店数据",
                "properties": {
                    "tenant_id": {"type": "string"},
                    "store_id": {"type": "string"},
                    "patrol_date": {"type": "string", "description": "巡检日期（YYYY-MM-DD）"},
                    "inspector_name": {"type": "string"},
                    "checklist_items": {
                        "type": "array",
                        "description": "检查清单列表，每项含 category/item_name/result(pass/fail/na)/score/notes",
                        "items": {"type": "object"},
                    },
                    "overall_score": {"type": "number", "description": "本次综合评分（0-100）"},
                    "previous_score": {"type": "number", "description": "上次综合评分"},
                },
                "required": ["tenant_id", "store_id", "patrol_date", "checklist_items", "overall_score"],
            },
        },
        "required": ["payload"],
    },
))

_register("patrol_inspector__analyze_from_mv", _entry(
    agent_id="patrol_inspector",
    action="analyze_from_mv",
    description="巡店质检增强分析 - 从 mv_public_opinion 读取近4周舆情上下文，丰富巡店分析背景",
    input_schema={
        "properties": {
            "payload": {
                "type": "object",
                "description": "巡店数据（同 patrol_inspector__analyze 的 payload 结构）",
            },
        },
        "required": ["payload"],
    },
))

_register("patrol_inspector__get_opinion_context", _entry(
    agent_id="patrol_inspector",
    action="get_opinion_context",
    description="获取舆情上下文 - 从 mv_public_opinion 读取门店近4周舆情摘要（负面数/最差平台/平均情感分）",
    input_schema={
        "properties": {
            "tenant_id": {"type": "string", "description": "租户ID"},
            "store_id": {"type": "string", "description": "门店ID"},
        },
        "required": ["tenant_id", "store_id"],
    },
))

# ---------------------------------------------------------------------------
# tx-brain: menu_optimizer (1 action)
# ---------------------------------------------------------------------------

_register("menu_optimizer__optimize", _entry(
    agent_id="menu_optimizer",
    action="optimize",
    description="智能排菜优化 - 根据库存/销量/利润推荐最优排菜方案（临期食材消耗/高毛利推广/套餐建议）",
    input_schema={
        "properties": {
            "payload": {
                "type": "object",
                "description": "排菜请求数据",
                "properties": {
                    "tenant_id": {"type": "string"},
                    "store_id": {"type": "string"},
                    "date": {"type": "string", "description": "日期（YYYY-MM-DD）"},
                    "meal_period": {"type": "string", "description": "餐段（breakfast/lunch/dinner）"},
                    "current_inventory": {
                        "type": "array",
                        "description": "当前库存列表，含 ingredient_id/name/quantity/unit/expiry_days/cost_per_unit_fen",
                        "items": {"type": "object"},
                    },
                    "dish_performance": {
                        "type": "array",
                        "description": "菜品表现数据，含 dish_id/dish_name/category/avg_daily_orders/margin_rate/prep_time_minutes/is_available",
                        "items": {"type": "object"},
                    },
                    "weather": {"type": "string", "description": "天气（可选）"},
                    "day_type": {"type": "string", "description": "日期类型（weekday/weekend/holiday）"},
                },
                "required": ["tenant_id", "store_id", "date", "meal_period"],
            },
        },
        "required": ["payload"],
    },
))

# ---------------------------------------------------------------------------
# tx-brain: crm_operator (2 actions)
# ---------------------------------------------------------------------------

_register("crm_operator__generate_campaign", _entry(
    agent_id="crm_operator",
    action="generate_campaign",
    description="私域运营活动生成 - 生成微信群/朋友圈/小程序推送文案和活动方案",
    input_schema={
        "properties": {
            "payload": {
                "type": "object",
                "description": "活动请求数据",
                "properties": {
                    "tenant_id": {"type": "string"},
                    "store_id": {"type": "string"},
                    "brand_name": {"type": "string", "description": "品牌名称"},
                    "campaign_type": {
                        "type": "string",
                        "description": "活动类型",
                        "enum": ["retention", "reactivation", "upsell", "event", "holiday"],
                    },
                    "target_segment": {
                        "type": "string",
                        "description": "目标用户群",
                        "enum": ["vip", "regular", "at_risk", "new"],
                    },
                    "target_count": {"type": "integer", "description": "目标用户数量"},
                    "budget_fen": {"type": "integer", "description": "活动预算（分）"},
                    "key_dishes": {"type": "array", "items": {"type": "string"}, "description": "重点推广菜品名列表"},
                    "discount_limit": {"type": "number", "description": "最大折扣率（如0.2=8折）"},
                    "special_occasion": {"type": "string", "description": "特殊场合（如'母亲节'）"},
                },
                "required": ["tenant_id", "brand_name", "campaign_type"],
            },
        },
        "required": ["payload"],
    },
))

_register("crm_operator__analyze_from_mv", _entry(
    agent_id="crm_operator",
    action="analyze_from_mv",
    description="会员CLV快速分析 - 从 mv_member_clv 物化视图快速读取会员生命周期价值数据（<5ms）",
    input_schema={
        "properties": {
            "tenant_id": {"type": "string", "description": "租户ID"},
            "store_id": {"type": "string", "description": "门店ID（可选，不传则取租户级别数据）"},
        },
        "required": ["tenant_id"],
    },
))

# ---------------------------------------------------------------------------
# tx-brain: customer_service (2 actions)
# ---------------------------------------------------------------------------

_register("customer_service__handle", _entry(
    agent_id="customer_service",
    action="handle",
    description="智能客服处理 - 处理顾客投诉/询问/反馈，生成建议回复及处置动作（VIP投诉/食安关键词强制升级）",
    input_schema={
        "properties": {
            "payload": {
                "type": "object",
                "description": "客服请求数据",
                "properties": {
                    "tenant_id": {"type": "string"},
                    "store_id": {"type": "string"},
                    "customer_id": {"type": "string", "description": "顾客ID（可选）"},
                    "channel": {
                        "type": "string",
                        "description": "渠道",
                        "enum": ["wechat_mp", "miniapp", "review", "call", "in_store"],
                    },
                    "message": {"type": "string", "description": "顾客原文"},
                    "order_id": {"type": "string", "description": "关联订单ID（可选）"},
                    "message_type": {
                        "type": "string",
                        "description": "消息类型",
                        "enum": ["complaint", "inquiry", "feedback", "praise"],
                    },
                    "context_history": {
                        "type": "array",
                        "description": "历史对话 [{role, content}]",
                        "items": {"type": "object"},
                    },
                    "customer_tier": {
                        "type": "string",
                        "description": "顾客等级",
                        "enum": ["vip", "regular", "new"],
                    },
                },
                "required": ["tenant_id", "store_id", "message", "message_type"],
            },
        },
        "required": ["payload"],
    },
))

_register("customer_service__analyze_from_mv", _entry(
    agent_id="customer_service",
    action="analyze_from_mv",
    description="客服舆情快速分析 - 从 mv_public_opinion 物化视图快速读取门店舆情数据（<5ms）",
    input_schema={
        "properties": {
            "tenant_id": {"type": "string", "description": "租户ID"},
            "store_id": {"type": "string", "description": "门店ID（可选，不传则取租户级别数据）"},
        },
        "required": ["tenant_id"],
    },
))

# ---------------------------------------------------------------------------
# tx-brain: energy_monitor (2 actions)
# ---------------------------------------------------------------------------

_register("energy_monitor__analyze", _entry(
    agent_id="energy_monitor",
    action="analyze",
    description="能耗分析 - 分析门店能耗效率，识别异常消耗，给出节能建议（能耗/营收比分级：优秀≤5%/良好≤8%/警告≤12%/超标）",
    input_schema={
        "properties": {
            "payload": {
                "type": "object",
                "description": "能耗数据",
                "properties": {
                    "tenant_id": {"type": "string"},
                    "store_id": {"type": "string"},
                    "stat_date": {"type": "string", "description": "统计日期（YYYY-MM-DD）"},
                    "electricity_kwh": {"type": "number", "description": "当日用电量（kWh）"},
                    "gas_m3": {"type": "number", "description": "当日用气量（m³）"},
                    "water_ton": {"type": "number", "description": "当日用水量（吨）"},
                    "energy_cost_fen": {"type": "integer", "description": "能耗总费用（分）"},
                    "revenue_fen": {"type": "integer", "description": "当日营业收入（分）"},
                    "energy_revenue_ratio": {"type": "number", "description": "能耗/营收比"},
                    "anomaly_count": {"type": "integer", "description": "异常次数"},
                    "off_hours_anomalies": {
                        "type": "array",
                        "description": "非营业时段异常列表",
                        "items": {"type": "string"},
                    },
                },
                "required": ["tenant_id", "store_id", "stat_date"],
            },
        },
        "required": ["payload"],
    },
))

_register("energy_monitor__analyze_from_mv", _entry(
    agent_id="energy_monitor",
    action="analyze_from_mv",
    description="能耗快速分析 - 从 mv_energy_efficiency 物化视图快速读取最新能耗效率数据（<5ms）",
    input_schema={
        "properties": {
            "tenant_id": {"type": "string", "description": "租户ID"},
            "store_id": {"type": "string", "description": "门店ID（可选，不传则取最新门店数据）"},
        },
        "required": ["tenant_id"],
    },
))


# ---------------------------------------------------------------------------
# tx-pay: payment_nexus (7 actions) — 支付中枢 MCP 工具
# ---------------------------------------------------------------------------

_register("payment_nexus__query_status", _entry(
    agent_id="payment_nexus",
    action="query_status",
    description="查询支付状态 — 输入 payment_id，返回支付方式、金额、状态、第三方流水号",
    input_schema={
        "properties": {
            "payment_id": {"type": "string", "description": "支付单号（如 PAY20260411143000ABCD）"},
        },
        "required": ["payment_id"],
    },
))

_register("payment_nexus__daily_summary", _entry(
    agent_id="payment_nexus",
    action="daily_summary",
    description="门店当日支付汇总 — 按支付方式分组（微信/支付宝/现金/储值/挂账），含手续费计算",
    input_schema={
        "properties": {
            "store_id": {"type": "string", "description": "门店ID"},
            "summary_date": {"type": "string", "description": "日期 YYYY-MM-DD（默认今天）"},
        },
        "required": ["store_id"],
    },
))

_register("payment_nexus__list_channels", _entry(
    agent_id="payment_nexus",
    action="list_channels",
    description="列出已注册的支付渠道及其支持的支付方式 — 用于诊断渠道配置问题",
    input_schema={
        "properties": {},
    },
))

_register("payment_nexus__list_pending_agent_payments", _entry(
    agent_id="payment_nexus",
    action="list_pending_agent_payments",
    description="列出等待人类确认的 Agent 支付请求 — POS 端展示确认弹窗",
    input_schema={
        "properties": {
            "agent_id": {"type": "string", "description": "筛选特定 Agent（可选）"},
        },
    },
))

_register("payment_nexus__prepare", _entry(
    agent_id="payment_nexus",
    action="prepare",
    description="Agent 准备支付（不扣款）— 生成 prepared_id 推送到 POS 端等待收银员确认。单笔上限 1000 元",
    input_schema={
        "properties": {
            "tenant_id": {"type": "string", "description": "租户ID"},
            "store_id": {"type": "string", "description": "门店ID"},
            "order_id": {"type": "string", "description": "订单ID"},
            "amount_fen": {"type": "integer", "description": "金额（分）"},
            "method": {"type": "string", "description": "支付方式: wechat/alipay/cash/member_balance/credit_account"},
            "reason": {"type": "string", "description": "Agent 发起支付的理由"},
        },
        "required": ["tenant_id", "store_id", "order_id", "amount_fen", "method", "reason"],
    },
))

_register("payment_nexus__confirm_agent", _entry(
    agent_id="payment_nexus",
    action="confirm_agent",
    description="确认 Agent 准备的支付并执行扣款 — 必须由收银员通过生物识别/密码确认",
    input_schema={
        "properties": {
            "prepared_id": {"type": "string", "description": "Agent 准备的支付ID"},
            "operator_id": {"type": "string", "description": "操作员ID"},
            "auth_type": {"type": "string", "description": "认证方式: biometric/password/sms_code"},
        },
        "required": ["prepared_id", "operator_id", "auth_type"],
    },
))

_register("payment_nexus__refund", _entry(
    agent_id="payment_nexus",
    action="refund",
    description="发起退款 — 需管理员审批。支持全额退款和部分退款",
    input_schema={
        "properties": {
            "payment_id": {"type": "string", "description": "原支付单号"},
            "refund_amount_fen": {"type": "integer", "description": "退款金额（分）"},
            "reason": {"type": "string", "description": "退款原因"},
        },
        "required": ["payment_id", "refund_amount_fen", "reason"],
    },
))


# ---------------------------------------------------------------------------
# Convenience accessors
# ---------------------------------------------------------------------------

def get_tool_names() -> list[str]:
    """Return all registered tool names."""
    return list(TOOL_REGISTRY.keys())


def get_tool_entry(tool_name: str) -> ToolEntry | None:
    """Look up a tool entry by name."""
    return TOOL_REGISTRY.get(tool_name)


def get_skill_agent_tool_count() -> int:
    """Count only the 73 Skill Agent tools (excludes master/planner/event_bus)."""
    return sum(
        1 for entry in TOOL_REGISTRY.values()
        if entry["agent_id"] not in ("master", "planner", "event_bus")
    )


def get_tools_by_agent(agent_id: str) -> dict[str, ToolEntry]:
    """Return all tools belonging to a specific agent."""
    return {
        name: entry
        for name, entry in TOOL_REGISTRY.items()
        if entry["agent_id"] == agent_id
    }
