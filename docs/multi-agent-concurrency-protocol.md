# 多智能体并发开发协议（Multi-Agent Concurrency Protocol）

> 创建日期：2026-05-04
> 适用范围：屯象OS 全仓
> 状态：v1（Living document — 随实战经验迭代）
>
> **PG.3 任务交付**：定义多 Claude Code Agent 在同一仓库并发开发时的隔离方案，
> 杜绝分支污染、push 互踩、CI 队列拥堵、admin merge 顺序错乱等问题。

---

## 一、问题背景

近期高峰期同时运行 4–6 个 Agent 会话（PG.2/PG.5/PG.6/P2.2/PI.1 …），
每个 Agent 独立完成"读 → 改 → commit → push → PR → CI → admin merge"全流程。
观察到的实际问题：

| 现象 | 触发原因 | 后果 |
|------|---------|------|
| **本地 worktree 互踩** | 多 Agent 同时 checkout 同分支或修同文件 | 提交丢失、IDE 状态错乱 |
| **push 失败 502 雪崩** | 公司代理 `127.0.0.1:53896` 间歇 502，多 Agent 同时重试加重压力 | 单次推送循环 30+ 次仍失败 |
| **PR base 漂移** | A 的 PR 在 B 合并 main 后过时 | rebase 冲突、CI 重跑、admin merge 链崩 |
| **CI 队列竞争** | 5 个 PR 同时跑 → 共用 runner 池 → 某些 PR 卡 5 分钟+ | 阻塞所有后续 admin merge |
| **守门测试相互发现污染** | A 的 tier1 守门测扫到 B 未合并的代码（但 A 拉了 B 的 worktree base） | 假阳性 fail，浪费 fix 一轮 |
| **配对测试网关级联红** | 改 Tier 1 源但忘加 *tier1*.py 测试 | 一次 commit → CI red → 补测 → 重跑 → 再 push |

---

## 二、隔离协议（强制）

### 协议 1：每任务一个 worktree，禁共享

```bash
# 标准位置（已验证可用）
git worktree add /Users/<user>/.tunxiang-p0-worktrees/<task-id> \
    -b feat/<descriptive-slug>-<task-id> origin/main

# 例：
git worktree add ~/.tunxiang-p0-worktrees/datetime-pg2 \
    -b feat/datetime-codemod-pg2 origin/main
```

**禁止**：
- 多 Agent 共用 `/Users/<user>/tunxiang-os` 主 clone（其作为 canonical 只读 + push hub）
- 跨 worktree 复用分支（Git 会拒绝，但 Agent 易踩）

**收尾**：合并后 `git worktree remove <path>` + `git branch -d <branch>`。

---

### 协议 2：分支命名 = `<type>/<slug>-<task-id>`

| 类型 | 前缀 | 示例 |
|------|------|------|
| 功能 | `feat/` | `feat/franchise-events-backfill-pg5` |
| 修复 | `fix/` | `fix/audit-outbox-flusher-flaky-ph7b` |
| 测试 | `test/` | `test/corporate-orders-db-rewrite-pg7` |
| 重构 | `refactor/` | `refactor/datetime-codemod-pg2` |
| 安全 | `security/` | `security/sql-fstring-param-p22` |
| CI/基建 | `ci/` `infra/` | `ci/migration-chain-allowlist-pi1` |

**任务 ID 必填**：避免重启会话后 Agent 找不到自己的分支。

---

### 协议 3：Push 失败重试 / Fallback 阶梯

```
1. git -c http.version=HTTP/1.1 -c http.postBuffer=524288000 push
   ↓ 失败（HTTP/2 framing layer / 502 / Empty reply）
2. 重试 3 次（间隔 5–8s，proxy 多为瞬时）
   ↓ 仍失败
3. 后台启动 30 次重试循环（5s 间隔，不阻塞主 Agent）
   ↓ 5 分钟后仍未恢复
4. 走 gh api fallback：
   - gh api -X POST /git/refs 创建新分支（如分支不存在）
   - gh api -X PUT /contents/<path> 逐文件上传（带 sha 字段）
```

**关键**：gh api 走独立 GitHub auth 通道，不受公司代理影响。
本协议在 PG.2/PG.5/P2.2 三次 502 雪崩中已验证有效。

**禁止**：force push 到他人分支；force push 到 main/master。

#### 删除 / 重命名 fallback（PJ.6 补充）

push 失败走 gh api 时，**写文件**用 PUT /contents 已记录在上面，但**删除/改名**和
**sha 规则**长期靠摸索。下次 422 之前先看本节：

- **删除**：
  ```bash
  gh api -X DELETE "/repos/<owner>/<repo>/contents/<path>" \
      -f sha=<file_sha> \
      -f branch=<branch> \
      -f message="<msg>"
  ```
  `sha` **必带**（GitHub 用它做乐观锁，否则 409/422）。

- **重命名**：等价于"PUT 新路径 + DELETE 旧路径"两次独立调用。
  GitHub Contents API 没有 atomic rename，容忍两次 commit；如要原子，回退用 git tree API。

- **文件级 sha 规则（核心 422 来源）**：
  | 场景 | sha 字段 | 后果 |
  |------|---------|------|
  | 已有文件 PUT（更新） | **必带** | 不带 → 422 "sha wasn't supplied" |
  | 新文件 PUT（创建） | **不能带** | 带了 → 422 "reference does not exist" |
  | 删除 DELETE | **必带** | 不带 → 422/409 |

  **推荐探测一次**再决定：
  ```bash
  gh api "/repos/<owner>/<repo>/contents/<path>?ref=<branch>" 2>/dev/null \
      | jq -r '.sha // empty'
  # 返回非空 → 已存在 → PUT 时带 sha；空/404 → 新建 → PUT 时不带 sha
  ```

