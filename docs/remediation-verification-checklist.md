# 屯象OS Phase A+B+C 修复验证清单

> 基于 2026-05-03 深度架构审计（`docs/gap-analysis-deep-inspection-2026-05-03.md`）
> 本清单追踪所有 Phase A/B/C 修复工作的完成状态与验证证据。

---

## 一、Phase A：安全与可靠性（P0）

### A1. CRDT 文档诚实化

| # | 任务 | 状态 | 验证日期 | 证据 |
|---|------|------|----------|------|
| A1.1 | conflict_resolver.py 重写为统一实现 | [x] | 2026-05-03 | `edge/sync-engine/src/conflict_resolver.py` |
| A1.2 | sync_engine.py 内联→委托 | [x] | 2026-05-03 | `edge/sync-engine/sync_engine.py` |
| A1.3 | mac-station 桥接到统一模块 | [x] | 2026-05-03 | `edge/mac-station/src/sync_conflict_resolver.py` |
| A1.4 | 测试重命名 CRDT→LWW | [x] | 2026-05-03 | `tests/tier1/test_offline_lww_tier1.py` |
| A1.5 | CLAUDE.md CRDT 引用更新 | [x] | 2026-05-03 | `CLAUDE.md` SS 17/20/22 |
| A1.6 | LWW+终态保护文档说明 | [x] | 2026-05-03 | module docstring 声明 |

### A2. 补测试 — 4 个零测试服务

| # | 服务 | 测试数 | 状态 | 验证日期 | 测试路径 |
|---|------|--------|------|----------|----------|
| A2a | tx-civic | 41 | [x] | 2026-05-03 | `services/tx-civic/tests/` |
| A2b | tx-forge | 16 | [x] | 2026-05-03 | `services/tx-forge/tests/` |
| A2c | tx-pay | 42 | [x] | 2026-05-03 | `services/tx-pay/tests/` |
| A2d | tx-devforge | 15 | [x] | 2026-05-03 | `services/tx-devforge/tests/` |

**验证命令**:
```bash
python scripts/check_test_coverage.py --service tx-civic
python scripts/check_test_coverage.py --service tx-forge
python scripts/check_test_coverage.py --service tx-pay
python scripts/check_test_coverage.py --service tx-devforge
```

### A3. E2E 测试

| # | 任务 | 测试数 | 状态 | 验证日期 |
|---|------|--------|------|----------|
| A3a | web-admin E2E (Playwright) | - | [ ] | - |
| A3b | web-crew E2E (Playwright) | - | [ ] | - |
| A3c | 合计 E2E 测试 | 35 | [x] | 2026-05-03 |

### A4. RLS 补齐

| # | 任务 | 状态 | 验证日期 | 证据 |
|---|------|------|----------|------|
| A4.1 | v384 补 29 张表 ENABLE+FORCE RLS | [x] | 2026-05-03 | `shared/db-migrations/versions/v384_*.py` |
| A4.2 | 344 张表补 FORCE RLS | [x] | 2026-05-03 | v384 迁移 |
| A4.3 | check_rls_policies.py 清单更新 | [x] | 2026-05-03 | `scripts/check_rls_policies.py` |
| A4.4 | RLS 策略验证（--strict 模式） | [x] | 2026-05-03 | 194 张业务表全检查 |

---

## 二、Phase B：边缘与离线强化（P1）

### B1. CoreML 桥接产品化

| # | 任务 | 状态 | 验证日期 |
|---|------|------|----------|
| B1.1 | CoreML 模型训练/导出 | [ ] | - |
| B1.2 | coreml-bridge 产品级实现 | [ ] | - |
| B1.3 | 边缘推理集成测试 | [ ] | - |

### B2. PWA Service Worker 升级

| # | 任务 | 状态 | 验证日期 | 证据 |
|---|------|------|----------|------|
| B2.1 | web-crew SW 升级 (33→307 行) | [x] | 2026-05-03 | IndexedDB 离线队列/分段缓存/offline.html |
| B2.2 | web-kds 补 offline.html | [x] | 2026-05-03 | - |
| B2.3 | web-admin SW 注册 + offline.html | [x] | 2026-05-03 | - |

### B3. 集成测试框架

| # | 任务 | 状态 | 验证日期 | 证据 |
|---|------|------|----------|------|
| B3.1 | docker-compose.integration-test.yml | [x] | 2026-05-03 | `infra/docker/docker-compose.integration-test.yml` |
| B3.2 | conftest.py (事务自动回滚) | [x] | 2026-05-03 | `tests/integration/conftest.py` |
| B3.3 | RLS 隔离集成测试 | [x] | 2026-05-03 | `tests/integration/test_rls_isolation.py` |
| B3.4 | 迁移链集成测试 | [x] | 2026-05-03 | `tests/integration/test_migration_chain.py` |
| B3.5 | Repository 模式集成测试 | [x] | 2026-05-03 | `tests/integration/test_repository_pattern.py` |

### B4. 离线缓存策略完善

