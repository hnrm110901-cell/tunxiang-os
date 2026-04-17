"""
健康证到期扫描服务 — D11 Must-Fix P0

合规痛点：健康证过期员工若继续上岗属食品安全法违法行为。
职责：
  1. 每日定时扫描 health_certificates 表
  2. 分级预警：30 / 15 / 7 / 1 天
  3. 到期当日立即将员工 is_active 置为 False（自动停岗）
  4. 聚合结果返回给 Celery 任务推送店长企微

遵循项目宪法：
  - 金额存分（本服务无金额）
  - SQL 全部参数化，使用 SQLAlchemy async
  - UUID 主键
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# 分级预警阈值（天）— 从大到小排列，便于后续判定
WARN_TIERS: List[int] = [30, 15, 7, 1]


def _classify_tier(days_left: int) -> str:
    """根据剩余天数归类预警等级"""
    if days_left < 0:
        return "expired"
    if days_left <= 1:
        return "critical_1d"
    if days_left <= 7:
        return "urgent_7d"
    if days_left <= 15:
        return "warning_15d"
    if days_left <= 30:
        return "notice_30d"
    return "safe"


class HealthCertScanService:
    """健康证到期扫描服务"""

    @staticmethod
    async def scan_expiring_certs(
        session: AsyncSession,
        days_ahead: int = 30,
        store_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        扫描 days_ahead 天内到期（含已过期）的健康证记录。

        Args:
            session: 异步数据库 session
            days_ahead: 预警窗口天数（默认 30 天）
            store_id: 若指定则只扫描该门店，否则全量扫描

        Returns:
            {
              "scan_date": "2026-04-17",
              "total": 12,
              "expired": [...],
              "critical_1d": [...],
              "urgent_7d": [...],
              "warning_15d": [...],
              "notice_30d": [...],
              "auto_suspended_employees": ["E001", ...],
            }
        """
        from src.models.health_certificate import HealthCertificate

        today = date.today()
        cutoff = today + timedelta(days=days_ahead)

        conds = [HealthCertificate.expiry_date <= cutoff, HealthCertificate.status != "revoked"]
        if store_id:
            conds.append(HealthCertificate.store_id == store_id)

        result = await session.execute(
            select(HealthCertificate).where(and_(*conds)).order_by(HealthCertificate.expiry_date.asc())
        )
        certs = result.scalars().all()

        buckets: Dict[str, List[Dict[str, Any]]] = {
            "expired": [],
            "critical_1d": [],
            "urgent_7d": [],
            "warning_15d": [],
            "notice_30d": [],
        }
        auto_suspended: List[str] = []

        for cert in certs:
            days_left = (cert.expiry_date - today).days
            tier = _classify_tier(days_left)
            if tier == "safe":
                continue

            item = {
                "cert_id": str(cert.id),
                "store_id": cert.store_id,
                "brand_id": cert.brand_id,
                "employee_id": cert.employee_id,
                "employee_name": cert.employee_name,
                "certificate_number": cert.certificate_number,
                "expiry_date": cert.expiry_date.isoformat(),
                "days_left": days_left,
                "tier": tier,
            }
            buckets[tier].append(item)

            # 已过期 → 自动停岗（员工 is_active=False，健康证 status=expired）
            if tier == "expired" and cert.status != "expired":
                cert.status = "expired"
                suspended_id = await HealthCertScanService._auto_suspend_employee(session, cert.employee_id)
                if suspended_id:
                    auto_suspended.append(suspended_id)

        await session.flush()

        total = sum(len(v) for v in buckets.values())
        logger.info(
            "health_cert_scan.done",
            store_id=store_id,
            total=total,
            expired=len(buckets["expired"]),
            auto_suspended=len(auto_suspended),
        )

        return {
            "scan_date": today.isoformat(),
            "days_ahead": days_ahead,
            "store_id": store_id,
            "total": total,
            **buckets,
            "auto_suspended_employees": auto_suspended,
        }

    @staticmethod
    async def _auto_suspend_employee(session: AsyncSession, employee_id: str) -> Optional[str]:
        """
        将健康证过期的员工 is_active 置为 False（自动停岗）。
        返回被停岗的 employee_id；若员工不存在或已停岗返回 None。
        """
        from src.models.employee import Employee

        result = await session.execute(
            select(Employee).where(and_(Employee.id == employee_id, Employee.is_active.is_(True)))
        )
        emp = result.scalar_one_or_none()
        if emp is None:
            return None

        emp.is_active = False
        # employment_status 兼容写入（若字段存在）
        if hasattr(emp, "employment_status"):
            emp.employment_status = "suspended_health_cert"

        logger.warning(
            "health_cert.auto_suspend",
            employee_id=employee_id,
            reason="health_certificate_expired",
        )
        return employee_id

    @staticmethod
    def build_wechat_summary(scan_result: Dict[str, Any]) -> str:
        """拼装店长企微推送文本（决策型：建议动作 + 影响 + 一键入口）"""
        lines = [
            f"⚠️ 健康证合规预警（{scan_result['scan_date']}）",
            f"扫描窗口：{scan_result['days_ahead']} 天内",
            f"总计待处理：{scan_result['total']} 人",
        ]
        if scan_result.get("expired"):
            lines.append(f"🔴 已过期 {len(scan_result['expired'])} 人 — 已自动停岗，请立即补办")
            for it in scan_result["expired"][:5]:
                lines.append(f"  · {it['employee_name']}（到期 {it['expiry_date']}）")
        if scan_result.get("critical_1d"):
            lines.append(f"🟠 明日到期 {len(scan_result['critical_1d'])} 人 — 今日内安排体检")
        if scan_result.get("urgent_7d"):
            lines.append(f"🟡 7 天内到期 {len(scan_result['urgent_7d'])} 人")
        if scan_result.get("warning_15d"):
            lines.append(f"🔵 15 天内到期 {len(scan_result['warning_15d'])} 人")
        if scan_result.get("notice_30d"):
            lines.append(f"⚪ 30 天内到期 {len(scan_result['notice_30d'])} 人")
        lines.append("👉 查看详情：/hr/health-certs/expiring")
        return "\n".join(lines)
