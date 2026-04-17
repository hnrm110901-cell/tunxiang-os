"""
D8 采购单审批流模型 — Should-Fix P1

设计要点：
  - 多级审批（按金额分档）：店长/区域经理/老板
  - 每一步操作（提交/审批/驳回）都写入日志，形成完整审批链
  - 金额以「分」存储，`_yuan` 仅用于展示
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from .base import Base


class ApprovalAction(str, enum.Enum):
    """审批动作枚举"""

    SUBMIT = "submit"      # 提交
    APPROVE = "approve"    # 批准
    REJECT = "reject"      # 驳回


class ApprovalLevel(str, enum.Enum):
    """审批级别枚举（按金额分档）"""

    STORE_MANAGER = "store_manager"     # 店长（<1 万）
    REGIONAL_MANAGER = "regional_manager"  # 区域经理（1-5 万）
    BOSS = "boss"                       # 老板（>5 万）


class PurchaseApprovalLog(Base):
    """采购单审批日志

    每次 submit/approve/reject 写入一条记录，串联形成完整审批链。
    """

    __tablename__ = "purchase_approval_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    po_id = Column(String, ForeignKey("purchase_orders.id"), nullable=False, index=True)

    level = Column(String(30), nullable=False)    # ApprovalLevel 值
    action = Column(String(20), nullable=False)   # ApprovalAction 值
    approver_id = Column(String(50), nullable=False, index=True)

    # 金额快照（分），便于审计
    amount_snapshot_fen = Column(Integer, nullable=True)

    reason = Column(Text, nullable=True)           # 驳回或说明
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    @property
    def amount_snapshot_yuan(self) -> float:
        """审批时金额（元）"""
        return round((self.amount_snapshot_fen or 0) / 100, 2)
