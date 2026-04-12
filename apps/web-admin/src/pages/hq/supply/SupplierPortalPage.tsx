/**
 * 供应商门户管理页 — 域D 供应链 · 总部视角
 * Tab1: 供应商档案 | Tab2: 询价管理(RFQ) | Tab3: 风险评估
 *
 * 技术栈：Ant Design 5.x + ProComponents
 * API: supplierApi (txFetchData) — try/catch 降级 Mock 数据
 * 金额规范：存储/传输分(fen)，展示元(÷100)
 */
import React, { useRef, useState, useCallback, useEffect } from 'react';
import {
  ProTable,
  ModalForm,
  ProFormText,
  ProFormSelect,
  ProFormDigit,
  ActionType,
} from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';
import {
  Button,
  Tag,
  Space,
  Drawer,
  Descriptions,
  Progress,
  Badge,
  Alert,
  List,
  Modal,
  Tabs,
  Row,
  Col,
  Card,
  Statistic,
  message,
  Spin,
  Typography,
  DatePicker,
  Select,
  InputNumber,
  Divider,
  Table,
} from 'antd';
import {
  PlusOutlined,
  EyeOutlined,
  BarChartOutlined,
  SafetyCertificateOutlined,
  ShopOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import {
  fetchSupplierList,
  fetchSupplierDetail,
  createSupplier,
  fetchRFQList,
  createRFQ,
  fetchRFQCompare,
  acceptRFQQuote,
  fetchRiskAssessment,
} from '../../../api/supplierApi';
import type {
  SupplierListItem,
  SupplierDetail,
  RFQListItem,
  RFQCompareResult,
  RiskAssessmentResult,
  SupplierCategory,
  RiskLevel,
} from '../../../api/supplierApi';

const { Text, Title } = Typography;

// ─── 类别 Tag 配置 ─────────────────────────────────────────────────────────────

const CATEGORY_CONFIG: Record<string, { label: string; color: string }> = {
  seafood:   { label: '活鲜',   color: 'blue'    },
  meat:      { label: '肉禽',   color: 'red'     },
  vegetable: { label: '蔬菜',   color: 'green'   },
  seasoning: { label: '调料',   color: 'orange'  },
  frozen:    { label: '冷冻',   color: 'cyan'    },
  dry_goods: { label: '干货',   color: 'gold'    },
  beverage:  { label: '饮品',   color: 'purple'  },
  other:     { label: '其他',   color: 'default' },
};

const CATEGORY_OPTIONS = Object.entries(CATEGORY_CONFIG).map(([value, { label }]) => ({
  value,
  label,
}));

// ─── 状态配置 ─────────────────────────────────────────────────────────────────

const SUPPLIER_STATUS_CONFIG: Record<string, { label: string; status: 'success' | 'error' | 'warning' | 'default' }> = {
  active:    { label: '合作中', status: 'success' },
  inactive:  { label: '暂停中', status: 'warning' },
  suspended: { label: '已停合作', status: 'error' },
};

const RFQ_STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  open:     { label: '进行中', color: 'processing' },
  quoted:   { label: '已报价', color: 'blue'       },
  accepted: { label: '已接受', color: 'success'    },
  expired:  { label: '已过期', color: 'default'    },
};

const RISK_CONFIG: Record<RiskLevel, { label: string; color: string; badgeStatus: 'success' | 'warning' | 'error' }> = {
  low:    { label: '低风险',  color: 'success', badgeStatus: 'success' },
  medium: { label: '中风险',  color: 'warning', badgeStatus: 'warning' },
  high:   { label: '高风险',  color: 'error',   badgeStatus: 'error'   },
};

// ─── Mock 数据（后端未就绪时降级展示）───────────────────────────────────────────

