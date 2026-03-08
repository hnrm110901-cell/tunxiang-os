"""
宴会 Agent 单元测试
遵循 L001/L002：独立运行，顶部设环境变量后再 import
"""
import os
import sys
import pytest
from pathlib import Path
from datetime import date, timedelta, datetime
from unittest.mock import AsyncMock, MagicMock, patch

# L002: 先设环境变量，防止 pydantic_settings 校验失败
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")

# 添加 agent 路径
agent_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(agent_root))

from src.agent import (
    FollowupAgent, QuotationAgent, SchedulingAgent,
    ExecutionAgent, ReviewAgent,
)
from src.agent import (
    LeadStageEnum, OrderStatusEnum, TaskStatusEnum,
    BanquetHallType, BanquetTypeEnum,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

def make_lead(
    lead_id="L001",
    stage=LeadStageEnum.CONTACTED,
    last_followup_days_ago=5,
    expected_budget_fen=300000,
):
    lead = MagicMock()
    lead.id = lead_id
    lead.current_stage = stage
    lead.last_followup_at = datetime.utcnow() - timedelta(days=last_followup_days_ago)
    lead.expected_budget_fen = expected_budget_fen
    lead.expected_date = date.today() + timedelta(days=30)
    return lead


def make_order(
    order_id="O001",
    store_id="S001",
    banquet_date=None,
    people_count=50,
    table_count=5,
    status=OrderStatusEnum.CONFIRMED,
    paid_fen=0,
    total_fen=500000,
):
    order = MagicMock()
    order.id = order_id
    order.store_id = store_id
    order.banquet_date = banquet_date or (date.today() + timedelta(days=10))
    order.people_count = people_count
    order.table_count = table_count
    order.order_status = status
    order.paid_fen = paid_fen
    order.total_amount_fen = total_fen
    order.banquet_type = BanquetTypeEnum.WEDDING
    return order


def make_hall(
    hall_id="H001",
    name="一号大厅",
    hall_type=BanquetHallType.MAIN_HALL,
    max_people=200,
    min_spend_fen=50000,
    is_active=True,
):
    hall = MagicMock()
    hall.id = hall_id
    hall.name = name
    hall.hall_type = hall_type
    hall.max_people = max_people
    hall.max_tables = 20
    hall.min_spend_fen = min_spend_fen
    hall.is_active = is_active
    return hall


def make_package(
    pkg_id="P001",
    name="婚宴标准套餐",
    price_fen=68800,
    cost_fen=30000,
    people_min=30,
    people_max=100,
    banquet_type=BanquetTypeEnum.WEDDING,
):
    pkg = MagicMock()
    pkg.id = pkg_id
    pkg.name = name
    pkg.suggested_price_fen = price_fen
    pkg.cost_fen = cost_fen
    pkg.target_people_min = people_min
    pkg.target_people_max = people_max
    pkg.banquet_type = banquet_type
    pkg.is_active = True
    return pkg


# ─── FollowupAgent ───────────────────────────────────────────────────────────

class TestFollowupAgent:
    @pytest.fixture
    def agent(self):
        return FollowupAgent()

    @pytest.mark.asyncio
    async def test_scan_stale_leads_returns_stale(self, agent):
        """超过3天未跟进的线索应出现在扫描结果中"""
        stale_lead = make_lead(last_followup_days_ago=5)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[stale_lead])))))

        results = await agent.scan_stale_leads(store_id="S001", db=db, dry_run=True)

        assert len(results) == 1
        assert results[0]["lead_id"] == "L001"
        assert results[0]["days_stale"] == 5
        assert "跟进提醒" in results[0]["suggestion"]

    @pytest.mark.asyncio
    async def test_scan_empty_store(self, agent):
        """无停滞线索时返回空列表"""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))

        results = await agent.scan_stale_leads(store_id="S001", db=db, dry_run=True)
        assert results == []

    @pytest.mark.asyncio
    async def test_dry_run_does_not_commit(self, agent):
        """dry_run=True 时不应调用 db.commit"""
        lead = make_lead(last_followup_days_ago=4)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[lead])))))

        await agent.scan_stale_leads(store_id="S001", db=db, dry_run=True)
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_suggestion_contains_yuan_amount(self, agent):
        """提醒文本应包含¥预算信息（Rule 6）"""
        lead = make_lead(expected_budget_fen=500000)  # ¥5000
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[lead])))))

        results = await agent.scan_stale_leads(store_id="S001", db=db, dry_run=True)
        assert "5000" in results[0]["suggestion"] or "¥" in results[0]["suggestion"]

    def test_stale_days_constant(self, agent):
        assert agent.STALE_DAYS == 3


