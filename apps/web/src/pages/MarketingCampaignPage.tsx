import React, { useState, useEffect, useCallback } from 'react';
import { Form, Input, message } from 'antd';
import { ZCard, ZKpi, ZBadge, ZButton, ZSkeleton, ZSelect, ZTable, ZModal, ZEmpty } from '../design-system/components';
import type { ZTableColumn } from '../design-system/components';
import ReactECharts from 'echarts-for-react';
import { apiClient, handleApiError } from '../services/api';
import styles from './MarketingCampaignPage.module.css';

// ── Types ──────────────────────────────────────────────────────────────────────

interface SegmentSummary {
  store_id: string;
  total_customers: number;
  segments: Record<string, number>;
  segments_pct: Record<string, number>;
  computed_at: string;
}

interface AtRiskCustomer {
  customer_phone: string;
  customer_name: string;
  order_count: number;
  total_amount_yuan: number;
  last_order_date: string | null;
  days_since_last_order: number;
  churn_risk: number;
  segment: string;
  recommended_action: string;
}

interface Campaign {
  id: string;
  name: string;
  campaign_type: string;
  status: string;
  start_date: string | null;
  end_date: string | null;
  budget: number;
  reach_count: number;
  conversion_count: number;
  revenue_generated: number;
  description: string;
}

interface StoreStats {
  total_campaigns: number;
  active_campaigns: number;
  total_reach: number;
  total_conversion: number;
  avg_roi: number;
}

interface RoiSummary {
  total_campaigns: number;
  active_campaigns: number;
  total_reach: number;
  total_conversion: number;
  conversion_rate: number;
  total_revenue_yuan: number;
  total_cost_yuan: number;
  overall_roi: number;
}

// ── Segment labels ─────────────────────────────────────────────────────────────

const SEG_LABEL: Record<string, string> = {
  high_value: '高价值客户',
  potential: '潜力客户',
  at_risk: '流失风险',
  lost: '已流失',
  new: '新客户',
};

const SEG_COLOR: Record<string, string> = {
  high_value: '#1677ff',
  potential: '#52c41a',
  at_risk: '#fa8c16',
  lost: '#f5222d',
  new: '#722ed1',
};

// ── At-risk columns ────────────────────────────────────────────────────────────

const atRiskColumns: ZTableColumn<AtRiskCustomer>[] = [
  {
    key: 'customer_name',
    title: '顾客',
    render: (name, row) => (
      <div>
        <div style={{ fontWeight: 600 }}>{name}</div>
        <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{row.customer_phone}</div>
      </div>
    ),
  },
  {
    key: 'days_since_last_order',
    title: '失联天数',
    align: 'center',
    render: (days) => {
      const color = days >= 60 ? 'var(--red)' : '#fa8c16';
      return <span style={{ color, fontWeight: 600 }}>{days}天</span>;
    },
  },
  {
    key: 'order_count',
    title: '历史订单',
    align: 'center',
    render: (n) => `${n}单`,
  },
  {
    key: 'total_amount_yuan',
    title: '消费总额',
    align: 'right',
    render: (v) => <span style={{ color: 'var(--accent)', fontWeight: 600 }}>¥{v?.toLocaleString('zh-CN')}</span>,
  },
  {
    key: 'churn_risk',
    title: '流失风险',
    width: 130,
    render: (risk) => {
      const pct = Math.round(risk * 100);
      const color = pct >= 90 ? 'var(--red)' : '#fa8c16';
      return (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ flex: 1, height: 5, background: '#f0f0f0', borderRadius: 3, overflow: 'hidden' }}>
            <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 3 }} />
          </div>
          <span style={{ fontSize: 12, color, minWidth: 30 }}>{pct}%</span>
        </div>
      );
    },
  },
  {
    key: 'recommended_action',
    title: '建议动作',
    render: (action) => <ZBadge type="warning" text={action} />,
  },
];

// ── Campaign columns ───────────────────────────────────────────────────────────

const campaignColumns: ZTableColumn<Campaign>[] = [
  { key: 'name', title: '活动名称', render: (n) => <strong>{n}</strong> },
  {
    key: 'status',
    title: '状态',
    align: 'center',
    render: (s) => {
      const map: Record<string, 'success' | 'warning' | 'neutral'> = {
        active: 'success', draft: 'neutral', completed: 'neutral', cancelled: 'warning',
      };
      const label: Record<string, string> = { active: '进行中', draft: '草稿', completed: '已结束', cancelled: '已取消' };
      return <ZBadge type={map[s] || 'neutral'} text={label[s] || s} />;
    },
  },
  {
    key: 'budget',
    title: '预算',
    align: 'right',
    render: (v) => `¥${v?.toLocaleString('zh-CN')}`,
  },
  { key: 'reach_count', title: '触达人数', align: 'center', render: (v) => (v || 0).toLocaleString() },
  {
    key: 'conversion_count',
    title: '转化',
    align: 'center',
    render: (v, row) => {
      const rate = row.reach_count > 0 ? ((v / row.reach_count) * 100).toFixed(1) : '0.0';
      return <span>{v} <span style={{ color: 'var(--text-secondary)', fontSize: 12 }}>({rate}%)</span></span>;
    },
  },
];

