# PRD-11 sub-B.2 — IndexSplitProjector 架构设计

> **状态**: 设计阶段, 待 deep-interview + explicit-ask 第 30 例
> **作者**: architect agent (Opus, READ-ONLY) 2026-05-15 + sediment 2026-05-16
> **关联 PRs**: #665 sub-A (v434 share_split_rules) + #681 sub-B (v436 OrderItem.share_count + ITEMS_SETTLED emit)
> **Tier**: **Tier 1 邻接 explicit-ask 第 30 例** (触 `auto_deduction.deduct_for_order` 写 BOM 库存, 与 #547 PR-B tx-supply row-lock 同模式)
> **工时**: ~15-16h ≈ 2 工作日 (含 §19 reviewer + 200 桌并发 regression + explicit-ask 流程)

---

## 1. 业务背景与链路现状

PRD-11 全 scope: 多人合点 ("2 人共享 1 份酸菜鱼") 按比例转入库扣料 + cost attribution.

**当前链路状态** (PR #681 ship 后):

```
POS body {share_count: 4}
  → cashier_api.AddItemReq pydantic ge=1
  → cashier_engine.add_item
    → _check_share_split_rule (v434 校验 allow_share + max_share_count)
    → INSERT OrderItem.share_count=4 (v436)
  → settle_order
    → asyncio.create_task(emit_event(OrderEventType.ITEMS_SETTLED, payload={items: [{share_count: 4, ...}]}))

  ─── BREAK (无 projector 消费) ───  ← sub-B.2 任务

  → [sub-B.2 IndexSplitProjector 消费 ITEMS_SETTLED]
    → 对每个 item.share_count>1 构造 share_split={method:'EVEN', count:N}
    → auto_deduction.deduct_for_order(items=[...], share_split={...})
      → BOM 物理扣料 (与 share_count=1 物理消耗等价)
      → apply_split (v434 share_split_service)
      → emit InventoryEventType.SPLIT_ATTRIBUTED (per-customer cost)
  → sub-C tx-analytics dashboard 消费 SPLIT_ATTRIBUTED
```

**ITEMS_SETTLED 当前是 historical record**, 无消费者 = sub-A 的 `apply_split` 永远不被调 = `INVENTORY.split_attributed` 永远不 emit = sub-C dashboard 空数据。**sub-B.2 是闭环 PRD-11 数据流的唯一缺口环节**。

---

## 2. Phase 1 投影器框架现状 (Q1)

✅ **ProjectorBase 框架成熟**:

- 基类: `shared/events/src/projector.py:51-260` — `ProjectorBase(ABC)`, 抽象 `handle(event, conn)`, 提供 `run()` LISTEN/NOTIFY + 5s 轮询, `rebuild()`, 自带 checkpoint UPSERT (`projector_checkpoints` 表 L237-254), batch=100, tenant 隔离 (`set_config('app.tenant_id')`)
- 现成范例: `shared/events/src/projectors/inventory_bom.py:21-107` — 消费 `inventory.consumed/received/wasted/adjusted` 4 事件, 更新 `mv_inventory_bom`. **sub-B.2 最直接的 fork 模板**
- 注册中心: `shared/events/src/projector_registry.py:50-237` — 9 单例 `start_all`/`stop_all`/`rebuild_all`, `asyncio.gather(return_exceptions=True)` 容错
- tx-supply 内: **无 INVENTORY.* 消费者** — 当前所有投影器都驻 `shared/events/src/projectors/` 全局, 无"服务内私养"先例

**质变判断**: 现有投影器**只更新物化视图, 不回写业务表**. sub-B.2 要"调 `deduct_for_order` 写 BOM 库存" = **首次让 projector 触发业务侧写**, 是质变 ≠ "再加一个 mv_*  projector".

---

## 3. 方案对比 + 推荐 (Q2)

| 维度 | A: tx-supply 内 service-local daemon | B: 全局 InventoryBomProjector 加 handler | C: Redis Stream consumer group |
|---|---|---|---|
| **复杂度** | 高 — 新进程入口 + 部署单元 + monitoring; 偏离全局 registry 范式 | **低** — 1 handler 分支, 复用 checkpoint/LISTEN/RLS/rebuild | 中 — Redis Stream 已存在 (Phase 1 双写), 需 consumer group + DLQ + 新 worker |
| **200 桌并发吞吐** | 单实例 batch=100, 5s 轮询; 高峰 50-100 settles/min hold | 同 A, 复用同一循环 + handler 阻塞拖慢 BOM 视图更新 (耦合风险) | 最佳 — 多 consumer 横向扩展; Redis Stream 内置 ack/retry/pending |
| **死锁风险** | sub-A 已 sorted FOR UPDATE 防 ABBA, 单消费者串行无新风险 | 同 A, 但与 mv_inventory_bom UPDATE 共享同事务拉长锁窗口 | 多 worker 同 (store,ingredient) 仍受 deduct_for_order 内部锁保护; 风险低 |
| **可恢复性** | ✅ 完整 — checkpoint + rebuild 现成 | ✅ 复用 inventory_bom checkpoint | ⚠️ Redis Stream 持久但**非源** — events 表才是 SoT |
| **错误处理** | `_process_backlog` 已 try/except 单事件 + log.error, **无死信表** | 同 A | Redis Stream PEL + XCLAIM 死信, 工业级 |
| **Tier 1 邻接** | ✅ 触 TIER1_SOURCE_PATTERNS — daemon 内调 deduct_for_order 修 ingredients, 同 #547. **第 30 例** | 同 A | 同 A/B — 写路径不变 |

**推荐: 方案 A** `IndexSplitProjector(ProjectorBase)` tx-supply 内 service-local daemon.

**理由**: 框架成熟度让"在哪儿驻"无关紧要, 但 **sub-B.2 性质 ≠ 视图维护 = 业务侧写**, 与 mv_inventory_bom 同进程共事务会污染"投影器只读"心智模型. 物理隔离 service-local registry, 复用 ProjectorBase 但独立 daemon 入口, 保留全局 9 个 mv_* 纯净边界.

**Antithesis (steelman B)**: B 最快 ship, 复用现有 daemon. 但 200 桌峰值排查时把"BOM 库存写"和"BOM 视图更新"绑同一 projector 会让 log/checkpoint/rebuild 语义糊掉, 长期成本 > 节省的一个 daemon.

---

## 4. Tier 级别 + 性能 + 死锁 (Q3)

- **Tier 级别**: **Tier 1 邻接**. 投影器本体 T2 (事件消费框架), 但调 `auto_deduction.deduct_for_order` 写 `ingredients.current_quantity` + `ingredient_transactions`, Tier 1 资金/物料路径 (`auto_deduction.py:285-368` 含 FOR UPDATE 行锁). 与 PR #547 同 Tier 边界, 走 **explicit-ask 第 30 例**.
- **P99 < 200ms 门槛**: ✅ **不受冲击**. settle 已 `asyncio.create_task(emit_event(ITEMS_SETTLED))`, HTTP 响应在 emit 入队后返回. Projector 异步消费, 即使 BOM 扣料耗 500ms 也只影响"库存视图新鲜度", 不影响支付链路 P99.
- **死锁**: sub-A `auto_deduction.py:256-261` 已预聚合 sorted FOR UPDATE 防 ABBA (§17-C 同模式). Projector 单消费者串行调 deduct_for_order 不引入新死锁面.

---

## 5. Schema / migration (Q4)

- **`projector_checkpoints` 新 row**: ✅ 需要, **不需要新 migration** — `ProjectorBase._process_backlog` UPSERT, 首次自动插入 `(projector_name='inventory_split_attribution', tenant_id=...)`.
- **`events.idempotency_key`**: ⚠️ 当前 events 表无, projector 自带去重 (checkpoint `(last_occurred_at, last_event_id)` 严格 `>`). **真问题**: `deduct_for_order` 无幂等键 → restart 重放**重复扣料**. 见 Failure mode F2.
- **`sub_B_2_inventory_attribution_log` 新表**: ❌ 不建议. `events.INVENTORY.SPLIT_ATTRIBUTED` 已是 SoT (event sourcing §15), 加旁表违 CQRS. sub-C 直读 events 或新建 `mv_split_attribution`.

---

## 6. Failure Modes (Q5)

| # | 场景 | 修法 | 优先级 |
|---|---|---|---|
| **F1** | ITEMS_SETTLED emit 后 settle 事务回滚 → projector 拿 stale event 调 deduct 失败 | emit 必须在 `await self.db.commit()` 之后 (Phase 1 范式). 若已 commit 但 emit 失败, ITEMS_SETTLED 丢, sub-B.2 永不消费 = silent data loss. **依赖 5/12 战略 FOUNDATION 真 Outbox** (W7-W12 立项) | P1 — Outbox 项前临时接受 |
| **F2** | projector crash → checkpoint 重放 → 重复扣料 (ingredient.current_quantity 可变) | **P0 必修**. `ingredient_transactions` 表加 `source_event_id UNIQUE (tenant_id, source_event_id)`, projector 拿 `event_id` 当 dedup 键; INSERT 冲突即 skip 整事件. **不加这个 sub-B.2 不能上生产** | **P0** |
| **F3** | dish.bom 在 settle 后但 projector 消费前被改 (cost_fen 变化), split attribution 算错 | dish_ingredients/bom_items 改 cost_fen 不动 quantity, deduct_for_order 用 `ingredient.unit_price_fen` 当时值. **轻微漂移**, 不是 P0 — 与 ORDER.PAID 的 final_amount 已固化属不同账本, 接受. 严格一致需 ITEMS_SETTLED payload 携 bom snapshot, 但 payload 体积爆炸 | P3 接受 |
| **F4** | share_split_rule 在 settle 后被禁用 (allow_share=False), projector 调 apply_split raise ValueError | sub-A `auto_deduction.py:287-310` 已抛 ValueError. Projector handler catch ValueError → log + skip + 写专表 `dlq_split_attribution_failed`; sub-C dashboard 显示 "N 条 attribution 失败需复核" | P1 |

---

## 7. 创始人决策点 (Q6) — deep-interview D1-D4

### D1 投影器模式 (复杂度 vs 隔离)
- **① A 方案 tx-supply 内 service-local daemon (推荐)** — 隔离 mv_* 心智, 长期成本低
- ② B 方案 InventoryBomProjector 加 handler (最快 ship, 半天)
- ③ C 方案 Redis Stream consumer group (战略对齐但工程量 2x)

### D2 幂等键设计 (F2 P0)
- **① 加 `ingredient_transactions.source_event_id UNIQUE` 列 (推荐)** — 与 events.event_id 强关联
- ② 复用 (order_id, dish_id, ingredient_id, occurred_date) 组合键 (无 schema 改但 race 模糊)
- ③ 不做幂等先 ship, F2 风险接受 (危险, 200 桌峰值重启高频)

### D3 错误处理 (F4 死信)
- **① skip + dlq 表 + sub-C 死信看板 (推荐)** — 与 Phase 4 治理四件套对齐
- ② skip + log only, sub-C 手动 grep (临时方案)
- ③ retry 3 次后停 projector (会让整个事件流卡死, 不推荐)

### D4 Tier 级别 + 验收
- **① Tier 1 邻接, 走 explicit-ask 第 30 例 + §19 reviewer + 200 桌并发 regression (推荐)**
- ② Tier 2 (本质事件消费), 集成测试通过即可 (低估了写 ingredients 的风险)
- ③ Tier 1 完整, 强制 TDD 在 DEMO 环境跑通 (过度, projector 不在 P99 关键路径)

---

## 8. 工时估算 + Ship 时机

| 工作项 | 工时 |
|---|---|
| IndexSplitProjector 实现 (handle + 幂等校验) | 3h |
| `ingredient_transactions.source_event_id` migration + 索引 | 1h |
| DLQ 表 + 错误处理 | 2h |
| Tier 1 mock 测试 13+ 用例 + 真 PG regression | 4h |
| §19 reviewer round-1 + fix + round-2 | 3h |
| 200 桌并发 regression (复用 #547 框架) | 2h |
| explicit-ask + admin-merge 流程 | 0.5h |
| **合计** | **~15-16h ≈ 2 工作日** |

**Ship 时机建议**: 不在当前 session 开工, 新 session 起手最优:
1. **session 漂移红线** (feedback_proactive_session_split) — 当前 session 已含 sub-A/B + #538 audit + W11 多发, context 临界
2. **真 Outbox 依赖** — 5/12 战略 FOUNDATION 立项之一, sub-B.2 F1 修法依赖, 现在做欠技术债
3. **新 session deep-interview** — 创始人逐答 D1-D4, 干净走 explicit-ask 第 30 例流程

---

## 9. 关键 References

- `shared/events/src/projector.py:51-260` — ProjectorBase 完整抽象
- `shared/events/src/projectors/inventory_bom.py:21-107` — 最直接 fork 范例
- `shared/events/src/projector_registry.py:50-237` — 9 投影器单例注册
- `shared/events/src/event_types.py:38` — `OrderEventType.ITEMS_SETTLED` (sub-B 注册)
- `shared/events/src/event_types.py:86` — `InventoryEventType.SPLIT_ATTRIBUTED` (sub-A 注册)
- `services/tx-supply/src/services/auto_deduction.py:97-380` — `deduct_for_dish/order` 完整链路 (sub-A merged)
- `services/tx-supply/src/services/auto_deduction.py:256-261` — 预聚合 sorted FOR UPDATE 防 ABBA
- `services/tx-trade/src/services/cashier_engine.py` — settle_order 末尾 ITEMS_SETTLED emit (sub-B merged)
- CLAUDE.md §15 (事件总线) / §17 (Tier 级别) / §19 (独立验证)
- PR #547 — tx-supply row-lock fix, sub-B.2 同 Tier 1 邻接模式
- PR #681 (e28f57c6) — sub-B ship, sub-B.2 依赖
- PR #665 (03fdd86f) — sub-A ship, sub-B.2 闭环目标
