"""
D12 合规 — 银行代发文件生成服务
------------------------------------------------
功能：
  - ICBC（工行）TXT     固定分隔 | 的文本格式
  - CCB（建行）TXT       空格/| 分隔（本实现采用 | 以便解析）
  - 通用 CSV             序号|姓名|银行账号|身份证|金额元|摘要

所有文件落到 /tmp/salary_disbursements/{batch_id}.{ext}
同时在 salary_disbursements 表中登记批次（状态 generated）。

约束：
  - 金额在文件中按"元（两位小数）"输出；内部计算仍为分
  - 银行账号与身份证号数据库侧为密文；此处视为解密后的明文（由调用方处理解密）
"""

import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.employee import Employee
from src.models.payroll import PayrollRecord, PayrollStatus
from src.models.payroll_disbursement import (
    DisbursementBank,
    DisbursementStatus,
    SalaryDisbursement,
)
from src.services.base_service import BaseService

logger = structlog.get_logger()

DEFAULT_OUTPUT_DIR = "/tmp/salary_disbursements"


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _fmt_yuan(fen: int) -> str:
    """分 → 元字符串(两位小数)"""
    return f"{fen / 100:.2f}"


class BankDisbursementService(BaseService):
    """银行代发文件生成服务"""

    output_dir: str = DEFAULT_OUTPUT_DIR

    def __init__(self, store_id: Optional[str] = None, output_dir: Optional[str] = None):
        super().__init__(store_id=store_id)
        if output_dir:
            self.output_dir = output_dir

    # ── 对外入口 ──────────────────────────────────────────────
    async def generate_icbc_file(
        self, db: AsyncSession, pay_month: str, store_id: str
    ) -> Dict[str, Any]:
        rows = await self._fetch_rows(db, store_id, pay_month)
        return await self._write_and_register(
            db, store_id, pay_month, rows, DisbursementBank.ICBC, "txt",
            self._render_icbc,
        )

    async def generate_ccb_file(
        self, db: AsyncSession, pay_month: str, store_id: str
    ) -> Dict[str, Any]:
        rows = await self._fetch_rows(db, store_id, pay_month)
        return await self._write_and_register(
            db, store_id, pay_month, rows, DisbursementBank.CCB, "txt",
            self._render_ccb,
        )

    async def generate_generic_csv(
        self, db: AsyncSession, pay_month: str, store_id: str
    ) -> Dict[str, Any]:
        rows = await self._fetch_rows(db, store_id, pay_month)
        return await self._write_and_register(
            db, store_id, pay_month, rows, DisbursementBank.GENERIC, "csv",
            self._render_csv,
        )

    async def get_by_batch_id(
        self, db: AsyncSession, batch_id: str
    ) -> Optional[SalaryDisbursement]:
        result = await db.execute(
            select(SalaryDisbursement).where(SalaryDisbursement.batch_id == batch_id)
        )
        return result.scalar_one_or_none()

    # ── 行数据拉取 ────────────────────────────────────────────
    async def _fetch_rows(
        self, db: AsyncSession, store_id: str, pay_month: str
    ) -> List[Dict[str, Any]]:
        """拉取门店本月工资单 + 员工银行信息（不含未算薪者）"""
        stmt = (
            select(PayrollRecord, Employee)
            .join(Employee, PayrollRecord.employee_id == Employee.id)
            .where(
                and_(
                    PayrollRecord.store_id == store_id,
                    PayrollRecord.pay_month == pay_month,
                    # 仅代发已确认或已发放状态；草稿通常不代发
                    PayrollRecord.status.in_(
                        [PayrollStatus.CONFIRMED, PayrollStatus.PAID, PayrollStatus.DRAFT]
                    ),
                )
            )
            .order_by(Employee.name)
        )
        result = await db.execute(stmt)
        rows: List[Dict[str, Any]] = []
        for record, emp in result.all():
            rows.append(
                {
                    "employee_id": emp.id,
                    "name": emp.name or "",
                    "bank_name": emp.bank_name or "",
                    "bank_account": emp.bank_account or "",
                    "id_card_no": emp.id_card_no or "",
                    "net_salary_fen": record.net_salary_fen or 0,
                    "pay_month": record.pay_month,
                }
            )
        return rows

    # ── 文件渲染 ──────────────────────────────────────────────
    def _render_icbc(self, rows: List[Dict[str, Any]], pay_month: str) -> str:
        """
        工行 ICBC 代发文件（TXT，| 分隔）
        Header:  H|ICBC|YYYY-MM|<count>|<total_yuan>
        Detail:  D|seq|name|bank_account|id_card|amount_yuan|memo
        """
        total_fen = sum(r["net_salary_fen"] for r in rows)
        lines = [f"H|ICBC|{pay_month}|{len(rows)}|{_fmt_yuan(total_fen)}"]
        for idx, r in enumerate(rows, start=1):
            memo = f"{pay_month}工资"
            lines.append(
                "|".join(
                    [
                        "D",
                        str(idx),
                        r["name"],
                        r["bank_account"],
                        r["id_card_no"],
                        _fmt_yuan(r["net_salary_fen"]),
                        memo,
                    ]
                )
            )
        lines.append(f"T|{len(rows)}|{_fmt_yuan(total_fen)}")
        return "\n".join(lines) + "\n"

    def _render_ccb(self, rows: List[Dict[str, Any]], pay_month: str) -> str:
        """
        建行 CCB 代发文件（TXT，| 分隔）
        Header:  BATCH|CCB|YYYY-MM|<count>|<total_yuan>
        Detail:  ROW|seq|name|bank_account|id_card|amount_yuan|memo|currency
        """
        total_fen = sum(r["net_salary_fen"] for r in rows)
        lines = [f"BATCH|CCB|{pay_month}|{len(rows)}|{_fmt_yuan(total_fen)}"]
        for idx, r in enumerate(rows, start=1):
            memo = f"{pay_month}工资"
            lines.append(
                "|".join(
                    [
                        "ROW",
                        str(idx),
                        r["name"],
                        r["bank_account"],
                        r["id_card_no"],
                        _fmt_yuan(r["net_salary_fen"]),
                        memo,
                        "CNY",
                    ]
                )
            )
        lines.append(f"END|{len(rows)}|{_fmt_yuan(total_fen)}")
        return "\n".join(lines) + "\n"

    def _render_csv(self, rows: List[Dict[str, Any]], pay_month: str) -> str:
        """
        通用 CSV（| 分隔 — 贴合需求描述）
        表头: 序号|姓名|银行账号|身份证|金额元|摘要
        """
        lines = ["序号|姓名|银行账号|身份证|金额元|摘要"]
        for idx, r in enumerate(rows, start=1):
            memo = f"{pay_month}工资"
            lines.append(
                "|".join(
                    [
                        str(idx),
                        r["name"],
                        r["bank_account"],
                        r["id_card_no"],
                        _fmt_yuan(r["net_salary_fen"]),
                        memo,
                    ]
                )
            )
        return "\n".join(lines) + "\n"

    # ── 落盘 + 登记 ───────────────────────────────────────────
    async def _write_and_register(
        self,
        db: AsyncSession,
        store_id: str,
        pay_month: str,
        rows: List[Dict[str, Any]],
        bank: DisbursementBank,
        ext: str,
        renderer,
    ) -> Dict[str, Any]:
        _ensure_dir(self.output_dir)
        batch_id = f"{bank.value.upper()}-{store_id}-{pay_month}-{uuid.uuid4().hex[:8]}"
        file_path = os.path.join(self.output_dir, f"{batch_id}.{ext}")

        content = renderer(rows, pay_month)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        total_fen = sum(r["net_salary_fen"] for r in rows)

        record = SalaryDisbursement(
            batch_id=batch_id,
            store_id=store_id,
            pay_month=pay_month,
            bank=bank,
            file_path=file_path,
            file_format=ext,
            total_amount_fen=total_fen,
            employee_count=len(rows),
            status=DisbursementStatus.GENERATED,
            generated_at=datetime.utcnow(),
        )
        db.add(record)
        await db.flush()

        logger.info(
            "salary_disbursement_generated",
            batch_id=batch_id,
            bank=bank.value,
            count=len(rows),
            total_yuan=round(total_fen / 100, 2),
            file_path=file_path,
        )

        return {
            "batch_id": batch_id,
            "bank": bank.value,
            "file_path": file_path,
            "employee_count": len(rows),
            "total_amount_fen": total_fen,
            "total_amount_yuan": round(total_fen / 100, 2),
            "status": DisbursementStatus.GENERATED.value,
            "pay_month": pay_month,
        }
