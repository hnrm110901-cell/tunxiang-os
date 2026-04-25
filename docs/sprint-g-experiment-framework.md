# Sprint G — 实验框架（Experiment Framework）

> Wave 4 Sprint G 落地 v278 + tx-analytics/experiment/ 模块。本文档是接入指南与架构总览。

---

## 1. 为什么需要实验框架（与 flags/ 的区别）

`flags/` 系统管"开关"——某功能要不要开（all-on / all-off / 部分租户开）。
`experiment/` 系统管"对照试验"——开了之后效果怎样、新版 vs 旧版谁赢、出问题自动回退。

| 对比维度 | flags/ | experiment/ |
|---------|--------|-------------|
| 输出 | 单一布尔/字符串 | 多变体桶（control/variant_a/variant_b...） |
| 评价 | 无（人肉看 Grafana） | Welch's t-test 自动出显著性 |
| 失败止损 | 人工关 flag | 熔断器自动关（核心指标跌幅 > 阈值） |
| 主体 | 通常租户/门店级 | 用户/设备/桌台级（粒度更细） |
| 可重放 | 否 | 是（同 seed + subject_id 永远同桶） |

两系统并存，互不替代。flag 是"灰度",experiment 是"灰度内的科学对照"。

---

## 2. 架构图（文字版）

```
                       ┌─────────────────────────────────────┐
                       │  HTTP 客户端（POS / KDS / Web）       │
                       └────────────┬────────────────────────┘
                                    │ POST /api/v1/experiments/{key}/bucket
                                    ▼
                       ┌─────────────────────────────────────┐
                       │  experiment_routes.py（5 端点）       │
                       │  • tenant_id 三方校验                 │
                       │  • reset 需 ADMIN role                │
                       └────────────┬────────────────────────┘
                                    │
                ┌───────────────────┼───────────────────┐
                ▼                   ▼                   ▼
       ┌────────────────┐  ┌────────────────┐  ┌────────────────┐
       │ Orchestrator   │  │ Dashboard      │  │ CircuitBreaker │
       │ G2             │  │ G3             │  │ G4             │
       │                │  │                │  │                │
       │ get_bucket():  │  │ summarize():   │  │ evaluate():    │
       │ ① def 缓存       │  │ ① 拉变体主体     │  │ ① 拉指标快照    │
       │ ② 熔断守卫       │  │ ② 拉指标值      │  │ ② 计算跌幅     │
       │ ③ assign_bucket │  │ ③ welch_t_test │  │ ③ 跨阈值则 trip│
       │ ④ idempotent   │  │   per pair     │  │                │
       │   expose       │  │                │  │ trip():        │
       │ ⑤ emit EXPOSED │  │                │  │ • disable_def  │
       └────────┬───────┘  └────────┬───────┘  │ • flag 文件     │
                │                   │          │ • emit TRIPPED │
                │                   │          └────────┬───────┘
                ▼                   ▼                   ▼
       ┌─────────────────────────────────────────────────────┐
       │  G1 assignment.assign_bucket — 纯函数 SHA-256 分桶    │
       └─────────────────────────────────────────────────────┘
                │                   │                   │
                ▼                   ▼                   ▼
       ┌─────────────────────────────────────────────────────┐
       │  PostgreSQL（v278）                                   │
       │   experiment_definitions  experiment_exposures        │
       │     RLS USING + WITH CHECK 双向对称                   │
       │     UNIQUE(tenant, exp_key, subject_type, subject_id) │
       └─────────────────────────────────────────────────────┘
                │
                ▼
       ┌─────────────────────────────────────────────────────┐
       │  shared/events 事件总线                               │
       │   EXPERIMENT.EXPOSED                                  │
       │   EXPERIMENT.CIRCUIT_BREAKER_TRIPPED                  │
       │   EXPERIMENT.CIRCUIT_BREAKER_RESET                    │
       └─────────────────────────────────────────────────────┘
```

---

## 3. 模块清单

| 文件 | 职责 | 行数 | 测试 |
|------|------|------|------|
| `experiment/assignment.py` | G1 纯函数分桶 | ~150 | 8 |
| `experiment/orchestrator.py` | G2 判桶 + idempotent 暴露 | ~330 | 7 |
| `experiment/metrics.py` | G3 Welch's t-test | ~210 | 7 |
| `experiment/dashboard.py` | G3 跨变体显著性汇总 | ~190 | （由 routes 测试覆盖）|
| `experiment/circuit_breaker.py` | G4 熔断评估 + 落盘 | ~280 | 7 |
| `api/experiment_routes.py` | HTTP 5 端点 | ~310 | 7 |

---

## 4. 数据库（v278）

### 4.1 experiment_definitions

```sql
id UUID PK
tenant_id UUID NOT NULL
experiment_key TEXT NOT NULL
description TEXT NULL
variants JSONB NOT NULL           -- [{"name":"control","weight":5000},{"name":"variant_a","weight":5000}]
guardrail_metrics JSONB NOT NULL  -- ["payment_success_rate","p99_ms","gmv_per_minute"]
circuit_breaker_threshold_pct NUMERIC(6,2) DEFAULT -20.0
enabled BOOLEAN DEFAULT TRUE
started_at / ended_at / created_at / updated_at / is_deleted

UNIQUE INDEX (tenant_id, experiment_key) WHERE is_deleted=FALSE
RLS POLICY USING + WITH CHECK
```

