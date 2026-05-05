# Compose 全矩阵自检结果 — 2026-05-04

> P0.5 阶段 E + 阶段 F。验证所有 base + env / base + env + tenant /
> base + env + tenant + special 组合在 `docker compose config` 阶段
> 全部通过。

## 验证环境
- Docker Compose: v5.0.2
- 工作目录: `/Users/lichun/.tunxiang-p0-worktrees/compose`
- 分支: `feat/p0-compose-consolidation`

## 必填环境变量（用最小占位测试）

```bash
export DATABASE_URL=postgresql://x@x/x
export POSTGRES_USER=tunxiang
export POSTGRES_PASSWORD=x
export POSTGRES_DB=tunxiang_os
export TX_JWT_SECRET_KEY=x
export DEVFORGE_DATABASE_URL=postgresql://x@x/x
export REDIS_PASSWORD=p
```

## 矩阵结果

### 基础矩阵（不带 tenant）

| # | 组合 | 命令 | 结果 |
|---|------|------|------|
| 1 | base | `docker compose -f infra/compose/base.yml config` | OK |
| 2 | base + dev | `... -f infra/compose/envs/dev.yml config` | OK |
| 3 | base + staging | `... -f infra/compose/envs/staging.yml config` | OK |
| 4 | base + prod | `... -f infra/compose/envs/prod.yml config` | OK |
| 5 | base + demo | `... -f infra/compose/envs/demo.yml config` | OK |
| 6 | base + gray | `... -f infra/compose/envs/gray.yml config` | OK |
| 7 | base + dev + resource-limits | `... -f infra/compose/special/resource-limits.yml config` | OK |
| 8 | base + dev + toxiproxy | `... -f infra/compose/special/toxiproxy.yml config` | OK |

### 租户独立部署矩阵（生产场景，无偏移）

