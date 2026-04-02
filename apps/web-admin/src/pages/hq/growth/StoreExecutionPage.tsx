/**
 * StoreExecutionPage — 门店执行中心
 * 路由: /hq/growth/execution
 * 接入真实API：/api/v1/ops/daily-review/status 获取各门店E1-E8完成状态
 * 支持按门店筛选，执行评分按E1-E8完成率计算
 */
import { useState, useEffect, useCallback } from 'react';
import { txFetch } from '../../../api';

// ---- 颜色常量 ----
const BG_0 = '#0d1e28';
const BG_1 = '#1a2a33';
const BG_2 = '#243443';
const BRAND = '#FF6B35';
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

interface NodeStatus {
  node_id: string;
  node_name: string;
  status: 'completed' | 'in_progress' | 'pending' | 'skipped' | 'error';
  completed_at?: string;
  score?: number;
  detail?: string;
}

interface StoreReviewStatus {
  date: string;
  store_id: string;
  store_name: string;
  region?: string;
  overall_score: number;
  nodes: NodeStatus[];
  completed_count: number;
  total_count: number;
}

interface AllStoresReviewResponse {
  date: string;
  items: StoreReviewStatus[];
  total: number;
}

// ---- 工具函数 ----

const todayStr = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

const calcScore = (nodes: NodeStatus[]): number => {
  if (!nodes || nodes.length === 0) return 0;
  const completed = nodes.filter(n => n.status === 'completed').length;
  const total = nodes.length;
  const base = Math.round((completed / total) * 100);
  // 加权：error节点扣分
  const errorCount = nodes.filter(n => n.status === 'error').length;
  return Math.max(0, base - errorCount * 5);
};

const NODE_NAMES: Record<string, string> = {
  E1: '开市', E2: '目标', E3: '午市', E4: '午复',
  E5: '晚备', E6: '晚市', E7: '收市', E8: '日结',
};

// ---- Tab 类型 ----

type TabKey = 'overview' | 'store_nodes' | 'ranking' | 'anomalies';

// ---- 子组件 ----

function LoadingSpinner() {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: 40, color: TEXT_4, fontSize: 14,
    }}>
      加载中...
    </div>
  );
}

function ErrorDisplay({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div style={{
      padding: '20px', borderRadius: 10,
      background: BG_1, border: `1px solid ${RED}44`,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    }}>
      <div>
        <div style={{ color: RED, fontWeight: 600, fontSize: 13 }}>数据加载失败</div>
        <div style={{ color: TEXT_4, fontSize: 12, marginTop: 4 }}>{message}</div>
      </div>
      <button
        onClick={onRetry}
        style={{
          padding: '6px 16px', borderRadius: 6, border: `1px solid ${RED}66`,
          background: 'transparent', color: RED, fontSize: 12, cursor: 'pointer',
          fontWeight: 600,
        }}
      >
        重试
      </button>
    </div>
  );
}

// 门店筛选器
function StoreFilter({
  stores,
  selectedStore,
  onSelect,
}: {
  stores: StoreReviewStatus[];
  selectedStore: string;
  onSelect: (id: string) => void;
}) {
  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
      <button
        onClick={() => onSelect('all')}
        style={{
          padding: '6px 14px', borderRadius: 8, border: 'none', cursor: 'pointer',
          background: selectedStore === 'all' ? BRAND : BG_2,
          color: selectedStore === 'all' ? '#fff' : TEXT_3,
          fontSize: 12, fontWeight: 600, transition: 'all .15s',
        }}
      >
        全部门店
      </button>
      {stores.map(s => (
        <button
          key={s.store_id}
          onClick={() => onSelect(s.store_id)}
          style={{
            padding: '6px 14px', borderRadius: 8, border: 'none', cursor: 'pointer',
            background: selectedStore === s.store_id ? BRAND : BG_2,
            color: selectedStore === s.store_id ? '#fff' : TEXT_3,
            fontSize: 12, fontWeight: 600, transition: 'all .15s',
          }}
        >
          {s.store_name}
        </button>
      ))}
    </div>
  );
}

