"""巡台自动签到 API 路由

涵盖:
- POST /api/v1/crew/patrol-checkin   — 记录巡台（BLE自动或手动）
- GET  /api/v1/crew/patrol-summary   — 今日巡台统计与时间线
"""
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["crew-patrol"])

# ---------- Pydantic 模型 ----------

class PatrolCheckinRequest(BaseModel):
    table_no: str = Field(..., description="桌台号，如 A03")
    beacon_id: Optional[str] = Field(None, description="BLE 信标 ID")
    signal_strength: Optional[int] = Field(None, description="信号强度 dBm")


# ---------- Mock 数据存储（生产环境替换为 DB 调用） ----------

# 内存存储：{(tenant_id, crew_id, table_no): last_checkin_ts}
_dedup_cache: dict[tuple[str, str, str], float] = {}

# 内存存储：patrol_logs mock 列表
_patrol_logs: list[dict] = []

_DEDUP_SECONDS = 300  # 5 分钟内同一人同一桌不重复记录


def _build_checkin_id() -> str:
    import uuid
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- 路由 ----------

@router.post("/api/v1/crew/patrol-checkin")
async def patrol_checkin(
    body: PatrolCheckinRequest,
    x_operator_id: str = Header(default="op-001", alias="X-Operator-ID"),
    x_tenant_id: str   = Header(default="",       alias="X-Tenant-ID"),
    x_store_id: str    = Header(default="",       alias="X-Store-ID"),
):
    """
    记录服务员巡台。

    - 防重复：同一 crew + 同一 table 5 分钟内不重复记录。
    - 支持 BLE 自动签到（beacon_id + signal_strength）和手动打卡（均为 null）。
    - 生产环境：写入 patrol_logs 表（设置 app.tenant_id 后由 RLS 隔离）。
    """
    log = logger.bind(
        operator_id=x_operator_id,
        tenant_id=x_tenant_id,
        store_id=x_store_id,
        table_no=body.table_no,
    )
    try:
        import time
        now_ts = time.time()
        dedup_key = (x_tenant_id, x_operator_id, body.table_no)
        last_ts = _dedup_cache.get(dedup_key, 0.0)

        if now_ts - last_ts < _DEDUP_SECONDS:
            remaining = int(_DEDUP_SECONDS - (now_ts - last_ts))
            log.info("patrol_checkin_dedup", remaining_seconds=remaining)
            raise HTTPException(
                status_code=429,
                detail=f"同一桌台 {_DEDUP_SECONDS // 60} 分钟内不重复记录，请 {remaining} 秒后再试",
            )

        checkin_id = _build_checkin_id()
        checked_at = _now_iso()

        # 生产环境：INSERT INTO patrol_logs ...
        record = {
            "id": checkin_id,
            "tenant_id": x_tenant_id,
            "store_id": x_store_id,
            "crew_id": x_operator_id,
            "table_no": body.table_no,
            "beacon_id": body.beacon_id,
            "signal_strength": body.signal_strength,
            "checked_at": checked_at,
            "created_at": checked_at,
        }
        _patrol_logs.append(record)
        _dedup_cache[dedup_key] = now_ts

        log.info("patrol_checkin_ok", checkin_id=checkin_id, table_no=body.table_no)
        return {
            "ok": True,
            "data": {
                "checkin_id": checkin_id,
                "table_no": body.table_no,
                "checked_at": checked_at,
            },
        }
    except HTTPException:
        raise
    except ValueError as exc:
        log.warning("patrol_checkin_value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — MLPS3-P0: 最外层HTTP兜底，异常收窄至此
        log.error("patrol_checkin_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.get("/api/v1/crew/patrol-summary")
async def patrol_summary(
    date: Optional[str] = Query(None, description="日期 YYYY-MM-DD，默认今日"),
    x_operator_id: str = Header(default="op-001", alias="X-Operator-ID"),
    x_tenant_id: str   = Header(default="",       alias="X-Tenant-ID"),
):
    """
    返回服务员今日巡台统计。

    - tables_visited_count: 已巡桌台数（去重）
    - timeline: 时间线列表（倒序，最新优先）

    生产环境：查询 patrol_logs 表，按 tenant_id + crew_id + date 过滤。
    """
    log = logger.bind(operator_id=x_operator_id, tenant_id=x_tenant_id, date=date)
    try:
        from datetime import date as date_cls
        target_date = date_cls.fromisoformat(date) if date else date_cls.today()

        # 生产环境：SELECT ... FROM patrol_logs WHERE tenant_id=... AND crew_id=... AND checked_at::date=...
        date_str = target_date.isoformat()
        logs = [
            r for r in _patrol_logs
            if r["tenant_id"] == x_tenant_id
            and r["crew_id"] == x_operator_id
            and r["checked_at"].startswith(date_str)
        ]

        # 去重计数（按 table_no）
        visited_tables: set[str] = {r["table_no"] for r in logs}

        timeline = [
            {
                "checkin_id": r["id"],
                "table_no": r["table_no"],
                "beacon_id": r["beacon_id"],
                "signal_strength": r["signal_strength"],
                "checked_at": r["checked_at"],
            }
            for r in sorted(logs, key=lambda x: x["checked_at"], reverse=True)
        ]

        log.info("patrol_summary_ok", count=len(timeline), tables=len(visited_tables))
        return {
            "ok": True,
            "data": {
                "date": date_str,
                "tables_visited_count": len(visited_tables),
                "timeline": timeline,
            },
        }
    except ValueError as exc:
        log.warning("patrol_summary_value_error", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — MLPS3-P0: 最外层HTTP兜底
        log.error("patrol_summary_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")
