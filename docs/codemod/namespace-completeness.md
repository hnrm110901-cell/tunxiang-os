# Codemod 完整性沉淀（决策 84，6 轮）

> 适用范围：屯象OS test/production import 路径 codemod 链（issue #298 起）。
> 目标：未来 codemod 工具一次走通，不再靠 review 反向揭露漏抓。

## 背景

issue #298 起 codemod 链跨 14 服务把 test 和 production 的 `from <pkg>` 路径切到容器布局
`from services.<svc>.src.<pkg>`（容器 `PYTHONPATH=/app`），消除 SQLAlchemy 双重注册 + 容器
启动 `ModuleNotFoundError`。

但每一轮 codemod 落地后，reviewer / pytest / runtime 总能再揭露一种漏抓形式 —— 决策 84
的存在意义是把这些"被揭露后才补"的漏抓沉淀成 codemod 必备的扫描清单。

## 6 轮漏抓清单

| 轮 | 揭露 PR | 漏抓形式 | 修补 |
|---|---|---|---|
| 1 | #322 | `^from <ns>` 行首正则抓不到缩进的 lazy import | 改 `^[[:space:]]*from <ns>` 抓任意缩进 |
| 2 | #355 | scanner 仅扫 `^from <ns>`，漏抓函数体内 lazy import | 同 1，确认全覆盖（反复发现需第 6 轮再修） |
| 3 | #358 | stub key 仅抓 `["X"]`，漏抓 `setdefault("X", ...)` 形式 | 双路 grep：`["<key>"]` ∪ `setdefault("<key>"` |
| 4 | 5/10 review-found（#355 / #358 commit 4） | NAMESPACES 列表只含标准 5 个（services / models / workers / repositories / api），漏 tx-growth `engine` / `templates` / `seeds` + tx-intel `adapters` | codemod 启动前 `ls services/<svc>/src/` 列出**所有**子目录，全注册到 NAMESPACES |
| 5 | 5/11 凌晨 #358（codex 暴露后回修） | codemod 切 production import 后，test 端仍用裸 `from models.X` → 两条 sys.modules 路径，同文件两个类对象，`isinstance()` 假阴性 | 每服务 `services/<svc>/conftest.py` 加 models/ 子目录身份别名（预加载裸路径，把全路径 sys.modules 别名指过去） |
| 6 | 5/11 凌晨 #353（codex P1 sweep） | 第 1 / 2 轮的 regex 在 production 路径漏跑（仅 test 路径走过更新），导致 lazy import 残留 | codemod 必须**对 test 和 production 双路径**跑同一套 regex；本批静态扫验证 `^[[:space:]]\+from services\.` |

## codemod 必备扫描清单（执行清单）

### A. 命名空间发现

```bash
# 1. 列出服务的所有源码子目录（**不限于**标准 7 个）
SVC=tx-growth  # 替换
ls services/$SVC/src/ | grep -v __pycache__

# 2. 把所有子目录注册到 codemod NAMESPACES：
NAMESPACES=("api" "models" "services" "repositories" "tests" "routers"
            "workers" "engine" "templates" "seeds" "adapters")  # 实际按 ls 结果扩展
```

### B. import 模式扫描（双路径）

```bash
# 测试 + production 端都跑
for SCOPE in services/$SVC/src services/$SVC/src/tests; do
  # 1. top-level + 缩进 lazy import
  grep -rn "^[[:space:]]*from services\." $SCOPE | grep -v "from services\.$SVC_UNDERSCORE\.src"
  # 2. import services.X
  grep -rn "^[[:space:]]*import services\." $SCOPE
done
```

### C. stub key 扫描（双路）

```bash
# 1. 直接索引
grep -rn '\["services\.[a-z_]\+"' services/$SVC/src/tests
# 2. setdefault 形式
grep -rn 'setdefault("services\.[a-z_]\+"' services/$SVC/src/tests
```

### D. conftest 兜底（models/ 身份别名）