// 汇总指标卡片
function SummaryCards({ stores }: { stores: StoreReviewStatus[] }) {
  const total = stores.length;
  const avgScore = total > 0
    ? Math.round(stores.reduce((s, st) => s + calcScore(st.nodes), 0) / total)
    : 0;
  const allCompleted = stores.filter(st => st.completed_count === st.total_count).length;
  const hasError = stores.filter(st => st.nodes?.some(n => n.status === 'error')).length;

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 20 }}>
      {[
        { label: '参与门店', value: total, color: TEXT_1, icon: '🏪' },
        { label: '平均执行分', value: avgScore, color: avgScore >= 85 ? GREEN : avgScore >= 70 ? YELLOW : RED, icon: '📊' },
        { label: '全节点完成', value: allCompleted, color: GREEN, icon: '✅' },
        { label: '有异常门店', value: hasError, color: hasError > 0 ? RED : TEXT_4, icon: '⚠️' },
      ].map((item, i) => (
        <div key={i} style={{
          background: BG_1, borderRadius: 12, padding: '16px 18px',
          border: `1px solid ${BG_2}`,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <span style={{ fontSize: 18 }}>{item.icon}</span>
            <span style={{ fontSize: 12, color: TEXT_3 }}>{item.label}</span>
          </div>
          <div style={{ fontSize: 28, fontWeight: 700, color: item.color }}>{item.value}</div>
        </div>
      ))}
    </div>
  );
}

