# tunxiangos.com 域名架构 V2 — 深度重构

> 三个维度的平衡：Palantir 级平台定位 × 技术生态兼容 × 餐饮从业者习惯

---

## 一、为什么要重新梳理

### 当前问题

```
api.tunxiangos.com     → 太技术化，老板不知道这是什么
admin.tunxiangos.com   → "admin"是技术词汇，店长会懵
miniapp.tunxiangos.com → 消费者根本不会手输这个域名
www.tunxiangos.com     → 空着
```

这个结构犯了三个错误：
1. **用技术视角而非用户视角规划** — 按系统模块分，不是按使用角色分
2. **没有平台层次** — 看不出 Forge/Hub/OS 的战略分层
3. **没有考虑生态** — 没有开放 API、开发者文档、应用市场的位置

### Palantir 的域名哲学

Palantir 不是一个产品，是三个平台：
- **Foundry** — 数据底座（给技术团队用）
- **Gotham** — 决策分析（给决策者用）
- **Apollo** — 部署运维（给运维团队用）

屯象OS 也不应该是一个产品，而是：
- **Forge** — 数据底座 + 开发者平台（给 ISV/技术团队）
- **Hub** — 经营决策中枢（给老板/总部）
- **OS** — 门店操作系统（给店长/员工）
- **消费者触点** — 小程序/H5（给顾客）

---

## 二、新域名架构

### 总览

```
tunxiangos.com                          ← 官网（品牌+产品介绍+客户案例）
│
├── 平台层（对外品牌叙事）
│   ├── forge.tunxiangos.com            ← Forge 开发者平台（API文档+SDK+应用市场）
│   └── hub.tunxiangos.com             ← Hub 经营决策中枢（老板/总部驾驶舱）
│
├── 商家端（日常经营使用）
│   ├── os.tunxiangos.com              ← OS 商家管理后台（菜品/库存/人力/财务配置）
│   ├── pos.tunxiangos.com             ← POS 收银端（安卓WebView加载地址）
│   └── kds.tunxiangos.com             ← KDS 出餐屏（厨房大屏加载地址）
│
├── 消费者端
│   ├── m.tunxiangos.com               ← 消费者 H5（扫码点餐/排队/会员）
│   └── (微信/抖音小程序)               ← 小程序不走域名，走微信服务器
│
├── 基础设施层（不对外暴露）
│   ├── api.tunxiangos.com             ← API Gateway（所有端统一入口）
│   ├── ws.tunxiangos.com              ← WebSocket（KDS推送/Agent实时通知）
│   └── edge.tunxiangos.com            ← 边缘节点管理（Mac mini 回连）
│
└── 文档与社区
    ├── docs.tunxiangos.com            ← 产品文档 + 操作手册
    └── status.tunxiangos.com          ← 服务状态页
```

### 为什么这样分

| 子域名 | 面向角色 | 设计逻辑 |
|--------|---------|---------|
| **hub** | 老板/CEO/投资人 | "Hub"="中枢"，老板听得懂"经营中枢"。这是屯象OS的"Gotham"。登录后看到的是驾驶舱+AI决策+门店排名——不是菜品管理表单 |
| **os** | 总部运营/HR/财务 | "OS"="操作系统"，运营团队的日常后台。菜品管理、库存配置、薪资设置、权限分配都在这里 |
| **pos** | 收银员/服务员 | 安卓POS WebView 加载 `pos.tunxiangos.com`，简短好记。店长也可以在电脑浏览器打开看 |
| **kds** | 厨师/传菜员 | KDS 大屏加载 `kds.tunxiangos.com`，简短好记 |
| **forge** | 开发者/ISV/技术团队 | "Forge"="锻造"，开放API文档+SDK下载+Webhook配置+应用市场。这是屯象OS的"Foundry" |
| **m** | 消费者 | `m` 是移动端的通用缩写（参考 m.meituan.com），消费者扫码后跳转到这里 |
| **api** | 所有客户端 | 纯技术接口，不面向人 |

---

## 三、角色 → 域名映射（餐饮从业者视角）

### 老板（决策者）

```
早上打开手机 → 企业微信推送"晨推·Top3决策" → 点击进入 hub.tunxiangos.com
              → 看到：品牌整体营收/门店健康排名/AI建议/待审批事项
              → 点击"审批折扣" → 直接在 Hub 完成
              → 不需要打开其他系统
```

**Hub 是老板唯一需要的入口。** 他不需要知道 OS/Forge/API 的存在。

### 总部运营（配置者）

```
打开电脑浏览器 → os.tunxiangos.com → 登录
               → 左侧导航：菜品中心/供应链/人力/财务/营销/系统设置
               → 日常工作：发布新菜品、配置营销方案、导出报表、管理权限
```

**OS 是运营团队的工作台。** 所有"配置型"操作在这里完成。

### 店长（管理者）

