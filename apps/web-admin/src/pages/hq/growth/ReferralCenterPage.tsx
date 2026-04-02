/**
 * ReferralCenterPage — 裂变增长中心
 * 路由: /hq/growth/referral
 * 裂变活动列表 + KPI卡片 + 推荐排行榜 + 新建活动弹窗
 * 数据来源:
 *   - /api/v1/member/referral-campaigns
 *   - /api/v1/member/referrals/leaderboard
 */
import { useState, useEffect } from 'react';
import { txFetch } from '../../../api';

// ─── 主题常量 ───
const BG = '#0d1e28';
const BG_1 = '#112228';
const BG_2 = '#1a2a33';
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

type TabKey = 'campaigns' | 'leaderboard' | 'create';

// ─── API 类型 ───
interface ReferralCampaign {
  id: string;
  name: string;
  campaign_type: string;
  status: string;
  start_date: string;
  end_date: string;
  inviter_reward: string;
  invitee_reward: string;
  total_inviters: number;
  total_invitees: number;
  first_orders: number;
  total_revenue_fen: number;
}

interface LeaderboardEntry {
  rank: number;
  member_id: string;
  name: string;
  phone: string;
  total_referrals: number;
  successful_conversions: number;
  total_reward_fen: number;
}

interface ReferralStats {
  total_campaigns: number;
  active_campaigns: number;
  total_referrers: number;
  total_new_members: number;
  total_gmv_fen: number;
  k_factor: number;
}

// ─── 工具函数 ───
function fenToWan(fen: number): string {
  const yuan = fen / 100;
  if (yuan >= 10000) return `¥${(yuan / 10000).toFixed(1)}万`;
  if (yuan >= 1000) return `¥${(yuan / 1000).toFixed(1)}千`;
  return `¥${yuan.toFixed(0)}`;
}

// ─── KPI卡片 ───
function KpiCard({
  label, value, sub, color, icon,
}: {
  label: string; value: string; sub?: string; color?: string; icon?: string;
}) {
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '14px 16px',
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
        <span style={{ fontSize: 11, color: TEXT_4 }}>{label}</span>
        {icon && <span style={{ fontSize: 18 }}>{icon}</span>}
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, color: color || TEXT_1 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: TEXT_3, marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

// ─── 活动状态标签 ───
function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; color: string }> = {
    '进行中': { label: '进行中', color: GREEN },
    'active':  { label: '进行中', color: GREEN },
    '已结束':  { label: '已结束', color: TEXT_4 },
    'ended':   { label: '已结束', color: TEXT_4 },
    '待启动':  { label: '待启动', color: BLUE },
    'pending': { label: '待启动', color: BLUE },
    '暂停':    { label: '已暂停', color: YELLOW },
    'paused':  { label: '已暂停', color: YELLOW },
  };
  const s = map[status] || { label: status, color: TEXT_3 };
  return (
    <span style={{
      fontSize: 10, padding: '2px 8px', borderRadius: 4,
      background: s.color + '22', color: s.color, fontWeight: 600,
    }}>{s.label}</span>
  );
}

// ─── 活动类型标签 ───
function TypeBadge({ type }: { type: string }) {
  const map: Record<string, { label: string; color: string }> = {
    '老带新':     { label: '老带新', color: BRAND },
    'referral':   { label: '老带新', color: BRAND },
    '拼团':       { label: '拼团',   color: PURPLE },
    'group':      { label: '拼团',   color: PURPLE },
    '分享有礼':   { label: '分享', color: BLUE },
    'share':      { label: '分享', color: BLUE },
  };
  const s = map[type] || { label: type, color: TEXT_3 };
  return (
    <span style={{
      fontSize: 10, padding: '2px 8px', borderRadius: 4,
      background: s.color + '22', color: s.color, fontWeight: 600,
    }}>{s.label}</span>
  );
}

