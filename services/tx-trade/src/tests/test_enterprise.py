"""企业挂账与协议客户中心（B6）— 测试

覆盖场景：
1. 企业创建/更新/查询
2. 额度检查（充足/不足）
3. 签单授权（成功/额度超限/缺签名）
4. 协议价设置与查询
5. 月结账单生成
6. 收款确认（全额/部分）+ 额度释放
7. 对账单生成
8. 企业消费分析
9. 未结账单查询
10. 边界场景（重复账单/零额度）
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
import pytest
import pytest_asyncio

from unittest.mock import AsyncMock


# ─── 模拟 AsyncSession ───


class FakeSession:
    """模拟 AsyncSession 用于纯逻辑测试"""
    def __init__(self):
        self.added = []
        self.flushed = False

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed = True

    async def execute(self, stmt, *args, **kwargs):
        return FakeResult()


class FakeResult:
    def scalar_one_or_none(self):
        return None

    def scalars(self):
        return self

    def all(self):
        return []


# ─── 通用 fixture ───


TENANT_ID = str(uuid.uuid4())
TENANT_ID_OTHER = str(uuid.uuid4())


def _clear_stores():
    """清理模块级内存存储"""
    from services.enterprise_account import _enterprises, _agreement_prices, _sign_records
    from services.enterprise_billing import _bills, _bill_items
    _enterprises.clear()
    _agreement_prices.clear()
    _sign_records.clear()
    _bills.clear()
    _bill_items.clear()


# ─── 1. 企业创建与管理 ───


class TestEnterpriseAccount:
    """企业账户管理测试"""

    def setup_method(self):
        _clear_stores()

    @pytest.mark.asyncio
    async def test_create_enterprise(self):
        """企业建档成功"""
        from services.enterprise_account import EnterpriseAccountService
        db = FakeSession()
        svc = EnterpriseAccountService(db, TENANT_ID)

        result = await svc.create_enterprise(
            name="徐记海鲜集团",
            contact="张经理 13800138000",
            credit_limit_fen=5000000,  # ¥50,000
            billing_cycle="monthly",
        )

        assert result["name"] == "徐记海鲜集团"
        assert result["credit_limit_fen"] == 5000000
        assert result["used_fen"] == 0
        assert result["billing_cycle"] == "monthly"
        assert result["status"] == "active"
        assert result["tenant_id"] == TENANT_ID

    @pytest.mark.asyncio
    async def test_create_enterprise_invalid_cycle(self):
        """不支持的账期类型应失败"""
        from services.enterprise_account import EnterpriseAccountService
        db = FakeSession()
        svc = EnterpriseAccountService(db, TENANT_ID)

        with pytest.raises(ValueError, match="不支持的账期类型"):
            await svc.create_enterprise(
                name="测试企业",
                contact="联系人",
                credit_limit_fen=100000,
                billing_cycle="weekly",
            )

    @pytest.mark.asyncio
    async def test_update_enterprise(self):
        """更新企业信息"""
        from services.enterprise_account import EnterpriseAccountService
        db = FakeSession()
        svc = EnterpriseAccountService(db, TENANT_ID)

        created = await svc.create_enterprise(
            name="初始名称", contact="联系人", credit_limit_fen=100000,
        )
        updated = await svc.update_enterprise(
            created["id"], {"name": "新名称", "credit_limit_fen": 200000}
        )

        assert updated["name"] == "新名称"
        assert updated["credit_limit_fen"] == 200000

    @pytest.mark.asyncio
    async def test_list_enterprises_tenant_isolation(self):
        """租户隔离：只能看到自己的企业"""
        from services.enterprise_account import EnterpriseAccountService
        db = FakeSession()

        svc_a = EnterpriseAccountService(db, TENANT_ID)
        svc_b = EnterpriseAccountService(db, TENANT_ID_OTHER)

        await svc_a.create_enterprise("企业A", "联系人A", 100000)
        await svc_b.create_enterprise("企业B", "联系人B", 200000)

        list_a = await svc_a.list_enterprises()
        list_b = await svc_b.list_enterprises()

        assert len(list_a) == 1
        assert list_a[0]["name"] == "企业A"
        assert len(list_b) == 1
        assert list_b[0]["name"] == "企业B"


# ─── 2. 额度检查 ───


class TestCreditCheck:
    """额度检查测试"""

    def setup_method(self):
        _clear_stores()

    @pytest.mark.asyncio
    async def test_credit_sufficient(self):
        """额度充足"""
        from services.enterprise_account import EnterpriseAccountService
        db = FakeSession()
        svc = EnterpriseAccountService(db, TENANT_ID)

        ent = await svc.create_enterprise("测试企业", "联系人", 5000000)
        result = await svc.check_credit(ent["id"], 1000000)

        assert result["sufficient"] is True
        assert result["available_fen"] == 5000000
        assert result["limit_fen"] == 5000000
        assert result["used_fen"] == 0

    @pytest.mark.asyncio
    async def test_credit_insufficient(self):
        """额度不足"""
        from services.enterprise_account import EnterpriseAccountService
        db = FakeSession()
        svc = EnterpriseAccountService(db, TENANT_ID)

        ent = await svc.create_enterprise("测试企业", "联系人", 100000)  # ¥1000
        result = await svc.check_credit(ent["id"], 200000)  # 请求¥2000

        assert result["sufficient"] is False
        assert result["available_fen"] == 100000
        assert result["requested_fen"] == 200000

    @pytest.mark.asyncio
    async def test_credit_after_sign(self):
        """签单后额度减少"""
        from services.enterprise_account import EnterpriseAccountService
        db = FakeSession()
        svc = EnterpriseAccountService(db, TENANT_ID)

        ent = await svc.create_enterprise("测试企业", "联系人", 5000000)
        await svc.authorize_sign(ent["id"], "order-001", "王总", 2000000)

        result = await svc.check_credit(ent["id"], 1000000)
        assert result["available_fen"] == 3000000
        assert result["used_fen"] == 2000000
        assert result["sufficient"] is True


# ─── 3. 签单授权 ───


class TestAuthorizeSign:
    """签单授权测试"""

    def setup_method(self):
        _clear_stores()

    @pytest.mark.asyncio
    async def test_sign_success(self):
        """签单成功"""
        from services.enterprise_account import EnterpriseAccountService
        db = FakeSession()
        svc = EnterpriseAccountService(db, TENANT_ID)

        ent = await svc.create_enterprise("徐记海鲜", "张经理", 5000000)
        result = await svc.authorize_sign(
            ent["id"], "order-001", "李总", 150000,  # ¥1500
        )

        assert result["authorized"] is True
        assert result["signer_name"] == "李总"
        assert result["amount_fen"] == 150000
        assert result["credit"]["used_fen"] == 150000

    @pytest.mark.asyncio
    async def test_sign_rejected_credit_exceeded(self):
        """额度超限拒绝签单"""
        from services.enterprise_account import EnterpriseAccountService
        db = FakeSession()
        svc = EnterpriseAccountService(db, TENANT_ID)

        ent = await svc.create_enterprise("小额企业", "联系人", 100000)  # ¥1000
        result = await svc.authorize_sign(
            ent["id"], "order-001", "王总", 200000,  # ¥2000，超过额度
        )

        assert result["authorized"] is False
        assert result["finance_notified"] is True
        assert "额度不足" in result["error"]

    @pytest.mark.asyncio
    async def test_sign_requires_signer_name(self):
        """签单必须有授权人姓名"""
        from services.enterprise_account import EnterpriseAccountService
        db = FakeSession()
        svc = EnterpriseAccountService(db, TENANT_ID)

        ent = await svc.create_enterprise("测试企业", "联系人", 5000000)

        with pytest.raises(ValueError, match="签单必须有授权人姓名"):
            await svc.authorize_sign(ent["id"], "order-001", "", 100000)

        with pytest.raises(ValueError, match="签单必须有授权人姓名"):
            await svc.authorize_sign(ent["id"], "order-001", "   ", 100000)

    @pytest.mark.asyncio
    async def test_multiple_signs_accumulate(self):
        """多次签单额度累计"""
        from services.enterprise_account import EnterpriseAccountService
        db = FakeSession()
        svc = EnterpriseAccountService(db, TENANT_ID)

        ent = await svc.create_enterprise("测试企业", "联系人", 5000000)

        await svc.authorize_sign(ent["id"], "order-001", "张总", 1000000)
        await svc.authorize_sign(ent["id"], "order-002", "李总", 1500000)
        result = await svc.authorize_sign(ent["id"], "order-003", "王总", 500000)

        assert result["credit"]["used_fen"] == 3000000
        assert result["credit"]["available_fen"] == 2000000


# ─── 4. 协议价 ───


class TestAgreementPrice:
    """协议价测试"""

    def setup_method(self):
        _clear_stores()

    @pytest.mark.asyncio
    async def test_set_and_get_agreement_price(self):
        """设置并查询协议价"""
        from services.enterprise_account import EnterpriseAccountService
        db = FakeSession()
        svc = EnterpriseAccountService(db, TENANT_ID)

        ent = await svc.create_enterprise("VIP企业", "联系人", 5000000)
        dish_id = str(uuid.uuid4())

        agreement = await svc.set_agreement_price(ent["id"], dish_id, 5800)  # ¥58
        assert agreement["price_fen"] == 5800
        assert agreement["enterprise_name"] == "VIP企业"

        fetched = await svc.get_agreement_price(ent["id"], dish_id)
        assert fetched is not None
        assert fetched["price_fen"] == 5800

    @pytest.mark.asyncio
    async def test_agreement_price_not_found(self):
        """未设置协议价返回None"""
        from services.enterprise_account import EnterpriseAccountService
        db = FakeSession()
        svc = EnterpriseAccountService(db, TENANT_ID)

        ent = await svc.create_enterprise("企业", "联系人", 100000)
        result = await svc.get_agreement_price(ent["id"], str(uuid.uuid4()))
        assert result is None


# ─── 5. 月结账单 ───


class TestMonthlyBilling:
    """月结账单测试"""

    def setup_method(self):
        _clear_stores()

    @pytest.mark.asyncio
    async def test_generate_monthly_bill(self):
        """生成月结账单"""
        from services.enterprise_account import EnterpriseAccountService, _sign_records
        from services.enterprise_billing import EnterpriseBillingService
        db = FakeSession()

        acct_svc = EnterpriseAccountService(db, TENANT_ID)
        bill_svc = EnterpriseBillingService(db, TENANT_ID)

        ent = await acct_svc.create_enterprise("月结企业", "联系人", 10000000)

        # 模拟签单记录（手动注入以控制月份）
        for i in range(3):
            sign_id = str(uuid.uuid4())
            _sign_records[sign_id] = {
                "id": sign_id,
                "tenant_id": TENANT_ID,
                "enterprise_id": ent["id"],
                "order_id": f"order-{i}",
                "signer_name": "张总",
                "amount_fen": 150000,  # ¥1500
                "status": "signed",
                "signed_at": "2026-03-15T12:00:00+00:00",
            }

        bill = await bill_svc.generate_monthly_bill(ent["id"], "2026-03")

        assert bill["enterprise_name"] == "月结企业"
        assert bill["month"] == "2026-03"
        assert bill["total_amount_fen"] == 450000  # 3 x ¥1500
        assert bill["order_count"] == 3
        assert bill["status"] == "issued"

    @pytest.mark.asyncio
    async def test_duplicate_bill_rejected(self):
        """重复生成同月账单应失败"""
        from services.enterprise_account import EnterpriseAccountService
        from services.enterprise_billing import EnterpriseBillingService
        db = FakeSession()

        acct_svc = EnterpriseAccountService(db, TENANT_ID)
        bill_svc = EnterpriseBillingService(db, TENANT_ID)

        ent = await acct_svc.create_enterprise("企业", "联系人", 10000000)
        await bill_svc.generate_monthly_bill(ent["id"], "2026-03")

        with pytest.raises(ValueError, match="月结账单已存在"):
            await bill_svc.generate_monthly_bill(ent["id"], "2026-03")


# ─── 6. 收款确认 ───


class TestPaymentConfirmation:
    """收款确认测试"""

    def setup_method(self):
        _clear_stores()

    @pytest.mark.asyncio
    async def test_full_payment(self):
        """全额收款"""
        from services.enterprise_account import EnterpriseAccountService, _sign_records
        from services.enterprise_billing import EnterpriseBillingService
        db = FakeSession()

        acct_svc = EnterpriseAccountService(db, TENANT_ID)
        bill_svc = EnterpriseBillingService(db, TENANT_ID)

        ent = await acct_svc.create_enterprise("企业", "联系人", 10000000)

        # 签单
        sign_id = str(uuid.uuid4())
        _sign_records[sign_id] = {
            "id": sign_id,
            "tenant_id": TENANT_ID,
            "enterprise_id": ent["id"],
            "order_id": "order-001",
            "signer_name": "张总",
            "amount_fen": 200000,
            "status": "signed",
            "signed_at": "2026-03-10T12:00:00+00:00",
        }
        # 手动增加已用额度（模拟签单流程）
        from services.enterprise_account import _enterprises
        _enterprises[ent["id"]]["used_fen"] = 200000

        bill = await bill_svc.generate_monthly_bill(ent["id"], "2026-03")
        result = await bill_svc.confirm_payment(bill["id"], "bank_transfer")

        assert result["status"] == "paid"
        assert result["outstanding_fen"] == 0
        assert result["pay_amount_fen"] == 200000

        # 额度释放
        enterprise = _enterprises[ent["id"]]
        assert enterprise["used_fen"] == 0

    @pytest.mark.asyncio
    async def test_partial_payment(self):
        """部分收款"""
        from services.enterprise_account import EnterpriseAccountService, _sign_records
        from services.enterprise_billing import EnterpriseBillingService
        db = FakeSession()

        acct_svc = EnterpriseAccountService(db, TENANT_ID)
        bill_svc = EnterpriseBillingService(db, TENANT_ID)

        ent = await acct_svc.create_enterprise("企业", "联系人", 10000000)

        sign_id = str(uuid.uuid4())
        _sign_records[sign_id] = {
            "id": sign_id,
            "tenant_id": TENANT_ID,
            "enterprise_id": ent["id"],
            "order_id": "order-001",
            "signer_name": "王总",
            "amount_fen": 300000,
            "status": "signed",
            "signed_at": "2026-03-10T12:00:00+00:00",
        }

        bill = await bill_svc.generate_monthly_bill(ent["id"], "2026-03")
        result = await bill_svc.confirm_payment(bill["id"], "bank_transfer", amount_fen=100000)

        assert result["status"] == "partial_paid"
        assert result["outstanding_fen"] == 200000
        assert result["total_paid_fen"] == 100000


# ─── 7. 对账单 ───


class TestStatement:
    """对账单测试"""

    def setup_method(self):
        _clear_stores()

    @pytest.mark.asyncio
    async def test_generate_statement(self):
        """生成对账单PDF数据"""
        from services.enterprise_account import EnterpriseAccountService, _sign_records
        from services.enterprise_billing import EnterpriseBillingService
        db = FakeSession()

        acct_svc = EnterpriseAccountService(db, TENANT_ID)
        bill_svc = EnterpriseBillingService(db, TENANT_ID)

        ent = await acct_svc.create_enterprise("徐记海鲜", "张经理 138", 10000000)

        sign_id = str(uuid.uuid4())
        _sign_records[sign_id] = {
            "id": sign_id,
            "tenant_id": TENANT_ID,
            "enterprise_id": ent["id"],
            "order_id": "order-001",
            "signer_name": "李总",
            "amount_fen": 250000,
            "status": "signed",
            "signed_at": "2026-03-20T18:00:00+00:00",
        }

        await bill_svc.generate_monthly_bill(ent["id"], "2026-03")
        statement = await bill_svc.generate_statement(ent["id"], "2026-03")

        assert "徐记海鲜" in statement["title"]
        assert statement["enterprise"]["name"] == "徐记海鲜"
        assert statement["bill"]["total_amount_fen"] == 250000
        assert len(statement["line_items"]) == 1
        assert statement["format"] == "pdf_data"

    @pytest.mark.asyncio
    async def test_statement_without_bill_fails(self):
        """未生成账单时请求对账单应失败"""
        from services.enterprise_account import EnterpriseAccountService
        from services.enterprise_billing import EnterpriseBillingService
        db = FakeSession()

        acct_svc = EnterpriseAccountService(db, TENANT_ID)
        bill_svc = EnterpriseBillingService(db, TENANT_ID)

        ent = await acct_svc.create_enterprise("企业", "联系人", 10000000)

        with pytest.raises(ValueError, match="月结账单不存在"):
            await bill_svc.generate_statement(ent["id"], "2026-03")


# ─── 8. 企业消费分析 ───


class TestEnterpriseAnalytics:
    """企业消费分析测试"""

    def setup_method(self):
        _clear_stores()

    @pytest.mark.asyncio
    async def test_analytics_basic(self):
        """基础消费分析"""
        from services.enterprise_account import EnterpriseAccountService, _sign_records
        from services.enterprise_billing import EnterpriseBillingService
        db = FakeSession()

        acct_svc = EnterpriseAccountService(db, TENANT_ID)
        bill_svc = EnterpriseBillingService(db, TENANT_ID)

        ent = await acct_svc.create_enterprise("分析企业", "联系人", 10000000)

        # 3笔签单
        for i in range(3):
            sign_id = str(uuid.uuid4())
            _sign_records[sign_id] = {
                "id": sign_id,
                "tenant_id": TENANT_ID,
                "enterprise_id": ent["id"],
                "order_id": f"order-{i}",
                "signer_name": "张总",
                "amount_fen": 100000 * (i + 1),
                "status": "signed",
                "signed_at": "2026-03-15T12:00:00+00:00",
            }

        analytics = await bill_svc.get_enterprise_analytics(ent["id"])

        assert analytics["enterprise_name"] == "分析企业"
        assert analytics["total_sign_count"] == 3
        assert analytics["total_sign_amount_fen"] == 600000  # 1000+2000+3000=6000元
        assert analytics["avg_sign_fen"] == 200000  # 平均2000元
        assert analytics["credit_limit_fen"] == 10000000


# ─── 9. 未结账单 ───


class TestOutstandingBills:
    """未结账单测试"""

    def setup_method(self):
        _clear_stores()

    @pytest.mark.asyncio
    async def test_outstanding_bills(self):
        """查询未结账单"""
        from services.enterprise_account import EnterpriseAccountService, _sign_records
        from services.enterprise_billing import EnterpriseBillingService
        db = FakeSession()

        acct_svc = EnterpriseAccountService(db, TENANT_ID)
        bill_svc = EnterpriseBillingService(db, TENANT_ID)

        ent = await acct_svc.create_enterprise("企业", "联系人", 10000000)

        # 2个月的签单
        for month_suffix, month_str in [("02", "2026-02"), ("03", "2026-03")]:
            sign_id = str(uuid.uuid4())
            _sign_records[sign_id] = {
                "id": sign_id,
                "tenant_id": TENANT_ID,
                "enterprise_id": ent["id"],
                "order_id": f"order-{month_suffix}",
                "signer_name": "张总",
                "amount_fen": 200000,
                "status": "signed",
                "signed_at": f"2026-{month_suffix}-15T12:00:00+00:00",
            }
            await bill_svc.generate_monthly_bill(ent["id"], month_str)

        outstanding = await bill_svc.get_outstanding_bills(ent["id"])
        assert len(outstanding) == 2

        # 支付一笔
        await bill_svc.confirm_payment(outstanding[0]["id"], "bank_transfer")
        outstanding = await bill_svc.get_outstanding_bills(ent["id"])
        assert len(outstanding) == 1


# ─── 10. 边界场景 ───


class TestEdgeCases:
    """边界场景测试"""

    def setup_method(self):
        _clear_stores()

    @pytest.mark.asyncio
    async def test_zero_credit_limit_rejected(self):
        """零额度创建企业应失败"""
        from services.enterprise_account import EnterpriseAccountService
        db = FakeSession()
        svc = EnterpriseAccountService(db, TENANT_ID)

        with pytest.raises(ValueError, match="授信额度必须大于0"):
            await svc.create_enterprise("企业", "联系人", 0)

    @pytest.mark.asyncio
    async def test_sign_zero_amount_rejected(self):
        """零金额签单应失败"""
        from services.enterprise_account import EnterpriseAccountService
        db = FakeSession()
        svc = EnterpriseAccountService(db, TENANT_ID)

        ent = await svc.create_enterprise("企业", "联系人", 5000000)

        with pytest.raises(ValueError, match="签单金额必须大于0"):
            await svc.authorize_sign(ent["id"], "order-001", "张总", 0)

    @pytest.mark.asyncio
    async def test_overpayment_rejected(self):
        """超额收款应失败"""
        from services.enterprise_account import EnterpriseAccountService, _sign_records
        from services.enterprise_billing import EnterpriseBillingService
        db = FakeSession()

        acct_svc = EnterpriseAccountService(db, TENANT_ID)
        bill_svc = EnterpriseBillingService(db, TENANT_ID)

        ent = await acct_svc.create_enterprise("企业", "联系人", 10000000)

        sign_id = str(uuid.uuid4())
        _sign_records[sign_id] = {
            "id": sign_id,
            "tenant_id": TENANT_ID,
            "enterprise_id": ent["id"],
            "order_id": "order-001",
            "signer_name": "张总",
            "amount_fen": 100000,
            "status": "signed",
            "signed_at": "2026-03-10T12:00:00+00:00",
        }

        bill = await bill_svc.generate_monthly_bill(ent["id"], "2026-03")

        with pytest.raises(ValueError, match="超过未结余额"):
            await bill_svc.confirm_payment(bill["id"], "bank_transfer", amount_fen=200000)


# ─── 11. API路由注册 ───


class TestEnterpriseAPIRoutes:
    """API 路由注册检查"""

    def test_enterprise_routes_exist(self):
        """验证所有10个端点已注册"""
        from api.enterprise_routes import router

        routes = {r.path: r.methods for r in router.routes if hasattr(r, "path")}

        # 10 endpoints
        assert "/api/v1/enterprise/accounts" in routes  # POST + GET
        assert "/api/v1/enterprise/accounts/{enterprise_id}" in routes  # PUT + GET
        assert "/api/v1/enterprise/accounts/{enterprise_id}/agreement-prices" in routes
        assert "/api/v1/enterprise/accounts/{enterprise_id}/sign" in routes
        assert "/api/v1/enterprise/accounts/{enterprise_id}/credit" in routes
        assert "/api/v1/enterprise/accounts/{enterprise_id}/bills" in routes
        assert "/api/v1/enterprise/bills/{bill_id}/payment" in routes
        assert "/api/v1/enterprise/accounts/{enterprise_id}/statement" in routes

    def test_route_methods(self):
        """验证HTTP方法正确"""
        from api.enterprise_routes import router

        route_methods = {}
        for r in router.routes:
            if hasattr(r, "path") and hasattr(r, "methods"):
                route_methods.setdefault(r.path, set()).update(r.methods)

        # POST endpoints
        assert "POST" in route_methods.get("/api/v1/enterprise/accounts", set())
        assert "POST" in route_methods.get("/api/v1/enterprise/accounts/{enterprise_id}/agreement-prices", set())
        assert "POST" in route_methods.get("/api/v1/enterprise/accounts/{enterprise_id}/sign", set())
        assert "POST" in route_methods.get("/api/v1/enterprise/accounts/{enterprise_id}/bills", set())
        assert "POST" in route_methods.get("/api/v1/enterprise/bills/{bill_id}/payment", set())

        # GET endpoints
        assert "GET" in route_methods.get("/api/v1/enterprise/accounts", set())
        assert "GET" in route_methods.get("/api/v1/enterprise/accounts/{enterprise_id}", set())
        assert "GET" in route_methods.get("/api/v1/enterprise/accounts/{enterprise_id}/credit", set())
        assert "GET" in route_methods.get("/api/v1/enterprise/accounts/{enterprise_id}/statement", set())

        # PUT endpoints
        assert "PUT" in route_methods.get("/api/v1/enterprise/accounts/{enterprise_id}", set())
