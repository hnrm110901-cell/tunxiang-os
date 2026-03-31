"""经营诊断 Router

路由：
  POST /api/v1/agent/diagnosis/run          — 手动触发诊断（调试用）
  GET  /api/v1/agent/diagnosis/reports      — 查询历史诊断报告列表
  GET  /api/v1/agent/diagnosis/reports/{report_id} — 查询单条报告详情
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/agent/diagnosis", tags=["diagnosis"])


# ─────────────────────────────────────────────────────────────────────────────
# 请求 / 响应模型
# ─────────────────────────────────────────────────────────────────────────────
class RunDiagnosisRequest(BaseModel):
    store_id: str
    target_date: Optional[date] = None  # 默认昨天


class RunDiagnosisResponse(BaseModel):
    report_id: str
    store_id: str
    report_date: str
    anomaly_count: int
    critical_count: int
    summary_text: str


# ─────────────────────────────────────────────────────────────────────────────
# 端点
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/run", response_model=dict)
async def run_diagnosis(
    body: RunDiagnosisRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """手动触发经营诊断（调试 / 补跑场景）。

    生产环境由 scheduler.py 每日 07:00 自动调用。
    """
    from ..business_diagnosis_agent import BusinessDiagnosisAgent

    log = logger.bind(tenant_id=x_tenant_id, store_id=body.store_id)
    log.info("manual_diagnosis_triggered", target_date=str(body.target_date))

    try:
        agent = BusinessDiagnosisAgent(
            tenant_id=x_tenant_id,
            store_id=body.store_id,
        )
        report = await agent.run(target_date=body.target_date)

        critical_count = sum(
            1 for a in report.anomalies if a.severity.value == "critical"
        )
        return {
            "ok": True,
            "data": RunDiagnosisResponse(
                report_id=report.id,
                store_id=report.store_id,
                report_date=str(report.report_date),
                anomaly_count=len(report.anomalies),
                critical_count=critical_count,
                summary_text=report.summary_text,
            ).model_dump(),
        }
    except ValueError as exc:
        log.error("diagnosis_value_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — 最外层HTTP兜底
        log.error("diagnosis_unexpected_error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="诊断执行失败") from exc


@router.get("/reports", response_model=dict)
async def list_reports(
    store_id: str = Query(..., description="门店 ID"),
    start_date: Optional[date] = Query(None, description="开始日期（含）"),
    end_date: Optional[date] = Query(None, description="结束日期（含）"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """查询历史诊断报告列表（分页）。

    TODO: 对接 business_diagnosis_reports 表查询逻辑。
    """
    logger.info(
        "list_reports",
        tenant_id=x_tenant_id,
        store_id=store_id,
        start_date=str(start_date),
        end_date=str(end_date),
        page=page,
        size=size,
    )
    # TODO: 从 business_diagnosis_reports 表分页查询
    # SELECT * FROM business_diagnosis_reports
    # WHERE tenant_id = :tenant_id AND store_id = :store_id
    #   AND (:start_date IS NULL OR report_date >= :start_date)
    #   AND (:end_date IS NULL OR report_date <= :end_date)
    # ORDER BY report_date DESC
    # LIMIT :size OFFSET (:page - 1) * :size
    return {
        "ok": True,
        "data": {
            "items": [],
            "total": 0,
            "page": page,
            "size": size,
        },
    }


@router.get("/reports/{report_id}", response_model=dict)
async def get_report(
    report_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> dict:
    """查询单条诊断报告详情。

    TODO: 对接 business_diagnosis_reports 表查询逻辑。
    """
    logger.info("get_report", tenant_id=x_tenant_id, report_id=report_id)
    # TODO: 从 business_diagnosis_reports 表查询
    # SELECT * FROM business_diagnosis_reports
    # WHERE id = :report_id AND tenant_id = :tenant_id
    raise HTTPException(status_code=404, detail="报告不存在或暂未实现持久化查询")
