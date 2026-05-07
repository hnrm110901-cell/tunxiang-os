import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { walkFiles, ALL_FRONTEND } from './walk.mjs';

const ROOT = process.cwd();
const BRAND_HEXES = ['#FF6B35','#FF6B2C','#FF8555','#E55A28','#FFF3ED','#CC4A1A','#1E2A3A','#2C3E50','#141E2A','#0F6E56','#BA7517','#A32D2D','#185FA5','#E8F5F0','#FEF3E2','#FDEAEA','#E8F0FB'];
const PATTERN = new RegExp(BRAND_HEXES.join('|'), 'gi');
const EXEMPT = ['packages/tx-tokens/src/tokens.css','packages/tx-tokens/src/tokens.ts','packages/tx-tokens/src/miniapp.scss','packages/tx-touch/src/styles/base-theme.ts','.storybook/'];

const byFile = new Map();
const byHex = new Map();

for (const app of ALL_FRONTEND) {
  for (const file of walkFiles(join(ROOT, app), ['.tsx','.ts','.css','.scss','.vue'])) {
    const rel = file.slice(ROOT.length + 1);
    if (EXEMPT.some(e => rel === e || rel.startsWith(e))) continue;
    const content = readFileSync(file, 'utf8');
    const matches = content.match(PATTERN);
    if (!matches) continue;
    byFile.set(rel, (byFile.get(rel) ?? 0) + matches.length);
    for (const m of matches) byHex.set(m.toUpperCase(), (byHex.get(m.toUpperCase()) ?? 0) + 1);
  }
}

console.log('=== TOP 30 FILES ===');
[...byFile.entries()].sort((a,b)=>b[1]-a[1]).slice(0,30).forEach(([f,n]) => console.log(`${String(n).padStart(5)}  ${f}`));
console.log('\n=== BY HEX ===');
[...byHex.entries()].sort((a,b)=>b[1]-a[1]).forEach(([h,n]) => console.log(`${String(n).padStart(5)}  ${h}`));
console.log('\n=== TOTAL ===');
console.log([...byFile.values()].reduce((a,b)=>a+b,0));
console.log('=== FILES WITH VIOLATIONS ===');
console.log(byFile.size);
