"""跨品牌联盟忠诚度测试 -- 覆盖15+个核心场景

TestAllianceService:
  1. 创建合作伙伴
  2. 更新合作伙伴
  3. 激活合作伙伴
  4. 暂停合作伙伴
  5. 暂停非活跃伙伴失败
  6. 激活已终止伙伴失败
  7. 积分外兑（扣减+转换）
  8. 积分内兑（增加+转换）
  9. 每日限额校验
  10. 兑换率计算
  11. 余额不足拒绝兑出
  12. 暂停伙伴拒绝兑换

TestAllianceRoutes:
  13. API 创建合作伙伴
  14. API 列表查询
  15. API 积分兑换
  16. API 联盟仪表盘
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from services.alliance_service import AllianceService, AllianceServiceError

TENANT_ID = str(uuid.uuid4())
CUSTOMER_A = str(uuid.uuid4())
PARTNER_ID = str(uuid.uuid4())
COUPON_TPL_ID = str(uuid.uuid4())


# ── Mock helpers ─────────────────────────────────────────────


class FakeMappingResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class FakeResult:
    def __init__(self, rows=None, scalar_val=None):
        self._rows = rows or []
        self._scalar_val = scalar_val

    def mappings(self):
        return FakeMappingResult(self._rows)

    def scalar(self):
        return self._scalar_val

    def fetchall(self):
        return self._rows


def make_db(side_effects=None):
    db = AsyncMock()
    if side_effects:
        db.execute = AsyncMock(side_effect=side_effects)
    return db


# ── TestAllianceService ──────────────────────────────────────


class TestAllianceService:
    svc = AllianceService()

    # ── 1. 创建合作伙伴 ──

    @pytest.mark.asyncio
    async def test_create_partner(self):
        db = make_db([FakeResult(), FakeResult()])  # _set_tenant, INSERT
        result = await self.svc.create_partner(
            tenant_id=TENANT_ID,
            partner_data={
                "partner_name": "星巴克",
                "partner_type": "restaurant",
                "exchange_rate_out": 1.5,
                "exchange_rate_in": 0.8,
            },
            db=db,
        )
        assert result["partner_name"] == "星巴克"
        assert result["partner_type"] == "restaurant"
        assert result["status"] == "pending"
        assert "id" in result

    # ── 2. 更新合作伙伴 ──

    @pytest.mark.asyncio
    async def test_update_partner(self):
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[{"id": PARTNER_ID, "status": "pending"}]),  # SELECT
            FakeResult(),  # UPDATE
        ])
        result = await self.svc.update_partner(
            tenant_id=TENANT_ID,
            partner_id=PARTNER_ID,
            update_data={"partner_name": "星巴克臻选", "exchange_rate_out": 2.0},
            db=db,
        )
        assert result["updated"] is True

    @pytest.mark.asyncio
    async def test_update_partner_not_found(self):
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[]),  # SELECT empty
        ])
        with pytest.raises(AllianceServiceError, match="partner_not_found"):
            await self.svc.update_partner(TENANT_ID, PARTNER_ID, {"partner_name": "x"}, db)

    # ── 3. 激活合作伙伴 ──

    @pytest.mark.asyncio
    async def test_activate_partner(self):
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[{"id": PARTNER_ID, "status": "pending"}]),  # SELECT
            FakeResult(),  # UPDATE
        ])
        result = await self.svc.activate_partner(TENANT_ID, PARTNER_ID, db)
        assert result["status"] == "active"

    # ── 4. 暂停合作伙伴 ──

    @pytest.mark.asyncio
    async def test_suspend_partner(self):
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[{"id": PARTNER_ID, "status": "active"}]),  # SELECT
            FakeResult(),  # UPDATE
        ])
        result = await self.svc.suspend_partner(TENANT_ID, PARTNER_ID, db)
        assert result["status"] == "suspended"

    # ── 5. 暂停非活跃伙伴失败 ──

    @pytest.mark.asyncio
    async def test_suspend_non_active_fails(self):
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[{"id": PARTNER_ID, "status": "pending"}]),  # SELECT
        ])
        with pytest.raises(AllianceServiceError, match="partner_not_active"):
            await self.svc.suspend_partner(TENANT_ID, PARTNER_ID, db)

    # ── 6. 激活已终止伙伴失败 ──

    @pytest.mark.asyncio
    async def test_activate_terminated_fails(self):
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[{"id": PARTNER_ID, "status": "terminated"}]),  # SELECT
        ])
        with pytest.raises(AllianceServiceError, match="partner_terminated"):
            await self.svc.activate_partner(TENANT_ID, PARTNER_ID, db)

    # ── 7. 积分外兑（扣减+转换）──

    @pytest.mark.asyncio
    async def test_exchange_points_out(self):
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[{  # SELECT partner
                "id": PARTNER_ID, "status": "active",
                "exchange_rate_out": 1.5, "partner_name": "星巴克",
            }]),
            FakeResult(rows=[{"daily_exchange_limit": 1000}]),  # _check_daily_limit: partner
            FakeResult(rows=[{"today_total": 100}]),  # _check_daily_limit: today sum
            FakeResult(rows=[{"balance": 500}]),  # points balance
            FakeResult(),  # INSERT points_ledger
            FakeResult(),  # INSERT alliance_transactions
            FakeResult(),  # UPDATE partner totals
        ])
        result = await self.svc.exchange_points_out(
            tenant_id=TENANT_ID,
            customer_id=CUSTOMER_A,
            partner_id=PARTNER_ID,
            points_amount=100,
            db=db,
        )
        assert result["direction"] == "outbound"
        assert result["points_amount"] == 100
        assert result["converted_points"] == 150  # 100 * 1.5
        assert result["status"] == "completed"

    # ── 8. 积分内兑（增加+转换）──

    @pytest.mark.asyncio
    async def test_exchange_points_in(self):
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[{  # SELECT partner
                "id": PARTNER_ID, "status": "active",
                "exchange_rate_in": 0.8, "partner_name": "星巴克",
            }]),
            FakeResult(rows=[{"daily_exchange_limit": 1000}]),  # _check_daily_limit: partner
            FakeResult(rows=[{"today_total": 0}]),  # _check_daily_limit: today sum
            FakeResult(),  # INSERT points_ledger
            FakeResult(),  # INSERT alliance_transactions
            FakeResult(),  # UPDATE partner totals
        ])
        result = await self.svc.exchange_points_in(
            tenant_id=TENANT_ID,
            customer_id=CUSTOMER_A,
            partner_id=PARTNER_ID,
            external_points=200,
            db=db,
        )
        assert result["direction"] == "inbound"
        assert result["points_amount"] == 200
        assert result["converted_points"] == 160  # 200 * 0.8
        assert result["status"] == "completed"

    # ── 9. 每日限额校验 ──

    @pytest.mark.asyncio
    async def test_daily_limit_exceeded(self):
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[{  # SELECT partner
                "id": PARTNER_ID, "status": "active",
                "exchange_rate_out": 1.0, "partner_name": "星巴克",
            }]),
            FakeResult(rows=[{"daily_exchange_limit": 500}]),  # _check_daily_limit: partner
            FakeResult(rows=[{"today_total": 450}]),  # already 450 today
        ])
        with pytest.raises(AllianceServiceError, match="daily_limit_exceeded"):
            await self.svc.exchange_points_out(
                TENANT_ID, CUSTOMER_A, PARTNER_ID, 100, db,
            )

    # ── 10. 兑换率计算 ──

    @pytest.mark.asyncio
    async def test_exchange_rate_calculation(self):
        """验证不同兑换率的转换结果"""
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[{
                "id": PARTNER_ID, "status": "active",
                "exchange_rate_out": 2.5, "partner_name": "万豪酒店",
            }]),
            FakeResult(rows=[{"daily_exchange_limit": 10000}]),
            FakeResult(rows=[{"today_total": 0}]),
            FakeResult(rows=[{"balance": 1000}]),
            FakeResult(),  # INSERT points_ledger
            FakeResult(),  # INSERT alliance_transactions
            FakeResult(),  # UPDATE partner totals
        ])
        result = await self.svc.exchange_points_out(
            TENANT_ID, CUSTOMER_A, PARTNER_ID, 300, db,
        )
        assert result["converted_points"] == 750  # 300 * 2.5
        assert result["exchange_rate"] == 2.5

    # ── 11. 余额不足拒绝兑出 ──

    @pytest.mark.asyncio
    async def test_insufficient_points_rejected(self):
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[{
                "id": PARTNER_ID, "status": "active",
                "exchange_rate_out": 1.0, "partner_name": "星巴克",
            }]),
            FakeResult(rows=[{"daily_exchange_limit": 10000}]),
            FakeResult(rows=[{"today_total": 0}]),
            FakeResult(rows=[{"balance": 50}]),  # only 50 points
        ])
        with pytest.raises(AllianceServiceError, match="insufficient_points"):
            await self.svc.exchange_points_out(
                TENANT_ID, CUSTOMER_A, PARTNER_ID, 100, db,
            )

    # ── 12. 暂停伙伴拒绝兑换 ──

    @pytest.mark.asyncio
    async def test_suspended_partner_rejected(self):
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[{
                "id": PARTNER_ID, "status": "suspended",
                "exchange_rate_out": 1.0, "partner_name": "星巴克",
            }]),
        ])
        with pytest.raises(AllianceServiceError, match="partner_not_active"):
            await self.svc.exchange_points_out(
                TENANT_ID, CUSTOMER_A, PARTNER_ID, 100, db,
            )

    # ── 查询 ──

    @pytest.mark.asyncio
    async def test_get_partner_list(self):
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[{"cnt": 2}]),  # COUNT
            FakeResult(rows=[
                {
                    "id": PARTNER_ID, "tenant_id": TENANT_ID,
                    "partner_name": "星巴克", "partner_type": "restaurant",
                    "partner_brand_logo": None, "contact_name": "张三",
                    "contact_phone": "13800138000", "contact_email": None,
                    "exchange_rate_out": 1.5, "exchange_rate_in": 0.8,
                    "daily_exchange_limit": 1000, "status": "active",
                    "contract_start": None, "contract_end": None,
                    "total_points_exchanged_out": 5000,
                    "total_points_exchanged_in": 3000,
                    "created_at": "2026-04-01", "updated_at": "2026-04-20",
                },
            ]),
        ])
        result = await self.svc.get_partner_list(TENANT_ID, db, page=1, size=20)
        assert result["total"] == 2
        assert len(result["items"]) == 1
        assert result["items"][0]["partner_name"] == "星巴克"

    @pytest.mark.asyncio
    async def test_get_alliance_dashboard(self):
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[{  # partner stats
                "total_partners": 5,
                "active_partners": 3,
                "pending_partners": 1,
                "suspended_partners": 1,
                "total_points_out": 50000,
                "total_points_in": 30000,
            }]),
            FakeResult(rows=[]),  # top partners
            FakeResult(rows=[]),  # trend
        ])
        result = await self.svc.get_alliance_dashboard(TENANT_ID, db)
        assert result["total_partners"] == 5
        assert result["active_partners"] == 3
        assert result["total_points_out"] == 50000

    @pytest.mark.asyncio
    async def test_exchange_for_coupon(self):
        db = make_db([
            FakeResult(),  # _set_tenant
            FakeResult(rows=[{  # SELECT partner
                "id": PARTNER_ID, "status": "active",
                "exchange_rate_in": 1.0, "partner_name": "星巴克",
            }]),
            FakeResult(rows=[{  # SELECT coupon_template
                "id": COUPON_TPL_ID, "name": "满100减20", "points_cost": 200,
            }]),
            FakeResult(),  # INSERT alliance_transactions
        ])
        result = await self.svc.exchange_for_coupon(
            TENANT_ID, CUSTOMER_A, PARTNER_ID, COUPON_TPL_ID, db,
        )
        assert result["coupon_name"] == "满100减20"
        assert result["points_cost"] == 200
        assert result["status"] == "completed"


# ── TestAllianceRoutes ───────────────────────────────────────


class TestAllianceRoutes:
    """API 路由层测试（通过 mock service 验证路由注册和参数传递）"""

    @pytest.mark.asyncio
    async def test_api_create_partner(self):
        """验证 POST /partners 路由创建合作伙伴"""
        from unittest.mock import MagicMock

        from api.alliance_routes import api_create_partner, CreatePartnerReq

        body = CreatePartnerReq(
            partner_name="肯德基",
            partner_type="restaurant",
            exchange_rate_out=1.2,
        )
        db = AsyncMock()
        with patch.object(AllianceService, "create_partner", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = {
                "id": str(uuid.uuid4()),
                "partner_name": "肯德基",
                "status": "pending",
            }
            result = await api_create_partner(body=body, x_tenant_id=TENANT_ID, db=db)
            assert result["ok"] is True
            assert result["data"]["partner_name"] == "肯德基"
            mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_api_list_partners(self):
        """验证 GET /partners 路由列表查询"""
        from api.alliance_routes import api_list_partners

        db = AsyncMock()
        with patch.object(AllianceService, "get_partner_list", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = {"items": [], "total": 0}
            result = await api_list_partners(
                x_tenant_id=TENANT_ID,
                status="active",
                partner_type=None,
                page=1,
                size=20,
                db=db,
            )
            assert result["ok"] is True
            assert result["data"]["total"] == 0

    @pytest.mark.asyncio
    async def test_api_exchange_points(self):
        """验证 POST /exchange 路由积分兑换"""
        from api.alliance_routes import api_exchange_points, ExchangePointsReq

        body = ExchangePointsReq(
            customer_id=CUSTOMER_A,
            partner_id=PARTNER_ID,
            direction="outbound",
            points_amount=100,
        )
        db = AsyncMock()
        with patch.object(AllianceService, "exchange_points_out", new_callable=AsyncMock) as mock_ex:
            mock_ex.return_value = {
                "transaction_id": str(uuid.uuid4()),
                "direction": "outbound",
                "points_amount": 100,
                "converted_points": 150,
                "status": "completed",
            }
            result = await api_exchange_points(body=body, x_tenant_id=TENANT_ID, db=db)
            assert result["ok"] is True
            assert result["data"]["converted_points"] == 150

    @pytest.mark.asyncio
    async def test_api_dashboard(self):
        """验证 GET /dashboard 路由仪表盘"""
        from api.alliance_routes import api_alliance_dashboard

        db = AsyncMock()
        with patch.object(AllianceService, "get_alliance_dashboard", new_callable=AsyncMock) as mock_dash:
            mock_dash.return_value = {
                "total_partners": 5,
                "active_partners": 3,
                "total_points_out": 50000,
                "total_points_in": 30000,
            }
            result = await api_alliance_dashboard(x_tenant_id=TENANT_ID, db=db)
            assert result["ok"] is True
            assert result["data"]["total_partners"] == 5
