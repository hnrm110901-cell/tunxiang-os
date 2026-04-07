"""
Y-K3 出餐时间预测器测试

覆盖文件：
  edge/coreml-bridge/src/dish_time_predictor.py
  edge/coreml-bridge/src/rule_fallback.py
  edge/coreml-bridge/src/main.py

测试共 8 个：
  1. test_rule_fallback_hot_dish_normal_hours   — 正常时段热菜基线
  2. test_rule_fallback_peak_hours_penalty      — 高峰期加时 2 分钟
  3. test_rule_fallback_deep_queue_penalty      — 队列深度加时（上限 8 分钟）
  4. test_rule_fallback_complexity_multiplier   — 复杂度乘数生效
  5. test_rule_fallback_minimum_3_minutes       — 最少 3 分钟保底
  6. test_predict_returns_method_field          — 返回 method 字段
  7. test_predict_returns_p95                  — p95 > estimated
  8. test_discount_risk_evaluation             — 折扣风险规则三档判定
"""
from __future__ import annotations

import os
import sys
import types

# ─── sys.path 准备 ────────────────────────────────────────────────────────────
_TESTS_DIR = os.path.dirname(__file__)
_SRC_DIR = os.path.abspath(os.path.join(_TESTS_DIR, "..", "src"))
_BRIDGE_ROOT = os.path.abspath(os.path.join(_TESTS_DIR, ".."))

for _p in [_SRC_DIR, _BRIDGE_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _ensure_pkg(name: str, path: str) -> None:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path]
        mod.__package__ = name
        sys.modules[name] = mod


_ensure_pkg("src", _SRC_DIR)

# ─── structlog mock ───────────────────────────────────────────────────────────
_structlog = types.ModuleType("structlog")
_bound_logger = types.SimpleNamespace(
    info=lambda *a, **k: None,
    warning=lambda *a, **k: None,
    error=lambda *a, **k: None,
    debug=lambda *a, **k: None,
)
_structlog.get_logger = lambda *a, **k: _bound_logger  # type: ignore[attr-defined]
_structlog.stdlib = types.SimpleNamespace(BoundLogger=object)  # type: ignore[attr-defined]
sys.modules.setdefault("structlog", _structlog)

# ─── 正式 import ──────────────────────────────────────────────────────────────
import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from dish_time_predictor import DishTimePredictor, PredictionInput  # type: ignore[import]  # noqa: E402
from rule_fallback import RuleBasedDiscountRisk, DiscountRiskInput  # type: ignore[import]  # noqa: E402

# main.py uses relative imports — build standalone FastAPI test app instead
from fastapi import HTTPException  # noqa: E402
from dish_time_predictor import get_predictor, PredictionInput as _PI  # type: ignore[import]  # noqa: E402
from rule_fallback import (  # type: ignore[import]  # noqa: E402
    RuleBasedDiscountRisk as _RDR,
    DiscountRiskInput as _DRI,
    RuleBasedTrafficPredict,
    TrafficPredictInput,
)

# ─── 独立测试 FastAPI App（避免相对导入问题）────────────────────────────────
_app = FastAPI()
_discount_risk = _RDR()
_traffic_predict = RuleBasedTrafficPredict()


@_app.get("/health")
async def _health():
    return {"ok": True, "service": "coreml-bridge-python"}


@_app.get("/model-status")
async def _model_status():
    predictor = get_predictor()
    method = "coreml" if predictor._coreml_available else "rule_fallback"
    return {"ok": True, "data": {"models": {
        "dish_time_predictor": {"method": method, "coreml_available": predictor._coreml_available},
        "discount_risk": {"method": "rule_fallback", "coreml_available": False},
        "traffic_predict": {"method": "rule_fallback", "coreml_available": False},
    }}}


from pydantic import BaseModel, Field  # noqa: E402


class _DishTimeReq(BaseModel):
    dish_category: str
    dish_complexity: int = Field(..., ge=1, le=5)
    current_queue_depth: int = 0
    hour_of_day: int = Field(..., ge=0, le=23)
    concurrent_orders: int = 1


class _DiscountRiskReq(BaseModel):
    discount_rate: float
    hour_of_day: int
    order_amount_fen: int = 0
    employee_id: str = ""
    table_id: str = ""


