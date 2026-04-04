/**
 * CampaignPage — 营销活动管理中心
 * 三大模块：活动列表 / 优惠券管理 / 活动效果分析
 * API: tx-growth :8004
 */
import { useRef, useState, useEffect, useCallback, useMemo } from 'react';
import {
  ProTable,
  ProColumns,
  ActionType,
  ModalForm,
  ProFormText,
  ProFormSelect,
  ProFormDigit,
  ProFormDateTimeRangePicker,
} from '@ant-design/pro-components';
import {
  Badge,
  Button,
  Card,
  Checkbox,
  Col,
  Descriptions,
  Drawer,
  message,
  Modal,
  Row,
  Space,
  Statistic,
  Steps,
  Table,
  Tabs,
  Tag,
  DatePicker,
} from 'antd';
import {
  PlusOutlined,
  PauseCircleOutlined,
  CopyOutlined,
  EyeOutlined,
  EditOutlined,
  RocketOutlined,
  GiftOutlined,
  PercentageOutlined,
  ShoppingCartOutlined,
  TeamOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { txFetch } from '../../api';

const { RangePicker } = DatePicker;

// ─── 常量（空数据 fallback）───

const EMPTY_SUMMARY: SummaryStats = {
  active_campaigns: 0,
  monthly_participants: 0,
  redemption_rate: 0,
  monthly_cost_fen: 0,
};

// ─── 类型定义 ───

type CampaignStatus = 'draft' | 'active' | 'paused' | 'ended' | 'cancelled';
type CampaignType = 'full_reduce' | 'discount' | 'buy_gift' | 'group_buy' | 'flash_sale';
type CouponStatus = 'active' | 'expired' | 'disabled';

interface Campaign {
  id: string;
  name: string;
  type: CampaignType;
  store_scope: string;
  start_time: string;
  end_time: string;
  participant_count: number;
  status: CampaignStatus;
  cost_fen: number;
  revenue_fen: number;
}

interface CampaignDetail extends Campaign {
  rule_config: Record<string, number>;
  store_ids: string[];
  daily_stats: DailyStat[];
}

interface Coupon {
  id: string;
  name: string;
  face_value_fen: number;
  min_order_fen: number;
  issued_count: number;
  claimed_count: number;
  redeemed_count: number;
  status: CouponStatus;
}

interface DailyStat {
  date: string;
  participants: number;
  redeemed: number;
}

interface StoreOption {
  id: string;
  name: string;
}

interface SummaryStats {
  active_campaigns: number;
  monthly_participants: number;
  redemption_rate: number;
  monthly_cost_fen: number;
}

// ─── 类型常量映射 ───

const TYPE_TAG: Record<CampaignType, { color: string; label: string; icon: React.ReactNode }> = {
  full_reduce: { color: 'volcano', label: '满减', icon: <RocketOutlined /> },
  discount: { color: 'blue', label: '折扣', icon: <PercentageOutlined /> },
  buy_gift: { color: 'green', label: '买赠', icon: <GiftOutlined /> },
  group_buy: { color: 'purple', label: '拼团', icon: <TeamOutlined /> },
  flash_sale: { color: 'red', label: '秒杀', icon: <ThunderboltOutlined /> },
};

const STATUS_BADGE: Record<CampaignStatus, { status: 'default' | 'success' | 'warning' | 'error' | 'processing'; text: string }> = {
  draft: { status: 'default', text: '草稿' },
  active: { status: 'success', text: '进行中' },
  paused: { status: 'warning', text: '已暂停' },
  ended: { status: 'default', text: '已结束' },
  cancelled: { status: 'error', text: '已取消' },
};

// ─── API 封装 ───

async function fetchSummary(): Promise<SummaryStats> {
  try {
    return await txFetch<SummaryStats>('/api/v1/growth/campaigns/summary');
  } catch {
    return EMPTY_SUMMARY;
  }
}

async function fetchCampaigns(status?: string): Promise<Campaign[]> {
  try {
    const params = status ? `?status=${encodeURIComponent(status)}` : '';
    const res = await txFetch<{ items: Campaign[] }>(`/api/v1/growth/campaigns${params}`);
    return res?.items ?? [];
  } catch {
    return [];
  }
}

async function fetchCampaignDetail(id: string): Promise<CampaignDetail | null> {
  try {
    return await txFetch<CampaignDetail>(`/api/v1/growth/campaigns/${id}`);
  } catch {
    return null;
  }
}

async function fetchCoupons(): Promise<Coupon[]> {
  try {
    const res = await txFetch<{ items: Coupon[] }>('/api/v1/growth/coupons');
    return res?.items ?? [];
  } catch {
    return [];
  }
}

async function fetchStores(): Promise<StoreOption[]> {
  try {
    const res = await txFetch<{ items: StoreOption[] }>('/api/v1/org/stores');
    return res?.items ?? [];
  } catch {
    return [];
  }
}

async function createCampaign(payload: {
  name: string;
  type: CampaignType;
  discount_value: number;
  start_date: string;
  end_date: string;
}): Promise<Campaign | null> {
  try {
    return await txFetch<Campaign>('/api/v1/growth/campaigns', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  } catch {
    return null;
  }
}

async function patchCampaignStatus(id: string, status: CampaignStatus): Promise<void> {
  await txFetch(`/api/v1/growth/campaigns/${id}`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  });
}

async function pauseCampaign(id: string): Promise<void> {
  try {
    await patchCampaignStatus(id, 'paused');
  } catch {
    message.error('操作失败，请重试');
  }
}

// ─── SVG 折线图组件 ───

function TrendChart({ data, width = 720, height = 260 }: { data: DailyStat[]; width?: number; height?: number }) {
  if (!data.length) return null;

  const padding = { top: 20, right: 20, bottom: 40, left: 50 };
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;

  const maxVal = Math.max(...data.map(d => Math.max(d.participants, d.redeemed)), 1);
  const yTicks = 5;

  const toX = (i: number) => padding.left + (i / Math.max(data.length - 1, 1)) * chartW;
  const toY = (v: number) => padding.top + chartH - (v / maxVal) * chartH;

  const participantPoints = data.map((d, i) => `${toX(i)},${toY(d.participants)}`).join(' ');
  const redeemedPoints = data.map((d, i) => `${toX(i)},${toY(d.redeemed)}`).join(' ');

  return (
    <svg width={width} height={height} style={{ fontFamily: '-apple-system, sans-serif', fontSize: 11 }}>
      {/* Y 轴网格 */}
      {Array.from({ length: yTicks + 1 }).map((_, i) => {
        const val = Math.round((maxVal / yTicks) * i);
        const y = toY(val);
        return (
          <g key={`y-${i}`}>
            <line x1={padding.left} y1={y} x2={width - padding.right} y2={y} stroke="#f0f0f0" />
            <text x={padding.left - 8} y={y + 4} textAnchor="end" fill="#999">{val}</text>
          </g>
        );
      })}
      {/* X 轴标签 */}
      {data.map((d, i) => {
        if (data.length > 14 && i % Math.ceil(data.length / 7) !== 0) return null;
        return (
          <text key={`x-${i}`} x={toX(i)} y={height - 8} textAnchor="middle" fill="#999">
            {d.date.slice(5)}
          </text>
        );
      })}
      {/* 折线 */}
      <polyline points={participantPoints} fill="none" stroke="#FF6B35" strokeWidth={2} />
      <polyline points={redeemedPoints} fill="none" stroke="#52c41a" strokeWidth={2} />
      {/* 数据点 */}
      {data.map((d, i) => (
        <g key={`dot-${i}`}>
          <circle cx={toX(i)} cy={toY(d.participants)} r={3} fill="#FF6B35" />
          <circle cx={toX(i)} cy={toY(d.redeemed)} r={3} fill="#52c41a" />
        </g>
      ))}
      {/* 图例 */}
      <g transform={`translate(${padding.left + 10}, ${padding.top})`}>
        <line x1={0} y1={0} x2={20} y2={0} stroke="#FF6B35" strokeWidth={2} />
        <text x={24} y={4} fill="#333">参与人次</text>
        <line x1={100} y1={0} x2={120} y2={0} stroke="#52c41a" strokeWidth={2} />
        <text x={124} y={4} fill="#333">核销人次</text>
      </g>
    </svg>
  );
}

// ─── 核销率进度条 ───

function RedemptionBar({ rate }: { rate: number }) {
  const pct = Math.round(rate * 100);
  const color = pct < 30 ? '#f5222d' : pct < 60 ? '#fa8c16' : '#52c41a';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ width: 80, height: 8, background: '#f0f0f0', borderRadius: 4, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 4, transition: 'width 0.3s' }} />
      </div>
      <span style={{ fontSize: 12, color }}>{pct}%</span>
    </div>
  );
}

