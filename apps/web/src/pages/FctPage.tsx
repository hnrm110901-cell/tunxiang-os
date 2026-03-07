/**
 * FctPage
 * 业财税资金一体化（FCT）— 仪表盘 / 税务测算 / 资金流预测 / 预算执行
 */
import React, { useState, useCallback } from 'react';
import { InputNumber, message } from 'antd';
import {
  DashboardOutlined, CalculatorOutlined, FundOutlined,
  BarChartOutlined, SaveOutlined, ReloadOutlined,
} from '@ant-design/icons';
import axios from 'axios';
import dayjs from 'dayjs';
import {
  ZCard, ZKpi, ZBadge, ZButton, ZSkeleton, ZSelect, ZTable, ZTabs,
} from '../design-system/components';
import type { ZTableColumn } from '../design-system/components/ZTable';
import styles from './FctPage.module.css';

// ── Constants ────────────────────────────────────────────────────────────────

const STORE_ID = localStorage.getItem('store_id') || '';

const now = dayjs();
const DEFAULT_YEAR  = now.month() === 0 ? now.year() - 1 : now.year();
const DEFAULT_MONTH = now.month() === 0 ? 12 : now.month();

// ── Dashboard Tab ─────────────────────────────────────────────────────────────

const DashboardTab: React.FC = () => {
  const [data, setData]       = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const fetch = useCallback(async () => {
    setLoading(true);
    try {
      const { data: d } = await axios.get(`/api/v1/fct/${STORE_ID}/dashboard`);
      setData(d);
    } catch {
      message.error('加载 FCT 仪表盘失败');
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { fetch(); }, [fetch]);

  if (loading) return <ZSkeleton rows={4} block />;
  if (!data) return (
    <ZButton icon={<ReloadOutlined />} onClick={fetch}>重新加载</ZButton>
  );

  const healthColor = (score: number) =>
    score >= 80 ? '#3f8600' : score >= 60 ? '#d46b08' : '#cf1322';

  return (
    <div>
      <div className={styles.kpiGrid4}>
        <ZCard>
          <ZKpi
            value={data.health_score ?? 0}
            unit="/ 100"
            label="FCT 健康分"
          />
        </ZCard>
        <ZCard>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 4 }}>7 日净流</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: healthColor(data.cash_flow?.net_7d_yuan >= 0 ? 80 : 0) }}>
            ¥{(data.cash_flow?.net_7d_yuan ?? (data.cash_flow?.net_7d ?? 0) / 100).toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
          </div>
        </ZCard>
        <ZCard>
          <ZKpi
            value={`¥${(data.tax?.total_tax_yuan ?? (data.tax?.total_tax ?? 0) / 100).toFixed(0)}`}
            label="当月估算税额"
          />
        </ZCard>
        <ZCard>
          <ZKpi
            value={(data.budget?.profit_margin_pct ?? 0).toFixed(1)}
            unit="%"
            label="当月利润率"
          />
        </ZCard>
      </div>

      {data.cash_flow?.alerts?.length > 0 && (
        <div className={`${styles.alertBar} ${styles.alertWarning}`} style={{ marginTop: 16 }}>
          资金预警：{data.cash_flow.alerts.length} 个风险日 — {data.cash_flow.alerts.slice(0, 3).join('、')}
        </div>
      )}
      {data.budget?.alerts?.length > 0 && (
        <div className={`${styles.alertBar} ${styles.alertError}`} style={{ marginTop: 8 }}>
          超预算科目：{data.budget.alerts.length} 项 — {data.budget.alerts.slice(0, 3).join('、')}
        </div>
      )}
    </div>
  );
};

// ── Tax Estimation Tab ────────────────────────────────────────────────────────

const taxTypeOptions = [
  { value: 'general', label: '一般纳税人' },
  { value: 'small',   label: '小规模纳税人' },
  { value: 'micro',   label: '微型企业' },
];

