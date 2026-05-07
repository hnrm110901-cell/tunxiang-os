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

/**
 * 跨多行匹配 <Tag ...> 元素文本（含自闭和开标签）
 * 返回完整属性区间字符串（不含外层 <>）
 */
function extractElementOpenTag(content, tagName, startIdx) {
  // 从 <tagName 后开始扫描，找到第一个未在字符串/属性表达式内部的 >
  let i = startIdx + tagName.length + 1; // skip "<tagName"
  let inStr = null; // null | "'" | '"' | '`'
  let braceDepth = 0;
  while (i < content.length) {
    const ch = content[i];
    if (inStr) {
      if (ch === '\\') { i += 2; continue; }
      if (ch === inStr) { inStr = null; }
      i++; continue;
    }
    if (ch === "'" || ch === '"' || ch === '`') { inStr = ch; i++; continue; }
    if (ch === '{') { braceDepth++; i++; continue; }
    if (ch === '}') { braceDepth--; i++; continue; }
    if (braceDepth === 0 && ch === '>') {
      return content.slice(startIdx + 1, i + 1); // include closing >
    }
    i++;
  }
  return null;
}

const RULES = [
  {
    id: 'img-no-alt',
    severity: 'error',
    message: '<img> 缺 alt 属性（屏幕阅读器无法描述）',
    multiline: true,
    test: (content) => {
      const violations = [];
      const re = /<img\b/g;
      let m;
      while ((m = re.exec(content)) !== null) {
        const tag = extractElementOpenTag(content, 'img', m.index);
        if (tag && !/\balt\s*=/.test(tag)) {
          // 找到行号
          const lineNum = content.slice(0, m.index).split('\n').length;
          violations.push({ idx: m.index, lineNum });
        }
      }
      return violations;
    },
  },
  {
    id: 'button-no-label',
    severity: 'warning',
    message: 'icon-only <button> 疑似缺 aria-label / 无文字 children',
    multiline: true,
    test: (content) => {
      const violations = [];
      const re = /<button\b/g;
      let m;
      while ((m = re.exec(content)) !== null) {
        const tag = extractElementOpenTag(content, 'button', m.index);
        if (!tag) continue;
        // 含 aria-label / aria-labelledby 即放过
        if (/\baria-(label|labelledby)\s*=/.test(tag)) continue;
        // 自闭标签且无 label → 违规
        if (tag.endsWith('/>')) {
          const lineNum = content.slice(0, m.index).split('\n').length;
          violations.push({ idx: m.index, lineNum });
          continue;
        }
        // 开标签：找 </button>，看 children 是否仅 component 而无文本
        const closeIdx = content.indexOf('</button>', m.index + tag.length);
        if (closeIdx < 0) continue;
        const children = content.slice(m.index + tag.length, closeIdx);
        const stripped = children.replace(/<[^>]+>/g, '').trim();
        // 如果 strip 掉所有 tag 后无文字内容（图标式按钮）→ 违规
        if (stripped === '' || /^[\s{}.一-鿿]*$/.test(stripped) === false) {
          // 进一步：children 是单个组件 <Foo />，剩余空 → icon-only
          const isOnlyComponent = /^\s*<[A-Z][^>]*\/>\s*$/.test(children) ||
                                  /^\s*<[A-Z][^>]*>[^<]*<\/[A-Z]/.test(children);
          if (isOnlyComponent) {
            const lineNum = content.slice(0, m.index).split('\n').length;
            violations.push({ idx: m.index, lineNum });
          }
        }
      }
      return violations;
    },
  },
  {
    id: 'icon-button-no-label',
    severity: 'warning',
    message: '<IconButton> / icon-only TXButton 疑似缺 aria-label',
    multiline: true,
    test: (content) => {
      const violations = [];
      // <IconButton ... />
      const re1 = /<IconButton\b/g;
      let m;
      while ((m = re1.exec(content)) !== null) {
        const tag = extractElementOpenTag(content, 'IconButton', m.index);
        if (tag && !/\baria-(label|labelledby)\s*=/.test(tag) && tag.endsWith('/>')) {
          violations.push({ idx: m.index, lineNum: content.slice(0, m.index).split('\n').length });
        }
      }
      // <TXButton icon=... /> 自闭无 children
      const re2 = /<TXButton\b/g;
      while ((m = re2.exec(content)) !== null) {
        const tag = extractElementOpenTag(content, 'TXButton', m.index);
        if (tag && /\bicon\s*=/.test(tag) && !/\baria-(label|labelledby)\s*=/.test(tag) && tag.endsWith('/>')) {
          violations.push({ idx: m.index, lineNum: content.slice(0, m.index).split('\n').length });
        }
      }
      return violations;
    },
  },
  {
    id: 'div-clickable',
    severity: 'warning',
    message: '<div onClick> / <span onClick> 无 role（应改 <button> 或加 role="button" + tabIndex + onKeyDown）',
    multiline: true,
    test: (content) => {
      const violations = [];
      const re = /<(div|span)\b/g;
      let m;
      while ((m = re.exec(content)) !== null) {
        const tag = extractElementOpenTag(content, m[1], m.index);
        if (!tag) continue;
        if (!/\bonClick\s*=/.test(tag)) continue;
        if (/\brole\s*=/.test(tag)) continue;
        violations.push({ idx: m.index, lineNum: content.slice(0, m.index).split('\n').length });
      }
      return violations;
    },
  },
  {
    id: 'anchor-no-href',
    severity: 'warning',
    message: '<a> 有 onClick 但无 href（键盘不可达）',
    multiline: true,
    test: (content) => {
      const violations = [];
      const re = /<a\b/g;
      let m;
      while ((m = re.exec(content)) !== null) {
        const tag = extractElementOpenTag(content, 'a', m.index);
        if (!tag) continue;
        if (!/\bonClick\s*=/.test(tag)) continue;
        if (/\bhref\s*=/.test(tag)) continue;
        violations.push({ idx: m.index, lineNum: content.slice(0, m.index).split('\n').length });
      }
      return violations;
    },
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

    // 多行规则：rule.test(content) 返回 [{idx, lineNum}, ...]
    for (const rule of RULES) {
      if (!rule.multiline) continue;
      const ms = rule.test(content);
      for (const m of ms) {
        const lineContent = lines[m.lineNum - 1] ?? '';
        allViolations.push({
          file: rel, line: m.lineNum, content: lineContent.trim(),
          rule: rule.id, severity: rule.severity, message: rule.message, app,
        });
        appCount++;
        byRule.set(rule.id, (byRule.get(rule.id) ?? 0) + 1);
      }
    }

    // 单行规则：line-by-line
    lines.forEach((line, idx) => {
      const trimmed = line.trim();
      if (isCommentLine(trimmed)) return;
      for (const rule of RULES) {
        if (rule.multiline) continue;
        if (rule.test(line)) {
          allViolations.push({
            file: rel, line: idx + 1, content: line.trim(),
            rule: rule.id, severity: rule.severity, message: rule.message, app,
          });
          appCount++;
          byRule.set(rule.id, (byRule.get(rule.id) ?? 0) + 1);
        }
      }
    });
  }
  byApp.set(app, appCount);
}

