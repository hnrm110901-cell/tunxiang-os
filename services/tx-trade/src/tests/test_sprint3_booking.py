"""Sprint 3 Tests — 预订/排队/宴会 全生命周期

测试场景：
1. 预订完整生命周期 (create → confirm → arrive → seat → complete)
2. 排队等位时间预估 (3组等待, 预估6人桌等位)
3. 排队+预订联动 (VIP到店 → 优先排队 → 入座)
4. 宴会完整生命周期 (线索 → 方案 → 合同 → 定金 → 筹备 → 执行 → 结算)
5. 80%最低计费规则 (合同20桌, 实际15桌, 按16桌收费)
6. 爽约处理
7. 时段冲突检测
8. 美团排队同步
"""
from datetime import datetime, timedelta, timezone

import pytest

from ..services import banquet_lifecycle as bl_mod
from ..services import queue_service as qs_mod
from ..services import reservation_service as rs_mod
from ..services.banquet_lifecycle import BanquetLifecycleService, can_stage_transition
from ..services.queue_service import QueueService, _today_str
from ..services.reservation_service import ReservationService


@pytest.fixture(autouse=True)
def clear_state():
    """每个测试开始前清空内存存储"""
    qs_mod._queues.clear()
    qs_mod._queue_counters.clear()
    qs_mod._queue_history.clear()
    rs_mod._reservations.clear()
    rs_mod._no_show_records.clear()
    bl_mod._leads.clear()
    bl_mod._followups.clear()
    bl_mod._proposals.clear()
    bl_mod._quotations.clear()
    bl_mod._contracts.clear()
    bl_mod._checklists.clear()
    bl_mod._feedbacks.clear()
    bl_mod._cases.clear()
    yield


TENANT = "tenant-changsha-001"
STORE = "store-xujihaixian-wanbao"


# ═══════════════════════════════════════════════════════════
# 1. 预订完整生命周期
# ═══════════════════════════════════════════════════════════

class TestReservationLifecycle:
    """场景：徐记海鲜万博店，张先生预订明天晚上6点8人包间"""

    def test_full_lifecycle_create_confirm_arrive_seat_complete(self):
        svc = ReservationService(tenant_id=TENANT, store_id=STORE)

        # 明天日期
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

        # Step 1: 创建预订
        result = svc.create_reservation(
            store_id=STORE,
            customer_name="张建国",
            phone="13812345678",
            type="private_room",
            date=tomorrow,
            time="18:00",
            party_size=8,
            special_requests="需要儿童座椅一个，不吃辣",
        )

        assert result["reservation_id"].startswith("RSV-")
        assert result["confirmation_code"]
        assert result["party_size"] == 8
        assert result["status"] == "pending"
        assert result["table_or_room"] != "待分配"  # 包间应自动分配
        reservation_id = result["reservation_id"]

        # Step 2: 确认预订
        confirm = svc.confirm_reservation(reservation_id, confirmed_by="前台小李")
        assert confirm["status"] == "confirmed"
        assert confirm["confirmed_by"] == "前台小李"
        assert confirm["notification_sent"] is True

        # Step 3: 顾客到店 — 包间预订应直接到座
        arrive = svc.customer_arrived(reservation_id)
        assert arrive["action"] == "direct_seat"
        assert arrive["status"] == "arrived"

        # Step 4: 入座
        seat = svc.seat_reservation(reservation_id, table_no="兰花厅")
        assert seat["status"] == "seated"
        assert seat["table_no"] == "兰花厅"

        # Step 5: 完成
        complete = svc.complete_reservation(reservation_id)
        assert complete["status"] == "completed"

    def test_create_regular_reservation_no_room(self):
        """普通预订不分配包间"""
        svc = ReservationService(tenant_id=TENANT, store_id=STORE)
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

        result = svc.create_reservation(
            store_id=STORE,
            customer_name="李明",
            phone="13900001111",
            type="regular",
            date=tomorrow,
            time="12:00",
            party_size=4,
        )
        assert result["table_or_room"] == "待分配"
        assert result["status"] == "pending"

    def test_reservation_with_deposit(self):
        """带定金的预订"""
        svc = ReservationService(tenant_id=TENANT, store_id=STORE)
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

        result = svc.create_reservation(
            store_id=STORE,
            customer_name="王总",
            phone="13900002222",
            type="vip",
            date=tomorrow,
            time="18:30",
            party_size=6,
            deposit_required=True,
            deposit_amount_fen=50000,
        )
        assert result["deposit_required"] is True
        assert result["deposit_amount_fen"] == 50000


