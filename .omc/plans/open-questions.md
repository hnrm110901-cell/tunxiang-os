# Open Questions

跨 plan 的待定问题与决策追踪.

## 2026-05-18 — Gateway 瘦身 tx-sync-worker (#758)

- [ ] **Q1 Job 命名 prefix (tx-sync-worker 包内)** — 推荐 A (保持原 5 个 id 不动). 见 plan `.omc/plans/2026-05-18-gateway-slim-plan.md` §5. 影响: metric label `job=daily_dishes_sync` 与 gateway 现行 dashboard 一致性.
- [ ] **Q2 sync_router (/api/v1/sync/health) Phase 2 是否迁** — 推荐 A (Phase 2 follow-up 迁). 影响: gateway 是否真瘦身 + 客户端 (web-admin / DEMO 巡检) URL 改.
- [ ] **Q3 Phase 1 cron 时间是否完全复制 gateway** — 推荐 A (完全复制 + dry_run=true 默认). 影响: §7.1+§7.3 dup task firing 风险 P0 缓解策略.
- [ ] **Q4 Helm chart Tier (T2 maxU=1 vs T3 default off)** — 推荐 A (T2 maxU=1, Phase 2 切单轨后直接顶 §17 Tier 2 品智 POS 同步). 影响: K8s 蓝绿部署期间 PDB 防剪掉单 pod.
- [ ] **W2 残留 P1 follow-up issue 是否本 PR 立**: "[W4 P1] 关 gateway scheduler 切换 tx-sync-worker 单轨" — 推荐 是 (Phase 2 路径必须本 PR 立, 不能漂).

## Handoff drift / issue 描述不准 (planner 自查发现)

- [x] **Issue #758 描述说 "2 个定时任务" 但 gateway 实际跑 5 个 cron job** — 已在 plan §0.3 落实修正. 5 jobs = wecom_group_daily_sop @ 09:00 (gateway main.py:120) + daily_dishes_sync @ 02:00 + daily_master_data_sync @ 03:00 + hourly_orders_incremental_sync + quarter_members_incremental_sync (sync_scheduler.py:582-648 4 jobs). handoff "pinzhi_pos_sync" 是 4 个独立 job 不是 1 个.
- [x] **Issue #758 描述说 "Helm chart 11 文件" 字面意义为 11 templates 但实际是 9 templates + Chart.yaml + values.yaml = 11 total** — 与 #757 决议文档 §3 第 3 项一致, 已落实 plan §0.7 + §3.5.
- [ ] **sync_router (/api/v1/sync/health) Phase 1 是否暴露 tx-sync-worker** — handoff 未提及, plan §1 设计 Phase 1 留 gateway, Phase 2 评估迁. 见 Q2.
- [ ] **wecom_group_service.py 跨服务 import (gateway 内部模块, 非 shared/)** — Phase 1 接受跨边界 import, Phase 2 follow-up 评估拆 shared/wecom/. 见 §7.6.
