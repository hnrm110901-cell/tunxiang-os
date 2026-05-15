# Tier 1 函数级 Review Checklist（reviewer 视角 v1）

**版本**：v1 (2026-05-15)
**适用对象**：§19 reviewer / verifier (PR 审查方)
**适用范围**：触及 CLAUDE.md §17 Tier 1 红线的 PR（订单状态机 / 支付 Saga / RLS / POS 写入 / 存酒押金 / 全电发票 / 库存增减）
**与 CLAUDE.md §19 § 20 关系**：§19 § 20 是**作者侧**自检 + 测试标准；本 checklist 是**reviewer 侧**核查清单，互补不重复。

---

## 0. 何时强制走本 checklist

满足任一即必须按本 checklist 逐条 grep / 通读 / 核对：

- 改动文件命中 `TIER1_SOURCE_PATTERNS`（CI workflow `tier1-gate.yml` 配置）
- 改动文件含 `cashier_engine` / `order_service` / `payment_saga_service` / `invoice_service` / `wine_storage` / `auto_deduction` / `inventory_io` / `stored_value_service` / `stocktake_service`
- 改动新增 / 修改任何 SQL UPDATE / DELETE 语句
- 改动新增 / 修改任何状态机 transition（订单 status / saga step / invoice status / wine_storage status / 调研 status 等）

**铁律**：本 checklist 任一条目漏检 = §19 必须打回。不接受"自评通过 + 测试绿 + CI 绿"作为可以跳条目的理由（PR #419 / PR #660 / PR #665 / PR #668 教训）。

---

## 1. SELECT-then-UPDATE 行锁核查

### 1.1 必查项

| 检查 | 命令 / 方法 | 通过标准 |
|---|---|---|
| 所有 mutation 路径的 SELECT 是否带行锁 | `rg -n "with_for_update|FOR UPDATE" <文件>` | mutation 入口 SELECT 100% 有锁 |
| read-only 入口是否**未误加**行锁 | 通读 read-only route handler | 不持有 `lock=True` |
| 公用 `_get_X` helper 是否用 `lock: bool = False` kwarg | 通读 helper 签名 | 默认 `False`，mutation caller 显式传 `lock=True` |
| rebase 后所有 caller 是否仍传 `lock=True` | `rg -n "_get_X\(" services/` | 不能 silent drop `lock=True`（feedback_post_rebase_caller_audit.md） |

### 1.2 多锁场景死锁防范

| 场景 | 必须 | 反例 |
|---|---|---|
| 同一事务锁两个相同类型对象（如 transfer 双桌台 / 双卡） | `sorted(items, key=lambda x: str(x.id))` 强制锁顺序 | ABBA 死锁（§17-C 教训） |
| 跨 dish 锁同 ingredient（auto_deduction.deduct_for_order） | BOM 行预聚合 / 排序 | 同 ingredient 多次锁请求（#549 未决） |
| `_get_order(lock=True)` 与 `update_item` 同事务 | 锁顺序统一上移（先锁 order 再锁 item） | ABBA（§17-C round-1 P0） |

### 1.3 raw SQL 路径

raw SQL `text()` 末尾必须显式加 `FOR UPDATE` 或 `FOR UPDATE SKIP LOCKED`（payment_saga.recover_pending_sagas 模式）。
ORM `select(Model).with_for_update()` 与 raw SQL `text("... FOR UPDATE")` 互不通用，**逐路径独立核查**。

### 1.4 行锁不能跨步骤的场景

| 模式 | FOR UPDATE 不够 | 必须 |
|---|---|---|
| Saga S1 校验 → S2 外部 HTTP → S3 落库 | FOR UPDATE 在 S2 commit 时释放 | 改条件 UPDATE 占位 / advisory lock（issue #537） |
| 跨 connection / 跨 worker | FOR UPDATE 仅当前连接 | SKIP LOCKED + `recover_pending_sagas` 模式 |

### 1.5 参考实现

- 最严谨范本：`services/tx-member/stored_value_service.py`（11 处 `.with_for_update()` + 2 卡同锁排序）
- 桌台锁 + 终态保护：PR #652 / #653 / #655 `services/tx-trade/src/services/cashier_engine.py`
- raw SQL 模式：PR #553 `services/tx-trade/src/services/payment_saga_service.py`

---

## 2. 状态机 UPDATE 乐观锁守卫

### 2.1 必查项

任何 `UPDATE ... SET status = :new_status` 必须满足：

```sql
UPDATE table
SET status = :new_status, ...
WHERE id = :id
  AND status = :current_status   -- ← 乐观锁守卫，不可缺
```

并在代码层检查 rowcount：

```python
result = await db.execute(stmt)
if result.rowcount == 0:
    raise ValueError("status transition raced — 并发改写")
```

### 2.2 不同场景如何选

