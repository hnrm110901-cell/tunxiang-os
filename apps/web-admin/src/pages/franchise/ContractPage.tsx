/**
 * 加盟合同管理页面 — ContractPage
 * Team K5 · 加盟合同全生命周期管理
 *
 * Tab 1：合同列表    — 统计卡 + 合同 ProTable + 新建合同 Steps
 * Tab 2：到期预警    — 按到期日排序卡片 + 倒计时 + 一键续签
 * Tab 3：费用收缴    — 费用 ProTable + 催缴通知
 *
 * API 基地址: /api/v1/org
 * 降级：API 失败时返回空数组，不使用 Mock 数据
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  ConfigProvider,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  message,
  Modal,
  Popconfirm,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Steps,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import {
  AlertOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  DeleteOutlined,
  DollarOutlined,
  EditOutlined,
  ExclamationCircleOutlined,
  EyeOutlined,
  FileTextOutlined,
  PlusOutlined,
  ReloadOutlined,
  SendOutlined,
  SyncOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';
import dayjs from 'dayjs';

const { Title, Text } = Typography;

import { txFetchData } from '../../api';
import { formatPrice } from '@tx-ds/utils';

// ─── 类型定义 ──────────────────────────────────────────────────

type ContractStatus = 'draft' | 'active' | 'expiring' | 'expired' | 'terminated';
type ContractType = 'franchise' | 'renewal' | 'supplement';
type FeeStatus = 'paid' | 'partial' | 'overdue';
type FeeType = 'franchise_fee' | 'management_fee' | 'deposit';

interface ContractRecord {
  id: string;
  contract_no: string;
  franchisee_name: string;
  store_name: string;
  contract_type: ContractType;
  amount_fen: number;
  start_date: string;
  end_date: string;
  status: ContractStatus;
  terms: ContractTerm[];
}

interface ContractTerm {
  id: string;
  title: string;
  content: string;
}

interface FeeRecord {
  id: string;
  franchisee_name: string;
  fee_type: FeeType;
  amount_due_fen: number;
  amount_paid_fen: number;
  gap_fen: number;
  status: FeeStatus;
  due_date: string;
}

interface ContractStats {
  total: number;
  active: number;
  expiring: number;
  expired: number;
}

// ─── 工具函数 ──────────────────────────────────────────────────

/** @deprecated Use formatPrice from @tx-ds/utils */
const fenToYuan = (fen: number): string =>
  (fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2 });

const getDaysRemaining = (endDate: string): number =>
  dayjs(endDate).diff(dayjs(), 'day');

const statusBadgeMap: Record<ContractStatus, { status: 'default' | 'success' | 'warning' | 'error'; text: string; color?: string }> = {
  draft: { status: 'default', text: '草稿' },
  active: { status: 'success', text: '生效中' },
  expiring: { status: 'warning', text: '即将到期' },
  expired: { status: 'error', text: '已过期' },
  terminated: { status: 'default', text: '已终止', color: '#999' },
};

const contractTypeMap: Record<ContractType, { label: string; color: string }> = {
  franchise: { label: '加盟', color: 'blue' },
  renewal: { label: '续签', color: 'green' },
  supplement: { label: '补充', color: 'orange' },
};

const feeTypeMap: Record<FeeType, string> = {
  franchise_fee: '加盟费',
  management_fee: '管理费',
  deposit: '保证金',
};

const feeStatusMap: Record<FeeStatus, { color: string; text: string }> = {
  paid: { color: 'green', text: '已缴' },
  partial: { color: 'orange', text: '部分缴纳' },
  overdue: { color: 'red', text: '逾期未缴' },
};

// ─── API 封装 ──────────────────────────────────────────────────

async function fetchContracts(): Promise<ContractRecord[]> {
  try {
    const data = await txFetchData<{ items: ContractRecord[] }>('/api/v1/org/contracts');
    return data.items ?? [];
  } catch (_e: unknown) {
    return [];
  }
}

async function fetchFees(): Promise<FeeRecord[]> {
  try {
    const data = await txFetchData<{ items: FeeRecord[] }>('/api/v1/org/fees');
    return data.items ?? [];
  } catch (_e: unknown) {
    return [];
  }
}

// ─── 主组件 ────────────────────────────────────────────────────

