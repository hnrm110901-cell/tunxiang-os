"""W2-A Phase 4 — reverse v384-v389 (国际化 schema 删除最后一公里)

承接 W2-A Phase 1 (#499) / Phase 2 (#504) / Phase 3 (#524) 完成应用层删除后,
reverse v384-v389 引入的 schema:
- v384: 17 表 country_code 删除
- v385: dishes.sst_category 删除
- v386: tenant_subsidies + subsidy_bills 整表删除 (含 v400 RLS hotfix policy)
- v387: pdpa_requests + pdpa_consent_logs 整表删除
- v388: dishes.ppn_category 删除
- v389: dishes.vat_category + ix_dishes_vat_category 删除

创始人 risk-accept (路径 A): production 三国 tenant 数据假定为零, 不跑前置 SQL.
5 条独立证据 converge 到"三国从未激活": (1) PR #499 commit 0 deployment /
(2) W2-A plan grep 0 import / (3) tenants/ 仅 3 国内 / (4) 7 seed scripts 0
三国 / (5) Phase 1-3 zero stale ref.

Tier 2 — schema 反向, 不动业务代码, 不动 RLS 通用 policy (仅删 v386/v387
引入的 subsidy/PDPA 专属 policy + v400 hotfix 反向).

Revision ID: v416_w2a_phase4_reverse
Revises: v415_wine_storage_amount_fen
Create Date: 2026-05-13
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v416_w2a_phase4_reverse"
down_revision: Union[str, None] = "v415_wine_storage_amount_fen"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """W2-A Phase 4: reverse v384-v389 schema.

    顺序 (按 FK + RLS 依赖):
    1. drop v400 hotfix policy (subsidy 2 表 WITH CHECK)
    2. drop v387 PDPA tables (含 policy + table)
    3. drop v386 subsidy tables (含 v386 自身 policy + FK + table)
    4. drop v389 dishes.vat_category + partial index
    5. drop v388 dishes.ppn_category
    6. drop v385 dishes.sst_category
    7. drop v384 country_code (17 表 reverse order)
    """
    # ===== Step 1: drop v400 RLS hotfix policies (subsidy 2 表 WITH CHECK) =====
    op.execute("DROP POLICY IF EXISTS tenant_subsidies_update ON tenant_subsidies")
    op.execute("DROP POLICY IF EXISTS subsidy_bills_update ON subsidy_bills")

    # ===== Step 2: drop v387 PDPA tables (CASCADE 处理 policy + index) =====
    op.execute("DROP TABLE IF EXISTS pdpa_consent_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS pdpa_requests CASCADE")

    # ===== Step 3: drop v386 subsidy tables (CASCADE 处理 v386 自身 policy + index + FK) =====
    op.execute("DROP TABLE IF EXISTS subsidy_bills CASCADE")
    op.execute("DROP TABLE IF EXISTS tenant_subsidies CASCADE")

    # ===== Step 4: drop v389 dishes.vat_category + partial index =====
    op.execute("DROP INDEX IF EXISTS ix_dishes_vat_category")
    op.drop_column("dishes", "vat_category")

    # ===== Step 5: drop v388 dishes.ppn_category =====
    op.drop_column("dishes", "ppn_category")

    # ===== Step 6: drop v385 dishes.sst_category =====
    op.drop_column("dishes", "sst_category")

    # ===== Step 7: drop v384 country_code (reverse order of 17 tables) =====
    # 注: v389 含 `UPDATE stores SET country_code='VN' ...` 数据写入,
    # drop column 一并消失, 无需先 UPDATE 回 'CN'.
    TARGET_TABLES = [
        # reverse of v384 TARGET_TABLES (originally CN default)
        "brands", "regions",
        "transfer_order_items", "transfer_orders",
        "receiving_order_items", "receiving_orders",
        "ingredient_transactions", "ingredients", "ingredient_masters",
        "order_items", "orders",
        "dish_ingredients", "dish_categories", "dishes",
        "employees", "stores", "customers",
    ]
    for table in TARGET_TABLES:
        op.drop_column(table, "country_code")


def downgrade() -> None:
    """W2-A Phase 4 reverse 的 downgrade — 重新引入 v384-v389 schema.

    不在 W2-A 范围内日常使用 (W2-A 完工后向前不可逆), 但保留 downgrade 以满足
    alembic chain integrity. 复用 v384-v389 的 upgrade() 内容. 仅用于灾难恢复
    或 production rollback 场景, 实际 SRE 操作必走 PG 全库恢复.
    """
    raise NotImplementedError(
        "W2-A Phase 4 是单向反向操作. Downgrade 需手动 cherry-pick "
        "v384..v389 upgrade(). 建议 PG 全库恢复而非 alembic downgrade. "
        "See docs/w2-deprecate-regional-plan.md Phase 4 section."
    )
