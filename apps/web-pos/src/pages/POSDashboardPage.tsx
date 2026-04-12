/**
 * 门店工作台首页 — 演示就绪版
 * 布局：横屏平板 1024×768
 * 左区：4个KPI卡片(2×2) + 今日待办列表
 * 右区：AI决策推荐卡片
 * 底部：4个快捷操作大按钮
 *
 * 规范：
 * - 深色主题 背景#0D1117 卡片#1A2232
 * - 主色 #FF6B35 (--tx-primary)
 * - 最小触控区 48×48px
 * - 最小字体 16px
 * - 所有可点击元素 :active + scale(0.97)
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { txFetch } from '../api/index';

/* ─── Design tokens (deep dark theme for POS tablet) ─── */
const T = {
  bg0: '#0D1117',
  bg1: '#1A2232',
  bg2: '#1F2A3F',
  border: '#2A3A52',
  primary: '#FF6B35',
  primaryDim: 'rgba(255,107,53,0.15)',
  success: '#0F6E56',
  successBg: 'rgba(15,110,86,0.15)',
  warning: '#BA7517',
  warningBg: 'rgba(186,117,23,0.15)',
  danger: '#A32D2D',
  dangerBg: 'rgba(163,45,45,0.15)',
  info: '#185FA5',
  infoBg: 'rgba(24,95,165,0.15)',
  text1: '#E8EDF5',
  text2: '#A0AEC0',
  text3: '#6B7A8D',
};

/* ─── 门店配置 ─── */
const STORES = [
  { id: 'store_001', name: '文化城店', address: '天心区文化路18号' },
  { id: 'store_002', name: '浏小鲜', address: '浏阳市淮川街道中山路88号' },
  { id: 'store_003', name: '永安店', address: '雨花区永安路255号' },
];

/* ─── Types ─── */
interface KpiData {
  revenue_fen: number;
  revenue_trend_pct: number;
  order_count: number;
  order_trend: number;
  avg_ticket_fen: number;
  avg_ticket_trend_pct: number;
  table_turnover: number;
  table_turnover_trend: number;
}

interface TodoItem {
  id: string;
  type: '预订确认' | '缺料预警' | '客诉处理' | '设备故障' | '人员调度';
  content: string;
  urgent: boolean;
}

interface AgentDecision {
  agent_name: string;
  suggestion: string;
  reasoning: string;
  confidence: number;
  revenue_impact_fen: number;
}

/* ─── Mock data (尝在一起 真实数字范围) ─── */
const MOCK_KPI: KpiData = {
  revenue_fen: 1_268_000,   // 12,680元
  revenue_trend_pct: 8.2,
  order_count: 86,
  order_trend: 12,
  avg_ticket_fen: 14_740,   // 147.4元
  avg_ticket_trend_pct: -2.1,
  table_turnover: 2.3,
  table_turnover_trend: 0.3,
};

const MOCK_TODOS: TodoItem[] = [
  { id: 't1', type: '预订确认', content: '18:00 王先生 6人包厢', urgent: true },
  { id: 't2', type: '缺料预警', content: '剁椒酱库存不足，预计今晚用完', urgent: true },
  { id: 't3', type: '客诉处理', content: 'A03桌反馈上菜慢（等待32分钟）', urgent: false },
  { id: 't4', type: '预订确认', content: '19:30 李女士 4人大厅', urgent: false },
];

const MOCK_AGENT: AgentDecision = {
  agent_name: '智能排菜Agent',
  suggestion: '今日主推剁椒鱼头套餐，同时减少外婆鸡推荐频次',
  reasoning: '鲈鱼到货充足(+40%)，剁椒酱尚有余量可坚持至明日采购；鸡肉库存偏低，预计18:00前售罄风险75%。主推鱼头套餐可提升毛利率约3.2个百分点。',
  confidence: 0.87,
  revenue_impact_fen: 80000, // +800元预测
};

/* ─── 格式化工具 ─── */
const fmt = {
  yuan: (fen: number) =>
    (fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 0 }),
  yenDecimal: (fen: number) =>
    (fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 1, maximumFractionDigits: 1 }),
  pct: (v: number) => (v >= 0 ? `+${v.toFixed(1)}%` : `${v.toFixed(1)}%`),
  delta: (v: number) => (v >= 0 ? `+${v}` : `${v}`),
};

