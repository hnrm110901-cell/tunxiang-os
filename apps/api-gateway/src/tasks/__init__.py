"""Celery 任务模块 — 按域组织的定时任务集合

健康证/劳动合同等合规扫描任务。
在 celery_app.autodiscover_tasks(["src.tasks"]) 中被自动发现。
"""

from . import health_cert_tasks, labor_contract_tasks  # noqa: F401
