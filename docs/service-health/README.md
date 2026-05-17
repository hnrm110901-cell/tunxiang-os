# docs/service-health — 服务健康度目录

**目的**：记录每周 code-fact-scan 输出和每月服务健康度评分，为守门会决策提供量化基线。
**charter**：见 `../governance/charter.md`。

---

## 文件命名规则

| 类型 | 命名 | 频次 |
|---|---|---|
| 周度 code-fact-scan | `YYYY-WXX.md` | 每周一自动生成（`weekly-health-check.yml` cron） |
| 月度评分 | `monthly/YYYY-MM.md` | 每月末守门会手动汇总 |
| CLAUDE.md drift check | `drift-YYYY-MM-DD.md` | PR 触发 + 每周一 cron（`claudemd-drift-check.yml`） |

---

## code-fact-scan 输出格式

每个 `YYYY-WXX.md` 包含：

```markdown
# 服务健康度报告 — YYYY-WXX

- **执行时间**: ISO 8601
- **Git commit**: `<sha8>`
- **扫描服务数**: N

## 主表格

| 服务名 | main_loc | router_count | commits_30d | try_except_count | silent_failure_count |
| --- | ---: | ---: | ---: | ---: | ---: |
| gateway | ... | ... | ... | ... | ... |
```

字段说明：

| 字段 | 含义 |
|---|---|
| `main_loc` | 主包 Python LOC（不含测试/迁移） |
| `router_count` | FastAPI router 数 |
| `commits_30d` | 近 30 天 commit 数（活跃度） |
| `try_except_count` | `try/except` 块总数（越高越需审查） |
| `silent_failure_count` | `except ... pass` / 无 log 吞异常数（Tier 1 红线） |

**Ratchet 规则**：`silent_failure_count` 只降不升。若单周上升须在守门会说明原因。

---

## 月度评分 rubric（0-10）

每月对每个服务评一个综合健康分：

| 分档 | 含义 |
|---|---|
| 9-10 | 无 silent failure，测试覆盖 >80%，P99<200ms，0 Tier 1 未修 issue |
| 7-8 | 少量 silent failure（<5），Tier 1 均有 follow-up issue 跟进 |
| 5-6 | silent failure 中等（5-15），有 Tier 1 issue 未 fix |
| 3-4 | silent failure 多（>15），Tier 1 issue backlog 积压 |
| 0-2 | 重大事故 / 数据丢失风险 / Tier 1 路径不稳定 |

**评分输入**：
1. code-fact-scan `silent_failure_count` 趋势（过去 4 周）
2. Tier 1 open issue 数
3. CI 失败率（`tier1-gate.yml` 近 4 周通过率）
4. P99 延迟（若有性能测试数据）

---

## 基线（W20 2026-05-15 实测）

服务数：20，threshold 告警：`silent_failure_count > 15`（参考 W20 数据 15/20 服务超阈值）。

详见：[2026-W20.md](./2026-W20.md)

---

## 相关自动化

- `scripts/code-fact-scan.py` — 扫描脚本（PR #659 ship）
- `scripts/clauded-md-drift-check.py` — CLAUDE.md drift 检查（issue #761）
- `.github/workflows/weekly-health-check.yml` — 每周一 09:00 CST cron
- `.github/workflows/claudemd-drift-check.yml` — PR + 每周一 cron
