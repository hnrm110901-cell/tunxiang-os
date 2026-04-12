/**
 * CrmPage — 会员 CDP 仪表板
 * Section 1: 会员总览（4个统计卡片）
 * Section 2: RFM 分层分布（水平条形图）
 * Section 3: 会员列表（搜索+分页+展开详情）
 * Section 4: 储值卡概览
 */
import React, { useCallback, useEffect, useState } from 'react';
import { txFetchData } from '../api';

// ─── 工具函数 ──────────────────────────────────────────────────

const maskPhone = (phone: string) =>
  phone.replace(/(\d{3})\d{4}(\d{4})/, '$1****$2');

const fenToYuan = (fen: number) =>
  (fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const formatDate = (iso?: string) => {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', year: 'numeric' });
};

// ─── 数据类型 ──────────────────────────────────────────────────

interface MemberItem {
  customer_id: string;
  name?: string;
  phone: string;
  level: string;
  total_spend_fen: number;
  visit_count: number;
  last_visit_at?: string;
  rfm_level?: string;
  stored_value_fen?: number;
  points?: number;
}

interface MemberDetail extends MemberItem {
  recentOrders?: Array<{
    order_id: string;
    total_fen: number;
    created_at: string;
  }>;
}

interface RfmDistItem {
  level: string;   // S1–S5
  count: number;
  ratio: number;
}

interface OverviewStats {
  total_members: number;
  new_this_month: number;
  active_30d: number;
  avg_order_value_fen: number;
}

interface StoredValueStats {
  active_cards: number;
  total_balance_fen: number;
  recharged_this_month_fen: number;
  consumed_this_month_fen: number;
}

// ─── RFM 等级映射 ──────────────────────────────────────────────

const RFM_LEVEL_MAP: Record<string, { label: string; emoji: string; color: string; barColor: string }> = {
  S5: { label: '至尊 VIP',   emoji: '💎', color: '#FFD700', barColor: '#FFD700' },
  S4: { label: '忠诚客户',   emoji: '⭐', color: '#4FC3F7', barColor: '#4FC3F7' },
  S3: { label: '需要维护',   emoji: '🔄', color: '#FFA726', barColor: '#FFA726' },
  S2: { label: '沉睡客户',   emoji: '😴', color: '#EF9A9A', barColor: '#EF5350' },
  S1: { label: '新客户',     emoji: '📢', color: '#A5D6A7', barColor: '#66BB6A' },
};

const getRfmTag = (level?: string) => {
  if (!level) return null;
  const info = RFM_LEVEL_MAP[level];
  if (!info) return null;
  return (
    <span style={{
      backgroundColor: `${info.barColor}22`,
      color: info.color,
      border: `1px solid ${info.barColor}55`,
      borderRadius: '4px',
      padding: '1px 7px',
      fontSize: '11px',
      whiteSpace: 'nowrap',
    }}>
      {info.emoji} {info.label}
    </span>
  );
};

const getLevelTag = (level: string) => {
  const colorMap: Record<string, string> = {
    diamond: '#FFD700',
    gold: '#FFA726',
    silver: '#90CAF9',
    bronze: '#A5D6A7',
    regular: '#8899A6',
  };
  const labelMap: Record<string, string> = {
    diamond: '钻石', gold: '金牌', silver: '银牌', bronze: '铜牌', regular: '普通',
  };
  const color = colorMap[level] ?? '#8899A6';
  return (
    <span style={{
      color,
      fontSize: '11px',
      border: `1px solid ${color}55`,
      borderRadius: '3px',
      padding: '1px 6px',
    }}>
      {labelMap[level] ?? level}
    </span>
  );
};

// ─── 样式常量（保留原深色主题） ─────────────────────────────────

const s = {
  container: {
    backgroundColor: '#0B1A20',
    color: '#E0E0E0',
    minHeight: '100vh',
    padding: '24px 32px',
    fontFamily: 'system-ui, -apple-system, sans-serif',
  } as React.CSSProperties,

  header: {
    fontSize: '24px',
    fontWeight: 700,
    color: '#FFFFFF',
    marginBottom: '4px',
  } as React.CSSProperties,

  subtitle: {
    fontSize: '14px',
    color: '#8899A6',
    marginBottom: '24px',
  } as React.CSSProperties,

  sectionTitle: {
    fontSize: '13px',
    fontWeight: 600,
    color: '#8899A6',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.08em',
    marginBottom: '12px',
    marginTop: '28px',
  } as React.CSSProperties,

  statsGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
    gap: '16px',
    marginBottom: '8px',
  } as React.CSSProperties,

  statCard: {
    backgroundColor: '#112B36',
    borderRadius: '10px',
    padding: '18px 20px',
    border: '1px solid #1E3A47',
  } as React.CSSProperties,

  statLabel: {
    fontSize: '12px',
    color: '#8899A6',
    marginBottom: '6px',
  } as React.CSSProperties,

  statValue: {
    fontSize: '28px',
    fontWeight: 700,
    color: '#FFFFFF',
    lineHeight: 1.2,
  } as React.CSSProperties,

  statUnit: {
    fontSize: '14px',
    color: '#8899A6',
    marginLeft: '4px',
  } as React.CSSProperties,

  card: {
    backgroundColor: '#112B36',
    borderRadius: '12px',
    padding: '20px',
    border: '1px solid #1E3A47',
    marginBottom: '20px',
  } as React.CSSProperties,

  cardTitle: {
    fontSize: '15px',
    fontWeight: 600,
    color: '#4FC3F7',
    marginBottom: '16px',
  } as React.CSSProperties,

  divider: {
    borderBottom: '1px solid #1E3A47',
  } as React.CSSProperties,

  tableHeader: {
    display: 'grid',
    gridTemplateColumns: '130px 130px 80px 110px 100px 1fr',
    padding: '8px 12px',
    fontSize: '11px',
    color: '#8899A6',
    fontWeight: 600,
    letterSpacing: '0.05em',
    textTransform: 'uppercase' as const,
  } as React.CSSProperties,

  tableRow: {
    display: 'grid',
    gridTemplateColumns: '130px 130px 80px 110px 100px 1fr',
    padding: '10px 12px',
    fontSize: '13px',
    borderTop: '1px solid #1E3A47',
    cursor: 'pointer',
    transition: 'background-color 0.15s',
    alignItems: 'center',
  } as React.CSSProperties,

  searchInput: {
    backgroundColor: '#0B1A20',
    border: '1px solid #1E3A47',
    borderRadius: '6px',
    color: '#E0E0E0',
    padding: '7px 12px',
    fontSize: '13px',
    width: '260px',
    outline: 'none',
  } as React.CSSProperties,

  pageBtn: (active: boolean): React.CSSProperties => ({
    padding: '4px 10px',
    borderRadius: '4px',
    border: '1px solid #1E3A47',
    backgroundColor: active ? '#1E6B8A' : 'transparent',
    color: active ? '#FFF' : '#8899A6',
    cursor: 'pointer',
    fontSize: '12px',
    margin: '0 2px',
  }),

  errorText: {
    color: '#EF5350',
    fontSize: '13px',
    padding: '12px 0',
  } as React.CSSProperties,

  loadingText: {
    color: '#8899A6',
    fontSize: '13px',
    padding: '12px 0',
  } as React.CSSProperties,

  expandRow: {
    backgroundColor: '#0D2330',
    borderTop: '1px solid #1E3A47',
    padding: '12px 16px',
    fontSize: '12px',
    color: '#B0C4CF',
  } as React.CSSProperties,
};

