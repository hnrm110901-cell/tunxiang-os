# 屯象OS 安全审计索引

本目录是屯象OS 安全审计活历史的 SoT（source of truth）。CLAUDE.md §14 + README 都引用本索引。

## 当前活跃审计

| 报告 | 日期 | Mode | Findings | 状态 |
|---|---|---|---|---|
| [CSO 2026-05-11](./cso-report-2026-05-11.md) | 2026-05-11 | Daily（8/10 confidence gate） | 3 HIGH / 2 MEDIUM / 1 TENTATIVE / 1 INFO | 部分修复中（PR #437 已 merged，F#2/F#5/F#6/F#7 排单） |

## 已 closed 历史审计

| 审计 | 日期 | Findings | 修复 PR | DEVLOG 锚点 |
|---|---|---|---|---|
| v6 代码审计 Phase 1 | 2026-04-12 | C2 / H1 / H3 / H4 / H5 / M4 + P0-2 | 修复成果迁移见 `68ffdfca feat: v6审计修复成果迁移 + 安全加固 + 200个测试` | DEVLOG.md 2026-04-12 节 |
| 生产前安全审计全量修复 | 2026-05-03 | — | — | DEVLOG.md 2026-05-03 节（2317 行起） |

历史报告原文（`docs/security-audit-report.md` 和 `docs/development-plan-v6-remediation.md`）已在 `9e6f99d7 chore: 清理28个过时/冗余文档` 中删除 — 内容已固化进 CLAUDE.md §14 + DEVLOG。

## 域专项审计

| 报告 | 主题 |
|---|---|
| [pg7 RLS UPDATE policy 残留](./pg7-rls-update-policy-residual.md) | PostgreSQL 7 RLS UPDATE 策略边缘场景 |

## 如何更新本索引

- 跑完一次 `/cso`（或 `/cso --comprehensive`）后，输出落盘到 `docs/security/cso-report-{date}.md`
- 本 INDEX.md 顶部「当前活跃审计」表新增一行；上一行视情况移到「已 closed 历史审计」
- 机器可读 JSON 同时落盘到 `.gstack/security-reports/{date}-{HHMMSS}.json`（注意 `.gstack/` 未 gitignore — 决定是否 commit 由该次审计执行者裁决）
- CLAUDE.md §14 + README.md 表格只引用本 INDEX，**不直接引用日期报告**，避免 doc-rot
