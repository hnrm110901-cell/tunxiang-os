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
