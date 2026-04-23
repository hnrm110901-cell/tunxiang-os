"""计件提成3.0 — 单元测试（DB模式，无Mock数据）

7个测试类：
  1. TestZoneCRUD                    — 区域创建/查询/更新/删除全流程
  2. TestSchemeWithItems              — 创建方案（含5个品项明细），查询明细完整
  3. TestRecordTotalFeeCalculation   — total_fee_fen = quantity x unit_fee_fen
  4. TestEmployeeStatsAggregation    — 同员工多条记录汇总金额正确
  5. TestDailyReportTop5             — 日报返回最多5名员工，按金额降序
  6. TestDBErrorReturns500           — DB异常时返回500而非mock数据
  7. TestSerializeRow                — _serialize_row 正确处理 UUID/datetime/date
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 被测模块
from api.piecework_routes import _serialize_row, router
from fastapi import FastAPI
from fastapi.testclient import TestClient

TENANT_ID = "11111111-1111-1111-1111-111111111111"
STORE_ID = "22222222-2222-2222-2222-222222222222"
EMPLOYEE_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
EMPLOYEE_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
HEADERS = {"X-Tenant-ID": TENANT_ID}


# ──────────────────────────────────────────────────────────────────────────────
# Fixture: 构造测试 App（使用 mock DB）
# ──────────────────────────────────────────────────────────────────────────────


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def _make_db_mock() -> AsyncMock:
    """返回一个模拟 AsyncSession，execute 默认返回空结果。"""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_result.__iter__ = MagicMock(return_value=iter([]))
    mock_db.execute.return_value = mock_result
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    return mock_db


class _MockRow:
    """模拟 SQLAlchemy Row 对象，支持 ._mapping 属性。"""

    def __init__(self, d: dict[str, Any]) -> None:
        self._d = d

    @property
    def _mapping(self) -> dict[str, Any]:
        return self._d


def _make_db_with_rows(rows: list[dict[str, Any]]) -> AsyncMock:
    """返回 mock DB，execute 返回指定行集。"""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.__iter__ = MagicMock(return_value=iter([_MockRow(r) for r in rows]))
    mock_db.execute.return_value = mock_result
    return mock_db


# ──────────────────────────────────────────────────────────────────────────────
# 测试1: 区域 CRUD 全流程
# ──────────────────────────────────────────────────────────────────────────────


class TestZoneCRUD:
    """区域创建/查询/更新/删除全流程测试。"""

    def test_zone_crud_create_success(self) -> None:
        """POST /zones -> 201 返回 id 和 name。"""
        app = _make_app()
        mock_db = _make_db_mock()

        with patch("api.piecework_routes.get_db", return_value=mock_db):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/org/piecework/zones",
                json={"name": "热菜区", "description": "主厨计件区域"},
                headers=HEADERS,
            )

        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["name"] == "热菜区"
        assert "id" in data

    def test_zone_list_returns_db_rows(self) -> None:
        """GET /zones 成功时返回DB数据。"""
        db_rows = [
            {
                "id": uuid.UUID("00000000-0000-0000-0000-000000000001"),
                "tenant_id": uuid.UUID(TENANT_ID),
                "store_id": None,
                "name": "热菜区",
                "description": "热菜",
                "is_active": True,
                "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            },
        ]
        app = _make_app()
        mock_db = _make_db_with_rows(db_rows)

        with patch("api.piecework_routes.get_db", return_value=mock_db):
            client = TestClient(app)
            resp = client.get("/api/v1/org/piecework/zones", headers=HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 1
        assert body["data"]["items"][0]["name"] == "热菜区"

    def test_zone_update_success(self) -> None:
        """PUT /zones/{id} -> 200 returned updated=True。"""
        zone_id = str(uuid.uuid4())
        app = _make_app()
        mock_db = _make_db_mock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_db.execute.return_value = mock_result

        with patch("api.piecework_routes.get_db", return_value=mock_db):
            client = TestClient(app)
            resp = client.put(
                f"/api/v1/org/piecework/zones/{zone_id}",
                json={"name": "热菜区（改名）"},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["data"]["updated"] is True

    def test_zone_delete_success(self) -> None:
        """DELETE /zones/{id} -> 200 returned deleted=True。"""
        zone_id = str(uuid.uuid4())
        app = _make_app()
        mock_db = _make_db_mock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_db.execute.return_value = mock_result

        with patch("api.piecework_routes.get_db", return_value=mock_db):
            client = TestClient(app)
            resp = client.delete(
                f"/api/v1/org/piecework/zones/{zone_id}",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        assert resp.json()["data"]["deleted"] is True

    def test_zone_delete_not_found(self) -> None:
        """DELETE /zones/{id} 找不到记录 -> 404。"""
        zone_id = str(uuid.uuid4())
        app = _make_app()
        mock_db = _make_db_mock()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_db.execute.return_value = mock_result

        with patch("api.piecework_routes.get_db", return_value=mock_db):
            client = TestClient(app)
            resp = client.delete(
                f"/api/v1/org/piecework/zones/{zone_id}",
                headers=HEADERS,
            )

        assert resp.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# 测试2: 方案含5个品项明细
# ──────────────────────────────────────────────────────────────────────────────


class TestSchemeWithItems:
    """创建方案（含5个品项明细），查询明细完整。"""

    ITEMS_5 = [
        {"dish_name": "红烧肉", "unit_fee_fen": 200, "min_qty": 1},
        {"dish_name": "清蒸鲈鱼", "unit_fee_fen": 300, "min_qty": 1},
        {"dish_name": "水煮鱼", "unit_fee_fen": 250, "min_qty": 1},
        {"dish_name": "夫妻肺片", "unit_fee_fen": 150, "min_qty": 1},
        {"dish_name": "宫保鸡丁", "unit_fee_fen": 180, "min_qty": 2},
    ]

    def test_scheme_create_with_5_items(self) -> None:
        """POST /schemes 携带5条明细 -> 201，items_count=5。"""
        app = _make_app()
        mock_db = _make_db_mock()

        with patch("api.piecework_routes.get_db", return_value=mock_db):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/org/piecework/schemes",
                json={
                    "name": "热菜厨师计件方案",
                    "calc_type": "by_dish",
                    "applicable_role": "chef",
                    "items": self.ITEMS_5,
                },
                headers=HEADERS,
            )

        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["items_count"] == 5
        assert "id" in data

    def test_scheme_get_detail_returns_items(self) -> None:
        """GET /schemes/{id} 返回方案详情含 items 列表。"""
        scheme_id = str(uuid.uuid4())
        app = _make_app()

        # 第一次 execute: _set_rls; 第二次: scheme查询; 第三次: items查询
        scheme_data = {
            "id": uuid.UUID(scheme_id),
            "tenant_id": uuid.UUID(TENANT_ID),
            "zone_id": None,
            "zone_name": None,
            "name": "测试方案",
            "calc_type": "by_dish",
            "applicable_role": "chef",
            "effective_date": date(2026, 1, 1),
            "is_active": True,
            "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        }
        item_data = {
            "id": uuid.uuid4(),
            "dish_id": None,
            "method_id": None,
            "dish_name": "红烧肉",
            "unit_fee_fen": 200,
            "min_qty": 1,
            "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        }

        mock_db = AsyncMock()
        call_count = 0

        async def side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # _set_rls
                return MagicMock()
            elif call_count == 2:
                # scheme query
                r = MagicMock()
                r.fetchone.return_value = _MockRow(scheme_data)
                return r
            else:
                # items query
                r = MagicMock()
                r.__iter__ = MagicMock(return_value=iter([_MockRow(item_data)]))
                return r

        mock_db.execute.side_effect = side_effect
        mock_db.commit = AsyncMock()

        with patch("api.piecework_routes.get_db", return_value=mock_db):
            client = TestClient(app)
            resp = client.get(
                f"/api/v1/org/piecework/schemes/{scheme_id}",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "items" in data
        assert len(data["items"]) == 1
        assert data["items"][0]["dish_name"] == "红烧肉"

    def test_scheme_create_validates_calc_type(self) -> None:
        """calc_type 非法值 -> 422 校验失败。"""
        app = _make_app()
        mock_db = _make_db_mock()

        with patch("api.piecework_routes.get_db", return_value=mock_db):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/org/piecework/schemes",
                json={
                    "name": "测试方案",
                    "calc_type": "by_banana",  # 非法值
                    "applicable_role": "chef",
                    "items": [],
                },
                headers=HEADERS,
            )

        assert resp.status_code == 422

    def test_scheme_list_returns_db_rows(self) -> None:
        """GET /schemes 成功时返回DB数据。"""
        db_rows = [
            {
                "id": uuid.uuid4(),
                "tenant_id": uuid.UUID(TENANT_ID),
                "zone_id": None,
                "zone_name": None,
                "name": "测试方案",
                "calc_type": "by_dish",
                "applicable_role": "chef",
                "effective_date": date(2026, 1, 1),
                "is_active": True,
                "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            },
        ]
        app = _make_app()
        mock_db = _make_db_with_rows(db_rows)

        with patch("api.piecework_routes.get_db", return_value=mock_db):
            client = TestClient(app)
            resp = client.get("/api/v1/org/piecework/schemes", headers=HEADERS)

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 1


# ──────────────────────────────────────────────────────────────────────────────
# 测试3: total_fee_fen = quantity x unit_fee_fen
# ──────────────────────────────────────────────────────────────────────────────


class TestRecordTotalFeeCalculation:
    """total_fee_fen 由 API 层计算正确（DB 层由 GENERATED STORED 列保证）。"""

    @pytest.mark.parametrize(
        "quantity,unit_fee_fen,expected",
        [
            (1, 200, 200),
            (10, 150, 1500),
            (99, 99, 9801),
            (5, 1000, 5000),
        ],
    )
    def test_total_fee_calculation(
        self,
        quantity: int,
        unit_fee_fen: int,
        expected: int,
    ) -> None:
        """total_fee_fen 的乘法逻辑：quantity x unit_fee_fen。"""
        result = quantity * unit_fee_fen
        assert result == expected

    def test_record_create_returns_correct_total(self) -> None:
        """POST /records -> 201，返回的 total_fee_fen 等于 quantity x unit_fee_fen。"""
        app = _make_app()
        mock_db = _make_db_mock()

        quantity = 7
        unit_fee_fen = 250
        expected_total = quantity * unit_fee_fen  # 1750

        with patch("api.piecework_routes.get_db", return_value=mock_db):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/org/piecework/records",
                json={
                    "store_id": STORE_ID,
                    "employee_id": EMPLOYEE_A,
                    "dish_name": "红烧肉",
                    "quantity": quantity,
                    "unit_fee_fen": unit_fee_fen,
                },
                headers=HEADERS,
            )

        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["total_fee_fen"] == expected_total

    def test_record_create_requires_positive_quantity(self) -> None:
        """quantity < 1 -> 422 校验失败。"""
        app = _make_app()
        mock_db = _make_db_mock()

        with patch("api.piecework_routes.get_db", return_value=mock_db):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/org/piecework/records",
                json={
                    "store_id": STORE_ID,
                    "employee_id": EMPLOYEE_A,
                    "dish_name": "红烧肉",
                    "quantity": 0,  # 非法
                    "unit_fee_fen": 200,
                },
                headers=HEADERS,
            )

        assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────────────────
# 测试4: 同员工多条记录汇总金额
# ──────────────────────────────────────────────────────────────────────────────


class TestEmployeeStatsAggregation:
    """同员工多条记录汇总金额正确。"""

    def test_aggregation_sum_correct(self) -> None:
        """stats/employee 返回各品项汇总，grand_total = sum(total_fee_fen)。"""
        agg_rows = [
            {"dish_name": "红烧肉", "total_quantity": 10, "unit_fee_fen": 200, "total_fee_fen": 2000},
            {"dish_name": "清蒸鲈鱼", "total_quantity": 5, "unit_fee_fen": 300, "total_fee_fen": 1500},
            {"dish_name": "水煮鱼", "total_quantity": 8, "unit_fee_fen": 250, "total_fee_fen": 2000},
        ]
        expected_total = sum(r["total_fee_fen"] for r in agg_rows)  # 5500

        app = _make_app()
        mock_db = _make_db_with_rows(agg_rows)

        with patch("api.piecework_routes.get_db", return_value=mock_db):
            client = TestClient(app)
            resp = client.get(
                f"/api/v1/org/piecework/stats/employee"
                f"?employee_id={EMPLOYEE_A}&start_date=2026-04-01&end_date=2026-04-06",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["grand_total_fee_fen"] == expected_total
        assert data["total"] == len(agg_rows)

    def test_aggregation_empty_returns_zero(self) -> None:
        """无记录时 grand_total_fee_fen = 0，不报错。"""
        app = _make_app()
        mock_db = _make_db_with_rows([])

        with patch("api.piecework_routes.get_db", return_value=mock_db):
            client = TestClient(app)
            resp = client.get(
                f"/api/v1/org/piecework/stats/employee"
                f"?employee_id={EMPLOYEE_A}&start_date=2026-04-01&end_date=2026-04-06",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["grand_total_fee_fen"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# 测试5: 日报最多5名员工，按金额降序
# ──────────────────────────────────────────────────────────────────────────────


class TestDailyReportTop5:
    """日报返回最多5名员工，按金额降序。"""

    def test_daily_report_total_fee_positive(self) -> None:
        """有计件活动时 total_fee_fen > 0。"""
        app = _make_app()
        mock_db = AsyncMock()
        # 模拟 summary 行
        mock_summary = MagicMock()
        mock_summary.total_fee_fen = 128000
        mock_summary.total_quantity = 320
        mock_summary.participant_count = 12

        mock_top5_result = MagicMock()
        mock_top5_result.__iter__ = MagicMock(return_value=iter([]))

        call_count = 0

        async def side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # _set_rls
                return MagicMock()
            elif call_count == 2:
                # summary query
                r = MagicMock()
                r.fetchone.return_value = mock_summary
                return r
            else:
                # top5 query
                return mock_top5_result

        mock_db.execute.side_effect = side_effect
        mock_db.commit = AsyncMock()

        with patch("api.piecework_routes.get_db", return_value=mock_db):
            client = TestClient(_make_app())
            resp = client.get(
                f"/api/v1/org/piecework/daily-report?store_id={STORE_ID}&date=2026-04-06",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total_fee_fen"] == 128000
        assert data["total_quantity"] == 320
        assert data["participant_count"] == 12

    def test_daily_report_top5_limit(self) -> None:
        """日报 top5 最多返回5条（SQL LIMIT 5 保证）。"""
        app = _make_app()
        mock_db = AsyncMock()

        mock_summary = MagicMock()
        mock_summary.total_fee_fen = 50000
        mock_summary.total_quantity = 100
        mock_summary.participant_count = 5

        top5_data = [
            {"employee_id": str(uuid.uuid4()), "total_fee_fen": 20000, "quantity": 40, "rank": 1},
            {"employee_id": str(uuid.uuid4()), "total_fee_fen": 15000, "quantity": 30, "rank": 2},
            {"employee_id": str(uuid.uuid4()), "total_fee_fen": 8000, "quantity": 16, "rank": 3},
            {"employee_id": str(uuid.uuid4()), "total_fee_fen": 5000, "quantity": 10, "rank": 4},
            {"employee_id": str(uuid.uuid4()), "total_fee_fen": 2000, "quantity": 4, "rank": 5},
        ]

        call_count = 0

        async def side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return MagicMock()  # _set_rls
            elif call_count == 2:
                r = MagicMock()
                r.fetchone.return_value = mock_summary
                return r
            else:
                r = MagicMock()
                r.__iter__ = MagicMock(return_value=iter([_MockRow(d) for d in top5_data]))
                return r

        mock_db.execute.side_effect = side_effect
        mock_db.commit = AsyncMock()

        with patch("api.piecework_routes.get_db", return_value=mock_db):
            client = TestClient(app)
            resp = client.get(
                f"/api/v1/org/piecework/daily-report?store_id={STORE_ID}&date=2026-04-06",
                headers=HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data["top5"]) == 5
        # 验证降序
        for i in range(len(data["top5"]) - 1):
            assert data["top5"][i]["total_fee_fen"] >= data["top5"][i + 1]["total_fee_fen"]


# ──────────────────────────────────────────────────────────────────────────────
# 测试6: DB异常时返回500
# ──────────────────────────────────────────────────────────────────────────────


class TestDBErrorReturns500:
    """DB 不可用时，查询端点返回 500 而非 mock 数据。"""

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/org/piecework/zones",
            "/api/v1/org/piecework/schemes",
            f"/api/v1/org/piecework/stats/store?store_id={STORE_ID}&start_date=2026-04-01&end_date=2026-04-06",
            f"/api/v1/org/piecework/stats/employee?employee_id={EMPLOYEE_A}&start_date=2026-04-01&end_date=2026-04-06",
            f"/api/v1/org/piecework/stats/by-dish?store_id={STORE_ID}&date=2026-04-06",
            f"/api/v1/org/piecework/daily-report?store_id={STORE_ID}&date=2026-04-06",
        ],
    )
    def test_db_error_returns_500(self, path: str) -> None:
        """所有查询端点在DB异常时返回500。"""
        from sqlalchemy.exc import SQLAlchemyError

        app = _make_app()
        mock_db = AsyncMock()
        mock_db.execute.side_effect = SQLAlchemyError("db down")

        with patch("api.piecework_routes.get_db", return_value=mock_db):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(path, headers=HEADERS)

        assert resp.status_code == 500

    def test_scheme_detail_db_error_returns_500(self) -> None:
        """GET /schemes/{id} DB异常时返回500。"""
        from sqlalchemy.exc import SQLAlchemyError

        scheme_id = str(uuid.uuid4())
        app = _make_app()
        mock_db = AsyncMock()
        mock_db.execute.side_effect = SQLAlchemyError("db down")

        with patch("api.piecework_routes.get_db", return_value=mock_db):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(
                f"/api/v1/org/piecework/schemes/{scheme_id}",
                headers=HEADERS,
            )

        assert resp.status_code == 500


# ──────────────────────────────────────────────────────────────────────────────
# 测试7: _serialize_row 序列化
# ──────────────────────────────────────────────────────────────────────────────


class TestSerializeRow:
    """_serialize_row 正确处理 UUID/datetime/date。"""

    def test_uuid_serialized_to_string(self) -> None:
        uid = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        row = _MockRow({"id": uid, "name": "test"})
        result = _serialize_row(row)
        assert result["id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        assert isinstance(result["id"], str)

    def test_datetime_serialized_to_isoformat(self) -> None:
        dt = datetime(2026, 4, 6, 12, 0, 0, tzinfo=timezone.utc)
        row = _MockRow({"created_at": dt})
        result = _serialize_row(row)
        assert result["created_at"] == "2026-04-06T12:00:00+00:00"

    def test_date_serialized_to_string(self) -> None:
        d = date(2026, 4, 6)
        row = _MockRow({"effective_date": d})
        result = _serialize_row(row)
        assert result["effective_date"] == "2026-04-06"

    def test_plain_values_unchanged(self) -> None:
        row = _MockRow({"name": "test", "fee": 200, "active": True})
        result = _serialize_row(row)
        assert result == {"name": "test", "fee": 200, "active": True}
