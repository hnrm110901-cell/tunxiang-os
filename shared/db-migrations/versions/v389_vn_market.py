"""v389 — Vietnam market preparation: VAT category column

Phase 3 Sprint 3.5 — Vietnam market expansion.

Changes:
  1. Add `vat_category` VARCHAR(20) column to `dishes` table
     (values: 'standard' / 'reduced' / 'export' / 'exempt')
  2. Add `country_code` VARCHAR(2) default 'VN' for Vietnam tenant stores
  3. Add index on `vat_category` for filtering

Note: This migration requires the v383 chain consolidation as parent.
      Run `alembic upgrade v389_vn_market` after v383 merge head.

Revision ID: v389_vn_market
Revises: v383_chain_consolidation
Create Date: 2026-05-03
"""
from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "v389_vn_market"
down_revision: str = "v388"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Apply Vietnam market schema changes."""

    # 1. Add vat_category to dishes table
    #    Values: 'standard' (10%), 'reduced' (8%), 'export' (0%), 'exempt' (0%)
    #    NULL defaults to 'standard' for backwards compatibility
    op.add_column(
        "dishes",
        sa.Column(
            "vat_category",
            sa.VARCHAR(20),
            nullable=True,
            comment="Vietnam VAT category: standard(10%), reduced(8%), export(0%), exempt(0%)",
        ),
    )
    op.create_index(
        "ix_dishes_vat_category",
        "dishes",
        ["vat_category"],
        postgresql_where=sa.text("vat_category IS NOT NULL"),
    )

    # 2. Update country_code for Vietnam tenant stores if country_code column exists
    #    This is idempotent — only affects rows where country_code is NULL or empty
    bind = op.get_bind()
    dialect = bind.dialect.name if bind else "postgresql"

    if dialect == "postgresql":
        # Check if country_code column exists before updating
        insp = sa.inspect(bind)
        columns = [c["name"] for c in insp.get_columns("stores")]
        if "country_code" in columns:
            op.execute(
                sa.text(
                    "UPDATE stores SET country_code = 'VN' "
                    "WHERE (country_code IS NULL OR country_code = '') "
                    "AND tenant_id IN ("
                    "  SELECT id FROM tenants WHERE region = 'vietnam'"
                    ")"
                )
            )


def downgrade() -> None:
    """Revert Vietnam market schema changes."""

    # 1. Drop index and column
    op.drop_index("ix_dishes_vat_category", table_name="dishes")
    op.drop_column("dishes", "vat_category")

    # 2. country_code is not reverted — clearing it could break other tenants
    pass