# ═══════════════════════════════════════════════════════════
# 2. 排队等位时间预估
# ═══════════════════════════════════════════════════════════

class TestQueueEstimation:
    """场景：周六晚高峰，已有3组在等位B桌(5-8人)，预估6人桌等位时间"""

    def test_estimate_with_3_groups_waiting(self):
        svc = QueueService(tenant_id=TENANT, store_id=STORE)

        # 先取3个6人桌号
        for i, (name, phone) in enumerate([
            ("赵一", "13800000001"),
            ("钱二", "13800000002"),
            ("孙三", "13800000003"),
        ]):
            result = svc.take_number(
                store_id=STORE,
                customer_name=name,
                phone=phone,
                party_size=6,
                source="walk_in",
            )
            assert result["queue_number"] == f"B{i+1:03d}"

        # 预估第4组6人的等位时间
        estimate = svc.estimate_wait_time(store_id=STORE, party_size=6)
        assert estimate["ahead_count"] == 3
        assert estimate["size_category"] == "中桌(5-8人)"
        assert estimate["prefix"] == "B"
        # 3 groups / 8 tables * 60 min ≈ 22 min
        assert estimate["estimated_wait_min"] > 0
        assert estimate["available_tables"] > 0

    def test_queue_number_series(self):
        """不同桌型分别编号"""
        svc = QueueService(tenant_id=TENANT, store_id=STORE)

        # 小桌
        r1 = svc.take_number(STORE, "客人A", "13800010001", 2)
        assert r1["queue_number"] == "A001"

        # 中桌
        r2 = svc.take_number(STORE, "客人B", "13800010002", 6)
        assert r2["queue_number"] == "B001"

        # 大桌
        r3 = svc.take_number(STORE, "客人C", "13800010003", 12)
        assert r3["queue_number"] == "C001"

        # 又一个小桌
        r4 = svc.take_number(STORE, "客人D", "13800010004", 3)
        assert r4["queue_number"] == "A002"


# ═══════════════════════════════════════════════════════════
# 3. 排队+预订联动（VIP优先排队）
# ═══════════════════════════════════════════════════════════

class TestQueueReservationLink:
    """场景：VIP客户有预订，到店后桌台未就绪，自动加入优先排队"""

    def test_vip_reservation_arrives_gets_priority_queue(self):
        rsvc = ReservationService(tenant_id=TENANT, store_id=STORE)
        qsvc = QueueService(tenant_id=TENANT, store_id=STORE)

        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

        # 先让2个散客在排队
        q1 = qsvc.take_number(STORE, "散客A", "13900010001", 4)
        q2 = qsvc.take_number(STORE, "散客B", "13900010002", 3)

        # VIP创建预订
        rsv = rsvc.create_reservation(
            store_id=STORE,
            customer_name="陈总",
            phone="13800888888",
            type="vip",
            date=tomorrow,
            time="18:00",
            party_size=4,
        )
        reservation_id = rsv["reservation_id"]

        # 确认
        rsvc.confirm_reservation(reservation_id)

        # VIP到店 — 因为是普通桌类型(非包间)，进入排队，带VIP优先
        arrive = rsvc.customer_arrived(reservation_id)
        assert arrive["action"] == "queue_with_priority"
        assert arrive["status"] == "queuing"
        assert "queue_info" in arrive

        vip_queue_id = arrive["queue_info"]["queue_id"]
        assert arrive["queue_info"]["vip_priority"] is True
        # VIP应排在散客前面
        assert arrive["queue_info"]["ahead_count"] == 0

        # 叫号 — VIP应该先被叫到
        called = qsvc.call_next(store_id=STORE, prefix="A")
        assert called is not None
        assert called["queue_id"] == vip_queue_id

        # VIP入座
        seat = rsvc.seat_reservation(reservation_id, table_no="A12")
        assert seat["status"] == "seated"
        assert seat["table_no"] == "A12"


