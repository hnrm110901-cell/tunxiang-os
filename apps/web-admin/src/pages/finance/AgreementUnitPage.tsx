/**
 * 协议单位管理
 * 路由：/finance/agreement-units
 * 5个Tab：单位档案 / 挂账还款 / 还款记录 / 预付管理 / 账龄分析
 *
 * 技术栈：Ant Design 5.x + ProComponents（Admin终端规范）
 */
import { useRef, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Col,
  DatePicker,
  Descriptions,
  Form,
  InputNumber,
  message,
  Modal,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import {
  CheckCircleOutlined,
  DollarOutlined,
  ExclamationCircleOutlined,
  MinusCircleOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  PrinterOutlined,
  ReloadOutlined,
  StopOutlined,
} from '@ant-design/icons';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormDigit,
  ProFormSelect,
  ProFormText,
  ProFormTextArea,
  ProTable,
} from '@ant-design/pro-components';
import dayjs from 'dayjs';

const { Title, Text } = Typography;

const TENANT_ID = localStorage.getItem('tenantId') ?? 'demo-tenant';
const OPERATOR_ID = localStorage.getItem('operatorId') ?? 'demo-operator';

const HEADERS = {
  'Content-Type': 'application/json',
  'X-Tenant-ID': TENANT_ID,
  'X-Operator-ID': OPERATOR_ID,
};

// ─── 类型 ──────────────────────────────────────────────────────────────────────

interface AgreementUnit {
  id: string;
  name: string;
  short_name?: string;
  contact_name?: string;
  contact_phone?: string;
  credit_limit_fen: number;
  credit_used_fen: number;
  available_credit_fen: number;
  balance_fen: number;
  total_consumed_fen: number;
  total_repaid_fen: number;
  settlement_cycle?: string;
  settlement_day?: number;
  status: string;
  notes?: string;
  created_at: string;
}

interface Transaction {
  id: string;
  type: string;
  amount_fen: number;
  order_id?: string;
  repay_method?: string;
  notes?: string;
  created_at: string;
}

// ─── 工具函数 ──────────────────────────────────────────────────────────────────

const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;
const fenToInputYuan = (fen: number) => fen / 100;
const inputYuanToFen = (yuan: number) => Math.round(yuan * 100);

const statusTag = (status: string) => {
  const map: Record<string, { color: string; label: string }> = {
    active: { color: 'green', label: '正常' },
    suspended: { color: 'orange', label: '已暂停' },
    closed: { color: 'red', label: '已关闭' },
  };
  const s = map[status] ?? { color: 'default', label: status };
  return <Tag color={s.color}>{s.label}</Tag>;
};

const txnTypeTag = (type: string) => {
  const map: Record<string, { color: string; label: string }> = {
    charge: { color: 'red', label: '挂账' },
    manual_charge: { color: 'volcano', label: '手动挂账' },
    repay: { color: 'green', label: '还款' },
  };
  const s = map[type] ?? { color: 'default', label: type };
  return <Tag color={s.color}>{s.label}</Tag>;
};

// ─── 主页面 ───────────────────────────────────────────────────────────────────

type TabKey = 'units' | 'charge-repay' | 'repay-records' | 'prepaid' | 'aging';

