"""
会计凭证服务 — D7-P0 Must-Fix Task 1

核心能力：
  - create_voucher: 创建凭证 + 借贷平衡强校验（不平衡抛 ValidationError）
  - void_voucher: 红字作废
  - get_voucher / list_vouchers

会计基本方程：借方合计 = 贷方合计（Debits == Credits）
"""

import uuid
from datetime import date as date_type
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundError, ValidationError
from src.models.accounting import (
    ChartOfAccounts,
    Voucher,
    VoucherEntry,
    VoucherStatus,
)

logger = structlog.get_logger()


def _fen_to_yuan(fen: Optional[int]) -> float:
    return round((fen or 0) / 100, 2) if fen is not None else 0.0


class VoucherService:
    """凭证服务（复式记账）"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ══════════════════════════════════════════════════════════════
    # 1. 创建凭证（借贷平衡强校验）
    # ══════════════════════════════════════════════════════════════

    async def create_voucher(
        self,
        entries: List[Dict[str, Any]],
        summary: str,
        voucher_date: Optional[date_type] = None,
        brand_id: Optional[uuid.UUID] = None,
        store_id: Optional[uuid.UUID] = None,
        source_type: Optional[str] = None,
        source_id: Optional[uuid.UUID] = None,
        created_by: Optional[uuid.UUID] = None,
        auto_post: bool = True,
        extras: Optional[Dict[str, Any]] = None,
        commit: bool = True,
    ) -> Dict[str, Any]:
        """
        创建凭证

        Args:
            entries: 分录列表 [{account_code, debit_fen?, credit_fen?, summary?}]
                     每行只允许借或贷其一非零；至少2行；借贷合计必须相等
            summary: 凭证摘要
            voucher_date: 会计日期，默认今天
            brand_id/store_id: 多租户隔离
            source_type/source_id: 业务关联（追溯）
            created_by: 制单人
            auto_post: 是否直接过账（默认 True）
            commit: 是否在本方法 commit（False 时由调用方统一 commit；方便与业务操作同事务）

        Returns: 凭证字典
        """
        if not entries or len(entries) < 2:
            raise ValidationError("凭证至少需要2条分录（一借一贷）")

        # 1. 借贷平衡校验
        total_debit = 0
        total_credit = 0
        for idx, e in enumerate(entries):
            d = int(e.get("debit_fen") or 0)
            c = int(e.get("credit_fen") or 0)
            if d < 0 or c < 0:
                raise ValidationError(f"分录#{idx+1} 金额不能为负")
            if d > 0 and c > 0:
                raise ValidationError(f"分录#{idx+1} 不能同时有借方和贷方金额")
            if d == 0 and c == 0:
                raise ValidationError(f"分录#{idx+1} 借贷金额必须有一个大于0")
            if not e.get("account_code"):
                raise ValidationError(f"分录#{idx+1} 缺少科目代码 account_code")
            total_debit += d
            total_credit += c

        if total_debit != total_credit:
            raise ValidationError(
                f"借贷不平衡: 借方合计 {_fen_to_yuan(total_debit)} 元 != "
                f"贷方合计 {_fen_to_yuan(total_credit)} 元"
            )

        # 2. 科目存在性校验（并回填科目名称）
        account_codes = list({e["account_code"] for e in entries})
        coa_stmt = select(ChartOfAccounts).where(ChartOfAccounts.code.in_(account_codes))
        coa_result = await self.db.execute(coa_stmt)
        coa_map = {c.code: c for c in coa_result.scalars().all()}
        missing = [code for code in account_codes if code not in coa_map]
        if missing:
            raise ValidationError(f"科目代码不存在: {missing}（请先运行种子脚本 seed_chart_of_accounts.py）")

        # 3. 生成凭证号
        vdate = voucher_date or date_type.today()
        voucher_no = await self._generate_voucher_no(vdate)

        # 4. 创建凭证头
        voucher = Voucher(
            brand_id=brand_id,
            store_id=store_id,
            voucher_no=voucher_no,
            voucher_date=vdate,
            summary=summary,
            status=VoucherStatus.POSTED if auto_post else VoucherStatus.DRAFT,
            total_debit_fen=total_debit,
            total_credit_fen=total_credit,
            source_type=source_type,
            source_id=source_id,
            created_by=created_by,
            posted_by=created_by if auto_post else None,
            posted_at=datetime.utcnow() if auto_post else None,
            extras=extras,
        )
        self.db.add(voucher)
        await self.db.flush()  # 获取 voucher.id

        # 5. 创建分录
        for idx, e in enumerate(entries):
            ve = VoucherEntry(
                voucher_id=voucher.id,
                line_no=idx + 1,
                account_code=e["account_code"],
                account_name=coa_map[e["account_code"]].name,
                debit_fen=int(e.get("debit_fen") or 0),
                credit_fen=int(e.get("credit_fen") or 0),
                summary=e.get("summary") or summary,
            )
            self.db.add(ve)

        if commit:
            await self.db.commit()
            await self.db.refresh(voucher)

        logger.info(
            "voucher_created",
            voucher_id=str(voucher.id),
            voucher_no=voucher_no,
            total_yuan=_fen_to_yuan(total_debit),
            source_type=source_type,
            status=voucher.status.value,
        )

        return await self._voucher_to_dict(voucher)

    # ══════════════════════════════════════════════════════════════
    # 2. 作废凭证（生成红字冲销）
    # ══════════════════════════════════════════════════════════════

    async def void_voucher(
        self,
        voucher_id: uuid.UUID,
        reason: str,
        operator_id: uuid.UUID,
    ) -> Dict[str, Any]:
        """作废凭证 — 状态置为 VOID，生成一张红字冲销凭证"""
        voucher = await self._get_voucher_or_raise(voucher_id)
        if voucher.status == VoucherStatus.VOID:
            raise ValidationError("凭证已作废")

        # 加载分录
        entries_stmt = select(VoucherEntry).where(VoucherEntry.voucher_id == voucher_id)
        orig_entries = (await self.db.execute(entries_stmt)).scalars().all()

        # 构造红字冲销分录（借贷互换）
        reverse_entries = []
        for e in orig_entries:
            reverse_entries.append({
                "account_code": e.account_code,
                "debit_fen": e.credit_fen,
                "credit_fen": e.debit_fen,
                "summary": f"冲销 {voucher.voucher_no}: {e.summary or ''}",
            })

        # 原凭证置为作废
        voucher.status = VoucherStatus.VOID
        voucher.void_reason = reason

        await self.db.flush()

        # 创建冲销凭证（不 commit，和作废同事务）
        reverse = await self.create_voucher(
            entries=reverse_entries,
            summary=f"红字冲销 {voucher.voucher_no}: {reason}",
            brand_id=voucher.brand_id,
            store_id=voucher.store_id,
            source_type="voucher_reverse",
            source_id=voucher.id,
            created_by=operator_id,
            auto_post=True,
            commit=False,
        )

        await self.db.commit()
        await self.db.refresh(voucher)

        logger.info("voucher_voided", voucher_id=str(voucher_id), reverse_voucher_no=reverse["voucher_no"])
        return {
            "voided": await self._voucher_to_dict(voucher),
            "reverse": reverse,
        }

    # ══════════════════════════════════════════════════════════════
    # 3. 查询
    # ══════════════════════════════════════════════════════════════

    async def get_voucher(self, voucher_id: uuid.UUID) -> Dict[str, Any]:
        voucher = await self._get_voucher_or_raise(voucher_id)
        return await self._voucher_to_dict(voucher)

    async def list_vouchers(
        self,
        store_id: Optional[uuid.UUID] = None,
        start_date: Optional[date_type] = None,
        end_date: Optional[date_type] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        conditions = []
        if store_id:
            conditions.append(Voucher.store_id == store_id)
        if start_date:
            conditions.append(Voucher.voucher_date >= start_date)
        if end_date:
            conditions.append(Voucher.voucher_date <= end_date)
        if status:
            conditions.append(Voucher.status == VoucherStatus(status))

        count_stmt = select(func.count(Voucher.id))
        if conditions:
            count_stmt = count_stmt.where(*conditions)
        total = (await self.db.execute(count_stmt)).scalar() or 0

        stmt = select(Voucher)
        if conditions:
            stmt = stmt.where(*conditions)
        stmt = stmt.order_by(Voucher.voucher_date.desc(), Voucher.created_at.desc()).limit(limit).offset(offset)
        vouchers = (await self.db.execute(stmt)).scalars().all()

        items = [await self._voucher_to_dict(v, include_entries=False) for v in vouchers]
        return {"total": total, "items": items}

    # ══════════════════════════════════════════════════════════════
    # 私有辅助
    # ══════════════════════════════════════════════════════════════

    async def _generate_voucher_no(self, vdate: date_type) -> str:
        """生成凭证号: PZ-YYYYMMDD-NNNN（当日序号 4 位）"""
        date_str = vdate.strftime("%Y%m%d")
        prefix = f"PZ-{date_str}-"
        stmt = select(func.count(Voucher.id)).where(Voucher.voucher_no.like(f"{prefix}%"))
        count = (await self.db.execute(stmt)).scalar() or 0
        return f"{prefix}{count + 1:04d}"

    async def _get_voucher_or_raise(self, voucher_id: uuid.UUID) -> Voucher:
        stmt = select(Voucher).where(Voucher.id == voucher_id)
        v = (await self.db.execute(stmt)).scalar_one_or_none()
        if not v:
            raise NotFoundError(f"凭证 {voucher_id} 不存在")
        return v

    async def _voucher_to_dict(self, v: Voucher, include_entries: bool = True) -> Dict[str, Any]:
        d = {
            "id": str(v.id),
            "voucher_no": v.voucher_no,
            "voucher_date": v.voucher_date.isoformat() if v.voucher_date else None,
            "summary": v.summary,
            "status": v.status.value,
            "total_debit_fen": v.total_debit_fen,
            "total_debit_yuan": _fen_to_yuan(v.total_debit_fen),
            "total_credit_fen": v.total_credit_fen,
            "total_credit_yuan": _fen_to_yuan(v.total_credit_fen),
            "source_type": v.source_type,
            "source_id": str(v.source_id) if v.source_id else None,
            "store_id": str(v.store_id) if v.store_id else None,
            "posted_at": v.posted_at.isoformat() if v.posted_at else None,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        if include_entries:
            stmt = select(VoucherEntry).where(VoucherEntry.voucher_id == v.id).order_by(VoucherEntry.line_no)
            entries = (await self.db.execute(stmt)).scalars().all()
            d["entries"] = [
                {
                    "line_no": e.line_no,
                    "account_code": e.account_code,
                    "account_name": e.account_name,
                    "debit_fen": e.debit_fen,
                    "debit_yuan": _fen_to_yuan(e.debit_fen),
                    "credit_fen": e.credit_fen,
                    "credit_yuan": _fen_to_yuan(e.credit_fen),
                    "summary": e.summary,
                }
                for e in entries
            ]
        return d


def get_voucher_service(db: AsyncSession) -> VoucherService:
    return VoucherService(db)
