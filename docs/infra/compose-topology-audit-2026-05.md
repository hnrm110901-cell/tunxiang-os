# 屯象OS Compose 拓扑审计 — 2026-05-04

> P0.5 第一阶段。审计 14 个核心 docker-compose 文件，定位职责重叠、端口冲突、租户独占资源、以及"哪个文件是后端权威源"问题。
>
> **本文档为只读审计，未修改任何 compose 文件。**

---

## 0. 审计范围

| # | 路径 | 行 | 简称 |
|---|------|---:|------|
| 1 | `docker-compose.yml` | 293 | root-dev |
| 2 | `docker-compose.prod.yml` | 429 | root-prod |
| 3 | `docker-compose.staging.yml` | 250 | root-staging |
| 4 | `docker-compose.gray.yml` | 196 | root-gray |
| 5 | `infra/docker/docker-compose.yml` | 342 | infra-base |
| 6 | `infra/docker/docker-compose.dev.yml` | 329 | infra-dev |
| 7 | `infra/docker/docker-compose.prod.yml` | 347 | infra-prod |
| 8 | `infra/docker/docker-compose.staging.yml` | 266 | infra-staging |
| 9 | `infra/docker/docker-compose.demo.yml` | 237 | infra-demo |
| 10 | `infra/docker/docker-compose.czyz.yml` | 274 | tenant-czyz |
| 11 | `infra/docker/docker-compose.sgc.yml` | 275 | tenant-sgc |
| 12 | `infra/docker/docker-compose.zqx.yml` | 274 | tenant-zqx |
| 13 | `infra/docker/docker-compose.resource-limits.yml` | 268 | resource-override |
| 14 | `infra/docker/docker-compose.toxiproxy.yml` | 67 | toxiproxy |

排除：`infra/jumpserver/docker-compose.yml`、`infra/monitoring/docker-compose.monitoring.yml`（独立子系统）。

审计基线：`main @ e328bb1d`（feat/p0-compose-consolidation 的祖先）。**未合并分支** `feat/p0-pay-port-unify`（P0-1）和 `feat/p0-forge-compose`（P0-2）单独分析，见 §6。

---

## 1. 后端权威源判定

`infra/docker/docker-compose.yml`（**infra-base**）是**当前事实上的后端权威源**：

- 服务覆盖最全：16 个后端服务（gateway + 14 业务 + tx-devforge），且**只有它**包含 `tx-predict:8013`、`tx-pay:8016`、`tx-devforge:8017` 三项最新业务。
- gateway 环境注入了完整的 `TX_*_URL`（包括 PREDICT/PAY/DEVFORGE）。
- 使用 YAML anchor (`x-build`/`x-svc`/`x-env`) 抽取共性，是唯一一个写法专业的基线。
- 引用方：`scripts/rollback-service.sh`、`scripts/week8_gate_check.sh` 都默认它。

但**根目录 `docker-compose.yml`（root-dev）也仍被脚本引用**：

- `scripts/env-manager.sh` 把 dev/test/uat/demo/prod/pilot 全部映射到根 compose 文件。
- `scripts/deploy.sh` 用 `docker-compose.staging.yml` / `docker-compose.prod.yml`（根）。
- `.github/workflows/deploy.yml` 用根 prod/staging。
- `scripts/auto-sync.sh` 默认根 prod。

**结论**：CI/CD 自动化几乎全部走"根目录 compose"，但根目录 compose 落后 infra/docker/ 至少 3 个服务（tx-predict/tx-pay/tx-devforge）。这是错位的根因——开发时一部分 agent 改 root，一部分改 infra/docker，互不知情。

---

## 2. 各 compose 文件 service 清单与差异

### 基线（infra-base）服务清单（16 个）

```
postgres / redis / gateway / tx-trade / tx-menu / tx-member / tx-growth /
tx-ops / tx-supply / tx-finance / tx-agent / tx-analytics / tx-brain /
tx-intel / tx-org / tx-predict / tx-civic / tx-pay / tx-devforge
```
共 19 service（含 2 基础设施）。**注意 infra-base 缺 `tx-expense:8015`（CLAUDE.md 也未列入），但 root-dev 有它。**

