# Plan — Gateway 瘦身: 抽 tx-sync-worker 接管品智 POS 同步 + 企微 daily SOP

**Issue**: #758 (W2 残留 P1, 4 人日预算)
**Branch**: `feat/gateway-slim-tx-sync-worker-2026-05-18` (base `origin/main` 9f4e8ec5)
**Worktree**: `/Users/lichun/.tunxiang-p0-worktrees/gateway-slim-2026-05-18`
**Date**: 2026-05-18
**Plan author**: planner agent (OMC team)
**战略锚**: §23 W2 / §24 举措 #1 服务收敛 (Phase 1 临时态 20 → 21, 终态 W12 = 17)
**Reference 模板**: tx-event-relay (#757 / PR #795 merged at 968a40fe)

---

## §0 自检 (self-regrep verify) — 红线 per memory `feedback_planner_verified_claims_must_regrep.md`

所有具体数字/行号/端口/路径声明的 verify 命令 + 结果. 任何后续 step 引用此章节即为 verified.

### §0.1 端口 8021 free

```bash
$ grep -c "8021" /Users/lichun/.tunxiang-p0-worktrees/gateway-slim-2026-05-18/infra/compose/base.yml
0
$ grep -nE "(80[12][0-9])" /Users/lichun/.tunxiang-p0-worktrees/gateway-slim-2026-05-18/infra/compose/base.yml | head -20
# 实测占用: 8010 tx-brain / 8011 tx-intel / 8012 tx-org / 8013 tunxiang-api+tx-forge (容器内同号不同名)
# 8014 tx-civic / 8015 tx-expense / 8016 tx-pay / 8017 tx-devforge / 8018 mcp-server
# 8019 tx-predict / 8020 tx-event-relay (#757 ship at 968a40fe)
# **8021 free** — 推荐 tx-sync-worker
```

### §0.2 sync_scheduler.py 真实结构 (gateway 自带, 712 行 27959 bytes)

```bash
$ wc -l services/gateway/src/sync_scheduler.py
     712
$ wc -c services/gateway/src/sync_scheduler.py
   27959
$ grep -nE "create_sync_scheduler|scheduler.add_job" services/gateway/src/sync_scheduler.py
582:def create_sync_scheduler() -> AsyncIOScheduler:
598:    scheduler.add_job(  # daily_dishes_sync @ 02:00
609:    scheduler.add_job(  # daily_master_data_sync @ 03:00
620:    scheduler.add_job(  # hourly_orders_incremental_sync
630:    scheduler.add_job(  # quarter_members_incremental_sync
```

### §0.3 sync_scheduler.py 真实 cron jobs (4 个, NOT 1)

**handoff 描述"pinzhi_pos_sync" 是单一 job 不准** — 真实是 4 个独立 APScheduler job:

| Job id | trigger | function | merchants |
|--------|---------|----------|-----------|
| `daily_dishes_sync` | cron h=2 m=0 Asia/Shanghai | `_run_dishes_sync` (line 402) | czyz/zqx/sgc 并行 |
| `daily_master_data_sync` | cron h=3 m=0 Asia/Shanghai | `_run_master_data_sync` (line 441) | czyz/zqx/sgc 并行 (员工 + 桌台) |
| `hourly_orders_incremental_sync` | interval hours=1 | `_run_orders_incremental_sync` (line 499) | czyz/zqx/sgc 并行 |
| `quarter_members_incremental_sync` | interval minutes=15 | `_run_members_incremental_sync` (line 539) | czyz/zqx/sgc 并行 |

verify:
```bash
$ grep -nE "^async def _run_" services/gateway/src/sync_scheduler.py
402:async def _run_dishes_sync() -> None:
441:async def _run_master_data_sync() -> None:
499:async def _run_orders_incremental_sync() -> None:
539:async def _run_members_incremental_sync() -> None:
```

加 `_run_daily_sop` (gateway/src/main.py:73 自带, 09:00 企微 SOP) = **gateway 当前实际跑 5 个 cron job**, 不是 issue 描述的 2 个.

### §0.4 sync_scheduler.py 自带 `sync_router` (健康 API)

```bash
$ grep -n "sync_router\|sync_health_router\|/api/v1/sync" services/gateway/src/sync_scheduler.py services/gateway/src/main.py
sync_scheduler.py:655:sync_router = APIRouter(prefix="/api/v1/sync", tags=["sync"])
sync_scheduler.py:658:@sync_router.get("/health", summary="查询各商户同步健康度（最近7天成功率）")
main.py:32:from .sync_scheduler import sync_router as sync_health_router
main.py:195:app.include_router(sync_health_router)
```

`/api/v1/sync/health` endpoint 与定时任务共存于 sync_scheduler.py. Phase 1 **不迁** (gateway 继续暴露), Phase 2 评估迁入 tx-sync-worker.

### §0.5 gateway/src/main.py 真实 scheduler 调用点 (verify before claim)

```bash
$ grep -n "_scheduler\|create_sync_scheduler\|_run_daily_sop\|wecom_group_daily_sop" services/gateway/src/main.py
7: import apscheduler...
31: from .sync_scheduler import create_sync_scheduler
32: from .sync_scheduler import sync_router as sync_health_router
70: _scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
73: async def _run_daily_sop() -> None:
79: log = logger.bind(task="wecom_group_daily_sop")
120: _scheduler.add_job(lambda: asyncio.create_task(_run_daily_sop()), "cron", hour=9, minute=0, ...)
130: _sync_scheduler = create_sync_scheduler()
131-138: for job in _sync_scheduler.get_jobs(): _scheduler.add_job(...)
140: _scheduler.start()
155: _scheduler.shutdown(wait=False)
```

注: handoff 给出的"line 7 / 31 / 70 / 120 / 130 / 140 / 155"全部 verified accurate.

### §0.6 service-freeze.yml planned_additions 已含

```bash
$ grep -nE "tx-sync-worker|tx-event-relay" .omc/policy/service-freeze.yml
26:  - tx-ontology      # W10 issue #766 — Ontology Layer 独立服务
27:  - tx-sync-worker   # W2  issue #758 — Outbox 真 worker
28:  - tx-event-relay   # W3  issue #757 — Event relay 服务
```

§26 服务冻结令 4 步例外流程, planned_additions 已就位 (step 3), 本 PR 完成 step 1 (创始人 explicit-ack §5 4 问) + step 2 (本守门会决议) + step 4 (实施).

### §0.7 tx-event-relay 模板真实结构 (复制基准)

```bash
$ ls services/tx-event-relay/
conftest.py  Dockerfile  requirements.txt  src/

$ ls services/tx-event-relay/src/
__init__.py  main.py  metrics.py  outbox_repo.py  relay_worker.py  tests/

$ ls services/tx-event-relay/src/tests/
__init__.py  test_outbox_repo.py  test_relay_worker_shadow_tier1.py

$ ls infra/helm/tx-event-relay/templates/ | wc -l
9     # = 9 templates: _helpers.tpl, configmap, deployment, hpa, networkpolicy,
      #                NOTES.txt, poddisruptionbudget, service, serviceaccount
$ ls infra/helm/tx-event-relay/
Chart.yaml  templates/  values.yaml  # 总文件 = 9 templates + Chart.yaml + values.yaml = 11
```

**handoff 中"Helm chart 11 文件"指 9 templates + Chart.yaml + values.yaml**, 与 #757 决议文档 §3 第 3 项措辞一致.

### §0.8 pinzhi adapters 全 shared/ 不需迁

```bash
$ ls shared/adapters/pinzhi_pos/src/
__init__.py  adapter.py  dish_sync.py  employee_sync.py  factory.py
inventory_sync.py  member_sync.py  merchants.py  order_sync.py
signature.py  supply_sync.py  table_sync.py
```

tx-sync-worker `from shared.adapters.pinzhi_pos.src.* import ...` 直接复用, 0 shared/ 改动.

### §0.9 governance decision template

```bash
$ ls docs/governance/decisions/
2026-05-17-tx-event-relay-shadow-mode-approval.md  # 复制 template, 改 §1-§7
2026-W21-2026-05-18-agenda-draft.md                 # W21 议程
2026-W21-2026-05-18-template.md
README.md
```

本 PR 落盘 `2026-05-18-tx-sync-worker-shadow-approval.md` (verbatim adapt from #757 template).

### §0.10 dev.yml + base.yml 注册 pattern

```bash
$ grep -nE "tx-event-relay" infra/compose/base.yml | head -3
37:#     ⊕ tx-event-relay :8020 ← 真 Outbox shadow relay worker
467:  # ── Event Relay 真 Outbox shadow worker :8020 ─────────
471:  tx-event-relay:

$ grep -nE "tx-event-relay" infra/compose/envs/dev.yml | head -3
330:  # ── tx-event-relay 真 Outbox shadow worker (W3 issue #757) ──
331:  tx-event-relay:
338:      - "8020:8020"
```

复用 svc-defaults / build-defaults / common-env YAML anchors (Phase 1).

---

## §1 Scope 边界

### IN-SCOPE (Phase 1 双轨并行)

1. **新服务 `services/tx-sync-worker/`** (端口 8021, 复用 tx-event-relay 模板 adapt)
   - conftest.py / Dockerfile / requirements.txt
   - src/main.py / src/__init__.py
   - src/jobs/__init__.py / src/jobs/pinzhi_sync.py / src/jobs/wecom_sop.py
   - src/scheduler.py (APScheduler 工厂, **拷贝** gateway sync_scheduler.py 业务函数 → 包私有)
   - src/metrics.py (5 Prometheus metrics)
   - src/tests/__init__.py + 2 tests (jobs registration / metrics emit / scheduler shutdown)
2. **Helm chart `infra/helm/tx-sync-worker/`** 11 文件 (Chart.yaml + values.yaml + 9 templates, T2 PDB maxU=1)
3. **`infra/compose/base.yml`** 注册 :8021 (复用 svc-defaults / build-defaults / common-env)
4. **`infra/compose/envs/dev.yml`** 注册 :8021 + hot-reload volume mount
5. **`docs/governance/decisions/2026-05-18-tx-sync-worker-shadow-approval.md`** (本守门会决议)
6. **`docs/infra/port-allocation-2026-05.md`** 加 8021 行
7. **DEVLOG.md + docs/progress.md** prepend 2026-05-18 块 (尾段 ship 时)

### OUT-OF-SCOPE (Phase 1 严禁本 PR 触, 任何一项触发 = plan 作废)

| 文件 | 原因 | Phase |
|------|------|------|
| `services/gateway/src/main.py` | Phase 1 双轨并行, gateway scheduler 仍跑 | Phase 2 关 (独立 follow-up) |
| `services/gateway/src/sync_scheduler.py` | **copy 不 modify**, sync_router 留 gateway | Phase 2 评估迁 |
| `services/tx-trade/cashier_engine.py` | §17/G10 双红线 Tier 1 零容忍 | 永不本 PR |
| `services/tx-trade/order_service.py` | §17/G10 双红线 | 永不本 PR |
| `services/tx-trade/payment_saga_service.py` | §17 红线 | 永不本 PR |
| `services/tx-trade/invoice.py` | §17 红线 | 永不本 PR |
| `services/tx-supply/inventory_io.py` | §17 红线 | 永不本 PR |
| `shared/events/src/emitter.py` | Tier 1 邻路径 + §17 红线邻接 | 永不本 PR |
| `shared/adapters/pinzhi_pos/` 任何改动 | 仅 import, 0 修改 | 永不本 PR |
| Migration v447+ | 本 issue 无 DB 写 / 0 schema change | 永不本 PR |
| `shared/ontology/` | §18 创始人确认门禁 | 永不本 PR |
| `services/gateway/src/wecom_group_service.py` | 仅被 tx-sync-worker import, 0 修改 | 永不本 PR |

### Phase 2 follow-up (本 PR 立 issue 不实施)

- Issue: `[W4 P1] 关 gateway scheduler 切换 tx-sync-worker 单轨`
  - 删 gateway/src/main.py line 70 `_scheduler` + line 120-138 add_job + line 130-138 create_sync_scheduler
  - 删 import `from .sync_scheduler import create_sync_scheduler`
  - 评估迁 `sync_router` 到 tx-sync-worker (Phase 2 子任务)
  - 验收: tx-sync-worker 跑满一周 + 旧/新路径 sync 成功率对比 + last_sync_at 对账

---

## §2 文件清单 (~22 新增 / 0 修改 gateway / 4 修改 infra+docs)

### 新增 (20 files, all under `services/tx-sync-worker/` + `infra/helm/tx-sync-worker/`)

```
services/tx-sync-worker/
├── conftest.py                              # 1 (adapt from tx-event-relay)
├── Dockerfile                                # 2
├── requirements.txt                          # 3
└── src/
    ├── __init__.py                          # 4
    ├── main.py                              # 5 — FastAPI lifespan (start scheduler) + /health + /metrics
    ├── scheduler.py                          # 6 — APScheduler 工厂 (兼容 copy sync_scheduler 5 jobs)
    ├── metrics.py                           # 7 — 5 Prometheus metrics
    ├── jobs/
    │   ├── __init__.py                      # 8
    │   ├── pinzhi_sync.py                   # 9 — 4 jobs (dishes/master/orders/members) refactored 套壳
    │   └── wecom_sop.py                     # 10 — _run_daily_sop refactored 套壳
    └── tests/
        ├── __init__.py                       # 11
        ├── test_scheduler_registration.py    # 12 — verify 5 jobs registered with correct trigger
        ├── test_pinzhi_sync_tier2.py         # 13 — 4 jobs invocation + retry path (mock adapter)
        └── test_wecom_sop_tier2.py           # 14 — daily SOP 单租户 mock

infra/helm/tx-sync-worker/
├── Chart.yaml                                # 15
├── values.yaml                               # 16 (T2 PDB maxU=1; HPA enabled=false; replicaCount=1)
└── templates/
    ├── _helpers.tpl                          # 17
    ├── configmap.yaml                        # 18
    ├── deployment.yaml                       # 19
    ├── hpa.yaml                              # 20
    ├── networkpolicy.yaml                    # 21
    ├── NOTES.txt                             # 22 (note: index 22 - 已重数, 总数 22 件新增)
    ├── poddisruptionbudget.yaml              # 23
    ├── service.yaml                          # 24
    └── serviceaccount.yaml                   # 25
```

实际新增 = 11 service files + 11 helm files = **22 files**.

### 修改 (4 files, surgical)

```
infra/compose/base.yml                         # 加 tx-sync-worker :8021 block (复用 anchors, ~30 行)
infra/compose/envs/dev.yml                     # 加 tx-sync-worker :8021 hot-reload block (~12 行)
docs/infra/port-allocation-2026-05.md          # 加 8021 行
DEVLOG.md + docs/progress.md                   # ship 时 prepend (per §16 + §18 规范, 单独 step §3.7)
```

### 新增 governance + open-questions (2 files)

```
docs/governance/decisions/2026-05-18-tx-sync-worker-shadow-approval.md   # 守门会决议
.omc/plans/open-questions.md                                              # 立 §5 4 问 + W2 残留
```

**总计**: 22 新增 service+helm + 2 新增 docs + 4 修改 infra/log = **28 files touched** (gateway 0, shared 0, Tier 1 0).

---

## §3 实施步骤 (按依赖顺序 7 大步, 4 人日)

### §3.1 骨架建立 (新服务目录 + 基础文件) — 0.5 人日

```bash
# 在 worktree 内执行 (per §0 verify root)
cd /Users/lichun/.tunxiang-p0-worktrees/gateway-slim-2026-05-18
mkdir -p services/tx-sync-worker/src/jobs services/tx-sync-worker/src/tests
mkdir -p infra/helm/tx-sync-worker/templates
```

依赖: 仅 §0 verify. 验收: `tree services/tx-sync-worker/` + `tree infra/helm/tx-sync-worker/` 显示目录骨架.

### §3.2 conftest.py + Dockerfile + requirements.txt — 0.3 人日

复制 tx-event-relay 模板 → adapt:

| 项 | tx-event-relay | tx-sync-worker (adapt) |
|---|---|---|
| `conftest.py` ROOT/SRC paths | `services/tx-event-relay/` | `services/tx-sync-worker/` |
| `_ensure_ns("services.tx_event_relay", ...)` | `tx_event_relay` | `tx_sync_worker` |
| Dockerfile COPY src/ | `tx_event_relay` 目标路径 | `tx_sync_worker` 目标路径 |
| Dockerfile CMD uvicorn port | `8020` | `8021` |
| Dockerfile USER 10001 | F#2 安全上下文 | 同 (复制) |
| requirements.txt | fastapi/uvicorn/asyncpg/structlog/prometheus-client | **+ apscheduler>=3.10 + sqlalchemy[asyncio] + httpx + python-multipart** (jobs 调 pinzhi adapter + sqlalchemy 写 sync_logs) |

注: tx-sync-worker 有 DB 写 (`_write_sync_log` 写 sync_logs 表) → 复用 `shared.ontology.src.database.async_session_factory` (与 sync_scheduler.py 原路径一致). **不**自建 asyncpg pool (与 tx-event-relay 模式区分):
- tx-event-relay relay loop 跨租户 polling outbox + BYPASSRLS 角色 → 用 asyncpg pool
- tx-sync-worker 每商户写 sync_logs (单租户视角 + RLS set_config) → 用 SQLAlchemy session
- 区分依据 memory `feedback_projector_asyncpg_pool_model.md` 中 "pool 来源 / 用途" 维度

验收:
```bash
$ docker build -f services/tx-sync-worker/Dockerfile -t tx-sync-worker:test .
# 期望: USER 10001 / CMD uvicorn ... --port 8021 / requirements 全装
$ docker run --rm tx-sync-worker:test python -c "import services.tx_sync_worker.src.main"
# 期望: 0 ImportError (per memory `feedback_smoke_test_must_verify_functionality.md`)
```

### §3.3 src/main.py + src/scheduler.py + src/jobs/*.py + src/metrics.py — 1.2 人日

#### main.py (FastAPI lifespan)

仿 tx-event-relay/src/main.py 但简化:
- lifespan: 启动 `create_sync_scheduler_v2()` (新工厂) 跑 5 jobs, shutdown 调 `scheduler.shutdown(wait=False)`
- /health: return `{"ok": True, "service": "tx-sync-worker", "port": 8021, "jobs": [...]}`
- /metrics: Prometheus exposition (per memory `feedback_tier1_ci_minimal_deps_trap.md` fail-open import)
- 严禁 add_job 真 cron (Q3 决议时 user 选 `same_cron` 才跑真 cron, `dry_run` 模式空挂证明可启动)

#### scheduler.py (APScheduler 工厂)

仿 sync_scheduler.py:582-648 `create_sync_scheduler()` 函数 → 复制不动业务 + 改 import 路径:
```python
from .jobs.pinzhi_sync import (
    _run_dishes_sync,
    _run_master_data_sync,
    _run_orders_incremental_sync,
    _run_members_incremental_sync,
)
from .jobs.wecom_sop import _run_daily_sop
```

cron 时间 (Q3 决议) — 默认 `Asia/Shanghai` 与 gateway 一致:
- 02:00 daily_dishes_sync
- 03:00 daily_master_data_sync
- hourly orders_incremental_sync
- every 15min members_incremental_sync
- 09:00 wecom_group_daily_sop

#### jobs/pinzhi_sync.py

把 gateway/src/sync_scheduler.py:128-577 共 5 个 `_sync_*_for_merchant` + `_with_retry` + `_run_*_sync` + `_write_sync_log` 共 ~450 行 **copy** (不 modify gateway 源):
- 改 module-level logger / import path / 0 业务函数 modify
- 落入 `services/tx-sync-worker/src/jobs/pinzhi_sync.py`
- 与 gateway/src/sync_scheduler.py 并存 (Phase 1 双轨); diff 0 行业务差异

#### jobs/wecom_sop.py

把 gateway/src/main.py:73-115 `_run_daily_sop` copy:
- 改 import 路径 (`from services.gateway.src.wecom_group_service ...` → 直接 import 不动 gateway 源)
- 注意: wecom_group_service.py / models/wecom_group.py / database.py / get_async_session 留 gateway, tx-sync-worker import 跨服务路径 (与 sync_scheduler.py import `from shared.ontology.src.database` 同模式)
- **0 业务函数 modify**

#### metrics.py

5 Prometheus metrics (fail-open import 模板 per memory `feedback_tier1_ci_minimal_deps_trap.md`):
```
tx_sync_worker_executions_total{job, status}     Counter — 每次 cron firing 计数
tx_sync_worker_last_run_timestamp_seconds{job}    Gauge   — 最近成功 run 时间戳
tx_sync_worker_duration_seconds{job}              Histogram — 单次 job 耗时
tx_sync_worker_retry_total{job, attempt}          Counter — 重试次数
tx_sync_worker_pending_sync_count{merchant,type}  Gauge   — 当前 pending sync 行数 (从 sync_logs 抓)
```

验收: 模块级 `logger = structlog.get_logger(__name__)` 必有 (per memory `feedback_mass_edit_module_logger_check.md` 教训); module top eager import 不触底层 mapper init (per memory `feedback_eager_api_import_smoke_too_aggressive.md`).

### §3.4 测试 (3 test files, T2 标准非 _tier1.py 后缀) — 0.8 人日

仿 tx-event-relay/src/tests/ 结构. T2 标准: 不强制 _tier1.py 后缀, 但仿 tx-event-relay tests/__init__.py + pytest 一致 collect 路径.

#### test_scheduler_registration.py

```python
def test_create_scheduler_registers_five_jobs():
    """create_sync_scheduler_v2() 注册 5 jobs (4 pinzhi + 1 wecom)."""
    scheduler = create_sync_scheduler_v2()
    job_ids = {j.id for j in scheduler.get_jobs()}
    assert job_ids == {
        "daily_dishes_sync",
        "daily_master_data_sync",
        "hourly_orders_incremental_sync",
        "quarter_members_incremental_sync",
        "wecom_group_daily_sop",
    }

def test_dishes_sync_trigger_02_asia_shanghai():
    """daily_dishes_sync cron hour=2 minute=0 Asia/Shanghai."""
    scheduler = create_sync_scheduler_v2()
    job = scheduler.get_job("daily_dishes_sync")
    assert job.trigger.fields[5].expressions[0].first == 2   # hour
    assert job.trigger.fields[6].expressions[0].first == 0   # minute
    assert str(job.trigger.timezone) == "Asia/Shanghai"

def test_scheduler_shutdown_no_hang(event_loop):
    """scheduler.shutdown(wait=False) 5s 内返回."""
    scheduler = create_sync_scheduler_v2()
    scheduler.start()
    await asyncio.wait_for(scheduler.shutdown(wait=False), timeout=5.0)
```

#### test_pinzhi_sync_tier2.py

```python
@patch("services.tx_sync_worker.src.jobs.pinzhi_sync.PinzhiAdapterFactory")
async def test_dishes_sync_merchant_success(mock_factory):
    """单租户 dishes sync — 成功路径 records_synced > 0."""
    # mock PinzhiDishSync.sync_dishes() return {"success": 100}
    result = await _sync_dishes_for_merchant("czyz")
    assert result["status"] == "success"
    assert result["records_synced"] > 0

async def test_with_retry_three_attempts_then_give_up():
    """_with_retry 3 次失败后返 retry_count=2 next_retry_at=None."""
    counter = {"calls": 0}
    async def _always_fail():
        counter["calls"] += 1
        raise RuntimeError("simulated")
    result = await _with_retry(lambda: _always_fail(), "test", "czyz")
    assert counter["calls"] == 3
    assert result["status"] == "failed"
    assert result["next_retry_at"] is None

async def test_sync_log_write_uses_set_config_tenant_id():
    """_write_sync_log 调 set_config('app.tenant_id') 保持 RLS."""
    # mock db, capture executed SQL, verify set_config preceded INSERT
```

#### test_wecom_sop_tier2.py

```python
@patch("services.tx_sync_worker.src.jobs.wecom_sop.WecomGroupService")
async def test_daily_sop_iterates_active_tenants(mock_service):
    """daily SOP scan 所有 active 群租户."""
    # mock db return [tenant_A, tenant_B]
    # verify service.scan_and_execute_daily_sop called 2 次

async def test_daily_sop_per_tenant_error_does_not_abort_loop():
    """单租户失败不阻塞其他租户 (gateway main.py:106 注释精神)."""
    # tenant_A throws, tenant_B 仍被调
```

验收:
```bash
$ cd services/tx-sync-worker && python -m pytest src/tests/ -v
# 期望: 3 test files 全 PASS
```

### §3.5 Helm chart (11 files) — 0.5 人日

复制 `infra/helm/tx-event-relay/` → `infra/helm/tx-sync-worker/` 全 11 文件, sed 替换:

| Q | tx-event-relay | tx-sync-worker (Q4 决议 = T2 maxU=1) |
|---|---|---|
| Chart.yaml `name` | tx-event-relay | tx-sync-worker |
| Chart.yaml `description` | 真 Outbox relay worker | 品智 POS 同步 + 企微 daily SOP worker |
| values.yaml `replicaCount` | 1 | **1** (单实例足够, scheduler 不能多副本 fire 同 job 重复) |
| values.yaml `image.repository` | tunxiang/tx-event-relay | tunxiang/tx-sync-worker |
| values.yaml `service.port` | 8020 | **8021** |
| values.yaml `RELAY_*` env | 3 项 | **DROPPED** (无 outbox 概念) → 加 `SYNC_TIMEZONE: Asia/Shanghai` |
| values.yaml `pdb.enabled` | false (T3) | **true / maxUnavailable: 1** (Q4 决议 T2 标准) |
| values.yaml `livenessProbe.path` | /health | /health (同) |
| values.yaml `readinessProbe.path` | /health | /health (同) |
| values.yaml `runAsUser` | 10001 | 10001 (F#2 一致) |
| templates/deployment.yaml `ports` | 8020 | **8021** |
| templates/service.yaml `port/targetPort` | 8020 | **8021** |
| templates/poddisruptionbudget.yaml | (Helm if .Values.pdb.enabled) | 同 (values 切到 true) |
| templates/NOTES.txt | 8020 URL | **8021** URL + jobs 列表 |
| networkPolicy.enabled | false | false (Phase 1 不接业务路径) |

注: 单实例 + cron job 不能 HPA scale (双 pod 会 fire 两次同 cron) → `autoscaling.enabled: false` + `replicaCount: 1` 永久. 升 T2 maxU=1 PDB 是为蓝绿部署期间不剪掉单点 daemon 致 job miss.

验收:
```bash
$ helm template infra/helm/tx-sync-worker/ | grep -E "containerPort|targetPort"
# 期望: 8021 三次 (deployment containerPort + service.port + targetPort)
$ helm lint infra/helm/tx-sync-worker/
# 期望: 0 errors
```

### §3.6 infra/compose/base.yml + envs/dev.yml + port-allocation doc — 0.2 人日

#### base.yml (复用 svc-defaults / build-defaults / common-env YAML anchors)

仿 base.yml:467-494 tx-event-relay block, 插入位置: tx-event-relay block 后. ~30 行:

```yaml
  # ── Sync Worker 品智POS + 企微 SOP daemon :8021 ─────
  # W2 P1 issue #758 — 战略 plan §23 W2 / §24 举措 #1 服务收敛 Phase 1
  # Phase 1 双轨并行: gateway scheduler 仍跑, tx-sync-worker shadow 验证一周
  # Phase 2 follow-up: 关 gateway scheduler 切单轨 (独立 issue)
  tx-sync-worker:
    <<: *svc-defaults
    build:
      <<: *build-defaults
      dockerfile: services/tx-sync-worker/Dockerfile
    environment:
      <<: *common-env
      SYNC_TIMEZONE: Asia/Shanghai
      CZYZ_TENANT_ID: ${CZYZ_TENANT_ID:-}
      ZQX_TENANT_ID: ${ZQX_TENANT_ID:-}
      SGC_TENANT_ID: ${SGC_TENANT_ID:-}
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8021/health',timeout=3).status==200 else 1)"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 20s
```

注释栏 :8 (line 8-38 概览段) 加一行 `#     ⊕ tx-sync-worker :8021 ← 品智POS 同步 + 企微 daily SOP daemon (W2 #758)`.

#### envs/dev.yml (hot-reload 模式)

仿 dev.yml:330-345 tx-event-relay block:

```yaml
  # ── tx-sync-worker 品智POS + 企微 SOP daemon (W2 issue #758) ──
  tx-sync-worker:
    command: >
      sh -c "pip install -q -i https://pypi.tuna.tsinghua.edu.cn/simple -r services/tx-sync-worker/requirements.txt &&
             uvicorn services.tx_sync_worker.src.main:app --host 0.0.0.0 --port 8021 --reload"
    ports:
      - "8021:8021"
    volumes:
      - ../../shared:/app/shared
      - ../../services/tx-sync-worker:/app/services/tx-sync-worker
```

#### docs/infra/port-allocation-2026-05.md

加一行 8021 tx-sync-worker 至端口表; 同 #757 决议文档 §2 Q2 在 8020 后加 8021.

验收:
```bash
$ docker compose -f infra/compose/base.yml -f infra/compose/envs/dev.yml up tx-sync-worker
# 期望: container 启动 → /health 返 200 → /metrics 暴露 5 metrics → 5 jobs registered 但 first fire 等到 02:00 (验收时手动 trigger 1 job)
```

### §3.7 governance decision + DEVLOG/progress + open-questions — 0.5 人日

#### docs/governance/decisions/2026-05-18-tx-sync-worker-shadow-approval.md

复制 `2026-05-17-tx-event-relay-shadow-mode-approval.md` 模板, 改:
- §1 背景: gateway scheduler 5 jobs 现状 + 4 人日预算 + 战略 W2 锚点
- §2 4 问决议 (§5 Q1-Q4)
- §3 IN/OUT scope (与本文档 §1 一致)
- §4 与服务冻结令关系 (§26 4 步: ✅ planned_additions ✅ explicit-ack ✅ 守门会归档 ✅ 实施)
- §5 5 项验收 (§3.4 测试 + Helm lint + compose up + /health 200 + 5 jobs registered)
- §6 W2 Tier 1 邻接 explicit-ask 状态 (T2 不要求 5 项稳定模式, 但走 §19 三 reviewer)
- §7 Phase 2 follow-up issue 立 (关 gateway scheduler 独立 PR)

#### DEVLOG.md + docs/progress.md prepend 2026-05-18

ship 时同 PR. 锚点 verify head -3 防 prepend drift (per memory `feedback_devlog_edit_anchor_drift.md`).

#### .omc/plans/open-questions.md (新建)

```markdown
## 2026-05-18 — Gateway 瘦身 tx-sync-worker (#758)
- [ ] **Q1** Job 命名 prefix (tx-sync-worker 包内) — 见 plan §5 Q1, 影响 metric label 命名
- [ ] **Q2** sync_router (/api/v1/sync/health) Phase 2 是否迁 — 见 plan §5 Q2
- [ ] **Q3** Phase 1 cron 时间是否完全复制 gateway — 见 plan §5 Q3
- [ ] **Q4** Helm Tier (T2 maxU=1 vs T3 default off) — 见 plan §5 Q4
- [ ] **W2 残留 P1**: Phase 2 follow-up 关 gateway scheduler 独立 issue 是否本 PR 立
```

### §3.8 (optional) §19 reviewer + ship — 0.7 人日

仿 #757 三 reviewer 流程 (T2 标准, 不强制 Tier 1 邻接 explicit-ask):
- code reviewer: 验证 §0.10 verify 5 jobs 业务函数与 gateway 0 diff (Python AST diff)
- security reviewer: 验证 RLS 一致 (`set_config('app.tenant_id')`) + 不读其他租户数据 + Dockerfile USER 10001
- critic reviewer: 验证 Phase 1 双轨并行 race condition (§7.3 dup task firing) + 时区一致 (§7.2)

每轮 0 P0/P1 后 → admin-merge (per memory `feedback_carveout_admin_merge_pattern.md` 5 项裁决标准).

### 4 人日分解汇总

| 天 | 子任务 | 估时 |
|---|---|---|
| **D1** | §3.1 骨架 (0.5) + §3.2 conftest/Dockerfile/req (0.3) + §3.3 main/scheduler/jobs/metrics (1.2 → 0.2 剩 D2) | 2.0 人日 |
| **D2** | §3.3 剩 (0.2) + §3.4 测试 (0.8) | 1.0 人日 |
| **D3** | §3.5 Helm (0.5) + §3.6 compose/dev/port doc (0.2) + §3.7 governance + DEVLOG + open-q (0.3 剩 0.2 D4) | 1.0 人日 |
| **D4** | §3.7 剩 (0.2) + §3.8 §19 review + ship (0.7) + buffer (0.1) | 1.0 人日 |
| **合计** | | **4.0 人日** ✅ |

---

## §4 测试策略 (T2 标准)

### 4.1 集成测试 (覆盖 5 jobs 主路径)

3 个 test file 共 ~12 test cases:
- `test_scheduler_registration.py`: 3 cases (5 jobs registered / cron timezone / shutdown timeout)
- `test_pinzhi_sync_tier2.py`: 5 cases (dishes success / orders incremental / with_retry 3 attempts / set_config RLS / merchant tenant_id env)
- `test_wecom_sop_tier2.py`: 4 cases (active tenants iteration / per-tenant error isolation / db not configured ImportError / scheduler shutdown 期间 sop run)

### 4.2 单元测试 (不强制 _tier1.py)

T2 标准: file name `test_*.py` (不带 _tier1) ; 与 tx-event-relay 同模式 (那是 Tier 1 邻接故有 _tier1 后缀).

### 4.3 手动 DEMO 验证 (W4 demo 轨 deliverable, 本 PR 验收不含)

| # | 验收项 | 命令 |
|---|---|---|
| 1 | docker build + run | `docker build -f services/tx-sync-worker/Dockerfile .` |
| 2 | /health 返 5 jobs | `curl localhost:8021/health` |
| 3 | /metrics 暴露 5 metrics | `curl localhost:8021/metrics \| grep tx_sync_worker_` |
| 4 | helm template + lint 全绿 | `helm template/lint infra/helm/tx-sync-worker/` |
| 5 | 5 jobs 业务 函数与 gateway diff | `diff services/gateway/src/sync_scheduler.py:128-577 services/tx-sync-worker/src/jobs/pinzhi_sync.py` → 0 业务 line diff |

### 4.4 CI 触发

per memory `feedback_tier1_test_filename_workflow_trigger.md`: 本 PR 测试不带 `_tier1` 后缀 → CI `tier1-gate.yml` glob `services/**/src/tests/**/*tier1*.py` 不触发. 这是 T2 标准设计预期. § 17 业务路径分级 + § 25 邻接 5 项稳定模式都不强制.

但: `Run Tier 1 Pre-flight Checks` + `python-lint-test (tx-sync-worker)` workflow 应触发 (services/tx-sync-worker/** glob).

### 4.5 fail-open import 模板

per memory `feedback_tier1_ci_minimal_deps_trap.md`:
- metrics.py `try: from prometheus_client import Counter, Gauge, Histogram except ImportError: ...` (no-op stub)
- scheduler.py `try: from apscheduler.schedulers.asyncio import AsyncIOScheduler except ImportError: ...` (CI minimal deps 兜底 sentinel class)
- jobs/pinzhi_sync.py 中调 `from shared.adapters.pinzhi_pos.src.*` **不**加 try/except (业务路径 ImportError 应 fail-loud, CI minimal deps 不装 pinzhi_pos 也不应跑 jobs/pinzhi_sync.py 测试)

---

## §5 explicit-ask 候选 4 问 (Q1-Q4) — 决策影响 + 推荐 + 备选

### Q1 — Job 命名 prefix (tx-sync-worker 包内)

| 选项 | 含义 | 影响 |
|---|---|---|
| **A (推荐)** | 保持原 5 个 id 不动 (daily_dishes_sync / daily_master_data_sync / hourly_orders_incremental_sync / quarter_members_incremental_sync / wecom_group_daily_sop) | 与 gateway 现行 metrics / 日志 ID 100% 一致, Phase 2 切换时 monitoring dashboard 0 改; metric label `job=daily_dishes_sync` |
| B | 加 `txsw_` prefix (txsw_daily_dishes_sync ...) | 命名空间清晰但 Phase 2 切换 dashboard / alerts 需双写 1 周; metric collision 风险 |
| C | 加 `tx_sync_worker.` 命名空间 (`tx_sync_worker.daily_dishes_sync`) | 形似 OpenTelemetry, 但 APScheduler job id 不接受 `.` (会被 misfire_grace_time check 解析错) |

**推荐**: **A** (0 监控改动, Phase 1 双轨期 metric `tx_sync_worker_executions_total{job="daily_dishes_sync"}` vs gateway `apscheduler_jobs_executed_total{job="daily_dishes_sync"}` 通过 service label 区分; 两套指标可对账)

### Q2 — sync_router (/api/v1/sync/health) Phase 2 是否迁

| 选项 | 含义 | 影响 |
|---|---|---|
| **A (推荐)** | Phase 2 follow-up issue **迁** sync_router 到 tx-sync-worker (8021/api/v1/sync/health) | scheduler + 健康 API 同服务边界清晰; gateway 真瘦身; 客户端 (web-admin / DEMO 巡检) 需 1 行 URL 改 |
| B | sync_router 永远留 gateway (查 `sync_logs` 表, 读 DB 而非 daemon) | 0 客户端改; 但 gateway 不能完全瘦身; W12 终态 17 服务收敛实现差 0.5 |
| C | Phase 1 本 PR **就**迁 (写读分离, gateway sync_router 立刻删) | 客户端立刻 break, 违反 §1 Phase 1 双轨边界 → 不可选 |

**推荐**: **A** Phase 2 迁. 本 PR Phase 1 留 gateway sync_router 不动 (§1 IN-SCOPE 排除).

### Q3 — Phase 1 cron 时间是否完全复制 gateway (timezone 风险评估)

| 选项 | 含义 | 影响 |
|---|---|---|
| **A (推荐)** | 完全复制 gateway 5 jobs 时间 (02:00/03:00/hourly/15min/09:00 Asia/Shanghai) | Phase 1 双轨期 **两套 daemon 同时 fire** 同一 cron — 风险见 §7.3 (dup task firing). 缓解: tx-sync-worker `RUN_MODE=dry_run` env 默认 true, 只 log 不真调 pinzhi adapter |
| B | tx-sync-worker 在 gateway 时间基础上 +5min offset (02:05/03:05/...) | 0 dup fire 风险, 但 gateway scheduler 任 1 job 失败时 tx-sync-worker offset 跑可能掩盖原 bug, 不利对账 |
| C | tx-sync-worker Phase 1 不跑真 cron (jobs registered 但 `next_run_time=None`) | 完全无 dup fire 风险, 但失去 Phase 2 切换前的 "tx-sync-worker 跑满一周对账" 验收 |

**推荐**: **A** + `RUN_MODE=dry_run` 模式 (default true). dry_run = jobs fire 时 log + metric 但不调 pinzhi adapter (即不真同步), Phase 2 follow-up issue 翻 `dry_run=false` 切单轨同时关 gateway scheduler. 这与 tx-event-relay `shadow_mode=true` 模式同构.

### Q4 — Helm chart Tier (T2 maxU=1 vs T3 default off)

| 选项 | 含义 | 影响 |
|---|---|---|
| **A (推荐)** | **T2 maxU=1 PDB enabled** | Phase 2 切单轨后 tx-sync-worker 是唯一同步入口, scheduler 不能 disruption 致 cron miss; PDB maxU=1 防 K8s 蓝绿部署期间剪掉单 pod; replicaCount 永久=1 (cron 不能 scale, dup fire) |
| B | T3 default off (与 tx-event-relay 一致) | shadow 期间 0 业务影响 (Phase 1 dry_run 也是); 切单轨后再升 Tier; 当前 PR 更小 |
| C | T1 minA=1 (永远至少 1 pod) | 过度, K8s replicaCount=1 + restart 重启已够; T1 minA=1 与 maxU=1 在 replicaCount=1 时语义等价但表达不一致 |

**推荐**: **A** T2. 理由: Phase 2 切单轨后 tx-sync-worker 直接顶 Tier 2 (品智 POS 同步 = §17 Tier 2 "影响门店运营效率"); 一开始就 T2 避免 W4 切换时再改一轮 PR. 但 Phase 1 dry_run 期间 PDB 实际不触发 (无 disruption).

---

## §6 reviewer focus area (§19 三 reviewer, T2 标准)

### 6.1 code reviewer

- **§0.10 业务函数 0 diff verify**: `diff -u <(sed -n '128,577p' services/gateway/src/sync_scheduler.py) <(sed -n '<lines>p' services/tx-sync-worker/src/jobs/pinzhi_sync.py)` → 仅 import path / module-level logger 改动, 0 业务 line 改
- **scheduler.py vs sync_scheduler.py:582-648**: cron 时间 / job id / trigger 完全一致
- **wecom_sop.py vs gateway/src/main.py:73-115**: `_run_daily_sop` 业务 0 diff
- **fail-open import 模板正确性**: prometheus_client / apscheduler 全 try/except ImportError + module 加载不崩溃 (per memory `feedback_tier1_ci_minimal_deps_trap.md`)
- **module-level logger 存在**: 每 file `logger = structlog.get_logger(__name__)` (per memory `feedback_mass_edit_module_logger_check.md`)

### 6.2 security reviewer

- **RLS 隔离**: `_write_sync_log` 调 `set_config('app.tenant_id', tenant_id, true)` (local=true) 保持; per memory `feedback_asyncpg_rollback_after_integrity_error.md` 模式不丢
- **Dockerfile USER 10001**: 与 tx-event-relay 一致 + F#2 安全上下文 + 非 root + readOnlyRootFilesystem 评估
- **环境变量泄露**: CZYZ_TENANT_ID / ZQX_TENANT_ID / SGC_TENANT_ID 走 secretRef, 不 hardcode
- **tx-sync-worker 不接收外部 HTTP** (只 /health /metrics): NetworkPolicy default off OK; W11 切单轨后评估 ingress lock down
- **per-tenant error isolation**: tenant_A 失败不阻塞 tenant_B (gateway main.py:106 注释精神, jobs/wecom_sop.py 必须保留)
- **dry_run 默认 true 强红线 (Q3 决议)**: 严禁 fall-through fire 真 cron — env unset → default true; mock test 验证

### 6.3 critic reviewer

- **Phase 1 双轨 race condition** (见 §7.3 dup task firing): dry_run=true 期间 0 风险; 但 PR ship 后误操作翻 false → 两 daemon 并发 fire 同 pinzhi adapter → API rate-limit / duplicate sync_logs / 重复 records_synced. critic 应推荐: 加 `if os.getenv("DRY_RUN", "true") == "true": log + return` 在 jobs 顶部 first thing, 防误配置
- **Phase 2 切换路径明确**: follow-up issue 是否立? PR 描述是否说清 "tx-sync-worker shadow 一周后 follow-up issue 翻 dry_run + 关 gateway scheduler"
- **timezone drift** (见 §7.2): gateway scheduler `timezone="Asia/Shanghai"` 与 tx-sync-worker 是否一致? 容器 TZ env? UTC offset 配置?
- **Helm replicaCount=1 永久**: 文档化 "cron job daemon 不能 scale" 防新人误改; values.yaml comment 加大写警告
- **gateway scheduler 仍跑 = Phase 1 资源浪费**: 接受 (双轨期可接受) 但 Phase 2 issue 必须本 PR 立, 不能漂

---

## §7 风险评估 (Phase 1 双轨并行)

### 7.1 dry_run 误关 → dup pinzhi API 调用 (P0)

**风险**: Q3 决议 A 选项 dry_run=true 默认; 误配置 `DRY_RUN=false` env → tx-sync-worker 跑真 cron + gateway scheduler 也跑 → 同一 cron 同时 fire 两次同租户同步, pinzhi POS API rate-limit 触发 (品智后台 429), sync_logs 双倍写入, 对账数据混乱.

**缓解**:
1. `DRY_RUN=true` 默认 (env unset = true) hardcode 在 jobs 顶部
2. Helm values.yaml 显式 `DRY_RUN: "true"` 注释 "Phase 2 follow-up #XXX 翻 false 前必须先关 gateway scheduler"
3. Phase 2 follow-up issue 标题 explicit "**先**关 gateway scheduler **再**翻 dry_run"
4. /metrics 加 `tx_sync_worker_dry_run_active{value}` gauge, monitoring alert dry_run=false 触发 → 创始人 immediate 通知

### 7.2 timezone drift (P1)

**风险**: gateway scheduler `timezone="Asia/Shanghai"` (sync_scheduler.py:595, main.py:70). tx-sync-worker 容器内 `/etc/localtime` 默认 UTC. Python `pytz.timezone("Asia/Shanghai")` 应正确解析 (apscheduler 内部用 pytz), 但若代码漏传 `timezone=` 参数 → 02:00 Asia/Shanghai 跑成 02:00 UTC = 10:00 北京 = 高峰期误同步.

**缓解**:
1. test_scheduler_registration.py:`assert str(job.trigger.timezone) == "Asia/Shanghai"` (per §3.4)
2. Dockerfile 加 `ENV TZ=Asia/Shanghai` (可选, apscheduler 用 trigger.timezone 优先)
3. main.py lifespan 启动 log `scheduler_started`, `default_timezone=str(scheduler.timezone)`

### 7.3 dup task firing (P0 if dry_run 误关)

**与 7.1 重叠**, 单独列因 critic reviewer focus:
- Phase 1 双轨期, 两套 daemon 同时存在
- 缓解依赖 dry_run=true 严格

### 7.4 metric collision (P2)

**风险**: gateway 自带 `apscheduler_jobs_executed_total` (prometheus_fastapi_instrumentator 自动 + apscheduler integration) 与 tx-sync-worker `tx_sync_worker_executions_total` 共存于 Prometheus.

**缓解**:
1. metric 名 prefix 强制 `tx_sync_worker_` 不冲突
2. label `service="tx-sync-worker"` 区分
3. Grafana dashboard 升级 Phase 2 follow-up

### 7.5 sync_logs 写入失败级联 (P1)

**风险**: tx-sync-worker `_write_sync_log` 调 `async_session_factory()` 复用 SQLAlchemy ontology session. 与 sync_scheduler.py 同路径. asyncpg pool 不一致风险? 不: 都用同 `shared.ontology.src.database.async_session_factory`, 同 engine.

**缓解**: 0 (使用 shared 同模块).

### 7.6 wecom_group_service.py 跨服务 import (P2)

**风险**: tx-sync-worker jobs/wecom_sop.py 跨服务 import gateway 内部模块 (`services.gateway.src.wecom_group_service`). 微服务边界违反.

**评估**: 与 sync_scheduler.py:130 `from shared.adapters.pinzhi_pos.src...` 同模式 (sync_scheduler.py 在 gateway 但 import shared), 但 wecom_group_service.py 在 gateway 内部不是 shared/. **决策**: Phase 1 保留 (避免移文件破坏 Tier 1 邻接边界), Phase 2 follow-up 把 wecom_group_service.py 拆到 shared/wecom/ 子包再 import.

---

## §8 4 人日估时分解 (汇总, 详 §3 每步)

| Day | 内容 | 人时 |
|---|---|---|
| D1 (Mon) | §3.1 骨架 + §3.2 conftest/Dockerfile/req + §3.3 main/scheduler/jobs/metrics 大部 | 2.0 人日 (16h) |
| D2 (Tue) | §3.3 收尾 (metrics + jobs 最后) + §3.4 测试 3 file 12 cases | 1.0 人日 (8h) |
| D3 (Wed) | §3.5 Helm 11 file + §3.6 compose/dev/port + §3.7 governance/DEVLOG/open-q 大部 | 1.0 人日 (8h) |
| D4 (Thu) | §3.7 收尾 + §3.8 §19 三 reviewer 流程 + admin-merge ship + buffer | 1.0 人日 (8h) |
| **合计** | | **4.0 人日** (32h) |

Phase 2 follow-up (本 PR 立 issue, 不实施): 另估 2 人日 (W4 demo 轨, 关 gateway scheduler + 翻 dry_run + 验收 last_sync_at 对账).

---

## §9 §17/G10 红线 audit (显式列出 untouched 路径)

本 PR 严禁触动以下 §17 Tier 1 零容忍 + §G10 供应链双红线路径:

| 路径 | 红线类型 | 本 PR 触动? |
|---|---|---|
| `services/tx-trade/cashier_engine.py` | §17 订单状态机 + G10 供应链邻接 | ❌ 0 改动 |
| `services/tx-trade/order_service.py` | §17 订单状态机 + G10 供应链邻接 | ❌ 0 改动 |
| `services/tx-trade/payment_saga_service.py` | §17 支付补偿 Saga | ❌ 0 改动 |
| `services/tx-trade/invoice.py` (invoice_service.py) | §17 全电发票 / 金税四期 | ❌ 0 改动 |
| `services/tx-supply/inventory_io.py` | §17 库存写入 + G10 主线 | ❌ 0 改动 |
| `shared/events/src/emitter.py` | Tier 1 邻接事件总线 | ❌ 0 改动 |
| `shared/events/src/projector.py` | Tier 1 邻接事件总线 | ❌ 0 改动 |
| `shared/events/src/pg_event_store.py` | Tier 1 邻接事件总线 | ❌ 0 改动 |
| `shared/ontology/` (全目录) | §18 创始人冻结 | ❌ 0 改动 |
| `services/gateway/src/main.py` | Phase 1 边界 (Phase 2 才改) | ❌ 0 改动 |
| `services/gateway/src/sync_scheduler.py` | Phase 1 copy 不 modify | ❌ 0 改动 |
| `services/gateway/src/wecom_group_service.py` | 仅 import 不改 | ❌ 0 改动 |
| `shared/adapters/pinzhi_pos/` (全 12 文件) | 仅 import 不改 | ❌ 0 改动 |
| 任何 alembic migration | 本 PR 无 schema 改动 | ❌ 0 改动 |
| `cashier_engine.py` / `order_service.py` 测试集 | §17 + G10 | ❌ 0 改动 |

**双 audit 验证命令** (ship 前必跑):
```bash
$ git diff --name-only origin/main..HEAD | grep -E "(cashier_engine|order_service|payment_saga|invoice|inventory_io|emitter\.py|projector\.py|pg_event_store\.py|shared/ontology|alembic|migrations)"
# 期望: 0 行输出

$ git diff --name-only origin/main..HEAD | grep -E "services/gateway/"
# 期望: 0 行输出 (gateway 0 改动 = Phase 1 边界严守)

$ git diff --stat origin/main..HEAD | tail -5
# 期望: ~22 新增 + 4 修改 (infra + docs only) + 0 gateway/shared 改
```

---

## §10 Plan Summary

**Plan saved to:** `.omc/plans/2026-05-18-gateway-slim-plan.md`

**Scope:**
- 22 新增 (services/tx-sync-worker/ 11 files + infra/helm/tx-sync-worker/ 11 files) + 4 修改 (infra+docs) + 2 新增 (governance + open-q)
- Estimated complexity: **MEDIUM** (复用 tx-event-relay 模板 + copy 业务函数 + 0 业务改动 = 低风险; 双轨并行 = 中风险)
- Tier: **T2 (非 Tier 1)**, §19 三 reviewer 走但不强制 Tier 1 邻接 5 项 explicit-ask
- 4 人日预算严格符合

**Key Deliverables:**
1. tx-sync-worker 新服务 (端口 8021, dry_run=true 默认)
2. 5 cron jobs 完整复制 (4 pinzhi + 1 wecom, 0 业务函数 diff)
3. Helm chart 11 文件 (T2 maxU=1)
4. infra/compose 注册 + Phase 2 follow-up issue 立
5. 守门会决议 + open-questions 落盘

**Does this plan capture your intent?**
- "proceed" — Begin implementation via /oh-my-claudecode:start-work
- "adjust [X]" — Return to interview to modify
- "restart" — Discard and start fresh
