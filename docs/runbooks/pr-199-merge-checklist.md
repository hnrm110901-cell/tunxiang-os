# PR #199 (v500 RLS FORCE migration) merge checklist

**对应任务**：审计 follow-up #22 — PR #199 merge 前 alembic heads 核对 + rebase down_revision
**估时**：10-30 分钟（含 staging dry-run）
**执行者**：release manager

---

## 为什么需要这份 checklist

verifier 第三轮 review 警告：

> PR #199 `down_revision = "v399"`。当前 main head 是 v399 链合法，但用户的
> PRs（v400/v401/v402 WITH CHECK 系列）若先 merge，main head 变成 v402，
> PR #199 的 `down_revision="v399"` 就指向历史中间节点 → **alembic
> multi-heads 错** → staging/生产 DB 迁移卡死。

外加：PR #199 标记 **DO NOT MERGE pending staging dry-run**。本 checklist 把
两个前置条件都列清。

---

## ⚠️ 不可跳过的前置条件

merge PR #199 **必须** 先满足全部 ✅：

- [ ] **PR #207 (RLS 阶段 4 — tx_system_role) 已 merge**
  - PR #207 提供双模式 `get_db_no_rls()` + tx_system_role 部署脚本
  - 没 PR #207 就直接跑 PR #199 的 FORCE migration → 5 处合法 BYPASSRLS 调用方
    （gateway hub_api / banquet_payment_routes / wechat_pay_notify_service /
    seed_loader / brain_routes）会立即返 0 行 → **生产业务全断**
- [ ] **DBA 已跑 `scripts/db/create_tx_system_role.sql`** 在目标环境
- [ ] **应用已部署带 `RLS_USE_TX_SYSTEM_ROLE=true`** 的版本，且灰度 24h 无 RLS-related 5xx
- [ ] **DBA 已跑 `scripts/db/revoke_tunxiang_bypassrls.sql`**（PR #207 阶段 5）
- [ ] **staging dry-run** v500 migration 通过（见下方步骤）

---

## 步骤 1：核对 alembic head（10 分钟）

```bash
gh pr checkout 199
bash scripts/db/check_alembic_head_for_pr_199.sh
```

期望输出：
```
✅ PASS — PR #199 down_revision (vXXX) 与当前 main head 一致
```

### 如果输出 NEEDS REBASE

脚本会给出具体修复命令：

1. 编辑 `shared/db-migrations/versions/v500_rls_force_all_business_tables.py`
2. 把 `down_revision = "v399"` 改为 main 当前 head（如 `"v402"`）
3. 重跑脚本确认 ✅ PASS
4. `git commit --amend --no-edit` + `git push --force-with-lease`
5. 在 PR #199 description 加一行说明："rebased down_revision from v399 to vXXX"

---

## 步骤 2：staging dry-run（30-60 分钟）

```bash
# 在 staging 环境（独立 PG，无生产数据）
ssh staging-db "psql -U postgres -c 'CREATE DATABASE tunxiang_dryrun_v500'"

# 拉取 PR #199 代码
gh pr checkout 199

# 跑 alembic upgrade head（应无 multi-heads 错）
DATABASE_URL=postgres://...staging.../tunxiang_dryrun_v500 \
  cd shared/db-migrations && alembic upgrade head

# 验证 FORCE 真生效
psql -d tunxiang_dryrun_v500 -c "
  SELECT count(*) FROM pg_tables
  WHERE schemaname = 'public'
    AND rowsecurity = true
    AND forcerowsecurity = false;
"
# 期望：0（除 EXEMPT 表外，所有 ENABLE RLS 的业务表都 FORCE 了）

# 用主 app role 直查含 RLS 的表（非 SET ROLE）
psql -d tunxiang_dryrun_v500 -U tunxiang -c "
  SELECT count(*) FROM banquet_deposits;
"
# 期望：0 行（FORCE 生效 + 阶段 5 撤了 BYPASSRLS）
```

### 如果 dry-run 失败

- alembic multi-heads → 回到步骤 1 修 down_revision
- 业务表查询非 0 → PR #207 cutover 没完全生效，先确认 NOBYPASSRLS 已应用
- 5 处合法调用方测试失败 → 阶段 4 灰度未完成，回滚 PR #199 暂留

---

## 步骤 3：merge + 灰度（详见 cutover playbook 阶段 H）

通过 staging dry-run 后，按 `docs/security/rls-force-rollout.md` 阶段 5：

| 阶段 | 范围 | 监控 | 回滚阈值 |
|---|---|---|---|
| Canary 1 | demo 环境 | rls_query_total / RLS-related 5xx | 任何业务回归 |
| Canary 2 | 1 真实门店（尝在一起 文化城店）| 4h 0 异常订单 | RLS-related 错误 > 0 |
| Canary 3 | 整个尝在一起品牌 | 24h 无 5xx 增加 | RLS 错误 > 0 |
| Full | 全部 3 品牌 | 持续 48h | — |

merge 命令：
```bash
gh pr merge 199 --squash --delete-branch
```

---

## 步骤 4：merge 后立即验证

```bash
# 触发生产 migration（按 deploy.yml 流程）
git push origin main  # 触发 deploy → 跑 alembic upgrade head

# 5 分钟后检查告警
# 期望：无 alembic 错；无 5xx 增加；payment_saga_total{result="success"} 仍 > 99.9%
```

如任一项不通过：
```bash
# 紧急回滚（撤销 v500）
ssh prod-db "psql -d tunxiang -c '
  -- 临时让 app role 恢复 BYPASSRLS（防业务断）
  ALTER ROLE tunxiang BYPASSRLS;
'"

# 然后 alembic downgrade（v500 的 downgrade 会 NO FORCE 全表）
DATABASE_URL=$PROD_DB_URL alembic downgrade v399
```

---

## 紧急联系

- DBA：`<待补充>`
- release manager：`<待补充>`
- security on-call：`<待补充>`

---

## 相关文档

- `docs/security/rls-force-rollout.md` 5 阶段完整 rollout
- `docs/runbooks/audit-2026-05-cutover.md` 阶段 H
- `docs/audit-2026-05/01-security.md` S-05 P0 详情
- PR #207 (audit/p0-followup-rls-stage-4-bypassrls) — 阶段 4 必先 merge
- PR #199 (audit/p0-followup-rls-force-migration) — 本 checklist 针对的 PR