### 详表

| 文件 | service 总数 | 比 infra-base 多 | 比 infra-base 少 | 备注 |
|------|---:|------|------|------|
| **root-dev** | 16 | `tx-expense:8015`、`sync-engine`(profile=edge) | `tx-predict`、`tx-pay`、`tx-devforge`、`tx-growth` | 默认 dev 启动；外设/边缘 sim |
| **root-prod** | 19 | `nginx`、`certbot`(无)、`celery-worker`、`celery-beat`、`pg-backup`、6 个前端 (web-hub/web-admin/web-pos/web-kds/miniapp/web-forge) | `tx-predict`、`tx-pay`、`tx-devforge`、`tx-civic`、`tx-expense`、`tx-growth` | **端口规划与项目宪法不一致**（详见 §3） |
| **root-staging** | 14 | 全部 service 加 `stg-` 前缀；`stg-nginx`、3 前端 (stg-web-pos/admin/kds) | `tx-predict`、`tx-pay`、`tx-devforge`、`tx-civic`、`tx-expense`、`tx-growth`、`tx-brain`、`tx-intel` | 与 root-prod 共住一台机器，端口偏移 +100；命名空间隔离 (`stg-*`) |
| **root-gray** | 13 | 全部加 `gray-` 前缀；`gray-nginx`、3 前端 | 同 root-staging | `network_mode: host` + 复用生产 PG/Redis；连**生产数据库**（关键风险） |
| **infra-base** | 19 | — | — | **后端权威源** |
| **infra-dev** | 18 | `tunxiang-api:8013`、`mcp-server:8014`、3 前端（vite hot reload） | `tx-civic`(被 mcp-server 占 8014)、`tx-pay:8016`、`tx-expense:8015`、`tx-growth`、`tx-supply` 等部分服务名缺失 | **端口冲突源**：`tunxiang-api:8013` 与 `tx-predict:8013` 冲突；`mcp-server:8014` 与 `tx-civic:8014` 冲突 |
| **infra-prod** | 14 | `postgres-replica`(主从占位)、`certbot`、`nginx`(用 infra/nginx config) | `tunxiang-api`、`mcp-server`、`tx-pay`、`tx-civic`、`tx-devforge`、`tx-growth`、`tx-expense` | 注释里有 "tunxiang-api 和 mcp-server 尚无 requirements.txt，暂不部署"——和 infra-dev 不对齐 |
| **infra-staging** | 16 | `tunxiang-api:8013`、`mcp-server:8014`、3 前端（镜像构建） | 同 infra-prod 缺项 | 与 infra-dev 在 8013/8014 端口分配上一致，但与 infra-base 冲突 |
| **infra-demo** | 9 | `migrate`(一次性)、3 前端 | 仅启动 6 个核心业务（trade/menu/member/ops/finance/analytics）+ migrate；缺 supply/agent/org/brain/intel/civic/predict/pay/devforge/growth 等 | 演示精简包；数据库密码硬编码 `tunxiang_demo_2024` |
| **tenant-czyz** | 7 业务 | 同上演示包；额外 `seed-data`、`merchant-env` 锚点 | 缺所有非演示服务 | 端口同 dev (5432/6379/8000-8009/5173-5175)；**与 infra-demo 完全冲突** |
| **tenant-sgc** | 7 业务 | 同上 | 同上 | **端口偏移 +200**（5632/6381/8200-8209/5373-5375） |
| **tenant-zqx** | 7 业务 | 同上 | 同上 | **端口偏移 +100**（5532/6380/8100-8109/5273-5275） |
| **resource-override** | 14 | 仅 `deploy.resources` override | 不定义任何 build/image | override 模型典范；**包含 tx-civic** 但不含 tx-predict/tx-pay/tx-devforge/tx-expense |
| **toxiproxy** | 1 | 单独 toxiproxy | — | 测试设施；端口 8474 + 18001/18002/18008（Sprint A2）+ 9001/9002/9003（F2）；通过 `external: true` 加入 `docker_txos-dev` 网络 |

---

## 3. 服务级差异表

下表只列出**同名 service 在多文件间不一致**的关键属性。

