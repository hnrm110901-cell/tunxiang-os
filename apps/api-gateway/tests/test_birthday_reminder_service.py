"""
BirthdayReminderService 单元测试

覆盖：
  - scan_upcoming_events 返回生日/周年事件
  - 当 birth_date=None 时不返回生日事件
  - 当注册不足1年时不返回周年事件（SQL WHERE 保证）
  - DB 异常时返回空列表，不抛出
  - 结果按 days_until 升序排列
  - BUILTIN_JOURNEYS 包含 birthday_greeting / anniversary_greeting
  - beat_schedule 包含 trigger-birthday-reminders（10:00）
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("APP_ENV", "test")

from unittest.mock import AsyncMock, MagicMock, patch
import pytest


# ════════════════════════════════════════════════════════════════════════════
# 辅助工厂
# ════════════════════════════════════════════════════════════════════════════

def _make_row(customer_id, store_id, wechat_openid, event_type, days_until):
    """模拟 SQLAlchemy Row（5元素序列）。"""
    row = MagicMock()
    row.__getitem__ = lambda self, i: (
        customer_id, store_id, wechat_openid, event_type, days_until
    )[i]
    return row


# ════════════════════════════════════════════════════════════════════════════
# UpcomingEvent 数据类
# ════════════════════════════════════════════════════════════════════════════

class TestUpcomingEvent:
    def test_fields(self):
        from src.services.birthday_reminder_service import UpcomingEvent
        ev = UpcomingEvent(
            customer_id="C001",
            store_id="S001",
            wechat_openid="wx001",
            event_type="birthday",
            days_until=2,
        )
        assert ev.customer_id == "C001"
        assert ev.event_type == "birthday"
        assert ev.days_until == 2

    def test_anniversary_event_type(self):
        from src.services.birthday_reminder_service import UpcomingEvent
        ev = UpcomingEvent("C002", "S001", None, "anniversary", 0)
        assert ev.event_type == "anniversary"
        assert ev.wechat_openid is None


# ════════════════════════════════════════════════════════════════════════════
# scan_upcoming_events
# ════════════════════════════════════════════════════════════════════════════

class TestScanUpcomingEvents:

    @pytest.mark.asyncio
    async def test_returns_birthday_events(self):
        """生日查询返回行时，结果包含 birthday 事件。"""
        from src.services.birthday_reminder_service import BirthdayReminderService

        birthday_row = _make_row("C001", "S001", "wx001", "birthday", 1)
        db = AsyncMock()
        # 第一次 execute = 生日查询，第二次 = 周年查询
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(fetchall=MagicMock(return_value=[birthday_row])),
                MagicMock(fetchall=MagicMock(return_value=[])),
            ]
        )

        svc = BirthdayReminderService()
        events = await svc.scan_upcoming_events("S001", db, horizon_days=3)

        assert len(events) == 1
        assert events[0].customer_id == "C001"
        assert events[0].event_type == "birthday"
        assert events[0].days_until == 1

    @pytest.mark.asyncio
    async def test_returns_anniversary_events(self):
        """周年查询返回行时，结果包含 anniversary 事件。"""
        from src.services.birthday_reminder_service import BirthdayReminderService

        ann_row = _make_row("C002", "S001", None, "anniversary", 0)
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(fetchall=MagicMock(return_value=[])),
                MagicMock(fetchall=MagicMock(return_value=[ann_row])),
            ]
        )

        svc = BirthdayReminderService()
        events = await svc.scan_upcoming_events("S001", db)

        assert len(events) == 1
        assert events[0].event_type == "anniversary"
        assert events[0].wechat_openid is None

    @pytest.mark.asyncio
    async def test_mixed_events_sorted_by_days_until(self):
        """同时有生日(days=2)和周年(days=0)事件时，周年排在前面。"""
        from src.services.birthday_reminder_service import BirthdayReminderService

        b_row = _make_row("C001", "S001", "wx1", "birthday",    2)
        a_row = _make_row("C002", "S001", "wx2", "anniversary", 0)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(fetchall=MagicMock(return_value=[b_row])),
                MagicMock(fetchall=MagicMock(return_value=[a_row])),
            ]
        )

        svc = BirthdayReminderService()
        events = await svc.scan_upcoming_events("S001", db)

        assert len(events) == 2
        assert events[0].days_until == 0   # 周年(今天)排前
        assert events[1].days_until == 2   # 生日(后天)排后

    @pytest.mark.asyncio
    async def test_empty_when_no_upcoming(self):
        """无即将到来的事件时返回空列表。"""
        from src.services.birthday_reminder_service import BirthdayReminderService

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(fetchall=MagicMock(return_value=[])),
                MagicMock(fetchall=MagicMock(return_value=[])),
            ]
        )

        svc = BirthdayReminderService()
        events = await svc.scan_upcoming_events("S001", db)
        assert events == []

    @pytest.mark.asyncio
    async def test_birthday_query_exception_returns_partial(self):
        """生日查询出错时，周年结果仍正常返回（不中断）。"""
        from src.services.birthday_reminder_service import BirthdayReminderService

        ann_row = _make_row("C002", "S001", None, "anniversary", 1)
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                Exception("DB error"),
                MagicMock(fetchall=MagicMock(return_value=[ann_row])),
            ]
        )

        svc = BirthdayReminderService()
        events = await svc.scan_upcoming_events("S001", db)

        assert len(events) == 1
        assert events[0].event_type == "anniversary"

    @pytest.mark.asyncio
    async def test_both_queries_fail_returns_empty(self):
        """两次查询均出错时返回空列表，不抛出。"""
        from src.services.birthday_reminder_service import BirthdayReminderService

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=Exception("DB down"))

        svc = BirthdayReminderService()
        events = await svc.scan_upcoming_events("S001", db)
        assert events == []


# ════════════════════════════════════════════════════════════════════════════
# BUILTIN_JOURNEYS 完整性
# ════════════════════════════════════════════════════════════════════════════

class TestBuiltinJourneys:

    def test_birthday_greeting_defined(self):
        from src.services.journey_orchestrator import BUILTIN_JOURNEYS
        defn = BUILTIN_JOURNEYS["birthday_greeting"]
        assert defn.journey_id == "birthday_greeting"
        assert len(defn.steps) == 1
        assert defn.steps[0].template_id == "birthday_wish"

    def test_anniversary_greeting_defined(self):
        from src.services.journey_orchestrator import BUILTIN_JOURNEYS
        defn = BUILTIN_JOURNEYS["anniversary_greeting"]
        assert defn.journey_id == "anniversary_greeting"
        assert len(defn.steps) == 1
        assert defn.steps[0].template_id == "anniversary_wish"

    def test_all_six_journeys_present(self):
        from src.services.journey_orchestrator import BUILTIN_JOURNEYS
        expected = {
            "member_activation", "first_order_conversion",
            "dormant_wakeup", "proactive_remind",
            "birthday_greeting", "anniversary_greeting",
        }
        assert expected.issubset(BUILTIN_JOURNEYS.keys())


# ════════════════════════════════════════════════════════════════════════════
# journey_narrator fallback templates
# ════════════════════════════════════════════════════════════════════════════

class TestNarratorBirthdayTemplates:

    @pytest.mark.asyncio
    async def test_birthday_wish_fallback(self):
        from src.services.journey_narrator import JourneyNarrator, _FALLBACK_TEMPLATES
        assert "birthday_wish" in _FALLBACK_TEMPLATES
        narrator = JourneyNarrator(llm=None)
        result = await narrator.generate(
            template_id="birthday_wish",
            store_id="S001",
            customer_id="C001",
        )
        assert result == _FALLBACK_TEMPLATES["birthday_wish"]

    @pytest.mark.asyncio
    async def test_anniversary_wish_fallback(self):
        from src.services.journey_narrator import JourneyNarrator, _FALLBACK_TEMPLATES
        assert "anniversary_wish" in _FALLBACK_TEMPLATES
        narrator = JourneyNarrator(llm=None)
        result = await narrator.generate(
            template_id="anniversary_wish",
            store_id="S001",
            customer_id="C001",
        )
        assert result == _FALLBACK_TEMPLATES["anniversary_wish"]


# ════════════════════════════════════════════════════════════════════════════
# Beat schedule
# ════════════════════════════════════════════════════════════════════════════

class TestBeatSchedule:

    def test_birthday_reminders_in_beat_schedule(self):
        """trigger-birthday-reminders 已注册到 Celery beat，10:00 执行。"""
        with patch.dict(os.environ, {"DATABASE_URL": "sqlite+aiosqlite:///:memory:"}):
            from src.core.celery_app import celery_app
            schedule = celery_app.conf.beat_schedule
            assert "trigger-birthday-reminders" in schedule
            entry = schedule["trigger-birthday-reminders"]
            assert entry["task"] == "src.core.celery_tasks.trigger_birthday_reminders"
            # crontab: hour=10, minute=0
            cron = entry["schedule"]
            assert cron.hour == {10}
            assert cron.minute == {0}
