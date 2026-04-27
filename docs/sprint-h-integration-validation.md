# Sprint H — 集成验证运行手册

> Week 7-10（2026-06-10 至 2026-07-04）。跑通徐记海鲜 DEMO 端到端，
> 通过 Week 8 DEMO Go/No-Go 10 项门槛。

## 目标

在真实 DEMO 环境（腾讯云 + Mac mini + 商米 T2）跑通一家门店一天的完整业务流，
向徐记海鲜、尚宫厨、尝在一起 3 位决策者演示屯象OS 替代现有系统的能力。

## 前置条件

- [ ] D 批次 6 PR 合入 main（#82 #83 #84 #85 #87 #88）
- [ ] E 批次 4 PR 合入 main（#91 #92 #93 #94）
- [ ] D4 shared/prompt_cache 合入（#89）
- [ ] 测试环境 PostgreSQL 16 + RLS 启用
- [ ] Mac mini M4 部署完成（至少 1 台）
- [ ] 商米 T2 POS 1 台 + 打印机

## 三步走

### 第一步：DEMO 数据准备（Week 7）

```bash
# 1. 执行所有迁移
cd shared/db-migrations && alembic upgrade head

# 2. 导入徐记海鲜种子数据
export DEMO_TENANT_ID=10000000-0000-0000-0000-000000001001
export DATABASE_URL=postgresql://user:pass@demo-db:5432/tunxiang_demo

psql $DATABASE_URL -v tenant_id="'$DEMO_TENANT_ID'" \
  -f infra/demo/xuji_seafood/seed.sql

# 3. 验证数据
python3 scripts/demo_go_no_go.py --tenant-id $DEMO_TENANT_ID --only 6 8
```

### 第二步：Week 8 Go/No-Go 10 项验证

按顺序跑 10 项检查：

```bash
# 完整跑（含 Tier 1 测试 + RLS 审计）
python3 scripts/demo_go_no_go.py --tenant-id $DEMO_TENANT_ID

# CI 门禁（任何 NO_GO 即 exit 1）
python3 scripts/demo_go_no_go.py --tenant-id $DEMO_TENANT_ID --strict

# JSON 输出（供 Grafana dashboard 订阅）
python3 scripts/demo_go_no_go.py --tenant-id $DEMO_TENANT_ID --json \
  > /tmp/go-no-go-$(date +%Y%m%d).json
```

### 10 项门槛详解

| # | 项目 | 通过标准 | 验证方式 |
|---|------|---------|---------|
| 1 | Tier 1 测试 100% 通过 | 全部绿 | `pytest services/*/src/tests/**/test_*tier1*.py` |
| 2 | k6 P99 < 200ms | P99 < 200ms | `infra/performance/k6-latest-results.json` |
| 3 | 支付成功率 > 99.9% | 近 7 天 | DB 查 `payments` 表 |
| 4 | 断网 4h E2E 绿 | 连续 3 日 | `infra/nightly/offline-e2e-results.json` |
| 5 | 收银员零培训 3 位签字 | 签字页 3 个签字 | `docs/demo/cashier-signoff.md` |
| 6 | 三商户 scorecard ≥ 85 | 每家 ≥ 85 | `docs/demo/scorecards/*.json` |
| 7 | 安全审计零告警 | RLS + 端口 + secrets | `scripts/check_rls_policies.py` |
| 8 | demo-reset.sh 回退可用 | 可执行 | `scripts/demo-reset.sh` / `cleanup.sql` |
| 9 | A/B 实验 running 未熔断 | ≥1 个 | DB 查 `ab_experiments` |
| 10 | 三套话术打印就位 | ≥3 份 md | `docs/demo/scripts/` |

### 第三步：端到端场景演示

按 3 套演示话术顺序执行（见 `docs/demo/scripts/`）：

#### 话术 01：运营故事线（45min）
受众：徐记董事长 + 运营总监 + IT 总监
核心：23 套系统替代路径

#### 话术 02：IT 架构视角（60min）
受众：徐记 IT 总监 + 架构师
核心：技术栈成熟度 + 运维可控

#### 话术 03：财务采购视角（40min）
受众：CFO + 采购总监
核心：月结对账 + 税务合规

每场演示后填 scorecard：
```bash
# 编辑 docs/demo/scorecards/<merchant>.json
# 记录 evaluated_at / score / dimensions / risks
```

## 集成测试

### 跑 Sprint H 验证测试

```bash
# 不依赖 DB（快速校验脚本 + 文件）
pytest tests/integration/test_sprint_h_demo.py -v -k "not EndToEnd"

# 完整 integration（需 DATABASE_URL + seed 已导入）
export DATABASE_URL=postgresql://...
pytest tests/integration/test_sprint_h_demo.py -v
```

### 预期结果

- 30+ 测试覆盖：seed 结构 / 脚本可执行 / scorecard 格式 / 话术存在
- `TestEndToEndDemo` 在 DB 可用时额外校验 RLS + 数据完整性

## 异常恢复

### DEMO 数据污染

```bash
# 软删当前 tenant 所有 DEMO 数据
psql $DATABASE_URL -v tenant_id="'$DEMO_TENANT_ID'" \
  -f infra/demo/xuji_seafood/cleanup.sql

# 重新导入
psql $DATABASE_URL -v tenant_id="'$DEMO_TENANT_ID'" \
  -f infra/demo/xuji_seafood/seed.sql
```

### Mac mini 故障

降级方案：切云端直连 POS。演示无 Core ML 边缘加速，延迟从 200ms 升到 800ms。
恢复后自动同步 + CRDT 冲突解析。

### Claude API 不可用

所有 D 批次 service 有规则引擎 fallback（`invoker=None`）。演示用 fallback 数据，
标 `[规则引擎]` 前缀说明。

## 进入 Week 8 的前提

本 Sprint H 输出 3 份 `go-no-go-YYYYMMDD.json` 连续绿，即可进入 Week 8 正式 DEMO。

任何 NO_GO 需要：
1. 当日 standup 同步
2. 48h 内修复 + 回归
3. 修复后重跑 Go/No-Go 直到连绿

## 后续 Sprint 映射

Week 10 后：
- Week 11: Pilot 准备（选 1 家门店真实上线）
- Week 12: Pilot 上线 + 2 周真实运行 + 数据采集
- Week 14: 复盘 + 决定是否 GA（general availability）

## 参考文件

- `CLAUDE.md` § 22 Week 8 DEMO 门槛
- `docs/sprint-plan-2026Q2-unified.md` § 3
- `infra/demo/xuji_seafood/seed.sql`
- `scripts/demo_go_no_go.py`
- `tests/integration/test_sprint_h_demo.py`
- `docs/demo/scripts/01-03`
- `docs/demo/scorecards/*.json`
- `docs/demo/cashier-signoff.md`