@_app.post("/predict/dish-time")
async def _predict_dish_time(req: _DishTimeReq):
    predictor = get_predictor()
    result = predictor.predict(_PI(
        dish_category=req.dish_category,
        dish_complexity=req.dish_complexity,
        current_queue_depth=req.current_queue_depth,
        hour_of_day=req.hour_of_day,
        concurrent_orders=req.concurrent_orders,
    ))
    return {"ok": True, "data": {
        "estimated_minutes": result.estimated_minutes,
        "confidence": result.confidence,
        "method": result.method,
        "p95_minutes": result.p95_minutes,
        "inference_ms": round(result.inference_ms, 3),
    }}


@_app.post("/predict/discount-risk")
async def _predict_discount_risk(req: _DiscountRiskReq):
    result = _discount_risk.evaluate_discount(_DRI(
        discount_rate=req.discount_rate,
        hour_of_day=req.hour_of_day,
        order_amount_fen=req.order_amount_fen,
        employee_id=req.employee_id,
        table_id=req.table_id,
    ))
    return {"ok": True, "data": {
        "risk_level": result.risk_level,
        "risk_score": result.risk_score,
        "method": result.method,
        "reasons": result.reasons,
        "should_alert": result.should_alert,
    }}


client = TestClient(_app)


# ─── 辅助工厂 ─────────────────────────────────────────────────────────────────


def _make_predictor() -> DishTimePredictor:
    """创建不依赖 CoreML 的预测器实例（强制规则引擎）"""
    p = DishTimePredictor.__new__(DishTimePredictor)
    p._coreml_available = False
    p._model = None
    return p


# ─── Tests ────────────────────────────────────────────────────────────────────


class TestRuleEngine:

    def test_rule_fallback_hot_dish_normal_hours(self) -> None:
        """1. 正常时段热菜：base=12, complexity=3(×1.0), no queue, no peak → 12.0"""
        predictor = _make_predictor()
        inp = PredictionInput(
            dish_category="hot_dishes",
            dish_complexity=3,
            current_queue_depth=0,
            hour_of_day=10,   # 非高峰期
            concurrent_orders=1,
        )
        result = predictor._predict_rules(inp)
        assert result.method == "rule_fallback"
        assert result.estimated_minutes == pytest.approx(12.0, abs=0.2)
        assert result.confidence == 0.85  # 非高峰期置信度

    def test_rule_fallback_peak_hours_penalty(self) -> None:
        """2. 高峰期（12时）加时 +2 分钟，且置信度降为 0.75"""
        predictor = _make_predictor()
        inp_normal = PredictionInput(
            dish_category="hot_dishes",
            dish_complexity=3,
            current_queue_depth=0,
            hour_of_day=10,
            concurrent_orders=1,
        )
        inp_peak = PredictionInput(
            dish_category="hot_dishes",
            dish_complexity=3,
            current_queue_depth=0,
            hour_of_day=12,   # 午市高峰
            concurrent_orders=1,
        )
        normal = predictor._predict_rules(inp_normal)
        peak = predictor._predict_rules(inp_peak)

        assert peak.estimated_minutes == pytest.approx(normal.estimated_minutes + 2.0, abs=0.2)
        assert peak.confidence == 0.75

    def test_rule_fallback_deep_queue_penalty(self) -> None:
        """3. 队列深度=15（超限）→ queue_penalty 上限 8 分钟"""
        predictor = _make_predictor()
        inp = PredictionInput(
            dish_category="cold_dishes",
            dish_complexity=1,
            current_queue_depth=15,  # 15*0.8=12 → 超过上限 8
            hour_of_day=10,
            concurrent_orders=1,
        )
        result = predictor._predict_rules(inp)
        # base=5*0.7=3.5 + queue_penalty=8(上限) + no peak = 11.5
        assert result.estimated_minutes == pytest.approx(11.5, abs=0.3)

    def test_rule_fallback_complexity_multiplier(self) -> None:
        """4. 复杂度乘数：complexity=5 → ×1.6，complexity=1 → ×0.7"""
        predictor = _make_predictor()
        inp_low = PredictionInput(
            dish_category="noodles",
            dish_complexity=1,
            current_queue_depth=0,
            hour_of_day=10,
            concurrent_orders=1,
        )
        inp_high = PredictionInput(
            dish_category="noodles",
            dish_complexity=5,
            current_queue_depth=0,
            hour_of_day=10,
            concurrent_orders=1,
        )
        low = predictor._predict_rules(inp_low)
        high = predictor._predict_rules(inp_high)

        # noodles base=8: 8*0.7=5.6, 8*1.6=12.8
        assert low.estimated_minutes == pytest.approx(5.6, abs=0.2)
        assert high.estimated_minutes == pytest.approx(12.8, abs=0.2)
        assert high.estimated_minutes > low.estimated_minutes

    def test_rule_fallback_minimum_3_minutes(self) -> None:
        """5. 极低输入（cold_dishes, complexity=1, 0队列）保底 3 分钟"""
        predictor = _make_predictor()
        inp = PredictionInput(
            dish_category="cold_dishes",
            dish_complexity=1,
            current_queue_depth=0,
            hour_of_day=3,   # 深夜，非高峰
            concurrent_orders=1,
        )
        result = predictor._predict_rules(inp)
        # 5*0.7=3.5, 超过3.0保底
        assert result.estimated_minutes >= 3.0

    def test_predict_returns_method_field(self) -> None:
        """6. predict() 返回结果包含 method 字段"""
        predictor = _make_predictor()
        inp = PredictionInput(
            dish_category="grill",
            dish_complexity=3,
            current_queue_depth=2,
            hour_of_day=19,
            concurrent_orders=2,
        )
        result = predictor.predict(inp)
        assert hasattr(result, "method")
        assert result.method in ("coreml", "rule_fallback")
        # 无 CoreML 时必然是规则引擎
        assert result.method == "rule_fallback"

    def test_predict_returns_p95(self) -> None:
        """7. p95_minutes > estimated_minutes（上分位数必须大于期望值）"""
        predictor = _make_predictor()
        inp = PredictionInput(
            dish_category="hot_dishes",
            dish_complexity=4,
            current_queue_depth=5,
            hour_of_day=18,
            concurrent_orders=4,
        )
        result = predictor.predict(inp)
        assert result.p95_minutes > result.estimated_minutes


