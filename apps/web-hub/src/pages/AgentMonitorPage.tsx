/**
 * Agent 可观测性中心 — 全局监控 Dashboard
 *
 * 四个 Tab：实时事件流 / 决策追踪 / 效果分析 / Agent健康
 * KPI 卡片始终展示在顶部。
 */
import { useState, useEffect, useCallback } from 'react';
import { hubGet } from '../api/hubApi';

// ── 颜色常量（与 Hub 主题一致）──
const BG_0 = '#0B1A20';
const BG_1 = '#0D2129';
const BG_2 = '#1A3540';
const BRAND = '#FF6B2C';
const GREEN = '#22C55E';
const RED = '#EF4444';
const YELLOW = '#F59E0B';
const BLUE = '#3B82F6';
const TEXT_1 = '#FFFFFF';
const TEXT_2 = '#E0E0E0';
const TEXT_3 = '#8BA5B2';
const TEXT_4 = '#6B8A97';

const API_BASE = '/api/v1/agent/observability';

/** Hub 运维 — GET /api/v1/hub/agents/health（与可观测性 API 并行展示） */
interface HubAgentsHealth {
  total_executions_today: number;
  success_rate: number;
  constraint_violations: number;
  top_agents: { agent: string; executions: number; violations: number }[];
}

// ── 类型定义 ──

interface KpiData {
  today_decisions: number;
  adoption_rate: number;
  avg_effectiveness_score: number;
  constraint_blocks: number;
  active_agents: number;
  total_events_today: number;
}

interface EventItem {
  event_id: string;
  timestamp: string;
  source_agent: string;
  event_type: string;
  store_name: string;
  summary: string;
  correlation_id: string;
}

interface DecisionItem {
  decision_id: string;
  agent: string;
  agent_name: string;
  decision: string;
  reason: string;
  confidence: number;
  status: string;
  outcome_score: number | null;
  outcome_summary: string | null;
  store_name: string;
  created_at: string;
}

interface AgentEffectiveness {
  agent_id: string;
  agent_name: string;
  current_score: number;
  trend: string;
  scores_30d: number[];
}

interface DecisionTypeDist {
  type: string;
  label: string;
  count: number;
}

interface AgentMonthlyStat {
  agent_name: string;
  suggestions: number;
  adopted: number;
}

interface EffectivenessData {
  agents: AgentEffectiveness[];
  decision_type_distribution: DecisionTypeDist[];
  agent_monthly_stats: AgentMonthlyStat[];
}

interface AgentHealth {
  agent_id: string;
  agent_name: string;
  status: string;
  today_calls: number;
  avg_latency_ms: number;
  error_rate: number;
  last_call: string;
  uptime_pct: number;
}

interface HealthData {
  agents: AgentHealth[];
  summary: { total_agents: number; healthy: number; warning: number; error: number };
}

interface EventChainItem {
  event_id: string;
  timestamp: string;
  source_agent: string;
  event_type: string;
  summary: string;
}

// ── Mock 数据（API 不可用时回退）──

const MOCK_KPIS: KpiData = {
  today_decisions: 156,
  adoption_rate: 92.0,
  avg_effectiveness_score: 87.3,
  constraint_blocks: 3,
  active_agents: 9,
  total_events_today: 48,
};

const MOCK_EVENTS: EventItem[] = [
  { event_id: 'e1', timestamp: '08:15', source_agent: 'inventory_alert', event_type: 'inventory_surplus', store_name: '芙蓉路店', summary: '鲈鱼库存超预期+50%', correlation_id: 'chain-001' },
  { event_id: 'e2', timestamp: '08:15', source_agent: 'smart_menu', event_type: 'menu_adjustment', store_name: '芙蓉路店', summary: '主推鲈鱼相关菜品', correlation_id: 'chain-001' },
  { event_id: 'e3', timestamp: '08:16', source_agent: 'discount_guard', event_type: 'violation_blocked', store_name: '芙蓉路店', summary: '拦截A05桌62%折扣(超毛利底线)', correlation_id: 'chain-002' },
  { event_id: 'e4', timestamp: '08:20', source_agent: 'planner', event_type: 'plan_generated', store_name: '芙蓉路店', summary: '芙蓉路店今日经营计划已生成(11条建议)', correlation_id: 'chain-003' },
  { event_id: 'e5', timestamp: '08:25', source_agent: 'serve_dispatch', event_type: 'dispatch_optimized', store_name: '芙蓉路店', summary: '午高峰排班优化:增派1名服务员', correlation_id: 'chain-004' },
  { event_id: 'e6', timestamp: '08:30', source_agent: 'member_insight', event_type: 'vip_alert', store_name: '芙蓉路店', summary: 'VIP客户张总预订午餐,偏好剁椒鱼头', correlation_id: 'chain-005' },
  { event_id: 'e7', timestamp: '09:00', source_agent: 'inventory_alert', event_type: 'inventory_shortage', store_name: '万家丽店', summary: '基围虾库存不足,建议紧急采购15kg', correlation_id: 'chain-006' },
  { event_id: 'e8', timestamp: '09:10', source_agent: 'finance_audit', event_type: 'anomaly_detected', store_name: '芙蓉路店', summary: '检测到昨日原材料成本异常偏高+12%', correlation_id: 'chain-007' },
  { event_id: 'e9', timestamp: '09:15', source_agent: 'private_ops', event_type: 'campaign_triggered', store_name: '芙蓉路店', summary: '向156位30天未到店老客发送回归优惠券', correlation_id: 'chain-008' },
  { event_id: 'e10', timestamp: '09:20', source_agent: 'store_inspect', event_type: 'checklist_generated', store_name: '万家丽店', summary: '万家丽店午市前巡检清单已生成(8项)', correlation_id: 'chain-009' },
];