> P0.5 阶段 F 新增。tenants/*.yml 已剥离所有 host 端口映射。

| # | 组合 | 结果 |
|---|------|------|
| 9 | base + prod + tenants/czyz | OK |
| 10 | base + prod + tenants/sgc | OK |
| 11 | base + prod + tenants/zqx | OK |

命令模板：
```bash
docker compose -f infra/compose/base.yml \
               -f infra/compose/envs/prod.yml \
               -f infra/compose/tenants/<x>.yml config
```

### 租户演示矩阵（demo + tenant，原阶段 E 沿用）

| # | 组合 | 结果 |
|---|------|------|
| 12 | base + demo + tenants/czyz | OK |
| 13 | base + demo + tenants/zqx | OK |
| 14 | base + demo + tenants/sgc | OK |

### 同机联调矩阵（dev + tenant + special/multi-host-dev，dev-only）

> P0.5 阶段 F 新增。multi-host-dev.yml 通过 `${SERVICE_HOST_PORT:-默认}`
> 全量变量提供主机端口暴露。三份 `.env.<tenant>.dev.example` 分别给出
> 偏移 0 / +100 / +200 的示例。

| # | 组合 | 结果 |
|---|------|------|
| 15 | base + dev + tenants/czyz + special/multi-host-dev | OK |
| 16 | base + dev + tenants/zqx + special/multi-host-dev | OK |
| 17 | base + dev + tenants/sgc + special/multi-host-dev | OK |

命令模板：
```bash
set -a && source infra/compose/special/.env.<tenant>.dev.example && set +a
docker compose -f infra/compose/base.yml \
               -f infra/compose/envs/dev.yml \
               -f infra/compose/tenants/<tenant>.yml \
               -f infra/compose/special/multi-host-dev.yml config
```

**17/17 通过。** 全部 config 校验返回 exit 0。

## 不在矩阵的组合（已验证不会同时使用）
- gray + tenants：gray 走 host 网络复用生产 PG，与租户独立 DB 互斥
- prod + special/toxiproxy：toxiproxy 仅用于 dev/staging 故障注入
- prod + resource-limits + toxiproxy：未来需要测试 prod 压测时再单独验证
- prod + tenants + multi-host-dev：multi-host-dev 是 dev-only 设计，禁止叠加生产

## 关键决策落地的 yaml 验证点
- gray.yml 的 `network_mode: host` + `networks: !reset null` 已在每个 service
  显式声明（19 处），合并 base 后无 mutually exclusive 冲突
- 所有 service 含 `labels.tunxiang.env=${TUNXIANG_ENV:-…}`，
  `docker ps --filter "label=tunxiang.env=dev"` 可定位
- prod.yml 内 `postgres-replica` 是 base 之外新增 service（不修改 base 的 postgres）
- **tenants/*.yml 不再含 `ports: !override`**（阶段 F 剥离）；改为 `multi-host-dev.yml`
  使用 `ports: !override` 替换 dev.yml 里的硬编码 host 端口
- **tenants/*.yml 中 `seed-data` 服务声明 `profiles: [seed]`**（阶段 F 修复）：
  默认不启动，`prod + tenant` 场景里 compose 整体丢弃 seed-data，
  避免它依赖的 `migrate`（demo.yml 提供）触发 undefined service 校验

## 后续 CI 接入提示
本次未改动 `.github/workflows/`。当 CI 切换至新路径时，建议先用本表的 17 项作为 CI 冒烟。

## Phase 4 执行结果（2026-05-04）

P0.5 后下游引用已全部对齐 `infra/compose/`。

### 阶段 G — CI workflows
| 文件 | 改动要点 |
|------|---------|
| `.github/workflows/deploy.yml` | staging/prod ssh 部署改用 `base.yml + envs/{staging,prod}.yml` |
| `.github/workflows/toxiproxy-smoke.yml` | toxiproxy 启停改用 `base.yml + envs/dev.yml + special/toxiproxy.yml` |
| `.github/workflows/offline-e2e.yml` | paths 触发器从 `infra/docker/docker-compose.toxiproxy.yml` 改为 `infra/compose/special/toxiproxy.yml` |
| `.github/workflows/pr-check.yml` | path 分类去掉已废弃的 `docker-compose*` 通配 |

四份 workflow 均通过 `python -c "import yaml; yaml.safe_load(open(f))"` 校验。

### 阶段 H — scripts
| 文件 | 改动要点 |
|------|---------|
| `scripts/auto-sync.sh` | `COMPOSE_FILE`+`COMPOSE_DIR` → `COMPOSE_ARGS=(-f base -f envs/prod)`；监听路径含 `infra/compose/` |
| `scripts/rollback-service.sh` | `ps` + `up -d` 改用 base + envs/prod |
| `scripts/deploy.sh` | 重构 — 引入 `compose_files_for_target()` 函数；`docker-compose` → `docker compose`（v2） |
| `scripts/gate1-manual-ops.sh` | 8.1/8.2 提示词改用 base + envs/prod |
| `scripts/setup-security-keys.sh` | 下一步指引改用 base + envs/prod |
| `scripts/week8_gate_check.sh` | 端口冲突扫描器改扫 `infra/compose/envs/*.yml`（dev 主文件 envs/dev.yml） |
| `scripts/DEPLOY_QUICKSTART.md` | 日志命令同步对齐 |

七份脚本均通过 `bash -n` 语法校验。

### 阶段 I — Helm chart 端口反向校验
14 个 chart 全部对齐 `infra/compose/base.yml` 权威源（无端口变更，无 image tag 变更）：

| chart | values.yaml port | 权威端口 | 状态 |
|-------|------------------|----------|------|
| api-gateway | 8000 | 8000 | OK |
| tx-trade | 8001 | 8001 | OK |
| tx-menu | 8002 | 8002 | OK |
| tx-member | 8003 | 8003 | OK |
| tx-growth | 8004 | 8004 | OK |
| tx-ops | 8005 | 8005 | OK |
| tx-supply | 8006 | 8006 | OK |
| tx-finance | 8007 | 8007 | OK |
| tx-agent | 8008 | 8008 | OK |
| tx-analytics | 8009 | 8009 | OK |
| tx-brain | 8010 | 8010 | OK |
| tx-intel | 8011 | 8011 | OK |
| tx-org | 8012 | 8012 | OK |
| web-admin | 80 | 80（前端） | OK |

**未发现错位**——本次仅做读取式校验，未做改动。`mcp-server / tx-pay / tx-predict / tx-civic / tx-expense / tx-forge / tx-devforge` 在 `infra/helm/` 下无独立 chart（待 P0-2/后续补齐）。

机器无 helm CLI，未跑 `helm template`；所有 `values.yaml` 通过 `python -c "import yaml; yaml.safe_load(...)"` 语法校验。

### 阶段 J — 残留扫描（已清零）
两条扫描全空：
- `grep -rn 'docker-compose\.(yml|prod|staging|gray|dev|demo|czyz|sgc|zqx|toxiproxy|resource-limits)'`（排除归档文档）
- `grep -rn 'infra/docker/docker-compose'`（排除 `infra/compose/special/`、归档文档）

附带改动（避免开发者跟着废弃路径走）：
- `Makefile` — 引入 `COMPOSE_BASE/_DEV/_PROD/_STAGING/_GRAY` 变量，所有目标走 base + envs/<env>
- `README.md` — 部署一节改用新命令
- `.env.staging.example` / `.env.gray.example` — 示例命令对齐
- `infra/nginx/conf.d/api.conf` — 注释文件名改为 `infra/compose/envs/dev.yml`
- `e2e/README.md` / `e2e/scripts/toxiproxy-inject.sh` — toxiproxy 启动方式对齐
- `shared/test_infra/fixtures.py` / `shared/test_infra/tests/test_toxiproxy_smoke.py` — toxiproxy 启动指引对齐

### 归档文档（按设计保留旧路径，不改）
`DEVLOG.md`、`docs/progress.md`、`docs/audit-regression-2026-07.md`、`docs/credential-migration-guide.md`、`docs/harness-architecture.md`、`docs/devforge-platform-plan.md`、`docs/may-gap-closure-plan-2026-05.md`、`docs/test-infra-toxiproxy.md`、`docs/infra/compose-consolidation-proposal-2026-05.md`、`docs/infra/compose-topology-audit-2026-05.md` 中保留旧路径作为时间快照。

### `infra/compose/special/*.yml` 内的旧路径注释
`special/toxiproxy.yml` 与 `special/resource-limits.yml` 中头部注释仍引用 `infra/docker/docker-compose.*`。本次按"不碰 base.yml/envs/tenants/special（P0.5 已稳定）"约束**未修改**，可在 P0.6 维护轮中一并校正。

## 端口最终分配
见 `docs/infra/port-allocation-2026-05.md`。