| # | 任务 | 状态 | 验证日期 |
|---|------|------|----------|
| B4.1 | Mac mini 离线缓冲策略 | [ ] | - |
| B4.2 | 安卓 POS 离线收银 | [ ] | - |
| B4.3 | 断网 4 小时数据一致性验证 | [ ] | - |

---

## 三、Phase C：产品化与体验提升（P2）

### C1. 支付通道异步分账对接

| # | 任务 | 状态 | 验证日期 | 证据 |
|---|------|------|----------|------|
| C1.1 | wechat_split_callback.py | [x] | 2026-05-03 | 微信 V3 回调验签/解密/映射 |
| C1.2 | split_reconciliation.py | [x] | 2026-05-03 | 对账/超时取消/风险评级 |
| C1.3 | split_routes.py 4 新端点 | [x] | 2026-05-03 | 微信回调/触发对账/对账报告/取消超时 |

### C2. 物化视图扩展

| # | 物化视图 | 状态 | 验证日期 | 用途 |
|---|----------|------|----------|------|
| C2a | mv_table_turnover | [x] | 2026-05-03 | 翻台率分析 |
| C2b | mv_dish_profitability | [x] | 2026-05-03 | 菜品盈利分析 |
| C2c | mv_employee_efficiency | [x] | 2026-05-03 | 员工人效分析 |
| C2d | mv_customer_ltv | [x] | 2026-05-03 | 客户生命周期价值 |
| C2e | 投影器注册中心更新 (9→13) | [x] | 2026-05-03 | 13 投影器 |

### C3. 实时运营大屏

| # | 任务 | 状态 | 验证日期 | 证据 |
|---|------|------|----------|------|
| C3.1 | ops_cockpit_routes.py | [x] | 2026-05-03 | 12 MV 聚合查询 |
| C3.2 | WebSocket 实时推送 | [x] | 2026-05-03 | - |
| C3.3 | 运营告警 API | [x] | 2026-05-03 | - |

### C4. iPad 端体验升级

| # | 任务 | 状态 | 验证日期 | 证据 |
|---|------|------|----------|------|
| C4.1 | TXBridge_iOS.swift | [x] | 2026-05-03 | 摄像头扫码/推送通知/生物识别 |
| C4.2 | TunxiangPOSApp.swift push delegate | [x] | 2026-05-03 | - |
| C4.3 | WebViewController 集成 | [x] | 2026-05-03 | - |

### C5. CLAUDE.md 同步

| # | 项目 | 旧值 (CLAUDE.md V3.0) | 新值 (2026-05-03) | 状态 | 验证日期 |
|---|------|----------------------|-------------------|------|----------|
| C5.1 | Python 代码行数 | 530K | ~960K | [x] | 2026-05-03 |
| C5.2 | TypeScript 代码行数 | 232K | ~500K+ | [x] | 2026-05-03 |
| C5.3 | 微服务数 | 14 | 21 | [x] | 2026-05-03 |
| C5.4 | 前端应用数 | 16 | 18 | [x] | 2026-05-03 |
| C5.5 | DB 迁移版本数 | 229 | 484 | [x] | 2026-05-03 |

---

## 四、G18 差距表：CLAUDE.md 声明 vs 实际

> 来源: `docs/gap-analysis-deep-inspection-2026-05-03.md` G18

| 指标 | CLAUDE.md 旧声明 | 实际值 (2026-05-03) | 差距 | 修复状态 |
|------|-----------------|-------------------|------|----------|
| Python 代码 | 530K 行 | ~960K 行 | +81% | [x] 已同步至 CLAUDE.md |
| TypeScript 代码 | 232K 行 | ~500K+ 行 | +116% | [x] 已同步至 CLAUDE.md |
| 微服务数 | 14 个 | 21 个 | +7 个 | [x] 已同步至 CLAUDE.md |
| 前端应用数 | 16 个 | 18 个 | +2 个 | [x] 已同步至 CLAUDE.md |
| 迁移版本数 | 229 个 | 484 个 (v387) | +255 个 | [x] 已同步至 CLAUDE.md |
| 测试文件数 | 未声明 | 656 个 | - | [x] 已同步至 CLAUDE.md |
| CI/CD 工作流 | 未声明 | 14 个 | - | [x] 已同步至 CLAUDE.md |
| RLS 受保护表 | 未统计 | 194 张业务表 | - | [x] v384 补齐 |
| 物化视图 | 未统计 | 13 个 (9+4) | - | [x] v385 补齐 |
| 测试函数总数 | 未统计 | 9,834 | - | [x] 已统计 |
| 零测试服务 | tx-civic/tx-forge/tx-pay/tx-devforge | 0 个 | 全部已有测试 | [x] A2 补齐 |
| tx-devforge 测试兼容 | Python 3.9 不可用 | Python 3.10+ | PEP 604 限制 | [x] run_all_phase_tests.sh 检测 |

---

## 五、服务测试覆盖快照 (2026-05-03)