const MOCK_DECISIONS: DecisionItem[] = [
  { decision_id: 'dec-001', agent: 'smart_menu', agent_name: '智能排菜', decision: '主推剁椒鱼头', reason: '近7天销量上升23%,毛利率62%,库存充足', confidence: 0.92, status: 'adopted', outcome_score: 87, outcome_summary: '销量+18%', store_name: '芙蓉路店', created_at: '2026-03-26 08:00' },
  { decision_id: 'dec-002', agent: 'inventory_alert', agent_name: '库存预警', decision: '虾仁紧急采购15kg', reason: '当前库存3kg,预测今日消耗18kg', confidence: 0.95, status: 'adopted', outcome_score: 92, outcome_summary: '无缺货', store_name: '芙蓉路店', created_at: '2026-03-26 08:10' },
  { decision_id: 'dec-003', agent: 'discount_guard', agent_name: '折扣守护', decision: '拦截62%折扣(A05桌)', reason: '折扣率62%超过毛利底线阈值55%', confidence: 0.98, status: 'auto_executed', outcome_score: 95, outcome_summary: '挽回毛利损失\u00A5180', store_name: '芙蓉路店', created_at: '2026-03-26 08:16' },
  { decision_id: 'dec-004', agent: 'serve_dispatch', agent_name: '出餐调度', decision: '午高峰增派1名服务员', reason: '预测今日午间客流+18%', confidence: 0.88, status: 'adopted', outcome_score: 78, outcome_summary: '人效+8%', store_name: '芙蓉路店', created_at: '2026-03-26 08:25' },
  { decision_id: 'dec-005', agent: 'member_insight', agent_name: '会员洞察', decision: 'VIP张总偏好提醒', reason: '张总近3次必点剁椒鱼头', confidence: 0.85, status: 'adopted', outcome_score: 80, outcome_summary: '客户满意度提升', store_name: '芙蓉路店', created_at: '2026-03-26 08:30' },
  { decision_id: 'dec-006', agent: 'smart_menu', agent_name: '智能排菜', decision: '减推外婆鸡', reason: '鸡肉库存偏低,明日到货前需控制出品量', confidence: 0.85, status: 'adopted', outcome_score: 83, outcome_summary: '库存节约2.5kg', store_name: '芙蓉路店', created_at: '2026-03-26 08:35' },
  { decision_id: 'dec-007', agent: 'private_ops', agent_name: '私域运营', decision: '发送回归优惠券', reason: '156位30天未到店老客', confidence: 0.76, status: 'adopted', outcome_score: 72, outcome_summary: '回流率9.5%', store_name: '芙蓉路店', created_at: '2026-03-26 09:15' },
  { decision_id: 'dec-008', agent: 'finance_audit', agent_name: '财务稽核', decision: '标记原材料成本异常', reason: '昨日原材料成本同比+12%', confidence: 0.91, status: 'pending', outcome_score: null, outcome_summary: null, store_name: '芙蓉路店', created_at: '2026-03-26 09:10' },
  { decision_id: 'dec-009', agent: 'discount_guard', agent_name: '折扣守护', decision: '拦截B12桌员工餐滥用', reason: '同一员工本周第4次员工餐折扣', confidence: 0.96, status: 'auto_executed', outcome_score: 93, outcome_summary: '阻止违规折扣\u00A585', store_name: '万家丽店', created_at: '2026-03-26 09:25' },
  { decision_id: 'dec-010', agent: 'store_inspect', agent_name: '巡店质检', decision: '生成午市前巡检清单', reason: '万家丽店午市前需完成8项检查', confidence: 0.90, status: 'adopted', outcome_score: 85, outcome_summary: '8项全部完成', store_name: '万家丽店', created_at: '2026-03-26 09:20' },
];

