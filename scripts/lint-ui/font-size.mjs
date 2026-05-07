#!/usr/bin/env node
/**
 * lint:font-size
 *
 * 规则：v1.0 宪法 §3.3 — Store 终端绝对底线 16px；KDS 应用额外强制
 *   - 桌号 / 订单号 ≥ 32px 粗体
 *   - 区域 / 档口标题 ≥ 28px
 *   - 菜品行 ≥ 20px
 *   - 倒计时 ≥ 32px 粗体
 *   - VIP / 状态徽标 ≥ 16px
 * 检查：apps/web-{pos,kds,crew}/src 与 packages/tx-touch/src 中：
 *   1) Tailwind text-xs (12px) / text-sm (14px) — 在 Store 终端 fail
 *   2) inline style fontSize: <16
 *   3) CSS font-size: <16px
 * 例外：纯图标徽标（rushIcon 等）需用注释豁免 `/* @lint-ignore-font *\/`
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { walkFiles, STORE_APPS, reportAndExit } from './walk.mjs';

const ROOT = process.cwd();
const TX_TOUCH = 'packages/tx-touch';

const violations = [];

const TW_SMALL = /\btext-(xs|sm)\b/;
const INLINE_FS = /fontSize:\s*(\d+)/g;
const CSS_FS = /font-size:\s*(\d+)px\s*;/g;

function checkTsxLine(file, line, idx) {
  if (TW_SMALL.test(line)) {
    const m = line.match(TW_SMALL);
    const px = m[1] === 'xs' ? 12 : 14;
    violations.push({
      file, line: idx + 1, content: line,
      message: `Tailwind text-${m[1]} (= ${px}px) < 16px Store 底线（v1.0 §3.3）`,
    });
  }
  let m;
  while ((m = INLINE_FS.exec(line)) !== null) {
    const px = parseInt(m[1], 10);
    if (px < 16 && px > 0) {
      violations.push({
        file, line: idx + 1, content: line,
        message: `inline fontSize: ${px} < 16px（v1.0 §3.3）`,
      });
    }
  }
  INLINE_FS.lastIndex = 0;
}

function checkCssLine(file, line, idx) {
  if (line.includes('/* @lint-ignore-font */')) return;
  let m;
  while ((m = CSS_FS.exec(line)) !== null) {
    const px = parseInt(m[1], 10);
    if (px < 16 && px > 0) {
      violations.push({
        file, line: idx + 1, content: line,
        message: `CSS font-size: ${px}px < 16px Store 底线（v1.0 §3.3）— 用 var(--tx-store-caption) 等 token 或加 /* @lint-ignore-font */ 注释（仅图标徽标）`,
      });
    }
  }
  CSS_FS.lastIndex = 0;
}

for (const app of [...STORE_APPS, TX_TOUCH]) {
  const appDir = join(ROOT, app, 'src');
  for (const file of walkFiles(appDir, ['.tsx', '.ts'])) {
    const content = readFileSync(file, 'utf8');
    const lines = content.split('\n');
    lines.forEach((line, idx) => checkTsxLine(file, line, idx));
  }
  for (const file of walkFiles(appDir, ['.css'])) {
    const content = readFileSync(file, 'utf8');
    const lines = content.split('\n');
    lines.forEach((line, idx) => checkCssLine(file, line, idx));
  }
}

reportAndExit('font-size', violations, ROOT);
