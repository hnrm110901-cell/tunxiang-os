/**
 * WorkbenchPage.tsx — Stripe Workbench 风格 SRE 命令行工作台
 * 全屏终端模拟器，支持命令补全、历史、表格输出、进度条
 */
import { useState, useRef, useEffect, useCallback, useMemo } from 'react';

/* ═══════════════════════════════════════════════════════════════
   色板
   ═══════════════════════════════════════════════════════════════ */
const C = {
  bg: '#0A1418', surface: '#0E1E24', surface2: '#132932', surface3: '#1A3540',
  border: '#1A3540', border2: '#23485a',
  text: '#E6EDF1', text2: '#94A8B3', text3: '#647985',
  orange: '#FF6B2C', green: '#22C55E', yellow: '#F59E0B', red: '#EF4444', blue: '#3B82F6', purple: '#A855F7',
};

const MONO = "ui-monospace, 'SF Mono', Menlo, Consolas, monospace";

/* ═══════════════════════════════════════════════════════════════
   输出行类型
   ═══════════════════════════════════════════════════════════════ */
type OutputLine =
  | { type: 'command'; text: string }
  | { type: 'text'; text: string; color?: string }
  | { type: 'table'; headers: string[]; rows: string[][]; statusCol?: number }
  | { type: 'kv'; pairs: { key: string; value: string; color?: string }[] }
  | { type: 'json'; data: unknown }
  | { type: 'progress'; label: string; done: boolean }
  | { type: 'divider' }
  | { type: 'blank' };

/* ═══════════════════════════════════════════════════════════════
   命令定义树
   ═══════════════════════════════════════════════════════════════ */
interface CmdDef {
  description: string;
  flags?: string[];
  exec: (args: string[], flags: Record<string, string>) => OutputLine[] | Promise<OutputLine[]>;
}

