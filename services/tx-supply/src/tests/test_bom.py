"""BOM 管理服务单元测试 — 使用 mock AsyncSession

覆盖:
  - BOM 创建/查询/更新/删除
  - 理论成本计算（正常/无BOM/原料无价格）
  - 版本激活
  - 多租户隔离
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


TENANT_A = str(uuid.uuid4())
TENANT_B = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())
DISH_ID = str(uuid.uuid4())
INGREDIENT_1 = str(uuid.uuid4())
INGREDIENT_2 = str(uuid.uuid4())


def _mock_session():
    """创建 mock AsyncSession"""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


def _make_mapping(data: dict):
    """创建模拟 SQLAlchemy mapping 行"""
    m = MagicMock()
    m.__getitem__ = lambda self, key: data[key]
    m.get = lambda key, default=None: data.get(key, default)
    return m


# ─── BOM 创建 ───


@pytest.mark.asyncio
async def test_create_bom_template():
    """create_bom_template 应插入模板和明细, 返回正确结构"""
    from services.bom_service import BOMService

    session = _mock_session()
    # set_config + 1 template insert + 2 item inserts + flush
    session.execute.return_value = MagicMock()

    svc = BOMService(session, TENANT_A)
    result = await svc.create_bom_template(
        dish_id=DISH_ID,
        items=[
            {"ingredient_id": INGREDIENT_1, "standard_qty": 0.5, "unit": "kg", "unit_cost_fen": 3500},
            {"ingredient_id": INGREDIENT_2, "standard_qty": 2.0, "unit": "个", "unit_cost_fen": 200},
        ],
        store_id=STORE_ID,
        version="v1",
    )

    assert result["dish_id"] == DISH_ID
    assert result["version"] == "v1"
    assert result["is_active"] is False
    assert len(result["items"]) == 2
    assert result["items"][0]["ingredient_id"] == INGREDIENT_1
    # set_config(1) + template insert(1) + 2 item inserts + flush
    assert session.execute.call_count >= 4


@pytest.mark.asyncio
async def test_create_bom_template_with_defaults():
    """create_bom_template 使用默认值"""
    from services.bom_service import BOMService

    session = _mock_session()
    session.execute.return_value = MagicMock()

    svc = BOMService(session, TENANT_A)
    result = await svc.create_bom_template(
        dish_id=DISH_ID,
        items=[{"ingredient_id": INGREDIENT_1, "standard_qty": 1.0, "unit": "kg"}],
        store_id=STORE_ID,
    )

    assert result["version"] == "v1"
    assert result["yield_rate"] == 1.0


# ─── BOM 查询 ───


@pytest.mark.asyncio
async def test_get_bom_template_found():
    """get_bom_template 找到模板时返回完整数据"""
    from services.bom_service import BOMService

    session = _mock_session()
    now = datetime.now(timezone.utc)
    template_id = str(uuid.uuid4())
    template_uuid = uuid.UUID(template_id)

    template_row = {
        "id": template_uuid,
        "store_id": uuid.UUID(STORE_ID),
        "dish_id": uuid.UUID(DISH_ID),
        "version": "v1",
        "effective_date": now,
        "expiry_date": None,
        "yield_rate": 0.9,
        "standard_portion": 200.0,
        "prep_time_minutes": 15,
        "is_active": True,
        "is_approved": False,
        "approved_by": None,
        "approved_at": None,
        "scope": "store",
        "notes": "测试BOM",
        "created_by": "admin",
        "created_at": now,
        "updated_at": now,
    }

    item_row = {
        "id": uuid.uuid4(),
        "ingredient_id": uuid.UUID(INGREDIENT_1),
        "standard_qty": 0.5,
        "raw_qty": 0.6,
        "unit": "kg",
        "unit_cost_fen": 3500,
        "is_key_ingredient": True,
        "is_optional": False,
        "waste_factor": 0.1,
        "prep_notes": "切丁",
        "item_action": "ADD",
    }

    # Mock responses: set_config, template query, items query
    set_config_result = MagicMock()

    template_result = MagicMock()
    template_mappings = MagicMock()
    template_mappings.first.return_value = _make_mapping(template_row)
    template_result.mappings.return_value = template_mappings

    items_result = MagicMock()
    items_mappings = MagicMock()
    items_mappings.all.return_value = [_make_mapping(item_row)]
    items_result.mappings.return_value = items_mappings

    session.execute.side_effect = [set_config_result, template_result, items_result]

    svc = BOMService(session, TENANT_A)
    result = await svc.get_bom_template(template_id)

    assert result is not None
    assert result["id"] == template_id
    assert result["version"] == "v1"
    assert result["is_active"] is True
    assert len(result["items"]) == 1
    assert result["items"][0]["standard_qty"] == 0.5


@pytest.mark.asyncio
async def test_get_bom_template_not_found():
    """get_bom_template 找不到模板时返回 None"""
    from services.bom_service import BOMService

    session = _mock_session()

    set_config_result = MagicMock()
    template_result = MagicMock()
    template_mappings = MagicMock()
    template_mappings.first.return_value = None
    template_result.mappings.return_value = template_mappings

    session.execute.side_effect = [set_config_result, template_result]

    svc = BOMService(session, TENANT_A)
    result = await svc.get_bom_template(str(uuid.uuid4()))

    assert result is None


# ─── BOM 删除 ───


@pytest.mark.asyncio
async def test_delete_bom_template():
    """delete_bom_template 应软删除模板及明细"""
    from services.bom_service import BOMService

    session = _mock_session()
    template_id = str(uuid.uuid4())

    set_config_result = MagicMock()
    check_result = MagicMock()
    check_result.scalar_one_or_none.return_value = uuid.UUID(template_id)
    update_template_result = MagicMock()
    update_items_result = MagicMock()

    session.execute.side_effect = [
        set_config_result, check_result,
        update_template_result, update_items_result,
    ]

    svc = BOMService(session, TENANT_A)
    result = await svc.delete_bom_template(template_id)

    assert result is True


@pytest.mark.asyncio
async def test_delete_bom_template_not_found():
    """delete_bom_template 模板不存在时返回 False"""
    from services.bom_service import BOMService

    session = _mock_session()

    set_config_result = MagicMock()
    check_result = MagicMock()
    check_result.scalar_one_or_none.return_value = None

    session.execute.side_effect = [set_config_result, check_result]

    svc = BOMService(session, TENANT_A)
    result = await svc.delete_bom_template(str(uuid.uuid4()))

    assert result is False


# ─── 版本激活 ───


@pytest.mark.asyncio
async def test_activate_version():
    """activate_version 应停用同菜品其他版本, 激活指定版本"""
    from services.bom_service import BOMService

    session = _mock_session()
    template_id = str(uuid.uuid4())

    set_config_result = MagicMock()

    row_data = {
        "id": uuid.UUID(template_id),
        "dish_id": uuid.UUID(DISH_ID),
        "version": "v2",
        "store_id": uuid.UUID(STORE_ID),
    }
    query_result = MagicMock()
    query_mappings = MagicMock()
    query_mappings.first.return_value = _make_mapping(row_data)
    query_result.mappings.return_value = query_mappings

    deactivate_result = MagicMock()
    activate_result = MagicMock()

    session.execute.side_effect = [
        set_config_result, query_result,
        deactivate_result, activate_result,
    ]

    svc = BOMService(session, TENANT_A)
    result = await svc.activate_version(template_id)

    assert result is not None
    assert result["is_active"] is True
    assert result["version"] == "v2"
    assert result["dish_id"] == DISH_ID


# ─── 理论成本计算 ───


@pytest.mark.asyncio
async def test_calculate_dish_cost_normal():
    """calculate_dish_cost 正常计算: 2个原料, yield_rate=0.9"""
    from services.cost_calculator import CostCalculator

    session = _mock_session()

    set_config_result = MagicMock()

    bom_id = uuid.uuid4()
    bom_result = MagicMock()
    bom_mappings = MagicMock()
    bom_mappings.first.return_value = _make_mapping({
        "id": bom_id,
        "version": "v1",
        "yield_rate": 0.9,
    })
    bom_result.mappings.return_value = bom_mappings

    items_data = [
        _make_mapping({
            "ingredient_id": uuid.UUID(INGREDIENT_1),
            "standard_qty": 0.5,
            "unit": "kg",
            "bom_unit_cost_fen": 3500,
            "waste_factor": 0.1,
            "ingredient_unit_price_fen": 3000,
        }),
        _make_mapping({
            "ingredient_id": uuid.UUID(INGREDIENT_2),
            "standard_qty": 2.0,
            "unit": "个",
            "bom_unit_cost_fen": 200,
            "waste_factor": 0,
            "ingredient_unit_price_fen": 180,
        }),
    ]
    items_result = MagicMock()
    items_mappings = MagicMock()
    items_mappings.all.return_value = items_data
    items_result.mappings.return_value = items_mappings

    session.execute.side_effect = [set_config_result, bom_result, items_result]

    calc = CostCalculator(session, TENANT_A)
    result = await calc.calculate_dish_cost(DISH_ID)

    assert result["dish_id"] == DISH_ID
    assert result["bom_version"] == "v1"
    assert result["yield_rate"] == 0.9
    # 原料1: 0.5 * 1.1 * 3500 = 1925
    # 原料2: 2.0 * 1.0 * 200 = 400
    # 合计: 2325 / 0.9 = 2583 (四舍五入)
    assert result["theoretical_cost_fen"] == 2583
    assert len(result["items"]) == 2


@pytest.mark.asyncio
async def test_calculate_dish_cost_no_bom():
    """calculate_dish_cost 无激活BOM时返回零成本"""
    from services.cost_calculator import CostCalculator

    session = _mock_session()

    set_config_result = MagicMock()
    bom_result = MagicMock()
    bom_mappings = MagicMock()
    bom_mappings.first.return_value = None
    bom_result.mappings.return_value = bom_mappings

    session.execute.side_effect = [set_config_result, bom_result]

    calc = CostCalculator(session, TENANT_A)
    result = await calc.calculate_dish_cost(DISH_ID)

    assert result["bom_template_id"] is None
    assert result["theoretical_cost_fen"] == 0
    assert result["items"] == []


@pytest.mark.asyncio
async def test_calculate_dish_cost_no_price():
    """calculate_dish_cost 原料无价格时该行成本为0"""
    from services.cost_calculator import CostCalculator

    session = _mock_session()

    set_config_result = MagicMock()

    bom_id = uuid.uuid4()
    bom_result = MagicMock()
    bom_mappings = MagicMock()
    bom_mappings.first.return_value = _make_mapping({
        "id": bom_id,
        "version": "v1",
        "yield_rate": 1.0,
    })
    bom_result.mappings.return_value = bom_mappings

    items_data = [
        _make_mapping({
            "ingredient_id": uuid.UUID(INGREDIENT_1),
            "standard_qty": 1.0,
            "unit": "kg",
            "bom_unit_cost_fen": None,
            "waste_factor": 0,
            "ingredient_unit_price_fen": None,
        }),
    ]
    items_result = MagicMock()
    items_mappings = MagicMock()
    items_mappings.all.return_value = items_data
    items_result.mappings.return_value = items_mappings

    session.execute.side_effect = [set_config_result, bom_result, items_result]

    calc = CostCalculator(session, TENANT_A)
    result = await calc.calculate_dish_cost(DISH_ID)

    assert result["theoretical_cost_fen"] == 0
    assert result["items"][0]["line_cost_fen"] == 0
    assert result["items"][0]["unit_cost_fen"] is None


# ─── 多租户隔离 ───


@pytest.mark.asyncio
async def test_tenant_isolation():
    """不同 tenant_id 创建的 BOMService 应使用不同的 tenant 上下文"""
    from services.bom_service import BOMService

    session_a = _mock_session()
    session_b = _mock_session()

    svc_a = BOMService(session_a, TENANT_A)
    svc_b = BOMService(session_b, TENANT_B)

    assert svc_a.tenant_id == TENANT_A
    assert svc_b.tenant_id == TENANT_B
    assert svc_a._tenant_uuid != svc_b._tenant_uuid

    # 验证 _set_tenant 使用各自的 tenant_id
    await svc_a._set_tenant()
    await svc_b._set_tenant()

    # 检查 set_config 调用参数
    call_a = session_a.execute.call_args
    call_b = session_b.execute.call_args

    assert call_a[0][1]["tid"] == TENANT_A
    assert call_b[0][1]["tid"] == TENANT_B


# ─── 订单批量成本 ───


@pytest.mark.asyncio
async def test_calculate_order_cost():
    """calculate_order_cost 应汇总多个菜品的理论成本"""
    from services.cost_calculator import CostCalculator

    session = _mock_session()

    calc = CostCalculator(session, TENANT_A)

    # Mock calculate_dish_cost 的返回
    async def mock_dish_cost(dish_id):
        return {
            "dish_id": dish_id,
            "bom_template_id": str(uuid.uuid4()),
            "bom_version": "v1",
            "yield_rate": 1.0,
            "theoretical_cost_fen": 1000,
            "items": [],
        }

    with patch.object(calc, "calculate_dish_cost", side_effect=mock_dish_cost):
        result = await calc.calculate_order_cost([
            {"dish_id": DISH_ID, "quantity": 3},
            {"dish_id": str(uuid.uuid4()), "quantity": 2},
        ])

    assert result["total_theoretical_cost_fen"] == 5000
    assert len(result["per_item"]) == 2
    assert result["per_item"][0]["subtotal_cost_fen"] == 3000
    assert result["per_item"][1]["subtotal_cost_fen"] == 2000
