/**
 * UI lint 共享文件遍历工具 + baseline 机制
 * 用于 packages/tx-touch + apps/web-* 等前端目录扫描
 *
 * baseline 模式（默认）：
 *   - 读 scripts/lint-ui/baseline.json 中对应 lint 名的 max
 *   - 违规数 > max → exit 1；<= max → exit 0（仍打印违规便于团队渐进清理）
 *   - --strict 标志：忽略基线，违规 > 0 即 fail
 *   - --update-baseline 标志：把当前违规数写入 baseline.json 并 exit 0
 */
import { readdirSync, statSync, readFileSync, writeFileSync } from 'node:fs';
import { join, extname, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const SKIP_DIRS = new Set([
  'node_modules', 'dist', 'build', '.next', '.turbo', 'coverage',
  '__tests__', '__pycache__', '.cache', '.vite',
]);

/**
 * 递归遍历目录，yield 符合扩展名的文件绝对路径
 *
 * @param {string} dir - 目录绝对路径
 * @param {string[]} exts - 扩展名（带点，如 ['.tsx', '.ts']）
 */
export function* walkFiles(dir, exts = ['.tsx', '.ts', '.css']) {
  let entries;
  try {
    entries = readdirSync(dir);
  } catch {
    return;
  }
  for (const entry of entries) {
    if (SKIP_DIRS.has(entry) || entry.startsWith('.')) continue;
    const full = join(dir, entry);
    let stat;
    try {
      stat = statSync(full);
    } catch {
      continue;
    }
    if (stat.isDirectory()) {
      yield* walkFiles(full, exts);
    } else if (exts.includes(extname(entry))) {
      yield full;
    }
  }
}

/**
 * Store 终端目录列表（v1.0 宪法 §2.2-2.4）
 */
export const STORE_APPS = ['apps/web-pos', 'apps/web-kds', 'apps/web-crew'];

/**
 * 全前端目录列表（覆盖品牌色检查）
 */
export const ALL_FRONTEND = [
  'apps/web-pos', 'apps/web-kds', 'apps/web-crew',
  'apps/web-admin', 'apps/web-hub', 'apps/web-forge', 'apps/web-forge-admin',
  'apps/web-reception', 'apps/web-tv-menu', 'apps/web-wecom-sidebar',
  'apps/h5-self-order',
  'apps/miniapp-customer', 'apps/miniapp-customer-v2',
  'packages/tx-touch', 'packages/tx-tokens',
  'shared/design-system',
];

/**
 * 输出违规清单 + baseline 比对，按结果退出
 *
 * @param {string} title - 检查项名称（与 baseline.json key 对应）
 * @param {Array<{file:string, line:number, content:string, message:string}>} violations
 * @param {string} root - 项目根，用于剪短路径
 */
export function reportAndExit(title, violations, root) {
  const __dirname = dirname(fileURLToPath(import.meta.url));
  const baselinePath = join(__dirname, 'baseline.json');
  const args = process.argv.slice(2);
  const isStrict = args.includes('--strict');
  const isUpdate = args.includes('--update-baseline');

  // 打印违规明细（最多 20 条防止刷屏，剩余仅汇总）
  const PREVIEW = 20;
  if (violations.length > 0) {
    console.error(`[${title}] 当前 ${violations.length} 处违规${violations.length > PREVIEW ? `（仅显示前 ${PREVIEW} 条）` : ''}：\n`);
    for (const v of violations.slice(0, PREVIEW)) {
      const rel = v.file.startsWith(root) ? v.file.slice(root.length + 1) : v.file;
      console.error(`  ${rel}:${v.line}`);
      console.error(`    ${v.content.trim().slice(0, 120)}`);
      console.error(`    → ${v.message}\n`);
    }
  }

  // --update-baseline：写入并退出
  if (isUpdate) {
    let baseline;
    try {
      baseline = JSON.parse(readFileSync(baselinePath, 'utf8'));
    } catch {
      baseline = {};
    }
    const previous = baseline[title] ?? 0;
    baseline[title] = violations.length;
    writeFileSync(baselinePath, JSON.stringify(baseline, null, 2) + '\n');
    console.log(`✏  [${title}] baseline 更新: ${previous} → ${violations.length}`);
    process.exit(0);
  }

  // --strict：违规 > 0 即 fail
  if (isStrict) {
    if (violations.length === 0) {
      console.log(`✓ [${title}] strict 模式：无违规`);
      process.exit(0);
    }
    console.error(`✗ [${title}] strict 模式：违规数 ${violations.length} > 0`);
    process.exit(1);
  }

  // 默认 baseline 模式
  let max = 0;
  try {
    const baseline = JSON.parse(readFileSync(baselinePath, 'utf8'));
    max = baseline[title] ?? 0;
  } catch {
    /* no baseline file → max=0 */
  }

  if (violations.length === 0) {
    console.log(`✓ [${title}] 无违规（baseline=${max}）`);
    process.exit(0);
  }
  if (violations.length <= max) {
    console.log(`◐ [${title}] ${violations.length} 处违规 ≤ baseline ${max}（informational，不阻塞 PR）`);
    process.exit(0);
  }
  console.error(`✗ [${title}] ${violations.length} 处违规 > baseline ${max}（PR 引入了新违规，请修复或更新 baseline）`);
  process.exit(1);
}
