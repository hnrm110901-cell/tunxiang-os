"""菜品生命周期AI — API路由

端点列表（原有）：
    GET  /dish-lifecycle/health-scores              菜品健康评分列表
    GET  /dish-lifecycle/health-scores/{dish_id}    单品评分明细
    GET  /dish-lifecycle/sellout-warnings/{store_id} 沽清预警
    GET  /dish-lifecycle/removal-suggestions/{store_id} 下架建议
    POST /dish-lifecycle/run-checks                 每日检查（定时任务）
    GET  /dish-lifecycle/new-dish-report/{dish_id}  新品评测报告

新增端点（生命周期管理）：
    GET  /api/v1/menu/lifecycle/stages              生命周期阶段列表
    POST /api/v1/dishes/{id}/lifecycle/advance      推进生命周期
    GET  /api/v1/menu/lifecycle/report              按阶段统计
    POST /api/v1/dishes/{id}/lifecycle/retire       下线菜品（归档）

# ROUTER REGISTRATION:
# from .api.dish_lifecycle_routes import router as dish_lifecycle_router
# app.include_router(dish_lifecycle_router, prefix="/api/v1/dish-lifecycle")
"""
import uuid as _uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.dish_health_score import DishHealthScoreEngine, ScoreWeights
from ..services.dish_lifecycle import DishLifecycleService

log = structlog.get_logger(__name__)
router = APIRouter(tags=["dish-lifecycle"])

# 生命周期阶段及顺序
_LIFECYCLE_STAGES = [
    {
        "stage": "research",
        "display": "研发中",
        "description": "菜品研发阶段，尚未上市，仅内部测试",
        "order": 1,
        "next": "testing",
    },
    {
        "stage": "testing",
        "display": "内测期",
        "description": "小范围内部试吃，收集反馈",
        "order": 2,
        "next": "pilot",
    },
    {
        "stage": "pilot",
        "display": "试卖期",
        "description": "部分门店上线，评测销量与口碑（7天评测期）",
        "order": 3,
        "next": "full",
    },
    {
        "stage": "full",
        "display": "正式销售",
        "description": "全渠道正常销售",
        "order": 4,
        "next": "sunset",
    },
    {
        "stage": "sunset",
        "display": "夕阳期",
        "description": "健康评分持续下降，准备逐步退出",
        "order": 5,
        "next": "discontinued",
    },
    {
        "stage": "discontinued",
        "display": "已停售",
        "description": "已从所有渠道下线，保留历史数据",
        "order": 6,
        "next": None,
    },
]

_STAGE_NAMES = [s["stage"] for s in _LIFECYCLE_STAGES]
_STAGE_ORDER = {s["stage"]: s["order"] for s in _LIFECYCLE_STAGES}


# ─── 依赖注入占位 ─────────────────────────────────────────────────────────────


async def get_db() -> AsyncSession:  # type: ignore[override]
    """数据库会话依赖 — 由 main.py 中 app.dependency_overrides 注入"""
    raise NotImplementedError("DB session dependency not configured")


# ─── 请求模型 ─────────────────────────────────────────────────────────────────


class RunChecksReq(BaseModel):
    tenant_id: str


# ─── 端点 ─────────────────────────────────────────────────────────────────────


