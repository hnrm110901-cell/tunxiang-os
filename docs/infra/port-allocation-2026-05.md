# 屯象OS 端口分配权威表 — 2026-05-04

> P0.5 阶段 E + 阶段 F。`infra/compose/base.yml` 是端口分配的唯一权威源。
> 与 CLAUDE.md §五 项目结构（宪法）交叉验证。

## 后端服务端口（容器内 = 宿主机端口，单租户场景）

| 服务 | 端口 | 来源 | 备注 |
|------|------|------|------|
| gateway | 8000 | 宪法 §五 | API Gateway + 域路由 |
| tx-trade | 8001 | 宪法 §五 | 交易履约 |
| tx-menu | 8002 | 宪法 §五 | 菜品菜单 |
| tx-member | 8003 | 宪法 §五 | 会员 CDP |
| tx-growth | 8004 | 宪法 §五 | 增长营销 |
| tx-ops | 8005 | 宪法 §五 | 运营流程 |
| tx-supply | 8006 | 宪法 §五 | 供应链 |
| tx-finance | 8007 | 宪法 §五 | 财务结算 |
| tx-agent | 8008 | 宪法 §五 | Agent OS |
| tx-analytics | 8009 | 宪法 §五 | 经营分析 |
| tx-brain | 8010 | 宪法 §五 | AI 决策 |
| tx-intel | 8011 | 宪法 §五 | 商业智能 |
| tx-org | 8012 | 宪法 §五 | 组织人事 |
| tunxiang-api | 8013 | 沿用 | 遗留 API 兼容层（宪法未规定） |
| tx-civic | 8014 | 宪法 §五 | 城市监管平台 |
| tx-expense | 8015 | 沿用（root-dev） | 费控（宪法未规定） |
| tx-pay | 8016 | P0-1 决议 | 支付中枢 |
| tx-devforge | 8017 | 沿用 | DevForge 内部研发平台 |
| **mcp-server** | **8018** | **P0.5 修复** | **原 8014 与 tx-civic 宪法冲突 → 改 8018** |
| **tx-predict** | **8019** | **P0.5 修复** | **原 8013 与 tunxiang-api 冲突 → 改 8019** |

**端口冲突修复对照**：

| 服务 | 原端口（冲突） | 现端口 | 冲突原因 |
|------|---------------|--------|----------|
| tx-predict | 8013 | **8019** | tunxiang-api 占 8013（infra-dev/staging 既定） |
| mcp-server | 8014 | **8018** | tx-civic 是 CLAUDE.md §五 宪法规定的 8014 |

## 前端 Vite Dev Server 端口（dev/demo 默认）

| 应用 | 端口 |
|------|------|
| web-admin | 5173 |
| web-pos | 5174 |
| web-kds | 5175 |

## 基础设施端口

| 服务 | 端口 |
|------|------|
| postgres | 5432 |
| redis | 6379 |
| nginx (prod) | 80 / 443 |
| nginx (staging) | 80 / 443 |
| toxiproxy 管理 API | 8474 |
| toxiproxy 服务级代理 | 18001 / 18002 / 18008 |
| toxiproxy 基础设施代理 | 9001 / 9002 / 9003 |

## 租户独立部署模式（生产场景，无偏移）

> P0.5 阶段 F 修订：尝在一起 / 最黔线 / 尚宫厨 是 **三家独立的商户**，
> **各自独立部署** 到自己的 VM/服务器。`infra/compose/tenants/<x>.yml`
> 已剥离所有 host 端口映射，纯粹承载"商户身份"（DB 名 / tenant_id /
> 品牌 env / seed 脚本 / 独占 volume）。

生产部署用法（每家在自己的机器上跑，端口都走默认）：

```bash
# 在 czyz 自己的 VM
docker compose -f infra/compose/base.yml \
               -f infra/compose/envs/prod.yml \
               -f infra/compose/tenants/czyz.yml up -d
# 容器内端口仍然 8000/5432/6379…，只有 nginx 80/443 暴露给外部，
# 业务接口访问统一走 nginx 反代
```

**生产场景没有任何端口偏移**。docker-network 内部直连，外部访问由各 VM 的 nginx/反代自配。

## 同机联调端口偏移（dev-only 少数场景）

> 仅服务 **开发者本地同时拉起多家做联调** 这一场景。
> 通过 `infra/compose/special/multi-host-dev.yml` + 三份
> `.env.<tenant>.dev.example` 实现。**生产部署不要叠加这层**。

用法：

