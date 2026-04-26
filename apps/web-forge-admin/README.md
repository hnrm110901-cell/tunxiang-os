# @tunxiang/web-forge-admin

> 屯象 Forge 管理后台 · React 18 + TypeScript + Vite · 14 模块 / 70+ 子页

## 目录结构

```
packages/web-forge-admin/
├── package.json                      # 依赖与脚本
├── tsconfig.json
├── vite.config.ts
├── index.html
├── README.md                         # 本文件
└── src/
    ├── main.tsx                      # React 入口
    ├── App.tsx                       # 根组件 + Provider
    ├── router.tsx                    # React Router · 14 路由
    ├── types/
    │   ├── menu.ts                   # 菜单类型定义
    │   └── domain.ts                 # 业务实体类型(商品/ISV/订单)
    ├── data/
    │   └── menuConfig.ts             # 14 菜单配置(单一来源)
    ├── styles/
    │   ├── tokens.css                # v2 design tokens(从 design-tokens 包导入)
    │   └── globals.css               # 全局重置 + 工具类
    ├── components/
    │   ├── layout/
    │   │   ├── Layout.tsx            # 整体布局(top + side + main)
    │   │   ├── TopNav.tsx            # 顶 nav
    │   │   └── Sidebar.tsx           # 侧菜单(可折叠子项)
    │   ├── ui/                       # 复用 UI 原子组件
    │   │   ├── Card.tsx
    │   │   ├── Button.tsx
    │   │   ├── Badge.tsx
    │   │   ├── KpiCard.tsx
    │   │   ├── Table.tsx
    │   │   ├── PageHeader.tsx
    │   │   └── index.ts              # 统一导出
    │   └── feature/
    │       └── AgentVoiceCard.tsx    # Agent L1/L2/L3 视觉签名
    └── pages/                        # 14 个一级模块页
        ├── OverviewPage.tsx          # ✅ 完整示范
        ├── CatalogPage.tsx           # ✅ 完整示范
        ├── ReviewPage.tsx            # ⏳ 骨架(参照 prototype.html)
        ├── MakersPage.tsx            # ⏳ 骨架
        ├── SubscriptionsPage.tsx     # ⏳ 骨架
        ├── LabsPage.tsx              # ⏳ 骨架
        ├── AdaptersPage.tsx          # ⏳ 骨架
        ├── FinancePage.tsx           # ⏳ 骨架
        ├── AnalyticsPage.tsx         # ⏳ 骨架
        ├── ContentPage.tsx           # ⏳ 骨架
        ├── SecurityPage.tsx          # ⏳ 骨架
        ├── IntegrationsPage.tsx      # ⏳ 骨架
        ├── SettingsPage.tsx          # ⏳ 骨架
        └── RbacPage.tsx              # ⏳ 骨架
```

## 落地步骤

```bash
# 1. 把 packages/web-forge-admin/ 拷到 monorepo
cp -r outputs/web-forge-admin packages/

# 2. 安装依赖
cd packages/web-forge-admin
pnpm install

# 3. 启动 dev
pnpm dev          # → http://localhost:5176

# 4. 把 prototype.html 里 12 个未完成页面的 HTML 段落,
#    照着 OverviewPage.tsx / CatalogPage.tsx 的模式
#    迁移到对应的 *Page.tsx 文件
```

## 设计原则

**单一来源**: 14 菜单结构在 `src/data/menuConfig.ts` 集中维护。Sidebar / Router / 面包屑 都从它读,不重复书写。

**Tokens 来自外部包**: 颜色 / 字体 / 圆角全部用 CSS 变量,变量定义在 `@tunxiang/design-tokens` 包里。本 app 不应该直接写任何 hex。

**页面分层**: PageHeader → KPI 行 → 内容主区。所有页面遵循这个结构,降低视觉跳跃。

**Agent Voice 三级**: 9 大 Agent 的展示统一用 `<AgentVoiceCard level="L1|L2|L3" />` 组件,跨页一致。

**数据假**: 当前所有数据是 mock(在每个 Page 内部的 const)。后续接 `tx-forge` 微服务的 API 时,把 mock 替换为 react-query 调用。

## 接 API 的位置

```ts
// 当前(mock)
const products = mockProducts

// 接 API 后
const { data: products, isLoading } = useQuery({
  queryKey: ['products', filters],
  queryFn: () => api.products.list(filters)
})
```

API 客户端在 `@tunxiang/api-client`(另一个 monorepo 包)。

## 测试

```bash
pnpm test          # vitest
pnpm test:e2e      # playwright
pnpm test:visual   # percy / chromatic
```

每个页面至少 3 个用例:① 默认渲染 ② 数据加载 loading ③ 错误态 fallback。

## 部署

走 `gitops/` 五环境:dev → test → uat → pilot → prod。本 app 上线优先级排在 13(参考 MIGRATION.md 的 per-app 升级顺序)。

---

**屯象科技 · Forge Ops · 2026-04-25 · v2.0**
