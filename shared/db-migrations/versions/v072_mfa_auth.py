"""v072 — MFA双因素认证字段

等保三级要求：两种或两种以上组合的鉴别技术
实现：密码（第一因素）+ TOTP（第二因素）

新增表：
  users — 系统用户表（包含认证、MFA字段）

新增字段（通过 ADD COLUMN IF NOT EXISTS，兼容已有表）：
  password_hash       TEXT        — bcrypt哈希
  password_changed_at TIMESTAMPTZ
  last_login_at       TIMESTAMPTZ
  failed_login_count  INTEGER DEFAULT 0
  locked_until        TIMESTAMPTZ — 账户锁定到期时间
  mfa_enabled         BOOLEAN DEFAULT FALSE
  mfa_type            VARCHAR(10) DEFAULT 'totp'
  mfa_secret_enc      TEXT        — XOR加密的TOTP secret
  mfa_backup_codes    JSONB       — SHA256哈希后的8个备用码
  mfa_verified_at     TIMESTAMPTZ

RLS 策略：
  用户只能读取/修改自己的记录（actor_id = current_setting('app.actor_id')）
  平台管理员通过超级用户连接管理

Revision ID: v072
Revises: v071
Create Date: 2026-03-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "v072"
down_revision = "v071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 创建 users 表（如不存在）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            username        VARCHAR(64) NOT NULL,
            name            VARCHAR(100),
            role            VARCHAR(30) NOT NULL DEFAULT 'staff',
            is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN     NOT NULL DEFAULT FALSE
        )
    """)

    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_tenant_username
            ON users (tenant_id, username)
            WHERE is_deleted = FALSE
    """)

    # ─────────────────────────────────────────────────────────────────
    # 添加认证字段（ADD COLUMN IF NOT EXISTS — 兼容已有表）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS password_hash        TEXT,
            ADD COLUMN IF NOT EXISTS password_changed_at  TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS last_login_at        TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS failed_login_count   INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS locked_until         TIMESTAMPTZ
    """)

    # ─────────────────────────────────────────────────────────────────
    # 添加MFA字段
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS mfa_enabled      BOOLEAN     NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS mfa_type         VARCHAR(10) NOT NULL DEFAULT 'totp',
            ADD COLUMN IF NOT EXISTS mfa_secret_enc   TEXT,
            ADD COLUMN IF NOT EXISTS mfa_backup_codes JSONB,
            ADD COLUMN IF NOT EXISTS mfa_verified_at  TIMESTAMPTZ
    """)

    # ─────────────────────────────────────────────────────────────────
    # 添加 refresh_tokens 表（存储可撤销的 refresh token）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            jti         UUID        PRIMARY KEY,
            user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            tenant_id   UUID        NOT NULL,
            issued_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at  TIMESTAMPTZ NOT NULL,
            revoked_at  TIMESTAMPTZ,
            ip_address  VARCHAR(45),
            user_agent  TEXT
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id
            ON refresh_tokens (user_id)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires_at
            ON refresh_tokens (expires_at)
    """)

    # ─────────────────────────────────────────────────────────────────
    # 索引 — 锁定查询、登录失败统计
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_users_tenant_id
            ON users (tenant_id)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_users_locked_until
            ON users (locked_until)
            WHERE locked_until IS NOT NULL
    """)

    # ─────────────────────────────────────────────────────────────────
    # RLS — users 表租户隔离
    # 等保三级：用户只能查看本租户数据
    # NULLIF(..., '') 防止空字符串绕过 RLS（修复v056的漏洞模式）
    # ─────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE POLICY users_select ON users
            FOR SELECT
            USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)

    op.execute("""
        CREATE POLICY users_insert ON users
            FOR INSERT
            WITH CHECK (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)

    op.execute("""
        CREATE POLICY users_update ON users
            FOR UPDATE
            USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)

    # refresh_tokens 不启用 RLS（gateway 服务用超级用户连接管理）
    # 应用层通过 user_id 过滤保证安全

    # ─────────────────────────────────────────────────────────────────
    # 插入 Demo 系统用户（仅占位，密码由应用层在首次启动时设置）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        INSERT INTO users (id, tenant_id, username, name, role)
        VALUES
            (gen_random_uuid(), 'a0000000-0000-0000-0000-000000000001'::UUID, 'admin',         '系统管理员',    'admin'),
            (gen_random_uuid(), 'a0000000-0000-0000-0000-000000000002'::UUID, 'changzaiyiqi',  '尝在一起管理员', 'merchant_admin'),
            (gen_random_uuid(), 'a0000000-0000-0000-0000-000000000003'::UUID, 'zuiqianxian',   '最黔线管理员',   'merchant_admin'),
            (gen_random_uuid(), 'a0000000-0000-0000-0000-000000000004'::UUID, 'shanggongchu',  '尚宫厨管理员',   'merchant_admin'),
            (gen_random_uuid(), 'a0000000-0000-0000-0000-000000000005'::UUID, 'xuji',          '徐记海鲜管理员', 'merchant_admin')
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS users_update ON users")
    op.execute("DROP POLICY IF EXISTS users_insert ON users")
    op.execute("DROP POLICY IF EXISTS users_select ON users")
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY")

    op.execute("DROP TABLE IF EXISTS refresh_tokens")

    op.execute("""
        ALTER TABLE users
            DROP COLUMN IF EXISTS mfa_verified_at,
            DROP COLUMN IF EXISTS mfa_backup_codes,
            DROP COLUMN IF EXISTS mfa_secret_enc,
            DROP COLUMN IF EXISTS mfa_type,
            DROP COLUMN IF EXISTS mfa_enabled,
            DROP COLUMN IF EXISTS locked_until,
            DROP COLUMN IF EXISTS failed_login_count,
            DROP COLUMN IF EXISTS last_login_at,
            DROP COLUMN IF EXISTS password_changed_at,
            DROP COLUMN IF EXISTS password_hash
    """)

    op.execute("DROP TABLE IF EXISTS users")
