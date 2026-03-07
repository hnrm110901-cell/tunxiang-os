import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { ZCard, ZKpi, ZBadge, ZButton, ZSkeleton, ZTable, ZEmpty, ZModal } from '../design-system/components';
import type { ZTableColumn } from '../design-system/components';
import { apiClient, handleApiError } from '../services/api';
import styles from './ApiBillingPage.module.css';

// ── Types ────────────────────────────────────────────────────────────────────

interface BillingCycle {
  id: string;
  developer_id: string;
  period: string;
  total_calls: number;
  billable_calls: number;
  free_quota: number;
  overage_calls: number;
  amount_fen: number;
  amount_yuan: number;
  status: 'draft' | 'finalized' | 'invoiced';
  finalized_at: string | null;
  created_at: string | null;
}

interface Invoice {
  id: string;
  cycle_id: string;
  developer_id: string;
  period: string;
  invoice_no: string;
  amount_yuan: number;
  line_items: LineItem[] | null;
  status: 'unpaid' | 'paid' | 'void';
  issued_at: string | null;
  paid_at: string | null;
}

interface LineItem {
  description: string;
  quantity: number;
  unit_price_yuan: number;
  amount_yuan: number;
}

interface AdminSummary {
  monthly_revenue: { period: string; total_yuan: number; dev_count: number; total_calls: number }[];
  invoice_summary: Record<string, { count: number; total_yuan: number }>;
  outstanding_yuan: number;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const STATUS_CYCLE: Record<string, 'neutral' | 'warning' | 'success'> = {
  draft:     'neutral',
  finalized: 'warning',
  invoiced:  'success',
};

const STATUS_INV: Record<string, 'neutral' | 'error' | 'success'> = {
  unpaid: 'error',
  paid:   'success',
  void:   'neutral',
};

const DEVELOPER_ID = localStorage.getItem('developer_id') || 'dev-demo-001';

// ── Cycle columns ─────────────────────────────────────────────────────────────

const cycleColumns = (
  onFinalize: (id: string) => void,
  onInvoice:  (id: string) => void,
): ZTableColumn<BillingCycle>[] => [
  { key: 'period', title: '账单周期' },
  {
    key: 'status',
    title: '状态',
    align: 'center',
    render: (v) => <ZBadge type={STATUS_CYCLE[v] || 'neutral'} text={
      v === 'draft' ? '草稿' : v === 'finalized' ? '已锁定' : '已开票'
    } />,
  },
  {
    key: 'total_calls',
    title: '总调用',
    align: 'right',
    render: (v) => <span className={styles.mono}>{Number(v).toLocaleString()}</span>,
  },
  {
    key: 'free_quota',
    title: '免费额度',
    align: 'right',
    render: (v) => <span className={styles.mono} style={{ color: 'var(--text-secondary)' }}>{Number(v).toLocaleString()}</span>,
  },
  {
    key: 'overage_calls',
    title: '超量调用',
    align: 'right',
    render: (v) => <span className={styles.mono} style={{ color: v > 0 ? 'var(--accent)' : 'var(--text-secondary)' }}>
      {Number(v).toLocaleString()}
    </span>,
  },
  {
    key: 'amount_yuan',
    title: '账单金额',
    align: 'right',
    render: (v) => <span className={styles.amountCell}>¥{Number(v).toFixed(2)}</span>,
  },
  {
    key: 'id',
    title: '操作',
    align: 'center',
    render: (id, row) => (
      <div style={{ display: 'flex', gap: 6, justifyContent: 'center' }}>
        {row.status === 'draft' && (
          <ZButton onClick={() => onFinalize(id)}>锁定</ZButton>
        )}
        {row.status === 'finalized' && (
          <ZButton onClick={() => onInvoice(id)}>开票</ZButton>
        )}
      </div>
    ),
  },
];

// ── Invoice columns ───────────────────────────────────────────────────────────

const invoiceColumns = (
  onPay: (id: string) => void,
  onDetail: (inv: Invoice) => void,
): ZTableColumn<Invoice>[] => [
  { key: 'invoice_no', title: '发票号', render: (v) => <code className={styles.invNo}>{v}</code> },
  { key: 'period',     title: '周期' },
  {
    key: 'status',
    title: '状态',
    align: 'center',
    render: (v) => <ZBadge type={STATUS_INV[v] || 'neutral'} text={
      v === 'unpaid' ? '待付款' : v === 'paid' ? '已付款' : '已作废'
    } />,
  },
  {
    key: 'amount_yuan',
    title: '金额',
    align: 'right',
    render: (v) => <span className={styles.amountCell}>¥{Number(v).toFixed(2)}</span>,
  },
  {
    key: 'issued_at',
    title: '开票时间',
    render: (v) => v ? v.slice(0, 10) : '—',
  },
  {
    key: 'id',
    title: '操作',
    align: 'center',
    render: (id, row) => (
      <div style={{ display: 'flex', gap: 6, justifyContent: 'center' }}>
        <ZButton onClick={() => onDetail(row)}>明细</ZButton>
        {row.status === 'unpaid' && (
          <ZButton onClick={() => onPay(id)}>标记已付</ZButton>
        )}
      </div>
    ),
  },
];

// ── Component ─────────────────────────────────────────────────────────────────

const currentPeriod = (): string => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
};

