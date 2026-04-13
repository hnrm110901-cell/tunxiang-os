/**
 * HomePage — 品牌管理员 Landing Dashboard
 * 登录后的默认着陆页：欢迎区 + KPI + 快捷入口 + 待办 + 实时动态 + 营收趋势
 */
import { useEffect, useState, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { txFetchData } from '../api';
import { formatPrice } from '@tx-ds/utils';

// ─── 类型 ───

interface HomeKPI {
  today_revenue_fen: number;
  yesterday_revenue_fen: number;
  today_orders: number;
  yesterday_orders: number;
  online_stores: number;
  total_stores: number;
  pending_count: number;
}

interface TodoItem {
  id: string;
  type: 'approval' | 'complaint' | 'contract' | 'inventory' | 'certificate';
  label: string;
  count: number;
  path: string;
}

interface TimelineEvent {
  id: string;
  type: 'order' | 'member' | 'campaign' | 'inventory_alert' | 'agent_decision';
  message: string;
  created_at: string;
}

interface HourlyRevenue {
  hour: number;
  today_fen: number;
  yesterday_fen: number;
}

interface HomeData {
  kpi: HomeKPI;
  todos: TodoItem[];
  timeline: TimelineEvent[];
  hourly_revenue: HourlyRevenue[];
}

// ─── Mock 数据（后端 API 未就绪时降级） ───

function generateMockData(): HomeData {
  const now = new Date();
  const currentHour = now.getHours();

  const hourlyRevenue: HourlyRevenue[] = [];
  for (let h = 0; h <= 23; h++) {
    const base = h >= 11 && h <= 13 ? 8000 : h >= 17 && h <= 20 ? 12000 : 3000;
    hourlyRevenue.push({
      hour: h,
      today_fen: h <= currentHour ? Math.round(base * (0.8 + Math.random() * 0.4) * 100) : 0,
      yesterday_fen: Math.round(base * (0.8 + Math.random() * 0.4) * 100),
    });
  }

  return {
    kpi: {
      today_revenue_fen: 28563200,
      yesterday_revenue_fen: 26180000,
      today_orders: 347,
      yesterday_orders: 312,
      online_stores: 18,
      total_stores: 22,
      pending_count: 7,
    },
    todos: [
      { id: '1', type: 'approval', label: '待审批', count: 3, path: '/approval-center' },
      { id: '2', type: 'complaint', label: '待处理客诉', count: 2, path: '/service/workbench' },
      { id: '3', type: 'contract', label: '到期合同', count: 1, path: '/franchise/contracts' },
      { id: '4', type: 'inventory', label: '库存预警', count: 5, path: '/supply/expiry-alerts' },
      { id: '5', type: 'certificate', label: '员工证书到期', count: 2, path: '/org/training' },
    ],
    timeline: [
      { id: 't1', type: 'order', message: '长沙IFS店 新订单 #20260402-0347', created_at: new Date(Date.now() - 30000).toISOString() },
      { id: 't2', type: 'member', message: '新会员注册：尾号8821，来源小程序', created_at: new Date(Date.now() - 120000).toISOString() },
      { id: 't3', type: 'agent_decision', message: '折扣守护Agent: 拦截异常折扣 ¥-88（信心95%）', created_at: new Date(Date.now() - 180000).toISOString() },
      { id: 't4', type: 'inventory_alert', message: '梅溪湖店 三文鱼库存低于安全线', created_at: new Date(Date.now() - 300000).toISOString() },
      { id: 't5', type: 'campaign', message: '营销活动「春季尝鲜周」已自动开启', created_at: new Date(Date.now() - 450000).toISOString() },
      { id: 't6', type: 'order', message: '五一广场店 新订单 #20260402-0346', created_at: new Date(Date.now() - 600000).toISOString() },
      { id: 't7', type: 'agent_decision', message: '智能排菜Agent: 推荐今日特推「蒜蓉龙虾」', created_at: new Date(Date.now() - 720000).toISOString() },
      { id: 't8', type: 'member', message: 'VIP会员李女士 累计消费突破50000元', created_at: new Date(Date.now() - 900000).toISOString() },
      { id: 't9', type: 'order', message: '河西万达店 新订单 #20260402-0345', created_at: new Date(Date.now() - 1100000).toISOString() },
      { id: 't10', type: 'inventory_alert', message: '德思勤店 牛肉批次B2026-0328 明日到期', created_at: new Date(Date.now() - 1300000).toISOString() },
    ],
    hourly_revenue: hourlyRevenue,
  };
}

// ─── 工具函数 ───

/** @deprecated Use formatPrice from @tx-ds/utils */
const fen2yuan = (fen: number): string => `¥${(fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0 })}`;

function calcChange(today: number, yesterday: number): { text: string; color: string; arrow: string } {
  if (yesterday === 0) return { text: '--', color: '#999', arrow: '' };
  const pct = ((today - yesterday) / yesterday) * 100;
  if (pct > 0) return { text: `+${pct.toFixed(1)}%`, color: '#52c41a', arrow: '\u2191' };
  if (pct < 0) return { text: `${pct.toFixed(1)}%`, color: '#ff4d4f', arrow: '\u2193' };
  return { text: '0%', color: '#999', arrow: '' };
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return '刚刚';
  if (diffMin < 60) return `${diffMin}分钟前`;
  const diffHour = Math.floor(diffMin / 60);
  if (diffHour < 24) return `${diffHour}小时前`;
  return d.toLocaleDateString('zh-CN');
}

function formatDate(): string {
  const now = new Date();
  const weekdays = ['日', '一', '二', '三', '四', '五', '六'];
  return `${now.getFullYear()}年${now.getMonth() + 1}月${now.getDate()}日 星期${weekdays[now.getDay()]}`;
}

// ─── 时间线事件类型配置 ───

const eventTypeConfig: Record<string, { icon: string; color: string }> = {
  order:           { icon: '\uD83D\uDCCB', color: '#1890ff' },
  member:          { icon: '\uD83D\uDC64', color: '#722ed1' },
  campaign:        { icon: '\uD83D\uDE80', color: '#eb2f96' },
  inventory_alert: { icon: '\u26A0\uFE0F', color: '#faad14' },
  agent_decision:  { icon: '\uD83E\uDD16', color: '#13c2c2' },
};

// ─── 待办类型配置 ───

const todoTypeConfig: Record<string, { icon: string; color: string }> = {
  approval:    { icon: '\u2705', color: '#1890ff' },
  complaint:   { icon: '\uD83D\uDCE2', color: '#ff4d4f' },
  contract:    { icon: '\uD83D\uDCC4', color: '#faad14' },
  inventory:   { icon: '\uD83D\uDCE6', color: '#fa8c16' },
  certificate: { icon: '\uD83C\uDF93', color: '#722ed1' },
};

// ─── 快捷入口 ───

interface QuickEntry {
  name: string;
  desc: string;
  path: string;
  iconBg: string;
  iconSymbol: string;
}

const quickEntries: QuickEntry[] = [
  { name: '门店管理', desc: '查看与配置门店', path: '/store/manage', iconBg: '#1890ff', iconSymbol: '\uD83C\uDFEA' },
  { name: '菜品管理', desc: '菜单与定价维护', path: '/catalog', iconBg: '#52c41a', iconSymbol: '\uD83C\uDF7D\uFE0F' },
  { name: '订单查询', desc: '实时订单与退单', path: '/trade', iconBg: '#FF6B35', iconSymbol: '\uD83D\uDCCB' },
  { name: '会员管理', desc: '会员画像与运营', path: '/member/insight', iconBg: '#722ed1', iconSymbol: '\uD83D\uDC65' },
  { name: '营销活动', desc: '活动创建与效果', path: '/marketing/campaigns', iconBg: '#eb2f96', iconSymbol: '\uD83C\uDF89' },
  { name: '数据报表', desc: '经营数据与分析', path: '/analytics/dashboard', iconBg: '#13c2c2', iconSymbol: '\uD83D\uDCCA' },
];

// ─── SVG 折线图 ───

interface RevenueChartProps {
  data: HourlyRevenue[];
}

function RevenueChart({ data }: RevenueChartProps) {
  const svgW = 900;
  const svgH = 220;
  const padL = 50;
  const padR = 20;
  const padT = 20;
  const padB = 30;
  const chartW = svgW - padL - padR;
  const chartH = svgH - padT - padB;

  const maxVal = useMemo(() => {
    let m = 0;
    for (const d of data) {
      if (d.today_fen > m) m = d.today_fen;
      if (d.yesterday_fen > m) m = d.yesterday_fen;
    }
    return m || 100000;
  }, [data]);

  const toX = (h: number) => padL + (h / 23) * chartW;
  const toY = (v: number) => padT + chartH - (v / maxVal) * chartH;

  const todayPath = data.filter(d => d.today_fen > 0).map((d, i) =>
    `${i === 0 ? 'M' : 'L'}${toX(d.hour).toFixed(1)},${toY(d.today_fen).toFixed(1)}`
  ).join(' ');

  const yesterdayPath = data.map((d, i) =>
    `${i === 0 ? 'M' : 'L'}${toX(d.hour).toFixed(1)},${toY(d.yesterday_fen).toFixed(1)}`
  ).join(' ');

  // Y 轴刻度
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map(r => ({
    val: Math.round(maxVal * r),
    y: toY(maxVal * r),
  }));

  return (
    <svg viewBox={`0 0 ${svgW} ${svgH}`} style={{ width: '100%', height: 220 }}>
      {/* 网格线 */}
      {yTicks.map(t => (
        <g key={t.val}>
          <line x1={padL} y1={t.y} x2={svgW - padR} y2={t.y} stroke="#1a2a33" strokeWidth={1} />
          <text x={padL - 6} y={t.y + 4} textAnchor="end" fill="#666" fontSize={10}>
            {t.val > 0 ? `${(t.val / 100).toLocaleString('zh-CN')}` : '0'}
          </text>
        </g>
      ))}

      {/* X 轴小时标签 */}
      {[0, 4, 8, 12, 16, 20, 23].map(h => (
        <text key={h} x={toX(h)} y={svgH - 6} textAnchor="middle" fill="#666" fontSize={10}>
          {h}:00
        </text>
      ))}

      {/* 昨日虚线 */}
      {yesterdayPath && (
        <path d={yesterdayPath} fill="none" stroke="#666" strokeWidth={1.5} strokeDasharray="4 3" />
      )}

      {/* 今日实线 */}
      {todayPath && (
        <path d={todayPath} fill="none" stroke="#FF6B35" strokeWidth={2.5} />
      )}

      {/* 图例 */}
      <line x1={svgW - 180} y1={12} x2={svgW - 160} y2={12} stroke="#FF6B35" strokeWidth={2.5} />
      <text x={svgW - 155} y={16} fill="#ccc" fontSize={11}>今日</text>
      <line x1={svgW - 110} y1={12} x2={svgW - 90} y2={12} stroke="#666" strokeWidth={1.5} strokeDasharray="4 3" />
      <text x={svgW - 85} y={16} fill="#666" fontSize={11}>昨日</text>
    </svg>
  );
}

// ─── 搜索框 ───

function GlobalSearch() {
  const [query, setQuery] = useState('');
  const navigate = useNavigate();

  const handleSearch = useCallback(() => {
    if (!query.trim()) return;
    // 未来跳转到全局搜索结果页；当前阶段仅做占位
    navigate(`/trade?search=${encodeURIComponent(query.trim())}`);
  }, [query, navigate]);

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8,
      background: '#112228', borderRadius: 8, padding: '6px 12px',
      border: '1px solid #1a3a44', maxWidth: 360,
    }}>
      <span style={{ color: '#666', fontSize: 14 }}>{'\uD83D\uDD0D'}</span>
      <input
        type="text"
        value={query}
        onChange={e => setQuery(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') handleSearch(); }}
        placeholder="搜索门店/菜品/会员/订单..."
        style={{
          flex: 1, background: 'transparent', border: 'none', outline: 'none',
          color: '#ccc', fontSize: 13, padding: '4px 0',
        }}
      />
    </div>
  );
}

