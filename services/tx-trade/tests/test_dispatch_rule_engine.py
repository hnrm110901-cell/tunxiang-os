"""档口路由规则引擎单元测试

场景覆盖：
1. 外卖单的宫保鸡丁路由到B窗口（而非默认A窗口）
2. 品牌X的订单路由到X专属档口
3. 午高峰(11:00-14:00)的烤鸭路由到专门的烤鸭炉档口
4. 无匹配规则时fallback到DishDeptMapping默认值
5. 规则优先级：priority高的先匹配
6. tenant_id隔离：不同租户的规则互不影响
7. 跨午夜时段匹配
8. 规则缓存失效不影响其他门店
9. test_rule管理员测试接口
10. 渠道不匹配时跳过规则
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import uuid
from datetime import datetime, time, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

# ─── 测试工具 ───

def _uid() -> str:
    return str(uuid.uuid4())


TENANT_A = _uid()
TENANT_B = _uid()
STORE_1 = _uid()
STORE_2 = _uid()

DEPT_A = uuid.uuid4()   # 堂食默认A档口
DEPT_B = uuid.uuid4()   # 外卖B档口
DEPT_BRAND_X = uuid.uuid4()  # 品牌X专属档口
DEPT_ROAST = uuid.uuid4()    # 烤鸭炉档口

DISH_KUNG_PAO = _uid()   # 宫保鸡丁
DISH_DUCK = _uid()       # 烤鸭
DISH_SALAD = _uid()      # 凉菜（无规则）

BRAND_X = _uid()
PRINTER_B = uuid.uuid4()


def _make_rule(
    priority: int = 0,
    match_dish_id=None,
    match_dish_category=None,
    match_brand_id=None,
    match_channel=None,
    match_time_start=None,
    match_time_end=None,
    match_day_type=None,
    target_dept_id=DEPT_A,
    target_printer_id=None,
    tenant_id=None,
    store_id=None,
):
    """构建测试用 DispatchRule 对象。"""
    from models.dispatch_rule import DispatchRule

    rule = MagicMock(spec=DispatchRule)
    rule.id = uuid.uuid4()
    rule.name = f"规则-p{priority}"
    rule.priority = priority
    rule.match_dish_id = (match_dish_id if isinstance(match_dish_id, uuid.UUID)
                          else uuid.UUID(match_dish_id) if match_dish_id else None)
    rule.match_dish_category = match_dish_category
    rule.match_brand_id = (match_brand_id if isinstance(match_brand_id, uuid.UUID)
                           else uuid.UUID(match_brand_id) if match_brand_id else None)
    rule.match_channel = match_channel
    rule.match_time_start = match_time_start
    rule.match_time_end = match_time_end
    rule.match_day_type = match_day_type
    rule.target_dept_id = target_dept_id
    rule.target_printer_id = target_printer_id
    rule.is_active = True
    rule.is_deleted = False
    rule.tenant_id = uuid.UUID(tenant_id or TENANT_A)
    rule.store_id = uuid.UUID(store_id or STORE_1)
    return rule


def _make_db_with_rules(rules):
    """构建返回指定规则列表的 mock db。"""
    db = AsyncMock()

    class FakeScalars:
        def __init__(self, items):
            self._items = items

        def all(self):
            return self._items

    class FakeResult:
        def __init__(self, items):
            self._items = items

        def scalars(self):
            return FakeScalars(self._items)

        def one_or_none(self):
            return self._items[0] if self._items else None

        def scalar_one_or_none(self):
            return self._items[0] if self._items else None

    db.execute = AsyncMock(return_value=FakeResult(rules))
    return db


# ─── 测试 1: 外卖单宫保鸡丁路由到B窗口 ───

@pytest.mark.asyncio
async def test_takeaway_kung_pao_routes_to_dept_b():
    """外卖单的宫保鸡丁应路由到B窗口，而非默认A窗口。"""
    from services.dispatch_rule_engine import DispatchRuleEngine, _rule_cache

    _rule_cache.clear()

    # 优先级高的外卖规则
    rule_takeaway = _make_rule(
        priority=10,
        match_dish_id=DISH_KUNG_PAO,
        match_channel="takeaway",
        target_dept_id=DEPT_B,
        target_printer_id=PRINTER_B,
    )
    # 优先级低的堂食规则（不应该匹配）
    rule_dine_in = _make_rule(
        priority=5,
        match_dish_id=DISH_KUNG_PAO,
        match_channel="dine_in",
        target_dept_id=DEPT_A,
    )

    db = _make_db_with_rules([rule_takeaway, rule_dine_in])
    engine = DispatchRuleEngine()

    dept_id, printer_id = await engine.resolve_dept(
        dish_id=DISH_KUNG_PAO,
        dish_category=None,
        brand_id=None,
        channel="takeaway",
        order_time=datetime.now(timezone.utc),
        store_id=STORE_1,
        tenant_id=TENANT_A,
        db=db,
    )

    assert dept_id == DEPT_B, "外卖单应路由到B窗口"
    assert printer_id == PRINTER_B, "外卖单应使用B窗口打印机"


# ─── 测试 2: 品牌X订单路由到X专属档口 ───

@pytest.mark.asyncio
async def test_brand_x_routes_to_dedicated_dept():
    """品牌X的订单应路由到X专属档口。"""
    from services.dispatch_rule_engine import DispatchRuleEngine, _rule_cache

    _rule_cache.clear()

    rule_brand_x = _make_rule(
        priority=20,
        match_brand_id=BRAND_X,
        target_dept_id=DEPT_BRAND_X,
    )

    db = _make_db_with_rules([rule_brand_x])
    engine = DispatchRuleEngine()

    dept_id, printer_id = await engine.resolve_dept(
        dish_id=DISH_KUNG_PAO,
        dish_category=None,
        brand_id=BRAND_X,
        channel="dine_in",
        order_time=datetime.now(timezone.utc),
        store_id=STORE_1,
        tenant_id=TENANT_A,
        db=db,
    )

    assert dept_id == DEPT_BRAND_X, "品牌X订单应路由到X专属档口"
    assert printer_id is None


# ─── 测试 3: 午高峰烤鸭路由到专门的烤鸭炉档口 ───

@pytest.mark.asyncio
async def test_peak_hour_duck_routes_to_roast_dept():
    """午高峰(11:00-14:00)的烤鸭应路由到专门的烤鸭炉档口。"""
    from services.dispatch_rule_engine import DispatchRuleEngine, _rule_cache

    _rule_cache.clear()

    rule_roast = _make_rule(
        priority=15,
        match_dish_id=DISH_DUCK,
        match_time_start=time(11, 0),
        match_time_end=time(14, 0),
        target_dept_id=DEPT_ROAST,
    )

    db = _make_db_with_rules([rule_roast])
    engine = DispatchRuleEngine()

    # 12:30 下单，在午高峰时段内
    order_time_in_peak = datetime(2026, 3, 30, 12, 30, 0, tzinfo=timezone.utc)
    dept_id, _ = await engine.resolve_dept(
        dish_id=DISH_DUCK,
        dish_category=None,
        brand_id=None,
        channel="dine_in",
        order_time=order_time_in_peak,
        store_id=STORE_1,
        tenant_id=TENANT_A,
        db=db,
    )
    assert dept_id == DEPT_ROAST, "午高峰时段烤鸭应路由到烤鸭炉档口"


@pytest.mark.asyncio
async def test_off_peak_duck_no_rule_match():
    """午高峰以外时段的烤鸭，时段规则不应匹配。"""
    from services.dispatch_rule_engine import _rule_matches

    rule_roast = _make_rule(
        priority=15,
        match_dish_id=uuid.UUID(DISH_DUCK),
        match_time_start=time(11, 0),
        match_time_end=time(14, 0),
        target_dept_id=DEPT_ROAST,
    )

    # 09:00 下单，在午高峰时段外
    order_time_off_peak = datetime(2026, 3, 30, 9, 0, 0, tzinfo=timezone.utc)
    matched = _rule_matches(
        rule_roast,
        dish_id=uuid.UUID(DISH_DUCK),
        dish_category=None,
        brand_id=None,
        channel="dine_in",
        order_time=order_time_off_peak,
    )
    assert matched is False, "非午高峰时段不应匹配烤鸭炉规则"


# ─── 测试 4: 无匹配规则时fallback到DishDeptMapping ───

@pytest.mark.asyncio
async def test_no_rule_match_fallback_to_dish_dept_mapping():
    """无匹配规则时应fallback到DishDeptMapping默认值。"""
    from services.dispatch_rule_engine import DispatchRuleEngine, _rule_cache

    _rule_cache.clear()

    fallback_dept_id = uuid.uuid4()
    fallback_printer_id = uuid.uuid4()

    # 规则不匹配（品牌限制不符合当前请求）
    rule_brand_x = _make_rule(
        priority=10,
        match_brand_id=BRAND_X,
        target_dept_id=DEPT_BRAND_X,
    )

    class FakeRow:
        def __init__(self, dept_id, printer_id):
            self._data = (dept_id, printer_id)

        def __getitem__(self, idx):
            return self._data[idx]

    db = AsyncMock()
    call_count = [0]

    async def mock_execute(stmt):
        call_count[0] += 1
        if call_count[0] == 1:
            # 加载规则列表
            class R:
                def scalars(self):
                    class S:
                        def all(self):
                            return [rule_brand_x]
                    return S()
            return R()
        else:
            # fallback到DishDeptMapping
            class R2:
                def one_or_none(self):
                    return FakeRow(fallback_dept_id, fallback_printer_id)
            return R2()

    db.execute = mock_execute

    engine = DispatchRuleEngine()

    # 请求中 brand_id 是品牌Y（不是X），规则不匹配
    brand_y = _uid()
    dept_id, printer_id = await engine.resolve_dept(
        dish_id=DISH_SALAD,
        dish_category=None,
        brand_id=brand_y,
        channel="dine_in",
        order_time=datetime.now(timezone.utc),
        store_id=STORE_1,
        tenant_id=TENANT_A,
        db=db,
    )

    assert dept_id == fallback_dept_id, "无规则匹配时应fallback到DishDeptMapping"
    assert printer_id == fallback_printer_id


# ─── 测试 5: 规则优先级 ───

@pytest.mark.asyncio
async def test_higher_priority_rule_wins():
    """优先级高的规则应先于低优先级规则匹配。"""
    from services.dispatch_rule_engine import DispatchRuleEngine, _rule_cache

    _rule_cache.clear()

    dept_low = uuid.uuid4()
    dept_high = uuid.uuid4()

    # 两条规则都匹配，但 priority 不同
    rule_low = _make_rule(priority=5, match_channel="takeaway", target_dept_id=dept_low)
    rule_high = _make_rule(priority=100, match_channel="takeaway", target_dept_id=dept_high)

    # 规则按 priority DESC 返回（高优先级在前）
    db = _make_db_with_rules([rule_high, rule_low])
    engine = DispatchRuleEngine()

    order_time = datetime.now(timezone.utc)
    dept_id, _ = await engine.resolve_dept(
        dish_id=DISH_KUNG_PAO,
        dish_category=None,
        brand_id=None,
        channel="takeaway",
        order_time=order_time,
        store_id=STORE_1,
        tenant_id=TENANT_A,
        db=db,
    )

    assert dept_id == dept_high, "优先级100的规则应先于优先级5的规则匹配"


# ─── 测试 6: tenant_id隔离 ───

@pytest.mark.asyncio
async def test_tenant_isolation():
    """不同租户的规则列表互不影响（缓存按 tenant_id:store_id 隔离）。"""
    from services.dispatch_rule_engine import _cache_key, _rule_cache

    _rule_cache.clear()

    key_a = _cache_key(TENANT_A, STORE_1)
    key_b = _cache_key(TENANT_B, STORE_1)

    assert key_a != key_b, "不同租户的缓存key必须不同"

    # 模拟写入两个租户的缓存
    _rule_cache[key_a] = ([_make_rule(target_dept_id=DEPT_A)], float("inf"))
    _rule_cache[key_b] = ([_make_rule(target_dept_id=DEPT_B)], float("inf"))

    rules_a, _ = _rule_cache[key_a]
    rules_b, _ = _rule_cache[key_b]

    assert rules_a[0].target_dept_id == DEPT_A
    assert rules_b[0].target_dept_id == DEPT_B
    assert rules_a is not rules_b, "租户A和租户B的规则列表不能共享"


# ─── 测试 7: 缓存失效 ───

def test_invalidate_store_cache_clears_only_target():
    """缓存失效只影响目标门店，不影响其他门店。"""
    from services.dispatch_rule_engine import _cache_key, _rule_cache, invalidate_store_cache

    _rule_cache.clear()

    key_s1 = _cache_key(TENANT_A, STORE_1)
    key_s2 = _cache_key(TENANT_A, STORE_2)

    _rule_cache[key_s1] = ([], float("inf"))
    _rule_cache[key_s2] = ([], float("inf"))

    invalidate_store_cache(TENANT_A, STORE_1)

    assert key_s1 not in _rule_cache, "STORE_1 缓存应已失效"
    assert key_s2 in _rule_cache, "STORE_2 缓存不应受影响"


# ─── 测试 8: 通配条件（NULL字段） ───

def test_null_conditions_are_wildcards():
    """规则中 None 的匹配条件应视为通配，不阻止匹配。"""
    from services.dispatch_rule_engine import _rule_matches

    # 规则完全无匹配条件（全部NULL），应匹配所有情况
    rule = _make_rule(priority=1, target_dept_id=DEPT_A)

    order_time = datetime(2026, 3, 30, 8, 0, 0, tzinfo=timezone.utc)

    result = _rule_matches(
        rule,
        dish_id=uuid.uuid4(),
        dish_category="随意分类",
        brand_id=uuid.uuid4(),
        channel="delivery",
        order_time=order_time,
    )
    assert result is True, "无条件规则应匹配所有情况"


# ─── 测试 9: 渠道不匹配时跳过规则 ───

def test_channel_mismatch_skips_rule():
    """渠道条件不匹配时规则不应生效。"""
    from services.dispatch_rule_engine import _rule_matches

    rule = _make_rule(
        priority=10,
        match_channel="takeaway",
        target_dept_id=DEPT_B,
    )

    # 堂食订单，规则要求外卖
    result = _rule_matches(
        rule,
        dish_id=None,
        dish_category=None,
        brand_id=None,
        channel="dine_in",
        order_time=datetime.now(timezone.utc),
    )
    assert result is False, "堂食订单不应匹配外卖专属规则"


# ─── 测试 10: test_rule 管理员测试接口 ───

@pytest.mark.asyncio
async def test_rule_test_interface_matched():
    """test_rule 接口对匹配的规则返回 matched=True。"""
    from services.dispatch_rule_engine import DispatchRuleEngine

    engine = DispatchRuleEngine()

    rule = _make_rule(
        priority=10,
        match_channel="takeaway",
        target_dept_id=DEPT_B,
        target_printer_id=PRINTER_B,
    )

    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=rule)
    ))

    result = await engine.test_rule(
        rule_id=str(rule.id),
        test_context={"channel": "takeaway"},
        tenant_id=TENANT_A,
        db=db,
    )

    assert result["matched"] is True
    assert result["reason"] == "matched"
    assert result["target_dept_id"] == str(DEPT_B)


@pytest.mark.asyncio
async def test_rule_test_interface_not_matched():
    """test_rule 接口对不匹配的规则返回 matched=False。"""
    from services.dispatch_rule_engine import DispatchRuleEngine

    engine = DispatchRuleEngine()

    rule = _make_rule(
        priority=10,
        match_channel="takeaway",
        target_dept_id=DEPT_B,
    )

    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(
        scalar_one_or_none=MagicMock(return_value=rule)
    ))

    result = await engine.test_rule(
        rule_id=str(rule.id),
        test_context={"channel": "dine_in"},   # 堂食，不匹配外卖规则
        tenant_id=TENANT_A,
        db=db,
    )

    assert result["matched"] is False
    assert result["reason"] == "conditions_not_met"


# ─── 测试 11: 跨午夜时段匹配 ───

def test_cross_midnight_time_window():
    """时段匹配支持跨午夜（如 22:00-02:00）。"""
    from services.dispatch_rule_engine import _rule_matches

    dept_night = uuid.uuid4()
    rule = _make_rule(
        priority=10,
        match_time_start=time(22, 0),
        match_time_end=time(2, 0),
        target_dept_id=dept_night,
    )

    # 23:00 — 在跨午夜时段内
    t1 = datetime(2026, 3, 30, 23, 0, 0, tzinfo=timezone.utc)
    assert _rule_matches(rule, None, None, None, None, t1) is True

    # 01:30 — 在跨午夜时段内
    t2 = datetime(2026, 3, 30, 1, 30, 0, tzinfo=timezone.utc)
    assert _rule_matches(rule, None, None, None, None, t2) is True

    # 12:00 — 不在跨午夜时段内
    t3 = datetime(2026, 3, 30, 12, 0, 0, tzinfo=timezone.utc)
    assert _rule_matches(rule, None, None, None, None, t3) is False


# ─── 测试 12: 工作日类型匹配 ───

def test_weekday_rule_only_matches_weekday():
    """weekday 规则只在工作日匹配，周末不匹配。"""
    from services.dispatch_rule_engine import _rule_matches

    rule = _make_rule(
        priority=5,
        match_day_type="weekday",
        target_dept_id=DEPT_A,
    )

    # 2026-03-30 是周一（weekday）
    monday = datetime(2026, 3, 30, 12, 0, 0, tzinfo=timezone.utc)
    assert _rule_matches(rule, None, None, None, None, monday) is True

    # 2026-03-28 是周六（weekend）
    saturday = datetime(2026, 3, 28, 12, 0, 0, tzinfo=timezone.utc)
    assert _rule_matches(rule, None, None, None, None, saturday) is False
