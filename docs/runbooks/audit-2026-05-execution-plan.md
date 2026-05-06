# 审计 2026-05 — 18 PR 合并 + 部署 + 验证执行计划

**目标**：把已交付的 18 个 PR 从 `[已 push, 未 merge]` 推进到 `[已生产部署 + 7d 无 5xx 验证]`
**周期**：4 周（28 工作日）
**前置**：所有 18 PR 已 push 到 origin（已完成）；本计划由 Claude 起草，供团队按 wave 推进
**RACI**：Tech Lead = R/A，DevOps = R，DBA = R（Wave 6/7），QA = R（Wave 4），CSM = C，创始人 = I

---

## 一、18 PR 分类 + 依赖图

### A. 独立可合（无 base 依赖；6 PR）

```
#195 audit/p0-fixes-batch-1-5         ← S-02 part 1 (gateway proxy)
#196 audit/p0-followup-edge-hmac-client (NEW-P0 解 #195 阻塞)
#199 audit/p0-followup-rls-force-migration (DO NOT MERGE 到 Wave 6)
#200 audit/p0-followup-tx-pay-channel-metrics
#201 audit/p0-followup-redis-nonce-store
#205 ops/payment-provider-failure-runbook (纯 doc)
```

### B. 依赖 #195 的 S-02 链（4 PR）

```
#195 ──→ #202 audit/p0-followup-internal-jwt-middleware (S-02 part 2)
#195 ──→ #206 audit/p0-followup-tx-pay-monitoring-blindspots
#202 ──→ #208 audit/p0-followup-internaljwt-23-services (S-02 100%)
#208 ──→ #210 audit/p0-followup-networkpolicy-templates (纵深防御)
```

### C. 独立 RLS 链（2 PR）

```
#207 audit/p0-followup-rls-stage-4-bypassrls (双模式)
#199 audit/p0-followup-rls-force-migration (DO NOT MERGE 阶段 5)
#211 ops/pr-199-merge-helper (alembic head 检查)
```

### D. Cutover 后 cleanup（4 PR + DO NOT MERGE）

```
#212 audit/p0-followup-cutover-cleanup (X-Tenant-ID 兜底删除) ← 依赖 #208 + #210
#213 audit/p0-followup-cleanup-proxy-simplify (proxy 简化) ← 依赖 #195 + #208
#214 audit/p0-followup-cleanup-rls-no-bypass-single-mode ← 依赖 #207 + #199
#215 audit/p0-followup-cleanup-internal-jwt-no-dev-fallback ← 依赖 #208
```

### E. 纯 ops doc（2 PR）

```
#203 ops/audit-2026-05-cutover-playbook
#216 ops/audit/p0-followup-s01-pinzhi-token-rotation-runbook
```

---

## 二、Wave 时间表

```
Wave 1  (D1-D2)  Foundation merge        │ 6 PR + 2 doc PR
Wave 2  (D3-D4)  S-02 链 + RLS 阶段 4    │ 4 PR
Wave 3  (D5-D7)  staging 部署 + 24h 观察 │ 0 PR + DevOps 执行
Wave 4  (D8)     E2E 5 项验收            │ 0 PR + QA 执行
Wave 5  (D9-D15) Prod 灰度 7d            │ 0 PR + DevOps + SRE
Wave 6  (D16-D21) RLS 阶段 5 + #199 merge │ 1 PR (#199) + DBA
Wave 7  (D22-D25) Cutover 后 cleanup merge│ 4 PR (#212/#213/#214/#215)
Wave 8  (D5-D8 并行) 17 token 轮换       │ DevOps + 品智客服
```

---

## 三、Wave 1 — Foundation merge（D1-D2）

### 任务

| # | 操作 | 估时 | 责任人 | 阻塞条件 |
|---|------|------|--------|----------|
| W1.1 | 6 PR 团队 review（独立可合）| 1d | Tech Lead + 2 reviewers | 无 |
| W1.2 | merge #205（doc only） | 5min | Tech Lead | W1.1 通过 |
| W1.3 | merge #211（doc + script） | 5min | Tech Lead | W1.1 通过 |
| W1.4 | merge #195（按 review checklist） | 30min | Tech Lead | W1.1 通过 + CI 全绿 |
| W1.5 | merge #196（NEW-P0 fix） | 15min | Tech Lead | W1.4 完成 |
| W1.6 | merge #200/#201（独立小 PR） | 15min | Tech Lead | W1.1 通过 |
| W1.7 | merge #207（RLS 阶段 4，不启用） | 15min | Tech Lead | W1.1 通过 |
| W1.8 | merge #216（S-01 + cutover runbook） | 5min | Tech Lead | W1.1 通过 |

