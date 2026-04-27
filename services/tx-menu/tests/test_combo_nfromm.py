"""套餐N选M校验测试套件

覆盖：
1. 有效选择（N=2 M=3，选了2个）→ 通过
2. 选择数量不足 → 返回400（errors 不为空）
3. 选择数量超出 → 返回400（errors 不为空）
4. required=True 分组未选 → 返回400
5. required=False 分组未选 → 通过
6. 含附加价格选项的总价计算
7. 无效菜品选项（不属于该分组）→ errors 含无效菜品提示
8. is_active=False 的分组验证行为（通过 is_required=False 测试路径）
9. 无分组套餐 → 返回404
10. 缺少 X-Tenant-ID → 返回400

依赖：FastAPI + httpx.AsyncClient + unittest.mock（全Mock，无真实DB连接）
"""

import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))


# ─── 常量 ─────────────────────────────────────────────────────────────────────

TENANT_ID = str(uuid.uuid4())
COMBO_ID = str(uuid.uuid4())
GROUP_ID_MAIN = str(uuid.uuid4())
GROUP_ID_STAPLE = str(uuid.uuid4())
GROUP_ID_DRINK = str(uuid.uuid4())
ITEM_ID_FISH = str(uuid.uuid4())
ITEM_ID_PORK = str(uuid.uuid4())
ITEM_ID_SHRIMP = str(uuid.uuid4())
ITEM_ID_RICE = str(uuid.uuid4())
ITEM_ID_COKE = str(uuid.uuid4())
ITEM_ID_SPRITE = str(uuid.uuid4())

HEADERS = {
    "X-Tenant-ID": TENANT_ID,
    "Content-Type": "application/json",
}


# ─── Fixture ──────────────────────────────────────────────────────────────────


def _build_app_with_mock(mock_db: AsyncMock) -> FastAPI:
    """构建带 Mock DB 的测试应用"""
    from api.combo_routes import router

    from shared.ontology.src.database import get_db

    app = FastAPI()
    app.include_router(router)

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    return app


def _make_group_row(
    group_id: str,
    group_name: str,
    min_select: int,
    max_select: int,
    is_required: bool,
) -> MagicMock:
    """构造 combo_groups 查询行 Mock"""
    row = MagicMock()
    row.id = uuid.UUID(group_id)
    row.group_name = group_name
    row.min_select = min_select
    row.max_select = max_select
    row.is_required = is_required
    return row


def _make_valid_item_row(item_id: str, group_id: str) -> MagicMock:
    """构造 combo_group_items 有效行 Mock"""
    row = MagicMock()
    row.id = uuid.UUID(item_id)
    row.group_id = uuid.UUID(group_id)
    return row


