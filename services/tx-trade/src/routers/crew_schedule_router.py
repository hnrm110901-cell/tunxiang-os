"""服务员排班打卡 API 路由

涵盖:
- POST /api/v1/crew/checkin        — 打卡记录（上班/下班，验证时间窗口）
- GET  /api/v1/crew/schedule       — 本周排班数据
- POST /api/v1/crew/shift-swap     — 创建换班申请
- GET  /api/v1/crew/shift-swaps    — 查询我的换班申请列表
"""
from datetime import date, datetime, time, timedelta
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["crew-schedule"])

# ---------- Pydantic 模型 ----------

class CheckinRequest(BaseModel):
    type: Literal["clock_in", "clock_out"]
    lat: Optional[float] = Field(None, description="纬度")
    lng: Optional[float] = Field(None, description="经度")
    device_id: Optional[str] = Field(None, description="设备ID")


class ShiftSwapRequest(BaseModel):
    from_date: str = Field(..., description="换班日期 YYYY-MM-DD")
    to_crew_id: str = Field(..., description="接班同事ID或姓名")
    reason: Optional[str] = Field(None, description="换班原因")


# ---------- Mock 排班数据 ----------

def _build_week_schedule(crew_id: str) -> list[dict]:
    """返回本周7天排班数据（Mock 实现）。"""
    today = date.today()
    # 从本周周一开始（isoweekday: 周一=1）
    monday = today - timedelta(days=today.isoweekday() - 1)
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    shift_cycle = [
        {"shift": "午班", "start": "11:00", "end": "17:00"},
        {"shift": "晚班", "start": "17:00", "end": "22:00"},
        {"shift": "",     "start": "",      "end": ""},
        {"shift": "早班", "start": "09:00", "end": "14:00"},
        {"shift": "午班", "start": "11:00", "end": "17:00"},
        {"shift": "晚班", "start": "17:00", "end": "22:00"},
        {"shift": "午班", "start": "11:00", "end": "17:00"},
    ]
    items = []
    for i in range(7):
        day = monday + timedelta(days=i)
        s = shift_cycle[i]
        if day < today:
            status = "present" if s["shift"] else "pending"
        elif day == today:
            status = "today"
        else:
            status = "pending"

        items.append({
            "date": day.isoformat(),
            "date_label": day.strftime("%m-%d"),
            "weekday": weekday_names[i],
            "shift": s["shift"],
            "time_range": f"{s['start']}-{s['end']}" if s["shift"] else "",
            "status": status,
            "is_today": day == today,
        })
    return items


def _build_mock_swaps(crew_id: str) -> list[dict]:
    """返回换班申请 Mock 数据。"""
    today = date.today()
    return [
        {
            "id": "sw-001",
            "from_date": (today - timedelta(days=3)).strftime("%m-%d"),
            "to_crew": "李四",
            "reason": "家里有事",
            "status": "approved",
            "created_at": (today - timedelta(days=4)).strftime("%m-%d") + " 10:20",
        },
        {
            "id": "sw-002",
            "from_date": (today + timedelta(days=2)).strftime("%m-%d"),
            "to_crew": "王五",
            "reason": "看病",
            "status": "pending",
            "created_at": (today - timedelta(days=1)).strftime("%m-%d") + " 14:05",
        },
    ]


# ---------- 时间窗口校验 ----------

_CLOCK_WINDOW_HOURS_BEFORE = 1   # 班次开始前 N 小时内可打上班卡
_CLOCK_WINDOW_HOURS_AFTER  = 2   # 班次结束后 N 小时内可打下班卡


def _validate_clock_window(checkin_type: str, now: datetime) -> bool:
    """
    简化时间窗口校验（Mock 实现）。
    生产环境应从 DB 查询当班班次时间，判断是否在允许范围内。
    当前实现：仅允许 06:00-24:00 期间打卡。
    """
    hour = now.hour
    if checkin_type == "clock_in":
        return 6 <= hour <= 23
    # clock_out
    return 6 <= hour <= 24


# ---------- 路由 ----------