const COMMAND_TREE: Record<string, Record<string, CmdDef>> = {
  edges: {
    list: {
      description: '列出边缘节点',
      flags: ['--status'],
      exec: (_, flags) => {
        const nodes = [
          { sn: 'MM-A001', store: '徐记万达店', status: 'online', lat: '4ms', ver: 'v2.8.1' },
          { sn: 'MM-A002', store: '徐记天河店', status: 'online', lat: '8ms', ver: 'v2.8.1' },
          { sn: 'MM-A003', store: '徐记IFS店', status: 'online', lat: '12ms', ver: 'v2.8.0' },
          { sn: 'MM-B001', store: '最黔线五一店', status: 'online', lat: '6ms', ver: 'v2.8.1' },
          { sn: 'MM-B002', store: '最黔线河西店', status: 'offline', lat: '-', ver: 'v2.7.9' },
          { sn: 'MM-C001', store: '尚宫厨开福店', status: 'online', lat: '5ms', ver: 'v2.8.1' },
          { sn: 'MM-C002', store: '尚宫厨岳麓店', status: 'updating', lat: '15ms', ver: 'v2.8.0' },
          { sn: 'MM-D001', store: '尝在一起总店', status: 'online', lat: '3ms', ver: 'v2.8.1' },
          { sn: 'MM-D002', store: '尝在一起二店', status: 'online', lat: '7ms', ver: 'v2.8.1' },
          { sn: 'MM-D003', store: '尝在一起三店', status: 'warning', lat: '89ms', ver: 'v2.7.9' },
        ];
        const statusFilter = flags['--status'];
        const filtered = statusFilter ? nodes.filter(n => n.status === statusFilter) : nodes;
        return [{
          type: 'table' as const,
          headers: ['SN', 'Store', 'Status', 'Latency', 'Version'],
          rows: filtered.map(n => [n.sn, n.store, n.status, n.lat, n.ver]),
          statusCol: 2,
        }];
      },
    },
    wake: {
      description: '唤醒节点',
      exec: async (args) => {
        const sn = args[0] || '<missing>';
        return [
          { type: 'progress', label: `Waking ${sn}...`, done: false },
          { type: 'progress', label: `Waking ${sn}...`, done: true },
          { type: 'text', text: `Node ${sn} wake signal sent. ETA: ~30s`, color: C.green },
        ];
      },
    },
    reboot: {
      description: '重启节点',
      exec: async (args) => {
        const sn = args[0] || '<missing>';
        return [
          { type: 'progress', label: `Rebooting ${sn}...`, done: false },
          { type: 'progress', label: `Rebooting ${sn}...`, done: true },
          { type: 'text', text: `Node ${sn} reboot initiated. ETA: ~2min`, color: C.yellow },
        ];
      },
    },
    push: {
      description: '推送更新',
      flags: ['--version'],
      exec: async (args, flags) => {
        const sn = args[0] || '<missing>';
        const ver = flags['--version'] || 'latest';
        return [
          { type: 'progress', label: `Pushing ${ver} to ${sn}...`, done: false },
          { type: 'progress', label: `Pushing ${ver} to ${sn}...`, done: true },
          { type: 'text', text: `Version ${ver} deployed to ${sn}`, color: C.green },
        ];
      },
    },
  },
  services: {
    list: {
      description: '列出微服务',
      exec: () => {
        const svcs = [
          { name: 'tx-trade', status: 'healthy', p95: '23ms', uptime: '99.97%' },
          { name: 'tx-menu', status: 'healthy', p95: '12ms', uptime: '99.99%' },
          { name: 'tx-member', status: 'healthy', p95: '18ms', uptime: '99.95%' },
          { name: 'tx-growth', status: 'healthy', p95: '15ms', uptime: '99.98%' },
          { name: 'tx-ops', status: 'degraded', p95: '67ms', uptime: '99.82%' },
          { name: 'tx-supply', status: 'healthy', p95: '21ms', uptime: '99.96%' },
          { name: 'tx-finance', status: 'healthy', p95: '19ms', uptime: '99.97%' },
          { name: 'tx-agent', status: 'healthy', p95: '45ms', uptime: '99.93%' },
          { name: 'tx-analytics', status: 'healthy', p95: '34ms', uptime: '99.94%' },
          { name: 'tx-brain', status: 'healthy', p95: '128ms', uptime: '99.91%' },
          { name: 'tx-intel', status: 'healthy', p95: '28ms', uptime: '99.96%' },
          { name: 'tx-org', status: 'healthy', p95: '16ms', uptime: '99.98%' },
          { name: 'tx-civic', status: 'healthy', p95: '14ms', uptime: '99.99%' },
          { name: 'gateway', status: 'healthy', p95: '8ms', uptime: '99.99%' },
        ];
        return [{
          type: 'table' as const,
          headers: ['Service', 'Status', 'P95', 'Uptime'],
          rows: svcs.map(s => [s.name, s.status, s.p95, s.uptime]),
          statusCol: 1,
        }];
      },
    },
    health: {
      description: '查看服务健康',
      exec: (args) => {
        const name = args[0] || 'tx-trade';
        const healthy = name !== 'tx-ops';
        return [{
          type: 'kv' as const,
          pairs: [
            { key: 'Service', value: name },
            { key: 'Status', value: healthy ? 'healthy' : 'degraded', color: healthy ? C.green : C.yellow },
            { key: 'P95', value: healthy ? '23ms' : '67ms' },
            { key: 'P99', value: healthy ? '45ms' : '142ms' },
            { key: 'SLO', value: healthy ? '99.95% (budget: 42min remaining)' : '99.80% (budget: 12min remaining)', color: healthy ? C.green : C.yellow },
            { key: 'Instances', value: '3/3 running' },
            { key: 'Last Deploy', value: '2026-04-25 14:32 UTC' },
          ],
        }];
      },
    },
    slos: {
      description: '查看 SLO',
      exec: (args) => {
        const name = args[0] || 'tx-trade';
        return [
          { type: 'text' as const, text: `SLO Report: ${name}`, color: C.blue },
          { type: 'divider' as const },
          {
            type: 'table' as const,
            headers: ['Metric', 'Target', 'Current', '30d Budget'],
            rows: [
              ['Availability', '99.95%', '99.97%', '21.6min / 42min used'],
              ['Latency P99', '<200ms', '45ms', 'OK'],
              ['Error Rate', '<0.1%', '0.03%', 'OK'],
            ],
            statusCol: -1,
          },
        ];
      },
    },
  },
  customers: {
    list: {
      description: '列出客户',
      flags: ['--tier'],
      exec: (_, flags) => {
        const custs = [
          { id: 'tx-9001', name: '徐记海鲜', tier: 'A', stores: 42, health: 92 },
          { id: 'tx-9002', name: '最黔线', tier: 'B', stores: 8, health: 87 },
          { id: 'tx-9003', name: '尚宫厨', tier: 'B', stores: 5, health: 84 },
          { id: 'tx-9004', name: '尝在一起', tier: 'A', stores: 15, health: 91 },
          { id: 'tx-9005', name: '湘味轩', tier: 'C', stores: 3, health: 76 },
          { id: 'tx-9006', name: '味千拉面长沙', tier: 'B', stores: 12, health: 82 },
        ];
        const tierFilter = flags['--tier'];
        const filtered = tierFilter ? custs.filter(c => c.tier === tierFilter) : custs;
        return [{
          type: 'table' as const,
          headers: ['ID', 'Name', 'Tier', 'Stores', 'Health'],
          rows: filtered.map(c => [c.id, c.name, c.tier, String(c.stores), String(c.health)]),
          statusCol: -1,
        }];
      },
    },
    health: {
      description: '查看健康分',
      exec: (args) => {
        const id = args[0] || 'tx-9001';
        return [
          { type: 'text' as const, text: `Customer Health: ${id}`, color: C.blue },
          { type: 'divider' as const },
          {
            type: 'kv' as const,
            pairs: [
              { key: 'Overall Score', value: '92/100', color: C.green },
              { key: 'System Uptime', value: '99.97% — Excellent', color: C.green },
              { key: 'Data Freshness', value: 'Last sync 3s ago', color: C.green },
              { key: 'SLA Compliance', value: '100% — 0 breaches in 30d', color: C.green },
              { key: 'Edge Health', value: '41/42 online (1 updating)', color: C.yellow },
              { key: 'Open Incidents', value: '1 (P2)', color: C.yellow },
            ],
          },
        ];
      },
    },
  },
  incidents: {
    list: {
      description: '列出 Incident',
      flags: ['--status'],
      exec: (_, flags) => {
        const incs = [
          { id: 'INC-2026-041', title: 'tx-ops P95 spike', priority: 'P2', status: 'active', age: '2h' },
          { id: 'INC-2026-040', title: 'MM-B002 offline', priority: 'P3', status: 'active', age: '6h' },
          { id: 'INC-2026-039', title: 'Payment timeout burst', priority: 'P1', status: 'resolved', age: '1d' },
          { id: 'INC-2026-038', title: 'KDS push delay', priority: 'P3', status: 'resolved', age: '2d' },
        ];
        const statusFilter = flags['--status'];
        const filtered = statusFilter ? incs.filter(i => i.status === statusFilter) : incs;
        return [{
          type: 'table' as const,
          headers: ['ID', 'Title', 'Priority', 'Status', 'Age'],
          rows: filtered.map(i => [i.id, i.title, i.priority, i.status, i.age]),
          statusCol: 3,
        }];
      },
    },
    declare: {
      description: '声明 Incident',
      flags: ['--title', '--priority'],
      exec: async (_, flags) => {
        const title = flags['--title'] || 'Untitled Incident';
        const priority = flags['--priority'] || 'P2';
        return [
          { type: 'progress' as const, label: 'Declaring incident...', done: false },
          { type: 'progress' as const, label: 'Declaring incident...', done: true },
          { type: 'text' as const, text: `Incident INC-2026-043 已声明`, color: C.green },
          { type: 'kv' as const, pairs: [
            { key: 'ID', value: 'INC-2026-043' },
            { key: 'Title', value: title },
            { key: 'Priority', value: priority, color: priority === 'P0' ? C.red : C.yellow },
            { key: 'Status', value: 'active', color: C.orange },
            { key: 'Commander', value: '未了已 (auto-assigned)' },
          ]},
        ];
      },
    },
  },
  adapters: {
    list: {
      description: '列出适配器',
      exec: () => [{
        type: 'table' as const,
        headers: ['ID', 'Name', 'Type', 'Status', 'Last Sync'],
        rows: [
          ['adp-001', '品智POS', 'pos', 'connected', '2s ago'],
          ['adp-002', '奥琦玮', 'pos', 'connected', '5s ago'],
          ['adp-003', '美团外卖', 'delivery', 'connected', '1s ago'],
          ['adp-004', '饿了么', 'delivery', 'connected', '3s ago'],
          ['adp-005', '抖音本地生活', 'platform', 'degraded', '45s ago'],
          ['adp-006', '天财商龙', 'legacy', 'connected', '8s ago'],
          ['adp-007', '微信支付', 'payment', 'connected', '<1s ago'],
          ['adp-008', '支付宝', 'payment', 'connected', '<1s ago'],
        ],
        statusCol: 3,
      }],
    },
    sync: {
      description: '手动同步',
      exec: async (args) => {
        const id = args[0] || 'adp-001';
        return [
          { type: 'progress' as const, label: `Syncing ${id}...`, done: false },
          { type: 'progress' as const, label: `Syncing ${id}...`, done: true },
          { type: 'text' as const, text: `Adapter ${id} sync completed. 0 conflicts.`, color: C.green },
        ];
      },
    },
  },
  migrations: {
    list: {
      description: '列出迁移',
      exec: () => [{
        type: 'table' as const,
        headers: ['ID', 'Customer', 'Phase', 'Progress', 'ETA'],
        rows: [
          ['mig-001', '徐记海鲜', 'Phase 3: Data Migration', '68%', '2026-05-15'],
          ['mig-002', '最黔线', 'Phase 2: Parallel Run', '45%', '2026-06-01'],
          ['mig-003', '尚宫厨', 'Phase 1: Assessment', '20%', '2026-07-01'],
          ['mig-004', '尝在一起', 'Phase 4: Cutover', '92%', '2026-04-30'],
        ],
        statusCol: -1,
      }],
    },
    advance: {
      description: '推进阶段',
      exec: async (args) => {
        const id = args[0] || 'mig-001';
        return [
          { type: 'progress' as const, label: `Advancing ${id}...`, done: false },
          { type: 'progress' as const, label: `Advancing ${id}...`, done: true },
          { type: 'text' as const, text: `Migration ${id} advanced to next phase`, color: C.green },
        ];
      },
    },
  },
  playbooks: {
    list: {
      description: '列出剧本',
      exec: () => [{
        type: 'table' as const,
        headers: ['ID', 'Name', 'Type', 'Last Run', 'Success Rate'],
        rows: [
          ['pb-001', 'Edge Recovery', 'auto', '2h ago', '98%'],
          ['pb-002', 'Service Rollback', 'manual', '1d ago', '100%'],
          ['pb-003', 'Incident Triage', 'auto', '6h ago', '95%'],
          ['pb-004', 'Customer Onboard', 'manual', '3d ago', '100%'],
          ['pb-005', 'DB Failover', 'manual', 'never', '-'],
          ['pb-006', 'Peak Hour Scale-up', 'auto', '12h ago', '97%'],
        ],
        statusCol: -1,
      }],
    },
    run: {
      description: '触发剧本',
      flags: ['--target'],
      exec: async (args, flags) => {
        const id = args[0] || 'pb-001';
        const target = flags['--target'] || 'default';
        return [
          { type: 'progress' as const, label: `Running playbook ${id} on ${target}...`, done: false },
          { type: 'progress' as const, label: `Running playbook ${id} on ${target}...`, done: true },
          { type: 'text' as const, text: `Playbook ${id} completed on ${target}. All steps passed.`, color: C.green },
        ];
      },
    },
  },
  flags: {
    list: {
      description: '列出开关',
      exec: () => [{
        type: 'table' as const,
        headers: ['Name', 'Value', 'Scope', 'Updated'],
        rows: [
          ['enable_ai_discount_guard', 'true', 'global', '2026-04-20'],
          ['enable_crdt_sync', 'true', 'global', '2026-04-18'],
          ['enable_new_kds_layout', 'false', 'edge', '2026-04-22'],
          ['enable_voice_ordering', 'true', 'pilot:tx-9004', '2026-04-25'],
          ['enable_auto_scaling', 'true', 'global', '2026-04-15'],
          ['dark_launch_private_domain', 'false', 'global', '2026-04-26'],
        ],
        statusCol: -1,
      }],
    },
    set: {
      description: '设置开关',
      flags: ['--value'],
      exec: async (args, flags) => {
        const name = args[0] || '<missing>';
        const value = flags['--value'] || 'true';
        return [
          { type: 'progress' as const, label: `Setting ${name}=${value}...`, done: false },
          { type: 'progress' as const, label: `Setting ${name}=${value}...`, done: true },
          { type: 'text' as const, text: `Flag ${name} set to ${value}`, color: C.green },
        ];
      },
    },
  },
};

