"""活动 ROI 预测（D3b）单元测试

覆盖：
  1. Prophet baseline forecast on synthetic data
  2. Insufficient history → InsufficientHistoricalDataError
  3. Sonnet narrator returns Chinese text + caveats（mock ModelRouter）
  4. Sonnet narrator falls back to template on error
  5. Pipeline full predict（mocks 全链路）
  6. MAPE estimation 用尾部回测
  7. HTTP route 鉴权（缺失 JWT/X-Tenant-ID 拒绝）
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from ..agents.activity_roi.pipeline import (
    ACTIVITY_LIFT_TABLE,
    ActivityROIPipeline,
)
from ..agents.activity_roi.prophet_baseline import (
    HistoricalGmvPoint,
    ProphetBaselineService,
    estimate_mape_holdout,
)
from ..agents.activity_roi.schemas import (
    ActivityROIRequest,
    InsufficientHistoricalDataError,
)
from ..agents.activity_roi.sonnet_narrator import ActivityROINarrator
from ..api.activity_roi_routes import _get_pipeline, _require_bearer, _require_tenant
from ..main import app

TENANT_ID = uuid.UUID("a0000000-0000-0000-0000-000000000001")
STORE_ID = uuid.UUID("b0000000-0000-0000-0000-000000000001")


# ─── Fakes ───────────────────────────────────────────────────────────────────


class FakeGmvRepo:
    """生成稳定季节性 GMV 序列。"""

    def __init__(self, *, base_fen: int = 50_000_00, weekend_boost: float = 1.4) -> None:
        self.base_fen = base_fen
        self.weekend_boost = weekend_boost
        self.calls: list[tuple] = []

    async def fetch_daily_gmv(self, tenant_id, store_id, start: date, end: date):
        self.calls.append((tenant_id, store_id, start, end))
        out: list[HistoricalGmvPoint] = []
        d = start
        while d <= end:
            # 周末 1.4x，周内 1.0x，加少量正弦扰动
            wd = d.weekday()
            mult = self.weekend_boost if wd >= 5 else 1.0
            jitter = 1.0 + 0.05 * math.sin(d.toordinal() / 3.0)
            gmv = int(self.base_fen * mult * jitter)
            out.append(HistoricalGmvPoint(day=d, gmv_fen=gmv))
            d += timedelta(days=1)
        return out


class _ShortGmvRepo:
    """只返回 7 天，触发 InsufficientHistoricalDataError。"""

    async def fetch_daily_gmv(self, tenant_id, store_id, start: date, end: date):
        out: list[HistoricalGmvPoint] = []
        d = start
        for _ in range(7):  # 只生成 7 天
            if d > end:
                break
            out.append(HistoricalGmvPoint(day=d, gmv_fen=10_000_00))
            d += timedelta(days=1)
        return out


class FakeMerchantRepo:
    async def fetch_profile(self, tenant_id, store_id):
        return {
            "brand": "徐记海鲜",
            "city": "长沙",
            "cuisine": "湘式海鲜",
            "avg_check_yuan": 168,
        }


class FakeModelRouter:
    """模拟 ModelRouterCompat / MultiProviderRouter，返回可控 JSON。"""

    def __init__(self, response_text: str | None = None, raise_exc: Exception | None = None):
        self.response_text = response_text or json.dumps(
            {
                "narrative": "建议谨慎启动本次满减活动。预算约 2000 元，预期增量 GMV 约 8000 元，"
                "相对客单未明显稀释。",
                "caveats": ["假动作风险：会员日老客本就消费", "毛利侵蚀：满减幅度需复核"],
            },
            ensure_ascii=False,
        )
        self.raise_exc = raise_exc
        self.calls: list[dict] = []

    async def complete(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        if self.raise_exc:
            raise self.raise_exc
        return self.response_text


# ─── 1) Prophet baseline forecasts with synthetic data ───────────────────────


@pytest.mark.asyncio
async def test_prophet_baseline_forecasts_with_synthetic_data():
    repo = FakeGmvRepo()
    svc = ProphetBaselineService(repo, force_fallback=True)

    today = date(2026, 4, 1)
    predict_dates = [today + timedelta(days=i) for i in range(7)]
    points = await svc.forecast_baseline(
        tenant_id=TENANT_ID,
        store_id=STORE_ID,
        train_window_days=30,
        predict_dates=predict_dates,
    )

    # 形状正确
    assert len(points) == 7
    assert [p.date for p in points] == predict_dates

    # baseline 都 > 0 且非疯狂数字
    assert all(p.baseline_gmv_fen > 0 for p in points)
    assert all(p.baseline_gmv_fen < 200_000_00 for p in points)

    # 周末（周六/周日）应高于周内（周一到周五），季节性被学到了
    weekday_avg = sum(
        p.baseline_gmv_fen for p in points if p.date.weekday() < 5
    ) / max(1, sum(1 for p in points if p.date.weekday() < 5))
    weekend_avg = sum(
        p.baseline_gmv_fen for p in points if p.date.weekday() >= 5
    ) / max(1, sum(1 for p in points if p.date.weekday() >= 5))
    assert weekend_avg > weekday_avg, "fallback Holt-Winters 必须学到周季节"


# ─── 2) Insufficient history rejected ────────────────────────────────────────


@pytest.mark.asyncio
async def test_prophet_baseline_rejects_insufficient_history():
    svc = ProphetBaselineService(_ShortGmvRepo(), force_fallback=True)
    with pytest.raises(InsufficientHistoricalDataError):
        await svc.forecast_baseline(
            tenant_id=TENANT_ID,
            store_id=STORE_ID,
            train_window_days=30,
            predict_dates=[date(2026, 4, 1)],
        )

    # train_window_days 小于 14 也直接 raise
    svc2 = ProphetBaselineService(FakeGmvRepo(), force_fallback=True)
    with pytest.raises(InsufficientHistoricalDataError):
        await svc2.forecast_baseline(
            tenant_id=TENANT_ID,
            store_id=STORE_ID,
            train_window_days=10,
            predict_dates=[date(2026, 4, 1)],
        )


# ─── 3) Sonnet narrator returns Chinese text with caveats ────────────────────


@pytest.mark.asyncio
async def test_sonnet_narrator_returns_chinese_text_with_caveats():
    router = FakeModelRouter()
    narrator = ActivityROINarrator(model_router=router)

    text, cache = await narrator.narrate(
        tenant_id=TENANT_ID,
        request_id=uuid.uuid4(),
        prediction={
            "activity_type": "full_reduction",
            "start_at": "2026-04-10",
            "end_at": "2026-04-12",
            "window_days": 3,
            "cost_budget_fen": 2_000_00,
            "lift_gmv_fen": 8_000_00,
            "lift_gross_margin_fen": 3_500_00,
            "roi_ratio": 1.75,
            "mape_estimate": 0.18,
            "confidence_interval": (1.5, 2.0),
        },
        merchant_profile={"brand": "徐记海鲜", "city": "长沙"},
    )

    assert "建议" in text or "启动" in text
    assert "风险提示" in text
    assert any("一" <= ch <= "鿿" for ch in text), "must contain Chinese"
    assert cache == 0.75, "提供了 merchant_profile 时应给出 cache 比例估计"
    # router 被调用一次，task_type 是 agent_decision
    assert len(router.calls) == 1
    assert router.calls[0]["task_type"] == "agent_decision"
    # 商户档案应进了 system 字段
    assert "徐记海鲜" in router.calls[0]["system"]


# ─── 4) Sonnet narrator falls back to template on error ──────────────────────


@pytest.mark.asyncio
async def test_sonnet_narrator_falls_back_to_template_on_error():
    router = FakeModelRouter(raise_exc=TimeoutError("model timeout"))
    narrator = ActivityROINarrator(model_router=router)

    text, cache = await narrator.narrate(
        tenant_id=TENANT_ID,
        request_id=uuid.uuid4(),
        prediction={
            "activity_type": "douyin_groupon",
            "cost_budget_fen": 5_000_00,
            "lift_gmv_fen": 20_000_00,
            "lift_gross_margin_fen": 6_000_00,
            "roi_ratio": 1.2,
        },
        merchant_profile={"brand": "测试品牌"},
    )

    # fallback 模板必须包含数字与风险提示
    assert "fallback" in text or "风险提示" in text
    assert "1.20" in text or "1.2" in text
    assert cache is None

    # 解析失败也走 fallback
    bad_router = FakeModelRouter(response_text="not a json at all")
    narrator2 = ActivityROINarrator(model_router=bad_router)
    text2, cache2 = await narrator2.narrate(
        tenant_id=TENANT_ID,
        request_id=uuid.uuid4(),
        prediction={
            "activity_type": "member_day",
            "cost_budget_fen": 100,
            "lift_gmv_fen": 500,
            "lift_gross_margin_fen": 200,
            "roi_ratio": 2.0,
        },
    )
    assert "风险提示" in text2
    assert cache2 is None


# ─── 5) Pipeline full predict with mocks ─────────────────────────────────────


@pytest.mark.asyncio
async def test_pipeline_full_predict_with_mocks():
    repo = FakeGmvRepo()
    router = FakeModelRouter()
    narrator = ActivityROINarrator(model_router=router)
    pipeline = ActivityROIPipeline(
        gmv_repository=repo,
        narrator=narrator,
        merchant_repository=FakeMerchantRepo(),
    )

    req = ActivityROIRequest(
        tenant_id=TENANT_ID,
        store_id=STORE_ID,
        activity_type="full_reduction",
        start_at=datetime(2026, 4, 10, tzinfo=timezone.utc),
        end_at=datetime(2026, 4, 12, tzinfo=timezone.utc),
        cost_budget_fen=2_000_00,
        target_audience_size=500,
        historical_baseline_days=30,
    )

    resp = await pipeline.predict(req)

    # daily_predictions 长度 = 3 天（含起止）
    assert len(resp.daily_predictions) == 3
    # 每日都有 baseline + lift + total，且 total = baseline + lift（裁剪到 ≥ 0）
    for pt in resp.daily_predictions:
        assert pt.baseline_gmv_fen >= 0
        assert pt.expected_total_gmv_fen == max(0, pt.baseline_gmv_fen + pt.expected_lift_gmv_fen)
    # ROI 比率与 lift_gross_margin / cost_budget 一致（小误差）
    expected_ratio = resp.predicted_lift_gross_margin_fen / req.cost_budget_fen
    assert abs(resp.predicted_roi_ratio - round(expected_ratio, 4)) < 1e-3
    # full_reduction 表里 lift_factor=1.18，所以 lift > 0
    assert resp.predicted_total_lift_gmv_fen > 0
    # MAPE 在 [0, 1]
    assert 0.0 <= resp.mape_estimate <= 1.0
    # 80% CI 覆盖 ROI
    low, high = resp.confidence_interval
    assert low <= resp.predicted_roi_ratio <= high + 1e-6
    # narrative 含中文
    assert any("一" <= ch <= "鿿" for ch in resp.narrative_zh)
    # 商户档案触发 cache_hit_ratio
    assert resp.cache_hit_ratio == 0.75


@pytest.mark.asyncio
async def test_pipeline_uses_default_lift_for_unknown_type():
    """ACTIVITY_LIFT_TABLE 里的 8 类应该都覆盖；未知类型走 DEFAULT_LIFT。"""
    assert "full_reduction" in ACTIVITY_LIFT_TABLE
    assert "douyin_groupon" in ACTIVITY_LIFT_TABLE
    assert all(v["lift_factor"] >= 1.0 for v in ACTIVITY_LIFT_TABLE.values())


# ─── 6) MAPE estimation uses holdout window ──────────────────────────────────


def test_mape_estimation_uses_holdout_window():
    # 构造 21 天的数据：14 天训练 + 7 天 holdout
    repo = FakeGmvRepo()
    history: list[HistoricalGmvPoint] = []
    for i in range(21):
        d = date(2026, 3, 1) + timedelta(days=i)
        wd = d.weekday()
        mult = 1.4 if wd >= 5 else 1.0
        history.append(HistoricalGmvPoint(day=d, gmv_fen=int(50_000_00 * mult)))

    mape = estimate_mape_holdout(history, holdout_days=7)
    # 季节性纯净时 fallback 应在 < 30% 范围
    assert math.isfinite(mape)
    assert 0.0 <= mape < 0.30, f"holdout MAPE 异常: {mape}"

    # 数据不足 21 天时返回 inf
    short = history[:10]
    assert math.isinf(estimate_mape_holdout(short, holdout_days=7))


# ─── 7) Route auth: missing JWT / X-Tenant-ID rejected ───────────────────────


@pytest.fixture
def fake_pipeline():
    """构造一个真实 pipeline + mock router；不需要可达性。"""
    pipe = ActivityROIPipeline(
        gmv_repository=FakeGmvRepo(),
        narrator=ActivityROINarrator(model_router=FakeModelRouter()),
        merchant_repository=FakeMerchantRepo(),
    )
    return pipe


@pytest.mark.asyncio
async def test_route_authn_rejects_missing_jwt(fake_pipeline):
    app.dependency_overrides[_get_pipeline] = lambda: fake_pipeline
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            payload = {
                "tenant_id": str(TENANT_ID),
                "store_id": str(STORE_ID),
                "activity_type": "full_reduction",
                "start_at": "2026-04-10T00:00:00+00:00",
                "end_at": "2026-04-12T00:00:00+00:00",
                "cost_budget_fen": 200000,
                "historical_baseline_days": 30,
            }

            # 缺 Authorization → 422 (FastAPI Header(...) 必填)
            resp = await client.post(
                "/api/v1/agents/activity-roi/predict",
                headers={"X-Tenant-ID": str(TENANT_ID)},
                json=payload,
            )
            assert resp.status_code in (401, 422)

            # 缺 X-Tenant-ID → 422
            resp = await client.post(
                "/api/v1/agents/activity-roi/predict",
                headers={"Authorization": "Bearer test-token"},
                json=payload,
            )
            assert resp.status_code in (400, 422)

            # 完整 + body.tenant_id 与 header 不一致 → 403
            other = uuid.uuid4()
            resp = await client.post(
                "/api/v1/agents/activity-roi/predict",
                headers={
                    "X-Tenant-ID": str(other),
                    "Authorization": "Bearer test-token",
                },
                json=payload,
            )
            assert resp.status_code == 403

            # 完整 + 一致 → 200
            resp = await client.post(
                "/api/v1/agents/activity-roi/predict",
                headers={
                    "X-Tenant-ID": str(TENANT_ID),
                    "Authorization": "Bearer test-token",
                },
                json=payload,
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert "predicted_roi_ratio" in data
            assert "narrative_zh" in data
            assert "daily_predictions" in data
    finally:
        app.dependency_overrides.pop(_get_pipeline, None)


@pytest.mark.asyncio
async def test_route_rejects_insufficient_history_with_409(fake_pipeline):
    """注入 _ShortGmvRepo 后整个 pipeline 应 raise InsufficientHistoricalDataError → 409。"""
    pipeline_short = ActivityROIPipeline(
        gmv_repository=_ShortGmvRepo(),
        narrator=ActivityROINarrator(model_router=FakeModelRouter()),
    )
    app.dependency_overrides[_get_pipeline] = lambda: pipeline_short
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            payload = {
                "tenant_id": str(TENANT_ID),
                "store_id": str(STORE_ID),
                "activity_type": "douyin_groupon",
                "start_at": "2026-04-10T00:00:00+00:00",
                "end_at": "2026-04-11T00:00:00+00:00",
                "cost_budget_fen": 500000,
                "historical_baseline_days": 30,
            }
            resp = await client.post(
                "/api/v1/agents/activity-roi/predict",
                headers={
                    "X-Tenant-ID": str(TENANT_ID),
                    "Authorization": "Bearer test-token",
                },
                json=payload,
            )
            assert resp.status_code == 409
    finally:
        app.dependency_overrides.pop(_get_pipeline, None)


# 防 unused import 报错（ruff 配 __init__.py 例外，不需要）
_ = AsyncMock
_ = _require_tenant
_ = _require_bearer
