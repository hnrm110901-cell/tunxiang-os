# 屯象OS 升级迭代统一规划 V1.0（2026 Q2）

> 本文件为管理**唯一真源**，替代 V4/V6 并行分裂状态。V4/V6 文档冻结于当前版本，新增只追加到本文件。
> 生效日期：2026-04-18
> 周期：10 周（W1 = 2026-04-21）
> 硬门槛：W8（2026-06-09）徐记海鲜现场 DEMO 过 10 项 Go/No-Go

---

## 1. 8 个 Sprint 总览

| Sprint | 主题 | 周 | Tier | Owner | 估时 | Flag 前缀 |
|---|---|---|---|---|---|---|
| A | 收银链路稳定性 Hardening | W1-2 | T1 | 交易+前端 | 18.5 人日 | `trade.pos.*` |
| C | KDS 端本地强化 | W2-3 | T1 | 前端+边缘 | 14 人日 | `edge.kds.*` |
| B | 合规红线补齐 | W3-5 | T1 | HR+财务+Civic | 24 人日 | `compliance.*` |
| F | 演示体验完整化 | W3-4 | T3 | QA+架构师 | 18 人日 | — |
| D | AI 管理层标准化 | W4-9 | T2 | AI+后端 | 1000 人时 | `agent.*` |
| E | 外卖渠道全景统一 | W5-7 | T2 | 交易 | 17 人日 | `channel.*` |
| G | A/B 测试框架 | W6-8 | T3 | 增长+分析 | 14 人日 | `experiment.*` |
| H | 企业级集成验证 | W7-10 | T2 | QA+运维 | 22 人日 | — |

合计 ~128 人日 + 1000 AI 人时，峰值并行 5 FTE。

---

## 2. Sprint 立项卡

### Sprint A · 收银链路 T1（W1-2）
**边界**：apps/web-pos、services/tx-trade、shared/security  
**子项**：
- A1 ErrorBoundary + 3s 超时 + Toast（v260 pos_crash_reports）
- A2 Saga 本地 SQLite 缓冲 4h（v261 saga_buffer_meta）
- A3 离线订单号 UUID v7 + 死信待确认（v262 offline_order_mapping）
- A4 RBAC 装饰器 + trade_audit_logs（v263 trade_audit_logs）

**门禁**：DEMO 断网 100 单零丢失、越权 403、audit_log 全覆盖、5%→50%→100% 灰度
**Flag**：`trade.pos.settle.hardening` / `edge.payment.saga_buffer` / `edge.offline.order_id_bridge` / `trade.rbac.strict`

### Sprint C · KDS 端 T1（W2-3）
**边界**：apps/web-kds、edge/sync-engine  
**子项**：C1 IndexedDB last-100 / C2 connectionHealth / C3 `/kds/orders/delta` + device_kind / C4 Playwright 4h E2E  
**迁移**：v264 edge_device_registry  
**门禁**：IDB<20MB、4h 零卡顿、恢复 60s 全同步

### Sprint B · 合规（W3-5）
**子项**：B1 加班 36h 冻结（v263 schedule_compliance_blocks）/ B2 金税四期+OCR（v263-264 invoice_xml_archive + invoice_ocr_jobs）/ B3 湘食通（v265 civic_traceability_submissions）/ B4 劳动合同扫描（v266 employee_labor_contracts）  
**前置**：合规需求 workshop 5d + 供应商采购 10d（诺诺全电 / 腾讯+阿里 OCR / 湘食通账号 / 沪食安）  
**罚款量化**：B1 ¥2.4M / 10 店、B2 单张拒收 500-2000+失信、B3 食安法 5-10 万、B4 2N 人均 1.6 万

### Sprint D · AI 管理层（W4-9）
**子项**：  
- D1 51 Skill ConstraintChecker 覆盖（批次化 6 周）
- D2 ROI 三字段（v263 `saved_labor_hours / prevented_loss_fen / improved_kpi / roi_evidence` + `mv_agent_roi_monthly`）
- D3a RFM 触达 Haiku 4.5+CF（复购率 +5pp）
- D3b 活动 ROI Prophet+Sonnet（MAPE<20%）
- D3c 菜品动态定价 边缘 Core ML+云端拟合（毛利 +2pp）
- D4a 成本根因 / D4b 薪资异常 / D4c 预算预测（Sonnet 4.7 + Prompt Cache ≥75%）

