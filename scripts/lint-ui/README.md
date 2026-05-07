# UI Quality Gate（v1.0 宪法 lint 套件）

> 锁定 `docs/ui-ux-constitution-v1.md` §6 4 道 UI 质量闸门，防止规范漂移。

## 4 道闸门

| 检查项 | 规则来源 | 当前 baseline |
|--------|---------|--------------|
| `no-antd-in-store` | v1.0 §9 #1 — Store 终端禁用 AntD | 3（→ #268 清理） |
| `hardcoded-color` | v1.0 §3.6 — 禁止硬编码品牌/语义色 | 4112（→ #251 清理） |
| `tap-target` | v1.0 §3.4 — Store ≥48px / 关键 ≥72px | 447（含 base-theme legacy）|
| `font-size` | v1.0 §3.3 — Store ≥16px / KDS 强化 | 1712 |

## 使用

```bash
# 一次跑全部（baseline 模式，违规 ≤ baseline 即通过）
pnpm lint:ui

# 单跑某项
pnpm lint:no-antd-in-store
pnpm lint:hardcoded-color
pnpm lint:tap-target
pnpm lint:font-size

# 严格模式：违规 > 0 即 fail（用于已清理至 0 的检查项）
node scripts/lint-ui/no-antd-in-store.mjs --strict

# 团队完成清理后，更新 baseline 降低数字
node scripts/lint-ui/font-size.mjs --update-baseline
```

## 模式说明

### baseline 模式（默认 / CI 走这条）

- 读 `baseline.json` 对应 lint 名的 max 值
- 违规数 > max → exit 1（PR 引入新违规即 fail）
- 违规数 ≤ max → exit 0（informational：仍打印前 20 条便于团队渐进清理）
- 违规数 == 0 → exit 0（自然达到目标）

### --strict 模式

- 忽略基线，违规 > 0 即 fail
- 用途：已彻底清理的检查项进入"防回退"状态
- 路径：每个检查项最终都应进入 strict（专项清理 issue 完结后切换）

### --update-baseline 模式

- 把当前违规数写入 `baseline.json`
- 仅用于"已合并清理 PR 后"降低基线
- 严禁拿 --update-baseline 来临时绕过 fail（会让 baseline 飘忽）

## 添加新 lint

新检查项放 `scripts/lint-ui/<name>.mjs`，调用 `walk.mjs` 暴露的：

- `walkFiles(dir, exts)` — 递归文件
- `STORE_APPS`、`ALL_FRONTEND` — 目录常量
- `reportAndExit(title, violations, root)` — 输出 + 三种模式分发

然后：
1. 在 `package.json` scripts 加 `lint:<name>` 入口
2. 在 `all.mjs` CHECKS 数组追加
3. 在 `baseline.json` 加初始基线
4. 在 `.github/workflows/ui-quality-gate.yml` 加 step

## 与宪法的关系

```
docs/ui-ux-constitution-v1.md §6 (人读)
  ↓
.claude/skills/tx-ui/references/{tokens,store}.md (Claude 读)
  ↓
packages/tx-tokens/src/tokens.css (运行时引用)
  ↓
scripts/lint-ui/* (CI 强制) ← 你在这里
```

## 路线

- M1 末（2026-06-07）：4 baseline 锁定，无回退
- M2 末（2026-09-07）：tap-target / font-size 进入 --strict（KDS / TXTouch 字号清零）
- M3 末（2026-12-07）：no-antd-in-store + hardcoded-color 进入 --strict（#251 / #268 完结）
- 终极：4 道全 strict，违规 = 0
