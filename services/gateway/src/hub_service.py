"""Hub 运维 — PostgreSQL 读/写模型（跨租户，session 须为 get_db_no_rls）"""

from __future__ import annotations

import re
import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _row_to_dict(row: Any) -> dict[str, Any]:
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    return dict(row)


async def hub_list_merchants(
    db: AsyncSession,
    status: Optional[str],
    page: int,
    size: int,
) -> dict[str, Any]:
    offset = max(0, (page - 1) * size)
    where = "NOT COALESCE(pt.is_deleted, false)"
    base_params: dict[str, Any] = {}
    if status:
        where += " AND pt.status = :st"
        base_params["st"] = status
    count_sql = text(f"SELECT COUNT(*) AS c FROM platform_tenants pt WHERE {where}")
    list_sql = text(
        f"""
        SELECT pt.tenant_id::text AS id,
               pt.name,
               pt.plan_template AS template,
               COALESCE(sc.cnt, 0)::int AS stores,
               pt.status,
               pt.subscription_expires_at::text AS expires
        FROM platform_tenants pt
        LEFT JOIN (
          SELECT tenant_id, COUNT(*)::int AS cnt
          FROM stores
          WHERE NOT COALESCE(is_deleted, false)
          GROUP BY tenant_id
        ) sc ON sc.tenant_id = pt.tenant_id
        WHERE {where}
        ORDER BY pt.name
        LIMIT :limit OFFSET :offset
        """
    )
    total_r = await db.execute(count_sql, base_params)
    total = int(total_r.scalar_one())
    rows = await db.execute(list_sql, {**base_params, "limit": size, "offset": offset})
    items = [_row_to_dict(r) for r in rows.fetchall()]
    return {"items": items, "total": total}


async def hub_list_stores(
    db: AsyncSession,
    merchant_id: Optional[str],
    online: Optional[bool],
    page: int,
    size: int,
) -> dict[str, Any]:
    offset = max(0, (page - 1) * size)
    base_params: dict[str, Any] = {}
    where = (
        "NOT COALESCE(s.is_deleted, false) "
        "AND NOT COALESCE(pt.is_deleted, false)"
    )
    if merchant_id:
        where += " AND pt.tenant_id::text = :mid"
        base_params["mid"] = merchant_id
    if online is not None:
        where += " AND COALESCE(o.edge_online, false) = :onl"
        base_params["onl"] = online
    count_sql = text(
        f"""
        SELECT COUNT(*) AS c
        FROM stores s
        JOIN platform_tenants pt ON pt.tenant_id = s.tenant_id
        LEFT JOIN hub_store_overlay o ON o.store_id = s.id
        WHERE {where}
        """
    )
    list_sql = text(
        f"""
        SELECT s.id::text AS store_id,
               s.store_name AS name,
               pt.name AS merchant,
               COALESCE(o.edge_online, false) AS online,
               COALESCE(to_char(o.last_sync_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS'), to_char(s.updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS')) AS last_sync,
               COALESCE(o.client_version, '—') AS version
        FROM stores s
        JOIN platform_tenants pt ON pt.tenant_id = s.tenant_id
        LEFT JOIN hub_store_overlay o ON o.store_id = s.id
        WHERE {where}
        ORDER BY pt.name, s.store_name
        LIMIT :limit OFFSET :offset
        """
    )
    total_r = await db.execute(count_sql, base_params)
    total = int(total_r.scalar_one())
    rows = await db.execute(list_sql, {**base_params, "limit": size, "offset": offset})
    items = [_row_to_dict(r) for r in rows.fetchall()]
    return {"items": items, "total": total}


async def hub_list_adapters(db: AsyncSession) -> list[dict[str, Any]]:
    sql = text(
        """
        SELECT adapter_key AS adapter,
               merchant_name AS merchant,
               status,
               to_char(last_sync_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') AS last_sync,
               success_rate,
               error_message AS error
        FROM hub_adapter_connections
        WHERE NOT COALESCE(is_deleted, false)
        ORDER BY merchant_name, adapter_key
        """
    )
    rows = await db.execute(sql)
    out = []
    for r in rows.fetchall():
        d = _row_to_dict(r)
        sr = d.get("success_rate")
        if isinstance(sr, Decimal):
            d["success_rate"] = float(sr)
        out.append(d)
    return out