// ─── 裂变活动卡片列表 ───
function CampaignList({
  campaigns,
  loading,
  apiMissing,
}: {
  campaigns: ReferralCampaign[];
  loading: boolean;
  apiMissing: boolean;
}) {
  if (loading) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {[1, 2, 3].map(i => (
          <div key={i} style={{
            background: BG_1, borderRadius: 10, padding: 20,
            border: `1px solid ${BG_2}`, height: 100,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <span style={{ fontSize: 12, color: TEXT_4 }}>加载中...</span>
          </div>
        ))}
      </div>
    );
  }

  if (apiMissing) {
    return (
      <div style={{
        background: BG_1, borderRadius: 10, padding: 32,
        border: `1px solid ${BG_2}`, textAlign: 'center',
      }}>
        <div style={{ fontSize: 32, marginBottom: 12 }}>🚧</div>
        <div style={{ fontSize: 15, fontWeight: 600, color: TEXT_2, marginBottom: 8 }}>功能对接中</div>
        <div style={{ fontSize: 12, color: TEXT_4, lineHeight: 1.8 }}>
          裂变活动列表 API 尚未就绪<br />
          <code style={{ color: BRAND, fontSize: 11 }}>/api/v1/member/referral-campaigns</code>
        </div>
        <div style={{ marginTop: 16, fontSize: 11, color: TEXT_4 }}>
          接入后将在此处展示所有裂变活动及转化数据
        </div>
      </div>
    );
  }

  if (campaigns.length === 0) {
    return (
      <div style={{
        background: BG_1, borderRadius: 10, padding: 32,
        border: `1px solid ${BG_2}`, textAlign: 'center',
      }}>
        <div style={{ fontSize: 32, marginBottom: 12 }}>📭</div>
        <div style={{ fontSize: 14, color: TEXT_3 }}>暂无裂变活动</div>
        <div style={{ fontSize: 11, color: TEXT_4, marginTop: 6 }}>点击「新建活动」创建第一个裂变活动</div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {campaigns.map(c => (
        <div key={c.id} style={{
          background: BG_1, borderRadius: 10, padding: 16,
          border: `1px solid ${BG_2}`,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 15, fontWeight: 700, color: TEXT_1 }}>{c.name}</span>
              <TypeBadge type={c.campaign_type} />
              <StatusBadge status={c.status} />
            </div>
            <span style={{ fontSize: 11, color: TEXT_4 }}>
              {c.start_date} ~ {c.end_date}
            </span>
          </div>

          {(c.inviter_reward || c.invitee_reward) && (
            <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
              {c.inviter_reward && (
                <span style={{ color: TEXT_3, padding: '3px 8px', background: BG_2, borderRadius: 4, fontSize: 11 }}>
                  邀请人: <strong style={{ color: BRAND }}>{c.inviter_reward}</strong>
                </span>
              )}
              {c.invitee_reward && (
                <span style={{ color: TEXT_3, padding: '3px 8px', background: BG_2, borderRadius: 4, fontSize: 11 }}>
                  被邀请人: <strong style={{ color: GREEN }}>{c.invitee_reward}</strong>
                </span>
              )}
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 10 }}>
            {[
              { label: '邀请人数', value: c.total_inviters.toLocaleString(), color: TEXT_1 },
              { label: '被邀请人数', value: c.total_invitees.toLocaleString(), color: TEXT_1 },
              { label: '首单转化', value: c.first_orders.toLocaleString(), color: GREEN },
              {
                label: '裂变GMV',
                value: c.total_revenue_fen > 0 ? fenToWan(c.total_revenue_fen) : '-',
                color: BRAND,
              },
              {
                label: 'K系数',
                value: c.total_inviters > 0
                  ? (c.total_invitees / c.total_inviters).toFixed(2)
                  : '-',
                color: PURPLE,
              },
            ].map((item, i) => (
              <div key={i} style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 10, color: TEXT_4, marginBottom: 4 }}>{item.label}</div>
                <div style={{ fontSize: 16, fontWeight: 700, color: item.color }}>{item.value}</div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── 推荐排行榜 ───
function Leaderboard({
  entries,
  loading,
  apiMissing,
}: {
  entries: LeaderboardEntry[];
  loading: boolean;
  apiMissing: boolean;
}) {
  const medalColors = ['#FFD700', '#C0C0C0', '#CD7F32'];

  if (loading) {
    return (
      <div style={{ background: BG_1, borderRadius: 10, padding: 20, border: `1px solid ${BG_2}` }}>
        <div style={{ textAlign: 'center', color: TEXT_4, fontSize: 12, padding: '40px 0' }}>加载中...</div>
      </div>
    );
  }

  if (apiMissing) {
    return (
      <div style={{
        background: BG_1, borderRadius: 10, padding: 32,
        border: `1px solid ${BG_2}`, textAlign: 'center',
      }}>
        <div style={{ fontSize: 32, marginBottom: 12 }}>🏆</div>
        <div style={{ fontSize: 15, fontWeight: 600, color: TEXT_2, marginBottom: 8 }}>推荐排行榜</div>
        <div style={{ fontSize: 12, color: TEXT_4, lineHeight: 1.8 }}>
          排行榜 API 尚未就绪<br />
          <code style={{ color: BRAND, fontSize: 11 }}>/api/v1/member/referrals/leaderboard</code>
        </div>
        <div style={{ marginTop: 16, fontSize: 11, color: TEXT_4 }}>
          接入后展示推荐人数 TOP 榜单
        </div>
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <div style={{
        background: BG_1, borderRadius: 10, padding: 32,
        border: `1px solid ${BG_2}`, textAlign: 'center',
      }}>
        <div style={{ fontSize: 32, marginBottom: 12 }}>📋</div>
        <div style={{ fontSize: 14, color: TEXT_3 }}>暂无排行数据</div>
      </div>
    );
  }

  return (
    <div style={{ background: BG_1, borderRadius: 10, padding: 16, border: `1px solid ${BG_2}` }}>
      <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>推荐人排行榜 · 本月</h3>

      {/* 前三名高亮 */}
      {entries.slice(0, 3).length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginBottom: 16 }}>
          {entries.slice(0, 3).map((e, i) => (
            <div key={e.member_id} style={{
              background: BG_2, borderRadius: 10, padding: '14px 12px', textAlign: 'center',
              border: `1px solid ${medalColors[i]}44`,
            }}>
              <div style={{ fontSize: 22, marginBottom: 4 }}>
                {['🥇', '🥈', '🥉'][i]}
              </div>
              <div style={{ fontSize: 13, fontWeight: 700, color: TEXT_1, marginBottom: 2 }}>
                {e.name || `用户${e.member_id.slice(-4)}`}
              </div>
              <div style={{ fontSize: 10, color: TEXT_4, marginBottom: 8 }}>
                {e.phone ? `${e.phone.slice(0, 3)}****${e.phone.slice(-4)}` : '—'}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                <div>
                  <div style={{ fontSize: 9, color: TEXT_4 }}>推荐数</div>
                  <div style={{ fontSize: 15, fontWeight: 700, color: BRAND }}>{e.total_referrals}</div>
                </div>
                <div>
                  <div style={{ fontSize: 9, color: TEXT_4 }}>转化数</div>
                  <div style={{ fontSize: 15, fontWeight: 700, color: GREEN }}>{e.successful_conversions}</div>
                </div>
              </div>
              {e.total_reward_fen > 0 && (
                <div style={{ marginTop: 6, fontSize: 11, color: YELLOW }}>
                  奖励 {fenToWan(e.total_reward_fen)}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* 4-10名列表 */}
      {entries.slice(3).length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${BG_2}` }}>
              {['排名', '会员', '手机号', '推荐数', '转化数', '获得奖励'].map(h => (
                <th key={h} style={{
                  textAlign: 'left', padding: '8px 10px',
                  color: TEXT_4, fontWeight: 600, fontSize: 11,
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {entries.slice(3).map(e => (
              <tr key={e.member_id} style={{ borderBottom: `1px solid ${BG_2}` }}>
                <td style={{ padding: '10px', color: TEXT_3, fontWeight: 600 }}>#{e.rank}</td>
                <td style={{ padding: '10px', color: TEXT_1 }}>
                  {e.name || `用户${e.member_id.slice(-4)}`}
                </td>
                <td style={{ padding: '10px', color: TEXT_3 }}>
                  {e.phone ? `${e.phone.slice(0, 3)}****${e.phone.slice(-4)}` : '—'}
                </td>
                <td style={{ padding: '10px', color: BRAND, fontWeight: 600 }}>{e.total_referrals}</td>
                <td style={{ padding: '10px', color: GREEN }}>{e.successful_conversions}</td>
                <td style={{ padding: '10px', color: YELLOW }}>
                  {e.total_reward_fen > 0 ? fenToWan(e.total_reward_fen) : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ─── 新建活动弹窗 ───
interface CreateCampaignModalProps {
  onClose: () => void;
  onSubmit: (data: Record<string, string>) => void;
  submitting: boolean;
}

function CreateCampaignModal({ onClose, onSubmit, submitting }: CreateCampaignModalProps) {
  const [form, setForm] = useState({
    name: '',
    campaign_type: 'referral',
    start_date: '',
    end_date: '',
    inviter_reward: '',
    invitee_reward: '',
    description: '',
  });

  function set(key: string, value: string) {
    setForm(prev => ({ ...prev, [key]: value }));
  }

  function handleSubmit() {
    if (!form.name || !form.start_date || !form.end_date) return;
    onSubmit(form);
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 1000,
      background: 'rgba(0,0,0,0.7)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }} onClick={e => e.target === e.currentTarget && onClose()}>
      <div style={{
        background: BG_1, borderRadius: 12, padding: 24,
        border: `1px solid ${BG_2}`, width: 520, maxHeight: '90vh', overflowY: 'auto',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <h3 style={{ margin: 0, fontSize: 17, fontWeight: 700, color: TEXT_1 }}>新建裂变活动</h3>
          <button onClick={onClose} style={{
            background: 'none', border: 'none', color: TEXT_4,
            fontSize: 18, cursor: 'pointer', lineHeight: 1, padding: '4px 6px',
          }}>✕</button>
        </div>

        {[
          { label: '活动名称 *', key: 'name', placeholder: '如：五一老带新活动' },
          { label: '活动开始日期 *', key: 'start_date', placeholder: '2026-05-01' },
          { label: '活动结束日期 *', key: 'end_date', placeholder: '2026-05-07' },
          { label: '邀请人奖励', key: 'inviter_reward', placeholder: '如：邀请1人得¥20券' },
          { label: '被邀请人奖励', key: 'invitee_reward', placeholder: '如：新客满60减25' },
          { label: '活动说明', key: 'description', placeholder: '简要描述活动规则...' },
        ].map(field => (
          <div key={field.key} style={{ marginBottom: 14 }}>
            <label style={{ display: 'block', fontSize: 12, color: TEXT_3, marginBottom: 5 }}>
              {field.label}
            </label>
            <input
              value={form[field.key as keyof typeof form]}
              onChange={e => set(field.key, e.target.value)}
              placeholder={field.placeholder}
              style={{
                width: '100%', padding: '9px 12px', borderRadius: 6,
                border: `1px solid ${BG_2}`, background: BG_2,
                color: TEXT_1, fontSize: 13, boxSizing: 'border-box',
                outline: 'none',
              }}
            />
          </div>
        ))}

        {/* 活动类型选择 */}
        <div style={{ marginBottom: 20 }}>
          <label style={{ display: 'block', fontSize: 12, color: TEXT_3, marginBottom: 5 }}>
            活动类型
          </label>
          <div style={{ display: 'flex', gap: 8 }}>
            {[
              { value: 'referral', label: '老带新' },
              { value: 'group', label: '拼团' },
              { value: 'share', label: '分享有礼' },
            ].map(opt => (
              <button key={opt.value} onClick={() => set('campaign_type', opt.value)} style={{
                padding: '7px 16px', borderRadius: 6,
                border: `1px solid ${form.campaign_type === opt.value ? BRAND : BG_2}`,
                background: form.campaign_type === opt.value ? BRAND + '22' : 'transparent',
                color: form.campaign_type === opt.value ? BRAND : TEXT_3,
                fontSize: 12, fontWeight: 600, cursor: 'pointer',
              }}>{opt.label}</button>
            ))}
          </div>
        </div>

        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{
            padding: '9px 20px', borderRadius: 6,
            border: `1px solid ${BG_2}`, background: 'transparent',
            color: TEXT_3, fontSize: 13, cursor: 'pointer',
          }}>取消</button>
          <button
            onClick={handleSubmit}
            disabled={submitting || !form.name || !form.start_date || !form.end_date}
            style={{
              padding: '9px 24px', borderRadius: 6, border: 'none',
              background: submitting ? TEXT_4 : BRAND,
              color: '#fff', fontSize: 13, fontWeight: 600,
              cursor: submitting ? 'not-allowed' : 'pointer',
              opacity: (!form.name || !form.start_date || !form.end_date) ? 0.5 : 1,
            }}
          >{submitting ? '提交中...' : '创建活动'}</button>
        </div>
      </div>
    </div>
  );
}

// ─── 主页面 ───
export function ReferralCenterPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('campaigns');
  const [loadingCampaigns, setLoadingCampaigns] = useState(true);
  const [loadingLeaderboard, setLoadingLeaderboard] = useState(true);
  const [campaigns, setCampaigns] = useState<ReferralCampaign[]>([]);
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [stats, setStats] = useState<ReferralStats | null>(null);
  const [campaignApiMissing, setCampaignApiMissing] = useState(false);
  const [leaderboardApiMissing, setLeaderboardApiMissing] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createResult, setCreateResult] = useState<'success' | 'error' | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadCampaigns() {
      setLoadingCampaigns(true);
      try {
        const resp = await txFetch<{
          items: ReferralCampaign[];
          stats?: ReferralStats;
        }>('/api/v1/member/referral-campaigns?page=1&size=20');
        if (!cancelled) {
          setCampaigns(resp.items || []);
          if (resp.stats) setStats(resp.stats);
          setCampaignApiMissing(false);
        }
      } catch {
        if (!cancelled) setCampaignApiMissing(true);
      } finally {
        if (!cancelled) setLoadingCampaigns(false);
      }
    }

    async function loadLeaderboard() {
      setLoadingLeaderboard(true);
      try {
        const resp = await txFetch<{ items: LeaderboardEntry[] }>(
          '/api/v1/member/referrals/leaderboard?period=month&size=10',
        );
        if (!cancelled) {
          setLeaderboard(resp.items || []);
          setLeaderboardApiMissing(false);
        }
      } catch {
        if (!cancelled) setLeaderboardApiMissing(true);
      } finally {
        if (!cancelled) setLoadingLeaderboard(false);
      }
    }

    loadCampaigns();
    loadLeaderboard();
    return () => { cancelled = true; };
  }, []);

  async function handleCreateCampaign(data: Record<string, string>) {
    setCreating(true);
    setCreateResult(null);
    try {
      await txFetch('/api/v1/member/referral-campaigns', {
        method: 'POST',
        body: JSON.stringify(data),
      });
      setCreateResult('success');
      setShowCreateModal(false);
      // 刷新列表
      const resp = await txFetch<{ items: ReferralCampaign[] }>(
        '/api/v1/member/referral-campaigns?page=1&size=20',
      );
      setCampaigns(resp.items || []);
    } catch {
      setCreateResult('error');
    } finally {
      setCreating(false);
    }
  }

  // 计算KPI（优先用API stats，否则从campaigns推算）
  const activeCampaigns = stats?.active_campaigns
    ?? campaigns.filter(c => c.status === '进行中' || c.status === 'active').length;
  const totalReferrers = stats?.total_referrers
    ?? campaigns.reduce((s, c) => s + c.total_inviters, 0);
  const totalNewMembers = stats?.total_new_members
    ?? campaigns.reduce((s, c) => s + c.first_orders, 0);
  const totalGmv = stats?.total_gmv_fen
    ?? campaigns.reduce((s, c) => s + c.total_revenue_fen, 0);
  const kFactor = stats?.k_factor
    ?? (totalReferrers > 0
      ? campaigns.reduce((s, c) => s + c.total_invitees, 0) / Math.max(totalReferrers, 1)
      : 0);

  const tabs: { key: TabKey; label: string }[] = [
    { key: 'campaigns', label: '裂变活动' },
    { key: 'leaderboard', label: '推荐排行榜' },
    { key: 'create', label: '+ 新建活动' },
  ];

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto', background: BG, minHeight: '100vh', padding: '0 0 32px' }}>
      {/* 页头 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: TEXT_1 }}>裂变增长中心</h2>
        <button onClick={() => setShowCreateModal(true)} style={{
          padding: '8px 18px', borderRadius: 8, border: 'none',
          background: BRAND, color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer',
        }}>+ 新建活动</button>
      </div>

      {/* 创建结果提示 */}
      {createResult === 'success' && (
        <div style={{
          padding: '10px 16px', background: GREEN + '22', borderRadius: 8,
          marginBottom: 12, fontSize: 13, color: GREEN,
          display: 'flex', justifyContent: 'space-between',
        }}>
          <span>✓ 活动创建成功！</span>
          <button onClick={() => setCreateResult(null)} style={{
            background: 'none', border: 'none', color: GREEN, cursor: 'pointer', fontSize: 16,
          }}>×</button>
        </div>
      )}
      {createResult === 'error' && (
        <div style={{
          padding: '10px 16px', background: RED + '22', borderRadius: 8,
          marginBottom: 12, fontSize: 13, color: RED,
          display: 'flex', justifyContent: 'space-between',
        }}>
          <span>✗ 创建失败，API 尚未就绪（功能对接中）</span>
          <button onClick={() => setCreateResult(null)} style={{
            background: 'none', border: 'none', color: RED, cursor: 'pointer', fontSize: 16,
          }}>×</button>
        </div>
      )}

      {/* KPI 卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 16 }}>
        <KpiCard
          label="活跃裂变活动"
          value={campaignApiMissing ? '—' : String(activeCampaigns)}
          sub={campaignApiMissing ? '功能对接中' : '进行中'}
          color={GREEN}
          icon="🎯"
        />
        <KpiCard
          label="总推荐人数"
          value={campaignApiMissing ? '—' : totalReferrers.toLocaleString()}
          sub={campaignApiMissing ? '功能对接中' : '累计邀请人'}
          color={TEXT_1}
          icon="👥"
        />
        <KpiCard
          label="成功转化"
          value={campaignApiMissing ? '—' : totalNewMembers.toLocaleString()}
          sub={campaignApiMissing ? '功能对接中' : '首单新客'}
          color={BRAND}
          icon="✅"
        />
        <KpiCard
          label="K系数"
          value={campaignApiMissing || kFactor === 0 ? '—' : kFactor.toFixed(2)}
          sub={campaignApiMissing ? '功能对接中' : kFactor >= 1 ? '病毒式传播' : '待提升'}
          color={PURPLE}
          icon="📈"
        />
        <KpiCard
          label="裂变GMV"
          value={campaignApiMissing || totalGmv === 0 ? '—' : fenToWan(totalGmv)}
          sub={campaignApiMissing ? '功能对接中' : '累计贡献'}
          color={GREEN}
          icon="💰"
        />
      </div>

      {/* Tab 切换 */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 16 }}>
        {tabs.filter(t => t.key !== 'create').map(t => (
          <button key={t.key} onClick={() => setActiveTab(t.key)} style={{
            padding: '8px 18px', borderRadius: 8, border: 'none', cursor: 'pointer',
            background: activeTab === t.key ? BRAND : BG_1,
            color: activeTab === t.key ? '#fff' : TEXT_3,
            fontSize: 13, fontWeight: 600,
          }}>{t.label}</button>
        ))}
      </div>

      {/* 内容区 */}
      {activeTab === 'campaigns' && (
        <CampaignList
          campaigns={campaigns}
          loading={loadingCampaigns}
          apiMissing={campaignApiMissing}
        />
      )}
      {activeTab === 'leaderboard' && (
        <Leaderboard
          entries={leaderboard}
          loading={loadingLeaderboard}
          apiMissing={leaderboardApiMissing}
        />
      )}

      {/* 新建活动弹窗 */}
      {showCreateModal && (
        <CreateCampaignModal
          onClose={() => { setShowCreateModal(false); setCreateResult(null); }}
          onSubmit={handleCreateCampaign}
          submitting={creating}
        />
      )}
    </div>
  );
}