```bash
# 拉 czyz：默认偏移 0（占用 8000/5432/6379 默认槽位）
set -a && source infra/compose/special/.env.czyz.dev.example && set +a
docker compose -f infra/compose/base.yml \
               -f infra/compose/envs/dev.yml \
               -f infra/compose/tenants/czyz.yml \
               -f infra/compose/special/multi-host-dev.yml up -d

# 同机再起 zqx：偏移 +100
set -a && source infra/compose/special/.env.zqx.dev.example && set +a
docker compose -f infra/compose/base.yml \
               -f infra/compose/envs/dev.yml \
               -f infra/compose/tenants/zqx.yml \
               -f infra/compose/special/multi-host-dev.yml up -d

# 同机再起 sgc：偏移 +200
set -a && source infra/compose/special/.env.sgc.dev.example && set +a
docker compose -f infra/compose/base.yml \
               -f infra/compose/envs/dev.yml \
               -f infra/compose/tenants/sgc.yml \
               -f infra/compose/special/multi-host-dev.yml up -d
```

| 租户 | 偏移示例 | postgres | redis | gateway | tx-trade…tx-predict | web-admin | web-pos | web-kds |
|------|----------|----------|-------|---------|--------------------|-----------|---------|---------|
| czyz | 0 | 5432 | 6379 | 8000 | 8001-8019 | 5173 | 5174 | 5175 |
| zqx | +100 | 5532 | 6380 | 8100 | 8101-8119 | 5273 | 5274 | 5275 |
| sgc | +200 | 5632 | 6381 | 8200 | 8201-8219 | 5373 | 5374 | 5375 |

注：偏移由 `.env.<tenant>.dev.example` 中各服务的 `*_HOST_PORT` 全量变量决定。
docker compose 不直接支持 `${BASE}+${OFFSET}` 算术，所以本设计走"全量变量名 + 默认值"
方案，同时保留 `TENANT_PORT_OFFSET` 作为信息字段方便人读。

## 与 CLAUDE.md §五 宪法 交叉验证

宪法表（截取）：
```
gateway:8000, tx-trade:8001, tx-menu:8002, tx-member:8003, tx-growth:8004,
tx-ops:8005, tx-supply:8006, tx-finance:8007, tx-agent:8008, tx-analytics:8009,
tx-brain:8010, tx-intel:8011, tx-org:8012, tx-civic:8014, mcp-server, tunxiang-api
```

14 个有具体端口的服务全部对齐。
宪法没有规定的 mcp-server / tunxiang-api，本表给出明确分配（8018 / 8013）。

## 引用源代码
- `infra/compose/base.yml` — 16 服务定义 + 端口决策注释
- `infra/compose/special/multi-host-dev.yml` — 同机联调端口暴露层
- `infra/compose/special/.env.<tenant>.dev.example` — 三份偏移示例
- `services/gateway/` — 通过环境变量读取上游 URL（见 base.yml gateway 块的
  TX_*_URL 注入）

## 端口空间剩余
- 8020-8099 全部空闲（如未来加新服务，从 8020 开始顺序分配）
- 9000-9020 toxiproxy 预留
- 18000-18099 toxiproxy 服务级代理预留

## Helm Chart 完整性矩阵（P0.6 完成 — 2026-05-04）

> 14 个原有 + 7 个新增 = 21 个 chart，覆盖 base.yml 全部 16 个业务服务（含
> 基础设施 postgres/redis 由 PG/Redis Operator 或外置实例承接，不入 chart）
> 以及 web-admin（前端）和 tx-forge（未合并 P0-2 分支，预先建好待复审）。
>
> P0.6（2026-05-04）补齐 5 个项目级工件，全部 21 chart 同质化：
> NOTES.txt / serviceaccount.yaml / poddisruptionbudget.yaml /
> networkpolicy.yaml / configmap.yaml。
>
> 注：本表 Tier 列对齐 CLAUDE.md 第十七节宪法（资金链路 + 三条硬约束 = T1）。
> Tier 1 = 资金/收银核心 + 三条硬约束校验 — 零容忍。
> Tier 2 = 运营核心。
> Tier 3 = 辅助/低频。

