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
    """客户列表（带健康分、ARR、续约日）"""
    # TODO: 接入真实数据
    items = _MOCK_CUSTOMERS
    if status:
        items = [c for c in items if c["status"] == status]
    total = len(items)
    offset = max(0, (page - 1) * size)
    paged = items[offset : offset + size]
    return {"items": paged, "total": total}


async def hub_get_customer(db: AsyncSession, customer_id: str) -> Optional[dict[str, Any]]:
    """客户详情"""
    # TODO: 接入真实数据
    for c in _MOCK_CUSTOMERS:
        if c["id"] == customer_id:
            return c
    return None


async def hub_customer_playbooks(db: AsyncSession, customer_id: str) -> Optional[list[dict[str, Any]]]:
    """客户订阅的 Playbook 列表"""
    # TODO: 接入真实数据
    customer = await hub_get_customer(db, customer_id)
    if not customer:
        return None
    pb_ids = customer.get("playbook_subscriptions", [])
    result = []
    for pb in _MOCK_PLAYBOOKS:
        if pb["id"] in pb_ids:
            result.append({**pb, "subscribed": True, "customer_id": customer_id})
    return result


async def hub_run_customer_playbook(
    db: AsyncSession, customer_id: str, playbook_id: str,
) -> Optional[dict[str, Any]]:
    """手动触发客户 Playbook"""
    # TODO: 接入真实 Playbook 引擎
    customer = await hub_get_customer(db, customer_id)
    if not customer:
        return None
    pb = None
    for p in _MOCK_PLAYBOOKS:
        if p["id"] == playbook_id:
            pb = p
            break
    if not pb:
        return {"error": "playbook_not_found"}
    run_id = str(uuid.uuid4())[:8]
    return {
        "run_id": f"run-{run_id}",
        "playbook_id": playbook_id,
        "playbook_name": pb["name"],
        "customer_id": customer_id,
        "customer_name": customer["name"],
        "status": "running",
        "triggered_at": datetime.utcnow().isoformat(),
        "triggered_by": "manual",
    }