export function AgreementUnitPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('units');

  const tabConfig: { key: TabKey; label: string }[] = [
    { key: 'units', label: '单位档案' },
    { key: 'charge-repay', label: '挂账还款' },
    { key: 'repay-records', label: '还款记录' },
    { key: 'prepaid', label: '预付管理' },
    { key: 'aging', label: '账龄分析' },
  ];

  return (
    <div style={{ padding: 24, background: '#F8F7F5', minHeight: '100vh' }}>
      <div style={{ marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>协议单位管理</Title>
        <Text type="secondary">企业挂账 · 预付管理 · 账龄分析</Text>
      </div>

      {/* Tab Bar */}
      <div style={{
        display: 'flex',
        gap: 8,
        marginBottom: 20,
        borderBottom: '1px solid #E8E6E1',
        paddingBottom: 0,
      }}>
        {tabConfig.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            style={{
              padding: '10px 20px',
              border: 'none',
              background: 'transparent',
              cursor: 'pointer',
              fontSize: 15,
              fontWeight: activeTab === tab.key ? 700 : 400,
              color: activeTab === tab.key ? '#FF6B35' : '#5F5E5A',
              borderBottom: activeTab === tab.key ? '2px solid #FF6B35' : '2px solid transparent',
              transition: 'all 150ms',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab 内容 */}
      {activeTab === 'units' && <UnitsTab />}
      {activeTab === 'charge-repay' && <ChargeRepayTab />}
      {activeTab === 'repay-records' && <RepayRecordsTab />}
      {activeTab === 'prepaid' && <PrepaidTab />}
      {activeTab === 'aging' && <AgingTab />}
    </div>
  );
}

// ─── Tab 1: 单位档案 ──────────────────────────────────────────────────────────

function UnitsTab() {
  const actionRef = useRef<ActionType>();

  const columns: ProColumns<AgreementUnit>[] = [
    {
      title: '单位名称',
      dataIndex: 'name',
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          <Text strong>{r.name}</Text>
          {r.short_name && <Text type="secondary" style={{ fontSize: 12 }}>{r.short_name}</Text>}
        </Space>
      ),
    },
    {
      title: '联系人',
      dataIndex: 'contact_name',
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          <span>{r.contact_name ?? '-'}</span>
          {r.contact_phone && <Text type="secondary" style={{ fontSize: 12 }}>{r.contact_phone}</Text>}
        </Space>
      ),
    },
    {
      title: '授信额度',
      dataIndex: 'credit_limit_fen',
      render: (_, r) => (
        <Space direction="vertical" size={2}>
          <span>{fen2yuan(r.credit_limit_fen)}</span>
          <Progress
            percent={Math.min(100, r.credit_limit_fen > 0
              ? Math.round(r.credit_used_fen / r.credit_limit_fen * 100)
              : 0)}
            size="small"
            strokeColor={r.credit_used_fen / (r.credit_limit_fen || 1) >= 0.9 ? '#A32D2D'
              : r.credit_used_fen / (r.credit_limit_fen || 1) >= 0.7 ? '#BA7517' : '#0F6E56'}
            showInfo={false}
            style={{ width: 80 }}
          />
          <Text type="secondary" style={{ fontSize: 11 }}>
            已用 {fen2yuan(r.credit_used_fen)}
          </Text>
        </Space>
      ),
    },
    {
      title: '可用额度',
      dataIndex: 'available_credit_fen',
      render: (_, r) => (
        <Tag color={r.available_credit_fen <= 0 ? 'red'
          : r.available_credit_fen < r.credit_limit_fen * 0.2 ? 'orange' : 'green'}>
          {fen2yuan(r.available_credit_fen)}
        </Tag>
      ),
    },
    {
      title: '账户余额',
      dataIndex: 'balance_fen',
      render: (_, r) => (
        <span style={{ color: r.balance_fen >= 0 ? '#0F6E56' : '#A32D2D', fontWeight: 600 }}>
          {fen2yuan(r.balance_fen)}
        </span>
      ),
    },
    {
      title: '结算周期',
      dataIndex: 'settlement_cycle',
      valueEnum: {
        monthly: { text: '月结' },
        weekly: { text: '周结' },
        custom: { text: '自定义' },
      },
      render: (_, r) => {
        if (!r.settlement_cycle) return '-';
        const label = { monthly: '月结', weekly: '周结', custom: '自定义' }[r.settlement_cycle] ?? r.settlement_cycle;
        const detail = r.settlement_cycle === 'monthly' && r.settlement_day
          ? `每月${r.settlement_day}号` : '';
        return (
          <Space direction="vertical" size={0}>
            <span>{label}</span>
            {detail && <Text type="secondary" style={{ fontSize: 12 }}>{detail}</Text>}
          </Space>
        );
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      valueEnum: {
        active: { text: '正常', status: 'Success' },
        suspended: { text: '已暂停', status: 'Warning' },
        closed: { text: '已关闭', status: 'Error' },
      },
      render: (_, r) => statusTag(r.status),
    },
    {
      title: '操作',
      valueType: 'option',
      render: (_, r, __, action) => [
        <UnitEditModal key="edit" unit={r} onSuccess={() => action?.reload()} />,
        r.status === 'active' ? (
          <SuspendBtn key="suspend" unit={r} action="suspend"
            onSuccess={() => action?.reload()} />
        ) : r.status === 'suspended' ? (
          <SuspendBtn key="resume" unit={r} action="resume"
            onSuccess={() => action?.reload()} />
        ) : null,
      ],
    },
  ];

  return (
    <ProTable<AgreementUnit>
      actionRef={actionRef}
      columns={columns}
      rowKey="id"
      request={async (params) => {
        try {
          const qs = new URLSearchParams({
            page: String(params.current ?? 1),
            size: String(params.pageSize ?? 20),
          });
          if (params.status) qs.set('status', params.status);
          if (params.name) qs.set('keyword', params.name);
          const res = await fetch(`/api/v1/agreement-units?${qs}`, { headers: HEADERS });
          const json = await res.json();
          return { data: json.data?.items ?? [], total: json.data?.total ?? 0, success: true };
        } catch {
          return { data: [], total: 0, success: false };
        }
      }}
      search={{ labelWidth: 'auto' }}
      toolBarRender={() => [
        <CreateUnitModal key="create" onSuccess={() => actionRef.current?.reload()} />,
      ]}
      pagination={{ defaultPageSize: 20 }}
    />
  );
}

// ─── 新建协议单位 Modal ────────────────────────────────────────────────────────

function CreateUnitModal({ onSuccess }: { onSuccess: () => void }) {
  return (
    <ModalForm
      title="新建协议单位"
      trigger={
        <Button type="primary" icon={<PlusOutlined />}>新建协议单位</Button>
      }
      onFinish={async (values) => {
        try {
          const res = await fetch('/api/v1/agreement-units', {
            method: 'POST',
            headers: HEADERS,
            body: JSON.stringify({
              ...values,
              credit_limit_fen: inputYuanToFen(values.credit_limit_yuan ?? 0),
            }),
          });
          const json = await res.json();
          if (!json.ok) throw new Error(json.error?.message ?? '创建失败');
          message.success('协议单位已创建');
          onSuccess();
          return true;
        } catch (e) {
          message.error(e instanceof Error ? e.message : '创建失败');
          return false;
        }
      }}
      width={560}
    >
      <ProFormText name="name" label="单位名称" rules={[{ required: true }]} />
      <ProFormText name="short_name" label="简称" />
      <ProFormText name="contact_name" label="联系人" />
      <ProFormText name="contact_phone" label="联系电话" />
      <ProFormDigit
        name="credit_limit_yuan"
        label="授信额度（元）"
        min={0}
        fieldProps={{ precision: 2, prefix: '¥' }}
      />
      <ProFormSelect
        name="settlement_cycle"
        label="结算周期"
        options={[
          { label: '月结', value: 'monthly' },
          { label: '周结', value: 'weekly' },
          { label: '自定义', value: 'custom' },
        ]}
      />
      <ProFormDigit
        name="settlement_day"
        label="月结算日"
        min={1}
        max={31}
        fieldProps={{ precision: 0 }}
        tooltip="月结时有效，如15=每月15号"
      />
      <ProFormTextArea name="notes" label="备注" />
    </ModalForm>
  );
}

// ─── 编辑协议单位 Modal ────────────────────────────────────────────────────────

function UnitEditModal({ unit, onSuccess }: { unit: AgreementUnit; onSuccess: () => void }) {
  return (
    <ModalForm
      title={`编辑 — ${unit.name}`}
      trigger={<a>编辑</a>}
      initialValues={{
        name: unit.name,
        short_name: unit.short_name,
        contact_name: unit.contact_name,
        contact_phone: unit.contact_phone,
        credit_limit_yuan: fenToInputYuan(unit.credit_limit_fen),
        settlement_cycle: unit.settlement_cycle,
        settlement_day: unit.settlement_day,
        notes: unit.notes,
      }}
      onFinish={async (values) => {
        try {
          const res = await fetch(`/api/v1/agreement-units/${unit.id}`, {
            method: 'PUT',
            headers: HEADERS,
            body: JSON.stringify({
              ...values,
              credit_limit_fen: inputYuanToFen(values.credit_limit_yuan ?? 0),
            }),
          });
          const json = await res.json();
          if (!json.ok) throw new Error(json.error?.message ?? '更新失败');
          message.success('更新成功');
          onSuccess();
          return true;
        } catch (e) {
          message.error(e instanceof Error ? e.message : '更新失败');
          return false;
        }
      }}
      width={560}
    >
      <ProFormText name="name" label="单位名称" rules={[{ required: true }]} />
      <ProFormText name="short_name" label="简称" />
      <ProFormText name="contact_name" label="联系人" />
      <ProFormText name="contact_phone" label="联系电话" />
      <ProFormDigit
        name="credit_limit_yuan"
        label="授信额度（元）"
        min={0}
        fieldProps={{ precision: 2, prefix: '¥' }}
      />
      <ProFormSelect
        name="settlement_cycle"
        label="结算周期"
        options={[
          { label: '月结', value: 'monthly' },
          { label: '周结', value: 'weekly' },
          { label: '自定义', value: 'custom' },
        ]}
      />
      <ProFormDigit name="settlement_day" label="月结算日" min={1} max={31}
        fieldProps={{ precision: 0 }} />
      <ProFormTextArea name="notes" label="备注" />
    </ModalForm>
  );
}

// ─── 暂停/启用按钮 ────────────────────────────────────────────────────────────

function SuspendBtn({ unit, action, onSuccess }: {
  unit: AgreementUnit;
  action: 'suspend' | 'resume';
  onSuccess: () => void;
}) {
  const label = action === 'suspend' ? '暂停' : '启用';
  const icon = action === 'suspend' ? <PauseCircleOutlined /> : <PlayCircleOutlined />;

  return (
    <a
      onClick={() => {
        Modal.confirm({
          title: `确认${label}「${unit.name}」？`,
          icon: <ExclamationCircleOutlined />,
          content: action === 'suspend'
            ? '暂停后该单位不能继续挂账，但已有欠款不受影响。'
            : '启用后该单位可以继续挂账消费。',
          onOk: async () => {
            try {
              const res = await fetch(`/api/v1/agreement-units/${unit.id}/suspend`, {
                method: 'POST',
                headers: HEADERS,
                body: JSON.stringify({ action }),
              });
              const json = await res.json();
              if (!json.ok) throw new Error(json.error?.message ?? '操作失败');
              message.success(`${label}成功`);
              onSuccess();
            } catch (e) {
              message.error(e instanceof Error ? e.message : '操作失败');
            }
          },
        });
      }}
    >
      {icon} {label}
    </a>
  );
}

// ─── Tab 2: 挂账还款 ──────────────────────────────────────────────────────────

function ChargeRepayTab() {
  const [units, setUnits] = useState<AgreementUnit[]>([]);
  const [selectedUnitId, setSelectedUnitId] = useState<string | null>(null);
  const [selectedUnit, setSelectedUnit] = useState<AgreementUnit | null>(null);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [txnTotal, setTxnTotal] = useState(0);
  const [txnPage, setTxnPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [chargeModal, setChargeModal] = useState(false);
  const [repayModal, setRepayModal] = useState(false);

  // 加载单位列表（用于下拉）
  const loadUnits = async () => {
    try {
      const res = await fetch('/api/v1/agreement-units?size=200&status=active', { headers: HEADERS });
      const json = await res.json();
      setUnits(json.data?.items ?? []);
    } catch {
      setUnits([]);
    }
  };

  // 加载选中单位详情+流水
  const loadUnitDetail = async (unitId: string, page = 1) => {
    setLoading(true);
    try {
      const [detailRes, txnRes] = await Promise.all([
        fetch(`/api/v1/agreement-units/${unitId}`, { headers: HEADERS }),
        fetch(`/api/v1/agreement-units/${unitId}/transactions?page=${page}&size=20`, { headers: HEADERS }),
      ]);
      const detail = await detailRes.json();
      const txns = await txnRes.json();
      if (detail.ok) setSelectedUnit(detail.data);
      if (txns.ok) {
        setTransactions(txns.data?.items ?? []);
        setTxnTotal(txns.data?.total ?? 0);
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  useState(() => { loadUnits(); });

  const handleUnitSelect = (unitId: string) => {
    setSelectedUnitId(unitId);
    setTxnPage(1);
    loadUnitDetail(unitId, 1);
  };

  return (
    <Row gutter={24}>
      {/* 左侧：选择单位 */}
      <Col span={8}>
        <Card title="选择协议单位" size="small">
          <Select
            placeholder="搜索或选择协议单位..."
            showSearch
            filterOption={(input, option) =>
              String(option?.label ?? '').toLowerCase().includes(input.toLowerCase())}
            style={{ width: '100%', marginBottom: 16 }}
            value={selectedUnitId}
            onChange={handleUnitSelect}
            options={units.map((u) => ({
              label: u.name,
              value: u.id,
            }))}
          />

          {/* 单位余额卡片 */}
          {selectedUnit && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <Card size="small" style={{ background: '#F8F7F5' }}>
                <Statistic
                  title="当前余额"
                  value={fenToInputYuan(selectedUnit.balance_fen)}
                  prefix="¥"
                  precision={2}
                  valueStyle={{ color: selectedUnit.balance_fen >= 0 ? '#0F6E56' : '#A32D2D' }}
                />
              </Card>
              <Card size="small" style={{ background: '#F8F7F5' }}>
                <Statistic
                  title="已用授信 / 总授信"
                  value={fenToInputYuan(selectedUnit.credit_used_fen)}
                  suffix={`/ ¥${fenToInputYuan(selectedUnit.credit_limit_fen).toFixed(2)}`}
                  prefix="¥"
                  precision={2}
                  valueStyle={{ color: '#FF6B35' }}
                />
                <Progress
                  percent={Math.min(100, selectedUnit.credit_limit_fen > 0
                    ? Math.round(selectedUnit.credit_used_fen / selectedUnit.credit_limit_fen * 100)
                    : 0)}
                  strokeColor={
                    selectedUnit.credit_used_fen / (selectedUnit.credit_limit_fen || 1) >= 0.9 ? '#A32D2D'
                    : '#FF6B35'
                  }
                  style={{ marginTop: 8 }}
                />
              </Card>

              <Row gutter={8}>
                <Col span={12}>
                  <Button
                    type="primary"
                    icon={<MinusCircleOutlined />}
                    block
                    onClick={() => setChargeModal(true)}
                  >
                    手动挂账
                  </Button>
                </Col>
                <Col span={12}>
                  <Button
                    type="default"
                    icon={<DollarOutlined />}
                    block
                    style={{ borderColor: '#0F6E56', color: '#0F6E56' }}
                    onClick={() => setRepayModal(true)}
                  >
                    还款
                  </Button>
                </Col>
              </Row>
            </div>
          )}
        </Card>
      </Col>

      {/* 右侧：流水列表 */}
      <Col span={16}>
        <Card
          title={selectedUnit ? `「${selectedUnit.name}」挂账/还款流水` : '请先选择协议单位'}
          size="small"
          extra={selectedUnit && (
            <Button
              size="small"
              icon={<ReloadOutlined />}
              onClick={() => loadUnitDetail(selectedUnitId!, txnPage)}
            >
              刷新
            </Button>
          )}
        >
          {!selectedUnit ? (
            <div style={{ textAlign: 'center', padding: 60, color: '#B4B2A9' }}>
              请在左侧选择协议单位
            </div>
          ) : (
            <ProTable<Transaction>
              dataSource={transactions}
              loading={loading}
              rowKey="id"
              search={false}
              toolBarRender={false}
              pagination={{
                current: txnPage,
                total: txnTotal,
                pageSize: 20,
                onChange: (page) => {
                  setTxnPage(page);
                  loadUnitDetail(selectedUnitId!, page);
                },
              }}
              columns={[
                {
                  title: '时间',
                  dataIndex: 'created_at',
                  render: (v) => dayjs(String(v)).format('MM-DD HH:mm'),
                },
                { title: '类型', dataIndex: 'type', render: (v) => txnTypeTag(String(v)) },
                {
                  title: '金额',
                  dataIndex: 'amount_fen',
                  render: (v) => {
                    const val = Number(v);
                    return (
                      <span style={{ color: val > 0 ? '#A32D2D' : '#0F6E56', fontWeight: 600 }}>
                        {val > 0 ? '+' : ''}{fen2yuan(val)}
                      </span>
                    );
                  },
                },
                {
                  title: '还款方式',
                  dataIndex: 'repay_method',
                  render: (v) => {
                    if (!v) return '-';
                    const m: Record<string, string> = { cash: '现金', transfer: '转账', wechat: '微信' };
                    return m[String(v)] ?? String(v);
                  },
                },
                { title: '备注', dataIndex: 'notes', render: (v) => v ?? '-' },
              ]}
            />
          )}
        </Card>
      </Col>

      {/* 手动挂账 Modal */}
      {selectedUnit && (
        <ChargeModal
          open={chargeModal}
          unit={selectedUnit}
          onClose={() => setChargeModal(false)}
          onSuccess={() => {
            setChargeModal(false);
            loadUnitDetail(selectedUnitId!, txnPage);
          }}
        />
      )}

      {/* 还款 Modal */}
      {selectedUnit && (
        <RepayModal
          open={repayModal}
          unit={selectedUnit}
          onClose={() => setRepayModal(false)}
          onSuccess={() => {
            setRepayModal(false);
            loadUnitDetail(selectedUnitId!, txnPage);
          }}
        />
      )}
    </Row>
  );
}

// ─── 手动挂账 Modal ────────────────────────────────────────────────────────────

function ChargeModal({ open, unit, onClose, onSuccess }: {
  open: boolean;
  unit: AgreementUnit;
  onClose: () => void;
  onSuccess: (voucher?: string) => void;
}) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [voucherText, setVoucherText] = useState<string | null>(null);

  const handleOk = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);
      const res = await fetch(`/api/v1/agreement-units/${unit.id}/charge`, {
        method: 'POST',
        headers: HEADERS,
        body: JSON.stringify({
          amount_fen: inputYuanToFen(values.amount_yuan),
          notes: values.notes,
          print_voucher: values.print_voucher ?? false,
        }),
      });
      const json = await res.json();
      if (!json.ok) throw new Error(json.error?.message ?? '挂账失败');
      message.success('挂账成功');
      if (json.data?.voucher) {
        setVoucherText(json.data.voucher);
      } else {
        onSuccess();
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : '挂账失败');
    } finally {
      setLoading(false);
    }
  };

  if (voucherText) {
    return (
      <Modal open title="挂账凭证" onOk={() => { setVoucherText(null); onSuccess(voucherText); }}
        onCancel={() => { setVoucherText(null); onSuccess(voucherText); }}>
        <pre style={{ background: '#F8F7F5', padding: 16, borderRadius: 8,
          fontFamily: 'monospace', fontSize: 13 }}>{voucherText}</pre>
      </Modal>
    );
  }

  return (
    <Modal
      open={open}
      title={`手动挂账 — ${unit.name}`}
      onOk={handleOk}
      onCancel={onClose}
      confirmLoading={loading}
      okText="确认挂账"
    >
      <Alert
        style={{ marginBottom: 16 }}
        type="info"
        message={`可用授信额度：${fen2yuan(unit.available_credit_fen)}`}
        showIcon
      />
      <Form form={form} layout="vertical">
        <Form.Item name="amount_yuan" label="挂账金额（元）" rules={[
          { required: true, message: '请输入挂账金额' },
          {
            validator: (_, v) => {
              if (v && inputYuanToFen(v) > unit.available_credit_fen) {
                return Promise.reject(`超出可用授信额度 ${fen2yuan(unit.available_credit_fen)}`);
              }
              return Promise.resolve();
            },
          },
        ]}>
          <InputNumber
            style={{ width: '100%' }} min={0.01} precision={2}
            prefix="¥" placeholder="0.00"
          />
        </Form.Item>
        <Form.Item name="notes" label="备注">
          <input
            style={{ width: '100%', padding: '8px 12px', border: '1px solid #d9d9d9', borderRadius: 6 }}
            placeholder="备注说明（可选）"
          />
        </Form.Item>
        <Form.Item name="print_voucher" valuePropName="checked">
          <Checkbox><PrinterOutlined /> 打印凭证</Checkbox>
        </Form.Item>
      </Form>
    </Modal>
  );
}

// ─── 还款 Modal ───────────────────────────────────────────────────────────────

function RepayModal({ open, unit, onClose, onSuccess }: {
  open: boolean;
  unit: AgreementUnit;
  onClose: () => void;
  onSuccess: (voucher?: string) => void;
}) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [repayMode, setRepayMode] = useState<'normal' | 'bulk'>('normal');
  const [voucherText, setVoucherText] = useState<string | null>(null);

  const handleOk = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);
      const body: Record<string, unknown> = {
        repay_mode: repayMode,
        repay_method: values.repay_method ?? 'cash',
        notes: values.notes,
        print_voucher: values.print_voucher ?? false,
      };
      if (repayMode === 'normal') {
        body.amount_fen = inputYuanToFen(values.amount_yuan);
      }

      const res = await fetch(`/api/v1/agreement-units/${unit.id}/repay`, {
        method: 'POST',
        headers: HEADERS,
        body: JSON.stringify(body),
      });
      const json = await res.json();
      if (!json.ok) throw new Error(json.error?.message ?? '还款失败');
      message.success('还款成功');
      if (json.data?.voucher) {
        setVoucherText(json.data.voucher);
      } else {
        onSuccess();
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : '还款失败');
    } finally {
      setLoading(false);
    }
  };

  if (voucherText) {
    return (
      <Modal open title="还款凭证" onOk={() => { setVoucherText(null); onSuccess(voucherText); }}
        onCancel={() => { setVoucherText(null); onSuccess(voucherText); }}>
        <pre style={{ background: '#F8F7F5', padding: 16, borderRadius: 8,
          fontFamily: 'monospace', fontSize: 13 }}>{voucherText}</pre>
      </Modal>
    );
  }

  return (
    <Modal
      open={open}
      title={`还款 — ${unit.name}`}
      onOk={handleOk}
      onCancel={onClose}
      confirmLoading={loading}
      okText="确认还款"
    >
      <Descriptions column={1} size="small" style={{ marginBottom: 16 }}>
        <Descriptions.Item label="当前欠款">
          <span style={{ color: '#A32D2D', fontWeight: 600 }}>
            {fen2yuan(unit.credit_used_fen)}
          </span>
        </Descriptions.Item>
      </Descriptions>

      <Form form={form} layout="vertical"
        initialValues={{ repay_method: 'cash' }}>
        <Form.Item label="还款方式">
          <Space>
            <Button
              type={repayMode === 'normal' ? 'primary' : 'default'}
              onClick={() => setRepayMode('normal')}
            >
              普通还款
            </Button>
            <Button
              type={repayMode === 'bulk' ? 'primary' : 'default'}
              onClick={() => setRepayMode('bulk')}
              danger={repayMode === 'bulk'}
            >
              一键结清（{fen2yuan(unit.credit_used_fen)}）
            </Button>
          </Space>
        </Form.Item>

        {repayMode === 'normal' && (
          <Form.Item name="amount_yuan" label="还款金额（元）"
            rules={[{ required: true, message: '请输入还款金额' }]}>
            <InputNumber
              style={{ width: '100%' }} min={0.01} precision={2}
              prefix="¥" placeholder="0.00"
            />
          </Form.Item>
        )}

        <Form.Item name="repay_method" label="还款方式">
          <Select
            options={[
              { label: '现金', value: 'cash' },
              { label: '转账', value: 'transfer' },
              { label: '微信支付', value: 'wechat' },
            ]}
          />
        </Form.Item>

        <Form.Item name="notes" label="备注">
          <input
            style={{ width: '100%', padding: '8px 12px', border: '1px solid #d9d9d9', borderRadius: 6 }}
            placeholder="备注说明（可选）"
          />
        </Form.Item>

        <Form.Item name="print_voucher" valuePropName="checked">
          <Checkbox><PrinterOutlined /> 打印还款凭证</Checkbox>
        </Form.Item>
      </Form>
    </Modal>
  );
}