// 门店E节点详情表
function StoreNodesTable({ stores, selectedStore }: { stores: StoreReviewStatus[]; selectedStore: string }) {
  const filtered = selectedStore === 'all' ? stores : stores.filter(s => s.store_id === selectedStore);

  const statusDot = (status: string) => {
    const colors: Record<string, string> = {
      completed: GREEN, in_progress: BLUE, pending: TEXT_4, skipped: TEXT_4, error: RED,
    };
    return <span style={{
      display: 'inline-block', width: 8, height: 8, borderRadius: 4,
      background: colors[status] || TEXT_4,
    }} />;
  };

  const nodeKeys = ['E1', 'E2', 'E3', 'E4', 'E5', 'E6', 'E7', 'E8'];

  return (
    <div style={{ background: BG_1, borderRadius: 12, padding: 16, border: `1px solid ${BG_2}` }}>
      <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>
        门店 E1-E8 节点执行状态
      </h3>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, minWidth: 700 }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${BG_2}` }}>
              <th style={{ textAlign: 'left', padding: '8px 10px', color: TEXT_4, fontWeight: 600, fontSize: 11 }}>门店</th>
              {nodeKeys.map(k => (
                <th key={k} style={{ textAlign: 'center', padding: '8px 6px', color: TEXT_4, fontWeight: 600, fontSize: 11, minWidth: 54 }}>
                  <div>{k}</div>
                  <div style={{ fontWeight: 400, fontSize: 9, color: TEXT_4 }}>{NODE_NAMES[k]}</div>
                </th>
              ))}
              <th style={{ textAlign: 'center', padding: '8px 10px', color: TEXT_4, fontWeight: 600, fontSize: 11 }}>完成率</th>
              <th style={{ textAlign: 'center', padding: '8px 10px', color: TEXT_4, fontWeight: 600, fontSize: 11 }}>评分</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(store => {
              const nodeMap = new Map(store.nodes?.map(n => [n.node_id.toUpperCase(), n]));
              const score = calcScore(store.nodes ?? []);
              const completedCount = store.nodes?.filter(n => n.status === 'completed').length ?? 0;
              const totalCount = store.nodes?.length ?? 8;
              const pct = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;

              return (
                <tr key={store.store_id} style={{ borderBottom: `1px solid ${BG_2}` }}>
                  <td style={{ padding: '10px', color: TEXT_1, fontWeight: 500, whiteSpace: 'nowrap' }}>
                    {store.store_name}
                  </td>
                  {nodeKeys.map(k => {
                    const node = nodeMap.get(k);
                    const status = node?.status ?? 'pending';
                    const colors: Record<string, string> = {
                      completed: GREEN, in_progress: BLUE, pending: TEXT_4, skipped: TEXT_4, error: RED,
                    };
                    const labels: Record<string, string> = {
                      completed: '✓', in_progress: '⟳', pending: '·', skipped: '—', error: '✗',
                    };
                    return (
                      <td key={k} style={{ padding: '10px 6px', textAlign: 'center' }}>
                        <span
                          title={node?.detail || status}
                          style={{ color: colors[status], fontSize: 14, fontWeight: 700 }}
                        >
                          {labels[status] || '·'}
                        </span>
                      </td>
                    );
                  })}
                  <td style={{ padding: '10px', textAlign: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'center' }}>
                      <div style={{ width: 48, height: 4, borderRadius: 2, background: BG_2 }}>
                        <div style={{
                          width: `${pct}%`, height: '100%', borderRadius: 2,
                          background: pct >= 80 ? GREEN : pct >= 50 ? YELLOW : RED,
                        }} />
                      </div>
                      <span style={{ fontSize: 11, color: TEXT_3 }}>{pct}%</span>
                    </div>
                  </td>
                  <td style={{ padding: '10px', textAlign: 'center' }}>
                    <span style={{
                      fontSize: 13, fontWeight: 700,
                      color: score >= 85 ? GREEN : score >= 70 ? YELLOW : RED,
                    }}>
                      {score}
                    </span>
                  </td>
                </tr>
              );
            })}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={11} style={{ padding: '24px', textAlign: 'center', color: TEXT_4 }}>
                  暂无数据
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* 图例 */}
      <div style={{
        marginTop: 12, display: 'flex', gap: 16, flexWrap: 'wrap',
        padding: '8px 10px', background: BG_2, borderRadius: 6,
      }}>
        {[
          { symbol: '✓', label: '已完成', color: GREEN },
          { symbol: '⟳', label: '进行中', color: BLUE },
          { symbol: '·', label: '待执行', color: TEXT_4 },
          { symbol: '—', label: '已跳过', color: TEXT_4 },
          { symbol: '✗', label: '异常', color: RED },
        ].map(item => (
          <div key={item.label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ color: item.color, fontSize: 13, fontWeight: 700 }}>{item.symbol}</span>
            <span style={{ fontSize: 11, color: TEXT_4 }}>{item.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// 门店排名
function StoreRanking({ stores }: { stores: StoreReviewStatus[] }) {
  const ranked = [...stores]
    .map(s => ({
      ...s,
      score: calcScore(s.nodes ?? []),
      completionRate: s.total_count > 0
        ? Math.round((s.completed_count / s.total_count) * 100)
        : 0,
    }))
    .sort((a, b) => b.score - a.score);

  return (
    <div style={{ background: BG_1, borderRadius: 12, padding: 16, border: `1px solid ${BG_2}` }}>
      <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>
        门店执行评分排名
      </h3>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ borderBottom: `1px solid ${BG_2}` }}>
            {['排名', '门店', '区域', '完成节点', '完成率', 'E节点完成率', '综合评分'].map(h => (
              <th key={h} style={{ textAlign: 'left', padding: '8px 10px', color: TEXT_4, fontWeight: 600, fontSize: 11 }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ranked.map((s, i) => (
            <tr key={s.store_id} style={{ borderBottom: `1px solid ${BG_2}` }}>
              <td style={{ padding: '10px' }}>
                <span style={{
                  width: 24, height: 24, borderRadius: 12,
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 11, fontWeight: 700,
                  background: i < 3 ? BRAND + '22' : BG_2,
                  color: i < 3 ? BRAND : TEXT_4,
                }}>
                  {i + 1}
                </span>
              </td>
              <td style={{ padding: '10px', color: TEXT_1, fontWeight: 500 }}>{s.store_name}</td>
              <td style={{ padding: '10px', color: TEXT_3 }}>{s.region || '—'}</td>
              <td style={{ padding: '10px', color: TEXT_2 }}>
                {s.completed_count}/{s.total_count}
              </td>
              <td style={{ padding: '10px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <div style={{ width: 60, height: 4, borderRadius: 2, background: BG_2 }}>
                    <div style={{
                      width: `${s.completionRate}%`, height: '100%', borderRadius: 2,
                      background: s.completionRate >= 80 ? GREEN : s.completionRate >= 50 ? YELLOW : RED,
                    }} />
                  </div>
                  <span style={{ fontSize: 11, color: TEXT_3 }}>{s.completionRate}%</span>
                </div>
              </td>
              <td style={{ padding: '10px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  {(['E1','E2','E3','E4','E5','E6','E7','E8']).map(k => {
                    const node = s.nodes?.find(n => n.node_id.toUpperCase() === k);
                    const status = node?.status ?? 'pending';
                    const colors: Record<string, string> = {
                      completed: GREEN, in_progress: BLUE, pending: BG_2, skipped: BG_2, error: RED,
                    };
                    return (
                      <div key={k} title={k} style={{
                        width: 10, height: 10, borderRadius: 2,
                        background: colors[status] || BG_2,
                      }} />
                    );
                  })}
                </div>
              </td>
              <td style={{ padding: '10px' }}>
                <span style={{
                  fontSize: 15, fontWeight: 700,
                  color: s.score >= 85 ? GREEN : s.score >= 70 ? YELLOW : RED,
                }}>
                  {s.score}
                </span>
              </td>
            </tr>
          ))}
          {ranked.length === 0 && (
            <tr>
              <td colSpan={7} style={{ padding: '24px', textAlign: 'center', color: TEXT_4 }}>
                暂无数据
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// 异常节点面板
function AnomalyPanel({ stores, selectedStore }: { stores: StoreReviewStatus[]; selectedStore: string }) {
  const filtered = selectedStore === 'all' ? stores : stores.filter(s => s.store_id === selectedStore);

  const anomalies: Array<{
    store: StoreReviewStatus;
    node: NodeStatus;
  }> = [];

  for (const store of filtered) {
    for (const node of store.nodes ?? []) {
      if (node.status === 'error') {
        anomalies.push({ store, node });
      }
    }
  }

  return (
    <div style={{ background: BG_1, borderRadius: 12, padding: 16, border: `1px solid ${BG_2}` }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: TEXT_1 }}>异常节点</h3>
        {anomalies.length > 0 && (
          <span style={{
            padding: '2px 8px', borderRadius: 8,
            background: RED + '22', color: RED, fontSize: 11, fontWeight: 700,
          }}>
            {anomalies.length} 个异常
          </span>
        )}
      </div>

      {anomalies.length === 0 ? (
        <div style={{
          padding: '32px', textAlign: 'center',
          color: GREEN, fontSize: 14,
        }}>
          <div style={{ fontSize: 32, marginBottom: 8 }}>✓</div>
          <div>所有门店节点运行正常</div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {anomalies.map(({ store, node }, i) => (
            <div key={i} style={{
              padding: '12px 14px', background: BG_2, borderRadius: 8,
              borderLeft: `3px solid ${RED}`,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{
                    padding: '2px 8px', borderRadius: 4,
                    background: RED + '22', color: RED, fontSize: 11, fontWeight: 700,
                  }}>
                    {node.node_id.toUpperCase()}
                  </span>
                  <span style={{ fontSize: 13, fontWeight: 600, color: TEXT_1 }}>
                    {NODE_NAMES[node.node_id.toUpperCase()] || node.node_name}
                  </span>
                </div>
                <span style={{ fontSize: 12, color: TEXT_3 }}>{store.store_name}</span>
              </div>
              {node.detail && (
                <div style={{ fontSize: 12, color: TEXT_3, lineHeight: 1.5 }}>
                  {node.detail}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---- 主页面 ----

export function StoreExecutionPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('overview');
  const [date, setDate] = useState(todayStr());
  const [selectedStore, setSelectedStore] = useState('all');

  const [storesData, setStoresData] = useState<StoreReviewStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const tabs: { key: TabKey; label: string; icon: string }[] = [
    { key: 'overview',     label: '总览',     icon: '📊' },
    { key: 'store_nodes',  label: '节点状态',  icon: '🔗' },
    { key: 'ranking',      label: '排名',      icon: '🏆' },
    { key: 'anomalies',    label: '异常',      icon: '⚠️' },
  ];

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await txFetch<AllStoresReviewResponse>(
        `/api/v1/ops/daily-review/status?date=${encodeURIComponent(date)}&all_stores=true`,
      );
      setStoresData(resp.items ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : '数据加载失败');
      setStoresData([]);
    } finally {
      setLoading(false);
    }
  }, [date]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // 当选中的门店在新数据中不存在时，重置为全部
  useEffect(() => {
    if (selectedStore !== 'all' && storesData.length > 0) {
      const exists = storesData.some(s => s.store_id === selectedStore);
      if (!exists) setSelectedStore('all');
    }
  }, [storesData, selectedStore]);

  const anomalyCount = storesData.reduce((sum, s) => (
    sum + (s.nodes?.filter(n => n.status === 'error').length ?? 0)
  ), 0);

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto', background: BG_0, minHeight: '100vh', padding: '0 0 40px' }}>
      {/* 顶部 */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 20, flexWrap: 'wrap', gap: 12,
        padding: '20px 0 16px',
        borderBottom: `1px solid ${BG_2}`,
      }}>
        <div>
          <h2 style={{ margin: '0 0 4px', fontSize: 22, fontWeight: 700, color: TEXT_1 }}>
            门店执行中心
          </h2>
          <div style={{ fontSize: 12, color: TEXT_3 }}>
            各门店 E1-E8 节点完成状态实时监控
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <input
            type="date"
            value={date}
            onChange={e => setDate(e.target.value)}
            style={{
              background: BG_1, border: `1px solid ${BG_2}`, borderRadius: 8,
              color: TEXT_2, padding: '6px 12px', fontSize: 13, outline: 'none', cursor: 'pointer',
            }}
          />
          <button
            onClick={loadData}
            disabled={loading}
            style={{
              padding: '8px 16px', borderRadius: 8, border: `1px solid ${BG_2}`,
              background: loading ? BG_2 : BG_1, color: loading ? TEXT_4 : TEXT_2,
              fontSize: 13, cursor: loading ? 'not-allowed' : 'pointer',
              fontWeight: 600,
            }}
          >
            {loading ? '加载中...' : '刷新'}
          </button>
        </div>
      </div>

      {/* 错误提示 */}
      {error && !loading && (
        <div style={{ marginBottom: 16 }}>
          <ErrorDisplay message={error} onRetry={loadData} />
        </div>
      )}

      {/* 汇总卡片 */}
      {!loading && !error && (
        <SummaryCards stores={storesData} />
      )}

      {/* 门店筛选 */}
      {!loading && storesData.length > 0 && (
        <StoreFilter
          stores={storesData}
          selectedStore={selectedStore}
          onSelect={setSelectedStore}
        />
      )}

      {/* Tab 栏 */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 16 }}>
        {tabs.map(t => {
          const isActive = activeTab === t.key;
          const showBadge = t.key === 'anomalies' && anomalyCount > 0;
          return (
            <button
              key={t.key}
              onClick={() => setActiveTab(t.key)}
              style={{
                padding: '8px 18px', borderRadius: 8, border: 'none', cursor: 'pointer',
                background: isActive ? BRAND : BG_1,
                color: isActive ? '#fff' : TEXT_3,
                fontSize: 13, fontWeight: 600,
                display: 'flex', alignItems: 'center', gap: 6,
                transition: 'all .15s',
              }}
            >
              <span>{t.icon}</span>
              <span>{t.label}</span>
              {showBadge && (
                <span style={{
                  background: RED, color: '#fff',
                  fontSize: 10, padding: '1px 5px', borderRadius: 8, fontWeight: 700,
                }}>
                  {anomalyCount}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* 内容区 */}
      {loading ? (
        <LoadingSpinner />
      ) : (
        <>
          {activeTab === 'overview' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {/* 快速状态概览 */}
              <div style={{
                background: BG_1, borderRadius: 12, padding: 16,
                border: `1px solid ${BG_2}`,
              }}>
                <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>
                  今日执行快览
                  <span style={{ fontSize: 12, color: TEXT_3, fontWeight: 400, marginLeft: 8 }}>
                    {date}
                  </span>
                </h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {(selectedStore === 'all' ? storesData : storesData.filter(s => s.store_id === selectedStore))
                    .map(store => {
                      const score = calcScore(store.nodes ?? []);
                      const pct = store.total_count > 0
                        ? Math.round((store.completed_count / store.total_count) * 100)
                        : 0;
                      const hasError = store.nodes?.some(n => n.status === 'error');

                      return (
                        <div key={store.store_id} style={{
                          display: 'flex', alignItems: 'center', gap: 12,
                          padding: '10px 12px', background: BG_2, borderRadius: 8,
                          borderLeft: `3px solid ${hasError ? RED : pct >= 80 ? GREEN : YELLOW}`,
                        }}>
                          <div style={{ minWidth: 100, fontWeight: 600, color: TEXT_1, fontSize: 13 }}>
                            {store.store_name}
                          </div>
                          {/* 节点状态小方块 */}
                          <div style={{ display: 'flex', gap: 4, flex: 1 }}>
                            {(['E1','E2','E3','E4','E5','E6','E7','E8']).map(k => {
                              const node = store.nodes?.find(n => n.node_id.toUpperCase() === k);
                              const status = node?.status ?? 'pending';
                              const bgColors: Record<string, string> = {
                                completed: GREEN, in_progress: BLUE,
                                pending: BG_1, skipped: TEXT_4 + '44', error: RED,
                              };
                              return (
                                <div
                                  key={k}
                                  title={`${k}: ${status}`}
                                  style={{
                                    width: 28, height: 24, borderRadius: 4, fontSize: 9,
                                    background: bgColors[status] || BG_1,
                                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                                    color: status === 'completed' ? '#fff' : TEXT_4, fontWeight: 700,
                                  }}
                                >
                                  {k.replace('E', '')}
                                </div>
                              );
                            })}
                          </div>
                          {/* 完成率进度 */}
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 90 }}>
                            <div style={{ width: 50, height: 4, borderRadius: 2, background: BG_1 }}>
                              <div style={{
                                width: `${pct}%`, height: '100%', borderRadius: 2,
                                background: pct >= 80 ? GREEN : pct >= 50 ? YELLOW : RED,
                              }} />
                            </div>
                            <span style={{ fontSize: 11, color: TEXT_3 }}>{pct}%</span>
                          </div>
                          {/* 评分 */}
                          <div style={{
                            minWidth: 40, textAlign: 'right',
                            fontSize: 15, fontWeight: 700,
                            color: score >= 85 ? GREEN : score >= 70 ? YELLOW : RED,
                          }}>
                            {score}
                          </div>
                          {hasError && (
                            <span style={{ fontSize: 12, color: RED }}>⚠</span>
                          )}
                        </div>
                      );
                    })}
                  {storesData.length === 0 && (
                    <div style={{ padding: '20px', textAlign: 'center', color: TEXT_4 }}>
                      暂无门店数据，请检查API连接
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {activeTab === 'store_nodes' && (
            <StoreNodesTable stores={storesData} selectedStore={selectedStore} />
          )}

          {activeTab === 'ranking' && (
            <StoreRanking stores={storesData} />
          )}

          {activeTab === 'anomalies' && (
            <AnomalyPanel stores={storesData} selectedStore={selectedStore} />
          )}
        </>
      )}

      {/* 底部：数据来源说明 */}
      <div style={{
        marginTop: 20, padding: '12px 16px', borderRadius: 8,
        background: BG_1, border: `1px solid ${BG_2}`,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <span style={{ fontSize: 12, color: TEXT_4 }}>
          数据来源：
          <span style={{ color: TEXT_3 }}>
            GET /api/v1/ops/daily-review/status?date={date}&all_stores=true
          </span>
        </span>
        <span style={{ fontSize: 11, color: TEXT_4 }}>
          评分算法：E1-E8完成率 × 100，每个error节点 -5分
        </span>
      </div>
    </div>
  );
}