// ─── 子组件：统计卡片 ──────────────────────────────────────────

function StatCard({
  label, value, unit, accent,
}: {
  label: string;
  value: string | number;
  unit?: string;
  accent?: string;
}) {
  return (
    <div style={s.statCard}>
      <div style={s.statLabel}>{label}</div>
      <div style={{ ...s.statValue, color: accent ?? '#FFFFFF' }}>
        {value}
        {unit && <span style={s.statUnit}>{unit}</span>}
      </div>
    </div>
  );
}

// ─── 子组件：RFM 条形图 ────────────────────────────────────────

function RfmBar({ items, total }: { items: RfmDistItem[]; total: number }) {
  if (!items.length) return <div style={s.loadingText}>暂无数据</div>;

  // S5→S1 降序排列
  const sorted = [...items].sort((a, b) => b.level.localeCompare(a.level));

  return (
    <div>
      {sorted.map((item) => {
        const info = RFM_LEVEL_MAP[item.level] ?? {
          label: item.level, emoji: '', color: '#8899A6', barColor: '#8899A6',
        };
        const pct = total > 0 ? Math.round((item.count / total) * 100) : 0;

        return (
          <div key={item.level} style={{ marginBottom: '14px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '5px' }}>
              <span style={{ fontSize: '13px', color: '#E0E0E0' }}>
                {info.emoji} {info.label}
              </span>
              <span style={{ fontSize: '12px', color: '#8899A6' }}>
                <span style={{ color: info.color, fontWeight: 600 }}>{item.count.toLocaleString()}</span> 人
                &nbsp;·&nbsp;
                <span style={{ color: info.color }}>{pct}%</span>
              </span>
            </div>
            <div style={{
              width: '100%',
              height: '8px',
              backgroundColor: '#1E3A47',
              borderRadius: '4px',
              overflow: 'hidden',
            }}>
              <div style={{
                width: `${Math.max(pct, pct > 0 ? 1 : 0)}%`,
                height: '100%',
                backgroundColor: info.barColor,
                borderRadius: '4px',
                transition: 'width 0.5s ease',
              }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── 子组件：展开的会员详情行 ──────────────────────────────────

function MemberExpandRow({ detail, loading }: { detail: MemberDetail | null; loading: boolean }) {
  if (loading) return <div style={s.expandRow}><span style={s.loadingText}>加载详情中…</span></div>;
  if (!detail) return null;

  return (
    <div style={s.expandRow}>
      <div style={{ display: 'flex', gap: '32px', flexWrap: 'wrap', marginBottom: '10px' }}>
        <span>
          <span style={{ color: '#8899A6' }}>储值余额：</span>
          <span style={{ color: '#4FC3F7' }}>
            ¥{fenToYuan(detail.stored_value_fen ?? 0)}
          </span>
        </span>
        <span>
          <span style={{ color: '#8899A6' }}>积分：</span>
          <span style={{ color: '#FFD700' }}>{(detail.points ?? 0).toLocaleString()}</span>
        </span>
        <span>
          <span style={{ color: '#8899A6' }}>到店次数：</span>
          <span>{detail.visit_count}</span>
        </span>
      </div>
      {detail.recentOrders && detail.recentOrders.length > 0 && (
        <div>
          <div style={{ color: '#8899A6', marginBottom: '6px', fontSize: '11px', fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
            最近消费
          </div>
          <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
            {detail.recentOrders.slice(0, 3).map((o) => (
              <div key={o.order_id} style={{
                backgroundColor: '#112B36',
                border: '1px solid #1E3A47',
                borderRadius: '6px',
                padding: '6px 12px',
                fontSize: '12px',
              }}>
                <span style={{ color: '#E0E0E0' }}>¥{fenToYuan(o.total_fen)}</span>
                <span style={{ color: '#8899A6', marginLeft: '8px' }}>{formatDate(o.created_at)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {(!detail.recentOrders || detail.recentOrders.length === 0) && (
        <span style={{ color: '#8899A6', fontSize: '12px' }}>暂无消费记录</span>
      )}
    </div>
  );
}

// ─── 主组件 ────────────────────────────────────────────────────

export function CrmPage() {
  // — 状态：会员总览 —
  const [overview, setOverview] = useState<OverviewStats | null>(null);
  const [overviewError, setOverviewError] = useState(false);

  // — 状态：RFM 分布 —
  const [rfmItems, setRfmItems] = useState<RfmDistItem[]>([]);
  const [rfmTotal, setRfmTotal] = useState(0);
  const [rfmError, setRfmError] = useState(false);

  // — 状态：会员列表 —
  const [members, setMembers] = useState<MemberItem[]>([]);
  const [memberTotal, setMemberTotal] = useState(0);
  const [memberPage, setMemberPage] = useState(1);
  const [searchKeyword, setSearchKeyword] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [membersLoading, setMembersLoading] = useState(false);
  const [membersError, setMembersError] = useState(false);

  // — 状态：展开行 —
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [expandedDetail, setExpandedDetail] = useState<MemberDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // — 状态：储值卡 —
  const [storedValue, setStoredValue] = useState<StoredValueStats | null>(null);
  const [svError, setSvError] = useState(false);

  const PAGE_SIZE = 15;

  // ── 加载会员总览 ──────────────────────────────────────────────
  useEffect(() => {
    setOverviewError(false);
    const today = new Date();
    const firstDay = new Date(today.getFullYear(), today.getMonth(), 1).toISOString().slice(0, 10);
    const todayStr = today.toISOString().slice(0, 10);

    // 并行请求：活跃度分析 + 增长分析
    Promise.all([
      txFetchData<{ active_members: number; mau: number; avg_order_value_fen?: number }>(
        `/api/v1/member/analytics/activity?start_date=${firstDay}&end_date=${todayStr}`,
      ).catch(() => null),
      txFetchData<{ total_members: number; new_members_period: number }>(
        `/api/v1/member/analytics/growth?start_date=${firstDay}&end_date=${todayStr}`,
      ).catch(() => null),
    ]).then(([activityData, growthData]) => {
      if (!activityData && !growthData) {
        setOverviewError(true);
        return;
      }
      setOverview({
        total_members: (growthData as any)?.total_members ?? 0,
        new_this_month: (growthData as any)?.new_members_period ?? 0,
        active_30d: (activityData as any)?.active_members ?? (activityData as any)?.mau ?? 0,
        avg_order_value_fen: (activityData as any)?.avg_order_value_fen ?? 0,
      });
    });
  }, []);

  // ── 加载 RFM 分布 ─────────────────────────────────────────────
  useEffect(() => {
    setRfmError(false);
    txFetchData<{ distribution: RfmDistItem[]; total: number }>(
      '/api/v1/member/rfm/distribution',
    ).then((data) => {
      setRfmItems(data.distribution ?? []);
      setRfmTotal(data.total ?? 0);
    }).catch(() => {
      setRfmError(true);
    });
  }, []);

  // ── 加载会员列表 ──────────────────────────────────────────────
  const loadMembers = useCallback(() => {
    setMembersLoading(true);
    setMembersError(false);
    const query = new URLSearchParams({
      page: String(memberPage),
      size: String(PAGE_SIZE),
    });
    if (searchKeyword.trim()) query.set('q', searchKeyword.trim());

    txFetchData<{ items: MemberItem[]; total: number }>(
      `/api/v1/member/customers?${query.toString()}`,
    ).then((data) => {
      setMembers(data.items ?? []);
      setMemberTotal(data.total ?? 0);
    }).catch(() => {
      setMembersError(true);
    }).finally(() => {
      setMembersLoading(false);
    });
  }, [memberPage, searchKeyword]);

  useEffect(() => {
    loadMembers();
  }, [loadMembers]);

  // ── 加载储值卡数据 ────────────────────────────────────────────
  useEffect(() => {
    setSvError(false);
    const today = new Date();
    const firstDay = new Date(today.getFullYear(), today.getMonth(), 1).toISOString().slice(0, 10);
    const todayStr = today.toISOString().slice(0, 10);

    txFetchData<StoredValueStats>(
      `/api/v1/member/analytics/stored-value?start_date=${firstDay}&end_date=${todayStr}`,
    ).then((data) => {
      setStoredValue(data);
    }).catch(() => {
      setSvError(true);
    });
  }, []);

  // ── 展开/收起会员行 ───────────────────────────────────────────
  const handleRowClick = (member: MemberItem) => {
    if (expandedId === member.customer_id) {
      setExpandedId(null);
      setExpandedDetail(null);
      return;
    }
    setExpandedId(member.customer_id);
    setExpandedDetail(null);
    setDetailLoading(true);

    // 并行：基本详情 + 最近订单
    Promise.all([
      txFetchData<MemberItem>(`/api/v1/member/customers/${member.customer_id}`).catch(() => null),
      txFetchData<{ items: Array<{ order_id: string; total_fen: number; created_at: string }>; total: number }>(
        `/api/v1/member/customers/${member.customer_id}/orders?page=1&size=3`,
      ).catch(() => null),
    ]).then(([detail, orders]) => {
      const base: MemberDetail = (detail as MemberDetail) ?? { ...member };
      base.recentOrders = (orders as any)?.items ?? [];
      setExpandedDetail(base);
    }).finally(() => {
      setDetailLoading(false);
    });
  };

  // ── 搜索提交 ──────────────────────────────────────────────────
  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setMemberPage(1);
    setSearchKeyword(searchInput);
  };

  // ── 分页计算 ──────────────────────────────────────────────────
  const totalPages = Math.max(1, Math.ceil(memberTotal / PAGE_SIZE));
  const pageNumbers: number[] = [];
  const start = Math.max(1, memberPage - 2);
  const end = Math.min(totalPages, memberPage + 2);
  for (let i = start; i <= end; i++) pageNumbers.push(i);

  // ─── 渲染 ─────────────────────────────────────────────────────
  return (
    <div style={s.container}>

      {/* ── 页头 ── */}
      <h1 style={s.header}>客户经营</h1>
      <p style={s.subtitle}>会员 CDP · RFM 分层 · 储值卡概览</p>

      {/* ═══════════════════════════════════════════════════
          Section 1 — 会员总览
      ═══════════════════════════════════════════════════ */}
      <div style={s.sectionTitle}>会员总览</div>
      {overviewError ? (
        <div style={s.errorText}>数据加载失败，请稍后重试</div>
      ) : (
        <div style={s.statsGrid}>
          <StatCard
            label="总会员数"
            value={overview ? overview.total_members.toLocaleString() : '—'}
            unit="人"
            accent="#4FC3F7"
          />
          <StatCard
            label="本月新增"
            value={overview ? overview.new_this_month.toLocaleString() : '—'}
            unit="人"
            accent="#66BB6A"
          />
          <StatCard
            label="活跃会员（近30天）"
            value={overview ? overview.active_30d.toLocaleString() : '—'}
            unit="人"
            accent="#FFA726"
          />
          <StatCard
            label="平均客单价"
            value={overview ? `¥${fenToYuan(overview.avg_order_value_fen)}` : '—'}
            accent="#FF6B35"
          />
        </div>
      )}

      {/* ═══════════════════════════════════════════════════
          Section 2 — RFM 分层分布
      ═══════════════════════════════════════════════════ */}
      <div style={s.sectionTitle}>RFM 客户分层</div>
      <div style={s.card}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <div style={s.cardTitle}>分层分布</div>
          {rfmTotal > 0 && (
            <span style={{ fontSize: '12px', color: '#8899A6' }}>
              共 <span style={{ color: '#E0E0E0' }}>{rfmTotal.toLocaleString()}</span> 位会员
            </span>
          )}
        </div>
        {rfmError ? (
          <div style={s.errorText}>数据加载失败</div>
        ) : (
          <RfmBar items={rfmItems} total={rfmTotal} />
        )}
      </div>

      {/* ═══════════════════════════════════════════════════
          Section 3 — 会员列表
      ═══════════════════════════════════════════════════ */}
      <div style={s.sectionTitle}>会员列表</div>
      <div style={s.card}>

        {/* 搜索栏 */}
        <form
          onSubmit={handleSearch}
          style={{ display: 'flex', gap: '10px', marginBottom: '16px', alignItems: 'center' }}
        >
          <input
            style={s.searchInput}
            placeholder="按姓名或手机号搜索…"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
          />
          <button
            type="submit"
            style={{
              backgroundColor: '#1E6B8A',
              color: '#FFF',
              border: 'none',
              borderRadius: '6px',
              padding: '7px 16px',
              fontSize: '13px',
              cursor: 'pointer',
            }}
          >
            搜索
          </button>
          {searchKeyword && (
            <button
              type="button"
              onClick={() => { setSearchInput(''); setSearchKeyword(''); setMemberPage(1); }}
              style={{
                backgroundColor: 'transparent',
                color: '#8899A6',
                border: '1px solid #1E3A47',
                borderRadius: '6px',
                padding: '7px 12px',
                fontSize: '12px',
                cursor: 'pointer',
              }}
            >
              清除
            </button>
          )}
        </form>

        {/* 表头 */}
        <div style={s.tableHeader}>
          <span>姓名</span>
          <span>手机号</span>
          <span>等级</span>
          <span>累计消费</span>
          <span>最近消费</span>
          <span>RFM 标签</span>
        </div>

        {/* 加载/错误状态 */}
        {membersLoading && <div style={s.loadingText}>加载中…</div>}
        {membersError && <div style={s.errorText}>数据加载失败，请稍后重试</div>}

        {/* 会员行 */}
        {!membersLoading && !membersError && members.map((m) => (
          <React.Fragment key={m.customer_id}>
            <div
              style={{
                ...s.tableRow,
                backgroundColor: expandedId === m.customer_id ? '#0D2330' : 'transparent',
              }}
              onClick={() => handleRowClick(m)}
              onMouseEnter={(e) => {
                if (expandedId !== m.customer_id)
                  (e.currentTarget as HTMLDivElement).style.backgroundColor = '#142536';
              }}
              onMouseLeave={(e) => {
                if (expandedId !== m.customer_id)
                  (e.currentTarget as HTMLDivElement).style.backgroundColor = 'transparent';
              }}
            >
              <span style={{ color: '#E0E0E0', fontWeight: 500 }}>
                {m.name ?? '—'}
              </span>
              <span style={{ color: '#8899A6', fontFamily: 'monospace' }}>
                {maskPhone(m.phone)}
              </span>
              <span>{getLevelTag(m.level)}</span>
              <span style={{ color: '#E0E0E0' }}>
                ¥{fenToYuan(m.total_spend_fen)}
              </span>
              <span style={{ color: '#8899A6', fontSize: '12px' }}>
                {formatDate(m.last_visit_at)}
              </span>
              <span>{getRfmTag(m.rfm_level)}</span>
            </div>

            {/* 展开详情 */}
            {expandedId === m.customer_id && (
              <MemberExpandRow
                detail={expandedDetail}
                loading={detailLoading}
              />
            )}
          </React.Fragment>
        ))}

        {/* 空态 */}
        {!membersLoading && !membersError && members.length === 0 && (
          <div style={{ ...s.loadingText, textAlign: 'center', padding: '32px 0' }}>
            {searchKeyword ? '未找到匹配会员' : '暂无会员数据'}
          </div>
        )}

        {/* 分页 */}
        {memberTotal > PAGE_SIZE && (
          <div style={{
            display: 'flex',
            justifyContent: 'flex-end',
            alignItems: 'center',
            marginTop: '16px',
            gap: '4px',
          }}>
            <span style={{ fontSize: '12px', color: '#8899A6', marginRight: '8px' }}>
              共 {memberTotal} 条 / 第 {memberPage}/{totalPages} 页
            </span>
            <button
              style={s.pageBtn(false)}
              disabled={memberPage <= 1}
              onClick={() => setMemberPage(1)}
            >«</button>
            <button
              style={s.pageBtn(false)}
              disabled={memberPage <= 1}
              onClick={() => setMemberPage((p) => p - 1)}
            >‹</button>
            {pageNumbers.map((n) => (
              <button
                key={n}
                style={s.pageBtn(n === memberPage)}
                onClick={() => setMemberPage(n)}
              >{n}</button>
            ))}
            <button
              style={s.pageBtn(false)}
              disabled={memberPage >= totalPages}
              onClick={() => setMemberPage((p) => p + 1)}
            >›</button>
            <button
              style={s.pageBtn(false)}
              disabled={memberPage >= totalPages}
              onClick={() => setMemberPage(totalPages)}
            >»</button>
          </div>
        )}
      </div>

      {/* ═══════════════════════════════════════════════════
          Section 4 — 储值卡概览
      ═══════════════════════════════════════════════════ */}
      <div style={s.sectionTitle}>储值卡概览</div>
      {svError ? (
        <div style={s.errorText}>数据加载失败，请稍后重试</div>
      ) : (
        <div style={s.statsGrid}>
          <StatCard
            label="有效储值卡"
            value={storedValue ? storedValue.active_cards.toLocaleString() : '—'}
            unit="张"
            accent="#4FC3F7"
          />
          <StatCard
            label="储值余额总额"
            value={storedValue ? `¥${fenToYuan(storedValue.total_balance_fen)}` : '—'}
            accent="#FFD700"
          />
          <StatCard
            label="本月充值金额"
            value={storedValue ? `¥${fenToYuan(storedValue.recharged_this_month_fen)}` : '—'}
            accent="#66BB6A"
          />
          <StatCard
            label="本月消费使用"
            value={storedValue ? `¥${fenToYuan(storedValue.consumed_this_month_fen)}` : '—'}
            accent="#FFA726"
          />
        </div>
      )}

      {/* 底部空白 */}
      <div style={{ height: '32px' }} />
    </div>
  );
}
