# V4 架构对齐 Sprint · D1 Hot/Cool Path 边界决策清单

| 字段 | 值 |
|---|---|
| 文档类型 | Boundary decision sign-off |
| 日期 | 2026-05-07 |
| 状态 | 🟡 **草案 — 等创始人 sign-off** |
| 决策者 | lichun（创始人） |
| 提议者 | Claude Code（基于 [`v4-pre-d1-audit.md`](v4-pre-d1-audit.md) + Sprint plan §一 1.3）|
| 关联 | sprint-0-dedup PR #239 / V4 sprint plan |

---

## 一、决策原则（已立）

> 收银员每天 8h 操作，按键响应延迟从 30ms 涨到 80ms 都会被她敏锐感知。**hot path = 高频按键 + 资金安全 + 性能关键 → Native Compose**；**cool path = 高频迭代 + 多端一致 + AI 注入 → React WebView**。Native 与 WebView 之间通过 TXBridge / Mac mini PG 真相源解耦。

---

## 二、Hot Path（Native Compose）— 已锁定 5 屏

| # | 屏 | 文件 | 锁定原因 |
|---|---|---|---|
| H1 | OrderScreen | `apps/android-pos/src/main/kotlin/com/tunxiang/pos/ui/screens/OrderScreen.kt` | 高频点单（每张订单 N 次按键）|
| H2 | TableMapScreen | `.../TableMapScreen.kt` | 200 桌并发反复切换 |
| H3 | SettleScreen | `.../SettleScreen.kt` | 资金 Tier 1，结账核心 |
| H4 | ShiftScreen | `.../ShiftScreen.kt` | 收银员换班高频 + 资金核对 |
| H5 | DailyCloseScreen | `.../DailyCloseScreen.kt` | 每日 1 次但资金 Tier 1 |

**外加 Native 直调 Sunmi SDK**：打印（IWoyouService.sendRAWData）/ 称重 / 扫码 / 钱箱 — 无 JS Bridge 序列化开销。

---

## 三、Cool Path（WebView + React）— 已锁定 9 类

| # | 类 | 锁定原因 |
|---|---|---|
| C1 | 菜品 / 菜单 CMS | 每周 +20 道菜，每日改价 → 需 OTA 级迭代速度 |
| C2 | 营销活动 / 优惠券规则 | 总部下发，多店一致 |
| C3 | 经营驾驶舱 / Agent 决策弹窗 | AI-Native 卖点核心 |
| C4 | 总部 SOP / 培训 | 总部下发内容 |
| C5 | 报表 / 财务 / 食安上报 | 低频，多端一致 |
| C6 | 跨品牌 / 跨门店切换 UI | 集团运营 |
| C7 | 设置 | 低频 |
| C8 | 食安溯源 / 明厨亮灶 | 监管展示型 |
| C9 | iPad 高端店专用屏 | 一套 React 复用，零 Native 开发 |

---

## 四、灰色地带定性（**待 sign-off**，20 项）

> 每项标注：**Claude 建议**（hot/cool）+ 理由。一行决策：勾选 = 同意建议；写"改 cool"/"改 hot" = 反向；写"分屏" = 该功能拆 hot 子能力 + cool 子能力。

| # | 功能 | 候选 | Claude 建议 | 理由 | **你的决定** |
|---|---|---|---|---|---|
| G1 | 退款（同店/跨店/跨日）| hot/cool | **hot** | 资金 Tier 1，收银台现场触发，需 < 100ms | [ ] |
| G2 | 修改订单 / 作废订单 | hot/cool | **hot** | 资金 Tier 1，操作连续性强 | [ ] |
| G3 | 储值卡充值 | hot/cool | **hot** | 资金 Tier 1，会员现场操作 | [ ] |
| G4 | 储值卡消费 / 余额查询 | hot/cool | **hot** | 收银关键路径 | [ ] |
| G5 | 优惠券核销 | hot/cool | **hot** | 收银关键路径，扫码后即扣 | [ ] |
| G6 | 礼品卡 | hot/cool | **hot** | 同 G3 | [ ] |
| G7 | 押金支付 / 退还（宴会 / 包间）| hot/cool | **hot** | 资金 Tier 1，CLAUDE.md §十七 已锁 Tier 1 | [ ] |
| G8 | 存酒查询 / 续存 / 提酒 | hot/cool | **hot** | 押金 Tier 1（§十七）| [ ] |
| G9 | 宴会订单创建（提前 1-7 天）| hot/cool | **cool** | 不在收银台高峰用，内勤前端用 | [ ] |
| G10 | 宴会当天结算 | hot/cool | **hot** | 结算时段高峰，Tier 1 | [ ] |
| G11 | 桌台预订（pre-booking）| hot/cool | **cool** | 不影响实时收银 | [ ] |
| G12 | 排队叫号 | hot/cool | **cool** | 独立 surface（前台/电视屏），不影响收银 | [ ] |
| G13 | 会员卡查询 / 绑定 | hot/cool | **cool** | 响应稍慢可接受，注册流程在前 | [ ] |
| G14 | 菜品 86 / 沽清 | hot/cool | **cool** | 厨师用，OrderScreen 接收 KDS 推送即可 | [ ] |
| G15 | 小费 / 服务费 | hot/cool | **hot** | 收银关键，包间最低消费一并 | [ ] |
| G16 | 打印小票补打 | hot/cool | **hot** | 收银台现场触发 | [ ] |
| G17 | 设备状态 / 重启 / 网络诊断 | hot/cool | **cool** | 维护用，IT/店长 | [ ] |
| G18 | 外卖单接单 / 推单 / 改单 | hot/cool | **hot** | 高频实时（美团/饿了么/抖音 webhook 推送）| [ ] |
| G19 | 全电发票申请（顾客现场扫码）| hot/cool | **hot** | 资金 Tier 1（§十七），现场触发 | [ ] |
| G20 | 全电发票管理（红冲/重打/批量）| hot/cool | **cool** | 财务后台用，非收银台 | [ ] |