每服务 `services/<svc>/conftest.py` 在 namespace 注册段后，加一段对 `services/<svc>/src/models/`
每个 `.py` 预加载裸 `models.X` 模块，把 `services.<svc>.src.models.X` sys.modules 键别名指过去。

参考实现：见 `services/tx-finance/conftest.py`（PR #358）。

适用场景：production source 切换 `from services.<svc>.src.models.X` 后，未切换的 test 仍 `from
models.X` 时，避免 `isinstance()` 假阴性。

> **范围只限 models/**：services / repositories 等其他子目录有循环 import 风险；仅 models/
> 是 SQLAlchemy declarative 纯注册元数据，预加载无副作用。

### E. 验收闸（每 codemod PR 必跑）

```bash
# 1. 静态扫零残留（test 端）
grep -rn "^[[:space:]]*from services\.$SVC[^_]" services/$SVC/src/tests \
  | grep -v "from services\.$SVC_UNDERSCORE\.src"  # 应空

# 2. 静态扫零残留（production 端）
grep -rn "^[[:space:]]*from services\.$SVC[^_]" services/$SVC/src \
  --include="*.py" \
  | grep -v "from services\.$SVC_UNDERSCORE\.src" \
  | grep -v src/tests  # 应空

# 3. 本地 pytest 净 0 变化
pytest services/$SVC/src/tests -q  # 必绿

# 4. Tier 1 真门禁绿（CI）
#    Tier 1 门禁判定 / Run Tier 1 services/$SVC/src/tests / 源改动必须配对测试改动 / RLS 严格门禁
```

## 决策 84 配套决策

| 决策 | 关系 |
|---|---|
| 78 | 本地 pytest 必跑（不靠 codex/coderabbit 单点门禁）—— 是发现第 5 轮的途径 |
| 79 | 暴露的 pre-existing prod BUG → 独立 follow-up PR，不混入 codemod PR；但**第 6 轮 lazy import 修属于 codemod 残缺**，决策 79 不适用，必须当 PR 内修 |
| 80 | Tier 1 修复优先 AST 静态扫，不写脆弱 mock |
| 83 | 每服务首接入 codemod chain 需建 `services/<svc>/conftest.py`（标准模板见任一已建服务） |

## Review 流程沉淀（5/10 决策 77 完工反向收割）

> 来源：5/10 晚上 #355 / #358 review-fix wave 2（review-found 漏抓 namespace），用 code-reviewer
> agent 独立审 + B 选项止线（真 BUG only）。两条流程 lesson 直接影响后续 codemod review 应不应
> 该 inline-fix vs follow-up，独立沉淀避免下次重判。

### 流程 1：MUST FIX vs SHOULD CONSIDER 边界

reviewer 把"漏抓 namespace"列 SHOULD CONSIDER + 建议独立 issue（属 codemod tooling 改进
范畴），但 codemod **任务定义**是覆盖**所有 production 裸 namespace**（不仅
services/models/workers/repositories/api 五个标准 namespace）。

**裁决标准**：

- 任务定义内的漏抓 → **MUST FIX 当 PR 内修**（codemod 不完整即不算完工，决策 79 不适用）
- 任务定义外暴露的 prod BUG → **SHOULD CONSIDER follow-up issue**（决策 79 适用）

**实例**：tx-growth `engine` / `templates` / `seeds` 9 处漏抓 + tx-intel `adapters` 5 处漏抓
均属任务定义内 → 各 PR 加 commit 4 当 PR 内修，不拆 follow-up。

### 流程 2：mock binding fix 并入 PR（决策 79 边缘判定）

`fake_svc.X = AsyncMock(...)` → `.return_value = ...` 的 1-line trivial 改在 codemod PR 中
属"latent bug 借 codemod 暴露"：codemod 切换 production import 路径后，router once-bind
captures 出旧实例，导致 test 中 `fake_svc.X = AsyncMock(...)` 重新赋值无效（router 仍
持旧 bind）。

**裁决标准**：

- 修是 codemod 直接副作用一致性维护（不修 codemod 自带 test 即红） → **并入原 PR**
- 修非 codemod 直接相关、属独立 prod 行为 BUG → **独立 follow-up PR**（决策 79）

**实例**：#356 mock binding 1-line 修并入 PR，比独立 follow-up 价值高（避免审 review +
PR overhead 8 倍于 1 行 fix）。

### 流程 3：CI gate false positive → admin-merge 边界（5/11 中午沉淀）

`tier1-gate` 子项 `源改动必须配对测试改动` 对每个 PR 校验：若 PR 改 Tier 1 source whitelist
（`invoice_service.py` / `cashier_engine.py` / `payment_saga_service.py` 等，见 CLAUDE.md
§17），同 PR 内必须有相应 test 文件改动。但 codemod / namespace-completeness 类 PR 改 Tier 1
production import 路径时，**不需要新测试**（import 切换无业务行为变化），gate 不区分 import-only
vs 业务改动 → false positive。

**裁决标准**：

满足**全部条件**时，admin-merge bypass gate 是合理 escape hatch：

1. PR 改动是纯 import / 容器布局切换（diff 行非空非注释 100% 匹配 `^[+-].*(?:from |import )` 或 stub key 维护）
2. 没动 test fixture 内部的真业务断言（test 改动如有，仅同款 import 切换）
3. Tier 1 真门禁绿（区分真 required 和 noisy 漂移：`Tier 1 门禁判定` / `Run Tier 1 *` /
   `源改动必须配对测试改动` / RLS 严格门禁 真 required；`python-lint-test (*)` / `Ruff` /
   `frontend-build` / `TypeScript Check (*)` 全 PR 一律失败的预存漂移可忽略）
4. 本地 pytest 净 0 变化（决策 78）
5. PR description 明确标注 `codemod / namespace-completeness 沉淀第 N 轮` 或对应 issue 编号

**不适用 admin-merge**：业务改动 / 模型字段加减 / 路由签名变化 / 任何动到运行时行为的 PR。

**实例（5/10-5/11 production codemod chain，4 PR established pattern）**：

| PR | 服务 | admin-merge sha | Tier 1 source whitelist 触发文件（举例） |
|---|---|---|---|
| #353 | tx-org | `c8ff35dc` | `services/tx-org/src/services/payroll_engine_v3.py`（hr_event_consumer 等 lazy import 切容器布局） |
| #355 | tx-growth | `a6e48d73` | `services/tx-growth/src/services/*` 28 文件 import 切换 |
| #356 | tx-member | `bbefda66` | `services/tx-member/src/services/*` 11 文件 import 切换 |
| #358 | tx-finance + tx-intel + tx-supply | `ccaa4375` | `services/tx-finance/src/services/invoice_service.py` 等 27 文件 |

四 PR 都因为改 Tier 1 source whitelist 文件 import 路径，触 gate false positive；本地 pytest
真门禁验证全绿（决策 78）后 admin-squash merge。main 完全无 branch protection 是 admin-merge
机制可用前提；未来若启用 protection 需另议。

**根治 follow-up**：

- ⚠️ **方案 1 已落地但覆盖窄**（issue #417 / PR #419 + review fix）：`tier1-gate`
  加 import-only carve-out — `scripts/ci/detect_import_only_diff.py` 扫 PR diff，所有
  改动行必须为单行 `from X import Y` / `import X` / 注释 / 空白，且至少有一行真 import
  改动；满足则跳过 `源改动必须配对测试改动` 校验。19 单测覆盖（含 P0 分号复合语句攻击
  向量回归）。
  - **实际覆盖范围**：仅单行 import 形式的纯 import 切换。
  - **不覆盖**：多行括号 import `from x import (\n    a,\n    b,\n)` 续行 / stub key
    `setdefault("services.x", mod)` / conftest body 改动（模块身份别名段等） / 任何非
    `.py` 文件改动 / `from X import Y; side_effect()` 复合语句（攻击向量已阻断）。
  - **实测 5/10-5/11 4 PR 真终态覆盖率 = 0/4**：#353 (120 .py add: 118 imp + 1 close
    paren + 1 ident-cont → fail) / #355 (168 add: 93 imp + 75 stub/conftest other →
    fail) / #356 (120 add: 56 imp + 64 other → fail) / #358 (199 add: 66 imp + 2
    ident-cont + 131 other → fail)。**触发本流程沉淀的 4 个原型 PR 本 carve-out 全部
    不通过**。
  - 方案 1 的实际价值：未来若有**单文件 + 单行 import 切换**的小型 codemod PR（如
    个别服务少量 lazy import 修），可自动通过；当前 4 PR 规模不适用。

- ✅ **方案 2 主路径配套（2026-05-11 落地）**：PR title prefix `[codemod]` 显式 skip。
  实施在 `.github/workflows/tier1-gate.yml` `source-test-pairing` job 头部 —
  `[codemod]` 开头的 PR title 即跳过 `源改动必须配对测试改动` gate（其他 Tier 1 gate
  不豁免，Run Tier 1 系列照跑）。覆盖 4 PR 实测形态：多行括号 import / stub
  setdefault / conftest body / mock binding fix。
  - **PR title 经 `env:` 注入**（非直插 `${{ }}` 表达式），防御 title 内引号 / 反引号 /
    `$()` 等 shell 元字符 escape 出 command injection（GitHub Actions security
    best practice）。
  - **严格 prefix 匹配** `[codemod]` 大小写敏感、严格首字符匹配（`[[ "$PR_TITLE" ==
    \[codemod\]* ]]`），避免 "fix(channel): [codemod] integration" 这类中嵌触发。
  - **Reviewer 仍负责 5 项自验**（本节 §裁决标准），prefix 不豁免审查质量；流程：
    `[codemod] title → 跳过 source-test-pairing → **必须** reviewer 手动 5/5 通过后
    merge（Tier 1 测试失败仍 block）` ↔ `非 [codemod] title → 走 carve-out 检测 →
    失败要求配对测试`。
  - 未来若收紧（如检出"PR title 假冒"行为），可加 `git diff --name-only` 二次校验
    或 require approval；当前 4 PR 实测均可信场景，不预防御。

- 📋 **AST 升级（独立 issue 候选）**：用 `ast.parse` 解析 added/removed 行，识别多行
  括号 import 续行 + 区分真 import-only。复杂度比正则高一档，但能把覆盖率从单行扩到
  通用 import 形式。立 issue 前需先看是否有真实 codemod PR 触发频次足以 Justify。

## 历史 PR 链

- #298 issue 元 PR（trace + baseline 路径）
- #318 / #320 / #322 — Phase 1 / 2.1 / 2.2（tx-trade 起步 + 第 1-2 轮）
- #335 / #338 / #341 / #344 / #348 / #349 / #350 — Phase 3-9 test-codemod chain（5/9）
- #353 / #355 / #356 / #358 — production codemod 链（5/10 / 5/11，第 4-6 轮 + 流程 3 admin-merge pattern）
- 测试 codemod chain 的 7 PR 在 production codemod 完工后部分 superseded（脱链或 close）
- #370 close + #411 cherry-pick — 决策 81 second instance 实例（commit history 与 main 严重 diverge 时不死磕 rebase）

## 后续可能的第 7 轮（codemod 完整性方向）

> 注：5/11 中午沉淀的 §"Review 流程沉淀 流程 3"（CI gate 边界）属 process / governance 类
> lesson，与本节"codemod 完整性"主表（6 轮漏抓清单）不同 lane，不计入第 7 轮候选。

以下三项仍属 codemod 完整性方向的潜在第 7 轮：

- **stub `import services.X as Y`**：若有这类 import 形式，需补扫描
- **`__import__("services.X")` 或 `importlib.import_module("services.X")`**：动态 import，目前未发现，但理论可能漏抓
- **跨服务的 conftest 模块身份别名**：当前仅 tx-finance 有 models/ 别名段；若其他服务后续暴露同款 isinstance 假阴性，需复用模板补建

> 6 轮已是 review-driven 沉淀，不是 ahead-of-time 设计。第 7 轮如出现，按本文档同款格式追加。
