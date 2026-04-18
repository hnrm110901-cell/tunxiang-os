"""
多时区服务

- 所有时间存储 UTC
- 显示/业务边界判定按员工本地时区（employee.timezone）
- 租户默认时区作为 fallback
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.employee import Employee
from src.models.tenant_locale import TenantLocaleConfig

DEFAULT_TIMEZONE = "Asia/Shanghai"


class TimezoneService:
    """员工/租户级时区转换"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _get_employee_tz(self, employee_id: str) -> str:
        emp = await self.session.get(Employee, employee_id)
        tz = getattr(emp, "timezone", None) if emp else None
        return tz or DEFAULT_TIMEZONE

    async def get_tenant_timezone(self, tenant_id: str) -> str:
        stmt = select(TenantLocaleConfig).where(TenantLocaleConfig.tenant_id == tenant_id)
        cfg = (await self.session.execute(stmt)).scalar_one_or_none()
        return cfg.default_timezone if cfg else DEFAULT_TIMEZONE

    @staticmethod
    def _ensure_utc(dt: datetime) -> datetime:
        """保证 dt 带 tzinfo=UTC"""
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    async def to_employee_local_time(self, utc_dt: datetime, employee_id: str) -> datetime:
        """UTC → 员工本地"""
        tz_name = await self._get_employee_tz(employee_id)
        return self._ensure_utc(utc_dt).astimezone(ZoneInfo(tz_name))

    async def from_employee_local_time(self, local_dt: datetime, employee_id: str) -> datetime:
        """员工本地（无 tzinfo 时按其本地时区解释） → UTC"""
        tz_name = await self._get_employee_tz(employee_id)
        if local_dt.tzinfo is None:
            local_dt = local_dt.replace(tzinfo=ZoneInfo(tz_name))
        return local_dt.astimezone(timezone.utc)

    async def format_datetime_for_display(
        self,
        utc_dt: datetime,
        employee_id: str,
        format_type: str = "datetime",
    ) -> str:
        """按员工本地时区格式化显示"""
        local_dt = await self.to_employee_local_time(utc_dt, employee_id)
        if format_type == "date":
            return local_dt.strftime("%Y-%m-%d")
        if format_type == "time":
            return local_dt.strftime("%H:%M:%S")
        return local_dt.strftime("%Y-%m-%d %H:%M:%S %Z")

    async def get_employee_pay_month_boundaries(
        self, employee_id: str, year: int, month: int
    ) -> tuple[datetime, datetime]:
        """
        跨时区工资月份边界：返回 [月初 00:00:00, 次月初 00:00:00) 的 UTC 区间。
        例：员工在香港，2026-09 = HKT 9/1 00:00 ~ HKT 10/1 00:00 → 对应 UTC。
        """
        tz_name = await self._get_employee_tz(employee_id)
        tz = ZoneInfo(tz_name)
        start_local = datetime(year, month, 1, 0, 0, 0, tzinfo=tz)
        if month == 12:
            end_local = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=tz)
        else:
            end_local = datetime(year, month + 1, 1, 0, 0, 0, tzinfo=tz)
        return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)