| Chart | base.yml 端口 | Tier | NOTES | SA | PDB | NetPol | CM | 备注 |
|---|---|---|---|---|---|---|---|---|
| api-gateway | 8000 | T1 | ✓ | ✓ | ✓ minA=1 | ✓ off | ✓ off | 唯一带 ingress |
| tx-trade | 8001 | T1 | ✓ | ✓ | ✓ minA=1 | ✓ off | ✓ off | 交易履约 |
| tx-menu | 8002 | T2 | ✓ | ✓ | ✓ maxU=1 | ✓ off | ✓ off | 菜品菜单 |
| tx-member | 8003 | T1 | ✓ | ✓ | ✓ minA=1 | ✓ off | ✓ off | 会员 CDP（含储值，资金链路）|
| tx-growth | 8004 | T2 | ✓ | ✓ | ✓ maxU=1 | ✓ off | ✓ off | 增长营销 |
| tx-ops | 8005 | T3 | ✓ | ✓ | ✓ off | ✓ off | ✓ off | 日清日结 |
| tx-supply | 8006 | T1 | ✓ | ✓ | ✓ minA=1 | ✓ off | ✓ off | 供应链（含食安合规，三条硬约束）|
| tx-finance | 8007 | T1 | ✓ | ✓ | ✓ minA=1 | ✓ off | ✓ off | 财务结算（发票/押金，资金链路）|
| tx-agent | 8008 | T1 | ✓ | ✓ | ✓ minA=1 | ✓ off | ✓ off | Agent OS（三条硬约束校验）|
| tx-analytics | 8009 | T3 | ✓ | ✓ | ✓ off | ✓ off | ✓ off | 经营分析 |
| tx-brain | 8010 | T3 | ✓ | ✓ | ✓ off | ✓ off | ✓ off | AI 决策 |
| tx-intel | 8011 | T3 | ✓ | ✓ | ✓ off | ✓ off | ✓ off | 商业智能 |
| tx-org | 8012 | T2 | ✓ | ✓ | ✓ maxU=1 | ✓ off | ✓ off | 组织人事 |
| tunxiang-api | 8013 | — | — | — | — | — | — | **缺 chart**（遗留兼容层）|
| tx-civic | 8014 | T3 | ✓ | ✓ | ✓ off | ✓ off | ✓ off | 宪法端口（Phase 4.5）|
| tx-expense | 8015 | T2 | ✓ | ✓ | ✓ maxU=1 | ✓ off | ✓ off | 费控（Phase 4.5）|
| tx-pay | 8016 | T1 | ✓ | ✓ | ✓ minA=1 | ✓ off | ✓ off | 支付中枢（Phase 4.5）|
| tx-devforge | 8017 | T3 | ✓ | ✓ | ✓ off | ✓ off | ✓ off | 内部研发（Phase 4.5）|
| mcp-server | 8018 | T3 | ✓ | ✓ | ✓ off | ✓ off | ✓ off | Claude Code（Phase 4.5）|
| tx-predict | 8019 | T2 | ✓ | ✓ | ✓ maxU=1 | ✓ off | ✓ off | 预测引擎（Phase 4.5）|
| tx-forge | 8013 (TODO) | T3 | ✓ | ✓ | ✓ off | ✓ off | ✓ off | ⚠️ 端口待 P0-2 复审 |
| web-admin | 5173 | T3 | ✓ | ✓ | ✓ off | ✓ off | ✓ off* | *enabled=false，复用既有 ConfigMap |

**21 个 chart × 5 工件 = 105 处对账，全绿**。

**Tier 化 PDB 默认值**：
- Tier 1（7 chart）：`pdb.enabled=true`, `minAvailable=1`
- Tier 2（5 chart）：`pdb.enabled=true`, `maxUnavailable=1`
- Tier 3（9 chart）：`pdb.enabled=false`（保留模板，按需启用）

**NetworkPolicy / ConfigMap 全部默认 disabled**：
错误的 NetworkPolicy 会断服务间通信，启用前必须画清楚服务依赖图
（见 docs/infra/service-dependency-graph.md，待补）；ConfigMap 默认禁用
保持 deployment.yaml 不变（向后兼容）。

**仍待补**：
- `tunxiang-api`（8013 遗留兼容层）— P0.5 范围内不单独打 chart，由 tx-forge
  P0-2 合并时一并决议（与 tunxiang-api 端口冲突的处理同时含 8013 的归属）。
- `tx-forge` 端口 — values.yaml 顶部 TODO 注释已标，P0-2 合并 base.yml 时复审
  是否改 8020+ 以及是否与 tunxiang-api 二选一。
- `docs/infra/service-dependency-graph.md` — NetworkPolicy 启用的前置依赖图
  尚未建设，P0.7（或单独安全 PR）补齐后逐 chart 按依赖关系开启 NetworkPolicy。
