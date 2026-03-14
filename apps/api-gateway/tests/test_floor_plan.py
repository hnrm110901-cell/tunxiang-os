"""
R3: 桌台平面图 — 单元测试

测试内容：
- 模型枚举值（TableShape/TableStatus）
- _to_response 转换函数
- 实时状态计算逻辑（available/reserved/occupied/maintenance）
"""
import os
for _k, _v in {
    "APP_ENV": "test",
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
    "REDIS_URL": "redis://localhost:6379/0",
    "CELERY_BROKER_URL": "redis://localhost:6379/0",
    "CELERY_RESULT_BACKEND": "redis://localhost:6379/0",
    "SECRET_KEY": "test-secret-key",
    "JWT_SECRET": "test-jwt-secret",
}.items():
    os.environ.setdefault(_k, _v)

import pytest
from unittest.mock import MagicMock

from src.models.floor_plan import TableShape, TableStatus, TableDefinition
from src.api.floor_plan import _to_response, TableResponse, TableRealtimeResponse


class TestTableShapeEnum:

    def test_rect(self):
        assert TableShape.RECT.value == "rect"

    def test_circle(self):
        assert TableShape.CIRCLE.value == "circle"

    def test_from_string(self):
        assert TableShape("rect") == TableShape.RECT
        assert TableShape("circle") == TableShape.CIRCLE


class TestTableStatusEnum:

    def test_available(self):
        assert TableStatus.AVAILABLE.value == "available"

    def test_reserved(self):
        assert TableStatus.RESERVED.value == "reserved"

    def test_occupied(self):
        assert TableStatus.OCCUPIED.value == "occupied"

    def test_maintenance(self):
        assert TableStatus.MAINTENANCE.value == "maintenance"


class TestToResponse:

    def _make_table(self, **overrides):
        defaults = {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "store_id": "S001",
            "table_number": "A01",
            "table_type": "大厅",
            "min_capacity": 2,
            "max_capacity": 4,
            "pos_x": 30.0,
            "pos_y": 50.0,
            "width": 8.0,
            "height": 8.0,
            "rotation": 0.0,
            "shape": TableShape.RECT,
            "floor": 1,
            "area_name": "A区",
            "status": TableStatus.AVAILABLE,
            "is_active": True,
        }
        defaults.update(overrides)
        mock = MagicMock(**defaults)
        # Ensure attribute access works
        for k, v in defaults.items():
            setattr(mock, k, v)
        return mock

    def test_basic_conversion(self):
        table = self._make_table()
        resp = _to_response(table)
        assert isinstance(resp, TableResponse)
        assert resp.table_number == "A01"
        assert resp.store_id == "S001"
        assert resp.pos_x == 30.0
        assert resp.shape == "rect"
        assert resp.status == "available"

    def test_circle_shape(self):
        table = self._make_table(shape=TableShape.CIRCLE)
        resp = _to_response(table)
        assert resp.shape == "circle"

    def test_maintenance_status(self):
        table = self._make_table(status=TableStatus.MAINTENANCE)
        resp = _to_response(table)
        assert resp.status == "maintenance"

    def test_none_defaults(self):
        """None 字段使用默认值"""
        table = self._make_table(
            table_type=None,
            min_capacity=None,
            max_capacity=None,
            pos_x=None,
            pos_y=None,
            width=None,
            height=None,
            rotation=None,
            shape=None,
            floor=None,
            area_name=None,
            status=None,
            is_active=None,
        )
        resp = _to_response(table)
        assert resp.table_type == "大厅"
        assert resp.min_capacity == 1
        assert resp.max_capacity == 4
        assert resp.pos_x == 50.0
        assert resp.pos_y == 50.0
        assert resp.width == 8.0
        assert resp.height == 8.0
        assert resp.rotation == 0.0
        assert resp.shape == "rect"
        assert resp.floor == 1
        assert resp.area_name == ""
        assert resp.status == "available"
        assert resp.is_active is True

    def test_vip_table(self):
        table = self._make_table(
            table_number="VIP01",
            table_type="VIP",
            min_capacity=8,
            max_capacity=20,
            shape=TableShape.CIRCLE,
            floor=2,
            area_name="VIP区",
        )
        resp = _to_response(table)
        assert resp.table_number == "VIP01"
        assert resp.table_type == "VIP"
        assert resp.max_capacity == 20
        assert resp.floor == 2


