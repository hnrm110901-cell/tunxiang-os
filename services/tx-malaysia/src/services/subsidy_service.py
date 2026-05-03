"""马来西亚政府补贴计费服务 — MDEC / SME Corp 补贴套餐

支持两种补贴方案：
  1. MDEC Digitalisation Grant — 政府补贴 50%，最高补贴 RM3,500
  2. SME Corp Automasuk — 政府补贴 40%，最高补贴 RM2,000

所有金额单位：分（fen），与系统 Amount Convention 一致。
RM35.00 = 3500 fen
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ── 补贴方案定义 ──────────────────────────────────────────────

SUBSIDY_PROGRAMS: dict[str, dict[str, Any]] = {
    "mdec_digital_grant": {
        "id": "mdec_digital_grant",
        "name": "MDEC Digitalisation Grant",
        "subsidy_rate": 0.5,
        "max_subsidy_fen": 3500_00,  # 最高补贴 RM3,500
        "monthly_fee_fen": 3500,  # RM35/月基础费
        "description": "MDEC 数字化补助 — 补贴 50% 月度 SaaS 费用，最高 RM3,500",
        "eligibility_criteria": ["ssm_verified", "bumiputera", "sme"],
    },
    "smecorp_automasuk": {
        "id": "smecorp_automasuk",
        "name": "SME Corp Automasuk",
        "subsidy_rate": 0.4,
        "max_subsidy_fen": 2000_00,  # 最高补贴 RM2,000
        "monthly_fee_fen": 3500,  # RM35/月基础费
        "description": "SME Corp 自动化补助 — 补贴 40% 月度 SaaS 费用，最高 RM2,000",
        "eligibility_criteria": ["ssm_verified", "registered_6months", "smc"],
    },
}

# ── 资格校验结果枚举 ──────────────────────────────────────────

ELIGIBILITY_STATUSES = ("eligible", "ineligible", "already_applied", "ssm_not_verified")


class SubsidyService:
    """马来西亚政府补贴计费服务

    用法:
        subsidy = SubsidyService(db, tenant_id)
        status = await subsidy.check_eligibility(tenant_id, "mdec_digital_grant")
        result = await subsidy.apply_subsidy(tenant_id, "mdec_digital_grant")
        bill = await subsidy.calculate_bill(tenant_id, period_start, period_end)
    """

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self._tid = uuid.UUID(tenant_id)

    async def _set_tenant(self) -> None:
        """设置 RLS 租户上下文"""
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self.tenant_id},
        )

    # ════════════════════════════════════════════════════════════
    # 补贴方案
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def list_programs() -> dict[str, Any]:
        """返回所有可用补贴方案"""
        return {
            "programs": [
                {
                    "id": prog["id"],
                    "name": prog["name"],
                    "subsidy_rate": prog["subsidy_rate"],
                    "max_subsidy_fen": prog["max_subsidy_fen"],
                    "max_subsidy_rm": round(prog["max_subsidy_fen"] / 100, 2),
                    "monthly_fee_fen": prog["monthly_fee_fen"],
                    "monthly_fee_rm": round(prog["monthly_fee_fen"] / 100, 2),
                    "description": prog["description"],
                    "eligibility_criteria": prog["eligibility_criteria"],
                }
                for prog in SUBSIDY_PROGRAMS.values()
            ],
        }

    # ════════════════════════════════════════════════════════════
    # 资格校验
    # ════════════════════════════════════════════════════════════

    async def check_eligibility(self, tenant_id: str, program: str) -> dict[str, Any]:
        """校验商户在指定补贴方案中的资格

        检查项：
          - SSM 验证状态（需已验证）
          - 企业规模是否符合 SME 标准
          - 是否已有同类型补贴
          - 方案特有条件（bumiputera / registered_6months / smc）

        Returns:
            {
                eligible: bool,
                status: "eligible"|"ineligible"|"already_applied"|"ssm_not_verified",
                program: str,
                reasons: [str, ...],
                subsidy_rate: float,
                max_subsidy_fen: int,
                monthly_fee_fen: int,
            }
        """
        log = logger.bind(tenant_id=tenant_id, program=program)
        log.info("subsidy.check_eligibility")

        if program not in SUBSIDY_PROGRAMS:
            raise ValueError(f"未知的补贴方案: {program}，可选: {', '.join(SUBSIDY_PROGRAMS)}")

        prog = SUBSIDY_PROGRAMS[program]
        reasons: list[str] = []

        # 1. 检查 SSM 验证状态
        # 暂从 tenants 表的 ssm_verified 字段读取；生产环境调用 SSMService
        ssm_verified = await self._check_ssm_verified(tenant_id)
        if not ssm_verified:
            reasons.append("SSM 企业验证未完成")

        # 2. 检查企业规模（SME criteria）
        sme_status = await self._check_sme_status(tenant_id)
        if not sme_status.get("is_sme", False):
            reasons.append("企业规模不符合 SME 标准")

        # 3. 检查是否已有补贴
        existing = await self._check_existing_subsidy(tenant_id, program)
        if existing:
            log.info("subsidy.already_applied", existing_status=existing["status"])
            return {
                "eligible": False,
                "status": "already_applied",
                "program": program,
                "reasons": ["该商户已申请此补贴方案"],
                "subsidy_rate": prog["subsidy_rate"],
                "max_subsidy_fen": prog["max_subsidy_fen"],
                "monthly_fee_fen": prog["monthly_fee_fen"],
            }

        # 4. 方案特有条件
        criteria = prog.get("eligibility_criteria", [])
        for criterion in criteria:
            if criterion == "bumiputera":
                is_bumi = await self._check_bumiputera(tenant_id)
                if not is_bumi:
                    reasons.append("非 Bumiputera 企业（此方案仅限 Bumiputera）")
            elif criterion == "registered_6months":
                is_reg_6m = await self._check_registered_6months(tenant_id)
                if not is_reg_6m:
                    reasons.append("注册未满 6 个月")
            elif criterion == "smc":
                is_smc = await self._check_smc(tenant_id)
                if not is_smc:
                    reasons.append("非 SMC（中小型公司）类别")

        eligible = len(reasons) == 0 and ssm_verified
        status = "eligible" if eligible else "ineligible"

        log.info(
            "subsidy.eligibility_result",
            eligible=eligible,
            status=status,
            reasons=reasons,
        )

        return {
            "eligible": eligible,
            "status": status,
            "program": program,
            "reasons": reasons,
            "subsidy_rate": prog["subsidy_rate"],
            "max_subsidy_fen": prog["max_subsidy_fen"],
            "monthly_fee_fen": prog["monthly_fee_fen"],
        }

    # ════════════════════════════════════════════════════════════
    # 补贴申请
    # ════════════════════════════════════════════════════════════

    async def apply_subsidy(self, tenant_id: str, program: str) -> dict[str, Any]:
        """申请补贴套餐

        Args:
            tenant_id: 商户 ID
            program: 补贴方案 ID

        Returns:
            { applied: bool, subsidy_id, program, status, subsidy_rate,
              monthly_fee_fen, subsidy_amount_fen, applied_at, expires_at }
        """
        log = logger.bind(tenant_id=tenant_id, program=program)
        log.info("subsidy.apply")

        if program not in SUBSIDY_PROGRAMS:
            raise ValueError(f"未知的补贴方案: {program}，可选: {', '.join(SUBSIDY_PROGRAMS)}")

        # 先校验资格
        eligibility = await self.check_eligibility(tenant_id, program)
        if not eligibility["eligible"]:
            raise ValueError(
                f"商户 {tenant_id} 不符合 {program} 补贴资格: "
                + "; ".join(eligibility["reasons"])
            )

        prog = SUBSIDY_PROGRAMS[program]
        subsidy_amount = min(
            int(prog["monthly_fee_fen"] * prog["subsidy_rate"]),
            prog["max_subsidy_fen"],
        )

        await self._set_tenant()
        subsidy_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        expires_at = now.replace(year=now.year + 1)  # 默认有效期 1 年

        await self.db.execute(
            text("""
                INSERT INTO tenant_subsidies
                    (id, tenant_id, program, status, subsidy_rate,
                     monthly_fee_fen, subsidy_amount_fen,
                     applied_at, expires_at, country_code)
                VALUES
                    (:id, :tid, :program, 'active', :rate,
                     :fee, :amount,
                     :now, :expires, 'MY')
            """),
            {
                "id": subsidy_id,
                "tid": self._tid,
                "program": program,
                "rate": prog["subsidy_rate"],
                "fee": prog["monthly_fee_fen"],
                "amount": subsidy_amount,
                "now": now,
                "expires": expires_at,
            },
        )
        await self.db.flush()

        log.info(
            "subsidy.applied",
            subsidy_id=str(subsidy_id),
            subsidy_amount_fen=subsidy_amount,
            monthly_fee_fen=prog["monthly_fee_fen"],
            expires_at=expires_at.isoformat(),
        )

        return {
            "applied": True,
            "subsidy_id": str(subsidy_id),
            "program": program,
            "status": "active",
            "subsidy_rate": prog["subsidy_rate"],
            "monthly_fee_fen": prog["monthly_fee_fen"],
            "subsidy_amount_fen": subsidy_amount,
            "payable_fen": prog["monthly_fee_fen"] - subsidy_amount,
            "applied_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }

    # ════════════════════════════════════════════════════════════
    # 账单计算
    # ════════════════════════════════════════════════════════════

    async def calculate_bill(
        self,
        tenant_id: str,
        period_start: date,
        period_end: date,
    ) -> dict[str, Any]:
        """计算补贴后账单

        公式: payable_fen = base_fee_fen - subsidy_amount_fen

        Args:
            tenant_id: 商户 ID
            period_start: 账单周期起始日
            period_end: 账单周期结束日

        Returns:
            { period_start, period_end, base_fee_fen, subsidy_fen,
              payable_fen, active_subsidies: [...] }
        """
        log = logger.bind(
            tenant_id=tenant_id,
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
        )
        log.info("subsidy.calculate_bill")

        await self._set_tenant()

        # 查询该商户所有活跃补贴
        result = await self.db.execute(
            text("""
                SELECT id, program, subsidy_rate, monthly_fee_fen,
                       subsidy_amount_fen, status
                FROM tenant_subsidies
                WHERE tenant_id = :tid
                  AND status = 'active'
                  AND expires_at >= :now
                ORDER BY applied_at DESC
            """),
            {"tid": self._tid, "now": datetime.now(timezone.utc)},
        )
        rows = result.fetchall()

        if not rows:
            log.info("subsidy.no_active_subsidies")
            return {
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "base_fee_fen": 0,
                "subsidy_fen": 0,
                "payable_fen": 0,
                "active_subsidies": [],
            }

        active_subsidies = []
        total_base_fee_fen = 0
        total_subsidy_fen = 0

        for row in rows:
            total_base_fee_fen += row.monthly_fee_fen
            total_subsidy_fen += row.subsidy_amount_fen
            active_subsidies.append({
                "subsidy_id": str(row.id),
                "program": row.program,
                "subsidy_rate": float(row.subsidy_rate),
                "monthly_fee_fen": row.monthly_fee_fen,
                "subsidy_amount_fen": row.subsidy_amount_fen,
            })

        payable_fen = max(0, total_base_fee_fen - total_subsidy_fen)

        log.info(
            "subsidy.bill_calculated",
            active_count=len(active_subsidies),
            base_fee_fen=total_base_fee_fen,
            subsidy_fen=total_subsidy_fen,
            payable_fen=payable_fen,
        )

        return {
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "base_fee_fen": total_base_fee_fen,
            "subsidy_fen": total_subsidy_fen,
            "payable_fen": payable_fen,
            "active_subsidies": active_subsidies,
        }

    # ════════════════════════════════════════════════════════════
    # 补贴账单生成
    # ════════════════════════════════════════════════════════════

    async def generate_invoice(
        self,
        tenant_id: str,
        period: str,
    ) -> dict[str, Any]:
        """生成补贴账单记录

        Args:
            tenant_id: 商户 ID
            period: 账单周期标识（如 "2026-05"）

        Returns:
            { bill_id, tenant_id, period, base_fee_fen, subsidy_fen,
              payable_fen, status }
        """
        log = logger.bind(tenant_id=tenant_id, period=period)
        log.info("subsidy.generate_invoice")

        # 解析周期
        try:
            year_str, month_str = period.split("-")
            period_start = date(int(year_str), int(month_str), 1)
            if int(month_str) == 12:
                period_end = date(int(year_str) + 1, 1, 1)
            else:
                period_end = date(int(year_str), int(month_str) + 1, 1)
        except (ValueError, IndexError) as exc:
            raise ValueError(f"周期格式无效: {period}，期望格式 YYYY-MM") from exc

        bill_data = await self.calculate_bill(tenant_id, period_start, period_end)

        await self._set_tenant()
        bill_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # 只在有费用时生成账单
        if bill_data["base_fee_fen"] == 0 and bill_data["payable_fen"] == 0:
            log.info("subsidy.no_charge_invoice")
            return {
                "bill_id": None,
                "tenant_id": tenant_id,
                "period": period,
                "base_fee_fen": 0,
                "subsidy_fen": 0,
                "payable_fen": 0,
                "status": "no_charge",
                "note": "该周期无活跃补贴方案，无需收费",
            }

        await self.db.execute(
            text("""
                INSERT INTO subsidy_bills
                    (id, tenant_id, period_start, period_end,
                     base_fee_fen, subsidy_fen, payable_fen, status,
                     country_code)
                VALUES
                    (:id, :tid, :pstart, :pend,
                     :bfee, :sub, :pay, 'pending',
                     'MY')
            """),
            {
                "id": bill_id,
                "tid": self._tid,
                "pstart": bill_data["period_start"],
                "pend": bill_data["period_end"],
                "bfee": bill_data["base_fee_fen"],
                "sub": bill_data["subsidy_fen"],
                "pay": bill_data["payable_fen"],
            },
        )
        await self.db.flush()

        log.info(
            "subsidy.invoice_generated",
            bill_id=str(bill_id),
            payable_fen=bill_data["payable_fen"],
        )

        return {
            "bill_id": str(bill_id),
            "tenant_id": tenant_id,
            "period": period,
            "base_fee_fen": bill_data["base_fee_fen"],
            "subsidy_fen": bill_data["subsidy_fen"],
            "payable_fen": bill_data["payable_fen"],
            "status": "pending",
        }

    # ════════════════════════════════════════════════════════════
    # 补贴状态查询
    # ════════════════════════════════════════════════════════════

    async def get_subsidy_status(self, tenant_id: str) -> dict[str, Any]:
        """查询商户当前补贴状态

        Returns:
            {
                has_active_subsidy: bool,
                active_subsidies: [{...}],
                current_bill: {...} | None,
                total_saved_fen: int,
            }
        """
        log = logger.bind(tenant_id=tenant_id)
        log.info("subsidy.get_status")

        await self._set_tenant()
        now = datetime.now(timezone.utc)

        # 查询活跃补贴
        result = await self.db.execute(
            text("""
                SELECT id, program, subsidy_rate, monthly_fee_fen,
                       subsidy_amount_fen, applied_at, expires_at, status
                FROM tenant_subsidies
                WHERE tenant_id = :tid
                  AND status = 'active'
                  AND expires_at >= :now
                ORDER BY applied_at DESC
            """),
            {"tid": self._tid, "now": now},
        )
        active_rows = result.fetchall()

        # 查询累计节省
        total_saved = await self.db.execute(
            text("""
                SELECT COALESCE(SUM(subsidy_fen), 0) AS total_saved
                FROM subsidy_bills
                WHERE tenant_id = :tid AND status = 'paid'
            """),
            {"tid": self._tid},
        )
        total_saved_fen = total_saved.fetchone().total_saved

        # 当前周期账单
        current_bill = None
        bill_result = await self.db.execute(
            text("""
                SELECT id, period_start, period_end, base_fee_fen,
                       subsidy_fen, payable_fen, status
                FROM subsidy_bills
                WHERE tenant_id = :tid AND status = 'pending'
                ORDER BY period_start DESC
                LIMIT 1
            """),
            {"tid": self._tid},
        )
        bill_row = bill_result.fetchone()
        if bill_row:
            current_bill = {
                "bill_id": str(bill_row.id),
                "period_start": bill_row.period_start.isoformat() if bill_row.period_start else None,
                "period_end": bill_row.period_end.isoformat() if bill_row.period_end else None,
                "base_fee_fen": bill_row.base_fee_fen,
                "subsidy_fen": bill_row.subsidy_fen,
                "payable_fen": bill_row.payable_fen,
                "status": bill_row.status,
            }

        active_subsidies = [
            {
                "subsidy_id": str(r.id),
                "program": r.program,
                "subsidy_rate": float(r.subsidy_rate),
                "monthly_fee_fen": r.monthly_fee_fen,
                "subsidy_amount_fen": r.subsidy_amount_fen,
                "applied_at": r.applied_at.isoformat() if r.applied_at else None,
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                "status": r.status,
            }
            for r in active_rows
        ]

        log.info(
            "subsidy.status_result",
            has_active=len(active_subsidies) > 0,
            total_saved_fen=total_saved_fen,
        )

        return {
            "has_active_subsidy": len(active_subsidies) > 0,
            "active_subsidies": active_subsidies,
            "current_bill": current_bill,
            "total_saved_fen": total_saved_fen,
        }

    # ════════════════════════════════════════════════════════════
    # 内部资格校验方法
    # ════════════════════════════════════════════════════════════

    async def _check_ssm_verified(self, tenant_id: str) -> bool:
        """检查商户是否已完成 SSM 验证"""
        result = await self.db.execute(
            text("""
                SELECT ssm_verified FROM tenants
                WHERE id = :tid
            """),
            {"tid": self._tid},
        )
        row = result.fetchone()
        return bool(row and row.ssm_verified)

    async def _check_sme_status(self, tenant_id: str) -> dict[str, Any]:
        """检查商户是否满足 SME 标准

        SME 定义（马来西亚 SME Corp）：
          - 制造业：营收 ≤ RM50 百万 或 员工 ≤ 200 人
          - 服务业：营收 ≤ RM20 百万 或 员工 ≤ 75 人
        """
        result = await self.db.execute(
            text("""
                SELECT
                    annual_revenue_fen,
                    employee_count,
                    industry_sector
                FROM tenants
                WHERE id = :tid
            """),
            {"tid": self._tid},
        )
        row = result.fetchone()
        if row is None:
            return {"is_sme": False, "reason": "Tenant not found"}

        revenue_rm = (row.annual_revenue_fen or 0) / 100
        employees = row.employee_count or 0
        sector = (row.industry_sector or "").lower()

        if sector in ("manufacturing", "production"):
            is_sme = revenue_rm <= 50_000_000 or employees <= 200
        else:
            is_sme = revenue_rm <= 20_000_000 or employees <= 75

        return {
            "is_sme": is_sme,
            "revenue_rm": revenue_rm,
            "employee_count": employees,
            "sector": sector,
        }

    async def _check_existing_subsidy(self, tenant_id: str, program: str) -> Optional[dict[str, Any]]:
        """检查商户是否已有该方案的补贴"""
        result = await self.db.execute(
            text("""
                SELECT id, status FROM tenant_subsidies
                WHERE tenant_id = :tid AND program = :prog
                  AND status IN ('active', 'pending')
                LIMIT 1
            """),
            {"tid": self._tid, "prog": program},
        )
        row = result.fetchone()
        if row:
            return {"subsidy_id": str(row.id), "status": row.status}
        return None

    async def _check_bumiputera(self, tenant_id: str) -> bool:
        """检查是否 Bumiputera 企业"""
        result = await self.db.execute(
            text("""
                SELECT is_bumiputera FROM tenants
                WHERE id = :tid
            """),
            {"tid": self._tid},
        )
        row = result.fetchone()
        return bool(row and row.is_bumiputera)

    async def _check_registered_6months(self, tenant_id: str) -> bool:
        """检查企业是否已注册满 6 个月"""
        result = await self.db.execute(
            text("""
                SELECT incorporation_date FROM tenants
                WHERE id = :tid
            """),
            {"tid": self._tid},
        )
        row = result.fetchone()
        if row is None or row.incorporation_date is None:
            return False

        if isinstance(row.incorporation_date, date):
            incorp = row.incorporation_date
        else:
            incorp = datetime.fromisoformat(str(row.incorporation_date)).date()

        months_ago = (date.today().year - incorp.year) * 12 + (date.today().month - incorp.month)
        return months_ago >= 6

    async def _check_smc(self, tenant_id: str) -> bool:
        """检查是否 SMC（Small Medium Company）类别

        SMC 定义：营收 < RM300,000 或 员工 < 5 人
        """
        result = await self.db.execute(
            text("""
                SELECT annual_revenue_fen, employee_count
                FROM tenants
                WHERE id = :tid
            """),
            {"tid": self._tid},
        )
        row = result.fetchone()
        if row is None:
            return False
        revenue_rm = (row.annual_revenue_fen or 0) / 100
        employees = row.employee_count or 0
        return revenue_rm < 300_000 or employees < 5