const ApiBillingPage: React.FC = () => {
  const [cycles, setCycles]         = useState<BillingCycle[]>([]);
  const [invoices, setInvoices]     = useState<Invoice[]>([]);
  const [summary, setSummary]       = useState<AdminSummary | null>(null);
  const [loading, setLoading]       = useState(false);
  const [computing, setComputing]   = useState(false);
  const [detailInv, setDetailInv]   = useState<Invoice | null>(null);
  const [computePeriod, setComputePeriod] = useState(currentPeriod());

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [cycleRes, invRes, sumRes] = await Promise.allSettled([
        apiClient.get('/api/v1/billing/cycles',     { params: { developer_id: DEVELOPER_ID } }),
        apiClient.get('/api/v1/billing/invoices',   { params: { developer_id: DEVELOPER_ID } }),
        apiClient.get('/api/v1/billing/admin/summary'),
      ]);
      if (cycleRes.status === 'fulfilled') setCycles(cycleRes.value.data.cycles || []);
      if (invRes.status === 'fulfilled')   setInvoices(invRes.value.data.invoices || []);
      if (sumRes.status === 'fulfilled')   setSummary(sumRes.value.data);
    } catch (e) { handleApiError(e); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  const computeCycle = async () => {
    setComputing(true);
    try {
      await apiClient.post('/api/v1/billing/cycles/compute', {
        developer_id: DEVELOPER_ID,
        period: computePeriod,
      });
      loadAll();
    } catch (e) { handleApiError(e); }
    finally { setComputing(false); }
  };

  const finalizeCycle = async (cycleId: string) => {
    try {
      await apiClient.post(`/api/v1/billing/cycles/${cycleId}/finalize`, null, {
        params: { developer_id: DEVELOPER_ID },
      });
      loadAll();
    } catch (e) { handleApiError(e); }
  };

  const generateInvoice = async (cycleId: string) => {
    try {
      await apiClient.post(`/api/v1/billing/cycles/${cycleId}/invoice`, null, {
        params: { developer_id: DEVELOPER_ID },
      });
      loadAll();
    } catch (e) { handleApiError(e); }
  };

  const markPaid = async (invoiceId: string) => {
    try {
      await apiClient.post(`/api/v1/billing/invoices/${invoiceId}/pay`);
      loadAll();
    } catch (e) { handleApiError(e); }
  };

  // Summary KPIs
  const totalRevenue = useMemo(
    () => (summary?.monthly_revenue || []).reduce((s, m) => s + m.total_yuan, 0),
    [summary]
  );
  const unpaidTotal  = summary?.outstanding_yuan || 0;
  const paidTotal    = summary?.invoice_summary?.paid?.total_yuan || 0;

  const cols = useMemo(() => cycleColumns(finalizeCycle, generateInvoice), []);
  const invCols = useMemo(() => invoiceColumns(markPaid, setDetailInv), []);

  return (
    <div className={styles.page}>
      {/* Header */}
      <div className={styles.pageHeader}>
        <div>
          <h1 className={styles.pageTitle}>API 计量计费</h1>
          <p className={styles.pageSub}>按开发者套餐统计 API 用量，生成账单与发票</p>
        </div>
        <div className={styles.headerActions}>
          <input
            type="month"
            className={styles.monthInput}
            value={computePeriod}
            onChange={e => setComputePeriod(e.target.value)}
          />
          <ZButton onClick={computeCycle} disabled={computing}>
            {computing ? '计算中…' : '计算账单'}
          </ZButton>
          <ZButton onClick={loadAll}>刷新</ZButton>
        </div>
      </div>

      {/* KPIs */}
      <div className={styles.kpiGrid}>
        <ZCard><ZKpi label="累计平台收入" value={`¥${totalRevenue.toFixed(2)}`} /></ZCard>
        <ZCard><ZKpi label="待收款" value={`¥${unpaidTotal.toFixed(2)}`} /></ZCard>
        <ZCard><ZKpi label="已收款" value={`¥${paidTotal.toFixed(2)}`} /></ZCard>
        <ZCard><ZKpi label="账单周期数" value={cycles.length} unit="个" /></ZCard>
      </div>

      {/* Billing cycles table */}
      <ZCard title="账单周期">
        {loading ? (
          <ZSkeleton height={200} />
        ) : cycles.length > 0 ? (
          <ZTable columns={cols} data={cycles} rowKey="id" />
        ) : (
          <ZEmpty text="暂无账单，请先点击「计算账单」生成当月账单" />
        )}
      </ZCard>

      {/* Invoices table */}
      <ZCard title="发票列表">
        {loading ? (
          <ZSkeleton height={200} />
        ) : invoices.length > 0 ? (
          <ZTable columns={invCols} data={invoices} rowKey="id" />
        ) : (
          <ZEmpty text="暂无发票，请先锁定账单后开票" />
        )}
      </ZCard>

      {/* Invoice detail modal */}
      <ZModal
        open={!!detailInv}
        title={detailInv ? `发票明细 — ${detailInv.invoice_no}` : ''}
        onClose={() => setDetailInv(null)}
        footer={<ZButton onClick={() => setDetailInv(null)}>关闭</ZButton>}
      >
        {detailInv && (
          <div className={styles.invDetail}>
            <div className={styles.invMetaRow}>
              <span>周期：<b>{detailInv.period}</b></span>
              <span>状态：<ZBadge type={STATUS_INV[detailInv.status] || 'neutral'} text={
                detailInv.status === 'unpaid' ? '待付款' : detailInv.status === 'paid' ? '已付款' : '已作废'
              } /></span>
            </div>
            <div className={styles.lineItems}>
              {(detailInv.line_items || []).map((item, i) => (
                <div key={i} className={styles.lineItem}>
                  <div className={styles.lineDesc}>{item.description}</div>
                  <div className={styles.lineRight}>
                    <span className={styles.lineQty}>{Number(item.quantity).toLocaleString()} 次</span>
                    <span className={styles.amountCell}>¥{Number(item.amount_yuan).toFixed(2)}</span>
                  </div>
                </div>
              ))}
            </div>
            <div className={styles.invTotal}>
              合计：<span className={styles.amountCell}>¥{Number(detailInv.amount_yuan).toFixed(2)}</span>
            </div>
          </div>
        )}
      </ZModal>
    </div>
  );
};

export default ApiBillingPage;
