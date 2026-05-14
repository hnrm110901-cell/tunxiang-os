# ADR 0002 — `auto_deduction.deduct_for_order` 跨 dish 行锁 ABBA 死锁防护

| 字段 | 值 |
|------|-----|
| 状态 | ACCEPTED — 已实施（PR #567 `7c4ee9cd`），追溯文档化 |
| 日期 | 2026-05-14 |
| 决策者 | Claude Code（architect agent 评审，issue #549 已 CLOSED 2026-05-13T13:45Z） |
| 提议者 | PR #547 §19 reviewer P1#1（Issue #549） |
| 关联 PR | #547（`6564b915`，PR-B `deduct_for_dish` 内部 sorted）+ #567（`7c4ee9cd`，本 ADR 实施） |
| 关联 Issue | [#549](https://github.com/hnrm110901-cell/tunxiang-os/issues/549) CLOSED |
| 上游审计 | `docs/security/tier1-row-lock-audit-2026-05.md` §4.3 + §8 + §11 |
| 范本参考 | `services/tx-member/src/services/stored_value_service.py:919`（`transfer` 2 卡同锁排序） |

## 1. 背景与问题

### 1.1 触发链

PR #547（tx-supply row-lock fix，PR-B）合并时，§19 reviewer P1#1 提出：

> `deduct_for_dish` 内部已按 `ingredient_id` 升序锁单菜 BOM 行（防同菜内多 ingredient ABBA），但 `deduct_for_order` 跨 dish 锁顺序无防护——订单含多 dish 共享同 ingredient 仍可 ABBA 死锁。

落 Issue #549，归 §17 桌台对齐之外的独立 architect 议题（audit doc §11.1 表注：`auto_deduction` 与 §17 无关）。PR #567（`7c4ee9cd`）实施方案 B 后 5/13 13:45Z 关闭 issue。本 ADR 为决策追溯文档化，固化方案选型理由 + 候选对比，供未来类似 row-lock 议题参考。

### 1.2 反例（PR #547 §19 reviewer 原文）

```
订单 A = [dish1(X, Y), dish2(Z)]
  锁序：dish1 内部 sorted X→Y → dish2 锁 Z
  实际：X → Y → Z

订单 B = [dish2(Z), dish1(X, Y)]
  锁序：dish2 优先锁 Z → dish1 内部 sorted X→Y
  实际：Z → X → Y

并发：A 持 X+Y 等 Z；B 持 Z 等 X → 经典 ABBA 死锁
```

PG 死锁检测器会回滚其中一方（`deadlock_timeout` 默认 1s），但：

1. **食安 / 毛利底线硬约束遭受秒级阻塞**（200 桌并发场景累积）
2. **被牺牲方的订单完成事件需要 retry**——retry 风暴在尖峰可加剧 contention
3. **日志噪声**——Postgres `ERROR: deadlock detected` 告警

### 1.3 PR #547 已修范围（不含本 ADR）

PR #547 `services/tx-supply/src/services/auto_deduction.py` 仅在 `deduct_for_dish` **内部** sorted BOM 行：

```python
sorted_bom_lines.sort(key=lambda x: str(x["ingredient_id"]))
```

这只防御**单菜 BOM 内多 ingredient ABBA**（红烧鱼 = 鱼+葱姜蒜+酱油，3 ingredient 内部排序）。**跨 dish 维度无防御**——本 ADR 解决该 gap。

## 2. 现状分析

### 2.1 调用链

```
订单完成事件
  → tx-trade settle_order / payment_saga._complete_order
    → tx-supply HTTP /api/deduction/order/{order_id}
      → deduct_for_order(order_id, order_items, store_id, tenant_id, db)
        → for item in order_items:
            → deduct_for_dish(dish_id, quantity, ...)
              → for line in sorted(bom_lines, key=ingredient_id):
                  → SELECT Ingredient ... FOR UPDATE
                  → UPDATE ingredient.current_quantity -= consume_qty
                  → INSERT IngredientTransaction(type=consume)
```

### 2.2 关键代码定位（修复前 vs 修复后）

**`auto_deduction.deduct_for_dish` 内部排序（PR #547 已修）**：

```python
# Tier 1 行锁防 ABBA 死锁（audit doc §4.3 P0）...
sorted_bom_lines.sort(key=lambda x: str(x["ingredient_id"]))
```

**`auto_deduction.deduct_for_order`（PR #567 实施方案 B，L252-292）**：

```python
async with db.begin_nested():
    await _set_tenant(db, tenant_id)
    bom_cache: dict[uuid.UUID, list[dict[str, Any]]] = {}
    all_ing_ids: set[uuid.UUID] = set()
    for item in order_items:
        # ... 调 _get_bom_for_dish 聚合 + 去重 ingredient_id
        for line in bom_cache[dish_uuid]:
            all_ing_ids.add(uuid.UUID(ing_id_str))

    for ing_uuid in sorted(all_ing_ids, key=str):
        await db.execute(
            select(Ingredient.id)
            .where(Ingredient.id == ing_uuid)
            ...
            .with_for_update()
        )

    for item in order_items:
        # 原有 deduct_for_dish 业务循环（内部 sorted 同事务 reentrant 无害）
        ...
```

### 2.3 caller 链审计

`grep -r deduct_for_order` 显示仅 `services/tx-supply/src/api/deduction_routes.py` 单 caller，路径为订单完成事件触发的批量扣料。无其他业务路径需要"快速单菜直接扣"的旁路。

`deduct_for_dish` 单 dish 直接路径仍被 `test_deduct_for_dish_internal_sort_still_works_when_called_directly`（`test_auto_deduction_row_lock_tier1.py:425-489`）守护——保证 `deduct_for_dish` 内部 sorted 是 defense-in-depth，未来若新增非 `deduct_for_order` 路径 caller 仍安全。

## 3. 候选方案对比

### 方案 A — 预聚合 SELECT IN FOR UPDATE 单语句锁集

**实现伪代码**：

```python
async with db.begin_nested():
    # 聚合所有 ingredient_id
    all_ing_ids = sorted({...}, key=str)

    # 单语句 SELECT IN FOR UPDATE 一次锁全部
    await db.execute(
        select(Ingredient.id)
        .where(Ingredient.id.in_(all_ing_ids))
        .where(Ingredient.tenant_id == tenant_uuid)
        ...
        .with_for_update()
    )

    for item in order_items:
        ...  # deduct_for_dish 业务循环
```

**优点**：
- N+1 round trip 消除——15 ingredient 从 15 次 SELECT 压到 1 次
- 网络延迟优势在跨 AZ 部署中更明显

**缺点**：
- **PG `SELECT IN FOR UPDATE` 锁获取顺序不保证按 IN 列表顺序**——PG 会按 query plan（index scan / bitmap scan）决定，实际可能按物理行顺序
- 仍需依赖外部协议（"全仓约定: 锁 ingredient 永远走预聚合 SELECT IN"）才能跨 service / 跨业务路径 ABBA 安全；任何旁路单条 SELECT FOR UPDATE 都会破坏防御
- 锁持有时间从聚合点开始计时直到 nested transaction commit——比逐条更长（虽然总 elapsed 更短）

**ABBA 防护强度**：⚠️ 中等（依赖 PG 行锁获取顺序未文档化的实现细节）

### 方案 B — collect-then-lock 升序逐条 SELECT FOR UPDATE（**已实施**）

**实现伪代码**：见 §2.2 修复后代码片段。

**优点**：
- **ABBA 防护强度最强**——锁顺序显式按 `sorted(key=str)`，与 `deduct_for_dish` 内部 sorted key 严格一致
- **范本一致性**——与 `stored_value_service.transfer` `sorted([from_card_id, to_card_id])` 概念完全对齐（参考 §4）
- **defense-in-depth 保留**——`deduct_for_dish` 内部 sorted 同事务 reentrant 无害，单 dish 直接路径仍有防御
- **可观测性好**——每个 SELECT 是独立 query，PG 慢日志 / pg_locks 视图可逐行追踪

**缺点**：
- N+1 round trip——15 ingredient 需 15 次 SELECT FOR UPDATE（本地 PG 每次 ~0.3-0.8ms，本地 socket 通常 < 1ms）
- 锁持有时间最长——从第一把锁到 nested transaction commit

**ABBA 防护强度**：✅ 强（与全仓 baseline `stored_value_service.transfer` 同模式）

**性能模型**：
- 单订单 5 dish × 平均 3 ingredient = 15 ingredient_id（去重后可能 10 个）
- 预锁阶段：10 次 SELECT FOR UPDATE × ~0.5ms = ~5ms 额外延迟
- 业务循环：deduct_for_dish 内 SELECT FOR UPDATE 同事务 reentrant，PG 不再获取锁，仅 catalog 查询 ~0.2ms × 15 = ~3ms
- **总额外延迟约 5-8ms**，远低于 P99 < 200ms Tier 1 门槛（CLAUDE.md §22）

### 方案 C — SAVEPOINT 隔离每 dish / SERIALIZABLE 隔离级别 / NOWAIT 重试

**C.1 SAVEPOINT 隔离每 dish**：每 dish 独立 SAVEPOINT，死锁时回滚单 dish 重试
- **驳回**：SAVEPOINT 不解决跨 dish ABBA——仍持有跨 SAVEPOINT 的锁；只能减少回滚范围，不能避免 deadlock

**C.2 SERIALIZABLE 隔离级别**：所有 tx-supply 写路径升级到 SERIALIZABLE
- **驳回**：(1) 全局影响——所有 tx-supply 服务路径都受影响，blast radius 失控 (2) SERIALIZABLE 在 PG 用 SSI（Serializable Snapshot Isolation）+ predicate locks，仍会以"serialization_failure"中断；只是把 deadlock 错误换皮 (3) 应用层需配对 retry 逻辑——比方案 B 复杂

**C.3 SELECT FOR UPDATE NOWAIT + 重试循环**：单条 SELECT 加 NOWAIT，遇 conflict 即抛错，应用层指数退避重试
- **驳回**：(1) 200 桌并发尖峰下 retry 风暴可能导致 thundering herd (2) 食安 / 毛利底线扣料失败需告警人工介入，retry 隐藏故障 (3) 用户感知到的延迟反而比方案 B 高

**结论**：方案 C 各子选项均不优于方案 B，不再单独评估。

### 3.1 推荐：方案 B（已实施）

按 ABBA 防护强度 + 范本一致性 + 可观测性 3 个维度，方案 B 全胜。N+1 性能代价在 200 桌并发本地 PG 场景下不显著（~5ms），且为可观测性 + 显式锁顺序换取的代价合理。

## 4. baseline 范本对照（`stored_value_service.transfer`）

`services/tx-member/src/services/stored_value_service.py:896-1014`：

```python
async def transfer(
    self, db, from_card_id, to_card_id, amount_fen, tenant_id, ...
):
    # 按 UUID 固定加锁顺序防死锁
    id_a, id_b = sorted([from_card_id, to_card_id])

    result_a = await db.execute(
        select(StoredValueCard)
        .where(StoredValueCard.id == id_a, ...)
        .with_for_update()
    )
    card_a = result_a.scalar_one_or_none()
    ...

    result_b = await db.execute(
        select(StoredValueCard)
        .where(StoredValueCard.id == id_b, ...)
        .with_for_update()
    )
    card_b = result_b.scalar_one_or_none()
    ...
```

### 4.1 概念一致性

| 维度 | `stored_value_service.transfer` | `auto_deduction.deduct_for_order`（方案 B） |
|------|--------------------------------|-------------------------------------------|
| 锁资源 | 2 张卡 | N 个 ingredient（动态聚合） |
| 排序 key | `sorted([uuid_a, uuid_b])`（Python 默认 UUID 比较） | `sorted(all_ing_ids, key=str)` |
| 锁形式 | 2 次独立 `.with_for_update()` SELECT | N 次独立 `.with_for_update()` SELECT |
| defense-in-depth | N/A（transfer 是唯一路径） | `deduct_for_dish` 内部 sorted 守护单 dish 直接路径 |

### 4.2 排序 key 差异说明

`stored_value_service.transfer` 用 Python 默认 `sorted([uuid_a, uuid_b])`，依赖 `uuid.UUID.__lt__` 按 128-bit 整数比较；本方案用 `sorted(key=str)` 按字符串字典序比较。**两者对同一组 UUID 输入的排序结果一致**（UUID hex 表达式字典序 = 128-bit 整数序），但 `key=str` 更显式、跨 DB / 跨语言一致性更好（Postgres `ORDER BY uuid_col::text` 与 Python `sorted(key=str)` 行为一致）。

`deduct_for_dish` 内部已用 `key=lambda x: str(x["ingredient_id"])`；本 ADR 方案 B 用 `sorted(all_ing_ids, key=str)`——**两处 key 严格一致**，否则一致性破坏防御失效。

## 5. 推荐方案

**方案 B（PR #567 `7c4ee9cd` 已实施）**——理由：

1. **ABBA 防护强度最强**——显式锁顺序、不依赖 PG 实现细节
2. **范本一致**——与 `stored_value_service.transfer` 同模式，全仓 row-lock 心智模型统一
3. **defense-in-depth 保留**——`deduct_for_dish` 内部 sorted 仍生效，未来旁路 caller 安全
4. **性能可接受**——~5ms 额外延迟 << Tier 1 P99 200ms 门槛
5. **可观测性最好**——每锁独立 query，pg_locks / slow log 可逐行追踪

### 5.1 风险声明

| 风险 | 缓解 |
|------|------|
| BOM cache 在 begin_nested 内构建，与外层事务隔离边界不清 | `_get_bom_for_dish` 是只读 SELECT，无副作用；nested rollback 不影响 cache 一致性 |
| 大订单（如 50 dish × 5 ing = 250 unique ingredient）锁持有时间长 | 单门店日常订单 ≤ 10 dish；宴席场景另起 PR 评估 batch size 阈值 |
| 跨 dish 锁先于业务校验——若某 dish 因 BOM 丢失被 skip，预锁仍占用 | broken-row 行为与 `deduct_for_dish` 完全一致——可接受，BOM 缺失是低频运维事件 |
| 测试 mock 的 `begin_nested` 不验证真 PG 死锁回滚行为 | follow-up：补 pytest-postgresql 真实并发 e2e 测（issue #535 同期落地） |

## 6. 测试需求

### 6.1 已实现（`tests/test_auto_deduction_row_lock_tier1.py`）

| 测试 | 覆盖 | 行号 |
|------|------|------|
| `test_deduct_for_order_pre_locks_all_ingredients_in_id_ascending_order` | 跨 dish 倒序 BOM 输入仍按 sorted prelock | L255-337 |
| `test_deduct_for_order_shared_ingredient_dedup_locked_once_in_prelock` | 共享 ingredient 去重 + 跨 dish 累加扣减正确 | L339-422 |
| `test_deduct_for_dish_internal_sort_still_works_when_called_directly` | defense-in-depth：单 dish 路径内部 sorted 不回归 | L424-489 |

### 6.2 待补（follow-up，本 PR 可不强制）

| 测试 | 必要性 | 备注 |
|------|--------|------|
| `test_deduct_for_order_real_pg_concurrent_no_deadlock` | 高 | pytest-postgresql + asyncio.gather 双订单 A=[X,Y]+[Z] / B=[Z]+[X,Y]，断言 50 轮无 deadlock 异常 |
| `test_deduct_for_order_perf_15_ingredients_p99` | 中 | 单订单 15 ingredient 预锁阶段 P99 < 50ms（远低于 Tier 1 200ms） |
| `test_deduct_for_order_broken_bom_row_skipped` | 低 | broken-row 行为与 deduct_for_dish 一致（已部分覆盖 `continue` 路径） |

## 7. 实施 PR 信息（已 ship）

**PR #567** `7c4ee9cd` [Tier1] fix(tx-supply): deduct_for_order 入口预聚合 + sorted 升序锁防跨 dish ABBA (#549)

- 修复实施：`services/tx-supply/src/services/auto_deduction.py` `deduct_for_order` 入口（~L252-292）
- 测试覆盖：`services/tx-supply/tests/test_auto_deduction_row_lock_tier1.py` L255-489 三用例
- Issue #549 closed: 2026-05-13T13:45:48Z

未来类似 row-lock 议题（如宴席 batch 扣料 / 跨服务联动扣料）应参考本 ADR 方案 B + 范本对照表 + 测试需求 §6.1 落地。

## 8. 监控 / 灰度（建议，未强制落地）

### 8.1 Prometheus metrics（建议新增）

```
tx_supply_deduct_for_order_prelock_duration_seconds{tenant_id, store_id}
  - 预锁阶段总耗时直方图 (bucket: 1ms, 5ms, 10ms, 50ms, 100ms)

tx_supply_deduct_for_order_unique_ingredients{tenant_id, store_id}
  - 单订单去重后 ingredient 数（gauge / histogram）

tx_supply_deduct_for_order_deadlock_total{tenant_id, store_id}
  - PG deadlock 计数（counter）— 修复后理论为 0，>0 即告警
```

### 8.2 structlog 字段（建议）

`deduct_for_order.start` / `.done` 已存在；建议补：

```python
log.info(
    "deduct_for_order.prelock",
    order_id=order_id,
    unique_ingredient_count=len(all_ing_ids),
    prelock_duration_ms=elapsed_ms,
)
```

### 8.3 灰度回滚阈值（200 桌并发场景，建议）

| 指标 | 阈值 | 动作 |
|------|------|------|
| `deduct_for_order` P99 延迟 | > 500ms | 告警，5% 流量暂停灰度 |
| `deduct_for_order` 错误率 | > 0.1% | 立即回滚 |
| PG deadlock counter | > 0 / 小时 | 告警（修复后理论为 0） |
| `deduct_for_order_unique_ingredients` P99 | > 100 | 告警，可能宴席批量订单需另立优化 |

## 9. 关联

- **PR #547**（`6564b915`，PR-B tx-supply row-lock fix）—— `deduct_for_dish` 内部 sorted 防御实施
- **PR #567**（`7c4ee9cd`，本 ADR 实施）—— `deduct_for_order` 预聚合 + sorted prelock，closes #549
- **Issue [#549](https://github.com/hnrm110901-cell/tunxiang-os/issues/549)** —— 本 ADR 主体（CLOSED 2026-05-13T13:45Z）
- **audit doc** `docs/security/tier1-row-lock-audit-2026-05.md` §4.3（tx-supply auto_deduction P0）+ §8.1（6-PR roadmap PR-B）+ §11.1（#549 与 §17 关系表注）
- **stored_value baseline** `services/tx-member/src/services/stored_value_service.py:896-1014`（`transfer` 2 卡同锁排序范本）
- **§17 决策跟踪表** audit doc §11（3 选择题 + §17-D follow-up PR 拆分预案，PR #628 落盘）
- **CLAUDE.md** §17 Tier 1 红线（食安合规 + 毛利底线硬约束）/ §19 reviewer 标准 / §20 Tier 1 测试标准

---

**ADR Lifecycle**: 本 ADR 为 PR #567 已实施决策的追溯文档化。如未来需调整方案（如压测后改方案 A 或方案 C 任一子方案），需起新 ADR (0003-*) 并标记本 ADR 状态为 SUPERSEDED。