# ─── QuotationAgent ──────────────────────────────────────────────────────────

class TestQuotationAgent:
    @pytest.fixture
    def agent(self):
        return QuotationAgent()

    @pytest.mark.asyncio
    async def test_recommend_returns_sorted_by_margin(self, agent):
        """套餐推荐应按毛利率降序排列"""
        pkg_high = make_package("P001", price_fen=100000, cost_fen=30000)   # 70%
        pkg_low  = make_package("P002", price_fen=100000, cost_fen=70000)   # 30%
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[pkg_high, pkg_low])))))

        result = await agent.recommend_packages(
            store_id="S001", people_count=50, budget_fen=6000000, banquet_type=None, db=db
        )
        pkgs = result["recommended_packages"]
        assert len(pkgs) == 2
        assert pkgs[0]["gross_margin_pct"] >= pkgs[1]["gross_margin_pct"]

    @pytest.mark.asyncio
    async def test_recommend_includes_yuan_profit(self, agent):
        """推荐结果必须包含¥毛利字段（Rule 6）"""
        pkg = make_package("P001", price_fen=68800, cost_fen=30000)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[pkg])))))

        result = await agent.recommend_packages(
            store_id="S001", people_count=50, budget_fen=5000000, banquet_type=None, db=db
        )
        pkg_result = result["recommended_packages"][0]
        assert "estimated_gross_profit_yuan" in pkg_result
        assert pkg_result["estimated_gross_profit_yuan"] > 0

    @pytest.mark.asyncio
    async def test_recommend_empty_returns_fallback_suggestion(self, agent):
        """无匹配套餐时返回自定义菜单建议"""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))

        result = await agent.recommend_packages(
            store_id="S001", people_count=50, budget_fen=100000, banquet_type=None, db=db
        )
        assert result["recommended_packages"] == []
        assert "自定义" in result["suggestion"]

    @pytest.mark.asyncio
    async def test_max_5_candidates(self, agent):
        """最多返回5个候选套餐"""
        pkgs = [make_package(f"P{i:03d}") for i in range(8)]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=pkgs)))))

        result = await agent.recommend_packages(
            store_id="S001", people_count=50, budget_fen=9999999, banquet_type=None, db=db
        )
        assert len(result["recommended_packages"]) <= 5


# ─── SchedulingAgent ─────────────────────────────────────────────────────────

