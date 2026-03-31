"""v070 — 操作审计日志表

新增表：
  audit_logs — 记录所有关键业务操作，合规要求不可删除/不可修改

RLS 策略（特殊合规模式）：
  - 只允许 SELECT 和 INSERT，故意不创建 UPDATE / DELETE policy
  - 即使超级用户调用也受 FORCE ROW LEVEL SECURITY 约束
  - 满足 GDPR / 个人信息保护法 的不可篡改要求

金额单位：无（本表不存储金额）

Revision ID: v070
Revises: v069
Create Date: 2026-03-31

Notes:
  - down_revision = "v069" 对应 Phase 4-A（并行开发，先于本迁移落地）
  - 若 v069 尚未执行，请先执行 v069 迁移再运行本迁移
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "v070"
down_revision = "v069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 创建 audit_logs 表
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            action          VARCHAR(50) NOT NULL,
            actor_id        VARCHAR(100) NOT NULL,
            actor_type      VARCHAR(20)  NOT NULL
                            CHECK (actor_type IN ('user', 'api_app', 'agent', 'system')),
            resource_type   VARCHAR(50),
            resource_id     VARCHAR(100),
            before_state    JSONB,
            after_state     JSONB,
            ip_address      VARCHAR(45),
            user_agent      VARCHAR(200),
            severity        VARCHAR(20)  NOT NULL DEFAULT 'info'
                            CHECK (severity IN ('info', 'warning', 'critical')),
            extra           JSONB        NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)

    # ─────────────────────────────────────────────────────────────────
    # 索引
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_created_at
            ON audit_logs (tenant_id, created_at DESC)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_actor_action
            ON audit_logs (tenant_id, actor_id, action)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_severity_created_at
            ON audit_logs (tenant_id, severity, created_at DESC)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_resource
            ON audit_logs (tenant_id, resource_type, resource_id)
    """)

    # ─────────────────────────────────────────────────────────────────
    # RLS — 合规特殊策略：只允许 SELECT 和 INSERT，禁止 UPDATE/DELETE
    #
    # 说明:
    #   - FORCE ROW LEVEL SECURITY 确保 superuser 也受策略约束
    #   - 故意不创建 UPDATE 和 DELETE policy（合规要求不可篡改）
    #   - 应用层通过 SET app.tenant_id = '<uuid>' 设置租户上下文
    #   - NULLIF(..., '') 防止空字符串绕过 RLS
    # ─────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY")

    # SELECT policy — 只能查看本租户的审计日志
    op.execute("""
        CREATE POLICY audit_logs_select ON audit_logs
            FOR SELECT
            USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)

    # INSERT policy — 只能写入本租户的审计日志
    op.execute("""
        CREATE POLICY audit_logs_insert ON audit_logs
            FOR INSERT
            WITH CHECK (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)

    # ⚠️ 合规说明: 此处故意不创建 UPDATE 和 DELETE policy。
    # 根据 GDPR / 个人信息保护法 及内部合规要求，审计日志一旦写入
    # 不允许被修改或删除。任何 UPDATE/DELETE 操作将因无匹配 policy
    # 而被 PostgreSQL RLS 拒绝（返回 permission denied）。


def downgrade() -> None:
    # 先删除 RLS 策略，再删除表
    op.execute("DROP POLICY IF EXISTS audit_logs_select ON audit_logs")
    op.execute("DROP POLICY IF EXISTS audit_logs_insert ON audit_logs")
    op.execute("DROP TABLE IF EXISTS audit_logs")
