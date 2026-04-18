# E2E Tests

基于 Playwright 的端到端测试套件，覆盖 web-admin / web-pos 关键用户路径。

---

## 目录结构

```
e2e/
├── playwright.config.ts        # 3 个 project: web-admin / web-pos / offline
├── package.json                # test:pos / test:offline / test:offline:marathon
├── scripts/
│   └── toxiproxy-inject.sh     # toxiproxy 故障注入脚本（nightly 马拉松用）
└── tests/
    ├── fixtures.ts             # 共享登录注入
    ├── auth.spec.ts            # 登录/注销
    ├── cashier.spec.ts         # 在线收银流程
    ├── dish-management.spec.ts
    ├── member.spec.ts
    ├── navigation.spec.ts
    ├── offline-cashier.spec.ts # Sprint A2 P0-2: 断网收银 4 场景
    └── offline-helpers.ts      # 断网场景共享工具
```

---

## 快速开始

```bash
# 安装浏览器内核（首次）
pnpm --dir e2e exec playwright install chromium

# 跑在线收银（需要 web-pos dev server 在 :5174）
pnpm --dir apps/web-pos dev &
pnpm --dir e2e run test:pos

# 跑断网收银（PR 门禁，默认 OFFLINE_HOURS=0.01 ≈ 36s）
pnpm --dir e2e run test:offline
```

---

## Offline E2E（Sprint A2 / PR E）

### 覆盖场景

对应 [CLAUDE.md §XX Tier 1 测试标准](../CLAUDE.md)：

| # | 场景 | 验证点 |
|---|------|--------|
| 1 | 断网结账 | `navigator.onLine=false` → 点微信支付 → 显示"已加入离线队列" Toast，不弹"支付失败"，IndexedDB 新增 1 条 |
| 2 | 幂等键去重 | 5 分钟内同桌同方式重付 → 队列长度不增长（`settle:${orderId}` 缓存命中） |
| 3 | 网络恢复 | `setOffline(false)` → 队列自动 flush → 服务端最多收到 1 次扣款 |
| 4 | 服务端降级 | 浏览器在线但后端返回 503 → 前端自动入队（`txFetchOffline` fallback） |

### 本地运行

```bash
# 前提：apps/web-pos 已在 5174 端口运行
pnpm --dir e2e run test:offline

# 查看报告
pnpm --dir e2e run report
```

### Nightly 4h 马拉松

```bash
# 本地手动跑（占用 4h+）
pnpm --dir e2e run test:offline:marathon
# 或：
OFFLINE_HOURS=4 pnpm --dir e2e run test:offline
```

GitHub Actions 在 UTC 18:00（北京时间 02:00）自动运行，见 `.github/workflows/offline-e2e.yml`。

### Toxiproxy 故障注入（长时场景）

当需要更真实的"网络抖动 + 高延迟 + 服务端部分可用"场景时，启用 toxiproxy：

```bash
# 启动 toxiproxy（监听 8474 管理口，代理 18001/18002/18008）
docker compose -f infra/docker/docker-compose.toxiproxy.yml up -d

# 让 tx-trade 代理完全下线（模拟断网）
./e2e/scripts/toxiproxy-inject.sh down tx-trade

# 恢复
./e2e/scripts/toxiproxy-inject.sh up tx-trade

# 注入 2s 延迟
./e2e/scripts/toxiproxy-inject.sh latency tx-trade 2000

# 清除所有 toxic
./e2e/scripts/toxiproxy-inject.sh reset tx-trade
```

浏览器端 `navigator.onLine` 由 Playwright 的 `context.setOffline(true)` 控制，与 toxiproxy 正交组合使用。

---

## CI 策略

| 触发 | 运行场景 | 超时 |
|------|---------|------|
| `pull_request` | 断网 4 场景（OFFLINE_HOURS=0.01） | 20min |
| `schedule`（UTC 18:00） | 4h 马拉松（OFFLINE_HOURS=4） | 300min |
| `workflow_dispatch` | 用户指定 OFFLINE_HOURS | 300min |

PR 失败会阻止合并（Week 8 DEMO 硬门禁之一）。

---

## 编写新离线场景

参考 `offline-cashier.spec.ts`：

1. `createMockTradeState()` 创建服务端状态
2. `installTradeMocks(page, state)` 装载所有 API mock
3. `page.context().setOffline(true/false)` 切换网络
4. `readOfflineQueueLength(page)` 读 IndexedDB 验证队列

**幂等测试要点**：重复调用同一 `idempotencyKey`（如 `settle:${orderId}`）5 分钟内只入队 1 次。超时或业务拒绝**不**应 throw，而是返回 `{ok:false,error}`，让 UI 层降级到 Toast 提示。

---

## 相关文档

- [docs/sprint-plan-2026Q2-unified.md](../docs/sprint-plan-2026Q2-unified.md) — Sprint A2 P0-2
- [CLAUDE.md §XX Tier 1 测试标准](../CLAUDE.md#二十tier-1-测试标准)
- [CLAUDE.md §XXII Week 8 DEMO 验收门槛](../CLAUDE.md#二十二week-8-demo-验收门槛)
