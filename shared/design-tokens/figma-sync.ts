#!/usr/bin/env ts-node
/**
 * Figma Variables → 屯象OS Design Token 同步脚本
 *
 * 用法:
 *   FIGMA_FILE_KEY=xxx FIGMA_ACCESS_TOKEN=yyy npx ts-node shared/design-tokens/figma-sync.ts
 *
 * 流程:
 *   1. 调用 Figma REST API 拉取 Variables
 *   2. 按 Collection 分组 + 解析 Mode（light/dark）
 *   3. 映射为屯象 Token 命名规范
 *   4. 输出到各终端目标格式
 */

import * as fs from 'fs';
import * as path from 'path';
import { defaultConfig, type FigmaSyncConfig, type OutputTarget } from './figma-sync.config';

// ── Figma API 类型 ──

interface FigmaVariable {
  id: string;
  name: string;
  resolvedType: 'COLOR' | 'FLOAT' | 'STRING' | 'BOOLEAN';
  valuesByMode: Record<string, FigmaVariableValue>;
}

interface FigmaColorValue {
  r: number;
  g: number;
  b: number;
  a: number;
}

type FigmaVariableValue = FigmaColorValue | number | string | boolean;

interface FigmaCollection {
  id: string;
  name: string;
  modes: Array<{ modeId: string; name: string }>;
}

interface FigmaVariablesResponse {
  meta: {
    variableCollections: Record<string, FigmaCollection>;
    variables: Record<string, FigmaVariable>;
  };
}

// ── Token 转换 ──

interface DesignToken {
  name: string;          // 如 "brand/primary"
  cssVar: string;        // 如 "--tx-primary"
  values: {
    light: string;
    dark: string;
  };
  type: 'color' | 'dimension' | 'string';
}

function figmaNameToCssVar(name: string): string {
  // "brand/primary" → "--tx-primary"
  // "semantic/success" → "--tx-success"
  // "neutral/text-1" → "--tx-text-1"
  const parts = name.split('/');
  const token = parts[parts.length - 1]
    .replace(/([A-Z])/g, '-$1')
    .toLowerCase()
    .replace(/^-/, '');
  return `--tx-${token}`;
}

function figmaColorToHex(color: FigmaColorValue): string {
  const r = Math.round(color.r * 255);
  const g = Math.round(color.g * 255);
  const b = Math.round(color.b * 255);
  if (color.a < 1) {
    return `rgba(${r}, ${g}, ${b}, ${color.a.toFixed(2)})`;
  }
  return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`.toUpperCase();
}

function resolveValue(value: FigmaVariableValue, type: string): string {
  if (type === 'COLOR' && typeof value === 'object' && 'r' in value) {
    return figmaColorToHex(value);
  }
  if (type === 'FLOAT' && typeof value === 'number') {
    return `${value}px`;
  }
  return String(value);
}

// ── 输出生成器 ──

function generateCssVariables(tokens: DesignToken[], mode: 'light' | 'dark'): string {
  const lines = tokens.map(t => `  ${t.cssVar}: ${t.values[mode]};`);
  return `/* Auto-generated from Figma — DO NOT EDIT MANUALLY */\n/* Run: npx ts-node shared/design-tokens/figma-sync.ts */\n\n:root[data-theme="${mode}"] {\n${lines.join('\n')}\n}\n`;
}

function generateTsObject(tokens: DesignToken[]): string {
  const lightEntries = tokens
    .filter(t => t.type === 'color')
    .map(t => {
      const key = t.cssVar.replace('--tx-', '').replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      return `  ${key}: '${t.values.light}',`;
    });

  return `/* Auto-generated from Figma — DO NOT EDIT MANUALLY */\nimport type { ThemeConfig } from 'antd';\n\nexport const figmaTokens = {\n${lightEntries.join('\n')}\n};\n\n/** Ant Design 5.x ConfigProvider 主题（从 Figma Token 生成） */\nexport const txAdminTheme: ThemeConfig = {\n  token: {\n    colorPrimary: figmaTokens.primary || '#FF6B35',\n    colorSuccess: figmaTokens.success || '#0F6E56',\n    colorWarning: figmaTokens.warning || '#BA7517',\n    colorError: figmaTokens.danger || '#A32D2D',\n    colorInfo: figmaTokens.info || '#185FA5',\n    colorTextBase: figmaTokens.text1 || '#2C2C2A',\n    colorBgBase: figmaTokens.bg1 || '#FFFFFF',\n    borderRadius: 6,\n    fontSize: 14,\n  },\n  components: {\n    Layout: { headerBg: figmaTokens.navy || '#1E2A3A', siderBg: figmaTokens.navy || '#1E2A3A' },\n    Menu: { darkItemBg: figmaTokens.navy || '#1E2A3A', darkItemSelectedBg: figmaTokens.primary || '#FF6B35' },\n    Table: { headerBg: figmaTokens.bg2 || '#F8F7F5' },\n  },\n};\n`;
}

function generateScssVariables(tokens: DesignToken[]): string {
  const lines = tokens.map(t => {
    const name = t.cssVar.replace('--', '$');
    return `${name}: ${t.values.light};`;
  });
  return `// Auto-generated from Figma — DO NOT EDIT MANUALLY\n// Run: npx ts-node shared/design-tokens/figma-sync.ts\n\n${lines.join('\n')}\n`;
}

