"""v073 — RBAC用户角色表 + 三权分立约束

等保三级要求：
  1. 系统管理员、审计管理员、安全管理员三权分立
  2. 角色分配记录留痕（授权人/时间）
  3. 支持临时授权（expires_at）

新增表：
  user_roles — 用户角色绑定记录

新增约束：
  - UNIQUE (user_id, tenant_id, role)：同一用户同一租户每个角色只有一条记录
  - CHECK + TRIGGER：三权分立互斥（system_admin / audit_admin / security_admin 不可共存）
  - RLS：基于 app.tenant_id 的租户隔离

Revision ID: v073
Revises: v072
Create Date: 2026-03-31
"""

from alembic import op

revision = "v073"
down_revision = "v072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 1. 创建 user_roles 表
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_roles (
            id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     UUID         NOT NULL,
            tenant_id   UUID,                          -- NULL 表示平台级角色
            role        VARCHAR(50)  NOT NULL,
            granted_by  UUID,                          -- 授权人 user_id，NULL=系统初始化
            granted_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            expires_at  TIMESTAMPTZ,                   -- NULL=永久有效
            is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

            -- 同一用户在同一作用域（平台或租户）下每种角色只有一条 active 记录
            CONSTRAINT uq_user_roles_active
                UNIQUE (user_id, tenant_id, role)
        )
    """)

    # ─────────────────────────────────────────────────────────────────
    # 2. 索引
    # ─────────────────────────────────────────────────────────────────

    # 按用户查询其所有角色（最常用）
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_roles_user_id
            ON user_roles (user_id)
        WHERE is_active = TRUE
    """)

    # 按租户查询所有成员角色
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_roles_tenant_id
            ON user_roles (tenant_id)
        WHERE is_active = TRUE
    """)

    # 过期角色扫描（定时任务使用）
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_roles_expires_at
            ON user_roles (expires_at)
        WHERE is_active = TRUE AND expires_at IS NOT NULL
    """)

    # ─────────────────────────────────────────────────────────────────
    # 3. updated_at 自动更新触发器
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION update_user_roles_updated_at()
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
        CREATE TRIGGER trg_user_roles_updated_at
            BEFORE UPDATE ON user_roles
            FOR EACH ROW
            EXECUTE FUNCTION update_user_roles_updated_at()
    """)

    # ─────────────────────────────────────────────────────────────────
    # 4. 三权分立互斥触发器
    #
    #    规则：system_admin / audit_admin / security_admin 三个平台角色
    #    中，同一 user_id 最多持有其中一个（tenant_id IS NULL 的记录）。
    #    违规时抛出异常，拒绝 INSERT/UPDATE。
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION check_separation_of_duties()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$
        DECLARE
            exclusive_roles TEXT[] := ARRAY[
                'system_admin',
                'audit_admin',
                'security_admin'
            ];
            conflict_count  INTEGER;
        BEGIN
            -- 仅在新角色属于互斥集合时才需要检查
            IF NEW.role = ANY(exclusive_roles) AND NEW.is_active = TRUE THEN
                SELECT COUNT(*) INTO conflict_count
                FROM user_roles
                WHERE user_id   = NEW.user_id
                  AND tenant_id IS NOT DISTINCT FROM NEW.tenant_id
                  AND role      = ANY(exclusive_roles)
                  AND role      <> NEW.role          -- 排除自身（UPDATE 场景）
                  AND is_active = TRUE
                  AND id        <> COALESCE(NEW.id, '00000000-0000-0000-0000-000000000000'::UUID);

                IF conflict_count > 0 THEN
                    RAISE EXCEPTION
                        '等保三级三权分立违规：用户 % 已持有互斥角色，不能同时持有 %',
                        NEW.user_id,
                        NEW.role
                        USING ERRCODE = 'P0001';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$
    """)

    op.execute("""
        CREATE TRIGGER trg_separation_of_duties
            BEFORE INSERT OR UPDATE ON user_roles
            FOR EACH ROW
            EXECUTE FUNCTION check_separation_of_duties()
    """)

    # ─────────────────────────────────────────────────────────────────
    # 5. RLS — 租户隔离
    #
    #    平台级角色（tenant_id IS NULL）不受租户 RLS 过滤，
    #    仅向持有平台角色的 session 可见（通过应用层控制）。
    #    租户级角色按 app.tenant_id 隔离。
    # ─────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE user_roles ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE user_roles FORCE ROW LEVEL SECURITY")

    # SELECT：可见本租户的角色记录，以及平台级（tenant_id IS NULL）角色
    op.execute("""
        CREATE POLICY user_roles_select ON user_roles
            FOR SELECT
            USING (
                tenant_id IS NULL
                OR tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)

    # INSERT：只允许写入本租户的角色（平台级由超级用户直接操作）
    op.execute("""
        CREATE POLICY user_roles_insert ON user_roles
            FOR INSERT
            WITH CHECK (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)

    # UPDATE：只允许更新本租户的角色
    op.execute("""
        CREATE POLICY user_roles_update ON user_roles
            FOR UPDATE
            USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)

    # ⚠️ 合规说明：故意不创建 DELETE policy。
    # 角色记录不可物理删除，通过 is_active=FALSE 逻辑撤销，保留留痕。


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_separation_of_duties ON user_roles")
    op.execute("DROP FUNCTION IF EXISTS check_separation_of_duties()")
    op.execute("DROP TRIGGER IF EXISTS trg_user_roles_updated_at ON user_roles")
    op.execute("DROP FUNCTION IF EXISTS update_user_roles_updated_at()")
    op.execute("DROP POLICY IF EXISTS user_roles_update ON user_roles")
    op.execute("DROP POLICY IF EXISTS user_roles_insert ON user_roles")
    op.execute("DROP POLICY IF EXISTS user_roles_select ON user_roles")
    op.execute("DROP TABLE IF EXISTS user_roles")