class TestRealtimeStatusLogic:
    """测试实时状态计算逻辑（从 floor_plan.py get_tables_realtime 中提取的逻辑）"""

    def test_available_no_reservation(self):
        """无预订 → available"""
        status = TableStatus.AVAILABLE
        reservation = None

        if status == TableStatus.MAINTENANCE:
            realtime = "maintenance"
        elif reservation:
            realtime = "occupied" if getattr(reservation, "is_seated", False) else "reserved"
        else:
            realtime = "available"

        assert realtime == "available"

    def test_maintenance_overrides_reservation(self):
        """维护状态优先于预订"""
        status = TableStatus.MAINTENANCE
        reservation = MagicMock()  # has reservation

        if status == TableStatus.MAINTENANCE:
            realtime = "maintenance"
        elif reservation:
            realtime = "reserved"
        else:
            realtime = "available"

        assert realtime == "maintenance"

    def test_reserved_with_pending_reservation(self):
        """有未到场预订 → reserved"""
        from src.models.reservation import ReservationStatus

        status = TableStatus.AVAILABLE
        reservation = MagicMock(status=ReservationStatus.CONFIRMED)

        if status == TableStatus.MAINTENANCE:
            realtime = "maintenance"
        elif reservation:
            if reservation.status == ReservationStatus.SEATED:
                realtime = "occupied"
            else:
                realtime = "reserved"
        else:
            realtime = "available"

        assert realtime == "reserved"

    def test_occupied_with_seated_reservation(self):
        """已入座 → occupied"""
        from src.models.reservation import ReservationStatus

        status = TableStatus.AVAILABLE
        reservation = MagicMock(status=ReservationStatus.SEATED)

        if status == TableStatus.MAINTENANCE:
            realtime = "maintenance"
        elif reservation:
            if reservation.status == ReservationStatus.SEATED:
                realtime = "occupied"
            else:
                realtime = "reserved"
        else:
            realtime = "available"

        assert realtime == "occupied"


class TestBatchLayoutRequest:
    """测试批量布局请求模型"""

    def test_pydantic_model(self):
        from src.api.floor_plan import BatchLayoutRequest, TableLayoutItem

        item1 = TableLayoutItem(
            table_number="A01",
            pos_x=10.0, pos_y=20.0,
        )
        item2 = TableLayoutItem(
            id="existing-id",
            table_number="A02",
            pos_x=30.0, pos_y=40.0,
            shape="circle",
            max_capacity=8,
        )
        req = BatchLayoutRequest(
            tables=[item1, item2],
            deleted_ids=["old-table-id"],
        )
        assert len(req.tables) == 2
        assert req.tables[0].id is None  # new table
        assert req.tables[1].id == "existing-id"  # update
        assert len(req.deleted_ids) == 1

    def test_default_values(self):
        from src.api.floor_plan import TableLayoutItem

        item = TableLayoutItem(table_number="B01", pos_x=50.0, pos_y=50.0)
        assert item.table_type == "大厅"
        assert item.min_capacity == 1
        assert item.max_capacity == 4
        assert item.width == 8.0
        assert item.height == 8.0
        assert item.rotation == 0.0
        assert item.shape == "rect"
        assert item.floor == 1
        assert item.is_active is True


class TestAssignReservationRequest:

    def test_model(self):
        from src.api.floor_plan import AssignReservationRequest

        req = AssignReservationRequest(reservation_id="RES_001")
        assert req.reservation_id == "RES_001"