### Wave 1 验收

- [ ] main 上 8 PR 已合：#195/#196/#200/#201/#205/#207/#211/#216
- [ ] CI 全绿（rls-gate / tier1-gate / pytest-tier1）
- [ ] 8 PR 的所有 Tier 1 测试在 main HEAD 100% 通过
- [ ] `RLS_USE_TX_SYSTEM_ROLE` 不设（双模式默认走老模式）

### 风险 / 应对

- ⚠️ **#195 vs #202 中间件顺序**：PR #202 在 #195 后会 rebase，#202 已修复（独立 review 验证）
- ⚠️ **#207 双模式 env 不设 = 行为与 main 一致**，安全降级
- ⚠️ 任何 PR review 发现新问题 → 不阻塞其他 PR；该 PR 进 hold-pending-fix 队列

---

## 四、Wave 2 — S-02 链 + 监控（D3-D4）

### 任务

| # | 操作 | 估时 | 责任人 | 阻塞条件 |
|---|------|------|--------|----------|
| W2.1 | rebase #202 onto main（W1.4 之后） | 30min | Tech Lead | W1.4 完成 |
| W2.2 | review + merge #202（InternalJwtMiddleware 实现） | 1h | Reviewer | W2.1 完成 |
| W2.3 | rebase + merge #206（tx-pay metric 补全） | 30min | Reviewer | W1.4 完成 |
| W2.4 | rebase #208 onto main（W2.2 之后） | 30min | Tech Lead | W2.2 完成 |
| W2.5 | review + merge #208（22 服务挂载） | 1h | Reviewer | W2.4 完成 + CI 绿 |
| W2.6 | rebase + merge #210（NetworkPolicy） | 30min | DevOps | W2.5 完成 |
| W2.7 | merge #203（cutover playbook doc） | 5min | Tech Lead | W2.5 完成 |

### Wave 2 验收

- [ ] main HEAD 含 12 PR：W1 8 个 + #202/#206/#208/#210
- [ ] `kubectl get networkpolicy -n tunxiang-staging` 显示 #210 模板（未应用）
- [ ] PR #208 测试 11/11 通过 + PR #215 修复版 4 个 webhook exempt 测试待 W7

### 风险 / 应对

- ⚠️ **#208 rebase 大概率冲突**（22 个 main.py 改动 vs main 演进）
  - mitigation: 用 `git rerere` + 自动 cherry-pick 脚本；冲突点全是 `from shared.security.src.internal_jwt_middleware import InternalJwtMiddleware\napp.add_middleware(InternalJwtMiddleware)` 同样的 import + add；用 sed 脚本批量解决
- ⚠️ **#210 NetworkPolicy 未应用 = 安全门户暂时打开**：是 Wave 3 staging deploy 的一部分

---

## 五、Wave 3 — Staging 部署 + 24h 观察（D5-D7）

详见 `docs/runbooks/cutover-staging-deployment.md`（PR #216）。

### 任务摘要

| # | 阶段 | 估时 | 责任人 | gate |
|---|------|------|--------|------|
| W3.A | 阶段 A：build images（main HEAD） | 2h | DevOps + CI | CI 全绿 |
| W3.B | 阶段 B：注 secret + RLS role + NetworkPolicy | 3h | DevOps + DBA | secret 22/22 服务可见 |
| W3.C | 阶段 C：rollout（gateway 先 + 22 并行） | 2h | DevOps | pod ready 100% |
| W3.D | 阶段 D：24h 观察 | 24h | SRE | 5xx 增 < 0.1% / P99 增 < 20% |

### Wave 3 验收

- [ ] 22 服务 staging pod 全部 Running
- [ ] InternalJwt-related 4xx 率 < 0.5%
- [ ] webhook 路径返 200（美团/饿了么/抖音手工触发或 mock）
- [ ] RLS-related 错误 = 0
- [ ] 24h 内 5xx 增量 vs 部署前同期 < 0.1%

### 回滚阈值（任一触发即回滚）

```
- InternalJwt 4xx 率 > 0.5%       → helm rollback gateway + tx-trade
- 任意服务 5xx 突增 > 0.1%         → 全 cutover 回滚（git checkout main 前一版）
- P99 延迟增 > 20%                 → 暂停灰度 + 调查
- webhook 路径 401 突增            → 立即回滚 #208（webhook 豁免在 #215 cleanup 才有）
```

