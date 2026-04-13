# 屯象OS 五月差距关闭计划 v1.0

> 基于四月交付评分 + 差距分析，锁定五月必须关闭的差距项  
> 日期：2026-05-01  
> 关联文件：`docs/april-merchant-delivery-gap-analysis-2026-04.md`  
> 负责人：屯象科技研发团队

---

## 一、核心目标

| 商户 | 四月评分 | 五月目标 | 目标等级 | 演示就绪度目标 |
|------|---------|---------|---------|--------------|
| czyz（尝在一起） | 81.9/B+ | ≥ 90 | A | ≥ 90 |
| zqx（最黔线） | 79.0/B | ≥ 90 | A | ≥ 90 |
| sgc（尚宫厨） | 72.5/B | ≥ 85 | B+ | ≥ 85 |

**综合差距率目标：~20% → ≤ 5%**

三商户全部 GO-TO-LIVE 就绪，可支撑签约前最终演示与正式上线。

---

## 二、五月交付计划（按周）

### Week 1 (05-01~05-07): 数据质量与基础资料标准化

**目标：关闭 A-01、A-02、A-03**

#### 1.1 三商户基础资料统一交付清单模板（A-01）

产出物：`docs/merchant-data-delivery-checklist-v1.md`

涵盖七大主数据域：

| 域 | 关键表/接口 | 完整率要求 |
|---|---|---|
| 组织架构 | `tx-org` 服务，`/api/v1/org/stores`，`/api/v1/org/departments` | ≥ 95% |
| 门店配置 | `tx-trade` 服务，`/api/v1/stores/{id}/config` | 100% |
| 菜品主档 | `tx-menu` 服务，`/api/v1/menu/dishes`，包含 BOM、分类、价格 | ≥ 98% |
| 会员主档 | `tx-member` 服务，`/api/v1/members`，含 RFM 分层 | ≥ 90% |
| 供应商/食材 | `tx-supply` 服务，`/api/v1/supply/ingredients` | ≥ 95% |
| 员工花名册 | `tx-org` 服务，`/api/v1/org/employees` | 100% |
| 渠道账号 | `shared/adapters/` 适配器，含美团/饿了么/品智POS配置 | 100% |

执行步骤：
1. 为每商户创建 `scripts/seed_{code}.py` 种子脚本（czyz/zqx/sgc），补齐空缺字段
2. 运行 `scripts/check_rls_policies.py` 确认每条记录有合法 `tenant_id`
3. 输出每商户一份《基础资料交付报告》，格式：`docs/delivery-report-{code}-2026-05.md`

#### 1.2 三商户验收口径标准（A-02）

在 `services/tx-analytics/src/api/` 新增 `merchant_data_quality_routes.py`：
- `GET /api/v1/analytics/data-quality/{merchant_code}` — 返回完整率/唯一性/跨系统一致率
- 验收阈值写入 `services/tx-analytics/src/config/quality_thresholds.py`
- 每日定时检查写入 `shared/events/src/event_types.py` 的 `DataQualityEventType`

#### 1.3 开发库→正式库发布闸门（A-03）

在 `scripts/` 新增 `release-gate.sh`：
- 检查 Alembic 迁移版本与目标环境一致（`shared/db-migrations/`）
- 跑 pytest 冒烟测试（P0 服务：tx-trade、tx-member、tx-analytics）
- 调用 `scripts/merchant-deploy-check.sh {code}` 确认评分 ≥ 85 且 go_no_go=GO
- 生成 `docs/release-gate-{code}-{date}.md` 发布闸门记录

---

### Week 2 (05-08~05-14): AI 分析深化与证据链

**目标：关闭 B-03、B-04，提升 B-01/B-02 完成度**

#### 2.1 AI 分析与分商户经营目标绑定（B-03）

服务：`services/tx-analytics`，`services/tx-brain`

在 `services/tx-analytics/src/api/merchant_kpi_config_routes.py` 新增：
- `POST /api/v1/analytics/merchant-kpi/configs` — 写入商户目标配置
- `GET /api/v1/analytics/merchant-kpi/configs` — 读取（带 `X-Tenant-ID` header）

商户目标配置模板（存入 `services/tx-analytics/src/config/merchant_targets.py`）：