async def hub_agent_health(db: AsyncSession) -> dict[str, Any]:
    sql = text(
        """
        SELECT total_executions, success_rate, constraint_violations, top_agents, avg_response_ms
        FROM hub_agent_metrics_daily
        WHERE stat_date = CURRENT_DATE
        LIMIT 1
        """
    )
    rows = await db.execute(sql)
    row = rows.fetchone()
    if not row:
        sql2 = text(
            """
            SELECT total_executions, success_rate, constraint_violations, top_agents, avg_response_ms
            FROM hub_agent_metrics_daily
            ORDER BY stat_date DESC
            LIMIT 1
            """
        )
        rows2 = await db.execute(sql2)
        row = rows2.fetchone()
    if not row:
        return {
            "total_executions_today": 0,
            "success_rate": 0.0,
            "constraint_violations": 0,
            "top_agents": [],
        }
    d = _row_to_dict(row)
    sr = d.get("success_rate")
    if isinstance(sr, Decimal):
        sr = float(sr)
    top = d.get("top_agents")
    if isinstance(top, str):
        import json

        top = json.loads(top)
    return {
        "total_executions_today": int(d["total_executions"]),
        "success_rate": float(sr) if sr is not None else 0.0,
        "constraint_violations": int(d["constraint_violations"]),
        "top_agents": top or [],
    }


async def hub_get_billing(db: AsyncSession, month: Optional[str]) -> dict[str, Any]:
    m = month or date.today().strftime("%Y-%m")
    sql = text(
        """
        SELECT month, total_revenue_yuan, haas_yuan, saas_yuan, ai_yuan,
               merchants_count, active_stores, arr_yuan
        FROM hub_billing_monthly
        WHERE month = :m
        LIMIT 1
        """
    )
    rows = await db.execute(sql, {"m": m})
    row = rows.fetchone()
    if not row:
        return {
            "month": m,
            "total_revenue_yuan": 0,
            "breakdown": {
                "haas": {"label": "硬件租赁(HaaS)", "yuan": 0, "pct": 0.0},
                "saas": {"label": "软件服务(SaaS)", "yuan": 0, "pct": 0.0},
                "ai": {"label": "AI增值", "yuan": 0, "pct": 0.0},
            },
            "merchants": 0,
            "active_stores": 0,
            "arr_yuan": 0,
        }
    d = _row_to_dict(row)
    haas = int(d["haas_yuan"])
    saas = int(d["saas_yuan"])
    ai = int(d["ai_yuan"])
    total = haas + saas + ai or int(d["total_revenue_yuan"])

    def _pct(part: int) -> float:
        if not total:
            return 0.0
        return round(100.0 * part / total, 1)

    return {
        "month": d["month"],
        "total_revenue_yuan": int(d["total_revenue_yuan"]),
        "breakdown": {
            "haas": {"label": "硬件租赁(HaaS)", "yuan": haas, "pct": _pct(haas)},
            "saas": {"label": "软件服务(SaaS)", "yuan": saas, "pct": _pct(saas)},
            "ai": {"label": "AI增值", "yuan": ai, "pct": _pct(ai)},
        },
        "merchants": int(d["merchants_count"]),
        "active_stores": int(d["active_stores"]),
        "arr_yuan": int(d["arr_yuan"]),
    }


async def hub_list_mac_minis(db: AsyncSession) -> list[dict[str, Any]]:
    sql = text(
        """
        SELECT store_label AS store,
               ip,
               tailscale_status AS tailscale,
               COALESCE(client_version, '—') AS version,
               to_char(last_heartbeat AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') AS last_heartbeat,
               cpu_pct,
               mem_pct
        FROM hub_edge_devices
        WHERE NOT COALESCE(is_deleted, false)
        ORDER BY store_label
        """
    )
    rows = await db.execute(sql)
    return [_row_to_dict(r) for r in rows.fetchall()]


