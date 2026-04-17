"""
劳动合同到期预警服务 — D9 Must-Fix P0

合规痛点：劳动合同到期未续签继续用工违反《劳动合同法》，面临 2N 赔偿风险。
职责：
  1. 每日定时扫描 employee_contracts 表
  2. 分级预警：60 / 30 / 15 天
  3. 聚合后推送店长 / HR 企微

复用既有 EmployeeContract / ContractType / ContractStatus 模型。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


def _classify_tier(days_left: int) -> str:
    """按剩余天数归类"""
    if days_left < 0:
        return "expired"
    if days_left <= 15:
        return "urgent_15d"
    if days_left <= 30:
        return "warning_30d"
    if days_left <= 60:
        return "notice_60d"
    return "safe"


class LaborContractAlertService:
    """劳动合同到期扫描服务"""

    @staticmethod
    async def scan_expiring_contracts(
        session: AsyncSession,
        days_ahead: int = 60,
        store_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        扫描 days_ahead 天内到期（含已过期）的劳动合同。

        Args:
            session: 异步数据库 session
            days_ahead: 预警窗口天数（默认 60 天）
            store_id: 若指定则只扫描该门店

        Returns:
            {
              "scan_date": "...",
              "total": 8,
              "expired": [...],
              "urgent_15d": [...],
              "warning_30d": [...],
              "notice_60d": [...],
            }
        """
        from src.models.employee_contract import ContractStatus, EmployeeContract

        today = date.today()
        cutoff = today + timedelta(days=days_ahead)

        conds = [
            EmployeeContract.end_date.isnot(None),
            EmployeeContract.end_date <= cutoff,
            EmployeeContract.status.in_(
                [ContractStatus.ACTIVE, ContractStatus.EXPIRING, ContractStatus.DRAFT]
            ),
        ]
        if store_id:
            conds.append(EmployeeContract.store_id == store_id)

        result = await session.execute(
            select(EmployeeContract).where(and_(*conds)).order_by(EmployeeContract.end_date.asc())
        )
        contracts = result.scalars().all()

        buckets: Dict[str, List[Dict[str, Any]]] = {
            "expired": [],
            "urgent_15d": [],
            "warning_30d": [],
            "notice_60d": [],
        }

        for ct in contracts:
            days_left = (ct.end_date - today).days
            tier = _classify_tier(days_left)
            if tier == "safe":
                continue

            item = {
                "contract_id": str(ct.id),
                "store_id": ct.store_id,
                "employee_id": ct.employee_id,
                "contract_type": ct.contract_type.value if hasattr(ct.contract_type, "value") else str(ct.contract_type),
                "start_date": ct.start_date.isoformat() if ct.start_date else None,
                "end_date": ct.end_date.isoformat(),
                "days_left": days_left,
                "tier": tier,
                "status": ct.status.value if hasattr(ct.status, "value") else str(ct.status),
            }
            buckets[tier].append(item)

            # 同步更新 status=EXPIRING（30 天内）/ EXPIRED（已过期）
            if tier == "expired" and ct.status != ContractStatus.EXPIRED:
                ct.status = ContractStatus.EXPIRED
            elif tier in ("urgent_15d", "warning_30d") and ct.status == ContractStatus.ACTIVE:
                ct.status = ContractStatus.EXPIRING

        await session.flush()

        total = sum(len(v) for v in buckets.values())
        logger.info(
            "labor_contract_scan.done",
            store_id=store_id,
            total=total,
            expired=len(buckets["expired"]),
            urgent=len(buckets["urgent_15d"]),
        )

        return {
            "scan_date": today.isoformat(),
            "days_ahead": days_ahead,
            "store_id": store_id,
            "total": total,
            **buckets,
        }

    @staticmethod
    def build_wechat_summary(scan_result: Dict[str, Any]) -> str:
        """拼装店长/HR 企微推送文本"""
        lines = [
            f"📋 劳动合同到期预警（{scan_result['scan_date']}）",
            f"扫描窗口：{scan_result['days_ahead']} 天内",
            f"总计待处理：{scan_result['total']} 份合同",
        ]
        if scan_result.get("expired"):
            lines.append(f"🔴 已过期 {len(scan_result['expired'])} 份 — 立即停止用工或签订续签协议")
        if scan_result.get("urgent_15d"):
            lines.append(f"🟠 15 天内到期 {len(scan_result['urgent_15d'])} 份 — 本周必须完成续签谈判")
        if scan_result.get("warning_30d"):
            lines.append(f"🟡 30 天内到期 {len(scan_result['warning_30d'])} 份")
        if scan_result.get("notice_60d"):
            lines.append(f"⚪ 60 天内到期 {len(scan_result['notice_60d'])} 份")
        lines.append("👉 查看详情：/hr/contracts/expiring")
        return "\n".join(lines)