# ═══════════════════════════════════════════════════════════
# 4. 宴会完整生命周期
# ═══════════════════════════════════════════════════════════

class TestBanquetFullLifecycle:
    """场景：徐记海鲜承接王先生的婚宴，20桌，预算40万"""

    def test_full_lifecycle_lead_to_archive(self):
        svc = BanquetLifecycleService(tenant_id=TENANT, store_id=STORE)

        # Step 1: 创建线索
        lead = svc.create_lead(
            store_id=STORE,
            customer_name="王志强",
            phone="13512345678",
            event_type="wedding",
            estimated_tables=20,
            estimated_budget_fen=40000000,  # 40万
            event_date="2026-05-18",
            special_requirements="需要LED大屏，新娘有海鲜过敏",
            referral_source="referral",
        )
        lead_id = lead["lead_id"]
        assert lead["stage"] == "lead"
        assert lead["estimated_per_table_fen"] == 2000000  # 2万/桌
        assert lead["estimated_guests"] == 200

        # Step 2: 沟通跟进
        svc.update_lead_stage(lead_id, "consultation")
        fu = svc.add_followup_record(
            lead_id=lead_id,
            content="与王先生夫妇面谈，确认2026-05-18日期，新娘对虾蟹过敏需替换菜品",
            next_action="出方案",
            next_date="2026-03-30",
        )
        assert fu["followup_id"].startswith("FU-")

        # Step 3: AI生成方案
        proposal = svc.generate_proposal(lead_id)
        assert proposal["proposal_id"].startswith("PRP-")
        assert len(proposal["tiers"]) == 3
        assert proposal["recommended_tier"] in ("economy", "standard", "premium")
        # 每档都有菜单
        for tier in proposal["tiers"]:
            assert len(tier["menu_items"]) > 0
            assert tier["total_fen"] > 0
            assert tier["margin_rate"] > 0

        # Step 4: 创建报价（选标准档，加一道佛跳墙）
        quotation = svc.create_quotation(
            lead_id=lead_id,
            proposal_tier="standard",
            adjustments=[
                {"item": "加菜:佛跳墙(每桌1盅)", "amount_fen": 1576000},  # 20桌 x 788
            ],
        )
        assert quotation["quotation_id"].startswith("QT-")
        assert quotation["adjustment_total_fen"] == 1576000
        assert quotation["final_total_fen"] > quotation["base_total_fen"]
        assert quotation["margin_rate"] > 0

        # Step 5: 签约
        contract = svc.create_contract(
            lead_id=lead_id,
            quotation_id=quotation["quotation_id"],
            terms={"cancellation_policy": "宴会前15天取消退全款"},
            deposit_rate=0.3,
        )
        contract_id = contract["contract_id"]
        assert contract["contract_no"].startswith("BQ-")
        assert contract["deposit_rate"] == 0.3
        assert contract["deposit_required_fen"] > 0
        assert contract["hall_locked"] is True

        # Step 6: 收取定金
        deposit = svc.collect_deposit(
            contract_id=contract_id,
            amount_fen=contract["deposit_required_fen"],
            method="bank_transfer",
            trade_no="TF2026032700001",
        )
        assert deposit["deposit_fulfilled"] is True
        assert deposit["remaining_fen"] == 0

        # Step 7: 确认菜单
        menu = svc.confirm_menu(
            contract_id=contract_id,
            final_menu_items=[
                {"name": "鸿运乳猪全体", "price_fen": 38800, "quantity": 20},
                {"name": "蒜蓉蒸波士顿龙虾", "price_fen": 68800, "quantity": 20},
                {"name": "鲍汁扣南非干鲍", "price_fen": 58800, "quantity": 20},
                {"name": "清蒸东星斑", "price_fen": 58800, "quantity": 20},
                {"name": "黑松露炒带子", "price_fen": 28800, "quantity": 20},
                {"name": "姜葱焗肉蟹", "price_fen": 38800, "quantity": 20},
                {"name": "蜜汁叉烧", "price_fen": 18800, "quantity": 20},
                {"name": "脆皮烧鹅", "price_fen": 22800, "quantity": 20},
                {"name": "佛跳墙", "price_fen": 78800, "quantity": 20},
                {"name": "竹笙花胶炖鸡", "price_fen": 38800, "quantity": 20},
                {"name": "松茸炒芦笋", "price_fen": 12800, "quantity": 20},
                {"name": "杨枝甘露+红豆沙", "price_fen": 8800, "quantity": 20},
                {"name": "精选时令果盘", "price_fen": 8800, "quantity": 20},
            ],
        )
        assert menu["course_count"] == 13
        assert menu["menu_total_fen"] > 0

        # Step 8: 生成筹备清单
        checklist = svc.generate_prep_checklist(contract_id)
        assert len(checklist) > 20  # 5个阶段总计应超过20项

        # 检查有T-7到T+1所有阶段
        phases_found = set(item["phase"] for item in checklist)
        assert phases_found == {"T-7", "T-3", "T-1", "T-0", "T+1"}

        # 完成几个检查项
        for item in checklist[:3]:
            svc.update_checklist_item(item["checklist_item_id"], "completed", notes="已完成")

        # Step 9: 开始执行
        execution = svc.start_execution(contract_id)
        assert execution["stage"] == "execution"
        assert execution["checklist_completion"]["completed_required"] >= 3

        # Step 10: 结算（实际18桌,180人）
        settlement = svc.settle_banquet(
            contract_id=contract_id,
            actual_tables=18,
            actual_guests=180,
            additional_charges=[
                {"item": "加菜:帝王蟹2只", "amount_fen": 158000},
                {"item": "茅台5瓶", "amount_fen": 750000},
            ],
        )
        assert settlement["actual_tables"] == 18
        assert settlement["billing_tables"] == 18  # 18 >= 80% of 20 = 16
        assert settlement["min_billing_applied"] is False
        assert settlement["additional_total_fen"] == 908000
        assert settlement["balance_due_fen"] > 0

        # Step 11: 收集反馈
        feedback = svc.collect_feedback(
            contract_id=contract_id,
            satisfaction_score=9,
            feedback_text="非常满意！菜品精致，服务周到，特别感谢宴会经理小张的贴心安排。"
                          "佛跳墙是亮点，宾客都赞不绝口。",
        )
        assert feedback["satisfaction_level"] == "excellent"

        # Step 12: 归档案例
        case = svc.archive_as_case(
            contract_id=contract_id,
            photos=["https://oss.tunxiang.com/cases/wedding-wang-01.jpg"],
            highlights=["LED大屏播放成长影片", "佛跳墙成为全场焦点", "服务零投诉"],
        )
        assert case["case_id"].startswith("CASE-")
        assert case["satisfaction_score"] == 9


