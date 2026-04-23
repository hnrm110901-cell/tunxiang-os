"""v280 — 薪资异常分析表（Sprint D4b）

目标：每月 HR 审核薪资表时，自动标注异常 + 给出处理建议（省 HR 人工翻表时间）。

业务场景：
  1. **底薪低于市场**：城市同岗 P25 线以下，离职风险高
  2. **加班失控**：月加班 > 法定 36h，合规风险（B1 合规红线）
  3. **调薪突增**：单次涨幅 > 30%，可能有人情/套利
  4. **提成异常**：佣金 > 底薪 200%，可能数据错乱
  5. **社保/公积金漏缴**：合规风险

工作流：
  1. 每月 5 号 cron 扫描 payroll_summaries → 生成 SalarySignalBundle
  2. Sonnet 4.7 + Prompt Cache（城市基准 + 合规规则 ~3KB cacheable）分析
  3. 输出 ranked_anomalies + remediation_actions
  4. HRD 审核 → act_on / dismiss / false_positive

与 D4a 共用 CachedPromptBuilder 模式，确保城市基准表只 cache 一次，
多店/多月分析共享 cache。

Revision ID: v280_salary_anomaly
Revises: v279_cost_root_cause
Create Date: 2026-04-23
"""
from alembic import op

revision = "v280_salary_anomaly"
down_revision = "v279_cost_root_cause"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS salary_anomaly_analyses (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            store_id                UUID,
            employee_id             UUID,
                                    -- NULL 表示批量分析（全店/全租户）
            -- 触发窗口
            analysis_month          DATE NOT NULL,
                                    -- YYYY-MM-01
            analysis_scope          VARCHAR(30) NOT NULL DEFAULT 'monthly_batch'
                                    CHECK (analysis_scope IN (
                                        'monthly_batch',    -- 月度批量扫描（全员）
                                        'single_employee',  -- 单员工深度分析
                                        'anomaly_triggered',-- 某员工触发红线
                                        'manual'            -- HR 手动触发
                                    )),
            -- 上下文
            employee_count          INTEGER NOT NULL DEFAULT 0,
            total_payroll_fen       BIGINT NOT NULL DEFAULT 0
                                    CHECK (total_payroll_fen >= 0),
            city                    VARCHAR(50),
                                    -- 用于关联城市薪资基准
            signals_snapshot        JSONB NOT NULL DEFAULT '{}'::jsonb,
                                    -- {employees: [...], policies: {...}}
            -- Sonnet 输出
            ranked_anomalies        JSONB NOT NULL DEFAULT '[]'::jsonb,
                                    -- [{employee_id, anomaly_type, severity, evidence,
                                    --   impact_fen, legal_risk}]
            remediation_actions     JSONB NOT NULL DEFAULT '[]'::jsonb,
                                    -- [{action, owner_role, deadline_days, impact_fen}]
            sonnet_analysis         TEXT,
            -- Prompt Cache 统计（D4 共用指标）
            model_id                VARCHAR(50) NOT NULL DEFAULT 'claude-sonnet-4-7',
            cache_read_tokens       INTEGER NOT NULL DEFAULT 0,
            cache_creation_tokens   INTEGER NOT NULL DEFAULT 0,
            input_tokens            INTEGER NOT NULL DEFAULT 0,
            output_tokens           INTEGER NOT NULL DEFAULT 0,
            -- 状态流（HR 审核）
            status                  VARCHAR(30) NOT NULL DEFAULT 'analyzed'
                                    CHECK (status IN (
                                        'pending',         -- 分析中
                                        'analyzed',        -- 已出报告
                                        'acted_on',        -- HRD 采纳并处理
                                        'dismissed',       -- 标记误报
                                        'escalated',       -- 升级到高管
                                        'error'
                                    )),
            reviewed_by             UUID,
            reviewed_at             TIMESTAMPTZ,
            -- 基础字段
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    # 唯一：同月同 scope 同 store 只一条 monthly_batch
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_salary_anomaly_monthly
            ON salary_anomaly_analyses (
                tenant_id,
                COALESCE(store_id, '00000000-0000-0000-0000-000000000000'::uuid),
                analysis_month
            )
            WHERE analysis_scope = 'monthly_batch' AND is_deleted = false
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_salary_anomaly_tenant_status
            ON salary_anomaly_analyses (tenant_id, status, created_at DESC)
            WHERE is_deleted = false
    """)
    # 单员工分析历史查询
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_salary_anomaly_employee_history
            ON salary_anomaly_analyses (tenant_id, employee_id, created_at DESC)
            WHERE employee_id IS NOT NULL AND is_deleted = false
    """)

    # RLS
    op.execute("ALTER TABLE salary_anomaly_analyses ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP POLICY IF EXISTS salary_anomaly_tenant_isolation ON salary_anomaly_analyses;
        CREATE POLICY salary_anomaly_tenant_isolation ON salary_anomaly_analyses
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true));
    """)

    # 注释
    op.execute("""
        COMMENT ON TABLE salary_anomaly_analyses IS
            'Sprint D4b: 薪资异常分析，Sonnet 4.7 + Prompt Cache 共享城市基准，
             每月 HRD 审核，省人工翻表时间';
        COMMENT ON COLUMN salary_anomaly_analyses.ranked_anomalies IS
            '[{employee_id, anomaly_type: below_market|overtime_excess|sudden_raise|commission_abuse|social_insurance_missing,
              severity: critical|high|medium|low, evidence, impact_fen, legal_risk}]';
        COMMENT ON COLUMN salary_anomaly_analyses.cache_read_tokens IS
            '与 D4a 共用城市基准 cache，跨分析类型共享可再提升命中率';
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS salary_anomaly_analyses CASCADE")