/* ═══════════════════════════════════════════════════════════════
   命令补全
   ═══════════════════════════════════════════════════════════════ */
function getCompletions(input: string): string[] {
  const parts = input.trim().split(/\s+/);
  if (parts[0] !== 'tx') {
    if ('tx'.startsWith(input.trim())) return ['tx'];
    return [];
  }
  if (parts.length <= 1) {
    // after "tx", suggest resources
    return [...Object.keys(COMMAND_TREE), 'help', 'clear'].map(k => `tx ${k}`);
  }
  const resource = parts[1];
  if (parts.length === 2) {
    // partial resource match
    const matches = [...Object.keys(COMMAND_TREE), 'help', 'clear']
      .filter(k => k.startsWith(resource));
    return matches.map(k => `tx ${k}`);
  }
  // suggest actions
  const tree = COMMAND_TREE[resource];
  if (!tree) return [];
  const action = parts[2];
  if (parts.length === 3) {
    const matches = Object.keys(tree).filter(k => k.startsWith(action));
    return matches.map(k => `tx ${resource} ${k}`);
  }
  // suggest flags
  const cmd = tree[action];
  if (!cmd || !cmd.flags) return [];
  const last = parts[parts.length - 1];
  if (last.startsWith('-')) {
    return cmd.flags.filter(f => f.startsWith(last));
  }
  return [];
}

