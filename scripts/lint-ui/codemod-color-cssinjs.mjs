#!/usr/bin/env node
/**
 * codemod-color-cssinjs — TSX/TS 中 CSS shorthand 字符串内嵌 hex 替换
 *
 * 目标：处理 codemod-color.mjs 漏掉的"hex 嵌在更长字符串内"的场景
 *   '2px solid #FF6B35'    → `2px solid ${txColors.primary}`
 *   '1px solid #A32D2D'    → `1px solid ${txColors.danger}`
 *   '3px solid #FF6B35 inset' → `3px solid ${txColors.primary} inset`
 *
 * 安全：模板字符串在运行时拼接为相同的字符串值，0 行为变化
 *
 * 用法：
 *   node scripts/lint-ui/codemod-color-cssinjs.mjs [--dry-run] [--limit N]
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { walkFiles, ALL_FRONTEND } from './walk.mjs';

const ROOT = process.cwd();
const args = process.argv.slice(2);
const DRY_RUN = args.includes('--dry-run');
const LIMIT_IDX = args.indexOf('--limit');
const LIMIT = LIMIT_IDX >= 0 ? parseInt(args[LIMIT_IDX + 1], 10) : Infinity;

const HEX_TO_TOKEN = {
  '#FF6B35': 'primary', '#FF6B2C': 'primary',
  '#FF8555': 'primaryHover', '#E55A28': 'primaryActive', '#FFF3ED': 'primaryLight',
  '#1E2A3A': 'navy', '#2C3E50': 'navyLight',
  '#0F6E56': 'success', '#E8F5F0': 'successLight',
  '#BA7517': 'warning', '#FEF3E2': 'warningLight',
  '#A32D2D': 'danger', '#FDEAEA': 'dangerLight',
  '#185FA5': 'info', '#E8F0FB': 'infoLight',
};

const HEX_ALT = Object.keys(HEX_TO_TOKEN).join('|');
// 匹配 '<text>#HEX<text>' 或 "<text>#HEX<text>"，要求字符串内有除 hex 外的内容
// 简化：仅处理单引号字符串（更常见）
const STRING_WITH_HEX = new RegExp(`'([^'\\n]*?)(${HEX_ALT})([^'\\n]*?)'`, 'gi');

const EXEMPT = ['packages/tx-tokens/', 'packages/tx-touch/src/styles/base-theme.ts', '.storybook/'];

function isExempt(rel) {
  return EXEMPT.some(e => rel === e || rel.startsWith(e));
}

function processFile(filepath, rel) {
  const original = readFileSync(filepath, 'utf8');
  const lines = original.split('\n');
  let totalCount = 0;
  const usedTokens = new Set();

  const newLines = lines.map(line => {
    // 跳过纯注释
    const trimmed = line.trim();
    if (trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('*/')) return line;
    if (line.includes('// @lint-ignore-color')) return line;

    return line.replace(STRING_WITH_HEX, (match, prefix, hex, suffix, offset) => {
      // 跳过 inline 注释中的命中
      const beforeMatch = line.slice(0, offset);
      const inlineSlash = beforeMatch.lastIndexOf('//');
      if (inlineSlash >= 0 && beforeMatch.charAt(inlineSlash - 1) !== ':') return match;

      // 跳过 import / export 行
      if (/^\s*(import|export)\s/.test(line)) return match;

      // 要求 prefix 或 suffix 非空（"完全是 hex 的字符串"由前一个 codemod 处理）
      if (prefix === '' && suffix === '') return match;

      // 跳过 prefix 内有 # 的（多个 hex 的复杂场景）
      if (prefix.includes('#') || suffix.includes('#')) return match;

      // 跳过包含模板字符串语法 ${} 的场景（罕见但稳妥）
      if (prefix.includes('${') || suffix.includes('${')) return match;

      const tokenName = HEX_TO_TOKEN[hex.toUpperCase()];
      if (!tokenName) return match;
      totalCount++;
      usedTokens.add(tokenName);
      // 转义 prefix/suffix 中的反引号（理论应无）
      const safePrefix = prefix.replace(/`/g, '\\`');
      const safeSuffix = suffix.replace(/`/g, '\\`');
      return `\`${safePrefix}\${txColors.${tokenName}}${safeSuffix}\``;
    });
  });

  if (totalCount === 0) return { changed: false, count: 0 };

  let result = newLines.join('\n');
  const hasImport = /import\s+(?:{[^}]*\btxColors\b[^}]*}|.*\btxColors\b)\s+from\s+['"]@tx\/tokens['"]/.test(result);
  if (!hasImport) {
    const importMatches = [...result.matchAll(/^import\s.+?;$/gm)];
    if (importMatches.length > 0) {
      const last = importMatches[importMatches.length - 1];
      const insertPos = last.index + last[0].length;
      result = result.slice(0, insertPos)
             + `\nimport { txColors } from '@tx/tokens';`
             + result.slice(insertPos);
    } else {
      result = `import { txColors } from '@tx/tokens';\n` + result;
    }
  }

  if (!DRY_RUN) writeFileSync(filepath, result);
  return { changed: true, count: totalCount, tokens: [...usedTokens] };
}

const candidates = [];
for (const app of ALL_FRONTEND) {
  for (const file of walkFiles(join(ROOT, app), ['.tsx', '.ts'])) {
    const rel = file.slice(ROOT.length + 1);
    if (isExempt(rel)) continue;
    const content = readFileSync(file, 'utf8');
    const matches = content.match(STRING_WITH_HEX);
    if (matches) candidates.push({ filepath: file, rel, count: matches.length });
  }
}

candidates.sort((a, b) => b.count - a.count);
const target = candidates.slice(0, LIMIT);
console.log(`候选 ${candidates.length}，本次处理 ${target.length}（${DRY_RUN ? 'DRY-RUN' : '写盘'}）\n`);

let totalReplaced = 0;
let totalFiles = 0;
for (const c of target) {
  const r = processFile(c.filepath, c.rel);
  if (r.changed) {
    totalReplaced += r.count;
    totalFiles++;
    console.log(`  ${String(r.count).padStart(4)}  ${c.rel}  [${r.tokens.join(', ')}]`);
  }
}
console.log(`\n汇总：${totalFiles} 文件 / ${totalReplaced} 处替换${DRY_RUN ? '（未写盘）' : ''}`);