---

## 五、不在本 Sprint 范围（其他 surface）

明确**不在本 V4 sprint 决策的 surface**（避免范围蔓延）：

| Surface | 处理 |
|---|---|
| `apps/web-kds`（后厨出餐屏）| 独立安卓平板，独立 surface，不在 hot/cool 二元里 |
| `apps/web-crew`（服务员手机端 PWA）| 独立 surface（员工自有手机），独立技术栈 |
| `apps/miniapp-customer-v2`（顾客小程序）| 独立 surface（顾客手机微信）|
| `apps/web-admin`（总部后台）| 独立 surface（电脑浏览器），技术栈是 cool path 同款 React 但运行在浏览器，不上 android-pos |
| `apps/h5-self-order`（H5 扫码点餐）| 独立 surface（顾客手机浏览器）|
| `apps/web-tv-menu`（TV 电子菜牌）| 独立 surface |

V4 sprint 只决策：**android-pos 和 web-pos 之间的边界**。其他 surface 后续按需各自处理。

---

## 六、Sign-off

请在下方逐项填写决策（同意建议直接打勾即可）：

```
## 创始人决策（请填写）

### Hot/Cool 边界（§二/三 已锁定，无需重决）：✅ 同意

### 灰色地带（§四 20 项）：
- G1 退款                         : [ ] 同意 hot   [ ] 改 cool   [ ] 分屏
- G2 修改订单/作废                : [ ] 同意 hot   [ ] 改 cool   [ ] 分屏
- G3 储值卡充值                   : [ ] 同意 hot   [ ] 改 cool   [ ] 分屏
- G4 储值卡消费/余额查询          : [ ] 同意 hot   [ ] 改 cool   [ ] 分屏
- G5 优惠券核销                   : [ ] 同意 hot   [ ] 改 cool   [ ] 分屏
- G6 礼品卡                       : [ ] 同意 hot   [ ] 改 cool   [ ] 分屏
- G7 押金支付/退还                : [ ] 同意 hot   [ ] 改 cool   [ ] 分屏
- G8 存酒查询/续存/提酒           : [ ] 同意 hot   [ ] 改 cool   [ ] 分屏
- G9 宴会订单创建（提前 1-7 天）  : [ ] 同意 cool  [ ] 改 hot    [ ] 分屏
- G10 宴会当天结算                : [ ] 同意 hot   [ ] 改 cool   [ ] 分屏
- G11 桌台预订                    : [ ] 同意 cool  [ ] 改 hot    [ ] 分屏
- G12 排队叫号                    : [ ] 同意 cool  [ ] 改 hot    [ ] 分屏
- G13 会员卡查询/绑定             : [ ] 同意 cool  [ ] 改 hot    [ ] 分屏
- G14 菜品 86/沽清                : [ ] 同意 cool  [ ] 改 hot    [ ] 分屏
- G15 小费/服务费                 : [ ] 同意 hot   [ ] 改 cool   [ ] 分屏
- G16 打印小票补打                : [ ] 同意 hot   [ ] 改 cool   [ ] 分屏
- G17 设备状态/重启/网络诊断      : [ ] 同意 cool  [ ] 改 hot    [ ] 分屏
- G18 外卖单接单/推单/改单        : [ ] 同意 hot   [ ] 改 cool   [ ] 分屏
- G19 全电发票申请（顾客现场扫码）: [ ] 同意 hot   [ ] 改 cool   [ ] 分屏
- G20 全电发票管理（红冲/重打/批量）: [ ] 同意 cool  [ ] 改 hot    [ ] 分屏

### 签字
日期：____________
创始人：____________
```

---

## 七、Sign-off 后的下一步

D2 启动（Repository 改造：Room → Mac mini PG 真相源），实施细节按 V4 sprint plan §二 D2 执行。

D6 真机回归仍 hard 依赖 PR #228（rebase/pr-201-clean）+ audit p0 链 ship 到 main。
