# 屯象OS — 多 Agent 协同开发标准 v1.0

> 本文件是三工具（Claude Code / Codex / Claude CLI）协同开发的**唯一权威标准**。
> 任何工具在触碰受保护路径前，必须先 `git pull --rebase origin develop` 重读最新文件。

---

## 1. 工具分工

| 工具 | 职责域 | 典型任务 |
|------|--------|---------|
| **Claude Code** | 架构设计、核心模块、复杂后端逻辑 | Agent、Service、Model、API路由、数据库迁移 |
| **Codex** | UI 组件、页面、设计系统、代码重构 | pages/、design-system/、layouts/、hooks/ |
| **Claude CLI** | 自动化脚本、CI/CD、批量操作 | scripts/、.github/workflows/、Makefile |

---

## 2. 分支策略（强制）

```
main          ← 生产分支，禁止直推，只接受来自 develop 的 PR
develop       ← 唯一集成分支，三端共同合并目标
feat/<tool>-<desc>  ← 各工具的功能分支，从 develop 切出
fix/<desc>          ← bug 修复分支
```

### 规则
- **main 禁止直推** — 必须通过 PR + review
- 每个功能在开始前先从 `develop` 切出新分支
- PR 合并到 `develop` 前必须 rebase 到最新 `develop`
- `develop` → `main` 的 PR 由负责人手动触发

---

## 3. 受保护路径（修改前必须重读最新文件）

以下路径改动风险高，**修改前必须执行 `git pull --rebase origin develop` 并重读文件**：

| 路径 | 风险原因 | 主责工具 |
|------|---------|---------|
| `apps/api-gateway/src/api/` | 多工具并发修改 API 路由易冲突 | Claude Code |
| `apps/api-gateway/edge/` | 边缘计算模块，依赖链复杂 | Claude Code |
| `apps/api-gateway/scripts/` | 脚本可能互相覆盖 | Claude CLI |
| `apps/web/src/pages/HardwarePage.tsx` | Codex 与 Claude Code 均可能修改 | Codex |
| `apps/api-gateway/alembic/versions/` | migration 冲突会破坏 DB 状态 | Claude Code |
| `.github/workflows/` | 工作流冲突影响所有部署 | Claude CLI |
| `docker-compose*.yml` | 端口/网络冲突影响所有环境 | Claude CLI |

---

## 4. 提交规范（Conventional Commits）

格式：`<type>(<scope>): <subject>`

```
feat(api): 新增门店健康评分接口
fix(pos): 修复品智收银 token 刷新逻辑
refactor(agents): 重构 DecisionAgent 响应字段映射
ci(deploy): 加入 Alembic 迁移步骤
```

**允许的 type**：`feat` / `fix` / `refactor` / `docs` / `test` / `chore` / `perf` / `ci` / `style` / `revert` / `build`

**允许的 scope**（见 `.commitlintrc.json`）：`kernel` / `api` / `web` / `ui` / `agents` / `models` / `services` / `pos` / `crm` / `db` / `auth` / `celery` / `deploy` / `bff` / `sm` / `hq` / `chef` / `floor` / `im` / `hr` / `platform` / `integrations` / `ci`

---

## 5. 三端工作流（每次开始前）

```bash
# Step 1: 同步最新 develop
git checkout develop
git pull --rebase origin develop

# Step 2: 切出功能分支
git checkout -b feat/claude-code-<desc>   # 或 feat/codex-* / feat/cli-*

# Step 3: 开发 + 提交（遵守 Conventional Commits）
git add <具体文件>   # 不用 git add -A
git commit -m "feat(api): ..."

# Step 4: 推送 + 开 PR 到 develop
git push origin feat/claude-code-<desc>
gh pr create --base develop --title "feat(api): ..." --body "..."

# Step 5: PR 合并后删除分支
git branch -d feat/claude-code-<desc>
```

---

## 6. 冲突预防规则

1. **不跨域修改**：Codex 不改 `src/api/`，Claude Code 不改 `pages/`，CLI 不改业务逻辑
2. **原子提交**：一个提交只做一件事，不混合 feat + refactor
3. **每日同步**：每次开始工作前先 `git pull --rebase origin develop`
4. **Issue 认领**：开始前在 GitHub Issues 标注"由哪个工具负责"，避免重复开发
5. **受保护路径修改前**：必须在 PR 描述中说明"已重读最新版本，变更意图是..."

---

## 7. 自动化质量门（pre-commit）

```bash
# 安装（首次）
pip install pre-commit
pre-commit install
pre-commit install --hook-type commit-msg   # 启用 commitlint

# 手动运行
pre-commit run --all-files
```

触发时机：
- `pre-commit`：每次 `git commit` 前自动运行 black/isort/flake8/eslint
- `commit-msg`：检查提交信息格式（commitlint）

---

*维护人：屯象OS 开发团队 | 版本：v1.0 | 最后更新：2026-03-15*