```
白天在门店 → 手机浏览器打开 hub.tunxiangos.com → 看本店经营简报
           → 或打开 pos.tunxiangos.com → 快速查看桌台/预订/异常
           → 下午14:00-16:00 → 打开 os.tunxiangos.com 看报表
```

**店长在 Hub（看数据）和 POS（管业务）之间切换。**

### 收银员（操作者）

```
上班 → 安卓POS开机 → 自动加载 pos.tunxiangos.com
     → 全屏收银界面 → 点菜/结算/打印 → 不需要其他操作
```

**收银员只接触 POS，永远不需要知道 Hub/OS 的存在。**

### 厨师（执行者）

```
上班 → KDS平板开机 → 自动加载 kds.tunxiangos.com
     → 三列看板 → 接单/制作/出餐 → 不需要其他操作
```

### 消费者（顾客）

```
到店 → 扫桌码 → 跳转 m.tunxiangos.com/order?store=xxx&table=A03
     → 点菜/下单/支付 → 完成
```

**消费者看到的是 `m.tunxiangos.com`，短、好记、像大平台。**

---

## 四、Hub vs OS 的功能边界（关键设计）

这是最容易混淆的地方：Hub 和 OS 到底有什么区别？

| 维度 | Hub（经营决策中枢） | OS（运营管理后台） |
|------|-------------------|-------------------|
| **核心用户** | 老板/CEO/区域总 | 运营/HR/财务/IT |
| **核心动作** | 看数据、做决策、审批 | 配置参数、录入数据、管理权限 |
| **信息密度** | 低（一屏看清全局） | 高（表单+表格+详情） |
| **Agent 角色** | 主角（AI建议驱动所有页面） | 辅助（侧边Agent Console） |
| **更新频率** | 实时（分钟级） | 低频（按需操作） |
| **移动端体验** | 必须好（老板在路上看） | 可以差（一般用电脑） |

### Hub 的页面（精简）

```
hub.tunxiangos.com/
├── /                    ← 品牌经营驾驶舱（KPI卡片+门店排名+趋势）
├── /store/{id}          ← 门店经营详情（健康度+简报+异常）
├── /decisions            ← AI决策中心（Top3+审批+历史）
├── /alerts              ← 预警中心（实时告警+处理进度）
└── /reports             ← 经营报告（日/周/月报+导出PDF）
```

**Hub 总共不超过 10 个页面。** 每个页面的设计原则是"2分钟看完"。

### OS 的页面（完整）

```
os.tunxiangos.com/
├── /trade/              ← 交易管理（订单/支付/结算/退款）
├── /catalog/            ← 菜品中心（菜品/BOM/发布/定价）
├── /supply/             ← 供应链（库存/采购/供应商/损耗）
├── /member/             ← 会员经营（会员/RFM/营销/旅程）
├── /finance/            ← 财务中心（利润/成本/月报/凭证）
├── /org/                ← 组织人力（员工/排班/考勤/薪资）
├── /ops/                ← 日清日结（E1-E8/巡检/整改）
├── /analytics/          ← 数据分析（KPI/趋势/对比）
├── /agent/              ← Agent管理（配置/监控/审计）
└── /system/             ← 系统设置（品牌/门店/权限/模板）
```

**OS 有 40+ 个页面。** 这是运营团队的"Excel替代品"。

---

## 五、Forge 开发者平台规划

Forge 是屯象OS 成为"行业基础设施"的关键——让第三方可以在屯象OS上开发。

```
forge.tunxiangos.com/
├── /                    ← 开发者首页（能力介绍+快速开始）
├── /docs/               ← API 文档（所有域的 OpenAPI Spec）
│   ├── /docs/trade      ← 交易域 API
│   ├── /docs/menu       ← 菜品域 API
│   ├── /docs/member     ← 会员域 API
│   └── ...
├── /sdk/                ← SDK 下载（Python/Node/Java）
├── /webhooks/           ← Webhook 配置（订单回调/库存变更/会员事件）
├── /marketplace/        ← 应用市场（第三方应用/增值服务）
│   ├── 供应链对接       ← 各地供应商 SaaS 接入
│   ├── 外卖平台        ← 美团/饿了么/抖音聚合
│   ├── 财务税务        ← 金蝶/用友/诺诺对接
│   └── AI 增值         ← 语音点餐/智能客服/AR菜单
├── /console/            ← 开发者控制台（应用管理/密钥/日志）
└── /sandbox/            ← 测试沙箱（模拟数据+调试工具）
```

**Forge 解决的核心问题：**
- ISV（独立软件供应商）可以在屯象OS上开发插件
- 供应商可以通过 API 对接库存/采购
- 财务软件可以通过 Webhook 自动获取凭证
- 这就是"行业基础设施"的含义——不只是给自己用，而是让整个生态在上面构建

---

## 六、与现有代码的映射