const MOCK_SUPPLIERS: SupplierListItem[] = [
  {
    id: 's1', name: '鲜丰水产有限公司', category: 'seafood', contact_name: '张伟',
    contact_phone: '13800138001', address: '长沙市岳麓区渔人码头3号', status: 'active',
    rating: 4.7, order_count: 128, qualifications: ['食品经营许可证', 'HACCP'],
    payment_term: 'net30', created_at: '2025-01-15T08:00:00Z', updated_at: '2026-04-01T10:00:00Z',
  },
  {
    id: 's2', name: '湘农有机蔬菜基地', category: 'vegetable', contact_name: '李娟',
    contact_phone: '13900139002', address: '长沙县蔬菜基地产业园', status: 'active',
    rating: 4.2, order_count: 96, qualifications: ['食品经营许可证', '有机认证'],
    payment_term: 'net60', created_at: '2025-03-20T08:00:00Z', updated_at: '2026-04-01T10:00:00Z',
  },
  {
    id: 's3', name: '联欣冷链物流', category: 'frozen', contact_name: '王强',
    contact_phone: '13700137003', address: '长沙市雨花区冷链园区', status: 'active',
    rating: 3.8, order_count: 64, qualifications: ['食品经营许可证', 'ISO22000'],
    payment_term: 'cod', created_at: '2025-06-01T08:00:00Z', updated_at: '2026-04-01T10:00:00Z',
  },
  {
    id: 's4', name: '天然调味品厂', category: 'seasoning', contact_name: '陈敏',
    contact_phone: '13600136004', address: '株洲市调味品工业园', status: 'inactive',
    rating: 3.5, order_count: 32, qualifications: ['食品经营许可证'],
    payment_term: 'net30', created_at: '2024-11-01T08:00:00Z', updated_at: '2026-02-01T10:00:00Z',
  },
];

const MOCK_RFQS: RFQListItem[] = [
  {
    rfq_id: 'rfq1', item_name: '大黄鱼（野生）', quantity: 50, unit: '斤',
    expected_delivery_date: '2026-04-08', supplier_ids: ['s1', 's3'],
    status: 'quoted', created_at: '2026-04-02T09:00:00Z', updated_at: '2026-04-03T14:00:00Z',
  },
  {
    rfq_id: 'rfq2', item_name: '有机生菜', quantity: 200, unit: '斤',
    expected_delivery_date: '2026-04-06', supplier_ids: ['s2'],
    status: 'open', created_at: '2026-04-03T10:00:00Z', updated_at: '2026-04-03T10:00:00Z',
  },
  {
    rfq_id: 'rfq3', item_name: '花椒油', quantity: 100, unit: '瓶',
    expected_delivery_date: '2026-04-10', supplier_ids: ['s4', 's2'],
    status: 'accepted', created_at: '2026-03-28T08:00:00Z', updated_at: '2026-04-01T16:00:00Z',
  },
];

const MOCK_RISK: RiskAssessmentResult = {
  assessed_at: '2026-04-04T08:00:00Z',
  overall_risk_level: 'medium',
  high_risk_count: 1,
  medium_risk_count: 2,
  low_risk_count: 5,
  items: [
    {
      supplier_id: 's4', supplier_name: '天然调味品厂', risk_level: 'high',
      risk_score: 72,
      risk_factors: ['近30天无交货记录', '资质证书即将到期', '联系人失联'],
      mitigation_suggestions: ['立即启动备用供应商', '发起资质续期提醒', '联系采购主管核实'],
      last_assessed_at: '2026-04-04T08:00:00Z',
    },
    {
      supplier_id: 's3', supplier_name: '联欣冷链物流', risk_level: 'medium',
      risk_score: 45,
      risk_factors: ['评分低于4.0', '最近两次交货延迟'],
      mitigation_suggestions: ['与供应商召开改进会议', '增加备用冷链供应商'],
      last_assessed_at: '2026-04-04T08:00:00Z',
    },
    {
      supplier_id: 's2', supplier_name: '湘农有机蔬菜基地', risk_level: 'low',
      risk_score: 18,
      risk_factors: [],
      mitigation_suggestions: ['维持当前合作关系'],
      last_assessed_at: '2026-04-04T08:00:00Z',
    },
  ],
  global_suggestions: [
    '建议为活鲜品类增加至少1个备用供应商',
    '冷链类别集中度较高，建议分散至2家供应商',
    '每季度对评分低于4.0的供应商进行约谈评审',
  ],
};

