#!/usr/bin/env python3
"""v150 历史数据回填脚本 — 为历史堂食订单创建 dining_sessions 记录

执行时机：v150 Alembic 迁移跑通后，业务低峰期（凌晨2-4点）执行。
幂等：重复执行安全，已有 dining_session_id 的订单不会重复处理。

用法：
    python -m scripts.migrate.v150_backfill_dining_sessions \
        --tenant-id <UUID> \
        --store-id  <UUID>      # 可选，省略则处理该租户所有门店
        --dry-run               # 只统计，不写入
        --batch-size 200
        --start-date 2025-01-01 # 从哪天开始回填
"""
from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import structlog

logger = structlog.get_logger()


async def backfill(
    tenant_id: uuid.UUID,
    store_id: Optional[uuid.UUID],
    dry_run: bool,
    batch_size: int,
    start_date: date,
) -> None:
    """主回填逻辑"""
    from shared.ontology.src.database import async_session_factory

    async with async_session_factory() as db:
        # 设置 RLS
        await db.execute(
            __import__("sqlalchemy").text(
                "SELECT set_config('app.tenant_id', :tid, true)"
            ),
            {"tid": str(tenant_id)},
        )
        from sqlalchemy import text

        # 1. 查询需要回填的门店列表
        if store_id:
            store_rows = [{"id": store_id, "store_code": "00"}]
        else:
            res = await db.execute(
                text("SELECT id, store_code FROM stores WHERE tenant_id = :tid AND is_deleted = FALSE"),
                {"tid": tenant_id},
            )
            store_rows = [dict(r) for r in res.mappings().all()]

        logger.info("backfill_start", tenant_id=str(tenant_id), stores=len(store_rows), dry_run=dry_run)

        total_sessions_created = 0
        total_orders_updated = 0

        for store in store_rows:
            sid = store["id"]
            store_code = (store.get("store_code") or "00")[:4]

            # 2. 按 (table_number, DATE(created_at)) 分组查出所有无 dining_session_id 的堂食订单
            res = await db.execute(
                text("""
                    SELECT
                        table_number,
                        DATE(created_at AT TIME ZONE 'UTC') AS order_date,
                        COUNT(*) AS order_count,
                        MIN(created_at) AS first_order_at,
                        MAX(created_at) AS last_order_at,
                        SUM(total_amount_fen) AS total_amount_fen,
                        SUM(final_amount_fen) AS final_amount_fen,
                        ARRAY_AGG(id ORDER BY created_at) AS order_ids,
                        MAX(waiter_id) AS waiter_id,
                        MAX(customer_id) AS vip_customer_id
                    FROM orders
                    WHERE tenant_id        = :tenant_id
                      AND store_id         = :store_id
                      AND sales_channel    = 'dine_in'
                      AND table_number     IS NOT NULL
                      AND table_number     != ''
                      AND dining_session_id IS NULL
                      AND is_deleted       = FALSE
                      AND DATE(created_at AT TIME ZONE 'UTC') >= :start_date
                    GROUP BY table_number, DATE(created_at AT TIME ZONE 'UTC')
                    ORDER BY order_date, table_number
                """),
                {"tenant_id": tenant_id, "store_id": sid, "start_date": start_date},
            )
            groups = [dict(r) for r in res.mappings().all()]

            logger.info("store_backfill", store_id=str(sid), groups=len(groups))

            for i, grp in enumerate(groups):
                table_number: str = grp["table_number"]
                order_date: date = grp["order_date"]
                order_ids: list[uuid.UUID] = grp["order_ids"]
                first_order_at: datetime = grp["first_order_at"]

                # 查找物理桌台ID（通过 table_no 匹配）
                t_res = await db.execute(
                    text("SELECT id, zone_id FROM tables WHERE store_id = :sid AND table_no = :no AND tenant_id = :tid LIMIT 1"),
                    {"sid": sid, "no": table_number, "tid": tenant_id},
                )
                table_info = t_res.mappings().one_or_none()
                table_id = table_info["id"] if table_info else None
                zone_id  = table_info["zone_id"] if table_info else None

                # 生成 session_no
                day_seq = i % 9999 + 1
                session_no = f"DS{store_code}{order_date.strftime('%Y%m%d')}{day_seq:04d}"

                # 估算状态：历史订单全部视为已清台
                # 估算结账时间 = 最后一笔订单时间 + 1小时（粗略）
                paid_at = grp["last_order_at"] + timedelta(hours=1)

                # 估算用餐时长（分钟）
                dining_minutes = int(
                    (paid_at - first_order_at).total_seconds() / 60
                ) if paid_at > first_order_at else 60

                session_id = uuid.uuid4()

                if dry_run:
                    logger.info(
                        "dry_run_would_create",
                        session_no=session_no,
                        table_number=table_number,
                        order_date=str(order_date),
                        order_count=grp["order_count"],
                        total_fen=grp["final_amount_fen"],
                    )
                else:
                    # 写入 dining_sessions
                    await db.execute(
                        text("""
                            INSERT INTO dining_sessions (
                                id, tenant_id, store_id, table_id,
                                session_no, guest_count,
                                vip_customer_id, status,
                                lead_waiter_id, zone_id, session_type,
                                opened_at, first_order_at, paid_at, cleared_at,
                                table_no_snapshot,
                                total_orders, total_amount_fen,
                                final_amount_fen, per_capita_fen,
                                room_config,
                                created_at, updated_at, is_deleted
                            ) VALUES (
                                :id, :tenant_id, :store_id, :table_id,
                                :session_no, 2,
                                :vip_customer_id, 'clearing',
                                :waiter_id, :zone_id, 'dine_in',
                                :opened_at, :first_order_at, :paid_at, :paid_at,
                                :table_no,
                                :total_orders, :total_amount_fen,
                                :final_amount_fen, 0,
                                '{}',
                                :now, :now, FALSE
                            )
                            ON CONFLICT DO NOTHING
                        """),
                        {
                            "id": session_id,
                            "tenant_id": tenant_id,
                            "store_id": sid,
                            "table_id": table_id,
                            "session_no": session_no,
                            "vip_customer_id": grp.get("vip_customer_id"),
                            "waiter_id": grp.get("waiter_id") or sid,
                            "zone_id": zone_id,
                            "opened_at": first_order_at,
                            "first_order_at": first_order_at,
                            "paid_at": paid_at,
                            "table_no": table_number,
                            "total_orders": grp["order_count"],
                            "total_amount_fen": grp["total_amount_fen"],
                            "final_amount_fen": grp["final_amount_fen"],
                            "now": datetime.now(timezone.utc),
                        },
                    )

                    # 更新所有关联订单
                    for seq, oid in enumerate(order_ids, start=1):
                        await db.execute(
                            text("""
                                UPDATE orders
                                SET dining_session_id = :dsid,
                                    order_sequence    = :seq,
                                    is_add_order      = :is_add,
                                    updated_at        = NOW()
                                WHERE id        = :oid
                                  AND tenant_id = :tid
                            """),
                            {
                                "dsid": session_id,
                                "seq": seq,
                                "is_add": seq > 1,
                                "oid": oid,
                                "tid": tenant_id,
                            },
                        )
                        total_orders_updated += 1

                    total_sessions_created += 1

                    # 每 batch_size 个会话提交一次
                    if total_sessions_created % batch_size == 0:
                        await db.commit()
                        logger.info(
                            "backfill_progress",
                            sessions=total_sessions_created,
                            orders=total_orders_updated,
                        )

        if not dry_run:
            await db.commit()

        logger.info(
            "backfill_complete",
            sessions_created=total_sessions_created,
            orders_updated=total_orders_updated,
            dry_run=dry_run,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="v150 历史堂食订单回填 dining_sessions")
    parser.add_argument("--tenant-id", required=True, help="租户UUID")
    parser.add_argument("--store-id",  default=None,  help="门店UUID（省略处理全部门店）")
    parser.add_argument("--dry-run",   action="store_true", help="仅统计不写入")
    parser.add_argument("--batch-size", type=int, default=200, help="每批提交数量")
    parser.add_argument("--start-date", default="2025-01-01", help="YYYY-MM-DD 从哪天开始")
    args = parser.parse_args()

    asyncio.run(backfill(
        tenant_id=uuid.UUID(args.tenant_id),
        store_id=uuid.UUID(args.store_id) if args.store_id else None,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        start_date=date.fromisoformat(args.start_date),
    ))


if __name__ == "__main__":
    main()