/* ═══════════════════════════════════════════════════════════════
   帮助命令
   ═══════════════════════════════════════════════════════════════ */
function helpOutput(): OutputLine[] {
  const lines: OutputLine[] = [
    { type: 'text', text: 'Available commands:', color: C.blue },
    { type: 'blank' },
  ];
  for (const [resource, actions] of Object.entries(COMMAND_TREE)) {
    for (const [action, def] of Object.entries(actions)) {
      const flagStr = def.flags ? ` ${def.flags.join(' ')}` : '';
      lines.push({
        type: 'text',
        text: `  tx ${resource} ${action}${flagStr}`,
        color: C.text2,
      });
      lines.push({
        type: 'text',
        text: `      ${def.description}`,
        color: C.text3,
      });
    }
  }
  lines.push({ type: 'blank' });
  lines.push({ type: 'text', text: '  tx help          显示帮助', color: C.text2 });
  lines.push({ type: 'text', text: '  tx clear         清屏', color: C.text2 });
  return lines;
}

/* ═══════════════════════════════════════════════════════════════
   命令解析与执行
   ═══════════════════════════════════════════════════════════════ */
function parseFlags(tokens: string[]): { args: string[]; flags: Record<string, string> } {
  const args: string[] = [];
  const flags: Record<string, string> = {};
  let i = 0;
  while (i < tokens.length) {
    if (tokens[i].startsWith('--')) {
      const key = tokens[i];
      // handle quoted values: --title "some thing"
      if (i + 1 < tokens.length) {
        flags[key] = tokens[i + 1];
        i += 2;
      } else {
        flags[key] = 'true';
        i++;
      }
    } else {
      args.push(tokens[i]);
      i++;
    }
  }
  return { args, flags };
}

