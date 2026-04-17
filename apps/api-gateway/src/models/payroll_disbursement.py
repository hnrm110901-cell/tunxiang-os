"""
D12 合规 — 银行代发批次模型
---------------------------------
SalaryDisbursement：一个门店一个月度对应一笔代发批次，
记录工资总额、人数、生成的银行文件路径以及状态。

银行文件落盘路径：/tmp/salary_disbursements/{batch_id}.{ext}
"""

import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from .base import Base, TimestampMixin


class DisbursementBank(str, enum.Enum):
    """代发银行类型"""

    ICBC = "icbc"  # 工商银行 TXT
    CCB = "ccb"  # 建设银行 TXT
    GENERIC = "generic"  # 通用 CSV


class DisbursementStatus(str, enum.Enum):
    """代发批次状态"""

    GENERATED = "generated"  # 已生成文件
    UPLOADED = "uploaded"  # 已上传至银行
    PAID = "paid"  # 银行已代发成功
    FAILED = "failed"  # 代发失败
    CANCELLED = "cancelled"  # 已撤销


class SalaryDisbursement(Base, TimestampMixin):
    """
    月度银行代发批次表。

    一个门店一个 pay_month 可以生成多个批次（例如分银行/补发），
    因此不设唯一键，而以 (store_id, pay_month, bank) 做组合索引。
    """

    __tablename__ = "salary_disbursements"
    __table_args__ = (
        Index("ix_salary_disbursement_store_month", "store_id", "pay_month"),
        Index("ix_salary_disbursement_bank", "bank"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id = Column(String(64), nullable=False, unique=True, index=True)  # 业务批次号
    store_id = Column(String(50), nullable=False, index=True)
    pay_month = Column(String(7), nullable=False, index=True)  # YYYY-MM

    bank = Column(
        SAEnum(DisbursementBank, name="disbursement_bank"),
        nullable=False,
    )
    file_path = Column(String(500), nullable=True)  # 落盘路径
    file_format = Column(String(10), nullable=False, default="txt")  # txt/csv

    # 批次金额与人数
    total_amount_fen = Column(Integer, nullable=False, default=0)
    employee_count = Column(Integer, nullable=False, default=0)

    status = Column(
        SAEnum(DisbursementStatus, name="disbursement_status"),
        nullable=False,
        default=DisbursementStatus.GENERATED,
    )

    generated_at = Column(DateTime, nullable=True)
    uploaded_at = Column(DateTime, nullable=True)
    paid_at = Column(DateTime, nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)
    remark = Column(Text, nullable=True)

    def __repr__(self):
        return (
            f"<SalaryDisbursement(batch='{self.batch_id}', "
            f"store='{self.store_id}', month='{self.pay_month}', "
            f"bank='{self.bank}', total={self.total_amount_fen/100:.2f}yuan, "
            f"count={self.employee_count})>"
        )

    @property
    def total_amount_yuan(self) -> float:
        return round(self.total_amount_fen / 100, 2)