⚠️ **重要 gap**：webhook exempt regex 在 PR #215 cleanup 才有，但 #215 是 DO NOT MERGE。
**Mitigation**: Wave 3 staging 部署前，先 cherry-pick #215 的 webhook regex commit 到 #208 的 main HEAD —— 作为热修。详见 §九"Wave 3 前置 hot-patch"。

---

## 六、Wave 4 — E2E 5 项验收（D8）

详见 `docs/runbooks/cutover-acceptance-checklist.md`（PR #216）。

| # | 验收项 | 估时 | 责任人 | gate |
|---|--------|------|--------|------|
| W4.1 | Tier 1 测试套（pytest tests/tier1/） | 2h | QA | 100% pass |
| W4.2 | k6 性能套（200 vus × 10min） | 1h | QA | P99 < 200ms / 错误率 < 0.1% |
| W4.3 | 支付全链路 3 渠道 6 用例 | 2h | QA + 收银员 | 全 200 + 3 metric 有数据 |
| W4.4 | 跨租户隔离 3 测试 | 30min | QA | A→B 跨租 0 行 + nodePort timeout |
| W4.5 | 断网 4h 恢复 | 4.5h | DevOps + QA | edge PG = cloud PG |

### Wave 4 验收

- [ ] 5/5 e2e 项目全绿
- [ ] k6 baseline JSON 已替换（OPS-004 闭环）→ 提 PR `ops/k6-baseline-staging-2026-XX`

---

## 七、Wave 5 — Prod 灰度 7d（D9-D15）

| # | 阶段 | 范围 | 时长 | 回滚阈值 |
|---|------|------|------|----------|
| W5.1 | Canary 1 | demo 环境 | 4h | 任意业务回归 |
| W5.2 | Canary 2 | 1 个真实店（尝在一起 文化城店） | 24h | RLS-related 错误 > 0 |
| W5.3 | Canary 3 | 整个尝在一起品牌（3 店） | 48h | 24h 5xx 增 > 0 |
| W5.4 | Full | 3 品牌全部 | 7d | 持续观察 |

### Wave 5 验收

- [ ] 7d prod 内 InternalJwt-related 5xx = 0
- [ ] RLS-related 错误 = 0
- [ ] payment_channel_call_total 3 渠道 × 3 method 全有数据
- [ ] 客户营业无投诉

---

## 八、Wave 6 — RLS 阶段 5 + #199 merge（D16-D21）

详见 `docs/security/rls-force-rollout.md` 阶段 5。

| # | 操作 | 责任人 | gate |
|---|------|--------|------|
| W6.1 | DBA 跑 `scripts/db/create_tx_system_role.sql`（staging） | DBA | role 创建成功 |
| W6.2 | env `RLS_USE_TX_SYSTEM_ROLE=true` 灰度 1 pod（staging） | DevOps | 4h 无 RLS 错误 |
| W6.3 | env 全量切（staging） | DevOps | 24h 无 RLS 错误 |
| W6.4 | DBA 跑 `ALTER ROLE tunxiang NOBYPASSRLS`（staging） | DBA | 旧 row_security=off 路径失效 |
| W6.5 | 验证 `tests/tier1/test_rls_force_no_bypass_tier1.py`（staging） | QA | 100% pass |
| W6.6 | rebase + 评审 + merge #199 (FORCE RLS migration) | Tech Lead + DBA | W6.5 通过 |
| W6.7 | staging 跑 alembic upgrade（#199 v500） | DevOps | 425+ 业务表 forcerowsecurity=true |
| W6.8 | 重复 W6.1-W6.7 在 prod | DBA + DevOps | 24h 无 5xx |

### Wave 6 验收

- [ ] `pg_tables.forcerowsecurity = true` 覆盖所有非 EXEMPT 业务表（≥ 425）
- [ ] `pg_roles.rolbypassrls = true` 仅 `tx_system_role`
- [ ] `tests/tier1/test_rls_force_no_bypass_tier1.py` 通过
- [ ] 24h prod RLS-related 5xx = 0

---

## 九、Wave 3 前置 hot-patch（webhook exempt）

PR #215 含 `_EXEMPT_REGEX = re.compile(r"/webhooks?(/|$)")`，但 #215 是 DO NOT MERGE。
Wave 3 部署 #208 时，**外部 webhook 会被 401 拦截**。

