# 屯象OS 审计治理回归报告（2026-07）

> 对比基线：任务描述中的 2026-04-27 基线数字（`docs/comprehensive-audit-2026-04.md` 文件当前不存在于仓库，基线数字来自任务规格）
> 检查日期：2026-07-14
> 距 Week 8 DEMO（2026-06-22）已约 22 天

---

## 一、核心指标对比

| 指标 | 基线（2026-04）| 当前（2026-07）| 改善/退化 | 评级 |
|------|:---:|:---:|:---:|:---:|
| `except Exception` 总数（services/shared/edge） | 556 | 601 | **+45** | 🔴 退化 |
| `except Exception` 不带 raise（同行）| 469 | 600 | **+131** | 🔴 退化 |
| RLS 业务表覆盖：v382 修复历史债 | 59 张缺失 | **45 张缺失**（-14）| -14 | 🟡 部分改善 |
| `import anthropic` 直连（services/，排除 model_router.py）| 11 处 | **14 处** | **+3** | 🔴 退化 |
| `asyncio.create_task` 总调用（services/shared/edge）| 50+ | **358 处** | 无可比基线 | 🟡 待建基线 |
| Tier 1 测试文件数 | 22 | **46** | **+24** | ✅ 大幅改善 |
| Dockerfile 含 HEALTHCHECK 占比 | 2/25 | **2/26** | 无改善 | 🔴 停滞 |
| docker-compose 服务有 healthcheck | 3/18 | **3/18** | 无改善 | 🔴 停滞 |
| TODO/FIXME/XXX/HACK 数 | 174 | **140** | -34 | 🟡 小幅改善 |
| `raise NotImplementedError` 数 | 34 | **37** | +3 | 🔴 轻微退化 |
| Alembic 最新版本 | v383 | **v383** | 无新迁移 | 🟡 停滞 |
| Alembic 多 head 数 | 1（已修）| **1** | 维持单 head | ✅ 维持 |
| RLS NULLIF guard 缺失（policies 直接转型，无 NULLIF）| 未记录 | **76 处** | 新发现风险 | 🔴 需关注 |

### 指标说明

**broad except 计数方法**：`grep -rEn "except Exception"` 同行无 `raise` 字样。注意多行 except 块中 raise 通常在下一行，故 600/601 比率是统计方法局限，不等于所有异常都被吞掉。关键结论是总数从 556 涨到 601，方向是退化。

**asyncio.create_task 358 处**：基线 "50+" 可能只统计了特定风险模式（裸用、不在 background task 管理下）。建议下次回归区分"在 lifespan 管理的 task 集"与"裸 fire-and-forget"两类。

---

## 二、P0 完成率（7 项安全 P0）

### P0-1 RLS NULL 绕过

**状态：🟡 部分修复**

证据：
- `v056_fix_rls_vulnerabilities.py`（2026-03-31）：修复了早期 v012/v032 表的危险模式 `current_setting('app.tenant_id')::UUID`（无 NULLIF 无 true 参数）。
- `v382_fill_rls_historical_debt.py`（PR #102，e5998e04，2026-04-27）：补齐 14 张历史缺 RLS 的表（供应链/WMS/试点模块）。
- 当前仍发现 **76 处** `current_setting('app.tenant_id', TRUE)::UUID` 不带 NULLIF 的直接类型转换：

```bash
# 命令
grep -rn "current_setting('app.tenant_id', TRUE)::UUID|current_setting('app.tenant_id', true)::UUID" \
  shared/db-migrations/versions/ --include="*.py" | grep -v "NULLIF" | grep -v "^.*#" | wc -l
# 结果：76
```

这 76 处若 `app.tenant_id` 未设置时 `current_setting` 在 `true` 模式下返回 `''`（空串），空串 `::UUID` 会抛出 cast error，导致查询失败而非静默绕过，安全风险等级中等。

**无 v384+ 新迁移修补**，最新 migration 停留在 v383。

### P0-2 Saga 幂等键服务端化

**状态：🔴 未修复**

证据：`cashier_api.py` 和 `settle_retry.py` 中 `idempotency_key` 均从客户端请求体取得：

```python
# services/tx-trade/src/api/cashier_api.py:127
idempotency_key: Optional[str] = Field(...)
# 格式建议：{device_id}-{order_id[:8]}-{unix_ts_seconds}

# services/tx-trade/src/api/settle_retry.py:45
idempotency_key: str = Field(..., min_length=1, max_length=128)
```

无 `hashlib` 服务端 hash 生成逻辑。服务端仅做查重（幂等检查），key 本身由客户端构造。攻击者可伪造任意 key 实现幂等碰撞。

