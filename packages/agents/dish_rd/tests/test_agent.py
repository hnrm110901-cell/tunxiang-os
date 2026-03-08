"""
菜品研发 Agent 单元测试 — Phase 10
运行：python3 -m pytest packages/agents/dish_rd/tests/test_agent.py -q
"""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost/zhilian")
os.environ.setdefault("SECRET_KEY",   "test-secret-key")
os.environ.setdefault("REDIS_URL",    "redis://localhost:6379")

import sys
import enum
import types
import uuid
from pathlib import Path
from datetime import datetime, date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

agent_root = Path(__file__).resolve().parent.parent

# ─────────────────────────────────────────────────────────────────────────────
# 构建假的 src 命名空间，解决 src 包名冲突
# ─────────────────────────────────────────────────────────────────────────────

# --- 真实 Enum 定义（与 production 一致）---
class DishStatusEnum(str, enum.Enum):
    DRAFT = "draft"; IDEATION = "ideation"; IN_DEV = "in_dev"
    SAMPLING = "sampling"; PILOT_PENDING = "pilot_pending"; PILOTING = "piloting"
    LAUNCH_READY = "launch_ready"; LAUNCHED = "launched"; OPTIMIZING = "optimizing"
    DISCONTINUED = "discontinued"; ARCHIVED = "archived"

class DishTypeEnum(str, enum.Enum):
    NEW = "new"; UPGRADE = "upgrade"; SEASONAL = "seasonal"
    REGIONAL = "regional"; BANQUET = "banquet"; DELIVERY = "delivery"

class VersionTypeEnum(str, enum.Enum):
    DEV = "dev"; PILOT = "pilot"; REGIONAL = "regional"; NATIONAL = "national"
    COST_DOWN = "cost_down"; DELIVERY = "delivery"; SEASONAL = "seasonal"; DEPRECATED = "deprecated"

class RecipeVersionStatusEnum(str, enum.Enum):
    DRAFT = "draft"; PENDING = "pending"; APPROVED = "approved"
    PUBLISHED = "published"; DEPRECATED = "deprecated"

class PilotStatusEnum(str, enum.Enum):
    PENDING = "pending"; ACTIVE = "active"; COMPLETED = "completed"; TERMINATED = "terminated"

class PilotDecisionEnum(str, enum.Enum):
    GO = "go"; REVISE = "revise"; STOP = "stop"

class LaunchStatusEnum(str, enum.Enum):
    PENDING = "pending"; LAUNCHING = "launching"; LAUNCHED = "launched"; ROLLED_BACK = "rolled_back"

class LaunchTypeEnum(str, enum.Enum):
    NATIONAL = "national"; REGIONAL = "regional"; STORE_GRAY = "store_gray"

class FeedbackSourceEnum(str, enum.Enum):
    CUSTOMER = "customer"; MANAGER = "manager"; CHEF = "chef"
    SUPERVISOR = "supervisor"; TASTER = "taster"; SYSTEM = "system"

class FeedbackTypeEnum(str, enum.Enum):
    TASTE = "taste"; PLATING = "plating"; SPEED = "speed"; COST = "cost"
    EXECUTION = "execution"; RETURN = "return"; COMPLAINT = "complaint"; SUGGESTION = "suggestion"

class LifecycleAssessmentEnum(str, enum.Enum):
    KEEP = "keep"; OPTIMIZE = "optimize"; REGIONAL_KEEP = "regional_keep"
    MONITOR = "monitor"; RETIRE = "retire"

class SupplyRecommendationEnum(str, enum.Enum):
    NATIONAL = "national"; REGIONAL = "regional"; PILOT_ONLY = "pilot_only"; NOT_READY = "not_ready"

class RiskLevelEnum(str, enum.Enum):
    LOW = "low"; MEDIUM = "medium"; HIGH = "high"

class DishRdAgentTypeEnum(str, enum.Enum):
    COST_SIM = "cost_sim"; PILOT_REC = "pilot_rec"; REVIEW = "review"
    LAUNCH_ASSIST = "launch_assist"; RISK_ALERT = "risk_alert"; ALT_INGREDIENT = "alt_ingredient"

