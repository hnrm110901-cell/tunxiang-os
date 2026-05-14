# 屯象OS Tier 1 写路径 SELECT-then-UPDATE 行锁审计（2026-05）

**审计日期**：2026-05-13
**触发**：[PR #272](https://github.com/hnrm110901-cell/tunxiang-os/pull/272) §19 reviewer 发现 wine_storage 4 路由中 3 个漏 FOR UPDATE 行锁
**关联 Issue**：[#532](https://github.com/hnrm110901-cell/tunxiang-os/issues/532)
**审计 commit base**：`origin/main @ 552de4d6`
**范围**：CLAUDE.md §17 Tier 1 红线全 16 服务写路径
**结论摘要**：**24 处漏锁 / 14 处 P0 / 3 服务受影响 / 2 处架构层 gap**

---

## 1. Executive Summary

| 服务 | 漏锁数 | P0 | P1 | P2 | P3 |
|---|---:|---:|---:|---:|---:|
| tx-trade | 17 | 5 | 6 | 6 | 0 |
| tx-finance | 6 | 4 | 1 | 0 | 1 |
| tx-supply | 4 + 1 verifier | 4 | 1 | 0 | 0 |
| **合计** | **24 (+1 待审)** | **13 + 1 verifier P0** | **8** | **6** | **1** |

**核心发现**：

1. **tx-trade 订单与支付主路径全无 row-lock** — `cashier_engine.py` / `order_service.py` / `payment_saga_service.py` 在 main 上 0 处 FOR UPDATE。9 个 SELECT-then-UPDATE 模式全裸（含 add_item / apply_discount / settle_order / payment_saga.compensate / payment_saga.recover_pending_sagas 等 P0）。
2. **tx-finance 金税四期 invoice 全 4 mutation 路径 0 处 FOR UPDATE** — retry_failed / cancel_invoice 并发可触发**诺诺端重复开票/红冲**，金税四期合规硬错。
3. **tx-finance 存酒模块（biz_wine_storage）与 tx-trade 存酒模块（wine_storage_records）双轨并存**，且 tx-finance 端 retrieve_wine（取酒）无行锁；架构层债。
4. **tx-supply 库存 P0**：`inventory_io.receive_stock` 加权平均单价并发错算；`issue_stock` FIFO 出库丢更新；`auto_deduction.deduct_for_dish` 订单完成 BOM 扣料 race —— **直接威胁毛利底线/食安合规硬约束**。
5. **PaymentSaga 设计层 gap**：S1 校验只 SELECT 不锁 → S3 才 UPDATE，期间状态可能被并发改 → 加单独 FOR UPDATE 不够，需架构级修复。

---

## 2. 触发与背景

PR #272（wine_storage Decimal → fen，MERGED `f249ae27`）§19 reviewer 在审视 take_wine 时发现 main pre-existing 一致性 BUG：

| 路由 | FOR UPDATE 状态（PR #272 修复前 main） |
|---|---|
| `take_wine_storage` (L578) | ✅ 历史已有（注释 "加 FOR UPDATE 锁防止并发超取"） |
| `extend_wine_storage` | ❌ 漏（PR #272 §19 修复时一并补） |
| `transfer_wine` | ❌ 漏（PR #272 §19 修复时一并补） |
| `write_off_wine` | ❌ 漏（PR #272 §19 修复时一并补，押金核销 Tier 1 资金路径） |

4 个 SELECT-then-UPDATE 路由 3 个漏锁，模式高度相似 → 强烈暗示 main 其他 Tier 1 写路径有同类 inconsistency。本审计验证该假设。

---

## 3. 审计方法

### 3.1 范围

CLAUDE.md §17 Tier 1 红线全 16 服务：

| Tier 1 路径 | 服务 | 核查文件 |
|---|---|---|
| 订单状态机 | tx-trade | `cashier_engine.py` / `order_service.py` |
| 支付补偿 Saga | tx-trade | `payment_saga_service.py` |
| POS 数据写入与结算 | tx-trade | `delivery_adapters/*.py` / `delivery_adapter.py` |
| 存酒/押金/协议挂账 | tx-trade / tx-finance | `wine_storage_routes.py` (两套) |
| 全电发票 / 金税四期 | tx-finance | `invoice_service.py` |
| 会员储值 | tx-member | `stored_value_service.py` (baseline) |
| 库存增减 / 食安 | tx-supply | `inventory_io.py` / `auto_deduction.py` / `stocktake_service.py` / `api/deduction_routes.py` / `api/inventory.py` |
| 渠道订单 webhook | tx-trade | `api/webhook_routes.py` / `services/delivery_adapter.py` |
| 积分商城兑换（baseline） | tx-org | `employee_points_service.py` |

### 3.2 工具与流程

1. **Grep baseline**：全仓 `with_for_update()` + raw `FOR UPDATE` 统计正例（12 已加锁位置 main 上确认）
2. **逐文件全文 Read**：security-reviewer agent 读完每个候选文件完整内容（不截 head/tail），找 SELECT-then-UPDATE 模式
3. **业务语义判断**：tenant 隔离的高并发场景才需要行锁；只读 SELECT 不算；纯 INSERT-only 不算；幂等 idempotent key 匹配不算
4. **Spot-verify**：5 个高优先级 P0 finding + 2 个 verifier 候选 manual 读 origin/main 版本核对

### 3.3 评级

| 级别 | 标准 |
|---|---|
| **P0** | Tier 1 资金/合规路径 + 高并发场景 + 损失不可逆（金额/合规/物权） |
| **P1** | Tier 1 资金/合规路径 + 状态错乱但可对账修复 |
| **P2** | 业务一致性问题 + 损失可恢复 |
| **P3** | 低影响 / 短窗口 / 业务上可接受 |

---

## 4. ❌ 漏锁详单

### 4.1 tx-trade（17 漏锁，5 P0）

#### `services/tx-trade/src/services/cashier_engine.py`（1675 行，0 处 FOR UPDATE）

| 行号 | 函数 | 模式 | 业务影响 | 级别 |
|---|---|---|---|---|
| L125-160 | `open_table` | SELECT Table → UPDATE Table.status='occupied' + table.current_order_id | 双开台争用：两服务员同时开同一桌 → state machine 后写者覆盖前者 | P1 |
| L284-322 | `change_table_status` | SELECT Table → UPDATE Table.status | 状态合法性校验过后被并发覆盖，非法状态转换绕过 | P2 |
| L353-414 | `add_item` | SELECT Order (+Dish join) → UPDATE Order.total_amount_fen + final_amount_fen | **并发加菜金额丢失**：两路读相同 old total → ORM 属性赋值后第二个 commit 覆盖第一个 → 订单总额错算 | **P0 资金路径** |
| L462-497 | `update_item` | SELECT OrderItem → UPDATE quantity/subtotal + Order.total（raw UPDATE 加减半安全） | OrderItem 无锁，两路并发改 quantity 用相同 old subtotal → diff 错 | P1 |
| L520-547 | `remove_item` | SELECT OrderItem → DELETE + UPDATE Order.total | 同 update_item，phantom 风险 | P1 |
| L580-688 | `apply_discount` | SELECT Order → 三条硬约束/审批 → UPDATE Order.discount_amount_fen + final_amount_fen | **毛利底线绕过**：读 total → 算 margin → 算审批 → 写 discount；并发加菜可让 final 低于毛利底线 | **P0 资金路径 + 硬约束** |
| L744-820 | `settle_order` | SELECT Order → transition_order(completed) → UPDATE Order.completed_at + 释放桌台 | **双结算 race**：两 POS 同时收银 → 两条 payment 记录 + 桌台释放 2 次 | **P0 支付路径** |
| L929-948 | `cancel_order` | SELECT Order → transition_order(cancelled) | 并发结算 + 取消时状态机守卫读旧状态，校验过被并发覆盖 → 已 paid 订单被 cancel | P1 |
| L1338-1389 | `transfer_table` | SELECT Order + target Table → UPDATE order.table_number + 释放原 + 锁新 | **桌台争抢**：两路转到同一空桌都通过校验 → 同时占用 | P1 |

#### `services/tx-trade/src/services/order_service.py`（548 行，0 处 FOR UPDATE）

| 行号 | 函数 | 模式 | 业务影响 | 级别 |
|---|---|---|---|---|
| L279-296 | `update_item_quantity` | SELECT OrderItem → SET item.quantity + UPDATE Order.total | 同 cashier_engine.update_item | P1 |
| L302-318 | `remove_item` | SELECT OrderItem → DELETE + UPDATE Order.total | 同 cashier_engine.remove_item | P1 |
| L323-334 | `apply_discount` | SELECT Order → UPDATE order.discount_amount_fen + final_amount_fen | **比 cashier_engine 简化版更危险** — 连 margin 校验都没有 | **P0 资金路径** |
| L402-418 | `settle_order`（online 路径） | SELECT Order → transition_order(completed) → UPDATE + 释放桌台 | **Saga S3 链路依赖此函数** — payment_saga_service L471 调用；漏锁直接放大 saga 风险 | **P0 支付路径** |
| L464-476 | `cancel_order` | SELECT Order → transition_order(cancelled) | 同 cashier_engine.cancel_order | P1 |

#### `services/tx-trade/src/services/payment_saga_service.py`（567 行，0 处 FOR UPDATE）

| 行号 | 函数 | 模式 | 业务影响 | 级别 |
|---|---|---|---|---|
| L188-200 | `_validate_order` (S1) | 纯 SELECT 查 status，无 mutation | **设计 gap**：S1 read 后到 S3 write 之间状态可能被并发改 — Saga 缺少"占位锁" | ⚠️ **架构 P0**（见 §6.2） |
| L468-506 | `_complete_order` (S3 inline) | UPDATE orders SET status='completed' WHERE status NOT IN (...) + rowcount=0 fallback SELECT 判幂等 | 条件 UPDATE 本身原子，但 rowcount=0 fallback 是 select-then-judge 反模式 | P2（条件 UPDATE 已 mitigate 大半） |
| L295-343 | `compensate` | SELECT saga step → UPDATE saga step | **两 worker 同时 compensate 同一 saga → 双退款**（payment_gateway.refund 调两次） | **P0 资金路径** |
| L363-446 | `recover_pending_sagas` | SELECT 挂起 sagas (paying/completing > 5min) → 逐条 UPDATE | **多 worker/多 pod 灾难恢复双跑**：缺 `FOR UPDATE SKIP LOCKED` | **P0 资金路径** |

#### `services/tx-trade/src/api/webhook_routes.py`（513 行）

- 委托给 `DeliveryPlatformAdapter.receive_order` — 见 4.1.5 `delivery_adapter.py`
- 本路由层无直接 SELECT-then-UPDATE。

#### `services/tx-trade/src/services/delivery_adapter.py`（734 行，0 处 FOR UPDATE）

| 行号 | 函数 | 模式 | 业务影响 | 级别 |
|---|---|---|---|---|
| L150-160 | `receive_order` (幂等性检查) | SELECT DeliveryOrder by platform_order_id → 不存在则 INSERT | **两路同时 receive 同一 platform_order_id → 都查不到 existing → 都 INSERT → 重复订单**（依赖 unique constraint 兜底但需 catch IntegrityError） | P1 |
| L289 | `confirm_order` | _get_order → order.status = "preparing" | state machine 切换无锁，多平台 webhook + 内部触发可能并发 | P2 |
| L335 | `start_preparing` | _get_order → order.status = "ready" | 同上 | P2 |
| L401 | `cancel_order` | _get_order → order.status = "cancelled" | 同上 | P2 |
| L450 | `complete_order` | _get_order → order.status = "completed" | 同上 | P2 |

---

### 4.2 tx-finance（6 漏锁，4 P0）

#### `services/tx-finance/src/services/invoice_service.py`（406 行，0 处 FOR UPDATE）

| 行号 | 函数 | 模式 | 业务影响 | 级别 |
|---|---|---|---|---|
| L249-272 | `get_invoice_status` | SELECT Invoice (status=pending) → 调诺诺 query → UPDATE invoice.status=issued/failed + invoice_no/code/pdf_url | **金税四期资金路径** — 并发两次查询同一发票：诺诺侧返回先写 issued，B 也写 → invoice_no 错写 | **P0 金税四期** |
| L188-237 | `retry_failed` | SELECT Invoice (status=failed) → 重置 pending + 生成新 request_id → 调诺诺 → UPDATE status | **重复重试 race**：两路并发 retry 都读到 failed → 都过守卫 → 都调诺诺 → 诺诺侧双开票 | **P0 金税四期** |
| L284-302 | `reprint` | SELECT Invoice (status=issued) → 调诺诺 get_pdf_url → UPDATE pdf_url | 状态守卫 issued，两次并发 reprint 都过 → pdf_url 双写（业务上无害） | P3 |
| L316-369 | `cancel_invoice`（红冲） | SELECT Invoice (status=issued + invoice_no/code 非空) → 调诺诺红冲 → UPDATE status=cancelled | 两路并发红冲 → 双红冲 → 金税四期投诉 | **P0 金税四期** |

⚠️ **invoice_service.py 全 4 mutation 路径 0 处 FOR UPDATE**，金税四期合规硬路径全裸。

#### `services/tx-finance/src/api/wine_storage_routes.py`（775 行，0 处 FOR UPDATE）

⚠️ **此文件独立于 tx-trade 同名文件，是 finance 端的存酒模块**（`biz_wine_storage` 表，不是 `wine_storage_records`）。两套数据模型并存 — 见 §6.1。

| 行号 | 函数 | 模式 | 业务影响 | 级别 |
|---|---|---|---|---|
| L248-328 | `retrieve_wine`（取酒） | SELECT biz_wine_storage (quantity/status) → 业务校验 (quantity ≤ 剩余) → UPDATE quantity/status + INSERT log | **客户存酒并发超取**：两路读 quantity=5，body.quantity=3 都过校验 → 各扣 3 → 最终 -1 | **P0 物权/押金** |
| L365-448 | `extend_storage`（续存） | SELECT biz_wine_storage → UPDATE expires_at + status | 并发续存：两路读相同 old expires → 都写相同 new_expires → 少续一次 + fee 收取重复 | P1 押金 |

---

### 4.3 tx-supply（4 漏锁，3 P0，+1 verifier P0）

#### `services/tx-supply/src/services/inventory_io.py`（521 行，0 处 FOR UPDATE）

| 行号 | 函数 | 模式 | 业务影响 | 级别 |
|---|---|---|---|---|
| L97-167 | `receive_stock` | SELECT Ingredient → 加权平均单价计算 → SET current_quantity + unit_price | **加权平均并发错算**：两路并发入库读相同 old → 各算加权 → 后写覆盖前者 → unit_price 错 + total qty 丢一次 | **P0 食安/成本** |
| L252-358 | `issue_stock` (FIFO) | SELECT Ingredient + 多次 SELECT batch_remaining → 逐批 SET current_quantity -= deduct + INSERT consume txn | **FIFO 并发出库丢更新**：两路读相同 current_quantity + 批次明细 → ORM 属性赋值后第二 commit 覆盖 → 库存比期望多 | **P0 食安/成本** |
| L364-425 | `adjust_stock` | SELECT Ingredient → SET current_quantity = old + delta + INSERT txn | 盘点调整 + 日常出入库并发可能丢更新 | P1 食安/成本 |

#### `services/tx-supply/src/services/auto_deduction.py`（0 处 FOR UPDATE）

| 行号 | 函数 | 模式 | 业务影响 | 级别 |
|---|---|---|---|---|
| L130-180 | `deduct_for_dish`（按 BOM 行循环） | SELECT Ingredient → ingredient.current_quantity -= consume_qty + INSERT txn | **订单完成 BOM 扣料 race**：两单同时完成同菜品 → 读相同 old_qty → 计算 new_qty → flush 后写覆盖 → BOM 扣料两份但库存只下降一份 → **负库存累积** | **P0 食安/成本** |

⚠️ **直接威胁毛利底线计算 + 食安合规硬约束**（CLAUDE.md §17 Tier 1 三条硬约束）。`deduct_for_order` 由订单完成事件触发，是 Tier 1 资金路径的下游必经之路。

#### `services/tx-supply/src/services/stocktake_service.py`（627 行，0 处 FOR UPDATE）

| 行号 | 函数 | 模式 | 业务影响 | 级别 |
|---|---|---|---|---|
| L460-490 | `finalize_stocktake`（库存调整） | SELECT Ingredient → SET current_quantity = actual_qty + status | **盘点终结 race**：两路并发 finalize 同一 stocktake，或与并发 issue_stock/receive_stock 撞 → ingredient 数量错乱 | **P0 食安/成本** |

⚠️ **Verifier 候选已升 P0**（spot-check 已确认模式）。

#### `services/tx-supply/src/api/deduction_routes.py` / `inventory.py`

- 全部委托给 service 层，路由层无直接 SELECT-then-UPDATE — 漏洞下沉到 inventory_io.py / auto_deduction.py / stocktake_service.py。

---

## 5. ✅ Baseline（main 已有 FOR UPDATE 的 Tier 1 正例）

| 文件 | 函数 | 行 | 锁形式 |
|---|---|---:|---|
| `tx-trade/api/wine_storage_routes.py` | `take_wine` | 578 | FOR UPDATE |
| `tx-trade/api/wine_storage_routes.py` | `extend_wine_storage` | 680 | FOR UPDATE（PR #272 §19 补） |
| `tx-trade/api/wine_storage_routes.py` | `transfer_wine` | 784 | FOR UPDATE（PR #272 §19 补） |
| `tx-trade/api/wine_storage_routes.py` | `write_off_wine` | 908 | FOR UPDATE（PR #272 §19 补） |
| `tx-trade/routers/payment_router.py` | `settle_order` | 77 | FOR UPDATE |
| `tx-trade/routers/self_pay_router.py` | `guest_submit_payment` | 198 | FOR UPDATE |
| `tx-trade/api/banquet_deposit_routes.py` | `apply_deposit` | 261 | FOR UPDATE |
| `tx-trade/api/banquet_deposit_routes.py` | `refund_deposit` | 372 | FOR UPDATE |
| `tx-trade/api/quick_cashier_routes.py` | `member_quick_pay` (order + member 双锁) | 1363 / 1386 | FOR UPDATE |
| `tx-member/services/stored_value_service.py` | recharge/consume/refund/transfer/freeze/unfreeze/expiry/exchange_points 等 11 处 | 928/941/1046/1153/1300/1443/1468 | `.with_for_update()`（含 2 卡同锁排序防死锁） |
| `tx-org/services/employee_points_service.py` | `redeem_reward`（reward + balance 双锁） | 891 / 915 | FOR UPDATE |
| `tx-trade/services/wechat_pay_notify_service.py` | wechat 异步回调订单锁 | 139 | `.with_for_update()` |
| `tx-trade/services/my_payment_notify_service.py` | 我方支付回调订单锁 | 322 | `.with_for_update()` |
| `tx-trade/services/retail_mall.py` | retail 三处 | 331 / 534 / 561 | `.with_for_update()` |
| `tx-agent/services/operation_planner.py` | operation 计划写入 | 221 / 263 | `.with_for_update()` |

**观察**：

- `tx-member.stored_value_service.py` 是全仓 row-lock 最严谨的服务（11 处锁，包含 2 卡同锁的排序防死锁）—— 可作为修复参考范本。
- `tx-trade` 内部一致性问题严重：`payment_router.py` / `self_pay_router.py` / `quick_cashier_routes.py` / `banquet_deposit_routes.py` / `wine_storage_routes.py` 有 lock，但 `cashier_engine.py` / `order_service.py` / `payment_saga_service.py` 0 处 lock —— **同一服务内主路径分裂**。

---

## 6. 架构层 gap

### 6.1 wine_storage 双轨（tx-trade vs tx-finance）

`tx-trade/src/api/wine_storage_routes.py`（`wine_storage_records` 表）与 `tx-finance/src/api/wine_storage_routes.py`（`biz_wine_storage` 表）**两套并存**：

- **tx-trade 版**：4 个 mutation 路由全部 ✅ 加锁（PR #272 §19 补完）
- **tx-finance 版**：2 个 mutation 路由全部 ❌ 无锁（retrieve_wine P0 / extend_storage P1）

**问题**：

1. 两套数据模型 + 两套业务路径并存，客户存酒究竟以哪边为 source of truth 不明
2. 行锁标准不一致 — finance 端漏锁的 retrieve_wine 是客户取酒物权资金路径，与 tx-trade 端 take_wine 同等业务地位
3. 修复策略未决 — 是统一到 tx-trade 还是 tx-finance？ontology 层冻结约束（CLAUDE.md §17）要求创始人级别决策

**建议**：另起 issue 由创始人对齐方向后再修。本审计先记录 finance 端漏锁事实。**Follow-up issue：[#535](https://github.com/hnrm110901-cell/tunxiang-os/issues/535)**。

### 6.2 PaymentSaga S1 → S3 状态间隙

`payment_saga_service._validate_order` (S1) 只 SELECT 不锁，到 `_complete_order` (S3) 之间订单状态可被并发改：

```
[S1 _validate_order]  SELECT status (无锁)    ← 通过校验
[S2 调用 payment_gateway.charge]                ← 期间状态可能被并发 settle/cancel/transition
[S3 _complete_order]  UPDATE status='completed' ← 写时与 S1 校验的状态可能已不一致
```

**问题**：单纯给 S1 加 FOR UPDATE 不够 —— Saga 跨多个 db 会话（S2 期间释放连接），FOR UPDATE 在 commit 时释放，无法跨 saga 步骤持有。

**建议**：

- 方案 A：在 S1 直接做条件 UPDATE 占位（如 `status = 'paying' WHERE status = 'pending'`），把"占位"和"校验"原子合并；S3 时校验 status='paying' 然后转 completed
- 方案 B：用专门的 saga_locks 表（advisory lock）跨步骤持有
- 方案 C：拆出独立 issue 由 architect agent 评估

本审计标记此为**架构 P0**，不在本轮修复 PR 范围内。**Follow-up issue：[#537](https://github.com/hnrm110901-cell/tunxiang-os/issues/537)（推荐方案 A，待 architect 评估）**。

---

## 7. Verifier 候选（不放心 / 待二审 / 待创始人对齐）

| # | 候选 | 状态 | 建议 |
|---|---|---|---|
| 1 | `cashier_engine.update_item` (L488-492) 用 `UPDATE Order SET total = total + diff` raw 加减 | 半安全 — Order 端 atomic，但 OrderItem 本身无锁 → 两路并发改同 item 用相同 old subtotal → diff 错 | 已归 P1（OrderItem 漏锁），不需 verifier 二审 |
| 2 | `change_table_status` 桌台状态机的并发语义 | 业务上是否要求强一致？last-writer-wins 桌台状态是否可接受？ | **需创始人对齐 CLAUDE.md §17 桌台状态机并发语义** |
| 3 | 二级派生表（payments / wine_storage_transactions / ingredient_transactions / stored_value_transactions）的多条 INSERT 对账 phantom | 不属 SELECT-then-UPDATE 但相关 — 如 saga 双 compensate 各自 INSERT 一条 refund txn | 不在本审计范围，建议另起对账层 issue |
| 4 | `payment_saga_service._complete_order` 条件 UPDATE 是否够 | rowcount=0 fallback 的 SELECT-and-check 仍有潜在 race | 归 P2（条件 UPDATE 已 mitigate 大半），主要风险已被 §6.2 架构 gap 覆盖 |
| 5 | tx-trade 其他 POS adapter（`delivery_adapters/foodpanda_adapter.py` / `grabfood_adapter.py` / `douyin_adapter.py`） | 本审计只覆盖 `meituan_adapter.py`（骨架无 mutation） | **下轮审计扩展候选** — 上线前必扫 |
| 6 | tx-trade 宴会订单全套 routes（`banquet_*_routes.py` 共 30+ 文件） | 本审计只覆盖 `banquet_deposit_routes.py`（baseline 正例） | **下轮审计扩展候选** — Tier 1 资金路径但本轮未扫 |
| 7 | tx-member `consume_by_id` 等单元测试已明确要求 `with_for_update`（见 `tests/test_stored_value.py:243`）— 是否所有 stored_value 路径都已加 | spot-check 看 11 处 lock 覆盖良好但未穷举 | 归 baseline ✅，但建议补一条 regression 测确认 |

---

## 8. 修复策略（Phase 4 —— 与创始人确认后启动）

### 8.1 修复 PR 拆分原则

**每服务独立 PR**，blast radius 限于单服务，每 PR 配相应 Tier 1 row-lock 并发测试：

| # | 服务 | 修复范围 | 估计 PR 大小 | 优先级 |
|---|---|---|---|---|
| PR-A | tx-finance | invoice_service.py 4 路径 + 独立 wine_storage_routes 2 路径 | 中（~80 行 + 测试） | **首发 P0**（金税四期合规） |
| PR-B | tx-supply | inventory_io.py 3 处 + auto_deduction.py 1 处 + stocktake_service.py 1 处 | 中（~100 行 + 测试） | **首发 P0**（食安/毛利底线） |
| PR-C | tx-trade payment_saga_service.py | compensate + recover_pending_sagas + （S3 条件 UPDATE 已足） | 中（~60 行 + 测试） | **首发 P0**（双退款风险） |
| PR-D | tx-trade cashier_engine.py | settle_order + add_item + apply_discount + 5 P1 状态机 | 大（~200 行 + 测试，需 §17 桌台对齐） | **二发 P0**（订单主路径） |
| PR-E | tx-trade order_service.py | settle_order + apply_discount + 3 P1（与 PR-D 协同） | 中（~120 行 + 测试） | **二发 P0** |
| PR-F | tx-trade delivery_adapter.py | receive_order 幂等性（INSERT ON CONFLICT）+ 5 状态机 | 中（~80 行 + 测试） | 三发 P1 |
| 架构 issue | payment_saga S1→S3 | 重新设计 saga 占位锁 | 大 | 单独 architect 评估 |
| 架构 issue | wine_storage 双轨 | 创始人对齐 source of truth | — | 单独创始人决策 |

### 8.2 ship 流程要求

- **每 PR 必须含 Tier 1 row-lock 并发 regression 测试**（200 桌并发场景，CLAUDE.md §20）
- **Tier 1 资金路径 PR 不在 7 类 carve-out 内** — 每 PR 必须 explicit-ask user 授权（参考 PR #271 / #272 模式）
- **§19 reviewer 必扫**：每 PR 必须派 code-reviewer agent 独立审

### 8.3 测试策略

**正面测试模式**：用 `pytest-postgresql` + asyncio.gather 模拟 N 路并发，断言最终一致性。参考 `tx-member/tests/test_stored_value.py:243` 的 `with_for_update` 行为断言模式。

**负面测试模式**：在修复前先写一个会失败的并发测（XFAIL），证明 race 真实存在；修复后翻为 PASS。

---

## 9. 关联

- **触发 PR**：[#272](https://github.com/hnrm110901-cell/tunxiang-os/pull/272) wine_storage Decimal → fen（MERGED `f249ae27`）
- **触发 §19 reviewer 修复**：take_wine 是历史已加锁 baseline，extend/transfer/write_off 漏锁，PR #272 补 3 处
- **本审计 issue**：[#532](https://github.com/hnrm110901-cell/tunxiang-os/issues/532)
- **架构层 follow-up issues（本 audit 同步落盘）**：
  - [#535](https://github.com/hnrm110901-cell/tunxiang-os/issues/535) "wine_storage 双轨架构债：tx-trade `wine_storage_records` vs tx-finance `biz_wine_storage` 谁是 SoT"（待创始人决策）
  - [#537](https://github.com/hnrm110901-cell/tunxiang-os/issues/537) "PaymentSaga S1→S3 跨步骤占位锁机制"（待 architect 评估，推荐方案 A）
- **CLAUDE.md 锚点**：§17 Tier 1 红线 / §19 reviewer 标准 / §20 Tier 1 测试标准 / §14 安全审计活历史

---

## 10. 审计执行记录

- **审计执行**：security-reviewer agent（read-only），主代理 spot-verify 5 处 P0 + 2 处 verifier 候选
- **审计耗时**：~5 分钟 agent 扫描 + ~10 分钟 spot-check + ~30 分钟报告整理
- **审计 commit base**：`origin/main @ 552de4d6`
- **审计范围**：16 个候选文件全文读取 + main 版本核对（避开当前 worktree 在 `refactor/w2a-remove-regional-phase2` 分支与 #271/#272 base 差异）

**审计完成。无文件修改（read-only 遵守）。**

---

## 11. §17 桌台并发语义对齐决策跟踪（待创始人答复）

> 本节为 PR-D / PR-E 6+3 P1 路径的语义决策追踪表。创始人答复 3 选择题后，按填空表格落地 §17 对齐 PR（cashier_engine 6 P1/P2 + order_service 3 P1 = 9 路径，合并 #549/#557/#559 follow-up issue = 11 路径范围）。
>
> 本节为决策记录，**不含实现指引**。创始人答复后，由 architect agent 出具具体修法 + 修复 PR 拆分方案。
>
> **2026-05-14 14:46 落盘** — DEVLOG 5/13 末段已记录"等创始人 3 选择题答复"，本节文档化以避免每次重新分析。

### 11.1 影响路径全景（11 路径，按 P 级别）

#### cashier_engine.py（6 路径，P1/P2）

| 路径 | 行号 | 级别 | 现状 | 涉及决策 |
|---|---|---|---|---|
| `open_table` | L125-160 | P1 | SELECT Table 无锁 → UPDATE 直接赋值 | **选择题 1（双开台 race）** |
| `change_table_status` | L284-322 | P2 | 状态校验后并发覆盖，非法转换绕过 | **选择题 1（衍生 — 状态机一致性）** |
| `update_item` | L462-497 | P1 | OrderItem 无锁，并发改 quantity 金额错 | 与 §17 无关 — 通用 OrderItem lock 议题（#557 落 issue） |
| `remove_item` | L520-547 | P1 | OrderItem 无锁 + phantom 风险 | 同上（OrderItem lock 议题） |
| `cancel_order` | L929-948 | P1 | 无 Order 锁，并发结算+取消 → 已 paid 订单被 cancel | 与 §17 关联 — **订单终态保护** |
| `transfer_table` | L1338-1389 | P1 | SELECT-then-校验-then-UPDATE 校验窗口竞争 — 两路转到同一空桌都通过 | **选择题 2（转桌争抢）** |

#### order_service.py（3 路径，P1）

| 路径 | 行号 | 级别 | 现状 | 涉及决策 |
|---|---|---|---|---|
| `update_item_quantity` | L279-296 | P1 | OrderItem 无锁 | 通用 OrderItem lock |
| `remove_item` | L302-318 | P1 | OrderItem 无锁 + phantom | 同上 |
| `cancel_order` | L464-476 | P1 | 无 Order 锁，并发结算+取消 | 与 §17 关联 — 订单终态保护 |

#### Follow-up issues（合并范围内的架构/补 test 议题）

| Issue | 类别 | 内容 | 与 §17 关系 |
|---|---|---|---|
| [#549](https://github.com/hnrm110901-cell/tunxiang-os/issues/549) | architect | `auto_deduction.deduct_for_order` 跨 dish ABBA 死锁防护 | 独立 — architect 评估，可合并到 §17 PR 同步 ship |
| [#557](https://github.com/hnrm110901-cell/tunxiang-os/issues/557) | 文档+test | `apply_discount _calc_order_cost` OrderItem 隐式不变量 | 与 OrderItem lock 议题关联（cashier update_item / remove_item） |
| [#559](https://github.com/hnrm110901-cell/tunxiang-os/issues/559) | 校验缺失 | `order_service.apply_discount` 未校验 order.status | 与终态保护关联 |

### 11.2 三个选择题

#### 选择题 1 — 双开台 race（`open_table` P1）

**场景**：两个服务员同时打开同一空桌（前台 + POS / 双 POS / 不同员工手机）。

**当前现状**：
- `cashier_engine.py:L125-160`: SELECT Table (status='free') → UPDATE Table.status='occupied' + current_order_id=order_id（直接赋值，无 FOR UPDATE）
- 两路并发都通过 SELECT 校验 → 各自 UPDATE → 后写者覆盖前写者的 order_id → 桌台被第二个订单"占"了，**第一个订单失去桌台引用**

**候选方案**：

| # | 方案 | 实现 | 优点 | 缺点 |
|---|------|------|------|------|
| 1A | 强一致（FOR UPDATE + rowcount check） | SELECT 加 `.with_for_update()`，第二路看到 status='occupied' 抛 `TableOccupiedError` | 业务语义清晰，错误前端可弹窗"桌台已被开台，请刷新" | 服务员看到错误需手动 retry，P99 延迟 +5-10ms |
| 1B | LWW（最后写入胜出，订单端兜底） | UPDATE Table 不加锁，允许后写者覆盖；订单状态机以 Order 表为准 | 性能最优，无阻塞 | 桌台-订单引用不一致，下次结算找桌台时数据漂移 — **不推荐** |
| 1C | 混合（开台锁桌，状态转换 LWW） | open_table 加 FOR UPDATE；后续 change_table_status 仍 LWW | 关键入口强一致，其他操作高性能 | 决策边界复杂 — 哪些操作算"关键入口"？需另立规则 |

**关联路径**: 选 1A 后 `change_table_status` (P2) 也建议一并加锁（强一致一致性）。

**测试需求**：
- `test_double_open_table_race_tier1.py`: asyncio.gather 2 路并发 open_table，断言只 1 路成功 + 1 路抛 `TableOccupiedError`（方案 1A）

---

#### 选择题 2 — 转桌争抢（`transfer_table` P1）

**场景**：两路并发转桌都指向同一空桌（典型：500 元桌 + 200 元桌都想升 1000 元 VIP 桌）。

**当前现状**：
- `cashier_engine.py:L1338-1389`: SELECT Order (无锁) → SELECT target Table (无锁) → 校验 target.status='free' → UPDATE 释放原桌 + 锁新桌
- **校验后竞争窗口**：两路同时见 free → 各自 UPDATE → 后写者覆盖，第一个 Order 失去桌台 + 源桌可能错误释放

**候选方案**：

| # | 方案 | 实现 | 优点 | 缺点 |
|---|------|------|------|------|
| 2A | 双锁（源桌+目标桌按 ID 排序） | SELECT 源桌 + 目标桌 `.with_for_update()`，按 `table_id` 升序锁防 ABBA | 强一致，无死锁 | 锁两桌持有时间长 (~10ms)，高峰转桌频繁可能 contention |
| 2B | 原子 UPDATE rowcount check | `UPDATE target SET status='occupied', current_order_id=:new_order_id WHERE status='free'` → rowcount=0 抛 `TableOccupiedError` | 单语句原子，无需 FOR UPDATE，性能最优 | 源桌释放需配套幂等 — 若中途 fail 源桌可能"丢失" |
| 2C | saga 模式（事件驱动） | `TableTransferRequested` 事件 → projector 串行处理 → 失败发送 `TableTransferFailed` 事件 | 完全异步，无锁 | 实现复杂度高，事件总线已 v147 接入但 transfer 未注册事件类型 |

**关联路径**: 与选择题 1 方案选择关联（如选 1A 强一致，则 2 推荐 2A 双锁；若选 1B/1C，则 2 可走 2B 原子 update）。

**测试需求**：
- `test_transfer_table_race_tier1.py`: 两路并发 transfer 到同一目标桌，断言只 1 路成功 + 桌台终态一致（无双占用 + 无源桌"丢失"）

---

#### 选择题 3 — 结算释放桌台中间态（`settle_order` P0 → `_release_table`）

**场景**：两路并发结算同一订单（典型：服务员 POS + 顾客自助 / 双 POS 同时点结算按钮）。

**当前现状**（PR #556/#560 后已部分修复）：
- `cashier_engine.py:L744-820`: SELECT Order **FOR UPDATE** → transition_order(completed) → `_release_table()` UPDATE 桌台释放（**故意无锁**, audit §4.1.2 备注 + DEVLOG 5/13 晚段晚 备忘）
- 设计意图：Order FOR UPDATE 串行化两路 settle，输者抛"订单已结算"分支，`_release_table` 只执行一次。**但桌台完整语义留 §17 创始人对齐**。

**候选方案**：

| # | 方案 | 实现 | 优点 | 缺点 |
|---|------|------|------|------|
| 3A | fail-fast（保留当前隐式） | 维持现状：Order FOR UPDATE + `_release_table` 不加锁，依赖串行化让 release 只跑一次 | 实现最简，已在 main | 隐式依赖事务边界 — 若 settle 完成后桌台未及时刷新（前端缓存）会显示"已释放"假状态 |
| 3B | 幂等释放（WHERE 子句过滤） | `_release_table` UPDATE WHERE `current_order_id=:order_id AND status='occupied'`，允许多次调用无害 | 显式幂等，便于 retry / replay / saga 补偿 | 多一次 WHERE 校验，性能微降；需 audit 既存 caller 是否依赖"释放必发生" |
| 3C | saga 补偿（显式 rollback） | settle fail 时 emit `OrderSettleFailed` → projector 触发 `_release_table` 补偿 | 完全异步，可观测性最好 | 实现复杂度高，需新增 event_type + projector |

**关联路径**: 与 `cancel_order` (cashier L929 + order_service L464) 终态保护关联 — 取消已结算订单也需 fail-fast。

**测试需求**：
- `test_concurrent_settle_release_tier1.py`: 双路并发 settle 同订单，断言 1 路成功 + 1 路抛"订单已结算" + 桌台 release 只执行 1 次（或幂等多次结果一致，方案 3B）
- `test_settle_fail_release_rollback_tier1.py`: settle 路径中途 fail（payment_saga compensate），断言桌台 status 回到 occupied（方案 3C）或保持 occupied（方案 3A 默认事务回滚）

### 11.3 决策追踪表

> 创始人答复后填本表。每题选 1 个候选方案，并标注答复时间 + 备注。

| 选择题 | 候选 | 创始人选择 | 答复时间 | 备注 |
|---|---|---|---|---|
| 1 — 双开台 race (`open_table` P1) | 1A / 1B / 1C | ⏳ pending | — | — |
| 2 — 转桌争抢 (`transfer_table` P1) | 2A / 2B / 2C | ⏳ pending | — | — |
| 3 — 结算释放桌台中间态 (`settle_order` P0 / `_release_table`) | 3A / 3B / 3C | ⏳ pending | — | — |

### 11.4 后续 PR 拆分预案（创始人答复后启动）

按 §8.1 拆分原则，§17 对齐 PR 候选拆分：

| # | PR | 范围 | 大小 | 依赖决策 |
|---|----|------|------|---------|
| §17-A | tx-trade cashier_engine 桌台路径 | open_table + change_table_status + transfer_table | 中 (~80 行) | 选择题 1 + 2 |
| §17-B | tx-trade settle 终态保护 | cashier.settle_order + cashier.cancel_order + order_service.cancel_order + _release_table | 中 (~100 行) | 选择题 3 |
| §17-C | OrderItem lock 议题 (与 §17 并行) | cashier.update_item + cashier.remove_item + order_service.update_item_quantity + order_service.remove_item | 中 (~120 行) | 不依赖 §17 — 可独立 ship |
| §17-D | follow-up 合并 | #549 ABBA architect + #557 OrderItem 不变量文档+test + #559 apply_discount status 校验 | 小-中 (~60 行) | 不依赖 §17 |

**ship 流程**: 每 PR 仍按 §8.2 — explicit-ask user / §19 reviewer / Tier 1 row-lock 并发 regression 测试。

### 11.5 阻塞依赖图

```
创始人答复 3 选择题
    ├─ 选择题 1 → 解锁 §17-A (cashier 桌台 3 路径)
    ├─ 选择题 2 → 解锁 §17-A (同 PR)
    └─ 选择题 3 → 解锁 §17-B (settle 4 路径)
                              ↓
                  §17-C / §17-D 可并行 ship（不依赖创始人答复）
```

### 11.6 决策点缘起

- **§17 命名缘起**: CLAUDE.md §17 "Tier 1：零容忍" 红线表 — 订单状态机 + 桌台拓扑相关均属 Tier 1
- **三选择题来源**: 本 audit doc §7 Verifier #2（"业务上是否要求强一致？last-writer-wins 桌台状态是否可接受？"）+ DEVLOG 5/13 晚段晚 PR #556/#560 ship 备忘（"桌台 release 故意不加锁 — 留 §17 创始人对齐"）
- **触发 PR**: PR #556 (`fca685e8`) cashier 3 P0 / PR #560 (`ebb758ce`) order_service 2 P0 — 5/14 凌晨 ship，明确 6+3 P1/P2 路径"待 §17 桌台对齐"
- **当前阻塞**: 11 路径 unable to ship until 创始人答复，DEVLOG 已 4+ session 记录该阻塞

### 11.7 推荐解读（不强制）

> 本节为审计层 architect 视角的初步偏好，**不替代创始人决策**，仅为减少决策成本提供 default 起点。

- **选择题 1**: 偏好 **1A 强一致** — 桌台是物理资源（一桌不能两团客人），LWW 数据漂移不可接受；服务员见错误重试是合理 UX
- **选择题 2**: 偏好 **2A 双锁排序** — 与 1A 一致性匹配；与 `tx-member/stored_value_service.py` 11 处"2 卡同锁排序"模式一致（5/13 row-lock audit baseline ✅ 12 正例之一）
- **选择题 3**: 偏好 **3B 幂等释放** — 显式幂等比隐式事务边界更鲁棒；为未来 saga 补偿 / 灰度 retry / 离线 replay 留余地，性能开销 minor (~1ms)

如创始人无特别意见，本表建议作 default 选项（1A / 2A / 3B）。

---
