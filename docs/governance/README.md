# docs/governance — 治理四件套目录

> 来源：战略 plan 5/12 §3 W2 治理 + §6 工程治理体系（12 周全程）

---

## 治理四件套节奏

| 频次 | 动作 | 产出路径 |
|---|---|---|
| **每周一** | 代码事实扫描（`scripts/code-fact-scan.py`） | `docs/service-health/YYYY-WXX.md` |
| **每两周（守门会）** | 架构守门会 30 min：过下两周 PR 的服务边界 / DB 写入 / 事件发射 / Tier 等级 | `docs/governance/decisions/` |
| **每月** | 服务健康度评分 0-10 | `docs/service-health/monthly/` |
| **每季度** | 多专家团队 review（Hassabis / Musk / Palantir / SAP 四视角）→ 校准战略 | 战略校准文档（`docs/governance/decisions/YYYY-WXX-strategic-calibration.md`） |

---

## 子目录用途

| 目录 | 用途 |
|---|---|
| `decisions/` | 守门会每周议程草稿、会议纪要、跨周 follow-up 决议。命名：`<ISO-year-week>-<YYYY-MM-DD>-<type>.md` |
| `retros/` | 根因复盘（近因 → 根因 → 系统修复）。命名：`<YYYY-MM-DD>-retro-<topic>.md` |
| `policies/` | 经守门会批准的长效策略文档，不随时间过期。每条政策与 issue 或 ADR 编号绑定 |
| `charter.md` | 守门会宪章 v1（成员 / 频次 / 权限 / 决议流程） |

---

## 自动化 hook（§6 治理四件套）

- `scripts/code-fact-scan.py` — 每周一自动扫描所有服务，输出 `docs/service-health/YYYY-WXX.md`。CI workflow: `.github/workflows/weekly-health-check.yml`
- `scripts/clauded-md-drift-check.py` — 检测 CLAUDE.md 与现实代码脱节 > 10% 报警，exit 1。CI workflow: `.github/workflows/claudemd-drift-check.yml`
- `.omc/policy/service-freeze.yml` — 拦截新服务文件（issue #755 落盘）

---

## 相关文档

- `docs/governance/charter.md` — 守门会宪章（频次 / 成员 / 决议权限）
- `docs/review/tier1-checklist.md` — Tier 1 PR reviewer 侧核查清单（§19 reviewer 工具）
- `docs/audit-2026-05/reviewer-checklist.md` — 历史审计 reviewer checklist（2026-05 审计期）
- `docs/service-health/` — 每周 code-fact-scan 输出 + 月度评分
- `docs/adr/` — 长效架构决策（ADR）

---

## 与 ADR 的关系

- ADR (`docs/adr/`) = 长效架构决策（months-years），一旦通过不轻易修改
- Decision（`decisions/`）= 周度运营决议（week-quarter），跟随项目快速演进
- 连续 2 周同一 decision 反复 → 升级为 ADR 候选
