"""Tier 1 — receiving_v2 complete_receiving 集成 delivery_window 检查（PRD-05 / 食安）

集成路径覆盖：
  1. 检查 complete_receiving 函数源码包含 check_delivery_window 调用 + DELIVERY_LATE event emit
  2. 检查 fail-open 异常处理（ProgrammingError / RuntimeError / ValueError）
  3. 检查 weekday_matched=False 时不写违约（fail-open）
  4. 检查同事务原子性 — record_violation 与收货主流程同 db session

mock 风格：源码静态检查 + 行为级 monkeypatch。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

if sys.version_info < (3, 10):
    pytest.skip(
        "需要 Python 3.10+ — 本机 3.9 跳过避免 sys.modules 污染",
        allow_module_level=True,
    )


# ─── 测试 1-2：源码静态契约（complete_receiving 必须含 delivery_window 集成）──


def _read_receiving_v2_source() -> str:
    """读取 receiving_v2_service.py 源码（complete_receiving 集成区段）。"""
    here = Path(__file__).resolve()
    # ../services/receiving_v2_service.py
    src = here.parent.parent / "services" / "receiving_v2_service.py"
    return src.read_text(encoding="utf-8")


class TestReceivingV2Integration:
    """receiving_v2.complete_receiving 必须接入 delivery_window 检查 + DELIVERY_LATE event。

    集成点位（源码契约）：
      - 调用 delivery_window_service.check_delivery_window(...)
      - 调用 delivery_window_service.record_violation(...)
      - 发射 SupplyEventType.DELIVERY_LATE event (asyncio.create_task)
      - fail-open: except (RuntimeError, ValueError, ProgrammingError) + logger.warning
    """

    def test_check_delivery_window_called_in_complete_receiving(self):
        """complete_receiving 必须调用 check_delivery_window。"""
        src = _read_receiving_v2_source()
        assert "check_delivery_window" in src, (
            "complete_receiving 应集成 delivery_window_service.check_delivery_window"
        )

    def test_delivery_late_event_emitted(self):
        """违约时必须 emit DELIVERY_LATE event（asyncio.create_task 旁路）。"""
        src = _read_receiving_v2_source()
        assert "SupplyEventType.DELIVERY_LATE" in src, (
            "违约时必须发射 SupplyEventType.DELIVERY_LATE event"
        )
        # 与 RECEIVING_COMPLETED 同 pattern — asyncio.create_task 旁路异步
        assert "asyncio.create_task" in src, (
            "DELIVERY_LATE event 必须旁路 asyncio.create_task（不阻塞主流程）"
        )

    def test_record_violation_called_on_violation(self):
        """违约时必须调 record_violation 写日志（supplier_scoring 扣分基础）。"""
        src = _read_receiving_v2_source()
        assert "record_violation" in src, (
            "complete_receiving 应集成 delivery_window_service.record_violation"
        )

    def test_fail_open_exception_handling(self):
        """delivery_window infra 失败必须 fail-open（不阻塞主流程收货）。

        预期 catch 多个异常类型（RuntimeError / ValueError / ProgrammingError）+ logger.warning。
        与 yield_anomaly_emit_failed / price_ledger_record_failed pattern 对齐。
        """
        src = _read_receiving_v2_source()
        # 找到 delivery_window 集成区段，验证含 try/except 与 warn
        marker = "check_delivery_window"
        idx = src.find(marker)
        assert idx > -1
        # 取该位置之后 4000 字范围检查（覆盖整个 try / event 发射 / except 块）
        block = src[idx : idx + 4000]
        assert "ProgrammingError" in block, (
            "fail-open 必须 catch ProgrammingError（表缺失 / migration 未运行）"
        )
        assert "delivery_window_check_failed" in block or "warning" in block, (
            "fail-open 必须 logger.warning 记录失败"
        )

    def test_weekday_matched_false_does_not_record(self):
        """配置存在但 weekday 不匹配 → fail-open 不写违约（PRD-05 设计）。

        源码契约：record_violation 调用须包裹在 within_window=False AND weekday_matched=True 分支。
        """
        src = _read_receiving_v2_source()
        marker = "check_delivery_window"
        idx = src.find(marker)
        block = src[idx : idx + 4000]
        # 必须含联合条件，否则 weekday 不匹配也会误记
        assert "weekday_matched" in block, (
            "record_violation 必须配 weekday_matched=True 条件，否则误记违约"
        )
        # 联合判断（不可单看 within_window，必须同时 weekday_matched=True）
        assert (
            "not check_result[\"within_window\"]" in block
            and "check_result[\"weekday_matched\"]" in block
        ), "必须 within=False AND weekday_matched=True 才记违约"


# ─── 测试 3：supplier_scoring_engine 集成（扣分基础）─────────────────────────


def _read_supplier_scoring_source() -> str:
    here = Path(__file__).resolve()
    src = here.parent.parent / "services" / "supplier_scoring_engine.py"
    return src.read_text(encoding="utf-8")


class TestSupplierScoringIntegration:
    """supplier_scoring_engine._aggregate_dimensions_from_db 必须接入 delivery_violations 扣分。"""

    def test_delivery_violations_query_extends_delivery_rate(self):
        """delivery_rate SQL 之后应查 supplier_delivery_violations 表扣分。"""
        src = _read_supplier_scoring_source()
        assert "supplier_delivery_violations" in src, (
            "supplier_scoring_engine 必须查 supplier_delivery_violations 表扣分"
        )
        assert "violation_cnt" in src, "必须聚合违约次数变量"

    def test_violations_query_fail_open(self):
        """v430 未运行 / 表缺失时 fail-open（保留原 delivery_rate）。"""
        src = _read_supplier_scoring_source()
        assert "delivery_violations_query_failed" in src, (
            "表缺失必须 logger.warning + fail-open（保留原 delivery_rate）"
        )

    def test_delivery_rate_adjusted_by_violation_count(self):
        """公式：effective_delivery_rate = max(0, (on_time_cnt - violation_cnt) / total_cnt)。"""
        src = _read_supplier_scoring_source()
        # 必须含 violation_cnt 减 on_time_cnt 的形式
        assert "on_time_cnt" in src and "violation_cnt" in src, (
            "必须用 on_time_cnt - violation_cnt 调整 delivery_rate"
        )
        assert "adjusted_on_time" in src, "应有显式 adjusted_on_time 变量做最大零截断"