### 3.1 gateway

| 文件 | 端口 | 内部端口 | env 关键差异 | depends_on |
|------|------|------|------|------|
| root-dev | 8000:8000 | 8000 | 无 PREDICT/PAY/DEVFORGE/FORGE；含 EXPENSE | postgres/redis healthy |
| root-prod | (内部) | 8000 | **TX_SUPPLY_URL=8004 / TX_FINANCE_URL=8005 / TX_ORG_URL=8006 / TX_ANALYTICS_URL=8007 / TX_OPS_URL=8009**（端口规划与 CLAUDE.md 完全冲突） | postgres/redis（service_healthy） |
| root-staging | (内部) | 8000 | 同 root-prod 端口规划（`stg-tx-*` 主机名） | stg-postgres/stg-redis |
| root-gray | (内部) | 8000 | 同 root-prod 端口规划（`gray-tx-*`） | gray-tx-trade |
| infra-base | `${GATEWAY_PORT:-8000}:8000` | 8000 | **完整 16 个 TX_*_URL（含 PREDICT/PAY/DEVFORGE）** | postgres/redis healthy |
| infra-dev | 8000:8000 | 8000 | 通过 env_file: .env 注入；TX_AUTH_ENABLED=false | postgres/redis healthy |
| infra-prod | (内部) | 8000 | env_file: .env；DATABASE_READ_URL 走 postgres-replica | postgres-primary/redis |
| infra-staging | (内部) | 8000 | env_file: .env；TX_AUTH_ENABLED=true | postgres/redis |
| infra-demo | 8000:8000 | 8000 | 硬编码密码 | postgres/redis |
| tenant-czyz | 8000:8000 | 8000 | TX_MERCHANT_CODE=czyz；TX_TENANT_ID=czyz-demo-tenant | seed-data 完成后 |
| tenant-zqx | 8100:8100 | **8100** | 端口完全偏移 +100 | seed-data |
| tenant-sgc | 8200:8200 | **8200** | 端口完全偏移 +200 | seed-data |

**结论：root-prod / root-staging / root-gray 的 gateway 路由表与项目宪法（CLAUDE.md §五"项目结构"）写的端口规划完全不符**：
- CLAUDE.md：tx-supply=8006, tx-finance=8007, tx-org=8012, tx-analytics=8009, tx-ops=8005
- root-prod：tx-supply=8004, tx-finance=8005, tx-org=8006, tx-analytics=8007, tx-ops=8009 ← 错位

### 3.2 tx-trade / tx-menu / tx-member / tx-ops / tx-supply / tx-finance / tx-org / tx-analytics

正确端口（CLAUDE.md + infra-base 一致）：
- tx-trade=8001, tx-menu=8002, tx-member=8003, tx-growth=8004, tx-ops=8005, tx-supply=8006, tx-finance=8007, tx-agent=8008, tx-analytics=8009, tx-brain=8010, tx-intel=8011, tx-org=8012, tx-predict=8013, tx-civic=8014, tx-expense=8015, tx-pay=8016, tx-devforge=8017

root-prod/root-staging/root-gray 错位的端口规划：
- tx-supply=8004, tx-finance=8005, tx-org=8006, tx-analytics=8007, tx-agent=8008, tx-ops=8009

**这是历史遗留**（v1 端口规划），但生产部署 CI 仍走 root-prod，意味着**如果这套 prod 真上线，会与 staging 写入相同端口的服务发生路由错乱**——tx-supply 实际是 supply 服务但被路由到 8004（项目宪法里 8004=tx-growth）。

### 3.3 tx-civic（8014）/ mcp-server（8014）冲突

- infra-base、resource-override：tx-civic 在 8014
- infra-dev、infra-staging：mcp-server 在 8014（**没有 tx-civic**）
- root-dev：tx-civic 在 8014
- 同一台机器若同时启动 infra-dev + infra-base 不可能（互斥），但 dev 工作流和 base 推荐路径都没有定义清楚，agent 容易搞混。

### 3.4 tunxiang-api（8013）/ tx-predict（8013）/ tx-forge（8013，未合并）冲突