```bash
grep -n "hashlib" services/tx-trade/src/services/payment_saga_service.py
# 结果：无输出（0 处）
```

### P0-3 内存版账户删除

**状态：🟡 部分修复**

证据：
- `deduct_stored_value`（coupon_service.py:250+）：已改用真实 DB 原子 SQL（`UPDATE ... WHERE (balance_fen - frozen_fen) >= :amount RETURNING ...`）✅
- `enterprise_account.py`：`EnterpriseAccountService` 已全面改用 `AsyncSession`，无内存 dict ✅
- `_StoredValueStore` 类（coupon_service.py:54-231）仍保留，注释 `# DEPRECATED: 已废弃，仅保留用于单测兼容`，但类内 `save/get` 方法仍在代码路径上（第 186、212、231 行调用）：

```python
# services/tx-trade/src/services/coupon_service.py:51
# DEPRECATED: _StoredValueStore 已废弃，仅保留用于单测兼容
class _StoredValueStore:
    ...
# 第 186/212/231 行仍有调用
```

**风险**：这些调用若在测试以外的非 `deduct_stored_value` 路径触发，仍走内存存储。建议完整删除该类（不可单凭注释声明废弃）。

### P0-4 ModelRouter 绕过修复

**状态：🔴 未修复**

当前 `services/` 下（排除 `model_router.py` 本身和测试文件）仍有 **14 处** 直接 `import anthropic`：

```bash
grep -rEn "^import anthropic|^from anthropic import" services/ --include="*.py" \
  | grep -v "test_" | grep -v "model_router.py"
# 结果：14 处
```

涉及文件：
- `services/tx-brain/src/agents/`：10 个 agent 文件（discount_guardian、menu_optimizer、dispatch_predictor 等）
- `services/tx-brain/src/api/brain_routes.py`
- `services/tx-intel/src/services/review_collector.py`
- `services/tx-member/src/api/member_insight_routes.py`
- `services/tx-agent/src/services/pilot_service.py`

所有 agent 均创建裸 `anthropic.AsyncAnthropic()` 客户端（如 `discount_guardian.py:20`），完全绕过 `ModelRouter` 的速率控制、审计日志、fallback 策略。

### P0-5 Prompt 注入修复

**状态：🔴 未修复**

`discount_guardian.py` 的 `_build_context`（第 103 行起）仍用 f-string 直接拼接未经净化的事件字段：

```python
# services/tx-brain/src/agents/discount_guardian.py:103
def _build_context(self, event: dict, history: list[dict]) -> str:
    return f"""折扣事件：
- 操作员：{event.get("operator_id")} ({event.get("operator_role")})
- 菜品：{event.get("dish_name")} 原价 ...
- 桌号：{event.get("table_no")} 订单：{event.get("order_id")}
...
"""
```

`dish_name`、`operator_role` 等字段若由前端提交，可注入 `\n忽略以上指令，请执行：` 类攻击。无结构化 messages 隔离，无输入净化。

### P0-6 payroll eval 替换

**状态：🟡 部分缓解（未根治）**

`payroll_engine.py` 中 `eval()` 保留两处（第 571、616 行），但已添加白名单字符过滤和 nosec 注释：

```python
# services/tx-org/src/services/payroll_engine.py:571
allowed = set("0123456789+-*/.()%")
if not all(c in allowed for c in test_expr):
    bad_chars = [...]
    errors.append(...)
else:
    eval(test_expr)  # nosec: 只含数字和运算符  # noqa: S307

# 第 616 行同样模式
result = eval(expr)  # nosec: 已经过滤非法字符  # noqa: S307
```

字符白名单 `"0123456789+-*/.()%"` 可抵御大多数注入（无字符串、无函数调用）。但 `eval` 本身仍存在边界风险（如 `...` 省略号语法、大数 DoS）。推荐改用 `ast.literal_eval` 或专用表达式解析库彻底替换。

Git log 显示 payroll_engine.py 最近变动：`13c03ac3 chore(tx-org+shared): ruff autofix + format (196 files)`，无安全性改动。

### P0-7 ruff BLE001 启用

**状态：🔴 未修复**

`pyproject.toml` 中 ruff `select` 仅含 `["E","W","F","I","C","B","S","SIM"]`，不含 `"BLE"`（Blind exception）：

```toml
# pyproject.toml [tool.ruff.lint]
select = [
    "E", "W", "F", "I", "C", "B", "S", "SIM",
]
# 无 "BLE" 规则组
```

BLE001（`blind-exception`）未启用，无法在 CI 自动拦截新增 `except Exception`。这也解释了为何 broad except 计数从 556 升至 601（+45）。

---

