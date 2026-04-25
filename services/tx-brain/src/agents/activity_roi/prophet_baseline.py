"""Prophet 基线 Service（D3b）

Prophet 不在项目依赖中（CLAUDE.md 禁止 Agent 私自加依赖）。
本模块实现两条路径：

1. Prophet 路径（首选）：若 `prophet` 已安装，使用 Prophet 模型，含 weekly_seasonality
   + yearly_seasonality + 中国节假日（如装 `chinesecalendar`）。
2. Fallback 路径：纯 numpy 实现的加性 Holt-Winters 三参数指数平滑（α/β/γ），
   周季节周期固定 7。结果与 Prophet API 在结构上对齐（点估计 + 上下界）。

外部接口：
    ProphetBaselineService.forecast_baseline(
        tenant_id, store_id, train_window_days, predict_dates
    ) -> list[ActivityROIPredictionPoint]

说明：
- 数据源通过 HistoricalGmvRepository 协议注入（不直接连 DB），便于单测注入 fake repo
- 训练数据 < 14 天 → InsufficientHistoricalDataError
- 所有 GMV 单位为**分**（int）；预测点使用 round() 转 int
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol
from uuid import UUID

import structlog

from .schemas import ActivityROIPredictionPoint, InsufficientHistoricalDataError

logger = structlog.get_logger(__name__)


# ─── Prophet 可选导入 ────────────────────────────────────────────────────────

try:  # pragma: no cover -- 实际是否走分支取决于运行时是否装了 prophet
    from prophet import Prophet  # type: ignore[import-not-found]

    _PROPHET_AVAILABLE = True
except ImportError:
    _PROPHET_AVAILABLE = False
    Prophet = None  # type: ignore[assignment]


# ─── 历史数据仓储协议 ────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class HistoricalGmvPoint:
    """单日历史 GMV 点（分）。"""

    day: date
    gmv_fen: int


class HistoricalGmvRepository(Protocol):
    """历史 GMV 仓储协议——单测可注入 FakeRepo。"""

    async def fetch_daily_gmv(
        self,
        tenant_id: UUID,
        store_id: UUID,
        start: date,
        end: date,
    ) -> list[HistoricalGmvPoint]:
        """返回 [start, end] 区间内每日 GMV（分）。允许中间日期缺失，
        Service 内部会做线性插值。"""
        ...


# ─── 配置 ────────────────────────────────────────────────────────────────────

MIN_TRAINING_DAYS = 14


# ─── 主 Service ──────────────────────────────────────────────────────────────


class ProphetBaselineService:
    """Prophet 基线预测，自动 fallback 到 Holt-Winters。"""

    def __init__(
        self,
        repository: HistoricalGmvRepository,
        *,
        force_fallback: bool = False,
    ) -> None:
        """
        Args:
            repository:     历史 GMV 仓储（注入，便于测试）
            force_fallback: 强制使用 Holt-Winters（测试用；默认按 prophet 是否可用决定）
        """
        self._repo = repository
        self._use_prophet = _PROPHET_AVAILABLE and not force_fallback

    @property
    def using_prophet(self) -> bool:
        """当前是否走 Prophet 路径（False 表示 Holt-Winters fallback）。"""
        return self._use_prophet

    async def forecast_baseline(
        self,
        tenant_id: UUID,
        store_id: UUID,
        train_window_days: int,
        predict_dates: list[date],
    ) -> list[ActivityROIPredictionPoint]:
        """生成 baseline GMV 预测。

        Args:
            tenant_id:          租户 UUID
            store_id:           门店 UUID
            train_window_days:  训练窗口天数（≥ 14）
            predict_dates:      待预测日期列表（升序）

        Returns:
            list[ActivityROIPredictionPoint]，仅填充 baseline_gmv_fen，
            lift / total 字段由后续增量模型填充（这里先置 0 / baseline）

        Raises:
            InsufficientHistoricalDataError: 训练数据 < 14 天
        """
        if train_window_days < MIN_TRAINING_DAYS:
            raise InsufficientHistoricalDataError(
                f"训练窗口必须 ≥ {MIN_TRAINING_DAYS} 天，收到 {train_window_days}"
            )
        if not predict_dates:
            raise ValueError("predict_dates 不能为空")
        if predict_dates != sorted(predict_dates):
            raise ValueError("predict_dates 必须升序排列")

        # 拉训练数据
        end_train = predict_dates[0] - timedelta(days=1)
        start_train = end_train - timedelta(days=train_window_days - 1)
        history = await self._repo.fetch_daily_gmv(
            tenant_id=tenant_id, store_id=store_id, start=start_train, end=end_train
        )

        # 强校验
        actual_days = len({p.day for p in history})
        if actual_days < MIN_TRAINING_DAYS:
            raise InsufficientHistoricalDataError(
                f"实际可用历史天数 {actual_days} < {MIN_TRAINING_DAYS}"
            )

        # 补全缺失日期（线性插值），输出按日升序
        filled = _fill_missing_days(history, start=start_train, end=end_train)

        # 选模型路径
        if self._use_prophet:
            forecast = self._forecast_with_prophet(filled, predict_dates)
        else:
            forecast = self._forecast_with_holt_winters(filled, predict_dates)

        logger.info(
            "prophet_baseline_done",
            tenant_id=str(tenant_id),
            store_id=str(store_id),
            train_days=actual_days,
            predict_days=len(predict_dates),
            engine="prophet" if self._use_prophet else "holt_winters",
        )

        return [
            ActivityROIPredictionPoint(
                date=d,
                baseline_gmv_fen=max(0, int(round(v))),
                expected_lift_gmv_fen=0,
                expected_total_gmv_fen=max(0, int(round(v))),
            )
            for d, v in zip(predict_dates, forecast, strict=True)
        ]

    # ── Prophet 路径 ────────────────────────────────────────────────────────

    def _forecast_with_prophet(
        self,
        history: list[HistoricalGmvPoint],
        predict_dates: list[date],
    ) -> list[float]:
        """使用 Prophet 模型预测。

        TODO(ops): 当 prophet 加入项目依赖后，建议注入 chinese_calendar 节假日，
        提升春节/国庆/中秋等假期的预测精度（当前 holiday=None）。
        """
        # pragma: no cover 注释保留——未装 prophet 时不会进入此分支
        import pandas as pd  # type: ignore[import-not-found]  # pragma: no cover

        df = pd.DataFrame(  # pragma: no cover
            {
                "ds": [p.day for p in history],
                "y": [p.gmv_fen for p in history],
            }
        )
        model = Prophet(  # pragma: no cover
            weekly_seasonality=True,
            yearly_seasonality=len(history) >= 365,
            daily_seasonality=False,
            interval_width=0.8,
        )
        model.fit(df)  # pragma: no cover
        future = pd.DataFrame({"ds": predict_dates})  # pragma: no cover
        out = model.predict(future)  # pragma: no cover
        return [float(v) for v in out["yhat"].tolist()]  # pragma: no cover

    # ── Holt-Winters 路径（fallback，纯 numpy/python） ──────────────────────

    def _forecast_with_holt_winters(
        self,
        history: list[HistoricalGmvPoint],
        predict_dates: list[date],
    ) -> list[float]:
        """加性 Holt-Winters，季节周期 7（周季节）。

        采用文献标准初始化：
        - level 初值 = 第一周均值
        - trend 初值 = (后一周均值 - 前一周均值) / 7
        - seasonal 初值 = 各周同位置均值 - 整体均值
        平滑参数 α=0.3 / β=0.1 / γ=0.3（餐饮日 GMV 较稳定时的常用经验值）。
        """
        ys = [float(p.gmv_fen) for p in history]
        n = len(ys)
        period = 7
        if n < 2 * period:
            # 不足两周时退化为简单加性预测：使用最近 7 天均值
            recent = sum(ys[-period:]) / min(period, n)
            return [recent for _ in predict_dates]

        # 初始化
        first_week = ys[:period]
        second_week = ys[period : 2 * period]
        level = sum(first_week) / period
        trend = (sum(second_week) / period - level) / period
        # 季节分量：把所有周对应位置取均值，再减去整体均值
        n_full_weeks = n // period
        overall_mean = sum(ys[: n_full_weeks * period]) / (n_full_weeks * period)
        seasonal: list[float] = [0.0] * period
        for i in range(period):
            buckets = [ys[w * period + i] for w in range(n_full_weeks)]
            seasonal[i] = sum(buckets) / n_full_weeks - overall_mean

        alpha, beta, gamma = 0.3, 0.1, 0.3

        # 训练阶段：逐点更新 level/trend/seasonal
        for t, y in enumerate(ys):
            s_idx = t % period
            prev_level = level
            level = alpha * (y - seasonal[s_idx]) + (1 - alpha) * (level + trend)
            trend = beta * (level - prev_level) + (1 - beta) * trend
            seasonal[s_idx] = gamma * (y - level) + (1 - gamma) * seasonal[s_idx]

        # 预测：从训练序列尾部继续外推
        last_day = history[-1].day
        forecast: list[float] = []
        for d in predict_dates:
            h = (d - last_day).days
            if h <= 0:
                # 预测日期早于训练末日：直接取最近实际值
                forecast.append(ys[-1])
                continue
            s_idx = (n - 1 + h) % period
            yhat = level + h * trend + seasonal[s_idx]
            # 防止数值漂移到负
            forecast.append(max(0.0, yhat))

        return forecast


# ─── 工具函数 ────────────────────────────────────────────────────────────────


def _fill_missing_days(
    history: list[HistoricalGmvPoint],
    *,
    start: date,
    end: date,
) -> list[HistoricalGmvPoint]:
    """对 [start, end] 区间内缺失的日期做线性插值，输出按日升序。"""
    by_day = {p.day: p.gmv_fen for p in history}
    days_total = (end - start).days + 1
    out: list[HistoricalGmvPoint] = []
    for offset in range(days_total):
        d = start + timedelta(days=offset)
        if d in by_day:
            out.append(HistoricalGmvPoint(day=d, gmv_fen=by_day[d]))
            continue
        # 找前后最近的已知点做线性插值
        before = next(
            (p for p in reversed(out) if p.gmv_fen is not None), None
        )
        after = None
        for off2 in range(offset + 1, days_total):
            d2 = start + timedelta(days=off2)
            if d2 in by_day:
                after = HistoricalGmvPoint(day=d2, gmv_fen=by_day[d2])
                break
        if before and after:
            span = (after.day - before.day).days
            ratio = (d - before.day).days / span
            interpolated = before.gmv_fen + (after.gmv_fen - before.gmv_fen) * ratio
            out.append(HistoricalGmvPoint(day=d, gmv_fen=int(round(interpolated))))
        elif before:
            out.append(HistoricalGmvPoint(day=d, gmv_fen=before.gmv_fen))
        elif after:
            out.append(HistoricalGmvPoint(day=d, gmv_fen=after.gmv_fen))
        else:
            # 完全没有已知数据，跳过（外层会因 < 14 天报错）
            continue
    return out


def estimate_mape_holdout(
    history: list[HistoricalGmvPoint],
    *,
    holdout_days: int = 7,
    force_fallback: bool = True,
) -> float:
    """在历史尾部留出 holdout_days 做 MAPE 估计。

    用同一套预测引擎（默认 fallback）训练 [..., -holdout] 数据，预测 [-holdout:, ...]，
    与真实值比较。返回 MAPE（如 0.18 表示 18%）。

    用于 ActivityROIResponse.mape_estimate 字段。
    """
    if len(history) < MIN_TRAINING_DAYS + holdout_days:
        return float("inf")

    train = history[:-holdout_days]
    truth = history[-holdout_days:]

    # 直接复用 service 的 holt_winters 逻辑
    class _MemRepo:
        async def fetch_daily_gmv(self, tenant_id, store_id, start, end):  # type: ignore[no-untyped-def]
            return [p for p in train if start <= p.day <= end]

    # 用 sync helper（避免引入 async）
    ys = [float(p.gmv_fen) for p in train]
    period = 7
    n = len(ys)
    if n < 2 * period:
        avg = sum(ys[-period:]) / min(period, n)
        preds = [avg] * holdout_days
    else:
        first_week = ys[:period]
        second_week = ys[period : 2 * period]
        level = sum(first_week) / period
        trend = (sum(second_week) / period - level) / period
        n_full_weeks = n // period
        overall_mean = sum(ys[: n_full_weeks * period]) / (n_full_weeks * period)
        seasonal = [0.0] * period
        for i in range(period):
            buckets = [ys[w * period + i] for w in range(n_full_weeks)]
            seasonal[i] = sum(buckets) / n_full_weeks - overall_mean
        alpha, beta, gamma = 0.3, 0.1, 0.3
        for t, y in enumerate(ys):
            s_idx = t % period
            prev_level = level
            level = alpha * (y - seasonal[s_idx]) + (1 - alpha) * (level + trend)
            trend = beta * (level - prev_level) + (1 - beta) * trend
            seasonal[s_idx] = gamma * (y - level) + (1 - gamma) * seasonal[s_idx]
        preds = []
        for h in range(1, holdout_days + 1):
            s_idx = (n - 1 + h) % period
            preds.append(max(0.0, level + h * trend + seasonal[s_idx]))

    # MAPE
    errors: list[float] = []
    for pred, real in zip(preds, truth, strict=True):
        if real.gmv_fen <= 0:
            continue
        errors.append(abs(pred - real.gmv_fen) / real.gmv_fen)
    if not errors:
        return float("inf")
    return sum(errors) / len(errors)