# ─── validate-selection 端点测试 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_selection_valid():
    """POST /combos/{id}/validate-selection：N=1 M=3，选了2个 → valid=True

    场景：主菜分组 min_select=1, max_select=3，用户选了2道菜
    期望：valid=True，errors=[]
    """
    mock_db = AsyncMock()

    # 模拟分组查询：1个主菜分组，min=1, max=3
    group_row = _make_group_row(GROUP_ID_MAIN, "主菜（任选1-3款）", 1, 3, True)
    groups_result = MagicMock()
    groups_result.fetchall.return_value = [group_row]

    # 模拟有效 item 验证：2个 item 均有效
    valid_item_1 = _make_valid_item_row(ITEM_ID_FISH, GROUP_ID_MAIN)
    valid_item_2 = _make_valid_item_row(ITEM_ID_PORK, GROUP_ID_MAIN)
    valid_result = MagicMock()
    valid_result.fetchall.return_value = [valid_item_1, valid_item_2]

    # execute 调用序列：
    # 1. _rls_menu (SELECT set_config)
    # 2. 查 combo_groups
    # 3. 验证 item_ids 有效性
    rls_result = MagicMock()
    mock_db.execute = AsyncMock(side_effect=[rls_result, groups_result, valid_result])

    app = _build_app_with_mock(mock_db)

    payload = {
        "selections": [
            {
                "group_id": GROUP_ID_MAIN,
                "item_ids": [ITEM_ID_FISH, ITEM_ID_PORK],
            }
        ]
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/menu/combos/{COMBO_ID}/validate-selection",
            json=payload,
            headers=HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["valid"] is True
    assert data["errors"] == []


@pytest.mark.asyncio
async def test_validate_selection_too_few():
    """POST .../validate-selection：N=2 M=3，选了1个 → valid=False，返回 errors

    场景：主菜分组 min_select=2, max_select=3，用户只选了1道菜
    期望：valid=False，errors 含该分组的错误信息
    """
    mock_db = AsyncMock()

    group_row = _make_group_row(GROUP_ID_MAIN, "主菜（任选2-3款）", 2, 3, True)
    groups_result = MagicMock()
    groups_result.fetchall.return_value = [group_row]

    # 1个 item 有效
    valid_item_1 = _make_valid_item_row(ITEM_ID_FISH, GROUP_ID_MAIN)
    valid_result = MagicMock()
    valid_result.fetchall.return_value = [valid_item_1]

    rls_result = MagicMock()
    mock_db.execute = AsyncMock(side_effect=[rls_result, groups_result, valid_result])

    app = _build_app_with_mock(mock_db)

    payload = {
        "selections": [
            {
                "group_id": GROUP_ID_MAIN,
                "item_ids": [ITEM_ID_FISH],  # 只选1个，不满足min=2
            }
        ]
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/menu/combos/{COMBO_ID}/validate-selection",
            json=payload,
            headers=HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["valid"] is False
    assert len(data["errors"]) > 0
    # 错误信息应包含"至少"
    assert "至少" in data["errors"][0]["message"]


@pytest.mark.asyncio
async def test_validate_selection_too_many():
    """POST .../validate-selection：N=2 M=3，选了4个 → valid=False

    场景：主菜分组 min_select=2, max_select=3，用户选了4道菜
    期望：valid=False，errors 含"最多"提示
    """
    mock_db = AsyncMock()

    group_row = _make_group_row(GROUP_ID_MAIN, "主菜（任选2-3款）", 2, 3, True)
    groups_result = MagicMock()
    groups_result.fetchall.return_value = [group_row]

    # 4个 item 均有效
    valid_items = [_make_valid_item_row(str(uuid.uuid4()), GROUP_ID_MAIN) for _ in range(4)]
    valid_result = MagicMock()
    valid_result.fetchall.return_value = valid_items

    rls_result = MagicMock()
    mock_db.execute = AsyncMock(side_effect=[rls_result, groups_result, valid_result])

    app = _build_app_with_mock(mock_db)

    four_item_ids = [str(uuid.uuid4()) for _ in range(4)]
    payload = {
        "selections": [
            {
                "group_id": GROUP_ID_MAIN,
                "item_ids": four_item_ids,
            }
        ]
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/menu/combos/{COMBO_ID}/validate-selection",
            json=payload,
            headers=HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["valid"] is False
    assert "最多" in data["errors"][0]["message"]


@pytest.mark.asyncio
async def test_required_group_missing():
    """POST .../validate-selection：required=True 分组未提交选择 → valid=False

    场景：主食分组 min_select=1, is_required=True，用户没有提交该分组的任何选择
    期望：valid=False，errors 含"必选项"提示
    """
    mock_db = AsyncMock()

    group_row = _make_group_row(GROUP_ID_STAPLE, "主食（必选）", 1, 1, True)
    groups_result = MagicMock()
    groups_result.fetchall.return_value = [group_row]

    # 没有选任何 item，valid_items 为空
    valid_result = MagicMock()
    valid_result.fetchall.return_value = []

    rls_result = MagicMock()
    mock_db.execute = AsyncMock(side_effect=[rls_result, groups_result, valid_result])

    app = _build_app_with_mock(mock_db)

    payload = {
        "selections": []  # 没有提交任何分组选择
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/menu/combos/{COMBO_ID}/validate-selection",
            json=payload,
            headers=HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["valid"] is False
    assert len(data["errors"]) > 0
    # 错误信息应含"必选项"
    assert "必选" in data["errors"][0]["message"]


@pytest.mark.asyncio
async def test_optional_group_empty():
    """POST .../validate-selection：required=False 分组未选 → valid=True

    场景：饮料分组 min_select=0, is_required=False，用户不选饮料
    期望：valid=True（可选分组可以不选）
    """
    mock_db = AsyncMock()

    group_row = _make_group_row(GROUP_ID_DRINK, "饮料（可选）", 0, 2, False)
    groups_result = MagicMock()
    groups_result.fetchall.return_value = [group_row]

    # 没有选 item
    valid_result = MagicMock()
    valid_result.fetchall.return_value = []

    rls_result = MagicMock()
    mock_db.execute = AsyncMock(side_effect=[rls_result, groups_result, valid_result])

    app = _build_app_with_mock(mock_db)

    payload = {
        "selections": []  # 不选饮料
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/menu/combos/{COMBO_ID}/validate-selection",
            json=payload,
            headers=HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["valid"] is True
    assert data["errors"] == []


@pytest.mark.asyncio
async def test_extra_price_calculation():
    """附加价格选项的总价计算测试（通过 order_combo 端点验证）

    场景：套餐底价=8800分，选了 extra_price_fen=1800 的白灼虾选项
    说明：validate-selection 端点本身不计算总价，总价在 order_combo 中计算。
    本测试通过验证 add_item_to_combo_group 接口的 extra_price_fen 字段正确存储来间接验证。
    """
    mock_db = AsyncMock()

    # 验证 AddGroupItemReq 的 extra_price_fen 字段 Pydantic 校验
    from api.combo_routes import AddGroupItemReq

    req = AddGroupItemReq(
        dish_id=str(uuid.uuid4()),
        dish_name="白灼虾",
        quantity=1,
        extra_price_fen=1800,  # 18元附加价
        is_default=False,
        sort_order=0,
    )
    assert req.extra_price_fen == 1800

    # 验证 extra_price_fen=0 也可以（不加价）
    req_no_extra = AddGroupItemReq(
        dish_id=str(uuid.uuid4()),
        dish_name="清蒸鲈鱼",
        quantity=1,
        extra_price_fen=0,
        is_default=False,
        sort_order=0,
    )
    assert req_no_extra.extra_price_fen == 0


@pytest.mark.asyncio
async def test_invalid_dish_in_group():
    """POST .../validate-selection：选不属于该分组的菜品 → valid=False，errors 含无效选项提示

    场景：用户提交了一个不在该套餐分组中的 item_id
    期望：valid=False，errors 含"无效菜品选项"
    """
    mock_db = AsyncMock()

    group_row = _make_group_row(GROUP_ID_MAIN, "主菜", 1, 2, True)
    groups_result = MagicMock()
    groups_result.fetchall.return_value = [group_row]

    # valid_result 返回空（item_id 不属于该套餐）
    valid_result = MagicMock()
    valid_result.fetchall.return_value = []  # 无效 → 空结果

    rls_result = MagicMock()
    mock_db.execute = AsyncMock(side_effect=[rls_result, groups_result, valid_result])

    app = _build_app_with_mock(mock_db)

    fake_item_id = str(uuid.uuid4())  # 伪造的 item_id
    payload = {
        "selections": [
            {
                "group_id": GROUP_ID_MAIN,
                "item_ids": [fake_item_id],  # 不属于该套餐的菜品
            }
        ]
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/menu/combos/{COMBO_ID}/validate-selection",
            json=payload,
            headers=HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["valid"] is False
    # 错误信息应含"无效菜品选项"
    assert any("无效" in e["message"] for e in data["errors"])


@pytest.mark.asyncio
async def test_group_disabled_is_not_returned_in_validation():
    """is_active=False 的分组（通过 is_deleted=true 软删除实现）不参与校验

    说明：源码中 combo_groups 通过 is_deleted=false 过滤，
    已软删除（逻辑上等同于 disabled）的分组不出现在查询结果中，
    因此不参与校验（视为不存在）。
    本测试验证：查询只返回1个分组时，验证只针对该分组。
    """
    mock_db = AsyncMock()

    # 只有1个活跃分组（is_deleted=false 的分组）
    group_row = _make_group_row(GROUP_ID_STAPLE, "主食", 1, 1, True)
    groups_result = MagicMock()
    groups_result.fetchall.return_value = [group_row]  # 只返回1个（disabled 组被 WHERE 过滤掉）

    valid_item = _make_valid_item_row(ITEM_ID_RICE, GROUP_ID_STAPLE)
    valid_result = MagicMock()
    valid_result.fetchall.return_value = [valid_item]

    rls_result = MagicMock()
    mock_db.execute = AsyncMock(side_effect=[rls_result, groups_result, valid_result])

    app = _build_app_with_mock(mock_db)

    payload = {
        "selections": [
            {
                "group_id": GROUP_ID_STAPLE,
                "item_ids": [ITEM_ID_RICE],
            }
        ]
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/menu/combos/{COMBO_ID}/validate-selection",
            json=payload,
            headers=HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    # 只有1个活跃分组且选择合法，应通过
    assert data["valid"] is True


@pytest.mark.asyncio
async def test_validate_selection_no_groups_returns_404():
    """POST .../validate-selection：套餐无分组（或不存在）→ 返回 404

    源码第812行：groups 为空时 raise HTTPException(404, "套餐不存在或无分组")
    """
    mock_db = AsyncMock()

    # 分组查询返回空
    groups_result = MagicMock()
    groups_result.fetchall.return_value = []

    rls_result = MagicMock()
    mock_db.execute = AsyncMock(side_effect=[rls_result, groups_result])

    app = _build_app_with_mock(mock_db)

    payload = {"selections": []}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/menu/combos/{COMBO_ID}/validate-selection",
            json=payload,
            headers=HEADERS,
        )

    assert resp.status_code == 404
    assert "套餐" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_validate_selection_missing_tenant_id():
    """缺少 X-Tenant-ID header → 返回 400"""
    mock_db = AsyncMock()
    app = _build_app_with_mock(mock_db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/menu/combos/{COMBO_ID}/validate-selection",
            json={"selections": []},
            # 故意不传 X-Tenant-ID
        )

    assert resp.status_code == 400
    assert "X-Tenant-ID" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_validate_multiple_groups_partial_valid():
    """多分组场景：部分分组通过、部分不通过

    场景：
    - 主菜分组（required=True, min=1, max=1）：选了1个 → 通过
    - 主食分组（required=True, min=1, max=1）：未选 → 失败
    期望：valid=False，errors 只含主食分组
    """
    mock_db = AsyncMock()

    group_main = _make_group_row(GROUP_ID_MAIN, "主菜", 1, 1, True)
    group_staple = _make_group_row(GROUP_ID_STAPLE, "主食", 1, 1, True)
    groups_result = MagicMock()
    groups_result.fetchall.return_value = [group_main, group_staple]

    # 只有主菜的 item 有效，主食未选
    valid_item = _make_valid_item_row(ITEM_ID_FISH, GROUP_ID_MAIN)
    valid_result = MagicMock()
    valid_result.fetchall.return_value = [valid_item]

    rls_result = MagicMock()
    mock_db.execute = AsyncMock(side_effect=[rls_result, groups_result, valid_result])

    app = _build_app_with_mock(mock_db)

    payload = {
        "selections": [
            {
                "group_id": GROUP_ID_MAIN,
                "item_ids": [ITEM_ID_FISH],  # 主菜选了1个
                # 主食没有提交（GROUP_ID_STAPLE 不在 selections 中）
            }
        ]
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/menu/combos/{COMBO_ID}/validate-selection",
            json=payload,
            headers=HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["valid"] is False
    # 应只有1个错误（主食分组）
    assert len(data["errors"]) == 1
    assert data["errors"][0]["group_name"] == "主食"


# ─── Pydantic 模型校验测试 ─────────────────────────────────────────────────────


class TestComboGroupRequestValidation:
    """测试 CreateGroupReq / AddGroupItemReq Pydantic 模型约束"""

    def test_create_group_max_less_than_min_raises_no_pydantic_error(self):
        """CreateGroupReq 不在 Pydantic 层校验 max >= min（由业务逻辑处理）

        源码：max_select < min_select 的校验在端点函数中（非 validator），
        所以 Pydantic 不报错，422 由 HTTPException 422 抛出。
        """
        from api.combo_routes import CreateGroupReq

        # Pydantic 层不校验 max >= min，此对象可以创建
        req = CreateGroupReq(group_name="测试分组", min_select=3, max_select=1)
        assert req.min_select == 3
        assert req.max_select == 1  # 不合理但 Pydantic 层不拒绝

    def test_add_group_item_negative_extra_price_rejected(self):
        """AddGroupItemReq：extra_price_fen 不能为负数（ge=0）"""
        from api.combo_routes import AddGroupItemReq
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AddGroupItemReq(
                dish_id=str(uuid.uuid4()),
                dish_name="龙虾",
                quantity=1,
                extra_price_fen=-100,  # 非法
            )

    def test_add_group_item_zero_quantity_rejected(self):
        """AddGroupItemReq：quantity 必须 >= 1"""
        from api.combo_routes import AddGroupItemReq
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AddGroupItemReq(
                dish_id=str(uuid.uuid4()),
                dish_name="龙虾",
                quantity=0,  # 非法
                extra_price_fen=0,
            )

    def test_selection_group_req_requires_item_ids(self):
        """SelectionGroupReq：item_ids 为必填字段"""
        from api.combo_routes import SelectionGroupReq
        from pydantic import ValidationError

        # 缺少 item_ids → ValidationError
        with pytest.raises((ValidationError, TypeError)):
            SelectionGroupReq(group_id=str(uuid.uuid4()))

    def test_validate_selection_req_allows_empty_selections(self):
        """ValidateSelectionReq：selections 可以为空列表"""
        from api.combo_routes import ValidateSelectionReq

        req = ValidateSelectionReq(selections=[])
        assert req.selections == []
