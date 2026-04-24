"""v075 — 角色10级权限体系：扩展roles表 + 预设默认配置

新增字段（ALTER TABLE role_configs）：
  level               — 1-10级，数字越大权限越高
  max_discount_rate   — 最大折扣率(%)，100.0=不打折，0=不允许打折
  max_wipeoff_fen     — 最大抹零金额(分)
  max_gift_fen        — 最大赠送金额(分)
  data_query_days     — 可查询数据天数
  can_void_order      — 是否可退单
  can_modify_price    — 是否可改价
  can_override_discount — 是否可超额折扣（需上级审批）

预设10级默认角色配置：
  Level 1  实习生    折扣≥95%, 抹零=0, 赠送=0, 查7天
  Level 2  兼职员工  折扣≥92%, 抹零=0, 赠送=0, 查7天
  Level 3  服务员    折扣≥90%, 抹零≤500, 赠送=0, 查30天
  Level 4  领班      折扣≥88%, 抹零≤800, 赠送≤2000, 查30天
  Level 5  收银员    折扣≥85%, 抹零≤1000, 赠送≤5000, 查30天
  Level 6  主管      折扣≥80%, 抹零≤2000, 赠送≤20000, 查60天, 可改价
  Level 7  店长      折扣≥70%, 抹零≤3000, 赠送≤50000, 查90天, 可退单+改价
  Level 8  大区经理  折扣≥60%, 抹零≤5000, 赠送≤100000, 查180天, 可退单+改价
  Level 9  区域总监  折扣≥50%, 抹零≤10000, 赠送≤200000, 查365天, 全操作
  Level 10 管理员    无限制

Revision ID: v075
Revises: v074
Create Date: 2026-03-31
"""

from alembic import op

