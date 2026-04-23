"""CampaignROIForecastService —— Sprint D3b 营销活动 ROI 预测（Prophet + Sonnet）

职责
----
1. **Prophet 基线预测**：基于历史营收时序，预测活动期"无活动状态下的营收"
   （counterfactual baseline），uplift = 实际观测 - 预测基线
2. **Sonnet 分析解读**：将 Prophet 数值 + 活动属性（类型/折扣/渠道）喂给 Sonnet，
   生成自然语言分析和下一步建议
3. **MAPE 监控**：complete 阶段自动计算 MAPE，> 20% 标记 needs_calibration
4. **优雅降级**：Prophet 未安装时走 moving average + linear，确保不阻塞

预期效果
-------
设计稿目标：MAPE < 20%。按 campaign_id 聚合，MAPE > 20% 的活动被标记
`needs_calibration=true`，下轮训练时自动剔除脏数据源。

设计权衡
-------
- Prophet 作 **optional dependency**：requirements 不强依赖，import 失败自动
  fallback 到手写 moving_average（7/30 天）+ linear trend
- Sonnet 任务类型 `campaign_roi_forecast`（MODERATE 复杂度）: Prophet 给数值，
  Sonnet 给"为什么"和"下一步怎么办"，符合分工
- 不自己实现 Prophet 算法（太重）：只做薄封装 + fallback
- 训练窗口 90 天起步，短期门店用 moving_average (MAPE 高的接受)
"""
from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)

# MAPE 阈值：超此阈值触发 needs_calibration
MAPE_THRESHOLD = 0.20
MIN_TRAINING_POINTS = 30  # Prophet 至少 30 天才靠谱；少于此走 moving_average
DEFAULT_MOVING_WINDOW_DAYS = 7


@dataclass
class TimeSeriesPoint:
    """一个时间序列点"""
    day: date
    revenue_fen: int


@dataclass
class ForecastResult:
    """单次预测的结构化结果"""
    model: str                        # prophet / moving_average / linear
    model_version: Optional[str] = None
    baseline_fen_by_day: dict = field(default_factory=dict)
    baseline_total_fen: int = 0
    confidence: float = 0.0           # 0-1
    training_data_snapshot: dict = field(default_factory=dict)


@dataclass
class BacktestResult:
    """基于实际数据的回测结果（用于算 MAPE）"""
    true_revenue_fen: int
    true_baseline_fen: int            # 从无活动期反推
    true_uplift_fen: int
    mape: float                       # 0-1，>1 表示偏离巨大
    needs_calibration: bool


def mean_absolute_percentage_error(
    actual: list[float], predicted: list[float]
) -> float:
    """MAPE = 平均(|actual - predicted| / |actual|)，actual=0 跳过"""
    if not actual or len(actual) != len(predicted):
        return 1.0   # 数据缺失 → 默认 100% 偏差（触发 calibration）
    pairs = [(a, p) for a, p in zip(actual, predicted) if a != 0]
    if not pairs:
        return 1.0
    return sum(abs(a - p) / abs(a) for a, p in pairs) / len(pairs)


def moving_average_forecast(
    history: list[TimeSeriesPoint],
    forecast_days: int,
    window: int = DEFAULT_MOVING_WINDOW_DAYS,
) -> tuple[dict[date, int], float]:
    """滑动窗口均值 forecast —— Prophet 不可用时的降级。

    Returns:
        (day → predicted_fen, confidence 0-1)
    """
    if not history:
        return {}, 0.0
    sorted_hist = sorted(history, key=lambda p: p.day)
    last_day = sorted_hist[-1].day
    window_data = [p.revenue_fen for p in sorted_hist[-window:]]
    avg = sum(window_data) / max(1, len(window_data))
    # 置信度：窗口内 CV（变异系数）越小越高
    if len(window_data) < 2:
        conf = 0.3
    else:
        mean = avg
        variance = sum((x - mean) ** 2 for x in window_data) / len(window_data)
        std = math.sqrt(variance)
        cv = std / mean if mean > 0 else 1.0
        conf = max(0.2, min(0.85, 1.0 - cv))
    result = {
        last_day + timedelta(days=i + 1): int(avg)
        for i in range(forecast_days)
    }
    return result, round(conf, 3)