@router.post("/api/v1/crew/checkin")
async def checkin(
    body: CheckinRequest,
    x_operator_id: str = Header(default="op-001", alias="X-Operator-ID"),
    x_tenant_id: str   = Header(default="",       alias="X-Tenant-ID"),
):
    """
    记录打卡。

    - 验证打卡时间窗口（允许窗口外打卡但返回 warning）。
    - 记录 GPS 坐标（可选）。
    - 记录设备 ID（可选）。
    """
    log = logger.bind(operator_id=x_operator_id, tenant_id=x_tenant_id, type=body.type)
    try:
        now = datetime.now()
        in_window = _validate_clock_window(body.type, now)

        log.info(
            "crew_checkin",
            lat=body.lat,
            lng=body.lng,
            device_id=body.device_id,
            in_window=in_window,
        )

        # 生产环境：写入 DB（crew_checkin_records 表）
        record = {
            "operator_id": x_operator_id,
            "tenant_id": x_tenant_id,
            "type": body.type,
            "checkin_at": now.isoformat(),
            "lat": body.lat,
            "lng": body.lng,
            "device_id": body.device_id,
            "in_window": in_window,
        }

        warning = None if in_window else "打卡时间不在标准班次窗口内，已记录但待主管确认"

        return {
            "ok": True,
            "data": {
                "record": record,
                "warning": warning,
            },
        }
    except ValueError as e:
        log.warning("crew_checkin_value_error", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error("crew_checkin_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.get("/api/v1/crew/schedule")
async def get_schedule(
    week: Literal["current", "next"] = Query("current", description="current=本周 / next=下周"),
    x_operator_id: str = Header(default="op-001", alias="X-Operator-ID"),
    x_tenant_id: str   = Header(default="",       alias="X-Tenant-ID"),
):
    """
    返回指定周的排班数据。

    week=current 返回本周（周一至周日），week=next 返回下周。
    """
    log = logger.bind(operator_id=x_operator_id, tenant_id=x_tenant_id, week=week)
    try:
        items = _build_week_schedule(x_operator_id)
        if week == "next":
            # 下周：日期各 +7 天
            for item in items:
                d = date.fromisoformat(item["date"]) + timedelta(days=7)
                item["date"] = d.isoformat()
                item["date_label"] = d.strftime("%m-%d")
                item["is_today"] = False
                if item["status"] == "today":
                    item["status"] = "pending"

        log.info("crew_schedule_ok", count=len(items))
        return {"ok": True, "data": {"items": items, "total": len(items), "week": week}}
    except ValueError as e:
        log.warning("crew_schedule_value_error", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error("crew_schedule_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.post("/api/v1/crew/shift-swap")
async def create_shift_swap(
    body: ShiftSwapRequest,
    x_operator_id: str = Header(default="op-001", alias="X-Operator-ID"),
    x_tenant_id: str   = Header(default="",       alias="X-Tenant-ID"),
):
    """
    创建换班申请。

    生产环境：写入 crew_shift_swaps 表，通知审批人。
    """
    log = logger.bind(operator_id=x_operator_id, tenant_id=x_tenant_id)
    try:
        # 基础校验
        try:
            swap_date = date.fromisoformat(body.from_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="from_date 格式错误，应为 YYYY-MM-DD")

        if swap_date <= date.today():
            raise HTTPException(status_code=400, detail="换班日期必须晚于今天")

        if not body.to_crew_id.strip():
            raise HTTPException(status_code=400, detail="接班同事不能为空")

        swap_id = f"sw-{int(datetime.now().timestamp())}"
        record = {
            "id": swap_id,
            "operator_id": x_operator_id,
            "tenant_id": x_tenant_id,
            "from_date": body.from_date,
            "to_crew_id": body.to_crew_id,
            "reason": body.reason,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
        }

        log.info("crew_shift_swap_created", swap_id=swap_id, from_date=body.from_date)
        return {"ok": True, "data": record}
    except HTTPException:
        raise
    except ValueError as e:
        log.warning("crew_shift_swap_value_error", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error("crew_shift_swap_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.get("/api/v1/crew/shift-swaps")
async def get_my_shift_swaps(
    status: Optional[Literal["pending", "approved", "rejected"]] = Query(
        None, description="筛选状态，不传则返回全部"
    ),
    x_operator_id: str = Header(default="op-001", alias="X-Operator-ID"),
    x_tenant_id: str   = Header(default="",       alias="X-Tenant-ID"),
):
    """
    查询我的换班申请列表。

    可按 status 筛选：pending / approved / rejected。
    """
    log = logger.bind(operator_id=x_operator_id, tenant_id=x_tenant_id, status=status)
    try:
        items = _build_mock_swaps(x_operator_id)
        if status:
            items = [i for i in items if i["status"] == status]

        log.info("crew_shift_swaps_ok", count=len(items))
        return {"ok": True, "data": {"items": items, "total": len(items)}}
    except ValueError as e:
        log.warning("crew_shift_swaps_value_error", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error("crew_shift_swaps_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")
