# 屯象OS 顾客端微信小程序 v1

> ⚠️ **DEPRECATED**（since 2026-05-06，sprint-0-dedup R7）
>
> 本项目（v1，原生微信小程序框架）已被 **`apps/miniapp-customer-v2`**（Taro + TypeScript）取代。
>
> ## 维护策略
> - ✅ 安全补丁
> - ✅ 已合作客户的 bug 修复
> - ❌ 新功能（必须在 v2 实现）
>
> ## EOL 时间
> 待全部 v1 租户迁移到 v2 之后，目前未定。
>
> ## 新需求请去
> [`apps/miniapp-customer-v2`](../miniapp-customer-v2)

---

## 项目说明

顾客端微信小程序，覆盖 8 个主包页面（点单 / 排队 / 预订 / 会员 / 优惠券 / 套餐详情 / 订单 / 首页）+ 7 分包。

技术栈：原生微信小程序框架（无 Taro/uniapp 编译层）。

## 启动

用微信开发者工具打开本目录即可。

## 入口

- 主入口：`pages/index/index`
- 配置：`app.json`（路由）/ `project.config.json`（开发者工具配置）/ `utils/config.js`（API base）

## 与 v2 的差异

| | v1（本目录）| v2（`miniapp-customer-v2`）|
|---|---|---|
| 框架 | 原生小程序 | Taro 4 + TypeScript |
| 状态管理 | globalData + page data | Zustand |
| 类型 | 无 | strict TS |
| 主战场 | 已停止演进 | 当前主战场 |