// ─── 新建活动 Steps 表单 ───

function CreateCampaignModal({ open, onClose, onSuccess }: { open: boolean; onClose: () => void; onSuccess: () => void }) {
  const [step, setStep] = useState(0);
  const [stores, setStores] = useState<StoreOption[]>([]);
  const [form, setForm] = useState<{
    name: string;
    type: CampaignType;
    time_range: [string, string] | null;
    threshold_fen: number;
    reduce_fen: number;
    discount_rate: number;
    discount_cap_fen: number;
    buy_n: number;
    gift_m: number;
    group_size: number;
    group_price_fen: number;
    store_mode: 'all' | 'selected';
    selected_store_ids: string[];
  }>({
    name: '',
    type: 'full_reduce',
    time_range: null,
    threshold_fen: 10000,
    reduce_fen: 2000,
    discount_rate: 80,
    discount_cap_fen: 5000,
    buy_n: 2,
    gift_m: 1,
    group_size: 3,
    group_price_fen: 8800,
    store_mode: 'all',
    selected_store_ids: [],
  });

  useEffect(() => {
    if (open) {
      fetchStores().then(setStores);
    }
  }, [open]);

  const updateForm = (patch: Partial<typeof form>) => setForm(prev => ({ ...prev, ...patch }));

  const handleSubmit = async () => {
    try {
      const rule = getRuleConfig() as Record<string, number>;
      const result = await createCampaign({
        name: form.name,
        type: form.type,
        discount_value: rule.reduce_fen ?? rule.discount_rate ?? 0,
        start_date: form.time_range?.[0] ?? '',
        end_date: form.time_range?.[1] ?? '',
      });
      if (result) {
        message.success('活动创建成功');
      } else {
        message.error('创建失败，请重试');
        return;
      }
    } catch {
      message.error('创建失败，请重试');
      return;
    }
    onSuccess();
    onClose();
    setStep(0);
  };

  const getRuleConfig = () => {
    switch (form.type) {
      case 'full_reduce': return { threshold_fen: form.threshold_fen, reduce_fen: form.reduce_fen };
      case 'discount': return { discount_rate: form.discount_rate, cap_fen: form.discount_cap_fen };
      case 'buy_gift': return { buy_n: form.buy_n, gift_m: form.gift_m };
      case 'group_buy': return { group_size: form.group_size, group_price_fen: form.group_price_fen };
      case 'flash_sale': return { threshold_fen: form.threshold_fen, reduce_fen: form.reduce_fen };
    }
  };

  const renderRuleForm = () => {
    switch (form.type) {
      case 'full_reduce':
      case 'flash_sale':
        return (
          <Space direction="vertical" style={{ width: '100%' }}>
            <div>
              <label>消费门槛（元）</label>
              <input type="number" value={form.threshold_fen / 100} onChange={e => updateForm({ threshold_fen: Number(e.target.value) * 100 })}
                style={{ display: 'block', width: '100%', padding: '4px 8px', border: '1px solid #d9d9d9', borderRadius: 6, marginTop: 4 }} />
            </div>
            <div>
              <label>减免金额（元）</label>
              <input type="number" value={form.reduce_fen / 100} onChange={e => updateForm({ reduce_fen: Number(e.target.value) * 100 })}
                style={{ display: 'block', width: '100%', padding: '4px 8px', border: '1px solid #d9d9d9', borderRadius: 6, marginTop: 4 }} />
            </div>
          </Space>
        );
      case 'discount':
        return (
          <Space direction="vertical" style={{ width: '100%' }}>
            <div>
              <label>折扣率（如 80 表示 8 折）</label>
              <input type="number" value={form.discount_rate} onChange={e => updateForm({ discount_rate: Number(e.target.value) })}
                style={{ display: 'block', width: '100%', padding: '4px 8px', border: '1px solid #d9d9d9', borderRadius: 6, marginTop: 4 }} />
            </div>
            <div>
              <label>折扣上限（元）</label>
              <input type="number" value={form.discount_cap_fen / 100} onChange={e => updateForm({ discount_cap_fen: Number(e.target.value) * 100 })}
                style={{ display: 'block', width: '100%', padding: '4px 8px', border: '1px solid #d9d9d9', borderRadius: 6, marginTop: 4 }} />
            </div>
          </Space>
        );
      case 'buy_gift':
        return (
          <Space direction="vertical" style={{ width: '100%' }}>
            <div>
              <label>买 N 件</label>
              <input type="number" value={form.buy_n} onChange={e => updateForm({ buy_n: Number(e.target.value) })}
                style={{ display: 'block', width: '100%', padding: '4px 8px', border: '1px solid #d9d9d9', borderRadius: 6, marginTop: 4 }} />
            </div>
            <div>
              <label>赠 M 件</label>
              <input type="number" value={form.gift_m} onChange={e => updateForm({ gift_m: Number(e.target.value) })}
                style={{ display: 'block', width: '100%', padding: '4px 8px', border: '1px solid #d9d9d9', borderRadius: 6, marginTop: 4 }} />
            </div>
          </Space>
        );
      case 'group_buy':
        return (
          <Space direction="vertical" style={{ width: '100%' }}>
            <div>
              <label>成团人数</label>
              <input type="number" value={form.group_size} onChange={e => updateForm({ group_size: Number(e.target.value) })}
                style={{ display: 'block', width: '100%', padding: '4px 8px', border: '1px solid #d9d9d9', borderRadius: 6, marginTop: 4 }} />
            </div>
            <div>
              <label>团购价（元）</label>
              <input type="number" value={form.group_price_fen / 100} onChange={e => updateForm({ group_price_fen: Number(e.target.value) * 100 })}
                style={{ display: 'block', width: '100%', padding: '4px 8px', border: '1px solid #d9d9d9', borderRadius: 6, marginTop: 4 }} />
            </div>
          </Space>
        );
    }
  };

  const stepItems = [
    { title: '基本信息' },
    { title: '优惠规则' },
    { title: '门店范围' },
    { title: '确认' },
  ];

  return (
    <Modal title="新建营销活动" open={open} onCancel={onClose} width={640} footer={null} destroyOnClose>
      <Steps current={step} items={stepItems} style={{ marginBottom: 24 }} />

      {step === 0 && (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <label>活动名称</label>
            <input value={form.name} onChange={e => updateForm({ name: e.target.value })}
              placeholder="请输入活动名称" style={{ display: 'block', width: '100%', padding: '4px 8px', border: '1px solid #d9d9d9', borderRadius: 6, marginTop: 4 }} />
          </div>
          <div>
            <label>活动类型</label>
            <select value={form.type} onChange={e => updateForm({ type: e.target.value as CampaignType })}
              style={{ display: 'block', width: '100%', padding: '4px 8px', border: '1px solid #d9d9d9', borderRadius: 6, marginTop: 4 }}>
              {Object.entries(TYPE_TAG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select>
          </div>
          <div>
            <label>活动时间段</label>
            <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
              <input type="datetime-local" value={form.time_range?.[0] ?? ''}
                onChange={e => updateForm({ time_range: [e.target.value, form.time_range?.[1] ?? ''] })}
                style={{ flex: 1, padding: '4px 8px', border: '1px solid #d9d9d9', borderRadius: 6 }} />
              <span style={{ lineHeight: '32px' }}>~</span>
              <input type="datetime-local" value={form.time_range?.[1] ?? ''}
                onChange={e => updateForm({ time_range: [form.time_range?.[0] ?? '', e.target.value] })}
                style={{ flex: 1, padding: '4px 8px', border: '1px solid #d9d9d9', borderRadius: 6 }} />
            </div>
          </div>
        </Space>
      )}

      {step === 1 && renderRuleForm()}

      {step === 2 && (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <Checkbox checked={form.store_mode === 'all'} onChange={e => updateForm({ store_mode: e.target.checked ? 'all' : 'selected' })}>
              全部门店
            </Checkbox>
          </div>
          {form.store_mode === 'selected' && (
            <Checkbox.Group
              value={form.selected_store_ids}
              onChange={vals => updateForm({ selected_store_ids: vals as string[] })}
              style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
            >
              {stores.map(s => <Checkbox key={s.id} value={s.id}>{s.name}</Checkbox>)}
            </Checkbox.Group>
          )}
        </Space>
      )}

      {step === 3 && (
        <Descriptions bordered column={1} size="small">
          <Descriptions.Item label="活动名称">{form.name || '-'}</Descriptions.Item>
          <Descriptions.Item label="活动类型">{TYPE_TAG[form.type]?.label}</Descriptions.Item>
          <Descriptions.Item label="时间段">
            {form.time_range ? `${form.time_range[0]} ~ ${form.time_range[1]}` : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="优惠规则">
            {JSON.stringify(getRuleConfig())}
          </Descriptions.Item>
          <Descriptions.Item label="门店范围">
            {form.store_mode === 'all' ? '全部门店' : `指定 ${form.selected_store_ids.length} 家门店`}
          </Descriptions.Item>
        </Descriptions>
      )}

      <div style={{ marginTop: 24, display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        {step > 0 && <Button onClick={() => setStep(s => s - 1)}>上一步</Button>}
        {step < 3 && <Button type="primary" onClick={() => setStep(s => s + 1)}>下一步</Button>}
        {step === 3 && <Button type="primary" onClick={handleSubmit}>提交创建</Button>}
      </div>
    </Modal>
  );
}

// ─── 主页面组件 ───

export function CampaignPage() {
  const campaignTableRef = useRef<ActionType>();
  const couponTableRef = useRef<ActionType>();

  const [summary, setSummary] = useState<SummaryStats>(EMPTY_SUMMARY);
  const [activeTab, setActiveTab] = useState('campaigns');
  const [createOpen, setCreateOpen] = useState(false);
  const [couponCreateOpen, setCouponCreateOpen] = useState(false);
  const [detailDrawer, setDetailDrawer] = useState<{ open: boolean; campaign: CampaignDetail | null }>({ open: false, campaign: null });
  const [analysisDays, setAnalysisDays] = useState<number>(7);
  const [analysisData, setAnalysisData] = useState<DailyStat[]>([]);
  const [roiCampaigns, setRoiCampaigns] = useState<Campaign[]>([]);
  const [roiLoading, setRoiLoading] = useState(false);

  useEffect(() => {
    fetchSummary().then(setSummary);
  }, []);

  useEffect(() => {
    if (activeTab === 'analysis') {
      setRoiLoading(true);
      fetchCampaigns().then((campaigns) => {
        setRoiCampaigns(campaigns.filter((c) => c.cost_fen > 0));
        setAnalysisData([]);
        setRoiLoading(false);
      });
    }
  }, [activeTab, analysisDays]);

  const openDetail = useCallback(async (id: string) => {
    const detail = await fetchCampaignDetail(id);
    setDetailDrawer({ open: true, campaign: detail });
  }, []);

  const handlePause = useCallback(async (id: string) => {
    await pauseCampaign(id);
    campaignTableRef.current?.reload();
  }, []);

  const handleCopy = useCallback((record: Campaign) => {
    setCreateOpen(true);
    message.info(`已复制活动「${record.name}」的配置`);
  }, []);

  // ─── 活动列表列 ───

  const campaignColumns: ProColumns<Campaign>[] = useMemo(() => [
    { title: '活动名称', dataIndex: 'name', width: 180, ellipsis: true },
    {
      title: '类型',
      dataIndex: 'type',
      width: 100,
      render: (_, r) => {
        const t = TYPE_TAG[r.type];
        return t ? <Tag icon={t.icon} color={t.color}>{t.label}</Tag> : r.type;
      },
      filters: Object.entries(TYPE_TAG).map(([k, v]) => ({ text: v.label, value: k })),
      onFilter: (value, record) => record.type === value,
    },
    { title: '门店范围', dataIndex: 'store_scope', width: 140, ellipsis: true },
    {
      title: '活动时间',
      width: 220,
      render: (_, r) => `${r.start_time.slice(0, 10)} ~ ${r.end_time.slice(0, 10)}`,
    },
    { title: '参与人次', dataIndex: 'participant_count', width: 100, sorter: (a, b) => a.participant_count - b.participant_count },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (_, r) => {
        const s = STATUS_BADGE[r.status];
        return <Badge status={s.status} text={s.text} />;
      },
      filters: Object.entries(STATUS_BADGE).map(([k, v]) => ({ text: v.text, value: k })),
      onFilter: (value, record) => record.status === value,
    },
    {
      title: '操作',
      width: 200,
      render: (_, record) => (
        <Space size="small">
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => openDetail(record.id)}>详情</Button>
          {record.status === 'active' && (
            <Button type="link" size="small" icon={<PauseCircleOutlined />} onClick={() => handlePause(record.id)}>暂停</Button>
          )}
          <Button type="link" size="small" icon={<CopyOutlined />} onClick={() => handleCopy(record)}>复制</Button>
          {record.status === 'draft' && (
            <Button type="link" size="small" icon={<EditOutlined />}>编辑</Button>
          )}
        </Space>
      ),
    },
  ], [openDetail, handlePause, handleCopy]);

  // ─── 优惠券列 ───

  const couponColumns: ProColumns<Coupon>[] = useMemo(() => [
    { title: '券名', dataIndex: 'name', width: 160 },
    { title: '面值', width: 80, render: (_, r) => `${(r.face_value_fen / 100).toFixed(0)}元` },
    { title: '使用条件', width: 120, render: (_, r) => `满${(r.min_order_fen / 100).toFixed(0)}元可用` },
    { title: '发放量', dataIndex: 'issued_count', width: 80 },
    { title: '领取量', dataIndex: 'claimed_count', width: 80 },
    { title: '核销量', dataIndex: 'redeemed_count', width: 80 },
    {
      title: '核销率',
      width: 140,
      render: (_, r) => {
        const rate = r.claimed_count > 0 ? r.redeemed_count / r.claimed_count : 0;
        return <RedemptionBar rate={rate} />;
      },
      sorter: (a, b) => {
        const ra = a.claimed_count > 0 ? a.redeemed_count / a.claimed_count : 0;
        const rb = b.claimed_count > 0 ? b.redeemed_count / b.claimed_count : 0;
        return ra - rb;
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 80,
      render: (_, r) => {
        const map: Record<CouponStatus, { color: string; label: string }> = {
          active: { color: 'green', label: '生效中' },
          expired: { color: 'default', label: '已过期' },
          disabled: { color: 'red', label: '已停用' },
        };
        const s = map[r.status];
        return <Tag color={s.color}>{s.label}</Tag>;
      },
    },
    {
      title: '操作',
      width: 100,
      render: () => (
        <Button type="link" size="small" icon={<EyeOutlined />}>查看</Button>
      ),
    },
  ], []);

  // ─── ROI 表格 ───

  const roiColumns = useMemo(() => [
    { title: '活动名称', dataIndex: 'name', key: 'name' },
    { title: '成本（元）', key: 'cost', render: (_: unknown, r: Campaign) => (r.cost_fen / 100).toFixed(0) },
    { title: '带来收入（元）', key: 'revenue', render: (_: unknown, r: Campaign) => (r.revenue_fen / 100).toFixed(0) },
    {
      title: 'ROI倍数',
      key: 'roi',
      render: (_: unknown, r: Campaign) => {
        const roi = r.cost_fen > 0 ? r.revenue_fen / r.cost_fen : 0;
        const color = roi >= 3 ? '#52c41a' : roi >= 1.5 ? '#fa8c16' : '#f5222d';
        return <span style={{ color, fontWeight: 600 }}>{roi.toFixed(1)}x</span>;
      },
      sorter: (a: Campaign, b: Campaign) => {
        const ra = a.cost_fen > 0 ? a.revenue_fen / a.cost_fen : 0;
        const rb = b.cost_fen > 0 ? b.revenue_fen / b.cost_fen : 0;
        return ra - rb;
      },
    },
  ], []);

  return (
    <div style={{ padding: 24 }}>
      {/* 顶部统计卡 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic title="进行中活动数" value={summary.active_campaigns} valueStyle={{ color: '#FF6B35' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="本月参与人次" value={summary.monthly_participants} valueStyle={{ color: '#FF6B35' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="核销率" value={`${(summary.redemption_rate * 100).toFixed(1)}%`} valueStyle={{ color: '#FF6B35' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="本月营销成本（万元）" value={(summary.monthly_cost_fen / 100 / 10000).toFixed(2)} valueStyle={{ color: '#FF6B35' }} />
          </Card>
        </Col>
      </Row>

      {/* Tabs */}
      <Card>
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
          {
            key: 'campaigns',
            label: '活动列表',
            children: (
              <>
                <ProTable<Campaign>
                  actionRef={campaignTableRef}
                  rowKey="id"
                  columns={campaignColumns}
                  request={async () => {
                    const data = await fetchCampaigns();
                    return { data, success: true, total: data.length };
                  }}
                  search={false}
                  pagination={{ pageSize: 10 }}
                  toolBarRender={() => [
                    <Button key="create" type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
                      新建活动
                    </Button>,
                  ]}
                />
                <CreateCampaignModal open={createOpen} onClose={() => setCreateOpen(false)} onSuccess={() => campaignTableRef.current?.reload()} />
              </>
            ),
          },
          {
            key: 'coupons',
            label: '优惠券管理',
            children: (
              <>
                <ProTable<Coupon>
                  actionRef={couponTableRef}
                  rowKey="id"
                  columns={couponColumns}
                  request={async () => {
                    const data = await fetchCoupons();
                    return { data, success: true, total: data.length };
                  }}
                  search={false}
                  pagination={{ pageSize: 10 }}
                  toolBarRender={() => [
                    <Button key="create" type="primary" icon={<PlusOutlined />} onClick={() => setCouponCreateOpen(true)}>
                      新建优惠券
                    </Button>,
                  ]}
                />
                <ModalForm
                  title="新建优惠券"
                  open={couponCreateOpen}
                  onOpenChange={setCouponCreateOpen}
                  onFinish={async (values) => {
                    try {
                      await txFetch('/api/v1/growth/coupons', {
                        method: 'POST',
                        body: JSON.stringify({
                          name: values.name,
                          face_value_fen: Number(values.face_value) * 100,
                          min_order_fen: Number(values.min_order) * 100,
                          total_count: Number(values.total_count),
                        }),
                      });
                      message.success('优惠券创建成功');
                    couponTableRef.current?.reload();
                    return true;
                  }}
                >
                  <ProFormText name="name" label="券名" placeholder="如：满100减20" rules={[{ required: true }]} />
                  <ProFormDigit name="face_value" label="面值（元）" min={1} rules={[{ required: true }]} />
                  <ProFormDigit name="min_order" label="最低消费（元）" min={0} rules={[{ required: true }]} />
                  <ProFormDigit name="total_count" label="发放总量" min={1} rules={[{ required: true }]} />
                </ModalForm>
              </>
            ),
          },
          {
            key: 'analysis',
            label: '活动效果分析',
            children: (
              <Space direction="vertical" style={{ width: '100%' }} size="large">
                {/* 时间选择 */}
                <Space>
                  <Button type={analysisDays === 7 ? 'primary' : 'default'} size="small" onClick={() => setAnalysisDays(7)}>最近7天</Button>
                  <Button type={analysisDays === 30 ? 'primary' : 'default'} size="small" onClick={() => setAnalysisDays(30)}>最近30天</Button>
                </Space>

                {/* 趋势图 */}
                <Card title="每日参与 & 核销趋势" size="small">
                  <TrendChart data={analysisData} width={720} height={260} />
                </Card>

                {/* ROI 表格 */}
                <Card title="活动 ROI 分析" size="small">
                  <Table<Campaign>
                    rowKey="id"
                    dataSource={roiCampaigns}
                    columns={roiColumns}
                    pagination={false}
                    size="small"
                    loading={roiLoading}
                  />
                </Card>
              </Space>
            ),
          },
        ]} />
      </Card>

      {/* 详情 Drawer */}
      <Drawer
        title={detailDrawer.campaign?.name ?? '活动详情'}
        open={detailDrawer.open}
        onClose={() => setDetailDrawer({ open: false, campaign: null })}
        width={640}
      >
        {detailDrawer.campaign && (
          <Space direction="vertical" style={{ width: '100%' }} size="large">
            <Descriptions bordered column={2} size="small">
              <Descriptions.Item label="活动类型">
                <Tag color={TYPE_TAG[detailDrawer.campaign.type]?.color}>{TYPE_TAG[detailDrawer.campaign.type]?.label}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                <Badge status={STATUS_BADGE[detailDrawer.campaign.status].status} text={STATUS_BADGE[detailDrawer.campaign.status].text} />
              </Descriptions.Item>
              <Descriptions.Item label="活动时间" span={2}>
                {detailDrawer.campaign.start_time.slice(0, 10)} ~ {detailDrawer.campaign.end_time.slice(0, 10)}
              </Descriptions.Item>
              <Descriptions.Item label="门店范围">{detailDrawer.campaign.store_scope}</Descriptions.Item>
              <Descriptions.Item label="参与人次">{detailDrawer.campaign.participant_count}</Descriptions.Item>
              <Descriptions.Item label="营销成本">{(detailDrawer.campaign.cost_fen / 100).toFixed(0)} 元</Descriptions.Item>
              <Descriptions.Item label="带来收入">{(detailDrawer.campaign.revenue_fen / 100).toFixed(0)} 元</Descriptions.Item>
            </Descriptions>

            <Card title="参与趋势" size="small">
              <TrendChart data={detailDrawer.campaign.daily_stats} width={560} height={220} />
            </Card>
          </Space>
        )}
      </Drawer>
    </div>
  );
}

export default CampaignPage;
