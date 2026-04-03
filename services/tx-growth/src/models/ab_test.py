"""AB测试数据模型 — 实验框架核心表

表：
  ab_tests              — AB测试实验定义（变体内容/分流规则/统计配置）
  ab_test_assignments   — 用户分组记录（幂等，UNIQUE on test_id+customer_id）

金额单位：分(fen)
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase


class ABTest(TenantBase):
    """AB测试实验表

    状态机：draft → running → paused → completed
    支持三种分流模式：random / rfm_based / store_based

    variants 字段示例（JSONB）：
    [
      {"variant": "A", "name": "控制组", "weight": 50,
       "content": {"title": "生日快乐", "description": "满100减20", "offer_fen": 2000}},
      {"variant": "B", "name": "实验组", "weight": 50,
       "content": {"title": "专属生日礼", "description": "满100减40", "offer_fen": 4000}},
    ]
    """

    __tablename__ = "ab_tests"

    # ------------------------------------------------------------------
    # 基本信息
    # ------------------------------------------------------------------

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="实验名称，如：生日祝福文案AB测试",
    )
    campaign_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        comment="关联的营销活动ID（可选）",
    )
    journey_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        comment="关联的营销旅程ID（可选）",
    )

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        comment="实验状态：draft | running | paused | completed",
    )

    # ------------------------------------------------------------------
    # 分流配置
    # ------------------------------------------------------------------

    split_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="random",
        comment="分流类型：random | rfm_based | store_based",
    )

    # ------------------------------------------------------------------
    # 变体定义（JSONB）
    # ------------------------------------------------------------------

    variants: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="变体列表：[{variant, name, weight, content}]，weight 之和须为 100",
    )

    # ------------------------------------------------------------------
    # 目标指标
    # ------------------------------------------------------------------

    primary_metric: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="conversion_rate",
        comment="主目标指标：conversion_rate | revenue | click_rate",
    )

    # ------------------------------------------------------------------
    # 统计设置
    # ------------------------------------------------------------------

    min_sample_size: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=100,
        comment="每组最小样本量，达到后才允许统计显著性判断",
    )
    confidence_level: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.95,
        comment="置信水平，默认 0.95（即 95%）",
    )

    # ------------------------------------------------------------------
    # 时间与结果
    # ------------------------------------------------------------------

    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="实验开始时间",
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="实验结束时间",
    )
    winner_variant: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
        comment="统计显著后自动填入的胜出变体，如 A 或 B",
    )

    # ------------------------------------------------------------------
    # 索引
    # ------------------------------------------------------------------

    __table_args__ = (
        Index(
            "idx_ab_tests_tenant_status",
            "tenant_id",
            "status",
        ),
        Index(
            "idx_ab_tests_campaign",
            "tenant_id",
            "campaign_id",
        ),
        Index(
            "idx_ab_tests_journey",
            "tenant_id",
            "journey_id",
        ),
        {"comment": "AB测试实验表 — 定义变体内容与分流规则"},
    )


class ABTestAssignment(TenantBase):
    """AB测试用户分组记录

    同一用户同一实验只有一条记录（由 UNIQUE(test_id, customer_id) + INSERT ON CONFLICT DO NOTHING 保证幂等）。
    转化发生时更新 is_converted / order_id / order_amount_fen / converted_at。
    """

    __tablename__ = "ab_test_assignments"

    # ------------------------------------------------------------------
    # 关联
    # ------------------------------------------------------------------

    test_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="所属AB测试的 UUID",
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="被分配的客户 UUID",
    )

    # ------------------------------------------------------------------
    # 分组结果
    # ------------------------------------------------------------------

    variant: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="分配到的变体：A 或 B",
    )

    # ------------------------------------------------------------------
    # 转化追踪
    # ------------------------------------------------------------------

    is_converted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否在实验期间内产生转化",
    )
    order_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="转化关联的订单 UUID",
    )
    order_amount_fen: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="转化订单金额（分）",
    )
    converted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="转化时间",
    )

    # ------------------------------------------------------------------
    # 分配时间
    # ------------------------------------------------------------------

    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="分配到变体的时间",
    )

    # ------------------------------------------------------------------
    # 索引与唯一约束
    # ------------------------------------------------------------------

    __table_args__ = (
        # 核心唯一约束：同一用户同一实验只能有一条分配记录
        UniqueConstraint(
            "test_id",
            "customer_id",
            name="uq_ab_test_assignments_test_customer",
        ),
        # 按实验查询所有分配（计算统计时用）
        Index(
            "idx_ab_test_assignments_test_id",
            "tenant_id",
            "test_id",
        ),
        # 按客户查询历史参与（避免重复加入同一实验）
        Index(
            "idx_ab_test_assignments_customer",
            "tenant_id",
            "customer_id",
        ),
        # 转化过滤
        Index(
            "idx_ab_test_assignments_converted",
            "tenant_id",
            "test_id",
            "is_converted",
        ),
        {"comment": "AB测试用户分组记录 — 幂等分配，追踪转化"},
    )
