# docs/service-health/monthly — 月度评分目录

**目的**：每月末汇总服务健康度综合评分（0-10），为季度战略校准提供量化依据。

---

## 命名规则

```
YYYY-MM.md
```

示例：`2026-05.md`、`2026-06.md`

---

## 月度评分模板

```markdown
# 服务健康度月度评分 — YYYY-MM

**汇总日期**：YYYY-MM-DD
**汇总人**：<name>
**基础数据**：[YYYY-WXX.md](../YYYY-WXX.md)（本月最后一周扫描）

---

## 综合评分表

| 服务名 | 健康分 (0-10) | 趋势 | 主要风险项 | 负责人 |
|---|---|---|---|---|
| gateway |   | → / ↑ / ↓ |   |   |
| tx-trade |   |   |   |   |
| tx-supply |   |   |   |   |
| tx-finance |   |   |   |   |
| tx-member |   |   |   |   |
| tx-org |   |   |   |   |
| tx-ops |   |   |   |   |
| tx-menu |   |   |   |   |
| tx-growth |   |   |   |   |
| tx-analytics |   |   |   |   |
| tx-brain |   |   |   |   |
| tx-intel |   |   |   |   |
| tx-agent |   |   |   |   |
| tx-civic |   |   |   |   |
| tx-pay |   |   |   |   |
| tx-expense |   |   |   |   |
| tx-forge |   |   |   |   |
| tx-devforge |   |   |   |   |
| tx-predict |   |   |   |   |
| mcp-server |   |   |   |   |

---

## 本月重点动作

### 健康分 <6 服务（强制跟进）

| 服务 | 分数 | 根因 | 修复计划 | 截止 |
|---|---|---|---|---|
|   |   |   |   |   |

### Silent failure ratchet 检查

| 服务 | 上月 | 本月 | delta | 说明 |
|---|---|---|---|---|
|   |   |   |   |   |

---

## 下月改善目标

- [ ] 服务 X：silent_failure_count 从 N 降到 M（issue #NNN）
- [ ] 服务 Y：Tier 1 issue backlog 清零

---

## 评分 rubric 参考

| 分档 | 含义 |
|---|---|
| 9-10 | 无 silent failure，测试覆盖 >80%，P99<200ms，0 Tier 1 未修 issue |
| 7-8 | silent failure <5，Tier 1 均有 follow-up issue 跟进 |
| 5-6 | silent failure 5-15，有 Tier 1 issue 未 fix |
| 3-4 | silent failure >15，Tier 1 issue backlog 积压 |
| 0-2 | 重大事故 / 数据丢失风险 / Tier 1 路径不稳定 |
```

---

## 索引

| 月份 | 文件 | 均分 |
|---|---|---|
| （新记录头插） |   |   |
