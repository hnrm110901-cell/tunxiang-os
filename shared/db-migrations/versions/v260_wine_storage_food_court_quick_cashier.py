"""v260 — tx-trade 新增：存酒管理、美食广场、快餐档口队列、orders演示模式字段

新建：
  wine_storage_records        — 存酒主记录
  wine_storage_transactions   — 存酒操作流水
  food_courts                 — 商街/美食广场（统一收银场所）
  food_court_vendors          — 商街档口（子商户）
  food_court_orders           — 商街统一订单
  food_court_order_items      — 商街订单行（按档口分组）
  food_court_vendor_settlements — 档口日结记录
  quick_cashier_counters      — 快餐档口
  quick_cashier_queue         — 快餐排队队列

修改：
  orders — 新增 is_demo / demo_session_id 字段（演示模式标记）

所有含 tenant_id 的表启用 RLS（app.tenant_id）。

Revision ID: v260b
Revises: v259
Create Date: 2026-04-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "v260b"
down_revision = "v259"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # ── wine_storage_records ──────────────────────────────────────────────────
    if "wine_storage_records" not in existing:
        op.create_table(
            "wine_storage_records",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", sa.String(64), nullable=False, comment="门店 ID"),
            sa.Column("table_id", sa.String(64), nullable=True, comment="台位 ID（可选）"),
            sa.Column("member_id", UUID(as_uuid=True), nullable=True, comment="会员 ID（可选）"),
            sa.Column("bottle_code", sa.String(64), nullable=False, comment="酒水编号/条码"),
            sa.Column("wine_name", sa.String(128), nullable=False, comment="酒水名称"),
            sa.Column("wine_brand", sa.String(128), nullable=True, comment="品牌"),
            sa.Column("wine_spec", sa.String(64), nullable=True, comment="规格，如 500ml/750ml"),
            sa.Column("quantity", sa.Integer, nullable=False, comment="存入数量"),
            sa.Column("remaining_quantity", sa.Integer, nullable=False, comment="剩余数量"),
            sa.Column("unit", sa.String(16), nullable=False, server_default="'瓶'", comment="单位：瓶/支/升"),
            sa.Column("storage_date", sa.Date, nullable=False, comment="存酒日期"),
            sa.Column("expiry_date", sa.Date, nullable=True, comment="到期日，NULL=长期有效"),
            sa.Column(
                "status",
                sa.String(32),
                nullable=False,
                server_default="'stored'",
                comment="stored/partial_taken/fully_taken/expired/written_off",
            ),
            sa.Column("storage_price", sa.Numeric(12, 2), nullable=True, comment="存入时金额（元）"),
            sa.Column("notes", sa.Text, nullable=True),
            sa.Column("created_by", sa.String(64), nullable=True, comment="操作员 ID"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
        op.create_index("ix_wine_storage_records_tenant_store", "wine_storage_records", ["tenant_id", "store_id"])
        op.create_index("ix_wine_storage_records_bottle_code", "wine_storage_records", ["bottle_code"])
        op.create_index("ix_wine_storage_records_member_id", "wine_storage_records", ["member_id"])
        op.create_index("ix_wine_storage_records_status", "wine_storage_records", ["tenant_id", "status"])
        op.create_index("ix_wine_storage_records_table_id", "wine_storage_records", ["table_id"])

    op.execute("ALTER TABLE wine_storage_records ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS wine_storage_records_tenant ON wine_storage_records;")
    op.execute("""
        CREATE POLICY wine_storage_records_tenant ON wine_storage_records
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── wine_storage_transactions ─────────────────────────────────────────────
    if "wine_storage_transactions" not in existing:
        op.create_table(
            "wine_storage_transactions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("record_id", UUID(as_uuid=True), nullable=False, comment="关联 wine_storage_records.id"),
            sa.Column("store_id", sa.String(64), nullable=False),
            sa.Column(
                "trans_type",
                sa.String(32),
                nullable=False,
                comment="store_in/take_out/extend/transfer_in/transfer_out/write_off/adjustment",
            ),
            sa.Column("quantity", sa.Integer, nullable=False, comment="本次操作数量（正数）"),
            sa.Column("price_at_trans", sa.Numeric(12, 2), nullable=True, comment="操作时单价或费用（元）"),
            sa.Column("table_id", sa.String(64), nullable=True, comment="关联台位（取酒/转台时）"),
            sa.Column("order_id", sa.String(64), nullable=True, comment="关联订单 ID（取酒核销时）"),
            sa.Column("operated_by", sa.String(64), nullable=True, comment="操作员 ID"),
            sa.Column("operated_at", sa.TIMESTAMP(timezone=True), nullable=True, comment="操作时间"),
            sa.Column("approved_by", sa.String(64), nullable=True, comment="审批人 ID（核销/调整时）"),
            sa.Column("notes", sa.Text, nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
            sa.ForeignKeyConstraint(["record_id"], ["wine_storage_records.id"], ondelete="RESTRICT"),
        )
        op.create_index("ix_wine_storage_transactions_record_id", "wine_storage_transactions", ["record_id"])
        op.create_index(
            "ix_wine_storage_transactions_store_type", "wine_storage_transactions", ["store_id", "trans_type"]
        )
        op.create_index("ix_wine_storage_transactions_tenant", "wine_storage_transactions", ["tenant_id"])

    op.execute("ALTER TABLE wine_storage_transactions ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS wine_storage_transactions_tenant ON wine_storage_transactions;")
    op.execute("""
        CREATE POLICY wine_storage_transactions_tenant ON wine_storage_transactions
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── food_courts ───────────────────────────────────────────────────────────
    if "food_courts" not in existing:
        op.create_table(
            "food_courts",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False, comment="所属主门店 ID"),
            sa.Column("name", sa.String(100), nullable=False, comment="商街名称，如：XX美食广场"),
            sa.Column("description", sa.String(500), nullable=True, comment="描述/简介"),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="'active'",
                comment="active=营业中 / inactive=停用",
            ),
            sa.Column(
                "unified_cashier", sa.Boolean, nullable=False, server_default="true", comment="是否启用统一收银台"
            ),
            sa.Column(
                "config", JSONB, nullable=True, server_default="'{}'", comment="扩展配置 JSON（营业时间、收银台数量等）"
            ),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
        op.create_index("ix_food_courts_tenant_store", "food_courts", ["tenant_id", "store_id"])

    op.execute("ALTER TABLE food_courts ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS food_courts_tenant ON food_courts;")
    op.execute("""
        CREATE POLICY food_courts_tenant ON food_courts
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── food_court_vendors ────────────────────────────────────────────────────
    if "food_court_vendors" not in existing:
        op.create_table(
            "food_court_vendors",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("food_court_id", UUID(as_uuid=True), nullable=False, comment="所属商街 ID"),
            sa.Column("vendor_code", sa.String(20), nullable=False, comment="档口编号，如 A1/B2（同一商街内唯一）"),
            sa.Column("vendor_name", sa.String(100), nullable=False, comment="档口名称"),
            sa.Column("category", sa.String(50), nullable=True, comment="档口分类：烧腊/粉面/饮料/小吃/快餐等"),
            sa.Column("owner_name", sa.String(50), nullable=True, comment="档主姓名"),
            sa.Column("contact_phone", sa.String(20), nullable=True, comment="联系电话"),
            sa.Column("commission_rate", sa.Numeric(5, 4), nullable=True, comment="抽成比例（如 0.08 = 8%）"),
            sa.Column("kds_station_id", sa.String(50), nullable=True, comment="对应 KDS 档口站点 ID"),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="'active'",
                comment="active=正常营业 / inactive=暂停 / suspended=被暂停",
            ),
            sa.Column("settlement_account", JSONB, nullable=True, server_default="'{}'", comment="结算账户信息 JSON"),
            sa.Column(
                "display_order",
                sa.Integer,
                nullable=False,
                server_default="1",
                comment="排列顺序（收银台菜单分组顺序）",
            ),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
            sa.ForeignKeyConstraint(["food_court_id"], ["food_courts.id"], ondelete="RESTRICT"),
        )
        op.create_index("ix_food_court_vendors_court_id", "food_court_vendors", ["food_court_id"])
        op.create_index("ix_food_court_vendors_tenant", "food_court_vendors", ["tenant_id"])

    op.execute("ALTER TABLE food_court_vendors ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS food_court_vendors_tenant ON food_court_vendors;")
    op.execute("""
        CREATE POLICY food_court_vendors_tenant ON food_court_vendors
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── food_court_orders ─────────────────────────────────────────────────────
    if "food_court_orders" not in existing:
        op.create_table(
            "food_court_orders",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("food_court_id", UUID(as_uuid=True), nullable=False, comment="所属商街 ID"),
            sa.Column(
                "order_no", sa.String(50), nullable=False, unique=True, comment="订单号，格式：FC{YYYYMMDD}{6位序号}"
            ),
            sa.Column("total_amount_fen", sa.Integer, nullable=False, comment="订单总金额（分）"),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="'pending'",
                comment="pending=待支付 / paid=已支付 / completed=已完成 / cancelled=已取消",
            ),
            sa.Column(
                "payment_method",
                sa.String(30),
                nullable=True,
                comment="支付方式：cash/wechat/alipay/unionpay/member_balance",
            ),
            sa.Column("paid_at", sa.TIMESTAMP(timezone=True), nullable=True, comment="支付完成时间"),
            sa.Column("cashier_id", sa.String(50), nullable=True, comment="收银员工号/ID"),
            sa.Column("notes", sa.String(500), nullable=True, comment="订单备注"),
            sa.Column(
                "idempotency_key", sa.String(128), nullable=True, unique=True, comment="支付幂等键，防止重复支付"
            ),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
            sa.ForeignKeyConstraint(["food_court_id"], ["food_courts.id"], ondelete="RESTRICT"),
        )
        op.create_index("ix_food_court_orders_court_id_status", "food_court_orders", ["food_court_id", "status"])
        op.create_index("ix_food_court_orders_tenant", "food_court_orders", ["tenant_id"])
        op.create_index("ix_food_court_orders_order_no", "food_court_orders", ["order_no"])

    op.execute("ALTER TABLE food_court_orders ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS food_court_orders_tenant ON food_court_orders;")
    op.execute("""
        CREATE POLICY food_court_orders_tenant ON food_court_orders
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── food_court_order_items ────────────────────────────────────────────────
    if "food_court_order_items" not in existing:
        op.create_table(
            "food_court_order_items",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("order_id", UUID(as_uuid=True), nullable=False, comment="所属商街订单 ID"),
            sa.Column("vendor_id", UUID(as_uuid=True), nullable=False, comment="所属档口 ID（KDS 分发依据）"),
            sa.Column("dish_name", sa.String(100), nullable=False, comment="菜品名称（冗余存储）"),
            sa.Column("dish_id", sa.String(50), nullable=True, comment="菜品 ID（档口有自己菜单时填写）"),
            sa.Column("quantity", sa.Integer, nullable=False, comment="数量"),
            sa.Column("unit_price_fen", sa.Integer, nullable=False, comment="单价（分）"),
            sa.Column("subtotal_fen", sa.Integer, nullable=False, comment="小计（分）= quantity × unit_price_fen"),
            sa.Column("notes", sa.String(200), nullable=True, comment="菜品备注/做法要求"),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="'pending'",
                comment="pending=待制作 / preparing=制作中 / ready=已出餐 / served=已取餐",
            ),
            sa.Column("ready_at", sa.TIMESTAMP(timezone=True), nullable=True, comment="档口标记出餐时间"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
            sa.ForeignKeyConstraint(["order_id"], ["food_court_orders.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["vendor_id"], ["food_court_vendors.id"], ondelete="RESTRICT"),
        )
        op.create_index("ix_food_court_order_items_order_id", "food_court_order_items", ["order_id"])
        op.create_index("ix_food_court_order_items_vendor_id", "food_court_order_items", ["vendor_id"])

    op.execute("ALTER TABLE food_court_order_items ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS food_court_order_items_tenant ON food_court_order_items;")
    op.execute("""
        CREATE POLICY food_court_order_items_tenant ON food_court_order_items
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── food_court_vendor_settlements ─────────────────────────────────────────
    if "food_court_vendor_settlements" not in existing:
        op.create_table(
            "food_court_vendor_settlements",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("vendor_id", UUID(as_uuid=True), nullable=False, comment="档口 ID"),
            sa.Column("food_court_id", UUID(as_uuid=True), nullable=False, comment="商街 ID"),
            sa.Column("settlement_date", sa.Date, nullable=False, comment="结算日期"),
            sa.Column("order_count", sa.Integer, nullable=False, server_default="0", comment="当日订单笔数"),
            sa.Column("item_count", sa.Integer, nullable=False, server_default="0", comment="当日菜品份数"),
            sa.Column("gross_amount_fen", sa.Integer, nullable=False, server_default="0", comment="当日营业总额（分）"),
            sa.Column("commission_fen", sa.Integer, nullable=False, server_default="0", comment="平台抽成（分）"),
            sa.Column(
                "net_amount_fen",
                sa.Integer,
                nullable=False,
                server_default="0",
                comment="档口实得金额（分）= gross - commission",
            ),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="'pending'",
                comment="pending=待结算 / settled=已结算",
            ),
            sa.Column("settled_at", sa.TIMESTAMP(timezone=True), nullable=True, comment="结算确认时间"),
            sa.Column("operator_id", sa.String(50), nullable=True, comment="财务确认人 ID"),
            sa.Column("details", JSONB, nullable=True, server_default="'{}'", comment="结算明细快照 JSON"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
            sa.ForeignKeyConstraint(["vendor_id"], ["food_court_vendors.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["food_court_id"], ["food_courts.id"], ondelete="RESTRICT"),
        )
        op.create_index(
            "ix_food_court_vendor_settlements_vendor_date",
            "food_court_vendor_settlements",
            ["vendor_id", "settlement_date"],
        )
        op.create_index(
            "ix_food_court_vendor_settlements_court_date",
            "food_court_vendor_settlements",
            ["food_court_id", "settlement_date"],
        )
        op.create_index("ix_food_court_vendor_settlements_tenant", "food_court_vendor_settlements", ["tenant_id"])

    op.execute("ALTER TABLE food_court_vendor_settlements ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS food_court_vendor_settlements_tenant ON food_court_vendor_settlements;")
    op.execute("""
        CREATE POLICY food_court_vendor_settlements_tenant ON food_court_vendor_settlements
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── quick_cashier_counters ────────────────────────────────────────────────
    if "quick_cashier_counters" not in existing:
        op.create_table(
            "quick_cashier_counters",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False, comment="所属门店 ID"),
            sa.Column("counter_code", sa.String(20), nullable=False, comment="档口编号"),
            sa.Column("counter_name", sa.String(100), nullable=False, comment="档口名称"),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="'closed'",
                comment="open=营业中 / closed=已关闭",
            ),
            sa.Column("operator_id", UUID(as_uuid=True), nullable=True, comment="当前当班操作员 ID"),
            sa.Column(
                "queue_length",
                sa.Integer,
                nullable=False,
                server_default="0",
                comment="当前排队人数（冗余字段，写操作同步更新）",
            ),
            sa.Column(
                "config",
                JSONB,
                nullable=False,
                server_default="'{}'",
                comment="档口配置 JSON（最大排队数、叫号前缀等）",
            ),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        )
        op.create_index("ix_quick_cashier_counters_tenant_store", "quick_cashier_counters", ["tenant_id", "store_id"])
        op.create_index("ix_quick_cashier_counters_status", "quick_cashier_counters", ["store_id", "status"])

    op.execute("ALTER TABLE quick_cashier_counters ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS quick_cashier_counters_tenant ON quick_cashier_counters;")
    op.execute("""
        CREATE POLICY quick_cashier_counters_tenant ON quick_cashier_counters
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── quick_cashier_queue ───────────────────────────────────────────────────
    if "quick_cashier_queue" not in existing:
        op.create_table(
            "quick_cashier_queue",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False, comment="门店 ID"),
            sa.Column("counter_id", UUID(as_uuid=True), nullable=True, comment="关联档口 ID"),
            sa.Column("queue_number", sa.String(20), nullable=True, comment="叫号号码，如 A001"),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="'waiting'",
                comment="waiting=等待中 / processing=服务中 / done=已完成 / left=已离开",
            ),
            sa.Column(
                "customer_info",
                JSONB,
                nullable=False,
                server_default="'{}'",
                comment="顾客信息（手机号/会员 ID 等，非必填）",
            ),
            sa.Column(
                "joined_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
                comment="入队时间",
            ),
            sa.Column("processed_at", sa.TIMESTAMP(timezone=True), nullable=True, comment="开始服务时间"),
            sa.ForeignKeyConstraint(["counter_id"], ["quick_cashier_counters.id"], ondelete="SET NULL"),
        )
        op.create_index("ix_quick_cashier_queue_counter_status", "quick_cashier_queue", ["counter_id", "status"])
        op.create_index("ix_quick_cashier_queue_tenant_store", "quick_cashier_queue", ["tenant_id", "store_id"])

    op.execute("ALTER TABLE quick_cashier_queue ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS quick_cashier_queue_tenant ON quick_cashier_queue;")
    op.execute("""
        CREATE POLICY quick_cashier_queue_tenant ON quick_cashier_queue
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── orders: 新增演示模式字段 ───────────────────────────────────────────────
    if "orders" in existing:
        col_names = {c["name"] for c in inspector.get_columns("orders")}
        if "is_demo" not in col_names:
            op.add_column(
                "orders",
                sa.Column("is_demo", sa.Boolean, nullable=False, server_default="false", comment="是否为演示模式订单"),
            )
        if "demo_session_id" not in col_names:
            op.add_column(
                "orders",
                sa.Column("demo_session_id", sa.String(100), nullable=True, comment="演示会话 ID"),
            )
        # 偏过滤索引：只索引演示订单（WHERE is_demo = TRUE）
        op.execute("""
            CREATE INDEX IF NOT EXISTS idx_orders_is_demo
                ON orders(store_id, is_demo) WHERE is_demo = TRUE;
        """)


def downgrade() -> None:
    # 删除 orders 演示模式字段
    op.execute("DROP INDEX IF EXISTS idx_orders_is_demo;")
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "orders" in set(inspector.get_table_names()):
        col_names = {c["name"] for c in inspector.get_columns("orders")}
        if "demo_session_id" in col_names:
            op.drop_column("orders", "demo_session_id")
        if "is_demo" in col_names:
            op.drop_column("orders", "is_demo")

    # 按依赖反序删除新建表
    op.drop_table("quick_cashier_queue")
    op.drop_table("quick_cashier_counters")
    op.drop_table("food_court_vendor_settlements")
    op.drop_table("food_court_order_items")
    op.drop_table("food_court_orders")
    op.drop_table("food_court_vendors")
    op.drop_table("food_courts")
    op.drop_table("wine_storage_transactions")
    op.drop_table("wine_storage_records")
