"""宴会管理服务测试 — 覆盖全生命周期

测试数据基于徐记海鲜典型宴会场景。
"""
import pytest

from ..services.banquet_service import (
    EVENT_TYPE_CONFIG,
    MENU_TEMPLATES,
    TIER_PRICING,
    BanquetCostEstimate,
    BanquetProposal,
    BanquetService,
    _bookings,
    _cases,
    _feedbacks,
    _inquiries,
    _proposals,
)

TENANT_ID = "t-xuji-seafood-001"
STORE_ID = "s-xuji-changsha-01"


@pytest.fixture(autouse=True)
def clean_storage():
    """每个测试前清空内存存储"""
    _inquiries.clear()
    _proposals.clear()
    _bookings.clear()
    _feedbacks.clear()
    _cases.clear()
    yield


@pytest.fixture
def svc():
    return BanquetService(tenant_id=TENANT_ID, store_id=STORE_ID)


# ─── 1. 线索管理 ───

class TestInquiry:
    def test_create_wedding_inquiry(self, svc: BanquetService):
        result = svc.create_inquiry(
            customer_name="张先生",
            event_type="wedding",
            guest_count=200,
            budget_range=(10000000, 20000000),  # 10万-20万
            preferred_date="2026-05-18",
            special_requests="新娘对海鲜过敏，需要替换菜品",
        )
        assert result["inquiry_id"].startswith("INQ-")
        assert result["customer_name"] == "张先生"
        assert result["event_type"] == "wedding"
        assert result["event_type_name"] == "婚宴"
        assert result["guest_count"] == 200
        assert result["table_count"] == 20  # 200/10
        assert result["status"] == "new"
        assert result["special_requests"] == "新娘对海鲜过敏，需要替换菜品"

    def test_create_birthday_inquiry(self, svc: BanquetService):
        result = svc.create_inquiry(
            customer_name="李阿姨",
            event_type="birthday",
            guest_count=50,
            budget_range=(3000000, 5000000),  # 3万-5万
            preferred_date="2026-06-15",
            special_requests="80大寿，需要寿桃12只",
        )
        assert result["event_type"] == "birthday"
        assert result["table_count"] == 5
        assert result["budget_per_head_fen"] == 100000  # 5万/50人=1000元

    def test_create_inquiry_invalid_event_type(self, svc: BanquetService):
        with pytest.raises(ValueError, match="Unsupported event_type"):
            svc.create_inquiry(
                customer_name="王先生",
                event_type="funeral",
                guest_count=100,
                budget_range=(5000000, 10000000),
                preferred_date="2026-07-01",
            )

    def test_create_inquiry_invalid_guest_count(self, svc: BanquetService):
        with pytest.raises(ValueError, match="guest_count must be positive"):
            svc.create_inquiry(
                customer_name="王先生",
                event_type="wedding",
                guest_count=0,
                budget_range=(5000000, 10000000),
                preferred_date="2026-07-01",
            )

    def test_create_inquiry_invalid_budget_range(self, svc: BanquetService):
        with pytest.raises(ValueError, match="budget_range min must not exceed max"):
            svc.create_inquiry(
                customer_name="王先生",
                event_type="wedding",
                guest_count=100,
                budget_range=(10000000, 5000000),
                preferred_date="2026-07-01",
            )

    def test_list_inquiries(self, svc: BanquetService):
        svc.create_inquiry("张先生", "wedding", 200, (10000000, 20000000), "2026-05-18")
        svc.create_inquiry("李阿姨", "birthday", 50, (3000000, 5000000), "2026-06-15")
        svc.create_inquiry("王总", "business", 30, (5000000, 8000000), "2026-04-20")

        # 列出全部
        all_inqs = svc.list_inquiries()
        assert len(all_inqs) == 3
        # 按日期排序
        assert all_inqs[0]["customer_name"] == "王总"

        # 按状态筛选
        new_inqs = svc.list_inquiries(status="new")
        assert len(new_inqs) == 3

    def test_list_inquiries_date_range(self, svc: BanquetService):
        svc.create_inquiry("张先生", "wedding", 200, (10000000, 20000000), "2026-05-18")
        svc.create_inquiry("李阿姨", "birthday", 50, (3000000, 5000000), "2026-06-15")
        svc.create_inquiry("王总", "business", 30, (5000000, 8000000), "2026-04-20")

        may_inqs = svc.list_inquiries(date_range=("2026-05-01", "2026-05-31"))
        assert len(may_inqs) == 1
        assert may_inqs[0]["customer_name"] == "张先生"


