import React, { useState, useEffect, useCallback } from 'react';
import { Form, Input, message } from 'antd';
import { ZCard, ZKpi, ZBadge, ZButton, ZSkeleton, ZTable, ZModal, ZEmpty } from '../design-system/components';
import type { ZTableColumn } from '../design-system/components';
import { apiClient, handleApiError } from '../services/api';
import styles from './RevenueSharePage.module.css';

// ── Types ──────────────────────────────────────────────────────────────────────

interface Settlement {
  id: string;
  developer_id: string;
  developer_name: string;
  developer_tier: string;
  developer_email: string;
  period: string;
  installed_plugins: number;
  gross_revenue_fen: number;
  gross_revenue_yuan: number;
  share_pct: number;
  net_payout_fen: number;
  net_payout_yuan: number;
  status: string;
  created_at: string | null;
  settled_at: string | null;
}

interface AdminSummary {
  total_gross_revenue_yuan: number;
  total_net_payout_yuan: number;
  platform_profit_yuan: number;
  pending_count: number;
  approved_count: number;
  paid_count: number;
  developer_count: number;
}

// ── Constants ──────────────────────────────────────────────────────────────────

const STATUS_BADGE: Record<string, 'neutral' | 'warning' | 'success' | 'error'> = {
  pending: 'warning', approved: 'neutral', paid: 'success',
};
const STATUS_LABELS: Record<string, string> = {
  pending: '待审核', approved: '已审核', paid: '已付款',
};
const TIER_BADGE: Record<string, 'neutral' | 'success' | 'warning' | 'error'> = {
  free: 'neutral', basic: 'success', pro: 'warning', enterprise: 'error',
};
const TIER_LABELS: Record<string, string> = {
  free: '免费版', basic: '基础版', pro: '专业版', enterprise: '企业版',
};

function currentPeriod() {
  return new Date().toISOString().slice(0, 7);
}

// ── Table columns ──────────────────────────────────────────────────────────────

const makeColumns = (
  onApprove: (id: string) => void,
  onPay: (id: string) => void,
): ZTableColumn<Settlement>[] => [
  {
    key: 'developer_name',
    title: '开发者',
    render: (name, row) => (
      <div>
        <div style={{ fontWeight: 600 }}>{name}</div>
        <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{row.developer_email}</div>
      </div>
    ),
  },
  { key: 'period', title: '结算周期', render: (p) => <span style={{ fontFamily: 'monospace' }}>{p}</span> },
  {
    key: 'developer_tier',
    title: '套餐',
    align: 'center',
    render: (tier) => <ZBadge type={TIER_BADGE[tier] || 'neutral'} text={TIER_LABELS[tier] || tier} />,
  },
  { key: 'installed_plugins', title: '安装插件', align: 'center', render: (n) => <span style={{ fontWeight: 600 }}>{n}</span> },
  {
    key: 'gross_revenue_yuan',
    title: '总收入',
    align: 'right',
    render: (v) => <span className={styles.amountCell}>¥{Number(v).toFixed(2)}</span>,
  },
  {
    key: 'share_pct',
    title: '分成比例',
    align: 'center',
    render: (v) => `${v}%`,
  },
  {
    key: 'net_payout_yuan',
    title: '应付分成',
    align: 'right',
    render: (v) => <span className={`${styles.amountCell} ${styles.amountCellGreen}`}>¥{Number(v).toFixed(2)}</span>,
  },
  {
    key: 'status',
    title: '状态',
    align: 'center',
    render: (status) => <ZBadge type={STATUS_BADGE[status] || 'neutral'} text={STATUS_LABELS[status] || status} />,
  },
  {
    key: 'settled_at',
    title: '结算时间',
    render: (dt) => dt ? new Date(dt).toLocaleDateString('zh-CN') : '—',
  },
  {
    key: 'id',
    title: '操作',
    render: (id, row) => (
      <div style={{ display: 'flex', gap: 6 }}>
        {row.status === 'pending' && (
          <ZButton variant="primary" onClick={() => onApprove(id)}>审核通过</ZButton>
        )}
        {row.status === 'approved' && (
          <ZButton variant="primary" onClick={() => onPay(id)}>标记已付</ZButton>
        )}
      </div>
    ),
  },
];

// ── Component ──────────────────────────────────────────────────────────────────

