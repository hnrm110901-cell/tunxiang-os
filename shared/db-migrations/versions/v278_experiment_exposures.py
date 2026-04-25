"""v278 — Sprint G 实验框架：experiment_exposures + experiment_definitions

Sprint G 完整四件套（G1 纯函数分桶 / G2 Orchestrator 判桶 / G3 Welch 仪表板 / G4 熔断）
的持久化基础。本迁移只建表 + RLS，不插入业务数据；具体实验记录由
services/tx-analytics/src/experiment/ 模块在运行时写入。

设计要点（CLAUDE.md §17 Tier3 + §13 RLS 强制）：
  - experiment_definitions: 实验配置（变体权重、监控指标、熔断阈值）
    * variants JSONB: [{name,weight,config}]，权重之和应为 100（运行时校验）
    * circuit_breaker_threshold_pct: 默认 -20.0（与 §决策点一致，可逐实验覆盖）
    * (tenant_id, experiment_key) 唯一
  - experiment_exposures: 不可变的暴露事件流（每对 subject ↔ experiment 仅一行）
    * (tenant_id, experiment_key, subject_type, subject_id) 唯一
      → idempotent expose 的 DB 约束基础
    * bucket_hash_seed 留作可重放分桶（同 seed 同输入 → 同桶）
    * exposed_at 用于 Welch 仪表板时间窗口过滤

  - 两表均 RLS USING + WITH CHECK（参考 v274 RLS 加固模式）
    避免任意 admin 路径写入异租户数据污染实验暴露记录

  - down 完整反向：DROP 表 + DROP POLICY 幂等，不影响其它表

跳号说明：
  并行 Agent E4 已落 v276 (channel_canonical_orders) + v277 (channel_disputes)。
  本迁移接 v277 作为 head。

Revision ID: v278
Revises: v277
Create Date: 2026-04-25
"""

import sqlalchemy as sa
from alembic import op

revision = "v278"
down_revision = "v277"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # ── experiment_definitions ────────────────────────────────────────────
    if "experiment_definitions" not in existing_tables:
        op.execute(
            """
            CREATE TABLE experiment_definitions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL,
                experiment_key TEXT NOT NULL,
                description TEXT NULL,
                variants JSONB NOT NULL DEFAULT '[]'::jsonb,
                guardrail_metrics JSONB NOT NULL DEFAULT '[]'::jsonb,
                circuit_breaker_threshold_pct NUMERIC(6, 2) NOT NULL DEFAULT -20.0,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                started_at TIMESTAMPTZ NULL,
                ended_at TIMESTAMPTZ NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted BOOLEAN NOT NULL DEFAULT FALSE
            );
            """
        )
        op.execute(
            "CREATE UNIQUE INDEX uq_experiment_definitions_tenant_key "
            "ON experiment_definitions (tenant_id, experiment_key) "
            "WHERE is_deleted = FALSE;"
        )
        op.execute(
            "ALTER TABLE experiment_definitions ENABLE ROW LEVEL SECURITY;"
        )
        op.execute(
            """
            CREATE POLICY experiment_definitions_tenant_isolation
                ON experiment_definitions
                USING (
                    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                )
                WITH CHECK (
                    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                );
            """
        )

    # ── experiment_exposures ──────────────────────────────────────────────
    if "experiment_exposures" not in existing_tables:
        op.execute(
            """
            CREATE TABLE experiment_exposures (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL,
                store_id UUID NULL,
                experiment_key TEXT NOT NULL,
                subject_type TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                bucket TEXT NOT NULL,
                bucket_hash_seed TEXT NOT NULL,
                exposed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                context JSONB NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        # 唯一索引保证 idempotent expose（subject 对每个实验只暴露一次）
        op.execute(
            "CREATE UNIQUE INDEX uq_experiment_exposures_subject "
            "ON experiment_exposures "
            "(tenant_id, experiment_key, subject_type, subject_id);"
        )
        # 仪表板时间窗扫描索引
        op.execute(
            "CREATE INDEX ix_experiment_exposures_window "
            "ON experiment_exposures "
            "(tenant_id, experiment_key, exposed_at DESC);"
        )
        op.execute(
            "ALTER TABLE experiment_exposures ENABLE ROW LEVEL SECURITY;"
        )
        op.execute(
            """
            CREATE POLICY experiment_exposures_tenant_isolation
                ON experiment_exposures
                USING (
                    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                )
                WITH CHECK (
                    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                );
            """
        )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS experiment_exposures_tenant_isolation "
        "ON experiment_exposures;"
    )
    op.execute("DROP TABLE IF EXISTS experiment_exposures CASCADE;")

    op.execute(
        "DROP POLICY IF EXISTS experiment_definitions_tenant_isolation "
        "ON experiment_definitions;"
    )
    op.execute("DROP TABLE IF EXISTS experiment_definitions CASCADE;")
