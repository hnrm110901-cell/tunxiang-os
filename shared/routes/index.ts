/**
 * 屯象OS 全局路由清单 — 7大应用域 × 完整路由树
 *
 * 本文件是"单一事实源"，所有前端 App 的 React Router 配置
 * 和后端 API 的模块边界都应基于此清单。
 *
 * 用途：
 * - 产品: IA 和 PRD 拆分
 * - 前端: React Router 骨架 + 菜单生成
 * - 后端: BFF 模块边界对齐
 * - 设计: Figma 页面树
 */

export { HUB_ROUTES, HUB_NAV } from './hub';
export { FRONT_ROUTES, FRONT_NAV } from './front';
export { STORE_ROUTES, STORE_NAV } from './store';
export { GROWTH_ROUTES, GROWTH_NAV } from './growth';
export { AGENT_ROUTES, AGENT_NAV } from './agent-studio';
export { PLATFORM_ROUTES, PLATFORM_NAV } from './platform';
export { MINI_ROUTES } from './mini';
export { LINKAGE_RULES } from './linkage';
export type { RouteNode, NavItem, LinkageRule } from './types';