# ═══════════════════════════════════════════════════════════
# 5. 80%最低计费规则
# ═══════════════════════════════════════════════════════════

class TestMinBillingRule:
    """场景：合同20桌婚宴，实际只来了15桌，按80%(16桌)计费"""

    def test_80_percent_minimum_billing(self):
        svc = BanquetLifecycleService(tenant_id=TENANT, store_id=STORE)

        # 快速走完到合同阶段
        lead = svc.create_lead(
            store_id=STORE, customer_name="刘总", phone="13700001111",
            event_type="wedding", estimated_tables=20,
            estimated_budget_fen=30000000, event_date="2026-06-01",
        )
        lead_id = lead["lead_id"]
        svc.update_lead_stage(lead_id, "consultation")
        proposal = svc.generate_proposal(lead_id)
        quotation = svc.create_quotation(lead_id, "standard")

        contract = svc.create_contract(
            lead_id=lead_id,
            quotation_id=quotation["quotation_id"],
            terms={"min_billing_rate": 0.8},
            deposit_rate=0.3,
        )
        contract_id = contract["contract_id"]

        # 支付定金
        svc.collect_deposit(contract_id, contract["deposit_required_fen"], "wechat")

        # 确认菜单
        svc.confirm_menu(contract_id, [
            {"name": "标准婚宴菜品", "price_fen": 98800, "quantity": 200},
        ])

        # 生成清单 & 执行
        svc.generate_prep_checklist(contract_id)
        svc.start_execution(contract_id)

        # 结算：实际只来了15桌
        settlement = svc.settle_banquet(
            contract_id=contract_id,
            actual_tables=15,
            actual_guests=150,
        )

        # 关键断言：实际15桌 < 80%的20桌 = 16桌，应按16桌计费
        assert settlement["contracted_tables"] == 20
        assert settlement["actual_tables"] == 15
        assert settlement["min_billing_tables"] == 16
        assert settlement["billing_tables"] == 16  # 不是15！
        assert settlement["min_billing_applied"] is True

        # 验证金额：应该是按16桌的价格
        per_table = settlement["per_table_fen"]
        assert settlement["base_total_fen"] == per_table * 16


