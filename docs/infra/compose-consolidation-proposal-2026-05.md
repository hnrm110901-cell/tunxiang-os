# 屯象OS Compose 收敛方案提案 — 2026-05-04

> P0.5 第一阶段输出。三个收敛方向 + 推荐 + 第二阶段执行 checklist。
>
> 配套审计：`docs/infra/compose-topology-audit-2026-05.md`
>
> **本文档不修改任何 docker-compose 文件，落地需第二阶段单独 PR。**

---

## 决断前提（必须先解的两个问题）

### Q1：哪个是后端权威源？
- 候选 A：`infra/docker/docker-compose.yml`（infra-base） — 服务最全（含 predict/pay/devforge）、用 anchor、scripts/rollback-service.sh 默认它
- 候选 B：根 `docker-compose.yml`（root-dev） — env-manager.sh 默认它、deploy.sh/auto-sync.sh 走根 prod/staging

**审计意见**：infra-base 在内容完整性上完胜（缺的只是 tx-expense:8015）。但 CI/CD 全部走根。**两条路径都存在历史依赖，必须显式收敛。**

### Q2：是否保留客户定制三个文件（czyz/sgc/zqx）？
- 这三个文件 95%+ 内容重复，是 base+override 的天然候选。
- 但**当前任务边界是不动它们**。本提案给出"以后如何收敛"的建议，本阶段执行时**不动**。

---

## 收敛方向 A：标准 Compose base + override 模型 ⭐⭐⭐⭐⭐（推荐）

### 目标目录结构
```
docker-compose.yml                       # 默认 dev 工作流（开发首选，docker compose up 即用）
infra/compose/
  base.yml                               # 后端服务权威源（19 service，含 predict/pay/devforge/civic/expense）
  envs/
    dev.override.yml                     # 端口暴露/hot reload/profile=edge/sync-engine（取代 root-dev 大部分内容）
    staging.override.yml                 # 资源减半/auth=on（取代 root-staging + infra-staging）
    prod.override.yml                    # 主从 PG/celery/pg-backup/nginx+SSL（合并 root-prod + infra-prod）
    gray.override.yml                    # network_mode=host + 复用生产 PG（取代 root-gray）
    demo.override.yml                    # 精简 6 服务 + seed（取代 infra-demo）
  resource-limits.yml                    # 现 resource-limits.yml 原地保留
  toxiproxy.yml                          # 现 toxiproxy.yml 原地保留（已是 override 模型）
  tenants/
    czyz.override.yml                    # 仅 env + 端口偏移 + volume 名（瘦身到 ~50 行）
    zqx.override.yml                     # 同上
    sgc.override.yml                     # 同上
```

根 `docker-compose.yml` 改为符号链接或 1 行 include 指向 `infra/compose/base.yml + dev.override.yml`，让"`cd repo && docker compose up`" 仍然 just-work（开发者无感）。

### 启动方式（统一）
```bash
# Dev（默认）
docker compose up -d

# Staging
docker compose -f infra/compose/base.yml -f infra/compose/envs/staging.override.yml up -d

# Prod
docker compose -f infra/compose/base.yml -f infra/compose/envs/prod.override.yml -f infra/compose/resource-limits.yml up -d

# Gray
docker compose -f infra/compose/base.yml -f infra/compose/envs/gray.override.yml --env-file .env.gray up -d

# Tenant czyz
docker compose -f infra/compose/base.yml -f infra/compose/tenants/czyz.override.yml up -d

# Demo
docker compose -f infra/compose/base.yml -f infra/compose/envs/demo.override.yml up -d
```

### 对 CI/CD/脚本的影响（已 grep 实测）