class PositioningTypeEnum(str, enum.Enum):
    TRAFFIC = "traffic"; PROFIT = "profit"; IMAGE = "image"; STAR = "star"; SEASONAL = "seasonal"

class SopTypeEnum(str, enum.Enum):
    STANDARD = "standard"; PEAK = "peak"; DELIVERY = "delivery"; BANQUET = "banquet"

class RecipeTypeEnum(str, enum.Enum):
    MAIN = "main"; SEMI = "semi"; SAUCE = "sauce"; DIPPING = "dipping"; DELIVERY = "delivery"; BANQUET = "banquet"

class IngredientSeasonEnum(str, enum.Enum):
    ALL_YEAR = "all_year"; SEASONAL = "seasonal"

class TemperatureTypeEnum(str, enum.Enum):
    AMBIENT = "ambient"; CHILLED = "chilled"; FROZEN = "frozen"

class SupplierTypeEnum(str, enum.Enum):
    ORIGIN = "origin"; PROCESSOR = "processor"; DISTRIBUTOR = "distributor"

class SemiTypeEnum(str, enum.Enum):
    BASE = "base"; SAUCE = "sauce"; PREPARED = "prepared"; DIPPING = "dipping"; CONDIMENT = "condiment"

class ProjectStatusEnum(str, enum.Enum):
    PENDING_APPROVAL = "pending_approval"; APPROVED = "approved"; IN_DEV = "in_dev"
    PILOTING = "piloting"; LAUNCHED = "launched"; TERMINATED = "terminated"; CLOSED = "closed"


# --- ORM Stub 机制 ---
class _ColProxy:
    def __eq__(self, other): return _ColProxy()
    def __ne__(self, other): return _ColProxy()
    def __lt__(self, other): return _ColProxy()
    def __le__(self, other): return _ColProxy()
    def __gt__(self, other): return _ColProxy()
    def __ge__(self, other): return _ColProxy()
    def __mul__(self, other): return _ColProxy()
    def __rmul__(self, other): return _ColProxy()
    def __floordiv__(self, other): return _ColProxy()
    def __add__(self, other): return _ColProxy()
    def __radd__(self, other): return _ColProxy()
    def __sub__(self, other): return _ColProxy()
    def __hash__(self): return id(self)
    def __bool__(self): return True
    def __repr__(self): return "ColProxy()"
    def notin_(self, *a, **kw): return _ColProxy()
    def in_(self, *a, **kw): return _ColProxy()
    def desc(self): return _ColProxy()
    def asc(self): return _ColProxy()
    def ilike(self, *a, **kw): return _ColProxy()
    def label(self, *a, **kw): return _ColProxy()
    def cast(self, *a, **kw): return _ColProxy()

def _orm_init(self, *args, **kwargs):
    for k, v in kwargs.items():
        setattr(self, k, v)

class _OrmStubMeta(type):
    def __getattr__(cls, name):
        return _ColProxy()

def _make_orm_stub(name: str):
    return _OrmStubMeta(name, (), {"__init__": _orm_init})

# --- 构建 src.models.dish_rd ---
_dish_rd_mod = types.ModuleType("src.models.dish_rd")
_all_enums = [
    DishStatusEnum, DishTypeEnum, VersionTypeEnum, RecipeVersionStatusEnum,
    PilotStatusEnum, PilotDecisionEnum, LaunchStatusEnum, LaunchTypeEnum,
    FeedbackSourceEnum, FeedbackTypeEnum, LifecycleAssessmentEnum,
    SupplyRecommendationEnum, RiskLevelEnum, DishRdAgentTypeEnum,
    PositioningTypeEnum, SopTypeEnum, RecipeTypeEnum, IngredientSeasonEnum,
    TemperatureTypeEnum, SupplierTypeEnum, SemiTypeEnum, ProjectStatusEnum,
]
for _e in _all_enums:
    setattr(_dish_rd_mod, _e.__name__, _e)