function generateJson(tokens: DesignToken[]): string {
  const obj: Record<string, { light: string; dark: string; type: string }> = {};
  for (const t of tokens) {
    obj[t.name] = { light: t.values.light, dark: t.values.dark, type: t.type };
  }
  return JSON.stringify(obj, null, 2) + '\n';
}

// ── 主流程 ──

async function fetchFigmaVariables(config: FigmaSyncConfig): Promise<FigmaVariablesResponse> {
  const url = `https://api.figma.com/v1/files/${config.fileKey}/variables/local`;
  const resp = await fetch(url, {
    headers: { 'X-Figma-Token': config.accessToken },
  });
  if (!resp.ok) {
    throw new Error(`Figma API error: ${resp.status} ${resp.statusText}`);
  }
  return resp.json() as Promise<FigmaVariablesResponse>;
}

function parseVariables(data: FigmaVariablesResponse, collectionNames: string[]): DesignToken[] {
  const collections = Object.values(data.meta.variableCollections)
    .filter(c => collectionNames.includes(c.name));

  const tokens: DesignToken[] = [];

  for (const collection of collections) {
    const lightMode = collection.modes.find(m => m.name.toLowerCase().includes('light'));
    const darkMode = collection.modes.find(m => m.name.toLowerCase().includes('dark'));
    const defaultMode = collection.modes[0];

    const variables = Object.values(data.meta.variables)
      .filter(v => {
        const modeIds = Object.keys(v.valuesByMode);
        return modeIds.some(id => collection.modes.some(m => m.modeId === id));
      });

    for (const variable of variables) {
      const lightModeId = lightMode?.modeId || defaultMode.modeId;
      const darkModeId = darkMode?.modeId || defaultMode.modeId;

      const lightValue = variable.valuesByMode[lightModeId];
      const darkValue = variable.valuesByMode[darkModeId] || lightValue;

      if (lightValue === undefined) continue;

      tokens.push({
        name: variable.name,
        cssVar: figmaNameToCssVar(variable.name),
        values: {
          light: resolveValue(lightValue, variable.resolvedType),
          dark: resolveValue(darkValue, variable.resolvedType),
        },
        type: variable.resolvedType === 'COLOR' ? 'color'
            : variable.resolvedType === 'FLOAT' ? 'dimension'
            : 'string',
      });
    }
  }

  return tokens;
}

function writeOutput(tokens: DesignToken[], output: OutputTarget, rootDir: string): void {
  const filePath = path.join(rootDir, output.outputPath);
  const dir = path.dirname(filePath);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }

  let content: string;
  switch (output.format) {
    case 'css-variables':
      content = generateCssVariables(tokens, 'light') + '\n' + generateCssVariables(tokens, 'dark');
      break;
    case 'ts-object':
      content = generateTsObject(tokens);
      break;
    case 'scss-variables':
      content = generateScssVariables(tokens);
      break;
    case 'json':
      content = generateJson(tokens);
      break;
  }

  fs.writeFileSync(filePath, content, 'utf-8');
  console.log(`✓ Written: ${output.outputPath} (${tokens.length} tokens)`);
}

// ── CLI ──

async function main() {
  const config = defaultConfig;
  const rootDir = path.resolve(__dirname, '../..');

  if (!config.fileKey || !config.accessToken) {
    console.log('⚠ No FIGMA_FILE_KEY or FIGMA_ACCESS_TOKEN — generating from fallback tokens.');
    console.log('  Set environment variables to enable live Figma sync.');
    console.log('  Generating from canonical token definitions...\n');

    // 使用本地 tokens.json 作为 fallback
    const fallbackPath = path.join(__dirname, 'tokens.json');
    if (fs.existsSync(fallbackPath)) {
      const raw = JSON.parse(fs.readFileSync(fallbackPath, 'utf-8'));
      const tokens: DesignToken[] = Object.entries(raw).map(([name, val]: [string, any]) => ({
        name,
        cssVar: figmaNameToCssVar(name),
        values: { light: val.light, dark: val.dark },
        type: val.type,
      }));
      for (const output of config.outputs) {
        writeOutput(tokens, output, rootDir);
      }
    } else {
      console.log('  No tokens.json found. Run with Figma credentials first, or create tokens.json manually.');
    }
    return;
  }

  console.log('🔄 Fetching variables from Figma...');
  const data = await fetchFigmaVariables(config);
  const tokens = parseVariables(data, config.collections);
  console.log(`  Found ${tokens.length} tokens\n`);

  for (const output of config.outputs) {
    writeOutput(tokens, output, rootDir);
  }

  console.log('\n✅ Figma token sync complete!');
}

main().catch(err => {
  console.error('❌ Figma sync failed:', err.message);
  process.exit(1);
});
