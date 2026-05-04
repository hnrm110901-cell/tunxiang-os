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
