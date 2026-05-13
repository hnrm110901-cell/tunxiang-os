"""[T3] v414 — drop dead v151b mv_* tables (解锁 fresh `alembic upgrade head`)

## 背景

`v301_table_analytics_views.py`（revision `v151b`，2026-04 落地）创建了 3 张
物化视图占位表：

  - mv_table_turnover
  - mv_session_analytics
  - mv_waiter_performance

CREATE TABLE 中 mv_table_turnover 的 PK 用 `COALESCE(zone_id, '0...'::UUID)`
表达式 — PostgreSQL 标准**所有版本**拒绝 PK constraint 用表达式
（详见 issue #510）。

历史 `migration-ci.yml` 自承认 KNOWN GAP："versions/ 全为空 → alembic
upgrade head 实质 no-op" — 9/10 历史 success 全是 no-op success。
PR #508 (RLS Runtime per-PR workflow `7a07703c`) 是首个真正用
v001..head 全链真 PG 跑 upgrade 的 workflow，首次暴露此 bug。

## 业务影响 = 0（dead schema）

全仓 grep 验证（2026-05-13 issue #510 comment）：3 张表**零业务消费者**

  | 表 | services/ | edge/ apps/ scripts/ | 测试 | 投影器 |
  |----|----|----|----|----|
  | mv_table_turnover | 0 | 0 | 1 (test 标 `gap=` 占位) | 未实现 |
  | mv_session_analytics | 0 | 0 | 0 | 未实现 |
  | mv_waiter_performance | 0 | 0 | 0 | 未实现 |

注：tx-analytics 中 `table_turnover` 字符串是 KPI 配置 dict key + score 函数名
（`merchant_kpi_config_routes.py` / `test_store_health.py`），与物化视图无 SQL 关联。

## 修复方式

新增 v414 migration，DROP TABLE IF EXISTS × 3。

- 假设 a（极可能）：生产从未跑过 fresh upgrade 到 v151b → 3 张表本来就不存在 →
  DROP IF EXISTS 是 no-op，零风险
- 假设 b（罕见）：生产手工补丁创建过这 3 张表 → DROP 删除 dead schema，仍零业务影响
  （0 消费者）

未来真需投影器时，按 CLAUDE.md §15 v147+ 事件总线规范"按需建视图"重建即可，
按事件流重新填充。

## 不动 v301

CLAUDE.md §18："已应用的迁移文件禁止修改"。v301 文件保留原状，
v414 作为 forward fix 新增。

## downgrade

dead schema 无业务回退价值；downgrade 不重建（重建仍需修 PK 表达式 BUG，超出本
PR 范围）。如确需回滚 v414，手工 ALTER 即可（生产无消费者）。

Revision: v414_drop_dead_v151b_tables
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v414_drop_dead_v151b_tables"
down_revision: Union[str, None] = "v413_member_identity_map"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_DEAD_TABLES = (
    "mv_table_turnover",
    "mv_session_analytics",
    "mv_waiter_performance",
)


def upgrade() -> None:
    for table in _DEAD_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")


def downgrade() -> None:
    raise NotImplementedError(
        "v414 是 dead schema cleanup — 3 张表无业务消费者，"
        "重建仍需修 v301 PK 表达式 BUG（超本 PR scope）。"
        "如需手工回滚，参考 issue #510 方案 A/B/C 重建并修 PK。"
    )
