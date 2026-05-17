# docs/governance/retros — 根因复盘目录

**目的**：将生产事故、重大 bug、流程失效的根因以文档形式落盘，防止同类问题重复出现。
**charter**：见 `../charter.md`。

---

## 命名规则

```
<YYYY-MM-DD>-retro-<topic-slug>.md
```

示例：
- `2026-04-12-retro-double-init-pr265.md` — PR #265 双 `__init__` 未抓双 `create_order`
- `2026-05-14-retro-structlog-event-kwarg.md` — structlog `event=` 字段冲突 4-PR 修复

---

## 复盘模板

每次根因复盘文件使用以下模板：

```markdown
# 根因复盘：<事件标题>

**日期**：YYYY-MM-DD
**严重度**：P0 / P1 / P2
**关联 PR**：#NNN
**关联 issue**：#NNN

---

## 近因（Proximate Cause）

直接触发问题的代码/操作描述。

## 根因（Root Cause）

系统性原因：流程缺失 / 测试盲区 / 规范不足 / 自动化缺失。

## 影响范围

- 受影响服务：
- 受影响时间窗口：
- 数据损失/业务中断：

## 修复措施（已执行）

- [ ] 代码修复（PR #NNN）
- [ ] 测试补全
- [ ] 文档更新

## 系统修复（防止复发）

| 修复项 | 负责人 | 截止日期 | 关联 issue |
|---|---|---|---|
|   |   |   |   |

## 经验教训（Lessons Learned）

1. 
2. 
```

---

## 索引

| 日期 | 事件 | 严重度 | 关联 PR |
|---|---|---|---|
| （新记录头插） |   |   |   |