- infra-base：tx-predict 在 8013
- infra-dev、infra-staging：tunxiang-api 在 8013（容器内端口）
- 未合并分支 `feat/p0-forge-compose`：拟将 tx-forge 加到 infra-base 也用 8013（容器内端口，不同容器，理论 DNS 不冲突；但**主机端口未映射**所以同一 compose 启动两者时 Docker 不会拒绝）

### 3.5 sync-engine

只在 root-dev 中定义，profile=`edge`，需 `--profile edge` 才启动。其它文件均无。

### 3.6 celery-worker / celery-beat / pg-backup

只在 root-prod 中定义。infra-prod 没有。这是**root-prod 唯一不可被 infra-prod 替代的能力**——但 infra-prod 又有 postgres-replica 主从占位是 root-prod 没有的。两者职责正交但都自称"prod compose"。

---

## 4. 端口冲突清单全集

### 4.1 容器内端口冲突（同 compose 文件内）
**无**——经核查 14 文件每一份内部都是分离的容器，无单 compose 内端口冲突。

### 4.2 跨 compose 文件端口冲突（同一台机同时启动）

| host port | 占用方 A | 占用方 B | 冲突级别 |
|-----------|----------|----------|----------|
| 5432 | root-dev / infra-dev / infra-demo / tenant-czyz | — | 同时启动两份必然冲突 |
| 6379 | root-dev / infra-dev / infra-demo / tenant-czyz | — | 同 |
| 8000 | root-dev / infra-dev / infra-demo / tenant-czyz | — | 同 |
| 8001-8014 | root-dev / infra-dev / infra-demo / tenant-czyz（部分子集） | — | 同 |
| 5173/5174/5175 | root 各份没暴露；infra-dev / infra-demo / tenant-czyz | — | 同 |

**租户间已避免冲突**：
- czyz：5432 / 6379 / 8000-8009 / 5173-5175（与 dev/demo 冲突，单机不可共存）
- zqx：**5532 / 6380 / 8100-8109 / 5273-5275**（+100，已独立）
- sgc：**5632 / 6381 / 8200-8209 / 5373-5375**（+200，已独立）

→ czyz 是**没有偏移的**，所以与开发环境互斥。zqx/sgc 偏移设计正确，可三租户并行（前提是不再启 dev/demo）。

### 4.3 容器内端口"逻辑冲突"（已知线索）

| 端口 | 服务 A（in 文件） | 服务 B（in 文件） | 影响 |
|------|------|------|------|
| **8013** | tx-predict (infra-base) | tunxiang-api (infra-dev / infra-staging) | 客户端 `TX_*_URL=:8013` 在 dev 与 prod 指向不同业务 |
| **8013** | tx-predict (infra-base) | tx-forge（未合并 feat/p0-forge-compose 拟加） | 容器隔离不冲突，但**两个容器都 listen 8013**，gateway 必须用容器名（tx-forge 或 tx-predict）区分；若任一被改成 host bind，立即冲突 |
| **8014** | tx-civic (infra-base / root-dev / resource-override) | mcp-server (infra-dev / infra-staging) | 与 8013 同结构 |
| **8013** | tunxiang-api (infra-staging) | tx-pay 旧端口（已改 8016 在 feat/p0-pay-port-unify 中） | 已被 P0-1 修复 |

**新增发现的端口冲突（除已知 forge↔predict 8013 之外）**：
1. **tx-civic ↔ mcp-server 都在 8014**（dev/staging vs base/root-dev/resource-override）
2. **tunxiang-api ↔ tx-predict 都在 8013**（dev/staging vs base）
3. **root-prod 的 gateway 路由表整体错位**（tx-supply→8004 等），与 CLAUDE.md 端口规划相悖；这不是端口冲突而是"业务路由错位"，但严重性更高。

---

## 5. customer-tenant 三个文件深度分析

### 5.1 端口区间表

