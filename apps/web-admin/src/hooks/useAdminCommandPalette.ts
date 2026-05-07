/**
 * useAdminCommandPalette — Admin 端 Cmd+K 命令面板状态管理
 *
 * 职责：
 *   - 全局键盘监听 Ctrl+K / Cmd+K 切换面板开闭
 *   - 注册可搜索命令（导航到 Top 20 页面）
 *   - 模糊搜索过滤（按 title / keywords / pinyin）
 *
 * v1.0 宪法 §5.3 + S2-03 #255 验收：
 *   全局 Cmd+K 触发 CommandPalette（Admin 端缺失，本 issue 顺带补）
 */
import { useState, useEffect, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

export interface AdminCommand {
  id: string;
  title: string;
  description?: string;
  group: 'nav' | 'action' | 'system';
  keywords?: string;
  shortcut?: string;
  to?: string; // 路由 path
  action?: () => void; // 自定义动作
}

/**
 * Admin 默认可搜索命令清单（Top 20 主流程页面 + 系统快捷键）
 * 按需在路由定义变更时同步扩展
 */
export const ADMIN_DEFAULT_COMMANDS: AdminCommand[] = [
  // ── 导航：仪表盘 / 经营 ──────────────────────────────────────
  { id: 'nav-dashboard', title: '经营驾驶舱', group: 'nav', to: '/dashboard',
    keywords: 'jingying jiashicang dashboard 仪表盘 首页 总览' },
  { id: 'nav-hq-dashboard', title: '总部驾驶舱（HQ）', group: 'nav', to: '/hq/dashboard',
    keywords: 'hq zongbu' },

  // ── 导航：菜品菜单 ────────────────────────────────────────
  { id: 'nav-dish-list', title: '菜品列表', group: 'nav', to: '/menu/dishes',
    keywords: 'caipin dish 菜单' },
  { id: 'nav-dish-template', title: '菜单模板', group: 'nav', to: '/menu/templates',
    keywords: 'mubian template 模板' },
  { id: 'nav-dish-pricing', title: '菜品定价', group: 'nav', to: '/menu/pricing',
    keywords: 'dingjia pricing 价格' },

  // ── 导航：会员 ────────────────────────────────────────────
  { id: 'nav-member-list', title: '会员管理', group: 'nav', to: '/members',
    keywords: 'huiyuan member crm' },
  { id: 'nav-rfm-analysis', title: 'RFM 分层分析', group: 'nav', to: '/members/rfm',
    keywords: 'rfm fenceng' },

  // ── 导航：交易 / 桌台 ─────────────────────────────────────
  { id: 'nav-tables', title: '桌台总览', group: 'nav', to: '/trade/tables',
    keywords: 'zhuotai table' },
  { id: 'nav-reservation', title: '预订管理', group: 'nav', to: '/trade/reservations',
    keywords: 'yuding reservation' },
  { id: 'nav-omnichannel', title: '全渠道订单', group: 'nav', to: '/trade/omnichannel',
    keywords: 'quanqudao orders' },

  // ── 导航：报表 ────────────────────────────────────────────
  { id: 'nav-report-center', title: '报表中心', group: 'nav', to: '/analytics/reports',
    keywords: 'baobiao report center' },
  { id: 'nav-daily-report', title: '日报', group: 'nav', to: '/analytics/daily',
    keywords: 'ribao daily' },
  { id: 'nav-pnl-report', title: '损益表 P&L', group: 'nav', to: '/finance/pnl',
    keywords: 'sunyi pnl finance 财务' },

  // ── 导航：组织人事 ────────────────────────────────────────
  { id: 'nav-employees', title: '员工管理', group: 'nav', to: '/org/employees',
    keywords: 'yuangong employee staff' },
  { id: 'nav-payroll', title: '工资单', group: 'nav', to: '/finance/payroll',
    keywords: 'gongzi payroll salary' },

  // ── 导航：Agent / AI ─────────────────────────────────────
  { id: 'nav-agent-console', title: 'Agent 控制台', group: 'nav', to: '/agent',
    keywords: 'agent ai zhinengti' },
  { id: 'nav-agent-decision', title: 'Agent 决策日志', group: 'nav', to: '/agent/decisions',
    keywords: 'juece decision log' },

  // ── 导航：供应链 / 库存 ───────────────────────────────────
  { id: 'nav-inventory', title: '库存', group: 'nav', to: '/supply/inventory',
    keywords: 'kucun inventory' },
  { id: 'nav-purchase', title: '采购', group: 'nav', to: '/supply/purchase',
    keywords: 'caigou purchase' },

  // ── 系统 ─────────────────────────────────────────────────
  { id: 'sys-settings', title: '系统设置', group: 'system', to: '/system',
    keywords: 'shezhi setting xitong' },
  { id: 'sys-iam', title: '权限管理', group: 'system', to: '/iam',
    keywords: 'quanxian iam role' },
];

export function useAdminCommandPalette(commands: AdminCommand[] = ADMIN_DEFAULT_COMMANDS) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const navigate = useNavigate();

  // 全局键盘监听：Ctrl+K / Cmd+K 切换
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const isCmdK = (e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K');
      if (isCmdK) {
        e.preventDefault();
        setOpen(prev => !prev);
        setQuery('');
      }
      // Esc 关闭（兜底，AntD Modal 也会处理）
      if (e.key === 'Escape' && open) {
        setOpen(false);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open]);

  // 按 query 过滤命令（不区分大小写，匹配 title + keywords）
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands.filter(c => {
      const haystack = `${c.title} ${c.description || ''} ${c.keywords || ''}`.toLowerCase();
      return haystack.includes(q);
    });
  }, [commands, query]);

  // 按 group 分组
  const grouped = useMemo(() => {
    const groups: Record<string, AdminCommand[]> = { nav: [], action: [], system: [] };
    for (const c of filtered) {
      groups[c.group].push(c);
    }
    return groups;
  }, [filtered]);

  const execute = useCallback((cmd: AdminCommand) => {
    setOpen(false);
    setQuery('');
    if (cmd.to) {
      navigate(cmd.to);
    } else if (cmd.action) {
      cmd.action();
    }
  }, [navigate]);

  return {
    open,
    setOpen,
    query,
    setQuery,
    filtered,
    grouped,
    execute,
  };
}
