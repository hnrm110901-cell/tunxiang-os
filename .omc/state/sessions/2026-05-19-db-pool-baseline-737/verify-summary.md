# A5 #737 helm DSN pool baseline Phase A — §0 起手 verify summary

会话: 2026-05-19 / branch `feat/db-pool-baseline-737-2026-05-19` / base HEAD `98baa2af`

## A. 3 个 pool 源真位置 (vs brief 文本)

| 源 | brief 路径 | 实测路径 | 实测 line | Default |
| --- | --- | --- | --- | --- |
| SQLAlchemy 共享 engine | `shared/ontology/database.py` | `shared/ontology/src/database.py` | line 15-22 (active); line 14 (dead, Q3=A 不动) | `pool_size=20, max_overflow=30, pool_pre_ping=True, pool_recycle=300` |
| projector asyncpg pool | `shared/events/src/projector.py` | `shared/events/src/projector.py` | line 93 (run, `max_size=3`); line 153 (rebuild, `max_size=2`) | `min_size=1, max_size=3 / 2` |
| tx-supply cert_alerter engine | `services/tx-supply/src/workers/cert_expiry_alerter.py` | `services/tx-supply/src/workers/cert_expiry_alerter.py` | line 42 (active, `_get_engine()` lazy init) | `pool_size=5, max_overflow=10` |

**与 brief 差异**:
- `shared/ontology/database.py` → 实际位于 `shared/ontology/src/database.py` (多一层 src/)。
- projector 有 2 个 `create_pool` 调用点 (run + rebuild)；brief 只提 line 93+153，**实测 line 153 是 rebuild 路径 `max_size=2`** (与 run 的 3 不同)。Q1 决议 `ASYNCPG_POOL_MAX` 共用于 projector + cert_alerter，但**实际只能 cover projector**（cert_alerter 是 SQLAlchemy engine，不是 asyncpg.create_pool）。Brief 也同样命名独立 `CERT_ALERTER_POOL_*`。**executor 决策**: `ASYNCPG_POOL_MAX` 应用在 projector 的 run + rebuild **两个**调用点（保持一致）。

## B. helm + compose 接入点

- `infra/helm/tx-supply/values.yaml`: `env:` 段 line 31-45 已有 5 个业务 env，新加 5 个 pool env 末尾。
- `infra/helm/tx-analytics/values.yaml`: `env:` 段 line 31-45 已有 4 个业务 env，新加 3 个 pool env (无 cert_alerter)。
- `infra/compose/base.yml`: `x-env: &common-env` line 73-79 已有 6 个公共 env，新加 5 个 pool env (含 default fallback)。
- compose envs: `dev.yml` / `staging.yml` / `prod.yml` / `gray.yml` / `demo.yml` — brief 列 4 个 (dev/staging/prod/gray)，实测**还多 1 个 `demo.yml`** (5 个文件)。executor 决策: dev override 大 pool；prod/staging/gray/demo 保留 default 不动 (Q2=A regression-safe)。

## C. scripts 现状 + 模板

- `scripts/ops/`: **不存在** (brief 已知，需新建)。
- `scripts/db/`: 仅 1 文件 `check_alembic_head_for_pr_199.sh` (shell, 非 Python)。
- `scripts/seed_czyz.py` (root scripts/): 79 行 psycopg2 sync 写法，含 `os.environ.get("DATABASE_URL")` + structlog-free `print()`。**不直接复用** — 新 script 用 asyncpg + structlog 沿 codebase 主流。

## D. §17/G10 红线 0 touch confirm (verify path)

- `services/tx-trade/src/services/cashier_engine.py` ✓ (Tier 1)
- `services/tx-trade/src/services/order_service.py` ✓ (Tier 1)
- `services/tx-trade/src/services/payment_saga_service.py` ✓ (Tier 1)
- `services/tx-trade/src/services/invoice_service.py` ✓ (Tier 1)
- `services/tx-trade/src/api/wine_storage_routes.py` + `services/tx-trade/src/models/wine_storage.py` ✓ (Tier 1)
- `shared/events/src/emitter.py` ✓ (event bus 核心)
- `services/tx-trade/tests/test_pinzhi_pos_tier1.py` ✓ (POS 适配)
- `services/tx-trade/src/services/delivery_adapters/meituan_adapter.py` ✓ (POS 适配)

**全部存在, ship 前最后 `git diff --name-only origin/main..HEAD` 必须 0 match。**

## E. DEVLOG/progress 顶部 anchor (memory feedback_devlog_edit_anchor_drift red line)

- `DEVLOG.md` line 1: `## 2026-05-19 W3 起手 — Prometheus 系统性审计 (#820) 4 Phase 单 PR 闭环` (今日早段 #820 顶部)
- `docs/progress.md` line 1: `## 2026-05-19 · #820 W3 起手 — Prometheus 系统性审计 4 Phase 单 PR 闭环 (Tier 1 邻接 explicit-ask 第 41 例)`

两个顶部 anchor 都是 5/19 #820 块, **新 prepend 走在 #820 块之上**。

## F. 并发 verify

- `git fetch origin main`: HEAD `98baa2af` 与本 branch base 一致, 无新 commit。
- 最近 5 commits: #842 / #839 / #835 / #826 / #828 — 主题 (governance docs / promtool / Prometheus audit / MetricsAuthMiddleware / outbox_repo helper), **无 pool/DSN/737 主题**。
- `gh pr list --search "DSN OR pool OR baseline OR 737" --state open`: 1 PR (#487 W1 batch 不相关), 无同主题。

## G. handoff N self-tally — 跳过

按 brief 指令使用占位 "第 NN 例", PR description 落地后由 reviewer/founder 校准真数。

---

## §0 结论

- 3 个 pool 源全部 verify 到, 路径有 1 处偏差 (database.py 多一层 src/), 已修正实施 spec。
- projector 有 2 个 create_pool 调用点 (run line 93 + rebuild line 153), 均应用 `ASYNCPG_POOL_MAX` env 保持一致。
- cert_alerter 独立 SQLAlchemy engine (非 asyncpg), 用 `CERT_ALERTER_POOL_SIZE` + `CERT_ALERTER_POOL_OVERFLOW` 独立命名 (planner Q1=B 已决议)。
- compose envs 实际 5 个文件 (含 demo.yml), brief 漏 demo, executor 5 个全加 (保持基础设施一致, dev 大 pool, 其他 4 default 不动)。
- DEVLOG/progress anchor 干净, prepend 安全。
- 无并发, 可以起手。
