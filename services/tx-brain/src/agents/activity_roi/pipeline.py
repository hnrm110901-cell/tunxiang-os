"""Activity ROI Pipeline（D3b）

把 Prophet baseline + 增量模型 + Sonnet 叙述拼装为 ActivityROIResponse。

增量模型（v1）：硬编码 activity_type → lift_factor 表。这是务实第一版，
等真实 A/B 数据回灌后用因果推断升级（TODO）。
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import date, timedelta
from typing import Protocol

from .prophet_baseline import (
    HistoricalGmvRepository,
    ProphetBaselineService,
    estimate_mape_holdout,
)
from .schemas import (
    ActivityROIPredictionPoint,
    ActivityROIRequest,
    ActivityROIResponse,
)
from .sonnet_narrator import ActivityROINarrator, ModelRouterLike

logger = logging.getLogger(__name__)


# ─── 增量模型（v1：硬编码） ──────────────────────────────────────────────────
#
# lift_factor: 活动期间 daily GMV 相对 baseline 的乘数（含正向 lift）
#   1.20 表示 +20% 增量
# margin_rate: 增量 GMV 中实现的毛利率（扣除食材/人力/平台抽佣后剩余）
#
# 数字来源：徐记海鲜历史活动 + 行业经验 + 团购平台抽佣率（抖音通常 5-8%）
# TODO(D3b-v2): 接入 mv_channel_margin / mv_store_pnl 后改为按门店/品牌动态学习

ACTIVITY_LIFT_TABLE: dict[str, dict[str, float]] = {
    "full_reduction":       {"lift_factor": 1.18, "margin_rate": 0.45, "ci_width": 0.10},
    "member_day":           {"lift_factor": 1.25, "margin_rate": 0.50, "ci_width": 0.08},
    "douyin_groupon":       {"lift_factor": 1.40, "margin_rate": 0.30, "ci_width": 0.15},
    "xiaohongshu_coupon":   {"lift_factor": 1.15, "margin_rate": 0.42, "ci_width": 0.12},
    "wechat_groupon":       {"lift_factor": 1.22, "margin_rate": 0.38, "ci_width": 0.10},
    "second_half_off":      {"lift_factor": 1.20, "margin_rate": 0.40, "ci_width": 0.10},
    "free_dish":            {"lift_factor": 1.10, "margin_rate": 0.35, "ci_width": 0.12},
    "limited_time_special": {"lift_factor": 1.12, "margin_rate": 0.45, "ci_width": 0.10},
}

DEFAULT_LIFT = {"lift_factor": 1.10, "margin_rate": 0.40, "ci_width": 0.15}


# ─── 商户档案 Repo（可选注入；缺省返回 {}） ──────────────────────────────────


class MerchantProfileRepository(Protocol):
    """商户档案仓储——给 Sonnet 叙述提供 cache 友好的稳定上下文。"""

    async def fetch_profile(self, tenant_id, store_id) -> dict:  # type: ignore[no-untyped-def]
        """返回 {brand, city, cuisine, avg_check_yuan, ...} 等稳定信息。"""
        ...


class _NullMerchantRepo:
    async def fetch_profile(self, tenant_id, store_id) -> dict:  # type: ignore[no-untyped-def]
        return {}


# ─── Pipeline ────────────────────────────────────────────────────────────────


class ActivityROIPipeline:
    """活动 ROI 预测 Pipeline。"""

    def __init__(
        self,
        *,
        gmv_repository: HistoricalGmvRepository,
        narrator: ActivityROINarrator,
        merchant_repository: MerchantProfileRepository | None = None,
        baseline_service: ProphetBaselineService | None = None,
    ) -> None:
        self._gmv_repo = gmv_repository
        self._narrator = narrator
        self._merchant_repo = merchant_repository or _NullMerchantRepo()
        self._baseline = baseline_service or ProphetBaselineService(gmv_repository)

    async def predict(self, req: ActivityROIRequest) -> ActivityROIResponse:
        request_id = uuid.uuid4()

        # 1) 计算预测日期序列（含起止两端）
        predict_dates = _date_range(req.start_at.date(), req.end_at.date())

        # 2) Prophet baseline
        baseline_points = await self._baseline.forecast_baseline(
            tenant_id=req.tenant_id,
            store_id=req.store_id,
            train_window_days=req.historical_baseline_days,
            predict_dates=predict_dates,
        )

        # 3) MAPE 估计：再拉一次训练数据，用尾部 7 天回测
        end_train = req.start_at.date() - timedelta(days=1)
        start_train = end_train - timedelta(days=req.historical_baseline_days - 1)
        history_for_mape = await self._gmv_repo.fetch_daily_gmv(
            tenant_id=req.tenant_id,
            store_id=req.store_id,
            start=start_train,
            end=end_train,
        )
        mape = estimate_mape_holdout(history_for_mape, holdout_days=7)
        if math.isinf(mape):
            mape = 0.20  # 历史不足 21 天时给保守估计 20%

        # 4) 增量模型：把 baseline 按 activity_type 对应的 lift_factor 放大
        params = ACTIVITY_LIFT_TABLE.get(req.activity_type, DEFAULT_LIFT)
        lift_factor = params["lift_factor"]
        margin_rate = params["margin_rate"]
        ci_width = params["ci_width"]

        daily_with_lift: list[ActivityROIPredictionPoint] = []
        total_lift_fen = 0
        for pt in baseline_points:
            lift = int(round(pt.baseline_gmv_fen * (lift_factor - 1.0)))
            total = max(0, pt.baseline_gmv_fen + lift)
            total_lift_fen += lift
            daily_with_lift.append(
                ActivityROIPredictionPoint(
                    date=pt.date,
                    baseline_gmv_fen=pt.baseline_gmv_fen,
                    expected_lift_gmv_fen=lift,
                    expected_total_gmv_fen=total,
                )
            )

        lift_margin_fen = int(round(total_lift_fen * margin_rate))
        roi_ratio = (lift_margin_fen / req.cost_budget_fen) if req.cost_budget_fen > 0 else 0.0

        # 80% CI：用 ci_width 作为相对宽度
        ci_low = max(0.0, roi_ratio * (1 - ci_width))
        ci_high = roi_ratio * (1 + ci_width)

        # 5) Sonnet 叙述
        merchant_profile = await self._merchant_repo.fetch_profile(req.tenant_id, req.store_id)
        narrative_zh, cache_ratio = await self._narrator.narrate(
            tenant_id=req.tenant_id,
            request_id=request_id,
            prediction={
                "activity_type": req.activity_type,
                "start_at": req.start_at.isoformat(),
                "end_at": req.end_at.isoformat(),
                "window_days": len(predict_dates),
                "cost_budget_fen": req.cost_budget_fen,
                "lift_gmv_fen": total_lift_fen,
                "lift_gross_margin_fen": lift_margin_fen,
                "roi_ratio": roi_ratio,
                "mape_estimate": mape,
                "confidence_interval": (round(ci_low, 3), round(ci_high, 3)),
            },
            merchant_profile=merchant_profile,
        )

        return ActivityROIResponse(
            request_id=request_id,
            predicted_total_lift_gmv_fen=total_lift_fen,
            predicted_lift_gross_margin_fen=lift_margin_fen,
            predicted_roi_ratio=round(roi_ratio, 4),
            confidence_interval=(round(ci_low, 4), round(ci_high, 4)),
            daily_predictions=daily_with_lift,
            narrative_zh=narrative_zh,
            mape_estimate=round(mape, 4),
            cache_hit_ratio=cache_ratio,
        )


def _date_range(start: date, end: date) -> list[date]:
    """[start, end] 闭区间，按日升序。"""
    if end < start:
        raise ValueError("end < start")
    days = (end - start).days + 1
    return [start + timedelta(days=i) for i in range(days)]


# ─── Pipeline 工厂（路由层使用） ─────────────────────────────────────────────


def build_default_pipeline(
    *,
    gmv_repository: HistoricalGmvRepository,
    model_router: ModelRouterLike,
    merchant_repository: MerchantProfileRepository | None = None,
) -> ActivityROIPipeline:
    """便捷构造函数。"""
    narrator = ActivityROINarrator(model_router=model_router)
    return ActivityROIPipeline(
        gmv_repository=gmv_repository,
        narrator=narrator,
        merchant_repository=merchant_repository,
    )
