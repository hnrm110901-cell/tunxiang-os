# 屯象OS 商户 Playbook 索引

> Sprint F / F3 — 三商户演示脚本汇总 + DEMO reset 通用参考。
> 单商户脚本：[czyz](./czyz.md) / [zqx](./zqx.md) / [sgc](./sgc.md)

---

## 一、三商户对比

| 维度 | czyz（尝在一起） | zqx（最黔线） | sgc（尚宫厨） |
|---|---|---|---|
| **业态** | 连锁中餐正餐 | 黔菜区域连锁 | 高端宴席/包间 |
| **核心痛点** | 翻台率、折扣失控 | 复购率、会员流失 | 宴席定金对账、尾款追收 |
| **DEMO 主线** | 折扣健康度 + 翻台率 | 会员洞察 + 沉睡唤醒 | 宴席全流程数字化 |
| **必装 POS 适配器** | pinzhi (16/35) | TBD | tiancai-shanglong (16/35) |
| **必装会员适配器** | aoqiwei (20) | aoqiwei + weishenghuo | — |
| **必装发票** | nuonuo (8/35) | nuonuo (8/35) | nuonuo (8/35) |
| **演示总时长** | 12-15 分钟 | 12-15 分钟 | 12-15 分钟 |
| **关键指标 #1** | 翻台率 3.4 | 复购率 28→33% | 定金回款率 75→95% |
| **关键指标 #2** | 折扣毛利 21.8% | 沉睡唤醒率 16% | 宴席净利率 32% |
| **关键指标 #3** | 出餐 P99 < 20min | 会员客单价 +36% | 尾款补缴 14min |
| **现场设备** | 安卓 POS（商米 T2） | 安卓 POS + PWA | iPad 接待 + 安卓 POS |

---

## 二、共性（三商户都要做的事）

1. **演示前 24h** 跑一次评分卡：`python3 scripts/score_adapters.py --markdown -`，确认必装适配器没退化
2. **演示前 1h** 跑 reset + seed：见下方"通用 reset 命令清单"
3. **演示中**：左侧始终保留 Agent 预警栏可见，证明 AI 在工作
4. **演示后**：录屏 + 截图 + 反馈表单 + GitHub Issue（带 `merchant:czyz/zqx/sgc` 标签）

---

## 三、差异（不同商户演示的重点不同）

- **czyz** 重在"流程透明 + 毛利可控"。话术围绕"23 套系统替换为一套"，**展示驾驶舱当家**
- **zqx** 重在"老客户识别 + 复购拉升"。话术围绕 Golden ID + 沉睡唤醒，**会员洞察 Agent 当家**
- **sgc** 重在"宴席全流程"。话术围绕定金/尾款/发票链路，**前台接待 + 包间排期当家**

---

## 四、通用 DEMO reset 命令清单

> 演示场地常见操作，按顺序执行。

```bash
# 0. 进入项目根目录
cd /Users/lichun/tunxiang-os

# 1. 重置 demo 环境数据（保留 schema，清业务数据）
bash scripts/demo-reset.sh

# 2. 灌入种子数据（按商户切换）
python3 scripts/seed_demo.py --merchant czyz --check
# 或 --merchant zqx / --merchant sgc

# 3. 评分卡 smoke（确认必装适配器没退化）
python3 scripts/score_adapters.py --markdown -

# 4. RLS 校验（关键，跨租户漏查会丢单）
python3 scripts/check_rls_policies.py

# 5. Migration 状态确认（v229 是否已应用）
bash scripts/check_migrations.sh

# 6. Mac mini 边缘服务健康检查（演示设备本地）
curl http://localhost:8000/health   # mac-station
curl http://localhost:8100/health   # coreml-bridge

# 7. 启动各前端（按商户演示需求选启）
# - web-pos          收银（czyz / zqx 主线）
# - web-admin        驾驶舱（czyz / zqx 都要）
# - web-kds          后厨（czyz / sgc 都要）
# - web-crew         服务员 PWA（zqx 重点）
# - web-reception    前台接待（sgc 重点）

# 8. 演示完毕后清理
bash scripts/demo-reset.sh
```

---

## 五、Feature Flag 紧急关闭参考

> 演示中 Agent 卡住时的快速关闭按钮。位于 `flags/agents/`。

| Flag | 关闭后影响 | 关闭命令 |
|---|---|---|
| `discount_guard` | 折扣不再校验毛利底线 | 编辑 `flags/agents/discount_guard.yaml` set enabled=false |
| `serve_dispatch` | KDS 不再算上菜节奏 | 同上 `flags/agents/serve_dispatch.yaml` |
| `member_insight` | 会员洞察 Agent 停 | 同上 |
| `private_ops` | 私域运营（沉睡唤醒）停 | 同上 |
| `inventory_alert` | 库存预警 Agent 停 | 同上 |

> **关 flag 必须 ≤ 30 秒内完成，否则切话术兜底。**

---

## 六、DEMO 失败应急联系人（placeholder）

| 角色 | 姓名 | 联系方式 | 兜底动作 |
|---|---|---|---|
| 创始人 | 未了已 | TBD | 远程接管 / 现场决策 |
| 后端值班 | TBD | TBD | 30 分钟内解决数据库 / 网络问题 |
| 前端值班 | TBD | TBD | 30 分钟内解决 React App 加载问题 |
| 边缘值班 | TBD | TBD | Mac mini 服务重启 / Core ML 排障 |

> 演示前 24h 必须在群里确认值班排班。

---

## 七、跨商户红线（统一遵守）

> §17 Tier 1 待审 + 未上线项。**任何一个商户的演示都不能触碰**。

- 存酒押金多次续存（wine_storage） — §19 二审中
- 支付 Saga 长链超时回滚 — Tier 1 待审
- CRDT 4 小时断网恢复 — 不要现场制造断网
- 金税四期发票实发 — 只演申请/预览，不发送
- Master Agent 链式编排 — Wave 4 H2 在做，不展示
- "全量同步"按钮（含 broad except 的适配器） — 不要触发

---

## 八、变更日志

- 2026-04-25 v1：Sprint F / F3 三商户 playbook 首版（czyz 完整 / zqx 部分 TBD / sgc 部分 TBD）
