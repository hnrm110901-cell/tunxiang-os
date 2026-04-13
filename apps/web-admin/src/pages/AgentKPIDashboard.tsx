/**
 * AgentKPIDashboard — AI Agent KPI总览仪表盘（模块4.4）
 *
 * 功能：
 * - 9大核心Agent KPI卡片展示（当前值 vs 目标值 + 达成率进度条 + 7日趋势迷你图）
 * - ROI汇总区域（本月节省金额/折扣异常拦截次数/食材损耗降低百分比）
 * - 30秒自动刷新
 */
import { useEffect, useState, useCallback } from 'react';

// ── 类型定义 ────────────────────────────────────────────────────────────────

interface TrendPoint {
  date: string;
  value: number;
}

interface KpiItem {
  kpi_type: string;
  label: string;
  measured_value: number;
  target_value: number;
  unit: string;
  achievement_rate: number;
  achievement_pct: number;
  color: 'green' | 'yellow' | 'red';
  direction: string;
  trend_7d: TrendPoint[];
}

interface AgentCard {
  agent_id: string;
  agent_name: string;
  overall_achievement_rate: number;
  overall_achievement_pct: number;
  overall_color: 'green' | 'yellow' | 'red';
  kpi_count: number;
  kpis: KpiItem[];
  as_of: string;
}

interface DashboardData {
  as_of: string;
  global_achievement_rate: number;
  global_achievement_pct: number;
  global_color: 'green' | 'yellow' | 'red';
  agent_count: number;
  agents: AgentCard[];
}

interface RoiSummary {
  total_saved_fen: number;
  total_saved_yuan: number;
  discount_intercept_count: number;
  waste_reduction_pct: number;
  member_recalled_count: number;
}

interface RoiData {
  report_month: string;
  summary: RoiSummary;
}

// ── 颜色工具 ─────────────────────────────────────────────────────────────────

const COLOR_MAP = {
  green: {
    bg: 'bg-green-50',
    border: 'border-green-200',
    badge: 'bg-green-100 text-green-800',
    bar: 'bg-green-500',
    text: 'text-green-700',
  },
  yellow: {
    bg: 'bg-yellow-50',
    border: 'border-yellow-200',
    badge: 'bg-yellow-100 text-yellow-800',
    bar: 'bg-yellow-500',
    text: 'text-yellow-700',
  },
  red: {
    bg: 'bg-red-50',
    border: 'border-red-200',
    badge: 'bg-red-100 text-red-800',
    bar: 'bg-red-500',
    text: 'text-red-700',
  },
} as const;

// ── 迷你趋势图（div模拟） ────────────────────────────────────────────────────

function MiniTrendChart({ data, direction }: { data: TrendPoint[]; direction: string }) {
  if (!data.length) return null;

  const values = data.map((d) => d.value);
  const maxVal = Math.max(...values);
  const minVal = Math.min(...values);
  const range = maxVal - minVal || 1;

  return (
    <div className="flex items-end gap-0.5 h-8">
      {values.map((v, i) => {
        const heightPct = ((v - minVal) / range) * 100;
        const barHeight = Math.max(4, Math.round(heightPct * 0.28) + 4);
        // 对lower_better，值越低越好（条形越短越绿）
        const isGood =
          direction === 'lower_better'
            ? v <= values[0]  // 相比第一天是否更低
            : v >= values[0]; // 相比第一天是否更高
        const barColor = isGood ? 'bg-blue-400' : 'bg-slate-300';
        return (
          <div
            key={i}
            className={`flex-1 rounded-sm ${barColor} transition-all`}
            style={{ height: `${barHeight}px` }}
            title={`${data[i].date}: ${v}`}
          />
        );
      })}
    </div>
  );
}

// ── KPI单项行 ────────────────────────────────────────────────────────────────