class TestSchedulingAgent:
    @pytest.fixture
    def agent(self):
        return SchedulingAgent()

    @pytest.mark.asyncio
    async def test_available_halls_excludes_booked(self, agent):
        """已预订厅房不出现在可用列表"""
        hall1 = make_hall("H001")
        hall2 = make_hall("H002")

        execute_results = [
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[hall1, hall2])))),
            MagicMock(fetchall=MagicMock(return_value=[("H001",)])),   # H001 已预订
        ]
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=execute_results)

        result = await agent.recommend_halls(
            store_id="S001", target_date=date.today(), slot_name="dinner", people_count=50, db=db
        )
        available_ids = [h["hall_id"] for h in result["available_halls"]]
        conflicted_ids = [h["hall_id"] for h in result["conflicted_halls"]]
        assert "H001" not in available_ids
        assert "H001" in conflicted_ids
        assert "H002" in available_ids

    @pytest.mark.asyncio
    async def test_all_halls_booked_warning_suggestion(self, agent):
        """全部厅房被占用时提示更换时段"""
        hall = make_hall("H001", max_people=200)
        execute_results = [
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[hall])))),
            MagicMock(fetchall=MagicMock(return_value=[("H001",)])),
        ]
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=execute_results)

        result = await agent.recommend_halls(
            store_id="S001", target_date=date.today(), slot_name="lunch", people_count=50, db=db
        )
        assert result["available_halls"] == []
        assert "更换" in result["suggestion"] or "满" in result["suggestion"]

    @pytest.mark.asyncio
    async def test_people_count_filter(self, agent):
        """容量不足的厅房不出现在可用列表"""
        small_hall = make_hall("H001", max_people=20)  # 容量不足
        big_hall   = make_hall("H002", max_people=200)
        execute_results = [
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[big_hall])))),  # 小厅被过滤
            MagicMock(fetchall=MagicMock(return_value=[])),
        ]
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=execute_results)

        result = await agent.recommend_halls(
            store_id="S001", target_date=date.today(), slot_name="dinner", people_count=50, db=db
        )
        assert any(h["hall_id"] == "H002" for h in result["available_halls"])

    @pytest.mark.asyncio
    async def test_min_spend_in_response(self, agent):
        """最低消费¥字段应出现在可用厅房信息中"""
        hall = make_hall("H001", min_spend_fen=100000)  # ¥1000
        execute_results = [
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[hall])))),
            MagicMock(fetchall=MagicMock(return_value=[])),
        ]
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=execute_results)

        result = await agent.recommend_halls(
            store_id="S001", target_date=date.today(), slot_name="dinner", people_count=50, db=db
        )
        assert result["available_halls"][0]["min_spend_yuan"] == 1000.0


# ─── ExecutionAgent ───────────────────────────────────────────────────────────

class TestExecutionAgent:
    @pytest.fixture
    def agent(self):
        return ExecutionAgent()

    @pytest.mark.asyncio
    async def test_generates_default_7_tasks(self, agent):
        """无自定义模板时应生成默认7个任务"""
        order = make_order()
        db = AsyncMock()
        # count = 0 (无已有任务)，no template
        count_result = MagicMock(scalar=MagicMock(return_value=0))
        template_result = MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None))))
        db.execute = AsyncMock(side_effect=[count_result, template_result])
        db.add = MagicMock()
        db.commit = AsyncMock()

        tasks = await agent.generate_tasks_for_order(order=order, db=db)
        assert len(tasks) == len(agent.DEFAULT_TASK_DEFS)

    @pytest.mark.asyncio
    async def test_idempotent_no_duplicate(self, agent):
        """已有任务时不重复生成（幂等）"""
        order = make_order()
        db = AsyncMock()
        count_result = MagicMock(scalar=MagicMock(return_value=5))  # 已有5个任务
        db.execute = AsyncMock(return_value=count_result)

        tasks = await agent.generate_tasks_for_order(order=order, db=db)
        assert tasks == []
        db.add.assert_not_called() if hasattr(db, 'add') else None

    @pytest.mark.asyncio
    async def test_tasks_due_before_banquet(self, agent):
        """所有任务的到期时间应在宴会日期之前"""
        order = make_order(banquet_date=date.today() + timedelta(days=14))
        db = AsyncMock()
        count_result = MagicMock(scalar=MagicMock(return_value=0))
        template_result = MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None))))
        db.execute = AsyncMock(side_effect=[count_result, template_result])
        db.add = MagicMock()
        db.commit = AsyncMock()

        tasks = await agent.generate_tasks_for_order(order=order, db=db)
        banquet_dt = datetime.combine(order.banquet_date, datetime.min.time())
        for task in tasks:
            assert task.due_time <= banquet_dt

    @pytest.mark.asyncio
    async def test_all_tasks_pending_status(self, agent):
        """新生成的任务状态均为 PENDING"""
        order = make_order()
        db = AsyncMock()
        count_result = MagicMock(scalar=MagicMock(return_value=0))
        template_result = MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None))))
        db.execute = AsyncMock(side_effect=[count_result, template_result])
        db.add = MagicMock()
        db.commit = AsyncMock()

        tasks = await agent.generate_tasks_for_order(order=order, db=db)
        for task in tasks:
            assert task.task_status == TaskStatusEnum.PENDING


