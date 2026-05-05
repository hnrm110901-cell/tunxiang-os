# Week 8 徐记海鲜 DEMO Go/No-Go 自审报告

> 自审日期：2026-05-04（距 W8 截止 2026-06-09 还剩约 5 周）
> 依据：`docs/sprint-plan-2026Q2-unified.md` §3 + `CLAUDE.md` §22
> 状态图例：✅ 就绪 / 🟡 部分就绪（缺口可控） / 🔴 阻塞 / ⚪ 待动

---

## 总览

| # | 验收项 | 状态 | 关键缺口 |
|---|---|---|---|
| 1 | Tier 1 测试 100% 通过 | 🟡 | 17% 已跑通（115/x），其余 38 文件未本地基线 |
| 2 | k6 P99 < 200ms | 🟡 | k6 脚本就位 + nightly cron 已配，缺 baseline 报告 |
| 3 | 支付成功率 > 99.9% | 🟡 | payment_saga 9 测试全绿；缺生产/灰度真实统计 |
| 4 | 断网 4h E2E（连续 3 日） | 🟡 | offline-e2e nightly cron 已配，缺连续 3 日绿运行证据 |
| 5 | 收银员零培训（3 位签字） | 🟡 | docs/demo/cashier-signoff.md 已就位；缺真实 3 签 |
| 6 | 三商户 scorecard ≥ 85 | 🔴 | 三商户 playbook 完备；缺最新 scorecard（4 月评分 czyz 81.9 / zqx 79.0 / sgc 72.5） |
| 7 | RLS/凭证/端口/CORS/secrets 零告警 | 🟡 | RLS 测试 5/5 绿；缺 H3 安全终查总报告 |
| 8 | scripts/demo-reset.sh 回退验证 | ✅ | 脚本就位（13.5KB），需跑一次留证据 |
| 9 | A/B 实验 running 未熔断 | 🟡 | service + 熔断逻辑就位；缺真实 running 实验 |
| 10 | 三套演示话术打印就位 | ✅ | docs/merchant-playbooks/{czyz,zqx,sgc}.md 三份齐全 |

**汇总**：2 ✅ / 7 🟡 / 1 🔴。Tier 3 验收（项 8/10）已完，主要瓶颈是 6 项（三商户达标）和 1 项（Tier 1 全量基线）。

---

## 逐项详情

### 项 1：Tier 1 测试 100% 通过 🟡

**已完成**（PD.2 本会话）：8 模块 / 115 测试全绿
- tx-member  test_points_tier1                 29
- tx-trade   test_order_state_machine_tier1    17
- tx-trade   test_payment_saga_tier1            9
- tx-trade   test_wine_storage_tier1            7
- tx-trade   test_rls_isolation_tier1           5
- tx-org     test_royalty_calculator_tier1     13
- tx-finance test_invoice_tier1                12
- edge       test_offline_sync_crdt            23

**缺口**：仓库共 45 个 *tier1* 文件名约定的测试，本会话只覆盖 8 个 = 17%。其余 38 文件包括：
- tx-finance: 凭证/科目/期间/ERP 推送/调整 等 ~10 个
- tx-trade: saga buffer / mark offline / 离线缓冲 等 ~5 个
- tx-org: task_engine / sales_target / RBAC ~3 个
- 其他

**处置**：扩展 `scripts/run_tier1_tests.sh` 默认列表到 45 个，下个会话 1 小时内完成基线建立。

---

### 项 2：k6 P99 < 200ms 🟡

**已就位**：
- `infra/performance/k6-load-test.js`（239 行）
- `.github/workflows/k6-nightly.yml`（北京时间 02:30 / UTC 18:30 cron）

**缺口**：
- 本地无 baseline 跑过证据（k6 nightly 是 CI 触发，需查 GitHub Actions 历史）
- 200 桌并发场景 P99 数据未沉淀到文档

**处置**：
- 立即查 `gh run list --workflow=k6-nightly.yml` 看最近 7 天结果
- 把最近一次 baseline 复制到 `docs/k6-baseline-2026-05.md`

---

### 项 3：支付成功率 > 99.9% 🟡

**已就位**：
- payment_saga 9 测试全绿（含超时回滚 / 半状态修复）
- saga_buffer_tier1 测试存在（未跑）

**缺口**：
- 真实生产/灰度环境的"成功率"指标需运行起来后才有；当前还在 DEV 阶段
- 监控大盘（Grafana/Prometheus）是否已埋点 `payment_success_rate` 指标待查

**处置**：W7-8 灰度阶段从生产监控反推；DEV 仅能提供测试通过率。

---

### 项 4：断网 4h E2E 绿（连续 3 日） 🟡

**已就位**：
- `.github/workflows/nightly-offline-e2e.yml`（北京时间 03:00 cron）
- `tests/tier1/test_offline_crdt_tier1.py`
- `services/tx-trade/tests/test_offline_buffer.py`
- `edge/sync-engine/tests/test_offline_sync_service_integration.py`

**缺口**：
- "连续 3 日绿" 需要查 nightly 历史
- 4h 真实断网（不是 mock 时钟）需 toxiproxy 配合

**处置**：查 GitHub Actions `nightly-offline-e2e` 最近 7 天结果，挑连续 3 绿的窗口作为证据。

---

### 项 5：收银员零培训（3 位签字） 🟡

**已就位**：
- `docs/demo/cashier-signoff.md`（验收模板）

**缺口**：
- 实际 3 位收银员（czyz/zqx/sgc 各 1）未签字
- W8 现场前需安排到 czyz 一线门店做 30 分钟无指导操作录像

**处置**：在 W7（灰度阶段）邀请客户安排，提供平板录像 + 文字签字。

