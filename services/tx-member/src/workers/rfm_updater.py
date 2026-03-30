"""RFM 每日批量更新 Worker

负责将全量会员的 r_score / f_score / m_score / rfm_level / risk_score
写入 customers 表，替代即时全量查询方案。

算法说明：
  R评分（1-5）：基于 last_order_at 距今天数
  F评分（1-5）：基于 total_order_count
  M评分（1-5）：基于 total_order_amount_fen（单位：分）
  rfm_level  ：R+F+M 总分 → S1(顶级VIP 13-15) / S2(高价值 10-12) /
               S3(中等 7-9) / S4(低频 4-6) / S5(沉睡 3)
  risk_score ：recency_days/90，R评分=1时额外乘1.3

分批策略：每批 500 条 UPDATE，避免长事务。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select, update, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.entities import Customer

logger = structlog.get_logger(__name__)

BATCH_SIZE = 500


# ── 评分函数 ───────────────────────────────────────────────────

def _calc_r_score(recency_days: int) -> int:
    """R评分：最近消费天数 → 1-5分（越近越高）"""
    if recency_days <= 7:
        return 5
    if recency_days <= 30:
        return 4
    if recency_days <= 60:
        return 3
    if recency_days <= 90:
        return 2
    return 1


def _calc_f_score(order_count: int) -> int:
    """F评分：累计消费次数 → 1-5分（越多越高）"""
    if order_count >= 20:
        return 5
    if order_count >= 10:
        return 4
    if order_count >= 5:
        return 3
    if order_count >= 2:
        return 2
    return 1


def _calc_m_score(amount_fen: int) -> int:
    """M评分：累计消费金额（分）→ 1-5分（越高越高）"""
    if amount_fen >= 1_000_000:  # 1万元
        return 5
    if amount_fen >= 500_000:    # 5000元
        return 4
    if amount_fen >= 200_000:    # 2000元
        return 3
    if amount_fen >= 50_000:     # 500元
        return 2
    return 1


def _calc_rfm_level(r: int, f: int, m: int) -> str:
    """综合 RFM 等级：R+F+M 总分划分"""
    total = r + f + m
    if total >= 13:
        return "S1"   # 顶级VIP  13-15分
    if total >= 10:
        return "S2"   # 高价值   10-12分
    if total >= 7:
        return "S3"   # 中等     7-9分
    if total >= 4:
        return "S4"   # 低频     4-6分
    return "S5"       # 沉睡     3分


def _calc_risk_score(recency_days: int, r_score: int) -> float:
    """流失风险分：0.0-1.0

    基础：recency_days / 90（超90天=1.0）
    调整：r_score=1 时额外乘1.3（超时滞留加权）
    """
    base = min(1.0, recency_days / 90)
    if r_score == 1:
        base = min(1.0, base * 1.3)
    return round(base, 3)


# ── RFMUpdater ────────────────────────────────────────────────

class RFMUpdater:
    """RFM 批量更新器

    外部调用入口：
        updater = RFMUpdater()
        await updater.update_all_tenants(db)
    """

    async def update_all_tenants(self, db: AsyncSession) -> dict[str, Any]:
        """遍历所有活跃租户，依次更新 RFM 评分。

        Args:
            db: 数据库异步会话

        Returns:
            {total_tenants, total_updated, elapsed_seconds}
        """
        started_at = datetime.now(timezone.utc)

        # 从 customers 表取 DISTINCT tenant_id（只处理有数据的租户）
        result = await db.execute(
            select(distinct(Customer.tenant_id))
            .where(Customer.is_deleted == False)  # noqa: E712
        )
        tenant_ids: list[uuid.UUID] = [row[0] for row in result.all()]

        total_updated = 0
        failed_tenants: list[str] = []

        logger.info(
            "rfm_update_started",
            tenant_count=len(tenant_ids),
        )

        for tenant_id in tenant_ids:
            try:
                updated = await self.update_tenant_rfm(tenant_id, db)
                total_updated += updated
            except (OSError, RuntimeError, ValueError) as exc:
                # 单个租户失败不中断整体任务
                logger.error(
                    "rfm_tenant_update_failed",
                    tenant_id=str(tenant_id),
                    error=str(exc),
                    exc_info=True,
                )
                failed_tenants.append(str(tenant_id))

        elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()

        logger.info(
            "rfm_update_completed",
            total_tenants=len(tenant_ids),
            total_updated=total_updated,
            failed_tenants=len(failed_tenants),
            elapsed_seconds=round(elapsed, 2),
        )

        return {
            "total_tenants": len(tenant_ids),
            "total_updated": total_updated,
            "failed_tenants": failed_tenants,
            "elapsed_seconds": round(elapsed, 2),
        }

    async def update_tenant_rfm(
        self,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> int:
        """更新单个租户下所有有效会员的 RFM 评分。

        Args:
            tenant_id: 租户 UUID
            db: 数据库异步会话

        Returns:
            本次更新的会员数量
        """
        tenant_started = datetime.now(timezone.utc)
        now = datetime.now(timezone.utc)

        # 查询该租户所有有效会员（非删除，有消费记录）
        result = await db.execute(
            select(
                Customer.id,
                Customer.last_order_at,
                Customer.total_order_count,
                Customer.total_order_amount_fen,
            )
            .where(Customer.tenant_id == tenant_id)
            .where(Customer.is_deleted == False)  # noqa: E712
            .where(Customer.is_merged == False)   # noqa: E712
        )
        rows = result.all()

        if not rows:
            logger.debug(
                "rfm_tenant_no_customers",
                tenant_id=str(tenant_id),
            )
            return 0

        # 计算每位会员的 RFM 评分
        updates: list[dict] = []
        level_counts: dict[str, int] = {"S1": 0, "S2": 0, "S3": 0, "S4": 0, "S5": 0}

        for customer_id, last_order_at, total_count, total_amount_fen in rows:
            # R 值：最近消费天数
            if last_order_at is not None:
                loa = last_order_at
                if loa.tzinfo is None:
                    loa = loa.replace(tzinfo=timezone.utc)
                recency_days = (now - loa).days
            else:
                recency_days = 9999

            # 三维评分
            r = _calc_r_score(recency_days)
            f = _calc_f_score(total_count or 0)
            m = _calc_m_score(total_amount_fen or 0)
            level = _calc_rfm_level(r, f, m)
            risk = _calc_risk_score(recency_days, r)

            level_counts[level] = level_counts.get(level, 0) + 1

            updates.append({
                "id": customer_id,
                "r_score": r,
                "f_score": f,
                "m_score": m,
                "rfm_level": level,
                "rfm_recency_days": min(recency_days, 9999),
                "risk_score": risk,
                "rfm_updated_at": now,
                "updated_at": now,
            })

        # 批量 UPDATE，每批 BATCH_SIZE 条，避免长事务
        # SQLAlchemy asyncio bulk update mappings：传入 list[dict]，
        # 每个 dict 必须含 "id" 作为 WHERE 条件，其余字段作为 SET 值。
        total_updated = 0
        for batch_start in range(0, len(updates), BATCH_SIZE):
            batch = updates[batch_start: batch_start + BATCH_SIZE]
            await db.execute(update(Customer), batch)
            await db.commit()
            total_updated += len(batch)

        elapsed_ms = int(
            (datetime.now(timezone.utc) - tenant_started).total_seconds() * 1000
        )

        # 尝试记录每日快照（表不存在时忽略）
        stats = {
            "date": date.today().isoformat(),
            "tenant_id": str(tenant_id),
            **{f"s{i}_count": level_counts.get(f"S{i}", 0) for i in range(1, 6)},
            "total_updated": total_updated,
        }
        await self.record_rfm_snapshot(tenant_id, stats, db)

        logger.info(
            "rfm_tenant_updated",
            tenant_id=str(tenant_id),
            total_customers=len(rows),
            total_updated=total_updated,
            level_distribution=level_counts,
            elapsed_ms=elapsed_ms,
        )

        return total_updated

    async def record_rfm_snapshot(
        self,
        tenant_id: uuid.UUID,
        stats: dict[str, Any],
        db: AsyncSession,
    ) -> None:
        """将每日 RFM 分布快照写入 rfm_daily_snapshots 表。

        表不存在时仅打印日志，不抛异常（可选功能）。

        Args:
            tenant_id: 租户 UUID
            stats: {date, tenant_id, s1_count~s5_count, total_updated}
            db: 数据库异步会话
        """
        from sqlalchemy import text
        from sqlalchemy.exc import ProgrammingError

        insert_sql = text("""
            INSERT INTO rfm_daily_snapshots
                (tenant_id, snapshot_date, s1_count, s2_count, s3_count,
                 s4_count, s5_count, total_updated, created_at)
            VALUES
                (:tenant_id, :snapshot_date, :s1_count, :s2_count, :s3_count,
                 :s4_count, :s5_count, :total_updated, now())
            ON CONFLICT (tenant_id, snapshot_date) DO UPDATE SET
                s1_count     = EXCLUDED.s1_count,
                s2_count     = EXCLUDED.s2_count,
                s3_count     = EXCLUDED.s3_count,
                s4_count     = EXCLUDED.s4_count,
                s5_count     = EXCLUDED.s5_count,
                total_updated = EXCLUDED.total_updated
        """)

        try:
            await db.execute(
                insert_sql,
                {
                    "tenant_id": str(tenant_id),
                    "snapshot_date": stats["date"],
                    "s1_count": stats.get("s1_count", 0),
                    "s2_count": stats.get("s2_count", 0),
                    "s3_count": stats.get("s3_count", 0),
                    "s4_count": stats.get("s4_count", 0),
                    "s5_count": stats.get("s5_count", 0),
                    "total_updated": stats.get("total_updated", 0),
                },
            )
            await db.commit()
            logger.debug(
                "rfm_snapshot_recorded",
                tenant_id=str(tenant_id),
                snapshot_date=stats["date"],
            )
        except ProgrammingError:
            # rfm_daily_snapshots 表尚未创建，跳过快照写入
            await db.rollback()
            logger.warning(
                "rfm_snapshot_table_missing",
                tenant_id=str(tenant_id),
                hint="run migration to create rfm_daily_snapshots table",
            )