async function executeCommand(input: string): Promise<{ lines: OutputLine[]; clear?: boolean }> {
  const trimmed = input.trim();
  if (!trimmed) return { lines: [] };

  // tokenize respecting quotes
  const tokens: string[] = [];
  let current = '';
  let inQuote = false;
  let quoteChar = '';
  for (const ch of trimmed) {
    if (inQuote) {
      if (ch === quoteChar) { inQuote = false; } else { current += ch; }
    } else if (ch === '"' || ch === "'") {
      inQuote = true; quoteChar = ch;
    } else if (ch === ' ') {
      if (current) { tokens.push(current); current = ''; }
    } else {
      current += ch;
    }
  }
  if (current) tokens.push(current);

  if (tokens[0] !== 'tx') {
    return {
      lines: [
        { type: 'text', text: `Unknown command: ${tokens[0]}`, color: C.red },
        { type: 'text', text: `Did you mean: tx ${tokens[0]}?`, color: C.text3 },
      ],
    };
  }

  const resource = tokens[1];
  if (!resource) {
    return { lines: [{ type: 'text', text: "Usage: tx <resource> <action> [args] [--flags]", color: C.text3 }] };
  }

  if (resource === 'help') return { lines: helpOutput() };
  if (resource === 'clear') return { lines: [], clear: true };

  const tree = COMMAND_TREE[resource];
  if (!tree) {
    const suggestions = Object.keys(COMMAND_TREE).filter(k => k.startsWith(resource.slice(0, 2)));
    return {
      lines: [
        { type: 'text', text: `Unknown resource: ${resource}`, color: C.red },
        ...(suggestions.length > 0
          ? [{ type: 'text' as const, text: `Did you mean: ${suggestions.join(', ')}?`, color: C.text3 }]
          : [{ type: 'text' as const, text: "Type 'tx help' for available commands", color: C.text3 }]),
      ],
    };
  }

  const action = tokens[2];
  if (!action) {
    const actions = Object.keys(tree);
    return {
      lines: [
        { type: 'text', text: `Available actions for '${resource}':`, color: C.blue },
        ...actions.map(a => ({ type: 'text' as const, text: `  tx ${resource} ${a}  — ${tree[a].description}`, color: C.text2 })),
      ],
    };
  }

  const cmd = tree[action];
  if (!cmd) {
    const suggestions = Object.keys(tree).filter(k => k.startsWith(action.slice(0, 2)));
    return {
      lines: [
        { type: 'text', text: `Unknown action: ${resource} ${action}`, color: C.red },
        ...(suggestions.length > 0
          ? [{ type: 'text' as const, text: `Did you mean: ${suggestions.join(', ')}?`, color: C.text3 }]
          : []),
      ],
    };
  }

  const rest = tokens.slice(3);
  const { args, flags } = parseFlags(rest);
  const result = cmd.exec(args, flags);
  const lines = result instanceof Promise ? await result : result;
  return { lines };
}

