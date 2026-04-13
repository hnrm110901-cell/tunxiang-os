/**
 * GroupBuyPage — 团购活动管理
 * 路由: /hq/growth/group-buy
 *
 * 后端状态：
 *   - tx-member 目前尚未实现 /api/v1/member/group-buys 端点
 *   - 本页面在 API 不可用时优雅降级，展示「功能对接中」状态
 *   - 已实现拼团活动列表、KPI、详情、新建弹窗完整 UI
 *   - 一旦后端上线，移除 apiUnavailable 降级逻辑即可
 */
import { useState, useEffect, useCallback } from 'react';
import { formatPrice } from '@tx-ds/utils';
import { txFetchData } from '../../../api';

// ── 设计 Token ──────────────────────────────────────────────────
const BG_1   = '#0d1e28';
const BG_2   = '#1a2a33';
const BG_3   = '#223040';
const BRAND  = '#FF6B35';
const GREEN  = '#52c41a';
const RED    = '#ff4d4f';
const YELLOW = '#faad14';
const BLUE   = '#1890ff';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

// ── 类型定义 ────────────────────────────────────────────────────
type TabKey = 'activities' | 'teams' | 'analytics';

interface GroupBuyActivity {
  id: string;
  name: string;
  product_name?: string;
  group_size: number;
  original_price_fen?: number;
  group_price_fen?: number;
  status: string;
  start_date?: string;
  end_date?: string;
  team_count?: number;
  success_count?: number;
  expire_minutes?: number;
  description?: string;
}

interface GroupBuyTeam {
  id: string;
  activity_name?: string;
  leader_name?: string;
  leader_phone?: string;
  current_size: number;
  target_size: number;
  status: string;
  created_at?: string;
  completed_at?: string;
}

interface KPI {
  label: string;
  value: string;
  sub: string;
  trend: 'up' | 'down' | 'flat';
  color?: string;
}

interface CreateGroupBuyForm {
  name: string;
  product_name: string;
  group_size: number;
  original_price_yuan: string;
  group_price_yuan: string;
  start_date: string;
  end_date: string;
  expire_minutes: number;
  description: string;
}

// ── 工具函数 ────────────────────────────────────────────────────
/** @deprecated Use formatPrice from @tx-ds/utils */
function fenToYuan(v: number): string {
  return `¥${(v / 100).toFixed(2)}`;
}

function statusColor(s: string): string {
  if (s === 'active' || s === '进行中' || s === '已成团') return GREEN;
  if (s === 'pending' || s === '待启动' || s === '拼团中') return BLUE;
  if (s === 'ended' || s === '已结束' || s === '已过期') return TEXT_4;
  return YELLOW;
}

function statusBg(s: string): string {
  if (s === 'active' || s === '进行中' || s === '已成团') return 'rgba(82,196,26,0.15)';
  if (s === 'pending' || s === '待启动' || s === '拼团中') return 'rgba(24,144,255,0.15)';
  if (s === 'ended' || s === '已结束' || s === '已过期') return 'rgba(255,255,255,0.06)';
  return 'rgba(250,173,20,0.15)';
}

function statusLabel(s: string): string {
  const map: Record<string, string> = {
    active: '进行中', pending: '待启动', ended: '已结束',
    进行中: '进行中', 待启动: '待启动', 已结束: '已结束',
    已成团: '已成团', 拼团中: '拼团中', 已过期: '已过期',
  };
  return map[s] ?? s;
}

