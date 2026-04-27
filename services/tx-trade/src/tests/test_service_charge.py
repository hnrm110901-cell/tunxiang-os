"""服务费管理测试

覆盖场景：
1. 按人头计算服务费
2. 按包厢计算服务费
3. 按时间计算服务费（含免费时长）
4. 按金额满免服务费
5. 无配置时返回0
6. 门店配置设置与查询
7. 总部模板创建
8. 模板下发到多门店
9. 模板不存在时报错
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid

import pytest


def _uid() -> str:
    return str(uuid.uuid4())


TENANT_ID = _uid()


@pytest.fixture(autouse=True)
def _clear_stores():
    """每个测试前清空内存存储"""
    from services.service_charge import _charge_configs, _charge_records, _charge_templates

    _charge_configs.clear()
    _charge_templates.clear()
    _charge_records.clear()


@pytest.mark.asyncio
async def test_calculate_by_person():
    """按人头: 4人 × 500分 = 2000分"""
    from services.service_charge import calculate_service_charge, set_charge_config

    store_id = _uid()
    await set_charge_config(
        store_id,
        {
            "mode": "by_person",
            "charge_per_person_fen": 500,
            "enabled": True,
        },
        TENANT_ID,
    )

    result = await calculate_service_charge(
        order_id=_uid(),
        store_id=store_id,
        tenant_id=TENANT_ID,
        guest_count=4,
    )
    assert result["amount_fen"] == 2000
    assert result["mode"] == "by_person"
    assert result["waived"] is False


@pytest.mark.asyncio
async def test_calculate_by_table():
    """按包厢: 固定8800分"""
    from services.service_charge import calculate_service_charge, set_charge_config

    store_id = _uid()
    await set_charge_config(
        store_id,
        {
            "mode": "by_table",
            "room_charge_fen": 8800,
            "enabled": True,
        },
        TENANT_ID,
    )

    result = await calculate_service_charge(
        order_id=_uid(),
        store_id=store_id,
        tenant_id=TENANT_ID,
        room_type="VIP",
    )
    assert result["amount_fen"] == 8800
    assert result["mode"] == "by_table"


@pytest.mark.asyncio
async def test_calculate_by_time():
    """按时间: 150分钟，免费120分钟，每30分钟2000分 → 1单位 = 2000分"""
    from services.service_charge import calculate_service_charge, set_charge_config

    store_id = _uid()
    await set_charge_config(
        store_id,
        {
            "mode": "by_time",
            "time_unit_minutes": 30,
            "charge_per_unit_fen": 2000,
            "free_minutes": 120,
            "enabled": True,
        },
        TENANT_ID,
    )

    result = await calculate_service_charge(
        order_id=_uid(),
        store_id=store_id,
        tenant_id=TENANT_ID,
        duration_minutes=150,
    )
    assert result["amount_fen"] == 2000
    assert result["detail"]["billable_minutes"] == 30
    assert result["detail"]["units"] == 1


@pytest.mark.asyncio
async def test_calculate_by_amount_waived():
    """按金额: 满50000分免服务费"""
    from services.service_charge import calculate_service_charge, set_charge_config

    store_id = _uid()
    await set_charge_config(
        store_id,
        {
            "mode": "by_amount",
            "waive_above_fen": 50000,
            "base_charge_fen": 3000,
            "enabled": True,
        },
        TENANT_ID,
    )

    result = await calculate_service_charge(
        order_id=_uid(),
        store_id=store_id,
        tenant_id=TENANT_ID,
        order_amount_fen=60000,
    )
    assert result["amount_fen"] == 0
    assert result["waived"] is True


@pytest.mark.asyncio
async def test_calculate_no_config():
    """无配置时返回0"""
    from services.service_charge import calculate_service_charge

    result = await calculate_service_charge(
        order_id=_uid(),
        store_id=_uid(),
        tenant_id=TENANT_ID,
        guest_count=4,
    )
    assert result["amount_fen"] == 0
    assert result["charge_id"] is None


@pytest.mark.asyncio
async def test_set_and_get_config():
    """设置并查询门店配置"""
    from services.service_charge import get_charge_config, set_charge_config

    store_id = _uid()
    await set_charge_config(store_id, {"mode": "by_person", "charge_per_person_fen": 800, "enabled": True}, TENANT_ID)

    config = await get_charge_config(store_id, TENANT_ID)
    assert config is not None
    assert config["config"]["mode"] == "by_person"
    assert config["config"]["charge_per_person_fen"] == 800


@pytest.mark.asyncio
async def test_create_template():
    """创建总部模板"""
    from services.service_charge import create_charge_template

    result = await create_charge_template(
        name="标准包厢费",
        rules={"mode": "by_table", "room_charge_fen": 6600},
        tenant_id=TENANT_ID,
    )
    assert result["name"] == "标准包厢费"
    assert result["status"] == "active"
    assert "id" in result


@pytest.mark.asyncio
async def test_publish_template():
    """模板下发到多门店"""
    from services.service_charge import create_charge_template, get_charge_config, publish_template

    template = await create_charge_template(
        name="人头费模板",
        rules={"mode": "by_person", "charge_per_person_fen": 600},
        tenant_id=TENANT_ID,
    )
    store_ids = [_uid(), _uid()]
    result = await publish_template(template["id"], store_ids, TENANT_ID)
    assert len(result["published_stores"]) == 2

    for sid in store_ids:
        config = await get_charge_config(sid, TENANT_ID)
        assert config["config"]["mode"] == "by_person"
        assert config["config"]["enabled"] is True


@pytest.mark.asyncio
async def test_publish_template_not_found():
    """模板不存在时报错"""
    from services.service_charge import publish_template

    with pytest.raises(ValueError, match="Template not found"):
        await publish_template("nonexistent", [_uid()], TENANT_ID)
