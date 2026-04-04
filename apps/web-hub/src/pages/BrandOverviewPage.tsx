/**
 * 品牌概览首页 — 品牌信息头 + 经营快报 + 快捷入口 + 最新动态 + 待办事项
 * 数据：GET /api/v1/hub/brand/overview
 */
import { useEffect, useState } from 'react';
import { hubGet } from '../api/hubApi';

/* ---------- 类型定义 ---------- */

type BrandInfo = {
  logo: string;
  name: string;
  franchiseStatus: string;
  joinDate: string;
};

type BizSnapshot = {
  monthlyRevenue: number;
  storeCount: number;
  activeMembers: number;
  complaintCount: number;
};

type ActivityLog = {
  id: string;
  time: string;
  operator: string;
  content: string;
};

type TodoSummary = {
  pendingApprovals: number;
  pendingComplaints: number;
  expiringContracts: number;
};

type BrandOverviewData = {
  brand: BrandInfo;
  snapshot: BizSnapshot;
  recentLogs: ActivityLog[];
  todos: TodoSummary;
};

/* ---------- 快捷入口定义 ---------- */

type ShortcutItem = {
  icon: string;
  label: string;
  route: string;
};

const SHORTCUTS: ShortcutItem[] = [
  { icon: '🏪', label: '门店管理', route: '/admin/stores' },
  { icon: '🍽', label: '菜品管理', route: '/admin/menu' },
  { icon: '👥', label: '会员中心', route: '/admin/members' },
  { icon: '📢', label: '营销工具', route: '/admin/marketing' },
  { icon: '💰', label: '财务报表', route: '/admin/finance' },
  { icon: '⚙️', label: '系统设置', route: '/admin/settings' },
];

/* ---------- Mock 数据（API 未就绪时的回退） ---------- */

const MOCK_DATA: BrandOverviewData = {
  brand: {
    logo: '',
    name: '尝在一起',
    franchiseStatus: '正式加盟',
    joinDate: '2024-06-15',
  },
  snapshot: {
    monthlyRevenue: 1285600,
    storeCount: 12,
    activeMembers: 8734,
    complaintCount: 3,
  },
  recentLogs: [
    { id: '1', time: '2026-04-02 14:22', operator: '张经理', content: '新增门店"天心区旗舰店"' },
    { id: '2', time: '2026-04-02 11:05', operator: '李主管', content: '更新菜品"招牌酸菜鱼"价格为 ¥58' },
    { id: '3', time: '2026-04-01 17:30', operator: '王店长', content: '提交3月门店日清报告' },
    { id: '4', time: '2026-04-01 15:12', operator: '系统', content: '会员等级批量升级完成，涉及326人' },
    { id: '5', time: '2026-04-01 10:00', operator: '陈财务', content: '3月财务对账已完成' },
    { id: '6', time: '2026-03-31 16:45', operator: '张经理', content: '审批通过"五一满减活动"方案' },
    { id: '7', time: '2026-03-31 14:20', operator: '系统', content: '供应商"鲜达配送"合同即将到期' },
    { id: '8', time: '2026-03-31 09:30', operator: '李主管', content: '新增员工"赵小明"至天心区旗舰店' },
    { id: '9', time: '2026-03-30 18:00', operator: '王店长', content: '处理客诉工单 #2026033001' },
    { id: '10', time: '2026-03-30 11:15', operator: '系统', content: '月度经营分析报告已生成' },
  ],
  todos: {
    pendingApprovals: 5,
    pendingComplaints: 3,
    expiringContracts: 2,
  },
};

/* ---------- 样式 ---------- */

