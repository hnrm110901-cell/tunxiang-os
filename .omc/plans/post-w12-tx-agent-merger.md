# Post-W12 智能层收敛计划（占位）

**状态**：🟡 占位 / 待规划（2026-05-06 sprint-0-dedup R4 立项）
**触发时间**：W12（2026-07-29）之后，徐记 demo 验收完成后
**前置条件**：W8 demo 通过 + V4 架构对齐 sprint 完成 + 至少 1 家门店稳定运行 1 个月

---

## 一、合并目标

把 4 个独立 AI service 物理收敛到 `services/tx-agent/sub/` 子模块结构：

```
services/tx-agent/                       :8008  (主服务)
  └── src/
      ├── (现有 agents / api / 9 大 Skill Agent / 73 actions)
      └── sub/
          ├── brain/      ← 接收 tx-brain  (Voice AI + CFO Dashboard + Evolution 2030)
          ├── intel/      ← 接收 tx-intel  (竞对监测 / 消费洞察 / 新品雷达等 8 模块)
          └── predict/    ← 接收 tx-predict (客流 / 需求 / 营收预测 + 和风天气)
```

退役端口：`:8010`、`:8011`、`:8013`（gateway 路由内部 rewrite 到 `:8008`）

---

## 二、合并动机

| 现状 | 数据 |
|---|---|
| `tx-agent` (主服务) | 258 py / 43 routes |
| `tx-brain` | 65 py / 9 routes |
| `tx-intel` | 46 py / 10 routes |
| `tx-predict` | 19 py / 6 routes |
| **3 子服务总计** | **130 py / 25 routes** |

**问题**：
1. 命名重叠（脑/智能/预测/Agent 在 AI 语境下没有清晰边界）
2. 决策链路分散——actor-critic 模式（V4 Sprint 引入）需 Agent 在同一进程闭环
3. AgentDecisionLog 跨 service 写不一致
4. Ontology Client 重复实例化

**Hassabis 论据**：DeepMind 的 alpha* 系列也是收敛到统一 platform 而非 N 个微服务，因为推理链路要在同一进程。

---

## 三、不在 W8 之前做的理由

1. W8 demo 是徐记验收硬窗口，所有 Tier 1 路径要稳定——合并 4 个 service = 重启 + 路由迁移 + DI 重布线，引入 Tier 1 风险
2. V4 架构对齐 sprint（D1-D7）已经吃 W8 前 1 周，再叠加合并 = 时间不够
3. 合并的真正价值在 W8 之后才显现（actor-critic 闭环 + 决策日志统一）

---

## 四、Post-W12 启动条件（hard gate）

满足以下**全部**才启动本计划：

- [ ] W8 demo 在徐记现场通过（5 项门槛全绿）
- [ ] V4 架构对齐 sprint 已 ship + 商米 T2 真机稳定 1 个月
- [ ] 至少 1 家门店在生产环境稳定运行 1 个月（无 Tier 1 故障）
- [ ] tx-agent 主服务有 actor-critic 实装 + AgentDecisionLog 落库
- [ ] CLAUDE.md §九 Agent 规范已修订到位（W8 demo 后必然要更新）

---

## 五、合并步骤（占位，待 W11 细化）

1. 路由前缀冲突排查（4 个 service 的 `/api/v1/*` 是否有同名）
2. DI 容器统一（数据库连接 / Redis / Claude Client）
3. import 路径迁移（`services.tx_brain.*` → `services.tx_agent.sub.brain.*`）
4. 测试套件合并 + 跨域测试新增
5. gateway 路由 rewrite（`:8010/:8011/:8013` → `:8008` 内部转发）
6. Helm chart 退役 3 个 chart（如启用过 K8s）/ Compose 退役 3 个服务定义
7. 发布灰度：5% → 50% → 100%
8. 退役端口监控：3 个端口 24h 0 流量后正式删 service 目录

预估工时：1 个工程周（含测试）

---

## 六、与 sprint-0-dedup R4 的关系

- sprint-0-dedup R4 仅做 marker（在 3 个 service README 顶部加 banner + 创建本占位文档）
- ❌ R4 不动代码
- ✅ 本计划独立 PR，独立工作分支 `feat/post-w12-tx-agent-merger`
- W11（2026-07-22 左右）开始细化本计划

---

## 七、风险

- AgentDecisionLog 数据迁移（如果 tx-brain/intel/predict 有自己的 log 表）
- Voice AI 在合并后的延迟（ASR + NLU 同进程 vs 跨服务）
- CFO Dashboard 的 SSE/WebSocket 长连接迁移
- 端口客户端硬编码（如有）

---

## 八、撤销

如果合并后发现"独立 service 才符合业务"（譬如 Voice AI 资源占用大需独立 scale），允许回退：
- 保留旧 commit + 单独 service 目录在 git history
- 撤销前必须找到具体业务原因（不能因为"工程麻烦"而回退）