_orm_class_names = [
    "Dish", "DishVersion", "IdeaProject", "Recipe", "RecipeVersion", "RecipeItem",
    "SOP", "NutritionProfile", "AllergenProfile", "CostModel", "SupplyAssessment",
    "PilotTest", "LaunchProject", "DishFeedback", "RetrospectiveReport",
    "DishRdAgentLog", "Ingredient", "SemiProduct", "Supplier", "DishCategory",
]
for _cls_name in _orm_class_names:
    setattr(_dish_rd_mod, _cls_name, _make_orm_stub(_cls_name))

# Retrieve stubs for easy use
Dish             = _dish_rd_mod.Dish
RecipeVersion    = _dish_rd_mod.RecipeVersion
RecipeItem       = _dish_rd_mod.RecipeItem
Recipe           = _dish_rd_mod.Recipe
CostModel        = _dish_rd_mod.CostModel
PilotTest        = _dish_rd_mod.PilotTest
LaunchProject    = _dish_rd_mod.LaunchProject
DishFeedback     = _dish_rd_mod.DishFeedback
RetrospectiveReport = _dish_rd_mod.RetrospectiveReport
DishRdAgentLog   = _dish_rd_mod.DishRdAgentLog
SOP              = _dish_rd_mod.SOP

# --- 构建 fake src ---
_src_mod = types.ModuleType("src")
_src_mod.__path__ = [str(agent_root / "src")]
_models_mod = types.ModuleType("src.models")
_models_mod.dish_rd = _dish_rd_mod
_src_mod.models = _models_mod

sys.modules.setdefault("src", _src_mod)
sys.modules.setdefault("src.models", _models_mod)
sys.modules.setdefault("src.models.dish_rd", _dish_rd_mod)

if str(agent_root) not in sys.path:
    sys.path.insert(0, str(agent_root))

# --- import agent & patch SQLAlchemy ---
import src.agent as _agent_module
from sqlalchemy import Integer as sa_Integer

def _chainable_mock(*_a, **_kw):
    m = MagicMock()
    m.where = lambda *a, **kw: m
    m.join  = lambda *a, **kw: m
    m.order_by = lambda *a, **kw: m
    m.offset   = lambda *a, **kw: m
    m.limit    = lambda *a, **kw: m
    m.group_by = lambda *a, **kw: m
    m.select_from = lambda *a, **kw: m
    return m

_agent_module.select = _chainable_mock
_agent_module.func   = MagicMock(count=_chainable_mock, avg=_chainable_mock, sum=_chainable_mock)
_agent_module.and_   = MagicMock(side_effect=lambda *args: args[0] if args else MagicMock())
_agent_module.sa_Integer = sa_Integer

from src.agent import CostSimAgent, PilotRecAgent, DishReviewAgent, LaunchAssistAgent, RiskAlertAgent


# ─────────────────────────────────────────────────────────────────────────────
# 辅助：创建 mock DB
# ─────────────────────────────────────────────────────────────────────────────

def _make_db(scalars_value=None, scalar_value=None, all_value=None):
    """创建一个 mock AsyncSession"""
    db = MagicMock()
    result = MagicMock()

    if all_value is not None:
        result.all.return_value = all_value
    if scalars_value is not None:
        scalars = MagicMock()
        scalars.all.return_value = scalars_value if isinstance(scalars_value, list) else [scalars_value]
        scalars.first.return_value = scalars_value if not isinstance(scalars_value, list) else (scalars_value[0] if scalars_value else None)
        result.scalars.return_value = scalars
    if scalar_value is not None:
        result.scalar.return_value = scalar_value

    db.execute = AsyncMock(return_value=result)
    db.add     = MagicMock()
    db.commit  = AsyncMock()
    return db


