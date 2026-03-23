# tunxiangos.com 域名架构 V3 — 最终版

> Hub = 屯象科技运维管理商家后台（平台运营端）
> Forge = 开发者平台 + API 生态
> OS = 商家端（老板+运营+门店全覆盖）

---

## 一、四个身份，四个平台

```
谁在用？                域名                        定位
─────────────────────────────────────────────────────────────
屯象科技内部团队        hub.tunxiangos.com          平台运维（管商家）
开发者/ISV/供应商       forge.tunxiangos.com        开放平台（接生态）
餐饮商家（B端全员）     os.tunxiangos.com           商家端（管生意）
消费者（C端顾客）       m.tunxiangos.com            消费者端（来吃饭）
```

### 关键区分

| | Hub（屯象运维） | OS（商家端） |
|--|-------------|-----------|
| **用户** | 屯象科技员工：客户成功/实施/运维/商务 | 商家员工：老板/运营/店长/收银/厨师 |
| **权限** | 超级管理员，可看所有商户 | 商户内权限，RLS 隔离 |
| **核心操作** | 开户/续费/模板分配/故障排查/数据监控 | 菜品管理/收银/排班/看报表/做决策 |
| **类比** | 美团商家后台的"美团运营侧" | 美团商家后台的"商家侧" |

---

## 二、完整域名架构

```
tunxiangos.com                              官网（品牌介绍+客户案例+价格方案）
│
├── 屯象科技内部（平台运营）
│   └── hub.tunxiangos.com                  屯象运维管理后台
│       ├── /merchants                      商户管理（开户/续费/停用）
│       ├── /stores                         门店管理（全局视角，跨商户）
│       ├── /templates                      模板管理（Pro/Standard/Lite 分配）
│       ├── /adapters                       Adapter 状态（品智/G10/金蝶连接监控）
│       ├── /agents                         Agent 全局监控（所有商户的 Agent 健康度）
│       ├── /billing                        计费账单（HaaS+SaaS+AI 三层收入）
│       ├── /tickets                        工单系统（商户报障/实施进度）
│       ├── /deployment                     部署管理（Mac mini 在线状态/版本/推送更新）
│       └── /analytics                      平台数据（商户数/门店数/日活/GMV）
│
├── 开发者生态
│   └── forge.tunxiangos.com                开发者平台
│       ├── /docs                           API 文档（OpenAPI Spec）
│       ├── /sdk                            SDK 下载（Python/Node/Java）
│       ├── /webhooks                       Webhook 管理
│       ├── /marketplace                    应用市场（第三方插件）
│       ├── /console                        开发者控制台
│       └── /sandbox                        测试沙箱
│
├── 商家端（B端 — 餐饮商户全员）
│   ├── os.tunxiangos.com                   商家管理后台（总部+门店）
│   │   ├── /dashboard                      经营驾驶舱（老板首屏）
│   │   ├── /decisions                      AI 决策中心（审批/建议）
│   │   ├── /trade                          交易管理
│   │   ├── /catalog                        菜品中心
│   │   ├── /supply                         供应链
│   │   ├── /member                         会员经营
│   │   ├── /finance                        财务中心
│   │   ├── /org                            组织人力
│   │   ├── /ops                            日清日结
│   │   └── /system                         门店设置
│   │
│   ├── pos.tunxiangos.com                  POS 收银端
│   │   ├── /dashboard                      门店工作台
│   │   ├── /tables                         桌台总览
│   │   ├── /cashier/:tableNo               收银/点餐
│   │   ├── /settle/:orderId                结算
│   │   ├── /shift                          交接班
│   │   └── /exceptions                     异常中心
│   │
│   └── kds.tunxiangos.com                  KDS 出餐屏
│       ├── /board                          三列看板
│       ├── /history                        出餐历史
│       └── /alerts                         超时告警
│
├── 消费者端（C端）
│   └── m.tunxiangos.com                    消费者 H5
│       ├── /order                          扫码点餐
│       ├── /queue                          排队取号
│       ├── /booking                        在线预订
│       ├── /member                         会员中心
│       └── /coupons                        优惠券
│
└── 基础设施（不面向用户）
    ├── api.tunxiangos.com                  API Gateway
    ├── ws.tunxiangos.com                   WebSocket
    ├── docs.tunxiangos.com                 产品文档/操作手册
    └── status.tunxiangos.com              服务状态页
```

---

## 三、Hub 详细功能规划（屯象科技运维端）

Hub 是屯象科技作为 SaaS 平台方管理所有商家的后台。

### 3.1 商户生命周期管理

```
商务签约 → Hub 开户 → 选择模板(Pro/Standard/Lite) → 分配门店数
        → 配置 Adapter(品智/G10/金蝶) → 派发 Mac mini
        → 门店上线 → 日常运维 → 续费/升级/退出
```

