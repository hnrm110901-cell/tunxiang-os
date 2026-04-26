"""AI运营教练 — Phase S3 全部12个API端点

端点分组：
- 教练模式（4端点）: 晨会简报 / 高峰预警 / 复盘分析 / 闭店日报
- 反馈（1端点）: 提交教练反馈
- 基线管理（4端点）: 查询 / 检测 / 更新 / 重建
- 日志查询（2端点）: 分页列表 / 详情
"""
from __future__ import annotations

from datetime import date as date_type

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from shared.ontology.src.database import get_db_with_tenant

from ..services.ai_coach_service import AICoachService
from ..services.baseline_service import BaselineService

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/agent/coaching", tags=["coaching"])


# ── 依赖 ──

async def _get_db(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> AsyncSession:
    async for session in get_db_with_tenant(x_tenant_id):
        yield session


# ══════════════════════════════════════════════
# Pydantic 请求/响应模型
# ══════════════════════════════════════════════

class MorningBriefingRequest(BaseModel):
    store_id: str = Field(..., description="门店ID")
    manager_id: str | None = Field(None, description="店长ID（可选）")


class PeakAlertRequest(BaseModel):
    store_id: str = Field(..., description="门店ID")
    slot_code: str = Field(
        ...,
        description="时段代码: lunch_peak / dinner_peak / etc.",
    )


class PostRushReviewRequest(BaseModel):
    store_id: str = Field(..., description="门店ID")
    slot_code: str = Field(
        ...,
        description="时段代码: lunch_peak / dinner_peak / etc.",
    )


class ClosingSummaryRequest(BaseModel):
    store_id: str = Field(..., description="门店ID")


class FeedbackRequest(BaseModel):
    feedback: str = Field(
        ...,
        pattern="^(helpful|not_helpful|ignored)$",
        description="反馈类型: helpful / not_helpful / ignored",
    )


class DetectAnomaliesRequest(BaseModel):
    metrics: dict[str, float] = Field(
        ...,
        description="当前指标字典, 如 {lunch_covers: 95, food_cost_rate: 38.5}",
    )
    slot_code: str | None = Field(None, description="时段代码（可选）")
    threshold_sigma: float = Field(2.0, ge=1.0, le=5.0, description="异常阈值σ")


class UpdateBaselineRequest(BaseModel):
    metric_code: str = Field(..., description="指标代码")
    value: float = Field(..., description="新数据值")
    day_of_week: int | None = Field(None, ge=0, le=6, description="星期几(0-6)")
    slot_code: str | None = Field(None, description="时段代码")


class RebuildBaselineRequest(BaseModel):
    metric_code: str = Field(..., description="指标代码")
    values: list[float] = Field(
        ..., min_length=1,
        description="历史数据值列表（至少1个）",
    )
    day_of_week: int | None = Field(None, ge=0, le=6, description="星期几(0-6)")
    slot_code: str | None = Field(None, description="时段代码")


# ══════════════════════════════════════════════
# 1. 教练模式端点
# ══════════════════════════════════════════════

@router.post("/morning-briefing")
async def morning_briefing(
    body: MorningBriefingRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """晨会简报 — 回顾昨日 + 今日预测 + 优先事项

    每天09:30自动推送或手动触发，为店长提供当天运营指南。
    """
    try:
        svc = AICoachService(db)
        result = await svc.morning_briefing(
            tenant_id=x_tenant_id,
            store_id=body.store_id,
            manager_id=body.manager_id,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/peak-alert")
async def peak_alert(
    body: PeakAlertRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """高峰预警 — 正常不说，异常论述

    在午市/晚市开始时检测指标，只有出现异常时才推送。
    正常返回 data=null。
    """
    try:
        svc = AICoachService(db)
        result = await svc.peak_alert(
            tenant_id=x_tenant_id,
            store_id=body.store_id,
            slot_code=body.slot_code,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/post-rush-review")
async def post_rush_review(
    body: PostRushReviewRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """复盘分析 — 午后/晚后回顾

    对比时段指标与基线，汇总SOP完成度，生成亮点和改进建议。
    """
    try:
        svc = AICoachService(db)
        result = await svc.post_rush_review(
            tenant_id=x_tenant_id,
            store_id=body.store_id,
            slot_code=body.slot_code,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/closing-summary")
async def closing_summary(
    body: ClosingSummaryRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """闭店日报 — 全天汇总

    21:00-23:00自动推送，包含全天指标、SOP报告、经验教训和明日建议。
    """
    try:
        svc = AICoachService(db)
        result = await svc.closing_summary(
            tenant_id=x_tenant_id,
            store_id=body.store_id,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ══════════════════════════════════════════════
# 2. 反馈
# ══════════════════════════════════════════════

@router.post("/feedback/{coaching_id}")
async def submit_feedback(
    coaching_id: str = Path(..., description="教练日志ID"),
    body: FeedbackRequest = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """提交教练反馈

    用户对教练推送的满意度反馈: helpful / not_helpful / ignored
    用于持续优化教练推送质量。
    """
    try:
        svc = AICoachService(db)
        result = await svc.submit_feedback(
            tenant_id=x_tenant_id,
            coaching_id=coaching_id,
            feedback=body.feedback,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ══════════════════════════════════════════════
# 3. 基线管理
# ══════════════════════════════════════════════

@router.get("/baselines/{store_id}")
async def get_baselines(
    store_id: str = Path(..., description="门店ID"),
    slot_code: str | None = Query(None, description="时段代码过滤"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """查询门店所有基线数据

    可选按时段过滤，返回各指标的历史均值、标准差、样本数等。
    """
    svc = BaselineService(db)
    baselines = await svc.get_all_baselines(
        tenant_id=x_tenant_id,
        store_id=store_id,
        slot_code=slot_code,
    )
    return {"ok": True, "data": baselines}


@router.post("/baselines/{store_id}/detect")
async def detect_anomalies(
    store_id: str = Path(..., description="门店ID"),
    body: DetectAnomaliesRequest = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """异常检测 — 正常不说，异常论述

    传入当前指标，对比基线检测异常。
    >2sigma=warning, >3sigma=critical。
    无异常返回空列表。
    """
    svc = BaselineService(db)
    anomalies = await svc.detect_anomalies(
        tenant_id=x_tenant_id,
        store_id=store_id,
        current_metrics=body.metrics,
        slot_code=body.slot_code,
        threshold_sigma=body.threshold_sigma,
    )
    return {"ok": True, "data": anomalies}


@router.post("/baselines/{store_id}/update")
async def update_baseline(
    store_id: str = Path(..., description="门店ID"),
    body: UpdateBaselineRequest = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """增量更新基线 — Welford在线算法

    每个新数据点增量更新均值和标准差，无需全量重算。
    """
    try:
        svc = BaselineService(db)
        result = await svc.upsert_baseline(
            tenant_id=x_tenant_id,
            store_id=store_id,
            metric_code=body.metric_code,
            value=body.value,
            day_of_week=body.day_of_week,
            slot_code=body.slot_code,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/baselines/{store_id}/rebuild")
async def rebuild_baseline(
    store_id: str = Path(..., description="门店ID"),
    body: RebuildBaselineRequest = ...,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """从历史数据重建基线

    传入全部历史值，完全重算均值、标准差、极值。
    用于初始化或修正错误的基线。
    """
    try:
        svc = BaselineService(db)
        result = await svc.rebuild_from_history(
            tenant_id=x_tenant_id,
            store_id=store_id,
            metric_code=body.metric_code,
            values=body.values,
            day_of_week=body.day_of_week,
            slot_code=body.slot_code,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ══════════════════════════════════════════════
# 4. 教练日志查询
# ══════════════════════════════════════════════

@router.get("/logs/{store_id}")
async def list_coaching_logs(
    store_id: str = Path(..., description="门店ID"),
    coaching_type: str | None = Query(
        None,
        description="教练类型过滤: morning_brief/peak_alert/post_rush_review/closing_summary",
    ),
    start_date: date_type | None = Query(None, description="开始日期"),
    end_date: date_type | None = Query(None, description="结束日期"),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页条数"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """分页列出教练日志

    支持按教练类型和日期范围过滤。
    """
    try:
        svc = AICoachService(db)
        result = await svc.list_coaching_logs(
            tenant_id=x_tenant_id,
            store_id=store_id,
            coaching_type=coaching_type,
            start_date=start_date,
            end_date=end_date,
            page=page,
            size=size,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/logs/detail/{coaching_id}")
async def get_coaching_log_detail(
    coaching_id: str = Path(..., description="教练日志ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(_get_db),
) -> dict:
    """获取教练日志详情

    返回完整的上下文快照和建议内容。
    """
    try:
        svc = AICoachService(db)
        result = await svc.get_coaching_log(
            tenant_id=x_tenant_id,
            coaching_id=coaching_id,
        )
        return {"ok": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