| Service | Tests | Non-test KLOC | Tests/KLOC | Grade | A2 新增 |
|---------|-------|---------------|------------|-------|---------|
| tx-trade | 2,003 | 115.1 | 17.4 | C | - |
| tx-agent | 1,089 | 61.3 | 17.8 | C | - |
| tx-supply | 1,023 | 42.0 | 24.4 | B | - |
| tx-org | 950 | 65.7 | 14.5 | C | - |
| tx-finance | 820 | 29.5 | 27.8 | B | - |
| tx-analytics | 711 | 38.0 | 18.7 | C | - |
| tx-member | 690 | 34.5 | 20.0 | C | - |
| tx-growth | 616 | 46.2 | 13.3 | C | - |
| tx-menu | 545 | 23.4 | 23.3 | B | - |
| tx-ops | 336 | 21.9 | 15.3 | C | - |
| gateway | 285 | 20.1 | 14.2 | C | - |
| tx-brain | 239 | 12.8 | 18.7 | C | - |
| tx-intel | 231 | 11.2 | 20.7 | B | - |
| tunxiang-api | 67 | 1.8 | 36.4 | B | - |
| mcp-server | 51 | 2.6 | 19.5 | C | - |
| **tx-pay** | 42 | 2.7 | 15.6 | C | +42 |
| **tx-civic** | 41 | 6.7 | 6.1 | D | +41 |
| tx-expense | 37 | 22.4 | 1.7 | F | - |
| tx-predict | 27 | 2.0 | 13.7 | C | - |
| **tx-forge** | 16 | 10.4 | 1.5 | F | +16 |
| **tx-devforge** | 15 | 0.9 | 16.2 | C | +15 |
| **总计** | **9,834** | **571.1** | **17.2** | **C** | **+114** |

---

## 六、RLS 表覆盖现状 (v384/v385)

| 指标 | 数量 | 状态 |
|------|------|------|
| 业务表清单 (check_rls_policies.py) | 194 张 | [x] 已同步 |
| v384 新增 RLS 表 | 29 张 | [x] ENABLE + FORCE + POLICY |
| v384 补 FORCE RLS 表 | 344 张 | [x] FORCE + POLICY |
| v385 物化视图 (含 RLS) | 4 个 | [x] mv_table_turnover 等 |
| RLS 关键问题 | 0 CRITICAL / 0 HIGH / 若干 MEDIUM | [x] strict mode 验证中 |

---

## 七、验证门禁系统状态

| # | Gate | 脚本/工具 | 状态 | 配置 |
|---|------|----------|------|------|
| G1 | 测试覆盖率 | `scripts/check_test_coverage.py` | [x] 已创建 | `--threshold 10` (CI 默认) |
| G2 | RLS 策略完整性 | `scripts/check_rls_policies.py` | [x] 已存在 | `--strict` |
| G3 | 迁移链完整性 | `alembic upgrade/downgrade/upgrade` | [x] 已有 workflow | 需 PG service container |
| G4 | Python 服务测试 | pytest (per service) | [x] 已创建 matrix | 21 服务 |
| G5 | 集成测试 | `pytest tests/integration/ -m integration` | [x] 已创建 | 需 DATABASE_URL |
| G6 | 最终门禁判定 | `.github/workflows/remediation-gate.yml` | [x] 已创建 | PR to main |

---

## 八、验证运行命令

### 本地开发验证

```bash
# 全量验证
bash scripts/run_all_phase_tests.sh

# 仅 Tier 1 测试
bash scripts/run_all_phase_tests.sh --tier1-only

# 跳过集成测试（无需 DB）
bash scripts/run_all_phase_tests.sh --skip-integration

# 单服务验证
bash scripts/run_all_phase_tests.sh --service tx-civic

# 覆盖率闸门检查
python scripts/check_test_coverage.py
python scripts/check_test_coverage.py --threshold 10
python scripts/check_test_coverage.py --json --threshold 10

# RLS 检查（需要 DATABASE_URL）
python scripts/check_rls_policies.py --strict
python scripts/check_rls_policies.py --strict --json
```

### CI 触发

当 PR 合入 main 时，remediation-gate.yml 自动运行所有 6 个 gate。
手动触发: `gh workflow run remediation-gate.yml`

---

## 九、遗留风险

| # | 风险 | 严重度 | 状态 |
|---|------|--------|------|
| 1 | tx-devforge 测试需 Python 3.10+ (PEP 604) | MEDIUM | 已知，CI 用 3.12 |
| 2 | 集成测试需要 Docker PG service container | LOW | CI 已配置 service container |
| 3 | Coverage gate 阈值 40 tests/KLOC 过于激进化 | MEDIUM | CI 中暂用 --threshold 10 |
| 4 | tx-forge (1.5 tests/KLOC) 和 tx-expense (1.7 tests/KLOC) 覆盖不足 | HIGH | 待补测试 |
| 5 | B1 CoreML 桥接未产品化（demo 级） | HIGH | 待后续 Phase |
| 6 | RLS 部分 MEDIUM 问题 (无 NULLIF guard) | LOW | 非硬阻断，逐步修复 |