# ═══════════════════════════════════════════════════════════
# 6. 爽约处理
# ═══════════════════════════════════════════════════════════

class TestNoShow:
    """场景：顾客预订后未到店，标记爽约并记录"""

    def test_no_show_recording(self):
        svc = ReservationService(tenant_id=TENANT, store_id=STORE)
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

        # 创建并确认预订
        r = svc.create_reservation(
            store_id=STORE, customer_name="赵大", phone="13600001111",
            type="regular", date=tomorrow, time="19:00", party_size=3,
        )
        reservation_id = r["reservation_id"]
        svc.confirm_reservation(reservation_id)

        # 标记爽约
        ns = svc.mark_no_show(reservation_id)
        assert ns["status"] == "no_show"
        assert ns["no_show_count"] == 1

        # 再创建一次预订并爽约 — 累计计数
        r2 = svc.create_reservation(
            store_id=STORE, customer_name="赵大", phone="13600001111",
            type="regular", date=tomorrow, time="12:00", party_size=2,
        )
        svc.confirm_reservation(r2["reservation_id"])
        ns2 = svc.mark_no_show(r2["reservation_id"])
        assert ns2["no_show_count"] == 2  # 累计2次

    def test_cannot_no_show_pending(self):
        """pending 状态不能直接标记爽约"""
        svc = ReservationService(tenant_id=TENANT, store_id=STORE)
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

        r = svc.create_reservation(
            store_id=STORE, customer_name="钱二", phone="13600002222",
            type="regular", date=tomorrow, time="19:00", party_size=2,
        )
        # pending → no_show 不允许
        with pytest.raises(ValueError, match="transition to 'no_show' not allowed"):
            svc.mark_no_show(r["reservation_id"])


# ═══════════════════════════════════════════════════════════
# 7. 时段冲突检测
# ═══════════════════════════════════════════════════════════

class TestTimeSlotConflict:
    """场景：竹韵阁包间已有18:00预订，检测18:30是否冲突"""

    def test_room_conflict_detection(self):
        svc = ReservationService(tenant_id=TENANT, store_id=STORE)
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

        # 第一个预订占用竹韵阁 18:00-20:00
        r1 = svc.create_reservation(
            store_id=STORE, customer_name="孙经理", phone="13700003333",
            type="private_room", date=tomorrow, time="18:00",
            party_size=10, room_name="竹韵阁",
        )
        assert r1["table_or_room"] == "竹韵阁"

        # 尝试在同一包间 18:30 创建预订 — 应冲突
        with pytest.raises(ValueError, match="Time slot conflict"):
            svc.create_reservation(
                store_id=STORE, customer_name="周总", phone="13700004444",
                type="private_room", date=tomorrow, time="18:30",
                party_size=12, room_name="竹韵阁",
            )

    def test_different_room_no_conflict(self):
        """不同包间同时段不冲突"""
        svc = ReservationService(tenant_id=TENANT, store_id=STORE)
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

        # 竹韵阁 18:00
        svc.create_reservation(
            store_id=STORE, customer_name="孙经理", phone="13700003333",
            type="private_room", date=tomorrow, time="18:00",
            party_size=10, room_name="竹韵阁",
        )

        # 菊香苑 18:00 — 不冲突
        r2 = svc.create_reservation(
            store_id=STORE, customer_name="周总", phone="13700004444",
            type="private_room", date=tomorrow, time="18:00",
            party_size=12, room_name="菊香苑",
        )
        assert r2["table_or_room"] == "菊香苑"

    def test_no_conflict_after_end_time(self):
        """前一场结束后再预订不冲突"""
        svc = ReservationService(tenant_id=TENANT, store_id=STORE)
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

        # 竹韵阁 12:00-14:00
        svc.create_reservation(
            store_id=STORE, customer_name="午餐客", phone="13700005555",
            type="private_room", date=tomorrow, time="12:00",
            party_size=8, room_name="竹韵阁",
        )

        # 竹韵阁 18:00 — 不冲突
        r2 = svc.create_reservation(
            store_id=STORE, customer_name="晚餐客", phone="13700006666",
            type="private_room", date=tomorrow, time="18:00",
            party_size=10, room_name="竹韵阁",
        )
        assert r2["table_or_room"] == "竹韵阁"


