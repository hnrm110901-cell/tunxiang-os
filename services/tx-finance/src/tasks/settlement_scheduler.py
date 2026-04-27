"""储值分账结算调度 — 每日自动结算 + 批次确认

调度逻辑：
  1. run_daily_settlement(tenant_id)
     - 每天凌晨执行（由外部 cron 或 APScheduler 调用）
     - 汇总前一天所有 pending 的分账流水
     - 生成 sv_settlement_batches 记录
     - 将流水的 settlement_batch_id 指向该批次

  2. confirm_settlement_batch(batch_id)
     - 财务确认结算批次（draft → confirmed）
     - 关联流水 settlement_status 改为 settled

  3. settle_batch(batch_id)
     - 实际打款完成后调用（confirmed → settled）

金额单位：分（fen）
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)


class SettlementScheduler:
    """储值分账结算调度器"""

    def __init__(self, db: AsyncSession, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self._tid = uuid.UUID(tenant_id)

    async def _set_tenant(self) -> None:
        await self.db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": self.tenant_id},
        )

    # ══════════════════════════════════════════════════════════════
    # 每日结算
    # ══════════════════════════════════════════════════════════════

    async def run_daily_settlement(
        self,
        settlement_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """执行每日结算

        参数：
            settlement_date: 结算日期，默认为昨天。
                             将汇总该日期 00:00:00 到 23:59:59 的 pending 流水。

        返回：
            batch_id, batch_no, total_records, total_amount_fen
        """
        await self._set_tenant()

        if settlement_date is None:
            settlement_date = (datetime.now(timezone.utc) - timedelta(days=1)).date()

        period_start = settlement_date
        period_end = settlement_date

        # 生成批次号: SV-SETTLE-YYYYMMDD-XXXXXX
        batch_no = f"SV-SETTLE-{settlement_date.strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}"

        # 查询当天 pending 的分账流水
        count_result = await self.db.execute(
            text("""
                SELECT COUNT(*) AS cnt,
                       COALESCE(SUM(ABS(total_amount_fen)), 0) AS total_fen
                FROM stored_value_split_ledger
                WHERE tenant_id = :tid
                  AND is_deleted = FALSE
                  AND settlement_status = 'pending'
                  AND settlement_batch_id IS NULL
                  AND created_at >= :start::date
                  AND created_at < (:end::date + INTERVAL '1 day')
            """),
            {"tid": self._tid, "start": period_start, "end": period_end},
        )
        row = count_result.fetchone()
        total_records = int(row.cnt)
        total_amount_fen = int(row.total_fen)

        if total_records == 0:
            log.info(
                "sv_settlement.no_pending_records",
                settlement_date=str(settlement_date),
                tenant_id=self.tenant_id,
            )
            return {
                "batch_id": None,
                "batch_no": None,
                "total_records": 0,
                "total_amount_fen": 0,
                "message": f"无需结算：{settlement_date} 无 pending 分账流水",
            }

        # 创建结算批次
        batch_id = uuid.uuid4()
        await self.db.execute(
            text("""
                INSERT INTO sv_settlement_batches
                    (id, tenant_id, batch_no, period_start, period_end,
                     total_records, total_amount_fen, status)
                VALUES
                    (:id, :tid, :batch_no, :p_start, :p_end,
                     :total_records, :total_fen, 'draft')
            """),
            {
                "id": batch_id,
                "tid": self._tid,
                "batch_no": batch_no,
                "p_start": period_start,
                "p_end": period_end,
                "total_records": total_records,
                "total_fen": total_amount_fen,
            },
        )

        # 将流水关联到批次
        await self.db.execute(
            text("""
                UPDATE stored_value_split_ledger
                SET settlement_batch_id = :batch_id,
                    updated_at = NOW()
                WHERE tenant_id = :tid
                  AND is_deleted = FALSE
                  AND settlement_status = 'pending'
                  AND settlement_batch_id IS NULL
                  AND created_at >= :start::date
                  AND created_at < (:end::date + INTERVAL '1 day')
            """),
            {
                "batch_id": batch_id,
                "tid": self._tid,
                "start": period_start,
                "end": period_end,
            },
        )

        await self.db.flush()

        log.info(
            "sv_settlement.batch_created",
            batch_id=str(batch_id),
            batch_no=batch_no,
            total_records=total_records,
            total_amount_fen=total_amount_fen,
            settlement_date=str(settlement_date),
            tenant_id=self.tenant_id,
        )

        return {
            "batch_id": str(batch_id),
            "batch_no": batch_no,
            "period_start": str(period_start),
            "period_end": str(period_end),
            "total_records": total_records,
            "total_amount_fen": total_amount_fen,
            "status": "draft",
        }

    # ══════════════════════════════════════════════════════════════
    # 批次确认
    # ══════════════════════════════════════════════════════════════

    async def confirm_settlement_batch(
        self,
        batch_id: str,
    ) -> Dict[str, Any]:
        """确认结算批次（draft → confirmed），关联流水标记为 settled

        步骤：
          1. 验证批次状态 = draft
          2. 更新批次状态 = confirmed
          3. 更新关联流水 settlement_status = settled, settled_at = NOW()
        """
        await self._set_tenant()
        bid = uuid.UUID(batch_id)

        # 原子更新：WHERE status = 'draft' 防止并发重复确认
        update_result = await self.db.execute(
            text("""
                UPDATE sv_settlement_batches
                SET status = 'confirmed', updated_at = NOW()
                WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE
                  AND status = 'draft'
                RETURNING id, batch_no, status, total_records, total_amount_fen
            """),
            {"id": bid, "tid": self._tid},
        )
        batch = update_result.fetchone()
        if not batch:
            # 区分不存在 vs 状态不对
            check = await self.db.execute(
                text(
                    "SELECT status FROM sv_settlement_batches WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE"
                ),
                {"id": bid, "tid": self._tid},
            )
            existing = check.fetchone()
            if not existing:
                raise ValueError(f"结算批次不存在: {batch_id}")
            raise ValueError(f"只能确认 draft 状态的批次，当前状态: {existing.status}")

        # 关联流水标记为 settled
        now = datetime.now(timezone.utc)
        settle_result = await self.db.execute(
            text("""
                UPDATE stored_value_split_ledger
                SET settlement_status = 'settled',
                    settled_at = :now,
                    updated_at = NOW()
                WHERE settlement_batch_id = :batch_id
                  AND tenant_id = :tid
                  AND settlement_status = 'pending'
            """),
            {"batch_id": bid, "tid": self._tid, "now": now},
        )
        settled_count = settle_result.rowcount

        await self.db.flush()

        log.info(
            "sv_settlement.batch_confirmed",
            batch_id=batch_id,
            batch_no=batch.batch_no,
            settled_count=settled_count,
            tenant_id=self.tenant_id,
        )

        return {
            "batch_id": batch_id,
            "batch_no": batch.batch_no,
            "status": "confirmed",
            "settled_count": settled_count,
            "total_records": batch.total_records,
            "total_amount_fen": int(batch.total_amount_fen),
        }

    async def settle_batch(
        self,
        batch_id: str,
    ) -> Dict[str, Any]:
        """实际打款完成后将批次标记为 settled（confirmed → settled）"""
        await self._set_tenant()
        bid = uuid.UUID(batch_id)

        # 原子更新：WHERE status = 'confirmed' 防止并发
        update_result = await self.db.execute(
            text("""
                UPDATE sv_settlement_batches
                SET status = 'settled', updated_at = NOW()
                WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE
                  AND status = 'confirmed'
                RETURNING id, batch_no
            """),
            {"id": bid, "tid": self._tid},
        )
        batch = update_result.fetchone()
        if not batch:
            check = await self.db.execute(
                text(
                    "SELECT status FROM sv_settlement_batches WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE"
                ),
                {"id": bid, "tid": self._tid},
            )
            existing = check.fetchone()
            if not existing:
                raise ValueError(f"结算批次不存在: {batch_id}")
            raise ValueError(f"只能将 confirmed 状态的批次标记为 settled，当前: {existing.status}")

        await self.db.flush()

        log.info(
            "sv_settlement.batch_settled",
            batch_id=batch_id,
            batch_no=batch.batch_no,
            tenant_id=self.tenant_id,
        )

        return {
            "batch_id": batch_id,
            "batch_no": batch.batch_no,
            "status": "settled",
        }

    # ══════════════════════════════════════════════════════════════
    # 批次查询
    # ══════════════════════════════════════════════════════════════

    async def list_batches(
        self,
        status: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> Dict[str, Any]:
        """查询结算批次列表"""
        await self._set_tenant()
        where = "WHERE tenant_id = :tid AND is_deleted = FALSE"
        params: Dict[str, Any] = {"tid": self._tid}

        if status:
            where += " AND status = :status"
            params["status"] = status

        count_result = await self.db.execute(
            text(f"SELECT COUNT(*) FROM sv_settlement_batches {where}"),
            params,
        )
        total = count_result.scalar() or 0

        params["limit"] = size
        params["offset"] = (page - 1) * size
        result = await self.db.execute(
            text(f"""
                SELECT id, batch_no, period_start, period_end,
                       total_records, total_amount_fen, status,
                       created_at, updated_at
                FROM sv_settlement_batches
                {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        items = [
            {
                "batch_id": str(r.id),
                "batch_no": r.batch_no,
                "period_start": str(r.period_start),
                "period_end": str(r.period_end),
                "total_records": r.total_records,
                "total_amount_fen": int(r.total_amount_fen),
                "total_amount_yuan": round(int(r.total_amount_fen) / 100, 2),
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in result.fetchall()
        ]
        return {"items": items, "total": total, "page": page, "size": size}

    async def get_batch(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """查询单个结算批次详情"""
        await self._set_tenant()
        result = await self.db.execute(
            text("""
                SELECT id, batch_no, period_start, period_end,
                       total_records, total_amount_fen, status,
                       created_at, updated_at
                FROM sv_settlement_batches
                WHERE id = :id AND tenant_id = :tid AND is_deleted = FALSE
            """),
            {"id": uuid.UUID(batch_id), "tid": self._tid},
        )
        r = result.fetchone()
        if not r:
            return None
        return {
            "batch_id": str(r.id),
            "batch_no": r.batch_no,
            "period_start": str(r.period_start),
            "period_end": str(r.period_end),
            "total_records": r.total_records,
            "total_amount_fen": int(r.total_amount_fen),
            "total_amount_yuan": round(int(r.total_amount_fen) / 100, 2),
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