function KpiRow({ kpi }: { kpi: KpiItem }) {
  const colors = COLOR_MAP[kpi.color];
  const barWidth = Math.min(100, Math.round(kpi.achievement_pct));

  return (
    <div className="py-2 border-b border-slate-100 last:border-0">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-slate-600">{kpi.label}</span>
        <span className={`text-xs font-medium ${colors.text}`}>
          {kpi.measured_value}
          {kpi.unit} / 目标{kpi.target_value}
          {kpi.unit}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <div className="flex-1 bg-slate-100 rounded-full h-1.5">
          <div
            className={`h-1.5 rounded-full transition-all ${colors.bar}`}
            style={{ width: `${barWidth}%` }}
          />
        </div>
        <span className={`text-xs font-bold w-10 text-right ${colors.text}`}>
          {kpi.achievement_pct}%
        </span>
      </div>
    </div>
  );
}

// ── Agent KPI卡片 ─────────────────────────────────────────────────────────────

const AGENT_ICONS: Record<string, string> = {
  discount_guardian: '🛡️',
  smart_dispatch: '⚡',
  member_insight: '👥',
  inventory_alert: '📦',
  finance_audit: '💰',
  store_patrol: '🔍',
  smart_menu: '🍽️',
  customer_service: '💬',
  private_ops: '📣',
};

function AgentKpiCard({ agent }: { agent: AgentCard }) {
  const [expanded, setExpanded] = useState(false);
  const colors = COLOR_MAP[agent.overall_color];
  const icon = AGENT_ICONS[agent.agent_id] || '🤖';

  // 仅展示前两个KPI，其余折叠
  const visibleKpis = expanded ? agent.kpis : agent.kpis.slice(0, 2);

  // 第一个KPI的7日趋势图
  const firstKpi = agent.kpis[0];

  return (
    <div
      className={`rounded-xl border-2 p-4 flex flex-col gap-3 ${colors.bg} ${colors.border} shadow-sm`}
    >
      {/* 头部 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xl">{icon}</span>
          <div>
            <h3 className="font-semibold text-slate-800 text-sm leading-tight">
              {agent.agent_name}
            </h3>
            <p className="text-xs text-slate-500">{agent.agent_id}</p>
          </div>
        </div>
        <div className="text-right">
          <span className={`text-2xl font-bold ${colors.text}`}>
            {agent.overall_achievement_pct}%
          </span>
          <p className="text-xs text-slate-500">综合达成</p>
        </div>
      </div>

      {/* 总体进度条 */}
      <div className="bg-white/60 rounded-full h-2">
        <div
          className={`h-2 rounded-full transition-all ${colors.bar}`}
          style={{ width: `${Math.min(100, agent.overall_achievement_pct)}%` }}
        />
      </div>

      {/* KPI列表 */}
      <div>
        {visibleKpis.map((kpi) => (
          <KpiRow key={kpi.kpi_type} kpi={kpi} />
        ))}
        {agent.kpis.length > 2 && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="mt-1 text-xs text-blue-500 hover:text-blue-700 transition-colors"
          >
            {expanded ? '收起' : `展开 ${agent.kpis.length - 2} 个更多指标`}
          </button>
        )}
      </div>

      {/* 7日趋势迷你图 */}
      {firstKpi && (
        <div>
          <p className="text-xs text-slate-400 mb-1">7日趋势 — {firstKpi.label}</p>
          <MiniTrendChart data={firstKpi.trend_7d} direction={firstKpi.direction} />
        </div>
      )}

      {/* 更新时间 */}
      <p className="text-xs text-slate-400 text-right">截至 {agent.as_of}</p>
    </div>
  );
}

// ── ROI汇总卡片 ──────────────────────────────────────────────────────────────

