"""d15 i18n 多语言 + 多时区 + GDPR + 多国合规（v3.3 出海基础设施）

新增 7 张表：
- locales / i18n_text_keys / i18n_translations
- tenant_locale_configs
- data_consent_records / data_access_requests
- country_payroll_rules

修改 employees 表：追加 timezone / locale_code（带默认值，向后兼容）

Revision ID: z70_d15_i18n_multi_country
Revises: z69_merge_wave5
Create Date: 2026-04-17
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "z70_d15_i18n_multi_country"
down_revision = "z69_merge_wave5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── locales ─────────────────────────────────
    op.create_table(
        "locales",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(10), nullable=False, unique=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("flag_emoji", sa.String(10)),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_locales_code", "locales", ["code"])

    # ── i18n_text_keys ─────────────────────────
    op.create_table(
        "i18n_text_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("namespace", sa.String(50), nullable=False),
        sa.Column("key", sa.String(200), nullable=False),
        sa.Column("default_value_zh", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("namespace", "key", name="uq_i18n_namespace_key"),
    )
    op.create_index("ix_i18n_text_keys_namespace", "i18n_text_keys", ["namespace"])
    op.create_index("ix_i18n_text_keys_key", "i18n_text_keys", ["key"])

    # ── i18n_translations ──────────────────────
    op.create_table(
        "i18n_translations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "text_key_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("i18n_text_keys.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("locale_code", sa.String(10), nullable=False),
        sa.Column("translated_value", sa.Text(), nullable=False),
        sa.Column("translator", sa.String(20), nullable=False, server_default="human"),
        sa.Column("reviewed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("text_key_id", "locale_code", name="uq_i18n_translation_key_locale"),
    )
    op.create_index("ix_i18n_translations_text_key_id", "i18n_translations", ["text_key_id"])
    op.create_index("ix_i18n_translations_locale_code", "i18n_translations", ["locale_code"])

    # ── tenant_locale_configs ──────────────────
    op.create_table(
        "tenant_locale_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, unique=True),
        sa.Column("default_locale", sa.String(10), nullable=False, server_default="zh-CN"),
        sa.Column("default_timezone", sa.String(50), nullable=False, server_default="Asia/Shanghai"),
        sa.Column("currency", sa.String(10), nullable=False, server_default="CNY"),
        sa.Column("date_format", sa.String(30), nullable=False, server_default="YYYY-MM-DD"),
        sa.Column("country_code", sa.String(5), nullable=False, server_default="CN"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_tenant_locale_configs_tenant_id", "tenant_locale_configs", ["tenant_id"])

    # ── data_consent_records ───────────────────
    op.create_table(
        "data_consent_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "employee_id",
            sa.String(50),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("consent_type", sa.String(40), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("granted_at", sa.DateTime()),
        sa.Column("revoked_at", sa.DateTime()),
        sa.Column("legal_basis", sa.String(40), nullable=False, server_default="consent"),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_data_consent_records_employee_id", "data_consent_records", ["employee_id"])
    op.create_index("ix_data_consent_records_consent_type", "data_consent_records", ["consent_type"])

    # ── data_access_requests ───────────────────
    op.create_table(
        "data_access_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "employee_id",
            sa.String(50),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("requested_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("export_file_url", sa.String(500)),
        sa.Column("rejection_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_data_access_requests_employee_id", "data_access_requests", ["employee_id"])

    # ── country_payroll_rules ──────────────────
    op.create_table(
        "country_payroll_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("country_code", sa.String(5), nullable=False),
        sa.Column("rule_type", sa.String(40), nullable=False),
        sa.Column("config_json", postgresql.JSON(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_country_payroll_rules_country_code", "country_payroll_rules", ["country_code"])
    op.create_index("ix_country_payroll_rules_rule_type", "country_payroll_rules", ["rule_type"])

    # ── employees 扩展 ─────────────────────────
    op.add_column(
        "employees",
        sa.Column("timezone", sa.String(50), nullable=False, server_default="Asia/Shanghai"),
    )
    op.add_column(
        "employees",
        sa.Column("locale_code", sa.String(10), nullable=False, server_default="zh-CN"),
    )


def downgrade() -> None:
    op.drop_column("employees", "locale_code")
    op.drop_column("employees", "timezone")

    op.drop_index("ix_country_payroll_rules_rule_type", table_name="country_payroll_rules")
    op.drop_index("ix_country_payroll_rules_country_code", table_name="country_payroll_rules")
    op.drop_table("country_payroll_rules")

    op.drop_index("ix_data_access_requests_employee_id", table_name="data_access_requests")
    op.drop_table("data_access_requests")

    op.drop_index("ix_data_consent_records_consent_type", table_name="data_consent_records")
    op.drop_index("ix_data_consent_records_employee_id", table_name="data_consent_records")
    op.drop_table("data_consent_records")

    op.drop_index("ix_tenant_locale_configs_tenant_id", table_name="tenant_locale_configs")
    op.drop_table("tenant_locale_configs")

    op.drop_index("ix_i18n_translations_locale_code", table_name="i18n_translations")
    op.drop_index("ix_i18n_translations_text_key_id", table_name="i18n_translations")
    op.drop_table("i18n_translations")

    op.drop_index("ix_i18n_text_keys_key", table_name="i18n_text_keys")
    op.drop_index("ix_i18n_text_keys_namespace", table_name="i18n_text_keys")
    op.drop_table("i18n_text_keys")

    op.drop_index("ix_locales_code", table_name="locales")
    op.drop_table("locales")