const MOCK_EFFECTIVENESS: EffectivenessData = {
  agents: [
    { agent_id: 'discount_guard', agent_name: '折扣守护', current_score: 95.0, trend: 'up', scores_30d: [88,89,90,91,90,92,91,93,92,93,94,93,94,95,94,95,94,95,96,95,94,95,95,96,95,95,96,95,95,95] },
    { agent_id: 'inventory_alert', agent_name: '库存预警', current_score: 87.3, trend: 'stable', scores_30d: [85,84,86,87,86,88,87,86,87,88,87,86,87,88,87,88,87,86,87,88,87,88,87,87,88,87,87,88,87,87] },
    { agent_id: 'smart_menu', agent_name: '智能排菜', current_score: 82.1, trend: 'up', scores_30d: [72,73,74,75,74,76,77,76,78,77,78,79,78,79,80,79,80,81,80,81,80,81,82,81,82,81,82,82,82,82] },
    { agent_id: 'member_insight', agent_name: '会员洞察', current_score: 78.5, trend: 'stable', scores_30d: [76,77,76,78,77,78,77,78,79,78,77,78,79,78,79,78,78,79,78,79,78,78,79,78,79,78,79,78,79,79] },
    { agent_id: 'serve_dispatch', agent_name: '出餐调度', current_score: 80.2, trend: 'up', scores_30d: [70,71,72,73,74,73,75,74,76,75,76,77,76,78,77,78,79,78,79,80,79,80,79,80,80,80,80,80,80,80] },
    { agent_id: 'finance_audit', agent_name: '财务稽核', current_score: 85.0, trend: 'stable', scores_30d: [84,84,85,84,85,85,84,85,85,85,84,85,85,85,84,85,85,85,85,85,84,85,85,85,85,85,85,85,85,85] },
    { agent_id: 'private_ops', agent_name: '私域运营', current_score: 72.8, trend: 'up', scores_30d: [62,63,64,65,64,66,67,66,68,67,68,69,68,70,69,70,71,70,71,72,71,72,71,72,72,72,73,72,73,73] },
    { agent_id: 'store_inspect', agent_name: '巡店质检', current_score: 76.5, trend: 'stable', scores_30d: [75,75,76,75,76,76,75,76,76,76,75,76,76,76,76,76,76,77,76,77,76,76,77,76,77,76,76,77,76,77] },
  ],
  decision_type_distribution: [
    { type: 'menu_adjustment', label: '排菜调整', count: 45 },
    { type: 'discount_block', label: '折扣拦截', count: 32 },
    { type: 'inventory_alert', label: '库存预警', count: 28 },
    { type: 'staffing', label: '人员调度', count: 22 },
    { type: 'marketing', label: '营销触发', count: 18 },
    { type: 'inspection', label: '巡检质检', count: 11 },
  ],
  agent_monthly_stats: [
    { agent_name: '折扣守护', suggestions: 234, adopted: 228 },
    { agent_name: '智能排菜', suggestions: 156, adopted: 138 },
    { agent_name: '出餐调度', suggestions: 189, adopted: 172 },
    { agent_name: '库存预警', suggestions: 98, adopted: 91 },
    { agent_name: '会员洞察', suggestions: 67, adopted: 54 },
    { agent_name: '财务稽核', suggestions: 45, adopted: 42 },
    { agent_name: '私域运营', suggestions: 38, adopted: 29 },
    { agent_name: '巡店质检', suggestions: 52, adopted: 48 },
  ],
};

const MOCK_HEALTH: HealthData = {
  agents: [
    { agent_id: 'discount_guard', agent_name: '折扣守护', status: 'healthy', today_calls: 234, avg_latency_ms: 12, error_rate: 0.001, last_call: '2分钟前', uptime_pct: 99.99 },
    { agent_id: 'smart_menu', agent_name: '智能排菜', status: 'healthy', today_calls: 89, avg_latency_ms: 45, error_rate: 0.002, last_call: '5分钟前', uptime_pct: 99.95 },
    { agent_id: 'serve_dispatch', agent_name: '出餐调度', status: 'healthy', today_calls: 156, avg_latency_ms: 23, error_rate: 0.0, last_call: '30秒前', uptime_pct: 100.0 },
    { agent_id: 'member_insight', agent_name: '会员洞察', status: 'healthy', today_calls: 67, avg_latency_ms: 120, error_rate: 0.005, last_call: '8分钟前', uptime_pct: 99.90 },
    { agent_id: 'inventory_alert', agent_name: '库存预警', status: 'healthy', today_calls: 98, avg_latency_ms: 35, error_rate: 0.001, last_call: '3分钟前', uptime_pct: 99.98 },
    { agent_id: 'finance_audit', agent_name: '财务稽核', status: 'healthy', today_calls: 45, avg_latency_ms: 89, error_rate: 0.002, last_call: '15分钟前', uptime_pct: 99.93 },
    { agent_id: 'store_inspect', agent_name: '巡店质检', status: 'healthy', today_calls: 52, avg_latency_ms: 67, error_rate: 0.0, last_call: '20分钟前', uptime_pct: 100.0 },
    { agent_id: 'private_ops', agent_name: '私域运营', status: 'warning', today_calls: 38, avg_latency_ms: 210, error_rate: 0.015, last_call: '25分钟前', uptime_pct: 99.50 },
    { agent_id: 'smart_cs', agent_name: '智能客服', status: 'healthy', today_calls: 23, avg_latency_ms: 150, error_rate: 0.003, last_call: '12分钟前', uptime_pct: 99.85 },
  ],
  summary: { total_agents: 9, healthy: 8, warning: 1, error: 0 },
};

// ── 样式 ──

