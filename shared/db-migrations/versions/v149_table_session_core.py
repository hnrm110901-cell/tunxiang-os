"""v149 — 桌台会话核心表 (Table Session Core)

桌台中心化架构升级 Phase 1：
将"订单中心"改为"桌台会话中心"，桌台会话 (TableSession) 成为门店业务聚合根。

新增 5 张表（按依赖顺序）：
  table_zones              — 门店区域管理（大厅/包间/吧台/户外）
  waiter_zone_assignments  — 服务员负责区分配（按班次）
  dining_sessions           — 堂食会话（核心聚合根，贯穿一次完整就餐旅程）
  service_calls            — 服务呼叫记录（催菜/呼叫服务员/需要纸巾等）
  dining_session_events     — 会话事件流（每个动作的完整历史审计）

桌台会话9态状态机：
  reserved → seated → ordering → dining → add_ordering
  → billing → paid → clearing → (下一个会话)

设计原则：
- dining_sessions 是每张桌台同一时刻只有一个活跃会话（部分唯一索引保障）
- orders.dining_session_id 外键在 v150 迁移中添加
- 注意：v045 已有 table_sessions 表（扫码协同购物车，不同用途），
  此处新表命名为 dining_sessions（堂食会话，POS侧全生命周期管理）
- 所有表含 tenant_id + RLS 策略，与现有架构一致
- 金额字段单位统一为分（整数）

Revision: v149
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "v149"
down_revision = "v148"
branch_labels = None
depends_on = None

NEW_TABLES = [
    "table_zones",
    "waiter_zone_assignments",
    "dining_sessions",
    "service_calls",
    "dining_session_events",
]


def _enable_rls(table_name: str) -> None:
    """启用 RLS + 租户隔离策略（与现有迁移保持一致）"""
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation_{table_name} ON {table_name} "
        f"USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)"
    )
    op.execute(
        f"CREATE POLICY tenant_insert_{table_name} ON {table_name} "
        f"FOR INSERT WITH CHECK "
        f"(tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID)"
    )


def _disable_rls(table_name: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_insert_{table_name} ON {table_name}")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table_name} ON {table_name}")
    op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:

    # ---------------------------------------------------------------
    # 1. table_zones — 门店区域管理
    #    大厅A区 / 大厅B区 / 包间区 / 吧台 / 户外露台 等
    #    每个区域可配置默认服务模式、最低消费倍率等
    # ---------------------------------------------------------------
    op.create_table(
        "table_zones",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"), comment="区域ID"
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False, index=True),
        sa.Column("zone_name", sa.String(50), nullable=False, comment="区域名称：大厅A区/包间区/吧台"),
        sa.Column(
            "zone_type",
            sa.String(20),
            nullable=False,
            server_default="hall",
            comment="区域类型：hall(大厅)/private_room(包间)/bar(吧台)/outdoor(户外)/takeaway(外卖专区)",
        ),
        sa.Column("floor_no", sa.Integer, server_default="1", comment="所在楼层"),
        sa.Column("table_count", sa.Integer, server_default="0", comment="桌台数量（冗余，便于统计）"),
        sa.Column(
            "min_consume_multiplier",
            sa.Numeric(4, 2),
            server_default="1.0",
            comment="最低消费倍率，1.0=不额外要求，2.0=包间费2倍",
        ),
        sa.Column(
            "service_config",
            JSONB,
            server_default="{}",
            comment="区域服务配置：{self_order_enabled, service_charge_rate, auto_assign_waiter}",
        ),
        sa.Column("sort_order", sa.Integer, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index("idx_table_zones_store", "table_zones", ["store_id", "is_active"])
    op.create_index("idx_table_zones_type", "table_zones", ["store_id", "zone_type"])
    _enable_rls("table_zones")

    # ---------------------------------------------------------------
    # 2. waiter_zone_assignments — 服务员负责区（按班次分配）
    #    支持一个服务员负责多个区，一个区多个服务员（高峰期）
    #    系统根据此表自动路由服务请求和出餐任务
    # ---------------------------------------------------------------
    op.create_table(
        "waiter_zone_assignments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "employee_id",
            UUID(as_uuid=True),
            sa.ForeignKey("employees.id"),
            nullable=False,
            index=True,
            comment="服务员员工ID",
        ),
        sa.Column(
            "zone_id",
            UUID(as_uuid=True),
            sa.ForeignKey("table_zones.id"),
            nullable=False,
            index=True,
            comment="负责区域ID",
        ),
        sa.Column("shift_date", sa.Date, nullable=False, comment="班次日期"),
        sa.Column(
            "shift_type",
            sa.String(20),
            server_default="all_day",
            comment="班次：morning(早班)/afternoon(午班)/evening(晚班)/all_day(全天)",
        ),
        sa.Column("start_time", sa.Time, comment="班次开始时间"),
        sa.Column("end_time", sa.Time, comment="班次结束时间"),
        sa.Column("is_primary", sa.Boolean, server_default="true", comment="是否为主责服务员（多人同区时区分主次）"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "idx_waiter_zone_date",
        "waiter_zone_assignments",
        ["store_id", "shift_date", "zone_id"],
    )
    op.create_index(
        "idx_waiter_zone_employee",
        "waiter_zone_assignments",
        ["employee_id", "shift_date"],
    )
    # waiter_zone_assignments 无 is_deleted，记录为历史数据保留
    # 注：tenant_id 列已在上方 op.create_table 中创建（line 116），无需 ALTER TABLE 重复添加。
    # 历史 v149 曾误以 ALTER TABLE 重复添加 tenant_id，导致 fresh-DB 部署时
    # `column "tenant_id" of relation already exists`。此次 v383 链条整理时一并修复。
    _enable_rls("waiter_zone_assignments")

    # ---------------------------------------------------------------
    # 3. dining_sessions — 堂食会话（核心聚合根）
    #    一次完整就餐旅程的主记录，贯穿开台→点菜→用餐→结账→清台全过程
    #    所有订单、服务呼叫、出餐进度都关联到此表
    # ---------------------------------------------------------------
    op.create_table(
        "dining_sessions",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"), comment="会话ID"
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"), nullable=False, index=True),
        sa.Column(
            "table_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tables.id"),
            nullable=False,
            index=True,
            comment="物理桌台ID（正式FK，替代 orders.table_number 字符串）",
        ),
        sa.Column(
            "session_no",
            sa.String(64),
            nullable=False,
            unique=True,
            comment="会话编号，格式：TS{store_code}{YYYYMMDD}{SEQ}，如 TS010120260405001",
        ),
        # ── 就餐人信息 ──────────────────────────────────────────────
        sa.Column("guest_count", sa.Integer, nullable=False, server_default="1", comment="就餐人数"),
        sa.Column(
            "vip_customer_id",
            UUID(as_uuid=True),
            sa.ForeignKey("customers.id"),
            comment="主要VIP顾客ID（开台时识别/扫码绑定）",
        ),
        sa.Column("booking_id", UUID(as_uuid=True), comment="来源预订单ID（从预订进来时记录）"),
        # ── 状态机（9态）────────────────────────────────────────────
        # reserved    — 已预留（管理员提前锁桌）
        # seated      — 已就坐（开台完成，等待点菜）
        # ordering    — 点菜中（服务员/扫码点餐进行中）
        # dining      — 用餐中（已出餐，正在就餐）
        # add_ordering — 加菜中（餐中追加点单）
        # billing     — 结账中（已请求买单，等待支付）
        # paid        — 已结账（支付完成，未清台）
        # clearing    — 清台中（员工正在清理桌面）
        # disabled    — 暂停服务（内部使用，非正常就餐状态）
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="seated",
            index=True,
            comment="会话状态：reserved/seated/ordering/dining/add_ordering/billing/paid/clearing",
        ),
        # ── 服务归属 ─────────────────────────────────────────────────
        sa.Column(
            "lead_waiter_id",
            UUID(as_uuid=True),
            sa.ForeignKey("employees.id"),
            comment="责任服务员ID（开台时从区域分配自动填充）",
        ),
        sa.Column("zone_id", UUID(as_uuid=True), sa.ForeignKey("table_zones.id"), comment="所属区域ID"),
        # ── 会话类型 ─────────────────────────────────────────────────
        sa.Column(
            "session_type",
            sa.String(20),
            nullable=False,
            server_default="dine_in",
            comment="类型：dine_in(堂食)/banquet(宴席)/vip_room(VIP包间)/self_order(扫码)/hotpot(拼台)",
        ),
        # ── 时间轴关键节点（每个状态变更时记录）───────────────────────
        sa.Column(
            "opened_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), comment="开台时间"
        ),
        sa.Column("first_order_at", sa.DateTime(timezone=True), comment="首次点菜时间"),
        sa.Column("first_dish_served_at", sa.DateTime(timezone=True), comment="首道菜上桌时间"),
        sa.Column("last_dish_served_at", sa.DateTime(timezone=True), comment="最后一道菜上桌时间"),
        sa.Column("bill_requested_at", sa.DateTime(timezone=True), comment="请求买单时间"),
        sa.Column("paid_at", sa.DateTime(timezone=True), comment="结账完成时间"),
        sa.Column("cleared_at", sa.DateTime(timezone=True), comment="清台完成时间"),
        # ── 实时汇总（冗余字段，业务层更新）──────────────────────────
        sa.Column("total_orders", sa.Integer, nullable=False, server_default="0", comment="关联订单数（含加菜单）"),
        sa.Column("total_items", sa.Integer, nullable=False, server_default="0", comment="总点餐品项数"),
        sa.Column(
            "total_amount_fen", sa.Integer, nullable=False, server_default="0", comment="消费总额（分），含折扣前"
        ),
        sa.Column("discount_amount_fen", sa.Integer, nullable=False, server_default="0", comment="折扣总额（分）"),
        sa.Column("final_amount_fen", sa.Integer, nullable=False, server_default="0", comment="实付金额（分）"),
        sa.Column(
            "per_capita_fen",
            sa.Integer,
            nullable=False,
            server_default="0",
            comment="人均消费（分），= final_amount_fen / guest_count",
        ),
        sa.Column(
            "service_call_count",
            sa.Integer,
            nullable=False,
            server_default="0",
            comment="服务呼叫次数（含催菜，用于服务质量分析）",
        ),
        # ── 包间/宴席扩展 ────────────────────────────────────────────
        sa.Column(
            "room_config",
            JSONB,
            server_default="{}",
            comment="包间配置：{room_fee_fen, min_spend_fen, decoration_requests, pre_order_items}",
        ),
        # ── 关联原始 tables.table_no（兼容旧系统/打印场景）────────────
        sa.Column("table_no_snapshot", sa.String(20), comment="开台时记录的桌号快照（避免桌号变更影响历史记录）"),
        # ── 标准字段 ──────────────────────────────────────────────────
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )

    # 同一桌台同一时刻只能有一个活跃会话（部分唯一索引）
    # paid/clearing 之后桌台释放，可以开新会话
    op.execute("""
        CREATE UNIQUE INDEX uq_table_session_active
        ON dining_sessions (store_id, table_id)
        WHERE status NOT IN ('paid', 'clearing', 'disabled')
    """)

    op.create_index("idx_dining_sessions_store_status", "dining_sessions", ["store_id", "status"])
    op.create_index("idx_dining_sessions_opened", "dining_sessions", ["store_id", "opened_at"])
    op.create_index("idx_dining_sessions_waiter", "dining_sessions", ["lead_waiter_id", "store_id"])
    op.create_index(
        "idx_dining_sessions_vip",
        "dining_sessions",
        ["vip_customer_id"],
        postgresql_where=sa.text("vip_customer_id IS NOT NULL"),
    )
    _enable_rls("dining_sessions")

    # ---------------------------------------------------------------
    # 4. service_calls — 服务呼叫记录
    #    涵盖：催菜 / 呼叫服务员 / 需要物品 / 投诉 / 买单请求 / 其他
    #    来源：POS端操作 / 消费者扫码自助呼叫 / 服务员App
    # ---------------------------------------------------------------
    op.create_table(
        "service_calls",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "table_session_id",
            UUID(as_uuid=True),
            sa.ForeignKey("dining_sessions.id"),
            nullable=False,
            index=True,
            comment="关联桌台会话",
        ),
        sa.Column(
            "call_type",
            sa.String(30),
            nullable=False,
            comment="呼叫类型：call_waiter/urge_dish/need_item/complaint/checkout_request/other",
        ),
        sa.Column("content", sa.Text, comment="呼叫内容，如催菜时填菜名，需要物品时填物品名"),
        sa.Column("target_dish_id", UUID(as_uuid=True), comment="催菜时关联的菜品ID（可选）"),
        sa.Column("target_order_item_id", UUID(as_uuid=True), comment="催菜时关联的订单条目ID（可选，精确定位）"),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
            index=True,
            comment="状态：pending(待处理)/handling(处理中)/handled(已处理)/cancelled(已取消)",
        ),
        sa.Column(
            "called_by",
            sa.String(20),
            server_default="pos",
            comment="呼叫来源：pos/self_order(扫码自助)/crew_app(服务员App)/kds",
        ),
        sa.Column("caller_name", sa.String(50), comment="呼叫人姓名或顾客标识"),
        sa.Column("handled_by", UUID(as_uuid=True), sa.ForeignKey("employees.id"), comment="处理员工ID"),
        sa.Column(
            "called_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), comment="呼叫时间"
        ),
        sa.Column("handled_at", sa.DateTime(timezone=True), comment="处理完成时间"),
        sa.Column("response_seconds", sa.Integer, comment="响应时长（秒），= handled_at - called_at，用于服务SLA分析"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_service_calls_session", "service_calls", ["table_session_id", "status"])
    op.create_index("idx_service_calls_store_date", "service_calls", ["store_id", "called_at"])
    op.create_index(
        "idx_service_calls_pending", "service_calls", ["store_id"], postgresql_where=sa.text("status = 'pending'")
    )
    _enable_rls("service_calls")

    # ---------------------------------------------------------------
    # 5. dining_session_events — 会话事件流
    #    记录每个会话的完整动作历史（状态变更/点菜/上菜/服务呼叫/支付等）
    #    append-only，不可修改，用于审计、重放、Agent决策追溯
    #    注意：这是桌台域的业务事件日志，与 shared/events 的跨域事件总线互补
    # ---------------------------------------------------------------
    op.create_table(
        "dining_session_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("store_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "table_session_id",
            UUID(as_uuid=True),
            sa.ForeignKey("dining_sessions.id"),
            nullable=False,
            index=True,
            comment="关联桌台会话",
        ),
        sa.Column(
            "event_type",
            sa.String(60),
            nullable=False,
            comment=(
                "事件类型：table.opened/table.order_placed/table.add_ordered/"
                "table.dish_served/table.service_called/table.bill_requested/"
                "table.paid/table.cleared/table.transferred/table.merged/"
                "table.split/table.vip_identified/table.overstay_alert"
            ),
        ),
        sa.Column(
            "payload",
            JSONB,
            nullable=False,
            server_default="{}",
            comment="事件数据：根据 event_type 不同而不同",
        ),
        sa.Column("operator_id", UUID(as_uuid=True), comment="操作员工ID（POS操作时）"),
        sa.Column(
            "operator_type",
            sa.String(20),
            server_default="employee",
            comment="操作者类型：employee/customer/system/agent",
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            index=True,
            comment="事件发生时间",
        ),
        # 因果链追踪（与 shared/events 一致的设计）
        sa.Column("causation_id", UUID(as_uuid=True), comment="触发此事件的上游事件ID"),
    )
    # 按会话+时间查询（服务员看单张桌的历史）
    op.create_index("idx_tse_session_time", "dining_session_events", ["table_session_id", "occurred_at"])
    # 按门店+时间查询（管理员看全店事件流）
    op.create_index("idx_tse_store_time", "dining_session_events", ["store_id", "occurred_at"])
    # 按事件类型快速筛选（Agent订阅特定类型）
    op.create_index("idx_tse_event_type", "dining_session_events", ["store_id", "event_type", "occurred_at"])
    _enable_rls("dining_session_events")

    # ---------------------------------------------------------------
    # 6. 在 tables 表新增 zone_id 列（关联区域）
    #    为现有 tables 表补充区域归属，支持新的区域管理功能
    # ---------------------------------------------------------------
    op.add_column(
        "tables",
        sa.Column("zone_id", UUID(as_uuid=True), sa.ForeignKey("table_zones.id"), comment="所属区域ID（v149新增）"),
    )
    op.add_column(
        "tables",
        sa.Column("qr_code_url", sa.String(500), comment="桌台二维码URL（扫码点餐/呼叫服务，v149新增）"),
    )
    op.add_column(
        "tables",
        sa.Column(
            "table_type",
            sa.String(20),
            server_default="standard",
            comment="桌型：standard(方桌)/round(圆桌)/booth(卡座)/bar(吧台凳)/private(包间专属），v149新增",
        ),
    )


def downgrade() -> None:
    # 逆序删除，先删子表再删父表

    # 撤销 tables 表新增列
    op.drop_column("tables", "table_type")
    op.drop_column("tables", "qr_code_url")
    op.drop_column("tables", "zone_id")

    # 删除新表（逆依赖顺序）
    for table_name in [
        "dining_session_events",
        "service_calls",
        "dining_sessions",
        "waiter_zone_assignments",
        "table_zones",
    ]:
        _disable_rls(table_name)
        op.drop_table(table_name)
