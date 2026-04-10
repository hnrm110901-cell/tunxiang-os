"""营销活动引擎持久化 — campaign_engine 内存→DB

campaigns / campaign_participants 表在 v097 已创建，本迁移补充新字段、
新索引，以支持 campaign_engine_db_routes.py 的完整持久化接口。

新增字段：
  campaigns            — start_at / end_at（列别名）、target_audience、rules、
                         applicable_stores、priority、max_per_member、
                         total_participants、used_fen、created_by
  campaign_participants — member_id、order_id、participation_type、
                          discount_applied_fen、points_earned、store_id

Revision ID: v193
Revises: v192
Create Date: 2026-04-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'v193'
down_revision = 'v192'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── 1. campaigns — 补充缺失字段 ──────────────────────────────────────────

    # start_at / end_at（v097 用的是 start_time / end_time，补充标准命名列）
    op.add_column('campaigns',
        sa.Column('start_at', sa.TIMESTAMP(timezone=True), nullable=True,
                  comment='活动开始时间（标准命名，兼容 start_time）'))
    op.add_column('campaigns',
        sa.Column('end_at', sa.TIMESTAMP(timezone=True), nullable=True,
                  comment='活动结束时间（标准命名，兼容 end_time）'))

    # 目标人群（{"levels": ["VIP"], "min_spend": 10000}）
    op.add_column('campaigns',
        sa.Column('target_audience',
                  postgresql.JSONB(astext_type=sa.Text()),
                  server_default='{}', nullable=False,
                  comment='目标人群：{"levels": ["VIP"], "min_spend": 10000}'))

    # 活动规则（{"threshold_fen": 10000, "discount_rate": 0.9}）
    op.add_column('campaigns',
        sa.Column('rules',
                  postgresql.JSONB(astext_type=sa.Text()),
                  server_default='{}', nullable=False,
                  comment='活动规则：{"threshold_fen": 10000, "discount_rate": 0.9}'))

    # 适用门店（空列表=全部）
    op.add_column('campaigns',
        sa.Column('applicable_stores',
                  postgresql.JSONB(astext_type=sa.Text()),
                  server_default='[]', nullable=False,
                  comment='适用门店列表，空=全部'))

    # 优先级（冲突时高优先执行）
    op.add_column('campaigns',
        sa.Column('priority', sa.Integer(), server_default='0', nullable=False,
                  comment='优先级，冲突时高优先执行'))

    # 每会员最多参与次数
    op.add_column('campaigns',
        sa.Column('max_per_member', sa.Integer(), nullable=True,
                  comment='每会员最多参与次数，NULL=不限'))

    # 参与人次（汇总计数）
    op.add_column('campaigns',
        sa.Column('total_participants', sa.Integer(), server_default='0', nullable=False,
                  comment='参与人次'))

    # 已使用金额（分）
    op.add_column('campaigns',
        sa.Column('used_fen', sa.BigInteger(), server_default='0', nullable=False,
                  comment='已使用金额（分）'))

    # 创建人
    op.add_column('campaigns',
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True,
                  comment='创建人 UUID'))

    # ─── 2. campaign_participants — 补充缺失字段 ──────────────────────────────

    # member_id（会员ID，兼容原有 customer_id）
    op.add_column('campaign_participants',
        sa.Column('member_id', postgresql.UUID(as_uuid=True), nullable=True,
                  comment='会员 UUID（标准命名，兼容 customer_id）'))

    # 关联订单
    op.add_column('campaign_participants',
        sa.Column('order_id', postgresql.UUID(as_uuid=True), nullable=True,
                  comment='关联订单 UUID'))

    # 参与类型
    op.add_column('campaign_participants',
        sa.Column('participation_type', sa.VARCHAR(20), nullable=True,
                  comment='joined/used/expired'))

    # 本次享受折扣金额（分）
    op.add_column('campaign_participants',
        sa.Column('discount_applied_fen', sa.BigInteger(),
                  server_default='0', nullable=False,
                  comment='本次享受折扣金额（分）'))

    # 本次获得积分
    op.add_column('campaign_participants',
        sa.Column('points_earned', sa.Integer(),
                  server_default='0', nullable=False,
                  comment='本次获得积分'))

    # 门店
    op.add_column('campaign_participants',
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=True,
                  comment='服务门店 UUID'))

    # ─── 3. 新增索引（高频查询路径）─────────────────────────────────────────────

    # campaigns — tenant 基础索引（v097 已有复合索引，这里补纯 tenant 索引）
    op.create_index('idx_campaigns_tenant', 'campaigns', ['tenant_id'],
                    postgresql_where=sa.text('is_deleted = false'))

    # campaigns — tenant+status 复合（v097 已有 idx_campaigns_tenant_status，跳过重建）

    # campaigns — 时间段查询（按 start_at/end_at 筛选活动）
    op.create_index('idx_campaigns_time', 'campaigns', ['tenant_id', 'start_at', 'end_at'],
                    postgresql_where=sa.text('is_deleted = false'))

    # campaign_participants — tenant
    op.create_index('idx_campaign_participants_tenant',
                    'campaign_participants', ['tenant_id'])

    # campaign_participants — campaign
    op.create_index('idx_campaign_participants_campaign',
                    'campaign_participants', ['campaign_id'])

    # campaign_participants — 会员参与历史（member_id + tenant）
    op.create_index('idx_campaign_participants_member',
                    'campaign_participants', ['tenant_id', 'member_id'],
                    postgresql_where=sa.text('member_id IS NOT NULL'))


def downgrade() -> None:
    # 删除新增索引
    op.drop_index('idx_campaign_participants_member',  table_name='campaign_participants')
    op.drop_index('idx_campaign_participants_campaign', table_name='campaign_participants')
    op.drop_index('idx_campaign_participants_tenant',  table_name='campaign_participants')
    op.drop_index('idx_campaigns_time',   table_name='campaigns')
    op.drop_index('idx_campaigns_tenant', table_name='campaigns')

    # 删除 campaign_participants 新增列
    for col in ('store_id', 'points_earned', 'discount_applied_fen',
                'participation_type', 'order_id', 'member_id'):
        op.drop_column('campaign_participants', col)

    # 删除 campaigns 新增列
    for col in ('created_by', 'used_fen', 'total_participants', 'max_per_member',
                'priority', 'applicable_stores', 'rules', 'target_audience',
                'end_at', 'start_at'):
        op.drop_column('campaigns', col)
