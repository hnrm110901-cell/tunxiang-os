# 屯象OS · 每周 AI 代码自审手册

> 执行频率：每周五下午
> 执行人：Claude Code（在新会话中执行）
> 目标：发现上周引入的高风险代码，防止技术债累积到生产环境

---

## 第一步：运行健康度检查脚本

```bash
cd /Users/lichun/tunxiang-os
bash scripts/weekly-health-check.sh
```

输出保存到：docs/code-health-YYYY-WW.md

---

## 第二步：AI 自审 Prompt（在新会话中使用）

将以下内容粘贴到新的 Claude Code 会话开头：

---

你是屯象OS的安全架构师，不是开发者。本周完成的代码修改如下：

[粘贴本周 git log --oneline --since="7 days ago" 的输出]

请重点审查本周涉及以下路径的修改：
- services/tx-trade/services/（订单/支付/存酒）
- services/tx-finance/services/（发票/结算）
- shared/db-migrations/（数据库迁移）

从以下维度找出所有风险，每个风险给出攻击路径和修复代码：

1. **并发安全**：高并发下有无竞态条件、死锁、连接池耗尽？
2. **幂等性**：重试是否安全？支付/扣款接口是否防重复执行？
3. **缓存安全**：有无缓存击穿/穿透/雪崩风险？
4. **RLS有效性**：每个DB查询是否携带 tenant_id？有无绕过RLS的路径？
5. **资金安全**：余额/押金/积分的增减是否原子操作？
6. **依赖安全**：新增的第三方库是否真实存在且安全？

如发现风险，直接给出修复代码，不要只描述问题。
将所有发现记录到 docs/weekly-review-YYYY-MM-DD.md。

---

## 第三步：Tier 1 测试全量运行

```bash
cd /Users/lichun/tunxiang-os
# 运行所有 Tier 1 测试
python -m pytest services/tx-trade/tests/test_*_tier1.py -v --tb=short
python -m pytest services/tx-finance/tests/test_*_tier1.py -v --tb=short
```

全部通过才能视为本周代码安全。

---

## 第四步：记录本周健康度评分

在 DEVLOG.md 顶部追加：

```markdown
## YYYY-MM-DD（周五健康度检查）
- Tier 1 测试：X/X 通过
- 新发现风险：N 个（详见 docs/weekly-review-YYYY-MM-DD.md）
- 已修复：N 个
- 遗留风险：N 个（需下周处理）
```

---

## 历史报告

| 日期 | Tier1通过率 | 发现风险 | 已修复 |
|------|-----------|---------|------|
（每次执行后在此添加记录）
