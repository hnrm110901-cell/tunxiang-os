"""KDS 桌台维度出餐视图 — 按堂食会话聚合，按优先级排序 (v149)

现有 KDS 按档口/工位维度展示任务列表。
本模块新增桌台会话维度的聚合视图，解决：
  1. 同桌多轮点菜（主单+加菜单）需整合显示
  2. 包间、VIP桌应有更高出餐优先级
  3. 催菜次数多的桌台应排在前面
  4. 前厅服务员按桌查出餐进度

优先级公式（0-100分）：
  = VIP权重(0-30) + 等待时长权重(0-25) + 催菜次数权重(0-25) + 桌台类型权重(0-20)

所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

router = APIRouter(prefix="/api/v1/kds/sessions", tags=["kds-sessions"])


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return str(tid)


def _ok(data: dict | list) -> dict:
    return {"ok": True, "data": data, "error": None}


@router.get("/board", summary="KDS桌台出餐看板（按会话优先级排序）")
async def get_kds_session_board(
    store_id: uuid.UUID = Query(..., description="门店ID"),
    dept_id: Optional[uuid.UUID] = Query(default=None, description="档口ID（为空则返回全档口汇总）"),
    request: Request = ...,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    KDS 桌台维度出餐看板。

    每行代表一个活跃堂食会话（一张桌台），包含：
    - 该桌所有未完成菜品清单（跨多张订单合并）
    - 综合出餐优先级评分（VIP + 等待时长 + 催菜次数 + 桌台类型）
    - 各档口出餐进度百分比

    用于：前厅经理/传菜员全局出餐监控，代替"只看某档口"的孤立视角。
    """
    tid = _get_tenant_id(request)

    dept_filter = "AND kt.dept_id = :dept_id" if dept_id else ""
    params: dict = {"store_id": store_id, "tenant_id": tid}
    if dept_id:
        params["dept_id"] = dept_id

    result = await db.execute(
        text(f"""
            WITH session_kds AS (
                -- 聚合：每个会话的 KDS 任务汇总
                SELECT
                    ds.id                                AS session_id,
                    ds.session_no,
                    ds.table_no_snapshot                 AS table_no,
                    ds.guest_count,
                    ds.opened_at,
                    ds.vip_customer_id,
                    ds.session_type,
                    ds.service_call_count,
                    -- KDS 任务汇总
                    COUNT(kt.id)                         AS total_tasks,
                    COUNT(kt.id) FILTER (WHERE kt.status = 'done')     AS done_tasks,
                    COUNT(kt.id) FILTER (WHERE kt.status = 'cooking')  AS cooking_tasks,
                    COUNT(kt.id) FILTER (WHERE kt.status = 'pending')  AS pending_tasks,
                    -- 最早未完成任务的创建时间（决定等待时长权重）
                    MIN(kt.created_at) FILTER (WHERE kt.status != 'done') AS oldest_pending_at,
                    -- 是否有催菜标记
                    COUNT(kt.id) FILTER (WHERE kt.is_rushed = TRUE AND kt.status != 'done') AS rush_count
                FROM dining_sessions ds
                JOIN orders o         ON o.dining_session_id = ds.id
                                     AND o.tenant_id = ds.tenant_id
                                     AND o.is_deleted = FALSE
                JOIN kds_tasks kt     ON kt.order_id = o.id
                                     AND kt.tenant_id = ds.tenant_id
                                     {dept_filter}
                WHERE ds.store_id  = :store_id
                  AND ds.tenant_id = :tenant_id
                  AND ds.status NOT IN ('paid', 'clearing', 'disabled')
                  AND ds.is_deleted = FALSE
                GROUP BY ds.id, ds.session_no, ds.table_no_snapshot,
                         ds.guest_count, ds.opened_at, ds.vip_customer_id,
                         ds.session_type, ds.service_call_count
            ),
            prioritized AS (
                SELECT *,
                    -- 优先级评分（0-100）
                    LEAST(100,
                        -- VIP权重：有VIP顾客 +30
                        (CASE WHEN vip_customer_id IS NOT NULL THEN 30 ELSE 0 END)
                        -- 等待时长权重：每10分钟+5，最高25
                        + LEAST(25, GREATEST(0,
                            EXTRACT(EPOCH FROM (NOW() - COALESCE(oldest_pending_at, opened_at))) / 600 * 5
                          )::INT)
                        -- 催菜权重：每次催菜+8，最高25
                        + LEAST(25, rush_count * 8)
                        -- 桌台类型：vip_room/banquet +20，普通 +0
                        + (CASE WHEN session_type IN ('vip_room', 'banquet') THEN 20 ELSE 0 END)
                    ) AS priority_score
                FROM session_kds
                WHERE total_tasks > done_tasks  -- 只显示有未完成任务的桌台
            )
            SELECT
                p.*,
                ROUND((done_tasks::NUMERIC / NULLIF(total_tasks, 0)) * 100, 0) AS completion_pct,
                EXTRACT(EPOCH FROM (NOW() - oldest_pending_at)) / 60 AS wait_minutes
            FROM prioritized p
            ORDER BY priority_score DESC, oldest_pending_at ASC NULLS LAST
        """),
        params,
    )
    sessions = [dict(r) for r in result.mappings().all()]
    return _ok({"sessions": sessions, "total": len(sessions)})


