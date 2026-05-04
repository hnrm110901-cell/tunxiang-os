/**
 * useCommandPalette — Cmd+K 命令面板状态机
 *
 * 键盘导航:
 *   Ctrl+K / Cmd+K → toggle 打开/关闭
 *   Escape          → 关闭
 *   ArrowDown/Up    → 上下导航
 *   Enter           → 执行选中命令 + 关闭
 *   输入             → 过滤命令列表，重置选中索引
 *
 * 触屏设备: isKeyboardDevice() 返回 false 时不挂载键盘监听
 */
import { useState, useCallback, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { isKeyboardDevice, POS_SHORTCUTS, SHORTCUT_CATEGORIES } from './useKeyboardShortcuts';
import { agentExecute } from '../api/tradeApi';
import type { ShortcutCategory } from './useKeyboardShortcuts';

// ─── 命令类型定义 ──────────────────────────────────────────────────────────────

export type CommandGroup = 'navigate' | 'action' | 'system';

export interface Command {
  id: string;
  group: CommandGroup;
  icon: string;
  title: string;
  description?: string;
  shortcut?: string;
  action: () => void;
  keywords?: string[];
}

const GROUP_LABELS: Record<CommandGroup, string> = {
  navigate: '页面导航',
  action: 'POS 操作',
  system: '系统功能',
};

const GROUP_ORDER: CommandGroup[] = ['action', 'navigate', 'system'];

// ─── 构建命令列表 ──────────────────────────────────────────────────────────────

function buildCommands(navigate: (path: string) => void): Command[] {
  const commands: Command[] = [];

  // 1. POS 快捷键命令（来自 POS_SHORTCUTS）
  for (const def of Object.values(POS_SHORTCUTS)) {
    const group: CommandGroup =
      def.category === 'dish' ? 'action' :
      (def.category as ShortcutCategory) === 'cashier' ? 'action' : 'system';
    if (def.key === 'Escape' || def.key === 'Ctrl+/') continue; // 跳过元命令
    commands.push({
      id: `shortcut-${def.key}`,
      group,
      icon: group === 'action' ? '⚡' : '⚙️',
      title: def.description,
      shortcut: def.key,
      action: () => {}, // 快捷键由 ShortcutAction handler 执行，命令面板仅触发导航
    });
  }

  // 2. 页面导航命令
  const pages: { icon: string; title: string; path: string; desc: string }[] = [
    { icon: '📊', title: '仪表盘', path: '/dashboard', desc: 'POS 主控仪表盘' },
    { icon: '🏠', title: '桌台总览', path: '/tables', desc: '桌台地图可视化' },
    { icon: '📋', title: '预订台账', path: '/reservations', desc: '预订与排队管理' },
    { icon: '💵', title: '快速收银', path: '/quick-cashier', desc: '无桌台快速收银' },
    { icon: '🧾', title: '排队管理', path: '/queue', desc: '取号/叫号/排队列表' },
    { icon: '🔄', title: '交接班', path: '/shift', desc: '开班/闭班/现金盘点' },
    { icon: '📦', title: '存酒管理', path: '/wine-storage', desc: '顾客存酒管理' },
    { icon: '💰', title: '宴会定金', path: '/banquet-deposit', desc: '宴会定金管理' },
    { icon: '🖨️', title: '打印管理', path: '/print-manager', desc: '打印队列与模板' },
    { icon: '⚙️', title: '系统设置', path: '/settings', desc: 'POS 参数配置' },
    { icon: '📈', title: '经营报表', path: '/reports', desc: 'POS 端经营报表' },
    { icon: '🍔', title: '快餐模式', path: '/fastfood', desc: '快餐平行收银' },
  ];

  for (const p of pages) {
    commands.push({
      id: `nav-${p.path.replace(/\//g, '-')}`,
      group: 'navigate',
      icon: p.icon,
      title: p.title,
      description: p.desc,
      action: () => navigate(p.path),
    });
  }

  // 3. 系统动作命令
  commands.push({
    id: 'sys-fullscreen',
    group: 'system',
    icon: '🖥️',
    title: '全屏切换',
    shortcut: 'F11',
    description: '进入/退出全屏模式',
    action: () => {
      if (document.fullscreenElement) {
        document.exitFullscreen().catch(() => {});
      } else {
        document.documentElement.requestFullscreen().catch(() => {});
      }
    },
  });

  commands.push({
    id: 'sys-lock',
    group: 'system',
    icon: '🔒',
    title: '锁屏',
    shortcut: 'Ctrl+L',
    description: '锁定 POS 终端',
    action: () => navigate('/'),
  });

  commands.push({
    id: 'sys-help',
    group: 'system',
    icon: '❓',
    title: '快捷键帮助',
    shortcut: 'Ctrl+/',
    description: '查看所有键盘快捷键',
    action: () => {}, // 由 useKeyboardShortcuts 处理
  });

  return commands;
}

// ─── 搜索过滤 ──────────────────────────────────────────────────────────────────

function filterCommands(commands: Command[], query: string): Command[] {
  if (!query.trim()) return commands;
  const q = query.toLowerCase();
  return commands.filter((cmd) => {
    const matchTitle = cmd.title.toLowerCase().includes(q);
    const matchDesc = cmd.description?.toLowerCase().includes(q);
    const matchShortcut = cmd.shortcut?.toLowerCase().includes(q);
    const matchKeywords = cmd.keywords?.some((k) => k.toLowerCase().includes(q));
    return matchTitle || matchDesc || matchShortcut || matchKeywords;
  });
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

interface UseCommandPaletteReturn {
  open: boolean;
  setOpen: (v: boolean) => void;
  toggle: () => void;
  query: string;
  setQuery: (q: string) => void;
  selectedIndex: number;
  setSelectedIndex: (i: number) => void;
  flatItems: Command[];
  groupedItems: { group: CommandGroup; label: string; items: Command[] }[];
  enabled: boolean;
  /** Phase 2: Agent 自然语言查询模式 */
  agentMode: boolean;
  agentResult: string | null;
  agentLoading: boolean;
  agentError: string | null;
  askAgent: (question: string) => void;
  clearAgentResult: () => void;
  exitAgentMode: () => void;
}

export function useCommandPalette(): UseCommandPaletteReturn {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const enabled = isKeyboardDevice();

  // Phase 2: Agent 自然语言查询状态
  const [agentMode, setAgentMode] = useState(false);
  const [agentResult, setAgentResult] = useState<string | null>(null);
  const [agentLoading, setAgentLoading] = useState(false);
  const [agentError, setAgentError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // 构建命令（navigate 稳定，不必用 useMemo）
  const commands = buildCommands(navigate);

  // 过滤
  const filtered = filterCommands(commands, query);

  // 分组 — 若查询未匹配任何命令且 >= 3 字符，追加 Agent 入口
  const showAgentEntry = !agentMode && query.trim().length >= 3 && filtered.length === 0;
  const groupedItems = GROUP_ORDER
    .filter((g) => filtered.some((c) => c.group === g))
    .map((group) => ({
      group,
      label: GROUP_LABELS[group],
      items: filtered.filter((c) => c.group === group),
    }));

  const flatItems = filtered;

  // 重置选中索引（查询变化时）
  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  // 键盘事件
  useEffect(() => {
    if (!enabled) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      const isMod = e.metaKey || e.ctrlKey;

      // Ctrl+K / Cmd+K → toggle
      if (isMod && e.key === 'k') {
        e.preventDefault();
        setOpen((prev) => {
          if (prev) return false;
          setQuery('');
          setSelectedIndex(0);
          setAgentMode(false);
          setAgentResult(null);
          setAgentError(null);
          return true;
        });
        return;
      }

      if (!open) return;

      if (e.key === 'Escape') {
        e.preventDefault();
        if (agentMode) {
          // Agent 模式下 Esc → 返回搜索
          exitAgentMode();
        } else {
          setOpen(false);
        }
        return;
      }

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIndex((i) => Math.min(i + 1, flatItems.length - 1));
        return;
      }

      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIndex((i) => Math.max(i - 1, 0));
        return;
      }

      if (e.key === 'Enter') {
        e.preventDefault();
        const cmd = flatItems[selectedIndex];
        if (cmd) {
          setTimeout(() => cmd.action(), 50);
          setOpen(false);
          setQuery('');
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown, { capture: true });
    return () => window.removeEventListener('keydown', handleKeyDown, { capture: true });
  }, [enabled, open, flatItems, selectedIndex, agentMode]);

  const toggle = useCallback(() => {
    setOpen((prev) => {
      if (prev) return false;
      setQuery('');
      setSelectedIndex(0);
      setAgentMode(false);
      setAgentResult(null);
      setAgentError(null);
      return true;
    });
  }, []);

  const askAgent = useCallback(async (question: string) => {
    setAgentMode(true);
    setAgentLoading(true);
    setAgentResult(null);
    setAgentError(null);

    try {
      const res = await agentExecute(question, {
        source: 'command_palette',
        query: question,
      });
      const data = res as Record<string, unknown>;
      setAgentResult(
        typeof data.result === 'string' ? data.result :
        typeof data.response === 'string' ? data.response :
        typeof data.message === 'string' ? data.message :
        JSON.stringify(data, null, 2),
      );
    } catch (err) {
      setAgentError(err instanceof Error ? err.message : 'Agent 暂时不可用');
    } finally {
      setAgentLoading(false);
    }
  }, []);

  const exitAgentMode = useCallback(() => {
    setAgentMode(false);
    setAgentResult(null);
    setAgentError(null);
    setQuery('');
    setSelectedIndex(0);
  }, []);

  const clearAgentResult = useCallback(() => {
    setAgentResult(null);
    setAgentError(null);
  }, []);

  return {
    open,
    setOpen,
    toggle,
    query,
    setQuery,
    selectedIndex,
    setSelectedIndex,
    flatItems,
    groupedItems,
    enabled,
    agentMode,
    agentResult,
    agentLoading,
    agentError,
    askAgent,
    clearAgentResult,
    exitAgentMode,
  };
}