**反模式**：不要先 `git rm <path>` 再 PUT —— PUT 是写文件接口不会删，旧文件仍在分支上。

---

### 协议 4：PR 顺序 = 依赖拓扑序

合并 PR 必须按依赖关系串行 admin merge，禁止并行 merge：

```
依赖链示例（实战）：
  PI.1 (CI 基建修复) → 解锁所有后续 PR 的 Migration Chain Gate
       ↓
  PG.4 (sync/pull endpoint) → 独立
  PG.6 (v396 last_event_id) → 独立
       ↓
  PG.5 (backfill 脚本) → 依赖 PG.6 已合并（脚本扫描 last_event_id 列）
  PG.2 (datetime codemod) → 独立
  P2.2 (f-string SQL 清理) → 独立
```

每次 merge 前：
1. 跑 `gh pr view <pr> --json mergeable` 确认 MERGEABLE
2. CI 真门禁全绿（Tier 1 / RLS / Migration Chain / Ruff / Edge / frontend-build）
3. legacy CI 失败（Test (xxx) / python-lint-test (xxx)）按 CLAUDE.md §17 admin merge

---

### 协议 5：CI 重跑期间禁推 next commit

观察到的反模式：

```
Agent 推 commit A → CI 起跑
   ↓ 等待中
Agent 又推 commit B（修 ruff 误报）→ CI 重跑 from B
   ↓ 但 commit A 的部分 job 仍在跑
   ↓ → CI 状态混乱、artifact 互覆盖、admin merge 误判
```

正确做法：
- 推 commit A 后 ≥ 240s（一轮 Tier 1 + Ruff 完整跑完）再推 commit B
- 或者：commit B 包含的修复必须明确地"叠加"在 A 之上（同一改动域）

---

### 协议 6：守门测试的"快照基线"

新增 tier1 守门测试（如 `test_no_sql_fstring_regression_tier1.py`、
`test_no_utcnow_regression_tier1.py`）必须包含：

1. **基线断言**：当前仓库 PASS（不能引入测试就 red）
2. **明示忽略路径**：测试文件自身、codemod 工具脚本必须在 ALLOWLIST
3. **失败信息可执行**：fail 时直接输出 grep 命中的 `path:line → src` 三元组，让下一个 Agent 一眼看到该改哪
4. **子进程命令使用 `sys.executable`**（避免 ruff S607 partial path）

---

### 协议 7：HTTP/2 失败 = 永远先怀疑 proxy

`fatal: unable to access ... HTTP2 framing layer / Empty reply / 502 / CONNECT tunnel failed`
**不是 git 问题，不是仓库问题，不是 token 问题**。

排查顺序：
1. `env | grep -i proxy` → 是否走 `127.0.0.1:53896`
2. `curl -I https://github.com` → 直连测速
3. `gh api meta` → gh CLI 通道是否通

如确认仅 git proxy 故障，立即跳到协议 3 step 4 的 gh api 兜底。

---

## 三、并发安全的 Code 模式

> 数据库层面的竞态已在 [race-condition-audit.md](./race-condition-audit.md) 详尽记录。
> 这里只补充 Agent 多会话特有的代码协作风险。

### 反模式：多 Agent 改同一文件的不同函数

```
Agent A 在 worktree-a 改 cashier_engine.py 的 charge() 函数
Agent B 在 worktree-b 改 cashier_engine.py 的 refund() 函数
两人同时 push → 后到的 PR rebase 冲突
```

**正确做法**：
- 改同一文件 = 串行任务（不要拆给多 Agent）
- 必须并行时：拆出独立模块（如 `cashier_engine_charge.py` / `cashier_engine_refund.py`），
  让两个 Agent 各持一文件

### 反模式：守门测试 + 业务代码同 PR 跨 Agent

```
Agent A 改业务（触发新 tier1 守门红）
Agent B 加守门测试（基于 main 当前状态，不知 A 已改业务）
合并顺序错 → A 的 PR 假绿合掉 → B 的 PR 突然红
```

**正确做法**：守门测试 + 配套业务清理 = 一个 PR 内完成（同一 Agent）。

---

## 四、Agent 自检清单（开 PR 前）

```
[ ] 我的 worktree 路径独立，未与其他 Agent 共用
[ ] 我的分支名带任务 ID（pg5/p22/...）
[ ] 我的 commit 消息按 CLAUDE.md §21 格式：[type]([service]): [描述] [Tier级别]
[ ] 改了 Tier 1 源 → 已加/改 *tier1*.py 配对测试（防"源/测试配对失败"网关）
[ ] 改了 RLS / migration → 已 grep 既有 USING/WITH CHECK 模式确认风格一致
[ ] PR 描述提到了依赖前置（"depends on PR #X merged"）
[ ] 本地跑 ruff check + ruff format + 相关 pytest 全绿
[ ] PR 开后 4 分钟内不推第二个 commit（除非合并修复）
[ ] 删除文件已用 DELETE /contents（带 sha + branch）而非 git rm 后 PUT —— 后者不会真正删除
```

---

## 五、协议演进

每次违反协议导致返工 → 把场景登记进上面"问题背景"表 → 协议条款相应升级。
拒绝靠"小心点"维持纪律 — 全部用工具/守门测试机械化执行。

| 版本 | 日期 | 变更 |
|------|------|------|
| v1 | 2026-05-04 | 初稿。基于 PG.2 + PG.5 + P2.2 + PI.1 + PH.7b 五次实战经验 |
| v1.1 | 2026-05-04 | PJ.6 补充：协议 3 加 DELETE/rename fallback + sha 三态规则；自检表加删除文件项 |
