import React, { useState, useEffect, useCallback, useMemo } from 'react';
import ReactECharts from 'echarts-for-react';
import { ZCard, ZKpi, ZBadge, ZButton, ZSkeleton, ZTable, ZEmpty } from '../design-system/components';
import type { ZTableColumn } from '../design-system/components';
import { apiClient, handleApiError } from '../services/api';
import styles from './SettlementRiskPage.module.css';

// ── Types ─────────────────────────────────────────────────────────────────────

interface SettlementRecord {
  id: string;
  store_id: string;
  platform: string;
  platform_label: string;
  period: string;
  settlement_no: string | null;
  settle_date: string;
  gross_yuan: number;
  commission_yuan: number;
  refund_yuan: number;
  net_yuan: number;
  expected_yuan: number;
  deviation_yuan: number;
  deviation_pct: number;
  risk_level: string;
  status: string;
}

interface RiskTask {
  id: string;
  risk_type: string;
  severity: string;
  title: string;
  description: string;
  amount_yuan: number;
  status: string;
  due_date: string | null;
  created_at: string | null;
}

interface SettlementSummary {
  settlement: {
    total_records: number;
    total_gross_yuan: number;
    total_net_yuan: number;
    total_commission_yuan: number;
    total_refund_yuan: number;
    high_risk_count: number;
    pending_count: number;
  };
  by_platform: Array<{
    platform: string;
    platform_label: string;
    net_yuan: number;
    record_count: number;
  }>;
  risk_tasks: { open_total: number; high_priority: number };
}

// ── Constants ─────────────────────────────────────────────────────────────────

const STORE_ID = localStorage.getItem('store_id') || 'store-demo-001';
const today    = new Date().toISOString().slice(0, 10);
const period   = today.slice(0, 7);

const RISK_BADGE: Record<string, 'neutral' | 'success' | 'warning' | 'error'> = {
  low: 'success', medium: 'warning', high: 'error', critical: 'error',
};
const RISK_LABELS: Record<string, string> = {
  low: '低', medium: '中', high: '高', critical: '严重',
};
const STATUS_BADGE: Record<string, 'neutral' | 'warning' | 'success' | 'error'> = {
  pending: 'warning', verified: 'success', disputed: 'error', auto_closed: 'neutral',
};
const STATUS_LABELS: Record<string, string> = {
  pending: '待核销', verified: '已核销', disputed: '有争议', auto_closed: '自动关闭',
};
const SEV_BADGE: Record<string, 'neutral' | 'warning' | 'error'> = {
  low: 'neutral', medium: 'warning', high: 'error', critical: 'error',
};

// ── Record columns ────────────────────────────────────────────────────────────

const recordColumns: ZTableColumn<SettlementRecord>[] = [
  {
    key: 'settle_date',
    title: '结算日',
    render: (v) => <span className={styles.mono}>{v}</span>,
  },
  { key: 'platform_label', title: '平台' },
  {
    key: 'gross_yuan',
    title: '流水',
    align: 'right',
    render: (v) => <span className={styles.mono}>¥{Number(v).toFixed(2)}</span>,
  },
  {
    key: 'commission_yuan',
    title: '抽佣',
    align: 'right',
    render: (v) => <span className={styles.mono}>¥{Number(v).toFixed(2)}</span>,
  },
  {
    key: 'net_yuan',
    title: '实收',
    align: 'right',
    render: (v) => <span className={styles.amount}>¥{Number(v).toFixed(2)}</span>,
  },
  {
    key: 'deviation_yuan',
    title: '偏差',
    align: 'right',
    render: (v, row) => {
      const d = Number(v);
      if (d === 0) return <span className={styles.mono}>—</span>;
      return (
        <span className={d < 0 ? styles.devWarn : styles.devOk}>
          {d > 0 ? '+' : ''}¥{d.toFixed(2)}
          <span style={{ fontSize: 10, marginLeft: 3 }}>({Number(row.deviation_pct).toFixed(1)}%)</span>
        </span>
      );
    },
  },
  {
    key: 'risk_level',
    title: '风险',
    align: 'center',
    render: (v) => <ZBadge type={RISK_BADGE[v] || 'neutral'} text={RISK_LABELS[v] || v} />,
  },
  {
    key: 'status',
    title: '状态',
    align: 'center',
    render: (v) => <ZBadge type={STATUS_BADGE[v] || 'neutral'} text={STATUS_LABELS[v] || v} />,
  },
];

// ── Risk task columns ─────────────────────────────────────────────────────────

