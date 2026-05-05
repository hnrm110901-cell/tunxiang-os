"""v398 — 收敛 35 个历史 alembic head 到单一主链 [PI.2]

主分支自 v264 起出现大量并列 b-suffix 分支（v264b/v264c/v265b/v266b/...），
每条分支独立向前推进，从未合并；加上若干 c-suffix 与 _<feature> 后缀分支，
共 35 个 dangling head 同时存在。任何环境跑 `alembic upgrade head` 都拒绝执行。

PG.1.1 的 v397 已合并 v393_sync_checkpoints_token + v396 双 head（业务 + 安全
两条主线），但更老的 b-suffix 分支群从未收敛。本 migration 一次性收敛剩余
**34 个 head + v397** = 35 个 head 到单一节点 v398。

合并方式：alembic 标准 merge migration。
  down_revision 为 35 元素元组，alembic 视为合并节点；upgrade/downgrade 均为 no-op
  （纯链路收敛，不改 schema）。合并后唯一 head = v398，v399+ down_revision 直接指 v398。

风险与缓解：
  - 风险 1：35 条分支若各自 upgrade 顺序敏感，alembic 选择的拓扑序可能触发
    schema 冲突（如同名表先后定义）。已抽查 b-suffix 分支多为独立功能模块
    （customer_lifecycle / agent_decision_logs / financial_vouchers_sync_orm 等），
    table 命名不冲突。
  - 风险 2：所有 dangling 分支在生产库的 alembic_version 历史里可能已部分应用，
    但因 head 不可达，`upgrade head` 一直失败。本 v398 不改 schema 但让 head
    可达，回滚链路一次性建立。
  - 风险 3：CI alembic-multiple-heads gate（PJ.5 加的）此前未生效（v397 之前），
    现在 head 收敛后 gate 可继续锁定 head ≤ 5 防再分叉（独立 PR）。

收敛的 35 个 head（按字母序）：
  v264b, v264c, v265b, v266_rfm_outreach, v266b, v267b, v268b, v270b,
  v272b, v274b, v276b, v277_campaign_roi, v278_dish_pricing, v278b,
  v279_cost_root_cause, v280, v281_budget_forecast, v281b, v282b,
  v283_banquet_schedule_lock, v286b, v287b, v288b, v290_ab_experiments,
  v290b, v294, v296b, v297, v298, v304, v310, v311, v330_reputation_alerts,
  v387, v397

Revision ID: v398
Revises: (35 个 head — 见 down_revision 元组)
Create Date: 2026-05-05
"""

from typing import Sequence, Union

revision: str = "v398"
down_revision: Union[str, Sequence[str], None] = (
    "v264b",
    "v264c",
    "v265b",
    "v266_rfm_outreach",
    "v266b",
    "v267b",
    "v268b",
    "v270b",
    "v272b",
    "v274b",
    "v276b",
    "v277_campaign_roi",
    "v278_dish_pricing",
    "v278b",
    "v279_cost_root_cause",
    "v280",
    "v281_budget_forecast",
    "v281b",
    "v282b",
    "v283_banquet_schedule_lock",
    "v286b",
    "v287b",
    "v288b",
    "v290_ab_experiments",
    "v290b",
    "v294",
    "v296b",
    "v297",
    "v298",
    "v304",
    "v310",
    "v311",
    "v330_reputation_alerts",
    "v387",
    "v397",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """纯合并节点 — 无 schema 变更"""
    pass


def downgrade() -> None:
    """合并节点 downgrade 等价 no-op — 拆回 35 个 head 由 alembic 自动处理"""
    pass
