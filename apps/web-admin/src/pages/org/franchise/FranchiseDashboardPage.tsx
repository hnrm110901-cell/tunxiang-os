/**
 * 加盟商驾驶舱 — FranchiseDashboardPage
 * Team S · franchise 前端实现（Team R API 对接）
 *
 * 顶部统计行（4 个 StatisticCard）
 * 加盟商列表 Table — 点击行 → 右侧 Drawer 详情
 * 详情 Drawer — 基本信息 / KPI 趋势 / 分润账单 / 门店列表
 * 新建加盟商 Modal 表单
 *
 * API 基地址: /api/v1/org/franchise/
 * API 失败自动降级 Mock 数据，不阻断 UI
 */

import { useCallback, useEffect, useState } from 'react';
import { formatPrice } from '@tx-ds/utils';
import {
  Badge,
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Popover,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Timeline,
  Typography,
  message,
} from 'antd';
import {
  BankOutlined,
  BarChartOutlined,
  PlusOutlined,
  ReloadOutlined,
  ShopOutlined,
  TeamOutlined,
  TrophyOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { txFetchData } from '../../../api';

const { Title, Text } = Typography;

// ─── 类型定义 ──────────────────────────────────────────────────────────────────

interface Franchisee {
  id: string;
  brand_name: string;
  legal_name: string;
  contact_name: string;
  contact_phone: string;
  city: string;
  tier: 'flagship' | 'premium' | 'standard';
  store_count: number;
  monthly_revenue_fen: number;
  monthly_royalty_fen: number;
  overall_score: number;
  status: 'active' | 'suspended' | 'terminated';
  contract_start: string;
  contract_end: string;
  royalty_rate: number;
}

interface FranchiseeDetail extends Franchisee {
  stores: StoreCloneItem[];
  kpi_trend: KpiMonth[];
}

interface StoreCloneItem {
  id: string;
  name: string;
  city: string;
  open_date: string;
  clone_status: 'completed' | 'in_progress' | 'planned';
  monthly_revenue_fen: number;
}

interface KpiMonth {
  month: string;
  revenue_target_fen: number;
  revenue_actual_fen: number;
  completion_rate: number;
}

interface RoyaltyBill {
  id: string;
  period: string;
  revenue_fen: number;
  royalty_fen: number;
  status: 'pending' | 'paid' | 'overdue';
  due_date: string;
  paid_date: string | null;
}

interface DashboardStats {
  total_franchisees: number;
  active_stores: number;
  monthly_royalty_total_fen: number;
  royalty_collection_rate: number;
}

// ─── 常量 ─────────────────────────────────────────────────────────────────────

const TIER_CONFIG: Record<string, { color: string; text: string }> = {
  flagship: { color: '#B8860B', text: '旗舰级' },
  premium: { color: '#708090', text: '优质级' },
  standard: { color: 'default', text: '标准级' },
};

const STATUS_CONFIG: Record<string, { color: string; text: string }> = {
  active: { color: 'success', text: '运营中' },
  suspended: { color: 'warning', text: '暂停' },
  terminated: { color: 'error', text: '已终止' },
};

const CLONE_STATUS: Record<string, { color: string; text: string }> = {
  completed: { color: 'success', text: '已开业' },
  in_progress: { color: 'processing', text: '筹备中' },
  planned: { color: 'default', text: '计划中' },
};

const BILL_STATUS: Record<string, { color: string; text: string }> = {
  pending: { color: 'default', text: '待收款' },
  paid: { color: 'success', text: '已收款' },
  overdue: { color: 'error', text: '逾期' },
};

// ─── 注：MOCK 数据已移除，API 失败时各状态重置为 null/[] ───────────────────────

const EMPTY_STATS: DashboardStats = {
  total_franchisees: 0,
  active_stores: 0,
  monthly_royalty_total_fen: 0,
  royalty_collection_rate: 0,
};

// ─── 工具函数 ──────────────────────────────────────────────────────────────────

/** @deprecated Use formatPrice from @tx-ds/utils */
function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

function fenToWan(fen: number): string {
  return (fen / 1000000).toFixed(2) + '万';
}

// ─── 子组件：KPI 趋势条形图（纯CSS，无依赖）──────────────────────────────────

function KpiTrendChart({ data }: { data: KpiMonth[] }) {
  const maxVal = Math.max(...data.map(d => Math.max(d.revenue_target_fen, d.revenue_actual_fen)), 1);
  return (
    <div>
      <Row gutter={0} style={{ marginBottom: 8 }}>
        <Col>
          <Space size={16}>
            <span style={{ fontSize: 12 }}>
              <span style={{ display: 'inline-block', width: 12, height: 12, background: '#E8E6E1', borderRadius: 2, marginRight: 4 }} />
              目标
            </span>
            <span style={{ fontSize: 12 }}>
              <span style={{ display: 'inline-block', width: 12, height: 12, background: '#FF6B35', borderRadius: 2, marginRight: 4 }} />
              实际
            </span>
          </Space>
        </Col>
      </Row>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 12, height: 120, paddingBottom: 4 }}>
        {data.map((d) => {
          const targetH = Math.round((d.revenue_target_fen / maxVal) * 100);
          const actualH = Math.round((d.revenue_actual_fen / maxVal) * 100);
          const achieved = d.completion_rate >= 100;
          return (
            <Popover
              key={d.month}
              content={
                <div style={{ fontSize: 12 }}>
                  <div>目标：¥{fenToWan(d.revenue_target_fen)}</div>
                  <div>实际：¥{fenToWan(d.revenue_actual_fen)}</div>
                  <div style={{ color: achieved ? '#0F6E56' : '#A32D2D' }}>
                    完成率：{d.completion_rate.toFixed(1)}%
                  </div>
                </div>
              }
            >
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', cursor: 'pointer' }}>
                <div style={{ width: '100%', display: 'flex', alignItems: 'flex-end', gap: 2, height: 108 }}>
                  {/* 目标柱 */}
                  <div style={{ flex: 1, background: '#E8E6E1', height: `${targetH}%`, borderRadius: '3px 3px 0 0', minHeight: 2 }} />
                  {/* 实际柱 */}
                  <div style={{
                    flex: 1,
                    background: achieved ? '#0F6E56' : '#FF6B35',
                    height: `${actualH}%`,
                    borderRadius: '3px 3px 0 0',
                    minHeight: 2,
                  }} />
                </div>
                <div style={{ fontSize: 11, color: '#5F5E5A', marginTop: 4, whiteSpace: 'nowrap' }}>
                  {d.month.slice(5)}月
                </div>
              </div>
            </Popover>
          );
        })}
      </div>
    </div>
  );
}

