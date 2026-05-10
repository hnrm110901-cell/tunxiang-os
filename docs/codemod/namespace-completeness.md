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

## 历史 PR 链

- #298 issue 元 PR（trace + baseline 路径）
- #318 / #320 / #322 — Phase 1 / 2.1 / 2.2（tx-trade 起步 + 第 1-2 轮）
- #335 / #338 / #341 / #344 / #348 / #349 / #350 — Phase 3-9 test-codemod chain（5/9）
- #353 / #355 / #356 / #358 — production codemod 链（5/10 / 5/11，第 4-6 轮）
- 测试 codemod chain 的 7 PR 在 production codemod 完工后部分 superseded（脱链或 close）

## 后续可能的第 7 轮

- **stub `import services.X as Y`**：若有这类 import 形式，需补扫描
- **`__import__("services.X")` 或 `importlib.import_module("services.X")`**：动态 import，目前未发现，但理论可能漏抓
- **跨服务的 conftest 模块身份别名**：当前仅 tx-finance 有 models/ 别名段；若其他服务后续暴露同款 isinstance 假阴性，需复用模板补建

> 6 轮已是 review-driven 沉淀，不是 ahead-of-time 设计。第 7 轮如出现，按本文档同款格式追加。
