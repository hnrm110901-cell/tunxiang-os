"""督导差旅费用系统：差旅申请 + 行程明细 + 费用分摊
Tables: travel_requests, travel_itineraries, travel_allocations
Sprint: P1-S3（数据层提前建设，服务层在P1-S3实现）

设计原则：
  - 差旅申请与屯象OS巡店任务深度打通（inspection_task_id）
  - GPS轨迹驱动里程计算，替代自报里程
  - 费用按实际签到时长自动分摊到各门店成本中心

Revision ID: v239
Revises: v238
Create Date: 2026-04-12
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, NUMERIC, UUID

revision = "v239"
down_revision = "v238b"
branch_labels = None
depends_on = None

# 标准安全 RLS 条件（NULLIF 保护，与 v231 规范一致）
_RLS_COND = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def upgrade() -> None:
    conn = op.get_bind()
    existing = sa.inspect(conn).get_table_names()

    # ------------------------------------------------------------------
    # 表1：travel_requests（差旅申请主表）
    # ------------------------------------------------------------------

    if "travel_requests" not in existing:
        op.create_table(
            "travel_requests",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"), nullable=False
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("brand_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False, comment="申请人所属门店"),
            sa.Column("traveler_id", UUID(as_uuid=True), nullable=False, comment="出行人员工ID"),
            sa.Column("applicant_id", UUID(as_uuid=True), nullable=False, comment="申请人（可能不同于出行人）"),
            # 关联屯象OS巡店任务（核心打通点）
            sa.Column(
                "inspection_task_id",
                UUID(as_uuid=True),
                nullable=True,
                comment="关联的巡店任务ID（可空，非巡店差旅为NULL）",
            ),
            sa.Column(
                "task_type",
                sa.String(30),
                nullable=False,
                server_default="inspection",
                comment="值域：inspection（巡店）/ training（培训）/ meeting（会议）/ other（其他）",
            ),
            # 行程信息
            sa.Column("departure_city", sa.String(50), nullable=True, comment="出发城市"),
            sa.Column(
                "destination_cities",
                JSONB,
                nullable=True,
                server_default=sa.text("'[]'::jsonb"),
                comment="目的地城市列表（多城市行程）",
            ),
            sa.Column(
                "planned_stores",
                JSONB,
                nullable=True,
                server_default=sa.text("'[]'::jsonb"),
                comment="计划巡店的门店ID列表",
            ),
            sa.Column("planned_start_date", sa.Date(), nullable=False),
            sa.Column("planned_end_date", sa.Date(), nullable=False),
            sa.Column("planned_days", sa.Integer(), nullable=False, server_default="1", comment="计划天数"),
            # 适用差标
            sa.Column("staff_level", sa.String(30), nullable=True, comment="出行人职级（提交时固化）"),
            sa.Column(
                "applicable_standards",
                JSONB,
                nullable=True,
                server_default=sa.text("'{}'::jsonb"),
                comment="适用的差标快照（提交时固化）",
            ),
            # 交通方式（申请人选择）
            sa.Column(
                "transport_mode",
                sa.String(20),
                nullable=False,
                server_default="train",
                comment="值域：plane（飞机）/ train（高铁/火车）/ car（自驾）/ other（其他）",
            ),
            sa.Column(
                "estimated_cost_fen",
                sa.BigInteger(),
                nullable=True,
                server_default="0",
                comment="预估总费用，单位：分(fen)，展示时除以100转元",
            ),
            # 状态
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="draft",
                comment="值域：draft / submitted / approved / in_progress / completed / rejected / cancelled",
            ),
            sa.Column("approval_instance_id", UUID(as_uuid=True), nullable=True, comment="关联的审批实例"),
            # 实际数据（行程完成后填写）
            sa.Column("actual_start_date", sa.Date(), nullable=True),
            sa.Column("actual_end_date", sa.Date(), nullable=True),
            sa.Column("actual_days", sa.Integer(), nullable=True),
            sa.Column(
                "total_mileage_km",
                NUMERIC(10, 2),
                nullable=True,
                server_default="0",
                comment="实际里程（公里，GPS计算）",
            ),
            sa.Column(
                "total_cost_fen",
                sa.BigInteger(),
                nullable=True,
                server_default="0",
                comment="实际总费用，单位：分(fen)，展示时除以100转元",
            ),
            sa.Column(
                "mileage_allowance_fen",
                sa.BigInteger(),
                nullable=True,
                server_default="0",
                comment="里程补贴，单位：分(fen)，展示时除以100转元，GPS核实后计算",
            ),
            # 报销单关联
            sa.Column("expense_application_id", UUID(as_uuid=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["expense_application_id"],
                ["expense_applications.id"],
                name="fk_travel_requests_expense_application_id",
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=True, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True, server_default=sa.text("now()")),
            sa.Column("is_deleted", sa.Boolean(), nullable=True, server_default="false"),
        )

        # 索引
        op.create_index(
            "ix_travel_requests_tenant_traveler_status",
            "travel_requests",
            ["tenant_id", "traveler_id", "status"],
        )
        op.create_index(
            "ix_travel_requests_tenant_inspection_task",
            "travel_requests",
            ["tenant_id", "inspection_task_id"],
            postgresql_where=sa.text("inspection_task_id IS NOT NULL"),
        )
        op.create_index(
            "ix_travel_requests_tenant_brand_start_date",
            "travel_requests",
            ["tenant_id", "brand_id", "planned_start_date"],
        )
        op.create_index(
            "ix_travel_requests_tenant_created_at",
            "travel_requests",
            ["tenant_id", sa.text("created_at DESC")],
        )

        # RLS
        op.execute("ALTER TABLE travel_requests ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY travel_requests_tenant_isolation
            ON travel_requests
            USING ({_RLS_COND})
            """
        )

        # ------------------------------------------------------------------
        # 表2：travel_itineraries（行程明细）
        # ------------------------------------------------------------------

    if "travel_itineraries" not in existing:
        op.create_table(
            "travel_itineraries",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"), nullable=False
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("travel_request_id", UUID(as_uuid=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["travel_request_id"],
                ["travel_requests.id"],
                name="fk_travel_itineraries_travel_request_id",
                ondelete="CASCADE",
            ),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False, comment="本次到访的门店"),
            sa.Column("store_name", sa.String(100), nullable=True, comment="冗余存储门店名（避免关联查询）"),
            # 时间记录
            sa.Column("checkin_time", sa.TIMESTAMP(timezone=True), nullable=True, comment="到达签到时间"),
            sa.Column("checkout_time", sa.TIMESTAMP(timezone=True), nullable=True, comment="离开签退时间"),
            sa.Column("duration_minutes", sa.Integer(), nullable=True, server_default="0", comment="停留时长（分钟）"),
            # GPS数据
            sa.Column(
                "checkin_location", JSONB, nullable=True, comment='{"lat": float, "lng": float, "accuracy": float}'
            ),
            sa.Column("checkout_location", JSONB, nullable=True),
            sa.Column(
                "gps_track",
                JSONB,
                nullable=True,
                server_default=sa.text("'[]'::jsonb"),
                comment="轨迹点列表（精简存储，每5分钟1个点）",
            ),
            sa.Column("distance_from_store_m", sa.Integer(), nullable=True, comment="签到时距门店距离（米）"),
            # 里程
            sa.Column(
                "leg_mileage_km",
                NUMERIC(10, 2),
                nullable=True,
                server_default="0",
                comment="本段里程（到达本门店的路程）",
            ),
            sa.Column(
                "is_mileage_anomaly",
                sa.Boolean(),
                nullable=True,
                server_default="false",
                comment="GPS里程异常标记（绕路>30%）",
            ),
            sa.Column("anomaly_reason", sa.Text(), nullable=True, comment="异常说明"),
            # 状态
            sa.Column(
                "itinerary_status",
                sa.String(20),
                nullable=False,
                server_default="planned",
                comment="值域：planned / checked_in / checked_out / skipped（计划未到访）",
            ),
            sa.Column("skip_reason", sa.Text(), nullable=True, comment="未到访原因"),
            sa.Column("sequence_order", sa.Integer(), nullable=False, server_default="0", comment="行程顺序"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=True, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True, server_default=sa.text("now()")),
        )

        # 索引
        op.create_index(
            "ix_travel_itineraries_tenant_request_order",
            "travel_itineraries",
            ["tenant_id", "travel_request_id", "sequence_order"],
        )
        op.create_index(
            "ix_travel_itineraries_tenant_store",
            "travel_itineraries",
            ["tenant_id", "store_id"],
        )
        op.create_index(
            "ix_travel_itineraries_tenant_checkin_time",
            "travel_itineraries",
            ["tenant_id", "checkin_time"],
        )

        # RLS
        op.execute("ALTER TABLE travel_itineraries ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY travel_itineraries_tenant_isolation
            ON travel_itineraries
            USING ({_RLS_COND})
            """
        )

        # ------------------------------------------------------------------
        # 表3：travel_allocations（费用分摊明细）
        # ------------------------------------------------------------------

    if "travel_allocations" not in existing:
        op.create_table(
            "travel_allocations",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"), nullable=False
            ),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("travel_request_id", UUID(as_uuid=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["travel_request_id"],
                ["travel_requests.id"],
                name="fk_travel_allocations_travel_request_id",
                ondelete="CASCADE",
            ),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False, comment="分摊到的门店"),
            sa.Column("brand_id", UUID(as_uuid=True), nullable=False),
            # 分摊规则
            sa.Column(
                "allocation_basis",
                sa.String(20),
                nullable=False,
                server_default="duration",
                comment="值域：duration（按停留时长）/ equal（平均分摊）/ manual（手工指定）",
            ),
            sa.Column("basis_value", NUMERIC(10, 4), nullable=True, comment="分摊基准值（如停留分钟数）"),
            sa.Column("allocation_rate", NUMERIC(7, 6), nullable=False, comment="分摊比例（0.000000-1.000000）"),
            # 分摊金额
            sa.Column(
                "total_travel_cost_fen",
                sa.BigInteger(),
                nullable=False,
                comment="本次差旅总费用，单位：分(fen)，展示时除以100转元",
            ),
            sa.Column(
                "allocated_amount_fen",
                sa.BigInteger(),
                nullable=False,
                comment="分摊到本门店的金额，单位：分(fen)，展示时除以100转元",
            ),
            # 成本归因
            sa.Column("cost_center_id", UUID(as_uuid=True), nullable=True, comment="成本中心ID（关联门店）"),
            sa.Column(
                "is_attributed", sa.Boolean(), nullable=True, server_default="false", comment="是否已归入门店P&L"
            ),
            sa.Column("attributed_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=True, server_default=sa.text("now()")),
        )

        # 索引
        op.create_index(
            "ix_travel_allocations_tenant_request",
            "travel_allocations",
            ["tenant_id", "travel_request_id"],
        )
        op.create_index(
            "ix_travel_allocations_tenant_store_attributed",
            "travel_allocations",
            ["tenant_id", "store_id", "is_attributed"],
        )
        op.create_unique_constraint(
            "uq_travel_allocations_tenant_request_store",
            "travel_allocations",
            ["tenant_id", "travel_request_id", "store_id"],
        )

        # RLS
        op.execute("ALTER TABLE travel_allocations ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY travel_allocations_tenant_isolation
            ON travel_allocations
            USING ({_RLS_COND})
            """
        )


def downgrade() -> None:
    # 按依赖反向删除

    # travel_allocations
    op.execute("DROP POLICY IF EXISTS travel_allocations_tenant_isolation ON travel_allocations")
    op.drop_table("travel_allocations")

    # travel_itineraries
    op.execute("DROP POLICY IF EXISTS travel_itineraries_tenant_isolation ON travel_itineraries")
    op.drop_table("travel_itineraries")

    # travel_requests
    op.execute("DROP POLICY IF EXISTS travel_requests_tenant_isolation ON travel_requests")
    op.drop_table("travel_requests")
