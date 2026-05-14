# doc_number Fallback Runbook

> 适用：tx-supply 服务 / 5 域 6 catch 现场 (issue #592 / PR #586 §19 round-2 follow-up)
> 维护者：供应链域 + SRE on-call
> 最后更新：2026-05-14（PR-03D 落盘）

## 1. 背景

`doc_number` 是收货单/入库单/出库单/盘点单/调拨单/采购单的人类可读单号
（如 `RCV-20260514-0001`），由 `doc_number_service.generate()` 通过 advisory_lock
+ doc_number_rules 表 + 顺序号生成器构建。

**辅助标识 graceful degradation 契约**（参考 `feedback_graceful_degradation_pattern.md`）：
- doc_number 是辅助标识，**infra 失败不应阻塞** Tier 1 业务（毛利底线 / 食安 / 客户体验）。
- 任何 advisory_lock / 顺序号 / 模板表 / network 异常 → `except Exception` 兜底
  日志 + Counter 上报 + 落 `doc_number=NULL`，业务继续进行。
- `DocNumberError`（预期 sentinel，例如模板未配置）→ 仅 structlog warn，**不计入** Counter
  以避免预期问题触发 PagerDuty。

## 2. 6 catch 现场清单

| service 标签 | doc_type 标签 | 文件 | 函数 |
|---|---|---|---|
| `inventory_io` | `inventory_io` | `services/tx-supply/src/services/inventory_io.py` | `receive_stock` |
| `inventory_io` | `waste` | `services/tx-supply/src/services/inventory_io.py` | `issue_stock`（仅 reason=waste 分支） |
| `inventory_io` | `adjustment` | `services/tx-supply/src/services/inventory_io.py` | `adjust_stock` |
| `receiving_v2` | `receiving` | `services/tx-supply/src/services/receiving_v2_service.py` | `create_receiving_order` |
| `stocktake` | `stocktake` | `services/tx-supply/src/services/stocktake_service.py` | `create_stocktake` |
| `purchase_order` | `purchase_order` | `services/tx-supply/src/api/purchase_order_routes.py` | `create_purchase_order` |

## 3. 指标

### Prometheus

```
# HELP tx_supply_doc_number_fallback_null_count doc_number infra 异常 graceful degradation 落 NULL 次数
# TYPE tx_supply_doc_number_fallback_null_count counter
tx_supply_doc_number_fallback_null_count{service="inventory_io", doc_type="waste"} 0
tx_supply_doc_number_fallback_null_count{service="receiving_v2", doc_type="receiving"} 0
... (6 个 service × doc_type 组合)
```

- **暴露端点**：tx-supply 的 `/metrics` (由 `prometheus_fastapi_instrumentator` 在 main.py 注册)
- **scrape interval**：建议 30s (与其它 service 一致)
- **保留**：30 天 (Prometheus 默认即可)

### Admin API（仅 on-pod sanity check + 仪表板，不替代 Prometheus）

```
GET /api/v1/doc-number/fallback-stats
Headers: X-Internal-Role: admin   # 或 ops（gateway proxy.py L142 注入；客户端不可伪造）
```

**安全注意**：用 `X-Internal-Role` 而非 `X-Role`。后者不在 gateway `_STRIP` 列表，客户端
绕过 gateway 直接打 tx-supply:8006 时可伪造身份。`X-Internal-Role` 在 _STRIP 内
（gateway/src/proxy.py L130）+ 仅 gateway 注入 trusted role（L142）→ 不可伪造。

Response:
```json
{
  "ok": true,
  "data": {
    "total": 0,
    "by_service": {},
    "by_doc_type": {},
    "by_combo": [],
    "note": "进程级 Counter snapshot（pod 重启清零）..."
  }
}
```

- **仅 admin/ops 角色可见**（跨租户聚合数据，会泄漏运营信息给普通用户）
- **进程级**：pod 重启后归零；历史趋势必须查 Prometheus

### 仪表板（web-admin）

`/supply/doc-number-rules` — Ant Design 表 + 3 卡片视图：
- 累计 fallback 次数（进程级，0 绿 / 1-9 黄 / ≥10 红）
- 按 service 维度分组
- 按 doc_type 维度分组
- 完整 (service, doc_type) 明细表

## 4. 告警规则

### Prometheus alerting rule（建议落 `infra/prometheus/alerts/tx-supply.yml`）

```yaml
groups:
- name: tx_supply_doc_number
  interval: 30s
  rules:
  - alert: DocNumberFallbackBurst
    expr: |
      sum(rate(tx_supply_doc_number_fallback_null_count[5m])) * 60 * 5 > 10
    for: 1m
    labels:
      severity: critical
      service: tx-supply
      pager: oncall-supply
    annotations:
      summary: "tx-supply doc_number fallback 5min 内 > 10 次"
      description: |
        过去 5min 内 tx_supply_doc_number_fallback_null_count 增加超过 10 次，
        意味着 advisory_lock / 顺序号表 / doc_number_rules 表 / network 有 infra 异常。
        业务未阻塞但 doc_number=NULL 单据正在累积，财务对账侧会暴露。
        Runbook: docs/operations/doc-number-fallback-runbook.md
      service_breakdown: |
        {{ range query "sum by(service, doc_type) (increase(tx_supply_doc_number_fallback_null_count[5m]))" }}
          - {{ .Labels.service }} / {{ .Labels.doc_type }}: {{ .Value }}
        {{ end }}

  - alert: DocNumberFallbackSlow
    expr: |
      sum(rate(tx_supply_doc_number_fallback_null_count[15m])) * 60 * 15 > 0
    for: 15m
    labels:
      severity: warning
      service: tx-supply
    annotations:
      summary: "tx-supply doc_number fallback 持续累积"
      description: |
        15min 内有至少 1 次 doc_number infra fallback — 非紧急但有漂移迹象。
        建议下班前清单 + 看 service/doc_type 分布定位短板。
```

## 5. On-call 处置流程

### Step 1 — 收到 `DocNumberFallbackBurst` PagerDuty

1. 立即看 `/supply/doc-number-rules` 仪表板 → 哪个 service / doc_type 在涨？
2. 看 tx-supply pod 的 structlog → 抓 `doc_number_generate_failed_fallback_null` 警告，
   `error` 字段会带具体异常类型（e.g. `OperationalError`, `TimeoutError`, `asyncpg.PostgresError`）。
3. 看 PG 主从状态：`SELECT pg_is_in_recovery();` + replica lag。
4. 看 advisory_lock 持有者：
   ```sql
   SELECT pid, locktype, mode, granted, query_start, query
   FROM pg_locks JOIN pg_stat_activity USING(pid)
   WHERE locktype = 'advisory';
   ```

### Step 2 — 已识别 root cause

| Root cause | 处置 |
|---|---|
| PG 主从切换中（pg_is_in_recovery=t 久未恢复） | 等 standby 提升成 primary；fallback 期间 doc_number=NULL 累积可接受，业务不阻塞 |
| advisory_lock 持有者卡死 | `SELECT pg_cancel_backend(<pid>);` 释放；考虑切短 tx 避免长事务 |
| doc_number_rules 表损坏 / 数据被误删 | 从 backup 恢复 + alembic 检查 v418 migration |
| 顺序号表 max(seq) 跳号 | 见 issue #580 补偿流程 |
| network partition | 等恢复；fallback 期间业务继续 |

### Step 3 — fallback 期间 NULL 单据补单号

> **风险警告**：目前**没有**自动批量补单号工具（YAGNI 拒绝 — issue #592 提到但需创始人决策）。
> Excel 手工补 + DBA 直接 UPDATE 仍是 5/14 时点最安全的选项。

人工补单号 SQL 模板（管理员账号执行，**必须先确认目标范围**）：
```sql
-- ⚠ 必须 DRY-RUN：先看哪些行受影响
SELECT id, created_at, tenant_id, store_id
FROM ingredient_transactions
WHERE doc_number IS NULL
  AND created_at >= '2026-05-15 00:00:00+08'
  AND created_at <  '2026-05-15 06:00:00+08'
ORDER BY created_at;

-- 确认后再 UPDATE（手工赋号或调 doc_number_service 重生成）
```

### Step 4 — 复盘

- 告警事件 root cause 落到 `docs/incidents/YYYY-MM-DD-doc-number-fallback.md`
- 若是新型 infra 失败模式，回到 `feedback_graceful_degradation_pattern.md` 评估是否需要
  扩 fail-open 覆盖（例如新加 try/except 包裹路径）。

## 6. 测试与回归

- **Tier 1 邻接测试**：`services/tx-supply/tests/test_doc_number_fallback_tier1.py`
  - 6 catch 现场源码 regex audit（防 future regression 漏 inc）
  - record 调用必须在 `except Exception` arm（不在 DocNumberError arm）
  - Counter inc 行为 + fail-open 契约
  - admin API 返回结构 + auth gate（无 X-Internal-Role / 错误 role 拒绝；admin/ops 大小写不敏感放行）

- **触发 tier1-gate**：文件名含 `*tier1*` 即 `.github/workflows/tier1-gate.yml` 自动跑

## 7. 关联

- 引入 PR：PR-03D（本 PR）
- 引出原因：PR #586 (PR-03B Wave1) §19 round-2 reviewer 建议
- 上游 issue：[#592](https://github.com/hnrm110901-cell/tunxiang-os/issues/592)
- graceful degradation 契约：`~/.claude/projects/-Users-lichun/memory/feedback_graceful_degradation_pattern.md`
- doc_number 设计：`services/tx-supply/src/services/doc_number_service.py` + 系统模板见 v418 migration
- 邻接 follow-up：
  - [#599](https://github.com/hnrm110901-cell/tunxiang-os/issues/599) DocNumberError 4 处补 `exc_info=True`
  - [#580](https://github.com/hnrm110901-cell/tunxiang-os/issues/580) 顺序号跳号补偿