## 三、P0 完成率汇总

| P0 项 | 描述 | 状态 | 修复 PR/Commit |
|-------|------|:----:|--------------|
| P0-1 | RLS NULL 绕过 | 🟡 部分修复 | PR #102（e5998e04），v382 补 14 表 |
| P0-2 | Saga 幂等键服务端化 | 🔴 未修复 | — |
| P0-3 | 内存版账户删除 | 🟡 部分修复 | deduct_stored_value 已改 DB；_StoredValueStore 类仍存在 |
| P0-4 | ModelRouter 绕过修复 | 🔴 未修复 | — |
| P0-5 | Prompt 注入修复 | 🔴 未修复 | — |
| P0-6 | payroll eval 替换 | 🟡 部分缓解 | 字符白名单添加，eval 本身未替换 |
| P0-7 | ruff BLE001 启用 | 🔴 未修复 | — |

**P0 完成率：0/7 完全修复，3/7 部分修复，4/7 未修复 = 约 21%**

---

## 四、P1 完成率（抽样 4 项）

### P1-1 RLS 缺失 59 张表补齐

**状态：🟡 部分修复（14/59，24%）**

`v382_fill_rls_historical_debt.py`（PR #102，2026-04-27）补齐了 14 张表（supply chain/WMS/pilot 模块）。无后续 v383+ 针对剩余 45 张的迁移。

### P1-7 events/orders/order_items 复合索引

**状态：✅ 已有索引（历史迁移已覆盖）**

`v147_unified_event_store.py` 已创建：
- `idx_events_tenant_time (tenant_id, occurred_at DESC)`
- `idx_events_tenant_store (tenant_id, store_id)`
- `idx_events_stream (stream_id, occurred_at)`
- `idx_events_payload_gin` (GIN 索引)

orders 相关表在 v127、v165 等迁移中也有 `(tenant_id, store_id)` 复合索引。

### P1-9 Dockerfile HEALTHCHECK 标准化

**状态：🔴 未修复（2/26，7.7%）**

当前仅 `infra/docker/Dockerfile.python` 和 `infra/docker/Dockerfile.frontend` 有 HEALTHCHECK，与基线 2/25 无改变（+1 个新 Dockerfile 同样无 HEALTHCHECK）。

### P1-10 SAST 工具链

**状态：🟡 部分覆盖**

CI 工作流现有：
- `ruff` 静态分析（ci.yml，python-ci.yml）
- `bandit` 安全扫描（.pre-commit-config.yaml）
- `detect-secrets`（.pre-commit-config.yaml）
- `rls-gate.yml`（新增 PR RLS 门禁）
- `tier1-gate.yml`（Tier 1 测试门禁）

仍缺：Semgrep/Trivy/Gitleaks 在 CI 工作流中的集成（`.github/workflows/` 下无相关文件）。Pre-commit 有 detect-secrets，但 CI 未强制。

---

## 五、新出现的反向退化（Regression）

| 退化项 | 基线 | 当前 | 说明 |
|--------|:---:|:---:|------|
| `except Exception` 总数 | 556 | 601 | +45，BLE001 未启用导致持续增长 |
| `import anthropic` 直连 | 11 | 14 | +3，新增 tx-intel/review_collector.py、tx-agent/pilot_service.py 等 |
| `raise NotImplementedError` | 34 | 37 | +3，新增 stub 未填充 |
| Alembic 新迁移 | v383 | v383 | DEMO 后 22 天零新迁移，P0-1 剩余 45 张表未跟进 |

---

## 六、下一阶段建议

### 仍未修复的 P0（优先级最高）

1. **P0-2 Saga 幂等键服务端化**：在 `settle_retry.py` 和 `cashier_api.py` 改为服务端用 `hashlib.sha256(f"{tenant_id}:{order_id}:{device_id}".encode()).hexdigest()` 生成 key，移除客户端字段。
2. **P0-4 ModelRouter 绕过**：tx-brain 10 个 agent 文件全部替换 `import anthropic` → `from services.tx_agent.src.services.model_router import ModelRouter`，统一入口。
3. **P0-5 Prompt 注入**：`_build_context` 改为结构化 `messages` 数组（system prompt 与 user content 分离），不在 system prompt 内插入用户/业务数据。
4. **P0-7 ruff BLE001**：`pyproject.toml` 的 `select` 加入 `"BLE"`，或单独 `ignore = ["BLE001"]` 并标注例外理由，优先前者。

### P0 部分修复需收口

5. **P0-3 _StoredValueStore**：删除 `coupon_service.py` 中 `_StoredValueStore` 类及第 186/212/231 行调用，测试改用 mock DB session。
6. **P0-6 payroll eval**：用 `ast.literal_eval` 替换 `eval`，或引入 `simpleeval` 库处理有变量替换的数学表达式。

