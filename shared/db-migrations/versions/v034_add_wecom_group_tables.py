"""v031: 添加企微群运营表（wecom_group_configs + wecom_group_messages）

解决的问题：支持企微群运营 SOP，包括群配置管理和消息发送历史记录。

新增表：
  wecom_group_configs    — 群运营配置（群名、目标分群、建群规则、SOP日历）
  wecom_group_messages   — 群消息发送历史（类型、内容、状态、归因SOP类型）

索引设计：
  wecom_group_configs：
    (tenant_id, status)                   — 筛选 active 群（定时任务扫描路径）
    (tenant_id, target_segment_id)        — 按分群查群配置
    (tenant_id,)                          — RLS 基础

  wecom_group_messages：
    (tenant_id, group_config_id, sent_at) — 消息历史核心查询路径
    (tenant_id, sop_type, sent_at)        — 按 SOP 类型统计
    (tenant_id, status, sent_at)          — 发送成功率统计
    (tenant_id,)                          — RLS 基础

RLS 策略：
  使用 v006+ 标准安全模式（4 操作 + NULL guard + FORCE ROW LEVEL SECURITY）
  current_setting('app.tenant_id', TRUE) IS NOT NULL
  AND current_setting('app.tenant_id', TRUE) <> ''
  AND tenant_id = current_setting('app.tenant_id')::UUID

Revision ID: v031
Revises: v030
Create Date: 2026-03-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "v034"
down_revision = "v033"
branch_labels = None
depends_on = None

# RLS 条件（v006+ 标准模式，禁止 NULL 绕过）
_RLS_COND = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = current_setting('app.tenant_id')::UUID"
)


def upgrade() -> None:
    # ----------------------------------------------------------------
    # 1. 创建 wecom_group_configs 表
    # ----------------------------------------------------------------
    op.create_table(
        "wecom_group_configs",

        # 基础字段
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),

        # 群基本信息
        sa.Column(
            "group_name",
            sa.String(100),
            nullable=False,
            comment='群名称，如"高端海鲜VIP群"',
        ),
        sa.Column(
            "group_chat_id",
            sa.String(100),
            nullable=True,
            comment="企微群 chatid（建群后回填）",
        ),

        # 目标分群
        sa.Column(
            "target_segment_id",
            sa.String(100),
            nullable=False,
            comment="关联 tx-growth 分群 ID，如 rfm_champions",
        ),
        sa.Column(
            "target_store_ids",
            JSONB,
            nullable=False,
            server_default="'[]'",
            comment="目标门店 UUID 列表（空数组=全部门店）",
        ),

        # 建群规则
        sa.Column(
            "max_members",
            sa.Integer(),
            nullable=False,
            server_default="200",
            comment="最大群成员数（企微上限500）",
        ),
        sa.Column(
            "auto_invite",
            sa.Boolean(),
            nullable=False,
            server_default="true",
            comment="是否自动邀请符合条件的新会员",
        ),

        # SOP 内容日历
        sa.Column(
            "sop_calendar",
            JSONB,
            nullable=False,
            server_default="'[]'",
            comment=(
                "SOP 内容日历，JSONB 数组，支持 daily/weekly/holiday/new_dish 类型\n"
                "示例：[{\"type\":\"daily\",\"time\":\"09:00\",\"content\":\"早安...\"}]"
            ),
        ),

        # 状态
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="'active'",
            comment="active | paused | disbanded",
        ),

        comment="企微群运营配置表",
    )

    # ----------------------------------------------------------------
    # 2. wecom_group_configs 索引
    # ----------------------------------------------------------------

    # 定时任务扫描路径：找出所有 active 群
    op.create_index(
        "idx_wecom_group_configs_tenant_status",
        "wecom_group_configs",
        ["tenant_id", "status"],
    )

    # 按分群查群配置
    op.create_index(
        "idx_wecom_group_configs_segment",
        "wecom_group_configs",
        ["tenant_id", "target_segment_id"],
    )

    # tenant_id 单列索引（RLS 基础）
    op.create_index(
        "idx_wecom_group_configs_tenant_id",
        "wecom_group_configs",
        ["tenant_id"],
    )

    # ----------------------------------------------------------------
    # 3. 创建 wecom_group_messages 表
    # ----------------------------------------------------------------
    op.create_table(
        "wecom_group_messages",

        # 基础字段
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "group_config_id",
            UUID(as_uuid=True),
            nullable=False,
            comment="关联 wecom_group_configs.id",
        ),
        sa.Column(
            "group_chat_id",
            sa.String(100),
            nullable=False,
            comment="企微群 chatid",
        ),

        # 消息内容
        sa.Column(
            "message_type",
            sa.String(20),
            nullable=False,
            comment="text | image | news | miniapp",
        ),
        sa.Column(
            "content",
            sa.Text(),
            nullable=False,
            comment="消息内容（JSON 序列化字符串）",
        ),
        sa.Column(
            "sop_type",
            sa.String(30),
            nullable=True,
            comment="daily | weekly | holiday | new_dish | manual",
        ),

        # 发送状态
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="发送时间",
        ),
        sa.Column(
            "sent_by",
            sa.String(100),
            nullable=False,
            server_default="'system'",
            comment="发送者：system 或员工的企微 userid",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="'sent'",
            comment="sent | failed",
        ),
        sa.Column(
            "error_msg",
            sa.Text(),
            nullable=True,
            comment="发送失败时的错误信息",
        ),

        comment="企微群消息发送历史记录表",
    )

    # ----------------------------------------------------------------
    # 4. wecom_group_messages 索引
    # ----------------------------------------------------------------

    # 核心查询路径：某群的消息历史时序
    op.create_index(
        "idx_wecom_group_messages_config_sent_at",
        "wecom_group_messages",
        ["tenant_id", "group_config_id", "sent_at"],
    )

    # 按 SOP 类型统计发送频率
    op.create_index(
        "idx_wecom_group_messages_sop_type",
        "wecom_group_messages",
        ["tenant_id", "sop_type", "sent_at"],
    )

    # 发送成功率统计
    op.create_index(
        "idx_wecom_group_messages_status",
        "wecom_group_messages",
        ["tenant_id", "status", "sent_at"],
    )

    # tenant_id 单列索引（RLS 基础）
    op.create_index(
        "idx_wecom_group_messages_tenant_id",
        "wecom_group_messages",
        ["tenant_id"],
    )

    # ----------------------------------------------------------------
    # 5. RLS — wecom_group_configs
    # ----------------------------------------------------------------
    op.execute("ALTER TABLE wecom_group_configs ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE wecom_group_configs FORCE ROW LEVEL SECURITY;")

    op.execute(f"""
        CREATE POLICY rls_wecom_group_configs_select
            ON wecom_group_configs FOR SELECT
            USING ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_wecom_group_configs_insert
            ON wecom_group_configs FOR INSERT
            WITH CHECK ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_wecom_group_configs_update
            ON wecom_group_configs FOR UPDATE
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_wecom_group_configs_delete
            ON wecom_group_configs FOR DELETE
            USING ({_RLS_COND});
    """)

    # ----------------------------------------------------------------
    # 6. RLS — wecom_group_messages
    # ----------------------------------------------------------------
    op.execute("ALTER TABLE wecom_group_messages ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE wecom_group_messages FORCE ROW LEVEL SECURITY;")

    op.execute(f"""
        CREATE POLICY rls_wecom_group_messages_select
            ON wecom_group_messages FOR SELECT
            USING ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_wecom_group_messages_insert
            ON wecom_group_messages FOR INSERT
            WITH CHECK ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_wecom_group_messages_update
            ON wecom_group_messages FOR UPDATE
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_wecom_group_messages_delete
            ON wecom_group_messages FOR DELETE
            USING ({_RLS_COND});
    """)


def downgrade() -> None:
    # 逆序：先删 RLS 再删索引再删表

    # wecom_group_messages RLS
    for policy in [
        "rls_wecom_group_messages_select",
        "rls_wecom_group_messages_insert",
        "rls_wecom_group_messages_update",
        "rls_wecom_group_messages_delete",
    ]:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON wecom_group_messages;")
    op.execute("ALTER TABLE wecom_group_messages DISABLE ROW LEVEL SECURITY;")

    # wecom_group_configs RLS
    for policy in [
        "rls_wecom_group_configs_select",
        "rls_wecom_group_configs_insert",
        "rls_wecom_group_configs_update",
        "rls_wecom_group_configs_delete",
    ]:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON wecom_group_configs;")
    op.execute("ALTER TABLE wecom_group_configs DISABLE ROW LEVEL SECURITY;")

    # wecom_group_messages 索引
    for idx in [
        "idx_wecom_group_messages_tenant_id",
        "idx_wecom_group_messages_status",
        "idx_wecom_group_messages_sop_type",
        "idx_wecom_group_messages_config_sent_at",
    ]:
        op.drop_index(idx, table_name="wecom_group_messages")

    # wecom_group_configs 索引
    for idx in [
        "idx_wecom_group_configs_tenant_id",
        "idx_wecom_group_configs_segment",
        "idx_wecom_group_configs_tenant_status",
    ]:
        op.drop_index(idx, table_name="wecom_group_configs")

    # 删表（先删消息表，因为它引用配置表）
    op.drop_table("wecom_group_messages")
    op.drop_table("wecom_group_configs")