revision = "v076"
down_revision = "v075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 0. 确保 role_configs 表存在（未在前序迁移中建立）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS role_configs (
            id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID         NOT NULL,
            name        VARCHAR(50)  NOT NULL,
            description TEXT,
            is_deleted  BOOLEAN      NOT NULL DEFAULT FALSE,
            created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_role_configs_tenant_name UNIQUE (tenant_id, name)
        )
    """)
    op.execute("ALTER TABLE role_configs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE role_configs FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS role_configs_rls_select ON role_configs")
    op.execute("""
        CREATE POLICY role_configs_rls_select ON role_configs
            FOR SELECT USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)
    op.execute("DROP POLICY IF EXISTS role_configs_rls_insert ON role_configs")
    op.execute("""
        CREATE POLICY role_configs_rls_insert ON role_configs
            FOR INSERT WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)
    op.execute("DROP POLICY IF EXISTS role_configs_rls_update ON role_configs")
    op.execute("""
        CREATE POLICY role_configs_rls_update ON role_configs
            FOR UPDATE USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)
    op.execute("DROP POLICY IF EXISTS role_configs_rls_delete ON role_configs")
    op.execute("""
        CREATE POLICY role_configs_rls_delete ON role_configs
            FOR DELETE USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)
    """)

    # ─────────────────────────────────────────────────────────────────
    # 1. 扩展 role_configs 表（如已有字段则跳过）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE role_configs
            ADD COLUMN IF NOT EXISTS level INTEGER NOT NULL DEFAULT 5
                CHECK (level >= 1 AND level <= 10),
            ADD COLUMN IF NOT EXISTS max_discount_rate NUMERIC(5,2) NOT NULL DEFAULT 100.0
                CHECK (max_discount_rate >= 0 AND max_discount_rate <= 100),
            ADD COLUMN IF NOT EXISTS max_wipeoff_fen INTEGER NOT NULL DEFAULT 0
                CHECK (max_wipeoff_fen >= 0),
            ADD COLUMN IF NOT EXISTS max_gift_fen_v2 INTEGER NOT NULL DEFAULT 0
                CHECK (max_gift_fen_v2 >= 0),
            ADD COLUMN IF NOT EXISTS data_query_days INTEGER NOT NULL DEFAULT 30
                CHECK (data_query_days >= 0),
            ADD COLUMN IF NOT EXISTS can_void_order BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS can_modify_price BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS can_override_discount BOOLEAN NOT NULL DEFAULT FALSE
    """)

    # ─────────────────────────────────────────────────────────────────
    # 2. 为 level 字段创建索引（按角色级别过滤是高频操作）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_role_configs_level
            ON role_configs (tenant_id, level)
        WHERE is_deleted = FALSE
    """)

    # ─────────────────────────────────────────────────────────────────
    # 3. 创建「角色级别默认模板」表（系统级，不属于任何租户）
    #    租户创建角色时可参考此模板快速填充默认值
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS role_level_defaults (
            level                 INTEGER PRIMARY KEY CHECK (level >= 1 AND level <= 10),
            level_name            VARCHAR(30) NOT NULL,
            max_discount_rate     NUMERIC(5,2) NOT NULL DEFAULT 100.0,
            max_wipeoff_fen       INTEGER NOT NULL DEFAULT 0,
            max_gift_fen          INTEGER NOT NULL DEFAULT 0,
            data_query_days       INTEGER NOT NULL DEFAULT 30,
            can_void_order        BOOLEAN NOT NULL DEFAULT FALSE,
            can_modify_price      BOOLEAN NOT NULL DEFAULT FALSE,
            can_override_discount BOOLEAN NOT NULL DEFAULT FALSE,
            description           TEXT,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # ─────────────────────────────────────────────────────────────────
    # 4. 预插入10级默认配置（ON CONFLICT DO NOTHING 保证幂等）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        INSERT INTO role_level_defaults
            (level, level_name, max_discount_rate, max_wipeoff_fen, max_gift_fen,
             data_query_days, can_void_order, can_modify_price, can_override_discount, description)
        VALUES
            (1,  '实习生',   95.0,  0,      0,       7,   FALSE, FALSE, FALSE, '仅限基础点餐操作，不允许折扣/赠送/抹零'),
            (2,  '兼职员工', 92.0,  0,      0,       7,   FALSE, FALSE, FALSE, '基础服务权限，极小折扣余地'),
            (3,  '服务员',   90.0,  500,    0,       30,  FALSE, FALSE, FALSE, '标准服务员，可小幅抹零，不可赠送'),
            (4,  '领班',     88.0,  800,    2000,    30,  FALSE, FALSE, FALSE, '小额赠送权限，小幅折扣'),
            (5,  '收银员',   85.0,  1000,   5000,    30,  FALSE, FALSE, FALSE, '收银标准配置，折扣最多8.5折'),
            (6,  '主管',     80.0,  2000,   20000,   60,  FALSE, TRUE,  FALSE, '可改价，折扣最多8折'),
            (7,  '店长',     70.0,  3000,   50000,   90,  TRUE,  TRUE,  TRUE,  '可退单改价，7折权限，超限需审批'),
            (8,  '大区经理', 60.0,  5000,   100000,  180, TRUE,  TRUE,  TRUE,  '多店管理，6折权限'),
            (9,  '区域总监', 50.0,  10000,  200000,  365, TRUE,  TRUE,  TRUE,  '全操作权限，5折下限'),
            (10, '管理员',   0.0,   999999, 999999,  9999,TRUE,  TRUE,  TRUE,  '系统管理员，无限制（0%折扣率=无限制）')
        ON CONFLICT (level) DO NOTHING
    """)

    # ─────────────────────────────────────────────────────────────────
    # 5. 创建「员工角色绑定」表（员工↔角色配置的多对一关系）
    #    每个员工在每个门店有一个生效的角色配置
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS employee_role_assignments (
            id             UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      UUID         NOT NULL,
            employee_id    UUID         NOT NULL,
            store_id       UUID,                      -- NULL = 全品牌生效
            role_config_id UUID         NOT NULL,     -- 指向 role_configs.id
            assigned_by    UUID,                      -- 授权人 employee_id
            assigned_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            expires_at     TIMESTAMPTZ,               -- NULL = 永久有效
            is_active      BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

            -- 每个员工在每个门店只有一条生效记录
            CONSTRAINT uq_employee_store_role_active
                UNIQUE (tenant_id, employee_id, store_id)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_era_employee_id
            ON employee_role_assignments (tenant_id, employee_id)
        WHERE is_active = TRUE
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_era_store_id
            ON employee_role_assignments (tenant_id, store_id)
        WHERE is_active = TRUE
    """)

    # ─────────────────────────────────────────────────────────────────
    # 6. employee_role_assignments — updated_at 自动触发器
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION update_era_updated_at()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$
    """)

    op.execute("""
        CREATE TRIGGER trg_era_updated_at
            BEFORE UPDATE ON employee_role_assignments
            FOR EACH ROW
            EXECUTE FUNCTION update_era_updated_at()
    """)

    # ─────────────────────────────────────────────────────────────────
    # 7. RLS — employee_role_assignments 租户隔离
    # ─────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE employee_role_assignments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE employee_role_assignments FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE POLICY era_select ON employee_role_assignments
            FOR SELECT
            USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)

    op.execute("""
        CREATE POLICY era_insert ON employee_role_assignments
            FOR INSERT
            WITH CHECK (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)

    op.execute("""
        CREATE POLICY era_update ON employee_role_assignments
            FOR UPDATE
            USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)

    # ─────────────────────────────────────────────────────────────────
    # 8. 权限检查日志表（留痕合规）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS permission_check_logs (
            id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID         NOT NULL,
            employee_id     UUID         NOT NULL,
            store_id        UUID,
            operation       VARCHAR(50)  NOT NULL,   -- discount/wipeoff/gift/void_order/modify_price
            amount_fen      INTEGER,                  -- 涉及金额(分)，折扣时为折扣率*100
            role_level      INTEGER,
            allowed         BOOLEAN      NOT NULL,
            require_approval BOOLEAN     NOT NULL DEFAULT FALSE,
            approver_min_level INTEGER,
            deny_reason     TEXT,
            checked_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            request_ip      VARCHAR(45),
            order_id        UUID
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_pcl_employee_id
            ON permission_check_logs (tenant_id, employee_id, checked_at DESC)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_pcl_operation
            ON permission_check_logs (tenant_id, operation, checked_at DESC)
        WHERE allowed = FALSE
    """)

    op.execute("ALTER TABLE permission_check_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE permission_check_logs FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE POLICY pcl_select ON permission_check_logs
            FOR SELECT
            USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)

    op.execute("""
        CREATE POLICY pcl_insert ON permission_check_logs
            FOR INSERT
            WITH CHECK (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)


def downgrade() -> None:
    # 删除权限检查日志
    op.execute("DROP POLICY IF EXISTS pcl_insert ON permission_check_logs")
    op.execute("DROP POLICY IF EXISTS pcl_select ON permission_check_logs")
    op.execute("DROP TABLE IF EXISTS permission_check_logs")

    # 删除员工角色绑定
    op.execute("DROP TRIGGER IF EXISTS trg_era_updated_at ON employee_role_assignments")
    op.execute("DROP FUNCTION IF EXISTS update_era_updated_at()")
    op.execute("DROP POLICY IF EXISTS era_update ON employee_role_assignments")
    op.execute("DROP POLICY IF EXISTS era_insert ON employee_role_assignments")
    op.execute("DROP POLICY IF EXISTS era_select ON employee_role_assignments")
    op.execute("DROP TABLE IF EXISTS employee_role_assignments")

    # 删除角色级别默认模板
    op.execute("DROP TABLE IF EXISTS role_level_defaults")

    # 删除索引
    op.execute("DROP INDEX IF EXISTS idx_role_configs_level")

    # 删除 role_configs 新增列
    op.execute("""
        ALTER TABLE role_configs
            DROP COLUMN IF EXISTS level,
            DROP COLUMN IF EXISTS max_discount_rate,
            DROP COLUMN IF EXISTS max_wipeoff_fen,
            DROP COLUMN IF EXISTS max_gift_fen_v2,
            DROP COLUMN IF EXISTS data_query_days,
            DROP COLUMN IF EXISTS can_void_order,
            DROP COLUMN IF EXISTS can_modify_price,
            DROP COLUMN IF EXISTS can_override_discount
    """)
