# 屯象OS 架构守门会 v1（charter）

**版本**：v1 (2026-05-15)
**生效**：W21 周一 (2026-05-18) 第一次会议起
**SoT**：战略 5/12 §6 工程治理体系 + §3 W2 任务 §2.5

---

## 1. 目的

集中处理跨服务架构决策、Tier 1 风险评估、服务收敛进度复盘，**避免决策散落在 PR review 与单 issue 评论中**。

具体做 3 件事：

1. **裁决 P0 架构决策**（如 wine_storage SoT / 服务收敛归位顺序 / Saga 跨步骤锁机制）
2. **跨服务协调 P1 议题**（如 router 跨界归位 / Outbox 切换批次 / Tier 1 修复 roadmap 排期）
3. **drift 监控**（CLAUDE.md 服务清单 vs 真实 main / Tier 1 路径行锁全扫 / silent failure baseline）

---

## 2. 节奏与时长

| 项 | 设置 |
|---|---|
| 频率 | 每周一上午 9:00（W21 = 5/18 起） |
| 时长 | 30 分钟硬上限 |
| 跳过条件 | 议程为空 + 无 P0 待裁 → 邮件汇报 drift snapshot 即可 |
| 月初加场 | 每月第一个周一加 15 分钟 — drift baseline re-classify（PR #666 §11 维护节奏） |

**时间硬上限**：30 分钟内决议不出的议题 → 升级为 ADR 走异步邮件 + 创始人单独决策。

---

## 3. 出席角色

| 角色 | 责任 | 必到 |
|---|---|---|
| 创始人 | 主持 / P0 裁决 / Tier 1 边界拍板 | ✅ |
| 架构议程准备方（agent / 主代理） | 议程草稿 / drift snapshot / 决议落盘 | ✅ |
| 独立 reviewer（轮值） | 反对方视角 / 风险提问 | ✅ |
| Tier 1 涉及服务 owner（如该周议题触及） | 影响评估 | 议题相关时到 |

议程准备方 = 上周决议指定的 agent（默认主代理）。

---

## 4. 议程结构（4 段 / 30 分钟分配）

| 段 | 时长 | 内容 |
|---|---:|---|
| §1 P0 决策待裁 | 12 min | 创始人决策点（如 wine_storage SoT / Saga 锁机制方向） |
| §2 P1 跨服务协调 | 8 min | 服务归位 / 修复 roadmap 排期 / Tier 1 follow-up |
| §3 Drift 监控 | 5 min | 服务清单 / silent failure baseline / 行锁审计 delta |
| §4 下周路线锁定 | 5 min | 下周 W+1 主题 + 任务 owner + W8 DEMO 进度 |

议程准备方在会议前 24h 把议程草稿（含 §1-§4 候选项）落到 `decisions/<iso-week>-<iso-date>-agenda-draft.md`，会上创始人勾选 / 否决 / 加项。

---

## 5. 文件命名与位置

```
docs/governance/
├── charter.md                    本文件（v1 - vN 演化）
└── decisions/
    ├── README.md                 目录索引 + 命名规则
    ├── 2026-W21-2026-05-18-agenda-draft.md   会前议程草稿
    ├── 2026-W21-2026-05-18-minutes.md        会后决议（如有）
    └── 2026-W22-...
```

命名规则：`<ISO-year-week>-<YYYY-MM-DD>-<type>.md`，type ∈ {agenda-draft, minutes, decision-followup}。

---

## 6. Decision vs ADR

| 维度 | Decision（本目录） | ADR (`docs/adr/`) |
|---|---|---|
| 时间维度 | 周度运营 | 长效架构（数月-数年） |
| 触发 | 守门会议程 | 重大架构选型（如服务边界 / 数据模型 / 协议设计） |
| 谁起草 | 议程准备方 | 提议者 + 创始人共识后形成 |
| 是否阻塞代码 | 否（指引性） | 是（违反 ADR 需先改 ADR） |
| 例 | "本周修 issue #535 wine_storage SoT 方向 A" | "ADR 0001 services 命名空间 import 规范" |

**升级路径**：连续 2 周同一 decision 反复出现 → 升级为 ADR 候选。

---

## 7. 决议落盘格式（minutes 模板）

见 `decisions/<W>-<date>-template.md`（已落第一份 W21 模板）。

最小必填项：

- 会议时间 / 主持 / 出席
- §1-§4 各段决议（每条 1-3 行）
- 每条决议的 owner + due date + 验证标准
- 下周议程候选种子（提前预告）

---

## 8. 与现有 SoT 的衔接

| 现有 | 本守门会的关系 |
|---|---|
| CLAUDE.md（项目宪法） | 守门会**不修 CLAUDE.md**，但会议决议可以触发独立 PR 改 CLAUDE.md（如服务清单更新） |
| `.omc/policy/service-freeze.yml` | 服务变更必须走守门会决议后再改 freeze 清单 |
| `docs/architecture/tx-trade-router-taxonomy.md` | 跨界归位评估输入 |
| `docs/security/tier1-row-lock-audit-2026-05.md` | Tier 1 修复 roadmap 排期依据 |
| `docs/service-health/<W>.md` | drift 监控基线 |
| 战略 5/12 SoT（Desktop / 不在 git） | 议程优先级源头，但守门会决议本身仍以本目录文件为 SoT |

---

## 9. 不在本 charter 范围

| 主题 | 去处 |
|---|---|
| Tier 1 PR 单 PR 审查 | §19 reviewer + `docs/review/tier1-checklist.md` |
| 单服务内部重构 | 服务 owner 自决 + PR review |
| 紧急 incident 响应 | 不走守门会（同步处理后补 decision 入档） |
| 创始人 3 决策（5/12 §9 已锁定） | 不重答 — 直接执行 |

---

## 10. 变更记录

| 版本 | 日期 | 变更 | 触发 |
|---|---|---|---|
| v1 | 2026-05-15 | 初版 charter（W2.5） | 战略 5/12 §6 工程治理体系 + PR #666 §11 评估输入需求 |
