"""菜品制作时间基准模型 — 存储dish+时段的P50/P90历史基准

每条记录代表：某租户下，某档口的某道菜，在特定时段（hour_bucket）和
日期类型（weekday/weekend）下的历史制作时间统计。
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.ontology.src.base import TenantBase

# 样本数低于此值则标记为不可靠
MIN_RELIABLE_SAMPLES = 10


class CookTimeBaseline(TenantBase):
    """菜品制作时间基准

    数据来源：kds_tasks 表的历史完成记录（completed_at IS NOT NULL）。
    计算方式：按 (dish_id, dept_id, hour_bucket, day_type) 分组，
              用 PostgreSQL PERCENTILE_CONT 函数计算 P50/P90。

    重算频率：每日凌晨 2:00 自动触发，可通过 POST /cook-time/recompute/{dept_id} 手动触发。
    """
    __tablename__ = "cook_time_baselines"

    # ── 分组维度 ──
    dish_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
        comment="菜品ID（关联 dishes 表）"
    )
    dept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
        comment="出品档口ID（关联 production_depts 表）"
    )
    hour_bucket: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="时段（0-23，提取自 kds_tasks.started_at 的小时部分）"
    )
    day_type: Mapped[str] = mapped_column(
        String(10), nullable=False, default="weekday",
        comment="日期类型：weekday（周一至周五）/ weekend（周六周日）"
    )

    # ── 统计数据 ──
    p50_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="制作时间中位数（秒），用于预估正常耗时"
    )
    p90_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="制作时间P90（秒），用于设置警告/超时阈值"
    )
    sample_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment=f"样本数（<{MIN_RELIABLE_SAMPLES}时标记为不可靠，需降级到dept默认值）"
    )

    # ── 元数据 ──
    computed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        comment="本条基准最后一次重算时间"
    )

    # ── 复合索引：高频查询优化 ──
    __table_args__ = (
        Index(
            "ix_cook_time_baselines_lookup",
            "tenant_id", "dish_id", "dept_id", "hour_bucket", "day_type",
            comment="制作时间基准核心查询索引"
        ),
        Index(
            "ix_cook_time_baselines_dept_computed",
            "tenant_id", "dept_id", "computed_at",
            comment="按档口查询最新基准时间"
        ),
    )

    @property
    def is_reliable(self) -> bool:
        """样本数是否达到可靠阈值"""
        return self.sample_count >= MIN_RELIABLE_SAMPLES