const TaxTab: React.FC = () => {
  const [year,    setYear]    = useState(DEFAULT_YEAR);
  const [month,   setMonth]   = useState(DEFAULT_MONTH);
  const [type,    setType]    = useState('general');
  const [data,    setData]    = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [saving,  setSaving]  = useState(false);

  const estimate = async () => {
    setLoading(true);
    try {
      const { data: d } = await axios.get(
        `/api/v1/fct/${STORE_ID}/tax/${year}/${month}`,
        { params: { taxpayer_type: type } },
      );
      setData(d);
    } catch {
      message.error('税务测算失败');
    } finally {
      setLoading(false);
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      await axios.post(
        `/api/v1/fct/${STORE_ID}/tax/${year}/${month}/save`,
        null,
        { params: { taxpayer_type: type } },
      );
      message.success('税务记录已保存');
    } catch {
      message.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div className={styles.toolbar}>
        <InputNumber min={2020} max={2099} value={year} onChange={v => setYear(v || DEFAULT_YEAR)} addonBefore="年份" />
        <InputNumber min={1} max={12} value={month} onChange={v => setMonth(v || DEFAULT_MONTH)} addonBefore="月份" />
        <ZSelect value={type} options={taxTypeOptions} onChange={v => setType(v as string)} style={{ width: 160 }} />
        <ZButton variant="primary" icon={<CalculatorOutlined />} onClick={estimate} disabled={loading}>
          开始测算
        </ZButton>
        {data && (
          <ZButton icon={<SaveOutlined />} onClick={save} disabled={saving}>
            保存记录
          </ZButton>
        )}
      </div>

      {loading && <ZSkeleton rows={6} block />}

      {!loading && data && (
        <div className={styles.twoColGrid}>
          <ZCard title="汇总">
            <dl className={styles.descList}>
              <div className={styles.descRow}><dt>期间</dt><dd>{data.period}</dd></div>
              <div className={styles.descRow}><dt>纳税人类型</dt><dd>{data.taxpayer_type}</dd></div>
              <div className={styles.descRow}>
                <dt>合计税额</dt>
                <dd><strong style={{ color: '#cf1322' }}>¥{(data.total_tax_yuan ?? (data.total_tax || 0) / 100).toLocaleString()}</strong></dd>
              </div>
              <div className={styles.descRow}><dt>综合税负率</dt><dd>{(data.effective_rate || 0).toFixed(2)}%</dd></div>
            </dl>
          </ZCard>
          <ZCard title="增值税">
            <dl className={styles.descList}>
              <div className={styles.descRow}><dt>销项税</dt><dd>¥{(data.vat?.output_vat_yuan ?? (data.vat?.output_vat || 0) / 100).toLocaleString()}</dd></div>
              <div className={styles.descRow}><dt>进项税</dt><dd>¥{(data.vat?.input_vat_yuan ?? (data.vat?.input_vat || 0) / 100).toLocaleString()}</dd></div>
              <div className={styles.descRow}><dt>应纳增值税</dt><dd>¥{(data.vat?.net_vat_yuan ?? (data.vat?.net_vat || 0) / 100).toLocaleString()}</dd></div>
              <div className={styles.descRow}><dt>附加税</dt><dd>¥{(data.vat?.surcharge_yuan ?? (data.vat?.surcharge || 0) / 100).toLocaleString()}</dd></div>
            </dl>
          </ZCard>
          <ZCard title="企业所得税">
            <dl className={styles.descList}>
              <div className={styles.descRow}><dt>应税收入</dt><dd>¥{(data.cit?.taxable_income_yuan ?? (data.cit?.taxable_income || 0) / 100).toLocaleString()}</dd></div>
              <div className={styles.descRow}><dt>假定利润率</dt><dd>{(data.cit?.assumed_margin || 0).toFixed(0)}%</dd></div>
              <div className={styles.descRow}><dt>税率</dt><dd>{(data.cit?.cit_rate || 0).toFixed(0)}%</dd></div>
              <div className={styles.descRow}><dt>应缴所得税</dt><dd>¥{(data.cit?.cit_amount_yuan ?? (data.cit?.cit_amount || 0) / 100).toLocaleString()}</dd></div>
            </dl>
          </ZCard>
          <ZCard title="收入基础">
            <dl className={styles.descList}>
              <div className={styles.descRow}><dt>POS 总收入</dt><dd>¥{(data.revenue?.pos_total_yuan ?? (data.revenue?.pos_total || 0) / 100).toLocaleString()}</dd></div>
              <div className={styles.descRow}><dt>订单数</dt><dd>{data.revenue?.order_count || 0}</dd></div>
              <div className={styles.descRow}><dt>均单价</dt><dd>¥{(data.revenue?.avg_order_yuan ?? (data.revenue?.avg_order || 0) / 100).toFixed(0)}</dd></div>
            </dl>
          </ZCard>
          <div style={{ gridColumn: '1 / -1' }}>
            <div className={`${styles.alertBar} ${styles.alertInfo}`}>{data.disclaimer}</div>
          </div>
        </div>
      )}
    </div>
  );
};

// ── Cash Flow Tab ─────────────────────────────────────────────────────────────

const cashFlowColumns: ZTableColumn<any>[] = [
  { key: 'date', title: '日期', width: 100 },
  {
    key:    'inflow_yuan',
    title:  '进流 (¥)',
    align:  'right',
    render: (v: number, row: any) => {
      const val = v ?? (row.inflow || 0) / 100;
      return <span style={{ color: '#3f8600' }}>+{val.toLocaleString()}</span>;
    },
  },
  {
    key:    'outflow_yuan',
    title:  '出流 (¥)',
    align:  'right',
    render: (v: number, row: any) => {
      const val = v ?? (row.outflow || 0) / 100;
      return <span style={{ color: '#cf1322' }}>-{val.toLocaleString()}</span>;
    },
  },
  {
    key:    'cumulative_balance_yuan',
    title:  '累计余额 (¥)',
    align:  'right',
    render: (v: number, row: any) => {
      const val = v ?? (row.cumulative_balance || 0) / 100;
      return <strong style={{ color: val >= 0 ? '#3f8600' : '#cf1322' }}>{val.toLocaleString()}</strong>;
    },
  },
  {
    key:    'confidence',
    title:  '置信度',
    width:  100,
    render: (v: number) => (
      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        <div style={{ width: 60, height: 5, background: '#f0f0f0', borderRadius: 3, overflow: 'hidden' }}>
          <div style={{ width: `${Math.round(v * 100)}%`, height: '100%', background: 'var(--accent)', borderRadius: 3 }} />
        </div>
        <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>{Math.round(v * 100)}%</span>
      </div>
    ),
  },
  {
    key:    'is_alert',
    title:  '预警',
    width:  70,
    align:  'center',
    render: (v: boolean) => (
      <ZBadge type={v ? 'critical' : 'success'} text={v ? '预警' : '正常'} />
    ),
  },
];

const CashFlowTab: React.FC = () => {
  const [days,    setDays]    = useState(30);
  const [balance, setBalance] = useState(0);
  const [data,    setData]    = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const forecast = async () => {
    setLoading(true);
    try {
      const { data: d } = await axios.get(`/api/v1/fct/${STORE_ID}/cash-flow`, {
        params: { days, starting_balance: Math.round(balance * 100) },
      });
      setData(d);
    } catch {
      message.error('资金流预测失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div className={styles.toolbar}>
        <InputNumber min={7} max={90} value={days} onChange={v => setDays(v || 30)} addonBefore="预测天数" addonAfter="天" />
        <InputNumber
          min={0} value={balance} onChange={v => setBalance(v || 0)}
          addonBefore="当前余额 ¥"
          formatter={v => `${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
        />
        <ZButton variant="primary" icon={<FundOutlined />} onClick={forecast} disabled={loading}>
          生成预测
        </ZButton>
      </div>

      {data?.alerts?.length > 0 && (
        <div className={`${styles.alertBar} ${styles.alertWarning}`} style={{ marginBottom: 16 }}>
          {data.alerts.length} 个资金预警日 — 预警日期：{data.alerts.join('、')}
        </div>
      )}

      {loading && <ZSkeleton rows={6} block />}

      {!loading && data?.daily_forecast && (
        <ZTable
          columns={cashFlowColumns}
          data={data.daily_forecast}
          rowKey="date"
          emptyText="暂无预测数据"
        />
      )}
    </div>
  );
};

// ── Budget Execution Tab ──────────────────────────────────────────────────────

const budgetStatusBadgeType: Record<string, 'critical' | 'success' | 'warning' | 'default'> = {
  over:      'critical',
  normal:    'success',
  under:     'warning',
  no_budget: 'default',
};
const budgetStatusLabel: Record<string, string> = {
  over:      '超预算',
  normal:    '正常',
  under:     '欠执行',
  no_budget: '无预算',
};

const budgetColumns: ZTableColumn<any>[] = [
  { key: 'category', title: '科目' },
  {
    key:    'actual_yuan',
    title:  '实际 (¥)',
    align:  'right',
    render: (v: number, row: any) => (v ?? (row.actual || 0) / 100).toLocaleString(),
  },
  {
    key:    'budget_yuan',
    title:  '预算 (¥)',
    align:  'right',
    render: (v: number, row: any) => {
      const val = v ?? (row.budget || 0) / 100;
      return val > 0 ? val.toLocaleString() : '—';
    },
  },
  {
    key:    'exec_rate',
    title:  '执行率',
    width:  140,
    render: (v: number) => {
      const pct = Math.min(150, Math.round(v));
      const color = v > 110 ? 'var(--red)' : 'var(--green)';
      return (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 80, height: 5, background: '#f0f0f0', borderRadius: 3, overflow: 'hidden' }}>
            <div style={{ width: `${(pct / 150) * 100}%`, height: '100%', background: color, borderRadius: 3 }} />
          </div>
          <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{v.toFixed(0)}%</span>
        </div>
      );
    },
  },
  {
    key:    'status',
    title:  '状态',
    width:  90,
    align:  'center',
    render: (s: string) => (
      <ZBadge type={budgetStatusBadgeType[s] ?? 'default'} text={budgetStatusLabel[s] || s} />
    ),
  },
];

const BudgetTab: React.FC = () => {
  const [year,    setYear]    = useState(DEFAULT_YEAR);
  const [month,   setMonth]   = useState(DEFAULT_MONTH);
  const [data,    setData]    = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const { data: d } = await axios.get(`/api/v1/fct/${STORE_ID}/budget-execution/${year}/${month}`);
      setData(d);
    } catch {
      message.error('加载预算执行数据失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div className={styles.toolbar}>
        <InputNumber min={2020} max={2099} value={year} onChange={v => setYear(v || DEFAULT_YEAR)} addonBefore="年份" />
        <InputNumber min={1} max={12} value={month} onChange={v => setMonth(v || DEFAULT_MONTH)} addonBefore="月份" />
        <ZButton variant="primary" icon={<BarChartOutlined />} onClick={load} disabled={loading}>
          查询执行率
        </ZButton>
      </div>

      {loading && <ZSkeleton rows={6} block />}

      {!loading && data && (
        <>
          <div className={styles.kpiGrid3} style={{ marginBottom: 16 }}>
            <ZCard>
              <ZKpi
                value={(data.revenue?.exec_rate || 0).toFixed(1)}
                unit="%"
                label="收入达成率"
              />
            </ZCard>
            <ZCard>
              <ZKpi
                value={(data.overall?.profit_margin_pct || 0).toFixed(1)}
                unit="%"
                label="本月利润率"
              />
            </ZCard>
            <ZCard>
              <ZKpi
                value={data.alerts?.length || 0}
                unit="项"
                label="超预算科目"
              />
            </ZCard>
          </div>

          {data.alerts?.length > 0 && (
            <div className={`${styles.alertBar} ${styles.alertError}`} style={{ marginBottom: 16 }}>
              超预算预警：{data.alerts.join('、')}
            </div>
          )}

          <ZTable
            columns={budgetColumns}
            data={data.categories || []}
            rowKey="category"
            emptyText="暂无预算数据"
          />
        </>
      )}
    </div>
  );
};

// ── Main Page ─────────────────────────────────────────────────────────────────

const FctPage: React.FC = () => (
  <div className={styles.page}>
    <div className={styles.pageHeader}>
      <h2 className={styles.pageTitle}>业财税资金一体化（FCT）</h2>
      <p className={styles.pageSub}>税务估算 · 资金流预测 · 预算执行率 · 月度业财对账</p>
    </div>

    <ZTabs
      items={[
        { key: 'dashboard', label: '仪表盘',   children: <DashboardTab /> },
        { key: 'tax',       label: '税务测算',  children: <TaxTab /> },
        { key: 'cashflow',  label: '资金流预测', children: <CashFlowTab /> },
        { key: 'budget',    label: '预算执行',  children: <BudgetTab /> },
      ]}
    />
  </div>
);

export default FctPage;