# ─── 2. AI方案推荐 ───

class TestProposal:
    def test_generate_wedding_proposal(self, svc: BanquetService):
        inq = svc.create_inquiry("张先生", "wedding", 200, (10000000, 20000000), "2026-05-18")
        proposal = svc.generate_proposal(
            inquiry_id=inq["inquiry_id"],
            guest_count=200,
            budget_per_head_fen=100000,  # 1000元/位
            event_type="wedding",
            dietary_restrictions=["海鲜"],
        )

        assert isinstance(proposal, BanquetProposal)
        assert proposal.event_type == "wedding"
        assert proposal.guest_count == 200
        assert len(proposal.tiers) == 3

        # 三档都有菜单
        tier_names = [t["tier"] for t in proposal.tiers]
        assert tier_names == ["economy", "standard", "premium"]

        # 标准档标记为推荐
        std_tier = proposal.tiers[1]
        assert std_tier["recommended"] is True
        assert std_tier["course_count"] > 0

        # 有场地推荐
        assert proposal.venue["capacity"] >= 200

        # 有装饰方案
        assert proposal.decoration["theme"] == "red"

        # 有服务方案
        assert proposal.service_plan["waiters"] > 0
        assert proposal.service_plan["chefs"] > 0
        assert proposal.service_plan["coordinator"] == 1

        # 毛利率合理
        assert 0.1 < proposal.margin_rate < 0.8

        # 置信度
        assert 0 < proposal.confidence <= 1.0

    def test_generate_business_proposal(self, svc: BanquetService):
        inq = svc.create_inquiry("王总", "business", 12, (5000000, 8000000), "2026-04-20")
        proposal = svc.generate_proposal(
            inquiry_id=inq["inquiry_id"],
            guest_count=12,
            budget_per_head_fen=200000,  # 2000元/位
            event_type="business",
        )

        assert proposal.event_type == "business"
        assert proposal.venue["capacity"] >= 12
        assert proposal.decoration["theme"] == "navy"

    def test_generate_team_building_proposal(self, svc: BanquetService):
        inq = svc.create_inquiry("HR李", "team_building", 80, (1000000, 2000000), "2026-08-15")
        proposal = svc.generate_proposal(
            inquiry_id=inq["inquiry_id"],
            guest_count=80,
            budget_per_head_fen=25000,  # 250元/位
            event_type="team_building",
        )

        assert proposal.event_type == "team_building"
        # 团建性价比优先，经济档单价应该最低
        economy = proposal.tiers[0]
        premium = proposal.tiers[2]
        assert economy["price_per_head_fen"] < premium["price_per_head_fen"]

    def test_proposal_dietary_restrictions_flagged(self, svc: BanquetService):
        inq = svc.create_inquiry("测试", "wedding", 100, (5000000, 10000000), "2026-05-18")
        proposal = svc.generate_proposal(
            inquiry_id=inq["inquiry_id"],
            guest_count=100,
            budget_per_head_fen=100000,
            event_type="wedding",
            dietary_restrictions=["龙虾"],
        )
        # 检查是否标记了含龙虾的菜品
        for tier in proposal.tiers:
            for item in tier["menu"]:
                if "龙虾" in item["name"]:
                    assert item["flagged_dietary"] is True

    def test_inquiry_status_updated_after_proposal(self, svc: BanquetService):
        inq = svc.create_inquiry("张先生", "wedding", 200, (10000000, 20000000), "2026-05-18")
        svc.generate_proposal(
            inquiry_id=inq["inquiry_id"],
            guest_count=200,
            budget_per_head_fen=100000,
            event_type="wedding",
        )
        updated_inq = _inquiries[inq["inquiry_id"]]
        assert updated_inq["status"] == "proposal_sent"


# ─── 3. 成本测算 ───

