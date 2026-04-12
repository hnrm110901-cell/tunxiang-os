/**
 * 日清追踪 E1-E8 — DailyReviewPage
 * 运营节点监控仪表板，深色主题，与 EventBusHealthPage 风格一致
 */
import { useEffect, useState, useCallback } from 'react';
import { txFetchData } from '../../../api';

// ─── 类型定义 ───

type NodeStatus = 'pending' | 'in_progress' | 'completed' | 'overdue' | 'skipped';

interface DailyNode {
  node_id: string;
  name: string;
  deadline: string;      // "HH:MM"
  status: NodeStatus;
  completed_at: string | null;
  completed_by: string | null;
  notes: string | null;
}

interface DailyReviewData {
  date: string;
  store_id: string;
  completion_rate: number;
  health_score: number;
  overdue_count: number;
  nodes: DailyNode[];
}

interface MultiStoreSummaryItem {
  store_id: string;
  date: string;
  completion_rate: number;
  health_score: number;
  completed_count: number;
  overdue_count: number;
  nodes: { node_id: string; status: NodeStatus; name: string }[];
}

// ─── 常量 ───

const REFRESH_INTERVAL = 30_000;

// 模拟门店列表（实际应从 API 获取）
const DEMO_STORES = [
  { id: 'store_001', name: '尝在一起·芙蓉路店' },
  { id: 'store_002', name: '尝在一起·解放路店' },
  { id: 'store_003', name: '最黔线·五一广场店' },
  { id: 'store_004', name: '尚宫厨·天心店' },
];

const NODE_ICONS: Record<string, string> = {
  E1: '🌅', E2: '📦', E3: '🚪', E4: '📊',
  E5: '🔄', E6: '🌆', E7: '💰', E8: '📋',
};

// ─── 工具函数 ───

function getStatusConfig(status: NodeStatus): {
  label: string;
  color: string;
  bg: string;
  icon: string;
} {
  switch (status) {
    case 'completed':   return { label: '已完成', color: '#0F6E56', bg: '#0F6E5622', icon: '✅' };
    case 'overdue':     return { label: '已超时', color: '#FF4D4D', bg: '#FF4D4D22', icon: '⚠️' };
    case 'in_progress': return { label: '进行中', color: '#185FA5', bg: '#185FA522', icon: '🔵' };
    case 'skipped':     return { label: '已跳过', color: '#888',    bg: '#88888822', icon: '⏭️' };
    default:            return { label: '待完成', color: '#555',    bg: '#55555522', icon: '⏳' };
  }
}

function getHealthColor(score: number): string {
  if (score >= 70) return '#0F6E56';
  if (score >= 40) return '#BA7517';
  return '#FF4D4D';
}

function formatCompletedBy(by: string | null): string {
  if (!by) return '';
  if (by === 'system') return '系统自动';
  return by;
}

