# .omc/policy — 屯象OS 治理策略目录

战略 plan §3 W1 治理四件套 / §5 取舍清单 / §6 自动化 hook 的落地配置。

## 文件清单

| 文件 | 说明 |
|------|------|
| `service-freeze.yml` | 服务冻结令 — 禁止冻结期内新增 `services/` 目录 (issue #755) |

## service-freeze.yml — 服务冻结令

### 背景

战略 §1 第一性原理 #1: "复杂度守恒 — 新服务 = 新故障源；新抽象 = 新维护成本"。
当前 20 个服务 (5/17 实测)，战略 W12 目标收敛到 17 个。冻结期内禁止新建服务。

### 生效机制

1. **本地 pre-commit hook** (建议安装):
   ```bash
   # 在 .git/hooks/pre-commit 中添加:
   bash scripts/git-hooks/service-freeze-check.sh
   ```
   或通过 `scripts/install-hooks.sh` 一键安装。

2. **CI 真门禁** (`service-freeze-check.yml`):
   - 触发条件: PR 改动 `services/**` 或 `.omc/policy/service-freeze.yml`
   - 拦截: 新增不在 `allowed_existing` + `planned_additions` 列表内的服务目录

### 例外申请流程

1. **创始人 explicit approval** — 飞书消息 或 GitHub issue comment，明确批准新服务
2. **架构守门会决议** — 记录至 `docs/governance/decisions/` (issue #761 ship 后正式启用)
3. **加入 planned_additions** — 在 `service-freeze.yml` 的 `planned_additions` 列表中添加服务名
4. **实施** — 创建服务目录并在 `infra/compose/base.yml` 注册

### 预批准的计划新增服务

| 服务 | 计划周次 | 关联 issue |
|------|---------|-----------|
| `tx-ontology` | W10 | #766 |
| `tx-sync-worker` | W2 | #758 |
| `tx-event-relay` | W3 | #757 |

### 冻结解除

`frozen_until: 2026-06-12` (W5 末)，届时架构守门会重新评估是否延续冻结。

## 参考

- 战略 plan §3 W1 / §5 / §6
- CLAUDE.md §26 (issue #754 ship 后生效)
- `docs/governance/policies/` (issue #761 ship 后正式归档)
- `scripts/git-hooks/service-freeze-check.sh` — 具体检查逻辑
- `.github/workflows/service-freeze-check.yml` — CI 真门禁