@router.get("/{session_id}/dishes", summary="桌台会话出餐明细")
async def get_session_dish_progress(
    session_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    获取某桌台会话的出餐明细（合并所有轮次订单）。

    每道菜显示：菜名、数量、档口、状态、下单时间、是否催菜。
    用于：服务员查询"这桌还有哪些菜没上"，传菜员核对出餐。
    """
    tid = _get_tenant_id(request)

    result = await db.execute(
        text("""
            SELECT
                kt.id          AS task_id,
                kt.status      AS kds_status,
                kt.is_rushed,
                kt.created_at  AS ordered_at,
                kt.cooking_started_at,
                kt.done_at,
                oi.item_name,
                oi.quantity,
                oi.notes,
                o.order_no,
                o.order_sequence,
                o.is_add_order,
                pd.dept_name   AS station_name,
                pd.dept_code   AS station_code,
                -- 等待分钟数（仅未完成任务）
                CASE WHEN kt.status != 'done'
                     THEN EXTRACT(EPOCH FROM (NOW() - kt.created_at)) / 60
                     ELSE NULL
                END AS wait_minutes
            FROM dining_sessions ds
            JOIN orders      o  ON o.dining_session_id = ds.id
                                AND o.tenant_id = :tenant_id
                                AND o.is_deleted = FALSE
            JOIN order_items oi ON oi.order_id = o.id
                                AND oi.tenant_id = :tenant_id
            JOIN kds_tasks   kt ON kt.order_id = o.id
                                AND kt.order_item_id = oi.id
                                AND kt.tenant_id = :tenant_id
            LEFT JOIN production_depts pd ON pd.id = kt.dept_id
            WHERE ds.id        = :session_id
              AND ds.tenant_id = :tenant_id
              AND ds.is_deleted = FALSE
            ORDER BY
                kt.status,               -- pending → cooking → done
                o.order_sequence,        -- 主单先于加菜单
                kt.created_at
        """),
        {"session_id": session_id, "tenant_id": tid},
    )
    dishes = [dict(r) for r in result.mappings().all()]

    # 汇总
    total = len(dishes)
    done = sum(1 for d in dishes if d["kds_status"] == "done")
    rushed = sum(1 for d in dishes if d["is_rushed"] and d["kds_status"] != "done")

    return _ok(
        {
            "session_id": str(session_id),
            "dishes": dishes,
            "summary": {
                "total": total,
                "done": done,
                "pending": total - done,
                "completion_pct": round(done / total * 100) if total else 0,
                "has_rush": rushed > 0,
                "rush_count": rushed,
            },
        }
    )


@router.post("/{session_id}/rush-all-pending", summary="催全桌未完成菜品")
async def rush_all_pending_for_session(
    session_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    一键催全桌所有未完成菜品（设置 is_rushed=TRUE）。

    通常由服务员在顾客多次催菜后操作，同时创建一条 service_call 记录。
    """
    tid = _get_tenant_id(request)
    now = datetime.now(timezone.utc)

    # 将该会话所有 pending/cooking 任务标记为 is_rushed
    result = await db.execute(
        text("""
            UPDATE kds_tasks kt
            SET is_rushed = TRUE,
                updated_at = :now
            FROM orders o
            WHERE kt.order_id  = o.id
              AND o.dining_session_id = :session_id
              AND o.tenant_id  = :tenant_id
              AND kt.status NOT IN ('done', 'cancelled')
              AND kt.tenant_id = :tenant_id
            RETURNING kt.id
        """),
        {"session_id": session_id, "tenant_id": tid, "now": now},
    )
    rushed_ids = [str(r["id"]) for r in result.mappings().all()]

    # 同步创建 service_call 记录（类型=urge_dish）
    if rushed_ids:
        # 获取 store_id
        store_row = await db.execute(
            text("SELECT store_id FROM dining_sessions WHERE id = :sid AND tenant_id = :tid"),
            {"sid": session_id, "tid": tid},
        )
        store = store_row.mappings().one_or_none()
        if store:
            await db.execute(
                text("""
                    INSERT INTO service_calls
                        (id, tenant_id, store_id, table_session_id,
                         call_type, content, status, called_by, called_at, created_at, updated_at)
                    VALUES
                        (gen_random_uuid(), :tenant_id, :store_id, :session_id,
                         'urge_dish', '催全桌菜品', 'pending', 'pos', :now, :now, :now)
                """),
                {
                    "tenant_id": tid,
                    "store_id": store["store_id"],
                    "session_id": session_id,
                    "now": now,
                },
            )

    return _ok({"rushed_count": len(rushed_ids), "task_ids": rushed_ids})