```python
MERCHANT_TARGETS = {
    "czyz": {
        "table_turnover_daily": 4.5,       # 翻台率
        "avg_dish_time_minutes": 18,        # 出餐时间（对应硬约束 C3）
        "seat_utilization_pct": 75,         # 座位利用率
    },
    "zqx": {
        "avg_ticket_rmb": 88,               # 客单价
        "member_repurchase_30d_pct": 35,    # 30日复购率
        "channel_mix_direct_pct": 60,       # 直营渠道占比
    },
    "sgc": {
        "avg_ticket_rmb": 168,              # 宴会客单价
        "banquet_deposit_rate_pct": 80,     # 订金收款率
        "labor_cost_ratio_pct": 22,         # 人力成本占比
    },
}
```

AI 报告生成（`services/tx-brain/src/`）：每次生成日报/周报时，注入对应商户目标作为 prompt context，确保建议与目标挂钩。

#### 2.2 AI 结论可追溯证据链（B-04）

在 `services/tx-analytics/src/models/` 新增 `ai_evidence_chain.py`：

```python
class AIEvidenceChain(BaseModel):
    conclusion: str                    # AI 结论摘要
    source_metrics: list[dict]         # 源指标列表（含时间戳、数值）
    mv_snapshots: list[str]            # 物化视图快照引用（mv_store_pnl 等）
    event_ids: list[UUID]              # 关联事件 ID（来自 events 表）
    confidence: float                  # 置信度
    generated_at: datetime
    agent_decision_log_id: UUID        # 关联 AgentDecisionLog
```

`GET /api/v1/analytics/ai-report/{report_id}/evidence` — 返回完整证据链

关联物化视图（`shared/db-migrations/` v148 已建）：
- `mv_store_pnl` → 财务结论证据
- `mv_member_clv` → 会员分析证据
- `mv_daily_settlement` → 日结结论证据
- `mv_discount_health` → 折扣异常证据

#### 2.3 实时数据 SLA 统一（B-01）

在 `docs/` 发布 `real-time-data-sla.md`：

| 指标类型 | 刷新频率 | 技术实现 |
|---------|---------|---------|
| 收银流水 | 实时（<30s） | PG LISTEN/NOTIFY → Redis Stream |
| KPI 聚合 | 分钟级（T+1min） | 物化视图 mv_store_pnl 定时刷新 |
| 经营日报 | T+0（当天） | sync-engine 300s 轮询 |
| 月度分析 | T+1（次日凌晨） | Cron 触发投影器 rebuild |

---

### Week 3 (05-15~05-21): 上线前压测与演示监控

**目标：关闭 C-03、C-04，sgc 演示就绪度从 60 → 85**

#### 3.1 演示环境数据重置机制（C-03）

新增 `scripts/demo-reset.sh`：
```bash
# 用法: ./scripts/demo-reset.sh <merchant_code>
# 步骤：
# 1. 截断演示租户数据（保留结构）
# 2. 重新运行 scripts/seed_{code}.py
# 3. 重建物化视图（shared/events/src/projector.py rebuild）
# 4. 清空 Redis 缓存（FLUSHDB 演示 DB）
# 5. 输出重置报告
```

对应 Docker Compose 服务（三份 `docker-compose.{code}.yml` 中均有 `seed-data` job，可单独重启）：
```bash
docker compose -f infra/docker/docker-compose.czyz.yml restart seed-data
```

#### 3.2 演示监控面板（C-04）

在 `services/tx-analytics/src/api/` 新增 `demo_monitor_routes.py`：
- `GET /api/v1/demo/health-check` — 汇总所有服务健康 + 接口成功率
- `GET /api/v1/demo/sync-status` — sync-engine 最近同步时间 + 差异行数
- `GET /api/v1/demo/device-status` — 安卓 POS + Mac mini 在线状态（WebSocket ping）

前端接入 `apps/web-admin/src/pages/DemoMonitor/` （新建页面）。

#### 3.3 sgc 宴会业务补齐

sgc 演示就绪度偏低（60分）的核心原因：宴会业务流程缺演示数据。

- 在 `scripts/seed_sgc.py` 补充：5张宴会预订、3张已付定金订单
- 确认 `tx-trade` 服务的 `banquet_routes.py` 返回正确数据
- 补充 sgc 专属宴会看板页面：`apps/web-admin/src/pages/BanquetDashboard/`

#### 3.4 全链路压测

