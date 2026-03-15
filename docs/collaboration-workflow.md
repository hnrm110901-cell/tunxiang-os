# 屯象OS — 协同工作流操作手册 v1.0

> 本文件与 `docs/agent-collaboration-standard.md` 配合使用。
> 标准文件说"做什么"，本文件说"怎么做"。

---

## 快速参考：当前分支状态

```
main     → 生产（https://zlsjos.cn）        push → GitHub Actions 自动部署
develop  → staging（http://42.194.229.21:8001）  push → GitHub Actions 自动部署
```

---

## 场景一：新功能开发

```bash
# 1. 同步
git checkout develop && git pull --rebase origin develop

# 2. 切分支（命名规范：feat/<工具前缀>-<短描述>）
git checkout -b feat/claude-code-pos-backfill

# 3. 开发，只改自己职责内的文件
# ...

# 4. 提交
git add apps/api-gateway/src/api/pos_sync.py
git commit -m "feat(api): 新增 POST /backfill 历史数据补拉接口"

# 5. 推送 + PR
git push origin feat/claude-code-pos-backfill
gh pr create --base develop \
  --title "feat(api): 新增 backfill 接口" \
  --body "## 变更\n- 新增 BackfillRequest/BackfillResponse schema\n- 支持最多 90 天历史补拉\n\n## 测试\n- 31/31 passed"
```

---

## 场景二：修改受保护路径

修改 `apps/api-gateway/src/api/`、`apps/api-gateway/edge/`、`apps/api-gateway/scripts/`、`apps/web/src/pages/HardwarePage.tsx` 前：

```bash
# 必须先重读最新文件
git pull --rebase origin develop

# 读取文件确认当前状态
# （Claude Code 用 Read 工具，Codex 用编辑器，CLI 用 cat）

# 在 PR 描述中声明：
# "已重读 apps/api-gateway/src/api/pos_sync.py 最新版本（commit: abc1234）
#  本次变更新增 GET /status/merchants 端点，不影响现有路由"
```

---

## 场景三：数据库 Schema 变更

```bash
# 1. 在 develop 分支上操作
git checkout develop && git pull --rebase origin develop

# 2. 生成 migration
cd apps/api-gateway
make migrate-gen msg="add_store_tags_table"

# 3. 检查生成的迁移文件
# alembic/versions/z50_add_store_tags_table.py

# 4. 本地验证
make migrate-up
make migrate-status

# 5. 提交
git add alembic/versions/z50_add_store_tags_table.py
git commit -m "db(models): 新增 store_tags 表"

# ⚠️ 注意：migration 文件不可修改已合并的版本，只能新建
```

---

## 场景四：develop → main 发布

```bash
# 确认 staging 功能验证通过后
gh pr create \
  --base main \
  --head develop \
  --title "release: Sprint X 发布" \
  --body "## 本次发布\n- feat: ...\n- fix: ...\n\n## 验证\n- [ ] staging 健康检查通过\n- [ ] 主要功能手动验证\n- [ ] 无未解决冲突"

# review + merge 后，GitHub Actions 自动部署到生产
```

---

## 场景五：紧急修复（hotfix）

```bash
# 从 main 切出 hotfix 分支
git checkout main && git pull --rebase origin main
git checkout -b fix/hotfix-celery-crash

# 修复...
git commit -m "fix(celery): 修复 pull_pinzhi_daily_data SyntaxError"

# 同时 PR 到 main 和 develop
gh pr create --base main --title "fix(celery): hotfix celery crash"
# main 合并后，cherry-pick 到 develop
git checkout develop
git cherry-pick <commit-hash>
git push origin develop
```

---

## 环境对照表

| 环境 | 分支 | 服务器路径 | API 端口 | 前端地址 |
|------|------|-----------|---------|---------|
| Production | `main` | `/opt/zhilian-os` | 8000 | https://zlsjos.cn |
| Staging | `develop` | `/opt/zhilian-os-staging` | 8001 | http://42.194.229.21:8081 |
| Local Dev | `feat/*` | localhost | 8000 | http://localhost:5173 |

---

## 常用命令速查

```bash
# 查看分支状态
git log --oneline --graph --all -10

# 检查 PR 状态
gh pr list --base develop

# 查看 Actions 运行情况
gh run list --limit 5

# 回滚到上一个成功部署（紧急情况）
ssh root@42.194.229.21 "cd /opt/zhilian-os && git log --oneline -5"
ssh root@42.194.229.21 "cd /opt/zhilian-os && git reset --hard <previous-commit>"
# 然后重跑 Docker
```

---

*维护人：屯象OS 开发团队 | 版本：v1.0 | 最后更新：2026-03-15*