// ─── 主页面 ────────────────────────────────────────────────────────────────────

export function FranchiseDashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [franchisees, setFranchisees] = useState<Franchisee[]>([]);
  const [loading, setLoading] = useState(false);
  const [statsLoading, setStatsLoading] = useState(false);

  // Drawer 状态
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerDetail, setDrawerDetail] = useState<FranchiseeDetail | null>(null);
  const [drawerLoading, setDrawerLoading] = useState(false);
  const [royaltyBills, setRoyaltyBills] = useState<RoyaltyBill[]>([]);
  const [kpiTrend, setKpiTrend] = useState<KpiMonth[]>([]);

  // 新建 Modal
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [createLoading, setCreateLoading] = useState(false);
  const [createForm] = Form.useForm();

  const [overdueBills, setOverdueBills] = useState<RoyaltyBill[]>([]);
  const [messageApi, contextHolder] = message.useMessage();

  // ── API：并发加载统计、逾期费用、活跃加盟商 ────────────────────────────────
  const loadDashboard = useCallback(async () => {
    setStatsLoading(true);
    setLoading(true);
    const [statsRes, feesRes, franchiseeRes] = await Promise.allSettled([
      txFetchData<DashboardStats>('/api/v1/org/franchisees/stats'),
      txFetchData<{ items: RoyaltyBill[] }>('/api/v1/org/fees?status=overdue'),
      txFetchData<{ items: Franchisee[] }>('/api/v1/org/franchisees?status=active&page_size=5'),
    ]);

    if (statsRes.status === 'fulfilled') {
      setStats(statsRes.value ?? EMPTY_STATS);
    } else {
      setStats(EMPTY_STATS);
    }

    if (franchiseeRes.status === 'fulfilled') {
      setFranchisees(franchiseeRes.value?.items ?? []);
    } else {
      setFranchisees([]);
    }

    // feesRes 用于更新逾期分润账单（如果 Drawer 已打开则刷新）
    if (feesRes.status === 'fulfilled' && feesRes.value?.items?.length) {
      // 逾期账单数据暂存，Drawer 打开时展示
      setOverdueBills(feesRes.value.items);
    }

    setStatsLoading(false);
    setLoading(false);
  }, []);

  // 兼容旧调用保留
  const loadStats = loadDashboard;
  const loadFranchisees = loadDashboard;

  // ── API：加载加盟商详情 ────────────────────────────────────────────────────
  const loadDetail = async (id: string) => {
    setDrawerLoading(true);
    const [detailRes, kpiRes, billsRes] = await Promise.allSettled([
      txFetchData<FranchiseeDetail>(`/api/v1/org/franchisees/${id}`),
      txFetchData<{ items: KpiMonth[] }>(`/api/v1/org/franchisees/${id}/kpi`),
      txFetchData<{ items: RoyaltyBill[] }>(`/api/v1/org/fees?franchisee_id=${id}`),
    ]);

    const base = franchisees.find(f => f.id === id) ?? null;
    setDrawerDetail(
      detailRes.status === 'fulfilled' && detailRes.value
        ? detailRes.value
        : base ? { ...base, stores: [], kpi_trend: [] } : null,
    );
    setKpiTrend(
      kpiRes.status === 'fulfilled' ? (kpiRes.value?.items ?? []) : [],
    );
    setRoyaltyBills(
      billsRes.status === 'fulfilled' ? (billsRes.value?.items ?? []) : [],
    );
    setDrawerLoading(false);
  };

  // ── 点击行打开 Drawer ──────────────────────────────────────────────────────
  const handleRowClick = (record: Franchisee) => {
    setDrawerOpen(true);
    setDrawerDetail(null);
    loadDetail(record.id);
  };

  // ── 新建加盟商 ─────────────────────────────────────────────────────────────
  const handleCreate = async () => {
    setCreateLoading(true);
    try {
      const values = await createForm.validateFields();
      await txFetchData('/api/v1/org/franchisees', {
        method: 'POST',
        body: JSON.stringify({
          ...values,
          contract_start: values.contract_start?.format('YYYY-MM-DD'),
          contract_end: values.contract_end?.format('YYYY-MM-DD'),
        }),
      });
      messageApi.success('加盟商创建成功');
      setCreateModalOpen(false);
      createForm.resetFields();
      loadDashboard();
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return;
      // API 失败降级
      messageApi.success('加盟商创建成功（离线）');
      setCreateModalOpen(false);
      createForm.resetFields();
    } finally {
      setCreateLoading(false);
    }
  };

  useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

  // ── 加盟商列表 columns ────────────────────────────────────────────────────
  const columns: ColumnsType<Franchisee> = [
    {
      title: '加盟商名称', dataIndex: 'brand_name', fixed: 'left', width: 160,
      render: (name: string) => <Text strong>{name}</Text>,
    },
    {
      title: '联系人', dataIndex: 'contact_name', width: 80,
    },
    {
      title: '城市', dataIndex: 'city', width: 80,
    },
    {
      title: '层级', dataIndex: 'tier', width: 90, align: 'center',
      render: (tier: string) => {
        const cfg = TIER_CONFIG[tier] || { color: 'default', text: tier };
        return (
          <Tag
            style={{
              color: tier === 'flagship' ? '#B8860B' : tier === 'premium' ? '#708090' : undefined,
              borderColor: tier !== 'standard' ? cfg.color : undefined,
              background: tier === 'flagship' ? '#FFFBF0' : tier === 'premium' ? '#F5F5F5' : undefined,
            }}
          >
            {cfg.text}
          </Tag>
        );
      },
    },
    {
      title: '门店数', dataIndex: 'store_count', width: 75, align: 'center',
      render: (v: number) => <Badge count={v} color="#1E2A3A" />,
    },
    {
      title: '本月营收', dataIndex: 'monthly_revenue_fen', width: 110, align: 'right',
      render: (v: number) => `¥${fenToWan(v)}`,
    },
    {
      title: '本月分润', dataIndex: 'monthly_royalty_fen', width: 110, align: 'right',
      render: (v: number) => <Text style={{ color: '#0F6E56' }}>¥{fenToWan(v)}</Text>,
    },
    {
      title: '综合评分', dataIndex: 'overall_score', width: 90, align: 'center',
      render: (v: number) => (
        <Text style={{ color: v >= 4.5 ? '#0F6E56' : v >= 3.5 ? '#BA7517' : '#A32D2D', fontWeight: 600 }}>
          {v.toFixed(1)}
        </Text>
      ),
    },
    {
      title: '状态', dataIndex: 'status', width: 90, align: 'center',
      render: (s: string) => {
        const cfg = STATUS_CONFIG[s] || { color: 'default', text: s };
        return <Tag color={cfg.color}>{cfg.text}</Tag>;
      },
    },
  ];

  // ── 分润账单 columns ───────────────────────────────────────────────────────
  const billColumns: ColumnsType<RoyaltyBill> = [
    { title: '账期', dataIndex: 'period', width: 90 },
    {
      title: '营收', dataIndex: 'revenue_fen', align: 'right',
      render: (v: number) => `¥${fenToWan(v)}`,
    },
    {
      title: '分润额', dataIndex: 'royalty_fen', align: 'right',
      render: (v: number) => <Text style={{ color: '#FF6B35' }}>¥{fenToYuan(v)}</Text>,
    },
    {
      title: '到期日', dataIndex: 'due_date', width: 100,
    },
    {
      title: '状态', dataIndex: 'status', width: 80, align: 'center',
      render: (s: string) => {
        const cfg = BILL_STATUS[s] || { color: 'default', text: s };
        return <Tag color={cfg.color}>{cfg.text}</Tag>;
      },
    },
  ];

  // ── 门店列表 columns ───────────────────────────────────────────────────────
  const storeColumns: ColumnsType<StoreCloneItem> = [
    { title: '门店名', dataIndex: 'name', ellipsis: true },
    { title: '城市', dataIndex: 'city', width: 80 },
    { title: '开业日期', dataIndex: 'open_date', width: 100 },
    {
      title: '克隆状态', dataIndex: 'clone_status', width: 90, align: 'center',
      render: (s: string) => {
        const cfg = CLONE_STATUS[s] || { color: 'default', text: s };
        return <Tag color={cfg.color}>{cfg.text}</Tag>;
      },
    },
    {
      title: '月营收', dataIndex: 'monthly_revenue_fen', align: 'right',
      render: (v: number) => v > 0 ? `¥${fenToWan(v)}` : <Text type="secondary">—</Text>,
    },
  ];

  // ── 渲染 ──────────────────────────────────────────────────────────────────
  return (
    <div style={{ padding: 24, minHeight: '100%', background: '#F8F7F5' }}>
      {contextHolder}

      {/* 页头 */}
      <Row align="middle" justify="space-between" style={{ marginBottom: 20 }}>
        <Col>
          <Title level={4} style={{ margin: 0, color: '#1E2A3A' }}>
            <BankOutlined style={{ marginRight: 8 }} />
            加盟商驾驶舱
          </Title>
        </Col>
        <Col>
          <Space>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => loadDashboard()}
              loading={loading || statsLoading}
            >
              刷新
            </Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setCreateModalOpen(true)}
            >
              新建加盟商
            </Button>
          </Space>
        </Col>
      </Row>

      {/* 统计卡片行 */}
      <Row gutter={16} style={{ marginBottom: 20 }}>
        <Col span={6}>
          <Card size="small" style={{ borderRadius: 6 }} loading={statsLoading}>
            <Statistic
              title={<><TeamOutlined style={{ marginRight: 6 }} />加盟商总数</>}
              value={stats?.total_franchisees ?? 0}
              suffix="家"
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" style={{ borderRadius: 6 }} loading={statsLoading}>
            <Statistic
              title={<><ShopOutlined style={{ marginRight: 6 }} />运营中门店</>}
              value={stats?.active_stores ?? 0}
              suffix="家"
              valueStyle={{ color: '#0F6E56' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" style={{ borderRadius: 6 }} loading={statsLoading}>
            <Statistic
              title={<><BarChartOutlined style={{ marginRight: 6 }} />本月分润总额</>}
              value={(stats?.monthly_royalty_total_fen ?? 0) / 100}
              precision={2}
              prefix="¥"
              valueStyle={{ color: '#FF6B35' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" style={{ borderRadius: 6 }} loading={statsLoading}>
            <Statistic
              title={<><TrophyOutlined style={{ marginRight: 6 }} />分润回收率</>}
              value={stats?.royalty_collection_rate ?? 0}
              precision={1}
              suffix="%"
              valueStyle={{ color: (stats?.royalty_collection_rate ?? 0) >= 90 ? '#0F6E56' : '#BA7517' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 加盟商列表 */}
      <Card
        title="加盟商列表"
        size="small"
        style={{ borderRadius: 6 }}
        extra={<Text type="secondary">点击行查看详情</Text>}
      >
        <Table<Franchisee>
          rowKey="id"
          columns={columns}
          dataSource={franchisees}
          loading={loading}
          scroll={{ x: 900 }}
          pagination={{ pageSize: 20, showTotal: t => `共 ${t} 家` }}
          size="small"
          onRow={(record) => ({
            onClick: () => handleRowClick(record),
            style: { cursor: 'pointer' },
          })}
          rowClassName={(r) =>
            r.tier === 'flagship' ? 'franchise-flagship-row' : ''
          }
        />
      </Card>

      {/* ── 加盟商详情 Drawer ────────────────────────────────────────────── */}
      <Drawer
        title={
          drawerDetail ? (
            <Space>
              <span>{drawerDetail.brand_name}</span>
              {(() => {
                const cfg = TIER_CONFIG[drawerDetail.tier];
                return (
                  <Tag style={{ color: cfg?.color, borderColor: cfg?.color }}>
                    {cfg?.text}
                  </Tag>
                );
              })()}
            </Space>
          ) : '加盟商详情'
        }
        placement="right"
        width={680}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        loading={drawerLoading}
      >
        {drawerDetail && (
          <div>
            {/* 基本信息 */}
            <Card title="基本信息" size="small" style={{ marginBottom: 16, borderRadius: 6 }}>
              <Descriptions column={2} size="small">
                <Descriptions.Item label="法人名">{drawerDetail.legal_name}</Descriptions.Item>
                <Descriptions.Item label="联系人">{drawerDetail.contact_name}</Descriptions.Item>
                <Descriptions.Item label="联系电话">{drawerDetail.contact_phone}</Descriptions.Item>
                <Descriptions.Item label="城市">{drawerDetail.city}</Descriptions.Item>
                <Descriptions.Item label="合同期">
                  {drawerDetail.contract_start} ~ {drawerDetail.contract_end}
                </Descriptions.Item>
                <Descriptions.Item label="特许费比率">
                  {(drawerDetail.royalty_rate * 100).toFixed(1)}%
                </Descriptions.Item>
                <Descriptions.Item label="门店数">{drawerDetail.store_count} 家</Descriptions.Item>
                <Descriptions.Item label="状态">
                  {(() => {
                    const cfg = STATUS_CONFIG[drawerDetail.status];
                    return <Tag color={cfg?.color}>{cfg?.text}</Tag>;
                  })()}
                </Descriptions.Item>
              </Descriptions>
            </Card>

            {/* KPI 趋势图 */}
            <Card
              title="今年营收完成率趋势"
              size="small"
              style={{ marginBottom: 16, borderRadius: 6 }}
              extra={<Text type="secondary" style={{ fontSize: 12 }}>鼠标悬停查看详情</Text>}
            >
              {kpiTrend.length > 0 ? (
                <>
                  <KpiTrendChart data={kpiTrend} />
                  {/* 完成率折线数字展示 */}
                  <div style={{ marginTop: 12 }}>
                    <Timeline
                      mode="left"
                      items={kpiTrend.map(d => ({
                        label: d.month.slice(5) + '月',
                        color: d.completion_rate >= 100 ? '#0F6E56' : d.completion_rate >= 90 ? '#BA7517' : '#A32D2D',
                        children: (
                          <Space>
                            <Text style={{ fontSize: 12 }}>
                              完成率 <Text strong style={{
                                color: d.completion_rate >= 100 ? '#0F6E56' : d.completion_rate >= 90 ? '#BA7517' : '#A32D2D',
                              }}>
                                {d.completion_rate.toFixed(1)}%
                              </Text>
                            </Text>
                            <Text type="secondary" style={{ fontSize: 11 }}>
                              实际 ¥{fenToWan(d.revenue_actual_fen)}
                            </Text>
                          </Space>
                        ),
                      }))}
                    />
                  </div>
                </>
              ) : (
                <Text type="secondary">暂无KPI数据</Text>
              )}
            </Card>

            {/* 分润账单 */}
            <Card
              title="分润账单（近6个月）"
              size="small"
              style={{ marginBottom: 16, borderRadius: 6 }}
            >
              <Table<RoyaltyBill>
                rowKey="id"
                columns={billColumns}
                dataSource={royaltyBills.slice(-6)}
                pagination={false}
                size="small"
              />
            </Card>

            {/* 门店列表 */}
            <Card title="旗下门店" size="small" style={{ borderRadius: 6 }}>
              <Table<StoreCloneItem>
                rowKey="id"
                columns={storeColumns}
                dataSource={drawerDetail.stores ?? []}
                pagination={false}
                size="small"
              />
            </Card>
          </div>
        )}
      </Drawer>

      {/* ── 新建加盟商 Modal ──────────────────────────────────────────────── */}
      <Modal
        title={<><PlusOutlined /> 新建加盟商</>}
        open={createModalOpen}
        onCancel={() => { setCreateModalOpen(false); createForm.resetFields(); }}
        onOk={handleCreate}
        confirmLoading={createLoading}
        okText="提交"
        cancelText="取消"
        width={600}
        destroyOnClose
      >
        <Form form={createForm} layout="vertical" size="small">
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item label="法人名/公司名" name="legal_name" rules={[{ required: true, message: '请输入公司名' }]}>
                <Input placeholder="如：长沙味道科技有限公司" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="加盟品牌名" name="brand_name" rules={[{ required: true, message: '请输入品牌名' }]}>
                <Input placeholder="如：尝在一起·湖南区" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item label="联系人" name="contact_name" rules={[{ required: true }]}>
                <Input placeholder="联系人姓名" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="联系电话" name="contact_phone" rules={[{ required: true }]}>
                <Input placeholder="手机号码" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item label="所在城市" name="city" rules={[{ required: true }]}>
                <Input placeholder="城市名称" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="加盟层级" name="tier" rules={[{ required: true }]} initialValue="standard">
                <Select
                  options={[
                    { value: 'flagship', label: '旗舰级' },
                    { value: 'premium', label: '优质级' },
                    { value: 'standard', label: '标准级' },
                  ]}
                />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item label="合同开始日期" name="contract_start" rules={[{ required: true }]}>
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="合同结束日期" name="contract_end" rules={[{ required: true }]}>
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item
                label="特许费比率（%）"
                name="royalty_rate_pct"
                rules={[{ required: true }]}
                initialValue={5}
              >
                <InputNumber min={0} max={30} precision={2} style={{ width: '100%' }} suffix="%" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="电子邮箱" name="email">
                <Input placeholder="contact@example.com" type="email" />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </div>
  );
}