def linear_trend_forecast(
    history: list[TimeSeriesPoint],
    forecast_days: int,
) -> tuple[dict[date, int], float]:
    """最小二乘线性拟合 —— 适合短期、弱季节性数据"""
    if len(history) < 2:
        return {}, 0.0
    sorted_hist = sorted(history, key=lambda p: p.day)
    xs = list(range(len(sorted_hist)))
    ys = [p.revenue_fen for p in sorted_hist]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    den = sum((xs[i] - mean_x) ** 2 for i in range(n))
    slope = num / den if den != 0 else 0.0
    intercept = mean_y - slope * mean_x

    # R² 作 confidence
    ss_total = sum((y - mean_y) ** 2 for y in ys)
    ss_residual = sum(
        (ys[i] - (slope * xs[i] + intercept)) ** 2 for i in range(n)
    )
    r2 = 1 - ss_residual / ss_total if ss_total > 0 else 0.0
    conf = max(0.2, min(0.85, r2))

    last_day = sorted_hist[-1].day
    result = {}
    for i in range(forecast_days):
        x_pred = n + i
        result[last_day + timedelta(days=i + 1)] = int(max(0, slope * x_pred + intercept))
    return result, round(conf, 3)


def try_prophet_forecast(
    history: list[TimeSeriesPoint],
    forecast_days: int,
) -> Optional[tuple[dict[date, int], float]]:
    """尝试调 Prophet。失败/未安装返回 None。"""
    try:
        from prophet import Prophet  # type: ignore
    except ImportError:
        logger.info("prophet_not_installed_falling_back")
        return None

    if len(history) < MIN_TRAINING_POINTS:
        return None

    try:
        # 构造 Prophet 输入
        rows = [{"ds": p.day.isoformat(), "y": p.revenue_fen}
                for p in sorted(history, key=lambda p: p.day)]
        # 延迟导入 pandas，避免模块级依赖
        import pandas as pd  # type: ignore
        df = pd.DataFrame(rows)

        m = Prophet(daily_seasonality=False, weekly_seasonality=True, yearly_seasonality=False)
        m.fit(df)
        future = m.make_future_dataframe(periods=forecast_days)
        forecast = m.predict(future)

        last_day = sorted(history, key=lambda p: p.day)[-1].day
        result = {}
        forecast_slice = forecast.tail(forecast_days)
        for _, row in forecast_slice.iterrows():
            ds = pd.to_datetime(row["ds"]).date()
            yhat = max(0, int(row["yhat"]))
            result[ds] = yhat
            _ = last_day  # reserved

        # Prophet 置信度：用 yhat_upper - yhat_lower 相对窄度当 proxy
        band_narrow = sum(
            1 - min(1, abs(r["yhat_upper"] - r["yhat_lower"]) / max(1, abs(r["yhat"])))
            for _, r in forecast_slice.iterrows()
        ) / max(1, len(forecast_slice))
        conf = max(0.5, min(0.95, band_narrow))
        return result, round(conf, 3)
    except Exception as exc:  # noqa: BLE001 — 外部库异常兜底
        logger.warning("prophet_forecast_failed error=%s", exc)
        return None