# ═══════════════════════════════════════════════════════════
# 8. 美团排队同步
# ═══════════════════════════════════════════════════════════

class TestMeituanSync:
    """场景：导入美团线上排队数据"""

    def test_sync_meituan_queue_entries(self):
        svc = QueueService(tenant_id=TENANT, store_id=STORE)

        meituan_data = [
            {"customer_name": "美团客A", "phone": "15000001111", "party_size": 4,
             "meituan_queue_no": "MT001", "taken_at": "2026-03-27T12:00:00"},
            {"customer_name": "美团客B", "phone": "15000002222", "party_size": 6,
             "meituan_queue_no": "MT002", "taken_at": "2026-03-27T12:05:00"},
            {"customer_name": "美团客C", "phone": "15000003333", "party_size": 10,
             "meituan_queue_no": "MT003", "taken_at": "2026-03-27T12:10:00"},
        ]

        result = svc.sync_meituan_queue(store_id=STORE, meituan_data=meituan_data)
        assert result["synced_count"] == 3
        assert result["skipped_count"] == 0
        assert len(result["queue_ids"]) == 3

        # 看板应显示3组等待
        board = svc.get_queue_board(STORE)
        assert board["total_waiting"] == 3

        # 再次同步 — 应全部跳过（去重）
        result2 = svc.sync_meituan_queue(store_id=STORE, meituan_data=meituan_data)
        assert result2["synced_count"] == 0
        assert result2["skipped_count"] == 3

    def test_meituan_entries_appear_in_board(self):
        """美团排队在看板上按桌型分组显示"""
        svc = QueueService(tenant_id=TENANT, store_id=STORE)

        svc.sync_meituan_queue(STORE, [
            {"customer_name": "美团客", "phone": "15000009999", "party_size": 6},
        ])

        board = svc.get_queue_board(STORE)
        b_group = [g for g in board["groups"] if g["prefix"] == "B"][0]
        assert b_group["waiting_count"] == 1


# ═══════════════════════════════════════════════════════════
# 9. 排队完整流程（叫号→到店→入座→过号）
# ═══════════════════════════════════════════════════════════

class TestQueueFullFlow:
    """排队各状态转换的完整测试"""

    def test_take_call_arrive_seat(self):
        svc = QueueService(tenant_id=TENANT, store_id=STORE)

        # 取号
        q = svc.take_number(STORE, "顾客甲", "13800001234", 4)
        queue_id = q["queue_id"]
        assert q["queue_number"] == "A001"

        # 叫号
        called = svc.call_number(queue_id)
        assert called["notification_sent"] is True
        assert called["auto_skip_at"]  # 应有10分钟后自动过号时间

        # 到店
        arrived = svc.customer_arrived(queue_id)
        assert arrived["wait_duration_min"] >= 0

        # 入座
        seated = svc.seat_customer(queue_id, "A05")
        assert seated["table_no"] == "A05"
        assert seated["total_wait_min"] >= 0

    def test_skip_after_call(self):
        """叫号后过号"""
        svc = QueueService(tenant_id=TENANT, store_id=STORE)

        q = svc.take_number(STORE, "顾客乙", "13800005678", 2)
        svc.call_number(q["queue_id"])

        skip = svc.skip_customer(q["queue_id"], reason="timeout")
        assert skip["reason"] == "timeout"

    def test_cancel_queue(self):
        """取消排队"""
        svc = QueueService(tenant_id=TENANT, store_id=STORE)

        q = svc.take_number(STORE, "顾客丙", "13800009012", 5)
        cancel = svc.cancel_queue(q["queue_id"], reason="等太久了不想吃了")
        assert cancel["reason"] == "等太久了不想吃了"

    def test_cannot_seat_already_seated(self):
        """已入座不能重复入座"""
        svc = QueueService(tenant_id=TENANT, store_id=STORE)

        q = svc.take_number(STORE, "顾客丁", "13800003456", 3)
        svc.seat_customer(q["queue_id"], "B02")

        with pytest.raises(ValueError, match="Cannot seat"):
            svc.seat_customer(q["queue_id"], "B03")


