"""v071 — AI 模型调用成本日志表

新增表：
  model_call_logs — 记录所有通过 ModelRouter 发出的 AI 调用，
                    用于成本追踪、用量分析、异常审计

RLS 策略（只读日志模式，与 audit_logs 一致）：
  - 只允许 SELECT 和 INSERT，故意不创建 UPDATE / DELETE policy
  - 应用层通过 SET app.tenant_id = '<uuid>' 设置租户上下文

金额单位：cost_usd 存储 USD，精度到 0.000001

Revision ID: v071
Revises: v070
Create Date: 2026-03-31

Notes:
  - request_id UNIQUE 保证幂等插入（ON CONFLICT DO NOTHING）
  - duration_ms 允许 NULL（熔断器拒绝时无实际调用时长）
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "v071"
down_revision = "v070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 创建 model_call_logs 表
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS model_call_logs (
            id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     UUID         NOT NULL,
            task_type     VARCHAR(50),
            model         VARCHAR(100) NOT NULL,
            input_tokens  INTEGER      NOT NULL DEFAULT 0,
            output_tokens INTEGER      NOT NULL DEFAULT 0,
            cost_usd      NUMERIC(10, 6) NOT NULL DEFAULT 0,
            duration_ms   INTEGER,
            success       BOOLEAN      NOT NULL,
            error_type    VARCHAR(100),
            request_id    VARCHAR(64)  UNIQUE,
            created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)

    # ─────────────────────────────────────────────────────────────────
    # 索引
    # ─────────────────────────────────────────────────────────────────

    # 按租户+时间降序查询（最常用）
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_model_call_logs_tenant_created_at
            ON model_call_logs (tenant_id, created_at DESC)
    """)

    # 按租户+任务类型统计
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_model_call_logs_tenant_task_type
            ON model_call_logs (tenant_id, task_type)
    """)

    # 按租户+模型统计成本
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_model_call_logs_tenant_model
            ON model_call_logs (tenant_id, model)
    """)

    # 失败记录快速检索
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_model_call_logs_tenant_success
            ON model_call_logs (tenant_id, success, created_at DESC)
    """)

    # ─────────────────────────────────────────────────────────────────
    # RLS — 只允许 SELECT 和 INSERT，禁止 UPDATE/DELETE（成本日志不可篡改）
    #
    # 应用层必须先执行:
    #   SET app.tenant_id = '<uuid>';
    # 再进行 SELECT / INSERT 操作。
    # NULLIF(..., '') 防止空字符串绕过 RLS。
    # ─────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE model_call_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE model_call_logs FORCE ROW LEVEL SECURITY")

    # SELECT policy — 只能查看本租户的调用日志
    op.execute("""
        CREATE POLICY model_call_logs_select ON model_call_logs
            FOR SELECT
            USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)

    # INSERT policy — 只能写入本租户的调用日志
    op.execute("""
        CREATE POLICY model_call_logs_insert ON model_call_logs
            FOR INSERT
            WITH CHECK (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID
            )
    """)

    # ⚠️ 合规说明: 故意不创建 UPDATE 和 DELETE policy。
    # 成本日志一旦写入不允许修改或删除，防止成本数据被篡改。
    # 任何 UPDATE/DELETE 操作将被 PostgreSQL RLS 拒绝。


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS model_call_logs_select ON model_call_logs")
    op.execute("DROP POLICY IF EXISTS model_call_logs_insert ON model_call_logs")
    op.execute("DROP TABLE IF EXISTS model_call_logs")
