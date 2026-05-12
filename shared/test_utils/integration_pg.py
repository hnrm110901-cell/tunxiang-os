"""跨 service 共享：integration-pg 真 PG 反测的最小公共子集（D2b'）

设计意图：仅抽取 in-place 重复 3 处的开销最小子集（DSN 读取 + skipif 决策 +
tenant GUC 设置），让 fixture-driven 测试（shared/db-migrations/tests/conftest.py）
和 service-level 多 session 测试（tx-analytics / tx-brain）共用同一份代码。

不在本模块的（按设计）：
  - integration_pg_engine / integration_pg_session 两个 fixture：fixture 设计假设
    （function-scoped + 单事务 rollback + 仅 channel-aggregation 3 表 GRANT +
    禁用 commit）与 service-level 测试模式（module-scoped engine + 多 session +
    跨租户 commit + 各自表 GRANT + row_security=off 清理）不兼容，service 端继续滚自己的。
  - role / table GRANT setup：channel-aggregation fixture 专属逻辑，留在
    shared/db-migrations/tests/conftest.py。

Exports:
  INTEGRATION_PG_DSN   — env var 值（已 strip whitespace），None 当未配置
  requires_integration_pg — pytest.mark.skipif 装饰器（统一 reason 文案）
  set_tenant_guc(session, tenant_id) — 在 session 上设事务级 app.tenant_id GUC

扩面调研结论（2026-05-12 issue #449 closed）:
  调研 6 个 `*_rls_*_tier1.py` 候选 + 4 个真 INTEGRATION_PG_DSN consumer 全集，
  结论：**0 in-place 残留**。所有真 PG consumer 已统一使用本模块。新加 *_tier1.py
  真 PG 反测直接 `from shared.test_utils.integration_pg import …` 即可。
  详 docs/integration-pg-fixture-audit-2026-05-12.md。
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

# 从 env 读 DSN —— strip whitespace 避免文件末尾换行误判；""→ None 统一未配置判断。
_raw = os.environ.get("INTEGRATION_PG_DSN", "").strip()
INTEGRATION_PG_DSN: str | None = _raw or None


requires_integration_pg = pytest.mark.skipif(
    not INTEGRATION_PG_DSN,
    reason=(
        "INTEGRATION_PG_DSN 未配置 — 跳过真 PG 反测（opt-in）。"
        "本地：docker compose -f infra/compose/test-pg.yml up -d，"
        "见 docs/integration-pg-fixture.md"
    ),
)


# sqlalchemy 仅 integration-pg 测试需要；本模块在 lint-only / migration-ci
# 等不装 asyncio extras 的 workflow 也可能被 import（常量 + 装饰器导出）。
# 把 sqlalchemy 依赖收敛在 set_tenant_guc 内，避免 import-time hard error。
try:
    from sqlalchemy import text

    _SQLA_AVAILABLE = True
except ImportError:
    _SQLA_AVAILABLE = False


if _SQLA_AVAILABLE:

    async def set_tenant_guc(
        session: AsyncSession, tenant_id: UUID | str
    ) -> None:
        """在 session 上设 app.tenant_id GUC（事务 scope）。

        第三参数 TRUE = 事务级（local），rollback 时自动清理，不污染下个 test。
        屯象 init-rls.sql 的 set_tenant_id() 用 FALSE（session 级）— 应用 runtime
        用法不同；反测 fixture 必须 TRUE 才能配合事务隔离。
        """
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