const s = {
  page: { color: TEXT_2 } as React.CSSProperties,
  title: { fontSize: 22, fontWeight: 700, color: TEXT_1, marginBottom: 16 } as React.CSSProperties,

  // Tab bar
  tabBar: {
    display: 'flex', gap: 0, marginBottom: 20, borderBottom: `1px solid ${BG_2}`,
  } as React.CSSProperties,
  tab: (active: boolean) => ({
    padding: '10px 20px', fontSize: 14, fontWeight: 600, cursor: 'pointer',
    color: active ? BRAND : TEXT_3,
    borderBottom: active ? `2px solid ${BRAND}` : '2px solid transparent',
    background: 'transparent', border: 'none', borderBottomStyle: 'solid' as const,
    transition: 'color 0.2s',
  }) as React.CSSProperties,

  // KPI cards
  cards: { display: 'flex', gap: 14, marginBottom: 24, flexWrap: 'wrap' as const } as React.CSSProperties,
  card: {
    flex: '1 1 180px', background: BG_1, borderRadius: 10, padding: '16px 18px',
    border: `1px solid ${BG_2}`,
  } as React.CSSProperties,
  cardLabel: { fontSize: 12, color: TEXT_4, marginBottom: 6 } as React.CSSProperties,
  cardValue: { fontSize: 26, fontWeight: 700 } as React.CSSProperties,

  // Table
  table: { width: '100%', borderCollapse: 'collapse' as const, fontSize: 13 } as React.CSSProperties,
  th: {
    textAlign: 'left' as const, padding: '10px 12px', borderBottom: `1px solid ${BG_2}`,
    color: TEXT_4, fontWeight: 600, fontSize: 12,
  } as React.CSSProperties,
  td: { padding: '10px 12px', borderBottom: `1px solid #112A33` } as React.CSSProperties,

  // Badges
  badge: (color: string) => ({
    display: 'inline-block', padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600,
    background: color + '22', color: color,
  }) as React.CSSProperties,

  // Buttons
  btnSec: {
    background: 'transparent', color: BRAND, border: `1px solid ${BRAND}`, borderRadius: 6,
    padding: '4px 12px', fontSize: 12, cursor: 'pointer',
  } as React.CSSProperties,

  // Filter bar
  filterBar: {
    display: 'flex', gap: 10, marginBottom: 16, alignItems: 'center', flexWrap: 'wrap' as const,
  } as React.CSSProperties,
  filterLabel: { fontSize: 12, color: TEXT_4 } as React.CSSProperties,
  select: {
    background: BG_1, color: TEXT_2, border: `1px solid ${BG_2}`, borderRadius: 6,
    padding: '5px 10px', fontSize: 12, outline: 'none',
  } as React.CSSProperties,

  // Section container
  section: {
    background: BG_1, borderRadius: 10, padding: '16px 20px', border: `1px solid ${BG_2}`,
    marginBottom: 16,
  } as React.CSSProperties,
  sectionTitle: { fontSize: 15, fontWeight: 700, marginBottom: 12, color: TEXT_1 } as React.CSSProperties,

  // Mini sparkline chart
  sparkContainer: {
    display: 'flex', alignItems: 'flex-end', gap: 1, height: 32,
  } as React.CSSProperties,
  sparkBar: (height: number, color: string) => ({
    width: 3, height: `${height}%`, background: color, borderRadius: 1, minHeight: 1,
  }) as React.CSSProperties,

  // Horizontal bar
  hBar: (pct: number, color: string) => ({
    height: 10, borderRadius: 5, background: color, width: `${pct}%`, minWidth: 2,
    transition: 'width 0.3s',
  }) as React.CSSProperties,
  hBarTrack: {
    height: 10, borderRadius: 5, background: BG_2, width: '100%', position: 'relative' as const,
    overflow: 'hidden',
  } as React.CSSProperties,

  // Chain modal
  overlay: {
    position: 'fixed' as const, top: 0, left: 0, right: 0, bottom: 0,
    background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center',
    zIndex: 1000,
  } as React.CSSProperties,
  modal: {
    background: BG_0, border: `1px solid ${BG_2}`, borderRadius: 12, padding: 24,
    minWidth: 500, maxWidth: 700, maxHeight: '80vh', overflow: 'auto',
  } as React.CSSProperties,
};

// ── Helper: fetch with mock fallback ──

async function fetchData<T>(url: string, fallback: T): Promise<T> {
  try {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const body = await resp.json();
    if (body.ok && body.data) return body.data as T;
    return fallback;
  } catch {
    return fallback;
  }
}

// ── Agent 名称映射 ──

const AGENT_NAMES: Record<string, string> = {
  discount_guard: '折扣守护',
  smart_menu: '智能排菜',
  serve_dispatch: '出餐调度',
  member_insight: '会员洞察',
  inventory_alert: '库存预警',
  finance_audit: '财务稽核',
  store_inspect: '巡店质检',
  private_ops: '私域运营',
  smart_cs: '智能客服',
  planner: '经营规划',
};

const EVENT_TYPE_NAMES: Record<string, string> = {
  inventory_surplus: '库存盈余',
  inventory_shortage: '库存不足',
  menu_adjustment: '排菜调整',
  violation_blocked: '违规拦截',
  plan_generated: '计划生成',
  dispatch_optimized: '调度优化',
  vip_alert: 'VIP提醒',
  anomaly_detected: '异常检测',
  campaign_triggered: '营销触发',
  checklist_generated: '清单生成',
};

const EVENT_TYPE_COLORS: Record<string, string> = {
  inventory_surplus: YELLOW,
  inventory_shortage: RED,
  menu_adjustment: BLUE,
  violation_blocked: RED,
  plan_generated: GREEN,
  dispatch_optimized: BLUE,
  vip_alert: BRAND,
  anomaly_detected: RED,
  campaign_triggered: GREEN,
  checklist_generated: BLUE,
};

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  adopted: { label: '已采纳', color: GREEN },
  auto_executed: { label: '自动执行', color: BLUE },
  pending: { label: '待处理', color: YELLOW },
  rejected: { label: '已拒绝', color: RED },
};

const HEALTH_STATUS_MAP: Record<string, { label: string; color: string }> = {
  healthy: { label: '正常', color: GREEN },
  warning: { label: '警告', color: YELLOW },
  error: { label: '异常', color: RED },
};

const TREND_MAP: Record<string, { label: string; color: string }> = {
  up: { label: '\u2191', color: GREEN },
  stable: { label: '\u2192', color: TEXT_3 },
  down: { label: '\u2193', color: RED },
};

// ── Distribution chart colors ──

const DIST_COLORS = [BRAND, BLUE, YELLOW, GREEN, '#A855F7', RED];

// ── Sub-components ──