// ─── 主组件 ───

export function HomePage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [data, setData] = useState<HomeData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);

  // 数据加载
  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    txFetchData<HomeData>('/api/v1/dashboard/home')
      .then(res => {
        if (!cancelled) setData(res);
      })
      .catch(() => {
        // API 不可用时降级为 Mock 数据
        if (!cancelled) setData(generateMockData());
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [refreshKey]);

  // 15 秒自动刷新时间线
  useEffect(() => {
    const timer = setInterval(() => {
      setRefreshKey(k => k + 1);
    }, 15000);
    return () => clearInterval(timer);
  }, []);

  const displayName = user?.display_name || user?.username || '管理员';

  // KPI 环比
  const revenueChange = data ? calcChange(data.kpi.today_revenue_fen, data.kpi.yesterday_revenue_fen) : null;
  const orderChange = data ? calcChange(data.kpi.today_orders, data.kpi.yesterday_orders) : null;

  return (
    <div style={{ padding: 24, maxWidth: 1400, margin: '0 auto' }}>

      {/* ────── 欢迎区 ────── */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: 24,
      }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 600 }}>
            欢迎回来，{displayName}
          </h2>
          <div style={{ color: '#999', fontSize: 13, marginTop: 4 }}>
            {formatDate()} {'  \u2601\uFE0F'} {/* 天气图标占位 */}
          </div>
        </div>
        <GlobalSearch />
      </div>

      {/* ────── 核心 KPI 卡片 ────── */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16,
        marginBottom: 24,
      }}>
        {loading ? (
          Array.from({ length: 4 }).map((_, i) => (
            <div key={i} style={{ background: '#112228', borderRadius: 10, padding: 20, height: 100 }}>
              <div style={{ height: 12, width: '40%', background: '#1a2a33', borderRadius: 4, marginBottom: 12 }} />
              <div style={{ height: 28, width: '60%', background: '#1a2a33', borderRadius: 4 }} />
            </div>
          ))
        ) : data ? (
          <>
            {/* 今日营收 */}
            <div style={{
              background: '#112228', borderRadius: 10, padding: 20,
              borderLeft: '4px solid #FF6B35',
            }}>
              <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>今日营收</div>
              <div style={{ fontSize: 28, fontWeight: 'bold', color: '#FF6B35', lineHeight: 1.2 }}>
                {fen2yuan(data.kpi.today_revenue_fen)}
              </div>
              {revenueChange && (
                <div style={{ fontSize: 12, color: revenueChange.color, marginTop: 4 }}>
                  {revenueChange.arrow} 环比昨日 {revenueChange.text}
                </div>
              )}
            </div>

            {/* 今日订单 */}
            <div style={{
              background: '#112228', borderRadius: 10, padding: 20,
              borderLeft: '4px solid #1890ff',
            }}>
              <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>今日订单</div>
              <div style={{ fontSize: 28, fontWeight: 'bold', color: '#1890ff', lineHeight: 1.2 }}>
                {data.kpi.today_orders.toLocaleString('zh-CN')}
              </div>
              {orderChange && (
                <div style={{ fontSize: 12, color: orderChange.color, marginTop: 4 }}>
                  {orderChange.arrow} 环比昨日 {orderChange.text}
                </div>
              )}
            </div>

            {/* 在线门店 */}
            <div style={{
              background: '#112228', borderRadius: 10, padding: 20,
              borderLeft: '4px solid #52c41a',
            }}>
              <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>在线门店</div>
              <div style={{ fontSize: 28, fontWeight: 'bold', color: '#52c41a', lineHeight: 1.2 }}>
                {data.kpi.online_stores}
                <span style={{ fontSize: 14, color: '#666', fontWeight: 400 }}>
                  {' '}/ {data.kpi.total_stores}
                </span>
              </div>
              <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>
                {data.kpi.total_stores - data.kpi.online_stores > 0
                  ? `${data.kpi.total_stores - data.kpi.online_stores} 家离线`
                  : '全部在线'}
              </div>
            </div>

            {/* 待处理事项 */}
            <div
              style={{
                background: '#112228', borderRadius: 10, padding: 20,
                borderLeft: '4px solid #ff4d4f', cursor: 'pointer',
              }}
              onClick={() => navigate('/approval-center')}
            >
              <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>待处理事项</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 28, fontWeight: 'bold', color: '#ff4d4f', lineHeight: 1.2 }}>
                  {data.kpi.pending_count}
                </span>
                {data.kpi.pending_count > 0 && (
                  <span style={{
                    background: '#ff4d4f', color: '#fff', borderRadius: 10,
                    padding: '1px 8px', fontSize: 11, fontWeight: 'bold',
                  }}>
                    需处理
                  </span>
                )}
              </div>
              <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>点击查看详情</div>
            </div>
          </>
        ) : null}
      </div>

      {/* ────── 快捷入口 ────── */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 12,
        marginBottom: 24,
      }}>
        {quickEntries.map(entry => (
          <div
            key={entry.name}
            onClick={() => navigate(entry.path)}
            style={{
              background: '#112228', borderRadius: 10, padding: '16px 12px',
              textAlign: 'center', cursor: 'pointer',
              transition: 'background 0.2s, transform 0.15s',
            }}
            onMouseEnter={e => {
              (e.currentTarget as HTMLDivElement).style.background = '#1a3040';
              (e.currentTarget as HTMLDivElement).style.transform = 'translateY(-2px)';
            }}
            onMouseLeave={e => {
              (e.currentTarget as HTMLDivElement).style.background = '#112228';
              (e.currentTarget as HTMLDivElement).style.transform = 'translateY(0)';
            }}
          >
            <div style={{
              width: 44, height: 44, borderRadius: 12, margin: '0 auto 8px',
              background: entry.iconBg, display: 'flex', alignItems: 'center',
              justifyContent: 'center', fontSize: 22,
            }}>
              {entry.iconSymbol}
            </div>
            <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 2 }}>{entry.name}</div>
            <div style={{ fontSize: 11, color: '#666' }}>{entry.desc}</div>
          </div>
        ))}
      </div>

      {/* ────── 待办事项 + 实时动态（左右布局） ────── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 24 }}>

        {/* 左：待办事项 */}
        <div style={{ background: '#112228', borderRadius: 10, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 600 }}>
            待办事项
          </h3>
          {loading ? (
            Array.from({ length: 5 }).map((_, i) => (
              <div key={i} style={{
                display: 'flex', justifyContent: 'space-between', padding: '10px 0',
                borderBottom: i < 4 ? '1px solid #1a2a33' : 'none',
              }}>
                <div style={{ height: 14, width: 120, background: '#1a2a33', borderRadius: 4 }} />
                <div style={{ height: 14, width: 30, background: '#1a2a33', borderRadius: 4 }} />
              </div>
            ))
          ) : data ? (
            data.todos.map((todo, idx) => {
              const cfg = todoTypeConfig[todo.type] || { icon: '\u2022', color: '#999' };
              return (
                <div
                  key={todo.id}
                  onClick={() => navigate(todo.path)}
                  style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '10px 8px', cursor: 'pointer', borderRadius: 6,
                    borderBottom: idx < data.todos.length - 1 ? '1px solid #1a2a33' : 'none',
                    transition: 'background 0.15s',
                  }}
                  onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.background = '#1a3040'; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.background = 'transparent'; }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span style={{ fontSize: 16 }}>{cfg.icon}</span>
                    <span style={{ fontSize: 13 }}>{todo.label}</span>
                  </div>
                  <span style={{
                    background: todo.count > 0 ? cfg.color : '#333',
                    color: '#fff', borderRadius: 10, padding: '2px 10px',
                    fontSize: 12, fontWeight: 'bold', minWidth: 24, textAlign: 'center',
                  }}>
                    {todo.count}
                  </span>
                </div>
              );
            })
          ) : null}
        </div>

        {/* 右：实时动态 */}
        <div style={{ background: '#112228', borderRadius: 10, padding: 20 }}>
          <div style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            marginBottom: 16,
          }}>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>实时动态</h3>
            <span style={{ fontSize: 11, color: '#666' }}>每15s自动刷新</span>
          </div>
          <div style={{ maxHeight: 320, overflowY: 'auto' }}>
            {loading ? (
              Array.from({ length: 6 }).map((_, i) => (
                <div key={i} style={{
                  display: 'flex', gap: 10, padding: '8px 0',
                  borderBottom: '1px solid #1a2a33',
                }}>
                  <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#1a2a33', marginTop: 4 }} />
                  <div style={{ flex: 1 }}>
                    <div style={{ height: 13, width: '80%', background: '#1a2a33', borderRadius: 3 }} />
                    <div style={{ height: 10, width: '30%', background: '#1a2a33', borderRadius: 3, marginTop: 6 }} />
                  </div>
                </div>
              ))
            ) : data ? (
              data.timeline.map(evt => {
                const cfg = eventTypeConfig[evt.type] || { icon: '\u2022', color: '#999' };
                return (
                  <div key={evt.id} style={{
                    display: 'flex', gap: 10, padding: '8px 0',
                    borderBottom: '1px solid #0d1f26',
                  }}>
                    <div style={{
                      width: 8, height: 8, borderRadius: '50%', background: cfg.color,
                      marginTop: 5, flexShrink: 0,
                    }} />
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13, color: '#ccc', lineHeight: 1.4 }}>{evt.message}</div>
                      <div style={{ fontSize: 11, color: '#555', marginTop: 2 }}>
                        {formatTime(evt.created_at)}
                      </div>
                    </div>
                  </div>
                );
              })
            ) : null}
          </div>
        </div>
      </div>

      {/* ────── 今日营收趋势 ────── */}
      <div style={{ background: '#112228', borderRadius: 10, padding: 20 }}>
        <h3 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 600 }}>今日营收趋势（逐小时）</h3>
        {loading ? (
          <div style={{ height: 220, background: '#0d1f26', borderRadius: 8 }} />
        ) : data ? (
          <RevenueChart data={data.hourly_revenue} />
        ) : null}
      </div>
    </div>
  );
}