// ─── Tab 3: 还款记录 ──────────────────────────────────────────────────────────

function RepayRecordsTab() {
  const actionRef = useRef<ActionType>();

  const columns: ProColumns<Transaction & { unit_name?: string }>[] = [
    {
      title: '协议单位',
      dataIndex: 'unit_name',
      render: (v) => v ?? '-',
    },
    {
      title: '时间',
      dataIndex: 'created_at',
      valueType: 'dateTimeRange',
      fieldProps: { placeholder: ['开始日期', '结束日期'] },
      render: (_, r) => dayjs(r.created_at).format('YYYY-MM-DD HH:mm'),
      search: {
        transform: (value: [string, string]) => ({
          start_date: value[0],
          end_date: value[1],
        }),
      },
    },
    {
      title: '还款金额',
      dataIndex: 'amount_fen',
      search: false,
      render: (_, r) => (
        <span style={{ color: '#0F6E56', fontWeight: 600 }}>
          {fen2yuan(Math.abs(r.amount_fen))}
        </span>
      ),
    },
    {
      title: '还款方式',
      dataIndex: 'repay_method',
      search: false,
      render: (v) => {
        const m: Record<string, string> = { cash: '现金', transfer: '转账', wechat: '微信' };
        return m[String(v)] ?? String(v ?? '-');
      },
    },
    { title: '备注', dataIndex: 'notes', search: false, render: (v) => v ?? '-' },
    {
      title: '操作',
      valueType: 'option',
      render: (_, r) => [
        <Tooltip key="reprint" title="补打凭证">
          <Button
            size="small"
            icon={<PrinterOutlined />}
            onClick={() => {
              const voucher = `还款凭证\n单位: -\n金额: ${fen2yuan(Math.abs(r.amount_fen))}\n流水号: ${r.id.slice(0, 8)}...\n时间: ${dayjs(r.created_at).format('YYYY-MM-DD HH:mm')}`;
              Modal.info({ title: '还款凭证', content: <pre style={{ fontFamily: 'monospace' }}>{voucher}</pre> });
            }}
          >
            补打
          </Button>
        </Tooltip>,
      ],
    },
  ];

  return (
    <ProTable<Transaction & { unit_name?: string }>
      actionRef={actionRef}
      columns={columns}
      rowKey="id"
      request={async (params) => {
        // 获取所有单位的还款流水（需要从所有单位中聚合）
        try {
          const unitsRes = await fetch('/api/v1/agreement-units?size=200', { headers: HEADERS });
          const unitsJson = await unitsRes.json();
          const units: AgreementUnit[] = unitsJson.data?.items ?? [];

          const allTxns: (Transaction & { unit_name: string })[] = [];
          await Promise.all(
            units.map(async (u) => {
              const qs = new URLSearchParams({ type: 'repay', size: '200' });
              if (params.start_date) qs.set('start_date', params.start_date);
              if (params.end_date) qs.set('end_date', params.end_date);
              const res = await fetch(
                `/api/v1/agreement-units/${u.id}/transactions?${qs}`,
                { headers: HEADERS },
              );
              const json = await res.json();
              const items = (json.data?.items ?? []) as Transaction[];
              items.forEach((t) => allTxns.push({ ...t, unit_name: u.name }));
            }),
          );

          allTxns.sort((a, b) =>
            new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

          return { data: allTxns, total: allTxns.length, success: true };
        } catch {
          return { data: [], total: 0, success: false };
        }
      }}
      search={{ labelWidth: 'auto' }}
      pagination={{ defaultPageSize: 20 }}
    />
  );
}

// ─── Tab 4: 预付管理 ──────────────────────────────────────────────────────────

function PrepaidTab() {
  const [units, setUnits] = useState<(AgreementUnit & { prepaid_balance_fen?: number })[]>([]);
  const [loading, setLoading] = useState(true);
  const [rechargeModal, setRechargeModal] = useState<AgreementUnit | null>(null);
  const [refundModal, setRefundModal] = useState<AgreementUnit | null>(null);

  const loadUnits = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/v1/agreement-units?size=200', { headers: HEADERS });
      const json = await res.json();
      setUnits(json.data?.items ?? []);
    } catch {
      setUnits([]);
    } finally {
      setLoading(false);
    }
  };

  useState(() => { loadUnits(); });

  const columns: ProColumns<AgreementUnit>[] = [
    { title: '单位名称', dataIndex: 'name' },
    { title: '联系人', dataIndex: 'contact_name', render: (v) => v ?? '-' },
    {
      title: '账户余额',
      dataIndex: 'balance_fen',
      render: (_, r) => (
        <span style={{
          fontWeight: 600,
          color: r.balance_fen > 0 ? '#0F6E56' : r.balance_fen < 0 ? '#A32D2D' : '#5F5E5A',
        }}>
          {fen2yuan(r.balance_fen)}
        </span>
      ),
    },
    {
      title: '操作',
      valueType: 'option',
      render: (_, r) => [
        <Button key="recharge" size="small" type="primary"
          onClick={() => setRechargeModal(r)}>
          充值
        </Button>,
        <Button key="refund" size="small" danger
          disabled={r.balance_fen <= 0}
          onClick={() => setRefundModal(r)}>
          退款
        </Button>,
      ],
    },
  ];

  return (
    <>
      <ProTable<AgreementUnit>
        dataSource={units}
        loading={loading}
        columns={columns}
        rowKey="id"
        search={false}
        toolBarRender={() => [
          <Button key="refresh" icon={<ReloadOutlined />} onClick={loadUnits}>
            刷新
          </Button>,
        ]}
        pagination={{ defaultPageSize: 20 }}
      />

      {/* 充值 Modal */}
      {rechargeModal && (
        <PrepaidActionModal
          type="recharge"
          unit={rechargeModal}
          onClose={() => setRechargeModal(null)}
          onSuccess={() => { setRechargeModal(null); loadUnits(); }}
        />
      )}

      {/* 退款 Modal */}
      {refundModal && (
        <PrepaidActionModal
          type="refund"
          unit={refundModal}
          onClose={() => setRefundModal(null)}
          onSuccess={() => { setRefundModal(null); loadUnits(); }}
        />
      )}
    </>
  );
}