# ═══════════════════════════════════════════════════════════
# 10. 预订取消与退款
# ═══════════════════════════════════════════════════════════

class TestReservationCancel:
    """预订取消各种场景"""

    def test_cancel_confirmed_reservation(self):
        svc = ReservationService(tenant_id=TENANT, store_id=STORE)
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

        r = svc.create_reservation(
            store_id=STORE, customer_name="吴六", phone="13600007777",
            type="regular", date=tomorrow, time="19:00", party_size=4,
        )
        svc.confirm_reservation(r["reservation_id"])

        cancel = svc.cancel_reservation(
            r["reservation_id"],
            reason="临时有事",
            cancel_fee_fen=0,
        )
        assert cancel["status"] == "cancelled"
        assert cancel["reason"] == "临时有事"

    def test_cannot_cancel_completed(self):
        """已完成的预订不能取消"""
        svc = ReservationService(tenant_id=TENANT, store_id=STORE)
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

        r = svc.create_reservation(
            store_id=STORE, customer_name="郑七", phone="13600008888",
            type="regular", date=tomorrow, time="12:00", party_size=2,
        )
        svc.confirm_reservation(r["reservation_id"])

        # 模拟到店→排队→入座→完成（非包间会进排队）
        arrive = svc.customer_arrived(r["reservation_id"])
        svc.seat_reservation(r["reservation_id"], "C03")
        svc.complete_reservation(r["reservation_id"])

        with pytest.raises(ValueError, match="transition to 'cancelled' not allowed"):
            svc.cancel_reservation(r["reservation_id"], reason="想取消")


# ═══════════════════════════════════════════════════════════
# 11. 宴会阶段转换验证
# ═══════════════════════════════════════════════════════════

class TestBanquetStageTransition:
    """验证宴会13阶段状态机的合法转换"""

    def test_valid_stage_transitions(self):
        # 正向流程
        assert can_stage_transition("lead", "consultation") is True
        assert can_stage_transition("consultation", "proposal") is True
        assert can_stage_transition("proposal", "quotation") is True
        assert can_stage_transition("quotation", "contract") is True
        assert can_stage_transition("contract", "deposit_paid") is True
        assert can_stage_transition("deposit_paid", "menu_confirmed") is True
        assert can_stage_transition("menu_confirmed", "preparation") is True
        assert can_stage_transition("preparation", "execution") is True  # 跳过彩排
        assert can_stage_transition("preparation", "rehearsal") is True
        assert can_stage_transition("rehearsal", "execution") is True
        assert can_stage_transition("execution", "settlement") is True
        assert can_stage_transition("settlement", "feedback") is True
        assert can_stage_transition("feedback", "archived") is True

    def test_invalid_stage_transitions(self):
        assert can_stage_transition("lead", "contract") is False
        assert can_stage_transition("archived", "lead") is False
        assert can_stage_transition("execution", "lead") is False
        assert can_stage_transition("deposit_paid", "lead") is False

    def test_can_cancel_from_early_stages(self):
        assert can_stage_transition("lead", "cancelled") is True
        assert can_stage_transition("consultation", "cancelled") is True
        assert can_stage_transition("proposal", "cancelled") is True
        assert can_stage_transition("quotation", "cancelled") is True
        assert can_stage_transition("contract", "cancelled") is True
        # 定金后不能随便取消
        assert can_stage_transition("deposit_paid", "cancelled") is False