const RevenueSharePage: React.FC = () => {
  const [summary, setSummary] = useState<AdminSummary | null>(null);
  const [settlements, setSettlements] = useState<Settlement[]>([]);
  const [loading, setLoading] = useState(false);
  const [period, setPeriod] = useState(currentPeriod());
  const [statusFilter, setStatusFilter] = useState('all');

  // Generate modal
  const [genModal, setGenModal] = useState(false);
  const [genPeriod, setGenPeriod] = useState(currentPeriod());
  const [genLoading, setGenLoading] = useState(false);

  const loadSummary = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/v1/revenue/admin/summary', { params: { period } });
      setSummary(res.data);
    } catch (e) {
      handleApiError(e);
    }
  }, [period]);

  const loadSettlements = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = {};
      if (period) params.period = period;
      if (statusFilter !== 'all') params.status = statusFilter;
      const res = await apiClient.get('/api/v1/revenue/admin/settlements', { params });
      setSettlements(res.data.settlements || []);
    } catch (e) {
      handleApiError(e);
    } finally {
      setLoading(false);
    }
  }, [period, statusFilter]);

  useEffect(() => {
    loadSummary();
    loadSettlements();
  }, [loadSummary, loadSettlements]);

  const handleStatusUpdate = async (id: string, status: 'approved' | 'paid') => {
    try {
      await apiClient.post(`/api/v1/revenue/admin/settlements/${id}/status`, { status });
      message.success(status === 'approved' ? '已审核通过' : '已标记为已付款');
      loadSummary();
      loadSettlements();
    } catch (e) {
      handleApiError(e);
    }
  };

  const handleGenerate = async () => {
    setGenLoading(true);
    try {
      const res = await apiClient.post('/api/v1/revenue/admin/settlements/generate', { period: genPeriod });
      const d = res.data;
      message.success(`${genPeriod} 结算完成：新建 ${d.created} 条，更新 ${d.updated} 条`);
      setGenModal(false);
      setPeriod(genPeriod);
      loadSummary();
      loadSettlements();
    } catch (e) {
      handleApiError(e);
    } finally {
      setGenLoading(false);
    }
  };

  const columns = makeColumns(
    (id) => handleStatusUpdate(id, 'approved'),
    (id) => handleStatusUpdate(id, 'paid'),
  );

  return (
    <div className={styles.page}>
      {/* Header */}
      <div className={styles.pageHeader}>
        <div>
          <h1 className={styles.pageTitle}>收入分成管理</h1>
          <p className={styles.pageSub}>ISV 月度结算 · 审核付款 · 平台收益分析</p>
        </div>
        <div className={styles.headerActions}>
          <ZButton onClick={() => { loadSummary(); loadSettlements(); }}>刷新</ZButton>
          <ZButton variant="primary" onClick={() => setGenModal(true)}>生成结算</ZButton>
        </div>
      </div>

      {/* KPI */}
      <div className={styles.kpiGrid}>
        {!summary ? (
          [...Array(4)].map((_, i) => <ZSkeleton key={i} height={88} />)
        ) : (
          <>
            <ZCard>
              <ZKpi label="期间总收入" value={`¥${summary.total_gross_revenue_yuan.toFixed(2)}`} />
            </ZCard>
            <ZCard>
              <ZKpi label="待发分成" value={`¥${summary.total_net_payout_yuan.toFixed(2)}`} />
            </ZCard>
            <ZCard>
              <ZKpi label="平台净利润" value={`¥${summary.platform_profit_yuan.toFixed(2)}`} />
            </ZCard>
            <ZCard>
              <ZKpi label="待审核" value={summary.pending_count} unit="条" />
            </ZCard>
          </>
        )}
      </div>

      {/* Filter + Table */}
      <ZCard
        title={`结算记录（${settlements.length} 条）`}
        extra={
          <div className={styles.filterBar}>
            <input
              type="month"
              className={styles.periodInput}
              value={period}
              onChange={e => setPeriod(e.target.value)}
            />
            <select
              className={styles.nativeSelect}
              style={{ width: 120 }}
              value={statusFilter}
              onChange={e => setStatusFilter(e.target.value)}
            >
              <option value="all">全部状态</option>
              <option value="pending">待审核</option>
              <option value="approved">已审核</option>
              <option value="paid">已付款</option>
            </select>
          </div>
        }
      >
        {loading ? <ZSkeleton height={300} /> : (
          settlements.length > 0
            ? <ZTable columns={columns} data={settlements} rowKey="id" />
            : <ZEmpty text="暂无结算记录" />
        )}
      </ZCard>

      {/* Generate settlement modal */}
      <ZModal
        open={genModal}
        title="生成月度结算"
        onClose={() => setGenModal(false)}
        footer={
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <ZButton onClick={() => setGenModal(false)}>取消</ZButton>
            <ZButton variant="primary" disabled={genLoading} onClick={handleGenerate}>
              {genLoading ? '生成中…' : '确认生成'}
            </ZButton>
          </div>
        }
        width={400}
      >
        <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 16 }}>
          系统将统计所有活跃 ISV 开发者的插件安装量，按套餐分成比例计算应付金额，生成结算记录。
        </p>
        <div>
          <label style={{ display: 'block', fontSize: 13, marginBottom: 6, fontWeight: 500 }}>结算周期</label>
          <input
            type="month"
            className={styles.periodInput}
            style={{ width: '100%' }}
            value={genPeriod}
            onChange={e => setGenPeriod(e.target.value)}
          />
        </div>
        <p style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 12 }}>
          若已有该周期记录（非已付款状态），将重新计算并更新。
        </p>
      </ZModal>
    </div>
  );
};

export default RevenueSharePage;
