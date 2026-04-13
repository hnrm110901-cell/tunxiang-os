/**
 * FranchiseContractPage — 加盟商合同+收费管理
 *
 * Tab 1: 合同管理
 *   - 到期预警横幅（30天内到期）
 *   - ProTable：合同列表，剩余天数颜色编码
 *   - 新建合同 ModalForm / 发送到期提醒
 *
 * Tab 2: 收费管理
 *   - 本季收款统计卡片（应收/已收/未收/逾期）
 *   - ProTable：收费记录，状态 Tag
 *   - 标记付款弹窗
 *
 * 终端：Admin（总部管理后台）
 * 技术栈：Ant Design 5.x + ProComponents
 */
import React, { useRef, useState, useCallback } from 'react';
import {
  Alert,
  Button,
  Col,
  Form,
  Input,
  InputNumber,
  message,
  Modal,
  Row,
  Select,
  Space,
  Statistic,
  Tag,
  Tabs,
  Tooltip,
  Typography,
} from 'antd';
import {
  BellOutlined,
  DollarOutlined,
  ExclamationCircleOutlined,
  FileAddOutlined,
  PlusOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import {
  ActionType,
  ModalForm,
  ProFormDatePicker,
  ProFormDigit,
  ProFormSelect,
  ProFormText,
  ProFormTextArea,
  ProTable,
} from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';
import { formatPrice } from '@tx-ds/utils';

const { Text } = Typography;

// ─── API 基础配置 ──────────────────────────────────────────────────────────────

const API_BASE = '/api/v1/org/franchise';
const TENANT_ID = localStorage.getItem('tenantId') || 'demo-tenant';

async function apiFetch<T>(
  url: string,
  options?: RequestInit,
): Promise<T> {
  const resp = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': TENANT_ID,
      ...(options?.headers ?? {}),
    },
  });
  if (!resp.ok) {
    const errBody = await resp.json().catch(() => ({}));
    throw new Error(errBody?.error?.message ?? `HTTP ${resp.status}`);
  }
  return resp.json();
}

// ─── 类型定义 ──────────────────────────────────────────────────────────────────

interface FranchiseContract {
  id: string;
  contract_no: string;
  contract_type: 'initial' | 'renewal' | 'amendment';
  franchisee_id: string;
  franchisee_name: string;
  sign_date: string;
  start_date: string;
  end_date: string;
  contract_amount_fen: number;
  file_url: string | null;
  status: 'active' | 'expired' | 'terminated';
  alert_days_before: number;
  days_to_expire: number;
  notes: string | null;
  created_at: string;
}

interface FeeRecord {
  id: string;
  franchisee_id: string;
  franchisee_name: string;
  contract_id: string | null;
  fee_type: 'joining_fee' | 'royalty' | 'management_fee' | 'marketing_fee' | 'deposit';
  period_start: string | null;
  period_end: string | null;
  amount_fen: number;
  paid_fen: number;
  due_date: string | null;
  status: 'unpaid' | 'partial' | 'paid' | 'overdue';
  receipt_no: string | null;
  notes: string | null;
  created_at: string;
}

interface FeeStats {
  total_amount_fen: number;
  total_paid_fen: number;
  total_unpaid_fen: number;
  total_overdue_fen: number;
  by_type: Array<{ fee_type: string; amount_fen: number; paid_fen: number; overdue_fen: number }>;
}

// ─── 辅助函数 ──────────────────────────────────────────────────────────────────

/** @deprecated Use formatPrice from @tx-ds/utils */
const fenToYuan = (fen: number): string => (fen / 100).toFixed(2);

const CONTRACT_TYPE_MAP: Record<string, string> = {
  initial: '首签',
  renewal: '续签',
  amendment: '补充协议',
};

const FEE_TYPE_MAP: Record<string, string> = {
  joining_fee: '加盟费',
  royalty: '提成',
  management_fee: '管理费',
  marketing_fee: '市场费',
  deposit: '保证金',
};