function KpiCards({ data }: { data: KpiData }) {
  return (
    <div style={s.cards}>
      <div style={s.card}>
        <div style={s.cardLabel}>今日决策</div>
        <div style={{ ...s.cardValue, color: BRAND }}>{data.today_decisions}</div>
      </div>
      <div style={s.card}>
        <div style={s.cardLabel}>采纳率</div>
        <div style={{ ...s.cardValue, color: GREEN }}>{data.adoption_rate}%</div>
      </div>
      <div style={s.card}>
        <div style={s.cardLabel}>平均效果分</div>
        <div style={{ ...s.cardValue, color: BLUE }}>{data.avg_effectiveness_score}</div>
      </div>
      <div style={s.card}>
        <div style={s.cardLabel}>约束拦截</div>
        <div style={{ ...s.cardValue, color: RED }}>{data.constraint_blocks}</div>
      </div>
      <div style={s.card}>
        <div style={s.cardLabel}>活跃Agent</div>
        <div style={{ ...s.cardValue, color: TEXT_1 }}>{data.active_agents}</div>
      </div>
      <div style={s.card}>
        <div style={s.cardLabel}>今日事件</div>
        <div style={{ ...s.cardValue, color: YELLOW }}>{data.total_events_today}</div>
      </div>
    </div>
  );
}