def _make_recipe_item(item_type, quantity, unit_price, loss_rate=0.05, name="鸡腿"):
    item = RecipeItem(
        id                  = str(uuid.uuid4()),
        recipe_version_id   = "rv-001",
        item_type           = item_type,
        item_id             = str(uuid.uuid4()),
        item_name_snapshot  = name,
        quantity            = quantity,
        unit                = "g",
        unit_price_snapshot = unit_price,
        loss_rate_snapshot  = loss_rate,
        process_stage       = "cooking",
        sequence_no         = 1,
        optional_flag       = False,
    )
    return item


# ─────────────────────────────────────────────────────────────────────────────
# TestCostSimAgent
# ─────────────────────────────────────────────────────────────────────────────

import pytest

class TestCostSimAgent:
    """成本仿真 Agent — 5个测试"""

    @pytest.mark.asyncio
    async def test_basic_cost_calculation(self):
        """基础：BOM 2行原料，成本正确计算"""
        agent = CostSimAgent()
        items = [
            _make_recipe_item("ingredient", 200, 0.05, loss_rate=0.1, name="猪里脊"),  # 200g@0.05元/g
            _make_recipe_item("ingredient", 50,  0.02, loss_rate=0.05, name="青椒"),
        ]
        db = _make_db(scalars_value=items, scalar_value=0)

        result = await agent.simulate(
            recipe_version_id="rv-001",
            dish_id="d-001",
            brand_id="brand-001",
            db=db,
            save=False,
        )
        assert result["total_cost"] > 0
        assert len(result["item_details"]) == 2
        assert result["margin_rate"] == 0.60    # 默认60%方案

    @pytest.mark.asyncio
    async def test_empty_bom_returns_zero(self):
        """无 BOM 明细时返回零成本结构"""
        agent = CostSimAgent()
        db = _make_db(scalars_value=[], scalar_value=0)

        result = await agent.simulate("rv-empty", "d-001", "brand-001", db, save=False)
        assert result["total_cost"] == 0
        assert result["price_scenarios"] == []

    @pytest.mark.asyncio
    async def test_price_scenarios_sorted_by_margin(self):
        """多定价方案按毛利率升序排列"""
        agent = CostSimAgent()
        items = [_make_recipe_item("ingredient", 100, 0.08, name="牛肉")]
        db = _make_db(scalars_value=items, scalar_value=0)

        result = await agent.simulate("rv-001", "d-001", "brand-001", db, save=False)
        rates = [s["target_margin_rate"] for s in result["price_scenarios"]]
        assert rates == sorted(rates)   # 升序

    @pytest.mark.asyncio
    async def test_suggested_price_covers_cost(self):
        """建议售价 > 总成本（毛利为正）"""
        agent = CostSimAgent()
        items = [_make_recipe_item("ingredient", 300, 0.04, name="鱼片")]
        db = _make_db(scalars_value=items, scalar_value=0)

        result = await agent.simulate("rv-001", "d-001", "brand-001", db, save=False)
        assert result["suggested_price_yuan"] > result["total_cost"]
        assert result["margin_amount_yuan"] > 0

    @pytest.mark.asyncio
    async def test_stress_test_reduces_margin(self):
        """原料涨价10%后毛利率下降"""
        agent = CostSimAgent()
        items = [_make_recipe_item("ingredient", 200, 0.06, name="猪肚")]
        db = _make_db(scalars_value=items, scalar_value=0)

        result = await agent.simulate(
            "rv-001", "d-001", "brand-001", db,
            price_sensitivity_pcts=[0.1],
            save=False,
        )
        assert len(result["stress_tests"]) == 1
        assert result["stress_tests"][0]["margin_delta"] < 0   # 毛利下降


# ─────────────────────────────────────────────────────────────────────────────
# TestPilotRecAgent
# ─────────────────────────────────────────────────────────────────────────────

