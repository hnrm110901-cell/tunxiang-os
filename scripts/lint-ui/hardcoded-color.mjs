#!/usr/bin/env node
/**
 * lint:hardcoded-color
 *
 * 规则：v1.0 宪法 §3.6 — 不允许任何文件硬编码品牌 / 语义色 hex
 * 检查：全前端目录扫描以下 hex（大小写不敏感）：
 *   #FF6B35 / #FF6B2C(老 H5) / #FF8555 / #E55A28 / #FFF3ED / #CC4A1A
 *   #1E2A3A / #2C3E50 / #141E2A
 *   #0F6E56 / #BA7517 / #A32D2D / #185FA5
 * 例外：tokens.css / tokens.ts / 测试 fixture 文件
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { walkFiles, ALL_FRONTEND, reportAndExit } from './walk.mjs';

const ROOT = process.cwd();

const BRAND_HEXES = [
  '#FF6B35', '#FF6B2C', '#FF8555', '#E55A28', '#FFF3ED', '#CC4A1A',
  '#1E2A3A', '#2C3E50', '#141E2A',
  '#0F6E56', '#BA7517', '#A32D2D', '#185FA5',
  '#E8F5F0', '#FEF3E2', '#FDEAEA', '#E8F0FB',
];
const PATTERN = new RegExp(BRAND_HEXES.map(h => h).join('|'), 'gi');

const EXEMPT_PATHS = [
  'packages/tx-tokens/src/tokens.css',
  'packages/tx-tokens/src/tokens.ts',
  'packages/tx-tokens/src/miniapp.scss',
  'packages/tx-touch/src/styles/base-theme.ts',
  '.storybook/',
];

function isExempt(file) {
  const rel = file.slice(ROOT.length + 1);
  return EXEMPT_PATHS.some(p => rel === p || rel.startsWith(p));
}

const violations = [];

/**
 * 跳过逻辑：
 *  1. 纯注释行（trim 后以 // 或 * 开头）
 *  2. CSS var 防御性 fallback：line 包含 `var(--tx-` 且 hex 出现在 `,` 之后（fallback 位）
 *  3. inline 注释 `// @lint-ignore-color`
 */
function isExemptLine(line, hexMatch, hexIdx) {
  const trimmed = line.trim();
  if (trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('*/')) return true;
  if (line.includes('// @lint-ignore-color')) return true;
  // inline 注释：hex 出现在行内 // 之后
  const beforeHex = line.slice(0, hexIdx);
  const inlineSlash = beforeHex.lastIndexOf('//');
  // 排除 url 中的 // (如 'https://...'), 简单启发：// 前不能是 :
  if (inlineSlash >= 0 && beforeHex.charAt(inlineSlash - 1) !== ':') return true;
  // CSS var fallback：var(--*, #HEX) — hex 出现在 var( 之内的 fallback 位置
  const varOpenIdx = line.lastIndexOf('var(--', hexIdx);
  if (varOpenIdx >= 0) {
    const between = line.slice(varOpenIdx, hexIdx);
    // var( 之后到 hex 之间有逗号且未越过 ) 边界 → fallback
    if (between.includes(',') && !between.includes(')')) return true;
  }
  return false;
}

for (const app of ALL_FRONTEND) {
  const appDir = join(ROOT, app);
  for (const file of walkFiles(appDir, ['.tsx', '.ts', '.css', '.scss', '.vue'])) {
    if (isExempt(file)) continue;
    const content = readFileSync(file, 'utf8');
    const lines = content.split('\n');
    lines.forEach((line, idx) => {
      let m;
      const localPattern = new RegExp(PATTERN.source, 'gi');
      while ((m = localPattern.exec(line)) !== null) {
        if (isExemptLine(line, m[0], m.index)) continue;
        violations.push({
          file,
          line: idx + 1,
          content: line,
          message: `硬编码品牌/语义色 ${m[0]}（v1.0 §3.6）— 改用 var(--tx-*) 或 @tx/tokens`,
        });
      }
    });
  }
}

reportAndExit('hardcoded-color', violations, ROOT);
