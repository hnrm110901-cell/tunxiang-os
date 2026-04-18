"""z68 D9 — 电子签约完整模块 + 多主体管理

新增 7 张表：
  legal_entities / store_legal_entities
  signature_templates / signature_seals / signature_envelopes
  signature_records / signature_audit_logs

Revision ID: z68_d9_e_signature_legal_entity
Revises: z67_merge_wave4
Create Date: 2026-04-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "z68_d9_e_signature_legal_entity"
down_revision = "z67_merge_wave4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------- 法人主体 ----------
    op.create_table(
        "legal_entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("brand_id", sa.String(50), nullable=True, index=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "entity_type",
            sa.Enum(
                "direct_operated",
                "franchise",
                "joint_venture",
                "subsidiary",
                name="legal_entity_type_enum",
            ),
            nullable=False,
            server_default="direct_operated",
        ),
        sa.Column("unified_social_credit", sa.String(50), nullable=True, unique=True),
        sa.Column("legal_representative", sa.String(100), nullable=True),
        sa.Column("registered_address", sa.String(500), nullable=True),
        sa.Column("registered_capital_fen", sa.Integer(), nullable=True),
        sa.Column("establish_date", sa.Date(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "suspended", "dissolved", name="legal_entity_status_enum"),
            nullable=False,
            server_default="active",
        ),
        sa.Column("tax_number", sa.String(50), nullable=True),
        sa.Column("bank_name", sa.String(100), nullable=True),
        sa.Column("bank_account", sa.String(50), nullable=True),
        sa.Column("contact_phone", sa.String(50), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "store_legal_entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("store_id", sa.String(50), nullable=False, index=True),
        sa.Column("legal_entity_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.true()),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("store_id", "legal_entity_id", "start_date", name="uq_store_legal_entity_period"),
    )

    # ---------- 电子签约 ----------
    op.create_table(
        "signature_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "category",
            sa.Enum(
                "labor_contract",
                "probation",
                "transfer",
                "resignation",
                "nda",
                "franchise_agreement",
                "supplier",
                "training_confirm",
                "other",
                name="template_category_enum",
            ),
            nullable=False,
            server_default="labor_contract",
        ),
        sa.Column("content_template_url", sa.String(500), nullable=True),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("placeholders_json", postgresql.JSON(), nullable=True),
        sa.Column("required_fields_json", postgresql.JSON(), nullable=True),
        sa.Column("legal_entity_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("version", sa.Integer(), server_default="1"),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), index=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "signature_seals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("legal_entity_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("seal_name", sa.String(200), nullable=False),
        sa.Column(
            "seal_type",
            sa.Enum("official", "contract", "finance", "legal_rep", name="seal_type_enum"),
            nullable=False,
            server_default="contract",
        ),
        sa.Column("seal_image_url", sa.String(500), nullable=True),
        sa.Column("authorized_users_json", postgresql.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), index=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "signature_envelopes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("envelope_no", sa.String(50), nullable=False, unique=True, index=True),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("signature_templates.id"), nullable=True),
        sa.Column("legal_entity_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("subject", sa.String(500), nullable=True),
        sa.Column("initiator_id", sa.String(50), nullable=True),
        sa.Column("signer_info_json", postgresql.JSON(), nullable=True),
        sa.Column("placeholder_values_json", postgresql.JSON(), nullable=True),
        sa.Column("document_url", sa.String(500), nullable=True),
        sa.Column("signed_document_url", sa.String(500), nullable=True),
        sa.Column(
            "envelope_status",
            sa.Enum(
                "draft",
                "sent",
                "partially_signed",
                "completed",
                "rejected",
                "expired",
                name="envelope_status_enum",
            ),
            nullable=False,
            server_default="draft",
            index=True,
        ),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("related_contract_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("related_entity_type", sa.String(50), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "signature_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "envelope_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("signature_envelopes.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("signer_id", sa.String(50), nullable=False, index=True),
        sa.Column("signer_name", sa.String(100), nullable=True),
        sa.Column(
            "signer_role",
            sa.Enum(
                "employee",
                "hr",
                "legal_rep",
                "witness",
                "party_a",
                "party_b",
                name="signer_role_enum",
            ),
            nullable=False,
            server_default="employee",
        ),
        sa.Column("sign_order", sa.Integer(), server_default="1"),
        sa.Column(
            "status",
            sa.Enum("pending", "signed", "rejected", name="sign_record_status_enum"),
            nullable=False,
            server_default="pending",
            index=True,
        ),
        sa.Column("signature_image_url", sa.String(500), nullable=True),
        sa.Column("seal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("signed_at", sa.DateTime(), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(50), nullable=True),
        sa.Column("device_info", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "signature_audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "envelope_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("signature_envelopes.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "action",
            sa.Enum(
                "create",
                "send",
                "view",
                "sign",
                "reject",
                "expire",
                "complete",
                "void",
                name="signature_audit_action_enum",
            ),
            nullable=False,
            index=True,
        ),
        sa.Column("actor_id", sa.String(50), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("details_json", postgresql.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("signature_audit_logs")
    op.drop_table("signature_records")
    op.drop_table("signature_envelopes")
    op.drop_table("signature_seals")
    op.drop_table("signature_templates")
    op.drop_table("store_legal_entities")
    op.drop_table("legal_entities")

    for enum_name in (
        "signature_audit_action_enum",
        "sign_record_status_enum",
        "signer_role_enum",
        "envelope_status_enum",
        "seal_type_enum",
        "template_category_enum",
        "legal_entity_status_enum",
        "legal_entity_type_enum",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