# ─── ReviewAgent ─────────────────────────────────────────────────────────────

class TestReviewAgent:
    @pytest.fixture
    def agent(self):
        return ReviewAgent()

    @pytest.mark.asyncio
    async def test_review_contains_yuan_fields(self, agent):
        """复盘结果必须包含¥收入和¥利润字段（Rule 6）"""
        order = make_order(status=OrderStatusEnum.COMPLETED, paid_fen=500000)
        snap = MagicMock()
        snap.revenue_fen = 500000
        snap.gross_profit_fen = 150000
        snap.gross_margin_pct = 30.0

        db = AsyncMock()
        snap_result = MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=snap))))
        overdue_result = MagicMock(scalar=MagicMock(return_value=0))
        db.execute = AsyncMock(side_effect=[snap_result, overdue_result])
        db.add = MagicMock()
        db.commit = AsyncMock()

        result = await agent.generate_review(order=order, db=db)
        assert result["revenue_yuan"] == 5000.0
        assert result["gross_profit_yuan"] == 1500.0
        assert result["gross_margin_pct"] == 30.0

    @pytest.mark.asyncio
    async def test_review_text_contains_yuan(self, agent):
        """复盘文本应包含¥金额"""
        order = make_order(status=OrderStatusEnum.COMPLETED, paid_fen=500000)
        snap = MagicMock(revenue_fen=500000, gross_profit_fen=150000, gross_margin_pct=30.0)
        db = AsyncMock()
        snap_result = MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=snap))))
        overdue_result = MagicMock(scalar=MagicMock(return_value=0))
        db.execute = AsyncMock(side_effect=[snap_result, overdue_result])
        db.add = MagicMock()
        db.commit = AsyncMock()

        result = await agent.generate_review(order=order, db=db)
        assert "¥" in result["review_text"]

    @pytest.mark.asyncio
    async def test_overdue_tasks_mentioned_in_review(self, agent):
        """有逾期任务时复盘文本应提示"""
        order = make_order(status=OrderStatusEnum.COMPLETED, paid_fen=500000)
        snap = MagicMock(revenue_fen=500000, gross_profit_fen=100000, gross_margin_pct=20.0)
        db = AsyncMock()
        snap_result = MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=snap))))
        overdue_result = MagicMock(scalar=MagicMock(return_value=3))  # 3个逾期
        db.execute = AsyncMock(side_effect=[snap_result, overdue_result])
        db.add = MagicMock()
        db.commit = AsyncMock()

        result = await agent.generate_review(order=order, db=db)
        assert result["overdue_task_count"] == 3
        assert "逾期" in result["review_text"] or "3" in result["review_text"]

    @pytest.mark.asyncio
    async def test_no_snapshot_falls_back_to_paid(self, agent):
        """无利润快照时回退到 paid_fen 作为收入"""
        order = make_order(status=OrderStatusEnum.COMPLETED, paid_fen=300000)
        db = AsyncMock()
        snap_result = MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None))))
        overdue_result = MagicMock(scalar=MagicMock(return_value=0))
        db.execute = AsyncMock(side_effect=[snap_result, overdue_result])
        db.add = MagicMock()
        db.commit = AsyncMock()

        result = await agent.generate_review(order=order, db=db)
        assert result["revenue_yuan"] == 3000.0

    def test_review_text_builder(self):
        """_build_review_text 纯函数测试"""
        order = make_order(people_count=80, table_count=8)
        text = ReviewAgent._build_review_text(
            order=order,
            revenue_yuan=8000.0,
            gross_profit_yuan=2400.0,
            margin_pct=30.0,
            overdue_count=0,
        )
        assert "¥8000" in text
        assert "30.0%" in text
        assert "按时完成" in text
