"""每日成本归集 Worker

每晚 23:30 运行，将当日营收与费控支出对比，生成成本归集日报。

流程：
1. 获取所有 active 租户列表
2. 对每个租户，获取所有门店
3. 对每个门店，从 tx-ops 拉取当日 POS 日结数据
4. 从 tx-expense 查询当日已审批的费控申请
5. 按成本类型（食材/人力/其他）分类归集
6. 计算成本率和毛利率
7. 写入/更新 daily_cost_reports
8. 如果成本率异常（食材 >40% 或毛利 <50%），触发 A4 预警

外部依赖：
  TX_OPS_URL  — tx-ops 服务地址（默认 http://localhost:8008）
  DEFAULT_TENANT_ID — P2 阶段单租户 ID
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

TX_OPS_URL = os.getenv("TX_OPS_URL", "http://localhost:8008")
DEFAULT_TENANT_ID = os.getenv("DEFAULT_TENANT_ID")

# 成本异常阈值
_FOOD_COST_RATE_ALERT = Decimal("0.40")   # 食材成本率 >40% 预警
_GROSS_MARGIN_RATE_ALERT = Decimal("0.50")  # 毛利率 <50% 预警

# 费控申请 cost_type 映射（category_code → cost_type）
_CATEGORY_TO_COST_TYPE: dict[str, str] = {
    "food": "food",
    "ingredient": "food",
    "raw_material": "food",
    "labor": "labor",
    "salary": "labor",
    "wage": "labor",
    "rent": "rent",
    "utility": "utility",
    "water": "utility",
    "electricity": "utility",
}


# ─────────────────────────────────────────────────────────────────────────────
# 主 Worker 类
# ─────────────────────────────────────────────────────────────────────────────

class DailyCostAttributionWorker:
    """每日成本归集批量处理器。

    外部调用入口：
        worker = DailyCostAttributionWorker()
        await worker.run()
    """

    # ── 1. 租户/门店获取 ─────────────────────────────────────────────────

    async def _get_active_tenant_ids(self) -> list[str]:
        """获取所有活跃租户 ID 列表。

        从 stores 表查询所有有效租户（BYPASSRLS 会话，跨租户读取）。
        查询失败时降级为 DEFAULT_TENANT_ID 环境变量（向后兼容单租户部署）。
        """
        from sqlalchemy import text as _text
        from shared.ontology.src.database import get_db_no_rls

        try:
            async for db in get_db_no_rls():
                result = await db.execute(
                    _text("""
                        SELECT DISTINCT tenant_id::text
                        FROM stores
                        WHERE is_deleted = FALSE
                        ORDER BY 1
                    """)
                )
                tenant_ids = [row[0] for row in result.fetchall()]
                if tenant_ids:
                    log.info(
                        "daily_cost_attribution_tenants_loaded",
                        tenant_count=len(tenant_ids),
                    )
                    return tenant_ids
                # stores 表为空：降级
                log.warning("daily_cost_attribution_stores_table_empty")
        except Exception as exc:  # noqa: BLE001
            log.error(
                "daily_cost_attribution_tenant_query_failed",
                error=str(exc),
                exc_info=True,
            )

        # 降级：单租户环境变量
        default_tenant = os.environ.get("DEFAULT_TENANT_ID")
        if default_tenant:
            log.warning(
                "daily_cost_attribution_fallback_to_default_tenant",
                tenant_id=default_tenant,
            )
            return [default_tenant]

        log.warning("daily_cost_attribution_no_tenant_configured")
        return []

    async def _get_store_ids(self, tenant_id: UUID, db: AsyncSession) -> list[UUID]:
        """从本地 DB 查询该租户下所有门店 ID（费控申请中出现过的门店）。

        多租户扩展时可优先从 tx-org /api/v1/org/stores 拉取，此处作兜底。
        """
        from ..models.expense_application import ExpenseApplication
        from ..models.expense_enums import ExpenseStatus

        stmt = (
            select(ExpenseApplication.store_id)
            .where(
                ExpenseApplication.tenant_id == tenant_id,
                ExpenseApplication.store_id.isnot(None),
            )
            .distinct()
        )
        result = await db.execute(stmt)
        store_ids = [row[0] for row in result.fetchall() if row[0] is not None]
        return store_ids

    # ── 2. POS 日结数据拉取 ────────────────────────────────────────────────

    async def _fetch_pos_daily_close(
        self, store_id: UUID, target_date: date
    ) -> Optional[dict[str, Any]]:
        """从 tx-ops 拉取指定门店指定日期的 POS 日结数据。

        失败时返回 None（降级），不中断整体流程。
        超时：10 秒。

        返回字段（来自 tx-ops /api/v1/pos/daily-close）：
            total_revenue_fen   int   当日营收（分）
            table_count         int   桌次
            customer_count      int   客数
            pos_source          str   POS 系统标识
        """
        url = f"{TX_OPS_URL}/api/v1/pos/daily-close"
        params = {"store_id": str(store_id), "date": target_date.isoformat()}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
                # tx-ops 统一响应格式 {"ok": true, "data": {...}}
                if data.get("ok") and data.get("data"):
                    return data["data"]
                log.warning(
                    "pos_daily_close_empty_response",
                    store_id=str(store_id),
                    date=target_date.isoformat(),
                    response=data,
                )
                return None
        except httpx.TimeoutException:
            log.error(
                "pos_daily_close_timeout",
                store_id=str(store_id),
                date=target_date.isoformat(),
                url=url,
            )
            return None
        except httpx.HTTPStatusError as exc:
            log.error(
                "pos_daily_close_http_error",
                store_id=str(store_id),
                date=target_date.isoformat(),
                status_code=exc.response.status_code,
                exc_info=True,
            )
            return None
        except httpx.RequestError as exc:
            log.error(
                "pos_daily_close_request_error",
                store_id=str(store_id),
                date=target_date.isoformat(),
                error=str(exc),
                exc_info=True,
            )
            return None

    # ── 3. 费控申请查询与分类 ──────────────────────────────────────────────

    async def _get_approved_expenses(
        self, db: AsyncSession, tenant_id: UUID, store_id: UUID, target_date: date
    ) -> list[dict[str, Any]]:
        """查询指定门店指定日期已审批的费控申请，返回归集所需字段列表。"""
        from ..models.expense_application import ExpenseApplication
        from ..models.expense_enums import ExpenseStatus

        stmt = select(
            ExpenseApplication.id,
            ExpenseApplication.category_code,
            ExpenseApplication.amount,
            ExpenseApplication.description,
        ).where(
            ExpenseApplication.tenant_id == tenant_id,
            ExpenseApplication.store_id == store_id,
            ExpenseApplication.status == ExpenseStatus.APPROVED,
            ExpenseApplication.expense_date == target_date,
            ExpenseApplication.is_deleted.is_(False),
        )
        result = await db.execute(stmt)
        rows = result.fetchall()

        expenses = []
        for row in rows:
            category_code = row[1] or "other"
            cost_type = _CATEGORY_TO_COST_TYPE.get(category_code.lower(), "other")
            expenses.append({
                "application_id": row[0],
                "category_code": category_code,
                "cost_type": cost_type,
                "amount_fen": row[2] or 0,
                "description": row[3] or "",
            })
        return expenses

    # ── 4. 成本归集计算 ────────────────────────────────────────────────────

    def _aggregate_costs(
        self, expenses: list[dict[str, Any]]
    ) -> dict[str, int]:
        """按成本类型汇总费控申请金额（分）。"""
        costs: dict[str, int] = {
            "food": 0,
            "labor": 0,
            "other": 0,
        }
        for exp in expenses:
            ct = exp["cost_type"]
            amount = int(exp["amount_fen"])
            if ct in ("food",):
                costs["food"] += amount
            elif ct in ("labor",):
                costs["labor"] += amount
            else:
                costs["other"] += amount
        return costs

    # ── 5. 写入/更新日报 ────────────────────────────────────────────────────

    async def _upsert_daily_report(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID,
        report_date: date,
        pos_data: Optional[dict[str, Any]],
        costs: dict[str, int],
        expenses: list[dict[str, Any]],
    ) -> UUID:
        """Upsert daily_cost_reports 并写入归集明细。

        使用 PostgreSQL INSERT ... ON CONFLICT DO UPDATE 保证幂等。
        """
        from ..models.cost_report import CostAttributionItem, DailyCostReport

        total_revenue_fen = int((pos_data or {}).get("total_revenue_fen", 0))
        table_count = int((pos_data or {}).get("table_count", 0))
        customer_count = int((pos_data or {}).get("customer_count", 0))
        pos_source = (pos_data or {}).get("pos_source") or (pos_data or {}).get("pos_data_source")

        food_cost_fen = costs["food"]
        labor_cost_fen = costs["labor"]
        other_cost_fen = costs["other"]
        total_cost_fen = food_cost_fen + labor_cost_fen + other_cost_fen

        # 计算成本率（营收为0时为None）
        food_cost_rate: Optional[Decimal] = None
        labor_cost_rate: Optional[Decimal] = None
        gross_margin_rate: Optional[Decimal] = None
        if total_revenue_fen > 0:
            rev = Decimal(total_revenue_fen)
            food_cost_rate = Decimal(food_cost_fen) / rev
            labor_cost_rate = Decimal(labor_cost_fen) / rev
            gross_margin_rate = Decimal(total_revenue_fen - total_cost_fen) / rev

        data_status = "complete" if pos_data is not None else "pending"

        # Upsert via PostgreSQL INSERT ... ON CONFLICT
        stmt = pg_insert(DailyCostReport.__table__).values(
            tenant_id=tenant_id,
            store_id=store_id,
            report_date=report_date,
            total_revenue_fen=total_revenue_fen,
            table_count=table_count,
            customer_count=customer_count,
            food_cost_fen=food_cost_fen,
            labor_cost_fen=labor_cost_fen,
            other_cost_fen=other_cost_fen,
            total_cost_fen=total_cost_fen,
            food_cost_rate=food_cost_rate,
            labor_cost_rate=labor_cost_rate,
            gross_margin_rate=gross_margin_rate,
            pos_data_source=pos_source,
            data_status=data_status,
        ).on_conflict_do_update(
            constraint="uq_daily_cost_reports_tenant_store_date",
            set_={
                "total_revenue_fen": total_revenue_fen,
                "table_count": table_count,
                "customer_count": customer_count,
                "food_cost_fen": food_cost_fen,
                "labor_cost_fen": labor_cost_fen,
                "other_cost_fen": other_cost_fen,
                "total_cost_fen": total_cost_fen,
                "food_cost_rate": food_cost_rate,
                "labor_cost_rate": labor_cost_rate,
                "gross_margin_rate": gross_margin_rate,
                "pos_data_source": pos_source,
                "data_status": data_status,
                "updated_at": datetime.now(timezone.utc),
            },
        ).returning(DailyCostReport.__table__.c.id)

        result = await db.execute(stmt)
        report_id: UUID = result.scalar_one()

        # 写入归集明细（先删除当日旧明细，再重新写入，保证幂等）
        from sqlalchemy import delete as sa_delete

        await db.execute(
            sa_delete(CostAttributionItem.__table__).where(
                CostAttributionItem.__table__.c.tenant_id == tenant_id,
                CostAttributionItem.__table__.c.store_id == store_id,
                CostAttributionItem.__table__.c.attribution_date == report_date,
            )
        )

        for exp in expenses:
            item = CostAttributionItem(
                tenant_id=tenant_id,
                report_id=report_id,
                expense_application_id=exp["application_id"],
                store_id=store_id,
                attribution_date=report_date,
                cost_type=exp["cost_type"],
                amount_fen=int(exp["amount_fen"]),
                description=exp.get("description", ""),
            )
            db.add(item)

        await db.flush()
        return report_id

    # ── 6. A4 异常预警 ─────────────────────────────────────────────────────

    async def _trigger_cost_alert_if_needed(
        self,
        tenant_id: UUID,
        store_id: UUID,
        report_date: date,
        food_cost_rate: Optional[Decimal],
        gross_margin_rate: Optional[Decimal],
    ) -> None:
        """如成本率异常，异步触发 A4 预算预警（不阻塞归集主流程）。"""
        alerts: list[str] = []

        if food_cost_rate is not None and food_cost_rate > _FOOD_COST_RATE_ALERT:
            alerts.append(
                f"食材成本率 {float(food_cost_rate):.1%} 超过阈值 {float(_FOOD_COST_RATE_ALERT):.0%}"
            )

        if gross_margin_rate is not None and gross_margin_rate < _GROSS_MARGIN_RATE_ALERT:
            alerts.append(
                f"综合毛利率 {float(gross_margin_rate):.1%} 低于阈值 {float(_GROSS_MARGIN_RATE_ALERT):.0%}"
            )

        if not alerts:
            return

        message = "；".join(alerts)
        log.warning(
            "daily_cost_report_anomaly_detected",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            report_date=report_date.isoformat(),
            alerts=alerts,
            food_cost_rate=str(food_cost_rate),
            gross_margin_rate=str(gross_margin_rate),
        )

        try:
            from ..agents.a4_budget_alert_agent import run as a4_run  # type: ignore[import]

            # A4 Agent 异步触发，失败不影响归集结果
            asyncio.create_task(
                a4_run(
                    tenant_id=str(tenant_id),
                    trigger="cost_anomaly",
                    payload={
                        "store_id": str(store_id),
                        "report_date": report_date.isoformat(),
                        "message": message,
                        "food_cost_rate": str(food_cost_rate),
                        "gross_margin_rate": str(gross_margin_rate),
                    },
                )
            )
        except ImportError:
            log.warning(
                "a4_agent_not_available",
                note="A4 agent not implemented; cost anomaly logged only.",
                message=message,
            )

    # ── 7. 单门店处理 ─────────────────────────────────────────────────────

    async def _process_store(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID,
        target_date: date,
    ) -> dict[str, Any]:
        """处理单个门店的成本归集。失败返回 error 结构，不向上抛出。"""
        try:
            # 并发拉取 POS 数据与查询费控申请
            pos_data, expenses = await asyncio.gather(
                self._fetch_pos_daily_close(store_id, target_date),
                self._get_approved_expenses(db, tenant_id, store_id, target_date),
                return_exceptions=False,
            )

            costs = self._aggregate_costs(expenses)

            report_id = await self._upsert_daily_report(
                db, tenant_id, store_id, target_date, pos_data, costs, expenses
            )
            await db.commit()

            # 计算用于预警的指标（重新算以确保一致）
            total_revenue = int((pos_data or {}).get("total_revenue_fen", 0))
            food_cost_rate: Optional[Decimal] = None
            gross_margin_rate: Optional[Decimal] = None
            if total_revenue > 0:
                rev = Decimal(total_revenue)
                food_cost_rate = Decimal(costs["food"]) / rev
                total_cost = costs["food"] + costs["labor"] + costs["other"]
                gross_margin_rate = Decimal(total_revenue - total_cost) / rev

            await self._trigger_cost_alert_if_needed(
                tenant_id, store_id, target_date, food_cost_rate, gross_margin_rate
            )

            log.info(
                "store_cost_attribution_complete",
                tenant_id=str(tenant_id),
                store_id=str(store_id),
                report_date=target_date.isoformat(),
                report_id=str(report_id),
                pos_data_available=pos_data is not None,
                expense_count=len(expenses),
                food_cost_fen=costs["food"],
                labor_cost_fen=costs["labor"],
                other_cost_fen=costs["other"],
            )
            return {
                "store_id": str(store_id),
                "report_id": str(report_id),
                "expense_count": len(expenses),
                "pos_data_available": pos_data is not None,
            }

        except Exception as exc:  # noqa: BLE001 — 外层兜底，保证其他门店继续处理
            await db.rollback()
            log.error(
                "store_cost_attribution_failed",
                tenant_id=str(tenant_id),
                store_id=str(store_id),
                report_date=target_date.isoformat(),
                error=str(exc),
                exc_info=True,
            )
            return {
                "store_id": str(store_id),
                "error": str(exc),
            }

    # ── 8. 主入口 ─────────────────────────────────────────────────────────

    async def run(self, target_date: date | None = None) -> dict[str, Any]:
        """多租户多门店成本归集批量处理主函数。

        Args:
            target_date: 归集日期，默认当日。

        Returns:
            {attribution_date, total_tenants, total_stores, success_count, errors}
        """
        attribution_date = target_date or date.today()
        started_at = datetime.now(timezone.utc)

        log.info(
            "daily_cost_attribution_worker_start",
            attribution_date=attribution_date.isoformat(),
        )

        results: dict[str, Any] = {
            "attribution_date": attribution_date.isoformat(),
            "total_tenants": 0,
            "total_stores": 0,
            "success_count": 0,
            "errors": [],
        }

        tenant_ids = await self._get_active_tenant_ids()
        if not tenant_ids:
            log.warning(
                "daily_cost_attribution_no_tenants_found",
                attribution_date=attribution_date.isoformat(),
            )
            return results

        for tenant_id_str in tenant_ids:
            try:
                tenant_id = UUID(tenant_id_str)
            except ValueError as exc:
                log.error(
                    "daily_cost_attribution_invalid_tenant_uuid",
                    tenant_id=tenant_id_str,
                    error=str(exc),
                    exc_info=True,
                )
                results["errors"].append({"tenant_id": tenant_id_str, "error": str(exc)})
                continue

            results["total_tenants"] += 1

            try:
                from shared.ontology.src.database import TenantSession

                async with TenantSession(tenant_id_str) as db:
                    store_ids = await self._get_store_ids(tenant_id, db)
                    for store_id in store_ids:
                        store_result = await self._process_store(db, tenant_id, store_id, attribution_date)
                        results["total_stores"] += 1
                        if "error" in store_result:
                            results["errors"].append({**store_result, "tenant_id": tenant_id_str})
                        else:
                            results["success_count"] += 1

            except Exception as exc:  # noqa: BLE001 — 外层兜底，保证其他租户继续
                log.error(
                    "tenant_cost_attribution_failed",
                    tenant_id=tenant_id_str,
                    attribution_date=attribution_date.isoformat(),
                    error=str(exc),
                    exc_info=True,
                )
                results["errors"].append({"tenant_id": tenant_id_str, "error": str(exc)})

        elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
        results["elapsed_seconds"] = round(elapsed, 2)

        log.info("daily_cost_attribution_worker_complete", **results)
        return results

    async def run_for_store(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        store_id: UUID,
        target_date: date | None = None,
    ) -> dict[str, Any]:
        """单门店成本归集（供 API 手动触发和单元测试使用）。

        Args:
            db: 已注入的 AsyncSession（由调用方管理事务）
            tenant_id: 租户 UUID
            store_id: 门店 UUID
            target_date: 归集日期，默认当日

        Returns:
            单门店归集结果 dict
        """
        attribution_date = target_date or date.today()
        return await self._process_store(db, tenant_id, store_id, attribution_date)


# ─────────────────────────────────────────────────────────────────────────────
# 模块级入口（供 APScheduler / Celery Beat 调用）
# ─────────────────────────────────────────────────────────────────────────────

async def run_daily_cost_attribution(target_date: date | None = None) -> dict[str, Any]:
    """模块级入口函数，供调度器直接调用。

    Args:
        target_date: 归集日期，默认当日。
    """
    worker = DailyCostAttributionWorker()
    return await worker.run(target_date=target_date)


if __name__ == "__main__":
    # 支持直接运行：python -m src.workers.daily_cost_attribution
    asyncio.run(run_daily_cost_attribution())
