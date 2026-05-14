"""回归测试: tx-growth main._run_calendar_trigger_check structlog kwarg 冲突 (Issue #585)

PR #574 / #581 / #583 同模式 cross-service follow-up 最后一例.

修前 (origin/main `c7a51ea1` 之前):
  L501-506: logger.info("calendar_trigger_suggestion",
                event=trigger["event_name"], action=..., description=...)
  → structlog 把第一个 positional 当 event_name 字段（保留字段 'event'）,
    payload 又传 `event=` kwarg → TypeError(multiple values for 'event').

修后:
  payload kwarg rename → `trigger_event=trigger["event_name"]` 避免冲突.

业务场景（营销日历 trigger 周期性任务）:
  _run_calendar_trigger_check 每日早 8 点检查日历表 due trigger,
  为每个 trigger 生成 Agent 营销建议（不直接执行旅程，走审核流）.

修前: trigger 列表非空时（任何节日 / 店庆日触发）, L501 logger.info 抛 TypeError
  → 整个 for-loop 中断 → 同批 trigger 全部丢失 → Agent 营销建议生成丢失

归 P2/P3: 周期性任务, 下次周期重试; 但单批 trigger 共享 loop, 单个异常让全批丢失.

测试策略说明:
  main.py 顶层 import 链拖 apscheduler / httpx / fastapi / 众多 service modules,
  本地完整 unit test 需 venv + tx-growth requirements.lock 重装. 为绕开依赖链
  污染（feedback_pytest_stub_setdefault_pitfall 教训），本测试用 2 层验证:

  Layer 1 (源码静态校验): grep 主 src 文件 main.py L501-506, 锁定 `trigger_event=`
    kwarg 出现 + `event=trigger` 旧 pattern 已消除. 锁住 fix 不被误回滚.

  Layer 2 (structlog 行为校验): 直接构造同 pattern call site (lambda),
    断言 trigger_event=... 不抛 TypeError + capture_logs 字段含值正确,
    回归 PR #574 / #581 / #583 同 root cause.
"""

from __future__ import annotations

import os
import re


# ── 路径 ──────────────────────────────────────────────────────────────────────
SRC_MAIN = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "main.py")
)


class TestCalendarTriggerSuggestionSourceCode:
    """Layer 1: 源码静态校验 — 锁住 fix 不被误回滚."""

    def test_main_source_uses_trigger_event_kwarg(self):
        """main.py L501-506 calendar_trigger_suggestion logger.info 必须用
        `trigger_event=` 字段名, 不得有 `event=trigger` 旧 pattern."""
        with open(SRC_MAIN, encoding="utf-8") as f:
            source = f.read()

        # 必须含修后 pattern
        assert re.search(
            r'logger\.info\(\s*\n?\s*"calendar_trigger_suggestion"\s*,\s*\n?\s*trigger_event=',
            source,
        ), (
            "main.py 中 calendar_trigger_suggestion logger.info 必须用 trigger_event=, "
            "不得回滚到 event=trigger 旧 pattern"
        )

        # 必须不含旧 pattern (避回滚)
        assert not re.search(
            r'logger\.info\(\s*\n?\s*"calendar_trigger_suggestion"\s*,\s*\n?\s*event=trigger',
            source,
        ), (
            "main.py 中 calendar_trigger_suggestion logger.info 旧 `event=trigger` "
            "pattern 仍存在 → fix 未生效或被回滚"
        )


class TestCalendarTriggerSuggestionStructlogBehavior:
    """Layer 2: structlog 行为校验 — 同 PR #574 / #581 / #583 模式."""

    def test_structlog_with_trigger_event_kwarg_no_typeerror(self):
        """同 PR #574 模式: structlog.info(event_name_positional, trigger_event=...)
        修后不抛 TypeError (旧 pattern event= 会抛)."""
        import structlog

        logger = structlog.get_logger(__name__)
        # 修后 pattern - 不抛
        logger.info(
            "calendar_trigger_suggestion",
            trigger_event="母亲节",
            action="promote_cake",
            description="母亲节促销建议",
        )

    def test_structlog_with_event_kwarg_raises_typeerror(self):
        """反向回归: 旧 pattern event=trigger['event_name'] 必须抛 TypeError,
        证明 root cause 是 structlog 保留字段冲突 (与 PR #574 / #581 / #583 同 bug)."""
        import structlog

        logger = structlog.get_logger(__name__)
        try:
            logger.info(
                "calendar_trigger_suggestion",
                event="母亲节",
                action="promote_cake",
            )
            raise AssertionError("旧 pattern event= 应抛 TypeError")
        except TypeError as exc:
            assert "event" in str(exc), f"TypeError 应含 'event' 字段冲突信息: {exc!r}"

    def test_structlog_capture_logs_trigger_event_field_preserved(self):
        """capture_logs 断言 log 含 trigger_event=<event_name> + event=event_name."""
        import structlog
        from structlog.testing import capture_logs

        logger = structlog.get_logger(__name__)
        with capture_logs() as logs:
            logger.info(
                "calendar_trigger_suggestion",
                trigger_event="店庆日",
                action="vip_invite",
                description="门店周年庆",
            )

        suggestion_logs = [
            log for log in logs if log.get("event") == "calendar_trigger_suggestion"
        ]
        assert len(suggestion_logs) == 1
        entry = suggestion_logs[0]
        assert entry.get("trigger_event") == "店庆日"
        assert entry.get("action") == "vip_invite"
        assert entry.get("description") == "门店周年庆"
        assert entry["event"] == "calendar_trigger_suggestion"
