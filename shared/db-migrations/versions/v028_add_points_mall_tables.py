"""v028: 添加积分商城表（points_mall_products + points_mall_orders）

新增两张表：
  points_mall_products  — 商城商品主档（实物/优惠券/菜品兑换/储值金）
  points_mall_orders    — 兑换订单

商品字段说明：
  product_type:     physical | coupon | dish | stored_value
  stock:            -1 = 不限库存；>= 0 = 有限库存（库存面值）
  stock_sold:       已兑换数量（不限库存时只增 stock_sold）
  product_content:  JSONB，各商品类型内容不同：
    coupon:       {"coupon_template_id": "xxx", "amount_fen": 1000}
    dish:         {"dish_id": "xxx", "dish_name": "辣子鸡"}
    stored_value: {"amount_fen": 500}
    physical:     {"sku": "xxx", "weight_g": 50}
  limit_per_customer: 每人限购次数（0=不限）
  limit_per_period:   每周期限购次数（0=不限）
  limit_period_days:  限购周期天数

订单 status 流转：
  pending → fulfilled（核销/自动发放）
  pending → cancelled（取消并退积分）
  pending → expired （超期未核销，由定时任务驱动）

索引：
  - points_mall_products: (tenant_id, is_active), (tenant_id, sort_order)
  - points_mall_orders:   (tenant_id, customer_id), (tenant_id, status),
                          (tenant_id, product_id), order_no UNIQUE

RLS 策略：
  使用 v006+ 标准安全模式（4 操作 + NULL 值 guard + FORCE ROW LEVEL SECURITY）
  current_setting('app.tenant_id', TRUE) IS NOT NULL
  AND current_setting('app.tenant_id', TRUE) <> ''
  AND tenant_id = current_setting('app.tenant_id')::UUID

Revision ID: v028
Revises: v027
Create Date: 2026-03-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "v028"
down_revision = "v027"
branch_labels = None
depends_on = None

# RLS 条件（v006+ 标准安全模式）
_RLS_COND = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = current_setting('app.tenant_id')::UUID"
)


def upgrade() -> None:
    # ----------------------------------------------------------------
    # 1. points_mall_products
    # ----------------------------------------------------------------
    op.create_table(
        "points_mall_products",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  onupdate=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),

        # 基本信息
        sa.Column("name", sa.String(100), nullable=False, comment="商品名称"),
        sa.Column("description", sa.Text(), nullable=True, comment="商品描述"),
        sa.Column("image_url", sa.String(500), nullable=True, comment="商品图片URL"),

        # 商品类型
        sa.Column("product_type", sa.String(20), nullable=False,
                  comment="physical=实物 | coupon=优惠券 | dish=菜品兑换 | stored_value=储值金"),

        # 积分定价
        sa.Column("points_required", sa.Integer(), nullable=False, comment="所需积分（正整数）"),

        # 库存：-1 = 不限
        sa.Column("stock", sa.Integer(), nullable=False, server_default="-1",
                  comment="-1=不限库存；>=0=有限库存"),
        sa.Column("stock_sold", sa.Integer(), nullable=False, server_default="0",
                  comment="累计已兑换数量"),

        # 商品内容（JSONB）
        sa.Column("product_content", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb"),
                  comment="商品内容详情，结构因 product_type 不同"),

        # 兑换限制
        sa.Column("limit_per_customer", sa.Integer(), nullable=False, server_default="0",
                  comment="每人最多兑换次数（0=不限）"),
        sa.Column("limit_per_period", sa.Integer(), nullable=False, server_default="0",
                  comment="每周期最多兑换次数（0=不限）"),
        sa.Column("limit_period_days", sa.Integer(), nullable=False, server_default="30",
                  comment="限购统计周期（天数）"),

        # 展示与状态
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true",
                  comment="是否上架"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0",
                  comment="排序权重，ASC 越小越靠前"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True,
                  comment="上架生效时间（NULL=立即生效）"),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True,
                  comment="下架时间（NULL=永久有效）"),

        comment="积分商城商品主档",
    )

    op.create_index(
        "idx_pm_products_tenant_id",
        "points_mall_products",
        ["tenant_id"],
    )
    op.create_index(
        "idx_pm_products_tenant_active",
        "points_mall_products",
        ["tenant_id", "is_active"],
    )
    op.create_index(
        "idx_pm_products_tenant_sort",
        "points_mall_products",
        ["tenant_id", "sort_order"],
    )

    # ----------------------------------------------------------------
    # 2. points_mall_orders
    # ----------------------------------------------------------------
    op.create_table(
        "points_mall_orders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  onupdate=sa.func.now(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),

        # 订单标识
        sa.Column("order_no", sa.String(40), nullable=False, unique=True,
                  comment="订单号 PM-{YYYYMMDD}-{6位大写随机}"),

        # 关联
        sa.Column("customer_id", UUID(as_uuid=True), nullable=False,
                  comment="兑换顾客 ID"),
        sa.Column("product_id", UUID(as_uuid=True),
                  sa.ForeignKey("points_mall_products.id", ondelete="RESTRICT"),
                  nullable=False, comment="兑换商品 ID"),
        sa.Column("store_id", UUID(as_uuid=True), nullable=True,
                  comment="兑换门店（实物需填）"),

        # 兑换信息
        sa.Column("points_deducted", sa.Integer(), nullable=False, comment="扣除积分"),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1",
                  comment="兑换数量"),

        # 状态
        sa.Column("status", sa.String(20), nullable=False, server_default="pending",
                  comment="pending | fulfilled | cancelled | expired"),

        # 配送信息（实物商品）
        sa.Column("delivery_address", sa.String(500), nullable=True, comment="配送地址"),
        sa.Column("delivery_name", sa.String(50), nullable=True, comment="收件人姓名"),
        sa.Column("delivery_phone", sa.String(20), nullable=True, comment="收件人电话"),
        sa.Column("tracking_no", sa.String(100), nullable=True, comment="快递单号"),

        # 关联业务
        sa.Column("coupon_id", UUID(as_uuid=True), nullable=True,
                  comment="兑换所发放的优惠券 ID"),

        # 操作时间戳
        sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True,
                  comment="核销/发放完成时间"),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True,
                  comment="取消时间"),
        sa.Column("cancel_reason", sa.String(200), nullable=True, comment="取消原因"),

        comment="积分商城兑换订单",
    )

    # order_no UNIQUE 已由 unique=True 建立，再建复合查询索引
    op.create_index(
        "idx_pm_orders_tenant_id",
        "points_mall_orders",
        ["tenant_id"],
    )
    op.create_index(
        "idx_pm_orders_customer",
        "points_mall_orders",
        ["tenant_id", "customer_id"],
    )
    op.create_index(
        "idx_pm_orders_status",
        "points_mall_orders",
        ["tenant_id", "status"],
    )
    op.create_index(
        "idx_pm_orders_product",
        "points_mall_orders",
        ["tenant_id", "product_id"],
    )
    op.create_index(
        "idx_pm_orders_customer_created",
        "points_mall_orders",
        ["tenant_id", "customer_id", "created_at"],
    )

    # ----------------------------------------------------------------
    # 3. RLS — points_mall_products
    # ----------------------------------------------------------------
    op.execute("ALTER TABLE points_mall_products ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE points_mall_products FORCE ROW LEVEL SECURITY;")

    op.execute(f"""
        CREATE POLICY rls_pm_products_select
            ON points_mall_products FOR SELECT
            USING ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_pm_products_insert
            ON points_mall_products FOR INSERT
            WITH CHECK ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_pm_products_update
            ON points_mall_products FOR UPDATE
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_pm_products_delete
            ON points_mall_products FOR DELETE
            USING ({_RLS_COND});
    """)

    # ----------------------------------------------------------------
    # 4. RLS — points_mall_orders
    # ----------------------------------------------------------------
    op.execute("ALTER TABLE points_mall_orders ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE points_mall_orders FORCE ROW LEVEL SECURITY;")

    op.execute(f"""
        CREATE POLICY rls_pm_orders_select
            ON points_mall_orders FOR SELECT
            USING ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_pm_orders_insert
            ON points_mall_orders FOR INSERT
            WITH CHECK ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_pm_orders_update
            ON points_mall_orders FOR UPDATE
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_pm_orders_delete
            ON points_mall_orders FOR DELETE
            USING ({_RLS_COND});
    """)


def downgrade() -> None:
    # ---- 先删 RLS 策略再删表 ----

    # points_mall_orders
    for policy in [
        "rls_pm_orders_select",
        "rls_pm_orders_insert",
        "rls_pm_orders_update",
        "rls_pm_orders_delete",
    ]:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON points_mall_orders;")
    op.execute("ALTER TABLE points_mall_orders DISABLE ROW LEVEL SECURITY;")

    # points_mall_products
    for policy in [
        "rls_pm_products_select",
        "rls_pm_products_insert",
        "rls_pm_products_update",
        "rls_pm_products_delete",
    ]:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON points_mall_products;")
    op.execute("ALTER TABLE points_mall_products DISABLE ROW LEVEL SECURITY;")

    # 删索引
    for idx, table in [
        ("idx_pm_orders_customer_created", "points_mall_orders"),
        ("idx_pm_orders_product", "points_mall_orders"),
        ("idx_pm_orders_status", "points_mall_orders"),
        ("idx_pm_orders_customer", "points_mall_orders"),
        ("idx_pm_orders_tenant_id", "points_mall_orders"),
        ("idx_pm_products_tenant_sort", "points_mall_products"),
        ("idx_pm_products_tenant_active", "points_mall_products"),
        ("idx_pm_products_tenant_id", "points_mall_products"),
    ]:
        op.drop_index(idx, table_name=table)

    # 先删子表，再删父表
    op.drop_table("points_mall_orders")
    op.drop_table("points_mall_products")
