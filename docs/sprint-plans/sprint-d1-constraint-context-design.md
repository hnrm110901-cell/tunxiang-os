# Sprint D1 — 51 Skill ConstraintChecker 批次化接入设计稿

**版本**：v1.0
**作者**：屯象OS AI 架构师
**日期**：2026-04-18
**范围**：Sprint D1（W4-W9）
**前置**：CLAUDE.md 第九章（三条硬约束）、docs/sprint-plan-2026Q2-unified.md Sprint D

---

## 1. ConstraintContext 提案

### 1.1 问题根因

上一轮规划误判"51 个 Skill 未接入 ConstraintChecker"。实地核查 `services/tx-agent/src/agents/base.py:103-108` 发现 `SkillAgent.run()` 早已统一调用 `ConstraintChecker.check_all(result.data)`。真正的缺陷在 `services/tx-agent/src/agents/constraints.py` 的三个 check 函数内部：当 `result.data` 里缺少 `price_fen / cost_fen / ingredients / estimated_serve_minutes` 时，它们返回 `None`（第 95、114、135 行），被 Checker 当作"无数据跳过"。结果是：51 个 Skill 里只有 9 个 P0 Skill 在 `data` 里真实填入了字段，其余 42 个全部是"静默 N/A"——约束看似通过，实则形同虚设。

### 1.2 提案：新建 `ConstraintContext` 数据类

路径：`services/tx-agent/src/agents/context.py`（新文件）。

```python
@dataclass
class IngredientSnapshot:
    name: str
    remaining_hours: float | None
    batch_id: str | None = None

@dataclass
class ConstraintContext:
    price_fen: int | None = None
    cost_fen: int | None = None
    ingredients: list[IngredientSnapshot] | None = None
    estimated_serve_minutes: float | None = None
    constraint_scope: set[Literal["margin","safety","experience"]] = field(
        default_factory=lambda: {"margin","safety","experience"}
    )
    waived_reason: str | None = None
```

### 1.3 方案对比

| 方案 | 结论 |
|---|---|
| dataclass | **采用**：零运行时开销，与 AgentResult 风格一致 |
| Pydantic | 否：多一层 import，基类所有子类需改造 |
| 基类 self.* 属性 | 禁止：并发不安全（同一 Agent 被多协程 run） |

### 1.4 与 AgentResult 共存

AgentResult 新增 `context: ConstraintContext | None = None`。Checker 优先从 `context` 读，fallback 到 `data`，保证向后兼容。迁移期两条路径并存，W10 后清理 data 中约束字段约定。

---

## 2. 基类强化方案

### 2.1 类变量声明

```python
class SkillAgent:
    constraint_scope: ClassVar[set[str]] = {"margin","safety","experience"}
    constraint_waived_reason: ClassVar[str | None] = None
```

### 2.2 run() 流程改造

`base.py:103-116` 替换为：
1. 取 `result.context`（若 None 则从 `data` 组装）
2. 若 `constraint_scope == set()` → 跳过 Checker，写 `constraints_check = {"scope":"waived", "reason":..., "passed":True}`，要求 `waived_reason is not None`
3. 否则调用 `ConstraintChecker.check_all(context, scope=self.constraint_scope)`
4. 收紧 N/A：Checker 返 None 且 Skill 未豁免 → `scope="n/a"` + warning 日志，CI 门禁失败

### 2.3 覆盖率演进

| 周 | 实装 | 显式豁免 | N/A | 总 |
|---|---|---|---|---|
| W3 | 9 | 0 | 42 | 18% |
| W4 批1 | 16 | 0 | 35 | 31% |
| W5 批2 | 23 | 2 | 26 | 49% |
| W6 批3 | 30 | 3 | 18 | 65% |
| W7 批4 | 37 | 4 | 10 | 80% |
| W8 批5 | 44 | 5 | 2 | 96% |
| W9 批6 | 50 | 7 | 0 | **100%** |

---

## 3. 6 批 + Overflow 计划（基于实地 glob 纠正）

实地 `services/tx-agent/src/agents/skills/` 有 **51 个文件**（含 `__init__.py`），50 个具体 SkillAgent。

### 3.1 已实装 P0（实际 8 个，主规划说 9）

discount_guard / smart_menu / ingredient_radar / inventory_alert / finance_audit / cost_diagnosis / billing_anomaly / cashier_audit（待复核完整度）

### 3.2 批 1 资金+毛利（W4）
billing_anomaly、finance_audit、cost_diagnosis、growth_attribution、closing_agent（agent_id=`closing_ops`）、ingredient_radar、stockout_alert。实际新接入 = growth_attribution + closing_ops + stockout_alert（3 个）。

### 3.3 批 2 出餐体验（W5）
kitchen_overtime、serve_dispatch、table_dispatch、queue_seating、ai_waiter、voice_order、smart_service。主约束 experience + `estimated_serve_minutes`。

### 3.4 批 3 定价营销（W6）
smart_menu、menu_advisor、points_advisor、seasonal_campaign、personalization、new_customer_convert、referral_growth。主约束 margin。

### 3.5 批 4 库存原料（W7）
inventory_alert、new_product_scout、trend_discovery、pilot_recommender、banquet_growth、enterprise_activation、private_ops。主约束 safety。

### 3.6 批 5 合规运营（W8）
compliance_alert、attendance_compliance、attendance_recovery、turnover_risk、workforce_planner、store_inspect、off_peak_traffic。多数显式豁免。

### 3.7 批 6 内容洞察（W9，全部豁免）
review_insight、review_summary、intel_reporter、audit_trail、growth_coach、salary_advisor、smart_customer_service。