| 文件 | 当前引用 | 调整动作 |
|------|----------|---------|
| `scripts/deploy.sh` | `docker-compose.staging.yml` / `docker-compose.prod.yml` | 改为 `-f infra/compose/base.yml -f infra/compose/envs/$env.override.yml` |
| `scripts/auto-sync.sh` | `docker-compose.prod.yml`（根） | 同 |
| `scripts/env-manager.sh` | dev→根、prod→根 prod、pilot→根 staging | 路径表统一改为 envs/* |
| `scripts/demo_deploy.sh` | `infra/docker/docker-compose.demo.yml` | 改为 base + demo.override.yml |
| `scripts/rollback-service.sh` | `infra/docker/docker-compose.yml`（infra-base） | 改为 base.yml；逻辑不变 |
| `scripts/week8_gate_check.sh` | `infra/docker/docker-compose*.yml`（grep） | 改为 `infra/compose/**/*.yml` |
| `.github/workflows/deploy.yml` | 根 prod/staging | 改为 base + envs/* |
| `.github/workflows/toxiproxy-smoke.yml` | `infra/docker/docker-compose.toxiproxy.yml` | 改为 `infra/compose/toxiproxy.yml`（路径） |
| `.github/workflows/offline-e2e.yml` | path filter 同上 | 同 |
| `.github/workflows/pr-check.yml` | path filter `docker-compose*` | 改为 `infra/compose/**` |
| `scripts/gate1-manual-ops.sh` | echo 文档 | 仅文本修订 |

### 工作量
- 第二阶段 1 PR：拆 base + 5 envs + 3 tenants（瘦身到 80%+ 重复消除）= **2-3 人天**
- 第三阶段 1 PR：CI/CD/脚本 11 处全部切到新路径 + 端到端冒烟 = **1-2 人天**
- 总计 **3-5 人天**

### 风险
| 风险 | 等级 | 缓解 |
|------|------|------|
| anchor/extends 兼容性 | 低 | docker compose 1.27+ 全支持，CI 用的就是新版 |
| 旧脚本残留引用未改全 | 中 | 第二阶段加 `grep -r "docker-compose\." scripts/ .github/` 验证清零 |
| root-prod 错位端口规划修复后引入回归 | 高 | base 用项目宪法的标准端口（8001-8017）；prod env 不再覆盖端口；CI 用 base 全量 smoke 验证 |
| 灰度环境 network_mode=host + 复用生产 PG 的语义被破坏 | 中 | gray.override.yml 严格保留 host 网络模式；新增冒烟测试验证可连通生产 PG |
| 客户租户文件瘦身需要重新对齐 KPI 注释 | 低 | tenants/*.override.yml 保留原 KPI 注释 |

### 推荐度 ⭐⭐⭐⭐⭐
- 原因：直接解 P0 错位风险（root-prod 缺服务+端口错位会真实部署失败）；同时把客户定制收敛掉 ~70% 重复行；docker compose 官方推荐模型，agent 后续不易再走偏。

---

## 收敛方向 B：二选一删除（保留 infra/docker/，删根 4 个文件）⭐⭐⭐

### 操作
1. 删 `docker-compose.yml`、`docker-compose.prod.yml`、`docker-compose.staging.yml`、`docker-compose.gray.yml`（根 4 个）
2. 把根 prod 独有的 `celery-worker / celery-beat / pg-backup / nginx / 6 个前端 build` 合并进 infra-prod
3. 把 sync-engine 合并进 infra-base（profile=edge 保留）
4. 重写 `scripts/deploy.sh`、`scripts/auto-sync.sh`、`scripts/env-manager.sh`、`.github/workflows/deploy.yml` 全部走 infra/docker/

### 工作量
- 内容合并 + 端口规划统一：**1.5 人天**
- 脚本/CI 改写：**1-2 人天**
- 总计 **2.5-3.5 人天**

### 风险
| 风险 | 等级 |
|------|------|
| 合并 root-prod celery/pg-backup 进 infra-prod 时遗漏 env 注入 | 中 |
| 任何外部文档/同事记忆里的"docker-compose up"突然失效 | 中 |
| 灰度环境 network_mode=host 合并不当导致 dev/prod 网络隔离失败 | 中 |
| 没有 base + override，下一次 P0-3/P0-4 类似问题再发生 | 高 |

### 推荐度 ⭐⭐⭐
- 比方向 A 工作量小一点，但**没有真正解决"重复粘贴"问题**（infra-base、infra-dev、infra-staging、infra-prod 之间仍 70% 重复）。
- 客户定制 czyz/sgc/zqx 仍然各自全量。
- 只是一次性整理，agent 下个月还会照旧重复粘贴。

---

## 收敛方向 C：现状保持 + 增强 README ⭐⭐

### 操作
1. 不动任何 compose 文件
2. 在 `infra/docker/README.md`（新建）写明：
   - 14 个文件的触发场景表
   - 哪些是"权威源"
   - root-prod 端口规划错位的警告
   - "新加服务必须改 X 个文件"清单
3. PR 模板加"如修改 docker-compose，请确认更新所有 N 个相关文件"checkbox

### 工作量
- **0.5 人天**

### 风险
| 风险 | 等级 |
|------|------|
| README 几乎肯定会过时 | 高 |
| 不解决 root-prod 缺 6 个服务+端口错位的 P0 风险 | **极高** |
| 下一个 agent 仍然不知道改哪份 | 高 |
| 客户租户文件 95% 重复无解 | 中 |

### 推荐度 ⭐⭐
- 只适合"明知架构不对但今年没人手收敛"的兜底。
- **本次任务背景是徐记海鲜 Week 8 DEMO 在即，不能容忍 P0 风险。不推荐。**

---

## 推荐：方向 A ⭐⭐⭐⭐⭐

**理由汇总**：
1. **修 P0**：root-prod 端口规划错位 + 缺 6 个服务，CI 自动部署会直接挂——必须修。方向 A 用 base 强制统一端口规划。
2. **解维护负担**：14 文件 ~70% 内容重复，加一个新服务要改至少 5 个文件——base+override 后只改 1 处。
3. **解错位风险**：本次审计的根因是"两组 P0 修复落在不同权威源"。方向 A 强制 base 唯一，避免重蹈。
4. **客户租户红利**：tenants/*.override.yml 后每文件可瘦身到 50 行（现 274 行），单一变更点（端口偏移、密码、tenant id），新增第四个客户从 4 小时降到 30 分钟。
5. **docker compose 官方模型**，新人/新 agent 看一次就懂，不需要项目专属知识。

**反对意见与回应**：
- "工作量 3-5 人天太多" → 方向 B 也要 2.5-3.5 人天，多出来的 1.5 人天换永久去重，是合算的。
- "改 11 个 CI/脚本引用风险大" → 第三阶段独立 PR，端到端冒烟门槛硬卡，回退也只是一行 git revert。
- "改根 docker-compose.yml 让其变成 include 是黑魔法" → 实际只需要根 compose 留 1 行 `include: [./infra/compose/base.yml, ./infra/compose/envs/dev.override.yml]`（compose 2.20+ 支持 `include` 语法），如不被支持就保留根作为 base 软链——开发者无感。

---

## 第二阶段执行 Checklist（待用户确认方向后启动）

### Phase 1: 抽 base + dev override（不动 CI）
- [ ] 创建 `infra/compose/base.yml`：从 infra-base 拷贝 + 补 tx-expense:8015 + 补 tx-growth（gateway env）
- [ ] 创建 `infra/compose/envs/dev.override.yml`：端口暴露 8001-8017、TX_AUTH_ENABLED=false、profile=edge sync-engine
- [ ] 让根 `docker-compose.yml` 用 `include` 或软链指向 base + dev.override
- [ ] 验证：在 worktree 跑 `docker compose config` 输出与现 root-dev 等价
- [ ] 提交：`docs(infra): compose base+dev override 抽取（不影响 CI）[Tier3]`

### Phase 2: 抽 prod / staging / gray override
- [ ] `prod.override.yml`：合并 root-prod 的 celery/pg-backup/nginx/前端 build + infra-prod 的 postgres-replica/certbot
- [ ] `staging.override.yml`：合并 root-staging 与 infra-staging
- [ ] `gray.override.yml`：保留 network_mode=host + 复用生产 PG
- [ ] **修复 root-prod 端口规划错位**：base 用 8001-8017 标准，gateway env 用容器名（http://tx-supply:8006 等）
- [ ] 删除根 `docker-compose.{prod,staging,gray}.yml`
- [ ] 端到端冒烟：staging 全栈起得来 + gateway /health 返回 16 个上游全 ok
- [ ] 提交：`refactor(infra): 收敛 prod/staging/gray compose [Tier1]`

### Phase 3: 抽 demo + tenants override
- [ ] `demo.override.yml`：精简 6 服务 + migrate
- [ ] `tenants/czyz.override.yml`：瘦身（仅端口/密码/tenant id/KPI 注释/seed 命令）
- [ ] `tenants/zqx.override.yml`：同上（保留 +100 偏移）
- [ ] `tenants/sgc.override.yml`：同上（保留 +200 偏移）
- [ ] **修 czyz 端口偏移**：建议改为 0（即保持单租户即默认 dev）或 +50；本阶段保守只做收敛不改端口偏移设计——单独议
- [ ] 删除原 czyz/zqx/sgc/demo 文件
- [ ] 验证：三租户并行 `docker compose -f base -f tenants/zqx -f tenants/sgc up`（czyz 仍冲突，留待后续）
- [ ] 提交：`refactor(infra): 收敛 demo + tenant compose [Tier1]`

### Phase 4: 切 CI/CD/脚本
- [ ] 改 `scripts/deploy.sh / auto-sync.sh / env-manager.sh / demo_deploy.sh / rollback-service.sh / week8_gate_check.sh / gate1-manual-ops.sh`
- [ ] 改 `.github/workflows/deploy.yml / pr-check.yml / toxiproxy-smoke.yml / offline-e2e.yml`
- [ ] 全文 `grep -rn 'docker-compose\.\(yml\|prod\|staging\|gray\)' scripts/ .github/` 必须返 0
- [ ] 端到端：在分支推一次 deploy.yml dry run，看 staging 部署绿
- [ ] 提交：`chore(ci): 切换至 infra/compose/* 拓扑 [Tier2]`

### Phase 5: 清理 P0-1 / P0-2 分支冲突
- [ ] rebase `feat/p0-pay-port-unify` 到新结构（tx-pay 已在 base.yml，无需重复加；只需保留 service 自身端口 8013→8016 修复 + 测试）
- [ ] rebase `feat/p0-forge-compose` 到新结构（tx-forge 加到 base.yml；gateway proxy 改动不变）
- [ ] 验证两个 PR 都能 merge 进新结构
- [ ] 提交：在各自 PR 上做 rebase commit

### Phase 6: 文档同步
- [ ] 更新 `docs/regional-deployment-guide.md`（如果有 compose 引用）
- [ ] 更新 `CLAUDE.md` §五"项目结构"中 `infra/docker/` 段落
- [ ] 更新 `DEVLOG.md` 当日记录
- [ ] 更新 `docs/progress.md`

---

## 不在本提案范围（已识别，留给后续）

1. **czyz 端口偏移问题** — 设计缺陷，需创始人决断（要不要让 czyz 也有 +50/+300 偏移）。
2. **infra/jumpserver/** 和 **infra/monitoring/** — 独立子系统，不在本次审计。
3. **k8s helm chart**（`infra/helm/`）— 完全独立的部署路径，与 compose 无关。
4. **gitops/** — 独立的部署声明，与 compose 不交叉。
5. **DEPLOYMENT 文档质量** — 收敛后统一更新一次 README 即可，本提案不展开。

---

## 决断请求

请创始人选择：
- [ ] 方向 A（base + override，3-5 人天，⭐⭐⭐⭐⭐ 推荐）
- [ ] 方向 B（删根 4 个，2.5-3.5 人天，⭐⭐⭐）
- [ ] 方向 C（保现状写 README，0.5 人天，⭐⭐ 不推荐）
- [ ] 其它（请说明）

确认后启动 P0.5 第二阶段。

---

## 执行结果（P0.5 阶段 2，2026-05-04）

用户最终决策：**方向 D**（删根 4 个 compose + infra/docker 内部用 base+override 重整）。
方向 D = 方向 A 与 B 的合体精简版：保留 base+override 模型 + 同时删根 4 个文件。

### 落地结构
```
infra/compose/
  base.yml                        # 16 服务唯一权威源
  envs/dev.yml                    # 主机端口暴露 + 热重载 + Vite Dev
  envs/staging.yml                # 镜像构建 + auth=on + 资源减半
  envs/prod.yml                   # PG 主从 + Nginx + Celery + pg-backup
  envs/demo.yml                   # 精简 6 业务 + migrate + seed
  envs/gray.yml                   # network_mode=host + 复用生产 PG
  tenants/czyz.yml                # 端口偏移 TODO（创始人决策）
  tenants/zqx.yml                 # +100
  tenants/sgc.yml                 # +200
  special/resource-limits.yml     # 压测叠加
  special/toxiproxy.yml           # 故障注入叠加
infra/docker/                     # Dockerfile / init-rls.sql / .env.example（不动）
```

### Commit 序列
| 阶段 | Commit | 说明 |
|------|--------|------|
| 1 | `85292aeb` | docs: 拓扑审计 |
| 1 | `3c3f05e8` | docs: 收敛方案 |
| 2A | `ef8a9e26` | feat: base.yml |
| 2B | `8ccd9f5c` | feat: 5 envs override |
| 2C | `d5d18f57` | feat: 3 tenants override |
| 2D | （本次） | chore: 删根 + scripts/CLAUDE.md |
| 2E | （后续） | docs: 矩阵自检 + 端口表 |

### 启动命令统一
```bash
# Dev
docker compose -f infra/compose/base.yml -f infra/compose/envs/dev.yml up -d

# Prod（叠加压测）
docker compose -f infra/compose/base.yml -f infra/compose/envs/prod.yml \
               -f infra/compose/special/resource-limits.yml up -d

# 三租户演示
docker compose -f infra/compose/base.yml -f infra/compose/envs/demo.yml \
               -f infra/compose/tenants/zqx.yml up -d
```

### 端口冲突最终决议（写入 base.yml 注释）
- tx-predict: 8013 → 8019
- mcp-server: 8014 → 8018
- tx-civic: 守 8014（宪法）
- 完整端口表 → `docs/infra/port-allocation-2026-05.md`
