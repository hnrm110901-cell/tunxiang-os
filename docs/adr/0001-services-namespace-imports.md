# ADR 0001 — services 命名空间 import 规范（草稿）

| 字段 | 值 |
|------|-----|
| 状态 | DRAFT — 等创始人决策 |
| 日期 | 2026-05-05 |
| 决策者 | TBD（创始人） |
| 提议者 | Claude Code（基于 Tier B 调研） |
| 关联 PR | #185 (scripts/README), #188 (tier1 runner pip cache) |

## 背景与问题

`services/` 下 16 个微服务（tx-trade / tx-finance / tx-supply / ...），每个 service 的源码物理位置是 `services/tx-<name>/src/services/<module>.py`，但项目内 import 出现两种风格混用：

```python
# 短 import — 依赖运行时 sys.path.insert(0, "services/tx-finance/src")
from services.invoice_service import InvoiceService

# 长 import — 完整命名空间路径
from services.tx_finance.src.services.invoice_service import InvoiceService
```

**Tier B 调研估算**:

- 短 import 使用：~18 个文件（gateway / tx-finance / tx-member 等）
- 长 import 使用：~12 个文件（较新的 tx-finance 分批、tx-org 等）
- 同一文件混用：~6 个文件

**真实风险案例**（来自调研）：
`services/gateway/tests/test_a1_authz_regression.py:89` 用 `from services.jwt_service import JWTService`，依赖测试 fixture 在 sys.path 头部插入 gateway/src。若同进程也跑 `services/tx-finance/tests/test_invoice_tier1.py`（其 fixture 也插入 tx-finance/src），后插入者会 shadow 前者的 `services.jwt_service` 命名空间。

**目前的规避**：`scripts/run_tier1_tests.sh` 逐文件 docker run（每文件一个独立进程），靠"进程隔离 ＋ 每次重新装 sys.path"避免 shadow（PR #188 加 pip cache 后仍保持每文件独立）。这是性能上的妥协（每文件 ~18s pip install + 启动开销）。

## 决策选项

### 选项 A — 全量 codemod 改长格式
- **执行**：写 codemod 把所有 `from services.X` 改成 `from services.tx_<svc>.src.services.X`
- **影响**：~20+ 文件改写
- **优点**：根本解决 shadow 风险；命名空间规范一致；可启用单进程跑测试，runner 大幅加速
- **缺点**：一次性大改 → 大 PR，diff 噪音多；冲突概率高；同 module 名跨 service（如 `services.gateway.invoice_service` vs `services.tx_finance.src.services.invoice_service`）需要 review

### 选项 B — 各 service `__init__.py` 显式 `__all__` + 渐进改造（**调研推荐**）
- **执行**：
  1. 每个 `services/tx-<svc>/src/__init__.py` 显式 `__all__` 暴露公开 API
  2. 新代码强制用长格式（lint 规则）
  3. 旧代码无须立即改，渐进迁移
- **影响**：每个 service 加一两行 `__init__.py`；ADR + lint 规则
- **优点**：不破坏现状；新代码立即合规；旧代码自然演化
- **缺点**：shadow 风险长期存在直到所有旧代码改完；需要 lint 规则维护
- **隐含**：runner 仍需逐文件 docker run

### 选项 C — 改 monorepo 结构（每 service 独立 package）
- **执行**：每个 service 改成 `pip install -e .` 可装的独立 package（pyproject.toml + namespace package）
- **影响**：架构层面重构；CI / Dockerfile / dev workflow 全部要改
- **优点**：彻底符合 Python package 标准；IDE / mypy 支持完整；runner 可单进程
- **缺点**：重构级别工作量；与现有 16 service / 230+ migration 体量不匹配
- **建议**：暂不考虑

## 推荐：B（渐进式）

短期 **不影响现有代码**、长期 **新代码命名空间规范化**。
关键约束：
1. **新增 lint 规则**禁止 `from services.<bare_module> import` 形式（仅允许 `from services.tx_<svc>...` 长格式或 `from services.<svc>...` 长格式）
2. **新 service** 必须从 day 1 走长格式
3. **旧 service** 在每次触碰相关测试时顺手转长格式（机会主义改造）
4. **每个 service 的 `src/__init__.py`** 显式 `__all__` 暴露公开 API，作为唯一外部入口

## 实施步骤（待批准后）

1. 写 lint 规则（ruff custom rule 或 pre-commit hook）禁止短 import 新增
2. 各 service 加 `src/__init__.py` `__all__`（每个 service ≤ 5 行）
3. CONTRIBUTING.md 加一节"import 规范"
4. 监控半年 metrics：剩余短 import 文件数量趋势

## 不会做的事

- 一次性 codemod 改写所有现有短 import（选项 A）
- 重构 monorepo（选项 C）
- 强制立即修旧代码（除非碰相关 PR）

## 后续依赖

- `scripts/run_tier1_tests.sh` 逐文件 docker run 模式继续保留
- 若未来全量短 import 清零，可考虑切单进程跑 → runner 大加速
