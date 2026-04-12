/**
 * DailyPlanPage -- 每日运营执行中心
 * 接入真实API：E1-E8节点状态 + 今日营收目标 vs 实际 + 待审批/异常数
 */
import { useState, useEffect, useCallback } from 'react';
import { txFetchData } from '../api';

// ---- 颜色常量 ----
const BG_0 = '#0d1e28';
const BG_1 = '#1a2a33';
const BG_2 = '#243443';
const BRAND = '#FF6B35';
const GREEN = '#52c41a';
const RED = '#ff4d4f';
const YELLOW = '#faad14';
const BLUE = '#1890ff';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

// ---- 类型定义 ----

interface NodeStatus {
  node_id: string;     // E1~E8
  node_name: string;
  status: 'completed' | 'in_progress' | 'pending' | 'skipped' | 'error';
  completed_at?: string;
  score?: number;
  detail?: string;
}

interface DailyReviewStatus {
  date: string;
  store_id: string;
  store_name: string;
  overall_score: number;
  nodes: NodeStatus[];
  completed_count: number;
  total_count: number;
}

interface DailyProfitData {
  date: string;
  revenue_fen: number;
  cost_fen: number;
  profit_fen: number;
  margin_rate: number;
  target_revenue_fen?: number;
  target_profit_fen?: number;
}

interface ApprovalCount {
  pending_count: number;
}

interface AnomalyCount {
  anomaly_count: number;
}

// ---- 工具函数 ----

const todayStr = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

const fenToYuan = (fen: number) => (fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 0 });

const weekDayMap = ['日', '一', '二', '三', '四', '五', '六'];
const formatDateTitle = (dateStr: string) => {
  const d = new Date(dateStr);
  const month = d.getMonth() + 1;
  const day = d.getDate();
  const weekday = weekDayMap[d.getDay()];
  return `${month}月${day}日 星期${weekday}`;
};

// ---- E节点名称映射 ----
const NODE_NAMES: Record<string, string> = {
  E1: '开市准备',
  E2: '营业目标确认',
  E3: '午市执行',
  E4: '午市复盘',
  E5: '晚市准备',
  E6: '晚市执行',
  E7: '收市结算',
  E8: '日结复盘',
};

const NODE_ICONS: Record<string, string> = {
  E1: '🌅',
  E2: '🎯',
  E3: '🍽️',
  E4: '📊',
  E5: '🌆',
  E6: '🍜',
  E7: '💰',
  E8: '📋',
};

// ---- 状态配置 ----
const STATUS_CONFIG = {
  completed:   { label: '已完成', color: GREEN,  bg: GREEN + '22' },
  in_progress: { label: '进行中', color: BLUE,   bg: BLUE + '22' },
  pending:     { label: '待执行', color: TEXT_4, bg: BG_2 },
  skipped:     { label: '已跳过', color: TEXT_4, bg: BG_2 },
  error:       { label: '异常',   color: RED,    bg: RED + '22' },
};

// ---- 子组件 ----

function LoadingCard({ height = 120 }: { height?: number }) {
  return (
    <div style={{
      background: BG_1, borderRadius: 12, height,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ color: TEXT_4, fontSize: 13 }}>加载中...</div>
    </div>
  );
}

function ErrorCard({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div style={{
      background: BG_1, borderRadius: 12, padding: '16px 20px',
      border: `1px solid ${RED}44`,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    }}>
      <span style={{ color: RED, fontSize: 13 }}>加载失败: {message}</span>
      <button
        onClick={onRetry}
        style={{
          padding: '4px 12px', borderRadius: 6, border: `1px solid ${RED}66`,
          background: 'transparent', color: RED, fontSize: 12, cursor: 'pointer',
        }}
      >
        重试
      </button>
    </div>
  );
}