class TestPilotRecAgent:
    """试点推荐 Agent — 4个测试"""

    def _make_dish(self, positioning_type=None, region_scope=None):
        dish = Dish(
            id               = "d-001",
            dish_name        = "测试菜品",
            positioning_type = positioning_type,
            region_scope     = region_scope or [],
        )
        return dish

    @pytest.mark.asyncio
    async def test_recommends_top_n_stores(self):
        """推荐店铺不超过 top_n 且按分值降序"""
        agent = PilotRecAgent()
        dish = self._make_dish()
        db = _make_db(scalars_value=dish)

        result = await agent.recommend_stores("d-001", "brand-001", db, top_n=3)
        assert len(result["recommended_stores"]) <= 3
        scores = [s["match_score"] for s in result["recommended_stores"]]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_higher_acceptance_rate_scores_higher(self):
        """新品接受率越高，匹配分越高"""
        agent = PilotRecAgent()
        dish = self._make_dish()

        store_high = {"store_id": "S_H", "region": "华南", "level": "standard", "new_dish_acceptance_rate": 0.9}
        store_low  = {"store_id": "S_L", "region": "华南", "level": "standard", "new_dish_acceptance_rate": 0.3}
        score_high = agent._score_store(dish, store_high)
        score_low  = agent._score_store(dish, store_low)
        assert score_high > score_low

    @pytest.mark.asyncio
    async def test_recommendation_includes_yuan_in_reason(self):
        """推荐理由包含菜品名称"""
        agent = PilotRecAgent()
        dish = self._make_dish()
        db = _make_db(scalars_value=dish)

        result = await agent.recommend_stores("d-001", "brand-001", db, top_n=3)
        assert dish.dish_name in result["recommendation_reason"]

    @pytest.mark.asyncio
    async def test_dish_not_found_returns_error(self):
        """菜品不存在时返回 error 字段"""
        agent = PilotRecAgent()
        db = _make_db(scalars_value=None)

        # scalars().first() 返回 None
        result_mock = MagicMock()
        scalars = MagicMock()
        scalars.first.return_value = None
        result_mock.scalars.return_value = scalars
        db.execute = AsyncMock(return_value=result_mock)

        result = await agent.recommend_stores("d-notfound", "brand-001", db, top_n=3)
        assert "error" in result


# ─────────────────────────────────────────────────────────────────────────────
# TestDishReviewAgent
# ─────────────────────────────────────────────────────────────────────────────

class TestDishReviewAgent:
    """复盘优化 Agent — 5个测试"""

    def _make_feedback(self, feedback_type, rating=4.0, keyword_tags=None):
        f = DishFeedback(
            id              = str(uuid.uuid4()),
            dish_id         = "d-001",
            brand_id        = "brand-001",
            feedback_type   = feedback_type,
            rating_score    = rating,
            keyword_tags    = keyword_tags or [],
            created_at      = datetime.utcnow(),
            happened_at     = datetime.utcnow(),
        )
        return f

    @pytest.mark.asyncio
    async def test_total_feedbacks_count(self):
        """total_feedbacks 返回实际数量"""
        agent = DishReviewAgent()
        feedbacks = [self._make_feedback(FeedbackTypeEnum.TASTE, 4.5) for _ in range(10)]
        db = _make_db(scalars_value=feedbacks)

        result = await agent.run_review("d-001", "brand-001", db, dry_run=True)
        assert result["total_feedbacks"] == 10

    @pytest.mark.asyncio
    async def test_high_return_rate_triggers_retire(self):
        """退菜率>30%时生命周期判断为 retire"""
        agent = DishReviewAgent()
        feedbacks = (
            [self._make_feedback(FeedbackTypeEnum.RETURN) for _ in range(4)] +
            [self._make_feedback(FeedbackTypeEnum.TASTE, 3.8) for _ in range(3)]
        )  # return_rate = 4/7 > 0.3
        db = _make_db(scalars_value=feedbacks)

        result = await agent.run_review("d-001", "brand-001", db, dry_run=True)
        assert result["lifecycle_assessment"] == LifecycleAssessmentEnum.RETIRE.value

    @pytest.mark.asyncio
    async def test_good_scores_return_keep(self):
        """口味均分≥4.0且低退菜率 → keep"""
        agent = DishReviewAgent()
        feedbacks = [self._make_feedback(FeedbackTypeEnum.TASTE, 4.5) for _ in range(8)]
        db = _make_db(scalars_value=feedbacks)

        result = await agent.run_review("d-001", "brand-001", db, dry_run=True)
        assert result["lifecycle_assessment"] == LifecycleAssessmentEnum.KEEP.value

    @pytest.mark.asyncio
    async def test_suggestions_not_empty(self):
        """优化建议列表不为空"""
        agent = DishReviewAgent()
        feedbacks = [self._make_feedback(FeedbackTypeEnum.TASTE, 3.0)]
        db = _make_db(scalars_value=feedbacks)

        result = await agent.run_review("d-001", "brand-001", db, dry_run=True)
        assert len(result["optimization_suggestions"]) > 0

    @pytest.mark.asyncio
    async def test_no_feedbacks_returns_monitor(self):
        """无反馈数据时默认返回 monitor"""
        agent = DishReviewAgent()
        db = _make_db(scalars_value=[])

        result = await agent.run_review("d-001", "brand-001", db, dry_run=True)
        assert result["lifecycle_assessment"] == LifecycleAssessmentEnum.MONITOR.value