针对三商户各执行：
```bash
# 压测收银→打印→KDS 主链路
locust -f scripts/load-test-trade.py --host http://localhost:8000 \
  --users 50 --spawn-rate 10 --run-time 5m
```

验收标准：P99 响应时间 < 500ms，错误率 < 0.1%。

---

### Week 4 (05-22~05-31): 正式上线与收尾

**目标：三商户 GO-TO-LIVE，差距率 ≤ 5%**

#### 4.1 上线前最终检查

按商户顺序（czyz → zqx → sgc）执行：
1. `./scripts/release-gate.sh {code}` — 发布闸门通过
2. `./scripts/merchant-deploy-check.sh {code}` — 部署就绪确认
3. `./scripts/demo-reset.sh {code}` — 演示数据重置为标准集
4. 执行《演示导播手册》完整彩排一遍

#### 4.2 交付评分卡最终评审

调用 `GET /api/v1/analytics/delivery-scorecard/{merchant_code}` 获取最终评分。  
目标：czyz ≥ 90，zqx ≥ 90，sgc ≥ 85。

#### 4.3 DEVLOG 与文档收尾

- `DEVLOG.md` 补齐五月所有开发记录
- 更新 `CLAUDE.md` 第十四节审计修复状态
- 归档本计划为 `docs/may-gap-closure-plan-2026-05-FINAL.md`

---

## 三、差距逐项关闭计划

| 差距ID | 描述 | 责任方 | 截止日 | 验收标准 | 关联代码/文件 |
|--------|------|--------|--------|---------|--------------|
| A-01 | 三商户基础资料统一交付清单模板 | 数据组 | 05-07 | 每商户一份交付报告，7大域完整率达标 | `scripts/seed_{code}.py`、`docs/merchant-data-delivery-checklist-v1.md` |
| A-02 | 三商户主数据验收口径标准化 | 数据组 + 后端 | 05-07 | `GET /api/v1/analytics/data-quality/{code}` 三商户全部 PASS | `services/tx-analytics/src/api/merchant_data_quality_routes.py` |
| A-03 | 开发库→正式库发布闸门 | 后端 + DevOps | 05-07 | `scripts/release-gate.sh` 三商户执行通过，生成闸门记录 | `scripts/release-gate.sh`、`shared/db-migrations/` |
| B-03 | AI 分析与分商户经营目标绑定 | AI 组 + 后端 | 05-14 | AI 日报含商户目标对比数据，czyz 含翻台率分析，zqx 含复购率分析，sgc 含宴会转化分析 | `services/tx-analytics/src/config/merchant_targets.py`、`services/tx-brain/src/` |
| B-04 | AI 结论可追溯证据链 | AI 组 + 后端 | 05-14 | `GET /api/v1/analytics/ai-report/{id}/evidence` 返回源指标 + 事件 ID + MV 引用 | `services/tx-analytics/src/models/ai_evidence_chain.py` |
| C-03 | 演示环境数据重置机制 | 后端 + DevOps | 05-21 | `./scripts/demo-reset.sh {code}` 10 分钟内完成重置，数据恢复标准集 | `scripts/demo-reset.sh`、`infra/docker/docker-compose.{code}.yml` |
| C-04 | 演示监控面板 | 后端 + 前端 | 05-21 | `GET /api/v1/demo/health-check` 可用；web-admin 有 DemoMonitor 页面实时显示服务状态 | `services/tx-analytics/src/api/demo_monitor_routes.py`、`apps/web-admin/src/pages/DemoMonitor/` |

---

## 四、风险与应对

| # | 风险描述 | 概率 | 影响 | 应对措施 |
|---|---------|------|------|---------|
| R1 | sgc 宴会数据缺口导致演示就绪度无法从 60 升至 85 | 高 | 高 | Week 3 专项冲刺，优先补充宴会种子数据与 `banquet_routes.py`；如仍不足则调整演示剧本绕过 |
| R2 | 物化视图（v148）在演示环境重建时间超 10 分钟 | 中 | 中 | 预先在 `scripts/demo-reset.sh` 中使用增量投影（`projector.rebuild(incremental=True)`）；非全量重建 |
| R3 | 三商户 Docker Compose 环境端口冲突（czyz/zqx/sgc 并行启动） | 低 | 中 | 端口偏移量 +100/+200 已在 `docker-compose.{code}.yml` 固定；增加启动前端口检查步骤 |
| R4 | `except Exception` 遗留代码在压测中触发静默失败 | 中 | 高 | Week 3 压测前用 `ruff check --select E722 services/` 扫描并修复，确保符合第十四节约束 |
| R5 | AI 证据链接口（B-04）与 AgentDecisionLog 关联查询性能差（全表扫描） | 中 | 中 | 为 `events` 表的 `(tenant_id, stream_id, event_type)` 添加复合索引（新迁移文件 v256） |

