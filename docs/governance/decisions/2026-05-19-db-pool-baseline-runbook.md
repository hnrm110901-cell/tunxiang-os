# DB Pool Baseline Runbook (#737 Phase A / W3 G10 邻接)

**Status**: Phase A 基础设施 ship, Phase B 真测量待启动
**Owner**: tunxiang-platform infrastructure
**Date**: 2026-05-19
**Issue**: [#737](https://github.com/hnrm110901-cell/tunxiang-os/issues/737)
**PR**: Phase A 基础设施 PR (本 PR)
**Predecessor**: [#734](https://github.com/hnrm110901-cell/tunxiang-os/issues/734) (5/17 Phase 0 baseline methodology decision)

---

## §1 Background

PG 16 default `max_connections=100`. 屯象 OS 当前部署 20 微服务 + cert_alerter daemon + N
projector daemon, **理论峰值连接数 = 20 × (pool_size=20 + max_overflow=30) +
projector_count × asyncpg_pool_max=3 + cert_alerter_count × (5+10) = ~1000+ →
远超 PG default**.

#737 Phase 0 baseline 5/17 已完成 methodology + sampler.sql/sampler.py + decision
matrix, 但**当时未真测量**. Phase A 本 PR 建测量基础设施 + env knob 入口,
让 Phase B 真测量后能快速翻起 prod 池子.

3 个 pool 源 (verified 5/19):
| 源 | 文件 | 类型 | Ship 前 default | env knob |
|---|---|---|---|---|
| SQLAlchemy 共享 engine | `shared/ontology/src/database.py:15-22` (line 14 dead, #738 scope) | SQLAlchemy async | `pool_size=20, max_overflow=30, pool_pre_ping=True, pool_recycle=300` | `DATABASE_POOL_SIZE` + `DATABASE_POOL_OVERFLOW` |
| projector asyncpg pool | `shared/events/src/projector.py:93,153` (run + rebuild) | asyncpg.create_pool | `min_size=1, max_size=3` (run); `min_size=1, max_size=2` (rebuild → 统一为 3) | `ASYNCPG_POOL_MAX` |
| cert_alerter engine | `services/tx-supply/src/workers/cert_expiry_alerter.py:42` | SQLAlchemy async (独立) | `pool_size=5, max_overflow=10` | `CERT_ALERTER_POOL_SIZE` + `CERT_ALERTER_POOL_OVERFLOW` |

---

## §2 Phase A/B/C 划分

### Phase A (本 PR, 2026-05-19 ship)

**目标**: 把 3 个 pool 源 hard-coded default 抽成 env knob, 加测量脚本, 加 runbook.
**不改任何 default 值**, env unset 时 ship 前后完全等价 (regression-safe).

Deliverable:
- `scripts/ops/db_pool_baseline.py` — pg_stat_activity 测量 CLI (JSON/Markdown/both)
- 3 个 pool 源 Python 改造 (env-controllable)
- `infra/helm/tx-supply/values.yaml` + `infra/helm/tx-analytics/values.yaml` env 段
- `infra/compose/base.yml` x-env: &common-env anchor env
- 静态层 10 + 单元 7 个测试

### Phase B (W4 起手, 真测量 + 决策)

**目标**: 在 dev 环境跑 baseline 1 周, 量化每服务 usage_pct, 触发决策矩阵.

SoP:
```bash
# 1. dev 跑 baseline (每小时)
*/60 * * * * cd /home/ops/tunxiang-os && \
  DATABASE_URL=postgresql://... \
  python scripts/ops/db_pool_baseline.py \
    --service all --output json \
    --report-path /var/log/tunxiang/db-pool-$(date +\%Y\%m\%d-\%H).json

# 2. 一周后聚合
jq -s '[.[] | .usage_pct] | max, min, (add/length)' /var/log/tunxiang/db-pool-*.json

# 3. 触发决策 (见 §4)
```

### Phase C (W5+ 起手, ratchet 上调)

**目标**: 按 Phase B 决策矩阵翻起 helm values, rolling restart, 实测验证后归档.

---

## §3 Phase A baseline SoP (Phase B 之前的烟测)

```bash
# 1. set DSN (dev / staging / prod 任一)
export DATABASE_URL='postgresql://tunxiang:***@host:5432/tunxiang_os'

# 2. 单次测量 → stdout markdown
python scripts/ops/db_pool_baseline.py

# 3. JSON 落 ops/baseline.json + threshold 阈值 (默认 60%/80%)
python scripts/ops/db_pool_baseline.py \
  --service all \
  --output json \
  --report-path /tmp/baseline.json \
  --threshold-warn 60 \
  --threshold-error 80

# 退出码:
#   0  < 60%   (healthy, 不需扩 pool)
#   1  60-80%  (warn,  Phase B 真测量阶段触发预警)
#   2  >= 80%  (error, 立即扩 pool 或 scale-down 服务)
#   3  infra 故障 (DSN 错配 / PG 不可达)
```

---

## §4 Phase B 决策矩阵

测量 1 周后, 按 max usage_pct 触发:

| max usage_pct | 决策 | 操作 |
|---|---|---|
| < 60% | NO-OP | 保持 default, Phase C 不启动. 季度复测. |
| 60-80% | 预警, 可选扩容 | 灰度 1 服务翻起 helm values (e.g. tx-supply DATABASE_POOL_SIZE=40), 观察 2d. |
| > 80% | 必须立即扩 | Phase C 全量 ratchet: helm values 翻起 + rolling restart + alert hook. |

---

## §5 Phase C ratchet 路径 (Phase B 触发后)

```bash
# 1. 灰度 1 service (e.g. tx-supply)
helm upgrade tx-supply infra/helm/tx-supply \
  --set env.DATABASE_POOL_SIZE=40 \
  --set env.DATABASE_POOL_OVERFLOW=60 \
  --reuse-values

# 2. rolling restart 观察 24h
kubectl rollout status deployment/tx-supply -n tunxiang-prod

# 3. 重跑 baseline 验 usage_pct 下降
python scripts/ops/db_pool_baseline.py --service tx-supply

# 4. 归档到 docs/governance/decisions/<date>-db-pool-ratchet-<service>.md
```

---

## §6 紧急回滚 (Phase B/C 翻 ON 后业务异常)

```bash
# 1. helm rollback 单 service (回到 Phase A default)
helm rollback tx-supply 1   # 1 = Phase A baseline revision

# 2. 或运行时 env override (无需重新部署)
kubectl set env deployment/tx-supply \
  DATABASE_POOL_SIZE=20 \
  DATABASE_POOL_OVERFLOW=30 \
  -n tunxiang-prod
kubectl rollout restart deployment/tx-supply -n tunxiang-prod

# 3. scale-down 兜底 (减少总连接数)
kubectl scale deployment/tx-supply --replicas=1 -n tunxiang-prod
```

---

## §7 关联 PR / Issue

- **#737** — Phase A/B/C 主 issue (本 runbook 锚点)
- **#734** — Phase 0 baseline methodology (5/17 ship, 本 PR 续接)
- **#738** — `shared/ontology/src/database.py:14` dead engine 清理 (独立 PR, 本 PR 不动)
- **#776** — W2/W3 governance follow-up (cert_alerter pool 决议来源)
- **PR-B/C/D** — Phase 2 W12 灰度链 (PR-D defaultValue:true 100% + #737 Phase 1 真测量 同期)
- **W4 #806** — Wave 4 PR-1 main.py module-level logger drift 教训 (executor 红线参考)

---

## §8 决策记录 (User Gate 4 Q, 2026-05-19)

| Q# | Question | Decision | Reason |
|---|---|---|---|
| Q1 | env knob 拆分粒度 | **B** (3 env knob: DATABASE_POOL_SIZE + DATABASE_POOL_OVERFLOW SQLAlchemy 共享 / ASYNCPG_POOL_MAX projector + cert_alerter 共用 / CERT_ALERTER_POOL_SIZE+OVERFLOW 独立) | cert_alerter 是独立 SQLAlchemy engine 不是 asyncpg pool, 需要独立 scope; projector + asyncpg 类同源可共 env |
| Q2 | default 是否动 | **A** (不动) | env unset 时 regression-safe, 与 ship 前完全等价 |
| Q3 | dead engine line 14 是否顺手清理 | **A** (#738 独立 PR scope) | 严格 #737 scope, 不顺手 |
| Q4 | Prometheus gauge | **A** (留 Phase B 测量时再决定) | Phase A 只是基础设施入口, 测量真起来再决定 metric 形态 |

---

## §9 Verify checklist (ship 前)

- [x] 3 个 pool 源 env knob 注入完成 (verify: scripts/ops/tests/test_pool_env_static.py 10/10 pass)
- [x] helm tx-supply 5 env + tx-analytics 3 env (verify: helm template render)
- [x] compose base.yml x-env anchor 5 env (verify: PyYAML safe_load merge 入 gateway service)
- [x] §17 红线 0 touch (verify: `git diff --name-only origin/main..HEAD` 0 match cashier_engine/order_service/payment_saga/wine_storage/invoice/emitter/adapter)
- [x] DEVLOG.md + docs/progress.md 顶部 anchor 干净 (5/19 #820 块) + 本 PR prepend
- [x] §0 verify summary 落 `.omc/state/sessions/2026-05-19-db-pool-baseline-737/verify-summary.md`