| 域名 | 对应前端应用 | 对应后端服务 |
|------|-----------|-----------|
| **hub.tunxiangos.com** | web-admin（精简为 Hub 模式） | tx-analytics + tx-agent |
| **os.tunxiangos.com** | web-admin（完整模式） | 全部 10 个域服务 |
| **pos.tunxiangos.com** | web-pos | tx-trade + tx-menu |
| **kds.tunxiangos.com** | web-kds | tx-trade(WS) + mac-station |
| **m.tunxiangos.com** | miniapp-customer（H5版） | gateway |
| **forge.tunxiangos.com** | 新建（文档站+控制台） | gateway(OpenAPI) |
| **api.tunxiangos.com** | — | gateway → 10 域服务 |
| **ws.tunxiangos.com** | — | mac-station WebSocket |

### 关键设计：Hub 和 OS 共用同一套代码

web-admin 应用通过 URL 判断模式：
```typescript
const isHub = window.location.hostname.startsWith('hub.');
const isOS = window.location.hostname.startsWith('os.');

// Hub 模式：只显示驾驶舱+决策+报告页面，Agent Console 永远展开
// OS 模式：显示完整 10 个模块，Agent Console 可折叠
```

不需要两套代码，只需要路由裁剪 + UI 密度调整。

---

## 七、技术生态兼容性

| 生态 | 域名 | 用途 |
|------|------|------|
| 微信生态 | api.tunxiangos.com | 小程序服务端域名配置 |
| | m.tunxiangos.com | 公众号 H5 授权域名 |
| 企业微信 | api.tunxiangos.com | 企微应用回调域名 |
| 钉钉 | api.tunxiangos.com | 钉钉应用回调域名 |
| 美团开放平台 | api.tunxiangos.com | 外卖接单回调 |
| 支付宝 | api.tunxiangos.com | 支付回调 notify_url |
| 微信支付 | api.tunxiangos.com | 支付回调 notify_url |

**所有第三方回调统一走 api.tunxiangos.com**，Gateway 内部路由到对应服务。

---

## 八、餐饮从业者习惯适配

### 命名用中文思维

| 域名 | 对外中文名称 | 餐饮老板理解 |
|------|-----------|-----------|
| hub | **经营中枢** | "打开'经营中枢'看看今天店里怎么样" |
| os | **管理后台** | "让运营去'管理后台'改一下菜品价格" |
| pos | **收银台** | "收银台登录不了了帮我看看" |
| kds | **出餐屏** | "后厨的'出餐屏'是不是掉线了" |
| m | **手机点餐** | "客人扫码就能用'手机点餐'" |
| forge | **开放平台** | "让供应商对接我们的'开放平台'" |

### 登录体验

```
1. 老板打开 hub.tunxiangos.com
   → 企业微信扫码登录（一步到位）
   → 直接看到自己品牌的驾驶舱

2. 运营打开 os.tunxiangos.com
   → 账号密码登录（日常工具，安全要求高）
   → 看到完整的管理菜单

3. 收银员打开 pos.tunxiangos.com（POS自动加载）
   → 工号+密码登录（快速，4位数字）
   → 直接进入收银界面

4. 厨师看 kds.tunxiangos.com（KDS自动加载）
   → 无需登录（设备绑定门店+档口）
   → 直接看到待做订单

5. 消费者扫码 m.tunxiangos.com
   → 微信授权（无感）
   → 直接看到菜单
```

---

## 九、DNS 配置清单

| 记录类型 | 主机记录 | 记录值 | 用途 |
|---------|---------|--------|------|
| A | @ | 腾讯云IP | 官网 |
| A | api | 腾讯云IP | API Gateway |
| A | hub | 腾讯云IP | 经营中枢 |
| A | os | 腾讯云IP | 管理后台 |
| A | pos | 腾讯云IP | POS收银 |
| A | kds | 腾讯云IP | KDS出餐 |
| A | m | 腾讯云IP | 消费者H5 |
| A | ws | 腾讯云IP | WebSocket |
| A | forge | 腾讯云IP | 开发者平台 |
| A | docs | 腾讯云IP | 文档站 |
| A | status | 腾讯云IP | 状态页 |
| CNAME | www | tunxiangos.com | 官网别名 |

共 12 条 DNS 记录。

---

## 十、SSL 证书策略

**推荐：申请通配符证书 `*.tunxiangos.com`**

一张证书覆盖所有子域名，省去逐个申请的麻烦。
Let's Encrypt 支持通配符，但需要 DNS 验证（DNS-01 challenge）。

```bash
certbot certonly --dns-tencent \
  -d "tunxiangos.com" \
  -d "*.tunxiangos.com"
```

---

## 十一、一句话总结

> **tunxiangos.com 不是一个网站，是一个平台生态的入口。Hub 给老板看数据做决策，OS 给运营配置管理，POS/KDS 给一线员工操作，m 给消费者点餐，Forge 给开发者对接——每个角色打开属于自己的那个域名，看到属于自己的那个世界。这才是"连锁餐饮 Palantir"的域名架构。**
