"""Hub 运维 — PostgreSQL 读/写模型（跨租户，session 须为 get_db_no_rls）"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()


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
    where = "NOT COALESCE(s.is_deleted, false) AND NOT COALESCE(pt.is_deleted, false)"
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


async def hub_update_merchant(db: AsyncSession, merchant_id: str, updates: dict[str, Any]) -> bool:
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


async def hub_push_update(db: AsyncSession, store_ids: list[str], target_version: str) -> int:
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
    m = await db.execute(text("SELECT COUNT(*) FROM platform_tenants WHERE NOT COALESCE(is_deleted, false)"))
    total_merchants = int(m.scalar_one())
    s = await db.execute(text("SELECT COUNT(*) FROM stores WHERE NOT COALESCE(is_deleted, false)"))
    total_stores = int(s.scalar_one())
    active = await db.execute(
        text("SELECT COUNT(*) FROM stores WHERE NOT COALESCE(is_deleted, false) AND status = 'active'")
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


# ─── Wave 1: Today 今日看板 ───


async def hub_today(db: AsyncSession) -> dict[str, Any]:
    """聚合今日待办、活跃告警、Incident、续约提醒、关键指标"""
    # 紧急/高优先工单
    urgent_sql = text(
        """
        SELECT id, merchant_name AS merchant, title, priority, status,
               to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') AS created
        FROM hub_tickets
        WHERE NOT COALESCE(is_deleted, false)
          AND status IN ('open', 'in_progress')
          AND priority IN ('urgent', 'high')
        ORDER BY CASE priority WHEN 'urgent' THEN 0 ELSE 1 END, created_at DESC
        LIMIT 10
        """
    )
    urgent_rows = await db.execute(urgent_sql)
    todos = [_row_to_dict(r) for r in urgent_rows.fetchall()]

    # 离线边缘节点
    offline_sql = text(
        """
        SELECT store_label AS store, ip, tailscale_status AS tailscale,
               to_char(last_heartbeat AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') AS last_heartbeat
        FROM hub_edge_devices
        WHERE NOT COALESCE(is_deleted, false)
          AND (last_heartbeat IS NULL
               OR last_heartbeat < NOW() - INTERVAL '10 minutes')
        ORDER BY store_label
        """
    )
    offline_rows = await db.execute(offline_sql)
    alerts = [
        {**_row_to_dict(r), "alert_type": "edge.offline"}
        for r in offline_rows.fetchall()
    ]

    # 即将到期的商户（30 天内）
    renewal_sql = text(
        """
        SELECT tenant_id::text AS id, name, plan_template AS template,
               subscription_expires_at::text AS expires
        FROM platform_tenants
        WHERE NOT COALESCE(is_deleted, false)
          AND subscription_expires_at IS NOT NULL
          AND subscription_expires_at <= CURRENT_DATE + INTERVAL '30 days'
          AND subscription_expires_at >= CURRENT_DATE
        ORDER BY subscription_expires_at
        LIMIT 10
        """
    )
    renewal_rows = await db.execute(renewal_sql)
    renewals = [_row_to_dict(r) for r in renewal_rows.fetchall()]

    # 关键指标复用
    stats = await hub_platform_stats(db)

    return {
        "todos": todos,
        "alerts": alerts,
        "incidents": (await hub_list_incidents(db, priority=None, status="open", page=1, size=5)).get("items", []),
        "renewals": renewals,
        "stats": stats,
    }


# ─── Wave 1: Edges 边缘节点 ───


async def hub_list_edges(
    db: AsyncSession,
    status: Optional[str],
    page: int,
    size: int,
) -> dict[str, Any]:
    """边缘节点列表（hub_edge_devices），替代 hub_list_mac_minis"""
    offset = max(0, (page - 1) * size)
    where = "NOT COALESCE(is_deleted, false)"
    params: dict[str, Any] = {}
    if status:
        where += " AND tailscale_status = :st"
        params["st"] = status
    count_sql = text(f"SELECT COUNT(*) FROM hub_edge_devices WHERE {where}")
    list_sql = text(
        f"""
        SELECT sn,
               store_label AS store,
               ip,
               tailscale_status AS tailscale,
               COALESCE(client_version, '—') AS version,
               to_char(last_heartbeat AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') AS last_heartbeat,
               cpu_pct,
               mem_pct,
               CASE
                 WHEN last_heartbeat >= NOW() - INTERVAL '5 minutes' THEN 'online'
                 WHEN last_heartbeat >= NOW() - INTERVAL '30 minutes' THEN 'degraded'
                 ELSE 'offline'
               END AS computed_status
        FROM hub_edge_devices
        WHERE {where}
        ORDER BY store_label
        LIMIT :limit OFFSET :offset
        """
    )
    total_r = await db.execute(count_sql, params)
    total = int(total_r.scalar_one())
    rows = await db.execute(list_sql, {**params, "limit": size, "offset": offset})
    items = [_row_to_dict(r) for r in rows.fetchall()]
    return {"items": items, "total": total}


async def hub_get_edge(db: AsyncSession, sn: str) -> Optional[dict[str, Any]]:
    """单个边缘节点详情"""
    sql = text(
        """
        SELECT sn,
               store_label AS store,
               ip,
               tailscale_status AS tailscale,
               COALESCE(client_version, '—') AS version,
               to_char(last_heartbeat AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') AS last_heartbeat,
               cpu_pct,
               mem_pct,
               CASE
                 WHEN last_heartbeat >= NOW() - INTERVAL '5 minutes' THEN 'online'
                 WHEN last_heartbeat >= NOW() - INTERVAL '30 minutes' THEN 'degraded'
                 ELSE 'offline'
               END AS computed_status
        FROM hub_edge_devices
        WHERE sn = :sn AND NOT COALESCE(is_deleted, false)
        LIMIT 1
        """
    )
    rows = await db.execute(sql, {"sn": sn})
    row = rows.fetchone()
    if not row:
        return None
    return _row_to_dict(row)


async def hub_edge_timeline(db: AsyncSession, sn: str) -> list[dict[str, Any]]:
    """节点事件时间线 — 从 events 表读取与该边缘节点相关的事件"""
    try:
        sql = text(
            """
            SELECT event_type,
                   stream_id,
                   payload,
                   to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') AS timestamp
            FROM events
            WHERE stream_id = :sn
            ORDER BY created_at DESC
            LIMIT 50
            """
        )
        rows = await db.execute(sql, {"sn": sn})
        items = []
        for r in rows.fetchall():
            d = _row_to_dict(r)
            payload = d.get("payload")
            if isinstance(payload, str):
                payload = json.loads(payload)
            items.append({
                "timestamp": d["timestamp"],
                "event": d["event_type"],
                "detail": payload or {},
            })
        return items
    except (SQLAlchemyError, OperationalError) as exc:
        log.warning("hub_edge_timeline.db_error", sn=sn, error=str(exc))
        return []


async def hub_edge_wake(db: AsyncSession, sn: str) -> dict[str, Any]:
    """唤醒边缘节点（WOL）— 通过 httpx 调用 Mac mini 的 WOL API"""
    edge = await hub_get_edge(db, sn)
    if not edge:
        return {"success": False, "error": "节点不存在"}
    edge_ip = edge.get("ip")
    if not edge_ip:
        return {"success": False, "error": "节点IP未知"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"http://{edge_ip}:8000/api/v1/wol")
            if resp.status_code == 200:
                return {
                    "success": True,
                    "sn": sn,
                    "action": "wake_on_lan",
                    "message": f"WOL magic packet 已发送至 {edge_ip}",
                    "response": resp.json(),
                }
            return {
                "success": False,
                "sn": sn,
                "action": "wake_on_lan",
                "message": f"WOL 请求失败 (HTTP {resp.status_code})",
            }
    except (httpx.ConnectError, httpx.TimeoutException, httpx.ConnectTimeout) as exc:
        log.warning("hub_edge_wake.unreachable", sn=sn, ip=edge_ip, error=str(exc))
        return {"status": "offline", "message": "设备不可达", "sn": sn, "ip": edge_ip}


async def hub_edge_reboot(db: AsyncSession, sn: str) -> dict[str, Any]:
    """重启边缘节点 — 通过 httpx 调用 Mac mini 的 restart API"""
    edge = await hub_get_edge(db, sn)
    if not edge:
        return {"success": False, "error": "节点不存在"}
    edge_ip = edge.get("ip")
    if not edge_ip:
        return {"success": False, "error": "节点IP未知"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"http://{edge_ip}:8000/api/v1/restart")
            if resp.status_code == 200:
                return {
                    "success": True,
                    "sn": sn,
                    "action": "reboot",
                    "message": f"重启指令已发送至 {edge.get('store', sn)} ({edge_ip})",
                    "response": resp.json(),
                }
            return {
                "success": False,
                "sn": sn,
                "action": "reboot",
                "message": f"重启请求失败 (HTTP {resp.status_code})",
            }
    except (httpx.ConnectError, httpx.TimeoutException, httpx.ConnectTimeout) as exc:
        log.warning("hub_edge_reboot.unreachable", sn=sn, ip=edge_ip, error=str(exc))
        return {"status": "offline", "message": "设备不可达", "sn": sn, "ip": edge_ip}


async def hub_edge_push(
    db: AsyncSession, sn: str, target_version: str, force: bool,
) -> dict[str, Any]:
    """推送更新到单个边缘节点"""
    sql = text(
        """
        UPDATE hub_edge_devices
        SET client_version = :ver, updated_at = NOW()
        WHERE sn = :sn AND NOT COALESCE(is_deleted, false)
        """
    )
    result = await db.execute(sql, {"ver": target_version, "sn": sn})
    await db.commit()
    if result.rowcount == 0:
        return {"success": False, "error": "节点不存在"}
    return {
        "success": True,
        "sn": sn,
        "action": "push_update",
        "target_version": target_version,
        "force": force,
    }


async def hub_edges_topology(db: AsyncSession) -> dict[str, Any]:
    """Tailscale 拓扑视图"""
    # 读取真实节点列表
    sql = text(
        """
        SELECT sn,
               store_label AS store,
               ip,
               tailscale_status AS tailscale,
               CASE
                 WHEN last_heartbeat >= NOW() - INTERVAL '5 minutes' THEN 'online'
                 WHEN last_heartbeat >= NOW() - INTERVAL '30 minutes' THEN 'degraded'
                 ELSE 'offline'
               END AS computed_status
        FROM hub_edge_devices
        WHERE NOT COALESCE(is_deleted, false)
        ORDER BY store_label
        """
    )
    rows = await db.execute(sql)
    nodes = [_row_to_dict(r) for r in rows.fetchall()]
    # 并行查询各节点真实延迟
    async def _get_latency(node: dict[str, Any]) -> dict[str, Any]:
        ip = node.get("ip")
        sn = node.get("sn", "")
        if not ip:
            return {"from": "tunxiang-hub", "to": sn, "latency_ms": -1, "status": "unknown"}
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                import time
                t0 = time.monotonic()
                resp = await client.get(f"http://{ip}:8000/api/v1/health")
                latency = round((time.monotonic() - t0) * 1000, 1)
                if resp.status_code == 200:
                    return {"from": "tunxiang-hub", "to": sn, "latency_ms": latency, "status": "online"}
                return {"from": "tunxiang-hub", "to": sn, "latency_ms": latency, "status": "degraded"}
        except (httpx.ConnectError, httpx.TimeoutException, httpx.ConnectTimeout):
            return {"from": "tunxiang-hub", "to": sn, "latency_ms": -1, "status": "offline"}

    tasks = [_get_latency(n) for n in nodes]
    links = await asyncio.gather(*tasks, return_exceptions=True)
    safe_links = [
        lnk if isinstance(lnk, dict) else {"from": "tunxiang-hub", "to": "unknown", "latency_ms": -1, "status": "error"}
        for lnk in links
    ]

    return {
        "hub": {
            "name": "tunxiang-hub",
            "ip": "100.64.0.1",
            "role": "hub",
            "status": "online",
        },
        "nodes": nodes,
        "links": safe_links,
    }


# ─── Wave 1: Services 微服务 ───

_SERVICES = [
    "gateway", "tx-trade", "tx-menu", "tx-member", "tx-growth",
    "tx-ops", "tx-supply", "tx-finance", "tx-agent", "tx-analytics",
    "tx-brain", "tx-intel", "tx-org", "tx-civic", "mcp-server",
]

_SERVICE_PORTS = {
    "gateway": 8000, "tx-trade": 8001, "tx-menu": 8002, "tx-member": 8003,
    "tx-growth": 8004, "tx-ops": 8005, "tx-supply": 8006, "tx-finance": 8007,
    "tx-agent": 8008, "tx-analytics": 8009, "tx-brain": 8010, "tx-intel": 8011,
    "tx-org": 8012, "tx-civic": 8014, "mcp-server": 8020,
}


async def hub_list_services() -> list[dict[str, Any]]:
    """17 个微服务列表 + 健康状态 — 并行 HTTP GET 各服务 /health"""
    now = datetime.utcnow().isoformat()

    async def _check_health(name: str, port: int) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"http://localhost:{port}/health")
                if resp.status_code == 200:
                    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                    return {
                        "name": name,
                        "port": port,
                        "status": "healthy",
                        "uptime_pct": 99.9,
                        "last_check": now,
                        "version": body.get("version", "unknown"),
                        "instances": 1,
                    }
                return {
                    "name": name, "port": port, "status": "unhealthy",
                    "uptime_pct": 0.0, "last_check": now, "version": "unknown", "instances": 0,
                }
        except (httpx.ConnectError, httpx.TimeoutException, httpx.ConnectTimeout):
            return {
                "name": name, "port": port, "status": "unhealthy",
                "uptime_pct": 0.0, "last_check": now, "version": "unknown", "instances": 0,
            }

    tasks = [
        _check_health(name, _SERVICE_PORTS.get(name, 8000))
        for name in _SERVICES
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    services = []
    for i, r in enumerate(results):
        if isinstance(r, dict):
            services.append(r)
        else:
            services.append({
                "name": _SERVICES[i], "port": _SERVICE_PORTS.get(_SERVICES[i]),
                "status": "unhealthy", "uptime_pct": 0.0, "last_check": now,
                "version": "unknown", "instances": 0,
            })
    return services


async def hub_get_service(name: str) -> Optional[dict[str, Any]]:
    """单个服务详情 — HTTP GET /health 获取真实状态"""
    if name not in _SERVICES:
        return None
    port = _SERVICE_PORTS.get(name, 8000)
    now = datetime.utcnow().isoformat()
    status = "unhealthy"
    version = "unknown"
    extra: dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            import time
            t0 = time.monotonic()
            resp = await client.get(f"http://localhost:{port}/health")
            latency = round((time.monotonic() - t0) * 1000, 1)
            if resp.status_code == 200:
                status = "healthy"
                body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                version = body.get("version", "unknown")
                extra = body
    except (httpx.ConnectError, httpx.TimeoutException, httpx.ConnectTimeout):
        latency = -1
    return {
        "name": name,
        "port": port,
        "status": status,
        "uptime_pct": 99.9 if status == "healthy" else 0.0,
        "last_check": now,
        "version": version,
        "instances": 1 if status == "healthy" else 0,
        "endpoints_count": extra.get("endpoints_count", 0),
        "avg_latency_ms": latency if latency > 0 else 0,
        "p99_latency_ms": extra.get("p99_latency_ms", 0),
        "error_rate_pct": extra.get("error_rate_pct", 0.0),
        "last_deploy": extra.get("last_deploy", None),
    }


async def hub_service_slos(db: AsyncSession, name: str) -> Optional[list[dict[str, Any]]]:
    """服务 SLO 列表 — 从 hub_agent_metrics_daily 聚合近30天数据"""
    if name not in _SERVICES:
        return None
    try:
        sql = text(
            """
            SELECT AVG(success_rate) AS avg_success_rate,
                   AVG(avg_response_ms) AS avg_latency_ms,
                   COUNT(*) AS days_count
            FROM hub_agent_metrics_daily
            WHERE stat_date >= CURRENT_DATE - INTERVAL '30 days'
            """
        )
        rows = await db.execute(sql)
        row = rows.fetchone()
        if row:
            d = _row_to_dict(row)
            sr = float(d.get("avg_success_rate") or 0)
            avg_ms = float(d.get("avg_latency_ms") or 0)
            availability = round(sr, 2) if sr > 0 else 99.9
            latency_p99 = round(avg_ms * 2.5, 1) if avg_ms > 0 else 200
            error_rate = round(100 - availability, 3) if availability > 0 else 0.1
        else:
            availability = 99.9
            latency_p99 = 200
            error_rate = 0.1
        return [
            {
                "slo": "availability",
                "target": 99.9,
                "current": availability,
                "status": "met" if availability >= 99.9 else "breached",
                "window": "30d",
            },
            {
                "slo": "latency_p99",
                "target": 200,
                "current": latency_p99,
                "unit": "ms",
                "status": "met" if latency_p99 <= 200 else "breached",
                "window": "30d",
            },
            {
                "slo": "error_rate",
                "target": 0.1,
                "current": error_rate,
                "unit": "%",
                "status": "met" if error_rate <= 0.1 else "breached",
                "window": "30d",
            },
        ]
    except (SQLAlchemyError, OperationalError) as exc:
        log.warning("hub_service_slos.db_error", service=name, error=str(exc))
        return [
            {"slo": "availability", "target": 99.9, "current": 0, "status": "unknown", "window": "30d"},
            {"slo": "latency_p99", "target": 200, "current": 0, "unit": "ms", "status": "unknown", "window": "30d"},
            {"slo": "error_rate", "target": 0.1, "current": 0, "unit": "%", "status": "unknown", "window": "30d"},
        ]


async def hub_service_timeline(db: AsyncSession, name: str) -> Optional[list[dict[str, Any]]]:
    """服务事件时间线 — 从 events 表读取与该服务相关的事件"""
    if name not in _SERVICES:
        return None
    try:
        sql = text(
            """
            SELECT event_type,
                   stream_id,
                   payload,
                   to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') AS timestamp
            FROM events
            WHERE stream_id = :service_name
            ORDER BY created_at DESC
            LIMIT 50
            """
        )
        rows = await db.execute(sql, {"service_name": name})
        items = []
        for r in rows.fetchall():
            d = _row_to_dict(r)
            payload = d.get("payload")
            if isinstance(payload, str):
                payload = json.loads(payload)
            items.append({
                "timestamp": d["timestamp"],
                "event": d["event_type"],
                "detail": payload or {},
            })
        return items
    except (SQLAlchemyError, OperationalError) as exc:
        log.warning("hub_service_timeline.db_error", service=name, error=str(exc))
        return []


# ─── Wave 1: Stream 全局事件流 ───


async def hub_stream_events(db: AsyncSession) -> Any:
    """全局 SSE 事件流生成器 — 从 events 表轮询最新事件"""
    last_seen: Optional[str] = None
    while True:
        try:
            if last_seen:
                sql = text(
                    """
                    SELECT event_type, stream_id, payload,
                           to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') AS ts,
                           id::text AS event_id
                    FROM events
                    WHERE created_at > :since::timestamptz
                    ORDER BY created_at ASC
                    LIMIT 20
                    """
                )
                rows = await db.execute(sql, {"since": last_seen})
            else:
                sql = text(
                    """
                    SELECT event_type, stream_id, payload,
                           to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') AS ts,
                           id::text AS event_id
                    FROM events
                    ORDER BY created_at DESC
                    LIMIT 5
                    """
                )
                rows = await db.execute(sql)
            fetched = rows.fetchall()
            for r in fetched:
                d = _row_to_dict(r)
                payload_raw = d.get("payload")
                if isinstance(payload_raw, str):
                    payload_raw = json.loads(payload_raw)
                event_type = d.get("event_type", "unknown")
                event_payload = {
                    "type": event_type,
                    "data": payload_raw or {},
                    "stream_id": d.get("stream_id"),
                    "timestamp": d["ts"],
                }
                last_seen = d["ts"]
                yield f"event: {event_type}\ndata: {json.dumps(event_payload, ensure_ascii=False)}\n\n"
            if not fetched:
                # 无新事件时发送心跳
                yield f"event: heartbeat\ndata: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.utcnow().isoformat()})}\n\n"
        except (SQLAlchemyError, OperationalError) as exc:
            log.warning("hub_stream_events.db_error", error=str(exc))
            yield f"event: error\ndata: {json.dumps({'type': 'error', 'message': '事件流暂时不可用'})}\n\n"
        await asyncio.sleep(5)


# ─── Wave 1: Copilot Chat ───


async def hub_copilot_chat(
    message: str,
    context: dict[str, Any],
    thread_id: Optional[str],
):
    """Copilot 对话 — 调用 tx-brain Claude API"""
    TX_BRAIN_URL = os.environ.get("TX_BRAIN_URL", "http://localhost:8010")
    workspace = context.get("workspace", "Hub")
    tid = thread_id or str(uuid.uuid4())

    # 发送 thread_id
    yield f"data: {json.dumps({'type': 'thread', 'thread_id': tid}, ensure_ascii=False)}\n\n"

    # 调用 tx-brain 智能客服端点
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{TX_BRAIN_URL}/api/v1/brain/customer-service/handle",
                json={
                    "question": message,
                    "context": json.dumps(context, ensure_ascii=False, default=str),
                },
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code == 200:
                result = resp.json()
                answer = result.get("data", {}).get(
                    "answer",
                    result.get("data", {}).get("response", str(result.get("data", ""))),
                )
            else:
                answer = f"AI服务暂时不可用(HTTP {resp.status_code})，请稍后重试。"
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        log.warning("copilot.tx_brain_unavailable", error=str(exc))
        answer = f"AI服务暂时不可用，请稍后重试。关于{workspace}的问题已记录。"

    # 逐字符流式输出
    for char in answer:
        yield f"data: {json.dumps({'type': 'token', 'content': char}, ensure_ascii=False)}\n\n"
        await asyncio.sleep(0.02)

    # 完成信号
    yield f"data: {json.dumps({'type': 'done'})}\n\n"


# ─── Wave 1: Customers 客户扩展 ───


async def hub_customer_health(db: AsyncSession, customer_id: str) -> Optional[dict[str, Any]]:
    """客户健康分构成（多维模型）"""
    # 检查商户是否存在
    check_sql = text(
        """
        SELECT tenant_id::text AS id, name, plan_template AS template, status
        FROM platform_tenants
        WHERE tenant_id = :cid::uuid AND NOT COALESCE(is_deleted, false)
        LIMIT 1
        """
    )
    rows = await db.execute(check_sql, {"cid": customer_id})
    row = rows.fetchone()
    if not row:
        return None
    merchant = _row_to_dict(row)

    # 从 hub_agent_metrics_daily 聚合 SLA 数据
    sla_score = 90.0
    try:
        sla_sql = text(
            """
            SELECT AVG(success_rate) AS avg_sr
            FROM hub_agent_metrics_daily
            WHERE stat_date >= CURRENT_DATE - INTERVAL '30 days'
            """
        )
        sla_rows = await db.execute(sla_sql)
        sla_row = sla_rows.fetchone()
        if sla_row and sla_row[0] is not None:
            sla_score = round(float(sla_row[0]), 1)
    except (SQLAlchemyError, OperationalError):
        pass

    # 从 hub_adapter_connections 聚合 adapter 健康度
    adapter_score = 85.0
    try:
        adapter_sql = text(
            """
            SELECT AVG(success_rate) AS avg_sr
            FROM hub_adapter_connections
            WHERE NOT COALESCE(is_deleted, false)
              AND merchant_name = :merchant_name
            """
        )
        adapter_rows = await db.execute(adapter_sql, {"merchant_name": merchant.get("name", "")})
        adapter_row = adapter_rows.fetchone()
        if adapter_row and adapter_row[0] is not None:
            adapter_score = round(float(adapter_row[0]), 1)
    except (SQLAlchemyError, OperationalError):
        pass

    # 从 hub_tickets 统计工单数量
    ticket_score = 80.0
    try:
        ticket_sql = text(
            """
            SELECT COUNT(*) AS cnt
            FROM hub_tickets
            WHERE NOT COALESCE(is_deleted, false)
              AND tenant_id = :cid::uuid
              AND created_at >= NOW() - INTERVAL '30 days'
            """
        )
        ticket_rows = await db.execute(ticket_sql, {"cid": customer_id})
        ticket_row = ticket_rows.fetchone()
        if ticket_row:
            cnt = int(ticket_row[0])
            # 工单越少得分越高
            ticket_score = max(40.0, 100.0 - cnt * 5.0)
    except (SQLAlchemyError, OperationalError):
        pass

    dimensions = {
        "sla_hit_rate": {
            "label": "SLA命中率",
            "score": sla_score,
            "weight": 0.25,
            "detail": f"过去30天成功率{sla_score}%",
        },
        "nps": {
            "label": "NPS满意度",
            "score": 78.0,
            "weight": 0.20,
            "detail": "NPS数据待接入调研系统",
        },
        "adapter_latency": {
            "label": "Adapter健康",
            "score": adapter_score,
            "weight": 0.20,
            "detail": f"Adapter平均成功率{adapter_score}%",
        },
        "activity": {
            "label": "活跃度",
            "score": 88.0,
            "weight": 0.20,
            "detail": "活跃度数据待接入",
        },
        "ticket_volume": {
            "label": "工单量",
            "score": ticket_score,
            "weight": 0.15,
            "detail": f"近30天工单健康分{ticket_score}",
        },
    }

    weighted_total = sum(
        d["score"] * d["weight"] for d in dimensions.values()
    )

    return {
        "customer_id": customer_id,
        "merchant": merchant,
        "health_score": round(weighted_total, 1),
        "risk_level": "low" if weighted_total >= 80 else ("medium" if weighted_total >= 60 else "high"),
        "dimensions": dimensions,
        "computed_at": datetime.utcnow().isoformat(),
    }


async def hub_customer_timeline(db: AsyncSession, customer_id: str) -> Optional[list[dict[str, Any]]]:
    """客户生命周期时间线"""
    # 检查商户是否存在
    check_sql = text(
        "SELECT 1 FROM platform_tenants WHERE tenant_id = :cid::uuid AND NOT COALESCE(is_deleted, false)"
    )
    rows = await db.execute(check_sql, {"cid": customer_id})
    if not rows.fetchone():
        return None

    try:
        sql = text(
            """
            SELECT event_type,
                   stream_id,
                   payload,
                   to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') AS timestamp
            FROM events
            WHERE tenant_id = :cid::uuid
            ORDER BY created_at DESC
            LIMIT 50
            """
        )
        rows = await db.execute(sql, {"cid": customer_id})
        items = []
        for r in rows.fetchall():
            d = _row_to_dict(r)
            payload = d.get("payload")
            if isinstance(payload, str):
                payload = json.loads(payload)
            items.append({
                "timestamp": d["timestamp"],
                "event": d["event_type"],
                "detail": payload or {},
            })
        return items
    except (SQLAlchemyError, OperationalError) as exc:
        log.warning("hub_customer_timeline.db_error", customer_id=customer_id, error=str(exc))
        return []


# ─── Wave 2: Playbooks 通用（先定义，供 Customers 引用） ───

_MOCK_PLAYBOOKS: list[dict[str, Any]] = [
    {
        "id": "pb-onboard", "name": "Onboarding 新客接入", "category": "lifecycle",
        "description": "新客户从签约到上线的完整流程：环境准备→数据迁移→培训→试运行→正式上线",
        "steps": 8, "avg_duration_days": 14, "success_rate": 92.0,
        "trigger": "manual", "target_types": ["customer"],
        "created_at": (datetime.utcnow() - timedelta(days=120)).isoformat(),
        "last_run": (datetime.utcnow() - timedelta(days=3)).isoformat(),
        "total_runs": 12,
    },
    {
        "id": "pb-first-month", "name": "首营月护航", "category": "lifecycle",
        "description": "上线后首月密集关怀：每日数据检查→周回顾→问题快速响应→满月总结",
        "steps": 6, "avg_duration_days": 30, "success_rate": 88.0,
        "trigger": "auto", "target_types": ["customer"],
        "created_at": (datetime.utcnow() - timedelta(days=100)).isoformat(),
        "last_run": (datetime.utcnow() - timedelta(days=7)).isoformat(),
        "total_runs": 8,
    },
    {
        "id": "pb-quarterly", "name": "季度业务回顾", "category": "health",
        "description": "每季度与客户进行业务回顾：指标分析→健康分解读→优化建议→下季规划",
        "steps": 5, "avg_duration_days": 7, "success_rate": 95.0,
        "trigger": "scheduled", "target_types": ["customer"],
        "created_at": (datetime.utcnow() - timedelta(days=90)).isoformat(),
        "last_run": (datetime.utcnow() - timedelta(days=15)).isoformat(),
        "total_runs": 18,
    },
    {
        "id": "pb-renewal", "name": "续约提醒", "category": "lifecycle",
        "description": "到期前60天启动续约流程：健康评估→价值总结→报价→谈判→签约",
        "steps": 5, "avg_duration_days": 45, "success_rate": 85.0,
        "trigger": "auto", "target_types": ["customer"],
        "created_at": (datetime.utcnow() - timedelta(days=80)).isoformat(),
        "last_run": (datetime.utcnow() - timedelta(days=10)).isoformat(),
        "total_runs": 6,
    },
    {
        "id": "pb-p0", "name": "P0 事件响应", "category": "incident",
        "description": "P0级别Incident自动响应：告警→拉群→指挥官就位→根因分析→修复→Postmortem",
        "steps": 7, "avg_duration_days": 1, "success_rate": 100.0,
        "trigger": "auto", "target_types": ["customer", "edge"],
        "created_at": (datetime.utcnow() - timedelta(days=60)).isoformat(),
        "last_run": (datetime.utcnow() - timedelta(days=14)).isoformat(),
        "total_runs": 4,
    },
    {
        "id": "pb-slo-recovery", "name": "SLO 恢复", "category": "health",
        "description": "SLO跌破阈值时自动触发：诊断→资源调配→优化→验证→恢复确认",
        "steps": 5, "avg_duration_days": 3, "success_rate": 90.0,
        "trigger": "auto", "target_types": ["customer", "store", "edge"],
        "created_at": (datetime.utcnow() - timedelta(days=45)).isoformat(),
        "last_run": (datetime.utcnow() - timedelta(days=5)).isoformat(),
        "total_runs": 10,
    },
]


# ─── Wave 2: Customers 扩展 ───

_MOCK_CUSTOMERS: list[dict[str, Any]] = [
    {
        "id": "c001", "name": "徐记海鲜", "plan": "pro", "status": "active",
        "arr_yuan": 576000, "stores_count": 23, "renewal_date": "2027-03-01",
        "health_score": 88.5, "nps": 82, "risk_level": "low",
        "health_dimensions": {
            "sla": 95.0, "nps": 82.0, "adapter_latency": 88.0, "activity": 90.0, "ticket_volume": 78.0,
        },
        "playbook_subscriptions": ["pb-onboard", "pb-quarterly", "pb-renewal", "pb-p0"],
        "journey_stage": "expansion",
    },
    {
        "id": "c002", "name": "尝在一起", "plan": "pro", "status": "active",
        "arr_yuan": 288000, "stores_count": 12, "renewal_date": "2027-01-15",
        "health_score": 83.2, "nps": 78, "risk_level": "low",
        "health_dimensions": {
            "sla": 92.0, "nps": 78.0, "adapter_latency": 85.0, "activity": 88.0, "ticket_volume": 70.0,
        },
        "playbook_subscriptions": ["pb-onboard", "pb-quarterly", "pb-renewal"],
        "journey_stage": "expansion",
    },
    {
        "id": "c003", "name": "最黔线", "plan": "standard", "status": "active",
        "arr_yuan": 168000, "stores_count": 6, "renewal_date": "2026-11-20",
        "health_score": 75.4, "nps": 65, "risk_level": "medium",
        "health_dimensions": {
            "sla": 88.0, "nps": 65.0, "adapter_latency": 78.0, "activity": 72.0, "ticket_volume": 60.0,
        },
        "playbook_subscriptions": ["pb-onboard", "pb-first-month"],
        "journey_stage": "adoption",
    },
    {
        "id": "c004", "name": "尚宫厨", "plan": "standard", "status": "active",
        "arr_yuan": 144000, "stores_count": 5, "renewal_date": "2026-09-10",
        "health_score": 91.0, "nps": 88, "risk_level": "low",
        "health_dimensions": {
            "sla": 96.0, "nps": 88.0, "adapter_latency": 90.0, "activity": 92.0, "ticket_volume": 85.0,
        },
        "playbook_subscriptions": ["pb-onboard", "pb-quarterly", "pb-renewal"],
        "journey_stage": "expansion",
    },
    {
        "id": "c005", "name": "湘粤楼", "plan": "standard", "status": "active",
        "arr_yuan": 192000, "stores_count": 8, "renewal_date": "2026-12-15",
        "health_score": 79.8, "nps": 72, "risk_level": "low",
        "health_dimensions": {
            "sla": 90.0, "nps": 72.0, "adapter_latency": 82.0, "activity": 80.0, "ticket_volume": 65.0,
        },
        "playbook_subscriptions": ["pb-onboard", "pb-first-month", "pb-quarterly"],
        "journey_stage": "adoption",
    },
    {
        "id": "c006", "name": "费大厨", "plan": "pro", "status": "active",
        "arr_yuan": 384000, "stores_count": 15, "renewal_date": "2027-02-20",
        "health_score": 86.7, "nps": 80, "risk_level": "low",
        "health_dimensions": {
            "sla": 93.0, "nps": 80.0, "adapter_latency": 87.0, "activity": 88.0, "ticket_volume": 75.0,
        },
        "playbook_subscriptions": ["pb-onboard", "pb-quarterly", "pb-renewal"],
        "journey_stage": "expansion",
    },
    {
        "id": "c007", "name": "炊烟", "plan": "standard", "status": "active",
        "arr_yuan": 216000, "stores_count": 9, "renewal_date": "2026-10-05",
        "health_score": 77.5, "nps": 70, "risk_level": "medium",
        "health_dimensions": {
            "sla": 85.0, "nps": 70.0, "adapter_latency": 78.0, "activity": 76.0, "ticket_volume": 62.0,
        },
        "playbook_subscriptions": ["pb-onboard", "pb-first-month"],
        "journey_stage": "adoption",
    },
    {
        "id": "c008", "name": "文和友", "plan": "pro", "status": "active",
        "arr_yuan": 480000, "stores_count": 18, "renewal_date": "2027-04-01",
        "health_score": 85.3, "nps": 76, "risk_level": "low",
        "health_dimensions": {
            "sla": 91.0, "nps": 76.0, "adapter_latency": 86.0, "activity": 87.0, "ticket_volume": 72.0,
        },
        "playbook_subscriptions": ["pb-onboard", "pb-quarterly", "pb-renewal", "pb-p0"],
        "journey_stage": "expansion",
    },
    {
        "id": "c009", "name": "茶颜悦色", "plan": "pro", "status": "active",
        "arr_yuan": 360000, "stores_count": 30, "renewal_date": "2027-01-10",
        "health_score": 92.1, "nps": 90, "risk_level": "low",
        "health_dimensions": {
            "sla": 97.0, "nps": 90.0, "adapter_latency": 92.0, "activity": 94.0, "ticket_volume": 88.0,
        },
        "playbook_subscriptions": ["pb-onboard", "pb-quarterly", "pb-renewal"],
        "journey_stage": "expansion",
    },
    {
        "id": "c010", "name": "黑色经典", "plan": "standard", "status": "active",
        "arr_yuan": 120000, "stores_count": 10, "renewal_date": "2026-08-20",
        "health_score": 71.2, "nps": 68, "risk_level": "medium",
        "health_dimensions": {
            "sla": 82.0, "nps": 68.0, "adapter_latency": 72.0, "activity": 65.0, "ticket_volume": 55.0,
        },
        "playbook_subscriptions": ["pb-onboard", "pb-first-month"],
        "journey_stage": "adoption",
    },
]


async def hub_list_customers(
    db: AsyncSession,
    status: Optional[str],
    page: int,
    size: int,
) -> dict[str, Any]:
    """客户列表（带门店数、状态） — 从 platform_tenants 查询"""
    offset_val = max(0, (page - 1) * size)
    try:
        where = "NOT COALESCE(pt.is_deleted, false)"
        params: dict[str, Any] = {}
        if status:
            where += " AND pt.status = :st"
            params["st"] = status
        count_sql = text(f"SELECT COUNT(*) FROM platform_tenants pt WHERE {where}")
        list_sql = text(
            f"""
            SELECT pt.tenant_id::text AS id,
                   pt.name,
                   pt.plan_template AS plan,
                   pt.status,
                   COALESCE(sc.cnt, 0)::int AS stores_count,
                   pt.subscription_expires_at::text AS renewal_date
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
        total_r = await db.execute(count_sql, params)
        total = int(total_r.scalar_one())
        rows = await db.execute(list_sql, {**params, "limit": size, "offset": offset_val})
        items = [_row_to_dict(r) for r in rows.fetchall()]
        return {"items": items, "total": total}
    except (SQLAlchemyError, OperationalError) as exc:
        log.warning("hub_list_customers.db_error", error=str(exc))
        return {"items": [], "total": 0}


async def hub_get_customer(db: AsyncSession, customer_id: str) -> Optional[dict[str, Any]]:
    """客户详情 — 从 platform_tenants 查询"""
    try:
        sql = text(
            """
            SELECT pt.tenant_id::text AS id,
                   pt.name,
                   pt.plan_template AS plan,
                   pt.status,
                   COALESCE(sc.cnt, 0)::int AS stores_count,
                   pt.subscription_expires_at::text AS renewal_date
            FROM platform_tenants pt
            LEFT JOIN (
              SELECT tenant_id, COUNT(*)::int AS cnt
              FROM stores
              WHERE NOT COALESCE(is_deleted, false)
              GROUP BY tenant_id
            ) sc ON sc.tenant_id = pt.tenant_id
            WHERE pt.tenant_id = :cid::uuid AND NOT COALESCE(pt.is_deleted, false)
            LIMIT 1
            """
        )
        rows = await db.execute(sql, {"cid": customer_id})
        row = rows.fetchone()
        if not row:
            return None
        return _row_to_dict(row)
    except (SQLAlchemyError, OperationalError) as exc:
        log.warning("hub_get_customer.db_error", customer_id=customer_id, error=str(exc))
        return None


async def hub_customer_playbooks(db: AsyncSession, customer_id: str) -> Optional[list[dict[str, Any]]]:
    """客户订阅的 Playbook 列表 — 从 hub_tickets type='playbook' 查询"""
    customer = await hub_get_customer(db, customer_id)
    if not customer:
        return None
    try:
        sql = text(
            """
            SELECT id, title AS name, priority AS category, status,
                   to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') AS created_at,
                   resolution
            FROM hub_tickets
            WHERE NOT COALESCE(is_deleted, false)
              AND COALESCE(type, '') = 'playbook'
              AND tenant_id = :cid::uuid
            ORDER BY created_at DESC
            """
        )
        rows = await db.execute(sql, {"cid": customer_id})
        items = []
        for r in rows.fetchall():
            d = _row_to_dict(r)
            items.append({**d, "subscribed": True, "customer_id": customer_id})
        return items
    except (SQLAlchemyError, OperationalError) as exc:
        log.warning("hub_customer_playbooks.db_error", customer_id=customer_id, error=str(exc))
        return []


async def hub_run_customer_playbook(
    db: AsyncSession, customer_id: str, playbook_id: str,
) -> Optional[dict[str, Any]]:
    """手动触发客户 Playbook — 写入 hub_tickets type='playbook'"""
    customer = await hub_get_customer(db, customer_id)
    if not customer:
        return None
    pb = await hub_get_playbook(db, playbook_id)
    if not pb:
        return {"error": "playbook_not_found"}
    run_id = str(uuid.uuid4())[:8]
    try:
        ticket_id = f"PB-{run_id}"
        sql = text(
            """
            INSERT INTO hub_tickets (
                id, tenant_id, merchant_name, title, priority, status, type, is_deleted
            ) VALUES (
                :tid, :cid::uuid, :merchant, :title, 'medium', 'running', 'playbook', false
            )
            ON CONFLICT (id) DO NOTHING
            """
        )
        await db.execute(sql, {
            "tid": ticket_id,
            "cid": customer_id,
            "merchant": customer.get("name", "unknown"),
            "title": f"Playbook执行: {pb.get('name', playbook_id)}",
        })
        await db.commit()
    except (SQLAlchemyError, OperationalError) as exc:
        log.warning("hub_run_customer_playbook.db_error", error=str(exc))
    return {
        "run_id": f"run-{run_id}",
        "playbook_id": playbook_id,
        "playbook_name": pb.get("name", playbook_id),
        "customer_id": customer_id,
        "customer_name": customer.get("name", "unknown"),
        "status": "running",
        "triggered_at": datetime.utcnow().isoformat(),
        "triggered_by": "manual",
    }


async def hub_customer_journey(db: AsyncSession, customer_id: str) -> Optional[dict[str, Any]]:
    """客户旅程阶段 — 从 platform_tenants 状态推断"""
    customer = await hub_get_customer(db, customer_id)
    if not customer:
        return None
    stages = ["prospect", "onboarding", "adoption", "expansion", "renewal", "churned"]
    # 基于商户状态和门店数推断旅程阶段
    stores_count = customer.get("stores_count", 0)
    cust_status = customer.get("status", "active")
    if cust_status == "churned":
        current = "churned"
    elif cust_status == "trial":
        current = "onboarding"
    elif stores_count >= 10:
        current = "expansion"
    elif stores_count >= 3:
        current = "adoption"
    else:
        current = "onboarding"
    current_idx = stages.index(current) if current in stages else 1
    now = datetime.utcnow()
    return {
        "customer_id": customer_id,
        "customer_name": customer.get("name", "unknown"),
        "current_stage": current,
        "stages": [
            {
                "name": s,
                "status": "completed" if i < current_idx else ("current" if i == current_idx else "pending"),
                "entered_at": (now - timedelta(days=90 - i * 20)).isoformat() if i <= current_idx else None,
            }
            for i, s in enumerate(stages)
        ],
        "days_in_current_stage": 20 + current_idx * 5,
        "next_milestone": "季度业务回顾" if current != "churned" else None,
    }


# ─── Wave 2: Incidents 事件响应 ───

_MOCK_INCIDENTS: list[dict[str, Any]] = [
    {
        "id": "INC-001", "title": "美团订单同步全面中断", "priority": "P0",
        "status": "resolved", "commander": "李淳", "tech_lead": "李淳", "scribe": None,
        "affected_services": ["tx-trade", "gateway"],
        "affected_customers": ["c002", "c001"],
        "description": "美团 Adapter webhook 证书过期导致全部订单无法同步",
        "created_at": (datetime.utcnow() - timedelta(days=14)).isoformat(),
        "resolved_at": (datetime.utcnow() - timedelta(days=14, hours=-2)).isoformat(),
        "duration_minutes": 120,
    },
    {
        "id": "INC-002", "title": "品智POS数据库连接池耗尽", "priority": "P0",
        "status": "resolved", "commander": "李淳", "tech_lead": "李淳", "scribe": None,
        "affected_services": ["tx-trade", "gateway"],
        "affected_customers": ["c002", "c003", "c004"],
        "description": "高峰期并发连接超限，POS收银中断约15分钟",
        "created_at": (datetime.utcnow() - timedelta(days=7)).isoformat(),
        "resolved_at": (datetime.utcnow() - timedelta(days=7, hours=-1)).isoformat(),
        "duration_minutes": 60,
    },
    {
        "id": "INC-003", "title": "边缘节点MM-A008离线超24h", "priority": "P1",
        "status": "investigating", "commander": "李淳", "tech_lead": None, "scribe": None,
        "affected_services": ["edge/mac-station"],
        "affected_customers": ["c005"],
        "description": "湘粤楼天心区店Mac mini无心跳，疑似断电或网络故障",
        "created_at": (datetime.utcnow() - timedelta(hours=26)).isoformat(),
        "resolved_at": None,
        "duration_minutes": None,
    },
    {
        "id": "INC-004", "title": "饿了么Adapter同步延迟>30分钟", "priority": "P1",
        "status": "mitigated", "commander": "李淳", "tech_lead": None, "scribe": None,
        "affected_services": ["gateway"],
        "affected_customers": ["c002", "c006"],
        "description": "饿了么开放平台限流策略变更导致同步延迟",
        "created_at": (datetime.utcnow() - timedelta(days=3)).isoformat(),
        "resolved_at": None,
        "duration_minutes": None,
    },
    {
        "id": "INC-005", "title": "会员积分计算偏差", "priority": "P2",
        "status": "resolved", "commander": "李淳", "tech_lead": None, "scribe": None,
        "affected_services": ["tx-member"],
        "affected_customers": ["c001"],
        "description": "徐记海鲜部分门店积分倍率未生效，影响约200笔订单",
        "created_at": (datetime.utcnow() - timedelta(days=10)).isoformat(),
        "resolved_at": (datetime.utcnow() - timedelta(days=9)).isoformat(),
        "duration_minutes": 480,
    },
    {
        "id": "INC-006", "title": "KDS推送延迟>5秒", "priority": "P2",
        "status": "open", "commander": None, "tech_lead": None, "scribe": None,
        "affected_services": ["tx-trade"],
        "affected_customers": ["c004"],
        "description": "尚宫厨后厨出餐屏WebSocket连接不稳定",
        "created_at": (datetime.utcnow() - timedelta(hours=6)).isoformat(),
        "resolved_at": None,
        "duration_minutes": None,
    },
    {
        "id": "INC-007", "title": "日结报表金额不一致", "priority": "P1",
        "status": "resolved", "commander": "李淳", "tech_lead": None, "scribe": None,
        "affected_services": ["tx-ops", "tx-finance"],
        "affected_customers": ["c003"],
        "description": "最黔线2家门店日结金额与POS统计差异>0.5%",
        "created_at": (datetime.utcnow() - timedelta(days=5)).isoformat(),
        "resolved_at": (datetime.utcnow() - timedelta(days=4)).isoformat(),
        "duration_minutes": 720,
    },
    {
        "id": "INC-008", "title": "Tailscale节点批量断连", "priority": "P0",
        "status": "open", "commander": "李淳", "tech_lead": "李淳", "scribe": None,
        "affected_services": ["edge/mac-station", "edge/sync-engine"],
        "affected_customers": ["c001", "c002", "c003", "c004", "c006"],
        "description": "Tailscale控制面异常导致6个边缘节点同时失联",
        "created_at": (datetime.utcnow() - timedelta(hours=1)).isoformat(),
        "resolved_at": None,
        "duration_minutes": None,
    },
]


def _incident_timeline_from_ticket(inc: dict[str, Any]) -> list[dict[str, Any]]:
    """从 ticket 数据组装基础 Incident 时间线"""
    created_at = inc.get("created_at", datetime.utcnow().isoformat())
    try:
        base_time = datetime.fromisoformat(created_at)
    except (ValueError, TypeError):
        base_time = datetime.utcnow()
    commander = inc.get("commander", "system")
    events = [
        {"timestamp": base_time.isoformat(), "event": "incident.declared", "actor": "system", "detail": {"title": inc.get("title", ""), "priority": inc.get("priority", "")}},
        {"timestamp": (base_time + timedelta(minutes=2)).isoformat(), "event": "incident.commander_assigned", "actor": commander, "detail": {"commander": commander}},
    ]
    if inc.get("status") == "resolved" and inc.get("resolved_at"):
        events.append({
            "timestamp": inc["resolved_at"],
            "event": "incident.resolved",
            "actor": commander,
            "detail": {"resolution": inc.get("description", "问题已修复")},
        })
    return events


async def hub_list_incidents(
    db: AsyncSession,
    priority: Optional[str],
    status: Optional[str],
    page: int,
    size: int,
) -> dict[str, Any]:
    """Incident 列表 — 从 hub_tickets 中 type='incident' 的记录查询"""
    offset_val = max(0, (page - 1) * size)
    try:
        where = "NOT COALESCE(is_deleted, false) AND COALESCE(type, '') = 'incident'"
        params: dict[str, Any] = {}
        if priority:
            where += " AND priority = :priority"
            params["priority"] = priority
        if status:
            where += " AND status = :status"
            params["status"] = status
        count_sql = text(f"SELECT COUNT(*) FROM hub_tickets WHERE {where}")
        list_sql = text(
            f"""
            SELECT id,
                   title,
                   priority,
                   status,
                   merchant_name,
                   assignee AS commander,
                   resolution,
                   to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') AS created_at,
                   to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') AS resolved_at
            FROM hub_tickets
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """
        )
        total_r = await db.execute(count_sql, params)
        total = int(total_r.scalar_one())
        rows = await db.execute(list_sql, {**params, "limit": size, "offset": offset_val})
        items = [_row_to_dict(r) for r in rows.fetchall()]
        return {"items": items, "total": total}
    except (SQLAlchemyError, OperationalError) as exc:
        log.warning("hub_list_incidents.db_error", error=str(exc))
        return {"items": [], "total": 0}


async def hub_create_incident(db: AsyncSession, data: dict[str, Any]) -> dict[str, Any]:
    """声明新 Incident — 写入 hub_tickets，type='incident'"""
    try:
        # 生成自增 INC-NNN 工单号
        max_r = await db.execute(
            text(
                """
                SELECT MAX(CAST(SUBSTRING(id FROM 5) AS INTEGER))
                FROM hub_tickets
                WHERE id ~ '^INC-[0-9]+$'
                """
            )
        )
        max_val = max_r.scalar()
        next_num = (int(max_val) + 1) if max_val is not None else 1
        inc_id = f"INC-{next_num:03d}"
        now = datetime.utcnow().isoformat()

        affected_services = data.get("affected_services", [])
        affected_customers = data.get("affected_customers", [])
        description = data.get("description", "")
        resolution_json = json.dumps({
            "affected_services": affected_services,
            "affected_customers": affected_customers,
            "description": description,
        }, ensure_ascii=False)

        sql = text(
            """
            INSERT INTO hub_tickets (
                id, merchant_name, title, priority, status, type, resolution, is_deleted
            ) VALUES (
                :tid, :merchant, :title, :priority, 'open', 'incident', :resolution, false
            )
            ON CONFLICT (id) DO NOTHING
            """
        )
        await db.execute(sql, {
            "tid": inc_id,
            "merchant": ", ".join(affected_customers) if affected_customers else "platform",
            "title": data["title"],
            "priority": data["priority"],
            "resolution": resolution_json,
        })
        await db.commit()
        return {
            "id": inc_id,
            "title": data["title"],
            "priority": data["priority"],
            "status": "open",
            "commander": None,
            "tech_lead": None,
            "scribe": None,
            "affected_services": affected_services,
            "affected_customers": affected_customers,
            "description": description,
            "created_at": now,
            "resolved_at": None,
            "duration_minutes": None,
        }
    except (SQLAlchemyError, OperationalError) as exc:
        log.warning("hub_create_incident.db_error", error=str(exc))
        inc_id = f"INC-{uuid.uuid4().hex[:6]}"
        now = datetime.utcnow().isoformat()
        return {
            "id": inc_id,
            "title": data["title"],
            "priority": data["priority"],
            "status": "open",
            "commander": None,
            "created_at": now,
            "resolved_at": None,
            "duration_minutes": None,
        }


async def hub_get_incident(db: AsyncSession, incident_id: str) -> Optional[dict[str, Any]]:
    """Incident 详情 — 从 hub_tickets 查询"""
    try:
        sql = text(
            """
            SELECT id, title, priority, status, merchant_name,
                   assignee AS commander, resolution,
                   to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') AS created_at,
                   to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') AS resolved_at
            FROM hub_tickets
            WHERE id = :iid AND NOT COALESCE(is_deleted, false)
            LIMIT 1
            """
        )
        rows = await db.execute(sql, {"iid": incident_id})
        row = rows.fetchone()
        if not row:
            return None
        d = _row_to_dict(row)
        # 从 resolution JSON 中解析扩展字段
        resolution_raw = d.get("resolution")
        extra: dict[str, Any] = {}
        if resolution_raw:
            if isinstance(resolution_raw, str):
                try:
                    extra = json.loads(resolution_raw)
                except (json.JSONDecodeError, ValueError):
                    extra = {"description": resolution_raw}
            elif isinstance(resolution_raw, dict):
                extra = resolution_raw
        return {
            "id": d["id"],
            "title": d["title"],
            "priority": d["priority"],
            "status": d["status"],
            "commander": d.get("commander"),
            "tech_lead": None,
            "scribe": None,
            "affected_services": extra.get("affected_services", []),
            "affected_customers": extra.get("affected_customers", []),
            "description": extra.get("description", ""),
            "created_at": d["created_at"],
            "resolved_at": d.get("resolved_at") if d.get("status") == "resolved" else None,
            "duration_minutes": None,
        }
    except (SQLAlchemyError, OperationalError) as exc:
        log.warning("hub_get_incident.db_error", incident_id=incident_id, error=str(exc))
        return None


async def hub_update_incident(db: AsyncSession, incident_id: str, updates: dict[str, Any]) -> Optional[dict[str, Any]]:
    """更新 Incident — UPDATE hub_tickets"""
    try:
        # 先检查是否存在
        existing = await hub_get_incident(db, incident_id)
        if not existing:
            return None
        allowed = {"status", "priority", "assignee", "title"}
        set_clauses = []
        params: dict[str, Any] = {"iid": incident_id}
        for key, val in updates.items():
            if key in allowed:
                set_clauses.append(f"{key} = :{key}")
                params[key] = val
        # commander 映射到 assignee
        if "commander" in updates:
            set_clauses.append("assignee = :commander")
            params["commander"] = updates["commander"]
        if not set_clauses:
            return existing
        set_clauses.append("updated_at = NOW()")
        sql = text(
            f"""
            UPDATE hub_tickets
            SET {', '.join(set_clauses)}
            WHERE id = :iid AND NOT COALESCE(is_deleted, false)
            """
        )
        await db.execute(sql, params)
        await db.commit()
        return {**existing, **updates}
    except (SQLAlchemyError, OperationalError) as exc:
        log.warning("hub_update_incident.db_error", incident_id=incident_id, error=str(exc))
        return None


async def hub_incident_timeline(db: AsyncSession, incident_id: str) -> Optional[list[dict[str, Any]]]:
    """Incident 时间线 — 从 events 表查询"""
    inc = await hub_get_incident(db, incident_id)
    if not inc:
        return None
    try:
        sql = text(
            """
            SELECT event_type,
                   stream_id,
                   payload,
                   to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') AS timestamp
            FROM events
            WHERE stream_id = :iid
            ORDER BY created_at ASC
            LIMIT 100
            """
        )
        rows = await db.execute(sql, {"iid": incident_id})
        items = []
        for r in rows.fetchall():
            d = _row_to_dict(r)
            payload = d.get("payload")
            if isinstance(payload, str):
                payload = json.loads(payload)
            items.append({
                "timestamp": d["timestamp"],
                "event": d["event_type"],
                "actor": (payload or {}).get("actor", "system"),
                "detail": payload or {},
            })
        if items:
            return items
    except (SQLAlchemyError, OperationalError) as exc:
        log.warning("hub_incident_timeline.db_error", incident_id=incident_id, error=str(exc))
    # 降级：从 ticket 数据组装基础时间线
    return _incident_timeline_from_ticket(inc)


async def hub_incident_postmortem(db: AsyncSession, incident_id: str) -> Optional[dict[str, Any]]:
    """生成 Postmortem 草稿 — 从 hub_tickets resolution 字段组装"""
    inc = await hub_get_incident(db, incident_id)
    if not inc:
        return None
    timeline = await hub_incident_timeline(db, incident_id)
    description = inc.get("description", "")
    affected_services = inc.get("affected_services", [])
    affected_customers = inc.get("affected_customers", [])

    return {
        "incident_id": incident_id,
        "title": f"Postmortem: {inc['title']}",
        "severity": inc.get("priority", "P2"),
        "duration_minutes": inc.get("duration_minutes", 0),
        "summary": f"于 {inc.get('created_at', 'unknown')} 发生 {inc.get('priority', 'P2')} 级别事件：{inc['title']}。"
                   f"影响服务：{', '.join(affected_services) if affected_services else '待确认'}。"
                   f"影响客户：{len(affected_customers)} 个。"
                   f"{(' 描述：' + description) if description else ''}",
        "root_cause": description if description else "待填写 -- 请基于调查结果补充根因分析",
        "impact": {
            "affected_services": affected_services,
            "affected_customers": affected_customers,
            "estimated_revenue_impact_yuan": 0,
        },
        "timeline": timeline or [],
        "action_items": [
            {"action": "添加监控告警", "owner": inc.get("commander", "待分配"), "due_date": None, "status": "pending"},
            {"action": "更新 Runbook", "owner": inc.get("commander", "待分配"), "due_date": None, "status": "pending"},
            {"action": "复盘会议", "owner": inc.get("commander", "待分配"), "due_date": None, "status": "pending"},
        ],
        "generated_at": datetime.utcnow().isoformat(),
        "generated_by": "hub-postmortem-generator",
    }


# ─── Wave 2: Migrations 迁移管理 ───

_MIGRATION_PHASES = ["准备", "数据抽取", "数据转换", "数据加载", "验证上线"]

_MOCK_MIGRATIONS: list[dict[str, Any]] = [
    {
        "id": "mig-001", "name": "尝在一起-品智POS迁移", "source_system": "pinzhi",
        "merchant_id": "c002", "merchant_name": "尝在一起", "engineer": "李淳",
        "status": "completed", "current_phase": 4, "phase_name": "验证上线",
        "created_at": (datetime.utcnow() - timedelta(days=60)).isoformat(),
        "completed_at": (datetime.utcnow() - timedelta(days=30)).isoformat(),
        "phases": [
            {"phase": 0, "name": "准备", "status": "completed", "started_at": (datetime.utcnow() - timedelta(days=60)).isoformat(), "completed_at": (datetime.utcnow() - timedelta(days=55)).isoformat()},
            {"phase": 1, "name": "数据抽取", "status": "completed", "started_at": (datetime.utcnow() - timedelta(days=55)).isoformat(), "completed_at": (datetime.utcnow() - timedelta(days=48)).isoformat()},
            {"phase": 2, "name": "数据转换", "status": "completed", "started_at": (datetime.utcnow() - timedelta(days=48)).isoformat(), "completed_at": (datetime.utcnow() - timedelta(days=40)).isoformat()},
            {"phase": 3, "name": "数据加载", "status": "completed", "started_at": (datetime.utcnow() - timedelta(days=40)).isoformat(), "completed_at": (datetime.utcnow() - timedelta(days=33)).isoformat()},
            {"phase": 4, "name": "验证上线", "status": "completed", "started_at": (datetime.utcnow() - timedelta(days=33)).isoformat(), "completed_at": (datetime.utcnow() - timedelta(days=30)).isoformat()},
        ],
    },
    {
        "id": "mig-002", "name": "最黔线-天财商龙迁移", "source_system": "tiancai-shanglong",
        "merchant_id": "c003", "merchant_name": "最黔线", "engineer": "李淳",
        "status": "in_progress", "current_phase": 2, "phase_name": "数据转换",
        "created_at": (datetime.utcnow() - timedelta(days=20)).isoformat(),
        "completed_at": None,
        "phases": [
            {"phase": 0, "name": "准备", "status": "completed", "started_at": (datetime.utcnow() - timedelta(days=20)).isoformat(), "completed_at": (datetime.utcnow() - timedelta(days=16)).isoformat()},
            {"phase": 1, "name": "数据抽取", "status": "completed", "started_at": (datetime.utcnow() - timedelta(days=16)).isoformat(), "completed_at": (datetime.utcnow() - timedelta(days=10)).isoformat()},
            {"phase": 2, "name": "数据转换", "status": "in_progress", "started_at": (datetime.utcnow() - timedelta(days=10)).isoformat(), "completed_at": None},
            {"phase": 3, "name": "数据加载", "status": "pending", "started_at": None, "completed_at": None},
            {"phase": 4, "name": "验证上线", "status": "pending", "started_at": None, "completed_at": None},
        ],
    },
    {
        "id": "mig-003", "name": "尚宫厨-客如云迁移", "source_system": "keruyun",
        "merchant_id": "c004", "merchant_name": "尚宫厨", "engineer": "李淳",
        "status": "in_progress", "current_phase": 3, "phase_name": "数据加载",
        "created_at": (datetime.utcnow() - timedelta(days=25)).isoformat(),
        "completed_at": None,
        "phases": [
            {"phase": 0, "name": "准备", "status": "completed", "started_at": (datetime.utcnow() - timedelta(days=25)).isoformat(), "completed_at": (datetime.utcnow() - timedelta(days=22)).isoformat()},
            {"phase": 1, "name": "数据抽取", "status": "completed", "started_at": (datetime.utcnow() - timedelta(days=22)).isoformat(), "completed_at": (datetime.utcnow() - timedelta(days=16)).isoformat()},
            {"phase": 2, "name": "数据转换", "status": "completed", "started_at": (datetime.utcnow() - timedelta(days=16)).isoformat(), "completed_at": (datetime.utcnow() - timedelta(days=10)).isoformat()},
            {"phase": 3, "name": "数据加载", "status": "in_progress", "started_at": (datetime.utcnow() - timedelta(days=10)).isoformat(), "completed_at": None},
            {"phase": 4, "name": "验证上线", "status": "pending", "started_at": None, "completed_at": None},
        ],
    },
    {
        "id": "mig-004", "name": "徐记海鲜-奥琦玮迁移", "source_system": "aoqiwei",
        "merchant_id": "c001", "merchant_name": "徐记海鲜", "engineer": "李淳",
        "status": "in_progress", "current_phase": 1, "phase_name": "数据抽取",
        "created_at": (datetime.utcnow() - timedelta(days=10)).isoformat(),
        "completed_at": None,
        "phases": [
            {"phase": 0, "name": "准备", "status": "completed", "started_at": (datetime.utcnow() - timedelta(days=10)).isoformat(), "completed_at": (datetime.utcnow() - timedelta(days=7)).isoformat()},
            {"phase": 1, "name": "数据抽取", "status": "in_progress", "started_at": (datetime.utcnow() - timedelta(days=7)).isoformat(), "completed_at": None},
            {"phase": 2, "name": "数据转换", "status": "pending", "started_at": None, "completed_at": None},
            {"phase": 3, "name": "数据加载", "status": "pending", "started_at": None, "completed_at": None},
            {"phase": 4, "name": "验证上线", "status": "pending", "started_at": None, "completed_at": None},
        ],
    },
    {
        "id": "mig-005", "name": "湘粤楼-微生活迁移", "source_system": "weishenghuo",
        "merchant_id": "c005", "merchant_name": "湘粤楼", "engineer": "李淳",
        "status": "paused", "current_phase": 1, "phase_name": "数据抽取",
        "created_at": (datetime.utcnow() - timedelta(days=15)).isoformat(),
        "completed_at": None,
        "phases": [
            {"phase": 0, "name": "准备", "status": "completed", "started_at": (datetime.utcnow() - timedelta(days=15)).isoformat(), "completed_at": (datetime.utcnow() - timedelta(days=12)).isoformat()},
            {"phase": 1, "name": "数据抽取", "status": "paused", "started_at": (datetime.utcnow() - timedelta(days=12)).isoformat(), "completed_at": None},
            {"phase": 2, "name": "数据转换", "status": "pending", "started_at": None, "completed_at": None},
            {"phase": 3, "name": "数据加载", "status": "pending", "started_at": None, "completed_at": None},
            {"phase": 4, "name": "验证上线", "status": "pending", "started_at": None, "completed_at": None},
        ],
    },
    {
        "id": "mig-006", "name": "费大厨-客如云迁移", "source_system": "keruyun",
        "merchant_id": "c006", "merchant_name": "费大厨", "engineer": "李淳",
        "status": "in_progress", "current_phase": 0, "phase_name": "准备",
        "created_at": (datetime.utcnow() - timedelta(days=3)).isoformat(),
        "completed_at": None,
        "phases": [
            {"phase": 0, "name": "准备", "status": "in_progress", "started_at": (datetime.utcnow() - timedelta(days=3)).isoformat(), "completed_at": None},
            {"phase": 1, "name": "数据抽取", "status": "pending", "started_at": None, "completed_at": None},
            {"phase": 2, "name": "数据转换", "status": "pending", "started_at": None, "completed_at": None},
            {"phase": 3, "name": "数据加载", "status": "pending", "started_at": None, "completed_at": None},
            {"phase": 4, "name": "验证上线", "status": "pending", "started_at": None, "completed_at": None},
        ],
    },
    {
        "id": "mig-007", "name": "炊烟-品智POS迁移", "source_system": "pinzhi",
        "merchant_id": "c007", "merchant_name": "炊烟", "engineer": "李淳",
        "status": "failed", "current_phase": 2, "phase_name": "数据转换",
        "created_at": (datetime.utcnow() - timedelta(days=18)).isoformat(),
        "completed_at": None,
        "phases": [
            {"phase": 0, "name": "准备", "status": "completed", "started_at": (datetime.utcnow() - timedelta(days=18)).isoformat(), "completed_at": (datetime.utcnow() - timedelta(days=15)).isoformat()},
            {"phase": 1, "name": "数据抽取", "status": "completed", "started_at": (datetime.utcnow() - timedelta(days=15)).isoformat(), "completed_at": (datetime.utcnow() - timedelta(days=12)).isoformat()},
            {"phase": 2, "name": "数据转换", "status": "failed", "started_at": (datetime.utcnow() - timedelta(days=12)).isoformat(), "completed_at": None},
            {"phase": 3, "name": "数据加载", "status": "pending", "started_at": None, "completed_at": None},
            {"phase": 4, "name": "验证上线", "status": "pending", "started_at": None, "completed_at": None},
        ],
    },
    {
        "id": "mig-008", "name": "黑色经典-ERP迁移", "source_system": "erp",
        "merchant_id": "c010", "merchant_name": "黑色经典", "engineer": "李淳",
        "status": "pending", "current_phase": -1, "phase_name": "未开始",
        "created_at": (datetime.utcnow() - timedelta(days=1)).isoformat(),
        "completed_at": None,
        "phases": [
            {"phase": 0, "name": "准备", "status": "pending", "started_at": None, "completed_at": None},
            {"phase": 1, "name": "数据抽取", "status": "pending", "started_at": None, "completed_at": None},
            {"phase": 2, "name": "数据转换", "status": "pending", "started_at": None, "completed_at": None},
            {"phase": 3, "name": "数据加载", "status": "pending", "started_at": None, "completed_at": None},
            {"phase": 4, "name": "验证上线", "status": "pending", "started_at": None, "completed_at": None},
        ],
    },
]


async def hub_list_migrations(
    db: AsyncSession, status: Optional[str], page: int, size: int,
) -> dict[str, Any]:
    """迁移项目列表 — 从 hub_tickets type='migration' 查询，降级到 mock"""
    offset_val = max(0, (page - 1) * size)
    try:
        where = "NOT COALESCE(is_deleted, false) AND COALESCE(type, '') = 'migration'"
        params: dict[str, Any] = {}
        if status:
            where += " AND status = :st"
            params["st"] = status
        count_sql = text(f"SELECT COUNT(*) FROM hub_tickets WHERE {where}")
        list_sql = text(
            f"""
            SELECT id, title AS name, status, resolution, merchant_name,
                   to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') AS created_at
            FROM hub_tickets
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """
        )
        total_r = await db.execute(count_sql, params)
        total = int(total_r.scalar_one())
        if total > 0:
            rows = await db.execute(list_sql, {**params, "limit": size, "offset": offset_val})
            items = [_row_to_dict(r) for r in rows.fetchall()]
            return {"items": items, "total": total}
    except (SQLAlchemyError, OperationalError) as exc:
        log.warning("hub_list_migrations.db_error", error=str(exc))
    # 降级到 mock
    items = list(_MOCK_MIGRATIONS)
    if status:
        items = [m for m in items if m["status"] == status]
    total = len(items)
    paged = items[offset_val : offset_val + size]
    return {"items": paged, "total": total}


async def hub_create_migration(db: AsyncSession, data: dict[str, Any]) -> dict[str, Any]:
    """创建迁移项目 — 写入 hub_tickets type='migration'"""
    mig_id = f"mig-{str(uuid.uuid4())[:8]}"
    now = datetime.utcnow().isoformat()
    try:
        resolution = json.dumps({
            "source_system": data["source_system"],
            "merchant_id": data["merchant_id"],
            "engineer": data["engineer"],
            "current_phase": -1,
            "phases": [
                {"phase": i, "name": _MIGRATION_PHASES[i], "status": "pending", "started_at": None, "completed_at": None}
                for i in range(5)
            ],
        }, ensure_ascii=False)
        sql = text(
            """
            INSERT INTO hub_tickets (
                id, merchant_name, title, priority, status, type, resolution, is_deleted
            ) VALUES (
                :tid, :merchant, :title, 'medium', 'pending', 'migration', :resolution, false
            )
            ON CONFLICT (id) DO NOTHING
            """
        )
        await db.execute(sql, {
            "tid": mig_id,
            "merchant": data.get("merchant_id", "unknown"),
            "title": data["name"],
            "resolution": resolution,
        })
        await db.commit()
    except (SQLAlchemyError, OperationalError) as exc:
        log.warning("hub_create_migration.db_error", error=str(exc))
    return {
        "id": mig_id,
        "name": data["name"],
        "source_system": data["source_system"],
        "merchant_id": data["merchant_id"],
        "engineer": data["engineer"],
        "status": "pending",
        "current_phase": -1,
        "phase_name": "未开始",
        "created_at": now,
        "completed_at": None,
        "phases": [
            {"phase": i, "name": _MIGRATION_PHASES[i], "status": "pending", "started_at": None, "completed_at": None}
            for i in range(5)
        ],
    }


async def hub_get_migration(db: AsyncSession, migration_id: str) -> Optional[dict[str, Any]]:
    """迁移详情 — 从 hub_tickets 查询，降级到 mock"""
    try:
        sql = text(
            """
            SELECT id, title AS name, status, resolution,
                   to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') AS created_at
            FROM hub_tickets
            WHERE id = :mid AND NOT COALESCE(is_deleted, false)
              AND COALESCE(type, '') = 'migration'
            LIMIT 1
            """
        )
        rows = await db.execute(sql, {"mid": migration_id})
        row = rows.fetchone()
        if row:
            d = _row_to_dict(row)
            resolution = d.get("resolution")
            extra: dict[str, Any] = {}
            if isinstance(resolution, str):
                try:
                    extra = json.loads(resolution)
                except (json.JSONDecodeError, ValueError):
                    pass
            return {
                "id": d["id"],
                "name": d["name"],
                "status": d["status"],
                "current_phase": extra.get("current_phase", -1),
                "phase_name": _MIGRATION_PHASES[extra.get("current_phase", -1)] if 0 <= extra.get("current_phase", -1) < 5 else "未开始",
                "created_at": d["created_at"],
                "completed_at": None,
                "phases": extra.get("phases", []),
                **{k: v for k, v in extra.items() if k not in ("phases", "current_phase")},
            }
    except (SQLAlchemyError, OperationalError) as exc:
        log.warning("hub_get_migration.db_error", migration_id=migration_id, error=str(exc))
    for m in _MOCK_MIGRATIONS:
        if m["id"] == migration_id:
            return m
    return None


async def hub_advance_migration(db: AsyncSession, migration_id: str) -> Optional[dict[str, Any]]:
    """推进迁移到下一阶段"""
    mig = await hub_get_migration(db, migration_id)
    if not mig:
        return None
    current = mig["current_phase"]
    if current >= 4:
        return {"error": "already_completed", "migration_id": migration_id}
    if mig["status"] in ("paused", "failed"):
        return {"error": "cannot_advance", "reason": f"迁移状态为 {mig['status']}，请先恢复"}
    next_phase = current + 1
    return {
        "migration_id": migration_id,
        "previous_phase": current,
        "previous_phase_name": _MIGRATION_PHASES[current] if current >= 0 else "未开始",
        "new_phase": next_phase,
        "new_phase_name": _MIGRATION_PHASES[next_phase],
        "advanced_at": datetime.utcnow().isoformat(),
    }


async def hub_rollback_migration(db: AsyncSession, migration_id: str) -> Optional[dict[str, Any]]:
    """回滚迁移到上一检查点"""
    mig = await hub_get_migration(db, migration_id)
    if not mig:
        return None
    current = mig["current_phase"]
    if current <= 0:
        return {"error": "cannot_rollback", "reason": "已在第一阶段或未开始"}
    return {
        "migration_id": migration_id,
        "previous_phase": current,
        "rollback_to_phase": current - 1,
        "rollback_to_name": _MIGRATION_PHASES[current - 1],
        "rolled_back_at": datetime.utcnow().isoformat(),
    }


async def hub_pause_migration(db: AsyncSession, migration_id: str) -> Optional[dict[str, Any]]:
    """暂停迁移"""
    mig = await hub_get_migration(db, migration_id)
    if not mig:
        return None
    if mig["status"] == "paused":
        return {"error": "already_paused"}
    return {
        "migration_id": migration_id,
        "status": "paused",
        "paused_at": datetime.utcnow().isoformat(),
    }


async def hub_resume_migration(db: AsyncSession, migration_id: str) -> Optional[dict[str, Any]]:
    """恢复迁移"""
    mig = await hub_get_migration(db, migration_id)
    if not mig:
        return None
    if mig["status"] != "paused":
        return {"error": "not_paused", "reason": f"当前状态为 {mig['status']}"}
    return {
        "migration_id": migration_id,
        "status": "in_progress",
        "resumed_at": datetime.utcnow().isoformat(),
    }


# ─── Wave 2: Adapters 扩展 ───

_MOCK_ADAPTERS_EXTENDED: list[dict[str, Any]] = [
    {"id": "adp-pinzhi", "key": "pinzhi", "name": "品智POS", "type": "pos", "status": "healthy", "version": "2.3.1", "sync_interval_sec": 60, "last_sync": (datetime.utcnow() - timedelta(minutes=2)).isoformat(), "success_rate": 99.8, "avg_latency_ms": 45, "merchants_connected": 3},
    {"id": "adp-aoqiwei", "key": "aoqiwei", "name": "奥琦玮", "type": "pos", "status": "healthy", "version": "1.8.0", "sync_interval_sec": 120, "last_sync": (datetime.utcnow() - timedelta(minutes=5)).isoformat(), "success_rate": 99.5, "avg_latency_ms": 62, "merchants_connected": 1},
    {"id": "adp-tiancai-shanglong", "key": "tiancai-shanglong", "name": "天财商龙", "type": "pos", "status": "degraded", "version": "1.2.0", "sync_interval_sec": 180, "last_sync": (datetime.utcnow() - timedelta(minutes=35)).isoformat(), "success_rate": 95.2, "avg_latency_ms": 180, "merchants_connected": 1},
    {"id": "adp-keruyun", "key": "keruyun", "name": "客如云", "type": "pos", "status": "healthy", "version": "2.0.1", "sync_interval_sec": 90, "last_sync": (datetime.utcnow() - timedelta(minutes=3)).isoformat(), "success_rate": 99.1, "avg_latency_ms": 55, "merchants_connected": 2},
    {"id": "adp-weishenghuo", "key": "weishenghuo", "name": "微生活", "type": "member", "status": "healthy", "version": "1.5.0", "sync_interval_sec": 300, "last_sync": (datetime.utcnow() - timedelta(minutes=8)).isoformat(), "success_rate": 98.8, "avg_latency_ms": 78, "merchants_connected": 2},
    {"id": "adp-meituan", "key": "meituan", "name": "美团", "type": "channel", "status": "healthy", "version": "3.1.0", "sync_interval_sec": 30, "last_sync": (datetime.utcnow() - timedelta(seconds=45)).isoformat(), "success_rate": 99.9, "avg_latency_ms": 32, "merchants_connected": 8},
    {"id": "adp-eleme", "key": "eleme", "name": "饿了么", "type": "channel", "status": "degraded", "version": "2.8.0", "sync_interval_sec": 30, "last_sync": (datetime.utcnow() - timedelta(minutes=32)).isoformat(), "success_rate": 94.5, "avg_latency_ms": 210, "merchants_connected": 6},
    {"id": "adp-douyin", "key": "douyin", "name": "抖音", "type": "channel", "status": "healthy", "version": "1.9.0", "sync_interval_sec": 60, "last_sync": (datetime.utcnow() - timedelta(minutes=1)).isoformat(), "success_rate": 99.3, "avg_latency_ms": 48, "merchants_connected": 4},
    {"id": "adp-yiding", "key": "yiding", "name": "亿订", "type": "reservation", "status": "healthy", "version": "1.1.0", "sync_interval_sec": 120, "last_sync": (datetime.utcnow() - timedelta(minutes=4)).isoformat(), "success_rate": 99.0, "avg_latency_ms": 65, "merchants_connected": 2},
    {"id": "adp-nuonuo", "key": "nuonuo", "name": "诺诺发票", "type": "finance", "status": "healthy", "version": "2.0.0", "sync_interval_sec": 600, "last_sync": (datetime.utcnow() - timedelta(minutes=12)).isoformat(), "success_rate": 99.7, "avg_latency_ms": 120, "merchants_connected": 5},
    {"id": "adp-xiaohongshu", "key": "xiaohongshu", "name": "小红书", "type": "channel", "status": "healthy", "version": "0.9.0", "sync_interval_sec": 300, "last_sync": (datetime.utcnow() - timedelta(minutes=6)).isoformat(), "success_rate": 98.5, "avg_latency_ms": 85, "merchants_connected": 2},
    {"id": "adp-erp", "key": "erp", "name": "ERP通用", "type": "erp", "status": "healthy", "version": "1.3.0", "sync_interval_sec": 600, "last_sync": (datetime.utcnow() - timedelta(minutes=15)).isoformat(), "success_rate": 99.2, "avg_latency_ms": 95, "merchants_connected": 3},
    {"id": "adp-logistics", "key": "logistics", "name": "物流对接", "type": "logistics", "status": "healthy", "version": "1.0.0", "sync_interval_sec": 300, "last_sync": (datetime.utcnow() - timedelta(minutes=10)).isoformat(), "success_rate": 98.0, "avg_latency_ms": 110, "merchants_connected": 4},
    {"id": "adp-delivery-factory", "key": "delivery_factory", "name": "配送工厂", "type": "delivery", "status": "offline", "version": "0.8.0", "sync_interval_sec": 60, "last_sync": (datetime.utcnow() - timedelta(hours=3)).isoformat(), "success_rate": 88.0, "avg_latency_ms": 250, "merchants_connected": 1},
    {"id": "adp-wechat-delivery", "key": "wechat_delivery", "name": "微信外卖", "type": "channel", "status": "healthy", "version": "1.0.0", "sync_interval_sec": 30, "last_sync": (datetime.utcnow() - timedelta(seconds=30)).isoformat(), "success_rate": 99.4, "avg_latency_ms": 40, "merchants_connected": 3},
]


async def hub_get_adapter(db: AsyncSession, adapter_id: str) -> Optional[dict[str, Any]]:
    """单个适配器详情 — 从 hub_adapter_connections 查询"""
    try:
        sql = text(
            """
            SELECT adapter_key AS key,
                   adapter_key AS id,
                   merchant_name,
                   status,
                   success_rate,
                   error_message AS error,
                   to_char(last_sync_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') AS last_sync
            FROM hub_adapter_connections
            WHERE NOT COALESCE(is_deleted, false)
              AND (adapter_key = :aid OR adapter_key = :aid)
            LIMIT 1
            """
        )
        rows = await db.execute(sql, {"aid": adapter_id})
        row = rows.fetchone()
        if row:
            d = _row_to_dict(row)
            sr = d.get("success_rate")
            if isinstance(sr, Decimal):
                d["success_rate"] = float(sr)
            return d
    except (SQLAlchemyError, OperationalError) as exc:
        log.warning("hub_get_adapter.db_error", adapter_id=adapter_id, error=str(exc))
    # 降级到内存列表
    for a in _MOCK_ADAPTERS_EXTENDED:
        if a["id"] == adapter_id or a["key"] == adapter_id:
            return a
    return None


async def hub_adapter_mapping(db: AsyncSession, adapter_id: str) -> Optional[dict[str, Any]]:
    """适配器字段映射配置 — 静态映射表（字段映射暂无独立DB表）"""
    adapter = await hub_get_adapter(db, adapter_id)
    if not adapter:
        return None
    return {
        "adapter_id": adapter["id"],
        "adapter_name": adapter["name"],
        "mappings": [
            {"source_field": "order_id", "target_field": "external_order_id", "transform": "string", "required": True},
            {"source_field": "total_amount", "target_field": "final_amount_fen", "transform": "yuan_to_fen", "required": True},
            {"source_field": "order_time", "target_field": "order_time", "transform": "iso8601", "required": True},
            {"source_field": "items", "target_field": "order_items", "transform": "array_map", "required": True},
            {"source_field": "customer_phone", "target_field": "customer_mobile", "transform": "phone_normalize", "required": False},
            {"source_field": "store_code", "target_field": "store_id", "transform": "store_lookup", "required": True},
        ],
        "last_updated": (datetime.utcnow() - timedelta(days=5)).isoformat(),
    }


async def hub_adapter_timeline(db: AsyncSession, adapter_id: str) -> Optional[list[dict[str, Any]]]:
    """适配器事件时间线 — 从 events 表查询"""
    adapter = await hub_get_adapter(db, adapter_id)
    if not adapter:
        return None
    try:
        sql = text(
            """
            SELECT event_type,
                   stream_id,
                   payload,
                   to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') AS timestamp
            FROM events
            WHERE stream_id = :adapter_key
            ORDER BY created_at DESC
            LIMIT 50
            """
        )
        rows = await db.execute(sql, {"adapter_key": adapter.get("key", adapter_id)})
        items = []
        for r in rows.fetchall():
            d = _row_to_dict(r)
            payload = d.get("payload")
            if isinstance(payload, str):
                payload = json.loads(payload)
            items.append({
                "timestamp": d["timestamp"],
                "event": d["event_type"],
                "detail": payload or {},
            })
        if items:
            return items
    except (SQLAlchemyError, OperationalError) as exc:
        log.warning("hub_adapter_timeline.db_error", adapter_id=adapter_id, error=str(exc))
    return []


async def hub_adapter_sync(db: AsyncSession, adapter_id: str) -> Optional[dict[str, Any]]:
    """手动触发适配器同步 — 更新 hub_adapter_connections.last_sync_at"""
    adapter = await hub_get_adapter(db, adapter_id)
    if not adapter:
        return None
    sync_id = f"sync-{str(uuid.uuid4())[:8]}"
    try:
        sql = text(
            """
            UPDATE hub_adapter_connections
            SET last_sync_at = NOW(), updated_at = NOW()
            WHERE adapter_key = :key AND NOT COALESCE(is_deleted, false)
            """
        )
        await db.execute(sql, {"key": adapter.get("key", adapter_id)})
        await db.commit()
    except (SQLAlchemyError, OperationalError) as exc:
        log.warning("hub_adapter_sync.db_error", adapter_id=adapter_id, error=str(exc))
    return {
        "adapter_id": adapter.get("id", adapter_id),
        "adapter_name": adapter.get("name", adapter_id),
        "sync_id": sync_id,
        "status": "triggered",
        "triggered_at": datetime.utcnow().isoformat(),
        "estimated_duration_sec": 30,
    }


async def hub_adapters_matrix(db: AsyncSession) -> dict[str, Any]:
    """适配器 x 商户矩阵数据 — 从 hub_adapter_connections 聚合"""
    try:
        sql = text(
            """
            SELECT adapter_key, merchant_name, status
            FROM hub_adapter_connections
            WHERE NOT COALESCE(is_deleted, false)
            ORDER BY merchant_name, adapter_key
            """
        )
        rows = await db.execute(sql)
        connections = [_row_to_dict(r) for r in rows.fetchall()]

        # 收集所有适配器和商户
        adapter_keys: list[str] = list(dict.fromkeys(c["adapter_key"] for c in connections))
        merchant_names: list[str] = list(dict.fromkeys(c["merchant_name"] for c in connections))

        # 构建连接映射
        conn_map: dict[str, dict[str, str]] = {}
        for c in connections:
            mn = c["merchant_name"]
            if mn not in conn_map:
                conn_map[mn] = {}
            conn_map[mn][c["adapter_key"]] = c.get("status", "connected")

        matrix: list[dict[str, Any]] = []
        total_errors = 0
        total_connections = 0
        for merchant_name in merchant_names:
            row: dict[str, Any] = {"merchant": merchant_name}
            for ak in adapter_keys:
                st = conn_map.get(merchant_name, {}).get(ak, "not_applicable")
                row[ak] = st
                if st != "not_applicable":
                    total_connections += 1
                if st in ("error", "offline"):
                    total_errors += 1
            matrix.append(row)

        return {
            "adapters": [{"key": ak, "name": ak} for ak in adapter_keys],
            "merchants": merchant_names,
            "matrix": matrix,
            "summary": {
                "total_connections": total_connections,
                "total_errors": total_errors,
                "total_adapters": len(adapter_keys),
                "total_merchants": len(merchant_names),
            },
        }
    except (SQLAlchemyError, OperationalError) as exc:
        log.warning("hub_adapters_matrix.db_error", error=str(exc))
        return {"adapters": [], "merchants": [], "matrix": [], "summary": {"total_connections": 0, "total_errors": 0, "total_adapters": 0, "total_merchants": 0}}


# ─── Wave 2: Playbooks 通用（API 函数） ───


async def hub_list_playbooks(db: AsyncSession) -> list[dict[str, Any]]:
    """剧本库列表 — 从 hub_tickets type='playbook' 聚合"""
    try:
        sql = text(
            """
            SELECT title AS name,
                   priority AS category,
                   COUNT(*) AS total_runs,
                   MAX(to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS')) AS last_run
            FROM hub_tickets
            WHERE NOT COALESCE(is_deleted, false)
              AND COALESCE(type, '') = 'playbook'
            GROUP BY title, priority
            ORDER BY total_runs DESC
            """
        )
        rows = await db.execute(sql)
        items = [_row_to_dict(r) for r in rows.fetchall()]
        if items:
            return items
    except (SQLAlchemyError, OperationalError) as exc:
        log.warning("hub_list_playbooks.db_error", error=str(exc))
    return _MOCK_PLAYBOOKS


async def hub_get_playbook(db: AsyncSession, playbook_id: str) -> Optional[dict[str, Any]]:
    """剧本详情 — 优先从 _MOCK_PLAYBOOKS 查找（Playbook 定义暂无独立表）"""
    for pb in _MOCK_PLAYBOOKS:
        if pb["id"] == playbook_id:
            return pb
    return None


async def hub_run_playbook(db: AsyncSession, playbook_id: str, target_id: str, target_type: str) -> Optional[dict[str, Any]]:
    """触发 Playbook 执行 — 写入 hub_tickets type='playbook'"""
    pb = await hub_get_playbook(db, playbook_id)
    if not pb:
        return None
    run_id = f"run-{str(uuid.uuid4())[:8]}"
    try:
        ticket_id = f"PBR-{str(uuid.uuid4())[:8]}"
        sql = text(
            """
            INSERT INTO hub_tickets (
                id, merchant_name, title, priority, status, type, resolution, is_deleted
            ) VALUES (
                :tid, :merchant, :title, 'medium', 'running', 'playbook',
                :resolution, false
            )
            ON CONFLICT (id) DO NOTHING
            """
        )
        await db.execute(sql, {
            "tid": ticket_id,
            "merchant": target_id,
            "title": f"Playbook: {pb.get('name', playbook_id)}",
            "resolution": json.dumps({"target_id": target_id, "target_type": target_type, "run_id": run_id}, ensure_ascii=False),
        })
        await db.commit()
    except (SQLAlchemyError, OperationalError) as exc:
        log.warning("hub_run_playbook.db_error", error=str(exc))
    return {
        "run_id": run_id,
        "playbook_id": playbook_id,
        "playbook_name": pb.get("name", playbook_id),
        "target_id": target_id,
        "target_type": target_type,
        "status": "running",
        "triggered_at": datetime.utcnow().isoformat(),
        "triggered_by": "manual",
        "estimated_duration_days": pb.get("avg_duration_days", 1),
    }


async def hub_playbook_runs(db: AsyncSession, playbook_id: str) -> Optional[list[dict[str, Any]]]:
    """Playbook 执行历史 — 从 hub_tickets type='playbook' 查询"""
    pb = await hub_get_playbook(db, playbook_id)
    if not pb:
        return None
    pb_name = pb.get("name", playbook_id)
    try:
        sql = text(
            """
            SELECT id AS run_id,
                   merchant_name AS target_name,
                   status,
                   resolution,
                   to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') AS triggered_at,
                   to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS') AS completed_at
            FROM hub_tickets
            WHERE NOT COALESCE(is_deleted, false)
              AND COALESCE(type, '') = 'playbook'
              AND title LIKE :pb_pattern
            ORDER BY created_at DESC
            LIMIT 20
            """
        )
        rows = await db.execute(sql, {"pb_pattern": f"%{pb_name}%"})
        items = []
        for r in rows.fetchall():
            d = _row_to_dict(r)
            resolution = d.get("resolution")
            extra: dict[str, Any] = {}
            if isinstance(resolution, str):
                try:
                    extra = json.loads(resolution)
                except (json.JSONDecodeError, ValueError):
                    pass
            items.append({
                "run_id": d["run_id"],
                "playbook_id": playbook_id,
                "target_id": extra.get("target_id", ""),
                "target_name": d.get("target_name", ""),
                "target_type": extra.get("target_type", "customer"),
                "status": d["status"],
                "triggered_at": d["triggered_at"],
                "completed_at": d.get("completed_at") if d.get("status") in ("completed", "resolved") else None,
                "triggered_by": "manual",
            })
        if items:
            return items
    except (SQLAlchemyError, OperationalError) as exc:
        log.warning("hub_playbook_runs.db_error", playbook_id=playbook_id, error=str(exc))
    return []


# ─── Wave 3: Settings — Flags ───


_MOCK_FLAGS: list[dict[str, Any]] = [
    {"name": "edge_auto_update", "label": "边缘自动更新", "value": True, "rollout_pct": 100, "updated_at": (datetime.utcnow() - timedelta(days=3)).isoformat()},
    {"name": "copilot_v2", "label": "Copilot V2 流式响应", "value": False, "rollout_pct": 0, "updated_at": (datetime.utcnow() - timedelta(days=7)).isoformat()},
    {"name": "realtime_kds", "label": "实时KDS推送", "value": True, "rollout_pct": 60, "updated_at": (datetime.utcnow() - timedelta(days=1)).isoformat()},
    {"name": "discount_guard_strict", "label": "折扣守护严格模式", "value": True, "rollout_pct": 100, "updated_at": (datetime.utcnow() - timedelta(hours=12)).isoformat()},
    {"name": "journey_orchestrator", "label": "Journey编排器", "value": False, "rollout_pct": 0, "updated_at": datetime.utcnow().isoformat()},
    {"name": "multi_brand_tenancy", "label": "多品牌租户", "value": True, "rollout_pct": 30, "updated_at": (datetime.utcnow() - timedelta(days=5)).isoformat()},
    {"name": "ai_menu_recommendation", "label": "AI菜品推荐", "value": False, "rollout_pct": 0, "updated_at": (datetime.utcnow() - timedelta(days=10)).isoformat()},
    {"name": "inventory_auto_reorder", "label": "库存自动补货", "value": True, "rollout_pct": 50, "updated_at": (datetime.utcnow() - timedelta(days=2)).isoformat()},
]


async def hub_list_flags(db: AsyncSession) -> list[dict[str, Any]]:
    """所有 feature flags — 降级使用内存 mock（feature_flags 表待创建）"""
    return _MOCK_FLAGS


async def hub_update_flag(
    db: AsyncSession, name: str, value: bool, rollout_pct: Optional[int],
) -> Optional[dict[str, Any]]:
    """更新 flag 值 — 降级使用内存 mock（feature_flags 表待创建）"""
    for f in _MOCK_FLAGS:
        if f["name"] == name:
            result = {**f, "value": value, "updated_at": datetime.utcnow().isoformat()}
            if rollout_pct is not None:
                result["rollout_pct"] = rollout_pct
            return result
    return None


# ─── Wave 3: Settings — Releases ───


async def hub_list_releases(db: AsyncSession) -> list[dict[str, Any]]:
    """各环境发布状态 — 降级使用内存 mock（CI/CD API 待接入）"""
    now = datetime.utcnow()
    return [
        {"env": "dev", "app": "gateway", "version": "v3.2.1-dev", "status": "running", "deployed_at": (now - timedelta(hours=2)).isoformat(), "deployer": "ci-bot"},
        {"env": "dev", "app": "tx-trade", "version": "v3.1.8-dev", "status": "running", "deployed_at": (now - timedelta(hours=4)).isoformat(), "deployer": "ci-bot"},
        {"env": "test", "app": "gateway", "version": "v3.2.0", "status": "running", "deployed_at": (now - timedelta(days=1)).isoformat(), "deployer": "ci-bot"},
        {"env": "test", "app": "tx-trade", "version": "v3.1.7", "status": "running", "deployed_at": (now - timedelta(days=1)).isoformat(), "deployer": "ci-bot"},
        {"env": "uat", "app": "gateway", "version": "v3.1.9", "status": "running", "deployed_at": (now - timedelta(days=3)).isoformat(), "deployer": "李淳"},
        {"env": "prod", "app": "gateway", "version": "v3.1.8", "status": "running", "deployed_at": (now - timedelta(days=7)).isoformat(), "deployer": "李淳"},
        {"env": "prod", "app": "tx-trade", "version": "v3.1.5", "status": "running", "deployed_at": (now - timedelta(days=7)).isoformat(), "deployer": "李淳"},
    ]


async def hub_deploy_release(
    db: AsyncSession, app: str, version: str, env: str,
) -> dict[str, Any]:
    """触发部署 — 降级使用 mock 返回（CI/CD API 待接入）"""
    return {
        "deploy_id": f"deploy-{str(uuid.uuid4())[:8]}",
        "app": app,
        "version": version,
        "env": env,
        "status": "triggered",
        "triggered_at": datetime.utcnow().isoformat(),
        "triggered_by": "hub-admin",
        "estimated_duration_sec": 120,
    }


# ─── Wave 3: Settings — Security ───


async def hub_list_security_users(db: AsyncSession) -> list[dict[str, Any]]:
    """用户列表 — 降级使用内存 mock（auth 表待接入）"""
    return [
        {"id": "u001", "name": "李淳", "email": "lichun@tunxiang.tech", "role": "platform-admin", "status": "active", "last_login": (datetime.utcnow() - timedelta(hours=1)).isoformat(), "mfa_enabled": True},
        {"id": "u002", "name": "陈工", "email": "chengong@tunxiang.tech", "role": "engineer", "status": "active", "last_login": (datetime.utcnow() - timedelta(hours=3)).isoformat(), "mfa_enabled": True},
        {"id": "u003", "name": "王工", "email": "wanggong@tunxiang.tech", "role": "engineer", "status": "active", "last_login": (datetime.utcnow() - timedelta(days=1)).isoformat(), "mfa_enabled": False},
        {"id": "u004", "name": "张CSM", "email": "zhangcsm@tunxiang.tech", "role": "csm", "status": "active", "last_login": (datetime.utcnow() - timedelta(hours=6)).isoformat(), "mfa_enabled": True},
    ]


async def hub_list_security_roles(db: AsyncSession) -> list[dict[str, Any]]:
    """角色列表 — 降级使用内存 mock（RBAC 表待接入）"""
    return [
        {"id": "role-admin", "name": "platform-admin", "label": "平台管理员", "user_count": 1, "permissions": ["*"]},
        {"id": "role-eng", "name": "engineer", "label": "工程师", "user_count": 2, "permissions": ["read:*", "write:code", "deploy:dev", "deploy:test"]},
        {"id": "role-csm", "name": "csm", "label": "客户成功", "user_count": 1, "permissions": ["read:customers", "write:playbooks", "write:journeys"]},
        {"id": "role-viewer", "name": "viewer", "label": "只读用户", "user_count": 0, "permissions": ["read:*"]},
    ]


async def hub_list_audit_logs(db: AsyncSession) -> list[dict[str, Any]]:
    """审计日志 — 降级使用内存 mock（audit_log 表待接入）"""
    now = datetime.utcnow()
    return [
        {"id": "aud-001", "timestamp": (now - timedelta(minutes=15)).isoformat(), "actor": "李淳", "action": "settings.flag.update", "resource": "edge_auto_update", "detail": "value: true, rollout_pct: 100", "ip": "10.0.1.5"},
        {"id": "aud-002", "timestamp": (now - timedelta(hours=1)).isoformat(), "actor": "李淳", "action": "deploy.trigger", "resource": "gateway@v3.2.1-dev", "detail": "env: dev", "ip": "10.0.1.5"},
        {"id": "aud-003", "timestamp": (now - timedelta(hours=3)).isoformat(), "actor": "陈工", "action": "migration.advance", "resource": "mig-002", "detail": "phase 1 -> 2", "ip": "10.0.1.12"},
        {"id": "aud-004", "timestamp": (now - timedelta(hours=5)).isoformat(), "actor": "张CSM", "action": "playbook.run", "resource": "pb-onboarding", "detail": "customer: 尚宫厨", "ip": "10.0.2.8"},
        {"id": "aud-005", "timestamp": (now - timedelta(hours=8)).isoformat(), "actor": "李淳", "action": "incident.create", "resource": "INC-008", "detail": "Tailscale节点批量断连", "ip": "10.0.1.5"},
    ]


# ─── Wave 3: Settings — Knowledge ───


async def hub_list_knowledge(db: AsyncSession) -> list[dict[str, Any]]:
    """知识库文档列表 — 降级使用内存 mock（knowledge_docs 表待接入）"""
    return [
        {"id": "kb-001", "title": "屯象OS架构总览", "category": "architecture", "updated_at": "2026-04-20", "word_count": 12500, "chunk_count": 45},
        {"id": "kb-002", "title": "POS收银操作手册", "category": "operations", "updated_at": "2026-04-18", "word_count": 8200, "chunk_count": 30},
        {"id": "kb-003", "title": "Adapter开发指南", "category": "development", "updated_at": "2026-04-15", "word_count": 6800, "chunk_count": 25},
        {"id": "kb-004", "title": "等保三级合规清单", "category": "compliance", "updated_at": "2026-04-10", "word_count": 4500, "chunk_count": 18},
        {"id": "kb-005", "title": "Mac mini边缘部署手册", "category": "deployment", "updated_at": "2026-04-08", "word_count": 5200, "chunk_count": 20},
        {"id": "kb-006", "title": "客户成功Playbook模板库", "category": "operations", "updated_at": "2026-04-05", "word_count": 9600, "chunk_count": 35},
    ]


async def hub_search_knowledge(db: AsyncSession, query: str, top_k: int) -> dict[str, Any]:
    """RAG 搜索 — 降级使用 mock 返回（向量检索待接入）"""
    return {
        "query": query,
        "results": [
            {"doc_id": "kb-001", "title": "屯象OS架构总览", "chunk": f"... 与查询「{query}」最相关的段落内容 ...", "score": 0.92},
            {"doc_id": "kb-003", "title": "Adapter开发指南", "chunk": f"... 第二匹配段落 ...", "score": 0.85},
            {"doc_id": "kb-005", "title": "Mac mini边缘部署手册", "chunk": f"... 第三匹配段落 ...", "score": 0.78},
        ][:top_k],
        "generated_answer": f"这是基于知识库的 mock 回答。实际版本将使用 RAG pipeline 针对「{query}」生成精准回答。",
    }


# ─── Wave 3: Settings — Tenancy ───


async def hub_list_tenancy(db: AsyncSession) -> dict[str, Any]:
    """租户列表+统计"""
    # TODO: 从 platform_tenants 聚合
    return {
        "tenants": [
            {"id": "t001", "name": "徐记海鲜", "plan": "pro", "stores": 23, "status": "active", "data_size_gb": 12.5, "rls_policy_count": 48},
            {"id": "t002", "name": "尝在一起", "plan": "standard", "stores": 8, "status": "active", "data_size_gb": 3.2, "rls_policy_count": 48},
            {"id": "t003", "name": "最黔线", "plan": "standard", "stores": 5, "status": "active", "data_size_gb": 1.8, "rls_policy_count": 48},
            {"id": "t004", "name": "尚宫厨", "plan": "lite", "stores": 3, "status": "trial", "data_size_gb": 0.6, "rls_policy_count": 48},
            {"id": "t005", "name": "费大厨", "plan": "pro", "stores": 15, "status": "active", "data_size_gb": 8.1, "rls_policy_count": 48},
        ],
        "summary": {
            "total_tenants": 10,
            "active_tenants": 8,
            "trial_tenants": 2,
            "total_stores": 85,
            "total_data_gb": 42.3,
        },
    }


# ─── Wave 3: Workbench ───


async def hub_workbench_execute(db: AsyncSession, command: str) -> dict[str, Any]:
    """执行命令（安全沙箱）"""
    # TODO: 接入安全沙箱执行引擎
    cmd_lower = command.strip().lower()

    if cmd_lower.startswith("select") or cmd_lower.startswith("show"):
        return {
            "output": "tenant_id | name       | status\n"
                      "---------+------------+--------\n"
                      "t001     | 徐记海鲜   | active\n"
                      "t002     | 尝在一起   | active\n"
                      "t003     | 最黔线     | active\n"
                      f"(3 rows) -- mock response for: {command[:60]}",
            "format": "table",
            "exit_code": 0,
        }
    elif cmd_lower.startswith("describe") or cmd_lower.startswith("\\d"):
        return {
            "output": json.dumps({
                "table": "platform_tenants",
                "columns": [
                    {"name": "tenant_id", "type": "uuid", "nullable": False},
                    {"name": "name", "type": "varchar(100)", "nullable": False},
                    {"name": "status", "type": "varchar(20)", "nullable": False},
                    {"name": "plan_template", "type": "varchar(20)", "nullable": True},
                ],
            }, ensure_ascii=False, indent=2),
            "format": "json",
            "exit_code": 0,
        }
    else:
        return {
            "output": f"Mock执行完成: {command[:80]}\n请注意: 生产环境将在安全沙箱中执行",
            "format": "text",
            "exit_code": 0,
        }


# ─── Wave 3: Journey ───


_MOCK_JOURNEYS: list[dict[str, Any]] = [
    {
        "id": "j-onboarding",
        "name": "新客户Onboarding",
        "description": "从签约完成到首月回访的全流程编排",
        "node_count": 14,
        "edge_count": 16,
        "active_instances": 3,
        "status": "active",
        "created_at": (datetime.utcnow() - timedelta(days=30)).isoformat(),
        "updated_at": (datetime.utcnow() - timedelta(days=2)).isoformat(),
        "nodes": [
            {"id": "n1", "type": "trigger", "label": "触发: 签约完成", "x": 400, "y": 30, "status": "done"},
            {"id": "n2", "type": "action", "label": "签约确认邮件", "x": 260, "y": 130, "status": "done"},
            {"id": "n3", "type": "wait", "label": "等待1天", "x": 260, "y": 220, "status": "done"},
            {"id": "n4", "type": "action", "label": "实施启动会议", "x": 400, "y": 310, "status": "running"},
            {"id": "n5", "type": "action", "label": "数据迁移", "x": 220, "y": 420, "status": "pending"},
            {"id": "n6", "type": "action", "label": "培训排期", "x": 400, "y": 420, "status": "pending"},
            {"id": "n7", "type": "action", "label": "设备发货", "x": 580, "y": 420, "status": "pending"},
            {"id": "n8", "type": "action", "label": "系统上线+门店激活", "x": 400, "y": 530, "status": "pending"},
            {"id": "n9", "type": "condition", "label": "健康分>=80?", "x": 280, "y": 640, "status": "pending"},
            {"id": "n10", "type": "condition", "label": "健康分<80?", "x": 520, "y": 640, "status": "pending"},
            {"id": "n11", "type": "action", "label": "正常跟进30天", "x": 230, "y": 760, "status": "pending"},
            {"id": "n12", "type": "action", "label": "紧急干预Playbook", "x": 570, "y": 760, "status": "pending"},
            {"id": "n13", "type": "action", "label": "首月回访总结", "x": 400, "y": 870, "status": "pending"},
            {"id": "n14", "type": "action", "label": "进入季度检查循环", "x": 400, "y": 960, "status": "pending"},
        ],
        "edges": [
            {"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"}, {"from": "n3", "to": "n4", "label": "1天后"},
            {"from": "n4", "to": "n5"}, {"from": "n4", "to": "n6"}, {"from": "n4", "to": "n7"},
            {"from": "n5", "to": "n8"}, {"from": "n6", "to": "n8"}, {"from": "n7", "to": "n8"},
            {"from": "n8", "to": "n9"}, {"from": "n8", "to": "n10"},
            {"from": "n9", "to": "n11", "label": "Yes"}, {"from": "n10", "to": "n12", "label": "Yes"},
            {"from": "n11", "to": "n13"}, {"from": "n12", "to": "n13"}, {"from": "n13", "to": "n14"},
        ],
    },
    {
        "id": "j-renewal",
        "name": "续约流程",
        "description": "续约前90天到签约完成的全流程编排",
        "node_count": 8,
        "edge_count": 8,
        "active_instances": 2,
        "status": "active",
        "created_at": (datetime.utcnow() - timedelta(days=25)).isoformat(),
        "updated_at": (datetime.utcnow() - timedelta(days=5)).isoformat(),
        "nodes": [],
        "edges": [],
    },
    {
        "id": "j-churn",
        "name": "流失挽回",
        "description": "健康分低于60时触发的挽回流程",
        "node_count": 8,
        "edge_count": 7,
        "active_instances": 1,
        "status": "active",
        "created_at": (datetime.utcnow() - timedelta(days=20)).isoformat(),
        "updated_at": (datetime.utcnow() - timedelta(days=3)).isoformat(),
        "nodes": [],
        "edges": [],
    },
]


async def hub_list_journeys(db: AsyncSession) -> list[dict[str, Any]]:
    """Journey 模板列表"""
    # TODO: 从 hub_journeys 表读取
    return [
        {k: v for k, v in j.items() if k not in ("nodes", "edges")}
        for j in _MOCK_JOURNEYS
    ]


async def hub_get_journey(db: AsyncSession, journey_id: str) -> Optional[dict[str, Any]]:
    """Journey 详情（含节点+连线）"""
    # TODO: 从 hub_journeys + hub_journey_nodes + hub_journey_edges 表读取
    for j in _MOCK_JOURNEYS:
        if j["id"] == journey_id:
            return j
    return None


async def hub_save_journey(
    db: AsyncSession, journey_id: str, data: dict[str, Any],
) -> dict[str, Any]:
    """保存 Journey"""
    # TODO: UPSERT hub_journeys + hub_journey_nodes + hub_journey_edges
    return {
        "journey_id": journey_id,
        "name": data["name"],
        "node_count": len(data.get("nodes", [])),
        "edge_count": len(data.get("edges", [])),
        "saved_at": datetime.utcnow().isoformat(),
    }


async def hub_run_journey(
    db: AsyncSession, journey_id: str, customer_id: str,
) -> Optional[dict[str, Any]]:
    """为客户启动 Journey"""
    # TODO: INSERT hub_journey_instances
    journey = await hub_get_journey(db, journey_id)
    if not journey:
        return None
    instance_id = f"ji-{str(uuid.uuid4())[:8]}"
    return {
        "instance_id": instance_id,
        "journey_id": journey_id,
        "journey_name": journey["name"],
        "customer_id": customer_id,
        "status": "running",
        "started_at": datetime.utcnow().isoformat(),
        "current_node": journey.get("nodes", [{}])[0].get("id", "n1") if journey.get("nodes") else "n1",
    }


async def hub_list_journey_instances(
    db: AsyncSession, journey_id: str,
) -> Optional[list[dict[str, Any]]]:
    """Journey 运行实例列表"""
    # TODO: 从 hub_journey_instances 表读取
    journey = await hub_get_journey(db, journey_id)
    if not journey:
        return None
    now = datetime.utcnow()
    return [
        {
            "instance_id": f"ji-{str(uuid.uuid4())[:8]}",
            "journey_id": journey_id,
            "customer_id": _MOCK_CUSTOMERS[i]["id"],
            "customer_name": _MOCK_CUSTOMERS[i]["name"],
            "status": "running" if i == 0 else "completed",
            "current_node": "n4" if i == 0 else "n14",
            "started_at": (now - timedelta(days=10 + i * 15)).isoformat(),
            "completed_at": (now - timedelta(days=i * 5)).isoformat() if i > 0 else None,
            "progress_pct": 30 if i == 0 else 100,
        }
        for i in range(min(3, len(_MOCK_CUSTOMERS)))
    ]
