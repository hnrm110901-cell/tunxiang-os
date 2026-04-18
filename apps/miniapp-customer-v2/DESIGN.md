# MiniApp 设计规范

品牌色：#FF6B35（暖橙色）
Design Token：`src/styles/tokens.scss`

使用方式：
- SCSS 文件中直接用 `$tx-primary`、`$tx-text-1` 等变量
- 无需 import（已在 Taro 配置中全局注入）

## 颜色 Token

| Token | 值 | 用途 |
|-------|----|------|
| `$tx-primary` | `#FF6B35` | 品牌主色（按钮/高亮/链接） |
| `$tx-primary-active` | `#E55A28` | 主色按压态 |
| `$tx-primary-light` | `#FFF3ED` | 主色浅背景 |
| `$tx-navy` | `#1E2A3A` | 深色导航/强调 |
| `$tx-success` | `#0F6E56` | 成功 |
| `$tx-warning` | `#BA7517` | 警告 |
| `$tx-danger` | `#A32D2D` | 危险/错误 |
| `$tx-text-1` | `#2C2C2A` | 主文字 |
| `$tx-text-2` | `#5F5E5A` | 次文字 |
| `$tx-text-3` | `#B4B2A9` | 辅助文字 |
| `$tx-bg-1` | `#FFFFFF` | 主背景 |
| `$tx-bg-2` | `#F8F7F5` | 次背景 |
| `$tx-border` | `#E8E6E1` | 边框 |

## Tailwind 配置

Tailwind 中使用 `bg-brand`、`text-brand` 等工具类，对应 `tailwind.config.js` 中的 `brand: '#FF6B35'`。
Token SCSS 和 Tailwind 保持并行，渐进迁移。

## 配置来源

- Token 来源：`packages/tx-tokens/src/miniapp.scss`
- Taro 全局注入：`config/index.ts` → `sass.resource: ['src/styles/tokens.scss']`
- CSS 自定义属性：`src/styles/global.css` → `--color-brand: #FF6B35`
