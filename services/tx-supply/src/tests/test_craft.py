"""BOM 工艺管理单元测试 — 使用 mock AsyncSession

覆盖:
  - 工艺卡创建（多步骤 / 总时间计算）
  - 档口路由设置（替换旧路由）
  - 替代料规则设置
  - BOM 版本管理（合法转换 / 非法转换 / 模板不存在）
  - 多租户隔离
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

TENANT_A = str(uuid.uuid4())
TENANT_B = str(uuid.uuid4())
DISH_ID = str(uuid.uuid4())
DEPT_ID_1 = str(uuid.uuid4())
DEPT_ID_2 = str(uuid.uuid4())
INGREDIENT_1 = str(uuid.uuid4())
SUBSTITUTE_1 = str(uuid.uuid4())
SUBSTITUTE_2 = str(uuid.uuid4())
TEMPLATE_ID = str(uuid.uuid4())


def _mock_session():
    """创建 mock AsyncSession"""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    return session


def _make_mapping(data: dict):
    """创建模拟 SQLAlchemy mapping 行"""
    m = MagicMock()
    m.__getitem__ = lambda self, key: data[key]
    m.get = lambda key, default=None: data.get(key, default)
    return m


# ─── 工艺卡创建 ───


@pytest.mark.asyncio
async def test_create_craft_card():
    """create_craft_card 应插入卡片和步骤，返回正确结构"""
    from services.bom_craft import create_craft_card

    session = _mock_session()
    session.execute.return_value = MagicMock()

    result = await create_craft_card(
        dish_id=DISH_ID,
        steps=[
            {"seq": 1, "name": "焯水", "duration_seconds": 120, "temperature": 100.0, "tool": "汤锅"},
            {"seq": 2, "name": "爆炒", "duration_seconds": 180, "temperature": 220.0, "tool": "炒锅"},
            {"seq": 3, "name": "装盘", "duration_seconds": 30},
        ],
        tenant_id=TENANT_A,
        db=session,
    )

    assert result["dish_id"] == DISH_ID
    assert result["total_duration_seconds"] == 330
    assert len(result["steps"]) == 3
    assert result["steps"][0]["name"] == "焯水"
    assert result["steps"][1]["temperature"] == 220.0
    # set_config(1) + card insert(1) + 3 step inserts + flush
    assert session.execute.call_count >= 5


@pytest.mark.asyncio
async def test_create_craft_card_single_step():
    """create_craft_card 单步骤也能正常工作"""
    from services.bom_craft import create_craft_card

    session = _mock_session()
    session.execute.return_value = MagicMock()

    result = await create_craft_card(
        dish_id=DISH_ID,
        steps=[{"seq": 1, "name": "拌匀", "duration_seconds": 60}],
        tenant_id=TENANT_A,
        db=session,
    )

    assert len(result["steps"]) == 1
    assert result["total_duration_seconds"] == 60


# ─── 档口路由 ───


@pytest.mark.asyncio
async def test_set_dept_routing():
    """set_dept_routing 应软删旧路由并插入新路由"""
    from services.bom_craft import set_dept_routing

    session = _mock_session()
    session.execute.return_value = MagicMock()

    result = await set_dept_routing(
        dish_id=DISH_ID,
        dept_sequence=[
            {"seq": 1, "dept_id": DEPT_ID_1, "process_name": "初加工", "estimated_seconds": 300},
            {"seq": 2, "dept_id": DEPT_ID_2, "process_name": "热炒", "estimated_seconds": 180},
        ],
        tenant_id=TENANT_A,
        db=session,
    )

    assert result["dish_id"] == DISH_ID
    assert len(result["routes"]) == 2
    assert result["routes"][0]["dept_id"] == DEPT_ID_1
    assert result["routes"][1]["process_name"] == "热炒"
    # set_config(1) + soft delete(1) + 2 inserts + flush
    assert session.execute.call_count >= 4


# ─── 替代料规则 ───


@pytest.mark.asyncio
async def test_set_substitute_rules():
    """set_substitute_rules 应建立替代关系"""
    from services.bom_craft import set_substitute_rules

    session = _mock_session()
    session.execute.return_value = MagicMock()

    result = await set_substitute_rules(
        ingredient_id=INGREDIENT_1,
        substitutes=[
            {"substitute_id": SUBSTITUTE_1, "ratio": 1.0, "priority": 1, "conditions": "缺货时"},
            {"substitute_id": SUBSTITUTE_2, "ratio": 0.8, "priority": 2},
        ],
        tenant_id=TENANT_A,
        db=session,
    )

    assert result["ingredient_id"] == INGREDIENT_1
    assert len(result["substitutes"]) == 2
    assert result["substitutes"][0]["ratio"] == 1.0
    assert result["substitutes"][1]["ratio"] == 0.8


# ─── BOM 版本管理 — 合法转换 ───


@pytest.mark.asyncio
async def test_manage_bom_version_draft_to_review():
    """manage_bom_version: draft -> review 合法"""
    from services.bom_craft import manage_bom_version

    session = _mock_session()

    set_config_result = MagicMock()

    row_data = {
        "id": uuid.UUID(TEMPLATE_ID),
        "dish_id": uuid.UUID(DISH_ID),
        "version": "v1",
        "status": "draft",
    }
    query_result = MagicMock()
    query_mappings = MagicMock()
    query_mappings.first.return_value = _make_mapping(row_data)
    query_result.mappings.return_value = query_mappings

    update_result = MagicMock()

    session.execute.side_effect = [set_config_result, query_result, update_result]

    result = await manage_bom_version(
        template_id=TEMPLATE_ID,
        action="review",
        tenant_id=TENANT_A,
        db=session,
    )

    assert result["ok"] is True
    assert result["current_status"] == "review"
    assert result["previous_status"] == "draft"


# ─── BOM 版本管理 — 非法转换 ───


@pytest.mark.asyncio
async def test_manage_bom_version_invalid_transition():
    """manage_bom_version: draft -> archived 非法"""
    from services.bom_craft import manage_bom_version

    session = _mock_session()

    set_config_result = MagicMock()

    row_data = {
        "id": uuid.UUID(TEMPLATE_ID),
        "dish_id": uuid.UUID(DISH_ID),
        "version": "v1",
        "status": "draft",
    }
    query_result = MagicMock()
    query_mappings = MagicMock()
    query_mappings.first.return_value = _make_mapping(row_data)
    query_result.mappings.return_value = query_mappings

    session.execute.side_effect = [set_config_result, query_result]

    result = await manage_bom_version(
        template_id=TEMPLATE_ID,
        action="archived",
        tenant_id=TENANT_A,
        db=session,
    )

    assert result["ok"] is False
    assert "Cannot transition" in result["error"]


# ─── BOM 版本管理 — 模板不存在 ───


@pytest.mark.asyncio
async def test_manage_bom_version_not_found():
    """manage_bom_version: 模板不存在返回错误"""
    from services.bom_craft import manage_bom_version

    session = _mock_session()

    set_config_result = MagicMock()
    query_result = MagicMock()
    query_mappings = MagicMock()
    query_mappings.first.return_value = None
    query_result.mappings.return_value = query_mappings

    session.execute.side_effect = [set_config_result, query_result]

    result = await manage_bom_version(
        template_id=str(uuid.uuid4()),
        action="review",
        tenant_id=TENANT_A,
        db=session,
    )

    assert result["ok"] is False
    assert "not found" in result["error"]


# ─── 多租户隔离 ───


@pytest.mark.asyncio
async def test_craft_tenant_isolation():
    """不同 tenant_id 的工艺卡操作应使用各自 tenant 上下文"""
    from services.bom_craft import create_craft_card

    session_a = _mock_session()
    session_b = _mock_session()
    session_a.execute.return_value = MagicMock()
    session_b.execute.return_value = MagicMock()

    await create_craft_card(
        dish_id=DISH_ID,
        steps=[{"seq": 1, "name": "煮", "duration_seconds": 60}],
        tenant_id=TENANT_A,
        db=session_a,
    )

    await create_craft_card(
        dish_id=DISH_ID,
        steps=[{"seq": 1, "name": "煮", "duration_seconds": 60}],
        tenant_id=TENANT_B,
        db=session_b,
    )

    # 检查各自的 set_config 调用使用了不同 tenant_id
    call_a = session_a.execute.call_args_list[0]
    call_b = session_b.execute.call_args_list[0]

    assert call_a[0][1]["tid"] == TENANT_A
    assert call_b[0][1]["tid"] == TENANT_B
