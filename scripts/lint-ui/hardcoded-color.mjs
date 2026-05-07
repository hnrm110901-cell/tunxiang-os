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

for (const app of ALL_FRONTEND) {
  const appDir = join(ROOT, app);
  for (const file of walkFiles(appDir, ['.tsx', '.ts', '.css', '.scss', '.vue'])) {
    if (isExempt(file)) continue;
    const content = readFileSync(file, 'utf8');
    const lines = content.split('\n');
    lines.forEach((line, idx) => {
      const matches = line.match(PATTERN);
      if (matches) {
        violations.push({
          file,
          line: idx + 1,
          content: line,
          message: `硬编码品牌/语义色 ${matches[0]}（v1.0 §3.6）— 改用 var(--tx-*) 或 @tx/tokens`,
        });
      }
    });
  }
}

reportAndExit('hardcoded-color', violations, ROOT);
