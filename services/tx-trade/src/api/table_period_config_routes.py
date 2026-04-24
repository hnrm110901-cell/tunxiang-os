"""桌台×时段配置矩阵 API (v286)

端点：
  GET    /api/v1/table-period-configs/{store_id}         — 门店全部时段配置
  GET    /api/v1/table-period-configs/{store_id}/matrix   — 矩阵视图（前端表格用）
  POST   /api/v1/table-period-configs                    — 批量创建/更新配置
  DELETE /api/v1/table-period-configs/{config_id}        — 删除单条配置

统一响应格式: {"ok": bool, "data": {}, "error": {}}
所有接口需 X-Tenant-ID header。
"""

from __future__ import annotations

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/table-period-configs",
    tags=["table-period-configs"],
)


# ─── 通用工具 ────────────────────────────────────────────────────────────────


def _get_tenant_id(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return str(tid)


def _ok(data: dict | list | None) -> dict:
    return {"ok": True, "data": data, "error": None}


def _err(msg: str, code: int = 400) -> HTTPException:
    raise HTTPException(
        status_code=code,
        detail={"ok": False, "data": None, "error": {"message": msg}},
    )


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, TRUE)"), {"tid": tenant_id})


# ─── Pydantic 模型 ────────────────────────────────────────────────────────────


class TablePeriodConfigItem(BaseModel):
    table_id: Optional[str] = Field(default=None, description="单桌ID（优先级高于 zone_id）")
    zone_id: Optional[str] = Field(default=None, description="区域ID（批量设置）")
    market_session_id: str = Field(description="市别ID")
    is_available: bool = Field(default=True, description="该时段是否开放")
    effective_seats: Optional[int] = Field(default=None, ge=1, description="时段可用座位数")
    time_limit_min: Optional[int] = Field(default=None, ge=1, description="用餐时限（分钟）")
    service_mode_override: Optional[str] = Field(
        default=None,
        max_length=20,
        description="覆盖服务模式：dine_first/scan_and_pay",
    )
    pricing_override: Optional[dict] = Field(
        default=None,
        description="定价覆盖：{min_consumption_fen, room_fee_fen, surcharge_rate}",
    )
    target_metrics: Optional[dict] = Field(
        default=None,
        description="经营目标：{target_turnover_rate, target_avg_spend_fen, target_duration_min}",
    )


class BatchCreateReq(BaseModel):
    store_id: str = Field(description="门店ID")
    configs: list[TablePeriodConfigItem] = Field(min_length=1, description="配置列表")


# ─── 路由 ─────────────────────────────────────────────────────────────────────


