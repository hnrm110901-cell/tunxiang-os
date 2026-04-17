"""
D10 多打卡方式模型 — Should-Fix P1

支持：GPS/WiFi/Face/QRCode/Manual 五种打卡方式。
方法、坐标、载荷全部冗余保存，便于合规审计。
"""

import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Numeric, String
from sqlalchemy.dialects.postgresql import JSON, UUID

from .base import Base, TimestampMixin


class PunchMethod(str, enum.Enum):
    """打卡方式枚举"""

    GPS = "gps"
    WIFI = "wifi"
    FACE = "face"
    QRCODE = "qrcode"
    MANUAL = "manual"


class PunchDirection(str, enum.Enum):
    """上/下班"""

    IN = "in"
    OUT = "out"


class AttendancePunch(Base, TimestampMixin):
    """考勤打卡明细记录

    与 AttendanceLog（一日一条汇总）互补：此表记录每次原始打卡。
    """

    __tablename__ = "attendance_punches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id = Column(String(50), nullable=False, index=True)
    store_id = Column(String(50), nullable=False, index=True)

    punch_at = Column(DateTime(timezone=True), nullable=False, index=True)
    direction = Column(String(10), nullable=False, default=PunchDirection.IN.value)
    method = Column(String(20), nullable=False)   # PunchMethod 值

    payload_json = Column(JSON, nullable=True)    # 方法专属载荷（wifi ssid、qrcode、face sdk resp 等）
    location_lat = Column(Numeric(10, 7), nullable=True)
    location_lng = Column(Numeric(10, 7), nullable=True)

    verified = Column(Boolean, default=False, nullable=False)
    verify_remark = Column(String(200), nullable=True)

    shift_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    needs_approval = Column(Boolean, default=False)  # 手工代打卡待审批

    def __repr__(self):
        return f"<AttendancePunch(emp={self.employee_id}, method={self.method}, at={self.punch_at})>"