// baseline 模式：与 scripts/lint-ui/baseline.json 中 a11y-* 比对
const isCheckBaseline = process.argv.includes('--check');
const isUpdateBaseline = process.argv.includes('--update-baseline');

if (isCheckBaseline || isUpdateBaseline) {
  const baselinePath = join(ROOT, 'scripts', 'lint-ui', 'baseline.json');
  let baseline = {};
  try { baseline = JSON.parse(readFileSync(baselinePath, 'utf8')); } catch { /* fresh */ }

  const ruleCounts = {};
  for (const r of RULES) ruleCounts[`a11y-${r.id}`] = byRule.get(r.id) ?? 0;

  if (isUpdateBaseline) {
    Object.assign(baseline, ruleCounts);
    writeFileSync(baselinePath, JSON.stringify(baseline, null, 2) + '\n');
    console.log('✏  a11y baseline 更新：');
    Object.entries(ruleCounts).forEach(([k, v]) => console.log(`   ${k}: ${v}`));
    process.exit(0);
  }

  // --check：违规 > baseline 即 fail
  let failed = 0;
  console.log(`a11y baseline 检查（共 ${RULES.length} 规则）：`);
  for (const r of RULES) {
    const k = `a11y-${r.id}`;
    const max = baseline[k] ?? 0;
    const cur = byRule.get(r.id) ?? 0;
    if (cur === 0) {
      console.log(`  ✓ ${r.id} — 0 处`);
    } else if (cur <= max) {
      console.log(`  ◐ ${r.id} — ${cur} ≤ baseline ${max}`);
    } else {
      console.error(`  ✗ ${r.id} — ${cur} > baseline ${max}（PR 引入新违规）`);
      failed++;
    }
  }
  process.exit(failed > 0 ? 1 : 0);
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
