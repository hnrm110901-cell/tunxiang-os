#!/usr/bin/env node
/**
 * codemod-color-css — CSS 文件中硬编码 hex 替换为 var(--tx-*)
 *
 * 处理范围：.css / .module.css / .scss
 * 安全：CSS Variables 在所有现代浏览器中的样式值上下文等价于 hex
 * 不动：注释 / 已经是 var(...) 的位置 / 豁免文件
 *
 * 用法：
 *   node scripts/lint-ui/codemod-color-css.mjs [--dry-run] [--limit N]
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { walkFiles, ALL_FRONTEND } from './walk.mjs';

const ROOT = process.cwd();
const args = process.argv.slice(2);
const DRY_RUN = args.includes('--dry-run');
const LIMIT_IDX = args.indexOf('--limit');
const LIMIT = LIMIT_IDX >= 0 ? parseInt(args[LIMIT_IDX + 1], 10) : Infinity;

// hex → CSS Variable 名映射（与 packages/tx-tokens/src/tokens.css 对齐）
const HEX_TO_VAR = {
  '#FF6B35': '--tx-primary',
  '#FF6B2C': '--tx-primary',
  '#FF8555': '--tx-primary-hover',
  '#E55A28': '--tx-primary-active',
  '#FFF3ED': '--tx-primary-light',
  '#1E2A3A': '--tx-navy',
  '#2C3E50': '--tx-navy-light',
  '#0F6E56': '--tx-success',
  '#E8F5F0': '--tx-success-light',
  '#BA7517': '--tx-warning',
  '#FEF3E2': '--tx-warning-light',
  '#A32D2D': '--tx-danger',
  '#FDEAEA': '--tx-danger-light',
  '#185FA5': '--tx-info',
  '#E8F0FB': '--tx-info-light',
};

const EXEMPT = [
  'packages/tx-tokens/',
  'packages/tx-touch/src/styles/base-theme.ts',
  '.storybook/',
];

function isExempt(rel) {
  return EXEMPT.some(e => rel === e || rel.startsWith(e));
}

/**
 * 一行 CSS 中替换 6 字符 hex（精确匹配，不动 8 字符 alpha hex）
 * 跳过：注释行、已经在 var() 内的位置（fallback）
 */
function transformLine(line) {
  // 整行注释跳过
  const trimmed = line.trim();
  if (trimmed.startsWith('/*') || trimmed.startsWith('//') || trimmed.startsWith('*')) return { line, count: 0 };

  let count = 0;
  let result = '';
  let i = 0;
  while (i < line.length) {
    // 寻找下一个 # 开头的可能 hex
    if (line[i] === '#' && /[0-9A-Fa-f]/.test(line[i + 1])) {
      // 提取最多 8 个 hex 字符
      let j = i + 1;
      while (j < line.length && /[0-9A-Fa-f]/.test(line[j]) && j - i < 9) j++;
      const hex = line.slice(i, j);
      // 仅处理 6 字符 hex（标准化大写后）
      if (hex.length === 7) { // # + 6 hex chars
        const upper = hex.toUpperCase();
        const cssVar = HEX_TO_VAR[upper];
        if (cssVar) {
          // 检查是否已在 var( 之内（fallback 位）— 跳过
          const before = result + line.slice(i - result.length + result.length, i); // fragile, simplify
          const lastVarOpen = (result + line.slice(0, i)).lastIndexOf('var(');
          const lastVarClose = (result + line.slice(0, i)).lastIndexOf(')');
          const inVar = lastVarOpen > lastVarClose;
          if (!inVar) {
            result += `var(${cssVar})`;
            i = j;
            count++;
            continue;
          }
        }
      }
      result += line.slice(i, j);
      i = j;
      continue;
    }
    result += line[i];
    i++;
  }
  return { line: result, count };
}

function processFile(filepath, rel) {
  const original = readFileSync(filepath, 'utf8');
  const lines = original.split('\n');
  let totalCount = 0;
  const newLines = lines.map(line => {
    const { line: newLine, count } = transformLine(line);
    totalCount += count;
    return newLine;
  });
  if (totalCount === 0) return { changed: false, count: 0 };
  if (!DRY_RUN) {
    writeFileSync(filepath, newLines.join('\n'));
  }
  return { changed: true, count: totalCount };
}

const candidates = [];
for (const app of ALL_FRONTEND) {
  for (const file of walkFiles(join(ROOT, app), ['.css', '.scss'])) {
    const rel = file.slice(ROOT.length + 1);
    if (isExempt(rel)) continue;
    const content = readFileSync(file, 'utf8');
    let count = 0;
    for (const hex of Object.keys(HEX_TO_VAR)) {
      const re = new RegExp(hex.replace(/\$/g, '\\$'), 'gi');
      const matches = content.match(re);
      if (matches) count += matches.length;
    }
    if (count > 0) candidates.push({ filepath: file, rel, count });
  }
}

candidates.sort((a, b) => b.count - a.count);
const target = candidates.slice(0, LIMIT);

console.log(`CSS 候选 ${candidates.length}，本次处理 ${target.length}（${DRY_RUN ? 'DRY-RUN' : '写盘'}）\n`);

let totalReplaced = 0;
let totalFiles = 0;
for (const c of target) {
  const r = processFile(c.filepath, c.rel);
  if (r.changed) {
    totalReplaced += r.count;
    totalFiles++;
    console.log(`  ${String(r.count).padStart(4)}  ${c.rel}`);
  }
}

console.log(`\n汇总：${totalFiles} 文件 / ${totalReplaced} 处替换${DRY_RUN ? '（未写盘）' : ''}`);