async def hub_customer_journey(db: AsyncSession, customer_id: str) -> Optional[dict[str, Any]]:
    """客户旅程阶段"""
    # TODO: 接入真实数据
    customer = await hub_get_customer(db, customer_id)
    if not customer:
        return None
    stages = ["prospect", "onboarding", "adoption", "expansion", "renewal", "churned"]
    current = customer.get("journey_stage", "onboarding")
    current_idx = stages.index(current) if current in stages else 1
    now = datetime.utcnow()
    return {
        "customer_id": customer_id,
        "customer_name": customer["name"],
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


def _incident_timeline(incident_id: str) -> list[dict[str, Any]]:
    """生成 Incident 时间线 mock 数据"""
    # TODO: 接入真实数据
    inc = None
    for i in _MOCK_INCIDENTS:
        if i["id"] == incident_id:
            inc = i
            break
    if not inc:
        return []
    base_time = datetime.fromisoformat(inc["created_at"])
    events = [
        {"timestamp": base_time.isoformat(), "event": "incident.declared", "actor": "system", "detail": {"title": inc["title"], "priority": inc["priority"]}},
        {"timestamp": (base_time + timedelta(minutes=2)).isoformat(), "event": "incident.commander_assigned", "actor": "李淳", "detail": {"commander": inc.get("commander", "李淳")}},
        {"timestamp": (base_time + timedelta(minutes=5)).isoformat(), "event": "incident.investigation_started", "actor": inc.get("commander", "李淳"), "detail": {"initial_hypothesis": "检查服务日志和监控告警"}},
        {"timestamp": (base_time + timedelta(minutes=15)).isoformat(), "event": "incident.status_update", "actor": inc.get("commander", "李淳"), "detail": {"message": "已定位根因，正在实施修复"}},
    ]
    if inc.get("resolved_at"):
        events.append({
            "timestamp": inc["resolved_at"],
            "event": "incident.resolved",
            "actor": inc.get("commander", "李淳"),
            "detail": {"resolution": "问题已修复，服务恢复正常"},
        })
    return events


async def hub_list_incidents(
    db: AsyncSession,
    priority: Optional[str],
    status: Optional[str],
    page: int,
    size: int,
) -> dict[str, Any]:
    """Incident 列表"""
    # TODO: 接入真实数据
    items = list(_MOCK_INCIDENTS)
    if priority:
        items = [i for i in items if i["priority"] == priority]
    if status:
        items = [i for i in items if i["status"] == status]
    total = len(items)
    offset = max(0, (page - 1) * size)
    paged = items[offset : offset + size]
    return {"items": paged, "total": total}


async def hub_create_incident(db: AsyncSession, data: dict[str, Any]) -> dict[str, Any]:
    """声明新 Incident"""
    # TODO: 接入真实数据
    inc_id = f"INC-{len(_MOCK_INCIDENTS) + 1:03d}"
    now = datetime.utcnow().isoformat()
    return {
        "id": inc_id,
        "title": data["title"],
        "priority": data["priority"],
        "status": "open",
        "commander": None,
        "tech_lead": None,
        "scribe": None,
        "affected_services": data.get("affected_services", []),
        "affected_customers": data.get("affected_customers", []),
        "description": data.get("description", ""),
        "created_at": now,
        "resolved_at": None,
        "duration_minutes": None,
    }


async def hub_get_incident(db: AsyncSession, incident_id: str) -> Optional[dict[str, Any]]:
    """Incident 详情"""
    # TODO: 接入真实数据
    for inc in _MOCK_INCIDENTS:
        if inc["id"] == incident_id:
            return inc
    return None


async def hub_update_incident(db: AsyncSession, incident_id: str, updates: dict[str, Any]) -> Optional[dict[str, Any]]:
    """更新 Incident"""
    # TODO: 接入真实数据
    for inc in _MOCK_INCIDENTS:
        if inc["id"] == incident_id:
            return {**inc, **updates}
    return None


async def hub_incident_timeline(db: AsyncSession, incident_id: str) -> Optional[list[dict[str, Any]]]:
    """Incident 时间线"""
    # TODO: 接入真实数据
    inc = await hub_get_incident(db, incident_id)
    if not inc:
        return None
    return _incident_timeline(incident_id)


async def hub_incident_postmortem(db: AsyncSession, incident_id: str) -> Optional[dict[str, Any]]:
    """生成 Postmortem 草稿"""
    # TODO: 接入 tx-brain Claude API 生成真实 postmortem
    inc = await hub_get_incident(db, incident_id)
    if not inc:
        return None
    timeline = _incident_timeline(incident_id)
    return {
        "incident_id": incident_id,
        "title": f"Postmortem: {inc['title']}",
        "severity": inc["priority"],
        "duration_minutes": inc.get("duration_minutes", 0),
        "summary": f"于 {inc['created_at']} 发生 {inc['priority']} 级别事件：{inc['title']}。"
                   f"影响服务：{', '.join(inc.get('affected_services', []))}。"
                   f"影响客户：{len(inc.get('affected_customers', []))} 个。",
        "root_cause": "待填写 -- 请基于调查结果补充根因分析",
        "impact": {
            "affected_services": inc.get("affected_services", []),
            "affected_customers": inc.get("affected_customers", []),
            "estimated_revenue_impact_yuan": 0,
        },
        "timeline": timeline,
        "action_items": [
            {"action": "添加监控告警", "owner": "李淳", "due_date": None, "status": "pending"},
            {"action": "更新 Runbook", "owner": "李淳", "due_date": None, "status": "pending"},
            {"action": "复盘会议", "owner": "李淳", "due_date": None, "status": "pending"},
        ],
        "generated_at": datetime.utcnow().isoformat(),
        "generated_by": "copilot-mock",
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
    """迁移项目列表"""
    # TODO: 接入真实数据
    items = list(_MOCK_MIGRATIONS)
    if status:
        items = [m for m in items if m["status"] == status]
    total = len(items)
    offset = max(0, (page - 1) * size)
    paged = items[offset : offset + size]
    return {"items": paged, "total": total}


async def hub_create_migration(db: AsyncSession, data: dict[str, Any]) -> dict[str, Any]:
    """创建迁移项目"""
    # TODO: 接入真实数据
    mig_id = f"mig-{len(_MOCK_MIGRATIONS) + 1:03d}"
    now = datetime.utcnow().isoformat()
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
    """迁移详情"""
    # TODO: 接入真实数据
    for m in _MOCK_MIGRATIONS:
        if m["id"] == migration_id:
            return m
    return None


async def hub_advance_migration(db: AsyncSession, migration_id: str) -> Optional[dict[str, Any]]:
    """推进迁移到下一阶段"""
    # TODO: 接入真实数据
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
    # TODO: 接入真实数据
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
    # TODO: 接入真实数据
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
    # TODO: 接入真实数据
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
    """单个适配器详情"""
    # TODO: 接入真实数据
    for a in _MOCK_ADAPTERS_EXTENDED:
        if a["id"] == adapter_id or a["key"] == adapter_id:
            return a
    return None


async def hub_adapter_mapping(db: AsyncSession, adapter_id: str) -> Optional[dict[str, Any]]:
    """适配器字段映射配置"""
    # TODO: 接入真实数据
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
    """适配器事件时间线"""
    # TODO: 接入真实数据
    adapter = await hub_get_adapter(db, adapter_id)
    if not adapter:
        return None
    now = datetime.utcnow()
    return [
        {"timestamp": (now - timedelta(minutes=2)).isoformat(), "event": "sync_complete", "detail": {"rows_synced": 23, "duration_ms": 450}},
        {"timestamp": (now - timedelta(minutes=62)).isoformat(), "event": "sync_complete", "detail": {"rows_synced": 18, "duration_ms": 380}},
        {"timestamp": (now - timedelta(hours=3)).isoformat(), "event": "error_recovered", "detail": {"error": "timeout", "retry_count": 2}},
        {"timestamp": (now - timedelta(hours=6)).isoformat(), "event": "config_updated", "detail": {"field": "sync_interval_sec", "old": 120, "new": 60}},
        {"timestamp": (now - timedelta(days=1)).isoformat(), "event": "version_upgraded", "detail": {"from": "1.2.0", "to": adapter.get("version", "unknown")}},
    ]


async def hub_adapter_sync(db: AsyncSession, adapter_id: str) -> Optional[dict[str, Any]]:
    """手动触发适配器同步"""
    # TODO: 接入真实同步引擎
    adapter = await hub_get_adapter(db, adapter_id)
    if not adapter:
        return None
    return {
        "adapter_id": adapter["id"],
        "adapter_name": adapter["name"],
        "sync_id": f"sync-{str(uuid.uuid4())[:8]}",
        "status": "triggered",
        "triggered_at": datetime.utcnow().isoformat(),
        "estimated_duration_sec": 30,
    }


async def hub_adapters_matrix(db: AsyncSession) -> dict[str, Any]:
    """适配器 x 商户矩阵数据 -- 15 适配器 x 10 商户"""
    # TODO: 接入真实数据
    adapters = [a["key"] for a in _MOCK_ADAPTERS_EXTENDED]
    merchants = [c["name"] for c in _MOCK_CUSTOMERS]

    _merchant_adapters = {
        "徐记海鲜": ["aoqiwei", "meituan", "eleme", "douyin", "xiaohongshu", "yiding", "nuonuo", "erp", "logistics"],
        "尝在一起": ["pinzhi", "meituan", "eleme", "douyin", "nuonuo", "weishenghuo"],
        "最黔线": ["tiancai-shanglong", "meituan", "eleme", "nuonuo"],
        "尚宫厨": ["keruyun", "meituan", "douyin", "yiding", "nuonuo"],
        "湘粤楼": ["pinzhi", "meituan", "eleme", "douyin", "weishenghuo"],
        "费大厨": ["keruyun", "meituan", "eleme", "douyin", "nuonuo", "erp"],
        "炊烟": ["pinzhi", "meituan", "douyin", "nuonuo"],
        "文和友": ["aoqiwei", "meituan", "eleme", "douyin", "xiaohongshu", "nuonuo", "erp", "wechat_delivery"],
        "茶颜悦色": ["meituan", "douyin", "xiaohongshu", "nuonuo", "wechat_delivery", "delivery_factory"],
        "黑色经典": ["meituan", "douyin", "erp"],
    }

    matrix: list[dict[str, Any]] = []
    for merchant_name in merchants:
        connected = _merchant_adapters.get(merchant_name, [])
        row: dict[str, Any] = {"merchant": merchant_name}
        for adapter_key in adapters:
            if adapter_key in connected:
                row[adapter_key] = "connected"
            else:
                row[adapter_key] = "not_applicable"
        matrix.append(row)

    return {
        "adapters": [{"key": a["key"], "name": a["name"]} for a in _MOCK_ADAPTERS_EXTENDED],
        "merchants": merchants,
        "matrix": matrix,
        "summary": {
            "total_connections": sum(1 for row in matrix for k, v in row.items() if k != "merchant" and v == "connected"),
            "total_errors": 0,
            "total_adapters": len(adapters),
            "total_merchants": len(merchants),
        },
    }


# ─── Wave 2: Playbooks 通用（API 函数） ───


async def hub_list_playbooks(db: AsyncSession) -> list[dict[str, Any]]:
    """剧本库列表"""
    # TODO: 接入真实数据
    return _MOCK_PLAYBOOKS


async def hub_get_playbook(db: AsyncSession, playbook_id: str) -> Optional[dict[str, Any]]:
    """剧本详情"""
    # TODO: 接入真实数据
    for pb in _MOCK_PLAYBOOKS:
        if pb["id"] == playbook_id:
            return pb
    return None


async def hub_run_playbook(db: AsyncSession, playbook_id: str, target_id: str, target_type: str) -> Optional[dict[str, Any]]:
    """触发 Playbook 执行"""
    # TODO: 接入真实 Playbook 引擎
    pb = await hub_get_playbook(db, playbook_id)
    if not pb:
        return None
    run_id = f"run-{str(uuid.uuid4())[:8]}"
    return {
        "run_id": run_id,
        "playbook_id": playbook_id,
        "playbook_name": pb["name"],
        "target_id": target_id,
        "target_type": target_type,
        "status": "running",
        "triggered_at": datetime.utcnow().isoformat(),
        "triggered_by": "manual",
        "estimated_duration_days": pb.get("avg_duration_days", 1),
    }


async def hub_playbook_runs(db: AsyncSession, playbook_id: str) -> Optional[list[dict[str, Any]]]:
    """Playbook 执行历史"""
    # TODO: 接入真实数据
    pb = await hub_get_playbook(db, playbook_id)
    if not pb:
        return None
    now = datetime.utcnow()
    mock_runs = []
    for i in range(min(pb.get("total_runs", 3), 5)):
        status = "completed" if i > 0 else "running"
        mock_runs.append({
            "run_id": f"run-{str(uuid.uuid4())[:8]}",
            "playbook_id": playbook_id,
            "target_id": _MOCK_CUSTOMERS[i % len(_MOCK_CUSTOMERS)]["id"],
            "target_name": _MOCK_CUSTOMERS[i % len(_MOCK_CUSTOMERS)]["name"],
            "target_type": "customer",
            "status": status,
            "triggered_at": (now - timedelta(days=i * 15 + 3)).isoformat(),
            "completed_at": (now - timedelta(days=i * 15)).isoformat() if status == "completed" else None,
            "triggered_by": "manual" if i % 2 == 0 else "auto",
        })
    return mock_runs


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
    """所有 feature flags"""
    # TODO: 从 feature_flags 表读取
    return _MOCK_FLAGS


async def hub_update_flag(
    db: AsyncSession, name: str, value: bool, rollout_pct: Optional[int],
) -> Optional[dict[str, Any]]:
    """更新 flag 值"""
    # TODO: UPDATE feature_flags SET value=:v, rollout_pct=:r WHERE name=:n
    for f in _MOCK_FLAGS:
        if f["name"] == name:
            result = {**f, "value": value, "updated_at": datetime.utcnow().isoformat()}
            if rollout_pct is not None:
                result["rollout_pct"] = rollout_pct
            return result
    return None


# ─── Wave 3: Settings — Releases ───


async def hub_list_releases(db: AsyncSession) -> list[dict[str, Any]]:
    """各环境发布状态"""
    # TODO: 从 CI/CD 系统拉取真实状态
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
    """触发部署"""
    # TODO: 调用 CI/CD API 执行部署
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
    """用户列表"""
    # TODO: 从 auth 表读取
    return [
        {"id": "u001", "name": "李淳", "email": "lichun@tunxiang.tech", "role": "platform-admin", "status": "active", "last_login": (datetime.utcnow() - timedelta(hours=1)).isoformat(), "mfa_enabled": True},
        {"id": "u002", "name": "陈工", "email": "chengong@tunxiang.tech", "role": "engineer", "status": "active", "last_login": (datetime.utcnow() - timedelta(hours=3)).isoformat(), "mfa_enabled": True},
        {"id": "u003", "name": "王工", "email": "wanggong@tunxiang.tech", "role": "engineer", "status": "active", "last_login": (datetime.utcnow() - timedelta(days=1)).isoformat(), "mfa_enabled": False},
        {"id": "u004", "name": "张CSM", "email": "zhangcsm@tunxiang.tech", "role": "csm", "status": "active", "last_login": (datetime.utcnow() - timedelta(hours=6)).isoformat(), "mfa_enabled": True},
    ]


async def hub_list_security_roles(db: AsyncSession) -> list[dict[str, Any]]:
    """角色列表"""
    # TODO: 从 RBAC 表读取
    return [
        {"id": "role-admin", "name": "platform-admin", "label": "平台管理员", "user_count": 1, "permissions": ["*"]},
        {"id": "role-eng", "name": "engineer", "label": "工程师", "user_count": 2, "permissions": ["read:*", "write:code", "deploy:dev", "deploy:test"]},
        {"id": "role-csm", "name": "csm", "label": "客户成功", "user_count": 1, "permissions": ["read:customers", "write:playbooks", "write:journeys"]},
        {"id": "role-viewer", "name": "viewer", "label": "只读用户", "user_count": 0, "permissions": ["read:*"]},
    ]


async def hub_list_audit_logs(db: AsyncSession) -> list[dict[str, Any]]:
    """审计日志"""
    # TODO: 从 audit_log 表读取
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
    """知识库文档列表"""
    # TODO: 从 knowledge_docs 表/向量库读取
    return [
        {"id": "kb-001", "title": "屯象OS架构总览", "category": "architecture", "updated_at": "2026-04-20", "word_count": 12500, "chunk_count": 45},
        {"id": "kb-002", "title": "POS收银操作手册", "category": "operations", "updated_at": "2026-04-18", "word_count": 8200, "chunk_count": 30},
        {"id": "kb-003", "title": "Adapter开发指南", "category": "development", "updated_at": "2026-04-15", "word_count": 6800, "chunk_count": 25},
        {"id": "kb-004", "title": "等保三级合规清单", "category": "compliance", "updated_at": "2026-04-10", "word_count": 4500, "chunk_count": 18},
        {"id": "kb-005", "title": "Mac mini边缘部署手册", "category": "deployment", "updated_at": "2026-04-08", "word_count": 5200, "chunk_count": 20},
        {"id": "kb-006", "title": "客户成功Playbook模板库", "category": "operations", "updated_at": "2026-04-05", "word_count": 9600, "chunk_count": 35},
    ]


async def hub_search_knowledge(db: AsyncSession, query: str, top_k: int) -> dict[str, Any]:
    """RAG 搜索"""
    # TODO: 接入向量检索 + Claude 生成
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