/* ═══════════════════════════════════════════════════════════════
   渲染组件
   ═══════════════════════════════════════════════════════════════ */

function statusColor(s: string): string {
  const lower = s.toLowerCase();
  if (['online', 'healthy', 'connected', 'active', 'true', 'resolved'].includes(lower)) return C.green;
  if (['offline', 'error', 'false'].includes(lower)) return C.red;
  if (['warning', 'degraded', 'updating'].includes(lower)) return C.yellow;
  return C.text;
}

function RenderTable({ line }: { line: Extract<OutputLine, { type: 'table' }> }) {
  const { headers, rows, statusCol } = line;
  const allRows = [headers, ...rows];
  const colWidths = headers.map((_, ci) =>
    Math.max(...allRows.map(r => (r[ci] || '').length))
  );

  const pad = (s: string, w: number) => s + ' '.repeat(Math.max(0, w - s.length));
  const sep = colWidths.map(w => '\u2500'.repeat(w + 2)).join('\u253C');

  return (
    <div style={{ fontFamily: MONO, fontSize: 13, lineHeight: 1.6 }}>
      <div style={{ color: C.text3 }}>{'\u250C' + colWidths.map(w => '\u2500'.repeat(w + 2)).join('\u252C') + '\u2510'}</div>
      <div>
        {'\u2502'}
        {headers.map((h, ci) => (
          <span key={ci}>
            <span style={{ color: C.blue, fontWeight: 600 }}> {pad(h, colWidths[ci])} </span>
            {ci < headers.length - 1 ? '\u2502' : ''}
          </span>
        ))}
        {'\u2502'}
      </div>
      <div style={{ color: C.text3 }}>{'\u251C' + sep + '\u2524'}</div>
      {rows.map((row, ri) => (
        <div key={ri}>
          {'\u2502'}
          {row.map((cell, ci) => {
            const clr = ci === statusCol ? statusColor(cell) : C.text;
            return (
              <span key={ci}>
                <span style={{ color: clr }}> {pad(cell, colWidths[ci])} </span>
                {ci < row.length - 1 ? '\u2502' : ''}
              </span>
            );
          })}
          {'\u2502'}
        </div>
      ))}
      <div style={{ color: C.text3 }}>{'\u2514' + colWidths.map(w => '\u2500'.repeat(w + 2)).join('\u2534') + '\u2518'}</div>
    </div>
  );
}

function RenderKV({ line }: { line: Extract<OutputLine, { type: 'kv' }> }) {
  const maxKey = Math.max(...line.pairs.map(p => p.key.length));
  return (
    <div style={{ fontFamily: MONO, fontSize: 13, lineHeight: 1.8 }}>
      {line.pairs.map((p, i) => (
        <div key={i}>
          <span style={{ color: C.text2 }}>{p.key.padEnd(maxKey + 2)}</span>
          <span style={{ color: p.color || C.text }}>{p.value}</span>
        </div>
      ))}
    </div>
  );
}

function RenderJson({ data }: { data: unknown }) {
  const colorize = (s: string): React.ReactNode[] => {
    const parts: React.ReactNode[] = [];
    // simple line-based colorizing
    const lines = JSON.stringify(data, null, 2).split('\n');
    lines.forEach((ln, li) => {
      const colored = ln
        .replace(/"([^"]+)":/g, `\x01"$1"\x02:`)
        .replace(/: "([^"]*)"/g, `: \x03"$1"\x04`)
        .replace(/: (\d+)/g, `: \x05$1\x06`);
      const segs: React.ReactNode[] = [];
      let buf = '';
      let ci = 0;
      for (let i = 0; i < colored.length; i++) {
        const ch = colored[i];
        if (ch === '\x01') { if (buf) segs.push(<span key={`${li}-${ci++}`} style={{ color: C.text3 }}>{buf}</span>); buf = ''; }
        else if (ch === '\x02') { segs.push(<span key={`${li}-${ci++}`} style={{ color: C.blue }}>{buf}</span>); buf = ''; }
        else if (ch === '\x03') { if (buf) segs.push(<span key={`${li}-${ci++}`} style={{ color: C.text3 }}>{buf}</span>); buf = ''; }
        else if (ch === '\x04') { segs.push(<span key={`${li}-${ci++}`} style={{ color: C.green }}>{buf}</span>); buf = ''; }
        else if (ch === '\x05') { if (buf) segs.push(<span key={`${li}-${ci++}`} style={{ color: C.text3 }}>{buf}</span>); buf = ''; }
        else if (ch === '\x06') { segs.push(<span key={`${li}-${ci++}`} style={{ color: C.orange }}>{buf}</span>); buf = ''; }
        else { buf += ch; }
      }
      if (buf) segs.push(<span key={`${li}-${ci}`} style={{ color: C.text3 }}>{buf}</span>);
      parts.push(<div key={li}>{segs}</div>);
    });
    return parts;
  };
  return <div style={{ fontFamily: MONO, fontSize: 13, lineHeight: 1.6 }}>{colorize(JSON.stringify(data))}</div>;
}