**模型成本月上限 ¥12,000**（Prompt Cache 后可降 40%）

### Sprint E · 外卖中心（W5-7）
**子项**：E1 canonical schema（v267）/ E2 一键发布（v268）/ E3 小红书核销 / E4 异议工作流（v269）  
**外部依赖**：小红书 ISV 审核（~2 周）、抖音团购服务商资质

### Sprint F · 演示体验（W3-4）
**子项**：F1 14 适配器 7 维评分卡 / F2 pytest+toxiproxy 断网 CI / F3 三商户 playbook（czyz/zqx/sgc）  
**门槛**：适配器评分 ≥22 才能上生产

### Sprint G · A/B 框架（W6-8）
**子项**：G1 纯函数分桶（v260 experiment_exposures）/ G2 Orchestrator 判桶 / G3 Welch's t-test 仪表板 / G4 熔断规则  
**熔断阈值**：单日核心指标跌幅>20% 自动关 flag

### Sprint H · 集成验证（W7-10）
**子项**：H1 k6 16k TPS / H2 7 维 Go/No-Go / H3 安全终查 / H4 `scripts/week8_gate_check.sh`

---

## 3. Week 8 徐记 DEMO Go/No-Go（10 项）

```
□ 1. Tier 1 测试 100% 通过
□ 2. k6 P99 < 200ms
□ 3. 支付成功率 > 99.9%
□ 4. 断网 4h E2E 绿（nightly 连续 3 日）
□ 5. 收银员零培训（3 位签字）
□ 6. 三商户 scorecard ≥ 85
□ 7. RLS/凭证/端口/CORS/secrets 零告警
□ 8. scripts/demo-reset.sh 回退验证
□ 9. 至少 1 个 A/B 实验 running 未熔断
□ 10. 三套演示话术打印就位
```

---

## 4. 需创始人签字的 5 个决策点

1. **D2 `agent_decision_logs` 新增 6 列** — 核心留痕变更
2. **E1 小红书升级为一级 channel** — 影响分渠道 P&L
3. **B1 Override 签名** — HRD+CEO 双签 vs 加法务三签
4. **B2 红冲双签阈值** — 建议 ≥¥10k
5. **E4 异议自动接受上限** — 建议 ≤¥50 auto-accept

---

## 5. 与 V4/V6 的合并映射

| 现有计划 | 归入 Sprint |
|---|---|
| V4 Phase 0 broad except 收窄 | A1 前置 |
| V4 Phase 1 sync-engine 协议 | A3+C3 字段协议统一 |
| V4 Phase 1.3 断网收银 E2E | C4 验收证据 |
| V4 Phase 3.2 薪资+加班 | B1+D4b |
| V4 Phase 3.3 增长+AI | D3 三赛道 |
| V6 P0-3 45 关键路径异常 | A1 同一 PR 系列 |
| V6 P1-1 品智适配器测试 | F1 品智部分 |
| V6 P1-4 RLS/端口审计 | H3 终查 |
| may-gap / april-delivery | B/E 种子验证 |
| xuji-go-live-plan | H4 Week 8 剧本 |

**即日动作**：V4/V6 冻结 → 新增只追加到本文件。

---

## 6. 风险登记册 Top 10

| # | 风险 | 缓解 | Owner |
|---|---|---|---|
| 1 | B1 排班绕过致月超 36h | precheck+双签 override | HR |
| 2 | B2 金税 XML 拒收 | 双跑+XSD+10% 抽检 | Finance |
| 3 | B3 湘食通账号延批 | 本地 CSV 应急 | Civic |
| 4 | A2 POS 容器卷权限 | 商米 T2 预配 `/var/tunxiang` | Edge |
| 5 | D3 模型幻觉 | Pydantic 校验+人工复核默认开 | AI |
| 6 | D3/D4 成本超支 | cache_read_tokens<60% 告警 | AI |
| 7 | A3 字段与 V4 sync-engine 冲突 | 一次协调会 | 架构师 |
| 8 | E2 抖音/小红书资质未批 | CSV 导入+Mock 保底 | 交易 |
| 9 | Skill 约束覆盖 CI 回退 | `test_constraint_coverage` 门禁 | AI |
| 10 | 合规 B 与交付 E 争抢资源 | W2 末 Owner 会+FTE 锁定 | PMO |
