#!/usr/bin/env node
/**
 * lint:no-antd-in-store
 *
 * 规则：v1.0 宪法 §9 #1 — Store 终端（POS / KDS / Crew）禁止任何 AntD 组件 import
 * 检查：apps/web-{pos,kds,crew}/src/**.{ts,tsx} 中匹配 `from 'antd'` / `from "antd"` / `from 'antd/...'`
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { walkFiles, STORE_APPS, reportAndExit } from './walk.mjs';

const ROOT = process.cwd();
const PATTERN = /from\s+['"]antd(\/[^'"]*)?['"]/g;

const violations = [];

for (const app of STORE_APPS) {
  const appDir = join(ROOT, app, 'src');
  for (const file of walkFiles(appDir, ['.tsx', '.ts'])) {
    const content = readFileSync(file, 'utf8');
    const lines = content.split('\n');
    lines.forEach((line, idx) => {
      if (PATTERN.test(line)) {
        violations.push({
          file,
          line: idx + 1,
          content: line,
          message: 'Store 终端禁止 AntD（v1.0 §9 #1）— 使用 TXTouch 等价组件替代',
        });
      }
      PATTERN.lastIndex = 0;
    });
  }
}

reportAndExit('no-antd-in-store', violations, ROOT);
