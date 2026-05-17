# docs/governance/policies — 治理政策目录

**目的**：经架构守门会批准的长效运营政策，不随项目迭代过期。每条政策与 GitHub issue 或 ADR 编号绑定。
**charter**：见 `../charter.md`。

---

## 命名规则

```
<policy-id>-<slug>.md
```

示例：
- `P001-service-freeze.md` — 服务冻结策略（issue #755）
- `P002-ontology-freeze.md` — Ontology 层冻结策略（CLAUDE.md §18）
- `P003-tier1-adjacent-review.md` — Tier 1 邻接代码强制 §19 review

---

## 现行政策索引

| ID | 标题 | 状态 | 关联 issue / ADR | 生效日期 |
|---|---|---|---|---|
| P001 | 服务冻结（新服务必须守门会批准） | 草案 | #755 | 待 W21 守门会确认 |
| P002 | Ontology 层冻结（`shared/ontology/` 不得 Agent 自动修改） | 生效 | CLAUDE.md §18 | 2026-04-01 |
| P003 | Tier 1 邻接代码强制 §19 独立 review | 生效 | CLAUDE.md §17/§19 | 2026-04-01 |
| P004 | CLAUDE.md drift 超 10% 自动报警（`clauded-md-drift-check.py`） | 生效 | #761 | 2026-05-17 |
| P005 | 每周 code-fact-scan 落盘服务健康度报告 | 生效 | #761 | 2026-05-17 |

---

## 政策模板

```markdown
# P<NNN>：<政策标题>

**版本**：v1
**状态**：草案 / 生效 / 废止
**关联 issue / ADR**：#NNN
**生效日期**：YYYY-MM-DD
**批准会议**：YYYY-WXX 守门会

---

## 背景

为什么需要这条政策（问题场景）。

## 政策内容

具体规则，可操作，可机器验证。

## 例外处理

允许的例外情况 + 例外批准流程。

## 自动化执行

关联的 CI hook / script / workflow。

## 废止条件

什么情况下本政策可被废止或修订。
```
