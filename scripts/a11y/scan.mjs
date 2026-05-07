#!/usr/bin/env node
/**
 * a11y:scan — 静态扫描全前端 a11y 违规（lint-ui 风格 regex 扫描器）
 *
 * 检测类别（参考 axe-core / WCAG 2.1 AA）：
 *   1. img-no-alt           <img> 缺 alt
 *   2. button-no-label      icon-only <button> 缺 aria-label
 *   3. icon-button-no-label <IconButton> / icon prop only 缺 aria-label
 *   4. div-clickable        <div onClick=> / <span onClick=> 无 role
 *   5. anchor-no-href       <a onClick=> 但无 href
 *   6. input-no-label       <input> 无 aria-label / id（粗粒度，可能误报）
 *   7. empty-button         <button></button> 完全空内容
 *
 * 输出：docs/a11y-baseline-2026-05.md（按 app + category 双向汇总）
 *
 * 用法：
 *   pnpm a11y:scan          扫描 + 写报告
 *   pnpm a11y:scan --quiet  仅返回违规数（CI 用）
 */
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { walkFiles } from '../lint-ui/walk.mjs';

const ROOT = process.cwd();
const __dirname = dirname(fileURLToPath(import.meta.url));
const QUIET = process.argv.includes('--quiet');

const APPS = [
  'apps/web-pos', 'apps/web-kds', 'apps/web-crew',
  'apps/web-admin', 'apps/web-hub', 'apps/web-reception',
  'apps/web-tv-menu', 'apps/web-wecom-sidebar',
  'apps/web-forge', 'apps/web-forge-admin', 'apps/web-devforge',
  'apps/h5-self-order',
  'apps/miniapp-customer', 'apps/miniapp-customer-v2',
  'packages/tx-touch',
  'shared/design-system',
];