// ─── Tab1: 供应商档案 ──────────────────────────────────────────────────────────

function SupplierArchiveTab() {
  const actionRef = useRef<ActionType>();
  const [detailDrawerOpen, setDetailDrawerOpen] = useState(false);
  const [selectedDetail, setSelectedDetail] = useState<SupplierDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const handleViewDetail = useCallback(async (record: SupplierListItem) => {
    setDetailDrawerOpen(true);
    setDetailLoading(true);
    try {
      const detail = await fetchSupplierDetail(record.id);
      setSelectedDetail(detail);
    } catch {
      // 降级为 Mock
      setSelectedDetail({
        ...record,
        delivery_rate: 0.96,
        quality_pass_rate: 0.98,
        active_contract_count: 3,
      });
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const columns: ProColumns<SupplierListItem>[] = [
    {
      title: '供应商名称',
      dataIndex: 'name',
      valueType: 'text',
      fixed: 'left',
      width: 200,
    },
    {
      title: '类别',
      dataIndex: 'category',
      valueType: 'select',
      width: 90,
      valueEnum: Object.fromEntries(
        Object.entries(CATEGORY_CONFIG).map(([k, v]) => [k, { text: v.label }]),
      ),
      render: (_, r) => {
        const cfg = CATEGORY_CONFIG[r.category] ?? { label: r.category, color: 'default' };
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    {
      title: '联系人',
      dataIndex: 'contact_name',
      valueType: 'text',
      search: false,
      width: 90,
    },
    {
      title: '联系电话',
      dataIndex: 'contact_phone',
      valueType: 'text',
      search: false,
      width: 130,
    },
    {
      title: '状态',
      dataIndex: 'status',
      valueType: 'select',
      width: 100,
      valueEnum: Object.fromEntries(
        Object.entries(SUPPLIER_STATUS_CONFIG).map(([k, v]) => [k, { text: v.label }]),
      ),
      render: (_, r) => {
        const cfg = SUPPLIER_STATUS_CONFIG[r.status] ?? { label: r.status, status: 'default' };
        return <Badge status={cfg.status} text={cfg.label} />;
      },
    },
    {
      title: '综合评分',
      dataIndex: 'rating',
      valueType: 'digit',
      search: false,
      width: 160,
      renderFormItem: () => (
        <InputNumber min={0} max={5} step={0.1} placeholder="最低评分" style={{ width: '100%' }} />
      ),
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          <Progress
            percent={r.rating * 20}
            showInfo={false}
            strokeColor="#FF6B35"
            style={{ width: 100, marginBottom: 2 }}
          />
          <Text style={{ fontSize: 12, color: '#5F5E5A' }}>{r.rating.toFixed(1)} / 5.0</Text>
        </Space>
      ),
    },
    {
      title: '订单数',
      dataIndex: 'order_count',
      valueType: 'digit',
      search: false,
      width: 80,
      sorter: true,
    },
    {
      title: '操作',
      valueType: 'option',
      fixed: 'right',
      width: 80,
      render: (_, record) => [
        <a key="view" onClick={() => handleViewDetail(record)}>
          <EyeOutlined /> 查看
        </a>,
      ],
    },
  ];

  return (
    <>
      <ProTable<SupplierListItem>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        scroll={{ x: 900 }}
        search={{ labelWidth: 'auto' }}
        pagination={{ defaultPageSize: 20, showSizeChanger: true }}
        toolBarRender={() => [
          <ModalForm
            key="create"
            title="新增供应商"
            trigger={
              <Button type="primary" icon={<PlusOutlined />}>
                新增供应商
              </Button>
            }
            width={600}
            modalProps={{ destroyOnClose: true }}
            onFinish={async (values) => {
              try {
                await createSupplier({
                  name: values.name,
                  category: values.category as SupplierCategory,
                  contact_name: values.contact_name,
                  contact_phone: values.contact_phone,
                  address: values.address,
                  qualifications: values.qualifications,
                  payment_term: values.payment_term,
                });
                message.success('供应商创建成功');
                actionRef.current?.reload();
                return true;
              } catch (err) {
                message.error('创建失败，请重试');
                return false;
              }
            }}
          >
            <ProFormText
              name="name"
              label="供应商名称"
              rules={[{ required: true, message: '请输入供应商名称' }]}
              placeholder="如：鲜丰水产有限公司"
            />
            <Row gutter={16}>
              <Col span={12}>
                <ProFormSelect
                  name="category"
                  label="类别"
                  rules={[{ required: true, message: '请选择类别' }]}
                  options={CATEGORY_OPTIONS}
                  placeholder="选择供应商类别"
                />
              </Col>
              <Col span={12}>
                <ProFormSelect
                  name="payment_term"
                  label="付款条件"
                  options={[
                    { value: 'net30', label: 'Net30（月结）' },
                    { value: 'net60', label: 'Net60（双月结）' },
                    { value: 'cod', label: 'COD（现付）' },
                  ]}
                  placeholder="选择付款条件"
                />
              </Col>
            </Row>
            <Row gutter={16}>
              <Col span={12}>
                <ProFormText name="contact_name" label="联系人姓名" placeholder="联系人姓名" />
              </Col>
              <Col span={12}>
                <ProFormText name="contact_phone" label="联系电话" placeholder="联系电话" />
              </Col>
            </Row>
            <ProFormText name="address" label="地址" placeholder="详细地址" />
            <ProFormSelect
              name="qualifications"
              label="资质证书"
              fieldProps={{ mode: 'tags' }}
              options={[
                { value: '食品经营许可证', label: '食品经营许可证' },
                { value: 'ISO22000',      label: 'ISO22000'      },
                { value: 'HACCP',         label: 'HACCP'         },
                { value: '有机认证',       label: '有机认证'       },
              ]}
              placeholder="选择或输入资质证书"
            />
          </ModalForm>,
        ]}
        request={async (params) => {
          try {
            const res = await fetchSupplierList({
              category: params.category,
              status: params.status,
              rating_min: params.rating,
              page: params.current,
              size: params.pageSize,
            });
            return { data: res.items, total: res.total, success: true };
          } catch {
            return { data: MOCK_SUPPLIERS, total: MOCK_SUPPLIERS.length, success: true };
          }
        }}
      />

      {/* 供应商详情 Drawer */}
      <Drawer
        title="供应商详情"
        open={detailDrawerOpen}
        onClose={() => setDetailDrawerOpen(false)}
        width={520}
        destroyOnClose
      >
        <Spin spinning={detailLoading}>
          {selectedDetail && (
            <>
              <Descriptions
                column={2}
                size="small"
                style={{ marginBottom: 24 }}
                items={[
                  { label: '供应商名称', children: <Text strong>{selectedDetail.name}</Text>, span: 2 },
                  { label: '类别', children: <Tag color={CATEGORY_CONFIG[selectedDetail.category]?.color}>{CATEGORY_CONFIG[selectedDetail.category]?.label ?? selectedDetail.category}</Tag> },
                  { label: '状态', children: <Badge status={SUPPLIER_STATUS_CONFIG[selectedDetail.status]?.status ?? 'default'} text={SUPPLIER_STATUS_CONFIG[selectedDetail.status]?.label ?? selectedDetail.status} /> },
                  { label: '联系人', children: selectedDetail.contact_name ?? '—' },
                  { label: '联系电话', children: selectedDetail.contact_phone ?? '—' },
                  { label: '地址', children: selectedDetail.address ?? '—', span: 2 },
                  { label: '付款条件', children: selectedDetail.payment_term?.toUpperCase() ?? '—' },
                  { label: '订单总数', children: `${selectedDetail.order_count} 单` },
                  { label: '资质证书', children: selectedDetail.qualifications?.length ? selectedDetail.qualifications.map((q) => <Tag key={q}>{q}</Tag>) : '—', span: 2 },
                ]}
              />
              <Divider>绩效指标</Divider>
              <Row gutter={16}>
                <Col span={8}>
                  <Card size="small" style={{ textAlign: 'center' }}>
                    <Statistic
                      title="交付率"
                      value={(selectedDetail.delivery_rate * 100).toFixed(1)}
                      suffix="%"
                      valueStyle={{ color: selectedDetail.delivery_rate >= 0.9 ? '#0F6E56' : '#BA7517', fontSize: 22 }}
                    />
                  </Card>
                </Col>
                <Col span={8}>
                  <Card size="small" style={{ textAlign: 'center' }}>
                    <Statistic
                      title="质量通过率"
                      value={(selectedDetail.quality_pass_rate * 100).toFixed(1)}
                      suffix="%"
                      valueStyle={{ color: selectedDetail.quality_pass_rate >= 0.95 ? '#0F6E56' : '#BA7517', fontSize: 22 }}
                    />
                  </Card>
                </Col>
                <Col span={8}>
                  <Card size="small" style={{ textAlign: 'center' }}>
                    <Statistic
                      title="活跃合同数"
                      value={selectedDetail.active_contract_count}
                      suffix="份"
                      valueStyle={{ fontSize: 22 }}
                    />
                  </Card>
                </Col>
              </Row>
              <div style={{ marginTop: 16 }}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  综合评分：{selectedDetail.rating.toFixed(1)} / 5.0
                </Text>
                <Progress
                  percent={selectedDetail.rating * 20}
                  showInfo={false}
                  strokeColor="#FF6B35"
                  style={{ marginTop: 4 }}
                />
              </div>
            </>
          )}
        </Spin>
      </Drawer>
    </>
  );
}

// ─── Tab2: 询价管理(RFQ) ──────────────────────────────────────────────────────

function RFQTab() {
  const actionRef = useRef<ActionType>();
  const [compareDrawerOpen, setCompareDrawerOpen] = useState(false);
  const [compareResult, setCompareResult] = useState<RFQCompareResult | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [acceptingId, setAcceptingId] = useState<string | null>(null);
  const [supplierOptions, setSupplierOptions] = useState<{ value: string; label: string }[]>([]);

  useEffect(() => {
    fetchSupplierList({ size: 100 })
      .then((res) => {
        setSupplierOptions(
          res.items.map((s) => ({ value: s.id, label: s.name })),
        );
      })
      .catch(() => {
        setSupplierOptions(MOCK_SUPPLIERS.map((s) => ({ value: s.id, label: s.name })));
      });
  }, []);

  const handleCompare = useCallback(async (record: RFQListItem) => {
    setCompareDrawerOpen(true);
    setCompareLoading(true);
    try {
      const result = await fetchRFQCompare(record.rfq_id);
      setCompareResult(result);
    } catch {
      // Mock 降级
      setCompareResult({
        rfq_id: record.rfq_id,
        item_name: record.item_name,
        quantity: record.quantity,
        unit: record.unit,
        quotes: [
          {
            supplier_id: 's1', supplier_name: '鲜丰水产有限公司', supplier_rating: 4.7,
            unit_price_fen: 6800, total_price_fen: 6800 * record.quantity,
            delivery_days: 1, is_recommended: true,
            recommendation_reason: '综合评分最高，价格适中，历史交付率96%',
          },
          {
            supplier_id: 's3', supplier_name: '联欣冷链物流', supplier_rating: 3.8,
            unit_price_fen: 6200, total_price_fen: 6200 * record.quantity,
            delivery_days: 2, is_recommended: false,
            recommendation_reason: undefined,
          },
        ],
      });
    } finally {
      setCompareLoading(false);
    }
  }, []);

  const handleAccept = useCallback(async (rfqId: string, supplierId: string) => {
    setAcceptingId(supplierId);
    try {
      await acceptRFQQuote(rfqId, supplierId);
      message.success('已接受报价');
      setCompareDrawerOpen(false);
      actionRef.current?.reload();
    } catch {
      message.error('操作失败，请重试');
    } finally {
      setAcceptingId(null);
    }
  }, []);

  const columns: ProColumns<RFQListItem>[] = [
    {
      title: '询价单号',
      dataIndex: 'rfq_id',
      valueType: 'text',
      width: 120,
      copyable: true,
    },
    {
      title: '品名',
      dataIndex: 'item_name',
      valueType: 'text',
      width: 160,
    },
    {
      title: '数量',
      dataIndex: 'quantity',
      valueType: 'digit',
      search: false,
      width: 100,
      render: (_, r) => `${r.quantity} ${r.unit}`,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      valueType: 'dateTime',
      search: false,
      width: 160,
      render: (_, r) => dayjs(r.created_at).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '状态',
      dataIndex: 'status',
      valueType: 'select',
      width: 100,
      valueEnum: Object.fromEntries(
        Object.entries(RFQ_STATUS_CONFIG).map(([k, v]) => [k, { text: v.label }]),
      ),
      render: (_, r) => {
        const cfg = RFQ_STATUS_CONFIG[r.status] ?? { label: r.status, color: 'default' };
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    {
      title: '操作',
      valueType: 'option',
      fixed: 'right',
      width: 100,
      render: (_, record) => [
        <a
          key="compare"
          onClick={() => handleCompare(record)}
          style={{ color: record.status === 'accepted' ? '#B4B2A9' : undefined }}
        >
          <BarChartOutlined /> 比价
        </a>,
      ],
    },
  ];

  const compareColumns = [
    { title: '供应商', dataIndex: 'supplier_name', width: 160 },
    {
      title: '单价',
      dataIndex: 'unit_price_fen',
      width: 100,
      render: (v: number) => `¥${(v / 100).toFixed(2)}`,
    },
    {
      title: '总价',
      dataIndex: 'total_price_fen',
      width: 100,
      render: (v: number) => `¥${(v / 100).toFixed(2)}`,
    },
    { title: '交货天数', dataIndex: 'delivery_days', width: 90, render: (v: number) => `${v} 天` },
    {
      title: '综合评分',
      dataIndex: 'supplier_rating',
      width: 90,
      render: (v: number) => <Text style={{ color: '#FF6B35' }}>{v.toFixed(1)}</Text>,
    },
    {
      title: '推荐',
      dataIndex: 'is_recommended',
      width: 60,
      render: (v: boolean) => v ? <Tag color="gold">推荐</Tag> : null,
    },
    {
      title: '推荐理由',
      dataIndex: 'recommendation_reason',
      ellipsis: true,
    },
    {
      title: '操作',
      width: 100,
      render: (_: unknown, row: { supplier_id: string; is_recommended: boolean }) => (
        <Button
          type={row.is_recommended ? 'primary' : 'default'}
          size="small"
          loading={acceptingId === row.supplier_id}
          onClick={() => compareResult && handleAccept(compareResult.rfq_id, row.supplier_id)}
        >
          接受报价
        </Button>
      ),
    },
  ];

  return (
    <>
      <ProTable<RFQListItem>
        actionRef={actionRef}
        rowKey="rfq_id"
        columns={columns}
        scroll={{ x: 800 }}
        search={{ labelWidth: 'auto' }}
        pagination={{ defaultPageSize: 20 }}
        toolBarRender={() => [
          <ModalForm
            key="rfq"
            title="发起询价"
            trigger={
              <Button type="primary" icon={<PlusOutlined />}>
                发起询价
              </Button>
            }
            width={560}
            modalProps={{ destroyOnClose: true }}
            onFinish={async (values) => {
              try {
                await createRFQ({
                  item_name: values.item_name,
                  quantity: values.quantity,
                  unit: values.unit,
                  expected_delivery_date: values.expected_delivery_date
                    ? dayjs(values.expected_delivery_date).format('YYYY-MM-DD')
                    : undefined,
                  supplier_ids: values.supplier_ids ?? [],
                });
                message.success('询价已发起');
                actionRef.current?.reload();
                return true;
              } catch {
                message.error('发起失败，请重试');
                return false;
              }
            }}
          >
            <ProFormText
              name="item_name"
              label="品名"
              rules={[{ required: true, message: '请输入品名' }]}
              placeholder="如：大黄鱼（野生）"
            />
            <Row gutter={16}>
              <Col span={14}>
                <ProFormDigit
                  name="quantity"
                  label="数量"
                  rules={[{ required: true, message: '请输入数量' }]}
                  min={0.01}
                  placeholder="数量"
                />
              </Col>
              <Col span={10}>
                <ProFormText
                  name="unit"
                  label="单位"
                  placeholder="如：斤/箱/件"
                />
              </Col>
            </Row>
            <ProFormSelect
              name="expected_delivery_date"
              label="期望交货日期"
              fieldProps={{
                children: null,
              }}
              // 使用 renderFormItem 放置 DatePicker
              renderFormItem={() => (
                <DatePicker
                  style={{ width: '100%' }}
                  format="YYYY-MM-DD"
                  disabledDate={(d) => d.isBefore(dayjs(), 'day')}
                />
              )}
            />
            <ProFormSelect
              name="supplier_ids"
              label="询价供应商"
              fieldProps={{ mode: 'multiple' }}
              options={supplierOptions}
              placeholder="选择询价供应商（可多选）"
            />
          </ModalForm>,
        ]}
        request={async (params) => {
          try {
            const res = await fetchRFQList({ page: params.current, size: params.pageSize });
            return { data: res.items, total: res.total, success: true };
          } catch {
            return { data: MOCK_RFQS, total: MOCK_RFQS.length, success: true };
          }
        }}
      />

      {/* 比价结果 Drawer */}
      <Drawer
        title="询价比价结果"
        open={compareDrawerOpen}
        onClose={() => setCompareDrawerOpen(false)}
        width={800}
        destroyOnClose
      >
        <Spin spinning={compareLoading}>
          {compareResult && (
            <>
              <Alert
                type="info"
                showIcon
                message={`询价品名：${compareResult.item_name}  / 数量：${compareResult.quantity} ${compareResult.unit}`}
                style={{ marginBottom: 16 }}
              />
              <Table
                dataSource={compareResult.quotes}
                columns={compareColumns}
                rowKey="supplier_id"
                pagination={false}
                size="middle"
                scroll={{ x: 700 }}
                rowClassName={(r) => r.is_recommended ? 'ant-table-row-selected' : ''}
              />
            </>
          )}
        </Spin>
      </Drawer>
    </>
  );
}

// ─── Tab3: 风险评估 ────────────────────────────────────────────────────────────

function RiskAssessmentTab() {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<RiskAssessmentResult | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const result = await fetchRiskAssessment();
      setData(result);
    } catch {
      setData(MOCK_RISK);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" tip="正在评估供应链风险..." />
      </div>
    );
  }

  if (!data) return null;

  const overallCfg = RISK_CONFIG[data.overall_risk_level];

  return (
    <div style={{ padding: '0 0 24px' }}>
      {/* 汇总指标 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card size="small" style={{ textAlign: 'center' }}>
            <Statistic
              title="整体风险等级"
              value={overallCfg.label}
              valueStyle={{ color: overallCfg.color === 'success' ? '#0F6E56' : overallCfg.color === 'warning' ? '#BA7517' : '#A32D2D' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" style={{ textAlign: 'center' }}>
            <Statistic title="高风险供应商" value={data.high_risk_count} suffix="家" valueStyle={{ color: '#A32D2D' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" style={{ textAlign: 'center' }}>
            <Statistic title="中风险供应商" value={data.medium_risk_count} suffix="家" valueStyle={{ color: '#BA7517' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" style={{ textAlign: 'center' }}>
            <Statistic title="低风险供应商" value={data.low_risk_count} suffix="家" valueStyle={{ color: '#0F6E56' }} />
          </Card>
        </Col>
      </Row>

      {/* 全局建议 */}
      {data.global_suggestions.length > 0 && (
        <Alert
          type="warning"
          showIcon
          icon={<SafetyCertificateOutlined />}
          message="供应链优化建议"
          description={
            <List
              size="small"
              dataSource={data.global_suggestions}
              renderItem={(item) => (
                <List.Item style={{ padding: '4px 0', border: 'none' }}>
                  <Text>• {item}</Text>
                </List.Item>
              )}
            />
          }
          style={{ marginBottom: 24 }}
        />
      )}

      {/* 逐个供应商风险详情 */}
      <Title level={5} style={{ marginBottom: 16 }}>供应商风险明细</Title>
      {data.items.map((item) => {
        const cfg = RISK_CONFIG[item.risk_level];
        const alertType = item.risk_level === 'high' ? 'error' : item.risk_level === 'medium' ? 'warning' : 'success';
        return (
          <Card
            key={item.supplier_id}
            size="small"
            style={{ marginBottom: 12 }}
            title={
              <Space>
                <Badge status={cfg.badgeStatus} />
                <Text strong>{item.supplier_name}</Text>
                <Tag color={cfg.color === 'success' ? 'green' : cfg.color === 'warning' ? 'orange' : 'red'}>
                  {cfg.label}
                </Tag>
                <Text type="secondary" style={{ fontSize: 12 }}>风险评分：{item.risk_score}</Text>
              </Space>
            }
          >
            {item.risk_factors.length > 0 && (
              <Alert
                type={alertType}
                showIcon={false}
                message={
                  <Space wrap>
                    <Text type="secondary" style={{ fontSize: 12 }}>风险因素：</Text>
                    {item.risk_factors.map((f) => (
                      <Tag key={f} color={alertType === 'error' ? 'red' : 'orange'}>{f}</Tag>
                    ))}
                  </Space>
                }
                style={{ marginBottom: 8, padding: '6px 12px' }}
              />
            )}
            {item.mitigation_suggestions.length > 0 && (
              <List
                size="small"
                dataSource={item.mitigation_suggestions}
                renderItem={(s) => (
                  <List.Item style={{ padding: '3px 0', border: 'none' }}>
                    <Text style={{ fontSize: 13 }}>→ {s}</Text>
                  </List.Item>
                )}
              />
            )}
            <Text type="secondary" style={{ fontSize: 11 }}>
              评估时间：{dayjs(item.last_assessed_at).format('YYYY-MM-DD HH:mm')}
            </Text>
          </Card>
        );
      })}
    </div>
  );
}

// ─── 主页面 ────────────────────────────────────────────────────────────────────

export function SupplierPortalPage() {
  const tabItems = [
    {
      key: 'archive',
      label: (
        <Space>
          <ShopOutlined />
          供应商档案
        </Space>
      ),
      children: <SupplierArchiveTab />,
    },
    {
      key: 'rfq',
      label: (
        <Space>
          <BarChartOutlined />
          询价管理(RFQ)
        </Space>
      ),
      children: <RFQTab />,
    },
    {
      key: 'risk',
      label: (
        <Space>
          <SafetyCertificateOutlined />
          风险评估
        </Space>
      ),
      children: <RiskAssessmentTab />,
    },
  ];

  return (
    <div style={{ padding: 24, background: '#F8F7F5', minHeight: '100vh' }}>
      <div style={{ marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0, color: '#2C2C2A' }}>
          供应商门户管理
        </Title>
        <Text type="secondary">供应商档案管理、询价比价、供应链风险评估</Text>
      </div>
      <div style={{ background: '#fff', borderRadius: 8, padding: '16px 24px' }}>
        <Tabs defaultActiveKey="archive" items={tabItems} size="large" />
      </div>
    </div>
  );
}
