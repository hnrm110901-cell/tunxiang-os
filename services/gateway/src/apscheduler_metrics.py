"""Phase C.1 (#820) — APScheduler → Prometheus 桥接模块。

tx-sync-worker/src/jobs/pinzhi_sync.py:435 同名 metric 已存在但 gateway 0 listener →
监控盲区: czyz/zqx/sgc daily sync + wecom_group_daily_sop 跑不跑没人知道。

修法: 加 EVENT_JOB_EXECUTED + EVENT_JOB_ERROR listener, 真 inc Counter (job_id, status)。

抽到独立 module 而非内嵌 main.py: 避免单测被 main.py 的重量级 import 链 (prometheus_fastapi_instrumentator /
全 middleware / 30+ router) 阻塞 (per feedback_helper_only_test_for_import_blocked_module.md)。
main.py 仍持有引用方便 startup hook add_listener。
"""

from __future__ import annotations

from prometheus_client import Counter

apscheduler_jobs_executed_total = Counter(
    "apscheduler_jobs_executed_total",
    "APScheduler job execution count (gateway scheduler)",
    ["job_id", "status"],
)


def apscheduler_job_listener(event) -> None:
    """EVENT_JOB_EXECUTED + EVENT_JOB_ERROR 监听器 — 桥接到 Prometheus Counter。

    event.exception is None → status=success
    event.exception not None → status=error
    """
    status = "error" if event.exception else "success"
    apscheduler_jobs_executed_total.labels(
        job_id=event.job_id, status=status
    ).inc()
