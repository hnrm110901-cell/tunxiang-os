"""屯象OS observability helper — Prometheus metrics setup 统一入口。

Phase C.3 (#820) 抽取。已装 Instrumentator 的 22 service 渐进迁移到本 helper
(逐 PR 推进, follow-up issue #820-I 跟踪)。
"""

from .metrics import setup_metrics

__all__ = ["setup_metrics"]
