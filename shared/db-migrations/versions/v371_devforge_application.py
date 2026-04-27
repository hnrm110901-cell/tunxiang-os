"""v371: devforge_applications — 内部研发运维平台应用目录基础表

为 tx-devforge 微服务建立 5 类资源（backend_service/frontend_app/edge_image/
adapter/data_asset）的统一应用目录，所有后续 CMDB/CI/CD/巡检功能都以此表为根。

Revision ID: v371_devforge_application
Revises: v365_forge_ecosystem_metrics
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "v371_devforge_application"
down_revision: Union[str, None] = "v365_forge_ecosystem_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS_CONDITION = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID"
)


def _enable_rls(table_name: str) -> None:
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    for action, clause in [
        ("select", f"FOR SELECT USING ({_RLS_CONDITION})"),
        ("insert", f"FOR INSERT WITH CHECK ({_RLS_CONDITION})"),
        ("update", f"FOR UPDATE USING ({_RLS_CONDITION}) WITH CHECK ({_RLS_CONDITION})"),
        ("delete", f"FOR DELETE USING ({_RLS_CONDITION})"),
    ]:
        op.execute(
            f"CREATE POLICY {table_name}_rls_{action} ON {table_name} "
            f"AS PERMISSIVE {clause}"
        )


def _disable_rls(table_name: str) -> None:
    for suffix in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS {table_name}_rls_{suffix} ON {table_name}")
    op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    op.create_table(
        "devforge_applications",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("resource_type", sa.String(40), nullable=False),
        sa.Column("owner", sa.String(200), nullable=True),
        sa.Column("repo_path", sa.String(500), nullable=True),
        sa.Column("tech_stack", sa.String(50), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "metadata_json",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "is_deleted",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "code", name="uq_devforge_applications_tenant_code"
        ),
        sa.CheckConstraint(
            "resource_type IN ('backend_service','frontend_app','edge_image',"
            "'adapter','data_asset')",
            name="ck_devforge_applications_resource_type",
        ),
    )
    op.create_index(
        "ix_devforge_applications_tenant_resource_type",
        "devforge_applications",
        ["tenant_id", "resource_type"],
    )
    op.create_index(
        "ix_devforge_applications_tenant_active",
        "devforge_applications",
        ["tenant_id"],
        postgresql_where=sa.text("is_deleted = false"),
    )
    _enable_rls("devforge_applications")


def downgrade() -> None:
    _disable_rls("devforge_applications")
    op.drop_index(
        "ix_devforge_applications_tenant_active",
        table_name="devforge_applications",
    )
    op.drop_index(
        "ix_devforge_applications_tenant_resource_type",
        table_name="devforge_applications",
    )
    op.drop_table("devforge_applications")