function PrepaidActionModal({ type, unit, onClose, onSuccess }: {
  type: 'recharge' | 'refund';
  unit: AgreementUnit;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const label = type === 'recharge' ? '充值' : '退款';

  const handleOk = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);
      const res = await fetch(`/api/v1/agreement-units/${unit.id}/prepaid/${type}`, {
        method: 'POST',
        headers: HEADERS,
        body: JSON.stringify({
          amount_fen: inputYuanToFen(values.amount_yuan),
          notes: values.notes,
        }),
      });
      const json = await res.json();
      if (!json.ok) throw new Error(json.error?.message ?? `${label}失败`);
      message.success(`${label}成功`);
      onSuccess();
    } catch (e) {
      message.error(e instanceof Error ? e.message : `${label}失败`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal open title={`预付${label} — ${unit.name}`} onOk={handleOk}
      onCancel={onClose} confirmLoading={loading} okText={`确认${label}`}>
      <Alert
        style={{ marginBottom: 16 }}
        type={type === 'recharge' ? 'info' : 'warning'}
        message={`当前余额：${fen2yuan(unit.balance_fen)}`}
        showIcon
      />
      <Form form={form} layout="vertical">
        <Form.Item name="amount_yuan" label={`${label}金额（元）`}
          rules={[
            { required: true, message: `请输入${label}金额` },
            type === 'refund' ? {
              validator: (_, v) => {
                if (v && inputYuanToFen(v) > unit.balance_fen) {
                  return Promise.reject(`余额不足，最多可退 ${fen2yuan(unit.balance_fen)}`);
                }
                return Promise.resolve();
              },
            } : {},
          ]}>
          <InputNumber style={{ width: '100%' }} min={0.01} precision={2}
            prefix="¥" placeholder="0.00" />
        </Form.Item>
        <Form.Item name="notes" label="备注">
          <input
            style={{ width: '100%', padding: '8px 12px', border: '1px solid #d9d9d9', borderRadius: 6 }}
            placeholder="备注（可选）"
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}

// ─── Tab 5: 账龄分析 ──────────────────────────────────────────────────────────

interface AgingItem {
  unit_id: string;
  unit_name: string;
  contact_name?: string;
  total_owed_fen: number;
  aged_0_30_fen: number;
  aged_31_60_fen: number;
  aged_61_90_fen: number;
  aged_90plus_fen: number;
}

function AgingTab() {
  // 账龄越长颜色越深（红色梯度）
  const agingColor = (fen: number, severity: 'low' | 'medium' | 'high' | 'critical') => {
    if (fen <= 0) return '#B4B2A9';
    const colors = {
      low: '#BA7517',
      medium: '#C84B2F',
      high: '#A32D2D',
      critical: '#6B1A1A',
    };
    return colors[severity];
  };

  const columns: ProColumns<AgingItem>[] = [
    { title: '单位名称', dataIndex: 'unit_name', fixed: 'left' as const },
    { title: '联系人', dataIndex: 'contact_name', render: (v) => v ?? '-' },
    {
      title: '总欠款',
      dataIndex: 'total_owed_fen',
      render: (_, r) => (
        <span style={{ fontWeight: 700, color: r.total_owed_fen > 0 ? '#A32D2D' : '#5F5E5A' }}>
          {fen2yuan(r.total_owed_fen)}
        </span>
      ),
      sorter: (a, b) => a.total_owed_fen - b.total_owed_fen,
    },
    {
      title: '0-30天',
      dataIndex: 'aged_0_30_fen',
      render: (_, r) => (
        <span style={{ color: agingColor(r.aged_0_30_fen, 'low') }}>
          {r.aged_0_30_fen > 0 ? fen2yuan(r.aged_0_30_fen) : '-'}
        </span>
      ),
    },
    {
      title: '31-60天',
      dataIndex: 'aged_31_60_fen',
      render: (_, r) => (
        <span style={{ color: agingColor(r.aged_31_60_fen, 'medium'), fontWeight: r.aged_31_60_fen > 0 ? 600 : 400 }}>
          {r.aged_31_60_fen > 0 ? fen2yuan(r.aged_31_60_fen) : '-'}
        </span>
      ),
    },
    {
      title: '61-90天',
      dataIndex: 'aged_61_90_fen',
      render: (_, r) => (
        <span style={{ color: agingColor(r.aged_61_90_fen, 'high'), fontWeight: r.aged_61_90_fen > 0 ? 700 : 400 }}>
          {r.aged_61_90_fen > 0 ? fen2yuan(r.aged_61_90_fen) : '-'}
        </span>
      ),
    },
    {
      title: '90天+',
      dataIndex: 'aged_90plus_fen',
      render: (_, r) => (
        <span style={{
          color: agingColor(r.aged_90plus_fen, 'critical'),
          fontWeight: r.aged_90plus_fen > 0 ? 700 : 400,
          background: r.aged_90plus_fen > 0 ? '#FFF3F3' : 'transparent',
          padding: r.aged_90plus_fen > 0 ? '2px 6px' : undefined,
          borderRadius: 4,
        }}>
          {r.aged_90plus_fen > 0 ? (
            <Space>
              <StopOutlined />
              {fen2yuan(r.aged_90plus_fen)}
            </Space>
          ) : '-'}
        </span>
      ),
      sorter: (a, b) => a.aged_90plus_fen - b.aged_90plus_fen,
    },
    {
      title: '操作',
      valueType: 'option',
      render: (_, r) => [
        r.total_owed_fen > 0 && (
          <Badge key="overdue" dot color="red">
            <CheckCircleOutlined
              style={{ color: '#0F6E56', cursor: 'pointer', fontSize: 16 }}
              title="去还款"
            />
          </Badge>
        ),
      ],
    },
  ];

  return (
    <>
      <Alert
        style={{ marginBottom: 16 }}
        type="warning"
        icon={<ExclamationCircleOutlined />}
        showIcon
        message="账龄分析说明"
        description="账龄越长，颜色越深。90天以上欠款（红底标注）建议优先催收。数据实时计算，每次打开刷新。"
      />
      <ProTable<AgingItem>
        rowKey="unit_id"
        request={async () => {
          try {
            const res = await fetch('/api/v1/agreement-units/report/aging', { headers: HEADERS });
            const json = await res.json();
            return { data: json.data?.items ?? [], total: json.data?.items?.length ?? 0, success: true };
          } catch {
            return { data: [], total: 0, success: false };
          }
        }}
        columns={columns}
        search={false}
        pagination={{ defaultPageSize: 20 }}
        scroll={{ x: 900 }}
        summary={(data) => {
          const totalOwed = data.reduce((s, r) => s + r.total_owed_fen, 0);
          const total90 = data.reduce((s, r) => s + r.aged_90plus_fen, 0);
          return (
            <ProTable.Summary fixed>
              <ProTable.Summary.Row>
                <ProTable.Summary.Cell index={0} colSpan={2}>
                  <Text strong>合计（{data.length} 家单位）</Text>
                </ProTable.Summary.Cell>
                <ProTable.Summary.Cell index={2}>
                  <Text strong style={{ color: '#A32D2D' }}>{fen2yuan(totalOwed)}</Text>
                </ProTable.Summary.Cell>
                <ProTable.Summary.Cell index={3} />
                <ProTable.Summary.Cell index={4} />
                <ProTable.Summary.Cell index={5} />
                <ProTable.Summary.Cell index={6}>
                  {total90 > 0 && (
                    <Text strong style={{ color: '#6B1A1A' }}>{fen2yuan(total90)}</Text>
                  )}
                </ProTable.Summary.Cell>
                <ProTable.Summary.Cell index={7} />
              </ProTable.Summary.Row>
            </ProTable.Summary>
          );
        }}
      />
    </>
  );
}

export default AgreementUnitPage;
