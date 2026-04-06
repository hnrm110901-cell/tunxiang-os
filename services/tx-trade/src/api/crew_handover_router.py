"""服务员交接班 API 路由

提供本班数据摘要查询与交班记录保存功能。
"""
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/crew", tags=["crew-handover"])


# ---------- 请求 / 响应模型 ----------

class ShiftSummaryData(BaseModel):
    table_count: int
    order_count: int
    revenue: int                  # 分（整数避免浮点）
    bell_responses: int
    complaints: int
    good_reviews: int


class HandoverRequest(BaseModel):
    crew_id: str
    notes: Optional[str] = ""
    shift_summary_data: ShiftSummaryData


# ---------- 路由 ----------

@router.get("/shift-summary")
async def get_shift_summary(
    store_id: str = Query(..., description="门店 ID"),
    x_operator_id: str = Header(default="op-001", alias="X-Operator-ID"),
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
):
    """获取当前服务员本班数据摘要。

    返回接待桌次、点单笔数、营业额、服务铃响应次数、投诉件数、好评数。
    待接入 crew_shifts / orders 表查询，当前返回空数据结构。
    """
    log = logger.bind(operator_id=x_operator_id, store_id=store_id)
    try:
        summary = {
            "crew_id": x_operator_id,
            "shift_start": None,
            "table_count": 0,
            "order_count": 0,
            "revenue": 0,
            "bell_responses": 0,
            "complaints": 0,
            "good_reviews": 0,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        log.info("crew_shift_summary_ok", table_count=summary["table_count"])
        return {"ok": True, "data": summary}
    except ValueError as e:
        log.warning("crew_shift_summary_value_error", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001 — MLPS3-P0: 最外层HTTP兜底
        log.error("crew_shift_summary_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.post("/handover")
async def submit_handover(
    payload: HandoverRequest,
    x_tenant_id: str = Header(default="", alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """保存交班记录。

    更新 crew_shifts.end_at 与 notes，写入本班汇总数据。
    """
    log = logger.bind(crew_id=payload.crew_id, tenant_id=x_tenant_id)
    try:
        if not payload.crew_id:
            raise ValueError("crew_id 不能为空")

        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id},
        )
        await db.execute(
            text("""
                UPDATE crew_shifts
                   SET end_at = NOW(),
                       notes = :notes,
                       summary_data = :summary
                 WHERE crew_id = :crew_id
                   AND end_at IS NULL
                   AND tenant_id = :tenant_id
            """),
            {
                "crew_id": payload.crew_id,
                "notes": payload.notes or "",
                "summary": payload.shift_summary_data.model_dump(),
                "tenant_id": x_tenant_id,
            },
        )
        await db.commit()

        handover_id = f"handover-{payload.crew_id}-{int(datetime.now(timezone.utc).timestamp())}"
        log.info(
            "crew_handover_ok",
            handover_id=handover_id,
            table_count=payload.shift_summary_data.table_count,
            revenue=payload.shift_summary_data.revenue,
        )
        return {
            "ok": True,
            "data": {
                "handover_id": handover_id,
                "crew_id": payload.crew_id,
                "end_at": datetime.now(timezone.utc).isoformat(),
                "notes": payload.notes,
                "message": "交班完成",
            },
        }
    except ValueError as e:
        log.warning("crew_handover_value_error", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001 — MLPS3-P0: 最外层HTTP兜底
        log.error("crew_handover_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="服务器内部错误")
