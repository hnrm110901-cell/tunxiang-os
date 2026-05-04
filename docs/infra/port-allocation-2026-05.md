# 屯象OS 端口分配权威表 — 2026-05-04

> P0.5 阶段 E。`infra/compose/base.yml` 是端口分配的唯一权威源。
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

## 租户端口偏移（base + demo + tenants/*.yml）

| 租户 | 偏移 | postgres | redis | gateway | tx-trade…tx-analytics | web-admin | web-pos | web-kds |
|------|------|----------|-------|---------|----------------------|-----------|---------|---------|
| czyz | **0** ⚠️ | 5432 | 6379 | 8000 | 8001-8009 | 5173 | 5174 | 5175 |
| zqx | +100 | 5532 | 6380 | 8100 | 8101-8109 | 5273 | 5274 | 5275 |
| sgc | +200 | 5632 | 6381 | 8200 | 8201-8209 | 5373 | 5374 | 5375 |

⚠️ **czyz 偏移=0 与 dev/demo 互斥** — 待创始人决策（见
   `infra/compose/tenants/czyz.yml:11` TODO 注释）。
   ENV 变量化已就绪：可用 `CZYZ_HOST_GATEWAY_PORT=8050 docker compose ... up`
   临时覆盖。

注：tenants/*.yml 中**容器内端口不变**（仍然是 base 的 8000/8001/...），只
变更主机端口映射。这与原 zqx/sgc 文件"内外端口都偏移"的实现不同，但
docker compose 多实例的标准做法。脚本/文档若依赖原内部端口，需注意。

## 与 CLAUDE.md §五 宪法 交叉验证

宪法表（截取）：
```
gateway:8000, tx-trade:8001, tx-menu:8002, tx-member:8003, tx-growth:8004,
tx-ops:8005, tx-supply:8006, tx-finance:8007, tx-agent:8008, tx-analytics:8009,
tx-brain:8010, tx-intel:8011, tx-org:8012, tx-civic:8014, mcp-server, tunxiang-api
```

✅ 14 个有具体端口的服务全部对齐。
✅ 宪法没有规定的 mcp-server / tunxiang-api，本表给出明确分配（8018 / 8013）。

## 引用源代码
- `infra/compose/base.yml` — 16 服务定义 + 端口决策注释
- `services/gateway/` — 通过环境变量读取上游 URL（见 base.yml gateway 块的
  TX_*_URL 注入）

## 端口空间剩余
- 8020-8099 全部空闲（如未来加新服务，从 8020 开始顺序分配）
- 9000-9020 toxiproxy 预留
- 18000-18099 toxiproxy 服务级代理预留
