"""薪资计算系统 — 完整薪资模块数据库迁移

新增表：
  salary_schemes              — 薪资方案定义（月薪/时薪/提成制）
  employee_salary_configs     — 员工薪资配置（方案绑定/生效区间）
  payroll_records_v2          — 月度薪资记录（完整字段，status 状态机）
  attendance_records          — 考勤打卡记录（上下班/工时/加班/缺勤类型）
  social_insurance_configs    — 五险一金地区费率配置

RLS 策略：
  全部使用 v006+ 标准安全模式（NULLIF + 4操作 + FORCE ROW LEVEL SECURITY）

Revision ID: v061
Revises: v060
Create Date: 2026-03-31
"""

from __future__ import annotations

from typing import Union

from alembic import op

revision: str = "v061"
down_revision: Union[str, None] = "v060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 1. salary_schemes — 薪资方案
    #    定义租户下可用的薪资计算方案（月薪/时薪/提成制）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS salary_schemes (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID        NOT NULL,
            name                VARCHAR(100) NOT NULL,
            scheme_type         VARCHAR(20)  NOT NULL
                CHECK (scheme_type IN (
                    'monthly',      -- 月薪制
                    'hourly',       -- 时薪制
                    'commission'    -- 提成制（底薪+提成）
                )),
            base_salary_fen     BIGINT       NOT NULL DEFAULT 0
                CHECK (base_salary_fen >= 0),           -- 月薪/底薪（分）
            hourly_rate_fen     BIGINT       NOT NULL DEFAULT 0
                CHECK (hourly_rate_fen >= 0),           -- 时薪（分，时薪制适用）
            overtime_multiplier NUMERIC(4,2) NOT NULL DEFAULT 1.50
                CHECK (overtime_multiplier >= 1.0),     -- 加班倍率（默认1.5x）
            is_active           BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted          BOOLEAN      NOT NULL DEFAULT FALSE
        );

        COMMENT ON TABLE salary_schemes IS
            '薪资方案：租户级别配置，支持月薪/时薪/提成三种计薪类型';
        COMMENT ON COLUMN salary_schemes.base_salary_fen IS
            '月薪标准或提成底薪，单位为分（fen），避免浮点精度问题';
        COMMENT ON COLUMN salary_schemes.hourly_rate_fen IS
            '时薪标准，单位为分（fen），时薪制必填，月薪制可为0';
        COMMENT ON COLUMN salary_schemes.overtime_multiplier IS
            '加班基础倍率，实际加班费按类型再乘以1.5/2.0/3.0系数';

        CREATE INDEX IF NOT EXISTS ix_salary_schemes_tenant_active
            ON salary_schemes (tenant_id, is_active)
            WHERE is_deleted = FALSE;
    """)

    # RLS: salary_schemes
    op.execute("""
        ALTER TABLE salary_schemes ENABLE ROW LEVEL SECURITY;
        ALTER TABLE salary_schemes FORCE ROW LEVEL SECURITY;

        CREATE POLICY salary_schemes_tenant_isolation
            ON salary_schemes
            AS PERMISSIVE FOR ALL
            USING (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            )
            WITH CHECK (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
    """)

    # ─────────────────────────────────────────────────────────────────
    # 2. employee_salary_configs — 员工薪资配置
    #    将员工与薪资方案绑定，支持时间区间，实现调薪历史追踪
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS employee_salary_configs (
            id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID        NOT NULL,
            employee_id             UUID        NOT NULL,
            scheme_id               UUID        REFERENCES salary_schemes(id),
            -- 允许独立覆盖方案值（个人谈判工资）
            base_salary_fen         BIGINT       NOT NULL DEFAULT 0
                CHECK (base_salary_fen >= 0),
            commission_rate         NUMERIC(5,4) NOT NULL DEFAULT 0
                CHECK (commission_rate >= 0 AND commission_rate <= 1),
            social_insurance_base_fen BIGINT     NOT NULL DEFAULT 0
                CHECK (social_insurance_base_fen >= 0), -- 社保缴费基数（分）
            effective_from          DATE         NOT NULL,
            effective_to            DATE,               -- NULL 表示当前有效
            created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN      NOT NULL DEFAULT FALSE,

            CONSTRAINT uq_emp_salary_config_current
                EXCLUDE USING gist (
                    employee_id WITH =,
                    daterange(effective_from, COALESCE(effective_to, '9999-12-31'), '[]') WITH &&
                ) WHERE (is_deleted = FALSE)
        );

        COMMENT ON TABLE employee_salary_configs IS
            '员工薪资配置：员工与薪资方案的绑定关系，支持有效期区间追踪调薪历史';
        COMMENT ON COLUMN employee_salary_configs.commission_rate IS
            '提成比例（0.0000-1.0000），提成制方案时使用';
        COMMENT ON COLUMN employee_salary_configs.social_insurance_base_fen IS
            '个人社保缴费基数，可独立设置（未配置时引擎使用合同基本工资）';
        COMMENT ON COLUMN employee_salary_configs.effective_to IS
            'NULL 代表当前有效配置；调薪时将旧记录 effective_to 设为新记录 effective_from - 1';

        CREATE INDEX IF NOT EXISTS ix_emp_salary_configs_tenant_emp
            ON employee_salary_configs (tenant_id, employee_id)
            WHERE is_deleted = FALSE;

        CREATE INDEX IF NOT EXISTS ix_emp_salary_configs_tenant_scheme
            ON employee_salary_configs (tenant_id, scheme_id)
            WHERE is_deleted = FALSE;
    """)

    # RLS: employee_salary_configs
    op.execute("""
        ALTER TABLE employee_salary_configs ENABLE ROW LEVEL SECURITY;
        ALTER TABLE employee_salary_configs FORCE ROW LEVEL SECURITY;

        CREATE POLICY employee_salary_configs_tenant_isolation
            ON employee_salary_configs
            AS PERMISSIVE FOR ALL
            USING (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            )
            WITH CHECK (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
    """)

    # ─────────────────────────────────────────────────────────────────
    # 3. payroll_records_v2 — 月度薪资记录（完整版）
    #    存储每月每员工最终薪资单，含各分项金额和状态机流转
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS payroll_records_v2 (
            id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID        NOT NULL,
            store_id                UUID        NOT NULL,
            employee_id             UUID        NOT NULL,
            period_year             SMALLINT    NOT NULL
                CHECK (period_year >= 2020 AND period_year <= 2099),
            period_month            SMALLINT    NOT NULL
                CHECK (period_month >= 1 AND period_month <= 12),

            -- 考勤汇总
            work_days               SMALLINT    NOT NULL DEFAULT 0
                CHECK (work_days >= 0),
            work_hours              NUMERIC(6,2) NOT NULL DEFAULT 0
                CHECK (work_hours >= 0),
            overtime_hours          NUMERIC(6,2) NOT NULL DEFAULT 0
                CHECK (overtime_hours >= 0),

            -- 收入各分项（分）
            base_salary_fen         BIGINT       NOT NULL DEFAULT 0,
            commission_fen          BIGINT       NOT NULL DEFAULT 0,
            overtime_pay_fen        BIGINT       NOT NULL DEFAULT 0,
            bonus_fen               BIGINT       NOT NULL DEFAULT 0,
            deductions_fen          BIGINT       NOT NULL DEFAULT 0,  -- 考勤/迟到等扣款
            social_insurance_fen    BIGINT       NOT NULL DEFAULT 0,  -- 个人五险（分）
            housing_fund_fen        BIGINT       NOT NULL DEFAULT 0,  -- 个人公积金（分）

            -- 汇总（分）
            gross_salary_fen        BIGINT       NOT NULL DEFAULT 0,  -- 应发
            net_salary_fen          BIGINT       NOT NULL DEFAULT 0,  -- 实发

            -- 状态机
            status                  VARCHAR(20)  NOT NULL DEFAULT 'draft'
                CHECK (status IN (
                    'draft',        -- 草稿（引擎计算后生成）
                    'confirmed',    -- 已确认（财务/HR确认）
                    'paid'          -- 已发放
                )),
            confirmed_at            TIMESTAMPTZ,
            paid_at                 TIMESTAMPTZ,
            created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN      NOT NULL DEFAULT FALSE,

            -- 同一员工同一月份只能有一条有效薪资单
            CONSTRAINT uq_payroll_records_v2_emp_period
                UNIQUE (tenant_id, employee_id, period_year, period_month)
                DEFERRABLE INITIALLY DEFERRED
        );

        COMMENT ON TABLE payroll_records_v2 IS
            '月度薪资记录：每月每员工一条，状态机 draft→confirmed→paid，所有金额以分为单位';
        COMMENT ON COLUMN payroll_records_v2.deductions_fen IS
            '考勤扣款合计（迟到+早退+缺勤），注意社保/公积金单独列字段';
        COMMENT ON COLUMN payroll_records_v2.gross_salary_fen IS
            '应发合计 = base + commission + overtime + bonus - deductions';
        COMMENT ON COLUMN payroll_records_v2.net_salary_fen IS
            '实发 = gross - social_insurance_fen - housing_fund_fen';

        CREATE INDEX IF NOT EXISTS ix_payroll_records_v2_tenant_period
            ON payroll_records_v2 (tenant_id, period_year, period_month)
            WHERE is_deleted = FALSE;

        CREATE INDEX IF NOT EXISTS ix_payroll_records_v2_tenant_store_period
            ON payroll_records_v2 (tenant_id, store_id, period_year, period_month)
            WHERE is_deleted = FALSE;

        CREATE INDEX IF NOT EXISTS ix_payroll_records_v2_tenant_emp
            ON payroll_records_v2 (tenant_id, employee_id)
            WHERE is_deleted = FALSE;

        CREATE INDEX IF NOT EXISTS ix_payroll_records_v2_status
            ON payroll_records_v2 (tenant_id, status)
            WHERE is_deleted = FALSE;
    """)

    # RLS: payroll_records_v2
    op.execute("""
        ALTER TABLE payroll_records_v2 ENABLE ROW LEVEL SECURITY;
        ALTER TABLE payroll_records_v2 FORCE ROW LEVEL SECURITY;

        CREATE POLICY payroll_records_v2_tenant_isolation
            ON payroll_records_v2
            AS PERMISSIVE FOR ALL
            USING (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            )
            WITH CHECK (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
    """)

    # ─────────────────────────────────────────────────────────────────
    # 4. attendance_records — 员工考勤打卡记录
    #    每天每员工一条，记录上下班时间和实际工时
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS attendance_records (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            employee_id     UUID        NOT NULL,
            work_date       DATE        NOT NULL,
            clock_in        TIMESTAMPTZ,
            clock_out       TIMESTAMPTZ,
            work_hours      NUMERIC(5,2) NOT NULL DEFAULT 0
                CHECK (work_hours >= 0),
            overtime_hours  NUMERIC(5,2) NOT NULL DEFAULT 0
                CHECK (overtime_hours >= 0),
            absence_type    VARCHAR(20)
                CHECK (absence_type IS NULL OR absence_type IN (
                    'sick',         -- 病假
                    'personal',     -- 事假
                    'annual',       -- 年假
                    'absent',       -- 旷工
                    'holiday',      -- 法定节假日
                    'compensatory'  -- 调休
                )),
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN      NOT NULL DEFAULT FALSE,

            -- 每人每天只有一条考勤记录
            CONSTRAINT uq_attendance_records_emp_date
                UNIQUE (tenant_id, employee_id, work_date)
        );

        COMMENT ON TABLE attendance_records IS
            '员工考勤打卡记录：每天每员工一条，存储上下班时刻、实际工时、加班工时和缺勤类型';
        COMMENT ON COLUMN attendance_records.absence_type IS
            'NULL 表示正常出勤；非 NULL 时 work_hours 通常为 0';
        COMMENT ON COLUMN attendance_records.overtime_hours IS
            '当日加班工时，由排班引擎或人工录入计算，用于月度薪资汇总';

        CREATE INDEX IF NOT EXISTS ix_attendance_records_tenant_emp_date
            ON attendance_records (tenant_id, employee_id, work_date)
            WHERE is_deleted = FALSE;

        CREATE INDEX IF NOT EXISTS ix_attendance_records_tenant_date
            ON attendance_records (tenant_id, work_date)
            WHERE is_deleted = FALSE;
    """)

    # RLS: attendance_records
    op.execute("""
        ALTER TABLE attendance_records ENABLE ROW LEVEL SECURITY;
        ALTER TABLE attendance_records FORCE ROW LEVEL SECURITY;

        CREATE POLICY attendance_records_tenant_isolation
            ON attendance_records
            AS PERMISSIVE FOR ALL
            USING (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            )
            WITH CHECK (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
    """)

    # ─────────────────────────────────────────────────────────────────
    # 5. social_insurance_configs — 五险一金地区费率配置
    #    按地区存储最新费率，支持历史版本追踪（effective_from）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS social_insurance_configs (
            id                              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id                       UUID        NOT NULL,
            region                          VARCHAR(50)  NOT NULL,  -- 如 "changsha"/"beijing"/"shanghai"
            -- 养老保险费率
            pension_rate_employee           NUMERIC(5,4) NOT NULL DEFAULT 0.0800,
            pension_rate_employer           NUMERIC(5,4) NOT NULL DEFAULT 0.1600,
            -- 医疗保险费率
            medical_rate_employee           NUMERIC(5,4) NOT NULL DEFAULT 0.0200,
            medical_rate_employer           NUMERIC(5,4) NOT NULL DEFAULT 0.0800,
            -- 失业保险费率
            unemployment_rate_employee      NUMERIC(5,4) NOT NULL DEFAULT 0.0050,
            unemployment_rate_employer      NUMERIC(5,4) NOT NULL DEFAULT 0.0050,
            -- 住房公积金费率（个人=企业对等）
            housing_fund_rate               NUMERIC(5,4) NOT NULL DEFAULT 0.0700,
            effective_from                  DATE         NOT NULL,
            created_at                      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at                      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted                      BOOLEAN      NOT NULL DEFAULT FALSE
        );

        COMMENT ON TABLE social_insurance_configs IS
            '五险一金地区费率配置：按地区+生效日期存储，支持多地区差异费率和费率调整历史';
        COMMENT ON COLUMN social_insurance_configs.region IS
            '地区标识符（拼音小写），如 changsha/beijing/shanghai，与员工归属门店城市对应';
        COMMENT ON COLUMN social_insurance_configs.housing_fund_rate IS
            '公积金缴存比例，个人与企业对等，各地法规范围 5%-12%';

        CREATE INDEX IF NOT EXISTS ix_si_configs_tenant_region
            ON social_insurance_configs (tenant_id, region, effective_from DESC)
            WHERE is_deleted = FALSE;
    """)

    # RLS: social_insurance_configs
    op.execute("""
        ALTER TABLE social_insurance_configs ENABLE ROW LEVEL SECURITY;
        ALTER TABLE social_insurance_configs FORCE ROW LEVEL SECURITY;

        CREATE POLICY social_insurance_configs_tenant_isolation
            ON social_insurance_configs
            AS PERMISSIVE FOR ALL
            USING (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            )
            WITH CHECK (
                tenant_id IS NOT NULL
                AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID
            );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS social_insurance_configs CASCADE;")
    op.execute("DROP TABLE IF EXISTS attendance_records CASCADE;")
    op.execute("DROP TABLE IF EXISTS payroll_records_v2 CASCADE;")
    op.execute("DROP TABLE IF EXISTS employee_salary_configs CASCADE;")
    op.execute("DROP TABLE IF EXISTS salary_schemes CASCADE;")
