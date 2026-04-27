# 演示话术 02 — IT 架构视角（徐记 IT 总监 + 技术评审）

> 受众：徐记海鲜 IT 总监 + 架构师 + 运维负责人
> 时长：60 分钟
> 核心诉求："技术栈是否成熟？运维可控吗？"

## 开场（3 分钟）

> "王总，今天不讲故事讲架构。
> 您关心的 5 个问题：技术选型、数据主权、可观测性、灾难恢复、扩展性。
> 我们按这 5 个主题逐一走，每个 10 分钟。"

## 1. 技术选型（10 分钟）

### 1.1 五层架构图走查

```
L4  多形态前端层    React 18 + TypeScript + Vite
L3  Agent OS 层     Master Agent + 9 Skill Agent（边缘+云端双层）
L2  业务中台层      14 微服务 × 9 产品域 = 360+ 路由模块
L1  Ontology 层     6 大实体 + 4 层治理 + PostgreSQL RLS
L0  设备适配层      安卓POS（商米 SDK）+ Mac mini（Core ML）
```

**关键决策**：
- **L4 React 一套代码** — 安卓 POS / iPad / 总部 Web 共用，iPad 优雅降级
- **L3 双层推理** — 边缘 Core ML（实时）+ 云端 Claude API（复杂）
- **L1 PostgreSQL RLS** — 多租户租户级数据硬隔离，不依赖应用层过滤
- **L0 商米 SDK 不自研驱动** — 中国餐饮外设生态 100% 围绕安卓成熟

### 1.2 云端 vs 门店分工

```
                    腾讯云（PostgreSQL 16 主）
                        │ Tailscale 零信任
                    Mac mini M4（本地 PG 副本）
                        │ WiFi 局域网
            ┌───────────┼───────────┐
     安卓 POS 主机     安卓平板       员工手机
     (收银+外设)       (KDS)         (PWA)
```

**为什么 Mac mini？** — M4 Neural Engine 做 Core ML 推理（出餐预测 / 折扣检测），同时是本地 PG 副本存放地。

## 2. 数据主权（12 分钟）

### 2.1 RLS 策略审计

- 演示 `scripts/check_rls_policies.py` 扫描：所有表 `tenant_id::text = current_setting('app.tenant_id')` 策略正确
- **硬约束**：所有业务表强制 `tenant_id` 非空 + RLS 启用

### 2.2 数据回导保障

- 演示 `scripts/export_tenant_data.py` 一次性导出某租户所有数据为 CSV/JSON
- **承诺**：任何时候客户可以 24h 内拿到全量数据

### 2.3 事件总线保真

- 演示 `shared/events/` 所有写入都旁路写 `events` 表（append-only）
- **价值**：即便物化视图损坏也能从事件流重建

## 3. 可观测性（10 分钟）

### 3.1 日志三件套

- **结构化日志**（structlog JSON） → 腾讯云 CLS
- **Trace**（OpenTelemetry） → Jaeger
- **Metrics**（Prometheus） → Grafana

### 3.2 Agent 决策可追溯

- 演示 `agent_decision_log` 表：每个 AI 决策包含 reasoning + context + constraints_check
- 演示 Grafana 看板：Prompt Cache 命中率 / 模型成本 / 置信度分布

### 3.3 告警规则

```yaml
- alert: AgentDecisionLatencyHigh
  expr: histogram_quantile(0.99, agent_decision_latency_ms_bucket) > 5000
  for: 10m
- alert: RlsBypassAttempt
  expr: rate(rls_bypass_count[5m]) > 0
  for: 1m
- alert: PromptCacheHitRateLow
  expr: prompt_cache_hit_rate < 0.75
  for: 1h
```

## 4. 灾难恢复（12 分钟）

### 4.1 断网 4h 验证

- 演示 nightly E2E：`infra/nightly/offline-e2e-results.json` 连续 3 日绿
- **机制**：Mac mini 本地 PG 副本 + CRDT 冲突解析，断网期间门店收银不受影响

### 4.2 数据库备份

- 每日凌晨 3:00 `pg_dump` → 腾讯云 COS（保留 90 天）
- 每周日 `pg_basebackup` 物理备份（保留 12 周）
- 演示 `scripts/restore_from_backup.sh` 回滚到任意时间点

### 4.3 服务降级

- 演示：如果 `tx-brain` 宕机 → `tx-agent` 自动 fallback 到规则引擎（D4 系列已支持）
- 演示：Claude API 不可用 → 边缘 Core ML 接管（延迟从 2s 降到 200ms）

## 5. 扩展性（8 分钟）

### 5.1 横向扩展

- 演示 K8s deployment：每个微服务独立 replicas + HPA
- 演示 Helm chart：生产 / 灰度 / 演示环境差异化配置

### 5.2 插件化架构

- 演示 `shared/adapters/` 10 个 Adapter：替换平台厂商只需替换 adapter 实现
- 演示 `shared/skill_registry/`：新 Agent Skill 通过注册即可被 Master Agent 调度

### 5.3 多租户隔离

- 演示同一 PostgreSQL 实例 100+ 租户，RLS + 连接池复用
- 成本：每 1000 门店预估月度基础设施 ¥8000（含 Claude API）

## Q&A 准备（技术向）

### Q1: "PostgreSQL 扛不住 200 桌并发？"
A: 主库 8C16G 实测 QPS 2000+；读走 read replica + 物化视图，写走主库。

### Q2: "Claude API 成本？"
A: Prompt Cache ≥ 75% 命中后月度 ¥8000；Haiku 轻量任务走边缘。有月度上限 ¥12k 硬阈值。

### Q3: "怎么保证 RLS 不被绕过？"
A: CI 门禁：所有新 migration 必须通过 `check_rls_policies.py`；另有 nightly 渗透测试。

### Q4: "事件总线吞吐？"
A: PG LISTEN/NOTIFY 同步 + Redis Streams 异步双写，每秒 10k 事件不是瓶颈。

### Q5: "如果 Mac mini 坏了？"
A: 门店配双 Mac mini 互备 + 云端 PG 是主源；Mac mini 只是边缘加速。

---

## 演示环境

同 01 脚本。重点展示：
- `web-admin/observability` 页面（Grafana embed）
- `scripts/demo_go_no_go.py` 输出（10 项 Week 8 门槛）
- PG RLS 实证：切换 tenant 后看到数据量归零