| 项 | czyz | zqx | sgc |
|----|------|------|------|
| postgres host | **5432** ⚠️ | 5532 | 5632 |
| postgres container | 5432 | 5432 | 5432 |
| redis host | **6379** ⚠️ | 6380 | 6381 |
| redis container | 6379 | 6379 | 6379 |
| gateway | **8000** ⚠️ | 8100 | 8200 |
| tx-trade | 8001 ⚠️ | 8101 | 8201 |
| tx-menu | 8002 ⚠️ | 8102 | 8202 |
| tx-member | 8003 ⚠️ | 8103 | 8203 |
| tx-agent | 8008 ⚠️ | 8108 | 8208 |
| tx-analytics | 8009 ⚠️ | 8109 | 8209 |
| web-admin | 5173 ⚠️ | 5273 | 5373 |
| web-pos | 5174 ⚠️ | 5274 | 5374 |
| web-kds | 5175 ⚠️ | 5275 | 5375 |
| 偏移量 | **0** | +100 | +200 |

⚠️ czyz 完全没有端口偏移——与 dev/demo 互斥，不能并发演示三租户。这是**待修隐患**（不在本审计范围动手）。

### 5.2 租户独占资源清单

每个租户独占：

**czyz（尝在一起）**：
- 数据库：`tunxiang_czyz` / 用户 `tunxiang` / 密码 `tunxiang_czyz_2024`
- 网络：`txos-czyz`（独立 bridge）
- volume：`czyz_pg_data`、`czyz_web_admin_nm`、`czyz_web_pos_nm`、`czyz_web_kds_nm`
- env：`TX_MERCHANT_CODE=czyz`、`TX_TENANT_ID=czyz-demo-tenant`、`TX_MERCHANT_NAME=尝在一起`
- seed 脚本：`scripts/seed_czyz.py`
- KPI 注释：翻台率 / 出餐时间 / 座位利用率
- 业务 7 个：gateway/tx-trade/tx-menu/tx-member/tx-analytics/tx-agent + 3 前端

**zqx（最黔线）**：
- 数据库：`tunxiang_zqx` / 密码 `tunxiang_zqx_2024`
- 网络：`txos-zqx`
- volume：`zqx_pg_data` 等 4 个
- env：`zqx-demo-tenant`
- seed：`scripts/seed_zqx.py`
- KPI：客单价 / 会员复购 / 渠道组合
- 业务同 czyz

**sgc（尚宫厨）**：
- 数据库：`tunxiang_sgc` / 密码 `tunxiang_sgc_2024`
- 网络：`txos-sgc`
- volume：`sgc_pg_data` 等 4 个
- env：`sgc-demo-tenant`
- seed：`scripts/seed_sgc.py`（含宴会预订数据）
- KPI：宴会客单价 / 订金收款率 / 人力成本占比
- 业务同 czyz

**结构高度对称**：3 文件除了端口偏移、密码、网络名、tenant id、KPI 注释之外，**95%+ 内容重复**。这是 base+override 收敛的天然候选。

---

## 6. 未合并分支（P0-1 / P0-2）影响分析

### P0-1 = `feat/p0-pay-port-unify`（4 commits）
- 4a5c490e: tx-pay 服务自身 8013→8016（src/main.py + Dockerfile）
- e113eec3: 调用方 default URL 8013→8016
- 75e81758: **在根 docker-compose.yml 中补 tx-pay service 块（端口 8016）**
- 969e2788: tx-pay /health 冒烟测试

主要影响文件：root-dev (`docker-compose.yml`)。infra-base 已经有 tx-pay，所以这次只是把 dev 也补上。**合并风险低**——只动 root-dev，不影响 infra-base。

### P0-2 = `feat/p0-forge-compose`（1 commit 89ff193a）
- 在 `infra/docker/docker-compose.yml` 加 tx-forge service（容器内 8013，与 tx-predict 同号）
- 在 gateway env 加 TX_FORGE_URL
- 同时改 `services/gateway/src/proxy.py` 加 forge 域路由

主要影响：infra-base（不动 root）。**合并风险点**：tx-forge:8013 和 tx-predict:8013 都 listen 8013。Docker 内网通过容器名隔离，gateway 用 `http://tx-forge:8013` vs `http://tx-predict:8013`。**如果未来需要把任一服务的 8013 暴露到主机，必须改容器内端口或主机端口。**

