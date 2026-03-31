"""厨房路由系统集成测试

测试场景：
1. 创建出品部门配置正确持久化
2. 菜品-档口映射设置和查询
3. 批量映射设置
4. 订单包含2个档口的菜品，正确创建2个KDS Task
5. 未配置档口的菜品不影响流程（走默认档口）
6. KDS设备按 dept_id 只看到自己档口的任务
7. 重复设置主档口自动降级旧映射
8. 删除档口时有菜品映射报错（非force模式）
9. force=True 删除档口同时软删除菜品映射
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

# ─── 测试工具 ───

def _uid() -> uuid.UUID:
    return uuid.uuid4()


def _uid_str() -> str:
    return str(uuid.uuid4())


TENANT_ID = str(uuid.uuid4())
BRAND_ID = str(uuid.uuid4())
STORE_ID = str(uuid.uuid4())

DEPT_COLD = str(uuid.uuid4())    # 凉菜档
DEPT_HOT = str(uuid.uuid4())     # 热菜档
DEPT_NOODLE = str(uuid.uuid4())  # 面点档

DISH_CUCUMBER = str(uuid.uuid4())   # 拍黄瓜（凉菜档）
DISH_PORK = str(uuid.uuid4())       # 红烧肉（热菜档）
DISH_NOODLE = str(uuid.uuid4())     # 刀削面（面点档）
DISH_UNKNOWN = str(uuid.uuid4())    # 未配置档口的菜品


# ─── 出品部门 CRUD 测试 ───

class TestProductionDeptCRUD:
    """出品部门配置管理测试"""

    @pytest.mark.asyncio
    async def test_create_dept_success(self):
        """创建档口成功，字段正确持久化"""
        from services.production_dept_service import create_production_dept

        # 模拟 DB
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None)  # 没有重复的 dept_code
        ))
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        dept = MagicMock()
        dept.id = uuid.UUID(DEPT_COLD)
        dept.dept_name = "凉菜档"
        dept.dept_code = "cold"
        dept.printer_address = "192.168.1.101:9100"
        dept.kds_device_id = "kds-cold-001"
        dept.display_color = "blue"
        dept.is_active = True

        with patch(
            "services.production_dept_service.ProductionDept",
            return_value=dept,
        ):
            mock_db.refresh.side_effect = lambda d: None
            result = await create_production_dept(
                tenant_id=TENANT_ID,
                brand_id=BRAND_ID,
                store_id=STORE_ID,
                dept_name="凉菜档",
                dept_code="cold",
                printer_address="192.168.1.101:9100",
                kds_device_id="kds-cold-001",
                display_color="blue",
                db=mock_db,
            )

        # 验证 db.add 被调用
        mock_db.add.assert_called_once()
        mock_db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_dept_duplicate_code_raises(self):
        """dept_code 重复时抛出 ValueError"""
        from services.production_dept_service import create_production_dept

        existing_dept = MagicMock()
        existing_dept.id = uuid.UUID(DEPT_COLD)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=existing_dept)
        ))

        with pytest.raises(ValueError, match="已存在"):
            await create_production_dept(
                tenant_id=TENANT_ID,
                brand_id=BRAND_ID,
                store_id=STORE_ID,
                dept_name="凉菜档",
                dept_code="cold",
                db=mock_db,
            )

    @pytest.mark.asyncio
    async def test_delete_dept_with_mappings_raises(self):
        """有菜品映射时删除档口抛出 RuntimeError"""
        from services.production_dept_service import delete_production_dept

        existing_dept = MagicMock()
        existing_dept.id = uuid.UUID(DEPT_COLD)
        existing_dept.is_deleted = False

        # 第一次查档口，第二次查映射数量
        mock_db = AsyncMock()
        execute_results = [
            MagicMock(scalar_one_or_none=MagicMock(return_value=existing_dept)),
            MagicMock(scalar=MagicMock(return_value=5)),  # 5条映射
        ]
        mock_db.execute = AsyncMock(side_effect=execute_results)

        with pytest.raises(RuntimeError, match="5 条菜品映射"):
            await delete_production_dept(DEPT_COLD, TENANT_ID, mock_db, force=False)

    @pytest.mark.asyncio
    async def test_delete_dept_force_unbinds_dishes(self):
        """force=True 时软删除所有菜品映射后再删档口"""
        from services.production_dept_service import delete_production_dept

        existing_dept = MagicMock()
        existing_dept.id = uuid.UUID(DEPT_COLD)
        existing_dept.is_deleted = False

        # 第一次查档口，第二次查映射数量，第三次执行 update
        mock_db = AsyncMock()
        execute_results = [
            MagicMock(scalar_one_or_none=MagicMock(return_value=existing_dept)),
            MagicMock(scalar=MagicMock(return_value=3)),  # 3条映射
            MagicMock(),  # update 执行结果
        ]
        mock_db.execute = AsyncMock(side_effect=execute_results)
        mock_db.flush = AsyncMock()

        await delete_production_dept(DEPT_COLD, TENANT_ID, mock_db, force=True)

        # 验证 update 被调用（解绑菜品）
        assert mock_db.execute.call_count == 3
        # 档口被软删除
        assert existing_dept.is_deleted is True


# ─── 菜品-档口映射测试 ───

class TestDishDeptMapping:
    """菜品-档口映射测试"""

    @pytest.mark.asyncio
    async def test_set_dish_mapping_creates_new(self):
        """为菜品设置新档口映射"""
        from services.production_dept_service import set_dish_dept_mapping

        dept = MagicMock()
        dept.id = uuid.UUID(DEPT_COLD)

        mock_db = AsyncMock()
        # 第一次查档口（exists），第二次降级旧主档口（update），第三次查existing映射（None）
        execute_seq = [
            MagicMock(scalar_one_or_none=MagicMock(return_value=dept)),  # get_production_dept_by_id
            MagicMock(),   # update is_primary=False for other mappings
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # 无已有映射
        ]
        mock_db.execute = AsyncMock(side_effect=execute_seq)
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        new_mapping = MagicMock()
        new_mapping.id = uuid.uuid4()
        new_mapping.dish_id = uuid.UUID(DISH_CUCUMBER)
        new_mapping.production_dept_id = uuid.UUID(DEPT_COLD)
        new_mapping.is_primary = True

        with patch(
            "services.production_dept_service.DishDeptMapping",
            return_value=new_mapping,
        ):
            result = await set_dish_dept_mapping(
                tenant_id=TENANT_ID,
                dish_id=DISH_CUCUMBER,
                dept_id=DEPT_COLD,
                db=mock_db,
                is_primary=True,
            )

        mock_db.add.assert_called_once_with(new_mapping)
        mock_db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_primary_demotes_existing_primary(self):
        """设置新主档口时，旧主档口映射自动降级"""
        from services.production_dept_service import set_dish_dept_mapping

        dept = MagicMock()
        dept.id = uuid.UUID(DEPT_HOT)

        existing_mapping = MagicMock()
        existing_mapping.is_primary = True

        mock_db = AsyncMock()
        execute_seq = [
            MagicMock(scalar_one_or_none=MagicMock(return_value=dept)),
            MagicMock(),   # update 降级旧主档口
            MagicMock(scalar_one_or_none=MagicMock(return_value=existing_mapping)),
        ]
        mock_db.execute = AsyncMock(side_effect=execute_seq)
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        await set_dish_dept_mapping(
            tenant_id=TENANT_ID,
            dish_id=DISH_PORK,
            dept_id=DEPT_HOT,
            db=mock_db,
            is_primary=True,
        )

        # 验证 update（降级）被执行
        assert mock_db.execute.call_count >= 2

    @pytest.mark.asyncio
    async def test_batch_set_mappings(self):
        """批量设置菜品映射"""
        from services.production_dept_service import batch_set_dish_dept_mappings

        mappings_input = [
            {"dish_id": DISH_CUCUMBER, "dept_id": DEPT_COLD, "is_primary": True},
            {"dish_id": DISH_PORK, "dept_id": DEPT_HOT, "is_primary": True},
            {"dish_id": DISH_NOODLE, "dept_id": DEPT_NOODLE, "is_primary": True},
        ]

        call_count = 0

        async def mock_set_mapping(tenant_id, dish_id, dept_id, db, is_primary, printer_id=None):
            nonlocal call_count
            call_count += 1
            m = MagicMock()
            m.dish_id = uuid.UUID(dish_id)
            return m

        with patch(
            "services.production_dept_service.set_dish_dept_mapping",
            side_effect=mock_set_mapping,
        ):
            mock_db = AsyncMock()
            results = await batch_set_dish_dept_mappings(
                tenant_id=TENANT_ID,
                mappings=mappings_input,
                db=mock_db,
            )

        assert len(results) == 3
        assert call_count == 3


# ─── KDS 分单路由测试 ───

class TestKdsDispatchRouting:
    """KDS 分单路由核心逻辑测试"""

    @pytest.mark.asyncio
    async def test_two_dept_order_creates_two_kds_tasks(self):
        """订单含2个档口的菜品，应创建2个独立KDS任务组"""
        from services.kds_dispatch import dispatch_order_to_kds

        order_id = _uid_str()
        order_items = [
            {
                "dish_id": DISH_CUCUMBER,
                "item_name": "拍黄瓜",
                "quantity": 1,
                "order_item_id": _uid_str(),
                "notes": "",
            },
            {
                "dish_id": DISH_PORK,
                "item_name": "红烧肉",
                "quantity": 2,
                "order_item_id": _uid_str(),
                "notes": "少盐",
            },
        ]

        # DishDeptMapping 查询：黄瓜→凉菜档，红烧肉→热菜档
        cold_dept_uuid = uuid.UUID(DEPT_COLD)
        hot_dept_uuid = uuid.UUID(DEPT_HOT)

        mapping_rows = [
            MagicMock(),
            MagicMock(),
        ]
        mapping_rows[0].__iter__ = lambda s: iter([uuid.UUID(DISH_CUCUMBER), cold_dept_uuid])
        mapping_rows[1].__iter__ = lambda s: iter([uuid.UUID(DISH_PORK), hot_dept_uuid])

        cold_dept = MagicMock()
        cold_dept.id = cold_dept_uuid
        cold_dept.dept_name = "凉菜档"
        cold_dept.dept_code = "cold"
        cold_dept.printer_address = "192.168.1.101:9100"
        cold_dept.sort_order = 0
        cold_dept.kds_device_id = "kds-cold-001"
        cold_dept.is_deleted = False

        hot_dept = MagicMock()
        hot_dept.id = hot_dept_uuid
        hot_dept.dept_name = "热菜档"
        hot_dept.dept_code = "hot"
        hot_dept.printer_address = "192.168.1.102:9100"
        hot_dept.sort_order = 1
        hot_dept.kds_device_id = "kds-hot-001"
        hot_dept.is_deleted = False

        # 模拟 DB，按调用顺序返回
        mock_db = AsyncMock()

        # 执行顺序：
        # 1. DishDeptMapping 查询（无规则引擎模式）
        # 2. ProductionDept 全量查询
        # 3. OrderItem.kds_station update (x2)
        # 4. kds_tasks insert (flush)
        # 5. Order 查询（桌号/单号）

        mapping_result = MagicMock()
        mapping_result.all = MagicMock(return_value=[
            (uuid.UUID(DISH_CUCUMBER), cold_dept_uuid),
            (uuid.UUID(DISH_PORK), hot_dept_uuid),
        ])

        dept_result = MagicMock()
        dept_result.scalars = MagicMock(return_value=MagicMock(
            all=MagicMock(return_value=[cold_dept, hot_dept])
        ))

        order_result = MagicMock()
        order_result.one_or_none = MagicMock(return_value=("A01", "ORDER-001"))

        execute_seq = [
            mapping_result,       # DishDeptMapping query
            dept_result,          # ProductionDept query
            MagicMock(),          # OrderItem update x1
            MagicMock(),          # OrderItem update x2
        ]
        mock_db.execute = AsyncMock(side_effect=execute_seq)
        mock_db.flush = AsyncMock()
        mock_db.add_all = MagicMock()

        with (
            patch("services.kds_dispatch.dispatch_rule_engine") as mock_engine,
            patch("services.kds_dispatch.print_kitchen_tickets_for_dispatch", new_callable=AsyncMock),
            patch("services.kds_dispatch.coordinate_same_table", new_callable=AsyncMock, return_value=[]),
        ):
            # 不使用规则引擎（store_id 为空）
            result = await dispatch_order_to_kds(
                order_id=order_id,
                order_items=order_items,
                tenant_id=TENANT_ID,
                db=mock_db,
                table_number="A01",
                order_no="ORDER-001",
                auto_print=False,  # 关闭打印，专注测试分单逻辑
                store_id="",
            )

        dept_tasks = result["dept_tasks"]

        # 应有2个档口任务组
        assert len(dept_tasks) == 2, f"期望2个档口任务组，实际 {len(dept_tasks)}"

        dept_ids_in_result = {t["dept_id"] for t in dept_tasks}
        assert DEPT_COLD in dept_ids_in_result, "凉菜档未出现在分单结果"
        assert DEPT_HOT in dept_ids_in_result, "热菜档未出现在分单结果"

        # 凉菜档应有1道菜，热菜档应有1道菜
        cold_task = next(t for t in dept_tasks if t["dept_id"] == DEPT_COLD)
        hot_task = next(t for t in dept_tasks if t["dept_id"] == DEPT_HOT)
        assert len(cold_task["items"]) == 1
        assert len(hot_task["items"]) == 1

    @pytest.mark.asyncio
    async def test_unmapped_dish_goes_to_default_dept(self):
        """未配置档口的菜品自动归入默认档口（第一个档口）"""
        from services.kds_dispatch import dispatch_order_to_kds

        order_id = _uid_str()
        order_items = [
            {
                "dish_id": DISH_UNKNOWN,
                "item_name": "神秘菜品",
                "quantity": 1,
                "order_item_id": _uid_str(),
                "notes": "",
            },
        ]

        cold_dept = MagicMock()
        cold_dept.id = uuid.UUID(DEPT_COLD)
        cold_dept.dept_name = "凉菜档"
        cold_dept.dept_code = "cold"
        cold_dept.printer_address = "192.168.1.101:9100"
        cold_dept.sort_order = 0
        cold_dept.is_deleted = False

        mapping_result = MagicMock()
        mapping_result.all = MagicMock(return_value=[])  # 无映射

        dept_result = MagicMock()
        dept_result.scalars = MagicMock(return_value=MagicMock(
            all=MagicMock(return_value=[cold_dept])
        ))

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[mapping_result, dept_result])
        mock_db.flush = AsyncMock()
        mock_db.add_all = MagicMock()

        with (
            patch("services.kds_dispatch.print_kitchen_tickets_for_dispatch", new_callable=AsyncMock),
            patch("services.kds_dispatch.coordinate_same_table", new_callable=AsyncMock, return_value=[]),
        ):
            result = await dispatch_order_to_kds(
                order_id=order_id,
                order_items=order_items,
                tenant_id=TENANT_ID,
                db=mock_db,
                table_number="B02",
                order_no="ORDER-002",
                auto_print=False,
                store_id="",
            )

        dept_tasks = result["dept_tasks"]
        assert len(dept_tasks) == 1
        # 未映射菜品归入默认档口（凉菜档，sort_order最小）
        assert dept_tasks[0]["dept_name"] == "凉菜档"
        assert len(dept_tasks[0]["items"]) == 1

    @pytest.mark.asyncio
    async def test_get_kds_tasks_by_dept_returns_pending_cooking(self):
        """按 dept_id 查询任务，默认返回 pending+cooking 状态"""
        from services.kds_dispatch import get_kds_tasks_by_dept

        task1 = MagicMock()
        task1.id = uuid.uuid4()
        task1.order_item_id = uuid.uuid4()
        task1.order_id = uuid.uuid4()
        task1.order_no = "ORDER-001"
        task1.table_number = "A01"
        task1.dish_id = uuid.UUID(DISH_CUCUMBER)
        task1.dish_name = "拍黄瓜"
        task1.quantity = 1
        task1.notes = ""
        task1.status = "pending"
        task1.priority = "normal"
        task1.created_at = datetime.now(timezone.utc)
        task1.started_at = None
        task1.rush_count = 0
        task1.promised_at = None

        count_result = MagicMock()
        count_result.scalar = MagicMock(return_value=1)

        task_result = MagicMock()
        task_result.scalars = MagicMock(return_value=MagicMock(
            all=MagicMock(return_value=[task1])
        ))

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[count_result, task_result])

        tasks, total = await get_kds_tasks_by_dept(
            dept_id=DEPT_COLD,
            tenant_id=TENANT_ID,
            db=mock_db,
            status=None,  # 默认 pending+cooking
        )

        assert total == 1
        assert len(tasks) == 1
        assert tasks[0]["dish_name"] == "拍黄瓜"
        assert tasks[0]["status"] == "pending"


# ─── KDS 设备识别测试 ───

class TestKdsDeviceIdentification:
    """KDS设备自我识别测试"""

    @pytest.mark.asyncio
    async def test_get_dept_by_kds_device_id(self):
        """KDS设备按 device_id 识别所属档口"""
        from services.production_dept_service import get_dept_by_kds_device_id

        dept = MagicMock()
        dept.id = uuid.UUID(DEPT_COLD)
        dept.kds_device_id = "kds-cold-001"
        dept.dept_name = "凉菜档"

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=dept)
        ))

        result = await get_dept_by_kds_device_id("kds-cold-001", TENANT_ID, mock_db)
        assert result is not None
        assert result.dept_name == "凉菜档"

    @pytest.mark.asyncio
    async def test_get_dept_by_unknown_device_id_returns_none(self):
        """未绑定的KDS设备返回 None"""
        from services.production_dept_service import get_dept_by_kds_device_id

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None)
        ))

        result = await get_dept_by_kds_device_id("unknown-device", TENANT_ID, mock_db)
        assert result is None