const CONTRACT_STATUS_COLOR: Record<string, string> = {
  active: 'success',
  expired: 'default',
  terminated: 'error',
};

const CONTRACT_STATUS_LABEL: Record<string, string> = {
  active: '生效中',
  expired: '已到期',
  terminated: '已终止',
};

const FEE_STATUS_COLOR: Record<string, string> = {
  unpaid: 'default',
  partial: 'processing',
  paid: 'success',
  overdue: 'error',
};

const FEE_STATUS_LABEL: Record<string, string> = {
  unpaid: '未付',
  partial: '部分付',
  paid: '已付',
  overdue: '逾期',
};

function DaysToExpireTag({ days }: { days: number }) {
  if (days < 0) {
    return <Tag color="error">已过期 {Math.abs(days)} 天</Tag>;
  }
  if (days <= 30) {
    return <Tag color="error" icon={<WarningOutlined />}>{days} 天</Tag>;
  }
  if (days <= 90) {
    return <Tag color="warning">{days} 天</Tag>;
  }
  return <Tag color="success">{days} 天</Tag>;
}

// ─── Tab 1: 合同管理 ───────────────────────────────────────────────────────────

function ContractTab() {
  const actionRef = useRef<ActionType>();
  const [expiringCount, setExpiringCount] = useState<number>(0);
  const [alertVisible, setAlertVisible] = useState<boolean>(true);
  const [createOpen, setCreateOpen] = useState<boolean>(false);
  const [createForm] = Form.useForm();
  const [alertLoading, setAlertLoading] = useState<string | null>(null);

  const handleSendAlert = useCallback(async (record: FranchiseContract) => {
    setAlertLoading(record.id);
    try {
      await apiFetch(`${API_BASE}/contracts/${record.id}/send-alert`, { method: 'POST' });
      message.success(`已向「${record.franchisee_name}」发送到期提醒`);
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : '发送失败';
      message.error(errMsg);
    } finally {
      setAlertLoading(null);
    }
  }, []);

  const columns: ProColumns<FranchiseContract>[] = [
    {
      title: '合同编号',
      dataIndex: 'contract_no',
      width: 160,
      render: (val) => <Text copyable style={{ fontFamily: 'monospace', fontSize: 12 }}>{val as string}</Text>,
    },
    {
      title: '加盟商',
      dataIndex: 'franchisee_name',
      width: 140,
    },
    {
      title: '合同类型',
      dataIndex: 'contract_type',
      width: 100,
      valueEnum: {
        initial: { text: '首签' },
        renewal: { text: '续签' },
        amendment: { text: '补充协议' },
      },
      render: (_, r) => <Tag>{CONTRACT_TYPE_MAP[r.contract_type] ?? r.contract_type}</Tag>,
    },
    {
      title: '签署日期',
      dataIndex: 'sign_date',
      width: 110,
      search: false,
    },
    {
      title: '到期日期',
      dataIndex: 'end_date',
      width: 110,
      search: false,
    },
    {
      title: '剩余天数',
      dataIndex: 'days_to_expire',
      width: 100,
      search: false,
      sorter: (a, b) => a.days_to_expire - b.days_to_expire,
      render: (_, r) => <DaysToExpireTag days={r.days_to_expire} />,
    },
    {
      title: '合同金额',
      dataIndex: 'contract_amount_fen',
      width: 120,
      search: false,
      render: (_, r) => <Text>¥{fenToYuan(r.contract_amount_fen)}</Text>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      valueEnum: {
        active: { text: '生效中' },
        expired: { text: '已到期' },
        terminated: { text: '已终止' },
      },
      render: (_, r) => (
        <Tag color={CONTRACT_STATUS_COLOR[r.status]}>
          {CONTRACT_STATUS_LABEL[r.status] ?? r.status}
        </Tag>
      ),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 140,
      render: (_, record) => [
        <a key="detail" onClick={() => Modal.info({
          title: `合同详情 — ${record.contract_no}`,
          width: 560,
          content: (
            <div style={{ lineHeight: 2 }}>
              <div><Text strong>加盟商：</Text>{record.franchisee_name}</div>
              <div><Text strong>类型：</Text>{CONTRACT_TYPE_MAP[record.contract_type]}</div>
              <div><Text strong>签署日期：</Text>{record.sign_date}</div>
              <div><Text strong>有效期：</Text>{record.start_date} 至 {record.end_date}</div>
              <div><Text strong>合同金额：</Text>¥{fenToYuan(record.contract_amount_fen)}</div>
              <div><Text strong>状态：</Text>{CONTRACT_STATUS_LABEL[record.status]}</div>
              <div><Text strong>备注：</Text>{record.notes ?? '—'}</div>
            </div>
          ),
        })}>详情</a>,
        <a
          key="alert"
          onClick={() => handleSendAlert(record)}
          style={{ color: record.days_to_expire <= 30 ? '#A32D2D' : undefined }}
        >
          {alertLoading === record.id ? '发送中…' : '发送提醒'}
        </a>,
      ],
    },
  ];

  return (
    <>
      {alertVisible && expiringCount > 0 && (
        <Alert
          type="warning"
          showIcon
          icon={<BellOutlined />}
          message={
            <span>
              <Text strong style={{ color: '#BA7517' }}>
                {expiringCount} 份合同将在 30 天内到期
              </Text>
              ，请及时跟进续签或发送提醒。
            </span>
          }
          closable
          onClose={() => setAlertVisible(false)}
          style={{ marginBottom: 16 }}
        />
      )}

      <ProTable<FranchiseContract>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        request={async (params) => {
          try {
            const qs = new URLSearchParams({
              page: String(params.current ?? 1),
              size: String(params.pageSize ?? 20),
            });
            if (params.franchisee_name) qs.set('franchisee_id', params.franchisee_name);
            if (params.status) qs.set('status', params.status);
            if (params.contract_type) qs.set('contract_type', params.contract_type);

            const res = await apiFetch<{ ok: boolean; data: { items: FranchiseContract[]; total: number } }>(
              `${API_BASE}/contracts?${qs.toString()}`,
            );
            // 统计即将到期数量，更新预警横幅
            const expCount = res.data.items.filter(
              (c) => c.days_to_expire >= 0 && c.days_to_expire <= 30,
            ).length;
            setExpiringCount(expCount);
            return { data: res.data.items, total: res.data.total, success: true };
          } catch {
            return { data: [], total: 0, success: false };
          }
        }}
        search={{ labelWidth: 'auto' }}
        toolBarRender={() => [
          <Button
            key="create"
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreateOpen(true)}
          >
            新建合同
          </Button>,
        ]}
        pagination={{ defaultPageSize: 20 }}
      />

      {/* 新建合同弹窗 */}
      <Modal
        title={<><FileAddOutlined /> 新建加盟合同</>}
        open={createOpen}
        onCancel={() => { setCreateOpen(false); createForm.resetFields(); }}
        onOk={async () => {
          try {
            const values = await createForm.validateFields();
            await apiFetch(`${API_BASE}/contracts`, {
              method: 'POST',
              body: JSON.stringify({
                ...values,
                contract_amount_fen: Math.round((values.contract_amount_yuan ?? 0) * 100),
              }),
            });
            message.success('合同创建成功');
            setCreateOpen(false);
            createForm.resetFields();
            actionRef.current?.reload();
          } catch (err: unknown) {
            if (err instanceof Error && err.message) {
              message.error(err.message);
            }
          }
        }}
        width={560}
        destroyOnClose
      >
        <Form form={createForm} layout="vertical" style={{ marginTop: 16 }}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="franchisee_id" label="加盟商ID" rules={[{ required: true }]}>
                <Input placeholder="fr-001" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="franchisee_name" label="加盟商名称">
                <Input placeholder="如：长沙五一广场店" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="contract_type" label="合同类型" rules={[{ required: true }]}>
                <Select>
                  <Select.Option value="initial">首签</Select.Option>
                  <Select.Option value="renewal">续签</Select.Option>
                  <Select.Option value="amendment">补充协议</Select.Option>
                </Select>
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="alert_days_before" label="提前预警天数" initialValue={30}>
                <InputNumber min={1} max={365} style={{ width: '100%' }} addonAfter="天" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="sign_date" label="签署日期" rules={[{ required: true }]}>
                <Input type="date" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="start_date" label="生效日期" rules={[{ required: true }]}>
                <Input type="date" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="end_date" label="到期日期" rules={[{ required: true }]}>
                <Input type="date" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="contract_amount_yuan" label="合同总金额（元）">
            <InputNumber min={0} precision={2} style={{ width: '100%' }} prefix="¥" />
          </Form.Item>
          <Form.Item name="file_url" label="合同文件URL">
            <Input placeholder="OSS文件地址（可选）" />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

// ─── Tab 2: 收费管理 ───────────────────────────────────────────────────────────

function FeeTab() {
  const actionRef = useRef<ActionType>();
  const [stats, setStats] = useState<FeeStats | null>(null);
  const [payTarget, setPayTarget] = useState<FeeRecord | null>(null);
  const [payForm] = Form.useForm();
  const [payLoading, setPayLoading] = useState(false);

  const fetchStats = useCallback(async () => {
    try {
      const res = await apiFetch<{ ok: boolean; data: FeeStats }>(`${API_BASE}/fees/stats`);
      setStats(res.data);
    } catch {
      // stats fetch failure is non-blocking
    }
  }, []);

  const handlePay = useCallback(async () => {
    if (!payTarget) return;
    setPayLoading(true);
    try {
      const values = await payForm.validateFields();
      await apiFetch(`${API_BASE}/fees/${payTarget.id}/pay`, {
        method: 'PUT',
        body: JSON.stringify({
          paid_fen: Math.round((values.paid_yuan ?? 0) * 100),
          receipt_no: values.receipt_no ?? undefined,
          notes: values.notes ?? undefined,
        }),
      });
      message.success('付款记录已更新');
      setPayTarget(null);
      payForm.resetFields();
      actionRef.current?.reload();
      fetchStats();
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : '操作失败';
      message.error(errMsg);
    } finally {
      setPayLoading(false);
    }
  }, [payTarget, payForm, fetchStats]);

  const columns: ProColumns<FeeRecord>[] = [
    {
      title: '加盟商',
      dataIndex: 'franchisee_name',
      width: 140,
    },
    {
      title: '费用类型',
      dataIndex: 'fee_type',
      width: 110,
      valueEnum: Object.fromEntries(
        Object.entries(FEE_TYPE_MAP).map(([k, v]) => [k, { text: v }]),
      ),
      render: (_, r) => <Tag>{FEE_TYPE_MAP[r.fee_type] ?? r.fee_type}</Tag>,
    },
    {
      title: '收费周期',
      width: 180,
      search: false,
      render: (_, r) =>
        r.period_start && r.period_end
          ? `${r.period_start} 至 ${r.period_end}`
          : '—',
    },
    {
      title: '应收金额',
      dataIndex: 'amount_fen',
      width: 110,
      search: false,
      render: (_, r) => <Text strong>¥{fenToYuan(r.amount_fen)}</Text>,
    },
    {
      title: '已收金额',
      dataIndex: 'paid_fen',
      width: 110,
      search: false,
      render: (_, r) => (
        <Text style={{ color: r.paid_fen >= r.amount_fen ? '#0F6E56' : undefined }}>
          ¥{fenToYuan(r.paid_fen)}
        </Text>
      ),
    },
    {
      title: '应付款日',
      dataIndex: 'due_date',
      width: 110,
      search: false,
      render: (_, r) => r.due_date ?? '—',
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      valueEnum: Object.fromEntries(
        Object.entries(FEE_STATUS_LABEL).map(([k, v]) => [k, { text: v }]),
      ),
      render: (_, r) => (
        <Tag color={FEE_STATUS_COLOR[r.status]}>
          {FEE_STATUS_LABEL[r.status] ?? r.status}
        </Tag>
      ),
    },
    {
      title: '收据编号',
      dataIndex: 'receipt_no',
      width: 130,
      search: false,
      render: (_, r) =>
        r.receipt_no ? (
          <Text copyable style={{ fontSize: 12, fontFamily: 'monospace' }}>
            {r.receipt_no}
          </Text>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 90,
      render: (_, record) =>
        record.status !== 'paid'
          ? [
              <a
                key="pay"
                onClick={() => setPayTarget(record)}
                style={{ color: record.status === 'overdue' ? '#A32D2D' : undefined }}
              >
                {record.status === 'overdue' ? (
                  <Tooltip title="该收款已逾期，请尽快处理">
                    <ExclamationCircleOutlined style={{ marginRight: 4 }} />
                    标记付款
                  </Tooltip>
                ) : (
                  '标记付款'
                )}
              </a>,
            ]
          : [<Text key="done" type="secondary">已完成</Text>],
    },
  ];

  return (
    <>
      {/* 本季统计卡片 */}
      {stats && (
        <Row gutter={16} style={{ marginBottom: 24 }}>
          <Col span={6}>
            <div style={{ background: '#F8F7F5', borderRadius: 6, padding: '16px 20px' }}>
              <Statistic
                title="本季应收"
                value={fenToYuan(stats.total_amount_fen)}
                prefix="¥"
                valueStyle={{ fontSize: 22 }}
              />
            </div>
          </Col>
          <Col span={6}>
            <div style={{ background: '#F8F7F5', borderRadius: 6, padding: '16px 20px' }}>
              <Statistic
                title="已收"
                value={fenToYuan(stats.total_paid_fen)}
                prefix="¥"
                valueStyle={{ fontSize: 22, color: '#0F6E56' }}
              />
            </div>
          </Col>
          <Col span={6}>
            <div style={{ background: '#F8F7F5', borderRadius: 6, padding: '16px 20px' }}>
              <Statistic
                title="未收"
                value={fenToYuan(stats.total_unpaid_fen)}
                prefix="¥"
                valueStyle={{ fontSize: 22, color: '#BA7517' }}
              />
            </div>
          </Col>
          <Col span={6}>
            <div style={{ background: '#FFF3ED', borderRadius: 6, padding: '16px 20px', border: stats.total_overdue_fen > 0 ? '1px solid #A32D2D' : undefined }}>
              <Statistic
                title="逾期未收"
                value={fenToYuan(stats.total_overdue_fen)}
                prefix="¥"
                valueStyle={{ fontSize: 22, color: stats.total_overdue_fen > 0 ? '#A32D2D' : '#2C2C2A' }}
              />
            </div>
          </Col>
        </Row>
      )}

      <ProTable<FeeRecord>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        request={async (params) => {
          try {
            const qs = new URLSearchParams({
              page: String(params.current ?? 1),
              size: String(params.pageSize ?? 20),
            });
            if (params.status) qs.set('status', params.status);
            if (params.fee_type) qs.set('fee_type', params.fee_type);

            const res = await apiFetch<{ ok: boolean; data: { items: FeeRecord[]; total: number } }>(
              `${API_BASE}/fees?${qs.toString()}`,
            );
            // 同步刷新统计卡片
            fetchStats();
            return { data: res.data.items, total: res.data.total, success: true };
          } catch {
            return { data: [], total: 0, success: false };
          }
        }}
        search={{ labelWidth: 'auto' }}
        toolBarRender={() => [
          <Button
            key="overdue"
            danger
            icon={<ExclamationCircleOutlined />}
            onClick={async () => {
              try {
                const res = await apiFetch<{ ok: boolean; data: { items: FeeRecord[]; total: number; total_overdue_fen: number } }>(
                  `${API_BASE}/fees/overdue`,
                );
                Modal.warning({
                  title: `逾期收款汇总（共 ${res.data.total} 条）`,
                  width: 520,
                  content: (
                    <div>
                      <Text type="danger" strong>
                        逾期总金额：¥{fenToYuan(res.data.total_overdue_fen)}
                      </Text>
                      <ul style={{ marginTop: 12 }}>
                        {res.data.items.map((r) => (
                          <li key={r.id}>
                            {r.franchisee_name} —{' '}
                            {FEE_TYPE_MAP[r.fee_type]}：¥{fenToYuan(r.amount_fen - r.paid_fen)}
                            （应付：{r.due_date}）
                          </li>
                        ))}
                      </ul>
                    </div>
                  ),
                });
              } catch (err: unknown) {
                const errMsg = err instanceof Error ? err.message : '查询失败';
                message.error(errMsg);
              }
            }}
          >
            查看逾期
          </Button>,
          <Button
            key="export"
            icon={<DollarOutlined />}
            onClick={() => message.info('账单导出功能开发中，敬请期待')}
          >
            导出账单
          </Button>,
        ]}
        pagination={{ defaultPageSize: 20 }}
      />

      {/* 标记付款弹窗 */}
      <Modal
        title={
          <Space>
            <DollarOutlined />
            标记付款
            {payTarget && (
              <Text type="secondary" style={{ fontSize: 13 }}>
                — {payTarget.franchisee_name} / {FEE_TYPE_MAP[payTarget.fee_type]}
              </Text>
            )}
          </Space>
        }
        open={!!payTarget}
        onCancel={() => { setPayTarget(null); payForm.resetFields(); }}
        onOk={handlePay}
        confirmLoading={payLoading}
        width={440}
        destroyOnClose
      >
        {payTarget && (
          <div style={{ marginBottom: 16, padding: '12px 16px', background: '#F8F7F5', borderRadius: 6 }}>
            <Row gutter={16}>
              <Col span={12}>
                <Text type="secondary">应收金额</Text>
                <div><Text strong>¥{fenToYuan(payTarget.amount_fen)}</Text></div>
              </Col>
              <Col span={12}>
                <Text type="secondary">已付金额</Text>
                <div>
                  <Text strong style={{ color: '#0F6E56' }}>
                    ¥{fenToYuan(payTarget.paid_fen)}
                  </Text>
                </div>
              </Col>
            </Row>
            <Row style={{ marginTop: 8 }}>
              <Col span={24}>
                <Text type="secondary">待收</Text>
                <Text strong style={{ color: '#A32D2D', marginLeft: 8 }}>
                  ¥{fenToYuan(payTarget.amount_fen - payTarget.paid_fen)}
                </Text>
              </Col>
            </Row>
          </div>
        )}
        <Form form={payForm} layout="vertical">
          <Form.Item
            name="paid_yuan"
            label="本次收款金额（元）"
            rules={[
              { required: true, message: '请输入收款金额' },
              {
                validator: (_, v) => {
                  if (!payTarget) return Promise.resolve();
                  const maxYuan = (payTarget.amount_fen - payTarget.paid_fen) / 100;
                  if (v > maxYuan) {
                    return Promise.reject(new Error(`不能超过待收金额 ¥${maxYuan.toFixed(2)}`));
                  }
                  return Promise.resolve();
                },
              },
            ]}
          >
            <InputNumber
              min={0.01}
              precision={2}
              style={{ width: '100%' }}
              prefix="¥"
              placeholder="请输入实际收款金额"
            />
          </Form.Item>
          <Form.Item name="receipt_no" label="收据编号">
            <Input placeholder="RCP-YYYY-XXXX（可选）" />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} placeholder="付款备注（可选）" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

// ─── 页面主体 ──────────────────────────────────────────────────────────────────

export default function FranchiseContractPage() {
  return (
    <div style={{ padding: 24, minWidth: 1280 }}>
      <Tabs
        defaultActiveKey="contracts"
        items={[
          {
            key: 'contracts',
            label: (
              <Space>
                <FileAddOutlined />
                合同管理
              </Space>
            ),
            children: <ContractTab />,
          },
          {
            key: 'fees',
            label: (
              <Space>
                <DollarOutlined />
                收费管理
              </Space>
            ),
            children: <FeeTab />,
          },
        ]}
      />
    </div>
  );
}