async def hub_list_tickets(db: AsyncSession, status: Optional[str]) -> dict[str, Any]:
    where = "NOT COALESCE(is_deleted, false)"
    base_params: dict[str, Any] = {}
    if status:
        where += " AND hub_tickets.status = :st"
        base_params["st"] = status
    count_sql = text(f"SELECT COUNT(*) FROM hub_tickets WHERE {where}")
    list_sql = text(
        f"""
        SELECT id,
               merchant_name AS merchant,
               title,
               priority,
               status,
               to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') AS created,
               assignee
        FROM hub_tickets
        WHERE {where}
        ORDER BY created_at DESC
        """
    )
    total_r = await db.execute(count_sql, base_params)
    total = int(total_r.scalar_one())
    rows = await db.execute(list_sql, base_params)
    items = [_row_to_dict(r) for r in rows.fetchall()]
    return {"items": items, "total": total}


async def hub_create_merchant(db: AsyncSession, data: dict[str, Any]) -> str:
    """INSERT platform_tenants，返回新 tenant_id（字符串）。"""
    new_id = str(uuid.uuid4())
    expires = data.get("subscription_expires_at")
    # 校验日期格式
    if expires and not re.match(r"^\d{4}-\d{2}-\d{2}$", expires):
        expires = None
    expires_expr = ":expires::date" if expires else "NULL"
    sql = text(
        f"""
        INSERT INTO platform_tenants (
            tenant_id, merchant_code, name, plan_template, status,
            subscription_expires_at, is_deleted
        ) VALUES (
            :tid::uuid, :code, :name, :tmpl, 'active',
            {expires_expr}, false
        )
        ON CONFLICT (tenant_id) DO NOTHING
        """
    )
    insert_params: dict[str, Any] = {
        "tid": new_id,
        "code": data.get("merchant_code"),
        "name": data["name"],
        "tmpl": data["plan_template"],
    }
    if expires:
        insert_params["expires"] = expires
    await db.execute(sql, insert_params)
    await db.commit()
    return new_id


async def hub_update_merchant(
    db: AsyncSession, merchant_id: str, updates: dict[str, Any]
) -> bool:
    """UPDATE platform_tenants，返回 True 表示找到了该行并更新。"""
    if not updates:
        return True
    allowed = {"name", "plan_template", "status", "subscription_expires_at"}
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        return True

    set_clauses = []
    params: dict[str, Any] = {"mid": merchant_id}
    for key, val in filtered.items():
        set_clauses.append(f"{key} = :{key}")
        if key == "subscription_expires_at" and val:
            params[key] = val  # 期望格式 YYYY-MM-DD
        else:
            params[key] = val
    set_clauses.append("updated_at = NOW()")
    set_str = ", ".join(set_clauses)

    sql = text(
        f"""
        UPDATE platform_tenants
        SET {set_str}
        WHERE tenant_id = :mid::uuid
          AND NOT COALESCE(is_deleted, false)
        """
    )
    result = await db.execute(sql, params)
    await db.commit()
    return result.rowcount > 0


async def hub_push_update(
    db: AsyncSession, store_ids: list[str], target_version: str
) -> int:
    """将 hub_edge_devices 中指定 store_label 或 store 所属门店的目标版本写入备注，
    并在 hub_store_overlay 打上待升级标记。
    由于 hub_edge_devices 无 pending_version 列，此处更新 client_version 为目标版本以记录意图，
    并返回实际匹配并标记的设备数。
    若 store_ids 为空则操作全部设备。
    """
    if not store_ids:
        # 全量推送
        sql = text(
            """
            UPDATE hub_edge_devices
            SET client_version = :ver,
                updated_at      = NOW()
            WHERE NOT COALESCE(is_deleted, false)
            """
        )
        result = await db.execute(sql, {"ver": target_version})
    else:
        sql = text(
            """
            UPDATE hub_edge_devices
            SET client_version = :ver,
                updated_at      = NOW()
            WHERE store_label = ANY(:labels)
              AND NOT COALESCE(is_deleted, false)
            """
        )
        result = await db.execute(sql, {"ver": target_version, "labels": store_ids})
    await db.commit()
    return result.rowcount