### 一致性结论
- P0-1 把改动放到了 root-dev → 默认开发者用根 compose 时能跑 tx-pay
- P0-2 把改动放到了 infra-base → 只有用 infra/docker/ compose 才能跑 tx-forge
- **两组 P0 修复落在了不同的"权威源"上**——这本身就是本次审计要解决的问题：哪个是真的权威，需要决断后两个分支才能并行合并不冲突。

**建议合并顺序（如审计后选定权威源 = infra-base）**：
1. 先合 P0-2（已落在 infra-base，无冲突）
2. P0-1 需"补回"——在 root-dev 加 tx-pay 是对的（dev 时单独用根 compose），但 infra-base 也已经有。不冲突，可直接合。
3. 第二阶段执行收敛后，root-dev 大概率会被废弃或重构成 infra-base override，届时 P0-1 的 root 改动会被覆盖，但语义被保留。

**建议合并顺序（如审计后选定权威源 = root）**：
- P0-2 必须重做，把 tx-forge 加到 root-dev/root-prod 而不是 infra-base。**P0-2 当前形态会被废弃。**
- 这是为什么"先收敛后合 P0"是更稳的路径。

---

## 7. CI/CD/脚本引用矩阵

### scripts/
| 脚本 | 引用 |
|------|------|
| `scripts/deploy.sh` | `docker-compose.staging.yml`、`docker-compose.prod.yml`、`docker-compose.gray.yml`（**全部根目录**） |
| `scripts/demo_deploy.sh` | `infra/docker/docker-compose.demo.yml` |
| `scripts/rollback-service.sh` | `infra/docker/docker-compose.yml`（infra-base） |
| `scripts/auto-sync.sh` | `docker-compose.prod.yml`（根） |
| `scripts/env-manager.sh` | dev/test/uat/demo→根 `docker-compose.yml`；prod→根 prod；pilot→根 staging |
| `scripts/week8_gate_check.sh` | grep `infra/docker/docker-compose*.yml`（基线扫描） |
| `scripts/gate1-manual-ops.sh` | echo 提示走根 prod |

### .github/workflows/
| 工作流 | 引用 |
|--------|------|
| `deploy.yml` | 根 `docker-compose.staging.yml` 和 `docker-compose.prod.yml` |
| `pr-check.yml` | grep `docker-compose*` 触发条件（路径过滤） |
| `toxiproxy-smoke.yml` | `infra/docker/docker-compose.toxiproxy.yml` |
| `offline-e2e.yml` | path filter 含 `infra/docker/docker-compose.toxiproxy.yml` |
| 其它 9 个 | 无 docker-compose 引用 |

**矛盾点**：CI/CD（deploy.yml + auto-sync.sh）走根 prod 文件，但根 prod 缺 6 个服务且端口规划错位。这意味着如果今天真的 `git push main` → 自动部署，生产环境的 gateway 会路由到错误的服务端口，且 tx-predict / tx-pay / tx-devforge / tx-civic / tx-expense / tx-growth 不会启动。这是**P0 级风险**。

---

## 8. 总结

| 项 | 现状 | 严重性 |
|----|------|--------|
| 后端权威源 | **infra/docker/docker-compose.yml**（事实上） | — |
| CI/CD 默认走 | **根 docker-compose.\*.yml**（错位） | P0 风险 |
| root-prod 端口规划 | 与 CLAUDE.md / infra-base 完全错位（错 5 个服务） | P0 风险 |
| root-prod 缺失服务 | tx-predict/tx-pay/tx-devforge/tx-civic/tx-expense/tx-growth/tx-brain/tx-intel | P0 |
| 容器端口逻辑冲突 | tx-predict↔tunxiang-api 都 8013；tx-civic↔mcp-server 都 8014 | P1 |
| czyz 端口未偏移 | 与 dev/demo 互斥 | P2（设计缺陷，本次只读） |
| 重复内容 | 14 文件平均 ~70% 内容雷同（service 定义重复粘贴） | 维护负担 |
| YAML 抽象 | 仅 infra-base / root-prod / resource-override 用 anchor，其它原始重复 | 维护负担 |

下一步建议见 `docs/infra/compose-consolidation-proposal-2026-05.md`。