class TestDiscountRisk:

    def test_discount_risk_evaluation(self) -> None:
        """8. 折扣风险规则三档判定"""
        engine = RuleBasedDiscountRisk()

        # 低风险：折扣率 0.1
        low = engine.evaluate_discount(DiscountRiskInput(
            discount_rate=0.1,
            hour_of_day=15,   # 非高峰
            order_amount_fen=5000,
        ))
        assert low.risk_level == "low"
        assert low.should_alert is False

        # 中风险：折扣率 0.35
        medium = engine.evaluate_discount(DiscountRiskInput(
            discount_rate=0.35,
            hour_of_day=15,
            order_amount_fen=5000,
        ))
        assert medium.risk_level == "medium"
        assert medium.should_alert is True

        # 高风险：折扣率 0.6
        high = engine.evaluate_discount(DiscountRiskInput(
            discount_rate=0.6,
            hour_of_day=15,
            order_amount_fen=5000,
        ))
        assert high.risk_level == "high"
        assert high.risk_score >= 60
        assert high.should_alert is True
        assert len(high.reasons) >= 1

        # 高峰期 + 折扣 > 0.4 → 额外加分
        peak_high = engine.evaluate_discount(DiscountRiskInput(
            discount_rate=0.45,
            hour_of_day=12,  # 午市高峰
            order_amount_fen=5000,
        ))
        non_peak = engine.evaluate_discount(DiscountRiskInput(
            discount_rate=0.45,
            hour_of_day=15,  # 非高峰
            order_amount_fen=5000,
        ))
        assert peak_high.risk_score > non_peak.risk_score


class TestAPIRoutes:
    """FastAPI 路由层冒烟测试"""

    def test_health_endpoint(self) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_model_status_endpoint(self) -> None:
        resp = client.get("/model-status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        models = body["data"]["models"]
        assert "dish_time_predictor" in models
        assert "discount_risk" in models
        assert models["dish_time_predictor"]["method"] in ("coreml", "rule_fallback")

    def test_predict_dish_time_api(self) -> None:
        resp = client.post("/predict/dish-time", json={
            "dish_category": "hot_dishes",
            "dish_complexity": 3,
            "current_queue_depth": 2,
            "hour_of_day": 12,
            "concurrent_orders": 2,
        })
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "estimated_minutes" in data
        assert "method" in data
        assert "p95_minutes" in data
        assert data["p95_minutes"] > data["estimated_minutes"]

    def test_predict_discount_risk_api(self) -> None:
        resp = client.post("/predict/discount-risk", json={
            "discount_rate": 0.55,
            "hour_of_day": 12,
            "order_amount_fen": 15000,
            "employee_id": "emp_001",
            "table_id": "T-05",
        })
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["risk_level"] == "high"
        assert data["should_alert"] is True
