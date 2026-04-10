"""测试：营销活动引擎 DB持久化版（campaign_engine_db_routes.py）

覆盖5个核心用例：
1. test_create_campaign         — 创建活动，验证 id/status/rules 字段
2. test_campaign_status_machine — 完整状态机流转 + 非法转换返回 400
3. test_apply_campaign_to_order — 核销：active折扣活动 → discount>0
4. test_campaign_not_applied_when_inactive — 非active活动不应用到订单
5. test_conflict_detection      — 同类型同时间段活动冲突检测

运行：
    pytest services/tx-growth/src/tests/test_campaign_engine_db.py -v
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from ..api.campaign_engine_db_routes import VALID_TRANSITIONS, _calc_discount, router

# ---------------------------------------------------------------------------
# 测试 App
# ---------------------------------------------------------------------------

from fastapi import FastAPI

_app = FastAPI()
_app.include_router(router)

_TENANT_ID = "11111111-1111-1111-1111-111111111111"
_TENANT_HEADERS = {"X-Tenant-ID": _TENANT_ID}


# ---------------------------------------------------------------------------
# 辅助：构造 mock DB session
# ---------------------------------------------------------------------------


def _make_mock_db(
    fetch_one_return=None,
    fetch_all_return=None,
    scalar_return=None,
    execute_raises=None,
):
    """返回 (mock_db, mock_execute_result)"""
    mock_result = MagicMock()
    mock_result.fetchone.return_value = fetch_one_return
    mock_result.fetchall.return_value = fetch_all_return or []
    mock_result.scalar.return_value = scalar_return

    mock_db = AsyncMock()
    if execute_raises:
        mock_db.execute.side_effect = execute_raises
    else:
        mock_db.execute.return_value = mock_result
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    return mock_db, mock_result


# ---------------------------------------------------------------------------
# 1. test_create_campaign
# ---------------------------------------------------------------------------

class TestCreateCampaign:
    """创建活动：id非空 / status=draft / rules字段完整"""

    def test_create_campaign_returns_draft(self):
        """创建活动后应返回 status=draft，id 非空，rules 字段保留"""
        mock_db, _ = _make_mock_db()

        with patch(
            "services.tx_growth.src.api.campaign_engine_db_routes.get_db",
            return_value=mock_db,
        ):
            client = TestClient(_app)
            resp = client.post(
                "/api/v1/growth/campaigns-v2",
                headers=_TENANT_HEADERS,
                json={
                    "name": "测试折扣活动",
                    "campaign_type": "discount",
                    "start_at": "2026-05-01T00:00:00Z",
                    "end_at": "2026-05-07T23:59:59Z",
                    "budget_fen": 100000,
                    "rules": {"threshold_fen": 5000, "discount_rate": 0.9},
                    "target_audience": {"levels": ["VIP"]},
                    "priority": 5,
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["id"] is not None and data["id"] != ""
        assert data["status"] == "draft"
        assert data["rules"]["threshold_fen"] == 5000
        assert data["rules"]["discount_rate"] == 0.9
        assert data["campaign_type"] == "discount"

    def test_create_campaign_invalid_time_range(self):
        """end_at 早于 start_at 应返回 400"""
        mock_db, _ = _make_mock_db()

        with patch(
            "services.tx_growth.src.api.campaign_engine_db_routes.get_db",
            return_value=mock_db,
        ):
            client = TestClient(_app)
            resp = client.post(
                "/api/v1/growth/campaigns-v2",
                headers=_TENANT_HEADERS,
                json={
                    "name": "非法时间",
                    "campaign_type": "discount",
                    "start_at": "2026-05-07T00:00:00Z",
                    "end_at": "2026-05-01T00:00:00Z",  # 结束早于开始
                },
            )

        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 2. test_campaign_status_machine
# ---------------------------------------------------------------------------

class TestCampaignStatusMachine:
    """状态机完整流转 + 非法转换返回 400"""

    def _make_row(self, status: str):
        """构造 mock fetchone 返回的行对象"""
        row = MagicMock()
        row.__getitem__ = lambda self, idx: status if idx == 0 else None
        return row

    def test_valid_transitions_table(self):
        """直接验证 VALID_TRANSITIONS 表的核心路径"""
        assert "active" in VALID_TRANSITIONS["draft"]
        assert "paused" in VALID_TRANSITIONS["active"]
        assert "active" in VALID_TRANSITIONS["paused"]
        assert "ended" in VALID_TRANSITIONS["active"]
        assert VALID_TRANSITIONS["ended"] == []
        assert VALID_TRANSITIONS["cancelled"] == []

    def test_activate_from_draft_allowed(self):
        """draft → active：合法，返回 200"""
        row = self._make_row("draft")
        mock_db, mock_res = _make_mock_db(fetch_one_return=row)

        with patch(
            "services.tx_growth.src.api.campaign_engine_db_routes.get_db",
            return_value=mock_db,
        ):
            client = TestClient(_app)
            resp = client.post(
                f"/api/v1/growth/campaigns-v2/camp-abc/activate",
                headers=_TENANT_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "active"

    def test_activate_from_ended_forbidden(self):
        """ended → active：非法转换应返回 400"""
        row = self._make_row("ended")
        mock_db, _ = _make_mock_db(fetch_one_return=row)

        with patch(
            "services.tx_growth.src.api.campaign_engine_db_routes.get_db",
            return_value=mock_db,
        ):
            client = TestClient(_app)
            resp = client.post(
                "/api/v1/growth/campaigns-v2/camp-abc/activate",
                headers=_TENANT_HEADERS,
            )
        assert resp.status_code == 400
        body = resp.json()
        assert body["detail"]["error"]["code"] == "INVALID_TRANSITION"

    def test_pause_from_active_allowed(self):
        """active → paused：合法"""
        row = self._make_row("active")
        mock_db, _ = _make_mock_db(fetch_one_return=row)

        with patch(
            "services.tx_growth.src.api.campaign_engine_db_routes.get_db",
            return_value=mock_db,
        ):
            client = TestClient(_app)
            resp = client.post(
                "/api/v1/growth/campaigns-v2/camp-abc/pause",
                headers=_TENANT_HEADERS,
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "paused"

    def test_end_from_cancelled_forbidden(self):
        """cancelled → ended：非法转换应返回 400"""
        row = self._make_row("cancelled")
        mock_db, _ = _make_mock_db(fetch_one_return=row)

        with patch(
            "services.tx_growth.src.api.campaign_engine_db_routes.get_db",
            return_value=mock_db,
        ):
            client = TestClient(_app)
            resp = client.post(
                "/api/v1/growth/campaigns-v2/camp-abc/end",
                headers=_TENANT_HEADERS,
            )
        assert resp.status_code == 400
        assert resp.json()["detail"]["error"]["code"] == "INVALID_TRANSITION"


# ---------------------------------------------------------------------------
# 3. test_apply_campaign_to_order
# ---------------------------------------------------------------------------

class TestApplyCampaignToOrder:
    """核销：active折扣活动，会员下单满足threshold，返回 applied_campaign_id 和 discount>0"""

    def test_apply_active_discount_campaign(self):
        """满足门槛的 active 活动应被核销并返回折扣金额"""
        import json

        camp_row = MagicMock()
        camp_row._mapping = {
            "id": "camp-001",
            "status": "active",
            "rules": {"threshold_fen": 5000, "discount_rate": 0.9},
            "target_audience": {"levels": ["VIP"]},
            "budget_fen": 1000000,
            "used_fen": 0,
            "max_per_member": None,
            "campaign_type": "discount",
        }

        count_row = MagicMock()
        count_row.scalar.return_value = 0

        execute_results = [
            # set_config
            MagicMock(fetchone=MagicMock(return_value=None)),
            # SELECT campaign
            MagicMock(fetchone=MagicMock(return_value=camp_row)),
            # COUNT participations
            MagicMock(scalar=MagicMock(return_value=0)),
            # INSERT participant
            MagicMock(),
            # UPDATE used_fen
            MagicMock(),
        ]
        call_idx = 0

        async def mock_execute(stmt, params=None):
            nonlocal call_idx
            result = execute_results[min(call_idx, len(execute_results) - 1)]
            call_idx += 1
            return result

        mock_db = AsyncMock()
        mock_db.execute.side_effect = mock_execute
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()

        with patch(
            "services.tx_growth.src.api.campaign_engine_db_routes.get_db",
            return_value=mock_db,
        ):
            client = TestClient(_app)
            resp = client.post(
                "/api/v1/growth/campaigns-v2/camp-001/apply",
                headers=_TENANT_HEADERS,
                json={
                    "member_id": "22222222-2222-2222-2222-222222222222",
                    "order_amount_fen": 10000,
                    "order_id": "33333333-3333-3333-3333-333333333333",
                },
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["applied_campaign_id"] == "camp-001"
        assert data["total_discount_fen"] > 0
        assert "camp-001" in data["applicable_campaigns"]

    def test_calc_discount_by_rate(self):
        """_calc_discount：10折率 discount_rate=0.9，10000分订单 → 1000分折扣"""
        result = _calc_discount(10000, {"threshold_fen": 5000, "discount_rate": 0.9})
        assert result == 1000

    def test_calc_discount_flat(self):
        """_calc_discount：满减 discount_fen=2000 → 直接减2000"""
        result = _calc_discount(15000, {"threshold_fen": 10000, "discount_fen": 2000})
        assert result == 2000

    def test_calc_discount_max_cap(self):
        """_calc_discount：max_discount_fen 上限生效"""
        result = _calc_discount(100000, {"discount_rate": 0.5, "max_discount_fen": 5000})
        assert result == 5000


# ---------------------------------------------------------------------------
# 4. test_campaign_not_applied_when_inactive
# ---------------------------------------------------------------------------

class TestCampaignNotAppliedWhenInactive:
    """非active活动（draft/paused）不应用到订单"""

    def _apply_with_status(self, status: str) -> dict:
        camp_row = MagicMock()
        camp_row._mapping = {
            "id": "camp-draft",
            "status": status,
            "rules": {"threshold_fen": 0, "discount_rate": 0.9},
            "target_audience": {},
            "budget_fen": None,
            "used_fen": 0,
            "max_per_member": None,
            "campaign_type": "discount",
        }

        execute_results = [
            MagicMock(fetchone=MagicMock(return_value=None)),  # set_config
            MagicMock(fetchone=MagicMock(return_value=camp_row)),  # SELECT campaign
        ]
        call_idx = 0

        async def mock_execute(stmt, params=None):
            nonlocal call_idx
            result = execute_results[min(call_idx, len(execute_results) - 1)]
            call_idx += 1
            return result

        mock_db = AsyncMock()
        mock_db.execute.side_effect = mock_execute
        mock_db.commit = AsyncMock()

        with patch(
            "services.tx_growth.src.api.campaign_engine_db_routes.get_db",
            return_value=mock_db,
        ):
            client = TestClient(_app)
            resp = client.post(
                "/api/v1/growth/campaigns-v2/camp-draft/apply",
                headers=_TENANT_HEADERS,
                json={
                    "member_id": "22222222-2222-2222-2222-222222222222",
                    "order_amount_fen": 10000,
                },
            )
        return resp.json()

    def test_draft_campaign_not_applied(self):
        """draft 状态活动核销时返回 total_discount_fen=0"""
        body = self._apply_with_status("draft")
        assert body["ok"] is True
        assert body["data"]["total_discount_fen"] == 0
        assert body["data"]["applied_campaign_id"] is None

    def test_paused_campaign_not_applied(self):
        """paused 状态活动核销时返回 total_discount_fen=0"""
        body = self._apply_with_status("paused")
        assert body["ok"] is True
        assert body["data"]["total_discount_fen"] == 0
        assert body["data"]["applied_campaign_id"] is None

    def test_ended_campaign_not_applied(self):
        """ended 状态活动核销时返回 total_discount_fen=0"""
        body = self._apply_with_status("ended")
        assert body["ok"] is True
        assert body["data"]["total_discount_fen"] == 0


# ---------------------------------------------------------------------------
# 5. test_conflict_detection
# ---------------------------------------------------------------------------

class TestConflictDetection:
    """冲突检测：两个同类型同时间段活动重叠 → conflict=True"""

    def test_conflict_detected(self):
        """同类型同时间段有活动时，冲突检测接口应返回 conflict=True"""
        conflict_row = MagicMock()
        conflict_row._mapping = {
            "id": "camp-existing",
            "name": "已有活动",
            "status": "active",
            "start_at": "2026-05-01T00:00:00+00:00",
            "end_at": "2026-05-07T23:59:59+00:00",
        }

        execute_results = [
            MagicMock(fetchone=MagicMock(return_value=None)),  # set_config
            MagicMock(fetchall=MagicMock(return_value=[conflict_row])),  # SELECT conflicts
        ]
        call_idx = 0

        async def mock_execute(stmt, params=None):
            nonlocal call_idx
            result = execute_results[min(call_idx, len(execute_results) - 1)]
            call_idx += 1
            return result

        mock_db = AsyncMock()
        mock_db.execute.side_effect = mock_execute

        with patch(
            "services.tx_growth.src.api.campaign_engine_db_routes.get_db",
            return_value=mock_db,
        ):
            client = TestClient(_app)
            resp = client.get(
                "/api/v1/growth/campaigns-v2/check-conflicts",
                headers=_TENANT_HEADERS,
                params={
                    "type": "discount",
                    "start_at": "2026-05-03T00:00:00Z",
                    "end_at": "2026-05-10T23:59:59Z",
                },
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["conflict"] is True
        assert len(data["conflicts"]) >= 1

    def test_no_conflict_when_no_overlap(self):
        """无重叠活动时，冲突检测应返回 conflict=False"""
        execute_results = [
            MagicMock(fetchone=MagicMock(return_value=None)),  # set_config
            MagicMock(fetchall=MagicMock(return_value=[])),  # 无冲突
        ]
        call_idx = 0

        async def mock_execute(stmt, params=None):
            nonlocal call_idx
            result = execute_results[min(call_idx, len(execute_results) - 1)]
            call_idx += 1
            return result

        mock_db = AsyncMock()
        mock_db.execute.side_effect = mock_execute

        with patch(
            "services.tx_growth.src.api.campaign_engine_db_routes.get_db",
            return_value=mock_db,
        ):
            client = TestClient(_app)
            resp = client.get(
                "/api/v1/growth/campaigns-v2/check-conflicts",
                headers=_TENANT_HEADERS,
                params={
                    "type": "discount",
                    "start_at": "2026-08-01T00:00:00Z",
                    "end_at": "2026-08-07T23:59:59Z",
                },
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["conflict"] is False
        assert data["conflicts"] == []
