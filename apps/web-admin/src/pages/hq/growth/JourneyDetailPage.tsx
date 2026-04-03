/**
 * JourneyDetailPage — 旅程详情页
 * 路由: /hq/growth/journeys/:journeyId
 * 接入真实API：旅程基本信息、节点执行统计、执行日志、激活/暂停
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { txFetch } from '../../../api';

// ---- 颜色常量 ----
const BG_0 = '#0d1e28';
const BG_1 = '#112228';
const BG_2 = '#1a2a33';
const BRAND = '#FF6B2C';
const GREEN = '#52c41a';
const RED = '#ff4d4f';
const YELLOW = '#faad14';
const BLUE = '#1890ff';
const PURPLE = '#722ed1';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

// ---- 类型定义 ----

type JourneyStatus = 'active' | 'paused' | 'draft' | 'ended';

interface JourneyNode {
  id: string;
  type: 'trigger' | 'condition' | 'action' | 'wait';
  title: string;
  description: string;
  channel: string;
  executed_count: number;
  completion_rate: number;
  avg_wait_hours: number | null;
  drop_off_count: number;
}

interface JourneyKPI {
  total_reached: number;
  total_converted: number;
  conversion_rate: number;
  total_revenue: number;
  roi: number;
}

interface JourneyDetail {
  id: string;
  name: string;
  status: JourneyStatus;
  target_segment: string;
  target_count: number;
  executed_count: number;
  conversion_rate: number;
  total_revenue: number;
  roi: number;
  created_at: string;
  creator: string;
  nodes: JourneyNode[];
  kpi: JourneyKPI;
}

interface ExecutionLog {
  id: string;
  customer_id: string;
  customer_name: string;
  current_step: string;
  entered_at: string;
  last_action_at: string;
  status: 'in_progress' | 'completed' | 'exited';
  converted_value: number | null;
}

// ---- 辅助工具 ----

const STATUS_LABEL: Record<JourneyStatus, string> = {
  active: '运行中',
  paused: '已暂停',
  draft: '草稿',
  ended: '已结束',
};

const STATUS_COLOR: Record<JourneyStatus, string> = {
  active: GREEN,
  paused: YELLOW,
  draft: TEXT_4,
  ended: BLUE,
};

const LOG_STATUS_LABEL: Record<ExecutionLog['status'], string> = {
  in_progress: '进行中',
  completed: '已完成',
  exited: '已退出',
};

const LOG_STATUS_COLOR: Record<ExecutionLog['status'], string> = {
  in_progress: BLUE,
  completed: GREEN,
  exited: TEXT_4,
};

const NODE_TYPE_LABEL: Record<JourneyNode['type'], string> = {
  trigger: '触发条件',
  condition: '人群分支',
  action: '发送消息',
  wait: '等待',
};

const NODE_TYPE_COLOR: Record<JourneyNode['type'], string> = {
  trigger: BRAND,
  condition: PURPLE,
  action: BLUE,
  wait: TEXT_4,
};

// ---- 加载骨架 ----

function Skeleton({ width = '100%', height = 16 }: { width?: string | number; height?: number }) {
  return (
    <div style={{
      width, height, borderRadius: 4,
      background: `linear-gradient(90deg, ${BG_2} 25%, #223344 50%, ${BG_2} 75%)`,
      backgroundSize: '200% 100%',
      animation: 'shimmer 1.5s infinite',
    }} />
  );
}

// ---- 子组件：旅程元信息卡片 ----

function JourneyMetaCard({
  journey,
  onToggleStatus,
  statusLoading,
}: {
  journey: JourneyDetail;
  onToggleStatus: () => void;
  statusLoading: boolean;
}) {
  const statusLabel = STATUS_LABEL[journey.status] ?? journey.status;
  const statusColor = STATUS_COLOR[journey.status] ?? TEXT_4;
  const isActive = journey.status === 'active';

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '16px 20px',
      border: `1px solid ${BG_2}`, marginBottom: 16,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 18, fontWeight: 700, color: TEXT_1 }}>{journey.name}</span>
        <span style={{
          fontSize: 11, padding: '2px 10px', borderRadius: 10,
          background: statusColor + '22', color: statusColor, fontWeight: 700,
        }}>{statusLabel}</span>
        <span style={{ fontSize: 12, color: TEXT_4 }}>
          创建于 {journey.created_at} · {journey.creator}
        </span>
        <div style={{ flex: 1 }} />
        <button
          onClick={onToggleStatus}
          disabled={statusLoading || journey.status === 'ended' || journey.status === 'draft'}
          style={{
            padding: '6px 16px', borderRadius: 8, border: `1px solid ${isActive ? YELLOW + '44' : GREEN + '44'}`,
            background: isActive ? YELLOW + '11' : GREEN + '11',
            color: isActive ? YELLOW : GREEN,
            fontSize: 13, fontWeight: 600, cursor: statusLoading ? 'wait' : 'pointer',
            opacity: (journey.status === 'ended' || journey.status === 'draft') ? 0.4 : 1,
          }}
        >
          {statusLoading ? '处理中...' : isActive ? '暂停旅程' : '激活旅程'}
        </button>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 12 }}>
        {[
          { label: '目标人群', value: journey.target_segment, color: BRAND },
          { label: '目标人数', value: journey.target_count.toLocaleString(), color: TEXT_1 },
          { label: '已执行', value: journey.executed_count.toLocaleString(), color: TEXT_1 },
          {
            label: '转化率',
            value: `${journey.conversion_rate.toFixed(1)}%`,
            color: journey.conversion_rate >= 15 ? GREEN : YELLOW,
          },
          {
            label: '归因收益',
            value: journey.total_revenue >= 10000
              ? `¥${(journey.total_revenue / 10000).toFixed(1)}万`
              : `¥${journey.total_revenue.toLocaleString()}`,
            color: GREEN,
          },
          { label: 'ROI', value: `${journey.roi.toFixed(1)}x`, color: journey.roi >= 3 ? GREEN : YELLOW },
        ].map(item => (
          <div key={item.label}>
            <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 4 }}>{item.label}</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: item.color }}>{item.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---- 子组件：节点流程图 ----

function JourneyFlowChart({ nodes }: { nodes: JourneyNode[] }) {
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '20px 24px',
      border: `1px solid ${BG_2}`, flex: '0 0 380px', minWidth: 320,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 20 }}>旅程步骤流程</div>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        {nodes.map((node, idx) => {
          const color = NODE_TYPE_COLOR[node.type] ?? BLUE;
          const typeLabel = NODE_TYPE_LABEL[node.type] ?? node.type;
          const isHovered = hoveredId === node.id;

          return (
            <div key={node.id} style={{ width: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              {idx > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', margin: '4px 0' }}>
                  <div style={{ width: 2, height: 20, background: BG_2 }} />
                  <div style={{
                    width: 0, height: 0,
                    borderLeft: '5px solid transparent', borderRight: '5px solid transparent',
                    borderTop: `6px solid ${BG_2}`,
                  }} />
                </div>
              )}
              <div
                style={{
                  width: '100%', padding: '12px 14px', borderRadius: 8,
                  background: isHovered ? BG_2 : `${color}11`,
                  border: `1px solid ${color}44`,
                  cursor: 'default', transition: 'all .15s',
                  borderLeft: `3px solid ${color}`,
                }}
                onMouseEnter={() => setHoveredId(node.id)}
                onMouseLeave={() => setHoveredId(null)}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                  <span style={{
                    fontSize: 10, padding: '1px 6px', borderRadius: 4,
                    background: color + '22', color, fontWeight: 600,
                  }}>{typeLabel}</span>
                  {node.channel && node.channel !== '无' && node.channel !== 'none' && (
                    <span style={{
                      fontSize: 10, padding: '1px 6px', borderRadius: 4,
                      background: BLUE + '22', color: BLUE,
                    }}>{node.channel}</span>
                  )}
                  <span style={{ fontSize: 11, color: TEXT_4 }}>#{idx + 1}</span>
                </div>
                <div style={{ fontSize: 13, fontWeight: 600, color: TEXT_1, marginBottom: 2 }}>{node.title}</div>
                <div style={{ fontSize: 11, color: TEXT_3, marginBottom: 8 }}>{node.description}</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <div style={{ flex: 1, height: 4, borderRadius: 2, background: BG_2 }}>
                    <div style={{
                      width: `${Math.min(node.completion_rate, 100)}%`, height: '100%', borderRadius: 2,
                      background: node.completion_rate >= 90 ? GREEN : node.completion_rate >= 70 ? YELLOW : RED,
                    }} />
                  </div>
                  <span style={{ fontSize: 11, color: TEXT_3, minWidth: 34, textAlign: 'right' }}>
                    {node.completion_rate.toFixed(0)}%
                  </span>
                </div>
                <div style={{ display: 'flex', gap: 14, marginTop: 6, fontSize: 11, color: TEXT_4 }}>
                  <span>执行 <span style={{ color: TEXT_2 }}>{node.executed_count.toLocaleString()}</span></span>
                  {node.drop_off_count > 0 && (
                    <span>流失 <span style={{ color: RED }}>{node.drop_off_count.toLocaleString()}</span></span>
                  )}
                  {node.avg_wait_hours !== null && node.avg_wait_hours !== undefined && (
                    <span>
                      均等待 <span style={{ color: TEXT_2 }}>
                        {node.avg_wait_hours < 24
                          ? `${node.avg_wait_hours}h`
                          : `${(node.avg_wait_hours / 24).toFixed(0)}天`}
                      </span>
                    </span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---- 子组件：漏斗图 ----

function StepFunnelChart({ nodes }: { nodes: JourneyNode[] }) {
  const maxCount = nodes[0]?.executed_count ?? 1;

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '20px 24px',
      border: `1px solid ${BG_2}`, flex: 1, minWidth: 0,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 20 }}>漏斗分析</div>
      {nodes.map((node, idx) => {
        const barWidth = maxCount > 0 ? (node.executed_count / maxCount) * 100 : 0;
        const color = NODE_TYPE_COLOR[node.type] ?? BLUE;
        const prev = nodes[idx - 1];

        return (
          <div key={node.id} style={{ marginBottom: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
              <span style={{ fontSize: 11, color: TEXT_4, minWidth: 24 }}>S{idx + 1}</span>
              <span style={{
                fontSize: 12, color: TEXT_2, minWidth: 120,
                whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
              }}>{node.title}</span>
              <div style={{ flex: 1, height: 20, borderRadius: 4, background: BG_2, position: 'relative' }}>
                <div style={{
                  width: `${barWidth}%`, height: '100%', borderRadius: 4,
                  background: `linear-gradient(90deg, ${color}88, ${color}44)`,
                  display: 'flex', alignItems: 'center', paddingLeft: 6,
                  transition: 'width 0.4s ease',
                }}>
                  {barWidth > 20 && (
                    <span style={{ fontSize: 10, color: '#fff', fontWeight: 600 }}>
                      {node.executed_count.toLocaleString()}人
                    </span>
                  )}
                </div>
              </div>
              <span style={{ fontSize: 11, color: TEXT_3, minWidth: 36, textAlign: 'right' }}>
                {barWidth.toFixed(0)}%
              </span>
            </div>
            {idx > 0 && prev && prev.executed_count > 0 && (
              <div style={{ paddingLeft: 34, fontSize: 10, color: TEXT_4 }}>
                环节转化率:
                <span style={{
                  color: node.executed_count / prev.executed_count >= 0.9 ? GREEN : YELLOW,
                  marginLeft: 4,
                }}>
                  {((node.executed_count / prev.executed_count) * 100).toFixed(1)}%
                </span>
              </div>
            )}
          </div>
        );
      })}
      {nodes.length === 0 && (
        <div style={{ textAlign: 'center', color: TEXT_4, padding: '32px 0' }}>暂无节点数据</div>
      )}
    </div>
  );
}

// ---- 子组件：执行日志表格 ----

function ExecutionLogTable({ logs, loading }: { logs: ExecutionLog[]; loading: boolean }) {
  const [page, setPage] = useState(1);
  const pageSize = 10;
  const totalPages = Math.max(1, Math.ceil(logs.length / pageSize));
  const pagedLogs = logs.slice((page - 1) * pageSize, page * pageSize);

  if (loading) {
    return (
      <div style={{ background: BG_1, borderRadius: 10, padding: '16px 20px', border: `1px solid ${BG_2}` }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 14 }}>近期执行记录</div>
        {[...Array(5)].map((_, i) => (
          <div key={i} style={{ marginBottom: 10 }}>
            <Skeleton height={32} />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '16px 20px',
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1 }}>近期执行记录</div>
        <span style={{ fontSize: 12, color: TEXT_4 }}>最近 {logs.length} 条</span>
      </div>
      {logs.length === 0 ? (
        <div style={{ textAlign: 'center', color: TEXT_4, padding: '32px 0' }}>暂无执行记录</div>
      ) : (
        <>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${BG_2}` }}>
                  {['客户ID', '姓名', '当前步骤', '进入时间', '最后操作', '状态', '转化金额'].map(h => (
                    <th key={h} style={{
                      textAlign: 'left', padding: '8px 12px',
                      color: TEXT_4, fontWeight: 600, fontSize: 11, whiteSpace: 'nowrap',
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pagedLogs.map(log => (
                  <tr key={log.id} style={{ borderBottom: `1px solid ${BG_2}` }}>
                    <td style={{ padding: '10px 12px', color: TEXT_3 }}>{log.customer_id}</td>
                    <td style={{ padding: '10px 12px', color: TEXT_1, fontWeight: 500 }}>{log.customer_name}</td>
                    <td style={{ padding: '10px 12px', color: TEXT_2 }}>{log.current_step}</td>
                    <td style={{ padding: '10px 12px', color: TEXT_3, whiteSpace: 'nowrap' }}>{log.entered_at}</td>
                    <td style={{ padding: '10px 12px', color: TEXT_3, whiteSpace: 'nowrap' }}>{log.last_action_at}</td>
                    <td style={{ padding: '10px 12px' }}>
                      <span style={{
                        fontSize: 11, padding: '2px 8px', borderRadius: 10,
                        background: LOG_STATUS_COLOR[log.status] + '22',
                        color: LOG_STATUS_COLOR[log.status], fontWeight: 600,
                      }}>{LOG_STATUS_LABEL[log.status] ?? log.status}</span>
                    </td>
                    <td style={{ padding: '10px 12px' }}>
                      {log.converted_value != null
                        ? <span style={{ color: GREEN, fontWeight: 600 }}>¥{log.converted_value}</span>
                        : <span style={{ color: TEXT_4 }}>-</span>
                      }
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}>
            <span style={{ fontSize: 12, color: TEXT_4 }}>共 {logs.length} 条</span>
            <button
              disabled={page === 1}
              onClick={() => setPage(p => p - 1)}
              style={{
                padding: '4px 10px', borderRadius: 6, border: `1px solid ${BG_2}`,
                background: BG_2, color: page === 1 ? TEXT_4 : TEXT_2,
                fontSize: 12, cursor: page === 1 ? 'default' : 'pointer',
              }}
            >上一页</button>
            <span style={{ fontSize: 12, color: TEXT_3 }}>{page} / {totalPages}</span>
            <button
              disabled={page >= totalPages}
              onClick={() => setPage(p => p + 1)}
              style={{
                padding: '4px 10px', borderRadius: 6, border: `1px solid ${BG_2}`,
                background: BG_2, color: page >= totalPages ? TEXT_4 : TEXT_2,
                fontSize: 12, cursor: page >= totalPages ? 'default' : 'pointer',
              }}
            >下一页</button>
          </div>
        </>
      )}
    </div>
  );
}

// ---- 子组件：KPI 汇总卡片 ----

function KPICards({ kpi }: { kpi: JourneyKPI }) {
  const items = [
    { label: '总触达人数', value: kpi.total_reached.toLocaleString(), unit: '人', color: BLUE },
    { label: '总转化人数', value: kpi.total_converted.toLocaleString(), unit: '人', color: GREEN },
    { label: '整体转化率', value: kpi.conversion_rate.toFixed(1), unit: '%', color: kpi.conversion_rate >= 15 ? GREEN : YELLOW },
    {
      label: '归因收益',
      value: kpi.total_revenue >= 10000 ? (kpi.total_revenue / 10000).toFixed(1) : kpi.total_revenue.toLocaleString(),
      unit: kpi.total_revenue >= 10000 ? '万元' : '元',
      color: GREEN,
    },
    { label: 'ROI', value: kpi.roi.toFixed(1), unit: 'x', color: kpi.roi >= 3 ? GREEN : YELLOW },
  ];

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))',
      gap: 12, marginBottom: 16,
    }}>
      {items.map(item => (
        <div key={item.label} style={{
          background: BG_1, borderRadius: 10, padding: '16px 20px',
          border: `1px solid ${BG_2}`,
        }}>
          <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 6 }}>{item.label}</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
            <span style={{ fontSize: 24, fontWeight: 700, color: item.color }}>{item.value}</span>
            <span style={{ fontSize: 12, color: TEXT_4 }}>{item.unit}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

// ---- 错误提示 ----

function ErrorBanner({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div style={{
      background: RED + '11', border: `1px solid ${RED}33`,
      borderRadius: 10, padding: '16px 20px', marginBottom: 16,
      display: 'flex', alignItems: 'center', gap: 12,
    }}>
      <span style={{ color: RED, fontSize: 18 }}>⚠</span>
      <span style={{ color: RED, flex: 1, fontSize: 14 }}>{message}</span>
      <button
        onClick={onRetry}
        style={{
          padding: '6px 14px', borderRadius: 6, border: `1px solid ${RED}44`,
          background: RED + '11', color: RED, fontSize: 12, cursor: 'pointer',
        }}
      >重试</button>
    </div>
  );
}

// ---- 主页面 ----

export function JourneyDetailPage() {
  const { journeyId } = useParams<{ journeyId: string }>();
  const navigate = useNavigate();

  const [journey, setJourney] = useState<JourneyDetail | null>(null);
  const [logs, setLogs] = useState<ExecutionLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [logsLoading, setLogsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const [statusMsg, setStatusMsg] = useState('');

  const loadJourney = useCallback(async () => {
    if (!journeyId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await txFetch<JourneyDetail>(`/api/v1/member/journeys/${journeyId}`);
      setJourney(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载旅程数据失败');
    } finally {
      setLoading(false);
    }
  }, [journeyId]);

  const loadLogs = useCallback(async () => {
    if (!journeyId) return;
    setLogsLoading(true);
    try {
      const data = await txFetch<{ items: ExecutionLog[]; total: number }>(
        `/api/v1/member/journeys/${journeyId}/logs?size=100`
      );
      setLogs(data.items ?? []);
    } catch {
      setLogs([]);
    } finally {
      setLogsLoading(false);
    }
  }, [journeyId]);

  useEffect(() => {
    loadJourney();
    loadLogs();
  }, [loadJourney, loadLogs]);

  const handleToggleStatus = async () => {
    if (!journey || !journeyId) return;
    const newStatus: JourneyStatus = journey.status === 'active' ? 'paused' : 'active';
    setStatusLoading(true);
    try {
      const updated = await txFetch<JourneyDetail>(
        `/api/v1/member/journeys/${journeyId}/status`,
        {
          method: 'PATCH',
          body: JSON.stringify({ status: newStatus }),
        },
      );
      setJourney(prev => prev ? { ...prev, status: updated.status ?? newStatus } : prev);
      setStatusMsg(newStatus === 'active' ? '旅程已激活' : '旅程已暂停');
    } catch (err) {
      setStatusMsg(err instanceof Error ? err.message : '操作失败');
    } finally {
      setStatusLoading(false);
      setTimeout(() => setStatusMsg(''), 3000);
    }
  };

  // 加载中骨架屏
  if (loading) {
    return (
      <div style={{ maxWidth: 1400, margin: '0 auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
          <Skeleton width={80} height={32} />
          <Skeleton width={200} height={28} />
        </div>
        <div style={{ background: BG_1, borderRadius: 10, padding: '16px 20px', border: `1px solid ${BG_2}`, marginBottom: 16 }}>
          <Skeleton width={300} height={24} />
          <div style={{ marginTop: 16, display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 12 }}>
            {[...Array(6)].map((_, i) => <Skeleton key={i} height={40} />)}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 16, marginBottom: 16 }}>
          <div style={{ flex: '0 0 380px' }}>
            <Skeleton height={400} />
          </div>
          <div style={{ flex: 1 }}>
            <Skeleton height={400} />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto', background: BG_0, minHeight: '100vh', padding: '0 0 24px' }}>
      {/* 顶部导航 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
        <button
          onClick={() => navigate('/hq/growth/journeys')}
          style={{
            padding: '6px 14px', borderRadius: 6, border: `1px solid ${BG_2}`,
            background: 'transparent', color: TEXT_3, fontSize: 12, cursor: 'pointer',
          }}
        >← 返回列表</button>
        <span style={{ color: TEXT_4 }}>/</span>
        <span style={{ fontSize: 20, fontWeight: 700, color: TEXT_1 }}>旅程详情</span>
        {journey && (
          <span style={{ fontSize: 14, color: TEXT_3 }}>— {journey.name}</span>
        )}
        <div style={{ flex: 1 }} />
        {statusMsg && (
          <span style={{
            fontSize: 12, color: statusMsg.includes('失败') || statusMsg.includes('Error') ? RED : GREEN,
            padding: '4px 12px', borderRadius: 6, background: BG_2,
          }}>{statusMsg}</span>
        )}
        <button
          onClick={() => navigate(`/hq/growth/journeys/${journeyId}/canvas`)}
          style={{
            padding: '8px 18px', borderRadius: 8, border: 'none',
            background: BRAND, color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer',
          }}
        >编辑画布</button>
      </div>

      {/* 错误提示 */}
      {error && <ErrorBanner message={error} onRetry={loadJourney} />}

      {/* 内容区域 */}
      {journey && (
        <>
          {/* 旅程元信息卡片 */}
          <JourneyMetaCard
            journey={journey}
            onToggleStatus={handleToggleStatus}
            statusLoading={statusLoading}
          />

          {/* KPI汇总 */}
          {journey.kpi && <KPICards kpi={journey.kpi} />}

          {/* 流程图 + 漏斗图 */}
          {journey.nodes && journey.nodes.length > 0 ? (
            <div style={{ display: 'flex', gap: 16, marginBottom: 16, alignItems: 'flex-start' }}>
              <JourneyFlowChart nodes={journey.nodes} />
              <StepFunnelChart nodes={journey.nodes} />
            </div>
          ) : (
            <div style={{
              background: BG_1, borderRadius: 10, padding: '40px',
              border: `1px solid ${BG_2}`, marginBottom: 16,
              textAlign: 'center', color: TEXT_4,
            }}>
              暂无节点数据 —
              <span
                style={{ color: BRAND, cursor: 'pointer', marginLeft: 8 }}
                onClick={() => navigate(`/hq/growth/journeys/${journeyId}/canvas`)}
              >
                前往画布编辑
              </span>
            </div>
          )}

          {/* 执行日志 */}
          <ExecutionLogTable logs={logs} loading={logsLoading} />
        </>
      )}
    </div>
  );
}