export const ContractPage: React.FC = () => {
  const [contracts, setContracts] = useState<ContractRecord[]>([]);
  const [fees, setFees] = useState<FeeRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('list');
  const [detailDrawerOpen, setDetailDrawerOpen] = useState(false);
  const [selectedContract, setSelectedContract] = useState<ContractRecord | null>(null);
  const [newContractOpen, setNewContractOpen] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const [form] = Form.useForm();
  const [termsData, setTermsData] = useState<ContractTerm[]>([
    { id: 'new-1', title: '经营范围', content: '' },
    { id: 'new-2', title: '装修标准', content: '' },
    { id: 'new-3', title: '排他区域', content: '' },
  ]);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [contractsData, feesData] = await Promise.all([fetchContracts(), fetchFees()]);
      setContracts(contractsData);
      setFees(feesData);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // ─── 统计数据 ────────────────────────────────────────────────
  const stats: ContractStats = useMemo(() => {
    const total = contracts.length;
    const active = contracts.filter((c) => c.status === 'active').length;
    const expiring = contracts.filter((c) => {
      const days = getDaysRemaining(c.end_date);
      return c.status === 'active' && days >= 0 && days <= 30;
    }).length + contracts.filter((c) => c.status === 'expiring').length;
    const expired = contracts.filter((c) => c.status === 'expired').length;
    return { total, active, expiring, expired };
  }, [contracts]);

  // ─── 到期预警列表 ────────────────────────────────────────────
  const expiringContracts = useMemo(() => {
    return contracts
      .filter((c) => {
        const days = getDaysRemaining(c.end_date);
        return (c.status === 'active' || c.status === 'expiring') && days <= 90;
      })
      .sort((a, b) => dayjs(a.end_date).diff(dayjs(b.end_date)));
  }, [contracts]);

  // ─── 操作 ────────────────────────────────────────────────────

  const handleViewDetail = (record: ContractRecord) => {
    setSelectedContract(record);
    setDetailDrawerOpen(true);
  };

  const handleRenew = (record: ContractRecord) => {
    message.success(`已发起合同 ${record.contract_no} 的续签流程`);
  };

  const handleTerminate = (record: ContractRecord) => {
    setContracts((prev) =>
      prev.map((c) => (c.id === record.id ? { ...c, status: 'terminated' as ContractStatus } : c))
    );
    message.success(`合同 ${record.contract_no} 已终止`);
  };

  const handleCreateContract = () => {
    form.validateFields().then((values) => {
      const newContract: ContractRecord = {
        id: `c${Date.now()}`,
        contract_no: `FC-2026-${String(contracts.length + 1).padStart(3, '0')}`,
        franchisee_name: values.franchisee_name,
        store_name: values.store_name,
        contract_type: values.contract_type,
        amount_fen: (values.amount_wan ?? 0) * 10000 * 100,
        start_date: values.start_date?.format('YYYY-MM-DD') ?? '',
        end_date: values.end_date?.format('YYYY-MM-DD') ?? '',
        status: 'draft',
        terms: termsData.filter((t) => t.content.trim()),
      };
      setContracts((prev) => [newContract, ...prev]);
      setNewContractOpen(false);
      setCurrentStep(0);
      form.resetFields();
      message.success('合同创建成功');
    }).catch(() => {
      message.warning('请填写必要信息');
    });
  };

  const handleUrge = (record: FeeRecord) => {
    message.success(`已向 ${record.franchisee_name} 发送催缴通知`);
  };

  // ─── 合同列表列定义 ──────────────────────────────────────────

  const contractColumns: ProColumns<ContractRecord>[] = [
    {
      title: '合同编号',
      dataIndex: 'contract_no',
      width: 140,
      copyable: true,
    },
    {
      title: '加盟商',
      dataIndex: 'franchisee_name',
      width: 100,
    },
    {
      title: '门店',
      dataIndex: 'store_name',
      width: 130,
    },
    {
      title: '合同类型',
      dataIndex: 'contract_type',
      width: 90,
      render: (_: unknown, record: ContractRecord) => {
        const info = contractTypeMap[record.contract_type];
        return <Tag color={info.color}>{info.label}</Tag>;
      },
      filters: [
        { text: '加盟', value: 'franchise' },
        { text: '续签', value: 'renewal' },
        { text: '补充', value: 'supplement' },
      ],
      onFilter: (value, record) => record.contract_type === value,
    },
    {
      title: '金额(万)',
      dataIndex: 'amount_fen',
      width: 100,
      render: (_: unknown, record: ContractRecord) => (
        <Text strong>{(record.amount_fen / 100 / 10000).toFixed(1)}</Text>
      ),
      sorter: (a: ContractRecord, b: ContractRecord) => a.amount_fen - b.amount_fen,
    },
    {
      title: '开始日期',
      dataIndex: 'start_date',
      width: 110,
      sorter: (a: ContractRecord, b: ContractRecord) => dayjs(a.start_date).diff(dayjs(b.start_date)),
    },
    {
      title: '结束日期',
      dataIndex: 'end_date',
      width: 110,
      sorter: (a: ContractRecord, b: ContractRecord) => dayjs(a.end_date).diff(dayjs(b.end_date)),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (_: unknown, record: ContractRecord) => {
        const info = statusBadgeMap[record.status];
        return (
          <Badge
            status={info.status}
            text={<span style={{ color: info.color }}>{info.text}</span>}
          />
        );
      },
      filters: [
        { text: '草稿', value: 'draft' },
        { text: '生效中', value: 'active' },
        { text: '即将到期', value: 'expiring' },
        { text: '已过期', value: 'expired' },
        { text: '已终止', value: 'terminated' },
      ],
      onFilter: (value, record) => record.status === value,
    },
    {
      title: '操作',
      width: 200,
      valueType: 'option',
      render: (_: unknown, record: ContractRecord) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => handleViewDetail(record)}
          >
            详情
          </Button>
          {(record.status === 'active' || record.status === 'expiring' || record.status === 'expired') && (
            <Button
              type="link"
              size="small"
              icon={<SyncOutlined />}
              onClick={() => handleRenew(record)}
            >
              续签
            </Button>
          )}
          {record.status !== 'terminated' && record.status !== 'expired' && record.status !== 'draft' && (
            <Popconfirm
              title="确认终止合同？"
              description="终止后不可恢复，请确认"
              onConfirm={() => handleTerminate(record)}
              okText="确认"
              cancelText="取消"
            >
              <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                终止
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  // ─── 费用列定义 ──────────────────────────────────────────────

  const feeColumns: ProColumns<FeeRecord>[] = [
    {
      title: '加盟商',
      dataIndex: 'franchisee_name',
      width: 100,
    },
    {
      title: '费用类型',
      dataIndex: 'fee_type',
      width: 100,
      render: (_: unknown, record: FeeRecord) => feeTypeMap[record.fee_type] ?? record.fee_type,
      filters: [
        { text: '加盟费', value: 'franchise_fee' },
        { text: '管理费', value: 'management_fee' },
        { text: '保证金', value: 'deposit' },
      ],
      onFilter: (value, record) => record.fee_type === value,
    },
    {
      title: '应缴金额',
      dataIndex: 'amount_due_fen',
      width: 120,
      render: (_: unknown, record: FeeRecord) => `¥${fenToYuan(record.amount_due_fen)}`,
      sorter: (a: FeeRecord, b: FeeRecord) => a.amount_due_fen - b.amount_due_fen,
    },
    {
      title: '实缴金额',
      dataIndex: 'amount_paid_fen',
      width: 120,
      render: (_: unknown, record: FeeRecord) => `¥${fenToYuan(record.amount_paid_fen)}`,
    },
    {
      title: '差额',
      dataIndex: 'gap_fen',
      width: 110,
      render: (_: unknown, record: FeeRecord) => (
        <Text type={record.gap_fen > 0 ? 'danger' : 'success'}>
          {record.gap_fen > 0 ? `-¥${fenToYuan(record.gap_fen)}` : '¥0.00'}
        </Text>
      ),
    },
    {
      title: '缴费状态',
      dataIndex: 'status',
      width: 100,
      render: (_: unknown, record: FeeRecord) => {
        const info = feeStatusMap[record.status];
        return <Tag color={info.color}>{info.text}</Tag>;
      },
      filters: [
        { text: '已缴', value: 'paid' },
        { text: '部分缴纳', value: 'partial' },
        { text: '逾期未缴', value: 'overdue' },
      ],
      onFilter: (value, record) => record.status === value,
    },
    {
      title: '截止日期',
      dataIndex: 'due_date',
      width: 110,
    },
    {
      title: '操作',
      width: 100,
      valueType: 'option',
      render: (_: unknown, record: FeeRecord) =>
        record.status !== 'paid' ? (
          <Button
            type="link"
            size="small"
            icon={<SendOutlined />}
            onClick={() => handleUrge(record)}
          >
            催缴
          </Button>
        ) : (
          <Text type="secondary">--</Text>
        ),
    },
  ];

  // ─── 行样式 ──────────────────────────────────────────────────

  const getRowClassName = (record: ContractRecord): string => {
    if (record.status === 'expired') return 'tx-row-expired';
    if (record.status === 'expiring') return 'tx-row-expiring';
    const days = getDaysRemaining(record.end_date);
    if (record.status === 'active' && days >= 0 && days <= 30) return 'tx-row-expiring';
    return '';
  };

  // ─── 新建合同弹窗 ────────────────────────────────────────────

  const renderNewContractModal = () => (
    <Modal
      title="新建合同"
      open={newContractOpen}
      width={700}
      onCancel={() => {
        setNewContractOpen(false);
        setCurrentStep(0);
        form.resetFields();
      }}
      footer={
        <Space>
          {currentStep > 0 && (
            <Button onClick={() => setCurrentStep((s) => s - 1)}>上一步</Button>
          )}
          {currentStep < 2 && (
            <Button type="primary" onClick={() => setCurrentStep((s) => s + 1)}>
              下一步
            </Button>
          )}
          {currentStep === 2 && (
            <Button type="primary" icon={<CheckCircleOutlined />} onClick={handleCreateContract}>
              确认签署
            </Button>
          )}
        </Space>
      }
    >
      <Steps
        current={currentStep}
        size="small"
        style={{ marginBottom: 24 }}
        items={[
          { title: '基本信息' },
          { title: '条款明细' },
          { title: '确认签署' },
        ]}
      />

      {currentStep === 0 && (
        <Form form={form} layout="vertical">
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                label="加盟商"
                name="franchisee_name"
                rules={[{ required: true, message: '请输入加盟商姓名' }]}
              >
                <Input placeholder="加盟商姓名" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                label="门店"
                name="store_name"
                rules={[{ required: true, message: '请输入门店名称' }]}
              >
                <Input placeholder="门店名称" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item
                label="合同类型"
                name="contract_type"
                rules={[{ required: true, message: '请选择合同类型' }]}
              >
                <Select placeholder="选择类型">
                  <Select.Option value="franchise">加盟</Select.Option>
                  <Select.Option value="renewal">续签</Select.Option>
                  <Select.Option value="supplement">补充</Select.Option>
                </Select>
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                label="金额(万元)"
                name="amount_wan"
                rules={[{ required: true, message: '请输入金额' }]}
              >
                <InputNumber
                  min={0}
                  precision={2}
                  style={{ width: '100%' }}
                  placeholder="合同金额"
                />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                label="开始日期"
                name="start_date"
                rules={[{ required: true, message: '请选择开始日期' }]}
              >
                <Input type="date" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                label="结束日期"
                name="end_date"
                rules={[{ required: true, message: '请选择结束日期' }]}
              >
                <Input type="date" />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      )}

      {currentStep === 1 && (
        <div>
          <Text type="secondary" style={{ marginBottom: 12, display: 'block' }}>
            编辑合同条款（可修改标题和内容）
          </Text>
          {termsData.map((term, idx) => (
            <Card key={term.id} size="small" style={{ marginBottom: 8 }}>
              <Row gutter={12}>
                <Col span={6}>
                  <Input
                    value={term.title}
                    onChange={(e) => {
                      const updated = [...termsData];
                      updated[idx] = { ...updated[idx], title: e.target.value };
                      setTermsData(updated);
                    }}
                    placeholder="条款标题"
                  />
                </Col>
                <Col span={16}>
                  <Input.TextArea
                    value={term.content}
                    rows={2}
                    onChange={(e) => {
                      const updated = [...termsData];
                      updated[idx] = { ...updated[idx], content: e.target.value };
                      setTermsData(updated);
                    }}
                    placeholder="条款内容"
                  />
                </Col>
                <Col span={2}>
                  <Button
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => setTermsData((prev) => prev.filter((_, i) => i !== idx))}
                  />
                </Col>
              </Row>
            </Card>
          ))}
          <Button
            type="dashed"
            block
            icon={<PlusOutlined />}
            onClick={() =>
              setTermsData((prev) => [
                ...prev,
                { id: `new-${Date.now()}`, title: '', content: '' },
              ])
            }
          >
            添加条款
          </Button>
        </div>
      )}

      {currentStep === 2 && (
        <div>
          <Alert
            message="请确认以下合同信息无误后签署"
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
          />
          <Descriptions bordered column={2} size="small">
            <Descriptions.Item label="加盟商">
              {form.getFieldValue('franchisee_name') || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="门店">
              {form.getFieldValue('store_name') || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="合同类型">
              {contractTypeMap[form.getFieldValue('contract_type') as ContractType]?.label || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="金额">
              {form.getFieldValue('amount_wan') ? `${form.getFieldValue('amount_wan')}万元` : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="期限">
              {form.getFieldValue('start_date') || '-'} ~ {form.getFieldValue('end_date') || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="条款数">
              {termsData.filter((t) => t.content.trim()).length} 条
            </Descriptions.Item>
          </Descriptions>
        </div>
      )}
    </Modal>
  );

  // ─── 详情 Drawer ─────────────────────────────────────────────

  const renderDetailDrawer = () => (
    <Drawer
      title={`合同详情 - ${selectedContract?.contract_no ?? ''}`}
      open={detailDrawerOpen}
      onClose={() => setDetailDrawerOpen(false)}
      width={520}
    >
      {selectedContract && (
        <>
          <Descriptions bordered column={1} size="small">
            <Descriptions.Item label="合同编号">{selectedContract.contract_no}</Descriptions.Item>
            <Descriptions.Item label="加盟商">{selectedContract.franchisee_name}</Descriptions.Item>
            <Descriptions.Item label="门店">{selectedContract.store_name}</Descriptions.Item>
            <Descriptions.Item label="合同类型">
              <Tag color={contractTypeMap[selectedContract.contract_type].color}>
                {contractTypeMap[selectedContract.contract_type].label}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="金额">
              ¥{fenToYuan(selectedContract.amount_fen)}
            </Descriptions.Item>
            <Descriptions.Item label="开始日期">{selectedContract.start_date}</Descriptions.Item>
            <Descriptions.Item label="结束日期">{selectedContract.end_date}</Descriptions.Item>
            <Descriptions.Item label="状态">
              <Badge
                status={statusBadgeMap[selectedContract.status].status}
                text={statusBadgeMap[selectedContract.status].text}
              />
            </Descriptions.Item>
          </Descriptions>

          {selectedContract.terms.length > 0 && (
            <>
              <Title level={5} style={{ marginTop: 24 }}>
                合同条款
              </Title>
              {selectedContract.terms.map((term, idx) => (
                <Card key={term.id} size="small" style={{ marginBottom: 8 }}>
                  <Text strong>
                    {idx + 1}. {term.title}
                  </Text>
                  <br />
                  <Text type="secondary">{term.content}</Text>
                </Card>
              ))}
            </>
          )}
        </>
      )}
    </Drawer>
  );

  // ─── Tab2 到期预警 ───────────────────────────────────────────

  const renderExpiryAlerts = () => (
    <div>
      {expiringContracts.length === 0 ? (
        <Alert message="暂无即将到期的合同" type="success" showIcon />
      ) : (
        <Row gutter={[16, 16]}>
          {expiringContracts.map((contract) => {
            const daysLeft = getDaysRemaining(contract.end_date);
            const isUrgent = daysLeft < 7;
            const isExpired = daysLeft < 0;
            return (
              <Col xs={24} sm={12} lg={8} key={contract.id}>
                <Card
                  hoverable
                  style={{
                    borderLeft: `4px solid ${isExpired ? '#ff4d4f' : isUrgent ? '#ff4d4f' : '#faad14'}`,
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div>
                      <Text strong style={{ fontSize: 16 }}>{contract.franchisee_name}</Text>
                      <br />
                      <Text type="secondary">{contract.store_name}</Text>
                      <br />
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {contract.contract_no}
                      </Text>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div
                        style={{
                          fontSize: 28,
                          fontWeight: 700,
                          color: isExpired ? '#ff4d4f' : isUrgent ? '#ff4d4f' : '#faad14',
                          animation: isUrgent && !isExpired ? 'pulse 1.5s ease-in-out infinite' : undefined,
                        }}
                      >
                        {isExpired ? '已过期' : `${daysLeft}天`}
                      </div>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {isExpired ? `过期${Math.abs(daysLeft)}天` : '剩余'}
                      </Text>
                    </div>
                  </div>

                  <div style={{ marginTop: 12 }}>
                    <div style={{ marginBottom: 4 }}>
                      <Text type="secondary" style={{ fontSize: 12 }}>到期日：{contract.end_date}</Text>
                    </div>
                    {!isExpired && (
                      <Progress
                        percent={Math.max(0, Math.min(100, 100 - (daysLeft / 90) * 100))}
                        showInfo={false}
                        strokeColor={isUrgent ? '#ff4d4f' : '#faad14'}
                        size="small"
                      />
                    )}
                  </div>

                  <Button
                    type="primary"
                    block
                    icon={<SyncOutlined />}
                    style={{ marginTop: 12 }}
                    onClick={() => handleRenew(contract)}
                  >
                    一键发起续签
                  </Button>
                </Card>
              </Col>
            );
          })}
        </Row>
      )}
    </div>
  );

  // ─── 渲染 ────────────────────────────────────────────────────

  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#FF6B35' } }}>
      <style>{`
        .tx-row-expiring { background-color: #fff7e6 !important; }
        .tx-row-expiring:hover > td { background-color: #fff1cc !important; }
        .tx-row-expired { background-color: #fff1f0 !important; }
        .tx-row-expired:hover > td { background-color: #ffe7e6 !important; }
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>

      <div style={{ padding: 24 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
          <Title level={3} style={{ margin: 0 }}>
            <FileTextOutlined style={{ marginRight: 8 }} />
            加盟合同管理
          </Title>
          <Button icon={<ReloadOutlined />} onClick={loadData} loading={loading}>
            刷新
          </Button>
        </div>

        {/* 顶部统计卡片 */}
        <Row gutter={16} style={{ marginBottom: 24 }}>
          <Col xs={12} sm={6}>
            <Card>
              <Statistic
                title="总合同数"
                value={stats.total}
                prefix={<FileTextOutlined />}
              />
            </Card>
          </Col>
          <Col xs={12} sm={6}>
            <Card>
              <Statistic
                title="生效中"
                value={stats.active}
                prefix={<CheckCircleOutlined style={{ color: '#52c41a' }} />}
                valueStyle={{ color: '#52c41a' }}
              />
            </Card>
          </Col>
          <Col xs={12} sm={6}>
            <Card>
              <Statistic
                title="即将到期(30天)"
                value={stats.expiring}
                prefix={<ClockCircleOutlined style={{ color: '#faad14' }} />}
                valueStyle={{ color: '#faad14' }}
              />
            </Card>
          </Col>
          <Col xs={12} sm={6}>
            <Card>
              <Statistic
                title="已过期"
                value={stats.expired}
                prefix={<ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />}
                valueStyle={{ color: '#ff4d4f' }}
              />
            </Card>
          </Col>
        </Row>

        {/* Tabs */}
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: 'list',
              label: (
                <span>
                  <FileTextOutlined /> 合同列表
                </span>
              ),
              children: (
                <ProTable<ContractRecord>
                  columns={contractColumns}
                  dataSource={contracts}
                  rowKey="id"
                  loading={loading}
                  search={false}
                  dateFormatter="string"
                  pagination={{ pageSize: 10, showSizeChanger: true }}
                  rowClassName={getRowClassName}
                  toolBarRender={() => [
                    <Button
                      key="new"
                      type="primary"
                      icon={<PlusOutlined />}
                      onClick={() => setNewContractOpen(true)}
                    >
                      新建合同
                    </Button>,
                  ]}
                  headerTitle="合同列表"
                />
              ),
            },
            {
              key: 'alerts',
              label: (
                <span>
                  <AlertOutlined /> 到期预警
                  {stats.expiring > 0 && (
                    <Badge count={stats.expiring} offset={[8, -2]} size="small" />
                  )}
                </span>
              ),
              children: renderExpiryAlerts(),
            },
            {
              key: 'fees',
              label: (
                <span>
                  <DollarOutlined /> 费用收缴
                </span>
              ),
              children: (
                <ProTable<FeeRecord>
                  columns={feeColumns}
                  dataSource={fees}
                  rowKey="id"
                  loading={loading}
                  search={false}
                  dateFormatter="string"
                  pagination={{ pageSize: 10, showSizeChanger: true }}
                  headerTitle="费用收缴记录"
                />
              ),
            },
          ]}
        />

        {renderNewContractModal()}
        {renderDetailDrawer()}
      </div>
    </ConfigProvider>
  );
};

export default ContractPage;