### 3.8 Overflow 批（W9 并行）
主规划漏列 7 个：ai_marketing_orchestrator、content_generation、competitor_watch、dormant_recall、high_value_member、member_insight、cashier_audit（重做）。

- margin 约束：ai_marketing_orchestrator、dormant_recall、high_value_member、member_insight
- 显式豁免：content_generation、competitor_watch
- 待复核：cashier_audit

---

## 4. CI 门禁设计

### 4.1 新测试文件
`services/tx-agent/tests/agents/test_constraint_coverage.py`

### 4.2 遍历策略
```python
from agents.skills import SKILL_REGISTRY
for skill_cls in SKILL_REGISTRY.values():
    for fixture in load_golden_fixtures(skill_cls.agent_id):
        result = await skill_instance.run(...)
        assert result.constraints_detail.get("scope") != "n/a"
        assert "passed" in result.constraints_detail
```

### 4.3 Golden Fixture 规范
每个 Skill `services/tx-agent/tests/fixtures/<agent_id>/` 3 条 YAML：normal / boundary / violation。

### 4.4 回归检测
`_constraint_baseline.json` 基线，新 PR 覆盖率下降 → fail。

### 4.5 Prometheus 指标
`agent_constraint_coverage{agent_id,scope}` counter，Grafana 显示实时 51/51 覆盖。

---

## 5. 迁移与发布策略

### 5.1 DB 迁移
**不新增**。`decision_log.py:25` 的 `constraints_check: JSON` 足以承载新 `scope/waived_reason` 键。

### 5.2 Feature Flag
命名空间 `agent.skill.<batch_id>.constraint.strict`，三态：off / shadow / strict。批上线当周 shadow，下周转 strict。

### 5.3 回滚
flag → shadow 立即降级；历史 `constraints_check` 保留可回溯。

---

## 6. 依赖与风险

### 6.1 依赖
- **ConstraintChecker.check_all 签名**：`constraints.py:54` 接受 dict，需扩展为 `check_all(context: ConstraintContext, scope: set[str])`，向后兼容用 `@overload` + `isinstance`
- **Skill Registry**：`skills/__init__.py` 若无统一注册表，W4 先补建
- **DB 查询开销**：批 3/4 需查 `dishes.cost_price_fen`/`bom_recipe_items`，建议 Orchestrator 预取

### 6.2 风险 Top 3
1. **P95 延迟升高 50-200ms** — Orchestrator 预查 + LRU（tenant+dish，TTL 60s）
2. **豁免滥用** — CI 强校验 reason 长度≥30 + 黑名单（["N/A","不适用","跳过"]）
3. **与 D2 6 列迁移冲突** — 本 Sprint 不触 agent_decision_logs 表结构；两者正交，D2 负责人在同一 head 叠加

### 6.3 其他风险
- `closing_agent.py` agent_id 是 `closing_ops`，fixture 按 agent_id 建
- `attendance_compliance_agent.py` 注册表去重需小心
- Overflow 批挤 W9 压力大，W4 先处理 content_generation/competitor_watch 两个豁免项（0.5 人日）

---

## 7. 交付清单（W4-W9）

| 周 | 目标 | 产出 |
|---|---|---|
| W4 | 批 1 + 基础设施 | `context.py` + 基类改造 + 批 1 新接入 3 + CI 门禁 + batch1 flag shadow + Overflow 先行豁免 2 |
| W5 | 批 2 出餐 | 7 个填 `estimated_serve_minutes`；batch1→strict；batch2→shadow |
| W6 | 批 3 定价 | price/cost 补齐；Orchestrator 预查+LRU；batch2→strict；batch3→shadow |
| W7 | 批 4 库存 | `IngredientSnapshot` 补齐；batch3→strict；batch4→shadow |
| W8 | 批 5 合规 | 豁免标注 + 理由审校；batch4→strict；batch5→shadow |
| W9 | 批 6 + Overflow | 7 豁免 + Overflow 5 个；全部 strict；51/51；Grafana 覆盖面板 |

### DoD
1. 100% Skill 满足 `constraints_detail.scope ∈ {margin,safety,experience,waived}`，无 `n/a` 残留
2. `test_constraint_coverage.py` main 绿
3. 近 7 天 `constraints_check->>'scope' = 'n/a'` 记录 = 0
4. 三条硬约束真实违规能拦截（每批 ≥1 条 violation.yaml 手工验证）

---

## 附录 A · 改动点

| 文件 | 改动 |
|---|---|
| `services/tx-agent/src/agents/context.py` | **新建** |
| `services/tx-agent/src/agents/base.py` | 加 `constraint_scope/constraint_waived_reason`；改 run() L103-116 |
| `services/tx-agent/src/agents/constraints.py` | `check_all` 签名扩展 + scope 过滤 |
| `services/tx-agent/src/agents/skills/__init__.py` | 补 SKILL_REGISTRY |
| `services/tx-agent/tests/agents/test_constraint_coverage.py` | **新建** |
| `services/tx-agent/tests/fixtures/<agent_id>/*.yaml` | **新建** 51 × 3 = 153 条 |
| 42 个 Skill `execute()` | 填 `context=ConstraintContext(...)` 或类级 `constraint_scope = set()` |

---

## 附录 B · 需创始人确认的 3 个决策点

1. **Overflow 批归属**：7 个被主规划遗漏的 Skill 如何安排到 W4 和 W9？
2. **cashier_audit 状态复核**：是否真已实装并符合 P0 标准？若否从"9 已实装"下调到"8 + 1 待做"
3. **Alembic head 协同**：允许 D1 与 D2 共用 head 叠加（避免分叉），或由 D2 负责人 rebase？