function EventChainModal({ correlationId, onClose }: { correlationId: string; onClose: () => void }) {
  const [chain, setChain] = useState<EventChainItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetchData<{ events: EventChainItem[] }>(
      `${API_BASE}/event-chain/${correlationId}`,
      { events: [] },
    ).then(data => {
      setChain(data.events);
      setLoading(false);
    });
  }, [correlationId]);

  return (
    <div style={s.overlay} onClick={onClose}>
      <div style={s.modal} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div style={{ fontSize: 16, fontWeight: 700, color: TEXT_1 }}>
            事件链路追踪
          </div>
          <button
            style={{ ...s.btnSec, padding: '4px 10px' }}
            onClick={onClose}
          >
            关闭
          </button>
        </div>
        <div style={{ fontSize: 12, color: TEXT_4, marginBottom: 12 }}>
          Correlation ID: {correlationId}
        </div>
        {loading ? (
          <div style={{ color: TEXT_3, padding: 20, textAlign: 'center' }}>加载中...</div>
        ) : chain.length === 0 ? (
          <div style={{ color: TEXT_3, padding: 20, textAlign: 'center' }}>暂无链路数据</div>
        ) : (
          <div>
            {chain.map((evt, i) => (
              <div key={evt.event_id} style={{
                display: 'flex', gap: 12, padding: '12px 0',
                borderBottom: i < chain.length - 1 ? `1px solid ${BG_2}` : 'none',
              }}>
                <div style={{
                  width: 24, height: 24, borderRadius: 12, background: BRAND + '33',
                  color: BRAND, display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 12, fontWeight: 700, flexShrink: 0,
                }}>
                  {i + 1}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>
                    {AGENT_NAMES[evt.source_agent] || evt.source_agent}
                    <span style={{ color: TEXT_4, fontWeight: 400, marginLeft: 8 }}>{evt.timestamp}</span>
                  </div>
                  <div style={{ fontSize: 12, color: TEXT_3 }}>{evt.summary}</div>
                  <span style={s.badge(EVENT_TYPE_COLORS[evt.event_type] || TEXT_3)}>
                    {EVENT_TYPE_NAMES[evt.event_type] || evt.event_type}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function MiniSparkline({ data, color }: { data: number[]; color: string }) {
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  return (
    <div style={s.sparkContainer}>
      {data.map((v, i) => (
        <div key={i} style={s.sparkBar(((v - min) / range) * 80 + 20, color)} />
      ))}
    </div>
  );
}

function HorizontalBar({ pct, color }: { pct: number; color: string }) {
  return (
    <div style={s.hBarTrack}>
      <div style={s.hBar(Math.min(100, pct), color)} />
    </div>
  );
}

// ── Tab: Events ──

function EventsTab({ events }: { events: EventItem[] }) {
  const [filterAgent, setFilterAgent] = useState('');
  const [filterType, setFilterType] = useState('');
  const [chainId, setChainId] = useState<string | null>(null);

  const uniqueAgents = [...new Set(events.map(e => e.source_agent))];
  const uniqueTypes = [...new Set(events.map(e => e.event_type))];

  const filtered = events.filter(e => {
    if (filterAgent && e.source_agent !== filterAgent) return false;
    if (filterType && e.event_type !== filterType) return false;
    return true;
  });

  return (
    <>
      {chainId && <EventChainModal correlationId={chainId} onClose={() => setChainId(null)} />}
      <div style={s.filterBar}>
        <span style={s.filterLabel}>来源Agent:</span>
        <select style={s.select} value={filterAgent} onChange={e => setFilterAgent(e.target.value)}>
          <option value="">全部</option>
          {uniqueAgents.map(a => <option key={a} value={a}>{AGENT_NAMES[a] || a}</option>)}
        </select>
        <span style={{ ...s.filterLabel, marginLeft: 8 }}>事件类型:</span>
        <select style={s.select} value={filterType} onChange={e => setFilterType(e.target.value)}>
          <option value="">全部</option>
          {uniqueTypes.map(t => <option key={t} value={t}>{EVENT_TYPE_NAMES[t] || t}</option>)}
        </select>
        <span style={{ marginLeft: 'auto', fontSize: 12, color: TEXT_4 }}>
          共 {filtered.length} 条事件
        </span>
      </div>
      <table style={s.table}>
        <thead>
          <tr>
            <th style={s.th}>时间</th>
            <th style={s.th}>门店</th>
            <th style={s.th}>来源Agent</th>
            <th style={s.th}>事件类型</th>
            <th style={s.th}>详情</th>
            <th style={s.th}>链路</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map(evt => (
            <tr key={evt.event_id}>
              <td style={s.td}><span style={{ fontFamily: 'monospace', fontSize: 12 }}>{evt.timestamp}</span></td>
              <td style={s.td}>{evt.store_name}</td>
              <td style={s.td}>{AGENT_NAMES[evt.source_agent] || evt.source_agent}</td>
              <td style={s.td}>
                <span style={s.badge(EVENT_TYPE_COLORS[evt.event_type] || TEXT_3)}>
                  {EVENT_TYPE_NAMES[evt.event_type] || evt.event_type}
                </span>
              </td>
              <td style={s.td}>{evt.summary}</td>
              <td style={s.td}>
                <button style={s.btnSec} onClick={() => setChainId(evt.correlation_id)}>
                  追踪
                </button>
              </td>
            </tr>
          ))}
          {filtered.length === 0 && (
            <tr><td colSpan={6} style={{ ...s.td, textAlign: 'center', color: TEXT_4, padding: 32 }}>暂无事件数据</td></tr>
          )}
        </tbody>
      </table>
    </>
  );
}

// ── Tab: Decisions ──

function DecisionsTab({ decisions }: { decisions: DecisionItem[] }) {
  const [filterAgent, setFilterAgent] = useState('');
  const [filterStatus, setFilterStatus] = useState('');

  const uniqueAgents = [...new Set(decisions.map(d => d.agent))];

  const filtered = decisions.filter(d => {
    if (filterAgent && d.agent !== filterAgent) return false;
    if (filterStatus && d.status !== filterStatus) return false;
    return true;
  });

  return (
    <>
      <div style={s.filterBar}>
        <span style={s.filterLabel}>Agent:</span>
        <select style={s.select} value={filterAgent} onChange={e => setFilterAgent(e.target.value)}>
          <option value="">全部</option>
          {uniqueAgents.map(a => <option key={a} value={a}>{AGENT_NAMES[a] || a}</option>)}
        </select>
        <span style={{ ...s.filterLabel, marginLeft: 8 }}>状态:</span>
        <select style={s.select} value={filterStatus} onChange={e => setFilterStatus(e.target.value)}>
          <option value="">全部</option>
          <option value="adopted">已采纳</option>
          <option value="auto_executed">自动执行</option>
          <option value="pending">待处理</option>
        </select>
        <span style={{ marginLeft: 'auto', fontSize: 12, color: TEXT_4 }}>
          共 {filtered.length} 条决策
        </span>
      </div>
      <table style={s.table}>
        <thead>
          <tr>
            <th style={s.th}>时间</th>
            <th style={s.th}>Agent</th>
            <th style={s.th}>决策内容</th>
            <th style={s.th}>置信度</th>
            <th style={s.th}>状态</th>
            <th style={s.th}>效果分</th>
            <th style={s.th}>效果摘要</th>
            <th style={s.th}>门店</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map(dec => {
            const statusInfo = STATUS_MAP[dec.status] || { label: dec.status, color: TEXT_3 };
            const confPct = Math.round(dec.confidence * 100);
            const confColor = confPct >= 90 ? GREEN : confPct >= 75 ? YELLOW : RED;
            return (
              <tr key={dec.decision_id}>
                <td style={s.td}><span style={{ fontFamily: 'monospace', fontSize: 12 }}>{dec.created_at.split(' ')[1] || dec.created_at}</span></td>
                <td style={s.td}>{dec.agent_name}</td>
                <td style={s.td}>
                  <div style={{ fontWeight: 600 }}>{dec.decision}</div>
                  <div style={{ fontSize: 11, color: TEXT_4, marginTop: 2 }}>{dec.reason}</div>
                </td>
                <td style={s.td}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <div style={{ width: 50, height: 5, borderRadius: 3, background: BG_2 }}>
                      <div style={{ width: `${confPct}%`, height: '100%', borderRadius: 3, background: confColor }} />
                    </div>
                    <span style={{ fontSize: 11, color: confColor }}>{confPct}%</span>
                  </div>
                </td>
                <td style={s.td}>
                  <span style={s.badge(statusInfo.color)}>{statusInfo.label}</span>
                </td>
                <td style={s.td}>
                  {dec.outcome_score !== null ? (
                    <span style={{ fontWeight: 700, color: dec.outcome_score >= 85 ? GREEN : dec.outcome_score >= 70 ? YELLOW : RED }}>
                      {dec.outcome_score}
                    </span>
                  ) : (
                    <span style={{ color: TEXT_4 }}>-</span>
                  )}
                </td>
                <td style={s.td}>
                  {dec.outcome_summary || <span style={{ color: TEXT_4 }}>-</span>}
                </td>
                <td style={s.td}>{dec.store_name}</td>
              </tr>
            );
          })}
          {filtered.length === 0 && (
            <tr><td colSpan={8} style={{ ...s.td, textAlign: 'center', color: TEXT_4, padding: 32 }}>暂无决策数据</td></tr>
          )}
        </tbody>
      </table>
    </>
  );
}

// ── Tab: Effectiveness ──

function EffectivenessTab({ data }: { data: EffectivenessData }) {
  const totalDist = data.decision_type_distribution.reduce((sum, d) => sum + d.count, 0);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Agent effectiveness scores with sparklines */}
      <div style={s.section}>
        <div style={s.sectionTitle}>Agent 效果分 30天趋势</div>
        <table style={s.table}>
          <thead>
            <tr>
              <th style={s.th}>Agent</th>
              <th style={s.th}>当前效果分</th>
              <th style={s.th}>趋势</th>
              <th style={{ ...s.th, width: 150 }}>30天走势</th>
            </tr>
          </thead>
          <tbody>
            {data.agents
              .sort((a, b) => b.current_score - a.current_score)
              .map(agent => {
                const trendInfo = TREND_MAP[agent.trend] || TREND_MAP['stable'];
                const scoreColor = agent.current_score >= 90 ? GREEN : agent.current_score >= 75 ? BLUE : YELLOW;
                return (
                  <tr key={agent.agent_id}>
                    <td style={s.td}>
                      <span style={{ fontWeight: 600 }}>{agent.agent_name}</span>
                    </td>
                    <td style={s.td}>
                      <span style={{ fontSize: 18, fontWeight: 700, color: scoreColor }}>
                        {agent.current_score}
                      </span>
                    </td>
                    <td style={s.td}>
                      <span style={{ fontSize: 16, fontWeight: 700, color: trendInfo.color }}>
                        {trendInfo.label}
                      </span>
                    </td>
                    <td style={s.td}>
                      <MiniSparkline data={agent.scores_30d} color={scoreColor} />
                    </td>
                  </tr>
                );
              })}
          </tbody>
        </table>
      </div>

      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        {/* Decision type distribution */}
        <div style={{ ...s.section, flex: '1 1 300px' }}>
          <div style={s.sectionTitle}>决策类型分布</div>
          {data.decision_type_distribution.map((d, i) => {
            const pct = totalDist > 0 ? Math.round(d.count / totalDist * 100) : 0;
            const color = DIST_COLORS[i % DIST_COLORS.length];
            return (
              <div key={d.type} style={{ marginBottom: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ width: 8, height: 8, borderRadius: 2, background: color, display: 'inline-block' }} />
                    {d.label}
                  </span>
                  <span style={{ color: TEXT_4 }}>{d.count} ({pct}%)</span>
                </div>
                <HorizontalBar pct={pct} color={color} />
              </div>
            );
          })}
        </div>

        {/* Monthly: suggestions vs adopted */}
        <div style={{ ...s.section, flex: '1 1 400px' }}>
          <div style={s.sectionTitle}>各Agent本月建议数 vs 采纳数</div>
          {data.agent_monthly_stats.map(stat => {
            const maxSugg = Math.max(...data.agent_monthly_stats.map(s => s.suggestions));
            const suggPct = maxSugg > 0 ? (stat.suggestions / maxSugg) * 100 : 0;
            const adoptPct = maxSugg > 0 ? (stat.adopted / maxSugg) * 100 : 0;
            const adoptionRate = stat.suggestions > 0 ? Math.round(stat.adopted / stat.suggestions * 100) : 0;
            return (
              <div key={stat.agent_name} style={{ marginBottom: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
                  <span>{stat.agent_name}</span>
                  <span style={{ color: TEXT_4 }}>
                    {stat.adopted}/{stat.suggestions} ({adoptionRate}%)
                  </span>
                </div>
                <div style={{ position: 'relative', height: 16 }}>
                  <div style={{
                    position: 'absolute', top: 0, left: 0, height: 8, borderRadius: 4,
                    width: `${suggPct}%`, background: BG_2,
                  }} />
                  <div style={{
                    position: 'absolute', top: 0, left: 0, height: 8, borderRadius: 4,
                    width: `${adoptPct}%`, background: GREEN, transition: 'width 0.3s',
                  }} />
                  <div style={{
                    position: 'absolute', top: 9, left: 0, fontSize: 10, color: TEXT_4,
                    display: 'flex', gap: 10,
                  }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                      <span style={{ width: 6, height: 6, borderRadius: 1, background: BG_2, display: 'inline-block' }} />
                      建议
                    </span>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                      <span style={{ width: 6, height: 6, borderRadius: 1, background: GREEN, display: 'inline-block' }} />
                      采纳
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ── Tab: Health ──

function HealthTab({ data }: { data: HealthData }) {
  return (
    <>
      {/* Summary strip */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 16 }}>
        <div style={{ ...s.section, flex: 1, display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 14, color: TEXT_3 }}>Agent 总计</span>
          <span style={{ fontSize: 20, fontWeight: 700, color: TEXT_1 }}>{data.summary.total_agents}</span>
          <span style={{ fontSize: 12 }}>
            <span style={{ color: GREEN, marginRight: 8 }}>正常 {data.summary.healthy}</span>
            {data.summary.warning > 0 && <span style={{ color: YELLOW, marginRight: 8 }}>警告 {data.summary.warning}</span>}
            {data.summary.error > 0 && <span style={{ color: RED }}>异常 {data.summary.error}</span>}
          </span>
        </div>
      </div>

      <table style={s.table}>
        <thead>
          <tr>
            <th style={s.th}>Agent</th>
            <th style={s.th}>状态</th>
            <th style={s.th}>今日调用</th>
            <th style={s.th}>平均响应</th>
            <th style={s.th}>错误率</th>
            <th style={s.th}>最后调用</th>
            <th style={s.th}>可用率</th>
          </tr>
        </thead>
        <tbody>
          {data.agents.map(agent => {
            const statusInfo = HEALTH_STATUS_MAP[agent.status] || HEALTH_STATUS_MAP['healthy'];
            const latencyColor = agent.avg_latency_ms <= 50 ? GREEN : agent.avg_latency_ms <= 150 ? YELLOW : RED;
            const errColor = agent.error_rate <= 0.002 ? GREEN : agent.error_rate <= 0.01 ? YELLOW : RED;
            return (
              <tr key={agent.agent_id}>
                <td style={s.td}>
                  <span style={{ fontWeight: 600 }}>{agent.agent_name}</span>
                  <div style={{ fontSize: 11, color: TEXT_4 }}>{agent.agent_id}</div>
                </td>
                <td style={s.td}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{
                      width: 8, height: 8, borderRadius: 4, background: statusInfo.color,
                      display: 'inline-block',
                    }} />
                    <span style={{ color: statusInfo.color, fontWeight: 600, fontSize: 12 }}>
                      {statusInfo.label}
                    </span>
                  </span>
                </td>
                <td style={s.td}>
                  <span style={{ fontWeight: 600 }}>{agent.today_calls}</span>
                </td>
                <td style={s.td}>
                  <span style={{ color: latencyColor, fontWeight: 600 }}>
                    {agent.avg_latency_ms}ms
                  </span>
                </td>
                <td style={s.td}>
                  <span style={{ color: errColor, fontWeight: 600 }}>
                    {(agent.error_rate * 100).toFixed(1)}%
                  </span>
                </td>
                <td style={s.td}>
                  <span style={{ fontSize: 12, color: TEXT_3 }}>{agent.last_call}</span>
                </td>
                <td style={s.td}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <div style={{ width: 60, height: 5, borderRadius: 3, background: BG_2 }}>
                      <div style={{
                        width: `${agent.uptime_pct}%`, height: '100%', borderRadius: 3,
                        background: agent.uptime_pct >= 99.9 ? GREEN : agent.uptime_pct >= 99 ? YELLOW : RED,
                      }} />
                    </div>
                    <span style={{ fontSize: 11, color: TEXT_3 }}>{agent.uptime_pct}%</span>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </>
  );
}

// ── Main page ──

type TabKey = 'events' | 'decisions' | 'effectiveness' | 'health';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'events', label: '实时事件流' },
  { key: 'decisions', label: '决策追踪' },
  { key: 'effectiveness', label: '效果分析' },
  { key: 'health', label: 'Agent健康' },
];

export function AgentMonitorPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('events');
  const [kpis, setKpis] = useState<KpiData>(MOCK_KPIS);
  const [events, setEvents] = useState<EventItem[]>(MOCK_EVENTS);
  const [decisions, setDecisions] = useState<DecisionItem[]>(MOCK_DECISIONS);
  const [effectiveness, setEffectiveness] = useState<EffectivenessData>(MOCK_EFFECTIVENESS);
  const [health, setHealth] = useState<HealthData>(MOCK_HEALTH);
  const [hubHealth, setHubHealth] = useState<HubAgentsHealth | null>(null);

  useEffect(() => {
    hubGet<HubAgentsHealth>('/agents/health')
      .then(setHubHealth)
      .catch(() => setHubHealth(null));
  }, []);

  const loadData = useCallback(async () => {
    const [kpiData, evtData, decData, effData, healthData] = await Promise.all([
      fetchData<KpiData>(`${API_BASE}/kpis`, MOCK_KPIS),
      fetchData<{ items: EventItem[] }>(`${API_BASE}/events?size=100`, { items: MOCK_EVENTS }),
      fetchData<{ items: DecisionItem[] }>(`${API_BASE}/decisions?size=100`, { items: MOCK_DECISIONS }),
      fetchData<EffectivenessData>(`${API_BASE}/effectiveness`, MOCK_EFFECTIVENESS),
      fetchData<HealthData>(`${API_BASE}/health`, MOCK_HEALTH),
    ]);
    setKpis(kpiData);
    setEvents(evtData.items || MOCK_EVENTS);
    setDecisions(decData.items || MOCK_DECISIONS);
    setEffectiveness(effData);
    setHealth(healthData);
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  return (
    <div style={s.page}>
      <div style={s.title}>Agent 可观测性中心</div>

      {hubHealth && (
        <div
          style={{
            background: BG_1,
            border: `1px solid ${BG_2}`,
            borderRadius: 10,
            padding: '12px 16px',
            marginBottom: 16,
            fontSize: 13,
            color: TEXT_3,
            display: 'flex',
            flexWrap: 'wrap',
            gap: 16,
            alignItems: 'center',
          }}
        >
          <span style={{ color: BRAND, fontWeight: 700 }}>Hub 全局</span>
          <span>今日执行 {hubHealth.total_executions_today.toLocaleString()}</span>
          <span>成功率 {hubHealth.success_rate}%</span>
          <span>约束违规 {hubHealth.constraint_violations}</span>
        </div>
      )}

      <KpiCards data={kpis} />

      <div style={s.tabBar}>
        {TABS.map(tab => (
          <button
            key={tab.key}
            style={s.tab(activeTab === tab.key)}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'events' && <EventsTab events={events} />}
      {activeTab === 'decisions' && <DecisionsTab decisions={decisions} />}
      {activeTab === 'effectiveness' && <EffectivenessTab data={effectiveness} />}
      {activeTab === 'health' && <HealthTab data={health} />}
    </div>
  );
}
