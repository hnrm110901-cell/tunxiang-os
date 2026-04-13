# 竞态条件安全审查报告
日期：2026-04-13

## 审查范围
`services/tx-trade/src/` 下所有余额/押金/支付/积分相关文件：
- `src/api/stored_value_routes.py` — 储值账户充值/消费/退款
- `src/api/banquet_deposit_routes.py` — 宴会场次定金抵扣/退款
- `src/services/banquet_payment_service.py` — 宴会在线定金支付
- `src/services/payment_saga_service.py` — 支付 Saga 补偿事务
- `src/services/payment_service.py` — 基础支付记录服务
- `src/services/coupon_service.py` — 储值卡消费（内存版）
- `src/services/enterprise_account.py` — 企业挂账额度管理（内存版）
- `src/services/cashier_engine.py` — 收银核心引擎（无感支付路径）

---

## 发现的风险

### 高风险（已修复）

| 文件 | 行号（修复前） | 问题 | 修复方式 |
|------|--------------|------|---------|
| `src/api/stored_value_routes.py` | ~323–347 | `consume` 函数：先 SELECT 查余额和冻结额，Python 层判断是否充足，再执行无条件 UPDATE 扣减。并发场景下两个请求均通过检查，导致余额扣至负数（重复扣款） | 改为原子 SQL：`UPDATE ... WHERE (balance_fen - frozen_fen) >= :amt RETURNING ...`，行数为 0 时直接返回余额不足 |
| `src/api/banquet_deposit_routes.py` | ~237–264 | `apply_deposit` 函数：先 SELECT 聚合查余额，再单独 SELECT 逐条记录，最后逐条 UPDATE。两次 SELECT 之间无行锁，并发请求读到相同的余额数据，导致同一笔定金被抵扣两次 | 合并为一次带 `FOR UPDATE` 的 SELECT，从结果集直接计算可用余额后逐条扣减 |
| `src/api/banquet_deposit_routes.py` | ~349–379 | `refund_deposit` 函数：同上模式，先 SELECT 聚合查余额校验，再单独 SELECT 并逐条 UPDATE，无行锁保护，并发退款会超出余额 | 同上：合并为一次带 `FOR UPDATE` 的 SELECT |

### 中风险（建议修复，未自动修改）

| 文件 | 行号 | 问题 | 建议 |
|------|------|------|------|
| `src/services/coupon_service.py` | ~243–290 | `deduct_stored_value`：使用内存 dict `_StoredValueStore` 存储储值卡数据，"检查余额 → 扣减"在同一 async 函数内。单进程 GIL 下相对安全，但多进程/多实例部署时无法保证原子性 | 需要接入真实数据库表，使用与 `stored_value_routes.py` 相同的原子 SQL 模式。当前 `cashier_engine.py` 的无感支付路径调用了此函数 |
| `src/services/enterprise_account.py` | ~195–328 | `check_credit` + `authorize_sign`：企业挂账额度存储在内存 dict `_enterprises`，`check_credit` 读额度、`authorize_sign` 扣额度，两步之间无锁。同理：多实例部署时存在超额签单风险 | 需接入真实数据库表，在 `authorize_sign` 中使用原子 SQL：`UPDATE ... SET used_fen = used_fen + :amt WHERE id = :eid AND (credit_limit_fen - used_fen) >= :amt` |
| `src/api/stored_value_routes.py` | ~246–298 | `recharge` 函数：UPDATE 使用 `balance_fen + :total` 相对值写法（正确），但 `balance_after` 仍由 Python 计算传入流水记录，若 UPDATE 影响行数为 0（账户被并发删除）流水仍会被写入 | 建议 `recharge` 也使用 `RETURNING` 取实际余额写流水，而非 Python 预计算值 |

### 已确认安全

| 文件 | 说明 |
|------|------|
| `src/services/payment_saga_service.py` | 有完整的 `idempotency_key` 幂等检查；`_complete_order` 使用 `AND status NOT IN ('completed','cancelled')` 的条件 UPDATE，rowcount=0 时做幂等判断，安全 |
| `src/services/banquet_payment_service.py` | `handle_payment_callback`：先检查 `status == 'paid'` 的幂等返回，再用 `AND status = 'pending'` 的条件 UPDATE，rowcount=0 抛出并发冲突异常，安全 |
| `src/services/payment_service.py` | `create_payment`/`process_refund`：使用 ORM 对象直接操作，`process_refund` 中 `amount_fen > payment.amount_fen` 检查在单事务内完成，无先查后改风险 |
| `src/api/banquet_deposit_routes.py` `collect_deposit` | INSERT 直接写入新记录，UPDATE `deposit_fen` 用 `= COALESCE(deposit_fen, 0) + :amt` 相对值累加，安全 |
| `src/api/stored_value_routes.py` `refund` | UPDATE 用 `balance_fen + :amt` 相对值累加，安全；唯一风险是流水金额由 Python 预计算，属中风险，已在上方标注 |

---

## 修复清单

- [x] `src/api/stored_value_routes.py` — `consume`：改为原子 SQL，增加 `WHERE (balance_fen - frozen_fen) >= :amt` + `RETURNING` 取实际余额
- [x] `src/api/banquet_deposit_routes.py` — `apply_deposit`：将两次 SELECT 合并为一次 `FOR UPDATE` 查询，消除读后不加锁的窗口
- [x] `src/api/banquet_deposit_routes.py` — `refund_deposit`：同上

- [ ] `src/services/coupon_service.py` — `deduct_stored_value`：迁移到真实 DB 表后使用原子 SQL（需要创始人确认迁移计划）
- [ ] `src/services/enterprise_account.py` — `authorize_sign`：迁移到真实 DB 表后使用原子 SQL（需要创始人确认迁移计划）
- [ ] `src/api/stored_value_routes.py` — `recharge`：使用 `RETURNING` 取实际余额写流水（低优先级，充值超发无资损风险）

---

## 遗留项（需创始人确认）

1. **`coupon_service.py` 储值卡内存存储**：当前整个储值卡体系（`_StoredValueStore`）是内存 dict，服务重启数据丢失。`cashier_engine.py` 的无感支付（`_try_auto_pay`）也依赖这套机制。需要确认：是保留内存版（仅用于演示/测试）还是尽快接入 `stored_value_accounts` 表（已有真实迁移）？若接入，`deduct_stored_value` 应改为调用 `stored_value_routes.py` 中已修复的原子 SQL 路径。

2. **`enterprise_account.py` 企业挂账内存存储**：同上，`_enterprises` 和 `_sign_records` 是内存 dict，服务重启数据丢失。需确认是否纳入近期迁移计划。

3. **`banquet_deposit_routes.py` `FOR UPDATE` 兼容性**：`FOR UPDATE` 要求数据库连接处于显式事务中。当前代码使用 `get_db_with_tenant` 依赖注入，需确认该依赖函数是否已开启显式事务（SQLAlchemy AsyncSession 默认开启隐式事务，理论上兼容）。如果使用连接池的自动提交模式则需要调整。

---

## 修复验证建议（Tier 1 标准）

```python
# 建议在 test_stored_value.py 中补充并发测试用例
async def test_concurrent_consume_no_overdraft():
    """100 个并发请求扣减同一账户余额，最终余额不得为负"""
    # 账户余额 500 分，50 个请求各扣 20 分（总需求 1000 分）
    # 预期：恰好 25 个成功，25 个返回余额不足，最终余额 = 0（不得为负）

async def test_concurrent_deposit_apply_no_double_deduct():
    """同一场次定金并发抵扣，不得出现重复扣减"""
```
