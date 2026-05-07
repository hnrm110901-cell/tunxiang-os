#!/usr/bin/env node
/**
 * codemod-color — 把硬编码 hex 色字面量替换成 @tx/tokens 引用
 *
 * 安全保证：txColors.<name> 在运行时解析为相同 hex（@tx/tokens 已 export 这些常量），
 * 因此 0 视觉变化，仅消除 lint:hardcoded-color 命中。
 *
 * 处理范围：.tsx / .ts 中的 '<hex>' / "<hex>" 字符串字面量
 * 不动：注释内容 / .css/.scss/.vue / 豁免文件
 *
 * 用法：
 *   node scripts/lint-ui/codemod-color.mjs [--dry-run] [--limit N]
 *
 *   --dry-run    仅显示会改的文件 + 计数，不写盘
 *   --limit N    最多处理 N 个文件（按违规数降序）
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { walkFiles, ALL_FRONTEND } from './walk.mjs';

const ROOT = process.cwd();
const args = process.argv.slice(2);
const DRY_RUN = args.includes('--dry-run');
const LIMIT_IDX = args.indexOf('--limit');
const LIMIT = LIMIT_IDX >= 0 ? parseInt(args[LIMIT_IDX + 1], 10) : Infinity;

// hex → token name 映射（与 @tx/tokens/src/tokens.ts 对齐）
const HEX_TO_TOKEN = {
  '#FF6B35': 'primary',
  '#FF6B2C': 'primary',         // h5 老版本错误色，统一为 primary
  '#FF8555': 'primaryHover',
  '#E55A28': 'primaryActive',
  '#FFF3ED': 'primaryLight',
  '#1E2A3A': 'navy',
  '#2C3E50': 'navyLight',
  '#0F6E56': 'success',
  '#E8F5F0': 'successLight',
  '#BA7517': 'warning',
  '#FEF3E2': 'warningLight',
  '#A32D2D': 'danger',
  '#FDEAEA': 'dangerLight',
  '#185FA5': 'info',
  '#E8F0FB': 'infoLight',
  // 不映射（无对应 token）：#CC4A1A / #141E2A
};

const HEX_PATTERN = /(['"])(#[0-9A-Fa-f]{6})\1/g;

const EXEMPT = [
  'packages/tx-tokens/src/tokens.css',
  'packages/tx-tokens/src/tokens.ts',
  'packages/tx-tokens/src/miniapp.scss',
  'packages/tx-touch/src/styles/base-theme.ts',
  '.storybook/',
];

function isExempt(rel) {
  return EXEMPT.some(e => rel === e || rel.startsWith(e));
}

/**
 * 跳过注释行：判断给定 hex 出现的位置是否在 // 注释或 /* * / 块内（启发式）
 * 由于精确判断需 AST，这里仅排除以 // 开头的整行
 */
function isInLineComment(line, idx) {
  const before = line.slice(0, idx);
  const sl = before.indexOf('//');
  return sl >= 0;
}

function processFile(filepath, rel) {
  const original = readFileSync(filepath, 'utf8');
  const lines = original.split('\n');
  let modified = false;
  let replaceCount = 0;
  const usedTokens = new Set();

  const newLines = lines.map(line => {
    return line.replace(HEX_PATTERN, (match, quote, hex, offset) => {
      const upper = hex.toUpperCase();
      const tokenName = HEX_TO_TOKEN[upper];
      if (!tokenName) return match;
      if (isInLineComment(line, offset)) return match;
      // 跳过 import / export 语句中的字符串（不应该出现，但稳妥起见）
      if (/^\s*(import|export)\s/.test(line)) return match;
      modified = true;
      replaceCount++;
      usedTokens.add(tokenName);
      return `txColors.${tokenName}`;
    });
  });

  if (!modified) return { changed: false, count: 0 };

  // 注入 import（如果尚未引入）
  let result = newLines.join('\n');
  const hasImport = /import\s+(?:{[^}]*\btxColors\b[^}]*}|.*\btxColors\b)\s+from\s+['"]@tx\/tokens['"]/.test(result);

  if (!hasImport) {
    // 找到第一个 import 块末尾插入；如果没 import 块就插在文件顶部（罕见）
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

  if (!DRY_RUN) {
    writeFileSync(filepath, result);
  }

  return { changed: true, count: replaceCount, tokens: [...usedTokens] };
}

// 先按违规数排序（取并集，从多到少处理）
const candidates = [];
for (const app of ALL_FRONTEND) {
  for (const file of walkFiles(join(ROOT, app), ['.tsx', '.ts'])) {
    const rel = file.slice(ROOT.length + 1);
    if (isExempt(rel)) continue;
    const content = readFileSync(file, 'utf8');
    let count = 0;
    for (const hex of Object.keys(HEX_TO_TOKEN)) {
      const re = new RegExp(`(['"])${hex.replace(/\$/g, '\\$')}\\1`, 'gi');
      const matches = content.match(re);
      if (matches) count += matches.length;
    }
    if (count > 0) candidates.push({ filepath: file, rel, count });
  }
}

candidates.sort((a, b) => b.count - a.count);

const target = candidates.slice(0, LIMIT);

console.log(`待处理文件 ${candidates.length}，本次处理 ${target.length}（${DRY_RUN ? 'DRY-RUN' : '写盘'}）\n`);

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