const s = {
  page: { color: '#E0E0E0' } as React.CSSProperties,
  title: { fontSize: 22, fontWeight: 700, color: '#FFFFFF', marginBottom: 24 } as React.CSSProperties,
  err: { color: '#EF4444', fontSize: 13, marginBottom: 12 } as React.CSSProperties,

  /* 品牌信息头 */
  brandHeader: {
    display: 'flex', alignItems: 'center', gap: 16, background: '#0D2129',
    borderRadius: 10, padding: '20px 24px', border: '1px solid #1A3540', marginBottom: 24,
  } as React.CSSProperties,
  brandLogo: {
    width: 56, height: 56, borderRadius: 12, background: '#FF6B2C',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontSize: 26, fontWeight: 700, color: '#FFF', flexShrink: 0,
  } as React.CSSProperties,
  brandName: { fontSize: 20, fontWeight: 700, color: '#FFFFFF' } as React.CSSProperties,
  brandMeta: { fontSize: 12, color: '#6B8A97', marginTop: 4 } as React.CSSProperties,
  badge: (color: string) => ({
    display: 'inline-block', padding: '2px 10px', borderRadius: 20,
    fontSize: 11, fontWeight: 600, background: `${color}22`, color, marginLeft: 8,
  }) as React.CSSProperties,

  /* 经营快报 */
  cards: { display: 'flex', gap: 16, marginBottom: 24, flexWrap: 'wrap' as const } as React.CSSProperties,
  card: {
    flex: '1 1 200px', background: '#0D2129', borderRadius: 10, padding: '18px 20px',
    border: '1px solid #1A3540',
  } as React.CSSProperties,
  cardLabel: { fontSize: 12, color: '#6B8A97', marginBottom: 6 } as React.CSSProperties,
  cardValue: { fontSize: 28, fontWeight: 700, color: '#FF6B2C' } as React.CSSProperties,
  cardValueGreen: { fontSize: 28, fontWeight: 700, color: '#22C55E' } as React.CSSProperties,
  cardValueBlue: { fontSize: 28, fontWeight: 700, color: '#3B82F6' } as React.CSSProperties,
  cardValueRed: { fontSize: 28, fontWeight: 700, color: '#EF4444' } as React.CSSProperties,

  /* 快捷入口 */
  sectionTitle: { fontSize: 16, fontWeight: 600, color: '#FFFFFF', marginBottom: 14 } as React.CSSProperties,
  shortcuts: {
    display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14, marginBottom: 24,
  } as React.CSSProperties,
  shortcut: {
    background: '#0D2129', borderRadius: 10, padding: '20px 16px',
    border: '1px solid #1A3540', textAlign: 'center' as const,
    cursor: 'pointer', transition: 'border-color 0.2s',
    textDecoration: 'none', display: 'block',
  } as React.CSSProperties,
  shortcutIcon: { fontSize: 28, marginBottom: 8 } as React.CSSProperties,
  shortcutLabel: { fontSize: 13, color: '#E0E0E0', fontWeight: 500 } as React.CSSProperties,

  /* 双栏布局：动态 + 待办 */
  twoCol: { display: 'flex', gap: 20, flexWrap: 'wrap' as const } as React.CSSProperties,
  colLeft: { flex: '2 1 400px', minWidth: 0 } as React.CSSProperties,
  colRight: { flex: '1 1 260px', minWidth: 0 } as React.CSSProperties,

  /* 最新动态 */
  logList: {
    background: '#0D2129', borderRadius: 10, border: '1px solid #1A3540', padding: 16,
  } as React.CSSProperties,
  logItem: {
    display: 'flex', gap: 12, padding: '10px 0',
    borderBottom: '1px solid #112A33', fontSize: 13,
  } as React.CSSProperties,
  logTime: { color: '#6B8A97', whiteSpace: 'nowrap' as const, minWidth: 120 } as React.CSSProperties,
  logOperator: { color: '#FF6B2C', fontWeight: 600, minWidth: 60 } as React.CSSProperties,
  logContent: { color: '#C0D0D8', flex: 1 } as React.CSSProperties,

  /* 待办事项 */
  todoPanel: {
    background: '#0D2129', borderRadius: 10, border: '1px solid #1A3540', padding: 16,
  } as React.CSSProperties,
  todoItem: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '12px 0', borderBottom: '1px solid #112A33', fontSize: 13,
  } as React.CSSProperties,
  todoLabel: { color: '#C0D0D8' } as React.CSSProperties,
  todoCount: (color: string) => ({
    fontSize: 20, fontWeight: 700, color,
  }) as React.CSSProperties,
};

/* ---------- 辅助函数 ---------- */

function formatRevenue(value: number): string {
  if (value >= 10000) return `¥${(value / 10000).toFixed(1)}万`;
  return `¥${value.toLocaleString()}`;
}