// ── Component ──────────────────────────────────────────────────────────────────

const STORE_OPTIONS = [
  { value: 'STORE001', label: '门店 001' },
  { value: 'STORE002', label: '门店 002' },
  { value: 'STORE003', label: '门店 003' },
];

const SCENARIO_OPTIONS = [
  { value: 'traffic_decline', label: '客流下降' },
  { value: 'new_product_launch', label: '新品上市' },
  { value: 'member_day', label: '会员日' },
  { value: 'default', label: '通用促活' },
];

const OBJECTIVE_OPTIONS = [
  { value: 'acquisition', label: '拉新' },
  { value: 'activation', label: '促活' },
  { value: 'retention', label: '挽回' },
];

const MarketingCampaignPage: React.FC = () => {
  const [storeId, setStoreId] = useState(localStorage.getItem('store_id') || 'STORE001');
  const [segData, setSegData] = useState<SegmentSummary | null>(null);
  const [atRisk, setAtRisk] = useState<AtRiskCustomer[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [stats, setStats] = useState<StoreStats | null>(null);
  const [roiSummary, setRoiSummary] = useState<RoiSummary | null>(null);
  const [loading, setLoading] = useState(false);

  const [couponModal, setCouponModal] = useState(false);
  const [couponResult, setCouponResult] = useState<Record<string, unknown> | null>(null);
  const [couponLoading, setCouponLoading] = useState(false);
  const [couponForm] = Form.useForm();

  const [campaignModal, setCampaignModal] = useState(false);
  const [campaignLoading, setCampaignLoading] = useState(false);
  const [campaignForm] = Form.useForm();

  const loadAll = useCallback(async (sid: string) => {
    setLoading(true);
    try {
      const [segRes, atRiskRes, campaignRes, statsRes, roiRes] = await Promise.allSettled([
        apiClient.get(`/api/v1/marketing/stores/${sid}/segments`),
        apiClient.get(`/api/v1/marketing/stores/${sid}/customers/at-risk?risk_threshold=0.5&limit=30`),
        apiClient.get(`/api/v1/marketing/stores/${sid}/campaigns?limit=20`),
        apiClient.get(`/api/v1/marketing/stores/${sid}/statistics`),
        apiClient.get(`/api/v1/marketing/stores/${sid}/campaigns/roi-summary?days=30`),
      ]);

      if (segRes.status === 'fulfilled') setSegData(segRes.value.data);
      if (atRiskRes.status === 'fulfilled') setAtRisk(atRiskRes.value.data.customers || []);
      if (campaignRes.status === 'fulfilled') setCampaigns(campaignRes.value.data.campaigns || []);
      if (statsRes.status === 'fulfilled') setStats(statsRes.value.data);
      if (roiRes.status === 'fulfilled') setRoiSummary(roiRes.value.data);
    } catch (e) {
      handleApiError(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadAll(storeId); }, [storeId, loadAll]);

  const [outreachLoading, setOutreachLoading] = useState(false);

  const handleBatchOutreach = async (dryRun: boolean) => {
    setOutreachLoading(true);
    try {
      const res = await apiClient.post(`/api/v1/marketing/stores/${storeId}/batch-churn-recovery`, { dry_run: dryRun });
      const d = res.data;
      if (dryRun) {
        message.info(`预估发送：${d.total_at_risk} 位流失风险客户，实际可发 ${d.sent} 位（频控过滤 ${d.skipped_freq_cap} 位）`);
      } else {
        message.success(`已发送 ${d.sent} 条企微挽回消息，跳过 ${d.skipped_freq_cap} 位（今日频控），失败 ${d.errors} 条`);
      }
    } catch (e) {
      handleApiError(e);
    } finally {
      setOutreachLoading(false);
    }
  };

  const handleCouponSubmit = async (values: { scenario: string }) => {
    setCouponLoading(true);
    try {
      const res = await apiClient.post('/api/v1/marketing/coupon-strategy', {
        scenario: values.scenario,
        store_id: storeId,
      });
      setCouponResult(res.data);
    } catch (e) {
      handleApiError(e);
    } finally {
      setCouponLoading(false);
    }
  };

  const handleCampaignSubmit = async (values: { name: string; objective: string; budget: number }) => {
    setCampaignLoading(true);
    try {
      await apiClient.post(`/api/v1/marketing/stores/${storeId}/campaigns`, {
        store_id: storeId,
        objective: values.objective,
        budget: Number(values.budget),
        name: values.name,
      });
      message.success('活动创建成功');
      setCampaignModal(false);
      campaignForm.resetFields();
      loadAll(storeId);
    } catch (e) {
      handleApiError(e);
    } finally {
      setCampaignLoading(false);
    }
  };

  const segs = segData?.segments || {};
  const atRiskCount = (segs['at_risk'] || 0) + (segs['lost'] || 0);

  // ECharts pie data
  const pieData = Object.entries(SEG_LABEL).map(([key, name]) => ({
    name,
    value: segs[key] || 0,
    itemStyle: { color: SEG_COLOR[key] },
  }));

  const pieOption = {
    tooltip: { trigger: 'item', formatter: '{b}: {c}人 ({d}%)' },
    legend: { bottom: 0, left: 'center', textStyle: { fontSize: 12 } },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      center: ['50%', '45%'],
      data: pieData,
      label: { show: false },
      emphasis: { label: { show: true, fontSize: 14, fontWeight: 700 } },
    }],
  };

  const couponFooter = (
    <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
      <ZButton onClick={() => { setCouponModal(false); setCouponResult(null); couponForm.resetFields(); }}>关闭</ZButton>
      {!couponResult && (
        <ZButton variant="primary" disabled={couponLoading} onClick={() => couponForm.submit()}>
          {couponLoading ? '生成中…' : '生成策略'}
        </ZButton>
      )}
    </div>
  );

  const campaignFooter = (
    <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
      <ZButton onClick={() => { setCampaignModal(false); campaignForm.resetFields(); }}>取消</ZButton>
      <ZButton variant="primary" disabled={campaignLoading} onClick={() => campaignForm.submit()}>
        {campaignLoading ? '创建中…' : '创建活动'}
      </ZButton>
    </div>
  );

  return (
    <div className={styles.page}>
      {/* Header */}
      <div className={styles.pageHeader}>
        <div>
          <h1 className={styles.pageTitle}>营销智能体</h1>
          <p className={styles.pageSub}>顾客画像 · 流失预警 · 智能发券 · 活动管理</p>
        </div>
        <div className={styles.headerActions}>
          <ZSelect
            value={storeId}
            options={STORE_OPTIONS}
            onChange={(v) => { setStoreId(v); localStorage.setItem('store_id', v); }}
          />
          <ZButton onClick={() => loadAll(storeId)}>刷新</ZButton>
          <ZButton onClick={() => handleBatchOutreach(true)} disabled={outreachLoading}>预估触达</ZButton>
          <ZButton variant="primary" onClick={() => handleBatchOutreach(false)} disabled={outreachLoading}>
            {outreachLoading ? '发送中…' : '批量挽回触达'}
          </ZButton>
          <ZButton variant="primary" onClick={() => setCouponModal(true)}>生成发券策略</ZButton>
          <ZButton variant="primary" onClick={() => setCampaignModal(true)}>新建营销活动</ZButton>
        </div>
      </div>

      {/* KPI Row */}
      {loading ? (
        <div className={styles.kpiGrid}>
          {[...Array(4)].map((_, i) => <ZSkeleton key={i} height={88} />)}
        </div>
      ) : (
        <>
          <div className={styles.kpiGrid}>
            <ZCard><ZKpi label="总顾客数" value={segData?.total_customers ?? '-'} unit="人" /></ZCard>
            <ZCard><ZKpi label="高价值客户" value={segs['high_value'] ?? 0} unit="人" /></ZCard>
            <ZCard><ZKpi label="流失风险客户" value={atRiskCount} unit="人" /></ZCard>
            <ZCard><ZKpi label="活跃活动" value={stats?.active_campaigns ?? 0} unit="个" /></ZCard>
          </div>
          {roiSummary && (
            <div className={styles.kpiGrid}>
              <ZCard><ZKpi label="近30天营收" value={`¥${roiSummary.total_revenue_yuan?.toLocaleString('zh-CN')}`} /></ZCard>
              <ZCard><ZKpi label="触达人次" value={(roiSummary.total_reach || 0).toLocaleString()} /></ZCard>
              <ZCard><ZKpi label="转化率" value={`${((roiSummary.conversion_rate || 0) * 100).toFixed(1)}%`} /></ZCard>
              <ZCard><ZKpi label="综合 ROI" value={`${(roiSummary.overall_roi || 0).toFixed(2)}x`} /></ZCard>
            </div>
          )}
        </>
      )}

      {/* Segment chart + Campaign table */}
      <div className={styles.twoCol}>
        <ZCard title="客群分布">
          {loading ? <ZSkeleton height={260} /> : (
            segData && segData.total_customers > 0
              ? <ReactECharts option={pieOption} style={{ height: 280 }} />
              : <ZEmpty text="暂无顾客数据" />
          )}
        </ZCard>

        <ZCard
          title="营销活动"
          extra={<span className={styles.statsText}>总触达 {(stats?.total_reach || 0).toLocaleString()} 人</span>}
        >
          {loading ? <ZSkeleton height={260} /> : (
            campaigns.length > 0
              ? <ZTable columns={campaignColumns} data={campaigns} rowKey="id" />
              : <ZEmpty text="暂无活动" />
          )}
        </ZCard>
      </div>

      {/* At-risk table */}
      <ZCard title={`流失风险客户 (${atRisk.length}人)`}>
        {loading ? <ZSkeleton height={200} /> : (
          atRisk.length > 0
            ? <ZTable columns={atRiskColumns} data={atRisk} rowKey="customer_phone" />
            : <ZEmpty text="无流失风险客户" />
        )}
      </ZCard>

      {/* Coupon Strategy Modal */}
      <ZModal
        open={couponModal}
        title="AI 生成发券策略"
        onClose={() => { setCouponModal(false); setCouponResult(null); couponForm.resetFields(); }}
        footer={couponFooter}
        width={480}
      >
        {!couponResult ? (
          <Form form={couponForm} layout="vertical" onFinish={handleCouponSubmit}>
            <Form.Item name="scenario" label="营销场景" rules={[{ required: true, message: '请选择场景' }]}>
              <select className={styles.nativeSelect}>
                <option value="">请选择场景</option>
                {SCENARIO_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </Form.Item>
          </Form>
        ) : (
          <div className={styles.couponResult}>
            <div className={styles.couponRow}>
              <span className={styles.couponLabel}>券类型</span>
              <strong>{couponResult.coupon_type as string}</strong>
            </div>
            <div className={styles.couponRow}>
              <span className={styles.couponLabel}>面额</span>
              <strong style={{ color: 'var(--accent)' }}>¥{String(couponResult.amount)}</strong>
            </div>
            {Boolean(couponResult.threshold) && (
              <div className={styles.couponRow}>
                <span className={styles.couponLabel}>使用门槛</span>
                <span>满 ¥{String(couponResult.threshold)} 可用</span>
              </div>
            )}
            <div className={styles.couponRow}>
              <span className={styles.couponLabel}>有效天数</span>
              <span>{String(couponResult.valid_days)} 天</span>
            </div>
            <div className={styles.couponRow}>
              <span className={styles.couponLabel}>目标客群</span>
              <ZBadge type="warning" text={SEG_LABEL[couponResult.target_segment as string] || String(couponResult.target_segment)} />
            </div>
            <div className={styles.couponRow}>
              <span className={styles.couponLabel}>预期转化率</span>
              <span>{(Number(couponResult.expected_conversion) * 100).toFixed(0)}%</span>
            </div>
            <div className={styles.couponRow}>
              <span className={styles.couponLabel}>预期 ROI</span>
              <strong style={{ color: 'var(--green)' }}>{Number(couponResult.expected_roi).toFixed(1)}x</strong>
            </div>
          </div>
        )}
      </ZModal>

      {/* Create Campaign Modal */}
      <ZModal
        open={campaignModal}
        title="新建营销活动"
        onClose={() => { setCampaignModal(false); campaignForm.resetFields(); }}
        footer={campaignFooter}
        width={480}
      >
        <Form form={campaignForm} layout="vertical" onFinish={handleCampaignSubmit}>
          <Form.Item name="name" label="活动名称" rules={[{ required: true, message: '请输入活动名称' }]}>
            <Input placeholder="例：4月会员日促活" />
          </Form.Item>
          <Form.Item name="objective" label="活动目标" rules={[{ required: true, message: '请选择目标' }]}>
            <select className={styles.nativeSelect}>
              <option value="">请选择目标</option>
              {OBJECTIVE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </Form.Item>
          <Form.Item name="budget" label="活动预算（元）" rules={[{ required: true, message: '请输入预算' }]}>
            <Input type="number" min={0} placeholder="例：5000" />
          </Form.Item>
        </Form>
      </ZModal>
    </div>
  );
};

export default MarketingCampaignPage;
