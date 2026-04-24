"""集团级发票去重系统：跨品牌/跨租户发票重复检测
Tables: invoice_dedup_groups, group_invoice_cross_ref
Sprint: P2-S3（集团级发票去重 + 费控汇总报表引擎）

设计原则：
  - invoice_dedup_groups 故意不加 RLS，允许跨租户查询（通过应用层超级账号连接）
  - group_id = SHA-256(invoice_code + ":" + invoice_number)，注意不含金额（同一张发票不同金额仍视为同一张）
  - total_usage_count > 1 表示跨品牌重复使用
  - is_suspicious = True 表示 first_tenant_id != 当前 tenant_id（真正的跨品牌重复）
  - group_invoice_cross_ref 记录每个租户/门店对该发票的引用

Revision ID: v244
Revises: v243
Create Date: 2026-04-12
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "v244b"
down_revision = "v244"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()

    # ------------------------------------------------------------------
    # 表1：invoice_dedup_groups（集团级发票去重组）
    # 注意：故意不加 RLS，允许跨租户查询（通过应用层 SERVICE_DB_URL 超级账号连接）
    # ------------------------------------------------------------------

    if "invoice_dedup_groups" not in existing:
        op.create_table(
            "invoice_dedup_groups",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column(
                "group_id",
                sa.String(64),
                nullable=False,
                unique=True,
                comment="SHA-256(invoice_code + ':' + invoice_number)，不含金额，跨金额识别同一张发票",
            ),
            sa.Column(
                "first_tenant_id",
                UUID(as_uuid=True),
                nullable=False,
                comment="第一次报销该发票的租户ID",
            ),
            sa.Column(
                "first_invoice_id",
                UUID(as_uuid=True),
                nullable=False,
                comment="第一条发票记录ID（invoices 表）",
            ),
            sa.Column(
                "first_reported_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                comment="第一次上报时间",
            ),
            sa.Column(
                "total_usage_count",
                sa.Integer(),
                nullable=False,
                server_default="1",
                comment="使用次数（> 1 表示跨品牌重复使用）",
            ),
            sa.Column(
                "is_suspicious",
                sa.Boolean(),
                nullable=False,
                server_default="false",
                comment="是否标记为可疑跨品牌重复（first_tenant_id != 当前上报租户）",
            ),
            sa.Column(
                "resolved_at",
                sa.TIMESTAMP(timezone=True),
                nullable=True,
                comment="人工处理时间（NULL=待处理）",
            ),
            sa.Column(
                "resolved_by",
                UUID(as_uuid=True),
                nullable=True,
                comment="处理人员ID",
            ),
            sa.Column(
                "resolve_note",
                sa.Text(),
                nullable=True,
                comment="处理备注（人工确认合规原因 或 驳回理由）",
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )

        # 索引：按 first_tenant_id 查询该租户首次发现的重复
        op.create_index(
            "ix_invoice_dedup_groups_first_tenant",
            "invoice_dedup_groups",
            ["first_tenant_id"],
        )
        # 索引：只查可疑记录（常用过滤条件）
        op.create_index(
            "ix_invoice_dedup_groups_suspicious",
            "invoice_dedup_groups",
            ["is_suspicious", "created_at"],
            postgresql_where=sa.text("is_suspicious = TRUE"),
        )
        # 索引：按处理状态筛选待处理记录
        op.create_index(
            "ix_invoice_dedup_groups_unresolved",
            "invoice_dedup_groups",
            ["is_suspicious", "resolved_at"],
            postgresql_where=sa.text("is_suspicious = TRUE AND resolved_at IS NULL"),
        )

        # ------------------------------------------------------------------
        # 表2：group_invoice_cross_ref（发票与集团去重组的关联）
        # 注意：同样不加 RLS，与 invoice_dedup_groups 同属跨租户查询范畴
        # ------------------------------------------------------------------

    if "group_invoice_cross_ref" not in existing:
        op.create_table(
            "group_invoice_cross_ref",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column(
                "group_id",
                sa.String(64),
                nullable=False,
                comment="关联 invoice_dedup_groups.group_id",
            ),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                nullable=False,
                comment="上报该发票的租户ID",
            ),
            sa.Column(
                "invoice_id",
                UUID(as_uuid=True),
                nullable=False,
                comment="发票记录ID（invoices 表）",
            ),
            sa.Column(
                "expense_application_id",
                UUID(as_uuid=True),
                nullable=True,
                comment="关联的费控申请ID（可空，支持发票先上传后关联）",
            ),
            sa.Column(
                "reported_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
                comment="该租户上报该发票的时间",
            ),
        )

        # 唯一约束：同一组内同一租户同一发票只记录一次
        op.create_unique_constraint(
            "uq_group_invoice_cross_ref_group_tenant_invoice",
            "group_invoice_cross_ref",
            ["group_id", "tenant_id", "invoice_id"],
        )

        # 外键：group_id → invoice_dedup_groups.group_id
        op.create_foreign_key(
            "fk_group_invoice_cross_ref_group_id",
            "group_invoice_cross_ref",
            "invoice_dedup_groups",
            ["group_id"],
            ["group_id"],
            ondelete="CASCADE",
        )

        # 索引：按 group_id 查所有引用（去重组详情页）
        op.create_index(
            "ix_group_invoice_cross_ref_group_id",
            "group_invoice_cross_ref",
            ["group_id"],
        )
        # 索引：按租户查本租户相关的跨品牌记录
        op.create_index(
            "ix_group_invoice_cross_ref_tenant",
            "group_invoice_cross_ref",
            ["tenant_id", "reported_at"],
        )
        # 索引：按发票ID查（关联查询）
        op.create_index(
            "ix_group_invoice_cross_ref_invoice_id",
            "group_invoice_cross_ref",
            ["invoice_id"],
        )


def downgrade() -> None:
    # 先删关联表（有外键依赖）
    op.drop_table("group_invoice_cross_ref")

    # 再删主表
    op.drop_table("invoice_dedup_groups")