**操作**（D4.5，W2 之后 W3 之前）：
```bash
# 从 PR #215 的 commit d2573a7e cherry-pick webhook regex 到 main
git checkout main
git cherry-pick d2573a7e -X theirs --strategy=recursive \
  -- shared/security/src/internal_jwt_middleware.py \
     shared/security/tests/test_internal_jwt_middleware_tier1.py \
     .github/workflows/tier1-gate.yml \
     .github/workflows/deploy.yml

# 提为单独 PR，标注 "blocking #208 cutover"
git push origin HEAD:hotfix/internal-jwt-webhook-exempt-pre-cutover
gh pr create --base main --title "hotfix: InternalJwtMiddleware webhook 路径豁免（#208 cutover 前置）"
```

或者 **在 W2.4 (rebase #208) 时直接合入**：把 webhook regex commit 加到 #208 的 rebase 结果中，作为单 PR merge。

后续 #215 merge 时去掉重复 commit（在 cleanup PR rebase 阶段处理）。

---

## 十、Wave 7 — Cutover 后 cleanup merge（D22-D25）

只有 Wave 5 prod 7d 全绿 + Wave 6 RLS 阶段 5 完成后才能进入。

| # | PR | rebase target | 估时 | 责任人 |
|---|-----|---------------|------|--------|
| W7.1 | #212 (X-Tenant-ID fallback 删) | main HEAD（含 #208 + 已 webhook 豁免） | 1h rebase + 30min review | Tech Lead |
| W7.2 | #215 (InternalJwt fail-closed) | main HEAD（含 #208 + webhook 豁免；去掉重复 webhook regex commit） | 30min rebase | Reviewer |
| W7.3 | #213 (proxy simplify) | main HEAD（含 #195 + #208） | 15min rebase | Reviewer |
| W7.4 | #214 (RLS single mode) | main HEAD（含 #207 + #199 + RLS 阶段 5 完成） | 30min rebase | Reviewer + DBA |

每个 PR merge 后 prod 灰度 24h 观察。

---

## 十一、Wave 8 — 17 Token 轮换（D5-D8 并行 Wave 3）

详见 `docs/runbooks/s01-pinzhi-token-rotation.md`（PR #216 已交付）。

**关键**：与 Wave 3 staging 部署 **并行**，不阻塞主 cutover。

| # | 阶段 | 估时 | 责任人 |
|---|------|------|--------|
| W8.0 | 联系品智客服开 case | 1h | DevOps |
| W8.1 | 品智后台签发新 17 token（02:00 营业低谷） | 2h | 品智客服 + DevOps |
| W8.2 | 双 token 灰度 5% | 30min | DevOps |
| W8.3 | 全量切 + `verify_pinzhi_token_rotation.py` | 1h | DevOps + QA |
| W8.4 | git filter-repo 清历史 + 强推 | 30min | Tech Lead |
| W8.5 | 团队重新 clone（Slack 接龙） | 1d | 全团队 |
| W8.6 | 通知品智 revoke 老 token | 30min | DevOps |

### Wave 8 验收

- [ ] `python3 scripts/security/verify_pinzhi_token_rotation.py` 17/17 OK
- [ ] git filter-repo 后 4 文件 + 32-hex 字面值 grep = 0
- [ ] 品智回执邮件确认老 token revoke
- [ ] 24h prod `pinzhi_api_5xx_total` 无突增

---

## 十二、4 周日历视图

```
┌────────────────────────────────────────────────────────────────────────────┐
│ Week 1                                                                      │
│  D1-D2 Wave 1: 6 PR review + merge (foundation)                            │
│  D3-D4 Wave 2: 4 PR S-02 链 merge + #210 NetworkPolicy + #203 doc          │
│  D4.5  Hot-patch: webhook exempt cherry-pick                                │
│  D5-D7 Wave 3: staging 部署 + 24h 观察 ─┐                                   │
│                                          │ 并行                              │
│        Wave 8: 17 token 轮换 启动 ──────┘                                   │
├────────────────────────────────────────────────────────────────────────────┤
│ Week 2                                                                      │
│  D8        Wave 4: E2E 5 项验收                                              │
│  D9-D15    Wave 5: Prod 灰度 7d (canary 1→2→3→full)                         │
│            Wave 8 完成 + git filter-repo 强推                                │
├────────────────────────────────────────────────────────────────────────────┤
│ Week 3                                                                      │
│  D16-D21   Wave 6: RLS 阶段 5 + #199 merge (staging → prod)                 │
├────────────────────────────────────────────────────────────────────────────┤
│ Week 4                                                                      │
│  D22-D25   Wave 7: Cutover 后 cleanup #212/#213/#214/#215 依次 merge        │
│  D26-D28   缓冲：处理回归 / 文档收尾 / 复盘                                   │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 十三、关键路径 + 阻塞风险

```
关键路径（任一失败影响后续 wave）：
  W1.4 #195 → W2.2 #202 → W2.5 #208 → W3 staging → W4 e2e → W5 prod 灰度
       │                          │
       ↓                          ↓
  W2.7 #210                  D4.5 hot-patch (webhook exempt)
       │
       ↓
  W6 RLS 阶段 5 → W6.6 #199 merge
       │
       ↓
  W7 cutover cleanup #212/#213/#214/#215
```

**Top 5 阻塞风险**：

1. **#195 review 发现新 P0** → 全计划 hold 1-2d，先修再继续
2. **#208 rebase 冲突大** → 用 git rerere 自动化，预留 1d 缓冲
3. **Wave 3 webhook 401 漏过** → §九 hot-patch 已防御，但需 D4.5 必须执行
4. **Wave 5 prod 灰度发现 5xx** → canary 1 即可暴露，回滚到 main 前一版（仅损失 1d）
5. **Wave 6 DBA 操作错（NOBYPASSRLS 提前撤）** → 5 处合法 BYPASSRLS 调用挂掉；mitigation: PR #214 verify_tx_system_role_exists() 启动期检查

---

## 十四、RACI 表

| Wave | 任务 | R | A | C | I |
|------|------|---|---|---|---|
| W1 | PR review + merge | Reviewer team | Tech Lead | DevOps | 创始人 |
| W2 | rebase + merge | Tech Lead | Tech Lead | DevOps | 创始人 |
| W3 | staging 部署 | DevOps | Tech Lead | SRE | QA |
| W4 | E2E 验收 | QA | Tech Lead | DevOps | CSM |
| W5 | prod 灰度 | DevOps + SRE | Tech Lead | CSM | 创始人 + 客户 |
| W6 | RLS 阶段 5 | DBA | Tech Lead | DevOps | 创始人 |
| W7 | cleanup merge | Reviewer | Tech Lead | — | 创始人 |
| W8 | 17 token 轮换 | DevOps + 品智客服 | Tech Lead | 品智 | 创始人 |

---

## 十五、外部依赖 / 资源需求估算

| 角色 | 总投入 | 关键时间窗 |
|------|--------|------------|
| Tech Lead | 5 人天 | W1-W2 review + W7 rebase |
| Reviewer (×2) | 4 人天 | W1-W2 |
| DevOps | 8 人天 | W3 + W5 + W6 + W8 |
| DBA | 3 人天 | W6（含 staging + prod） |
| QA | 4 人天 | W4 + W8 |
| SRE | 7 人天（待命） | W3 D24h + W5 D7d 监控 |
| 品智客服 | 0.5 人天 | W8（D5 02:00-03:00 时间窗） |
| 创始人 | 1 人天 | W4/W6/W7 决策 |

**总：约 32.5 人天，关键瓶颈 = Tech Lead + DBA**

---

## 十六、判断成功的最终标准

cutover 完成 7d 后，下列全部 ✅ 才宣告 "审计 2026-05 闭环"：

- [ ] 18 PR 全部 merge 到 main（或被 superseded 关闭）
- [ ] prod 22 服务挂载 InternalJwtMiddleware + secret 全注入
- [ ] prod NetworkPolicy 全部应用 + nodePort 直连验证 timeout
- [ ] prod `pg_tables.forcerowsecurity = true` ≥ 425 张
- [ ] prod `pg_roles.rolbypassrls = true` 仅 `tx_system_role`
- [ ] prod 17 个品智 token 已轮换 + 老 token revoke
- [ ] git 历史 grep 无 32-hex 字面值
- [ ] prod 7d 内 InternalJwt-related 5xx = 0
- [ ] prod 7d 内 RLS-related 错误 = 0
- [ ] payment_channel_call_total 3 渠道 × 3 method 全有数据
- [ ] 客户营业无 cutover-related 投诉
- [ ] cutover 后 cleanup 4 PR 全 merge

**任意一项 ❌ → 计划失败，需补做或回滚**。