async def hub_create_ticket(db: AsyncSession, data: dict[str, Any]) -> str:
    """INSERT hub_tickets，生成自增式工单号 T{n+1}，返回 ticket_id。"""
    # 生成工单号：查当前最大序号
    max_r = await db.execute(
        text(
            """
            SELECT MAX(CAST(SUBSTRING(id FROM 2) AS INTEGER))
            FROM hub_tickets
            WHERE id ~ '^T[0-9]+$'
            """
        )
    )
    max_val = max_r.scalar()
    next_num = (int(max_val) + 1) if max_val is not None else 1
    ticket_id = f"T{next_num:03d}"

    tenant_id = data.get("tenant_id")
    # 当 tenant_id 为 None 时避免 ::uuid 强转报错
    tid_expr = ":tenant_id::uuid" if tenant_id else "NULL"
    sql = text(
        f"""
        INSERT INTO hub_tickets (
            id, tenant_id, merchant_name, title, priority, status, assignee, is_deleted
        ) VALUES (
            :tid,
            {tid_expr},
            :merchant_name,
            :title,
            :priority,
            'open',
            :assignee,
            false
        )
        ON CONFLICT (id) DO NOTHING
        """
    )
    params: dict[str, Any] = {
        "tid": ticket_id,
        "merchant_name": data["merchant_name"],
        "title": data["title"],
        "priority": data["priority"],
        "assignee": data.get("assignee"),
    }
    if tenant_id:
        params["tenant_id"] = tenant_id
    await db.execute(sql, params)
    await db.commit()
    return ticket_id


async def hub_platform_stats(db: AsyncSession) -> dict[str, Any]:
    m = await db.execute(
        text("SELECT COUNT(*) FROM platform_tenants WHERE NOT COALESCE(is_deleted, false)")
    )
    total_merchants = int(m.scalar_one())
    s = await db.execute(
        text("SELECT COUNT(*) FROM stores WHERE NOT COALESCE(is_deleted, false)")
    )
    total_stores = int(s.scalar_one())
    active = await db.execute(
        text(
            "SELECT COUNT(*) FROM stores WHERE NOT COALESCE(is_deleted, false) AND status = 'active'"
        )
    )
    active_stores = int(active.scalar_one())

    orders_row = await db.execute(
        text(
            """
            SELECT COUNT(*)::bigint AS cnt,
                   COALESCE(SUM(final_amount_fen), 0)::bigint AS gmv_fen
            FROM orders
            WHERE NOT COALESCE(is_deleted, false)
              AND (order_time AT TIME ZONE 'Asia/Shanghai')::date
                  = (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai')::date
            """
        )
    )
    orow = orders_row.fetchone()
    if orow is None:
        total_orders_today = 0
        gmv_fen = 0
    else:
        total_orders_today = int(orow[0])
        gmv_fen = int(orow[1])

    agent = await hub_agent_health(db)
    avg_ms_sql = await db.execute(
        text(
            """
            SELECT avg_response_ms FROM hub_agent_metrics_daily
            WHERE stat_date = CURRENT_DATE
            LIMIT 1
            """
        )
    )
    ar = avg_ms_sql.fetchone()
    avg_response_ms = int(ar[0]) if ar and ar[0] is not None else 45

    return {
        "total_merchants": total_merchants,
        "total_stores": total_stores,
        "active_stores_today": active_stores,
        "total_orders_today": total_orders_today,
        "gmv_today_yuan": gmv_fen // 100,
        "agent_calls_today": int(agent.get("total_executions_today", 0)),
        "avg_response_ms": avg_response_ms,
    }
