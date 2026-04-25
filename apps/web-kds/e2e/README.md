# web-kds E2E（Sprint C / C4 — 4 小时零卡顿）

后厨 KDS 长跑 E2E。它是周 8 验收"断网恢复 4 小时无数据丢失"门槛的 nightly 三连绿之一（CLAUDE.md §22）。

---

## 用例（Tier 1，餐厅场景命名）

| 用例 | 验证 |
|------|------|
| `test_kitchen_4h_continuous_polling_no_freeze` | 后厨连续 4 小时轮询，全程无 `console.error`、长任务总占比 < 5% |
| `test_kitchen_polling_recovery_after_60s_outage` | 后厨网络中断 60 秒后恢复，DOM 仍可访问、错误数有上限 |
| `test_kitchen_memory_does_not_grow_past_50mb` | JS 堆内存增长 ≤ 50MB（无泄漏） |

---

## 两种模式

| 模式 | `KDS_E2E_DURATION_MS` | 何时跑 |
|------|----------------------|--------|
| fast | `60000`（60s，默认） | PR 门禁 / 本地快速验证 |
| nightly | `14400000`（4h） | CI 凌晨 nightly |

---

## 本地复现

```bash
# 安装 Playwright Chromium（首次）
pnpm --filter web-kds exec playwright install chromium

# fast 模式（60s，~3 分钟跑完 3 个用例）
pnpm --filter web-kds run e2e:fast

# nightly 模式（4h，本地慎用）
pnpm --filter web-kds run e2e:nightly

# 任意自定义时长（毫秒）
KDS_E2E_DURATION_MS=15000 pnpm --filter web-kds run e2e

# HTML 报告
pnpm --filter web-kds run e2e:report
```

---

## CI（GitHub Actions）

工作流：[`.github/workflows/nightly-kds-e2e.yml`](../../../.github/workflows/nightly-kds-e2e.yml)

- 触发：`schedule`（每日 UTC 18:00 = 北京时间 02:00）+ `workflow_dispatch`
- timeout-minutes: 270（4.5h）
- artifacts：
  - `kds-e2e-report-${run_id}`：Playwright HTML 报告（保留 14 天）
  - `kds-e2e-trace-${run_id}`：失败时的 trace + 截图

在 PR 检查中查看：Actions tab → Nightly KDS 4h Zero-Jank E2E → Artifacts。

---

## 测试页来源（重要）

`fixtures/mockDeltaServer.ts` 同时充当：
1. `/api/v1/kds/orders/delta` 与 `/api/v1/kds/device/heartbeat` 的 mock 后端
2. 一个内置的 KDS 风格静态测试页（每 3s fetch delta、增量渲染、LRU 淘汰）

### 为什么不直接用真 vite dev server？

当前 worktree 里 `pnpm-workspace.yaml` 不包含 `packages/*`，导致 `apps/web-kds/src/main.tsx` 里
`import '../../packages/tx-tokens/src/tokens.css'` 在 vite import-analysis 阶段失败（500）。
该问题与 C4 任务（4h 零卡顿验证）正交，已作为独立 task 跟踪。

一旦上游修好，把 `KDS_BASE_URL=http://localhost:5173` 设进环境，并在 `playwright.config.ts`
里恢复 `webServer` 块，同一组 spec 就能直接跑真 KDS UI——用例代码无需改动。

### 内置测试页 vs 真 UI 的代表性

内置测试页运行在真 Chromium、真 fetch、真 DOM、真 Map/setInterval/PerformanceObserver。
对 4h 零卡顿验证而言（焦点是浏览器端轮询的内存稳定性 + 帧率），它充分代表风险。
真 UI 的 React diff 成本会让数字略高但同阶——上限阈值（50MB / 5%）已留足余量。

---

## 已知限制

- `performance.memory` 仅 Chromium 暴露；其他浏览器测试会 skip。
- 4h nightly 单次失败重跑成本高，因此 `retries: 0`。失败后查 Playwright HTML 报告与 trace。
- mock server 端口随机（`listen(0)`），多个 spec 并发不冲突。
