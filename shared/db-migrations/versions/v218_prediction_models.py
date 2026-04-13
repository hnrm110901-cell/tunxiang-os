"""预测引擎数据模型

Revision: v218
Tables:
  - prediction_models   预测模型版本管理（类型/准确率/训练时间）
  - prediction_results  预测结果缓存（store_id/类型/日期/结果JSON）
  - weather_cache       天气数据缓存（避免重复API调用）
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v218"
down_revision = "v217"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()


    # ── 预测模型版本管理 ──

    if 'prediction_models' not in existing:
        op.create_table(
            "prediction_models",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=True,
                      comment="门店ID（NULL=全局模型）"),
            sa.Column("model_type", sa.VARCHAR(50), nullable=False,
                      comment="traffic/demand/revenue"),
            sa.Column("model_version", sa.VARCHAR(20), server_default="1.0",
                      comment="模型版本号"),
            sa.Column("accuracy_mape", sa.FLOAT, nullable=True,
                      comment="MAPE准确率指标(%)"),
            sa.Column("accuracy_rmse", sa.FLOAT, nullable=True,
                      comment="RMSE准确率指标"),
            sa.Column("training_data_days", sa.INTEGER, server_default="30",
                      comment="训练数据回溯天数"),
            sa.Column("training_samples", sa.INTEGER, server_default="0",
                      comment="训练样本数"),
            sa.Column("hyperparams", postgresql.JSONB, server_default="{}",
                      comment="超参数配置"),
            sa.Column("status", sa.VARCHAR(20), server_default="active",
                      comment="active/training/deprecated"),
            sa.Column("trained_at", sa.DateTime(timezone=True), nullable=True,
                      comment="最近训练时间"),
            sa.Column("is_deleted", sa.BOOLEAN, server_default="false", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
        )
        op.create_index("ix_prediction_models_tenant_type",
                        "prediction_models", ["tenant_id", "model_type"])
        op.create_index("ix_prediction_models_store",
                        "prediction_models", ["tenant_id", "store_id", "model_type"])

        op.execute("ALTER TABLE prediction_models ENABLE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY pm_tenant_isolation ON prediction_models
            USING (tenant_id = current_setting('app.tenant_id')::uuid)
        """)

        # ── 预测结果缓存 ──

    if 'prediction_results' not in existing:
        op.create_table(
            "prediction_results",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("prediction_type", sa.VARCHAR(50), nullable=False,
                      comment="traffic/demand/revenue/traffic_baseline"),
            sa.Column("target_date", sa.DATE, nullable=False,
                      comment="预测目标日期"),
            sa.Column("result_data", postgresql.JSONB, nullable=False, server_default="{}",
                      comment="预测结果JSON"),
            sa.Column("confidence", sa.FLOAT, nullable=True,
                      comment="整体置信度 0-1"),
            sa.Column("model_version", sa.VARCHAR(20), nullable=True),
            sa.Column("actual_data", postgresql.JSONB, nullable=True,
                      comment="实际数据（用于回测计算准确率）"),
            sa.Column("is_deleted", sa.BOOLEAN, server_default="false", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
        )
        op.create_index("ix_prediction_results_lookup",
                        "prediction_results",
                        ["tenant_id", "store_id", "prediction_type", "target_date"])
        op.create_index("ix_prediction_results_date",
                        "prediction_results", ["tenant_id", "target_date"])

        # 唯一约束：同一门店同一类型同一天只有一条预测
        op.create_unique_constraint(
            "uq_prediction_results_store_type_date",
            "prediction_results",
            ["tenant_id", "store_id", "prediction_type", "target_date"],
        )

        op.execute("ALTER TABLE prediction_results ENABLE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY pr_tenant_isolation ON prediction_results
            USING (tenant_id = current_setting('app.tenant_id')::uuid)
        """)

        # ── 天气数据缓存 ──

    if 'weather_cache' not in existing:
        op.create_table(
            "weather_cache",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("city", sa.VARCHAR(100), nullable=False, comment="城市名或城市ID"),
            sa.Column("forecast_data", postgresql.JSONB, nullable=False, server_default="[]",
                      comment="7天预报数据JSON"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False,
                      comment="缓存过期时间"),
            sa.Column("is_deleted", sa.BOOLEAN, server_default="false", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
        )
        op.create_index("ix_weather_cache_lookup",
                        "weather_cache", ["tenant_id", "city"])

        # 唯一约束：同一租户同一城市只缓存一条
        op.create_unique_constraint(
            "uq_weather_cache_tenant_city",
            "weather_cache",
            ["tenant_id", "city"],
        )

        op.execute("ALTER TABLE weather_cache ENABLE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY wc_tenant_isolation ON weather_cache
            USING (tenant_id = current_setting('app.tenant_id')::uuid)
        """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS wc_tenant_isolation ON weather_cache")
    op.drop_table("weather_cache")
    op.execute("DROP POLICY IF EXISTS pr_tenant_isolation ON prediction_results")
    op.drop_table("prediction_results")
    op.execute("DROP POLICY IF EXISTS pm_tenant_isolation ON prediction_models")
    op.drop_table("prediction_models")