class CampaignROIForecastService:
    """D3b 活动 ROI 预测服务。

    依赖注入：
      sonnet_invoker: async (prompt:str, model_id:str) -> str，可为 None（降级模板）
    """

    def __init__(self, sonnet_invoker: Optional[Any] = None) -> None:
        self.sonnet_invoker = sonnet_invoker

    async def forecast_baseline(
        self,
        history: list[TimeSeriesPoint],
        forecast_start: date,
        forecast_end: date,
    ) -> ForecastResult:
        """预测无活动期的营收基线。

        依次尝试：prophet → linear → moving_average。
        """
        days = (forecast_end - forecast_start).days + 1
        if days <= 0:
            return ForecastResult(model="error")

        # 1. Prophet
        prophet_result = try_prophet_forecast(history, days)
        if prophet_result is not None:
            by_day, conf = prophet_result
            return ForecastResult(
                model="prophet",
                baseline_fen_by_day={d.isoformat(): v for d, v in by_day.items()},
                baseline_total_fen=sum(by_day.values()),
                confidence=conf,
                training_data_snapshot=self._training_snapshot(history),
            )

        # 2. Linear trend（至少 2 个点）
        if len(history) >= 2 and len(history) < MIN_TRAINING_POINTS:
            by_day, conf = linear_trend_forecast(history, days)
            if by_day:
                return ForecastResult(
                    model="linear",
                    baseline_fen_by_day={d.isoformat(): v for d, v in by_day.items()},
                    baseline_total_fen=sum(by_day.values()),
                    confidence=conf,
                    training_data_snapshot=self._training_snapshot(history),
                )

        # 3. Moving average（最后兜底）
        by_day, conf = moving_average_forecast(history, days)
        return ForecastResult(
            model="moving_average",
            baseline_fen_by_day={d.isoformat(): v for d, v in by_day.items()},
            baseline_total_fen=sum(by_day.values()),
            confidence=conf,
            training_data_snapshot=self._training_snapshot(history),
        )

    def backtest(
        self,
        baseline_by_day: dict[date, int],
        actual_by_day: dict[date, int],
    ) -> BacktestResult:
        """基于实际观测回算 MAPE 和真实 uplift。

        Args:
            baseline_by_day:  forecast_baseline 的输出（日 → 分）
            actual_by_day:    活动期实际观测（日 → 分）
        """
        days = sorted(set(baseline_by_day.keys()) | set(actual_by_day.keys()))
        baseline_list = [baseline_by_day.get(d, 0) for d in days]
        actual_list = [actual_by_day.get(d, 0) for d in days]

        mape = mean_absolute_percentage_error(
            actual=[float(x) for x in actual_list],
            predicted=[float(x) for x in baseline_list],
        )
        true_revenue = sum(actual_list)
        true_baseline = sum(baseline_list)
        return BacktestResult(
            true_revenue_fen=true_revenue,
            true_baseline_fen=true_baseline,
            true_uplift_fen=true_revenue - true_baseline,
            mape=round(mape, 4),
            needs_calibration=mape > MAPE_THRESHOLD,
        )

    async def analyze_with_sonnet(
        self,
        *,
        campaign_name: str,
        campaign_type: str,
        forecast: ForecastResult,
        backtest: Optional[BacktestResult] = None,
    ) -> tuple[str, list[dict]]:
        """调 Sonnet 生成文本分析 + 推荐行动。

        Returns:
            (analysis_text, recommended_actions: list[dict])
        """
        prompt = self._build_analysis_prompt(
            campaign_name=campaign_name,
            campaign_type=campaign_type,
            forecast=forecast,
            backtest=backtest,
        )

        if self.sonnet_invoker is None:
            return self._fallback_analysis(
                campaign_name=campaign_name, forecast=forecast, backtest=backtest
            )

        try:
            response = await self.sonnet_invoker(prompt, "claude-sonnet-4-6")
            return self._parse_sonnet_response(response, backtest=backtest)
        except Exception as exc:  # noqa: BLE001
            logger.warning("sonnet_analysis_failed error=%s", exc)
            return self._fallback_analysis(
                campaign_name=campaign_name, forecast=forecast, backtest=backtest
            )

    # ─── 私有辅助 ────────────────────────────────────────────────

    @staticmethod
    def _training_snapshot(history: list[TimeSeriesPoint]) -> dict:
        if not history:
            return {"data_points": 0}
        sorted_hist = sorted(history, key=lambda p: p.day)
        return {
            "data_points": len(sorted_hist),
            "training_start": sorted_hist[0].day.isoformat(),
            "training_end": sorted_hist[-1].day.isoformat(),
            "training_window_days": (sorted_hist[-1].day - sorted_hist[0].day).days + 1,
        }

    @staticmethod
    def _build_analysis_prompt(
        *,
        campaign_name: str,
        campaign_type: str,
        forecast: ForecastResult,
        backtest: Optional[BacktestResult],
    ) -> str:
        parts = [
            "你是餐饮营销数据分析师。基于以下活动 ROI 数据给出中文分析和建议。",
            f"- 活动：{campaign_name} ({campaign_type})",
            f"- 预测模型：{forecast.model}，置信度 {forecast.confidence:.2f}",
            f"- 基线营收（分）：{forecast.baseline_total_fen}",
        ]
        if backtest:
            parts += [
                f"- 实际营收（分）：{backtest.true_revenue_fen}",
                f"- 真实增量（分）：{backtest.true_uplift_fen}",
                f"- MAPE：{backtest.mape:.2%}",
                f"- 需校准：{'是' if backtest.needs_calibration else '否'}",
            ]
        parts.append(
            "请输出：1) 一句话判定活动效果 "
            "2) 2-3 条具体改进建议（格式：action|expected_lift_fen|priority(high/med/low)）"
        )
        return "\n".join(parts)

    @staticmethod
    def _parse_sonnet_response(
        response: str, backtest: Optional[BacktestResult]
    ) -> tuple[str, list[dict]]:
        """解析 Sonnet 返回。格式约定：首段文本 + 1-3 行 action|lift|priority"""
        actions: list[dict] = []
        analysis_lines: list[str] = []
        for line in response.strip().split("\n"):
            parts = line.strip().split("|")
            if len(parts) >= 3:
                try:
                    actions.append({
                        "action": parts[0].strip(),
                        "expected_lift_fen": int(parts[1].strip()),
                        "priority": parts[2].strip().lower(),
                    })
                    continue
                except ValueError:
                    pass
            analysis_lines.append(line)
        analysis_text = "\n".join(analysis_lines).strip() or response.strip()
        return analysis_text, actions

    @staticmethod
    def _fallback_analysis(
        *,
        campaign_name: str,
        forecast: ForecastResult,
        backtest: Optional[BacktestResult],
    ) -> tuple[str, list[dict]]:
        """Sonnet 不可用时的降级分析（基于数值阈值）"""
        if backtest is None:
            return (
                f"活动 {campaign_name} 规划基线 ¥{forecast.baseline_total_fen / 100:.0f}，"
                f"使用 {forecast.model} 模型（置信度 {forecast.confidence:.0%}）。"
                f" 建议活动结束后回填 actual 数据以启动 MAPE 校准。",
                [],
            )

        mape = backtest.mape
        uplift = backtest.true_uplift_fen

        if mape > MAPE_THRESHOLD:
            text = (
                f"活动 {campaign_name} MAPE={mape:.2%} 超 {MAPE_THRESHOLD:.0%} 阈值，"
                f"预测偏离较大，已标记 needs_calibration。"
                f"真实增量 ¥{uplift / 100:.0f}。"
            )
            actions = [
                {"action": "剔除本活动样本于下轮训练", "expected_lift_fen": 0, "priority": "high"},
                {"action": "检查同期门店/促销叠加效应", "expected_lift_fen": 0, "priority": "med"},
            ]
        elif uplift > 0:
            text = (
                f"活动 {campaign_name} 成功增加营收 ¥{uplift / 100:.0f}，"
                f"MAPE={mape:.2%} 在阈值内，预测可信。建议沉淀活动模板用于同类场景复用。"
            )
            actions = [
                {"action": "记录活动模板入 playbook", "expected_lift_fen": uplift, "priority": "high"},
            ]
        else:
            text = (
                f"活动 {campaign_name} 未产生正增量（真实增量 ¥{uplift / 100:.0f}），"
                f"MAPE={mape:.2%}。建议复盘活动设计/渠道分发/受众定位。"
            )
            actions = [
                {"action": "活动复盘会讨论 ROI 负值原因", "expected_lift_fen": 0, "priority": "high"},
                {"action": "检查是否与其他活动互相消解", "expected_lift_fen": 0, "priority": "med"},
            ]
        return text, actions