### 4.2 experiment_exposures

```sql
id UUID PK
tenant_id UUID NOT NULL
store_id UUID NULL
experiment_key TEXT NOT NULL
subject_type TEXT NOT NULL       -- "user" | "device" | "store" | "table"
subject_id TEXT NOT NULL
bucket TEXT NOT NULL              -- "control" | "variant_a" | ...
bucket_hash_seed TEXT NOT NULL    -- 用于可重放分桶
exposed_at TIMESTAMPTZ DEFAULT NOW()
context JSONB NULL                -- {route, platform, app_version, ...}

UNIQUE (tenant_id, experiment_key, subject_type, subject_id)
INDEX (tenant_id, experiment_key, exposed_at DESC)
RLS POLICY USING + WITH CHECK
```

---

## 5. 接入指南：把现有 flag 接进实验

### 5.1 决策树
- **只想知道开 vs 关**：用 flags/，不需要 experiment
- **想测两个新 UI 哪个转化率高**：用 experiment（control + variant_a）
- **想三方对比 + 显著性**：用 experiment 多变体

### 5.2 三步接入

**Step 1：在 experiment_definitions 表里建实验**

```sql
INSERT INTO experiment_definitions (
  tenant_id, experiment_key, variants, guardrail_metrics,
  circuit_breaker_threshold_pct, enabled, started_at
) VALUES (
  'tenant-czyz',
  'checkout.button_color',
  '[{"name":"control","weight":5000},{"name":"variant_a","weight":5000}]'::jsonb,
  '["payment_success_rate","checkout_p99_ms"]'::jsonb,
  -20.0,
  TRUE,
  NOW()
);
```

**Step 2：业务路径调 orchestrator**

```python
result = await orchestrator.get_bucket(
    tenant_id=tenant_id,
    experiment_key="checkout.button_color",
    subject=ExperimentSubject(subject_type="user", subject_id=str(user_id)),
    store_id=str(store_id),
    context={"route": "/checkout", "app_version": "2.4.1"},
)

if result.bucket == "variant_a":
    button_color = "tuxiang-orange"
else:
    button_color = "tuxiang-blue"
```

**Step 3：仪表板看效果**

```bash
GET /api/v1/experiments/checkout.button_color/dashboard?metric=payment_success_rate
```

### 5.3 接入清单（候选 flag → experiment 迁移）

下列现有 flag 适合升级为 experiment（按 ROI 排序）：

| 现有 flag | experiment_key 建议 | 监控指标 | 阈值 |
|----------|---------------------|---------|------|
| `growth.silent_recall.enable` | `growth.silent_recall.template_v2` | repurchase_rate_30d | -15% |
| `agent.discount_guard.auto_execute` | `agent.discount_guard.severity_v3` | discount_leak_rate | -20% |
| `trade.voice_order.enable` | `trade.voice_order.asr_engine` | order_completion_rate | -10% |
| `member.clv_engine.enable` | `member.clv_engine.weights_v2` | clv_estimation_mae | +5%（注：劣化阈值） |
| `edge.coreml.dish_time_predict` | `edge.dish_time_predict.model_v2` | predict_mae_seconds | +20% |

注意：cargo culting 不可取，迁移前先确认目标指标稳定可观测。

---

## 6. 熔断阈值的"逐实验覆盖"

默认 -20% 是"sprint plan 决策点"——大多数实验适用。但是：

- **支付/收银相关**（影响 GMV）：建议设 -10%（更敏感）
- **UI 颜色 / icon**（无业务影响）：可设 -50%（更宽松）
- **Agent 决策路径**（高风险）：建议设 -5%（最严苛）

设置位置：`experiment_definitions.circuit_breaker_threshold_pct`。

---

## 7. 已知不足 / 后续 PR

- SQL Repository 实现：DefinitionRepo / ExposureRepo / MetricsRepository 接口已留，对应 SQL 实现需后续 PR 补
- main.py 挂载：3 个 Depends provider 默认抛 503，需运维在 lifespan 中注册具体实现
- 周期任务调度：CircuitBreakerEvaluator.evaluate 需要被 60 秒调一次，本 PR 未挂 background_task
- 大实验分页：dashboard 内部 fetch_metric 一次性传所有 subject_ids，实验主体超 10000 时需分块

---

## 8. 测试

```bash
# 全部 36 个 G 系测试
PYTHONPATH=. python3 -m pytest \
  services/tx-analytics/src/tests/test_experiment_assignment.py \
  services/tx-analytics/src/tests/test_experiment_metrics.py \
  services/tx-analytics/src/tests/test_experiment_orchestrator.py \
  services/tx-analytics/src/tests/test_circuit_breaker.py \
  services/tx-analytics/src/tests/test_experiment_routes.py -q
```