class TestCostEstimate:
    def test_estimate_cost(self, svc: BanquetService):
        inq = svc.create_inquiry("张先生", "wedding", 200, (10000000, 20000000), "2026-05-18")
        proposal = svc.generate_proposal(
            inquiry_id=inq["inquiry_id"],
            guest_count=200,
            budget_per_head_fen=100000,
            event_type="wedding",
        )
        estimate = svc.estimate_cost(proposal.proposal_id)

        assert isinstance(estimate, BanquetCostEstimate)
        assert estimate.food_cost_fen > 0
        assert estimate.labor_cost_fen > 0
        assert estimate.venue_cost_fen > 0
        assert estimate.decoration_cost_fen > 0
        assert estimate.beverage_cost_fen > 0
        assert estimate.total_cost_fen > 0
        assert estimate.estimated_revenue_fen > estimate.total_cost_fen
        assert estimate.estimated_margin_fen > 0
        assert 0 < estimate.margin_rate < 1

    def test_estimate_cost_not_found(self, svc: BanquetService):
        with pytest.raises(ValueError, match="Proposal not found"):
            svc.estimate_cost("PRP-NONEXISTENT")


# ─── 4. 合同确认 ───

class TestBooking:
    def _create_proposal(self, svc: BanquetService) -> tuple[str, str]:
        inq = svc.create_inquiry("张先生", "wedding", 200, (10000000, 20000000), "2026-05-18")
        proposal = svc.generate_proposal(
            inquiry_id=inq["inquiry_id"],
            guest_count=200,
            budget_per_head_fen=100000,
            event_type="wedding",
        )
        return inq["inquiry_id"], proposal.proposal_id

    def test_confirm_booking(self, svc: BanquetService):
        inq_id, prop_id = self._create_proposal(svc)
        proposal = _proposals[prop_id]

        final_menu = [
            {"name": "鸿运乳猪拼盘", "price_fen": 28800, "quantity": 20},
            {"name": "上汤焗龙虾", "price_fen": 58800, "quantity": 20},
            {"name": "清蒸石斑鱼", "price_fen": 38800, "quantity": 20},
        ]
        deposit = int(proposal.estimated_total * 0.3)  # 30% 定金

        booking = svc.confirm_booking(
            inquiry_id=inq_id,
            proposal_id=prop_id,
            deposit_amount_fen=deposit,
            final_menu=final_menu,
            special_notes="新娘入场播放指定音乐",
        )

        assert booking["booking_id"].startswith("BKG-")
        assert booking["status"] == "confirmed"
        assert booking["deposit_paid"] is True
        assert booking["customer_name"] == "张先生"
        assert len(booking["final_menu"]) == 3
        assert booking["special_notes"] == "新娘入场播放指定音乐"

    def test_confirm_booking_deposit_too_low(self, svc: BanquetService):
        inq_id, prop_id = self._create_proposal(svc)

        with pytest.raises(ValueError, match="Deposit.*below minimum"):
            svc.confirm_booking(
                inquiry_id=inq_id,
                proposal_id=prop_id,
                deposit_amount_fen=100,  # 远低于20%
                final_menu=[],
            )

    def test_update_booking_status(self, svc: BanquetService):
        inq_id, prop_id = self._create_proposal(svc)
        proposal = _proposals[prop_id]
        deposit = int(proposal.estimated_total * 0.3)

        booking = svc.confirm_booking(
            inquiry_id=inq_id,
            proposal_id=prop_id,
            deposit_amount_fen=deposit,
            final_menu=[],
        )

        result = svc.update_booking_status(booking["booking_id"], "preparing")
        assert result["old_status"] == "confirmed"
        assert result["new_status"] == "preparing"

    def test_update_booking_status_invalid(self, svc: BanquetService):
        inq_id, prop_id = self._create_proposal(svc)
        proposal = _proposals[prop_id]
        deposit = int(proposal.estimated_total * 0.3)

        booking = svc.confirm_booking(
            inquiry_id=inq_id,
            proposal_id=prop_id,
            deposit_amount_fen=deposit,
            final_menu=[],
        )

        with pytest.raises(ValueError, match="Invalid status"):
            svc.update_booking_status(booking["booking_id"], "invalid_status")


# ─── 5. 执行检查清单 ───

