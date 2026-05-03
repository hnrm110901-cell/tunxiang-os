"""v387 — PDPA 合规模块（Malaysia Personal Data Protection Act 2010）

新增两张表支持 Phase 2 Sprint 2.4 Malaysia PDPA 合规：

1. pdpa_requests — 数据主体权利请求
   - request_type: access(查阅)/correction(更正)/deletion(删除/匿名化)/portability(可携带)
   - status: pending → processing → completed / rejected
   - request_data: 请求附加数据（correction 需提供 corrections 字典）
   - response_data: 响应数据（access 返回摘要/deletion 返回匿名化日志等）

2. pdpa_consent_logs — 客户同意记录（PDPA opt-in 审计）
   - consent_type: marketing_sms/marketing_email/data_processing/cross_border/third_party
   - granted: True=同意, False=撤回同意
   - 记录 IP 地址和 User-Agent 用于审计

RLS 策略：
  - 两张表均启用 RLS，按 tenant_id 隔离
  - 遵循现有 gdpr_requests 表（v103）的 RLS 策略模式

Revision ID: v387
Revises: v386
Create Date: 2026-05-03
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v387"
down_revision: Union[str, Sequence[str], None] = "v386"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── pdpa_requests: 数据主体权利请求 ────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS pdpa_requests (
            id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID         NOT NULL,
            customer_id     UUID         NOT NULL,
            request_type    VARCHAR(20)  NOT NULL
                                CHECK (request_type IN ('access','correction','deletion','portability')),
            status          VARCHAR(20)  NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending','processing','completed','rejected')),
            request_data    JSONB        DEFAULT '{}',
            response_data   JSONB        DEFAULT '{}',
            requested_by    VARCHAR(200),
            notes           TEXT,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("ALTER TABLE pdpa_requests ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY pdpa_requests_rls ON pdpa_requests
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_pdpa_requests_customer
            ON pdpa_requests(tenant_id, customer_id, request_type)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_pdpa_requests_pending
            ON pdpa_requests(tenant_id, status, created_at)
            WHERE status IN ('pending','processing')
    """)

    # ── pdpa_consent_logs: 客户同意记录 ──────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS pdpa_consent_logs (
            id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID         NOT NULL,
            customer_id     UUID         NOT NULL,
            consent_type    VARCHAR(50)  NOT NULL
                                CHECK (consent_type IN (
                                    'marketing_sms','marketing_email',
                                    'data_processing','cross_border','third_party'
                                )),
            granted         BOOLEAN      NOT NULL,
            ip_address      VARCHAR(45),
            user_agent      TEXT,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("ALTER TABLE pdpa_consent_logs ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY pdpa_consent_logs_rls ON pdpa_consent_logs
            AS PERMISSIVE FOR ALL TO PUBLIC
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_pdpa_consent_customer
            ON pdpa_consent_logs(tenant_id, customer_id, consent_type, created_at)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pdpa_consent_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS pdpa_requests CASCADE")