@router.get("/{store_id}", summary="门店全部时段配置")
async def list_configs(
    store_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询门店所有活跃的桌台时段配置，JOIN 补充桌台号/区域名/市别名"""
    tid = _get_tenant_id(request)
    await _set_rls(db, tid)

    result = await db.execute(
        text("""
            SELECT
                tpc.id,
                tpc.table_id,
                tpc.zone_id,
                tpc.market_session_id,
                tpc.is_available,
                tpc.effective_seats,
                tpc.time_limit_min,
                tpc.service_mode_override,
                tpc.pricing_override,
                tpc.target_metrics,
                tpc.is_active,
                tpc.created_at,
                t.table_no,
                t.seats AS physical_seats,
                tz.zone_name,
                sms.name AS market_session_name
            FROM table_period_configs tpc
                LEFT JOIN tables t ON tpc.table_id = t.id
                LEFT JOIN table_zones tz ON tpc.zone_id = tz.id
                LEFT JOIN store_market_sessions sms ON tpc.market_session_id = sms.id
            WHERE tpc.store_id = :store_id
              AND tpc.tenant_id = :tid
              AND tpc.is_active = TRUE
              AND tpc.is_deleted = FALSE
            ORDER BY tz.zone_name NULLS LAST, t.table_no NULLS LAST, sms.start_time
        """),
        {"store_id": str(store_id), "tid": tid},
    )
    rows = result.fetchall()

    items = [
        {
            "id": str(r.id),
            "table_id": str(r.table_id) if r.table_id else None,
            "table_no": r.table_no,
            "physical_seats": r.physical_seats,
            "zone_id": str(r.zone_id) if r.zone_id else None,
            "zone_name": r.zone_name,
            "market_session_id": str(r.market_session_id),
            "market_session_name": r.market_session_name,
            "is_available": r.is_available,
            "effective_seats": r.effective_seats,
            "time_limit_min": r.time_limit_min,
            "service_mode_override": r.service_mode_override,
            "pricing_override": r.pricing_override,
            "target_metrics": r.target_metrics,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return _ok({"items": items, "total": len(items)})


@router.get("/{store_id}/matrix", summary="矩阵视图（前端表格用）")
async def get_matrix(
    store_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    返回前端表格渲染所需的矩阵结构。

    结构: {
      market_sessions: [{id, name, start_time, end_time}],
      zones: [{
        zone_id, zone_name,
        tables: [{
          table_id, table_no, seats,
          configs_by_session: {session_id: config}
        }]
      }]
    }
    """
    tid = _get_tenant_id(request)
    await _set_rls(db, tid)

    # 1. 获取门店市别
    ms_result = await db.execute(
        text("""
            SELECT id, name, start_time, end_time
            FROM store_market_sessions
            WHERE tenant_id = :tid AND store_id = :sid AND is_active = TRUE
            ORDER BY start_time
        """),
        {"tid": tid, "sid": str(store_id)},
    )
    market_sessions = [
        {
            "id": str(r.id),
            "name": r.name,
            "start_time": str(r.start_time),
            "end_time": str(r.end_time),
        }
        for r in ms_result.fetchall()
    ]

    # 2. 获取门店桌台（按区域分组）
    tables_result = await db.execute(
        text("""
            SELECT t.id AS table_id, t.table_no, t.seats, t.zone_id,
                   tz.zone_name
            FROM tables t
                LEFT JOIN table_zones tz ON t.zone_id = tz.id
            WHERE t.store_id = :sid
              AND t.tenant_id = :tid
              AND t.is_deleted = FALSE
            ORDER BY tz.zone_name NULLS LAST, t.table_no
        """),
        {"sid": str(store_id), "tid": tid},
    )
    table_rows = tables_result.fetchall()

    # 3. 获取所有配置
    cfg_result = await db.execute(
        text("""
            SELECT id, table_id, zone_id, market_session_id,
                   is_available, effective_seats, time_limit_min,
                   service_mode_override, pricing_override, target_metrics
            FROM table_period_configs
            WHERE store_id = :sid AND tenant_id = :tid
              AND is_active = TRUE AND is_deleted = FALSE
        """),
        {"sid": str(store_id), "tid": tid},
    )
    cfg_rows = cfg_result.fetchall()

    # 按 (table_id, session_id) 和 (zone_id, session_id) 索引
    table_cfg_map: dict[str, dict[str, dict]] = {}  # table_id -> {session_id -> cfg}
    zone_cfg_map: dict[str, dict[str, dict]] = {}  # zone_id  -> {session_id -> cfg}

    for c in cfg_rows:
        cfg_dict = {
            "id": str(c.id),
            "is_available": c.is_available,
            "effective_seats": c.effective_seats,
            "time_limit_min": c.time_limit_min,
            "service_mode_override": c.service_mode_override,
            "pricing_override": c.pricing_override,
            "target_metrics": c.target_metrics,
        }
        sid = str(c.market_session_id)
        if c.table_id:
            table_cfg_map.setdefault(str(c.table_id), {})[sid] = cfg_dict
        elif c.zone_id:
            zone_cfg_map.setdefault(str(c.zone_id), {})[sid] = cfg_dict

    # 4. 组装矩阵
    zone_groups: dict[str, dict] = {}
    for t in table_rows:
        zid = str(t.zone_id) if t.zone_id else "__no_zone__"
        zname = t.zone_name or "未分区"
        if zid not in zone_groups:
            zone_groups[zid] = {"zone_id": zid if zid != "__no_zone__" else None, "zone_name": zname, "tables": []}

        tid_str = str(t.table_id)
        # 优先级：table_id 级配置 > zone_id 级配置
        configs_by_session: dict[str, dict] = {}
        for ms in market_sessions:
            msid = ms["id"]
            if tid_str in table_cfg_map and msid in table_cfg_map[tid_str]:
                configs_by_session[msid] = table_cfg_map[tid_str][msid]
            elif zid in zone_cfg_map and msid in zone_cfg_map[zid]:
                cfg_copy = dict(zone_cfg_map[zid][msid])
                cfg_copy["_inherited_from"] = "zone"
                configs_by_session[msid] = cfg_copy

        zone_groups[zid]["tables"].append(
            {
                "table_id": tid_str,
                "table_no": t.table_no,
                "seats": t.seats,
                "configs_by_session": configs_by_session,
            }
        )

    return _ok(
        {
            "market_sessions": market_sessions,
            "zones": list(zone_groups.values()),
        }
    )


@router.post("", summary="批量创建/更新时段配置")
async def batch_upsert(
    body: BatchCreateReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    批量创建或更新桌台时段配置。

    使用 ON CONFLICT (table_id/zone_id + market_session_id) 进行 upsert。
    每条配置必须指定 table_id 或 zone_id 至少一个。
    """
    tid = _get_tenant_id(request)
    await _set_rls(db, tid)

    created_ids: list[str] = []
    for item in body.configs:
        if not item.table_id and not item.zone_id:
            _err("每条配置必须指定 table_id 或 zone_id 至少一个")

        new_id = str(uuid.uuid4())
        await db.execute(
            text("""
                INSERT INTO table_period_configs
                    (id, tenant_id, store_id, table_id, zone_id, market_session_id,
                     is_available, effective_seats, time_limit_min,
                     service_mode_override, pricing_override, target_metrics)
                VALUES
                    (:id, :tid, :store_id, :table_id, :zone_id, :market_session_id,
                     :is_available, :effective_seats, :time_limit_min,
                     :service_mode_override, :pricing_override::jsonb, :target_metrics::jsonb)
                ON CONFLICT (id) DO UPDATE SET
                    is_available = EXCLUDED.is_available,
                    effective_seats = EXCLUDED.effective_seats,
                    time_limit_min = EXCLUDED.time_limit_min,
                    service_mode_override = EXCLUDED.service_mode_override,
                    pricing_override = EXCLUDED.pricing_override,
                    target_metrics = EXCLUDED.target_metrics,
                    updated_at = NOW()
            """),
            {
                "id": new_id,
                "tid": tid,
                "store_id": body.store_id,
                "table_id": item.table_id,
                "zone_id": item.zone_id,
                "market_session_id": item.market_session_id,
                "is_available": item.is_available,
                "effective_seats": item.effective_seats,
                "time_limit_min": item.time_limit_min,
                "service_mode_override": item.service_mode_override,
                "pricing_override": str(item.pricing_override or {}),
                "target_metrics": str(item.target_metrics or {}),
            },
        )
        created_ids.append(new_id)

    await db.commit()
    logger.info(
        "table_period_configs_batch_upsert",
        store_id=body.store_id,
        count=len(created_ids),
    )
    return _ok({"ids": created_ids, "count": len(created_ids)})


@router.delete("/{config_id}", summary="删除单条时段配置")
async def delete_config(
    config_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """软删除单条桌台时段配置"""
    tid = _get_tenant_id(request)
    await _set_rls(db, tid)

    result = await db.execute(
        text("""
            UPDATE table_period_configs
            SET is_deleted = TRUE, is_active = FALSE, updated_at = NOW()
            WHERE id = :cid AND tenant_id = :tid AND is_deleted = FALSE
        """),
        {"cid": str(config_id), "tid": tid},
    )
    await db.commit()

    if result.rowcount == 0:
        _err("配置不存在或已删除", code=404)

    logger.info("table_period_config_deleted", id=str(config_id))
    return _ok({"id": str(config_id), "is_deleted": True})
