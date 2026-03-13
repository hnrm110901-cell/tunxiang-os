# /new-feature — 新功能开发流程

当用户输入 `/new-feature <功能描述>` 时，严格按以下流程执行。

## Phase 1: Research（研究）

1. 读取 `CLAUDE.md` 确认功能是否在 MVP 范围内
2. 读取 `ARCHITECTURE.md` 确认涉及哪些模块
3. 读取相关模块的 `CONTEXT.md`
4. 用 Grep/Glob 搜索是否已有相关实现（避免重复造轮子）
5. 检查 `tasks/lessons.md` 中是否有相关经验教训

**输出**：
- 功能是否在 MVP 范围内（如不在，需确认是否客户明确要求）
- 涉及的模块和文件清单
- 已有可复用的 Service/Component
- 潜在风险点

## Phase 2: Plan（规划）

使用 Plan Mode，输出变更蓝图：

```
## 功能：{功能名称}

### 涉及层级
- [ ] 模型层（models/）— 新增/修改表
- [ ] 服务层（services/）— 新增/修改服务
- [ ] Agent 层（packages/agents/）— 新增/修改 Agent
- [ ] 路由层（api/）— 新增/修改端点
- [ ] 前端（apps/web/）— 新增/修改页面
- [ ] 迁移（alembic/）— 数据库迁移
- [ ] 适配器（api-adapters/）— POS 集成

### 文件变更清单
| 文件 | 操作 | 变更意图 |
|------|------|---------|
| ... | 新增/修改 | 一句话描述 |

### 风险评估
- 多租户影响：...
- 金额相关：...
- 级联影响：...

### 测试计划
- ...
```

**等待用户确认后再进入 Phase 3**

## Phase 3: Implement（实现）

按以下顺序实现：

1. **数据模型**（如需）→ 注册到 `models/__init__.py` → 生成 Alembic migration
2. **服务层**（核心业务逻辑）→ 金额用分存储 → 中文注释关键逻辑
3. **Agent 层**（如需）→ 放在 `packages/agents/{domain}/`
4. **API 路由** → RESTful + 参数校验 → 注册到 `main.py`
5. **前端页面**（如需）→ 角色路由 + Z 组件 + CSS Modules + BFF
6. **企业微信推送**（如需）→ 决策型内容（动作+￥影响+置信度）

每完成一个步骤，更新 TodoWrite 进度。

## Phase 4: Validate（验证）

1. 编写测试（参考 tester agent 规范）
2. 运行测试：`pytest apps/api-gateway/tests/ -v`
3. 如涉及 Agent：独立运行 `pytest packages/agents/{domain}/tests -v`
4. 如涉及前端：`cd apps/web && pnpm test`
5. 如涉及数据库：`make migrate-up` 验证迁移
6. 自检：「一个高级工程师会批准这个吗？」

**输出验证报告后，功能开发完成。**