class TestChecklist:
    def _create_booking(self, svc: BanquetService) -> str:
        inq = svc.create_inquiry("张先生", "wedding", 200, (10000000, 20000000), "2026-05-18")
        proposal = svc.generate_proposal(
            inquiry_id=inq["inquiry_id"],
            guest_count=200,
            budget_per_head_fen=100000,
            event_type="wedding",
        )
        deposit = int(proposal.estimated_total * 0.3)
        booking = svc.confirm_booking(
            inquiry_id=inq["inquiry_id"],
            proposal_id=proposal.proposal_id,
            deposit_amount_fen=deposit,
            final_menu=[{"name": "龙虾", "price_fen": 58800, "quantity": 20}],
        )
        return booking["booking_id"]

    def test_generate_checklist(self, svc: BanquetService):
        booking_id = self._create_booking(svc)
        checklist = svc.generate_execution_checklist(booking_id)

        assert len(checklist) == 5  # T-7, T-3, T-1, T-0, T+1
        phases = [c["phase"] for c in checklist]
        assert phases == ["T-7", "T-3", "T-1", "T-0", "T+1"]

        # 每个阶段都有检查项
        for phase in checklist:
            assert len(phase["items"]) > 0
            for item in phase["items"]:
                assert "task" in item
                assert "responsible" in item
                assert item["status"] == "pending"

    def test_checklist_updates_booking_status(self, svc: BanquetService):
        booking_id = self._create_booking(svc)
        svc.generate_execution_checklist(booking_id)
        assert _bookings[booking_id]["status"] == "preparing"

    def test_checklist_not_found(self, svc: BanquetService):
        with pytest.raises(ValueError, match="Booking not found"):
            svc.generate_execution_checklist("BKG-NONEXISTENT")


# ─── 6. 结算与复盘 ───

class TestSettlement:
    def _full_booking(self, svc: BanquetService) -> str:
        inq = svc.create_inquiry("张先生", "wedding", 200, (10000000, 20000000), "2026-05-18")
        proposal = svc.generate_proposal(
            inquiry_id=inq["inquiry_id"],
            guest_count=200,
            budget_per_head_fen=100000,
            event_type="wedding",
        )
        deposit = int(proposal.estimated_total * 0.3)
        booking = svc.confirm_booking(
            inquiry_id=inq["inquiry_id"],
            proposal_id=proposal.proposal_id,
            deposit_amount_fen=deposit,
            final_menu=[{"name": "龙虾", "price_fen": 58800, "quantity": 20}],
        )
        return booking["booking_id"]

    def test_settle_banquet_full_attendance(self, svc: BanquetService):
        booking_id = self._full_booking(svc)
        settlement = svc.settle_banquet(
            booking_id=booking_id,
            actual_guest_count=200,
            additional_charges=[
                {"item": "加菜两道", "amount_fen": 50000},
                {"item": "红酒5瓶", "amount_fen": 150000},
            ],
        )
        assert settlement["actual_guest_count"] == 200
        assert settlement["billing_guest_count"] == 200
        assert settlement["additional_total_fen"] == 200000
        assert settlement["balance_due_fen"] > 0
        assert _bookings[booking_id]["status"] == "settled"

    def test_settle_banquet_low_attendance(self, svc: BanquetService):
        """实际到场人数少于预订的80%，按80%收费"""
        booking_id = self._full_booking(svc)
        settlement = svc.settle_banquet(
            booking_id=booking_id,
            actual_guest_count=100,  # 只来了100人（50%）
        )
        assert settlement["actual_guest_count"] == 100
        assert settlement["billing_guest_count"] == 160  # 200 * 80%

    def test_settle_banquet_over_attendance(self, svc: BanquetService):
        booking_id = self._full_booking(svc)
        settlement = svc.settle_banquet(
            booking_id=booking_id,
            actual_guest_count=220,  # 多了20人
        )
        assert settlement["actual_guest_count"] == 220
        assert settlement["billing_guest_count"] == 220
        assert settlement["count_diff"] == 20

    def test_collect_feedback(self, svc: BanquetService):
        booking_id = self._full_booking(svc)
        svc.settle_banquet(booking_id=booking_id, actual_guest_count=200)

        feedback = svc.collect_feedback(
            booking_id=booking_id,
            satisfaction_score=9,
            feedback_text="菜品非常好，服务周到，唯一不足是音响有点小",
        )
        assert feedback["satisfaction_score"] == 9
        assert feedback["satisfaction_level"] == "excellent"

    def test_collect_feedback_invalid_score(self, svc: BanquetService):
        booking_id = self._full_booking(svc)
        with pytest.raises(ValueError, match="satisfaction_score must be between"):
            svc.collect_feedback(booking_id, 11, "test")

    def test_archive_as_case(self, svc: BanquetService):
        booking_id = self._full_booking(svc)
        svc.settle_banquet(booking_id=booking_id, actual_guest_count=200)
        svc.collect_feedback(booking_id, 9, "很满意")

        case = svc.archive_as_case(
            booking_id=booking_id,
            photos=["https://img.xuji.com/banquet/001.jpg", "https://img.xuji.com/banquet/002.jpg"],
            highlights=["龙虾造型台获好评", "灯光秀效果震撼", "全程无投诉"],
        )
        assert case["case_id"].startswith("CASE-")
        assert case["satisfaction_score"] == 9
        assert len(case["photos"]) == 2
        assert len(case["highlights"]) == 3


