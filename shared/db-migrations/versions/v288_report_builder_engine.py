"""v288 — 报表配置化引擎（S5: 自定义报表模板 + 50行业预置）

目标：替代天财商龙50+定制客户报表，实现无代码报表配置。
包含4张新表 + 50个系统预置行业报表模板 seed。

表结构：
  - report_templates    — 报表模板（系统预置 + 租户自定义）
  - report_instances    — 报表实例（保存筛选条件 + 定时推送）
  - report_exports      — 报表导出记录
  - report_subscriptions — 报表订阅

Revision ID: v288
Revises: v287
Create Date: 2026-04-24
"""
from typing import Sequence, Union

from alembic import op

revision: str = "v288"
down_revision: Union[str, None] = "v287"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ══════════════════════════════════════════════════════════════
    # 1. report_templates — 报表模板
    # ══════════════════════════════════════════════════════════════
    op.execute("""
        CREATE TABLE IF NOT EXISTS report_templates (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID,
                                -- NULL = 系统预置模板，非NULL = 租户自定义
            template_code       VARCHAR(50) NOT NULL,
            template_name       VARCHAR(200) NOT NULL,
            category            VARCHAR(30) NOT NULL
                                CHECK (category IN (
                                    'revenue', 'sales', 'cost', 'staff',
                                    'kitchen', 'delivery', 'member',
                                    'inventory', 'banquet', 'custom',
                                    'finance', 'decision'
                                )),
            description         TEXT,
            data_source         VARCHAR(100) NOT NULL,
            dimensions          JSONB NOT NULL DEFAULT '[]'::jsonb,
            measures            JSONB NOT NULL DEFAULT '[]'::jsonb,
            filters             JSONB NOT NULL DEFAULT '[]'::jsonb,
            default_sort        JSONB,
            chart_type          VARCHAR(20)
                                CHECK (chart_type IS NULL OR chart_type IN (
                                    'table', 'bar', 'line', 'pie',
                                    'heatmap', 'scatter', 'funnel', 'radar'
                                )),
            layout              JSONB,
            is_system           BOOLEAN NOT NULL DEFAULT FALSE,
            is_active           BOOLEAN NOT NULL DEFAULT TRUE,
            version             INTEGER NOT NULL DEFAULT 1,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_report_templates_code
            ON report_templates (template_code)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_report_templates_tenant_category
            ON report_templates (tenant_id, category, is_active)
            WHERE is_deleted = false
    """)

    # RLS — 系统预置(tenant_id IS NULL)所有租户可读，自定义模板隔离
    op.execute("ALTER TABLE report_templates ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS report_templates_tenant_isolation ON report_templates;
        CREATE POLICY report_templates_tenant_isolation ON report_templates
            USING (
                tenant_id IS NULL
                OR tenant_id::text = current_setting('app.tenant_id', true)
            )
            WITH CHECK (
                tenant_id::text = current_setting('app.tenant_id', true)
            );
    """)

    # ══════════════════════════════════════════════════════════════
    # 2. report_instances — 报表实例
    # ══════════════════════════════════════════════════════════════
    op.execute("""
        CREATE TABLE IF NOT EXISTS report_instances (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            template_id         UUID NOT NULL REFERENCES report_templates(id),
            instance_name       VARCHAR(200) NOT NULL,
            custom_filters      JSONB NOT NULL DEFAULT '{}'::jsonb,
            custom_dimensions   JSONB,
            custom_measures     JSONB,
            schedule_type       VARCHAR(20) NOT NULL DEFAULT 'none'
                                CHECK (schedule_type IN ('none', 'daily', 'weekly', 'monthly')),
            schedule_config     JSONB,
            recipients          JSONB,
            last_generated_at   TIMESTAMPTZ,
            created_by          UUID NOT NULL,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_report_instances_tenant
            ON report_instances (tenant_id, template_id)
            WHERE is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_report_instances_schedule
            ON report_instances (tenant_id, schedule_type)
            WHERE schedule_type != 'none' AND is_deleted = false
    """)

    op.execute("ALTER TABLE report_instances ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS report_instances_tenant_isolation ON report_instances;
        CREATE POLICY report_instances_tenant_isolation ON report_instances
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ══════════════════════════════════════════════════════════════
    # 3. report_exports — 报表导出记录
    # ══════════════════════════════════════════════════════════════
    op.execute("""
        CREATE TABLE IF NOT EXISTS report_exports (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            instance_id         UUID REFERENCES report_instances(id),
            template_id         UUID NOT NULL REFERENCES report_templates(id),
            export_format       VARCHAR(10) NOT NULL
                                CHECK (export_format IN ('pdf', 'excel', 'csv')),
            file_url            TEXT,
            file_size_bytes     BIGINT,
            generated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at          TIMESTAMPTZ,
            requested_by        UUID NOT NULL,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_report_exports_tenant
            ON report_exports (tenant_id, template_id, generated_at DESC)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE report_exports ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS report_exports_tenant_isolation ON report_exports;
        CREATE POLICY report_exports_tenant_isolation ON report_exports
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ══════════════════════════════════════════════════════════════
    # 4. report_subscriptions — 报表订阅
    # ══════════════════════════════════════════════════════════════
    op.execute("""
        CREATE TABLE IF NOT EXISTS report_subscriptions (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            instance_id         UUID NOT NULL REFERENCES report_instances(id),
            subscriber_id       UUID NOT NULL,
            channel             VARCHAR(20) NOT NULL
                                CHECK (channel IN ('email', 'wechat', 'dingtalk', 'im')),
            is_active           BOOLEAN NOT NULL DEFAULT TRUE,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_report_subscriptions_unique
            ON report_subscriptions (tenant_id, instance_id, subscriber_id, channel)
            WHERE is_deleted = false
    """)

    op.execute("ALTER TABLE report_subscriptions ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS report_subscriptions_tenant_isolation ON report_subscriptions;
        CREATE POLICY report_subscriptions_tenant_isolation ON report_subscriptions
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # ══════════════════════════════════════════════════════════════
    # 表注释
    # ══════════════════════════════════════════════════════════════
    op.execute("""
        COMMENT ON TABLE report_templates IS
            'S5: 报表配置化引擎 — 系统预置(tenant_id=NULL) + 租户自定义报表模板';
        COMMENT ON TABLE report_instances IS
            'S5: 报表实例 — 保存用户筛选条件/定时推送配置';
        COMMENT ON TABLE report_exports IS
            'S5: 报表导出记录 — PDF/Excel/CSV 导出历史';
        COMMENT ON TABLE report_subscriptions IS
            'S5: 报表订阅 — 多渠道推送订阅（邮件/微信/钉钉/IM）';
    """)

    # ══════════════════════════════════════════════════════════════
    # 5. 预置50个行业报表模板 (Seeds)
    # ══════════════════════════════════════════════════════════════
    _seed_system_templates()


def _seed_system_templates() -> None:
    """插入50个系统预置行业报表模板，覆盖天财商龙报表中心全部核心报表"""

    # 使用 ON CONFLICT DO NOTHING 幂等插入
    op.execute("""
        INSERT INTO report_templates (
            tenant_id, template_code, template_name, category, description,
            data_source, dimensions, measures, filters, default_sort,
            chart_type, is_system, is_active
        ) VALUES

        -- ════════════ 营业统计 (10个) ════════════

        (NULL, 'REV_SUMMARY', '营业情况汇总', 'revenue',
         '按门店/日期汇总营业额、订单数、客单价、折扣等核心经营指标',
         'v_revenue_summary',
         '[{"key":"store_name","label":"门店","type":"string"},{"key":"order_date","label":"日期","type":"date","granularity":"day"}]'::jsonb,
         '[{"key":"revenue_fen","label":"营业额(元)","type":"sum","format":"currency"},{"key":"order_count","label":"订单数","type":"count"},{"key":"guest_count","label":"客数","type":"sum"},{"key":"avg_ticket_fen","label":"客单价(元)","type":"avg","format":"currency"},{"key":"discount_fen","label":"折扣金额(元)","type":"sum","format":"currency"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_7_days"}]'::jsonb,
         '{"key":"revenue_fen","direction":"desc"}'::jsonb,
         'table', TRUE, TRUE),

        (NULL, 'REV_DETAIL', '营业情况明细', 'revenue',
         '每笔订单级别的营业明细，含支付方式、渠道、折扣原因',
         'v_revenue_detail',
         '[{"key":"store_name","label":"门店","type":"string"},{"key":"order_no","label":"单号","type":"string"},{"key":"order_time","label":"下单时间","type":"datetime"},{"key":"channel","label":"渠道","type":"string"},{"key":"payment_method","label":"支付方式","type":"string"}]'::jsonb,
         '[{"key":"total_fen","label":"实收(元)","type":"sum","format":"currency"},{"key":"discount_fen","label":"优惠(元)","type":"sum","format":"currency"},{"key":"item_count","label":"品项数","type":"sum"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"today"},{"key":"channel","label":"渠道","type":"select","options":["dine_in","takeout","delivery"]},{"key":"payment_method","label":"支付方式","type":"select","options":["wechat","alipay","cash","card","member"]}]'::jsonb,
         '{"key":"order_time","direction":"desc"}'::jsonb,
         'table', TRUE, TRUE),

        (NULL, 'REV_KPI_TREND', '经营指标走势', 'revenue',
         '营业额/客单价/客数等核心指标按日/周/月走势图',
         'v_revenue_summary',
         '[{"key":"order_date","label":"日期","type":"date","granularity":"day"}]'::jsonb,
         '[{"key":"revenue_fen","label":"营业额(元)","type":"sum","format":"currency"},{"key":"order_count","label":"订单数","type":"count"},{"key":"avg_ticket_fen","label":"客单价(元)","type":"avg","format":"currency"},{"key":"guest_count","label":"客数","type":"sum"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_30_days"}]'::jsonb,
         '{"key":"order_date","direction":"asc"}'::jsonb,
         'line', TRUE, TRUE),

        (NULL, 'REV_KPI_COMPARE', '经营指标对比', 'revenue',
         '多门店同期经营指标横向对比（柱状图）',
         'v_revenue_summary',
         '[{"key":"store_name","label":"门店","type":"string"}]'::jsonb,
         '[{"key":"revenue_fen","label":"营业额(元)","type":"sum","format":"currency"},{"key":"order_count","label":"订单数","type":"count"},{"key":"avg_ticket_fen","label":"客单价(元)","type":"avg","format":"currency"},{"key":"table_turnover","label":"翻台率","type":"avg","format":"decimal"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_7_days"}]'::jsonb,
         '{"key":"revenue_fen","direction":"desc"}'::jsonb,
         'bar', TRUE, TRUE),

        (NULL, 'REV_KPI_HOURLY', '经营指标时段统计', 'revenue',
         '按小时时段统计营业额和订单分布（热力图）',
         'v_revenue_hourly',
         '[{"key":"hour","label":"时段","type":"integer"},{"key":"weekday","label":"星期","type":"string"}]'::jsonb,
         '[{"key":"revenue_fen","label":"营业额(元)","type":"sum","format":"currency"},{"key":"order_count","label":"订单数","type":"count"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_7_days"}]'::jsonb,
         '{"key":"hour","direction":"asc"}'::jsonb,
         'heatmap', TRUE, TRUE),

        (NULL, 'REV_STAFF_EFFICIENCY', '员工效能产值', 'revenue',
         '按员工统计服务桌数、营业额贡献、人均产值',
         'v_staff_revenue',
         '[{"key":"employee_name","label":"员工","type":"string"},{"key":"role","label":"岗位","type":"string"}]'::jsonb,
         '[{"key":"served_tables","label":"服务桌数","type":"sum"},{"key":"revenue_fen","label":"贡献营业额(元)","type":"sum","format":"currency"},{"key":"avg_per_table_fen","label":"桌均(元)","type":"avg","format":"currency"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_7_days"}]'::jsonb,
         '{"key":"revenue_fen","direction":"desc"}'::jsonb,
         'bar', TRUE, TRUE),

        (NULL, 'REV_ACTIVE_STATS', '经营活跃统计', 'revenue',
         '门店经营活跃天数、高峰时段、闲时统计',
         'v_revenue_summary',
         '[{"key":"store_name","label":"门店","type":"string"},{"key":"order_date","label":"日期","type":"date","granularity":"day"}]'::jsonb,
         '[{"key":"active_hours","label":"活跃时段数","type":"count"},{"key":"peak_hour_revenue_fen","label":"高峰时段营业额(元)","type":"max","format":"currency"},{"key":"order_count","label":"订单数","type":"count"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_30_days"}]'::jsonb,
         '{"key":"order_count","direction":"desc"}'::jsonb,
         'table', TRUE, TRUE),

        (NULL, 'REV_STORE_KPI', '门店经营指标统计', 'revenue',
         '按门店汇总经营指标排名（营业额/客单/翻台率/好评率）',
         'v_store_kpi',
         '[{"key":"store_name","label":"门店","type":"string"},{"key":"region","label":"区域","type":"string"}]'::jsonb,
         '[{"key":"revenue_fen","label":"营业额(元)","type":"sum","format":"currency"},{"key":"avg_ticket_fen","label":"客单价(元)","type":"avg","format":"currency"},{"key":"table_turnover","label":"翻台率","type":"avg","format":"decimal"},{"key":"satisfaction_score","label":"满意度","type":"avg","format":"decimal"}]'::jsonb,
         '[{"key":"region","label":"区域","type":"multi_select","source":"regions"},{"key":"date_range","label":"日期","type":"date_range","default":"last_30_days"}]'::jsonb,
         '{"key":"revenue_fen","direction":"desc"}'::jsonb,
         'table', TRUE, TRUE),

        (NULL, 'REV_TARGET_ACHIEVE', '营业目标达成', 'revenue',
         '门店营业目标完成率及差距分析',
         'v_revenue_target',
         '[{"key":"store_name","label":"门店","type":"string"},{"key":"month","label":"月份","type":"date","granularity":"month"}]'::jsonb,
         '[{"key":"target_fen","label":"目标(元)","type":"sum","format":"currency"},{"key":"actual_fen","label":"实际(元)","type":"sum","format":"currency"},{"key":"achieve_rate","label":"达成率","type":"avg","format":"percent"},{"key":"gap_fen","label":"差距(元)","type":"sum","format":"currency"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"this_month"}]'::jsonb,
         '{"key":"achieve_rate","direction":"desc"}'::jsonb,
         'bar', TRUE, TRUE),

        (NULL, 'REV_DAILY_SUMMARY', '营业情况汇总(按日期)', 'revenue',
         '按日期维度汇总各门店营业数据（日历视图）',
         'v_revenue_summary',
         '[{"key":"order_date","label":"日期","type":"date","granularity":"day"},{"key":"store_name","label":"门店","type":"string"}]'::jsonb,
         '[{"key":"revenue_fen","label":"营业额(元)","type":"sum","format":"currency"},{"key":"order_count","label":"订单数","type":"count"},{"key":"avg_ticket_fen","label":"客单价(元)","type":"avg","format":"currency"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_30_days"}]'::jsonb,
         '{"key":"order_date","direction":"desc"}'::jsonb,
         'table', TRUE, TRUE),

        -- ════════════ 品项销售 (10个) ════════════

        (NULL, 'SALES_ITEM_STATS', '品项销售统计', 'sales',
         '按品项统计销量、销售额、占比',
         'v_dish_sales',
         '[{"key":"dish_name","label":"品项","type":"string"},{"key":"category","label":"分类","type":"string"}]'::jsonb,
         '[{"key":"sales_qty","label":"销量","type":"sum"},{"key":"sales_fen","label":"销售额(元)","type":"sum","format":"currency"},{"key":"sales_ratio","label":"占比","type":"avg","format":"percent"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_7_days"},{"key":"category","label":"分类","type":"multi_select","source":"dish_categories"}]'::jsonb,
         '{"key":"sales_qty","direction":"desc"}'::jsonb,
         'table', TRUE, TRUE),

        (NULL, 'SALES_ITEM_COMPARE', '品项销售对比', 'sales',
         '两个时间段品项销售同比/环比对比',
         'v_dish_sales',
         '[{"key":"dish_name","label":"品项","type":"string"},{"key":"category","label":"分类","type":"string"}]'::jsonb,
         '[{"key":"current_qty","label":"本期销量","type":"sum"},{"key":"previous_qty","label":"上期销量","type":"sum"},{"key":"qty_change_rate","label":"变化率","type":"avg","format":"percent"},{"key":"current_fen","label":"本期销售额(元)","type":"sum","format":"currency"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"current_range","label":"本期","type":"date_range","default":"last_7_days"},{"key":"previous_range","label":"对比期","type":"date_range","default":"prev_7_days"}]'::jsonb,
         '{"key":"qty_change_rate","direction":"desc"}'::jsonb,
         'bar', TRUE, TRUE),

        (NULL, 'SALES_ITEM_RANK', '品项销售排行', 'sales',
         '品项销售TOP排行榜（按销量或销售额）',
         'v_dish_sales',
         '[{"key":"rank","label":"排名","type":"integer"},{"key":"dish_name","label":"品项","type":"string"},{"key":"category","label":"分类","type":"string"}]'::jsonb,
         '[{"key":"sales_qty","label":"销量","type":"sum"},{"key":"sales_fen","label":"销售额(元)","type":"sum","format":"currency"},{"key":"avg_price_fen","label":"均价(元)","type":"avg","format":"currency"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_7_days"},{"key":"top_n","label":"排名数","type":"number","default":20}]'::jsonb,
         '{"key":"sales_qty","direction":"desc"}'::jsonb,
         'bar', TRUE, TRUE),

        (NULL, 'SALES_METHOD_STATS', '制作方法统计', 'sales',
         '按制作方法/做法统计品项销量',
         'v_dish_method_sales',
         '[{"key":"method_name","label":"做法","type":"string"},{"key":"dish_name","label":"品项","type":"string"}]'::jsonb,
         '[{"key":"sales_qty","label":"销量","type":"sum"},{"key":"sales_fen","label":"销售额(元)","type":"sum","format":"currency"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_7_days"}]'::jsonb,
         '{"key":"sales_qty","direction":"desc"}'::jsonb,
         'table', TRUE, TRUE),

        (NULL, 'SALES_COMBO', '套餐销售', 'sales',
         '套餐及其子品项销售统计',
         'v_combo_sales',
         '[{"key":"combo_name","label":"套餐名","type":"string"},{"key":"sub_item","label":"子品项","type":"string"}]'::jsonb,
         '[{"key":"combo_qty","label":"套餐销量","type":"sum"},{"key":"combo_fen","label":"套餐销售额(元)","type":"sum","format":"currency"},{"key":"sub_item_qty","label":"子品销量","type":"sum"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_7_days"}]'::jsonb,
         '{"key":"combo_qty","direction":"desc"}'::jsonb,
         'table', TRUE, TRUE),

        (NULL, 'SALES_DEPT_STATS', '出品部门统计', 'sales',
         '按出品部门/档口统计销量和金额',
         'v_dept_sales',
         '[{"key":"dept_name","label":"出品部门","type":"string"}]'::jsonb,
         '[{"key":"sales_qty","label":"销量","type":"sum"},{"key":"sales_fen","label":"销售额(元)","type":"sum","format":"currency"},{"key":"dish_count","label":"品项数","type":"count"},{"key":"sales_ratio","label":"占比","type":"avg","format":"percent"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_7_days"}]'::jsonb,
         '{"key":"sales_fen","direction":"desc"}'::jsonb,
         'pie', TRUE, TRUE),

        (NULL, 'SALES_HOURLY_COMPARE', '时段品项对比', 'sales',
         '不同时段的品项销售对比（午市/晚市/夜宵）',
         'v_dish_hourly_sales',
         '[{"key":"time_slot","label":"时段","type":"string"},{"key":"dish_name","label":"品项","type":"string"}]'::jsonb,
         '[{"key":"sales_qty","label":"销量","type":"sum"},{"key":"sales_fen","label":"销售额(元)","type":"sum","format":"currency"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_7_days"}]'::jsonb,
         '{"key":"time_slot","direction":"asc"}'::jsonb,
         'bar', TRUE, TRUE),

        (NULL, 'SALES_SLOW_MOVING', '品项滞销', 'sales',
         '销量低于阈值的滞销品项分析',
         'v_dish_sales',
         '[{"key":"dish_name","label":"品项","type":"string"},{"key":"category","label":"分类","type":"string"},{"key":"last_sold_date","label":"最近售出","type":"date"}]'::jsonb,
         '[{"key":"sales_qty","label":"销量","type":"sum"},{"key":"days_since_last_sale","label":"距上次售出(天)","type":"max"},{"key":"cost_fen","label":"成本(元)","type":"sum","format":"currency"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_30_days"},{"key":"threshold","label":"滞销阈值","type":"number","default":5}]'::jsonb,
         '{"key":"sales_qty","direction":"asc"}'::jsonb,
         'table', TRUE, TRUE),

        (NULL, 'SALES_MULTI_DIM', '品项多维度', 'sales',
         '品项按分类/渠道/时段/门店多维交叉分析',
         'v_dish_sales',
         '[{"key":"dish_name","label":"品项","type":"string"},{"key":"category","label":"分类","type":"string"},{"key":"channel","label":"渠道","type":"string"},{"key":"time_slot","label":"时段","type":"string"}]'::jsonb,
         '[{"key":"sales_qty","label":"销量","type":"sum"},{"key":"sales_fen","label":"销售额(元)","type":"sum","format":"currency"},{"key":"margin_rate","label":"毛利率","type":"avg","format":"percent"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_7_days"},{"key":"channel","label":"渠道","type":"multi_select","options":["dine_in","takeout","delivery"]}]'::jsonb,
         '{"key":"sales_fen","direction":"desc"}'::jsonb,
         'table', TRUE, TRUE),

        (NULL, 'SALES_PER_GUEST', '客位品项销售', 'sales',
         '按客位/人均统计品项点选频率和金额',
         'v_guest_dish_sales',
         '[{"key":"dish_name","label":"品项","type":"string"},{"key":"category","label":"分类","type":"string"}]'::jsonb,
         '[{"key":"order_rate","label":"点选率","type":"avg","format":"percent"},{"key":"avg_qty_per_guest","label":"人均点数","type":"avg","format":"decimal"},{"key":"avg_spend_fen","label":"人均消费(元)","type":"avg","format":"currency"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_7_days"}]'::jsonb,
         '{"key":"order_rate","direction":"desc"}'::jsonb,
         'table', TRUE, TRUE),

        -- ════════════ 厨房管理 (5个) ════════════

        (NULL, 'KITCHEN_OVERTIME', '菜品制作超时', 'kitchen',
         '超出标准制作时间的菜品列表及超时原因分析',
         'v_kitchen_overtime',
         '[{"key":"dish_name","label":"菜品","type":"string"},{"key":"station","label":"工位","type":"string"},{"key":"order_time","label":"下单时间","type":"datetime"}]'::jsonb,
         '[{"key":"standard_minutes","label":"标准时长(分)","type":"avg"},{"key":"actual_minutes","label":"实际时长(分)","type":"avg"},{"key":"overtime_minutes","label":"超时(分)","type":"sum"},{"key":"overtime_count","label":"超时次数","type":"count"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"today"},{"key":"station","label":"工位","type":"multi_select","source":"kitchen_stations"}]'::jsonb,
         '{"key":"overtime_minutes","direction":"desc"}'::jsonb,
         'table', TRUE, TRUE),

        (NULL, 'KITCHEN_CHEF_PERF', '厨师业绩', 'kitchen',
         '厨师出品数量、速度、质量评分排名',
         'v_chef_performance',
         '[{"key":"chef_name","label":"厨师","type":"string"},{"key":"station","label":"工位","type":"string"}]'::jsonb,
         '[{"key":"dish_count","label":"出品数","type":"sum"},{"key":"avg_time_minutes","label":"平均用时(分)","type":"avg","format":"decimal"},{"key":"overtime_rate","label":"超时率","type":"avg","format":"percent"},{"key":"quality_score","label":"质量评分","type":"avg","format":"decimal"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_7_days"}]'::jsonb,
         '{"key":"dish_count","direction":"desc"}'::jsonb,
         'bar', TRUE, TRUE),

        (NULL, 'KITCHEN_PREP', '厨师备餐', 'kitchen',
         '厨师备餐任务完成情况和效率',
         'v_chef_prep',
         '[{"key":"chef_name","label":"厨师","type":"string"},{"key":"prep_item","label":"备餐品项","type":"string"}]'::jsonb,
         '[{"key":"target_qty","label":"目标量","type":"sum"},{"key":"actual_qty","label":"完成量","type":"sum"},{"key":"completion_rate","label":"完成率","type":"avg","format":"percent"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"today"}]'::jsonb,
         '{"key":"completion_rate","direction":"desc"}'::jsonb,
         'table', TRUE, TRUE),

        (NULL, 'KITCHEN_DISH_TIME', '菜品制作时长', 'kitchen',
         '各菜品平均制作时长分析（漏斗图）',
         'v_dish_cook_time',
         '[{"key":"dish_name","label":"菜品","type":"string"},{"key":"category","label":"分类","type":"string"}]'::jsonb,
         '[{"key":"avg_minutes","label":"平均时长(分)","type":"avg","format":"decimal"},{"key":"min_minutes","label":"最短(分)","type":"min"},{"key":"max_minutes","label":"最长(分)","type":"max"},{"key":"sample_count","label":"样本数","type":"count"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_7_days"}]'::jsonb,
         '{"key":"avg_minutes","direction":"desc"}'::jsonb,
         'funnel', TRUE, TRUE),

        (NULL, 'KITCHEN_ORDER_TIME', '整单制作时长', 'kitchen',
         '从下单到齐菜的整单制作时长统计',
         'v_order_cook_time',
         '[{"key":"order_no","label":"单号","type":"string"},{"key":"order_time","label":"下单时间","type":"datetime"},{"key":"table_name","label":"桌号","type":"string"}]'::jsonb,
         '[{"key":"total_minutes","label":"整单时长(分)","type":"avg","format":"decimal"},{"key":"dish_count","label":"品项数","type":"sum"},{"key":"is_overtime","label":"是否超时","type":"count"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"today"}]'::jsonb,
         '{"key":"total_minutes","direction":"desc"}'::jsonb,
         'table', TRUE, TRUE),

        -- ════════════ 财务核账 (8个) ════════════

        (NULL, 'FIN_SHIFT_REPORT', '结班报表', 'finance',
         '收银班次结算汇总（现金/电子支付/挂账/退款）',
         'v_shift_settlement',
         '[{"key":"shift_name","label":"班次","type":"string"},{"key":"cashier_name","label":"收银员","type":"string"},{"key":"shift_date","label":"日期","type":"date"}]'::jsonb,
         '[{"key":"cash_fen","label":"现金(元)","type":"sum","format":"currency"},{"key":"electronic_fen","label":"电子支付(元)","type":"sum","format":"currency"},{"key":"total_fen","label":"合计(元)","type":"sum","format":"currency"},{"key":"refund_fen","label":"退款(元)","type":"sum","format":"currency"},{"key":"order_count","label":"单数","type":"count"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"today"}]'::jsonb,
         '{"key":"shift_date","direction":"desc"}'::jsonb,
         'table', TRUE, TRUE),

        (NULL, 'FIN_CASHIER_SUMMARY', '收银情况汇总', 'finance',
         '按收银员汇总收款金额、笔数、差异',
         'v_cashier_summary',
         '[{"key":"cashier_name","label":"收银员","type":"string"},{"key":"shift_date","label":"日期","type":"date"}]'::jsonb,
         '[{"key":"total_fen","label":"收款总额(元)","type":"sum","format":"currency"},{"key":"order_count","label":"笔数","type":"count"},{"key":"avg_ticket_fen","label":"均单(元)","type":"avg","format":"currency"},{"key":"diff_fen","label":"差异(元)","type":"sum","format":"currency"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"today"}]'::jsonb,
         '{"key":"total_fen","direction":"desc"}'::jsonb,
         'table', TRUE, TRUE),

        (NULL, 'FIN_BILL_QUERY', '结账单查询', 'finance',
         '按条件查询结账单明细',
         'v_bill_detail',
         '[{"key":"bill_no","label":"账单号","type":"string"},{"key":"table_name","label":"桌号","type":"string"},{"key":"bill_time","label":"结账时间","type":"datetime"},{"key":"cashier_name","label":"收银员","type":"string"},{"key":"payment_method","label":"支付方式","type":"string"}]'::jsonb,
         '[{"key":"total_fen","label":"金额(元)","type":"sum","format":"currency"},{"key":"discount_fen","label":"优惠(元)","type":"sum","format":"currency"},{"key":"actual_fen","label":"实收(元)","type":"sum","format":"currency"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"today"},{"key":"bill_no","label":"账单号","type":"text"},{"key":"table_name","label":"桌号","type":"text"}]'::jsonb,
         '{"key":"bill_time","direction":"desc"}'::jsonb,
         'table', TRUE, TRUE),

        (NULL, 'FIN_RETURN_SETTLE', '返位结算', 'finance',
         '退菜/返位结算明细及原因统计',
         'v_return_settlement',
         '[{"key":"order_no","label":"单号","type":"string"},{"key":"dish_name","label":"品项","type":"string"},{"key":"return_reason","label":"原因","type":"string"},{"key":"operator","label":"操作人","type":"string"}]'::jsonb,
         '[{"key":"return_qty","label":"退菜数","type":"sum"},{"key":"return_fen","label":"退款金额(元)","type":"sum","format":"currency"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"today"}]'::jsonb,
         '{"key":"return_fen","direction":"desc"}'::jsonb,
         'table', TRUE, TRUE),

        (NULL, 'FIN_MANAGER_SIGN', '经理签单', 'finance',
         '经理签字免单/折扣记录审计',
         'v_manager_sign',
         '[{"key":"order_no","label":"单号","type":"string"},{"key":"manager_name","label":"签单经理","type":"string"},{"key":"sign_time","label":"签单时间","type":"datetime"},{"key":"sign_reason","label":"原因","type":"string"}]'::jsonb,
         '[{"key":"sign_fen","label":"签单金额(元)","type":"sum","format":"currency"},{"key":"sign_count","label":"签单次数","type":"count"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_7_days"}]'::jsonb,
         '{"key":"sign_fen","direction":"desc"}'::jsonb,
         'table', TRUE, TRUE),

        (NULL, 'FIN_CREDIT_STATS', '挂账统计', 'finance',
         '挂账客户及金额统计（含账龄分析）',
         'v_credit_stats',
         '[{"key":"customer_name","label":"挂账客户","type":"string"},{"key":"credit_type","label":"挂账类型","type":"string"}]'::jsonb,
         '[{"key":"credit_fen","label":"挂账金额(元)","type":"sum","format":"currency"},{"key":"settled_fen","label":"已结(元)","type":"sum","format":"currency"},{"key":"outstanding_fen","label":"未结(元)","type":"sum","format":"currency"},{"key":"aging_days","label":"账龄(天)","type":"max"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_30_days"},{"key":"credit_type","label":"类型","type":"select","options":["corporate","vip","staff","other"]}]'::jsonb,
         '{"key":"outstanding_fen","direction":"desc"}'::jsonb,
         'table', TRUE, TRUE),

        (NULL, 'FIN_PAYMENT_RECON', '支付对账', 'finance',
         '平台支付到账与系统记录核对差异',
         'v_payment_recon',
         '[{"key":"payment_channel","label":"支付渠道","type":"string"},{"key":"recon_date","label":"对账日期","type":"date"}]'::jsonb,
         '[{"key":"system_fen","label":"系统金额(元)","type":"sum","format":"currency"},{"key":"platform_fen","label":"到账金额(元)","type":"sum","format":"currency"},{"key":"diff_fen","label":"差异(元)","type":"sum","format":"currency"},{"key":"diff_count","label":"差异笔数","type":"count"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"yesterday"},{"key":"payment_channel","label":"渠道","type":"multi_select","options":["wechat","alipay","meituan","eleme"]}]'::jsonb,
         '{"key":"diff_fen","direction":"desc"}'::jsonb,
         'table', TRUE, TRUE),

        (NULL, 'FIN_DAILY_CLOSE', '日结查询', 'finance',
         '每日营业结算确认及差异',
         'v_daily_close',
         '[{"key":"close_date","label":"日结日期","type":"date"},{"key":"store_name","label":"门店","type":"string"}]'::jsonb,
         '[{"key":"total_revenue_fen","label":"营业总额(元)","type":"sum","format":"currency"},{"key":"total_refund_fen","label":"退款(元)","type":"sum","format":"currency"},{"key":"net_revenue_fen","label":"净营收(元)","type":"sum","format":"currency"},{"key":"cash_diff_fen","label":"现金差异(元)","type":"sum","format":"currency"},{"key":"status","label":"状态","type":"count"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_7_days"}]'::jsonb,
         '{"key":"close_date","direction":"desc"}'::jsonb,
         'table', TRUE, TRUE),

        -- ════════════ 决策分析 (8个) ════════════

        (NULL, 'DEC_AVG_SPEND_BAND', '人均消费区间', 'decision',
         '按人均消费金额分段统计订单和客户分布',
         'v_spend_analysis',
         '[{"key":"spend_band","label":"消费区间","type":"string"}]'::jsonb,
         '[{"key":"order_count","label":"订单数","type":"count"},{"key":"guest_count","label":"客数","type":"sum"},{"key":"revenue_fen","label":"营业额(元)","type":"sum","format":"currency"},{"key":"ratio","label":"占比","type":"avg","format":"percent"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_30_days"}]'::jsonb,
         '{"key":"spend_band","direction":"asc"}'::jsonb,
         'bar', TRUE, TRUE),

        (NULL, 'DEC_TABLE_SPEND_BAND', '桌消费区间', 'decision',
         '按桌均消费金额分段统计',
         'v_table_spend_analysis',
         '[{"key":"spend_band","label":"消费区间","type":"string"}]'::jsonb,
         '[{"key":"table_count","label":"桌数","type":"count"},{"key":"revenue_fen","label":"营业额(元)","type":"sum","format":"currency"},{"key":"avg_duration_min","label":"平均用餐时长(分)","type":"avg","format":"decimal"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_30_days"}]'::jsonb,
         '{"key":"spend_band","direction":"asc"}'::jsonb,
         'bar', TRUE, TRUE),

        (NULL, 'DEC_GUEST_PROFILE', '消费群体分析', 'decision',
         '按消费频次/金额/时段分析消费群体画像',
         'v_guest_profile',
         '[{"key":"segment","label":"客群分类","type":"string"},{"key":"frequency_band","label":"消费频次","type":"string"}]'::jsonb,
         '[{"key":"customer_count","label":"客户数","type":"count"},{"key":"total_spend_fen","label":"总消费(元)","type":"sum","format":"currency"},{"key":"avg_frequency","label":"平均频次","type":"avg","format":"decimal"},{"key":"retention_rate","label":"留存率","type":"avg","format":"percent"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_90_days"}]'::jsonb,
         '{"key":"total_spend_fen","direction":"desc"}'::jsonb,
         'pie', TRUE, TRUE),

        (NULL, 'DEC_DISH_QUADRANT', '品项四象限', 'decision',
         '品项按销量-毛利率四象限分类（明星/金牛/问号/瘦狗）',
         'v_dish_quadrant',
         '[{"key":"dish_name","label":"品项","type":"string"},{"key":"category","label":"分类","type":"string"},{"key":"quadrant","label":"象限","type":"string"}]'::jsonb,
         '[{"key":"sales_qty","label":"销量","type":"sum"},{"key":"margin_rate","label":"毛利率","type":"avg","format":"percent"},{"key":"revenue_fen","label":"销售额(元)","type":"sum","format":"currency"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_30_days"}]'::jsonb,
         '{"key":"sales_qty","direction":"desc"}'::jsonb,
         'scatter', TRUE, TRUE),

        (NULL, 'DEC_PROMO_ANALYSIS', '优惠活动分析', 'decision',
         '各优惠活动核销数、拉新数、ROI 分析',
         'v_promo_analysis',
         '[{"key":"promo_name","label":"活动名","type":"string"},{"key":"promo_type","label":"类型","type":"string"}]'::jsonb,
         '[{"key":"used_count","label":"核销数","type":"sum"},{"key":"new_customers","label":"拉新数","type":"sum"},{"key":"discount_fen","label":"优惠金额(元)","type":"sum","format":"currency"},{"key":"revenue_fen","label":"带动营收(元)","type":"sum","format":"currency"},{"key":"roi","label":"ROI","type":"avg","format":"decimal"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_30_days"},{"key":"promo_type","label":"类型","type":"select","options":["coupon","full_reduction","discount","gift"]}]'::jsonb,
         '{"key":"roi","direction":"desc"}'::jsonb,
         'bar', TRUE, TRUE),

        (NULL, 'DEC_GIFT_REASON', '赠送原因', 'decision',
         '赠送菜品原因统计及金额占比',
         'v_gift_analysis',
         '[{"key":"gift_reason","label":"赠送原因","type":"string"},{"key":"dish_name","label":"品项","type":"string"}]'::jsonb,
         '[{"key":"gift_count","label":"赠送次数","type":"count"},{"key":"gift_fen","label":"赠送金额(元)","type":"sum","format":"currency"},{"key":"ratio","label":"占比","type":"avg","format":"percent"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_30_days"}]'::jsonb,
         '{"key":"gift_fen","direction":"desc"}'::jsonb,
         'pie', TRUE, TRUE),

        (NULL, 'DEC_RETURN_REASON', '退单原因', 'decision',
         '退菜/退单原因统计及趋势分析',
         'v_return_reason',
         '[{"key":"return_reason","label":"退单原因","type":"string"},{"key":"category","label":"品项分类","type":"string"}]'::jsonb,
         '[{"key":"return_count","label":"退单数","type":"count"},{"key":"return_fen","label":"退款金额(元)","type":"sum","format":"currency"},{"key":"ratio","label":"占比","type":"avg","format":"percent"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_30_days"}]'::jsonb,
         '{"key":"return_count","direction":"desc"}'::jsonb,
         'pie', TRUE, TRUE),

        (NULL, 'DEC_SOLDOUT_REASON', '沽清原因', 'decision',
         '菜品沽清原因及频次统计',
         'v_soldout_analysis',
         '[{"key":"dish_name","label":"品项","type":"string"},{"key":"soldout_reason","label":"沽清原因","type":"string"}]'::jsonb,
         '[{"key":"soldout_count","label":"沽清次数","type":"count"},{"key":"estimated_loss_fen","label":"预估损失(元)","type":"sum","format":"currency"},{"key":"avg_soldout_hour","label":"平均沽清时段","type":"avg","format":"decimal"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_30_days"}]'::jsonb,
         '{"key":"soldout_count","direction":"desc"}'::jsonb,
         'bar', TRUE, TRUE),

        -- ════════════ 外卖 (4个) ════════════

        (NULL, 'DLV_ORDER_STATS', '外卖单统计', 'delivery',
         '外卖订单汇总（平台分布、时段、金额）',
         'v_delivery_orders',
         '[{"key":"platform","label":"平台","type":"string"},{"key":"order_date","label":"日期","type":"date","granularity":"day"}]'::jsonb,
         '[{"key":"order_count","label":"订单数","type":"count"},{"key":"revenue_fen","label":"营业额(元)","type":"sum","format":"currency"},{"key":"avg_ticket_fen","label":"客单价(元)","type":"avg","format":"currency"},{"key":"cancel_rate","label":"取消率","type":"avg","format":"percent"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_7_days"},{"key":"platform","label":"平台","type":"multi_select","options":["meituan","eleme","douyin"]}]'::jsonb,
         '{"key":"order_count","direction":"desc"}'::jsonb,
         'line', TRUE, TRUE),

        (NULL, 'DLV_ITEM_DETAIL', '外卖品项明细', 'delivery',
         '外卖渠道品项销售明细',
         'v_delivery_items',
         '[{"key":"dish_name","label":"品项","type":"string"},{"key":"platform","label":"平台","type":"string"}]'::jsonb,
         '[{"key":"sales_qty","label":"销量","type":"sum"},{"key":"sales_fen","label":"销售额(元)","type":"sum","format":"currency"},{"key":"platform_fee_fen","label":"平台费(元)","type":"sum","format":"currency"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_7_days"},{"key":"platform","label":"平台","type":"select","options":["meituan","eleme","douyin"]}]'::jsonb,
         '{"key":"sales_qty","direction":"desc"}'::jsonb,
         'table', TRUE, TRUE),

        (NULL, 'DLV_RIDER_PERF', '骑手业绩', 'delivery',
         '自有骑手配送业绩（单量/时效/好评）',
         'v_rider_performance',
         '[{"key":"rider_name","label":"骑手","type":"string"}]'::jsonb,
         '[{"key":"delivery_count","label":"配送单数","type":"count"},{"key":"avg_delivery_min","label":"平均配送时长(分)","type":"avg","format":"decimal"},{"key":"ontime_rate","label":"准时率","type":"avg","format":"percent"},{"key":"rating","label":"评分","type":"avg","format":"decimal"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_7_days"}]'::jsonb,
         '{"key":"delivery_count","direction":"desc"}'::jsonb,
         'bar', TRUE, TRUE),

        (NULL, 'DLV_DISPATCH_STATS', '配送单统计', 'delivery',
         '配送订单状态追踪（配送中/已完成/异常）',
         'v_dispatch_stats',
         '[{"key":"dispatch_status","label":"状态","type":"string"},{"key":"dispatch_date","label":"日期","type":"date","granularity":"day"}]'::jsonb,
         '[{"key":"dispatch_count","label":"单数","type":"count"},{"key":"avg_distance_km","label":"平均距离(km)","type":"avg","format":"decimal"},{"key":"avg_time_min","label":"平均时长(分)","type":"avg","format":"decimal"},{"key":"exception_count","label":"异常数","type":"count"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_7_days"},{"key":"dispatch_status","label":"状态","type":"multi_select","options":["dispatching","delivered","exception"]}]'::jsonb,
         '{"key":"dispatch_count","direction":"desc"}'::jsonb,
         'line', TRUE, TRUE),

        -- ════════════ 预订宴会 (5个) ════════════

        (NULL, 'BKG_DETAIL', '预定明细', 'banquet',
         '预定订单明细（预定人/时间/桌数/备注）',
         'v_booking_detail',
         '[{"key":"booking_no","label":"预定号","type":"string"},{"key":"customer_name","label":"预定人","type":"string"},{"key":"booking_date","label":"预定日期","type":"date"},{"key":"meal_type","label":"餐别","type":"string"},{"key":"status","label":"状态","type":"string"}]'::jsonb,
         '[{"key":"table_count","label":"桌数","type":"sum"},{"key":"guest_count","label":"人数","type":"sum"},{"key":"deposit_fen","label":"定金(元)","type":"sum","format":"currency"},{"key":"estimated_fen","label":"预估消费(元)","type":"sum","format":"currency"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"next_7_days"},{"key":"status","label":"状态","type":"select","options":["pending","confirmed","cancelled","completed"]}]'::jsonb,
         '{"key":"booking_date","direction":"asc"}'::jsonb,
         'table', TRUE, TRUE),

        (NULL, 'BKG_RATIO', '预定占比', 'banquet',
         '预定客户占比及来源渠道分析',
         'v_booking_ratio',
         '[{"key":"source_channel","label":"来源渠道","type":"string"}]'::jsonb,
         '[{"key":"booking_count","label":"预定数","type":"count"},{"key":"guest_count","label":"预定人数","type":"sum"},{"key":"ratio","label":"占比","type":"avg","format":"percent"},{"key":"convert_rate","label":"转化率","type":"avg","format":"percent"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_30_days"}]'::jsonb,
         '{"key":"booking_count","direction":"desc"}'::jsonb,
         'pie', TRUE, TRUE),

        (NULL, 'BKG_TREND', '预定走势', 'banquet',
         '预定量按日/周/月走势图',
         'v_booking_trend',
         '[{"key":"booking_date","label":"日期","type":"date","granularity":"day"}]'::jsonb,
         '[{"key":"booking_count","label":"预定数","type":"count"},{"key":"guest_count","label":"预定人数","type":"sum"},{"key":"cancel_count","label":"取消数","type":"count"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_30_days"}]'::jsonb,
         '{"key":"booking_date","direction":"asc"}'::jsonb,
         'line', TRUE, TRUE),

        (NULL, 'BKG_ITEMS', '预定品项', 'banquet',
         '预定订单中品项选择偏好分析',
         'v_booking_items',
         '[{"key":"dish_name","label":"品项","type":"string"},{"key":"category","label":"分类","type":"string"}]'::jsonb,
         '[{"key":"order_count","label":"预定次数","type":"count"},{"key":"total_qty","label":"预定量","type":"sum"},{"key":"avg_qty","label":"平均点数","type":"avg","format":"decimal"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_30_days"}]'::jsonb,
         '{"key":"order_count","direction":"desc"}'::jsonb,
         'bar', TRUE, TRUE),

        (NULL, 'BKG_CONVERT', '宴会转化率', 'banquet',
         '宴会预定到实际消费的转化分析',
         'v_banquet_conversion',
         '[{"key":"banquet_type","label":"宴会类型","type":"string"},{"key":"month","label":"月份","type":"date","granularity":"month"}]'::jsonb,
         '[{"key":"inquiry_count","label":"咨询数","type":"count"},{"key":"booking_count","label":"预定数","type":"count"},{"key":"completed_count","label":"完成数","type":"count"},{"key":"convert_rate","label":"转化率","type":"avg","format":"percent"},{"key":"revenue_fen","label":"宴会营收(元)","type":"sum","format":"currency"}]'::jsonb,
         '[{"key":"store_id","label":"门店","type":"multi_select","source":"stores"},{"key":"date_range","label":"日期","type":"date_range","default":"last_90_days"},{"key":"banquet_type","label":"宴会类型","type":"select","options":["wedding","birthday","corporate","other"]}]'::jsonb,
         '{"key":"convert_rate","direction":"desc"}'::jsonb,
         'funnel', TRUE, TRUE)

        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS report_subscriptions CASCADE")
    op.execute("DROP TABLE IF EXISTS report_exports CASCADE")
    op.execute("DROP TABLE IF EXISTS report_instances CASCADE")
    op.execute("DROP TABLE IF EXISTS report_templates CASCADE")
