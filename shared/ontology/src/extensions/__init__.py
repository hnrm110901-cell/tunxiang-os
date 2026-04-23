"""屯象 Ontology 扩展包（Pydantic 契约层）

按 CLAUDE.md §18 Ontology 冻结规则：
  shared/ontology/src/ 下的 SQLAlchemy Ontology（entities.py / base.py / enums.py）
  禁止自动修改；新业务的扩展契约（预订/任务/目标/宴会商机等）统一归入
  `extensions/` 子目录，以 Pydantic model 表达，供 API/Agent/投影器共用。

扩展层特征：
  - 纯 Pydantic V2，无 SQLAlchemy 依赖
  - 金额字段必须以 `_fen` 结尾且为 int
  - 所有字段必须带 Field(description=...)
  - 不持久化 Session / ORM 行为，只做契约描述

当前模块（Sprint R1）：
  customer_lifecycle — 客户四象限状态机
  tasks              — 10 类任务引擎
  sales_targets      — 年/月/周/日销售目标
  banquet_leads      — 宴会商机漏斗
"""

from .banquet_leads import (
    BanquetLead,
    BanquetLeadCreateRequest,
    BanquetLeadStageChangeRequest,
    BanquetType,
    LeadStage,
    SourceChannel,
)
from .customer_lifecycle import (
    CustomerLifecycleRecord,
    CustomerLifecycleState,
    CustomerLifecycleTransitionRequest,
)
from .sales_targets import (
    MetricType,
    PeriodType,
    SalesProgress,
    SalesTarget,
    SalesTargetCreateRequest,
)
from .tasks import (
    Task,
    TaskDispatchRequest,
    TaskDispatchResponse,
    TaskStatus,
    TaskType,
)

__all__ = [
    # customer_lifecycle
    "CustomerLifecycleState",
    "CustomerLifecycleRecord",
    "CustomerLifecycleTransitionRequest",
    # tasks
    "TaskType",
    "TaskStatus",
    "Task",
    "TaskDispatchRequest",
    "TaskDispatchResponse",
    # sales_targets
    "PeriodType",
    "MetricType",
    "SalesTarget",
    "SalesProgress",
    "SalesTargetCreateRequest",
    # banquet_leads
    "BanquetType",
    "SourceChannel",
    "LeadStage",
    "BanquetLead",
    "BanquetLeadCreateRequest",
    "BanquetLeadStageChangeRequest",
]
