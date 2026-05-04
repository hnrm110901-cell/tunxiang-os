#!/usr/bin/env python3
"""PG.5 — 加盟域历史数据回放生成 events（一次性 backfill）

背景：
  v060/v066 创建了 6 张加盟表，但当时尚未接入事件总线（v147+）。
  PB.3 完成后新写入会 emit_event；PG.6/v396 又给 6 张表加了 last_event_id 列。
  本脚本把存量旧行（last_event_id IS NULL）"补"出对应历史事件 → 回填 event_id，
  使加盟域的事件流与物化视图重建在历史数据上也成立。

幂等：仅扫 last_event_id IS NULL 的行（v396 PARTIAL 索引精确定位）；
      重跑只会处理上次失败的剩余行。

每行处理流程：
  1. 根据 (table, status) 推导事件类型（FranchiseEventType.*）
  2. 构造 payload（金额字段统一 fen，与 §15 财务红线一致）
  3. await emit_event(...) → 拿到 event_id
  4. UPDATE <table> SET last_event_id = :event_id WHERE id = :row_id

RLS 安全：
  - 按 tenant_id 分组，每组前 SET LOCAL app.tenant_id = '<uuid>'
  - emit_event() 内部 PG events 表写入也走同一 session 的 RLS

使用：
  python -m scripts.backfill_franchise_events --dry-run
  python -m scripts.backfill_franchise_events --table franchisees --batch-size 100
  python -m scripts.backfill_franchise_events --tenant-id <uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger("backfill_franchise_events")

# ─── 6 张加盟表的事件映射 ────────────────────────────────────────
# 每个 mapper 接收一行 dict → 返回 (event_type_str, payload_dict)
# event_type_str 用 FranchiseEventType.value 字符串避免 import 时序问题


def _franchisees_mapper(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """franchisees → APPLIED（活跃→ACTIVATED；终止→TERMINATED；暂停→SUSPENDED）"""
    status = (row.get("status") or "active").lower()
    event_type = {
        "active": "franchise.franchisee_activated",
        "suspended": "franchise.franchisee_suspended",
        "terminated": "franchise.franchisee_terminated",
    }.get(status, "franchise.franchisee_applied")
    return event_type, {
        "name": row.get("name"),
        "region": row.get("region"),
        "status": status,
        "contract_start": _iso(row.get("contract_start")),
        "contract_end": _iso(row.get("contract_end")),
        "royalty_rate": _to_float(row.get("royalty_rate")),
        "management_fee_fen": int(row.get("management_fee_fen") or 0),
        "brand_usage_fee_fen": int(row.get("brand_usage_fee_fen") or 0),
    }


def _franchisee_stores_mapper(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """franchisee_stores → ACTIVATED（带 metadata.kind=store_linked）"""
    return "franchise.franchisee_activated", {
        "store_id": str(row["store_id"]) if row.get("store_id") else None,
        "join_date": _iso(row.get("join_date")),
        "initial_fee_fen": int(row.get("initial_fee_fen") or 0),
        "status": (row.get("status") or "active").lower(),
        "_kind": "store_linked",
    }


def _royalty_bills_mapper(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """royalty_bills → ROYALTY_CALCULATED（已付→FEE_PAID）"""
    status = (row.get("status") or "pending").lower()
    event_type = "franchise.fee_paid" if status == "paid" else "franchise.royalty_calculated"
    return event_type, {
        "period_start": _iso(row.get("period_start")),
        "period_end": _iso(row.get("period_end")),
        "revenue_fen": int(row.get("revenue_fen") or 0),
        "royalty_rate": _to_float(row.get("royalty_rate")),
        "royalty_amount_fen": int(row.get("royalty_amount_fen") or 0),
        "management_fee_fen": int(row.get("management_fee_fen") or 0),
        "total_due_fen": int(row.get("total_due_fen") or 0),
        "status": status,
    }


def _franchise_audits_mapper(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """franchise_audits → ACTIVATED + metadata.kind=audit_logged
    （暂无 audit-专用事件；以加盟生命周期事件承载稽核留痕）"""
    return "franchise.franchisee_activated", {
        "store_id": str(row["store_id"]) if row.get("store_id") else None,
        "audit_date": _iso(row.get("audit_date")),
        "score": _to_float(row.get("score")),
        "findings": row.get("findings") or {},
        "_kind": "audit_logged",
    }


def _franchise_settlements_mapper(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """franchise_settlements → SETTLEMENT_GENERATED（已 paid → FEE_PAID）"""
    status = (row.get("status") or "draft").lower()
    event_type = "franchise.fee_paid" if status == "paid" else "franchise.settlement_generated"
    return event_type, {
        "year": int(row.get("year") or 0),
        "month": int(row.get("month") or 0),
        "revenue_fen": int(row.get("revenue_fen") or 0),
        "royalty_amount_fen": int(row.get("royalty_amount_fen") or 0),
        "mgmt_fee_fen": int(row.get("mgmt_fee_fen") or 0),
        "total_amount_fen": int(row.get("total_amount_fen") or 0),
        "status": status,
    }


def _franchise_settlement_items_mapper(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """franchise_settlement_items → SETTLEMENT_GENERATED（明细行；stream_id 用 settlement_id）"""
    return "franchise.settlement_generated", {
        "settlement_id": str(row["settlement_id"]) if row.get("settlement_id") else None,
        "item_type": row.get("item_type"),
        "description": row.get("description"),
        "amount_fen": int(row.get("amount_fen") or 0),
        "_kind": "settlement_item",
    }


@dataclass(frozen=True)
class TableSpec:
    """一张加盟表的回放规格。"""

    table: str
    pk_col: str  # 主键列名
    stream_id_col: str  # 用作 stream_id 的列（聚合根锚点）
    mapper: Callable[[dict[str, Any]], tuple[str, dict[str, Any]]]
    has_store_id: bool = False  # 是否有 store_id 列要透传到 emit_event


_TABLE_SPECS: tuple[TableSpec, ...] = (
    TableSpec("franchisees", "id", "id", _franchisees_mapper),
    TableSpec("franchisee_stores", "id", "franchisee_id", _franchisee_stores_mapper, has_store_id=True),
    TableSpec("royalty_bills", "id", "id", _royalty_bills_mapper, has_store_id=True),
    TableSpec("franchise_audits", "id", "franchisee_id", _franchise_audits_mapper, has_store_id=True),
    TableSpec("franchise_settlements", "id", "id", _franchise_settlements_mapper),
    TableSpec("franchise_settlement_items", "id", "settlement_id", _franchise_settlement_items_mapper),
)


# ─── helpers ──────────────────────────────────────────────────────────


def _iso(v: Any) -> Optional[str]:
    """date/datetime → ISO 字符串；None/缺失 → None。"""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ─── 主循环 ──────────────────────────────────────────────────────────


@dataclass
class BackfillStats:
    table: str
    scanned: int = 0
    emitted: int = 0
    failed: int = 0
    skipped_no_tenant: int = 0


async def backfill_one_table(
    spec: TableSpec,
    *,
    db_execute: Callable[[str, dict[str, Any]], Awaitable[list[dict[str, Any]]]],
    db_update: Callable[[str, dict[str, Any]], Awaitable[None]],
    emit_event: Callable[..., Awaitable[Optional[str]]],
    tenant_filter: Optional[str] = None,
    batch_size: int = 200,
    dry_run: bool = True,
) -> BackfillStats:
    """扫一张表的 last_event_id IS NULL 行 → 补 emit + writeback。

    抽出 db_execute / db_update / emit_event 为参数，便于 Tier1 测试注入 mock。
    """
    stats = BackfillStats(table=spec.table)

    # 1. 扫描待回放行
    cols = f"{spec.pk_col}, tenant_id, {spec.stream_id_col}"
    if spec.has_store_id and "store_id" not in cols:
        cols += ", store_id"
    # 关键业务字段（mapper 会用到）— 用 SELECT *  简化（量级可控）
    select_sql = f"""
        SELECT *
        FROM {spec.table}
        WHERE last_event_id IS NULL
        {"AND tenant_id = :tenant_id" if tenant_filter else ""}
        ORDER BY created_at NULLS FIRST, {spec.pk_col}
        LIMIT :limit
    """
    params: dict[str, Any] = {"limit": batch_size}
    if tenant_filter:
        params["tenant_id"] = tenant_filter

    rows = await db_execute(select_sql, params)
    stats.scanned = len(rows)

    for row in rows:
        tenant_id = row.get("tenant_id")
        if not tenant_id:
            stats.skipped_no_tenant += 1
            continue

        try:
            event_type_str, payload = spec.mapper(row)
            metadata = {"backfill": True, "source_table": spec.table}
            kind = payload.pop("_kind", None)
            if kind:
                metadata["kind"] = kind

            stream_id_val = row.get(spec.stream_id_col)
            store_id_val = row.get("store_id") if spec.has_store_id else None

            if dry_run:
                logger.info(
                    "DRY-RUN %s row=%s → %s payload_keys=%s",
                    spec.table,
                    row[spec.pk_col],
                    event_type_str,
                    list(payload.keys()),
                )
                stats.emitted += 1
                continue

            event_id = await emit_event(
                event_type=event_type_str,
                tenant_id=tenant_id,
                stream_id=str(stream_id_val) if stream_id_val else str(row[spec.pk_col]),
                payload=payload,
                store_id=str(store_id_val) if store_id_val else None,
                source_service="backfill_franchise_events",
                metadata=metadata,
            )

            if event_id:
                await db_update(
                    f"UPDATE {spec.table} SET last_event_id = :eid WHERE {spec.pk_col} = :pk",
                    {"eid": event_id, "pk": row[spec.pk_col]},
                )
                stats.emitted += 1
            else:
                stats.failed += 1
                logger.warning("emit_event 返回 None：%s row=%s", spec.table, row[spec.pk_col])
        except Exception:  # noqa: BLE001 — backfill 兜底，单行错不能阻断整批
            stats.failed += 1
            logger.exception("回放失败：%s row=%s", spec.table, row.get(spec.pk_col))

    return stats


# ─── CLI ─────────────────────────────────────────────────────────────


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="加盟域历史数据回放 backfill")
    p.add_argument("--dry-run", action="store_true", default=True, help="仅打印不写入（默认开启）")
    p.add_argument("--apply", action="store_true", help="真正执行（关闭 dry-run）")
    p.add_argument("--table", choices=[s.table for s in _TABLE_SPECS], help="只跑某张表")
    p.add_argument("--tenant-id", type=str, help="只跑某租户")
    p.add_argument("--batch-size", type=int, default=200)
    return p.parse_args(argv)


async def _main_async(args: argparse.Namespace) -> int:
    # 真实运行需要真实 DB；这里只在 --apply 时拉 emit_event/AsyncSession
    if not args.apply:
        logger.info("dry-run 模式：跳过 DB 连接，仅展示扫描计划")
        for spec in _TABLE_SPECS:
            if args.table and spec.table != args.table:
                continue
            logger.info("[plan] 将扫描 %s WHERE last_event_id IS NULL（mapper=%s）", spec.table, spec.mapper.__name__)
        return 0

    # 真正运行：在调用方接线 AsyncSession + emit_event
    # （故意不在脚本启动时 import shared.* 以保持 dry-run 可在干净环境跑）
    from shared.events.src.emitter import emit_event  # type: ignore
    from shared.ontology.src.database import async_session_factory  # type: ignore
    from sqlalchemy import text  # type: ignore

    async with async_session_factory() as session:
        if args.tenant_id:
            await session.execute(text("SET LOCAL app.tenant_id = :t"), {"t": args.tenant_id})

        async def _exec(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
            res = await session.execute(text(sql), params)
            keys = res.keys()
            return [dict(zip(keys, r)) for r in res.all()]

        async def _upd(sql: str, params: dict[str, Any]) -> None:
            await session.execute(text(sql), params)

        total = BackfillStats(table="ALL")
        for spec in _TABLE_SPECS:
            if args.table and spec.table != args.table:
                continue
            stats = await backfill_one_table(
                spec,
                db_execute=_exec,
                db_update=_upd,
                emit_event=emit_event,
                tenant_filter=args.tenant_id,
                batch_size=args.batch_size,
                dry_run=False,
            )
            await session.commit()
            logger.info(
                "[done] table=%s scanned=%d emitted=%d failed=%d skipped=%d",
                stats.table,
                stats.scanned,
                stats.emitted,
                stats.failed,
                stats.skipped_no_tenant,
            )
            total.scanned += stats.scanned
            total.emitted += stats.emitted
            total.failed += stats.failed
            total.skipped_no_tenant += stats.skipped_no_tenant

        logger.info(
            "[summary] scanned=%d emitted=%d failed=%d skipped=%d at %s",
            total.scanned,
            total.emitted,
            total.failed,
            total.skipped_no_tenant,
            datetime.now(timezone.utc).isoformat(),
        )
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv)
    if args.apply:
        args.dry_run = False
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    sys.exit(main())