---

## 五、技术债务处理

### 5.1 KPI 估算值 → 真实 DB（优先级：P1）

当前 `services/tx-analytics/src/api/merchant_delivery_scorecard_routes.py` 中部分指标（如 `demo_readiness_score`）为硬编码估算值。

五月目标：
- 将 sgc 演示就绪度（当前硬编码 60）改为从真实检查结果动态计算
- 数据源：`GET /api/v1/demo/health-check` 结果聚合
- 改动文件：`services/tx-analytics/src/services/delivery_scorecard_service.py`（待创建）

### 5.2 `except Exception` 清理（优先级：P0，符合第十四节约束）

重点清理范围（基于四月代码审计）：
- `services/tx-agent/` — Agent 动作执行器中的宽泛异常捕获
- `services/tx-trade/src/routers/cashier_engine.py` — 收银引擎异常路径
- `shared/adapters/` — 旧系统适配器的错误处理

执行方式：`ruff check services/ shared/adapters/ --select E722 --output-format=json > /tmp/broad-except.json`，逐文件修复，每修复一个文件提交一次。

### 5.3 数据库迁移版本推进（v256+）

计划新增迁移：
- v256：`events` 表复合索引（R5 风险缓解）
- v257：`merchant_kpi_targets` 配置表（B-03 依赖）
- v258：`ai_evidence_chains` 表（B-04 依赖）
- v259：`data_quality_checks` 表（A-02 依赖）

迁移文件位置：`shared/db-migrations/versions/`

### 5.4 ModelRouter 统一（符合第十四节安全约束）

确认 `services/tx-brain/src/` 所有 LLM 调用均通过 `ModelRouter`，不直接调用 Claude API。扫描命令：`grep -r "anthropic.Anthropic()" services/ --include="*.py"`，发现直接调用则替换。

---

## 六、成功标准

### 定量标准

| 指标 | 当前值 | 五月目标 | 验收方式 |
|------|-------|---------|---------|
| czyz 交付评分 | 81.9 | ≥ 90 | `GET /api/v1/analytics/delivery-scorecard/czyz` → `total_score` |
| zqx 交付评分 | 79.0 | ≥ 90 | `GET /api/v1/analytics/delivery-scorecard/zqx` → `total_score` |
| sgc 交付评分 | 72.5 | ≥ 85 | `GET /api/v1/analytics/delivery-scorecard/sgc` → `total_score` |
| czyz 演示就绪度 | ~80 | ≥ 90 | `demo_readiness_score` 字段 |
| zqx 演示就绪度 | ~80 | ≥ 90 | `demo_readiness_score` 字段 |
| sgc 演示就绪度 | 60 | ≥ 85 | `demo_readiness_score` 字段 |
| 差距率 | ~20% | ≤ 5% | 差距 ID 全部关闭（A-01/02/03 + B-03/04 + C-03/04） |
| broad except 数量 | 未统计 | 0 个新增 | `ruff check --select E722 services/` |
| P0 服务测试覆盖率 | 未统计 | ≥ 80% | `pytest --cov=services/tx-trade services/tx-member services/tx-analytics` |

### 定性标准

1. **三商户全部可独立演示**：执行 `./scripts/merchant-deploy-check.sh {code}` 均返回 exit 0（GO）
2. **AI 分析可执行化**：每份 AI 报告包含 3 条以上可追溯到源数据的具体建议
3. **数据信任度**：主数据域完整率 ≥ 95%，验收口径文档经商户确认签字
4. **演示稳定性**：连续 3 次彩排无中断，重置脚本 10 分钟内完成

---

> 本计划由 Claude Code 基于四月交付差距分析自动生成，需由研发负责人审核后生效。  
> 计划执行过程中如发现新差距，及时更新本文件并在 DEVLOG.md 记录。