const taskColumns: ZTableColumn<RiskTask>[] = [
  {
    key: 'severity',
    title: '严重度',
    align: 'center',
    render: (v) => <ZBadge type={SEV_BADGE[v] || 'neutral'} text={RISK_LABELS[v] || v} />,
  },
  {
    key: 'title',
    title: '风险描述',
    render: (v, row) => (
      <div>
        <div style={{ fontWeight: 600, fontSize: 13 }}>{v}</div>
        {row.description && (
          <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 2 }}>{row.description}</div>
        )}
      </div>
    ),
  },
  {
    key: 'amount_yuan',
    title: '涉及金额',
    align: 'right',
    render: (v) => <span className={styles.amount}>¥{Number(v).toFixed(2)}</span>,
  },
  {
    key: 'status',
    title: '状态',
    align: 'center',
    render: (v) => (
      <ZBadge
        type={v === 'open' ? 'error' : v === 'in_progress' ? 'warning' : 'success'}
        text={v === 'open' ? '待处理' : v === 'in_progress' ? '处理中' : v === 'resolved' ? '已解决' : '已忽略'}
      />
    ),
  },
];

// ── Component ─────────────────────────────────────────────────────────────────

const SettlementRiskPage: React.FC = () => {
  const [summary, setSummary]     = useState<SettlementSummary | null>(null);
  const [records, setRecords]     = useState<SettlementRecord[]>([]);
  const [tasks, setTasks]         = useState<RiskTask[]>([]);
  const [loading, setLoading]     = useState(false);
  const [scanning, setScanning]   = useState(false);
  const [activeTab, setActiveTab] = useState<'records' | 'tasks'>('records');
  const [riskFilter, setRiskFilter] = useState('');

  const loadSummary = useCallback(async () => {
    try {
      const res = await apiClient.get(`/api/v1/settlement/summary/${STORE_ID}`, {
        params: { period },
      });
      setSummary(res.data);
    } catch (e) { handleApiError(e); }
  }, []);

  const loadRecords = useCallback(async () => {
    try {
      const params: Record<string, string | number> = {
        store_id: STORE_ID, period, limit: 100, offset: 0,
      };
      if (riskFilter) params.risk_level = riskFilter;
      const res = await apiClient.get('/api/v1/settlement/records', { params });
      setRecords(res.data.records || []);
    } catch (e) { handleApiError(e); }
  }, [riskFilter]);

  const loadTasks = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/v1/settlement/risk-tasks', {
        params: { store_id: STORE_ID, limit: 100 },
      });
      setTasks(res.data.tasks || []);
    } catch (e) { handleApiError(e); }
  }, []);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      await Promise.allSettled([loadSummary(), loadRecords(), loadTasks()]);
    } finally { setLoading(false); }
  }, [loadSummary, loadRecords, loadTasks]);

  useEffect(() => { loadAll(); }, [loadAll]);
  useEffect(() => { loadRecords(); }, [loadRecords]);

  const scanOverdue = async () => {
    setScanning(true);
    try {
      const res = await apiClient.post('/api/v1/settlement/scan/overdue', null, {
        params: { store_id: STORE_ID },
      });
      await loadAll();
    } catch (e) { handleApiError(e); }
    finally { setScanning(false); }
  };

  const resolveTask = async (taskId: string) => {
    try {
      await apiClient.post(`/api/v1/settlement/risk-tasks/${taskId}/resolve`, {});
      await loadTasks();
      await loadSummary();
    } catch (e) { handleApiError(e); }
  };

  // ── Platform pie chart ────────────────────────────────────────────────────

  const platformChartOption = useMemo(() => {
    if (!summary?.by_platform.length) return {};
    return {
      tooltip: { trigger: 'item', formatter: '{b}: ¥{c} ({d}%)' },
      series: [{
        type: 'pie',
        radius: ['45%', '70%'],
        data: summary.by_platform.map(p => ({
          name:  p.platform_label,
          value: p.net_yuan.toFixed(2),
        })),
        label: { fontSize: 11 },
      }],
    };
  }, [summary]);

  const s = summary?.settlement;
  const openHighTasks = tasks.filter(t => t.status === 'open' && (t.severity === 'high' || t.severity === 'critical')).length;

  return (
    <div className={styles.page}>
      {/* Header */}
      <div className={styles.pageHeader}>
        <div>
          <h1 className={styles.pageTitle}>结算风控</h1>
          <p className={styles.pageSub}>平台结算对账 · 风控待办 · {period}</p>
        </div>
        <div className={styles.headerActions}>
          <ZButton onClick={scanOverdue} disabled={scanning}>
            {scanning ? '扫描中…' : '逾期扫描'}
          </ZButton>
          <ZButton onClick={loadAll}>刷新</ZButton>
        </div>
      </div>

      {/* KPI row */}
      <div className={styles.kpiGrid}>
        {loading && !s ? (
          [...Array(4)].map((_, i) => <ZSkeleton key={i} height={88} />)
        ) : (
          <>
            <ZCard>
              <ZKpi label="本月实收合计" value={`¥${(s?.total_net_yuan ?? 0).toFixed(0)}`} />
              <div className={styles.kpiSub}>
                流水 ¥{(s?.total_gross_yuan ?? 0).toFixed(0)}
              </div>
            </ZCard>
            <ZCard>
              <ZKpi label="平台抽佣" value={`¥${(s?.total_commission_yuan ?? 0).toFixed(0)}`} />
              <div className={styles.kpiSub}>
                抽佣率{' '}
                {s?.total_gross_yuan
                  ? ((s.total_commission_yuan / s.total_gross_yuan) * 100).toFixed(1)
                  : '0.0'}%
              </div>
            </ZCard>
            <ZCard>
              <ZKpi label="高风险结算" value={s?.high_risk_count ?? 0} unit="笔" />
              <div className={(s?.pending_count ?? 0) > 0 ? styles.kpiSubWarn : styles.kpiSub}>
                {s?.pending_count ?? 0} 笔待核销
              </div>
            </ZCard>
            <ZCard>
              <ZKpi label="开放风控任务" value={summary?.risk_tasks.open_total ?? 0} unit="项" />
              <div className={openHighTasks > 0 ? styles.kpiSubWarn : styles.kpiSub}>
                {openHighTasks > 0 ? `⚠ ${openHighTasks} 项高优先级` : '无高优先级风险'}
              </div>
            </ZCard>
          </>
        )}
      </div>

      {/* Platform donut + Tab section */}
      <div className={styles.mainLayout}>
        {/* Platform breakdown */}
        <ZCard title="平台结算分布">
          {loading ? <ZSkeleton height={200} /> :
           summary?.by_platform.length ? (
             <div className={styles.donut}>
               <ReactECharts option={platformChartOption} style={{ height: '100%' }} />
             </div>
           ) : <ZEmpty text="暂无数据" />}
        </ZCard>

        {/* Records + Tasks tabs */}
        <ZCard style={{ flex: 1 }}>
          <div className={styles.tabBar}>
            {(['records', 'tasks'] as const).map(tab => (
              <button
                key={tab}
                className={`${styles.tab} ${activeTab === tab ? styles.tabActive : ''}`}
                onClick={() => setActiveTab(tab)}
              >
                {{ records: `结算记录 (${records.length})`, tasks: `风控待办 (${tasks.filter(t => t.status === 'open').length})` }[tab]}
              </button>
            ))}
          </div>

          {activeTab === 'records' && (
            <div>
              <div className={styles.filterRow}>
                <select
                  className={styles.filterSelect}
                  value={riskFilter}
                  onChange={e => setRiskFilter(e.target.value)}
                >
                  <option value="">全部风险</option>
                  <option value="critical">严重</option>
                  <option value="high">高</option>
                  <option value="medium">中</option>
                  <option value="low">低</option>
                </select>
              </div>
              {loading ? <ZSkeleton height={200} /> :
               records.length > 0
                 ? <ZTable columns={recordColumns} data={records} rowKey="id" />
                 : <ZEmpty text="暂无结算记录" />
              }
            </div>
          )}

          {activeTab === 'tasks' && (
            loading ? <ZSkeleton height={200} /> :
            tasks.length > 0 ? (
              <div>
                {tasks.map(t => (
                  <div key={t.id} className={`${styles.taskCard} ${t.status !== 'open' ? styles.taskDone : ''}`}>
                    <div className={styles.taskHeader}>
                      <ZBadge type={SEV_BADGE[t.severity] || 'neutral'} text={RISK_LABELS[t.severity] || t.severity} />
                      <span className={styles.taskTitle}>{t.title}</span>
                      <span style={{ flex: 1 }} />
                      <span className={styles.amount}>¥{t.amount_yuan.toFixed(2)}</span>
                    </div>
                    {t.description && (
                      <div className={styles.taskDesc}>{t.description}</div>
                    )}
                    {t.status === 'open' && (
                      <ZButton onClick={() => resolveTask(t.id)}>标记已解决</ZButton>
                    )}
                  </div>
                ))}
              </div>
            ) : <ZEmpty text="暂无风控任务" />
          )}
        </ZCard>
      </div>
    </div>
  );
};

export default SettlementRiskPage;