const todoTypeStyle: Record<string, { bg: string; color: string }> = {
  '预订确认': { bg: T.infoBg, color: '#4A9FE0' },
  '缺料预警': { bg: T.warningBg, color: '#E0A020' },
  '客诉处理': { bg: T.dangerBg, color: '#E05050' },
  '设备故障': { bg: T.dangerBg, color: '#E05050' },
  '人员调度': { bg: T.primaryDim, color: T.primary },
};

/* ═══════════════════════════════════════════════
   StoreSelectPage — 门店选择界面（登录后首次进入）
   ═══════════════════════════════════════════════ */
function StoreSelectPage({
  onSelect,
}: {
  onSelect: (store: typeof STORES[0]) => void;
}) {
  const [pressing, setPressing] = useState<string | null>(null);

  return (
    <div
      style={{
        minHeight: '100vh',
        background: T.bg0,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        fontFamily: '"Noto Sans SC", -apple-system, sans-serif',
        padding: 32,
      }}
    >
      {/* 品牌 Logo 区 */}
      <div style={{ marginBottom: 48, textAlign: 'center' }}>
        <div
          style={{
            fontSize: 36,
            fontWeight: 700,
            color: T.primary,
            letterSpacing: 4,
            marginBottom: 8,
          }}
        >
          尝在一起
        </div>
        <div style={{ fontSize: 18, color: T.text2 }}>请选择您的门店</div>
      </div>

      {/* 门店卡片组 */}
      <div
        style={{
          display: 'flex',
          gap: 24,
          flexWrap: 'wrap',
          justifyContent: 'center',
          maxWidth: 900,
        }}
      >
        {STORES.map((store) => (
          <button
            key={store.id}
            onPointerDown={() => setPressing(store.id)}
            onPointerUp={() => setPressing(null)}
            onPointerLeave={() => setPressing(null)}
            onClick={() => onSelect(store)}
            style={{
              width: 260,
              padding: '32px 24px',
              background: pressing === store.id ? T.bg2 : T.bg1,
              border: `2px solid ${pressing === store.id ? T.primary : T.border}`,
              borderRadius: 16,
              cursor: 'pointer',
              textAlign: 'left',
              transform: pressing === store.id ? 'scale(0.97)' : 'scale(1)',
              transition: 'transform 0.15s ease, border-color 0.15s ease',
              display: 'flex',
              flexDirection: 'column',
              gap: 12,
            }}
          >
            {/* 门店图标 */}
            <div
              style={{
                width: 56,
                height: 56,
                borderRadius: 12,
                background: T.primaryDim,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 28,
                marginBottom: 4,
              }}
            >
              🏪
            </div>
            <div style={{ fontSize: 22, fontWeight: 700, color: T.text1 }}>
              {store.name}
            </div>
            <div style={{ fontSize: 16, color: T.text2, lineHeight: 1.5 }}>
              {store.address}
            </div>
            <div
              style={{
                marginTop: 8,
                padding: '10px 0',
                background: T.primary,
                borderRadius: 8,
                color: '#fff',
                fontSize: 16,
                fontWeight: 600,
                textAlign: 'center',
                minHeight: 48,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              进入工作台
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════
   KpiCard — 单个指标卡片
   ═══════════════════════════════════════════════ */
function KpiCard({
  label,
  value,
  unit,
  trend,
  trendPositive,
  accentColor,
}: {
  label: string;
  value: string;
  unit: string;
  trend: string;
  trendPositive: boolean;
  accentColor: string;
}) {
  return (
    <div
      style={{
        background: T.bg1,
        borderRadius: 12,
        padding: '16px 18px',
        borderLeft: `4px solid ${accentColor}`,
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        minHeight: 100,
      }}
    >
      <div style={{ fontSize: 16, color: T.text2 }}>{label}</div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
        <span style={{ fontSize: 30, fontWeight: 700, color: T.text1, lineHeight: 1.1 }}>
          {value}
        </span>
        <span style={{ fontSize: 16, color: T.text3 }}>{unit}</span>
      </div>
      <div
        style={{
          fontSize: 16,
          color: trendPositive ? '#4CAF82' : '#E05050',
          fontWeight: 500,
        }}
      >
        {trend} 较昨日
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════
   TodoItem — 单条待办（支持滑出消失动画）
   ═══════════════════════════════════════════════ */
function TodoRow({
  todo,
  onDone,
}: {
  todo: TodoItem;
  onDone: (id: string) => void;
}) {
  const [leaving, setLeaving] = useState(false);
  const [pressing, setPressing] = useState(false);
  const typeStyle = todoTypeStyle[todo.type] || { bg: T.bg2, color: T.text2 };

  const handleDone = () => {
    setLeaving(true);
    setTimeout(() => onDone(todo.id), 350);
  };

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '12px 0',
        borderBottom: `1px solid ${T.border}`,
        opacity: leaving ? 0 : 1,
        transform: leaving ? 'translateX(100%)' : 'translateX(0)',
        transition: 'opacity 0.3s ease, transform 0.3s ease',
        overflow: 'hidden',
      }}
    >
      {/* 类型 tag */}
      <span
        style={{
          flexShrink: 0,
          padding: '4px 10px',
          borderRadius: 6,
          background: typeStyle.bg,
          color: typeStyle.color,
          fontSize: 16,
          fontWeight: 600,
          whiteSpace: 'nowrap',
          minHeight: 32,
          display: 'flex',
          alignItems: 'center',
        }}
      >
        {todo.type}
      </span>

      {/* 内容 */}
      <span style={{ flex: 1, fontSize: 16, color: T.text1, lineHeight: 1.4 }}>
        {todo.content}
        {todo.urgent && (
          <span
            style={{
              marginLeft: 8,
              fontSize: 16,
              color: '#E05050',
              fontWeight: 600,
            }}
          >
            紧急
          </span>
        )}
      </span>

      {/* 处理按钮 — 最小48×48 */}
      <button
        onPointerDown={() => setPressing(true)}
        onPointerUp={() => setPressing(false)}
        onPointerLeave={() => setPressing(false)}
        onClick={handleDone}
        style={{
          flexShrink: 0,
          minWidth: 72,
          minHeight: 48,
          padding: '0 16px',
          background: pressing ? '#0A4A34' : T.successBg,
          color: '#4CAF82',
          border: '1px solid #4CAF82',
          borderRadius: 8,
          cursor: 'pointer',
          fontSize: 16,
          fontWeight: 600,
          transform: pressing ? 'scale(0.97)' : 'scale(1)',
          transition: 'transform 0.15s ease, background 0.15s ease',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        处理
      </button>
    </div>
  );
}

/* ═══════════════════════════════════════════════
   ShortcutButton — 底部快捷大按钮
   ═══════════════════════════════════════════════ */
function ShortcutButton({
  label,
  emoji,
  color,
  onClick,
}: {
  label: string;
  emoji: string;
  color: string;
  onClick: () => void;
}) {
  const [pressing, setPressing] = useState(false);

  return (
    <button
      onPointerDown={() => setPressing(true)}
      onPointerUp={() => setPressing(false)}
      onPointerLeave={() => setPressing(false)}
      onClick={onClick}
      style={{
        flex: 1,
        height: 72,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 10,
        background: pressing ? color : `${color}22`,
        border: `2px solid ${color}`,
        borderRadius: 12,
        cursor: 'pointer',
        color: pressing ? '#fff' : color,
        fontSize: 20,
        fontWeight: 700,
        transform: pressing ? 'scale(0.97)' : 'scale(1)',
        transition: 'transform 0.15s ease, background 0.15s ease, color 0.15s ease',
        letterSpacing: 1,
      }}
    >
      <span style={{ fontSize: 22 }}>{emoji}</span>
      {label}
    </button>
  );
}

/* ═══════════════════════════════════════════════
   StoreDashboard — 门店工作台主界面
   ═══════════════════════════════════════════════ */
function StoreDashboard({ store }: { store: typeof STORES[0] }) {
  const navigate = useNavigate();
  const [kpi, setKpi] = useState<KpiData>(MOCK_KPI);
  const [todos, setTodos] = useState<TodoItem[]>(MOCK_TODOS);
  const [agent, setAgent] = useState<AgentDecision>(MOCK_AGENT);
  const [adoptedRevenue, setAdoptedRevenue] = useState<number>(0);
  const [agentState, setAgentState] = useState<'idle' | 'adopted' | 'ignored'>('idle');
  const [adoptPressing, setAdoptPressing] = useState(false);
  const [ignorePressing, setIgnorePressing] = useState(false);
  const [loadingKpi, setLoadingKpi] = useState(false);

  /* ── 拉取今日KPI（有后端则用真实数据，否则保持mock）── */
  const loadKpi = useCallback(async () => {
    setLoadingKpi(true);
    try {
      const data = await txFetch<KpiData>(
        `/api/v1/analytics/store/today?store_id=${encodeURIComponent(store.id)}`,
      );
      setKpi(data);
    } catch {
      // 后端未就绪，保留 mock 数据，不显示错误
    } finally {
      setLoadingKpi(false);
    }
  }, [store.id]);

  /* ── 拉取 Agent 建议 ── */
  const loadAgent = useCallback(async () => {
    try {
      const data = await txFetch<AgentDecision>(
        `/api/v1/agent/decisions/latest?store_id=${encodeURIComponent(store.id)}`,
      );
      setAgent(data);
    } catch {
      // 保留 mock
    }
  }, [store.id]);

  /* ── 拉取待办 ── */
  const loadTodos = useCallback(async () => {
    try {
      const data = await txFetch<{ items: TodoItem[] }>(
        `/api/v1/agent/todos?store_id=${encodeURIComponent(store.id)}`,
      );
      setTodos(data.items);
    } catch {
      // 保留 mock
    }
  }, [store.id]);

  useEffect(() => {
    loadKpi();
    loadAgent();
    loadTodos();
    // 60秒刷新一次KPI
    const timer = setInterval(loadKpi, 60_000);
    return () => clearInterval(timer);
  }, [loadKpi, loadAgent, loadTodos]);

  /* ── 采纳建议 ── */
  const handleAdopt = () => {
    if (agentState !== 'idle') return;
    setAgentState('adopted');
    setAdoptedRevenue(agent.revenue_impact_fen);
    // 更新KPI营收展示（预测值叠加）
    setKpi((prev) => ({
      ...prev,
      revenue_fen: prev.revenue_fen + agent.revenue_impact_fen,
    }));
  };

  /* ── 忽略建议 ── */
  const handleIgnore = () => {
    if (agentState !== 'idle') return;
    setAgentState('ignored');
  };

  const handleTodoDone = (id: string) => {
    setTodos((prev) => prev.filter((t) => t.id !== id));
  };

  /* ── 当前营收显示值（已采纳时标注预测） ── */
  const revenueDisplay = fmt.yuan(kpi.revenue_fen);
  const revenueUnit = adoptedRevenue > 0 ? `元 +${fmt.yuan(adoptedRevenue)}元(预测)` : '元';

  return (
    <div
      style={{
        height: '100vh',
        display: 'flex',
        flexDirection: 'column',
        background: T.bg0,
        color: T.text1,
        fontFamily: '"Noto Sans SC", -apple-system, BlinkMacSystemFont, sans-serif',
        overflow: 'hidden',
      }}
    >
      {/* ─── Header ─── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '16px 24px',
          background: T.bg1,
          borderBottom: `1px solid ${T.border}`,
          flexShrink: 0,
        }}
      >
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: T.text1 }}>
          门店工作台
          {loadingKpi && (
            <span style={{ fontSize: 16, color: T.text3, marginLeft: 12, fontWeight: 400 }}>
              刷新中…
            </span>
          )}
        </h1>
        <div style={{ textAlign: 'right' }}>
          <div
            style={{
              fontSize: 18,
              fontWeight: 600,
              color: T.primary,
            }}
          >
            尝在一起
          </div>
          <div style={{ fontSize: 16, color: T.text2 }}>{store.name}</div>
        </div>
      </div>

      {/* ─── 主内容区 ─── */}
      <div
        style={{
          flex: 1,
          display: 'grid',
          gridTemplateColumns: '1fr 380px',
          gap: 16,
          padding: '16px 20px',
          overflow: 'hidden',
          minHeight: 0,
        }}
      >
        {/* ─── 左区 ─── */}
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 16,
            overflow: 'hidden',
            minHeight: 0,
          }}
        >
          {/* KPI 2×2 网格 */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: 12,
              flexShrink: 0,
            }}
          >
            <KpiCard
              label="今日营收"
              value={revenueDisplay}
              unit={revenueUnit}
              trend={fmt.pct(kpi.revenue_trend_pct)}
              trendPositive={kpi.revenue_trend_pct >= 0}
              accentColor={T.primary}
            />
            <KpiCard
              label="订单数"
              value={String(kpi.order_count)}
              unit="单"
              trend={fmt.delta(kpi.order_trend) + ' 单'}
              trendPositive={kpi.order_trend >= 0}
              accentColor="#185FA5"
            />
            <KpiCard
              label="客单价"
              value={fmt.yenDecimal(kpi.avg_ticket_fen)}
              unit="元"
              trend={fmt.pct(kpi.avg_ticket_trend_pct)}
              trendPositive={kpi.avg_ticket_trend_pct >= 0}
              accentColor="#BA7517"
            />
            <KpiCard
              label="翻台率"
              value={kpi.table_turnover.toFixed(1)}
              unit="次"
              trend={fmt.delta(kpi.table_turnover_trend) + ' 次'}
              trendPositive={kpi.table_turnover_trend >= 0}
              accentColor="#6B46C1"
            />
          </div>

          {/* 今日待办列表 */}
          <div
            style={{
              flex: 1,
              background: T.bg1,
              borderRadius: 12,
              padding: '16px 18px',
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
              minHeight: 0,
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                marginBottom: 8,
                flexShrink: 0,
              }}
            >
              <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: T.text1 }}>
                今日待办
              </h2>
              <span
                style={{
                  padding: '2px 10px',
                  background: todos.length > 0 ? T.dangerBg : T.successBg,
                  color: todos.length > 0 ? '#E05050' : '#4CAF82',
                  borderRadius: 20,
                  fontSize: 16,
                  fontWeight: 600,
                }}
              >
                {todos.length}
              </span>
            </div>

            <div
              style={{
                flex: 1,
                overflowY: 'auto',
                WebkitOverflowScrolling: 'touch' as const,
              }}
            >
              {todos.length === 0 ? (
                <div
                  style={{
                    height: 80,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: T.text3,
                    fontSize: 18,
                  }}
                >
                  暂无待办事项 ✓
                </div>
              ) : (
                todos.map((todo) => (
                  <TodoRow key={todo.id} todo={todo} onDone={handleTodoDone} />
                ))
              )}
            </div>
          </div>
        </div>

        {/* ─── 右区：AI 决策推荐 ─── */}
        <div
          style={{
            background: T.bg1,
            borderRadius: 12,
            padding: '20px 18px',
            borderTop: `4px solid ${agentState === 'adopted' ? '#4CAF82' : agentState === 'ignored' ? T.text3 : '#6B46C1'}`,
            display: 'flex',
            flexDirection: 'column',
            gap: 16,
            overflow: 'hidden',
          }}
        >
          {/* 标题行 */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: T.text1 }}>
              AI 决策推荐
            </h2>
            <span
              style={{
                padding: '4px 12px',
                background: 'rgba(107,70,193,0.2)',
                color: '#A78BFA',
                borderRadius: 20,
                fontSize: 16,
                fontWeight: 600,
              }}
            >
              置信度 {(agent.confidence * 100).toFixed(0)}%
            </span>
          </div>

          {/* Agent名称 */}
          <div
            style={{
              fontSize: 16,
              color: T.text2,
              padding: '6px 10px',
              background: T.bg2,
              borderRadius: 6,
            }}
          >
            {agent.agent_name}
          </div>

          {/* 建议内容（大字，显眼） */}
          <div
            style={{
              fontSize: 20,
              fontWeight: 700,
              color: '#E8C97F',
              lineHeight: 1.5,
            }}
          >
            {agent.suggestion}
          </div>

          {/* 数据依据（小字） */}
          <div
            style={{
              flex: 1,
              fontSize: 17,
              color: T.text2,
              lineHeight: 1.7,
              overflowY: 'auto',
              WebkitOverflowScrolling: 'touch' as const,
            }}
          >
            {agent.reasoning}
          </div>

          {/* 预测收益 */}
          <div
            style={{
              padding: '10px 14px',
              background: T.successBg,
              borderRadius: 8,
              fontSize: 17,
              color: '#4CAF82',
              fontWeight: 600,
            }}
          >
            预计增收：+{fmt.yuan(agent.revenue_impact_fen)} 元
          </div>

          {/* 操作按钮组 */}
          {agentState === 'idle' && (
            <div style={{ display: 'flex', gap: 10, flexShrink: 0 }}>
              <button
                onPointerDown={() => setAdoptPressing(true)}
                onPointerUp={() => setAdoptPressing(false)}
                onPointerLeave={() => setAdoptPressing(false)}
                onClick={handleAdopt}
                style={{
                  flex: 2,
                  minHeight: 56,
                  background: adoptPressing ? '#0A4A34' : T.successBg,
                  color: '#4CAF82',
                  border: '2px solid #4CAF82',
                  borderRadius: 10,
                  cursor: 'pointer',
                  fontSize: 18,
                  fontWeight: 700,
                  transform: adoptPressing ? 'scale(0.97)' : 'scale(1)',
                  transition: 'transform 0.15s ease, background 0.15s ease',
                }}
              >
                采纳建议
              </button>
              <button
                onPointerDown={() => setIgnorePressing(true)}
                onPointerUp={() => setIgnorePressing(false)}
                onPointerLeave={() => setIgnorePressing(false)}
                onClick={handleIgnore}
                style={{
                  flex: 1,
                  minHeight: 56,
                  background: 'transparent',
                  color: T.text3,
                  border: `2px solid ${T.border}`,
                  borderRadius: 10,
                  cursor: 'pointer',
                  fontSize: 18,
                  fontWeight: 600,
                  transform: ignorePressing ? 'scale(0.97)' : 'scale(1)',
                  transition: 'transform 0.15s ease',
                }}
              >
                忽略
              </button>
            </div>
          )}

          {/* 已采纳 反馈 */}
          {agentState === 'adopted' && (
            <div
              style={{
                minHeight: 56,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 10,
                background: T.successBg,
                border: '2px solid #4CAF82',
                borderRadius: 10,
                fontSize: 18,
                fontWeight: 700,
                color: '#4CAF82',
                flexShrink: 0,
              }}
            >
              ✓ 已采纳 — 营收预测 +{fmt.yuan(adoptedRevenue)} 元
            </div>
          )}

          {/* 已忽略 反馈 */}
          {agentState === 'ignored' && (
            <div
              style={{
                minHeight: 56,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: T.bg2,
                border: `2px solid ${T.border}`,
                borderRadius: 10,
                fontSize: 18,
                color: T.text3,
                flexShrink: 0,
              }}
            >
              已忽略此建议
            </div>
          )}
        </div>
      </div>

      {/* ─── 底部快捷按钮 ─── */}
      <div
        style={{
          display: 'flex',
          gap: 12,
          padding: '12px 20px 16px',
          background: T.bg1,
          borderTop: `1px solid ${T.border}`,
          flexShrink: 0,
        }}
      >
        <ShortcutButton
          label="开台"
          emoji="🪑"
          color={T.primary}
          onClick={() => navigate('/tables')}
        />
        <ShortcutButton
          label="预订"
          emoji="📅"
          color="#6B46C1"
          onClick={() => navigate('/reservations')}
        />
        <ShortcutButton
          label="交班"
          emoji="🔄"
          color="#BA7517"
          onClick={() => navigate('/shift')}
        />
        <ShortcutButton
          label="异常"
          emoji="⚠️"
          color="#A32D2D"
          onClick={() => navigate('/exceptions')}
        />
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════
   POSDashboardPage — 入口组件（含门店选择逻辑）
   ═══════════════════════════════════════════════ */
export function POSDashboardPage() {
  const [selectedStore, setSelectedStore] = useState<typeof STORES[0] | null>(() => {
    const saved = sessionStorage.getItem('tx_selected_store');
    if (saved) {
      try {
        return JSON.parse(saved) as typeof STORES[0];
      } catch {
        return null;
      }
    }
    return null;
  });

  const handleStoreSelect = (store: typeof STORES[0]) => {
    sessionStorage.setItem('tx_selected_store', JSON.stringify(store));
    setSelectedStore(store);
  };

  if (!selectedStore) {
    return <StoreSelectPage onSelect={handleStoreSelect} />;
  }

  return <StoreDashboard store={selectedStore} />;
}