| 模块 | 功能 | 说明 |
|------|------|------|
| **商户管理** | 开户/续费/停用/升级 | 录入企业信息、选择套餐、设置到期日 |
| **门店管理** | 全局门店列表 | 跨商户查看所有门店的在线状态、版本、最后同步时间 |
| **模板分配** | Pro/Standard/Lite | 给商户分配行业模板，决定功能范围 |
| **Adapter 监控** | 连接状态 | 品智API/G10API/金蝶API 的连通性、同步成功率、错误日志 |
| **Agent 监控** | 全局健康度 | 所有商户的 Agent 执行成功率、约束拦截次数、决策采纳率 |
| **计费账单** | 收入明细 | HaaS(硬件) + SaaS(软件) + AI(增值) 三层收入统计 |
| **部署管理** | Mac mini 舰队 | 所有 Mac mini 的在线状态、Tailscale IP、软件版本、远程推送更新 |
| **工单系统** | 客户支持 | 商户报障→分配→处理→关闭，SLA 监控 |
| **平台数据** | 运营指标 | 总商户数/总门店数/日活门店/总 GMV/Agent 调用次数 |

### 3.2 Hub 权限体系

| 角色 | 权限范围 |
|------|---------|
| 超级管理员 | 所有功能 |
| 客户成功 | 商户管理 + 工单 + 计费 |
| 实施工程师 | 门店管理 + 部署管理 + Adapter 监控 |
| 运维工程师 | 部署管理 + Agent 监控 + 平台数据 |
| 商务 | 商户管理(只读) + 计费 |

### 3.3 Hub vs 商家 OS 的数据隔离

```
Hub（屯象内部）
  → 看所有商户的数据（跨租户，不走 RLS）
  → 可以切换"以商户身份查看"（模拟 RLS）
  → 有平台级聚合数据（全网 GMV、Agent 总调用数）

OS（商家端）
  → 只能看自己商户的数据（严格 RLS 隔离）
  → 通过 tenant_id 过滤一切
  → 永远看不到其他商户的数据
```

---

## 四、OS 商家端的角色分层

OS 是商家的全部。但不同角色看到的 OS 不一样。

| 角色 | OS 首屏 | 可见模块 | 补充入口 |
|------|--------|---------|---------|
| **老板/CEO** | 经营驾驶舱(KPI+排名+AI决策) | 全部(只读为主) + 审批 | 企微推送直达 |
| **区域总监** | 区域门店对比 | 分析+门店+人力 | — |
| **总部运营** | 完整管理后台 | 全部 | — |
| **总部HR** | 组织人力首页 | 人力+薪资+考勤+绩效 | — |
| **总部财务** | 财务中心首页 | 财务+成本+凭证+报表 | — |
| **店长** | 门店经营简报 | 本店交易+库存+人力+日清日结 | pos.tunxiangos.com |
| **收银员** | — | — | 只用 pos.tunxiangos.com |
| **厨师** | — | — | 只用 kds.tunxiangos.com |
| **服务员** | — | — | 只用 web-crew(PWA) |

**关键设计**：菜单配置引擎（menu_config.py）根据角色自动裁剪 OS 侧边栏。
老板打开 OS 看到的是驾驶舱优先 + 审批入口；运营打开看到完整管理菜单。

---

## 五、与代码的映射（更新）

| 域名 | 前端应用 | 说明 |
|------|---------|------|
| **hub.tunxiangos.com** | **新建 apps/web-hub/** | 屯象内部运维后台，独立应用 |
| **os.tunxiangos.com** | apps/web-admin（现有） | 商家管理后台（已有 10 模块） |
| **pos.tunxiangos.com** | apps/web-pos（现有） | POS 收银（已有 12 路由） |
| **kds.tunxiangos.com** | apps/web-kds（现有） | KDS 出餐（已有 5 路由） |
| **m.tunxiangos.com** | apps/miniapp-customer（H5 版） | 消费者 H5 |
| **forge.tunxiangos.com** | **新建 apps/web-forge/** | 开发者平台 |
| **api.tunxiangos.com** | — | Gateway |
| **ws.tunxiangos.com** | — | WebSocket |

**新增 2 个前端应用**：web-hub（屯象运维）+ web-forge（开发者平台）

---

## 六、Nginx 路由规则（更新）

```nginx
# 屯象内部运维
server {
    server_name hub.tunxiangos.com;
    # 仅允许屯象办公 IP + Tailscale VPN 访问
    allow 屯象办公IP;
    allow 100.64.0.0/10;  # Tailscale CGNAT
    deny all;
    root /app/web-hub/dist;
    location /api/ { proxy_pass http://gateway:8000; }
}

# 商家端 OS
server {
    server_name os.tunxiangos.com;
    root /app/web-admin/dist;
    location /api/ { proxy_pass http://gateway:8000; }
}

# POS/KDS/消费者/Forge...（同理）
```

**Hub 有 IP 白名单**，商家无法访问屯象内部运维后台。

---

## 七、总结对比

| 维度 | V1(旧) | V2(上一版) | V3(最终) |
|------|--------|----------|---------|
| Hub 定位 | 无 | 老板经营中枢 | **屯象运维管商家** |
| 老板入口 | admin | hub | **os（驾驶舱首屏）** |
| 运营入口 | admin | os | **os（完整后台）** |
| 屯象内部 | 混在 admin 里 | 没考虑 | **hub（独立隔离）** |
| 开发者 | 无 | forge | **forge（不变）** |
| 消费者 | miniapp | m | **m（不变）** |

### 一句话

> **Hub 管商家，OS 管生意，Forge 管生态，POS/KDS 管操作，m 管顾客。五个域名，五个世界，各司其职。**