function formatTime(isoStr: string | null): string {
  if (!isoStr) return '';
  try {
    return new Date(isoStr).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

// ─── SVG 圆弧进度图 ───

function RingProgress({ rate, score }: { rate: number; score: number }) {
  const size = 140;
  const cx = size / 2;
  const cy = size / 2;
  const r = 52;
  const circumference = 2 * Math.PI * r;
  const dashOffset = circumference * (1 - rate);
  const color = getHealthColor(score);

  return (
    <svg width={size} height={size} style={{ display: 'block' }}>
      {/* 轨道 */}
      <circle
        cx={cx} cy={cy} r={r}
        fill="none"
        stroke="#2a3a44"
        strokeWidth={10}
      />
      {/* 进度弧 */}
      <circle
        cx={cx} cy={cy} r={r}
        fill="none"
        stroke={color}
        strokeWidth={10}
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={dashOffset}
        transform={`rotate(-90 ${cx} ${cy})`}
        style={{ transition: 'stroke-dashoffset 0.6s ease, stroke 0.4s ease' }}
      />
      {/* 完成率文字 */}
      <text
        x={cx} y={cy - 8}
        textAnchor="middle"
        dominantBaseline="middle"
        fill="#fff"
        fontSize={22}
        fontWeight={700}
      >
        {Math.round(rate * 100)}%
      </text>
      {/* 健康分 */}
      <text
        x={cx} y={cy + 16}
        textAnchor="middle"
        dominantBaseline="middle"
        fill={color}
        fontSize={12}
        fontWeight={600}
      >
        健康分 {score}
      </text>
    </svg>
  );
}

// ─── 手动完成弹窗 ───

interface CompleteModalProps {
  node: DailyNode;
  storeId: string;
  onClose: () => void;
  onSuccess: () => void;
}

function CompleteModal({ node, storeId, onClose, onSuccess }: CompleteModalProps) {
  const [notes, setNotes] = useState('');
  const [operatorId, setOperatorId] = useState('admin');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async () => {
    setLoading(true);
    setError('');
    try {
      await txFetchData('/api/v1/daily-review/complete-node', {
        method: 'POST',
        body: JSON.stringify({
          store_id: storeId,
          node_id: node.node_id,
          notes: notes || null,
          operator_id: operatorId,
        }),
      });
      onSuccess();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      zIndex: 1000,
    }}>
      <div style={{
        background: '#1a2a33', borderRadius: 12, padding: 24, width: 380,
        border: '1px solid #2a3a44',
      }}>
        <div style={{ fontSize: 16, fontWeight: 700, color: '#fff', marginBottom: 16 }}>
          {NODE_ICONS[node.node_id]} 手动完成 {node.node_id} · {node.name}
        </div>

        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 12, color: '#888', display: 'block', marginBottom: 4 }}>
            操作人 ID
          </label>
          <input
            value={operatorId}
            onChange={e => setOperatorId(e.target.value)}
            style={{
              width: '100%', padding: '8px 10px', borderRadius: 6,
              border: '1px solid #2a3a44', background: '#0d1e28',
              color: '#fff', fontSize: 13, outline: 'none', boxSizing: 'border-box',
            }}
          />
        </div>

        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 12, color: '#888', display: 'block', marginBottom: 4 }}>
            备注（可选）
          </label>
          <textarea
            value={notes}
            onChange={e => setNotes(e.target.value)}
            placeholder="说明完成情况..."
            rows={3}
            style={{
              width: '100%', padding: '8px 10px', borderRadius: 6,
              border: '1px solid #2a3a44', background: '#0d1e28',
              color: '#fff', fontSize: 13, outline: 'none',
              resize: 'vertical', boxSizing: 'border-box',
            }}
          />
        </div>

        {error && (
          <div style={{ color: '#FF4D4D', fontSize: 13, marginBottom: 12 }}>{error}</div>
        )}

        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button
            onClick={onClose}
            style={{
              padding: '8px 16px', borderRadius: 6, border: '1px solid #2a3a44',
              background: 'transparent', color: '#888', cursor: 'pointer', fontSize: 13,
            }}
          >
            取消
          </button>
          <button
            onClick={handleSubmit}
            disabled={loading || !operatorId.trim()}
            style={{
              padding: '8px 16px', borderRadius: 6, border: 'none',
              background: loading ? '#2a3a44' : '#0F6E56', color: '#fff',
              cursor: loading ? 'not-allowed' : 'pointer', fontSize: 13, fontWeight: 600,
            }}
          >
            {loading ? '提交中...' : '确认完成'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── 主页面 ───

export function DailyReviewPage() {
  const [tab, setTab] = useState<'single' | 'multi'>('single');
  const [selectedStore, setSelectedStore] = useState(DEMO_STORES[0].id);
  const [reviewData, setReviewData] = useState<DailyReviewData | null>(null);
  const [multiData, setMultiData] = useState<MultiStoreSummaryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState(new Date());
  const [countdown, setCountdown] = useState(REFRESH_INTERVAL / 1000);
  const [completingNode, setCompletingNode] = useState<DailyNode | null>(null);

  const fetchSingle = useCallback(async (storeId: string) => {
    try {
      const data = await txFetchData<DailyReviewData>(
        `/api/v1/daily-review/today?store_id=${encodeURIComponent(storeId)}`,
      );
      setReviewData(data);
      setLastRefresh(new Date());
      setCountdown(REFRESH_INTERVAL / 1000);
    } catch {
      /* 保留旧数据 */
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchMulti = useCallback(async () => {
    try {
      const ids = DEMO_STORES.map(s => s.id).join(',');
      const res = await txFetchData<{ items: MultiStoreSummaryItem[] }>(
        `/api/v1/daily-review/multi-store?store_ids=${encodeURIComponent(ids)}`,
      );
      setMultiData(res.items);
      setLastRefresh(new Date());
      setCountdown(REFRESH_INTERVAL / 1000);
    } catch {
      /* 保留旧数据 */
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchData = useCallback(async () => {
    setLoading(true);
    if (tab === 'single') {
      await fetchSingle(selectedStore);
    } else {
      await fetchMulti();
    }
  }, [tab, selectedStore, fetchSingle, fetchMulti]);

  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, REFRESH_INTERVAL);
    return () => clearInterval(timer);
  }, [fetchData]);

  useEffect(() => {
    const timer = setInterval(() => setCountdown(c => Math.max(0, c - 1)), 1000);
    return () => clearInterval(timer);
  }, [lastRefresh]);

  const storeName = DEMO_STORES.find(s => s.id === selectedStore)?.name ?? selectedStore;

  // 多门店汇总：按完成率升序（最差在上）
  const sortedMulti = [...multiData].sort((a, b) => a.completion_rate - b.completion_rate);

  return (
    <div style={{ padding: 24, minHeight: '100vh', background: '#0d1e28', color: '#fff' }}>
      {/* ── 页头 ── */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>📅 日清追踪 E1–E8</h2>
          <p style={{ color: '#888', margin: '4px 0 0', fontSize: 13 }}>
            运营节点实时状态 · 每日8个闭环节点
          </p>
        </div>
        <div style={{ textAlign: 'right' }}>
          <button
            onClick={fetchData}
            style={{
              padding: '6px 14px', borderRadius: 6, border: '1px solid #2a3a44',
              background: 'transparent', color: '#888', cursor: 'pointer', fontSize: 13,
              display: 'block', marginBottom: 4, marginLeft: 'auto',
            }}
          >
            ↻ 立即刷新
          </button>
          <div style={{ color: '#888', fontSize: 12 }}>
            {countdown}s 后自动刷新 · 上次 {lastRefresh.toLocaleTimeString('zh-CN')}
          </div>
        </div>
      </div>

      {/* ── Tab 切换 ── */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        {(['single', 'multi'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              padding: '7px 18px', borderRadius: 8, fontSize: 13, fontWeight: 600,
              border: 'none', cursor: 'pointer',
              background: tab === t ? '#0F6E56' : '#1a2a33',
              color: tab === t ? '#fff' : '#888',
            }}
          >
            {t === 'single' ? '单店视图' : '多店汇总'}
          </button>
        ))}
      </div>

      {/* ── 单店视图 ── */}
      {tab === 'single' && (
        <>
          {/* 门店选择 */}
          <div style={{ marginBottom: 20 }}>
            <select
              value={selectedStore}
              onChange={e => setSelectedStore(e.target.value)}
              style={{
                padding: '8px 14px', borderRadius: 8, border: '1px solid #2a3a44',
                background: '#1a2a33', color: '#fff', fontSize: 13,
                outline: 'none', cursor: 'pointer',
              }}
            >
              {DEMO_STORES.map(s => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          </div>

          {loading ? (
            <div style={{ textAlign: 'center', padding: 60, color: '#888' }}>加载中...</div>
          ) : reviewData ? (
            <>
              {/* 今日进度卡片 */}
              <div style={{
                background: '#1a2a33', borderRadius: 12, padding: 24, marginBottom: 20,
                border: '1px solid #2a3a44',
                display: 'flex', alignItems: 'center', gap: 32,
              }}>
                <RingProgress rate={reviewData.completion_rate} score={reviewData.health_score} />

                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, color: '#888', marginBottom: 6 }}>
                    {storeName} · {reviewData.date}
                  </div>
                  <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
                    <div>
                      <div style={{ fontSize: 28, fontWeight: 700, color: getHealthColor(reviewData.health_score) }}>
                        {reviewData.health_score}
                      </div>
                      <div style={{ fontSize: 12, color: '#888' }}>经营健康分</div>
                    </div>
                    <div>
                      <div style={{ fontSize: 28, fontWeight: 700, color: '#fff' }}>
                        {reviewData.nodes.filter(n => n.status === 'completed').length}
                        <span style={{ fontSize: 16, color: '#888', fontWeight: 400 }}>/{reviewData.nodes.length}</span>
                      </div>
                      <div style={{ fontSize: 12, color: '#888' }}>已完成节点</div>
                    </div>
                    {reviewData.overdue_count > 0 && (
                      <div style={{
                        background: '#FF4D4D22', border: '1px solid #FF4D4D44',
                        borderRadius: 8, padding: '8px 16px',
                        display: 'flex', alignItems: 'center', gap: 8,
                      }}>
                        <span style={{ fontSize: 18 }}>⚠️</span>
                        <div>
                          <div style={{ fontSize: 18, fontWeight: 700, color: '#FF4D4D' }}>
                            {reviewData.overdue_count}
                          </div>
                          <div style={{ fontSize: 12, color: '#FF4D4D' }}>超时节点</div>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* E1-E8 时间轴 */}
              <div style={{ background: '#1a2a33', borderRadius: 12, overflow: 'hidden', border: '1px solid #2a3a44' }}>
                <div style={{
                  padding: '14px 20px', borderBottom: '1px solid #2a3a44',
                  fontSize: 14, color: '#888',
                }}>
                  今日节点进度
                </div>

                {reviewData.nodes.map((node, idx) => {
                  const sc = getStatusConfig(node.status);
                  const isOverdue = node.status === 'overdue';
                  const canComplete = node.status === 'pending' || node.status === 'overdue';
                  const nodeIcon = NODE_ICONS[node.node_id] ?? '📌';
                  const isLast = idx === reviewData.nodes.length - 1;

                  return (
                    <div
                      key={node.node_id}
                      style={{
                        display: 'flex', alignItems: 'flex-start', gap: 16,
                        padding: '16px 20px',
                        background: isOverdue ? '#FF4D4D11' : 'transparent',
                        borderBottom: isLast ? 'none' : '1px solid #2a3a4430',
                        transition: 'background 0.2s',
                      }}
                    >
                      {/* 节点编号 + 竖线 */}
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 40, flexShrink: 0 }}>
                        <div style={{
                          width: 36, height: 36, borderRadius: '50%',
                          background: sc.bg, border: `2px solid ${sc.color}`,
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                          fontSize: 13, fontWeight: 700, color: sc.color,
                        }}>
                          {node.node_id}
                        </div>
                        {!isLast && (
                          <div style={{
                            width: 2, height: 16, marginTop: 4,
                            background: '#2a3a44',
                          }} />
                        )}
                      </div>

                      {/* 节点信息 */}
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                          <span style={{ fontSize: 16 }}>{nodeIcon}</span>
                          <span style={{ fontWeight: 600, fontSize: 15, color: '#fff' }}>{node.name}</span>
                          <span style={{ fontSize: 12, color: '#888' }}>截止 {node.deadline}</span>
                          <span style={{
                            fontSize: 11, padding: '2px 8px', borderRadius: 10,
                            background: sc.bg, color: sc.color, fontWeight: 600,
                          }}>
                            {sc.icon} {sc.label}
                          </span>
                          {isOverdue && (
                            <span style={{
                              fontSize: 11, padding: '2px 8px', borderRadius: 10,
                              background: '#FF4D4D33', color: '#FF4D4D', fontWeight: 600,
                            }}>
                              超时未完成
                            </span>
                          )}
                        </div>

                        {node.status === 'completed' && node.completed_at && (
                          <div style={{ fontSize: 12, color: '#888' }}>
                            {formatTime(node.completed_at)} 完成
                            {node.completed_by && (
                              <span style={{ marginLeft: 8, color: '#0F6E56' }}>
                                {formatCompletedBy(node.completed_by)}
                              </span>
                            )}
                            {node.notes && (
                              <span style={{ marginLeft: 8, color: '#999', fontStyle: 'italic' }}>
                                · {node.notes}
                              </span>
                            )}
                          </div>
                        )}
                      </div>

                      {/* 手动完成按钮 */}
                      {canComplete && (
                        <button
                          onClick={() => setCompletingNode(node)}
                          style={{
                            padding: '6px 14px', borderRadius: 6, fontSize: 12, fontWeight: 600,
                            border: `1px solid ${isOverdue ? '#FF4D4D' : '#0F6E56'}`,
                            background: 'transparent',
                            color: isOverdue ? '#FF4D4D' : '#0F6E56',
                            cursor: 'pointer', flexShrink: 0,
                            whiteSpace: 'nowrap',
                          }}
                        >
                          ✓ 手动完成
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>

              {/* 图例 */}
              <div style={{ display: 'flex', gap: 20, marginTop: 14, color: '#888', fontSize: 12, flexWrap: 'wrap' }}>
                <span>● <span style={{ color: '#0F6E56' }}>已完成</span></span>
                <span>● <span style={{ color: '#185FA5' }}>进行中</span></span>
                <span>● <span style={{ color: '#555' }}>待完成</span></span>
                <span>● <span style={{ color: '#FF4D4D' }}>超时未完成</span></span>
              </div>
            </>
          ) : (
            <div style={{ textAlign: 'center', padding: 60, color: '#888' }}>暂无数据</div>
          )}
        </>
      )}

      {/* ── 多门店汇总视图 ── */}
      {tab === 'multi' && (
        <>
          {loading ? (
            <div style={{ textAlign: 'center', padding: 60, color: '#888' }}>加载中...</div>
          ) : (
            <div style={{ background: '#1a2a33', borderRadius: 12, overflow: 'hidden', border: '1px solid #2a3a44' }}>
              <div style={{
                padding: '14px 20px', borderBottom: '1px solid #2a3a44',
                fontSize: 14, color: '#888', display: 'flex', justifyContent: 'space-between',
              }}>
                <span>各门店日清汇总（按完成率升序，最差在上）</span>
                <span>{sortedMulti[0]?.date}</span>
              </div>

              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ background: '#0d1e28' }}>
                    {['门店', '完成率', '健康分', '已完成', '超时节点', 'E1-E8 节点状态'].map(h => (
                      <th key={h} style={{
                        padding: '10px 16px', textAlign: 'left',
                        color: '#888', fontSize: 12, fontWeight: 500,
                      }}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sortedMulti.map(item => {
                    const storeInfo = DEMO_STORES.find(s => s.id === item.store_id);
                    const pct = Math.round(item.completion_rate * 100);
                    const isRed = pct < 50;
                    const healthColor = getHealthColor(item.health_score);

                    return (
                      <tr
                        key={item.store_id}
                        style={{
                          borderBottom: '1px solid #2a3a4440',
                          background: isRed ? '#FF4D4D0A' : 'transparent',
                        }}
                      >
                        <td style={{ padding: '14px 16px' }}>
                          <div style={{ fontWeight: 600, color: '#fff', fontSize: 14 }}>
                            {storeInfo?.name ?? item.store_id}
                          </div>
                          {isRed && (
                            <div style={{ fontSize: 11, color: '#FF4D4D', marginTop: 2 }}>
                              ⚠️ 完成率偏低
                            </div>
                          )}
                        </td>
                        <td style={{ padding: '14px 16px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <span style={{ fontSize: 18, fontWeight: 700, color: getHealthColor(item.health_score) }}>
                              {pct}%
                            </span>
                          </div>
                          <div style={{
                            marginTop: 6, height: 4, width: 80,
                            background: '#0d1e28', borderRadius: 2, overflow: 'hidden',
                          }}>
                            <div style={{
                              width: `${pct}%`, height: '100%', borderRadius: 2,
                              background: healthColor, transition: 'width 0.4s ease',
                            }} />
                          </div>
                        </td>
                        <td style={{ padding: '14px 16px' }}>
                          <span style={{ fontSize: 18, fontWeight: 700, color: healthColor }}>
                            {item.health_score}
                          </span>
                        </td>
                        <td style={{ padding: '14px 16px' }}>
                          <span style={{ color: '#0F6E56', fontWeight: 600 }}>{item.completed_count}</span>
                          <span style={{ color: '#888' }}>/8</span>
                        </td>
                        <td style={{ padding: '14px 16px' }}>
                          {item.overdue_count > 0 ? (
                            <span style={{
                              padding: '2px 10px', borderRadius: 10,
                              background: '#FF4D4D22', color: '#FF4D4D',
                              fontSize: 12, fontWeight: 600,
                            }}>
                              {item.overdue_count} 超时
                            </span>
                          ) : (
                            <span style={{ color: '#0F6E56', fontSize: 13 }}>✓ 无超时</span>
                          )}
                        </td>
                        <td style={{ padding: '14px 16px' }}>
                          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                            {item.nodes.map(n => {
                              const sc = getStatusConfig(n.status);
                              return (
                                <span
                                  key={n.node_id}
                                  title={`${n.node_id} ${n.name}: ${sc.label}`}
                                  style={{
                                    width: 28, height: 28, borderRadius: 6,
                                    background: sc.bg, border: `1px solid ${sc.color}`,
                                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                                    fontSize: 10, fontWeight: 700, color: sc.color,
                                    cursor: 'default',
                                  }}
                                >
                                  {n.node_id.replace('E', '')}
                                </span>
                              );
                            })}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                  {sortedMulti.length === 0 && (
                    <tr>
                      <td colSpan={6} style={{ padding: 40, textAlign: 'center', color: '#888' }}>
                        暂无数据
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {/* ── 手动完成弹窗 ── */}
      {completingNode && (
        <CompleteModal
          node={completingNode}
          storeId={selectedStore}
          onClose={() => setCompletingNode(null)}
          onSuccess={() => fetchSingle(selectedStore)}
        />
      )}
    </div>
  );
}
