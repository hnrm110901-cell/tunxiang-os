# Plan — silent failure governance Wave 1 sub-A (tx-supply 9 业务 silent)

- **创建**: 2026-05-17 W2 起手
- **关联 issue**: #663 silent failure 治理 sprint
- **战略锚点**: 5/12 战略 §6 治理四件套 W2-W3 sprint
- **Tier 1 邻接 explicit-ask 第 37 例** (5/16 PR #734 第 36 例后)
- **Single-track 严肃推** (per user W2 决策)

## 1) Requirements Summary

修 tx-supply 9 个业务侧 silent failure (3 routes + 6 services), 不修 8 个 tests (sub-C T3 follow-up). PR 整体走 Tier 1 邻接 explicit-ask (因 3 site 触食安/毛利/库存盘亏审计硬约束).

- **In scope** (9 业务 site):
  | # | site | line | 现状 | 触约束 |
  |---|---|---:|---|---|
  | 1 | `api/voice_count_routes.py` | 167 | `except ValueError: pass` | — (中文数字 fast-path probe) |
  | 2 | `api/deduction_routes.py` | 247 | `except CaseValidationError: pass` | **Tier 1 邻接** (库存盘亏审计) |
  | 3 | `api/smart_procurement_routes.py` | 234 | `except SQLAlchemyError: pass` | **Tier 1 邻接** (供应商推荐 → 触毛利) |
  | 4 | `services/auto_procurement.py` | 414 | `except Exception: pass` (§13 违反) | T2 (供应商评分排序辅助) |
  | 5 | `services/auto_procurement.py` | 584 | `except ImportError: pass` | T3 (test isolation) |
  | 6 | `services/expiry_monitor.py` | 45 | `except (JSONDec, TypeError, ValueError): return None` | **Tier 1 邻接** (食安检测器) |
  | 7 | `services/theoretical_cost.py` | 232 | `except (ImportError, AttributeError): return None` | T2 邻接 (毛利辅助) |
  | 8 | `services/actual_cost.py` | 231 | 同 #7 | T2 邻接 (毛利辅助) |
  | 9 | `services/actual_cost.py` | 260 | 同 #7 | T2 邻接 (毛利辅助) |

- **Out of scope** (sub-C T3 follow-up issue):
  - 8 个 tests/ silent (`except ValueError: pass` → `pytest.raises(ValueError)` 改造)

## 2) Per-site Fix 模式表

| # | site | fix 模式 | 关键改动 |
|---|---|---|---|
| 1 | `voice_count_routes.py:167` | **refactor 删 try/except** | 替换为 `if cn_str.lstrip("-").isdigit(): return int(cn_str)` — 显式判断, 不靠 exception control flow |
| 2 | `deduction_routes.py:247` | **(b) structlog.warn + exc_info** | fire-and-forget 仍 fail-open (不阻塞 stocktake 主流程), 但 `log.warning("auto_create_loss_case_failed", stocktake_id=..., tenant_id=..., exc_info=True)` |
| 3 | `smart_procurement_routes.py:234` | **(b) structlog.warn + exc_info + Prom counter** | 仍 return None (memory `feedback_graceful_degradation_pattern.md` 辅助标识 fail-open), 但 `log.warning("supplier_history_lookup_failed", ingredient_id=..., tenant_id=..., exc_info=True)` + counter inc |
| 4 | `auto_procurement.py:414` | **(b) narrow except + structlog.warn** | `except Exception` → `except (SQLAlchemyError, KeyError, TypeError, ValueError)`, 加 `log.warning("supplier_score_calc_failed", ...)` — §13 违反闭合 |
| 5 | `auto_procurement.py:584` | **(c) graceful + structlog.debug** | `from .requisition` ImportError 是 test isolation 预期, 不报 warn, 但加 `log.debug("requisition_module_unavailable_using_mock", ...)` 可追踪 |
| 6 | `expiry_monitor.py:45` | **(b) structlog.warn + exc_info + Prom counter** | 食安路径, 仍 return None (memory pattern 允许), 但必须 `log.warning("expiry_notes_parse_failed", batch_id=..., exc_info=True)` + counter `tx_supply_silent_fallback_total{site="expiry_monitor.parse_notes"}` |
| 7 | `theoretical_cost.py:232` | **(c) graceful + structlog.warn + Prom counter** | 毛利辅助, 仍 return None, 加 `log.warning("bom_lookup_dep_failed", dish_id=..., exc_info=True)` + counter |
| 8 | `actual_cost.py:231` | 同 #7 | counter site="actual_cost.last_purchase" |
| 9 | `actual_cost.py:260` | 同 #7 | counter site="actual_cost.ledger_price" |

## 3) Acceptance Criteria (testable)

1. `python3 scripts/code-fact-scan.py` tx-supply silent_failure_count **24 → 16** (本 PR 修 9 业务 site; 剩 16 = 10 tests + 4 graceful asyncio + 1 projector 真修法 + 2 metrics 批准 fail-open 模式; sub-C/D follow-up tracks). **真实 baseline + 5/17 §19 自查二次校正**: (1) W20 5/15 报 18, origin/main eda578a7 实测 24 (PR #698/#718/#734 ship 时 introduce 8 silent: main.py:122/142 lifespan asyncio.* + **metrics.py:88 + :130** 两个 fail-open 守护层 + projectors/index_split.py:298 + projectors/registry.py:156 + tests/test_lifespan_index_split_tier1.py:96/111). (2) 5/17 §19 自查发现 executor 漏抓 metrics.py:130 (本 PR commit 1 新建 metrics.py 自身的 `record_silent_fallback` fn 也含同模式 fail-open, 与 :88 `record_doc_number_fallback` 镜像). (3) metrics.py:88/130 **都是 PR #586 §19 round-2 / issue #592 批准 fail-open 模式** (`# noqa: BLE001` + comment "prometheus_client 内部已保证不 raise, 此处兜底防注册表损坏极端场景") — CLAUDE.md §10 broad except 禁止允许"最外层兜底", metrics 写入失败不能阻塞 Tier 1 业务是更强的硬约束, 故 sub-D 标记"批准模式不修". 本 PR 不扩 scope (user 5/17 sign-off 9 site), 余 6 新业务/基础 site 留 sub-D
2. `auto_procurement.py:414` 不再 `except Exception` (§13 broad except 零容忍)
3. 4 个 (b)/(c) site (#3, #6, #7, #8, #9) 真 emit `tx_supply_silent_fallback_total{site=...}` Prometheus counter — 每 site mock raise + assert `_metric_value(counter, {"site": ...}) == 1`
4. 4 个 (b) site (#2, #3, #4, #6) 真 emit structlog warn 含 `exc_info` — 测试 capture log records + assert `event` 字段 + `exception` 字段非空
5. `test_silent_failure_supply_governance_tier1.py` 全绿 (regression suite, ~12 用例)
6. CI 真门禁全绿: Tier 1 门禁判定 / Run Tier 1 supply / 源改动配对 / Fresh PG migration chain (无 schema 改) / RLS 严格 (本 PR 不动 RLS)

## 4) Implementation Steps (commit-by-commit, single-track strict)

```
commit 1: chore(tx-supply): 新建 core/metrics.py — tx_supply_silent_fallback_total Prom counter helper [T3]
commit 2: fix(tx-supply): voice_count_routes _cn_integer_to_int refactor 删 try/except [T3]
commit 3: [Tier1] fix(tx-supply): deduction_routes auto_create_loss_case fail-open 加 structlog.warn [Tier1 邻接]
commit 4: [Tier1] fix(tx-supply): smart_procurement_routes _get_last_supplier_purchase 加 warn+counter [Tier1 邻接]
commit 5: fix(tx-supply): auto_procurement supplier_score §13 broad except 收窄 + warn [T2]
commit 6: fix(tx-supply): auto_procurement create_requisition ImportError 加 debug log [T3]
commit 7: [Tier1] fix(tx-supply): expiry_monitor _parse_notes_expiry 食安路径 warn+counter [Tier1 邻接]
commit 8: fix(tx-supply): theoretical_cost _get_current_bom 加 warn+counter [T2 邻接]
commit 9: fix(tx-supply): actual_cost _get_last_purchase_price + _get_ledger_price 2 site 加 warn+counter [T2 邻接]
commit 10: test(tx-supply): test_silent_failure_supply_governance_tier1.py — 12 用例覆盖 9 site (含 §13 regression / structlog warn / counter inc) [Tier1]
```

合计 10 commits. 文件名后缀 `_tier1.py` 触 Tier 1 Gate workflow (per memory `feedback_tier1_test_filename_workflow_trigger.md`).

## 5) Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Tier 1 邻接 site 改动可能影响 200 桌并发场景 (库存盘亏 fire-and-forget) | regression 用例 fire 100 个 auto_create_loss_case task + assert 任何失败 log 都不阻塞主响应 |
| 食安路径 Prom counter 名命名冲突 既有 `tx_supply_*` metric | grep `tx_supply_` 现存 metric 名, 避撞 |
| structlog.warn `exception` 字段触发 PR #574/#581/#583/#588 `event=` 字段冲突 | 用 `log.warning("xxx_failed", ..., exc_info=True)` 不传 event= 关键字, 用第一 positional 字符串作 event name |
| 5/14 alembic 双 head merge revision pattern (本 PR 不动 migration, 跳过) | N/A |
| §13 broad except 收窄后某种未捕获异常导致 bubble up 阻塞 ProcurementRecommendation 生成 | 收窄至 (SQLAlchemyError, KeyError, TypeError, ValueError) 覆盖原 supplier_score 调用栈所有合理失败模式; 加 regression test cover 4 种异常 |
| §19 reviewer round-1 抓 P0/P1 | 提前自查 5/14 后所有相关 memory feedback (graceful degradation / multiline grep / module-level logger / handoff drift); reviewer 用 opus B 选项 (真 BUG only) |

## 6) Verification Steps

1. **本地**: `pytest services/tx-supply/src/tests/test_silent_failure_supply_governance_tier1.py -v` → 12/12 全绿
2. **AST 验证**: `python3 scripts/code-fact-scan.py | jq '.["tx-supply"].silent_failure_count'` → `16` (本 PR 修 9 后剩余, 与 §3 #1 一致; 其中 2 个 metrics fail-open 批准模式不计修)
3. **broad except 验证**: `rg -n "except Exception:\s*$|except Exception:\s*pass$" services/tx-supply/src --type py` → 0 命中
4. **Prom counter 验证**: 跑测试时打开 `prometheus_client` registry, 4 site 各 inc 1
5. **CI verify**: PR 创建后 watch `Tier 1 门禁判定` / `Run Tier 1 supply 16 services` / `源改动配对` / `Fresh PG 18 alembics` 4 真门禁
6. **§19 reviewer** (opus B 选项): 用 `code-reviewer` agent 真 BUG only, round-1 → fix → round-2 verify 无回归 → APPROVE → admin merge

## 7) Worktree + Branch

- **Worktree**: `~/.tunxiang-p0-worktrees/governance-silent-supply-2026-05-17/`
- **Branch**: `governance/silent-failure-supply-2026-05-17`
- **Base**: `origin/main eda578a7` (post-PR #734)

## 8) Follow-up Issues

- **sub-C TBD #N**: silent failure Wave 1 sub-C — tx-supply tests/ **10 个** (8 old + 2 new test_lifespan_index_split_tier1.py) silent → `pytest.raises(...)` / `contextlib.suppress` (asyncio.CancelledError 不能用 pytest.raises 直接) 改造 [T3]
- **sub-D TBD #N**: silent failure Wave 1 sub-D — tx-supply 6 新业务/基础 site (PR #698/#718/#734 + 本 PR commit 1 引入, W20 baseline 之后):
  - `main.py:122` + `:142` (lifespan `asyncio.TimeoutError` + `CancelledError`) — 大概率合法 graceful shutdown, document not-a-fix or 加 debug log [T3]
  - `metrics.py:88` (`record_doc_number_fallback` 内 `except Exception: pass`) — **批准 fail-open 模式** (`# noqa: BLE001` + comment), source PR #586 §19 round-2 / issue #592, **sub-D 标"不修, 文档化"** [T3]
  - `metrics.py:130` (`record_silent_fallback` 内 `except Exception: pass`) — **同 :88 镜像 fail-open 模式**, 本 PR commit 1 新建, 同 sub-D 标"不修, 文档化" [T3]
  - `projectors/index_split.py:298` (`except (ValueError, TypeError): return None`) — projector 异常 swallow, 需 structlog.warn + 决定 Prom counter [Tier 1 邻接 if projector 是 PRD-11 主路径]
  - `projectors/registry.py:156` (`asyncio.CancelledError`) — registry shutdown, 大概率合法 graceful [T3]
- (后续 Wave 1 sub-B tx-trade 53 + Wave 2/3 按 issue #663 路线推)

## 9) Explicit-ask Sign-off Question

- 整 PR 走 Tier 1 邻接 (3 site 触食安/库存盘亏/供应商推荐硬约束)
- 9 site fix 模式 per §2 表
- 10 commits single-track 严肃推
- §19 reviewer opus B 选项 round-1 → fix → round-2

**sign-off 后 executor 起手实施。**