# ═══════════════════════════════════════════════════════════
# 12. 排队看板与历史
# ═══════════════════════════════════════════════════════════

class TestQueueBoardAndHistory:
    """排队看板和历史记录验证"""

    def test_board_reflects_current_state(self):
        svc = QueueService(tenant_id=TENANT, store_id=STORE)

        # 取5个号：2个A, 2个B, 1个C
        svc.take_number(STORE, "客1", "13800001001", 2)
        svc.take_number(STORE, "客2", "13800001002", 3)
        q3 = svc.take_number(STORE, "客3", "13800001003", 6)
        svc.take_number(STORE, "客4", "13800001004", 7)
        svc.take_number(STORE, "客5", "13800001005", 12)

        # 叫一个B桌号
        svc.call_number(q3["queue_id"])

        board = svc.get_queue_board(STORE)
        assert board["total_waiting"] == 4  # 5 - 1 called
        assert board["total_called"] == 1
        assert board["total_today"] == 5

        # A组应有2个等待
        a_group = [g for g in board["groups"] if g["prefix"] == "A"][0]
        assert a_group["waiting_count"] == 2

        # B组应有1个等待, 1个已叫
        b_group = [g for g in board["groups"] if g["prefix"] == "B"][0]
        assert b_group["waiting_count"] == 1
        assert b_group["called_count"] == 1

    def test_history_with_stats(self):
        svc = QueueService(tenant_id=TENANT, store_id=STORE)

        # 取3个号，1个入座，1个过号
        q1 = svc.take_number(STORE, "客A", "13800002001", 2)
        q2 = svc.take_number(STORE, "客B", "13800002002", 3)
        q3 = svc.take_number(STORE, "客C", "13800002003", 4)

        svc.seat_customer(q1["queue_id"], "A01")
        svc.skip_customer(q2["queue_id"], reason="no_show")

        history = svc.get_queue_history(STORE, _today_str())
        assert history["total"] == 3
        assert history["stats"]["seated"] == 1
        assert history["stats"]["skipped"] == 1
        assert history["stats"]["abandon_rate_pct"] > 0


# ═══════════════════════════════════════════════════════════
# 13. 预订时段查询
# ═══════════════════════════════════════════════════════════

class TestTimeSlots:
    """时段查询"""

    def test_get_available_time_slots(self):
        svc = ReservationService(tenant_id=TENANT, store_id=STORE)
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

        slots = svc.get_time_slots(store_id=STORE, date=tomorrow, party_size=4)
        assert len(slots) > 0

        # 所有时段都应有 available 标记
        for slot in slots:
            assert "time" in slot
            assert "available" in slot
            assert "meal" in slot

        # 应该有午餐和晚餐时段
        meals = set(s["meal"] for s in slots)
        assert "lunch" in meals
        assert "dinner" in meals


# ═══════════════════════════════════════════════════════════
# 14. 预订统计
# ═══════════════════════════════════════════════════════════

class TestReservationStats:
    """预订统计"""

    def test_stats_with_multiple_reservations(self):
        svc = ReservationService(tenant_id=TENANT, store_id=STORE)
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

        # 创建3个预订
        svc.create_reservation(STORE, "客1", "13800111001", "regular", tomorrow, "12:00", 4)
        svc.create_reservation(STORE, "客2", "13800111002", "vip", tomorrow, "12:30", 6)
        r3 = svc.create_reservation(STORE, "客3", "13800111003", "regular", tomorrow, "18:00", 3)

        # 取消一个
        svc.confirm_reservation(r3["reservation_id"])
        svc.cancel_reservation(r3["reservation_id"], reason="test")

        stats = svc.get_reservation_stats(STORE, (tomorrow, tomorrow))
        assert stats["total"] == 3
        assert stats["by_type"]["regular"] == 2
        assert stats["by_type"]["vip"] == 1
        assert stats["by_status"]["cancelled"] == 1
        assert stats["avg_party_size"] > 0
