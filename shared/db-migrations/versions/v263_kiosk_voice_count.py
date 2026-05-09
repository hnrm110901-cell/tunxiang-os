"""v263 — tx-trade 速点终端 + tx-supply 语音盘点

新建（速点终端，服务：tx-trade）：
  kiosk_terminals   — 速点终端注册表
  kiosk_carts       — 购物车（临时会话，TTL 由应用层管理）
  kiosk_orders      — 速点订单
  kiosk_payments    — 速点支付记录

新建（语音盘点，服务：tx-supply）：
  voice_count_sessions    — 语音盘点会话
  voice_count_entries     — 语音录入明细
  inventory_count_sheets  — 正式盘点单（submit 后生成）

共 7 张表，所有含 tenant_id 的表启用 RLS（app.tenant_id）。

Revision ID: v263
Revises: v262
Create Date: 2026-04-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "v263"
down_revision = "v262"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # ── kiosk_terminals ───────────────────────────────────────────────────────
    if "kiosk_terminals" not in existing:
        op.create_table(
            "kiosk_terminals",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("terminal_code", sa.String(50), nullable=False, comment="终端编号，如：KIOSK-01"),
            sa.Column("terminal_name", sa.String(100), nullable=False, comment="终端名称，如：1号自助点单机"),
            sa.Column(
                "terminal_type",
                sa.String(30),
                nullable=True,
                server_default="'self_order'",
                comment="self_order=顾客自助点单 / cashier_assist=收银辅助",
            ),
            sa.Column(
                "display_mode",
                sa.String(20),
                nullable=True,
                server_default="'landscape'",
                comment="landscape=横屏 / portrait=竖屏",
            ),
            sa.Column(
                "payment_modes",
                JSONB,
                nullable=True,
                server_default=sa.text("'[]'::jsonb"),
                comment="支持的支付方式列表，如：[wechat, alipay, unionpay]",
            ),
            sa.Column(
                "welcome_screen_config",
                JSONB,
                nullable=True,
                server_default=sa.text("'{}'::jsonb"),
                comment="欢迎屏配置：{title, subtitle, background_image_url}",
            ),
            sa.Column(
                "idle_timeout_seconds",
                sa.Integer,
                nullable=True,
                server_default="120",
                comment="闲置超时（秒），超时后返回欢迎屏",
            ),
            sa.Column("ad_images", JSONB, nullable=True, server_default=sa.text("'[]'::jsonb"), comment="广告轮播图URL列表"),
            sa.Column(
                "status",
                sa.String(20),
                nullable=True,
                server_default="'inactive'",
                comment="active=在用 / inactive=停用",
            ),
            sa.Column("last_heartbeat_at", sa.TIMESTAMP(timezone=True), nullable=True, comment="最近一次心跳时间"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.UniqueConstraint("tenant_id", "terminal_code", name="uq_kiosk_terminals_tenant_code"),
        )
        op.create_index("idx_kiosk_terminals_store", "kiosk_terminals", ["tenant_id", "store_id"])
        op.create_index("idx_kiosk_terminals_status", "kiosk_terminals", ["tenant_id", "status"])

    op.execute("ALTER TABLE kiosk_terminals ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS kiosk_terminals_tenant ON kiosk_terminals;")
    op.execute("""
        CREATE POLICY kiosk_terminals_tenant ON kiosk_terminals
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── kiosk_carts ───────────────────────────────────────────────────────────
    if "kiosk_carts" not in existing:
        op.create_table(
            "kiosk_carts",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("terminal_id", UUID(as_uuid=True), nullable=False, comment="关联 kiosk_terminals.id"),
            sa.Column("session_token", sa.String(100), nullable=False, comment="会话令牌，唯一标识一次点单会话"),
            sa.Column(
                "items",
                JSONB,
                nullable=True,
                server_default=sa.text("'[]'::jsonb"),
                comment="[{dish_id, dish_name, quantity, unit_price_fen, specs, notes}]",
            ),
            sa.Column("subtotal_fen", sa.BigInteger, nullable=False, server_default="0", comment="小计金额（分）"),
            sa.Column("discounts", JSONB, nullable=True, server_default=sa.text("'[]'::jsonb"), comment="优惠明细列表"),
            sa.Column("total_fen", sa.BigInteger, nullable=False, server_default="0", comment="实付金额（分）"),
            sa.Column("member_id", UUID(as_uuid=True), nullable=True, comment="扫码识别的会员 ID"),
            sa.Column(
                "expires_at", sa.TIMESTAMP(timezone=True), nullable=False, comment="购物车过期时间，过期后应用层清理"
            ),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["terminal_id"], ["kiosk_terminals.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("terminal_id", "session_token", name="uq_kiosk_carts_terminal_session"),
        )
        op.create_index("idx_kiosk_carts_terminal", "kiosk_carts", ["terminal_id", "session_token"])
        op.create_index("idx_kiosk_carts_expires", "kiosk_carts", ["expires_at"])

    op.execute("ALTER TABLE kiosk_carts ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS kiosk_carts_tenant ON kiosk_carts;")
    op.execute("""
        CREATE POLICY kiosk_carts_tenant ON kiosk_carts
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── kiosk_orders ──────────────────────────────────────────────────────────
    if "kiosk_orders" not in existing:
        op.create_table(
            "kiosk_orders",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("terminal_id", UUID(as_uuid=True), nullable=False, comment="关联 kiosk_terminals.id"),
            sa.Column(
                "cart_id", UUID(as_uuid=True), nullable=True, comment="关联 kiosk_carts.id，下单后购物车可复用或归档"
            ),
            sa.Column("order_no", sa.String(50), nullable=False, unique=True, comment="速点订单号，系统自动生成"),
            sa.Column("queue_number", sa.String(20), nullable=True, comment="叫号编号，格式：K001"),
            sa.Column("member_id", UUID(as_uuid=True), nullable=True, comment="关联会员 ID"),
            sa.Column(
                "dining_type",
                sa.String(20),
                nullable=True,
                server_default="'dine_in'",
                comment="dine_in=堂食 / takeaway=外带",
            ),
            sa.Column("table_no", sa.String(20), nullable=True, comment="桌号（堂食时填写）"),
            sa.Column("items", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb"), comment="订单菜品快照列表"),
            sa.Column("subtotal_fen", sa.BigInteger, nullable=False, comment="小计金额（分）"),
            sa.Column("discount_fen", sa.BigInteger, nullable=False, server_default="0", comment="优惠金额（分）"),
            sa.Column("total_fen", sa.BigInteger, nullable=False, comment="实付金额（分）"),
            sa.Column(
                "status",
                sa.String(20),
                nullable=True,
                server_default="'pending'",
                comment="pending=待支付 / paid=已支付 / preparing=备餐中 "
                "/ ready=可取餐 / completed=已完成 / cancelled=已取消",
            ),
            sa.Column("estimated_wait_minutes", sa.Integer, nullable=True, comment="预计等待时长（分钟）"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["terminal_id"], ["kiosk_terminals.id"]),
            sa.ForeignKeyConstraint(["cart_id"], ["kiosk_carts.id"]),
        )
        op.create_index("idx_kiosk_orders_store", "kiosk_orders", ["tenant_id", "store_id"])
        op.create_index("idx_kiosk_orders_terminal", "kiosk_orders", ["terminal_id", "status"])
        op.create_index("idx_kiosk_orders_created", "kiosk_orders", ["tenant_id", sa.text("created_at DESC")])

    op.execute("ALTER TABLE kiosk_orders ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS kiosk_orders_tenant ON kiosk_orders;")
    op.execute("""
        CREATE POLICY kiosk_orders_tenant ON kiosk_orders
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── kiosk_payments ────────────────────────────────────────────────────────
    if "kiosk_payments" not in existing:
        op.create_table(
            "kiosk_payments",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("kiosk_order_id", UUID(as_uuid=True), nullable=False, comment="关联 kiosk_orders.id"),
            sa.Column(
                "payment_method",
                sa.String(30),
                nullable=True,
                comment="wechat=微信 / alipay=支付宝 / card=银行卡 / cash=现金",
            ),
            sa.Column("amount_fen", sa.BigInteger, nullable=False, comment="支付金额（分）"),
            sa.Column(
                "payment_status",
                sa.String(20),
                nullable=True,
                server_default="'pending'",
                comment="pending=待支付 / success=成功 / failed=失败 / refunded=已退款",
            ),
            sa.Column("transaction_no", sa.String(100), nullable=True, comment="第三方支付流水号（微信/支付宝单号）"),
            sa.Column("scan_code", sa.String(200), nullable=True, comment="主扫时顾客出示的付款码内容"),
            sa.Column("qr_polling_key", sa.String(100), nullable=True, comment="被扫时生成的二维码轮询 key"),
            sa.Column("paid_at", sa.TIMESTAMP(timezone=True), nullable=True, comment="实际支付完成时间"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["kiosk_order_id"], ["kiosk_orders.id"]),
        )
        op.create_index("idx_kiosk_payments_order", "kiosk_payments", ["kiosk_order_id"])
        op.execute("""
            CREATE INDEX idx_kiosk_payments_polling
                ON kiosk_payments (qr_polling_key)
                WHERE qr_polling_key IS NOT NULL;
        """)

    op.execute("ALTER TABLE kiosk_payments ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS kiosk_payments_tenant ON kiosk_payments;")
    op.execute("""
        CREATE POLICY kiosk_payments_tenant ON kiosk_payments
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── voice_count_sessions ──────────────────────────────────────────────────
    if "voice_count_sessions" not in existing:
        op.create_table(
            "voice_count_sessions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column("warehouse_id", UUID(as_uuid=True), nullable=True, comment="仓库 ID，NULL 表示门店默认仓库"),
            sa.Column(
                "count_type",
                sa.String(20),
                nullable=True,
                server_default="'full'",
                comment="full=全盘 / partial=部分盘 / spot=抽盘",
            ),
            sa.Column(
                "category_filter",
                JSONB,
                nullable=True,
                server_default=sa.text("'[]'::jsonb"),
                comment="限定盘点的商品分类 ID 列表，空表示不限",
            ),
            sa.Column(
                "status",
                sa.String(20),
                nullable=True,
                server_default="'in_progress'",
                comment="in_progress=盘点中 / closed=已关闭（未提交） / submitted=已提交",
            ),
            sa.Column("operator_id", UUID(as_uuid=True), nullable=True, comment="操作员工 ID"),
            sa.Column(
                "item_list",
                JSONB,
                nullable=True,
                server_default=sa.text("'[]'::jsonb"),
                comment="[{item_id, item_name, unit, expected_count}]，盘点目标清单",
            ),
            sa.Column("total_items", sa.Integer, nullable=False, server_default="0", comment="计划盘点品项总数"),
            sa.Column("counted_items", sa.Integer, nullable=False, server_default="0", comment="已录入品项数"),
            sa.Column(
                "started_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
                comment="开始时间",
            ),
            sa.Column("closed_at", sa.TIMESTAMP(timezone=True), nullable=True, comment="关闭时间（关闭或提交后写入）"),
            sa.Column("submitted_at", sa.TIMESTAMP(timezone=True), nullable=True, comment="提交正式盘点单的时间"),
        )
        op.create_index("idx_voice_sessions_store", "voice_count_sessions", ["tenant_id", "store_id", "status"])

    op.execute("ALTER TABLE voice_count_sessions ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS voice_count_sessions_tenant ON voice_count_sessions;")
    op.execute("""
        CREATE POLICY voice_count_sessions_tenant ON voice_count_sessions
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── voice_count_entries ───────────────────────────────────────────────────
    if "voice_count_entries" not in existing:
        op.create_table(
            "voice_count_entries",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("session_id", UUID(as_uuid=True), nullable=False, comment="关联 voice_count_sessions.id"),
            sa.Column("item_id", UUID(as_uuid=True), nullable=False, comment="物料 ID（逻辑引用 ingredients.id）"),
            sa.Column("item_name", sa.String(200), nullable=False, comment="物料名称（快照，防止改名后历史数据失真）"),
            sa.Column("quantity", sa.Numeric(12, 3), nullable=False, comment="盘点数量"),
            sa.Column("unit", sa.String(20), nullable=True, comment="计量单位，如：公斤/个/箱"),
            sa.Column(
                "source",
                sa.String(20),
                nullable=True,
                server_default="'voice'",
                comment="voice=语音录入 / manual=手动修正",
            ),
            sa.Column("original_text", sa.Text, nullable=True, comment="原始语音识别文字，用于审计和二次解析"),
            sa.Column("asr_confidence", sa.Numeric(4, 3), nullable=True, comment="ASR 识别置信度，0.000~1.000"),
            sa.Column(
                "match_confidence", sa.String(10), nullable=True, comment="物料匹配置信度：high=高 / medium=中 / low=低"
            ),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["session_id"], ["voice_count_sessions.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("session_id", "item_id", name="uq_voice_count_entries_session_item"),
        )
        op.create_index("idx_voice_entries_session", "voice_count_entries", ["session_id"])

    op.execute("ALTER TABLE voice_count_entries ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS voice_count_entries_tenant ON voice_count_entries;")
    op.execute("""
        CREATE POLICY voice_count_entries_tenant ON voice_count_entries
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── inventory_count_sheets ────────────────────────────────────────────────
    if "inventory_count_sheets" not in existing:
        op.create_table(
            "inventory_count_sheets",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "session_id",
                UUID(as_uuid=True),
                nullable=True,
                comment="关联 voice_count_sessions.id，手工录入的盘点单可为 NULL",
            ),
            sa.Column(
                "sheet_no",
                sa.String(50),
                nullable=False,
                unique=True,
                comment="盘点单号，系统自动生成，格式：IC{YYYYMMDD}{4位序号}",
            ),
            sa.Column("count_date", sa.Date, nullable=False, comment="盘点日期"),
            sa.Column("total_items", sa.Integer, nullable=False, server_default="0", comment="盘点品项总数"),
            sa.Column("variance_items", sa.Integer, nullable=False, server_default="0", comment="存在差异的品项数"),
            sa.Column(
                "total_variance_amount_fen",
                sa.BigInteger,
                nullable=False,
                server_default="0",
                comment="差异总金额（分），正=盘盈，负=盘亏",
            ),
            sa.Column(
                "details",
                JSONB,
                nullable=True,
                server_default=sa.text("'[]'::jsonb"),
                comment="完整盘点明细快照（含预期/实盘/差异/金额）",
            ),
            sa.Column(
                "status",
                sa.String(20),
                nullable=True,
                server_default="'pending'",
                comment="pending=待审批 / approved=已审批 / posted=已过账",
            ),
            sa.Column("created_by", UUID(as_uuid=True), nullable=True, comment="创建人员工 ID"),
            sa.Column("approved_by", UUID(as_uuid=True), nullable=True, comment="审批人员工 ID"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("approved_at", sa.TIMESTAMP(timezone=True), nullable=True, comment="审批时间"),
            sa.ForeignKeyConstraint(["session_id"], ["voice_count_sessions.id"]),
        )
        op.create_index(
            "idx_count_sheets_store", "inventory_count_sheets", ["tenant_id", "store_id", sa.text("count_date DESC")]
        )

    op.execute("ALTER TABLE inventory_count_sheets ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS inventory_count_sheets_tenant ON inventory_count_sheets;")
    op.execute("""
        CREATE POLICY inventory_count_sheets_tenant ON inventory_count_sheets
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)


def downgrade() -> None:
    op.drop_table("inventory_count_sheets")
    op.drop_table("voice_count_entries")
    op.drop_table("voice_count_sessions")
    op.drop_table("kiosk_payments")
    op.drop_table("kiosk_orders")
    op.drop_table("kiosk_carts")
    op.drop_table("kiosk_terminals")
