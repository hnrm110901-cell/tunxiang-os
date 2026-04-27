# web-devforge · 屯象 DevForge 前端

屯象 OS 内部研发运维平台前端骨架。对接后端 `tx-devforge:8017`。

## 定位

`web-devforge` 是面向**屯象自身研发团队**的内部研运平台（Internal Developer Platform）：
应用中心 / 流水线 / 制品库 / 部署 / 灰度 / 配置中心 / 可观测 / 边缘门店 / 安全审计 等 15 个一级模块。

> 注意：本应用与 `web-forge` / `web-forge-admin`（面向 ISV 的 AI Agent Exchange 市场）是**完全不同的产品**，请勿混淆。

## 技术栈

- React 18 + TypeScript strict
- Vite 5（端口 5182；5180 被 web-hub 占用）
- Ant Design v5（主色 Slate-900 + Amber-600 品牌色）
- TanStack Query v5（数据请求）
- Zustand（环境/用户状态）
- React Router v6
- ECharts / AntV G6 / Monaco Editor / xterm.js（按需懒加载）

## 启动

```bash
npm install
npm run dev          # http://localhost:5182
npm run typecheck    # tsc --noEmit
npm run build        # 类型检查 + 产物构建
```

## 后端代理

`vite.config.ts` 已将 `/api` 代理到 `http://localhost:8017`（tx-devforge；8015/8016 已被 tx-expense/tx-pay 占用）。
若后端未启动，应用中心页会 fallback 到 mock 数据，不会崩溃。

## 一级菜单 15 项

01 工作台 · 02 应用中心 · 03 代码协作 · 04 流水线 · 05 制品库 · 06 测试中心
07 部署中心 · 08 灰度发布 · 09 配置中心 · 10 可观测 · 11 边缘门店
12 数据治理 · 13 集成中心 · 14 安全审计 · 15 系统设置

详见 `src/data/menuConfig.ts`。

## 环境切换器

顶栏内置 `dev / test / staging / gray / prod` 五环境切换。
切换至 `prod` 时整体 UI 强制红色边框 + 二次确认。
当前环境持久化到 `localStorage` (key: `devforge.env`)。

## ⌘K / Ctrl+K 全局搜索

任意页面按 `⌘K`（macOS）或 `Ctrl+K`（其他）唤起全局搜索 Modal。
ESC 关闭。