| 场景 | 选 | 原因 |
|---|---|---|
| 高频资金 / 桌台 / 库存 race | SELECT FOR UPDATE | 强一致，序列化所有竞争 |
| 低频 status workflow（verified 训练池 / approved 审批 / paid 收银） | 乐观锁（AND status = :current） | 不阻塞读，并发 race 直接抛错 |
| Saga 跨步骤 | 条件 UPDATE 占位 | FOR UPDATE 跨步骤无效 |

（feedback_status_machine_optimistic_lock.md / PR #668 教训）

### 2.3 必须配套回归测试

```python
# mock 测试：第二次同事务 transition 必须抛错
async def test_status_transition_race():
    db.execute = AsyncMock(return_value=MagicMock(rowcount=0))
    with pytest.raises(ValueError):
        await service.transition_status(...)
```

---

## 3. 异常处理核查（asyncpg + pydantic V2）

### 3.1 asyncpg IntegrityError 后必须 rollback + 重设 RLS

```python
try:
    await db.execute(insert_stmt)
    await db.commit()
except asyncpg.IntegrityError:
    await db.rollback()        # ← rollback 后 RLS local config 丢失
    await _set_tenant(db, tenant_id)   # ← 必须重设
    raise UserFacingError(...)
```

reviewer 必查：
- [ ] `except asyncpg.IntegrityError` 后是否有 `await db.rollback()`
- [ ] rollback 后是否调用 `_set_tenant` / `set_config('app.current_tenant', ..., true)` 重设
- [ ] 同一事务后续 `await db.execute()` 是否会触 `InFailedSqlTransactionError`

（PR #660 round-2 P0-3 教训 / feedback_asyncpg_rollback_after_integrity_error.md）

### 3.2 pydantic V2 ValidationError ≠ ValueError 子类

```python
# ❌ 漏抓
try:
    parsed = MyModel(**raw)
except ValueError:
    raise UserFacingError(...)

# ✅ 显式 catch
try:
    parsed = MyModel(**raw)
except pydantic.ValidationError as exc:
    raise ValueError(str(exc))  # 让 FastAPI 转 422
```

（PR #665 round-1 P1-2 教训 / feedback_pydantic_v2_validation_error.md）

### 3.3 fail-open vs fail-closed

| 路径 | 策略 | 必须 |
|---|---|---|
| 资金 / 食安 / 合规硬约束 | **fail-closed** | 异常向上抛，让事务回滚 |
| 辅助标识 infra（doc_number / SKU 编码 / 可读编号） | **fail-open + structlog warn + exc_info=True + Prometheus counter** | 静默 fallback NULL 不阻塞 Tier 1 |
| 配置错误（如 pydantic ValidationError 调 deduct_for_dish） | **fail-loud** | 不放 fail-open 列表，让 422 暴露 |

（feedback_graceful_degradation_pattern.md）

### 3.4 broad except 强制 refactor

CLAUDE.md §14 强制条款：触碰任何 `except Exception:` / `except:` 时必须替换为具体异常类型组合（如 `except (ImportError, AttributeError)`）。reviewer 必查 PR diff 中本 PR 引入的 broad except 数 = 0。

---

## 4. RLS 多租户隔离核查

### 4.1 必查项

- [ ] 新增 mutation 路径是否在事务开始时调用 `_set_tenant(db, tenant_id)`
- [ ] rollback 后是否重设 RLS（参见 §3.1）
- [ ] dynamic SQL fragments（`UPDATE ... SET col1=:v1` 拼接）是否仍走 RLS policy 校验
- [ ] 测试是否覆盖 **cross-tenant 反测**（tenant_A 不能读 tenant_B 数据）+ **same-tenant 反测**（业务隔离正确）

### 4.2 RLS 严格门禁误判

alembic migration docstring / 注释禁止出现 `CREATE TABLE <name>` 字面文字（feedback_rls_gate_regex_false_positive.md）。改写为"无对应建表 migration"避开。

### 4.3 参考审计

- `docs/security/tier1-row-lock-audit-2026-05.md`（全 16 服务 24 漏锁 / 14 P0）
- workflow `rls-runtime-p0-pg-tests.yml` 7 P0 表反测（注：当前为预存漂移，不影响 review 判断）

---

## 5. 测试核查

### 5.1 测试必须存在

CI gate `源改动必须配对测试改动` 是真门禁。reviewer 必查：

- [ ] 每条新加 mutation 路径都有 mock 测试
- [ ] 状态机 transition 都有 race 测试（mock rowcount=0）
- [ ] 异常分支（IntegrityError / ValidationError / 状态非法）都有断言路径
- [ ] 文件命名 `test_<service>_tier1.py` 触发 tier1-gate paths

### 5.2 mock 局限 vs 真 PG 反测

| 适用 | mock | 真 PG (pytest-postgresql) |
|---|---|---|
| 业务分支覆盖 | ✅ 主选 | 备 |
| asyncpg state machine（IntegrityError → InFailedSqlTransactionError） | ❌ 绕过 | ✅ 必须（PR #660 实证 mock 没暴露 P0-3） |
| 锁顺序 / ABBA 死锁 | ❌ | ✅ 必须（§17-C 范本） |
| RLS policy 反测 | ❌ | ✅ 必须 |

