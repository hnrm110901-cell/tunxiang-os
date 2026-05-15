"""v435 — MarketSurvey 3 表（PRD-13 sub-A / Phase 2 W11 / T2 normal）

业务背景：
  徐记海鲜实际场景 — AI 主调研 (POS/采购订单) 缺早市/批发市场价 (菜场无 API),
  采购总监/创始人**早市拍照录入**进数据池兜底:
  - 凌晨 5 点马王堆海鲜批发市场: 创始人拍 30 张图 + 抄 20 个 SKU 价格录入
  - 调研价格用于 AI 训练池 (本地早市价数据集 — ⭐ 连锁餐饮独家长期资产)
  - 政府数据合作潜力: CPI 篮子菜价合作

PRD-13 范围 (sub-A schema only, sub-B 移动端上传 / sub-C AI 训练池入口):
  - market_surveys 调研主表 — surveyor_id (employee_id, RLS via tenant) + market_type +
    location_name 自由文本 + surveyed_at 时间 + status 三态工作流
  - market_survey_items 调研明细 — survey_id FK + ingredient (可选 FK + 自由文本兜底) +
    unit_price_fen + qty_per_unit Decimal + unit 文本 (斤/个/箱)
  - market_survey_photos 独立照片表 (创始人选项) — 关联 survey_id + 可选 item_id, 适合
    后续 AI Vision OCR 标注. 含 photo_url + caption + exif_meta JSONB

设计要点：
  - surveyor_id 是 employee_id (跨服务逻辑外键, 不加 FK 约束, 与 v432 同模式)
  - ingredient_id 可选 (NULL = 自由文本 ingredient 兜底, 调研可能见到不在系统的食材)
  - ingredient_name TEXT 必填 — 即便 ingredient_id 存在也冗余存名字 (历史变更兜底)
  - photos 独立表: 主表/明细可分别关联. item_id NULL = 调研封面图
  - 价格语义: unit_price_fen + qty_per_unit (单位价格) — AI 训练直接消费, 不需后处理
  - status 三态: draft (移动端起草) / submitted (提交进训练池候选) / verified (采购总监审核)
  - RLS 标准模式: ENABLE + FORCE + POLICY + WITH CHECK 四联 (PRD-08/11 同模式)
  - inspector-and-skip 模式 (与 v421+ 一致)
  - 索引: 主表 tenant+surveyed_at DESC (主查时序) + tenant+market_type +
    tenant+status (审核 workflow); items tenant+survey_id + tenant+ingredient_id;
    photos tenant+survey_id (+ item_id 部分索引)

长期资产: ⭐ 本地早市价数据集 = 连锁餐饮独家壁垒 — AI 训练 + CPI 合作潜力

Revision ID: v435_market_survey_schema
Revises: v434_share_split_rules
Create Date: 2026-05-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v435_market_survey_schema"
down_revision: Union[str, Sequence[str], None] = "v434_share_split_rules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # ─────────────────────────────────────────────────────────────────────────
    # 1. market_surveys 主表
    # ─────────────────────────────────────────────────────────────────────────
    if "market_surveys" not in existing:
        op.execute(
            """
            CREATE TABLE market_surveys (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id           UUID NOT NULL,
                surveyor_id         UUID NOT NULL,
                market_type         VARCHAR(20) NOT NULL,
                location_name       VARCHAR(200) NOT NULL,
                surveyed_at         TIMESTAMPTZ NOT NULL,
                status              VARCHAR(20) NOT NULL DEFAULT 'draft',
                notes               TEXT,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT chk_market_surveys_market_type
                    CHECK (market_type IN ('wholesale','wet_market','supermarket','other')),
                CONSTRAINT chk_market_surveys_status
                    CHECK (status IN ('draft','submitted','verified'))
            )
            """
        )
        op.execute("ALTER TABLE market_surveys ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE market_surveys FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY market_surveys_tenant_isolation
            ON market_surveys
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )
        # 主查询入口: surveyed_at 时序倒序 (移动端调研列表 / 训练池入池查询)
        op.execute(
            """
            CREATE INDEX idx_market_surveys_tenant_surveyed_at
            ON market_surveys (tenant_id, surveyed_at DESC)
            WHERE is_deleted = FALSE
            """
        )
        # market_type 反查: 早市 vs 批发市场价格分布
        op.execute(
            """
            CREATE INDEX idx_market_surveys_tenant_market_type
            ON market_surveys (tenant_id, market_type)
            WHERE is_deleted = FALSE
            """
        )
        # status workflow: 审核员查 submitted 列表
        op.execute(
            """
            CREATE INDEX idx_market_surveys_tenant_status
            ON market_surveys (tenant_id, status)
            WHERE is_deleted = FALSE
            """
        )

    # ─────────────────────────────────────────────────────────────────────────
    # 2. market_survey_items 调研明细
    # ─────────────────────────────────────────────────────────────────────────
    if "market_survey_items" not in existing:
        op.execute(
            """
            CREATE TABLE market_survey_items (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id           UUID NOT NULL,
                survey_id           UUID NOT NULL,
                ingredient_id       UUID,
                ingredient_name     VARCHAR(200) NOT NULL,
                unit_price_fen      BIGINT NOT NULL,
                qty_per_unit        NUMERIC(12,3) NOT NULL DEFAULT 1,
                unit                VARCHAR(20) NOT NULL DEFAULT '斤',
                notes               TEXT,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT chk_market_survey_items_price_positive
                    CHECK (unit_price_fen >= 0),
                CONSTRAINT chk_market_survey_items_qty_positive
                    CHECK (qty_per_unit > 0),
                CONSTRAINT fk_market_survey_items_survey
                    FOREIGN KEY (survey_id) REFERENCES market_surveys(id) ON DELETE CASCADE
            )
            """
        )
        op.execute("ALTER TABLE market_survey_items ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE market_survey_items FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY market_survey_items_tenant_isolation
            ON market_survey_items
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )
        # 主查: 按 survey 加载明细 (UI 详情页 + 训练池 batch read)
        op.execute(
            """
            CREATE INDEX idx_market_survey_items_tenant_survey
            ON market_survey_items (tenant_id, survey_id)
            WHERE is_deleted = FALSE
            """
        )
        # AI 训练池主查: 按 ingredient 聚合多次调研价格
        op.execute(
            """
            CREATE INDEX idx_market_survey_items_tenant_ingredient
            ON market_survey_items (tenant_id, ingredient_id)
            WHERE is_deleted = FALSE AND ingredient_id IS NOT NULL
            """
        )

    # ─────────────────────────────────────────────────────────────────────────
    # 3. market_survey_photos 独立照片表 (创始人决策: AI Vision OCR ready)
    # ─────────────────────────────────────────────────────────────────────────
    if "market_survey_photos" not in existing:
        op.execute(
            """
            CREATE TABLE market_survey_photos (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id           UUID NOT NULL,
                survey_id           UUID NOT NULL,
                item_id             UUID,
                photo_url           VARCHAR(1000) NOT NULL,
                caption             VARCHAR(500),
                exif_meta           JSONB,
                uploaded_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT fk_market_survey_photos_survey
                    FOREIGN KEY (survey_id) REFERENCES market_surveys(id) ON DELETE CASCADE,
                CONSTRAINT fk_market_survey_photos_item
                    FOREIGN KEY (item_id) REFERENCES market_survey_items(id) ON DELETE CASCADE
            )
            """
        )
        op.execute("ALTER TABLE market_survey_photos ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE market_survey_photos FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY market_survey_photos_tenant_isolation
            ON market_survey_photos
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )
        # 主查: 按 survey 加载所有照片 (UI 详情页相册)
        op.execute(
            """
            CREATE INDEX idx_market_survey_photos_tenant_survey
            ON market_survey_photos (tenant_id, survey_id)
            WHERE is_deleted = FALSE
            """
        )
        # 部分索引: item-level photos (item_id NOT NULL 的细颗粒度照片)
        op.execute(
            """
            CREATE INDEX idx_market_survey_photos_tenant_item
            ON market_survey_photos (tenant_id, item_id)
            WHERE is_deleted = FALSE AND item_id IS NOT NULL
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # 顺序倒序: photos → items → surveys (FK 依赖)
    if "market_survey_photos" in existing:
        op.execute("DROP TABLE market_survey_photos CASCADE")
    if "market_survey_items" in existing:
        op.execute("DROP TABLE market_survey_items CASCADE")
    if "market_surveys" in existing:
        op.execute("DROP TABLE market_surveys CASCADE")