function franchiseColor(status: string): string {
  if (status.includes('正式')) return '#22C55E';
  if (status.includes('试用') || status.includes('试运营')) return '#F59E0B';
  return '#3B82F6';
}

/* ---------- 组件 ---------- */

export function BrandOverviewPage() {
  const [data, setData] = useState<BrandOverviewData>(MOCK_DATA);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    hubGet<BrandOverviewData>('/brand/overview')
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setErr(null);
        }
      })
      .catch((_e: Error) => {
        // API 未就绪时静默使用 Mock 数据
        if (!cancelled) setErr(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const { brand, snapshot, recentLogs, todos } = data;

  return (
    <div style={s.page}>
      <div style={s.title}>品牌概览</div>
      {err && <div style={s.err}>{err}</div>}

      {/* 品牌信息头 */}
      <div style={s.brandHeader}>
        <div style={s.brandLogo}>
          {brand.logo ? (
            <img src={brand.logo} alt={brand.name} style={{ width: 56, height: 56, borderRadius: 12 }} />
          ) : (
            brand.name.charAt(0)
          )}
        </div>
        <div>
          <div style={s.brandName}>
            {brand.name}
            <span style={s.badge(franchiseColor(brand.franchiseStatus))}>
              {brand.franchiseStatus}
            </span>
          </div>
          <div style={s.brandMeta}>入驻时间：{brand.joinDate}</div>
        </div>
      </div>

      {/* 经营快报 4 卡片 */}
      <div style={s.sectionTitle}>经营快报</div>
      <div style={s.cards}>
        <div style={s.card}>
          <div style={s.cardLabel}>本月总营收</div>
          <div style={s.cardValue}>{formatRevenue(snapshot.monthlyRevenue)}</div>
        </div>
        <div style={s.card}>
          <div style={s.cardLabel}>门店数</div>
          <div style={s.cardValueGreen}>{snapshot.storeCount}</div>
        </div>
        <div style={s.card}>
          <div style={s.cardLabel}>活跃会员</div>
          <div style={s.cardValueBlue}>{snapshot.activeMembers.toLocaleString()}</div>
        </div>
        <div style={s.card}>
          <div style={s.cardLabel}>客诉数</div>
          <div style={s.cardValueRed}>{snapshot.complaintCount}</div>
        </div>
      </div>

      {/* 快捷入口 2x3 */}
      <div style={s.sectionTitle}>快捷入口</div>
      <div style={s.shortcuts}>
        {SHORTCUTS.map((sc) => (
          <a
            key={sc.route}
            href={sc.route}
            style={s.shortcut}
            target="_blank"
            rel="noopener noreferrer"
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLAnchorElement).style.borderColor = '#FF6B2C';
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLAnchorElement).style.borderColor = '#1A3540';
            }}
          >
            <div style={s.shortcutIcon}>{sc.icon}</div>
            <div style={s.shortcutLabel}>{sc.label}</div>
          </a>
        ))}
      </div>

      {/* 双栏：最新动态 + 待办事项 */}
      <div style={s.twoCol}>
        <div style={s.colLeft}>
          <div style={s.sectionTitle}>最新动态</div>
          <div style={s.logList}>
            {recentLogs.map((log, idx) => (
              <div
                key={log.id}
                style={{
                  ...s.logItem,
                  ...(idx === recentLogs.length - 1 ? { borderBottom: 'none' } : {}),
                }}
              >
                <span style={s.logTime}>{log.time}</span>
                <span style={s.logOperator}>{log.operator}</span>
                <span style={s.logContent}>{log.content}</span>
              </div>
            ))}
          </div>
        </div>

        <div style={s.colRight}>
          <div style={s.sectionTitle}>待办事项</div>
          <div style={s.todoPanel}>
            <div style={s.todoItem}>
              <span style={s.todoLabel}>待审批</span>
              <span style={s.todoCount('#F59E0B')}>{todos.pendingApprovals}</span>
            </div>
            <div style={s.todoItem}>
              <span style={s.todoLabel}>待处理客诉</span>
              <span style={s.todoCount('#EF4444')}>{todos.pendingComplaints}</span>
            </div>
            <div style={{ ...s.todoItem, borderBottom: 'none' }}>
              <span style={s.todoLabel}>到期合同</span>
              <span style={s.todoCount('#3B82F6')}>{todos.expiringContracts}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