---

### 项 6：三商户 scorecard ≥ 85 🔴 阻塞性

**已就位**：
- czyz/zqx/sgc 三套 playbook 齐全（`docs/merchant-playbooks/`）
- `scripts/merchant-deploy-check.sh`（13.7KB，部署就绪检查）
- 4 月评分基线（`docs/april-merchant-delivery-gap-analysis-2026-04.md`）：
  - czyz 81.9 / B+
  - zqx  79.0 / B
  - sgc  72.5 / B

**缺口**：
- czyz 81.9 → 90（差 +8.1）
- zqx  79.0 → 90（差 +11.0）
- sgc  72.5 → 85（差 +12.5）
- 5 月差距关闭计划（`docs/may-gap-closure-plan-2026-05.md`）正在 W1（今天 W1 第 4 天），按计划 W4 上线
- sgc 落后最多，宴会模块（`docs/BANQUET_MODULE_PLAN.md`）是关键

**处置**：
- 这是本计划的核心瓶颈，5 月 4 周（W1-W4）全部用于关闭差距
- W4 末（5-31）跑 `scripts/release-gate.sh {czyz,zqx,sgc}` 重打分
- W5（6 月初）进入灰度，W7-W8 客户演示

---

### 项 7：RLS/凭证/端口/CORS/secrets 零告警 🟡

**已就位**：
- RLS 单元测试 5/5 绿（test_rls_isolation_tier1）
- v395 已修 v391 RLS WITH CHECK 漏洞
- v397（PR #163）合并 alembic 双 head（本会话产出）
- pre-commit hook 守护 detail=str(e) 异常泄漏（v6 审计修复总会话产出）

**缺口**：
- H3 安全终查（`sprint-plan-2026Q2-unified.md` Sprint H 子项）未启动 — 全仓自动扫 + 第三方渗透报告
- 73 历史 alembic head（PI.2）未收敛
- ~120 处 detail=str(e) 异常泄漏（P2.5 Phase 2 待启动）
- ~394 处 f-string SQL 拼接（P2.2 全仓收紧待立项）

**处置**：W7（6 月初）启动 H3 安全终查 sprint，3-4 天完成。

---

### 项 8：scripts/demo-reset.sh 回退验证 ✅

**已就位**：
- `scripts/demo-reset.sh`（8.5KB，可执行）

**缺口**：跑一次留 stdout/stderr 样本到 `docs/demo-reset-verify-2026-05.md`。

**处置**：5 分钟事项，下个会话顺手做。

---

### 项 9：A/B 实验 running 未熔断 🟡

**已就位**：
- `services/tx-brain/src/services/ab_experiment_service.py`（生命周期 draft→running→terminated_*）
- `services/tx-brain/src/api/ab_experiment_routes.py`（CRUD）
- 熔断逻辑（`circuit_breaker_enabled` + `circuit_breaker_threshold` + `circuit_breaker_min_samples`）
- `services/tx-growth/src/services/growth_experiment_service.py`（业务包装）

**缺口**：
- 生产数据库无 running 实验（DEV 阶段）
- W8 验收要求"至少 1 个实验 running 未熔断"，需 W7 灰度时启一个

**处置**：W7（6 月初）灰度阶段建一个低风险实验（如 RFM 触达短信文案 A/B），running 1-2 周看数据。

---

### 项 10：三套演示话术打印就位 ✅

**已就位**：
- `docs/merchant-playbooks/czyz.md`
- `docs/merchant-playbooks/zqx.md`
- `docs/merchant-playbooks/sgc.md`
- `docs/merchant-playbooks/README.md`
- `docs/demo-playbook-store-fullflow.md`（全流程 fallback）

**处置**：W7 末打印纸质版准备 W8 现场。

---

## 关键路径图（5 周 → W8）

```
今(W1) ─→ W2 ──→ W3 ──→ W4 ──→ W5 ──→ W6 ──→ W7 ──→ W8(2026-06-09)
   │       │       │       │       │       │       │       │
   ▼       ▼       ▼       ▼       ▼       ▼       ▼       ▼
 PG.1.1  PD.2     B-01    B-04   release  灰度    H3安全  现场
 PD.2    扩45    A-01     C-04    gate    5%-50%   终查    DEMO
 W8自审  Tier1            sgc            实验启     收银员
                                          running    签字
```

## 风险登记（基于本自审）

| # | 风险 | 影响项 | 处置 |
|---|---|---|---|
| 1 | sgc 72.5 → 85 落差 12.5 最大 | 项 6 | 宴会模块 W2-W3 必须跑通；缺 W4 进入灰度 |
| 2 | 38 个 *tier1* 文件未本地基线 | 项 1 | 下会话扩展脚本，1 小时事项 |
| 3 | nightly k6 / offline-e2e 历史无连续 3 日绿证据 | 项 2/4 | 立查 gh run list；如非连续，找 root cause 修 |
| 4 | 73 历史 alembic head（PI.2） | 项 7 | 不阻塞 W8（生产 DB 主链未受影响），但要登记到风险册 |
| 5 | 收银员 3 签字需客户配合 | 项 5 | W6-W7 安排，被动等待，需 PMO 推动 |

---

## 结论

- **可控**：W8 验收**不存在不可逾越的硬阻塞**，但项 6（三商户达标）需要 5 月差距关闭计划严格按周推进
- **优先级**：项 6 > 项 7（H3 安全终查）> 项 1（Tier 1 全量）> 项 4（连续 3 日 offline-e2e）> 其他
- **建议**：本周内启动项 1 的"扩 38 文件"和项 7 的"H3 安全终查 sprint kickoff"