// E1-E8 节点状态卡片
function NodeStatusCard({
  data,
  loading,
  error,
  onRetry,
}: {
  data: DailyReviewStatus | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  if (loading) return <LoadingCard height={200} />;
  if (error) return <ErrorCard message={error} onRetry={onRetry} />;

  const nodes = data?.nodes ?? Object.keys(NODE_NAMES).map(k => ({
    node_id: k,
    node_name: NODE_NAMES[k],
    status: 'pending' as const,
  }));

  const completedCount = nodes.filter(n => n.status === 'completed').length;
  const totalCount = nodes.length;
  const completionPct = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;

  return (
    <div style={{
      background: BG_1, borderRadius: 12, padding: '20px',
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1 }}>今日执行节点</div>
          <div style={{ fontSize: 12, color: TEXT_3, marginTop: 2 }}>
            {data?.store_name || '全部门店'} · E1-E8
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 26, fontWeight: 700, color: BRAND }}>{completionPct}%</div>
          <div style={{ fontSize: 11, color: TEXT_3 }}>{completedCount}/{totalCount} 完成</div>
        </div>
      </div>

      {/* 进度条 */}
      <div style={{ width: '100%', height: 6, borderRadius: 3, background: BG_2, marginBottom: 16 }}>
        <div style={{
          width: `${completionPct}%`, height: '100%', borderRadius: 3,
          background: completionPct >= 80 ? GREEN : completionPct >= 50 ? YELLOW : BRAND,
          transition: 'width .4s',
        }} />
      </div>

      {/* 节点网格 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
        {nodes.map(node => {
          const cfg = STATUS_CONFIG[node.status] ?? STATUS_CONFIG.pending;
          const nodeKey = node.node_id.toUpperCase();
          return (
            <div
              key={node.node_id}
              title={node.detail || node.node_name}
              style={{
                padding: '10px 8px', borderRadius: 8, textAlign: 'center',
                background: cfg.bg, border: `1px solid ${cfg.color}44`,
                cursor: 'default',
              }}
            >
              <div style={{ fontSize: 18, marginBottom: 4 }}>
                {NODE_ICONS[nodeKey] || '⚙️'}
              </div>
              <div style={{ fontSize: 11, fontWeight: 700, color: cfg.color }}>{nodeKey}</div>
              <div style={{ fontSize: 10, color: TEXT_3, marginTop: 2, lineHeight: 1.3 }}>
                {NODE_NAMES[nodeKey] || node.node_name}
              </div>
              <div style={{
                marginTop: 4, fontSize: 10, padding: '1px 4px', borderRadius: 3,
                background: cfg.color + '33', color: cfg.color, fontWeight: 600,
              }}>
                {cfg.label}
              </div>
            </div>
          );
        })}
      </div>

      {data?.overall_score != null && (
        <div style={{
          marginTop: 14, padding: '8px 12px', borderRadius: 8,
          background: BG_2, display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <span style={{ fontSize: 12, color: TEXT_3 }}>今日执行评分</span>
          <span style={{
            fontSize: 18, fontWeight: 700,
            color: data.overall_score >= 85 ? GREEN : data.overall_score >= 70 ? YELLOW : RED,
          }}>
            {data.overall_score} 分
          </span>
        </div>
      )}
    </div>
  );
}

// 今日营收卡片
function RevenueCard({
  data,
  loading,
  error,
  onRetry,
}: {
  data: DailyProfitData | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  if (loading) return <LoadingCard height={180} />;
  if (error) return <ErrorCard message={error} onRetry={onRetry} />;

  const revenue = data?.revenue_fen ?? 0;
  const target = data?.target_revenue_fen ?? 0;
  const profit = data?.profit_fen ?? 0;
  const cost = data?.cost_fen ?? 0;
  const margin = data?.margin_rate ?? 0;
  const reachPct = target > 0 ? Math.min(Math.round((revenue / target) * 100), 999) : 0;

  return (
    <div style={{
      background: BG_1, borderRadius: 12, padding: '20px',
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 16 }}>
        今日营收 vs 目标
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
        <div style={{ padding: '12px 14px', background: BG_2, borderRadius: 8 }}>
          <div style={{ fontSize: 11, color: TEXT_3, marginBottom: 4 }}>实际营收</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: TEXT_1 }}>
            ¥{fenToYuan(revenue)}
          </div>
        </div>
        <div style={{ padding: '12px 14px', background: BG_2, borderRadius: 8 }}>
          <div style={{ fontSize: 11, color: TEXT_3, marginBottom: 4 }}>目标营收</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: target > 0 ? TEXT_2 : TEXT_4 }}>
            {target > 0 ? `¥${fenToYuan(target)}` : '未设置'}
          </div>
        </div>
      </div>

      {target > 0 && (
        <div style={{ marginBottom: 14 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
            <span style={{ fontSize: 12, color: TEXT_3 }}>目标达成率</span>
            <span style={{
              fontSize: 13, fontWeight: 700,
              color: reachPct >= 100 ? GREEN : reachPct >= 80 ? YELLOW : RED,
            }}>
              {reachPct}%
            </span>
          </div>
          <div style={{ width: '100%', height: 6, borderRadius: 3, background: BG_2 }}>
            <div style={{
              width: `${Math.min(reachPct, 100)}%`, height: '100%', borderRadius: 3,
              background: reachPct >= 100 ? GREEN : reachPct >= 80 ? YELLOW : RED,
              transition: 'width .4s',
            }} />
          </div>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
        {[
          { label: '毛利润', value: `¥${fenToYuan(profit)}`, color: profit >= 0 ? GREEN : RED },
          { label: '成本', value: `¥${fenToYuan(cost)}`, color: TEXT_2 },
          { label: '毛利率', value: `${(margin * 100).toFixed(1)}%`, color: margin >= 0.5 ? GREEN : margin >= 0.35 ? YELLOW : RED },
        ].map((item, i) => (
          <div key={i} style={{
            padding: '8px 10px', background: BG_2, borderRadius: 6, textAlign: 'center',
          }}>
            <div style={{ fontSize: 10, color: TEXT_4, marginBottom: 2 }}>{item.label}</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: item.color }}>{item.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// 待审批卡片
function ApprovalCard({
  count,
  loading,
  error,
  onRetry,
}: {
  count: number;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  if (loading) return <LoadingCard height={120} />;

  return (
    <div style={{
      background: BG_1, borderRadius: 12, padding: '20px',
      border: `1px solid ${error ? RED + '44' : BG_2}`,
      display: 'flex', flexDirection: 'column', gap: 10,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1 }}>待处理审批</div>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8 }}>
        <div style={{
          fontSize: 42, fontWeight: 700,
          color: error ? TEXT_4 : count > 0 ? YELLOW : GREEN,
        }}>
          {error ? '-' : count}
        </div>
        <div style={{ fontSize: 13, color: TEXT_3, paddingBottom: 6 }}>条</div>
      </div>
      {error ? (
        <button
          onClick={onRetry}
          style={{
            padding: '4px 10px', borderRadius: 5, border: `1px solid ${TEXT_4}44`,
            background: 'transparent', color: TEXT_4, fontSize: 11, cursor: 'pointer',
            alignSelf: 'flex-start',
          }}
        >
          重新加载
        </button>
      ) : (
        <div style={{ fontSize: 12, color: count > 0 ? YELLOW : TEXT_4 }}>
          {count > 0 ? `${count} 条AI建议等待审批` : '暂无待审批事项'}
        </div>
      )}
    </div>
  );
}

// 异常预警卡片
function AnomalyCard({
  count,
  loading,
  error,
  onRetry,
}: {
  count: number;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  if (loading) return <LoadingCard height={120} />;

  return (
    <div style={{
      background: BG_1, borderRadius: 12, padding: '20px',
      border: `1px solid ${error ? RED + '44' : count > 0 ? RED + '44' : BG_2}`,
      display: 'flex', flexDirection: 'column', gap: 10,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1 }}>当前异常</div>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8 }}>
        <div style={{
          fontSize: 42, fontWeight: 700,
          color: error ? TEXT_4 : count > 0 ? RED : GREEN,
        }}>
          {error ? '-' : count}
        </div>
        <div style={{ fontSize: 13, color: TEXT_3, paddingBottom: 6 }}>条</div>
      </div>
      {error ? (
        <button
          onClick={onRetry}
          style={{
            padding: '4px 10px', borderRadius: 5, border: `1px solid ${TEXT_4}44`,
            background: 'transparent', color: TEXT_4, fontSize: 11, cursor: 'pointer',
            alignSelf: 'flex-start',
          }}
        >
          重新加载
        </button>
      ) : (
        <div style={{ fontSize: 12, color: count > 0 ? RED : TEXT_4 }}>
          {count > 0 ? `${count} 条异常需要处理` : '运营状态正常'}
        </div>
      )}
    </div>
  );
}

// ---- 主页面 ----

export function DailyPlanPage() {
  const [date, setDate] = useState(todayStr());

  // E1-E8 节点状态
  const [nodeData, setNodeData] = useState<DailyReviewStatus | null>(null);
  const [nodeLoading, setNodeLoading] = useState(true);
  const [nodeError, setNodeError] = useState<string | null>(null);

  // 今日营收
  const [profitData, setProfitData] = useState<DailyProfitData | null>(null);
  const [profitLoading, setProfitLoading] = useState(true);
  const [profitError, setProfitError] = useState<string | null>(null);

  // 待审批数
  const [approvalCount, setApprovalCount] = useState(0);
  const [approvalLoading, setApprovalLoading] = useState(true);
  const [approvalError, setApprovalError] = useState<string | null>(null);

  // 异常数
  const [anomalyCount, setAnomalyCount] = useState(0);
  const [anomalyLoading, setAnomalyLoading] = useState(true);
  const [anomalyError, setAnomalyError] = useState<string | null>(null);

  const loadNodeStatus = useCallback(async () => {
    setNodeLoading(true);
    setNodeError(null);
    try {
      const data = await txFetchData<DailyReviewStatus>(
        `/api/v1/ops/daily-review/status?date=${encodeURIComponent(date)}`,
      );
      setNodeData(data);
    } catch (e) {
      setNodeError(e instanceof Error ? e.message : '未知错误');
      setNodeData(null);
    } finally {
      setNodeLoading(false);
    }
  }, [date]);

  const loadProfit = useCallback(async () => {
    setProfitLoading(true);
    setProfitError(null);
    try {
      const data = await txFetchData<DailyProfitData>(
        `/api/v1/finance/daily-profit?date=${encodeURIComponent(date)}`,
      );
      setProfitData(data);
    } catch (e) {
      setProfitError(e instanceof Error ? e.message : '未知错误');
      setProfitData(null);
    } finally {
      setProfitLoading(false);
    }
  }, [date]);

  const loadApprovalCount = useCallback(async () => {
    setApprovalLoading(true);
    setApprovalError(null);
    try {
      const data = await txFetchData<ApprovalCount>(
        `/api/v1/ops/approvals/count?date=${encodeURIComponent(date)}&status=pending`,
      );
      setApprovalCount(data.pending_count ?? 0);
    } catch {
      // 降级：显示0，不报错
      setApprovalCount(0);
      setApprovalError('接口不可用');
    } finally {
      setApprovalLoading(false);
    }
  }, [date]);

  const loadAnomalyCount = useCallback(async () => {
    setAnomalyLoading(true);
    setAnomalyError(null);
    try {
      const data = await txFetchData<AnomalyCount>(
        `/api/v1/ops/anomalies/count?date=${encodeURIComponent(date)}&status=open`,
      );
      setAnomalyCount(data.anomaly_count ?? 0);
    } catch {
      // 降级：显示0
      setAnomalyCount(0);
      setAnomalyError('接口不可用');
    } finally {
      setAnomalyLoading(false);
    }
  }, [date]);

  useEffect(() => {
    loadNodeStatus();
    loadProfit();
    loadApprovalCount();
    loadAnomalyCount();
  }, [loadNodeStatus, loadProfit, loadApprovalCount, loadAnomalyCount]);

  const handleDateChange = (newDate: string) => {
    setDate(newDate);
  };

  const isToday = date === todayStr();

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', background: BG_0, minHeight: '100vh', padding: '0 0 40px' }}>
      {/* 顶部标题栏 */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 24, flexWrap: 'wrap', gap: 12,
        padding: '20px 0 16px',
        borderBottom: `1px solid ${BG_2}`,
      }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: TEXT_1 }}>
              每日运营执行
            </h2>
            {isToday && (
              <span style={{
                padding: '3px 10px', borderRadius: 10,
                background: BRAND + '22', color: BRAND,
                fontSize: 11, fontWeight: 700,
              }}>今日</span>
            )}
          </div>
          <div style={{ fontSize: 15, color: TEXT_2, marginTop: 4, fontWeight: 500 }}>
            {formatDateTitle(date)}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <input
            type="date"
            value={date}
            onChange={e => handleDateChange(e.target.value)}
            style={{
              background: BG_1, border: `1px solid ${BG_2}`, borderRadius: 8,
              color: TEXT_2, padding: '6px 12px', fontSize: 13, outline: 'none',
              cursor: 'pointer',
            }}
          />
          <button
            onClick={() => {
              loadNodeStatus();
              loadProfit();
              loadApprovalCount();
              loadAnomalyCount();
            }}
            style={{
              padding: '8px 16px', borderRadius: 8, border: `1px solid ${BG_2}`,
              background: BG_1, color: TEXT_2, fontSize: 13, cursor: 'pointer',
              fontWeight: 600, transition: 'background .15s',
            }}
          >
            刷新
          </button>
        </div>
      </div>

      {/* 快速指标行 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 20 }}>
        {[
          {
            label: '今日日期',
            value: formatDateTitle(date),
            sub: isToday ? '今天' : '历史',
            color: BRAND,
            icon: '📅',
          },
          {
            label: 'E节点完成',
            value: nodeData
              ? `${nodeData.completed_count}/${nodeData.total_count}`
              : nodeLoading ? '...' : '-/-',
            sub: nodeData ? `完成率 ${Math.round((nodeData.completed_count / (nodeData.total_count || 1)) * 100)}%` : '',
            color: GREEN,
            icon: '✅',
          },
          {
            label: '待审批',
            value: approvalLoading ? '...' : String(approvalCount),
            sub: approvalCount > 0 ? '需要处理' : '全部清空',
            color: approvalCount > 0 ? YELLOW : GREEN,
            icon: '📋',
          },
          {
            label: '当前异常',
            value: anomalyLoading ? '...' : String(anomalyCount),
            sub: anomalyCount > 0 ? '需要处理' : '运营正常',
            color: anomalyCount > 0 ? RED : GREEN,
            icon: '⚠️',
          },
        ].map((item, i) => (
          <div key={i} style={{
            background: BG_1, borderRadius: 12, padding: '16px 18px',
            border: `1px solid ${BG_2}`,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <span style={{ fontSize: 18 }}>{item.icon}</span>
              <span style={{ fontSize: 12, color: TEXT_3 }}>{item.label}</span>
            </div>
            <div style={{ fontSize: 20, fontWeight: 700, color: item.color }}>{item.value}</div>
            {item.sub && (
              <div style={{ fontSize: 11, color: TEXT_4, marginTop: 2 }}>{item.sub}</div>
            )}
          </div>
        ))}
      </div>

      {/* 主要内容：2列布局 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
        {/* 左：E1-E8 节点状态 */}
        <NodeStatusCard
          data={nodeData}
          loading={nodeLoading}
          error={nodeError}
          onRetry={loadNodeStatus}
        />

        {/* 右：今日营收 */}
        <RevenueCard
          data={profitData}
          loading={profitLoading}
          error={profitError}
          onRetry={loadProfit}
        />
      </div>

      {/* 第二行：审批 + 异常 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <ApprovalCard
          count={approvalCount}
          loading={approvalLoading}
          error={approvalError}
          onRetry={loadApprovalCount}
        />
        <AnomalyCard
          count={anomalyCount}
          loading={anomalyLoading}
          error={anomalyError}
          onRetry={loadAnomalyCount}
        />
      </div>

      {/* 底部：数据来源说明 */}
      <div style={{
        marginTop: 20, padding: '12px 16px', borderRadius: 8,
        background: BG_1, border: `1px solid ${BG_2}`,
        display: 'flex', alignItems: 'center', gap: 8,
      }}>
        <span style={{ fontSize: 12, color: TEXT_4 }}>
          数据来源：
          <span style={{ color: TEXT_3 }}>/api/v1/ops/daily-review/status</span>
          <span style={{ margin: '0 8px', color: BG_2 }}>|</span>
          <span style={{ color: TEXT_3 }}>/api/v1/finance/daily-profit</span>
          <span style={{ margin: '0 8px', color: BG_2 }}>|</span>
          <span style={{ color: TEXT_3 }}>/api/v1/ops/approvals/count</span>
          <span style={{ margin: '0 8px', color: BG_2 }}>|</span>
          <span style={{ color: TEXT_3 }}>/api/v1/ops/anomalies/count</span>
        </span>
      </div>
    </div>
  );
}