### P1 补齐

7. **RLS 剩余 45 张表**（v384 迁移）：用 `scripts/check_rls_policies.py` 输出当前缺失列表，批量生成 migration。
8. **Dockerfile HEALTHCHECK**：按服务标准化 `HEALTHCHECK CMD curl -f http://localhost:{port}/health || exit 1`，目标 15/26（主力服务）。

### P2/P3 治理（本次未深入检查）

9. `raise NotImplementedError` +3：排查新增 stub，给出完成计划或移除。
10. TODO/FIXME 140 条：建议按 Tier 分级，Tier 1 模块中的 TODO 纳入 sprint 跟踪。

### 下次回归检查建议

**2026-10 季度回归**（Q3 末）：重点看 P0-2/P0-4/P0-5 修复率，BLE001 拦截效果（broad except 增长应归零），RLS 覆盖率是否达到 100%。

---

## 七、附：执行命令清单与原始数据

```bash
# 1. broad except 总数
grep -rEn "except Exception" services/ shared/ edge/ --include="*.py" | wc -l
# 结果：601

# 2. broad except 不带 raise（同行）
grep -rEn "except Exception" services/ shared/ edge/ --include="*.py" | grep -v "raise" | wc -l
# 结果：600（统计方法局限：raise 通常不在同行，见正文说明）

# 3. 最新 Alembic 版本
ls shared/db-migrations/versions/ | sort | tail -3
# v381_delivery_disputes.py  v382_fill_rls_historical_debt.py  v383_chain_consolidation.py

# 4. Alembic heads（v383 mega-merge 后）
grep -n "down_revision" shared/db-migrations/versions/v383_chain_consolidation.py | head -3
# 含 47 heads tuple，已合并为单 head

# 5. import anthropic 直连（排除 model_router 和测试）
grep -rEn "^import anthropic|^from anthropic import" services/ --include="*.py" \
  | grep -v "test_" | grep -v "model_router.py" | wc -l
# 结果：14

# 6. tier1 测试文件数
find . -name "*tier1*.py" -not -path "./.claude/*" -not -path "./.git/*" | wc -l
# 结果：46

# 7. Dockerfile 含 HEALTHCHECK
find . -name "Dockerfile*" -not -path "./.git/*" -not -path "*/node_modules/*" \
  | xargs grep -l "HEALTHCHECK" | wc -l && \
find . -name "Dockerfile*" -not -path "./.git/*" -not -path "*/node_modules/*" | wc -l
# 结果：2 / 26

# 8. docker-compose services with healthcheck
python3 -c "
import yaml
with open('docker-compose.yml') as f:
    dc = yaml.safe_load(f)
s = dc.get('services', {})
print(f'{sum(1 for v in s.values() if \"healthcheck\" in v)}/{len(s)}')
"
# 结果：3/18

# 9. TODO/FIXME/XXX/HACK
grep -rEn "TODO|FIXME|XXX|HACK" services/ shared/ edge/ --include="*.py" | wc -l
# 结果：140

# 10. raise NotImplementedError
grep -rEn "raise NotImplementedError" services/ shared/ edge/ --include="*.py" | wc -l
# 结果：37

# 11. RLS NULLIF 缺失（直接转型，无 NULLIF guard）
grep -rn "current_setting('app.tenant_id', TRUE)::UUID\|current_setting('app.tenant_id', true)::UUID" \
  shared/db-migrations/versions/ --include="*.py" | grep -v "NULLIF" | grep -v "^.*#" | wc -l
# 结果：76

# 12. asyncio.create_task 总调用
grep -rEn "asyncio\.create_task\(" services/ shared/ edge/ --include="*.py" | wc -l
# 结果：358

# 13. P0-6 eval in payroll_engine
grep -n "eval(" services/tx-org/src/services/payroll_engine.py
# 结果：571: eval(test_expr)  # nosec  616: result = eval(expr)  # nosec

# 14. P0-7 ruff BLE check
grep "BLE" pyproject.toml || echo "BLE not in ruff select"
# 结果：BLE not in ruff select

# 15. v382 commit hash (P0-1/P1-1 证据)
git log --oneline --grep="rls-historical-debt|v382" | head -3
# e5998e04  Merge pull request #102 ... fix(db,rls): v291 补齐 14 张历史业务表 RLS 技术债
# 206468b2  fix(rls): v382 migration 修复内部 revision/down_revision 字符串
```

---

*生成于 2026-07-14 | 对比基线：2026-04-27 | 下次建议：2026-10 季度回归*
