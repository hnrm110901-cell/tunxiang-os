#!/usr/bin/env node
/**
 * lint:ui — 串联跑 4 个 UI 质量闸门
 *
 *   1. no-antd-in-store
 *   2. hardcoded-color
 *   3. tap-target
 *   4. font-size
 *
 * 任一 fail 整体退出 1，但其他仍会跑完，便于一次看到所有违规。
 */
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));

const CHECKS = [
  { name: 'no-antd-in-store', file: 'no-antd-in-store.mjs' },
  { name: 'hardcoded-color',  file: 'hardcoded-color.mjs' },
  { name: 'tap-target',       file: 'tap-target.mjs' },
  { name: 'font-size',        file: 'font-size.mjs' },
];

const results = [];
for (const c of CHECKS) {
  const start = Date.now();
  const r = spawnSync('node', [join(__dirname, c.file)], { stdio: 'inherit' });
  const ms = Date.now() - start;
  results.push({ name: c.name, code: r.status ?? 1, ms });
}

console.log('\n─── lint:ui 汇总 ───');
let totalMs = 0;
let failedCount = 0;
for (const r of results) {
  totalMs += r.ms;
  const status = r.code === 0 ? '✓' : '✗';
  console.log(`  ${status} ${r.name.padEnd(20)} ${r.ms}ms`);
  if (r.code !== 0) failedCount++;
}
console.log(`\n  总耗时 ${totalMs}ms，失败 ${failedCount}/${results.length}`);

process.exit(failedCount > 0 ? 1 : 0);