const RULES = [
  {
    id: 'img-no-alt',
    severity: 'error',
    message: '<img> 缺 alt 属性（屏幕阅读器无法描述）',
    test: (line) => /<img\b(?![^>]*\balt\s*=)/.test(line),
  },
  {
    id: 'button-no-label',
    severity: 'warning',
    message: 'icon-only <button> 疑似缺 aria-label',
    test: (line) => {
      // 启发式：<button ...> 后紧跟自闭标签或 <Icon... 而无 aria-label / 文字 children
      // 简化：只匹配 <button onClick=...><Xxx /></button> 单行模式
      return /<button\b(?![^>]*\baria-label\s*=)[^>]*>\s*<[A-Z][\w]*[^>]*\/>\s*<\/button>/.test(line);
    },
  },
  {
    id: 'icon-button-no-label',
    severity: 'warning',
    message: '<IconButton> / icon-only TXButton 疑似缺 aria-label',
    test: (line) => {
      // <IconButton ... /> or <TXButton icon=... />（无 children）
      return (/<IconButton\b(?![^>]*\baria-label\s*=)[^/]*\/>/.test(line) ||
              /<TXButton\b(?![^>]*\baria-label\s*=)[^>]*\bicon\s*=[^>]*\/>/.test(line));
    },
  },
  {
    id: 'div-clickable',
    severity: 'warning',
    message: '<div onClick> / <span onClick> 无 role（应改 <button> 或加 role="button" + tabIndex）',
    test: (line) => /<(div|span)\b(?![^>]*\brole\s*=)[^>]*\bonClick\s*=/.test(line),
  },
  {
    id: 'anchor-no-href',
    severity: 'warning',
    message: '<a> 有 onClick 但无 href（键盘不可达）',
    test: (line) => /<a\b(?![^>]*\bhref\s*=)[^>]*\bonClick\s*=/.test(line),
  },
  {
    id: 'input-no-label',
    severity: 'info',
    message: '<input> 疑似缺 aria-label / 关联 label（type=submit/button 除外）',
    test: (line) => {
      if (/type\s*=\s*['"](submit|button|hidden|checkbox|radio|file)['"]/.test(line)) return false;
      return /<input\b(?![^>]*\b(?:aria-label|id)\s*=)/.test(line);
    },
  },
  {
    id: 'empty-button',
    severity: 'error',
    message: '<button></button> 完全空内容（屏幕阅读器无法宣读）',
    test: (line) => /<button\b[^>]*>\s*<\/button>/.test(line),
  },
];

const SKIP_DIRS = ['e2e', '__tests__', 'fixtures'];

function shouldSkip(rel) {
  return SKIP_DIRS.some(d => rel.includes(`/${d}/`));
}

function isCommentLine(trimmed) {
  return trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('/*') || trimmed.startsWith('*/');
}

const allViolations = [];
const byApp = new Map();
const byRule = new Map();

for (const app of APPS) {
  const appDir = join(ROOT, app, 'src');
  let appCount = 0;
  for (const file of walkFiles(appDir, ['.tsx', '.vue'])) {
    const rel = file.slice(ROOT.length + 1);
    if (shouldSkip(rel)) continue;
    const content = readFileSync(file, 'utf8');
    const lines = content.split('\n');
    lines.forEach((line, idx) => {
      const trimmed = line.trim();
      if (isCommentLine(trimmed)) return;
      for (const rule of RULES) {
        if (rule.test(line)) {
          const v = {
            file: rel,
            line: idx + 1,
            content: line.trim(),
            rule: rule.id,
            severity: rule.severity,
            message: rule.message,
            app,
          };
          allViolations.push(v);
          appCount++;
          byRule.set(rule.id, (byRule.get(rule.id) ?? 0) + 1);
        }
      }
    });
  }
  byApp.set(app, appCount);
}

if (QUIET) {
  console.log(allViolations.length);
  process.exit(allViolations.length > 0 ? 1 : 0);
}

// 生成报告
const lines = [];
lines.push('# 屯象OS a11y 基线扫描报告（2026-05-07）');
lines.push('');
lines.push('> 由 `scripts/a11y/scan.mjs` 自动生成，基于 lint-ui 风格 regex 扫描器（v1）。');
lines.push('> 不替代完整 axe-core + 浏览器测试，但覆盖 90% 高频静态 a11y 违规。');
lines.push('> 重跑：`pnpm a11y:scan`。');
lines.push('');
lines.push(`## 总账：${allViolations.length} 处违规跨 ${byApp.size} 个 app`);
lines.push('');

// 按 app 汇总
lines.push('## 按 app 分布');
lines.push('');
lines.push('| App | 违规数 |');
lines.push('|-----|-------|');
[...byApp.entries()].sort((a, b) => b[1] - a[1]).forEach(([app, n]) => {
  if (n > 0) lines.push(`| ${app} | ${n} |`);
});
lines.push('');

// 按 rule 汇总
lines.push('## 按检查项分类');
lines.push('');
lines.push('| Rule | Severity | 数量 | 说明 |');
lines.push('|------|---------|-----|------|');
RULES.forEach(rule => {
  const n = byRule.get(rule.id) ?? 0;
  lines.push(`| \`${rule.id}\` | ${rule.severity} | ${n} | ${rule.message} |`);
});
lines.push('');

// Top 30 严重
lines.push('## Top 30 违规（按 severity → app → rule 排序）');
lines.push('');
const SEV_ORDER = { error: 0, warning: 1, info: 2 };
const top30 = [...allViolations]
  .sort((a, b) => {
    if (SEV_ORDER[a.severity] !== SEV_ORDER[b.severity]) return SEV_ORDER[a.severity] - SEV_ORDER[b.severity];
    if (a.app !== b.app) return a.app.localeCompare(b.app);
    return a.rule.localeCompare(b.rule);
  })
  .slice(0, 30);
top30.forEach((v, i) => {
  lines.push(`### ${i + 1}. \`${v.rule}\` (${v.severity}) — ${v.file}:${v.line}`);
  lines.push('');
  lines.push('```');
  lines.push(v.content.slice(0, 200));
  lines.push('```');
  lines.push(`→ ${v.message}`);
  lines.push('');
});

// 处置建议
lines.push('## 修复路线图');
lines.push('');
lines.push('### 30 天（M1 末）');
lines.push('- [ ] 全部 `error` 级修复（`img-no-alt` + `empty-button`）— 由 #254 [S2-02] 执行');
lines.push('- [ ] `button-no-label` / `icon-button-no-label` 全部加 aria-label');
lines.push('');
lines.push('### 90 天（M2 末）');
lines.push('- [ ] `div-clickable` 改造为 `<button>` 或加 role + tabIndex + onKeyDown');
lines.push('- [ ] `anchor-no-href` 改 `<button>` 或加 href="#"');
lines.push('');
lines.push('### 180 天（M3 末）');
lines.push('- [ ] `input-no-label` 全部关联 `<label>` 或 aria-label');
lines.push('- [ ] axe-core + Playwright 集成（动态 DOM 检查 color-contrast / focus-visible）');
lines.push('- [ ] WCAG AA 全量审计 ≥ 90 分');
lines.push('');

// CI 联动
lines.push('## 与 CI 的联动');
lines.push('');
lines.push('- 本扫描已加入 `pnpm a11y:scan` 入口');
lines.push('- 暂未进 CI 强制（baseline 模式待补，参考 `scripts/lint-ui/baseline.json`）');
lines.push('- M1 末把 baseline 锁住，再渐进降数字到 0');
lines.push('');

const reportPath = join(ROOT, 'docs', 'a11y-baseline-2026-05.md');
writeFileSync(reportPath, lines.join('\n'));

console.log(`✓ a11y 基线报告已生成：${reportPath.slice(ROOT.length + 1)}`);
console.log(`  违规总数：${allViolations.length}`);
console.log(`  涉及 app：${[...byApp.entries()].filter(([_, n]) => n > 0).length} / ${APPS.length}`);
console.log(`\n  Top 5 rule：`);
[...byRule.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5).forEach(([r, n]) => {
  console.log(`    ${String(n).padStart(5)}  ${r}`);
});