### 5.3 常见测试陷阱

- `_ensure_stub("shared")` 注入空 sys.modules 包 → 跨 test 文件污染（feedback_pytest_stub_setdefault_pitfall.md）。改 `pytest.skip(allow_module_level=True) + sys.version_info < (3, 10)`
- SQL multi-space alignment 让 mock substring 失配 → 用参数名匹配而非单空格 substring
- Python 3.11 `MagicMock().rowcount = 0` 链式 return_value 不稳 → 用 plain class `_FakeResult`
- xfail strict 标记在 fix-after-cleanup PR 必须同步移除（PR #658 issue #559 教训）

### 5.4 CI 真门禁 vs 漂移

| 真门禁（reviewer 必须等绿） | 漂移噪音（reviewer 可忽略） |
|---|---|
| `Tier 1 门禁判定` | `python-lint-test (*)` 9 个全 PR fail |
| `Run Tier 1 ...` | `Ruff Lint & Format` |
| `源改动必须配对测试改动` | `Test Changed Services` |
| `RLS 严格门禁` | `frontend-build` |
| `Alembic Chain Integrity` | `TypeScript Check (*)` |

（feedback_tunxiang_ci_gates.md）

---

## 6. 事件 / 外部 IO 核查

### 6.1 emit_event 旁路语义

```python
try:
    await event_bus.emit(...)
except (ImportError, AttributeError):
    log.warning("event_emit_failed", exc_info=True)
```

reviewer 必查：
- [ ] 事件发射失败**不阻塞**主业务（旁路）
- [ ] 但失败必须 `structlog.warning + exc_info=True`，禁止 silent `pass`（issue #663 baseline）
- [ ] 金额相关事件 payload 用**分（整数）**，不用 Decimal / float

### 6.2 跨服务调用 Outbox 兜底

Tier 1 跨服务通知（如 GL 通账 / 库存扣减）必须走 Outbox Pattern + relay worker（W3 路线图），而非直接 HTTP 调用。

### 6.3 持锁调外部 HTTP 严禁

`get_invoice_status` 持锁调诺诺 HTTP 拆三段事务（issue #543）。reviewer 必查 mutation 路径锁定窗口内**无任何外部 IO**。

---

## 7. 类型边界

### 7.1 nullable 字段 NOT NULL vs NULLABLE 语义

PATCH 路径 `update_X` 时：

```python
# pydantic model_dump(exclude_unset=True) 区分未提供 vs 显式 None
patch = body.model_dump(exclude_unset=True)
if "field" in patch:
    # 用户显式设值 — NULLABLE 字段允许 None
    ...
```

NOT NULL 字段在 PATCH 中**不可显式设 None**，否则 asyncpg IntegrityError 500（PR #665 round-1 P1-1 教训）。

### 7.2 金额单位

资金路径金额 100% 用**分（整数）**，禁止 Decimal / float（PR #271 / #272 ship 模式）。

---

## 8. 不在本 checklist 范围

| 主题 | SoT |
|---|---|
| 作者侧 Tier 1 提交前自检 | CLAUDE.md §19 |
| Tier 1 测试标准（餐厅场景命名 / TDD） | CLAUDE.md §20 |
| Commit message + 原子化 | CLAUDE.md §21 |
| 性能 P99 < 200ms 验收 | CLAUDE.md §22（DEMO 验收门槛） |
| Outbox + GL 内核设计 | 战略 5/12 §3 W3-W4 + 举措 2/3 |
| Ontology 层冻结 | CLAUDE.md §17 |

---

## 9. 引用 / 实战教训 SoT

| 教训 | 来源 |
|---|---|
| SELECT-then-UPDATE 全 16 服务审计 24 漏锁 / 14 P0 | `docs/security/tier1-row-lock-audit-2026-05.md` |
| 桌台 FOR UPDATE + 双锁排序 + TableOccupiedError | PR #652 §17-A |
| 终态保护 + 3B 幂等释放 + state_machine 合法转移 | PR #653 §17-B |
| OrderItem FOR UPDATE 4 路径 + ABBA 锁顺序统一 | PR #655 §17-C |
| asyncpg IntegrityError rollback + RLS 重设 | PR #660 round-2 P0-3 |
| pydantic V2 ValidationError ≠ ValueError 子类 | PR #665 round-1 P1-2 |
| 状态机 UPDATE 加乐观锁守卫 | PR #668 round-1 P1-1 |
| nullable 字段 PATCH 语义 | PR #665 round-1 P1-1 |
| 持锁调外部 HTTP 拆三段事务 | issue #543 |
| PaymentSaga S1→S3 跨步骤锁机制 | issue #537 |
| wine_storage 双轨 SoT 创始人决策 | issue #535 |

---

## 10. 变更记录

| 版本 | 日期 | 变更 | 触发 |
|---|---|---|---|
| v1 | 2026-05-15 | 初版 (W2.4) | 战略 5/12 §6 工程治理体系 + 5/14-5/15 §17 + PRD-08/11/13 reviewer 实战沉淀 |
