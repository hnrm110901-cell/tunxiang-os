# Governance Decisions（架构守门会决议目录）

**目的**：守门会每周议程草稿、会议纪要、跨周 follow-up 决议落盘。
**charter**：见 `../charter.md`。

---

## 命名规则

```
<ISO-year-week>-<YYYY-MM-DD>-<type>.md
```

| type | 用途 | 何时落 |
|---|---|---|
| `agenda-draft` | 会前议程草稿（议程准备方起草） | 会前 24h |
| `minutes` | 会议纪要（含决议） | 会议结束当日 |
| `decision-followup` | 周会后单独跟进的决议（如异步邮件裁决） | 决议形成当日 |

例：

- `2026-W21-2026-05-18-agenda-draft.md`
- `2026-W21-2026-05-18-minutes.md`
- `2026-W21-2026-05-21-decision-followup.md`（周中 follow-up）

---

## 索引

| 周 | 日期 | agenda | minutes | follow-up |
|---|---|---|---|---|
| W21 | 2026-05-18 | [agenda-draft](2026-W21-2026-05-18-agenda-draft.md) | — | — |

每次新会议在本表头插入一行（最新在上）。

---

## 与 ADR 的关系

见 `../charter.md` §6。
- ADR (`docs/adr/`) = 长效架构决策（months-years）
- Decision（本目录）= 周度运营决议（week-quarter）
- 连续 2 周同一 decision 反复 → 升级为 ADR 候选