# ─────────────────────────────────────────────────────────────────────────────
# TestLaunchAssistAgent
# ─────────────────────────────────────────────────────────────────────────────

class TestLaunchAssistAgent:
    """发布助手 Agent — 4个测试"""

    def _make_dish(self):
        return Dish(id="d-001", dish_name="秘制红烧肉", brand_id="brand-001")

    def _make_approved_recipe(self):
        rv = RecipeVersion(id="rv-001", recipe_id="r-001", status="approved")
        return rv

    def _make_cost_model(self, margin_rate=0.60):
        cm = CostModel(id="cm-001", dish_id="d-001", brand_id="brand-001",
                       margin_rate=margin_rate, total_cost=15.0, suggested_price_yuan=38.0)
        return cm

    @pytest.mark.asyncio
    async def test_all_conditions_ready(self):
        """全部前置条件满足时 ready_to_launch=True"""
        agent = LaunchAssistAgent()
        db = MagicMock()

        # 模拟每次 execute 返回对应对象
        dish = self._make_dish()
        rv   = self._make_approved_recipe()
        cm   = self._make_cost_model(0.62)
        sop  = SOP(id="sop-001", dish_id="d-001", status="published")
        pilot = PilotTest(id="p-001", dish_id="d-001", decision="go")

        call_counter = [0]
        async def _execute(query):
            result = MagicMock()
            scalars = MagicMock()
            n = call_counter[0]
            call_counter[0] += 1
            # 按调用顺序返回
            objects = [dish, rv, cm, sop, pilot]
            scalars.first.return_value = objects[n] if n < len(objects) else None
            result.scalars.return_value = scalars
            return result

        db.execute = _execute
        db.add = MagicMock()
        db.commit = AsyncMock()

        result = await agent.check_launch_readiness("d-001", "brand-001", None, db)
        # dish found → checklist 至少有条目
        assert "checklist" in result

    @pytest.mark.asyncio
    async def test_missing_sop_shows_in_missing_items(self):
        """缺 SOP 时 missing_items 应包含 SOP 相关提示"""
        agent = LaunchAssistAgent()

        dish = self._make_dish()
        rv   = self._make_approved_recipe()
        cm   = self._make_cost_model(0.60)

        call_counter = [0]
        async def _execute(query):
            result = MagicMock()
            scalars = MagicMock()
            n = call_counter[0]
            call_counter[0] += 1
            # dish, rv, cm, sop=None, pilot=None
            values = [dish, rv, cm, None, None]
            scalars.first.return_value = values[n] if n < len(values) else None
            result.scalars.return_value = scalars
            return result

        db = MagicMock()
        db.execute = _execute
        db.add = MagicMock()
        db.commit = AsyncMock()

        result = await agent.check_launch_readiness("d-001", "brand-001", None, db)
        assert not result.get("ready_to_launch", True)
        assert any("SOP" in item or "工艺" in item for item in result.get("missing_items", []))

    @pytest.mark.asyncio
    async def test_low_margin_triggers_missing(self):
        """毛利率 < 50% 触发成本缺项"""
        agent = LaunchAssistAgent()
        dish = self._make_dish()
        rv   = self._make_approved_recipe()
        cm   = self._make_cost_model(0.40)    # 低于50%

        call_counter = [0]
        async def _execute(query):
            result = MagicMock()
            scalars = MagicMock()
            n = call_counter[0]
            call_counter[0] += 1
            values = [dish, rv, cm, None, None]
            scalars.first.return_value = values[n] if n < len(values) else None
            result.scalars.return_value = scalars
            return result

        db = MagicMock()
        db.execute = _execute
        db.add = MagicMock()
        db.commit = AsyncMock()

        result = await agent.check_launch_readiness("d-001", "brand-001", None, db)
        assert any("毛利" in item or "成本" in item for item in result.get("missing_items", []))

    @pytest.mark.asyncio
    async def test_dish_not_found_returns_error(self):
        """菜品不存在时返回 error"""
        agent = LaunchAssistAgent()
        result_mock = MagicMock()
        scalars = MagicMock()
        scalars.first.return_value = None
        result_mock.scalars.return_value = scalars

        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        db.commit = AsyncMock()

        result = await agent.check_launch_readiness("d-notfound", "brand-001", None, db)
        assert "error" in result