# ─── 7. 数据配置完整性 ───

class TestConfig:
    def test_all_event_types_have_config(self):
        for event_type in ["wedding", "birthday", "business", "team_building", "anniversary"]:
            assert event_type in EVENT_TYPE_CONFIG
            config = EVENT_TYPE_CONFIG[event_type]
            assert "name" in config
            assert "course_count" in config
            assert "theme_color" in config
            assert "must_have_dishes" in config

    def test_all_event_types_have_tier_pricing(self):
        for tier in ["economy", "standard", "premium"]:
            for event_type in EVENT_TYPE_CONFIG:
                assert event_type in TIER_PRICING[tier], \
                    f"Missing pricing for {tier}/{event_type}"

    def test_all_event_types_have_menu_templates(self):
        for event_type in EVENT_TYPE_CONFIG:
            assert event_type in MENU_TEMPLATES, f"Missing menu for {event_type}"
            for tier in ["economy", "standard", "premium"]:
                menu = MENU_TEMPLATES[event_type][tier]
                assert len(menu) >= 8, f"{event_type}/{tier} has too few dishes: {len(menu)}"

    def test_premium_more_expensive_than_economy(self):
        for event_type in EVENT_TYPE_CONFIG:
            economy = TIER_PRICING["economy"][event_type]
            standard = TIER_PRICING["standard"][event_type]
            premium = TIER_PRICING["premium"][event_type]
            assert economy < standard < premium, \
                f"{event_type}: pricing not ordered correctly"


# ─── 8. 端到端流程 ───

class TestEndToEnd:
    def test_full_banquet_lifecycle(self, svc: BanquetService):
        """完整宴会生命周期：线索 -> 方案 -> 成本 -> 确认 -> 检查 -> 结算 -> 反馈 -> 归档"""

        # Step 1: 线索
        inquiry = svc.create_inquiry(
            customer_name="徐记海鲜VIP-陈总",
            event_type="wedding",
            guest_count=300,
            budget_range=(30000000, 50000000),  # 30万-50万
            preferred_date="2026-10-01",
            special_requests="国庆婚宴，需要最高规格",
        )
        assert inquiry["status"] == "new"

        # Step 2: AI方案
        proposal = svc.generate_proposal(
            inquiry_id=inquiry["inquiry_id"],
            guest_count=300,
            budget_per_head_fen=150000,  # 1500元/位
            event_type="wedding",
        )
        assert proposal.guest_count == 300
        assert len(proposal.tiers) == 3

        # Step 3: 成本测算
        estimate = svc.estimate_cost(proposal.proposal_id)
        assert estimate.margin_rate > 0

        # Step 4: 确认预订
        deposit = int(proposal.estimated_total * 0.3)
        premium_menu = proposal.tiers[2]["menu"]  # 豪华档
        booking = svc.confirm_booking(
            inquiry_id=inquiry["inquiry_id"],
            proposal_id=proposal.proposal_id,
            deposit_amount_fen=deposit,
            final_menu=premium_menu,
            special_notes="国庆当天下午5点开始",
        )
        assert booking["status"] == "confirmed"

        # Step 5: 生成检查清单
        checklist = svc.generate_execution_checklist(booking["booking_id"])
        assert len(checklist) == 5

        # Step 6: 结算
        settlement = svc.settle_banquet(
            booking_id=booking["booking_id"],
            actual_guest_count=280,
            additional_charges=[{"item": "额外酒水", "amount_fen": 300000}],
        )
        assert settlement["final_total_fen"] > 0

        # Step 7: 反馈
        feedback = svc.collect_feedback(
            booking_id=booking["booking_id"],
            satisfaction_score=10,
            feedback_text="完美的婚宴，感谢徐记海鲜团队！",
        )
        assert feedback["satisfaction_level"] == "excellent"

        # Step 8: 归档
        case = svc.archive_as_case(
            booking_id=booking["booking_id"],
            photos=["photo1.jpg", "photo2.jpg", "photo3.jpg"],
            highlights=["300人大型婚宴零投诉", "帝王蟹刺身获全场好评"],
        )
        assert case["satisfaction_score"] == 10
        assert case["guest_count"] == 300