function ProgressBar({ label, done }: { label: string; done: boolean }) {
  const [ticks, setTicks] = useState(0);
  useEffect(() => {
    if (done) return;
    const id = setInterval(() => setTicks(t => (t + 1) % 20), 80);
    return () => clearInterval(id);
  }, [done]);

  const bar = done
    ? '\u2588'.repeat(20)
    : '\u2588'.repeat(ticks) + '\u2591'.repeat(20 - ticks);

  return (
    <div style={{ fontFamily: MONO, fontSize: 13, lineHeight: 1.6 }}>
      <span style={{ color: done ? C.green : C.yellow }}>{label} </span>
      <span style={{ color: done ? C.green : C.text3 }}>[{bar}]</span>
      <span style={{ color: done ? C.green : C.text3 }}> {done ? 'done' : ''}</span>
    </div>
  );
}

function RenderLine({ line }: { line: OutputLine }) {
  switch (line.type) {
    case 'command':
      return (
        <div style={{ fontFamily: MONO, fontSize: 13, lineHeight: 1.6, color: C.text3 }}>
          $ {line.text}
        </div>
      );
    case 'text':
      return (
        <div style={{ fontFamily: MONO, fontSize: 13, lineHeight: 1.6, color: line.color || C.text, whiteSpace: 'pre-wrap' }}>
          {line.text}
        </div>
      );
    case 'table':
      return <RenderTable line={line} />;
    case 'kv':
      return <RenderKV line={line} />;
    case 'json':
      return <RenderJson data={line.data} />;
    case 'progress':
      return <ProgressBar label={line.label} done={line.done} />;
    case 'divider':
      return (
        <div style={{ fontFamily: MONO, fontSize: 13, lineHeight: 1.6, color: C.text3 }}>
          {'\u2500'.repeat(50)}
        </div>
      );
    case 'blank':
      return <div style={{ height: 13 * 1.6 }} />;
    default:
      return null;
  }
}

/* ═══════════════════════════════════════════════════════════════
   主组件
   ═══════════════════════════════════════════════════════════════ */
const WELCOME: OutputLine[] = [
  { type: 'text', text: '屯象 Workbench v2.0', color: C.orange },
  { type: 'text', text: "Type 'tx help' for available commands", color: C.text3 },
  { type: 'divider' },
  { type: 'blank' },
];