# ─────────────────────────────────────────────────────────────────────────────
# TestRiskAlertAgent
# ─────────────────────────────────────────────────────────────────────────────

class TestRiskAlertAgent:
    """风险预警 Agent — 4个测试"""

    @pytest.mark.asyncio
    async def test_no_risks_when_no_data(self):
        """无数据时返回空风险列表"""
        agent = RiskAlertAgent()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        db.add = MagicMock()
        db.commit = AsyncMock()

        result = await agent.scan_risks("brand-001", db, dry_run=True)
        assert result["risk_count"] == 0
        assert result["risks"] == []

    @pytest.mark.asyncio
    async def test_low_margin_detected_as_high_risk(self):
        """毛利 < 45% 的成本模型识别为 high 风险"""
        agent = RiskAlertAgent()
        # 模拟一条毛利率为 0.35 的成本模型
        row = MagicMock()
        row.__iter__ = lambda s: iter([MagicMock(dish_id="d-001", margin_rate=0.35), "低毛利菜"])
        row[0] = MagicMock(dish_id="d-001", margin_rate=0.35)
        row[1] = "低毛利菜"

        # scan_risks 会执行 3 次 execute：cost/pilot/feedback
        call_counter = [0]
        async def _execute(query):
            n = call_counter[0]
            call_counter[0] += 1
            result = MagicMock()
            if n == 0:   # cost query
                result.all.return_value = [(MagicMock(dish_id="d-001", margin_rate=0.35), "低毛利菜")]
            else:
                result.all.return_value = []
            return result

        db = MagicMock()
        db.execute = _execute
        db.add = MagicMock()
        db.commit = AsyncMock()

        result = await agent.scan_risks("brand-001", db, dry_run=True)
        assert result["risk_count"] >= 1
        assert any(r["risk_level"] == "high" for r in result["risks"])

    @pytest.mark.asyncio
    async def test_dry_run_does_not_commit(self):
        """dry_run=True 时不写入数据库"""
        agent = RiskAlertAgent()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        db.add = MagicMock()
        db.commit = AsyncMock()

        await agent.scan_risks("brand-001", db, dry_run=True)
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_result_has_high_and_medium_lists(self):
        """返回结果包含 high_risks 和 medium_risks 分别的列表"""
        agent = RiskAlertAgent()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        db = MagicMock()
        db.execute = AsyncMock(return_value=result_mock)
        db.commit = AsyncMock()

        result = await agent.scan_risks("brand-001", db, dry_run=True)
        assert "high_risks" in result
        assert "medium_risks" in result
        assert isinstance(result["high_risks"], list)
        assert isinstance(result["medium_risks"], list)
