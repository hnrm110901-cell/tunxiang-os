"""事件→Agent 映射绑定表 + 初始化数据（从 DEFAULT_EVENT_HANDLERS 迁移）

将硬编码的事件→Agent 映射持久化到 DB 表，支持动态配置。
迁移后系统行为不变——所有原有映射作为 source='default' 初始行插入。

Revision ID: v232
Revises: v231
Create Date: 2026-04-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v232"
down_revision = "v231c"
branch_labels = None
depends_on = None

# 系统租户 UUID
_SYSTEM_TENANT = "00000000-0000-0000-0000-000000000000"

# RLS 标准条件
_RLS_COND = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def _add_rls(table: str, prefix: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY {prefix}_tenant ON {table}
        USING ({_RLS_COND})
        WITH CHECK ({_RLS_COND})
    """)


# ── 从 DEFAULT_EVENT_HANDLERS 转换的初始化数据 ──────────────────────────────
# 格式: (event_type, agent_id, action, priority, description)
# priority 按列表顺序递减（同事件内先出现的优先级更高）
_INITIAL_BINDINGS: list[tuple[str, str, str, int, str]] = [
    # ── 库存盈余 ──
    ("inventory_surplus", "smart_menu", "adjust_push_recommendations", 60, "库存盈余→智能排菜调整推荐"),
    ("inventory_surplus", "private_ops", "trigger_surplus_promotion", 50, "库存盈余→私域运营促销"),
    # ── 库存短缺 ──
    ("inventory_shortage", "smart_menu", "reduce_shortage_items", 60, "库存短缺→减少短缺菜品推荐"),
    ("inventory_shortage", "serve_dispatch", "alert_kitchen_shortage", 50, "库存短缺→通知后厨"),
    # ── 折扣违规 ──
    ("discount_violation", "discount_guard", "log_violation", 60, "折扣违规→记录违规"),
    ("discount_violation", "private_ops", "notify_store_manager", 50, "折扣违规→通知店长"),
    # ── VIP 到店 ──
    ("vip_arrival", "member_insight", "load_vip_preferences", 60, "VIP到店→加载偏好"),
    ("vip_arrival", "serve_dispatch", "assign_senior_waiter", 50, "VIP到店→分配资深服务员"),
    # ── 每日计划生成 ──
    ("daily_plan_generated", "private_ops", "notify_manager_for_approval", 50, "每日计划→通知店长审批"),
    # ── 订单完成 ──
    ("order_completed", "finance_audit", "update_daily_revenue", 60, "订单完成→更新日营收"),
    ("order_completed", "inventory_alert", "deduct_ingredients", 50, "订单完成→扣减食材"),
    # ── 班次交接 ──
    ("shift_handover", "finance_audit", "generate_shift_summary", 60, "班次交接→生成财务摘要"),
    ("shift_handover", "store_inspect", "trigger_shift_checklist", 50, "班次交接→触发质检清单"),

    # ── 交易域事件驱动 ──
    ("trade.order.paid", "member_insight", "update_customer_rfm", 70, "订单支付→更新会员RFM分层"),
    ("trade.order.paid", "private_ops", "check_journey_trigger", 60, "订单支付→检查私域旅程触发"),
    ("trade.order.paid", "finance_audit", "update_daily_revenue", 50, "订单支付→更新日营收"),
    ("trade.order.paid", "personalization", "generate_reorder_prompt", 40, "订单支付→生成复购提醒文案"),
    ("trade.discount.blocked", "discount_guard", "log_violation", 60, "折扣拦截→记录违规"),
    ("trade.discount.blocked", "finance_audit", "flag_discount_anomaly", 50, "折扣拦截→财务稽核标记"),
    ("trade.daily_settlement.completed", "finance_audit", "generate_shift_summary", 60, "日结完成→生成财务摘要"),
    ("trade.daily_settlement.completed", "store_inspect", "trigger_shift_checklist", 50, "日结完成→触发质检清单"),

    # ── 供应链域事件驱动 ──
    ("supply.stock.low", "inventory_alert", "assess_shortage_severity", 60, "库存低→评估短缺严重程度"),
    ("supply.stock.low", "smart_menu", "suggest_alternatives", 50, "库存低→推荐替代菜品"),
    ("supply.stock.zero", "smart_menu", "mark_sold_out", 60, "库存归零→标记售罄"),
    ("supply.stock.zero", "inventory_alert", "urgent_reorder_notify", 50, "库存归零→紧急补货通知"),
    ("supply.ingredient.expiring", "inventory_alert", "plan_usage", 60, "食材临期→制定用料计划"),
    ("supply.ingredient.expiring", "smart_menu", "push_expiry_specials", 50, "食材临期→推荐特价菜"),
    ("supply.receiving.variance", "finance_audit", "flag_receiving_variance", 50, "收货差异→财务稽核标记"),

    # ── 组织人事域事件驱动 ──
    ("org.attendance.late", "store_inspect", "log_attendance_issue", 50, "迟到→记录考勤问题"),
    ("org.attendance.exception", "store_inspect", "create_followup_task", 50, "考勤异常→创建跟进任务"),
    ("org.approval.completed", "finance_audit", "process_approval_result", 50, "审批完成→财务联动"),

    # ── 财务域事件驱动 ──
    ("finance.cost_rate.exceeded", "finance_audit", "root_cause_analysis", 60, "成本率超标→原因分析"),
    ("finance.cost_rate.exceeded", "smart_menu", "flag_high_cost_dishes", 50, "成本率超标→标记高成本菜品"),
    ("finance.daily_pl.generated", "finance_audit", "check_pl_anomaly", 50, "日P&L生成→异常检测"),

    # ── 千人千面Agent事件驱动 ──
    ("member.profile_updated", "personalization", "generate_batch_reasons", 50, "用户画像更新→重新生成推荐理由"),

    # ── 排位Agent事件驱动 ──
    ("trade.table.freed", "queue_seating", "auto_call_next", 50, "桌台空出→自动叫号"),
    ("trade.queue.ticket_created", "queue_seating", "predict_wait_time", 50, "新排队→预测等位时间"),
    ("trade.reservation.no_show", "queue_seating", "handle_no_show_release", 50, "爽约→释放桌位"),

    # ── 后厨超时Agent事件驱动 ──
    ("kds.item.overtime_warning", "kitchen_overtime", "analyze_overtime_cause", 60, "出餐超时→原因分析"),
    ("kds.item.overtime_warning", "kitchen_overtime", "auto_rush_notify", 50, "出餐超时→自动催菜"),
    ("kds.scan.scheduled", "kitchen_overtime", "scan_overtime_items", 50, "定时扫描→检查超时项"),

    # ── 收银异常Agent事件驱动 ──
    ("trade.order.reverse_settled", "billing_anomaly", "detect_reverse_settle_anomaly", 50, "反结账→异常检测"),
    ("trade.payment.confirmed", "billing_anomaly", "detect_payment_anomaly", 50, "支付确认→异常检测"),
    ("trade.shift.closed", "billing_anomaly", "analyze_shift_variance", 50, "班结→现金差异分析"),

    # ── 闭店Agent事件驱动 ──
    ("ops.closing_time.approaching", "closing_ops", "pre_closing_check", 60, "闭店临近→预检"),
    ("ops.closing_time.approaching", "closing_ops", "remind_unsettled_orders", 50, "闭店临近→未结单提醒"),
    ("ops.checklist.closing_submitted", "closing_ops", "check_checklist_status", 50, "检查单提交→追踪"),
    ("ops.daily_settlement.completed", "closing_ops", "validate_daily_settlement", 60, "日结完成→数据校验"),
    ("ops.daily_settlement.completed", "closing_ops", "generate_closing_report", 50, "日结完成→生成闭店报告"),
]


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()


    # ── 1. 创建 event_agent_bindings 表 ──

    if 'event_agent_bindings' not in existing:
        op.create_table(
            "event_agent_bindings",
            sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
            sa.Column("tenant_id", postgresql.UUID(), nullable=False),
            sa.Column("event_type", sa.String(100), nullable=False),
            sa.Column("agent_id", sa.String(100), nullable=False),
            sa.Column("action", sa.String(100), nullable=False),
            sa.Column("priority", sa.Integer(), server_default=sa.text("50"), nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
            sa.Column("condition_json", postgresql.JSON(), nullable=True),
            sa.Column("description", sa.String(500), nullable=True),
            sa.Column("source", sa.String(20), server_default=sa.text("'config'"), nullable=False),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
        )

        # ── 2. 创建索引 ──
        op.create_index("ix_eab_event_type", "event_agent_bindings", ["event_type"])
        op.create_index("ix_eab_agent_id", "event_agent_bindings", ["agent_id"])
        op.create_index("ix_eab_tenant_enabled", "event_agent_bindings", ["tenant_id", "enabled"])

        # ── 3. RLS ──
        _add_rls("event_agent_bindings", "eab")

        # ── 4. 插入初始化数据（从 DEFAULT_EVENT_HANDLERS 转换） ──
        # 使用临时 SET app.tenant_id 让 RLS 允许插入
        op.execute(f"SET LOCAL app.tenant_id = '{_SYSTEM_TENANT}'")

        for event_type, agent_id, action, priority, description in _INITIAL_BINDINGS:
            # 转义单引号（虽然当前数据无需，但防御性编程）
            desc_escaped = description.replace("'", "''")
            op.execute(f"""
                INSERT INTO event_agent_bindings
                    (tenant_id, event_type, agent_id, action, priority, enabled, source, description)
                VALUES
                    ('{_SYSTEM_TENANT}'::uuid, '{event_type}', '{agent_id}', '{action}',
                     {priority}, true, 'default', '{desc_escaped}')
            """)


def downgrade() -> None:
    op.drop_table("event_agent_bindings")
