"""Phase C.1 (#820) — APScheduler EVENT_JOB_EXECUTED + EVENT_JOB_ERROR listener 单测。

测试目标:
  1. EVENT_JOB_EXECUTED (exception=None) → status="success" + Counter.labels(...).inc() 调用一次
  2. EVENT_JOB_ERROR (exception=Exception(...)) → status="error" + Counter.labels(...).inc() 调用一次
  3. job_id 正确传递到 labels
  4. Counter 名字 + label schema 防漂移

测试策略 (helper-only test 模式 per feedback_helper_only_test_for_import_blocked_module.md):
  - 直接 import services.gateway.src.apscheduler_metrics (轻量, 仅依赖 prometheus_client)
  - 避开 services.gateway.src.main 的重量级 import 链 (prometheus_fastapi_instrumentator /
    全 middleware / 30+ router), 这些在 CI 装包 + 在本测试无关
  - 用 SimpleNamespace mock APScheduler event (只需 job_id + exception 两个属性)
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _repo_root() -> Path:
    # .../services/gateway/src/tests/this_file.py -> parents[4] = 仓库根
    return Path(__file__).resolve().parents[4]


# 确保 sys.path 含仓库根
_root = str(_repo_root())
if _root not in sys.path:
    sys.path.insert(0, _root)


def test_listener_event_executed_records_success() -> None:
    """EVENT_JOB_EXECUTED (exception=None) → Counter status=success inc."""
    from services.gateway.src import apscheduler_metrics as m

    event = SimpleNamespace(job_id="wecom_group_daily_sop", exception=None)

    with patch.object(m, "apscheduler_jobs_executed_total") as mock_counter:
        mock_labels = MagicMock()
        mock_counter.labels.return_value = mock_labels

        m.apscheduler_job_listener(event)

        mock_counter.labels.assert_called_once_with(
            job_id="wecom_group_daily_sop", status="success"
        )
        mock_labels.inc.assert_called_once_with()


def test_listener_event_error_records_error() -> None:
    """EVENT_JOB_ERROR (exception=Exception) → Counter status=error inc."""
    from services.gateway.src import apscheduler_metrics as m

    event = SimpleNamespace(
        job_id="daily_dishes_sync", exception=RuntimeError("db down")
    )

    with patch.object(m, "apscheduler_jobs_executed_total") as mock_counter:
        mock_labels = MagicMock()
        mock_counter.labels.return_value = mock_labels

        m.apscheduler_job_listener(event)

        mock_counter.labels.assert_called_once_with(
            job_id="daily_dishes_sync", status="error"
        )
        mock_labels.inc.assert_called_once_with()


def test_listener_real_counter_increments() -> None:
    """端到端验证: 用真 Counter (不 mock), 两个 event 后 _value 累加。

    此测试防御 Counter 类型/标签结构回归 (如 labels signature 改).
    """
    from services.gateway.src import apscheduler_metrics as m

    success_event = SimpleNamespace(
        job_id="hourly_orders_incremental_sync", exception=None
    )
    error_event = SimpleNamespace(
        job_id="hourly_orders_incremental_sync", exception=ValueError("api 500")
    )

    success_counter = m.apscheduler_jobs_executed_total.labels(
        job_id="hourly_orders_incremental_sync", status="success"
    )
    error_counter = m.apscheduler_jobs_executed_total.labels(
        job_id="hourly_orders_incremental_sync", status="error"
    )

    before_success = success_counter._value.get()
    before_error = error_counter._value.get()

    m.apscheduler_job_listener(success_event)
    m.apscheduler_job_listener(error_event)

    assert success_counter._value.get() == before_success + 1
    assert error_counter._value.get() == before_error + 1


def test_counter_metric_name_and_labels_shape() -> None:
    """Counter 名字 + label 名 schema 防漂移。

    注意: prometheus_client Counter 内部 _name 自动剥 `_total` suffix (序列化时回填),
    所以 assert "apscheduler_jobs_executed" (不带 _total) 是合规预期。
    """
    from services.gateway.src import apscheduler_metrics as m

    # prometheus_client Counter 暴露 _name (剥后) + _labelnames
    assert m.apscheduler_jobs_executed_total._name == "apscheduler_jobs_executed"
    assert tuple(m.apscheduler_jobs_executed_total._labelnames) == ("job_id", "status")

    # 验证序列化时 _total 后缀回填 (scrape 端实际暴露的 metric 名)
    samples = list(m.apscheduler_jobs_executed_total.collect())
    assert len(samples) == 1
    family_name = samples[0].name
    # samples[0].name 是无 _total 的 base name; samples[0].samples[*].name 才带 _total
    assert family_name == "apscheduler_jobs_executed"