export function WorkbenchPage() {
  const [output, setOutput] = useState<OutputLine[]>(WELCOME);
  const [input, setInput] = useState('');
  const [history, setHistory] = useState<string[]>([]);
  const [historyIdx, setHistoryIdx] = useState(-1);
  const [completions, setCompletions] = useState<string[]>([]);
  const [executing, setExecuting] = useState(false);

  const outputRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // auto-scroll
  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight;
    }
  }, [output]);

  // auto-focus
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSubmit = useCallback(async () => {
    if (executing) return;
    const cmd = input.trim();
    if (!cmd) return;

    setCompletions([]);
    setInput('');
    setHistory(h => {
      const next = [cmd, ...h.filter(x => x !== cmd)].slice(0, 50);
      return next;
    });
    setHistoryIdx(-1);

    // echo command
    setOutput(prev => [...prev, { type: 'command', text: cmd }]);

    // detect if write operation (needs delay)
    const isWrite = /\b(wake|reboot|push|declare|sync|advance|run|set)\b/.test(cmd);

    setExecuting(true);
    try {
      if (isWrite) {
        // show progress first
        const result = await executeCommand(cmd);
        if (result.clear) {
          setOutput(WELCOME);
          setExecuting(false);
          return;
        }
        // separate progress lines from final lines
        const progressLines = result.lines.filter(l => l.type === 'progress' && !l.done);
        const restLines = result.lines.filter(l => !(l.type === 'progress' && !l.done));

        if (progressLines.length > 0) {
          setOutput(prev => [...prev, ...progressLines]);
          await new Promise(r => setTimeout(r, 500));
          // replace progress with done
          setOutput(prev => {
            const withoutProgress = prev.filter(l => !(l.type === 'progress' && !l.done));
            return [...withoutProgress, ...restLines];
          });
        } else {
          setOutput(prev => [...prev, ...result.lines]);
        }
      } else {
        const result = await executeCommand(cmd);
        if (result.clear) {
          setOutput(WELCOME);
          setExecuting(false);
          return;
        }
        setOutput(prev => [...prev, ...result.lines]);
      }
    } finally {
      setExecuting(false);
    }

    setOutput(prev => [...prev, { type: 'blank' }]);
  }, [input, executing]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSubmit();
      return;
    }

    if (e.key === 'Tab') {
      e.preventDefault();
      const comps = getCompletions(input);
      if (comps.length === 1) {
        setInput(comps[0] + ' ');
        setCompletions([]);
      } else if (comps.length > 1) {
        setCompletions(comps);
      }
      return;
    }

    if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (history.length === 0) return;
      const newIdx = Math.min(historyIdx + 1, history.length - 1);
      setHistoryIdx(newIdx);
      setInput(history[newIdx]);
      setCompletions([]);
      return;
    }

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (historyIdx <= 0) {
        setHistoryIdx(-1);
        setInput('');
      } else {
        const newIdx = historyIdx - 1;
        setHistoryIdx(newIdx);
        setInput(history[newIdx]);
      }
      setCompletions([]);
      return;
    }

    // clear completions on other keys
    if (completions.length > 0 && e.key !== 'Shift') {
      setCompletions([]);
    }
  }, [input, history, historyIdx, completions, handleSubmit]);

  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setInput(e.target.value);
    setHistoryIdx(-1);
  }, []);

  // click anywhere to focus input
  const handleContainerClick = useCallback(() => {
    inputRef.current?.focus();
  }, []);

  // Blinking cursor style
  const cursorKeyframes = useMemo(() => {
    const id = 'wb-cursor-blink';
    if (typeof document !== 'undefined' && !document.getElementById(id)) {
      const style = document.createElement('style');
      style.id = id;
      style.textContent = `@keyframes wb-blink { 0%,50% { opacity: 1; } 51%,100% { opacity: 0; } }`;
      document.head.appendChild(style);
    }
    return id;
  }, []);
  void cursorKeyframes;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        background: C.bg,
        fontFamily: MONO,
        cursor: 'text',
      }}
      onClick={handleContainerClick}
    >
      {/* Title bar */}
      <div style={{
        height: 40,
        minHeight: 40,
        display: 'flex',
        alignItems: 'center',
        padding: '0 16px',
        borderBottom: `1px solid ${C.border}`,
        background: C.surface,
        gap: 8,
      }}>
        <span style={{ color: C.orange, fontWeight: 700, fontSize: 13 }}>屯象 Workbench</span>
        <span style={{ color: C.text3, fontSize: 12 }}>SRE Command Center</span>
      </div>

      {/* Output area */}
      <div
        ref={outputRef}
        style={{
          flex: 1,
          overflow: 'auto',
          padding: '16px 20px',
          background: C.surface,
        }}
      >
        {output.map((line, i) => (
          <RenderLine key={i} line={line} />
        ))}
      </div>

      {/* Completions popup */}
      {completions.length > 0 && (
        <div style={{
          padding: '6px 20px',
          background: C.surface2,
          borderTop: `1px solid ${C.border}`,
          display: 'flex',
          gap: 12,
          flexWrap: 'wrap',
        }}>
          {completions.map((c, i) => (
            <span
              key={i}
              style={{
                fontSize: 12,
                color: C.text2,
                padding: '2px 8px',
                background: C.surface3,
                borderRadius: 4,
                cursor: 'pointer',
              }}
              onClick={() => {
                setInput(c + ' ');
                setCompletions([]);
                inputRef.current?.focus();
              }}
            >
              {c}
            </span>
          ))}
        </div>
      )}

      {/* Input line */}
      <div style={{
        height: 48,
        minHeight: 48,
        display: 'flex',
        alignItems: 'center',
        padding: '0 20px',
        background: C.surface2,
        borderTop: `1px solid ${C.border}`,
        gap: 8,
      }}>
        <span style={{ color: C.green, fontWeight: 700, fontSize: 13, userSelect: 'none' }}>tx&gt;</span>
        <input
          ref={inputRef}
          value={input}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          disabled={executing}
          placeholder={executing ? 'executing...' : ''}
          style={{
            flex: 1,
            background: 'transparent',
            border: 'none',
            outline: 'none',
            color: C.text,
            fontFamily: MONO,
            fontSize: 13,
            caretColor: C.green,
          }}
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="off"
          spellCheck={false}
        />
        {!executing && (
          <span style={{
            width: 8,
            height: 16,
            background: C.green,
            animation: 'wb-blink 1s step-end infinite',
            borderRadius: 1,
          }} />
        )}
      </div>
    </div>
  );
}
