"""
决策权重学习模型

存储每个门店（或全局）当前学到的优先级权重，以及学习历史快照。
通过 DecisionWeightLearner 在每次执行反馈后在线更新。
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, JSON, String

from .base import Base


class DecisionWeightConfig(Base):
    """
    决策优先级权重配置

    scope 格式：
      "global"           — 全局默认权重（所有门店共享）
      "store:{store_id}" — 门店专属权重（优先级高于 global）
    """
    __tablename__ = "decision_weight_configs"

    id = Column(String(64), primary_key=True, comment="scope 值即主键（global | store:xxx）")

    # 四维权重（sum=1.0，范围 [0.05, 0.60]）
    w_financial  = Column(Float, nullable=False, default=0.40, comment="财务影响权重")
    w_urgency    = Column(Float, nullable=False, default=0.30, comment="紧急度权重")
    w_confidence = Column(Float, nullable=False, default=0.20, comment="置信度权重")
    w_execution  = Column(Float, nullable=False, default=0.10, comment="执行难度权重")

    # 学习统计
    sample_count = Column(Integer, nullable=False, default=0, comment="已学习的反馈样本数")
    last_updated = Column(DateTime, nullable=True, comment="上次权重更新时间")

    # 最近 20 次更新历史（JSON，用于可视化权重进化轨迹）
    update_history = Column(JSON, nullable=False, default=list, comment="最近权重更新历史")