# ──────────────────────────────────────────────────────────────────────
# DB 持久化辅助
# ──────────────────────────────────────────────────────────────────────

async def save_forecast_to_db(
    db: Any,
    *,
    tenant_id: str,
    store_id: Optional[str],
    campaign_id: Optional[str],
    campaign_name: str,
    campaign_type: str,
    forecast_start: date,
    forecast_end: date,
    forecast: ForecastResult,
    uplift_forecast_fen: int = 0,
    sonnet_analysis: Optional[str] = None,
    recommended_actions: Optional[list[dict]] = None,
) -> str:
    """写入 campaign_roi_forecasts 表（status='plan'）"""
    import json

    from sqlalchemy import text

    record_id = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO campaign_roi_forecasts (
            id, tenant_id, store_id, campaign_id,
            campaign_name, campaign_type,
            forecast_start, forecast_end,
            forecast_model, model_version,
            baseline_forecast_fen, uplift_forecast_fen, forecast_confidence,
            sonnet_analysis,
            recommended_actions,
            training_data_snapshot,
            status
        ) VALUES (
            CAST(:id AS uuid),
            CAST(:tenant_id AS uuid),
            CAST(:store_id AS uuid),
            CAST(:campaign_id AS uuid),
            :campaign_name, :campaign_type,
            :forecast_start, :forecast_end,
            :forecast_model, :model_version,
            :baseline_forecast_fen, :uplift_forecast_fen, :forecast_confidence,
            :sonnet_analysis,
            CAST(:recommended_actions AS jsonb),
            CAST(:training_snapshot AS jsonb),
            'plan'
        )
    """), {
        "id": record_id,
        "tenant_id": tenant_id,
        "store_id": store_id,
        "campaign_id": campaign_id,
        "campaign_name": campaign_name,
        "campaign_type": campaign_type,
        "forecast_start": forecast_start,
        "forecast_end": forecast_end,
        "forecast_model": forecast.model,
        "model_version": forecast.model_version,
        "baseline_forecast_fen": forecast.baseline_total_fen,
        "uplift_forecast_fen": uplift_forecast_fen,
        "forecast_confidence": forecast.confidence,
        "sonnet_analysis": sonnet_analysis,
        "recommended_actions": json.dumps(recommended_actions or [], ensure_ascii=False),
        "training_snapshot": json.dumps(forecast.training_data_snapshot, ensure_ascii=False),
    })
    await db.commit()
    logger.info(
        "campaign_roi_forecast_saved id=%s model=%s baseline_fen=%s",
        record_id, forecast.model, forecast.baseline_total_fen,
    )
    return record_id


async def complete_forecast_with_backtest(
    db: Any,
    *,
    tenant_id: str,
    forecast_id: str,
    backtest: BacktestResult,
    sonnet_analysis: Optional[str] = None,
    recommended_actions: Optional[list[dict]] = None,
) -> bool:
    """活动结束后回填 actual + MAPE，切换到 completed 状态"""
    import json

    from sqlalchemy import text

    result = await db.execute(text("""
        UPDATE campaign_roi_forecasts
        SET status = 'completed',
            actual_revenue_fen = :actual_revenue_fen,
            actual_baseline_fen = :actual_baseline_fen,
            true_uplift_fen = :true_uplift_fen,
            mape = :mape,
            needs_calibration = :needs_calibration,
            sonnet_analysis = COALESCE(:sonnet_analysis, sonnet_analysis),
            recommended_actions = COALESCE(CAST(:recommended_actions AS jsonb), recommended_actions),
            updated_at = NOW()
        WHERE id = CAST(:id AS uuid)
          AND tenant_id = CAST(:tenant_id AS uuid)
          AND status IN ('plan', 'running')
          AND is_deleted = false
        RETURNING id
    """), {
        "id": forecast_id,
        "tenant_id": tenant_id,
        "actual_revenue_fen": backtest.true_revenue_fen,
        "actual_baseline_fen": backtest.true_baseline_fen,
        "true_uplift_fen": backtest.true_uplift_fen,
        "mape": backtest.mape,
        "needs_calibration": backtest.needs_calibration,
        "sonnet_analysis": sonnet_analysis,
        "recommended_actions": json.dumps(recommended_actions, ensure_ascii=False) if recommended_actions else None,
    })
    row = result.first()
    await db.commit()
    return row is not None


__all__ = [
    "TimeSeriesPoint",
    "ForecastResult",
    "BacktestResult",
    "CampaignROIForecastService",
    "mean_absolute_percentage_error",
    "moving_average_forecast",
    "linear_trend_forecast",
    "try_prophet_forecast",
    "save_forecast_to_db",
    "complete_forecast_with_backtest",
    "MAPE_THRESHOLD",
    "MIN_TRAINING_POINTS",
]