// ── 主页面 ──────────────────────────────────────────────────────
export function GroupBuyPage() {
  const [tab, setTab] = useState<TabKey>('activities');
  const [showCreate, setShowCreate] = useState(false);
  const [activities, setActivities] = useState<GroupBuyActivity[]>([]);
  const [teams, setTeams] = useState<GroupBuyTeam[]>([]);
  const [loading, setLoading] = useState(true);
  const [apiUnavailable, setApiUnavailable] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);
  const [selectedActivity, setSelectedActivity] = useState<GroupBuyActivity | null>(null);

  const tabs: { key: TabKey; label: string }[] = [
    { key: 'activities', label: '拼团活动' },
    { key: 'teams', label: '开团记录' },
    { key: 'analytics', label: '数据概览' },
  ];

  const loadData = useCallback(async () => {
    setLoading(true);
    setApiError(null);
    try {
      const data = await txFetchData<{ items: GroupBuyActivity[]; total: number } | GroupBuyActivity[]>(
        '/api/v1/member/group-buys?page=1&size=20'
      );
      const list = Array.isArray(data) ? data : (data as { items: GroupBuyActivity[] }).items ?? [];
      setActivities(list);
      setApiUnavailable(false);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '接口暂不可用';
      // 区分"404/not found"（功能未上线）和其他错误
      const isNotFound = msg.includes('404') || msg.includes('not found') || msg.includes('Not Found');
      setApiUnavailable(isNotFound);
      setApiError(isNotFound ? null : msg);
      setActivities([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadTeams = useCallback(async () => {
    if (apiUnavailable) return;
    try {
      const data = await txFetchData<{ items: GroupBuyTeam[] } | GroupBuyTeam[]>(
        '/api/v1/member/group-buys/teams?page=1&size=20'
      );
      const list = Array.isArray(data) ? data : (data as { items: GroupBuyTeam[] }).items ?? [];
      setTeams(list);
    } catch {
      setTeams([]);
    }
  }, [apiUnavailable]);

  useEffect(() => { loadData(); }, [loadData]);
  useEffect(() => {
    if (tab === 'teams') loadTeams();
  }, [tab, loadTeams]);

  // 计算 KPI
  const kpis: KPI[] = (() => {
    if (apiUnavailable || activities.length === 0) {
      return [
        { label: '活跃团购数', value: '-', sub: '等待接入', trend: 'flat', color: BRAND },
        { label: '参团人数', value: '-', sub: '等待接入', trend: 'flat', color: BLUE },
        { label: '成团率', value: '-', sub: '等待接入', trend: 'flat', color: GREEN },
        { label: '团购GMV', value: '-', sub: '等待接入', trend: 'flat', color: YELLOW },
      ];
    }
    const active = activities.filter(a => a.status === 'active' || a.status === '进行中');
    const totalTeams = activities.reduce((s, a) => s + (a.team_count ?? 0), 0);
    const totalSuccess = activities.reduce((s, a) => s + (a.success_count ?? 0), 0);
    const rate = totalTeams > 0 ? `${((totalSuccess / totalTeams) * 100).toFixed(1)}%` : '-';
    const gmvFen = activities.reduce((s, a) => {
      const price = a.group_price_fen ?? 0;
      const success = a.success_count ?? 0;
      const groupSize = a.group_size ?? 1;
      return s + price * success * groupSize;
    }, 0);
    const gmvStr = gmvFen >= 10000 ? `¥${(gmvFen / 10000 / 100).toFixed(1)}万` : `¥${(gmvFen / 100).toFixed(0)}`;
    return [
      { label: '活跃团购数', value: String(active.length), sub: `共 ${activities.length} 个活动`, trend: 'up', color: BRAND },
      { label: '开团总数', value: totalTeams > 0 ? totalTeams.toLocaleString() : '-', sub: '累计开团', trend: 'up', color: BLUE },
      { label: '成团率', value: rate, sub: `成团 ${totalSuccess} 次`, trend: 'up', color: GREEN },
      { label: '团购GMV', value: gmvFen > 0 ? gmvStr : '-', sub: '累计GMV（含税）', trend: 'up', color: YELLOW },
    ];
  })();

  return (
    <div style={{ padding: 24, background: BG_1, minHeight: '100vh', color: TEXT_1, fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif' }}>

      {/* Header */}
      <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>团购活动管理</h1>
          <div style={{ fontSize: 13, color: TEXT_3, marginTop: 4 }}>社交裂变 · 以团代促 · 引流到店</div>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <button
            onClick={loadData}
            style={{ background: BG_3, color: TEXT_2, border: '1px solid rgba(255,255,255,0.08)', borderRadius: 6, padding: '8px 14px', fontSize: 13, cursor: 'pointer' }}
          >
            刷新
          </button>
          <button
            onClick={() => setShowCreate(true)}
            style={{ background: apiUnavailable ? TEXT_4 : BRAND, color: '#fff', border: 'none', borderRadius: 6, padding: '8px 20px', fontSize: 14, fontWeight: 600, cursor: apiUnavailable ? 'not-allowed' : 'pointer' }}
            title={apiUnavailable ? '后端接口对接中，暂不可用' : ''}
          >
            + 创建拼团活动
          </button>
        </div>
      </div>

      {/* 功能对接中横幅 */}
      {apiUnavailable && (
        <div style={{
          marginBottom: 20, padding: '14px 20px', borderRadius: 10,
          background: 'rgba(250,173,20,0.08)', border: '1px solid rgba(250,173,20,0.25)',
          display: 'flex', alignItems: 'center', gap: 12,
        }}>
          <span style={{ fontSize: 20 }}>🔧</span>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600, color: YELLOW }}>功能对接中</div>
            <div style={{ fontSize: 12, color: TEXT_3, marginTop: 2 }}>
              团购管理后端接口（<code style={{ color: YELLOW }}>GET /api/v1/member/group-buys</code>）尚未部署。
              UI 已就绪，后端上线后自动生效。
            </div>
          </div>
        </div>
      )}

      {/* 一般接口错误提示 */}
      {!apiUnavailable && apiError && (
        <div style={{ marginBottom: 16, padding: '12px 16px', background: 'rgba(255,77,79,0.1)', border: '1px solid rgba(255,77,79,0.3)', borderRadius: 8, fontSize: 13, color: RED }}>
          接口异常：{apiError}。请检查后端服务状态。
        </div>
      )}

      {/* KPI 卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
        {kpis.map(k => (
          <div key={k.label} style={{ background: BG_2, borderRadius: 10, padding: 18, borderLeft: `3px solid ${k.color ?? BRAND}`, opacity: apiUnavailable ? 0.55 : 1 }}>
            <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 6 }}>{k.label}</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: k.color ?? TEXT_1 }}>{loading ? '—' : k.value}</div>
            <div style={{ fontSize: 12, color: TEXT_4, marginTop: 6 }}>
              {k.trend === 'up' ? '↑ ' : k.trend === 'down' ? '↓ ' : ''}{k.sub}
            </div>
          </div>
        ))}
      </div>

      {/* Tab 切换 */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 20, background: BG_2, borderRadius: 8, padding: 4, width: 'fit-content' }}>
        {tabs.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            style={{
              padding: '8px 22px', fontSize: 14, fontWeight: tab === t.key ? 600 : 400, cursor: 'pointer',
              border: 'none', borderRadius: 6,
              background: tab === t.key ? BRAND : 'transparent',
              color: tab === t.key ? '#fff' : TEXT_3,
              transition: 'all 0.15s',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* 内容区 */}
      {tab === 'activities' && (
        <ActivitiesTab
          activities={activities}
          loading={loading}
          apiUnavailable={apiUnavailable}
          onRefresh={loadData}
          onSelect={setSelectedActivity}
        />
      )}
      {tab === 'teams' && (
        <TeamsTab teams={teams} loading={loading} apiUnavailable={apiUnavailable} />
      )}
      {tab === 'analytics' && (
        <AnalyticsTab activities={activities} apiUnavailable={apiUnavailable} />
      )}

      {/* 活动详情弹窗 */}
      {selectedActivity && (
        <ActivityDetailModal activity={selectedActivity} onClose={() => setSelectedActivity(null)} />
      )}

      {/* 新建弹窗 */}
      {showCreate && (
        <CreateModal
          onClose={() => setShowCreate(false)}
          onSuccess={() => { setShowCreate(false); loadData(); }}
        />
      )}
    </div>
  );
}

// ── 拼团活动 Tab ─────────────────────────────────────────────────
function ActivitiesTab({ activities, loading, apiUnavailable, onRefresh, onSelect }: {
  activities: GroupBuyActivity[];
  loading: boolean;
  apiUnavailable: boolean;
  onRefresh: () => void;
  onSelect: (a: GroupBuyActivity) => void;
}) {
  if (loading) {
    return (
      <div style={{ background: BG_2, borderRadius: 10, overflow: 'hidden' }}>
        {[1, 2, 3].map(i => (
          <div key={i} style={{ padding: '16px 20px', borderBottom: '1px solid rgba(255,255,255,0.04)', display: 'flex', gap: 16, opacity: 0.4 }}>
            <div style={{ flex: 3, height: 16, background: BG_3, borderRadius: 3 }} />
            <div style={{ flex: 2, height: 16, background: BG_3, borderRadius: 3 }} />
            <div style={{ flex: 1, height: 16, background: BG_3, borderRadius: 3 }} />
          </div>
        ))}
      </div>
    );
  }

  if (apiUnavailable) {
    return <ApiUnavailablePlaceholder message="团购活动列表" apiPath="GET /api/v1/member/group-buys" onRefresh={onRefresh} />;
  }

  if (activities.length === 0) {
    return (
      <div style={{ background: BG_2, borderRadius: 12, padding: 60, textAlign: 'center' }}>
        <div style={{ fontSize: 40, marginBottom: 16 }}>🛒</div>
        <div style={{ fontSize: 15, color: TEXT_2, marginBottom: 8 }}>暂无拼团活动</div>
        <div style={{ fontSize: 13, color: TEXT_4 }}>点击右上角「创建拼团活动」启动您的第一个拼团营销</div>
        <button onClick={onRefresh} style={{ marginTop: 20, background: BRAND, color: '#fff', border: 'none', borderRadius: 6, padding: '8px 20px', fontSize: 13, cursor: 'pointer' }}>
          重新加载
        </button>
      </div>
    );
  }

  return (
    <div style={{ background: BG_2, borderRadius: 10, overflow: 'hidden' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
        <thead>
          <tr style={{ background: 'rgba(255,255,255,0.04)' }}>
            {['活动名称', '商品', '拼团人数', '原价 / 团价', '状态', '有效期', '开团数', '成团率', '操作'].map(h => (
              <th key={h} style={{ padding: '12px 14px', textAlign: 'left', color: TEXT_3, fontWeight: 500, borderBottom: '1px solid rgba(255,255,255,0.06)', whiteSpace: 'nowrap' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {activities.map(a => {
            const teamCount = a.team_count ?? 0;
            const successCount = a.success_count ?? 0;
            const rate = teamCount > 0 ? `${((successCount / teamCount) * 100).toFixed(1)}%` : '-';
            return (
              <tr key={a.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                <td style={{ padding: '14px 14px', fontWeight: 500 }}>{a.name}</td>
                <td style={{ padding: '14px 14px', color: TEXT_2 }}>{a.product_name ?? '-'}</td>
                <td style={{ padding: '14px 14px' }}>{a.group_size}人团</td>
                <td style={{ padding: '14px 14px' }}>
                  {a.original_price_fen ? (
                    <>
                      <span style={{ textDecoration: 'line-through', color: TEXT_4, marginRight: 8 }}>{fenToYuan(a.original_price_fen)}</span>
                      <span style={{ color: RED, fontWeight: 600 }}>{fenToYuan(a.group_price_fen ?? 0)}</span>
                    </>
                  ) : (
                    <span style={{ color: TEXT_4 }}>-</span>
                  )}
                </td>
                <td style={{ padding: '14px 14px' }}>
                  <span style={{
                    display: 'inline-block', padding: '2px 10px', borderRadius: 12, fontSize: 12, fontWeight: 500,
                    background: statusBg(a.status), color: statusColor(a.status),
                  }}>
                    {statusLabel(a.status)}
                  </span>
                </td>
                <td style={{ padding: '14px 14px', color: TEXT_3, fontSize: 12, whiteSpace: 'nowrap' }}>
                  {a.start_date && a.end_date ? `${a.start_date} ~ ${a.end_date}` : '-'}
                </td>
                <td style={{ padding: '14px 14px' }}>{teamCount}</td>
                <td style={{ padding: '14px 14px', color: GREEN }}>{rate}</td>
                <td style={{ padding: '14px 14px' }}>
                  <span
                    onClick={() => onSelect(a)}
                    style={{ color: BLUE, cursor: 'pointer', marginRight: 12, fontSize: 13 }}
                  >
                    详情
                  </span>
                  {(a.status === 'pending' || a.status === '待启动') && (
                    <span style={{ color: GREEN, cursor: 'pointer', fontSize: 13 }}>启动</span>
                  )}
                  {(a.status === 'active' || a.status === '进行中') && (
                    <span style={{ color: YELLOW, cursor: 'pointer', fontSize: 13 }}>暂停</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── 开团记录 Tab ─────────────────────────────────────────────────
function TeamsTab({ teams, loading, apiUnavailable }: {
  teams: GroupBuyTeam[];
  loading: boolean;
  apiUnavailable: boolean;
}) {
  if (apiUnavailable) {
    return <ApiUnavailablePlaceholder message="开团记录" apiPath="GET /api/v1/member/group-buys/teams" />;
  }

  if (loading) {
    return (
      <div style={{ background: BG_2, borderRadius: 10, padding: 40, textAlign: 'center', color: TEXT_4 }}>
        加载中...
      </div>
    );
  }

  if (teams.length === 0) {
    return (
      <div style={{ background: BG_2, borderRadius: 12, padding: 60, textAlign: 'center' }}>
        <div style={{ fontSize: 40, marginBottom: 12 }}>👥</div>
        <div style={{ fontSize: 14, color: TEXT_3 }}>暂无开团记录</div>
      </div>
    );
  }

  return (
    <div style={{ background: BG_2, borderRadius: 10, overflow: 'hidden' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
        <thead>
          <tr style={{ background: 'rgba(255,255,255,0.04)' }}>
            {['团号', '活动', '团长', '人数进度', '状态', '开团时间', '成团时间'].map(h => (
              <th key={h} style={{ padding: '12px 14px', textAlign: 'left', color: TEXT_3, fontWeight: 500, borderBottom: '1px solid rgba(255,255,255,0.06)' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {teams.map(t => (
            <tr key={t.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
              <td style={{ padding: '14px 14px', fontFamily: 'monospace', fontSize: 12, color: TEXT_3 }}>
                {t.id.slice(0, 8)}…
              </td>
              <td style={{ padding: '14px 14px' }}>{t.activity_name ?? '-'}</td>
              <td style={{ padding: '14px 14px' }}>
                {t.leader_name ?? '-'}
                {t.leader_phone && <span style={{ color: TEXT_4, fontSize: 12, marginLeft: 6 }}>{t.leader_phone}</span>}
              </td>
              <td style={{ padding: '14px 14px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <div style={{ width: 80, height: 6, background: 'rgba(255,255,255,0.08)', borderRadius: 3, overflow: 'hidden' }}>
                    <div style={{
                      width: `${Math.min((t.current_size / t.target_size) * 100, 100)}%`,
                      height: '100%',
                      background: t.status === '已成团' || t.status === 'completed' ? GREEN : BRAND,
                      borderRadius: 3,
                    }} />
                  </div>
                  <span style={{ fontSize: 12, color: TEXT_3 }}>{t.current_size}/{t.target_size}</span>
                </div>
              </td>
              <td style={{ padding: '14px 14px' }}>
                <span style={{
                  display: 'inline-block', padding: '2px 10px', borderRadius: 12, fontSize: 12,
                  background: statusBg(t.status), color: statusColor(t.status),
                }}>
                  {statusLabel(t.status)}
                </span>
              </td>
              <td style={{ padding: '14px 14px', color: TEXT_3, fontSize: 12 }}>{t.created_at ?? '-'}</td>
              <td style={{ padding: '14px 14px', color: TEXT_3, fontSize: 12 }}>{t.completed_at ?? '-'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── 数据概览 Tab ─────────────────────────────────────────────────
function AnalyticsTab({ activities, apiUnavailable }: {
  activities: GroupBuyActivity[];
  apiUnavailable: boolean;
}) {
  if (apiUnavailable) {
    return <ApiUnavailablePlaceholder message="数据概览" apiPath="GET /api/v1/member/group-buys" />;
  }

  const active = activities.filter(a => a.status === 'active' || a.status === '进行中');
  const ended = activities.filter(a => a.status === 'ended' || a.status === '已结束');
  const totalTeams = activities.reduce((s, a) => s + (a.team_count ?? 0), 0);
  const totalSuccess = activities.reduce((s, a) => s + (a.success_count ?? 0), 0);
  const overallRate = totalTeams > 0 ? (totalSuccess / totalTeams) * 100 : 0;

  // 按成团率降序排列的 TOP 3
  const top3 = [...activities]
    .filter(a => (a.team_count ?? 0) > 0)
    .sort((a, b) => {
      const ra = (a.success_count ?? 0) / (a.team_count ?? 1);
      const rb = (b.success_count ?? 0) / (b.team_count ?? 1);
      return rb - ra;
    })
    .slice(0, 3);

  if (activities.length === 0) {
    return (
      <div style={{ background: BG_2, borderRadius: 12, padding: 60, textAlign: 'center' }}>
        <div style={{ fontSize: 40, marginBottom: 12 }}>📊</div>
        <div style={{ fontSize: 14, color: TEXT_3 }}>暂无活动数据</div>
      </div>
    );
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 16 }}>
      {/* 左侧：活动状态 + 成团率概览 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div style={{ background: BG_2, borderRadius: 10, padding: 20 }}>
          <h3 style={{ margin: '0 0 18px', fontSize: 15, fontWeight: 600 }}>活动状态分布</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14, marginBottom: 20 }}>
            {[
              { label: '进行中', value: active.length, color: GREEN },
              { label: '已结束', value: ended.length, color: TEXT_4 },
              { label: '待启动', value: activities.length - active.length - ended.length, color: YELLOW },
            ].map(m => (
              <div key={m.label} style={{ padding: 14, background: BG_3, borderRadius: 8, textAlign: 'center' }}>
                <div style={{ fontSize: 24, fontWeight: 700, color: m.color }}>{m.value}</div>
                <div style={{ fontSize: 12, color: TEXT_4, marginTop: 4 }}>{m.label}</div>
              </div>
            ))}
          </div>
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 8 }}>
              <span style={{ color: TEXT_3 }}>整体成团率</span>
              <span style={{ color: GREEN, fontWeight: 600 }}>{overallRate.toFixed(1)}%</span>
            </div>
            <div style={{ height: 10, background: 'rgba(255,255,255,0.06)', borderRadius: 5, overflow: 'hidden' }}>
              <div style={{
                width: `${Math.min(overallRate, 100)}%`, height: '100%',
                background: `linear-gradient(90deg, ${BRAND}, ${GREEN})`, borderRadius: 5,
                transition: 'width 0.5s ease',
              }} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: TEXT_4, marginTop: 6 }}>
              <span>开团 {totalTeams} 次</span>
              <span>成团 {totalSuccess} 次</span>
            </div>
          </div>
        </div>

        {/* 各活动详情 */}
        <div style={{ background: BG_2, borderRadius: 10, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 600 }}>各活动成团率</h3>
          {activities.filter(a => (a.team_count ?? 0) > 0).map(a => {
            const rate = ((a.success_count ?? 0) / (a.team_count ?? 1)) * 100;
            return (
              <div key={a.id} style={{ marginBottom: 14 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 5 }}>
                  <span style={{ color: TEXT_2 }}>{a.name}</span>
                  <span style={{ color: rate >= 70 ? GREEN : rate >= 50 ? YELLOW : RED, fontWeight: 600 }}>
                    {rate.toFixed(1)}%
                  </span>
                </div>
                <div style={{ height: 5, background: 'rgba(255,255,255,0.06)', borderRadius: 3, overflow: 'hidden' }}>
                  <div style={{
                    width: `${Math.min(rate, 100)}%`, height: '100%',
                    background: rate >= 70 ? GREEN : rate >= 50 ? YELLOW : RED,
                    borderRadius: 3,
                  }} />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* 右侧：热门TOP3 */}
      <div style={{ background: BG_2, borderRadius: 10, padding: 20 }}>
        <h3 style={{ margin: '0 0 18px', fontSize: 15, fontWeight: 600 }}>热门拼团 TOP3</h3>
        {top3.length === 0 ? (
          <div style={{ color: TEXT_4, fontSize: 13, textAlign: 'center', paddingTop: 40 }}>暂无数据</div>
        ) : (
          top3.map((a, i) => {
            const rate = ((a.success_count ?? 0) / (a.team_count ?? 1)) * 100;
            const rankColors = [BRAND, BLUE, TEXT_3];
            return (
              <div key={a.id} style={{
                display: 'flex', alignItems: 'flex-start', gap: 12, padding: '12px 0',
                borderBottom: i < top3.length - 1 ? '1px solid rgba(255,255,255,0.05)' : 'none',
              }}>
                <div style={{
                  width: 30, height: 30, borderRadius: 6, flexShrink: 0,
                  background: rankColors[i], display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 15, fontWeight: 700, color: '#fff',
                }}>
                  {i + 1}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 500, marginBottom: 4 }}>{a.name}</div>
                  <div style={{ fontSize: 12, color: TEXT_4 }}>
                    {a.group_size}人团 · {a.team_count ?? 0} 次开团
                  </div>
                  {a.group_price_fen && (
                    <div style={{ fontSize: 12, color: RED, marginTop: 2 }}>
                      团价 {fenToYuan(a.group_price_fen)}
                    </div>
                  )}
                </div>
                <div style={{ textAlign: 'right', flexShrink: 0 }}>
                  <div style={{ fontSize: 16, fontWeight: 700, color: GREEN }}>{rate.toFixed(0)}%</div>
                  <div style={{ fontSize: 11, color: TEXT_4 }}>成团率</div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

// ── 活动详情弹窗 ─────────────────────────────────────────────────
function ActivityDetailModal({ activity: a, onClose }: { activity: GroupBuyActivity; onClose: () => void }) {
  const teamCount = a.team_count ?? 0;
  const successCount = a.success_count ?? 0;
  const rate = teamCount > 0 ? ((successCount / teamCount) * 100).toFixed(1) : '-';

  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.65)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{ background: BG_2, borderRadius: 12, padding: 28, width: 480 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>{a.name}</h2>
          <span style={{
            padding: '3px 12px', borderRadius: 12, fontSize: 12,
            background: statusBg(a.status), color: statusColor(a.status),
          }}>
            {statusLabel(a.status)}
          </span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 20 }}>
          {[
            { label: '商品', value: a.product_name ?? '-' },
            { label: '目标人数', value: `${a.group_size}人/团` },
            { label: '原价', value: a.original_price_fen ? fenToYuan(a.original_price_fen) : '-' },
            { label: '团购价', value: a.group_price_fen ? fenToYuan(a.group_price_fen) : '-' },
            { label: '活动开始', value: a.start_date ?? '-' },
            { label: '活动结束', value: a.end_date ?? '-' },
            { label: '拼团时限', value: a.expire_minutes ? `${a.expire_minutes}分钟` : '-' },
            { label: '折扣力度', value: a.original_price_fen && a.group_price_fen ? `${((a.group_price_fen / a.original_price_fen) * 10).toFixed(1)}折` : '-' },
          ].map(item => (
            <div key={item.label} style={{ padding: 12, background: BG_3, borderRadius: 8 }}>
              <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 4 }}>{item.label}</div>
              <div style={{ fontSize: 14, fontWeight: 500 }}>{item.value}</div>
            </div>
          ))}
        </div>

        {/* 数据 */}
        <div style={{ display: 'flex', justifyContent: 'space-around', padding: '16px 0', borderTop: '1px solid rgba(255,255,255,0.06)', borderBottom: '1px solid rgba(255,255,255,0.06)', marginBottom: 20 }}>
          {[
            { label: '开团次数', value: teamCount, color: BLUE },
            { label: '成团次数', value: successCount, color: GREEN },
            { label: '成团率', value: rate + (rate !== '-' ? '%' : ''), color: BRAND },
          ].map(m => (
            <div key={m.label} style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 26, fontWeight: 700, color: m.color }}>{m.value}</div>
              <div style={{ fontSize: 11, color: TEXT_4, marginTop: 4 }}>{m.label}</div>
            </div>
          ))}
        </div>

        {a.description && (
          <div style={{ padding: 12, background: BG_3, borderRadius: 8, fontSize: 13, color: TEXT_3, marginBottom: 20 }}>
            {a.description}
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ padding: '9px 24px', borderRadius: 6, border: '1px solid rgba(255,255,255,0.1)', background: 'transparent', color: TEXT_2, fontSize: 14, cursor: 'pointer' }}>
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}

// ── 新建团购弹窗 ─────────────────────────────────────────────────
function CreateModal({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const [form, setForm] = useState<CreateGroupBuyForm>({
    name: '',
    product_name: '',
    group_size: 2,
    original_price_yuan: '',
    group_price_yuan: '',
    start_date: '',
    end_date: '',
    expire_minutes: 30,
    description: '',
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async () => {
    if (!form.name.trim()) { setError('请填写活动名称'); return; }
    if (!form.product_name.trim()) { setError('请填写商品名称'); return; }
    if (form.group_size < 2) { setError('拼团人数至少2人'); return; }
    if (!form.start_date || !form.end_date) { setError('请设置活动时间'); return; }

    const origFen = Math.round(parseFloat(form.original_price_yuan || '0') * 100);
    const groupFen = Math.round(parseFloat(form.group_price_yuan || '0') * 100);
    if (groupFen >= origFen && origFen > 0) { setError('团购价应低于原价'); return; }

    setSubmitting(true);
    setError(null);
    try {
      await txFetchData('/api/v1/member/group-buys', {
        method: 'POST',
        body: JSON.stringify({
          name: form.name.trim(),
          product_name: form.product_name.trim(),
          group_size: form.group_size,
          original_price_fen: origFen,
          group_price_fen: groupFen,
          start_date: form.start_date,
          end_date: form.end_date,
          expire_minutes: form.expire_minutes,
          description: form.description.trim(),
          status: 'pending',
        }),
      });
      onSuccess();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '创建失败';
      setError(`${msg}（后端接口尚未上线，请等待对接完成）`);
    } finally {
      setSubmitting(false);
    }
  };

  const inputStyle: React.CSSProperties = {
    width: '100%', background: BG_3, border: '1px solid rgba(255,255,255,0.1)',
    borderRadius: 6, padding: '9px 12px', color: TEXT_1, fontSize: 14, outline: 'none',
    boxSizing: 'border-box',
  };
  const labelStyle: React.CSSProperties = { fontSize: 13, color: TEXT_2, marginBottom: 6, display: 'block' };

  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.65)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{ background: BG_2, borderRadius: 12, padding: 28, width: 520, maxHeight: '90vh', overflowY: 'auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>创建拼团活动</h2>
          <span style={{ padding: '3px 10px', borderRadius: 10, fontSize: 11, background: 'rgba(250,173,20,0.15)', color: YELLOW }}>
            接口对接中
          </span>
        </div>

        <div style={{ marginBottom: 14 }}>
          <label style={labelStyle}>活动名称 *</label>
          <input style={inputStyle} placeholder="例：双人拼团·招牌酸菜鱼" value={form.name}
            onChange={e => setForm(p => ({ ...p, name: e.target.value }))} />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
          <div>
            <label style={labelStyle}>商品名称 *</label>
            <input style={inputStyle} placeholder="例：酸菜鱼双人套餐" value={form.product_name}
              onChange={e => setForm(p => ({ ...p, product_name: e.target.value }))} />
          </div>
          <div>
            <label style={labelStyle}>拼团人数 *</label>
            <input type="number" min={2} max={20} style={inputStyle} value={form.group_size}
              onChange={e => setForm(p => ({ ...p, group_size: parseInt(e.target.value) || 2 }))} />
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
          <div>
            <label style={labelStyle}>原价（元）</label>
            <input type="number" min={0} step="0.01" style={inputStyle} placeholder="0.00" value={form.original_price_yuan}
              onChange={e => setForm(p => ({ ...p, original_price_yuan: e.target.value }))} />
          </div>
          <div>
            <label style={labelStyle}>团购价（元）</label>
            <input type="number" min={0} step="0.01" style={inputStyle} placeholder="0.00" value={form.group_price_yuan}
              onChange={e => setForm(p => ({ ...p, group_price_yuan: e.target.value }))} />
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
          <div>
            <label style={labelStyle}>开始日期 *</label>
            <input type="date" style={inputStyle} value={form.start_date}
              onChange={e => setForm(p => ({ ...p, start_date: e.target.value }))} />
          </div>
          <div>
            <label style={labelStyle}>结束日期 *</label>
            <input type="date" style={inputStyle} value={form.end_date}
              onChange={e => setForm(p => ({ ...p, end_date: e.target.value }))} />
          </div>
        </div>

        <div style={{ marginBottom: 14 }}>
          <label style={labelStyle}>拼团时限（分钟）</label>
          <input type="number" min={10} max={1440} style={inputStyle} value={form.expire_minutes}
            onChange={e => setForm(p => ({ ...p, expire_minutes: parseInt(e.target.value) || 30 }))} />
        </div>

        <div style={{ marginBottom: 24 }}>
          <label style={labelStyle}>活动说明</label>
          <textarea
            style={{ ...inputStyle, minHeight: 70, resize: 'vertical' }}
            placeholder="活动规则说明（选填）"
            value={form.description}
            onChange={e => setForm(p => ({ ...p, description: e.target.value }))}
          />
        </div>

        {error && (
          <div style={{ marginBottom: 16, padding: '10px 14px', background: 'rgba(255,77,79,0.1)', border: '1px solid rgba(255,77,79,0.3)', borderRadius: 6, fontSize: 13, color: RED }}>
            {error}
          </div>
        )}

        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button onClick={onClose}
            style={{ padding: '9px 22px', borderRadius: 6, border: '1px solid rgba(255,255,255,0.1)', background: 'transparent', color: TEXT_2, fontSize: 14, cursor: 'pointer' }}>
            取消
          </button>
          <button onClick={handleSubmit} disabled={submitting}
            style={{ padding: '9px 24px', borderRadius: 6, border: 'none', background: submitting ? TEXT_4 : BRAND, color: '#fff', fontSize: 14, fontWeight: 600, cursor: submitting ? 'not-allowed' : 'pointer' }}>
            {submitting ? '提交中...' : '创建活动'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── API 不可用占位组件 ───────────────────────────────────────────
function ApiUnavailablePlaceholder({ message, apiPath, onRefresh }: {
  message: string;
  apiPath: string;
  onRefresh?: () => void;
}) {
  return (
    <div style={{ background: BG_2, borderRadius: 12, padding: 48, textAlign: 'center' }}>
      <div style={{ fontSize: 44, marginBottom: 16 }}>🔧</div>
      <div style={{ fontSize: 16, fontWeight: 600, color: YELLOW, marginBottom: 8 }}>功能对接中</div>
      <div style={{ fontSize: 13, color: TEXT_3, marginBottom: 6 }}>
        「{message}」后端接口尚未上线
      </div>
      <div style={{ fontSize: 12, color: TEXT_4, marginBottom: 24 }}>
        <code style={{ color: YELLOW, background: 'rgba(250,173,20,0.08)', padding: '2px 8px', borderRadius: 4 }}>
          {apiPath}
        </code>
      </div>
      {onRefresh && (
        <button onClick={onRefresh}
          style={{ padding: '8px 22px', borderRadius: 6, border: '1px solid rgba(255,107,53,0.4)', background: 'transparent', color: BRAND, fontSize: 13, cursor: 'pointer' }}>
          重试连接
        </button>
      )}
    </div>
  );
}
