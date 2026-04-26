"""Hub 运维 — PostgreSQL 读/写模型（跨租户，session 须为 get_db_no_rls）"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import date, datetime, timedelta
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
        "incidents": [],  # TODO: 接入 Incident 表（hub_incidents）
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
    """节点事件时间线"""
    # TODO: 接入真实事件表（events），目前返回 mock
    now = datetime.utcnow()
    return [
        {
            "timestamp": (now - timedelta(minutes=2)).isoformat(),
            "event": "heartbeat",
            "detail": {"cpu_pct": 12.3, "mem_pct": 45.6},
        },
        {
            "timestamp": (now - timedelta(hours=1)).isoformat(),
            "event": "sync_complete",
            "detail": {"tables_synced": 8, "rows": 142},
        },
        {
            "timestamp": (now - timedelta(hours=6)).isoformat(),
            "event": "client_update",
            "detail": {"from_version": "0.9.1", "to_version": "0.9.2"},
        },
    ]


async def hub_edge_wake(db: AsyncSession, sn: str) -> dict[str, Any]:
    """唤醒边缘节点（WOL）"""
    # TODO: 接入真实 WOL 实现（发送 magic packet via Tailscale）
    edge = await hub_get_edge(db, sn)
    if not edge:
        return {"success": False, "error": "节点不存在"}
    return {
        "success": True,
        "sn": sn,
        "action": "wake_on_lan",
        "message": f"WOL magic packet 已发送至 {edge.get('ip', 'unknown')}",
    }


async def hub_edge_reboot(db: AsyncSession, sn: str) -> dict[str, Any]:
    """重启边缘节点"""
    # TODO: 接入真实 SSH/Tailscale 远程重启
    edge = await hub_get_edge(db, sn)
    if not edge:
        return {"success": False, "error": "节点不存在"}
    return {
        "success": True,
        "sn": sn,
        "action": "reboot",
        "message": f"重启指令已发送至 {edge.get('store', sn)}",
    }


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
    # TODO: 接入真实 Tailscale API 获取对等连接和延迟
    return {
        "hub": {
            "name": "tunxiang-hub",
            "ip": "100.64.0.1",
            "role": "hub",
            "status": "online",
        },
        "nodes": nodes,
        "links": [
            {"from": "tunxiang-hub", "to": n.get("sn", ""), "latency_ms": 4 + i * 2}
            for i, n in enumerate(nodes)
        ],
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
    """17 个微服务列表 + 健康状态"""
    # TODO: 接入真实健康检查（HTTP ping 各服务 /health）
    now = datetime.utcnow().isoformat()
    services = []
    for name in _SERVICES:
        services.append({
            "name": name,
            "port": _SERVICE_PORTS.get(name),
            "status": "healthy",
            "uptime_pct": 99.9,
            "last_check": now,
            "version": "0.9.2",
            "instances": 1,
        })
    return services


async def hub_get_service(name: str) -> Optional[dict[str, Any]]:
    """单个服务详情"""
    if name not in _SERVICES:
        return None
    # TODO: 接入真实服务发现 + 指标
    now = datetime.utcnow().isoformat()
    return {
        "name": name,
        "port": _SERVICE_PORTS.get(name),
        "status": "healthy",
        "uptime_pct": 99.9,
        "last_check": now,
        "version": "0.9.2",
        "instances": 1,
        "endpoints_count": 15,
        "avg_latency_ms": 23,
        "p99_latency_ms": 89,
        "error_rate_pct": 0.02,
        "last_deploy": (datetime.utcnow() - timedelta(days=2)).isoformat(),
    }


async def hub_service_slos(name: str) -> Optional[list[dict[str, Any]]]:
    """服务 SLO 列表"""
    if name not in _SERVICES:
        return None
    # TODO: 接入真实 SLO 监控数据
    return [
        {
            "slo": "availability",
            "target": 99.9,
            "current": 99.95,
            "status": "met",
            "window": "30d",
        },
        {
            "slo": "latency_p99",
            "target": 200,
            "current": 89,
            "unit": "ms",
            "status": "met",
            "window": "30d",
        },
        {
            "slo": "error_rate",
            "target": 0.1,
            "current": 0.02,
            "unit": "%",
            "status": "met",
            "window": "30d",
        },
    ]


async def hub_service_timeline(name: str) -> Optional[list[dict[str, Any]]]:
    """服务事件时间线"""
    if name not in _SERVICES:
        return None
    # TODO: 接入真实事件表
    now = datetime.utcnow()
    return [
        {
            "timestamp": (now - timedelta(hours=2)).isoformat(),
            "event": "deploy",
            "detail": {"version": "0.9.2", "commit": "abc1234"},
        },
        {
            "timestamp": (now - timedelta(days=1)).isoformat(),
            "event": "health_check_recovered",
            "detail": {"downtime_seconds": 12},
        },
        {
            "timestamp": (now - timedelta(days=3)).isoformat(),
            "event": "config_change",
            "detail": {"key": "max_connections", "old": 50, "new": 100},
        },
    ]


# ─── Wave 1: Stream 全局事件流 ───


async def hub_stream_events():
    """全局 SSE 事件流生成器"""
    # TODO: 从 Redis Streams / PG NOTIFY 读取真实事件
    _mock_events = [
        {
            "type": "edge.heartbeat",
            "data": {"sn": "MM-A012", "status": "online", "latency_ms": 4},
        },
        {
            "type": "ticket.created",
            "data": {"id": "T042", "title": "POS打印机离线", "priority": "high"},
        },
        {
            "type": "service.health_change",
            "data": {"name": "tx-trade", "from": "degraded", "to": "healthy"},
        },
        {
            "type": "agent.decision",
            "data": {"agent": "discount_guard", "action": "block", "confidence": 0.94},
        },
        {
            "type": "adapter.sync_complete",
            "data": {"adapter": "meituan", "merchant": "尝在一起", "rows": 56},
        },
    ]
    idx = 0
    while True:
        event = _mock_events[idx % len(_mock_events)]
        payload = {
            **event,
            "timestamp": datetime.utcnow().isoformat(),
        }
        yield f"event: {event['type']}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        idx += 1
        await asyncio.sleep(5)


# ─── Wave 1: Copilot Chat ───


async def hub_copilot_chat(
    message: str,
    context: dict[str, Any],
    thread_id: Optional[str],
):
    """Copilot 对话 SSE 流式响应生成器"""
    # TODO: 接入 tx-brain Claude API
    workspace = context.get("workspace", "Hub")
    response = f"收到关于 {workspace} 的问题：「{message}」\n\n正在分析中... 这是 Copilot v1 的 mock 响应。实际版本将接入 tx-brain 服务进行智能推理。"

    tid = thread_id or str(uuid.uuid4())

    # 发送 thread_id
    yield f"data: {json.dumps({'type': 'thread', 'thread_id': tid}, ensure_ascii=False)}\n\n"

    # 逐字符流式输出
    for char in response:
        yield f"data: {json.dumps({'type': 'token', 'content': char}, ensure_ascii=False)}\n\n"
        await asyncio.sleep(0.03)

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

    # TODO: 接入真实多维健康分计算
    dimensions = {
        "sla_hit_rate": {
            "label": "SLA命中率",
            "score": 92.0,
            "weight": 0.25,
            "detail": "过去30天API可用性99.2%，响应时间达标率92%",
        },
        "nps": {
            "label": "NPS满意度",
            "score": 78.0,
            "weight": 0.20,
            "detail": "最近调研NPS=+45，推荐者62%，贬损者17%",
        },
        "adapter_latency": {
            "label": "Adapter延迟",
            "score": 85.0,
            "weight": 0.20,
            "detail": "美团Adapter P99=120ms，品智POS同步延迟<2s",
        },
        "activity": {
            "label": "活跃度",
            "score": 88.0,
            "weight": 0.20,
            "detail": "日均登录3.2次，周活跃率95%，功能使用覆盖率68%",
        },
        "ticket_volume": {
            "label": "工单量",
            "score": 70.0,
            "weight": 0.15,
            "detail": "近30天8张工单，其中2张高优先，平均解决时间4.2h",
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

    # TODO: 接入真实事件表
    now = datetime.utcnow()
    return [
        {
            "timestamp": (now - timedelta(days=90)).isoformat(),
            "event": "onboarding.started",
            "detail": {"plan": "standard", "source": "线下拜访"},
        },
        {
            "timestamp": (now - timedelta(days=85)).isoformat(),
            "event": "onboarding.completed",
            "detail": {"stores_activated": 3, "adapters_connected": 2},
        },
        {
            "timestamp": (now - timedelta(days=60)).isoformat(),
            "event": "subscription.renewed",
            "detail": {"plan": "standard", "period": "annual"},
        },
        {
            "timestamp": (now - timedelta(days=30)).isoformat(),
            "event": "expansion.store_added",
            "detail": {"store_name": "天心区新店", "total_stores": 4},
        },
        {
            "timestamp": (now - timedelta(days=7)).isoformat(),
            "event": "ticket.resolved",
            "detail": {"ticket_id": "T038", "title": "美团订单同步延迟"},
        },
    ]