@router.get("/health-scores")
async def list_health_scores(
    store_id: str = Query(..., description="门店ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取门店所有菜品健康评分列表（按综合评分升序，最差在前）

    Returns:
        scores: 健康评分列表
        count: 菜品总数
        low_health_count: 低健康分菜品数（< 40分）
    """
    engine = DishHealthScoreEngine()
    scores = await engine.score_all_dishes(store_id=store_id, tenant_id=x_tenant_id, db=db)
    low_health_count = sum(1 for s in scores if s.total_score < 40.0)
    return {
        "ok": True,
        "data": {
            "scores": [s.to_dict() for s in scores],
            "count": len(scores),
            "low_health_count": low_health_count,
        },
    }


@router.get("/health-scores/{dish_id}")
async def get_health_score(
    dish_id: str,
    store_id: str = Query(..., description="门店ID"),
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取单道菜健康评分明细（含三维子分）

    Returns:
        score: 评分详情（含 margin_score / sales_rank_score / review_score）
    """
    engine = DishHealthScoreEngine()
    score = await engine.score_dish(
        dish_id=dish_id,
        store_id=store_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    if score is None:
        return {"ok": False, "error": {"code": "DISH_NOT_FOUND", "message": "菜品不存在或无数据"}}
    return {"ok": True, "data": {"score": score.to_dict()}}


@router.get("/sellout-warnings/{store_id}")
async def get_sellout_warnings(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取门店沽清预警列表（库存低于2天用量）

    Returns:
        warnings: 预警列表（含 days_remaining / warning_level）
    """
    svc = DishLifecycleService()
    warnings = await svc.check_sellout_warnings(
        store_id=store_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {
        "ok": True,
        "data": {
            "warnings": [w.to_dict() for w in warnings],
            "count": len(warnings),
        },
    }


@router.get("/removal-suggestions/{store_id}")
async def get_removal_suggestions(
    store_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取下架建议列表（含理由和数据支撑）

    触发条件：
    - 健康分 < 40 持续30天
    - 评测期内零销量
    - 毛利率持续低于10%

    Returns:
        suggestions: 建议列表（含 reason / evidence / priority）
    """
    svc = DishLifecycleService()
    suggestions = await svc.generate_removal_suggestions(
        store_id=store_id,
        tenant_id=x_tenant_id,
        db=db,
    )
    return {
        "ok": True,
        "data": {
            "suggestions": [s.to_dict() for s in suggestions],
            "count": len(suggestions),
        },
    }


@router.post("/run-checks")
async def run_daily_checks(
    req: RunChecksReq,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """触发每日生命周期检查（管理员 / 定时任务专用）

    执行：新品7天评测 + 健康分低于阈值菜品标记。
    沽清预警和下架建议请分别调用对应端点（需要 store_id）。

    Returns:
        run_at: 执行时间
        eval_reports: 评测报告摘要
        low_health_dishes: 本次被标记为低健康状态的菜品ID列表
    """
    # X-Tenant-ID header 与 body 中的 tenant_id 必须一致（双重校验）
    if req.tenant_id != x_tenant_id:
        return {
            "ok": False,
            "error": {
                "code": "TENANT_MISMATCH",
                "message": "X-Tenant-ID 与请求体 tenant_id 不匹配",
            },
        }

    svc = DishLifecycleService()
    result = await svc.run_daily_checks(tenant_id=x_tenant_id, db=db)
    return {"ok": True, "data": result}


@router.get("/new-dish-report/{dish_id}")
async def get_new_dish_report(
    dish_id: str,
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
):
    """获取新品评测报告

    返回指定菜品的7天评测结果，含销量、毛利率、评测结论和建议。

    Returns:
        report: 评测报告（verdict / suggestions / eval_sales / margin_rate）
    """
    svc = DishLifecycleService()
    # 触发全租户评测并过滤出指定菜品
    reports = await svc.check_new_dish_evaluations(tenant_id=x_tenant_id, db=db)
    matching = [r.to_dict() for r in reports if r.dish_id == dish_id]

    if not matching:
        return {
            "ok": False,
            "error": {
                "code": "REPORT_NOT_FOUND",
                "message": "该菜品暂无评测报告（可能未到评测期或已过期）",
            },
        }
    return {"ok": True, "data": {"report": matching[0]}}


# ─── 生命周期管理端点（挂载在 /api/v1 下，单独路由） ─────────────────────────────
# 使用独立 router 以便 main.py 挂载时不加 dish-lifecycle 前缀

lifecycle_router = APIRouter(prefix="/api/v1", tags=["dish-lifecycle-manage"])


async def _get_lifecycle_db() -> AsyncSession:  # type: ignore[override]
    """数据库会话依赖 — 由 main.py 中 app.dependency_overrides 注入"""
    raise NotImplementedError("DB session dependency not configured")


async def _set_rls(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id},
    )


def _tenant_from_request(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID", "")
    if not tid:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
    return tid


class AdvanceLifecycleReq(BaseModel):
    target_stage: str = Field(
        ...,
        description="目标阶段: research/testing/pilot/full/sunset/discontinued",
    )
    reason: str = Field(..., min_length=1, description="推进原因（必填，用于审计）")
    operator_id: str = Field(..., description="操作人 ID")


@lifecycle_router.get("/menu/lifecycle/stages", summary="菜品生命周期阶段列表")
async def list_lifecycle_stages(
    request: Request,
) -> dict:
    """返回系统定义的所有生命周期阶段及流转规则。

    阶段顺序：research → testing → pilot → full → sunset → discontinued
    """
    return {
        "ok": True,
        "data": {
            "stages": _LIFECYCLE_STAGES,
            "total": len(_LIFECYCLE_STAGES),
        },
    }


@lifecycle_router.post(
    "/dishes/{dish_id}/lifecycle/advance",
    summary="推进菜品生命周期阶段",
)
async def advance_lifecycle(
    dish_id: str,
    req: AdvanceLifecycleReq,
    request: Request,
    db: AsyncSession = Depends(_get_lifecycle_db),
) -> dict:
    """推进菜品到指定生命周期阶段。

    规则：
    - 目标阶段必须在阶段列表中
    - 只能向后推进（不可回退），discontinued 为终态
    - 操作记录写入审计日志（结构化日志）

    推进到 discontinued 阶段时，请改用 POST /dishes/{id}/lifecycle/retire。
    """
    if req.target_stage not in _STAGE_NAMES:
        raise HTTPException(
            status_code=400,
            detail=f"无效的生命周期阶段: {req.target_stage}，有效值: {_STAGE_NAMES}",
        )
    if req.target_stage == "discontinued":
        raise HTTPException(
            status_code=400,
            detail="停售操作请使用 POST /dishes/{id}/lifecycle/retire",
        )

    tenant_id = _tenant_from_request(request)
    await _set_rls(db, tenant_id)
    tid = _uuid.UUID(tenant_id)

    try:
        did = _uuid.UUID(dish_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"dish_id 格式错误: {dish_id}") from exc

    # 查询当前阶段
    dish_result = await db.execute(
        text("""
            SELECT id, dish_name, lifecycle_stage, is_deleted
            FROM dishes
            WHERE id = :did AND tenant_id = :tid
        """),
        {"did": did, "tid": tid},
    )
    dish_row = dish_result.fetchone()
    if not dish_row:
        raise HTTPException(status_code=404, detail=f"菜品不存在: {dish_id}")
    if dish_row[3]:  # is_deleted
        raise HTTPException(status_code=422, detail="已删除的菜品无法推进生命周期")

    current_stage = dish_row[2] or "full"
    current_order = _STAGE_ORDER.get(current_stage, 4)
    target_order = _STAGE_ORDER[req.target_stage]

    if target_order <= current_order:
        raise HTTPException(
            status_code=422,
            detail=f"生命周期只能向后推进（当前: {current_stage}[{current_order}] → 目标: {req.target_stage}[{target_order}]）",
        )

    # 更新生命周期阶段
    await db.execute(
        text("""
            UPDATE dishes
            SET lifecycle_stage      = :stage,
                lifecycle_changed_at = NOW(),
                updated_at           = NOW()
            WHERE id = :did AND tenant_id = :tid
        """),
        {"stage": req.target_stage, "did": did, "tid": tid},
    )
    await db.commit()

    log.info(
        "lifecycle.advanced",
        dish_id=dish_id,
        dish_name=dish_row[1],
        from_stage=current_stage,
        to_stage=req.target_stage,
        operator_id=req.operator_id,
        reason=req.reason,
        tenant_id=tenant_id,
    )
    return {
        "ok": True,
        "data": {
            "dish_id": dish_id,
            "dish_name": dish_row[1],
            "from_stage": current_stage,
            "to_stage": req.target_stage,
            "operator_id": req.operator_id,
            "reason": req.reason,
            "changed_at": datetime.now(tz=timezone.utc).isoformat(),
        },
    }


@lifecycle_router.get("/menu/lifecycle/report", summary="按阶段统计菜品数量")
async def lifecycle_report(
    store_id: Optional[str] = Query(None, description="门店ID，不传则统计全租户"),
    request: Request = None,
    db: AsyncSession = Depends(_get_lifecycle_db),
) -> dict:
    """按生命周期阶段统计菜品数量，返回各阶段菜品分布。"""
    tenant_id = _tenant_from_request(request)
    await _set_rls(db, tenant_id)
    tid = _uuid.UUID(tenant_id)

    params: dict = {"tid": tid}
    store_clause = ""
    if store_id:
        store_clause = "AND store_id = :sid"
        try:
            params["sid"] = _uuid.UUID(store_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"store_id 格式错误: {store_id}") from exc

    result = await db.execute(
        text(f"""
            SELECT
                COALESCE(lifecycle_stage, 'full') AS stage,
                COUNT(*) AS cnt
            FROM dishes
            WHERE tenant_id = :tid
              AND is_deleted = false
              {store_clause}
            GROUP BY 1
        """),
        params,
    )
    counts: dict[str, int] = {row[0]: int(row[1]) for row in result.fetchall()}

    # 按定义顺序组装，补全为 0 的阶段
    report = [
        {
            "stage": s["stage"],
            "display": s["display"],
            "count": counts.get(s["stage"], 0),
        }
        for s in _LIFECYCLE_STAGES
    ]
    total = sum(item["count"] for item in report)

    log.info("lifecycle.report", store_id=store_id, total=total, tenant_id=tenant_id)
    return {
        "ok": True,
        "data": {
            "stages": report,
            "total": total,
            "store_id": store_id,
        },
    }


@lifecycle_router.post(
    "/dishes/{dish_id}/lifecycle/retire",
    summary="下线菜品（归档，保留历史订单记录）",
)
async def retire_dish(
    dish_id: str,
    request: Request,
    db: AsyncSession = Depends(_get_lifecycle_db),
) -> dict:
    """将菜品归档下线（lifecycle_stage → discontinued）。

    操作效果：
    - dishes.is_available = false（停止接单）
    - dishes.lifecycle_stage = 'discontinued'
    - channel_menu_items.is_available = false（所有渠道下线）
    - 历史订单记录保留，不删除

    注意：此操作不可逆，如需重新上线请联系管理员。
    """
    tenant_id = _tenant_from_request(request)
    await _set_rls(db, tenant_id)
    tid = _uuid.UUID(tenant_id)

    try:
        did = _uuid.UUID(dish_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"dish_id 格式错误: {dish_id}") from exc

    # 查询菜品信息
    dish_result = await db.execute(
        text("SELECT id, dish_name, lifecycle_stage, is_deleted FROM dishes WHERE id = :did AND tenant_id = :tid"),
        {"did": did, "tid": tid},
    )
    dish_row = dish_result.fetchone()
    if not dish_row:
        raise HTTPException(status_code=404, detail=f"菜品不存在: {dish_id}")
    if dish_row[3]:  # is_deleted
        raise HTTPException(status_code=422, detail="该菜品已物理删除，无法执行归档")
    if dish_row[2] == "discontinued":
        raise HTTPException(status_code=422, detail="该菜品已处于 discontinued 状态")

    previous_stage = dish_row[2] or "full"

    # 1. 更新 dishes 表
    await db.execute(
        text("""
            UPDATE dishes
            SET is_available         = false,
                lifecycle_stage      = 'discontinued',
                lifecycle_changed_at = NOW(),
                updated_at           = NOW()
            WHERE id = :did AND tenant_id = :tid
        """),
        {"did": did, "tid": tid},
    )

    # 2. 下线所有渠道的菜品映射
    channels_result = await db.execute(
        text("""
            UPDATE channel_menu_items
            SET is_available = false, updated_at = NOW()
            WHERE dish_id = :did AND tenant_id = :tid
            RETURNING channel
        """),
        {"did": did, "tid": tid},
    )
    retired_channels = [row[0] for row in channels_result.fetchall()]

    await db.commit()

    log.info(
        "lifecycle.retired",
        dish_id=dish_id,
        dish_name=dish_row[1],
        previous_stage=previous_stage,
        channels_retired=retired_channels,
        tenant_id=tenant_id,
    )
    return {
        "ok": True,
        "data": {
            "dish_id": dish_id,
            "dish_name": dish_row[1],
            "previous_stage": previous_stage,
            "current_stage": "discontinued",
            "channels_retired": retired_channels,
            "retired_at": datetime.now(tz=timezone.utc).isoformat(),
            "note": "历史订单记录已保留，菜品已从所有渠道下线",
        },
    }