function RoiSummaryCard({ data }: { data: RoiData }) {
  const { summary, report_month } = data;
  return (
    <div className="rounded-xl border-2 border-blue-200 bg-gradient-to-br from-blue-50 to-indigo-50 p-5 shadow-sm">
      <div className="flex items-center gap-2 mb-4">
        <span className="text-2xl">💎</span>
        <div>
          <h3 className="font-bold text-slate-800">本月AI累计价值</h3>
          <p className="text-xs text-slate-500">{report_month}</p>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-4">
        <div className="text-center">
          <p className="text-2xl font-bold text-blue-700">
            ¥{summary.total_saved_yuan.toLocaleString()}
          </p>
          <p className="text-xs text-slate-500 mt-0.5">累计节省金额（元）</p>
        </div>
        <div className="text-center border-x border-blue-200">
          <p className="text-2xl font-bold text-indigo-700">
            {summary.discount_intercept_count}
          </p>
          <p className="text-xs text-slate-500 mt-0.5">折扣异常拦截次数</p>
        </div>
        <div className="text-center">
          <p className="text-2xl font-bold text-green-700">
            -{summary.waste_reduction_pct}%
          </p>
          <p className="text-xs text-slate-500 mt-0.5">食材损耗降低</p>
        </div>
      </div>
      <div className="mt-4 pt-3 border-t border-blue-200 flex justify-between text-xs text-slate-500">
        <span>召回会员 {summary.member_recalled_count} 人</span>
        <span>数据每30秒刷新</span>
      </div>
    </div>
  );
}

// ── 主组件 ────────────────────────────────────────────────────────────────────

const API_BASE = '/api/v1/agent-kpi';
const DEFAULT_TENANT = 'default-tenant';

export default function AgentKPIDashboard() {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [roi, setRoi] = useState<RoiData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const headers = { 'X-Tenant-ID': DEFAULT_TENANT };

      const [dashRes, roiRes] = await Promise.all([
        fetch(`${API_BASE}/dashboard`, { headers }),
        fetch(`${API_BASE}/roi-report`, { headers }),
      ]);

      if (!dashRes.ok || !roiRes.ok) {
        throw new Error(`API错误: dashboard=${dashRes.status} roi=${roiRes.status}`);
      }

      const dashJson = await dashRes.json();
      const roiJson = await roiRes.json();

      if (dashJson.ok) setDashboard(dashJson.data);
      if (roiJson.ok) setRoi(roiJson.data);
      setError(null);
      setLastRefresh(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : '数据加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, 30_000);
    return () => clearInterval(timer);
  }, [fetchData]);

  // ── 渲染 ──────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-500">
        <span className="animate-spin mr-2">⏳</span>加载中…
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3">
        <p className="text-red-600">❌ {error}</p>
        <button
          onClick={fetchData}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm"
        >
          重试
        </button>
      </div>
    );
  }

  const globalColor = dashboard ? COLOR_MAP[dashboard.global_color] : COLOR_MAP.green;

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* 页头 */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">AI Agent KPI仪表盘</h1>
          <p className="text-sm text-slate-500 mt-0.5">9大核心Agent业务指标实时追踪 · 模块4.4</p>
        </div>
        <div className="flex items-center gap-3">
          {dashboard && (
            <div className={`px-4 py-2 rounded-xl border-2 text-center ${globalColor.bg} ${globalColor.border}`}>
              <p className={`text-xl font-bold ${globalColor.text}`}>
                {dashboard.global_achievement_pct}%
              </p>
              <p className="text-xs text-slate-500">全局达成率</p>
            </div>
          )}
          <div className="text-right text-xs text-slate-400">
            <p>上次刷新</p>
            <p>{lastRefresh?.toLocaleTimeString('zh-CN') ?? '-'}</p>
          </div>
          <button
            onClick={fetchData}
            className="px-3 py-2 bg-slate-100 hover:bg-slate-200 rounded-lg text-sm text-slate-600 transition-colors"
          >
            🔄 刷新
          </button>
        </div>
      </div>

      {/* ROI汇总 */}
      {roi && (
        <div className="mb-6">
          <RoiSummaryCard data={roi} />
        </div>
      )}

      {/* Agent KPI卡片网格 */}
      {dashboard && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {dashboard.agents.map((agent) => (
            <AgentKpiCard key={agent.agent_id} agent={agent} />
          ))}
        </div>
      )}

      {/* 底部说明 */}
      <div className="mt-6 text-center text-xs text-slate-400">
        <p>数据每30秒自动刷新 · 进度条颜色：绿色≥95% / 黄色80-94% / 红色&lt;80%</p>
      </div>
    </div>
  );
}
