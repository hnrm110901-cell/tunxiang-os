/**
 * SplitPaymentPage — Y-B2 聚合支付/分账
 *
 * Tab 1: 分账订单   — ProTable 状态颜色标记，可展开查看分账明细
 * Tab 2: 差错账调账 — Form 提交调账申请 + 调账记录历史 Table
 * Tab 3: 分润试算   — 输入总金额 + 拖拽分润比例 → 实时计算各方金额
 *
 * Admin 终端规范：Ant Design 5.x + ProComponents + 1280px 最小宽度
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Form,
  InputNumber,
  message,
  Modal,
  Progress,
  Row,
  Select,
  Slider,
  Space,
  Statistic,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import {
  ApartmentOutlined,
  CalculatorOutlined,
  FileSearchOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import { ActionType, ProColumns, ProTable } from '@ant-design/pro-components';
import { formatPrice } from '@tx-ds/utils';

const { Title, Text } = Typography;

// ── 类型定义 ──────────────────────────────────────────────────────────────────

interface SplitOrder {
  id: string;
  order_id: string;
  total_fen: number;
  channel: 'wechat' | 'alipay';
  merchant_order_id: string;
  split_status: 'pending' | 'splitting' | 'completed' | 'failed';
  split_count: number;
  created_at: string;
}

interface SplitRecord {
  id: string;
  split_order_id: string;
  receiver_type: 'brand' | 'franchise' | 'platform_fee';
  receiver_id: string;
  amount_fen: number;
  channel_sub_merchant_id: string | null;
  split_result: 'pending' | 'success' | 'failed';
  async_notify_id: string | null;
  idempotency_key: string;
  created_at: string;
}

interface AdjustmentLog {
  id: string;
  split_record_id: string;
  reason: string;
  original_amount_fen: number;
  adjusted_amount_fen: number;
  adjusted_by: string;
  created_at: string;
}

interface PreviewItem {
  receiver_type: string;
  receiver_id: string;
  ratio: number;
  amount_fen: number;
}

// ── 工具函数 ──────────────────────────────────────────────────────────────────

/** @deprecated Use formatPrice from @tx-ds/utils */
const fenToYuan = (fen: number): string => (fen / 100).toFixed(2);

const getTenantId = (): string =>
  localStorage.getItem('tx_tenant_id') ?? '';

const apiRequest = async <T,>(
  path: string,
  options: RequestInit = {},
): Promise<T> => {
  const resp = await fetch(`/api/v1/finance/split${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': getTenantId(),
      ...options.headers,
    },
  });
  const json = await resp.json();
  if (!json.ok) {
    throw new Error(json.error?.message ?? '请求失败');
  }
  return json.data as T;
};

const splitStatusConfig: Record<SplitOrder['split_status'], { color: string; label: string }> = {
  pending: { color: 'default', label: '待处理' },
  splitting: { color: 'processing', label: '分账中' },
  completed: { color: 'success', label: '已完成' },
  failed: { color: 'error', label: '失败' },
};

const recordResultConfig: Record<SplitRecord['split_result'], { color: string; label: string }> = {
  pending: { color: 'orange', label: '待处理' },
  success: { color: 'green', label: '成功' },
  failed: { color: 'red', label: '失败' },
};

const receiverTypeLabel: Record<string, string> = {
  brand: '品牌',
  franchise: '加盟商',
  platform_fee: '平台服务费',
};

const channelLabel: Record<string, string> = {
  wechat: '微信支付',
  alipay: '支付宝',
};

// ── Tab 1: 分账订单 ────────────────────────────────────────────────────────────

const SplitOrdersTab: React.FC = () => {
  const actionRef = useRef<ActionType>();

  // 展开行：加载分账明细
  const expandedRowRender = (order: SplitOrder) => (
    <ExpandedRecords splitOrderId={order.id} />
  );

  const columns: ProColumns<SplitOrder>[] = [
    {
      title: '分账订单ID',
      dataIndex: 'id',
      width: 280,
      copyable: true,
      ellipsis: true,
    },
    {
      title: '业务订单ID',
      dataIndex: 'order_id',
      width: 280,
      copyable: true,
      ellipsis: true,
    },
    {
      title: '渠道',
      dataIndex: 'channel',
      width: 100,
      valueType: 'select',
      valueEnum: {
        wechat: { text: '微信支付' },
        alipay: { text: '支付宝' },
      },
      render: (_, r) => (
        <Tag color={r.channel === 'wechat' ? 'green' : 'blue'}>
          {channelLabel[r.channel] ?? r.channel}
        </Tag>
      ),
    },
    {
      title: '总金额',
      dataIndex: 'total_fen',
      search: false,
      render: (_, r) => `¥${fenToYuan(r.total_fen)}`,
    },
    {
      title: '商户订单号',
      dataIndex: 'merchant_order_id',
      width: 180,
      copyable: true,
    },
    {
      title: '分账方数',
      dataIndex: 'split_count',
      width: 90,
      search: false,
    },
    {
      title: '状态',
      dataIndex: 'split_status',
      width: 100,
      valueType: 'select',
      valueEnum: {
        pending: { text: '待处理', status: 'Default' },
        splitting: { text: '分账中', status: 'Processing' },
        completed: { text: '已完成', status: 'Success' },
        failed: { text: '失败', status: 'Error' },
      },
      render: (_, r) => {
        const cfg = splitStatusConfig[r.split_status];
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      valueType: 'dateTime',
      search: false,
      width: 160,
    },
  ];

  return (
    <ProTable<SplitOrder>
      actionRef={actionRef}
      rowKey="id"
      columns={columns}
      expandable={{ expandedRowRender }}
      request={async (params) => {
        try {
          const qs = new URLSearchParams({
            page: String(params.current ?? 1),
            size: String(params.pageSize ?? 20),
          });
          if (params.split_status) qs.set('split_status', params.split_status);
          const data = await apiRequest<{
            items: SplitOrder[];
            total: number;
          }>(`/orders?${qs}`);
          return { data: data.items, total: data.total, success: true };
        } catch {
          return { data: [], total: 0, success: false };
        }
      }}
      search={{ labelWidth: 'auto' }}
      pagination={{ defaultPageSize: 20 }}
      scroll={{ x: 1200 }}
    />
  );
};

// 展开的分账明细子表
const ExpandedRecords: React.FC<{ splitOrderId: string }> = ({ splitOrderId }) => {
  const [records, setRecords] = useState<SplitRecord[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiRequest<{ items: SplitRecord[]; total: number }>(
      `/orders/${splitOrderId}/records`,
    )
      .then((data) => setRecords(data.items))
      .catch(() => setRecords([]))
      .finally(() => setLoading(false));
  }, [splitOrderId]);

  return (
    <ProTable<SplitRecord>
      loading={loading}
      dataSource={records}
      rowKey="id"
      search={false}
      toolBarRender={false}
      pagination={false}
      style={{ marginBottom: 0 }}
      columns={[
        {
          title: '收款方类型',
          dataIndex: 'receiver_type',
          render: (_, r) => receiverTypeLabel[r.receiver_type] ?? r.receiver_type,
        },
        { title: '收款方ID', dataIndex: 'receiver_id', copyable: true },
        { title: '分账金额', dataIndex: 'amount_fen', render: (_, r) => `¥${fenToYuan(r.amount_fen)}` },
        {
          title: '子商户号',
          dataIndex: 'channel_sub_merchant_id',
          render: (_, r) => r.channel_sub_merchant_id ?? <Text type="secondary">—</Text>,
        },
        {
          title: '分账结果',
          dataIndex: 'split_result',
          render: (_, r) => {
            const cfg = recordResultConfig[r.split_result];
            return <Tag color={cfg.color}>{cfg.label}</Tag>;
          },
        },
        {
          title: '渠道通知ID',
          dataIndex: 'async_notify_id',
          render: (_, r) => r.async_notify_id ?? <Text type="secondary">—</Text>,
        },
      ]}
    />
  );
};

// ── Tab 2: 差错账调账 ──────────────────────────────────────────────────────────

const AdjustmentTab: React.FC = () => {
  const [form] = Form.useForm();
  const [submitLoading, setSubmitLoading] = useState(false);
  const [logs, setLogs] = useState<AdjustmentLog[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);

  const loadLogs = useCallback(async () => {
    setLogsLoading(true);
    try {
      const data = await apiRequest<{ items: AdjustmentLog[]; total: number }>(
        '/adjustments',
      );
      setLogs(data.items);
    } catch {
      setLogs([]);
    } finally {
      setLogsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadLogs();
  }, [loadLogs]);

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setSubmitLoading(true);
      const result = await apiRequest<{
        adjustment_id: string;
        original_amount_fen: number;
        adjusted_amount_fen: number;
      }>('/adjustments', {
        method: 'POST',
        body: JSON.stringify({
          ...values,
          adjusted_amount_fen: Math.round(values.adjusted_amount_yuan * 100),
        }),
      });
      message.success(
        `调账成功：原金额 ¥${fenToYuan(result.original_amount_fen)} → 调整为 ¥${fenToYuan(result.adjusted_amount_fen)}`,
      );
      form.resetFields();
      loadLogs();
    } catch (err: unknown) {
      message.error((err as Error).message ?? '调账失败');
    } finally {
      setSubmitLoading(false);
    }
  };

  return (
    <Row gutter={24}>
      {/* 调账申请表单 */}
      <Col span={10}>
        <Card title="提交调账申请" bordered={false} style={{ borderRadius: 8 }}>
          <Alert
            type="warning"
            showIcon
            message="差错账调账为人工干预操作，请确认无误后提交。"
            style={{ marginBottom: 16 }}
          />
          <Form form={form} layout="vertical">
            <Form.Item
              name="split_record_id"
              label="分账明细 ID"
              rules={[{ required: true, message: '请输入分账明细 ID' }]}
            >
              <input
                style={{
                  width: '100%',
                  padding: '4px 11px',
                  border: '1px solid #d9d9d9',
                  borderRadius: 6,
                  fontSize: 14,
                  outline: 'none',
                }}
                placeholder="请粘贴分账明细 UUID"
              />
            </Form.Item>
            <Form.Item
              name="adjusted_amount_yuan"
              label="调整后金额（元）"
              rules={[{ required: true, message: '请输入调整后金额' }, { type: 'number', min: 0.01 }]}
            >
              <InputNumber
                style={{ width: '100%' }}
                min={0.01}
                precision={2}
                prefix="¥"
                placeholder="0.00"
              />
            </Form.Item>
            <Form.Item
              name="reason"
              label="调账原因"
              rules={[{ required: true, message: '请填写调账原因' }, { min: 5, message: '原因至少5个字' }]}
            >
              <input
                style={{
                  width: '100%',
                  padding: '4px 11px',
                  border: '1px solid #d9d9d9',
                  borderRadius: 6,
                  fontSize: 14,
                  outline: 'none',
                }}
                placeholder="如：渠道实际到账金额有误"
              />
            </Form.Item>
            <Form.Item
              name="adjusted_by"
              label="操作人"
              rules={[{ required: true, message: '请填写操作人信息' }]}
            >
              <input
                style={{
                  width: '100%',
                  padding: '4px 11px',
                  border: '1px solid #d9d9d9',
                  borderRadius: 6,
                  fontSize: 14,
                  outline: 'none',
                }}
                placeholder="工号或邮箱"
              />
            </Form.Item>
            <Form.Item>
              <Button
                type="primary"
                block
                loading={submitLoading}
                onClick={handleSubmit}
                style={{ marginTop: 8 }}
              >
                提交调账申请
              </Button>
            </Form.Item>
          </Form>
        </Card>
      </Col>

      {/* 调账历史记录 */}
      <Col span={14}>
        <Card
          title="调账历史"
          bordered={false}
          style={{ borderRadius: 8 }}
          extra={
            <Button size="small" onClick={loadLogs} loading={logsLoading}>
              刷新
            </Button>
          }
        >
          <ProTable<AdjustmentLog>
            loading={logsLoading}
            dataSource={logs}
            rowKey="id"
            search={false}
            toolBarRender={false}
            pagination={{ pageSize: 10 }}
            columns={[
              {
                title: '调账时间',
                dataIndex: 'created_at',
                valueType: 'dateTime',
                width: 150,
              },
              {
                title: '原金额',
                dataIndex: 'original_amount_fen',
                render: (_, r) => `¥${fenToYuan(r.original_amount_fen)}`,
              },
              {
                title: '调整后',
                dataIndex: 'adjusted_amount_fen',
                render: (_, r) => (
                  <Text strong style={{ color: '#FF6B35' }}>
                    ¥{fenToYuan(r.adjusted_amount_fen)}
                  </Text>
                ),
              },
              {
                title: '差额',
                render: (_, r) => {
                  const diff = r.adjusted_amount_fen - r.original_amount_fen;
                  return (
                    <Text style={{ color: diff >= 0 ? '#0F6E56' : '#A32D2D' }}>
                      {diff >= 0 ? '+' : ''}{fenToYuan(diff)}
                    </Text>
                  );
                },
              },
              {
                title: '原因',
                dataIndex: 'reason',
                ellipsis: true,
              },
              {
                title: '操作人',
                dataIndex: 'adjusted_by',
                width: 120,
                ellipsis: true,
              },
            ]}
          />
        </Card>
      </Col>
    </Row>
  );
};

// ── Tab 3: 分润试算 ────────────────────────────────────────────────────────────

interface RuleRow {
  receiver_type: 'brand' | 'franchise' | 'platform_fee';
  receiver_id: string;
  ratio: number; // 万分比
}

const PRESET_RULES: RuleRow[] = [
  { receiver_type: 'brand', receiver_id: 'brand_001', ratio: 2000 },
  { receiver_type: 'franchise', receiver_id: 'store_001', ratio: 7000 },
  { receiver_type: 'platform_fee', receiver_id: 'platform', ratio: 1000 },
];

const PreviewTab: React.FC = () => {
  const [totalYuan, setTotalYuan] = useState<number>(10000);
  const [rules, setRules] = useState<RuleRow[]>(PRESET_RULES);
  const [preview, setPreview] = useState<PreviewItem[]>([]);
  const [loading, setLoading] = useState(false);

  const totalRatio = rules.reduce((s, r) => s + r.ratio, 0);
  const isValid = totalRatio === 10000;

  const handleRatioChange = (index: number, value: number) => {
    const next = rules.map((r, i) => (i === index ? { ...r, ratio: value } : r));
    setRules(next);
  };

  const handlePreview = async () => {
    if (!isValid) {
      message.warning(`比例之和为 ${totalRatio / 100}%，必须等于 100%`);
      return;
    }
    setLoading(true);
    try {
      const totalFen = Math.round(totalYuan * 100);
      const rulesJson = JSON.stringify(
        rules.map((r) => ({
          receiver_type: r.receiver_type,
          receiver_id: r.receiver_id,
          ratio: r.ratio,
        })),
      );
      const qs = new URLSearchParams({
        total_fen: String(totalFen),
        rules: rulesJson,
      });
      const data = await apiRequest<{
        total_fen: number;
        preview_items: PreviewItem[];
        amounts_are_integers: boolean;
      }>(`/rules/preview?${qs}`);
      setPreview(data.preview_items);
    } catch (err: unknown) {
      message.error((err as Error).message ?? '试算失败');
    } finally {
      setLoading(false);
    }
  };

  // 实时试算（仅当比例合法时）
  useEffect(() => {
    if (isValid && totalYuan > 0) {
      handlePreview();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rules, totalYuan]);

  return (
    <Row gutter={24}>
      {/* 左侧：输入区 */}
      <Col span={12}>
        <Card title="分润规则配置" bordered={false} style={{ borderRadius: 8 }}>
          <div style={{ marginBottom: 24 }}>
            <Text strong>总金额（元）</Text>
            <InputNumber
              style={{ width: '100%', marginTop: 8 }}
              min={1}
              precision={2}
              value={totalYuan}
              onChange={(v) => setTotalYuan(v ?? 10000)}
              prefix="¥"
              size="large"
            />
          </div>

          <div style={{ marginBottom: 12 }}>
            <Row justify="space-between" align="middle">
              <Text strong>分润比例配置</Text>
              <Tag color={isValid ? 'green' : 'red'}>
                合计：{(totalRatio / 100).toFixed(2)}%
                {isValid ? ' ✓' : ' (须为 100%)'}
              </Tag>
            </Row>
          </div>

          {rules.map((rule, idx) => (
            <div key={idx} style={{ marginBottom: 20 }}>
              <Row align="middle" gutter={8} style={{ marginBottom: 6 }}>
                <Col>
                  <Tag
                    color={
                      rule.receiver_type === 'brand'
                        ? 'purple'
                        : rule.receiver_type === 'franchise'
                        ? 'orange'
                        : 'blue'
                    }
                  >
                    {receiverTypeLabel[rule.receiver_type]}
                  </Tag>
                </Col>
                <Col flex="auto">
                  <Text type="secondary">{rule.receiver_id}</Text>
                </Col>
                <Col>
                  <Text strong style={{ color: '#FF6B35' }}>
                    {(rule.ratio / 100).toFixed(2)}%
                  </Text>
                </Col>
              </Row>
              <Slider
                min={0}
                max={10000}
                step={1}
                value={rule.ratio}
                onChange={(v) => handleRatioChange(idx, v)}
                tooltip={{ formatter: (v) => `${((v ?? 0) / 100).toFixed(2)}%` }}
                trackStyle={{ background: '#FF6B35' }}
                handleStyle={{ borderColor: '#FF6B35' }}
              />
            </div>
          ))}
        </Card>
      </Col>

      {/* 右侧：试算结果 */}
      <Col span={12}>
        <Card title="试算结果" bordered={false} style={{ borderRadius: 8 }}>
          {!isValid ? (
            <Alert
              type="error"
              message="比例之和不等于 100%，无法试算"
              showIcon
            />
          ) : preview.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '40px 0', color: '#B4B2A9' }}>
              调整左侧比例后自动计算
            </div>
          ) : (
            <>
              <Row gutter={16} style={{ marginBottom: 20 }}>
                <Col span={24}>
                  <Statistic
                    title="总金额"
                    value={totalYuan.toFixed(2)}
                    prefix="¥"
                    valueStyle={{ color: '#1E2A3A', fontWeight: 700 }}
                  />
                </Col>
              </Row>

              {preview.map((item, idx) => {
                const percent = Math.round((item.amount_fen / Math.round(totalYuan * 100)) * 100);
                return (
                  <div key={idx} style={{ marginBottom: 20 }}>
                    <Row justify="space-between" align="middle" style={{ marginBottom: 6 }}>
                      <Col>
                        <Space>
                          <Tag
                            color={
                              item.receiver_type === 'brand'
                                ? 'purple'
                                : item.receiver_type === 'franchise'
                                ? 'orange'
                                : 'blue'
                            }
                          >
                            {receiverTypeLabel[item.receiver_type] ?? item.receiver_type}
                          </Tag>
                          <Text type="secondary">{item.receiver_id}</Text>
                        </Space>
                      </Col>
                      <Col>
                        <Text strong style={{ fontSize: 18, color: '#2C2C2A' }}>
                          ¥{fenToYuan(item.amount_fen)}
                        </Text>
                        <Text type="secondary" style={{ marginLeft: 8 }}>
                          ({(item.ratio / 100).toFixed(2)}%)
                        </Text>
                      </Col>
                    </Row>
                    <Progress
                      percent={percent}
                      showInfo={false}
                      strokeColor={
                        item.receiver_type === 'brand'
                          ? '#722ED1'
                          : item.receiver_type === 'franchise'
                          ? '#FF6B35'
                          : '#185FA5'
                      }
                      size="small"
                    />
                  </div>
                );
              })}

              <Row
                style={{
                  borderTop: '1px solid #E8E6E1',
                  paddingTop: 16,
                  marginTop: 8,
                }}
              >
                <Col span={24}>
                  <Row justify="space-between">
                    <Text>验证：各方合计</Text>
                    <Text strong style={{ color: '#0F6E56' }}>
                      ¥{fenToYuan(preview.reduce((s, i) => s + i.amount_fen, 0))}
                      {preview.reduce((s, i) => s + i.amount_fen, 0) ===
                      Math.round(totalYuan * 100) ? (
                        <Tag color="green" style={{ marginLeft: 8 }}>
                          金额校验通过
                        </Tag>
                      ) : (
                        <Tag color="red" style={{ marginLeft: 8 }}>
                          校验失败
                        </Tag>
                      )}
                    </Text>
                  </Row>
                </Col>
              </Row>
            </>
          )}
        </Card>
      </Col>
    </Row>
  );
};

// ── 主页面 ─────────────────────────────────────────────────────────────────────

const SplitPaymentPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState('orders');

  const tabs = [
    { key: 'orders', label: '分账订单', children: <SplitOrdersTab /> },
    { key: 'adjustments', label: '差错账调账', children: <AdjustmentTab /> },
    { key: 'preview', label: '分润试算', children: <PreviewTab /> },
  ];

  return (
    <div style={{ padding: '24px', minWidth: 1280, background: '#F8F7F5', minHeight: '100vh' }}>
      <Row align="middle" style={{ marginBottom: 20 }}>
        <Col flex="auto">
          <Title level={3} style={{ margin: 0, color: '#1E2A3A' }}>
            聚合支付 / 分账管理
          </Title>
          <Text type="secondary">微信/支付宝分账 · 差错账调账 · 分润试算</Text>
        </Col>
      </Row>

      {/* Tabs */}
      <div style={{ background: '#fff', borderRadius: 8, padding: '0 24px' }}>
        <div
          style={{
            display: 'flex',
            borderBottom: '1px solid #E8E6E1',
            marginBottom: 0,
          }}
        >
          {tabs.map((tab) => (
            <div
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              style={{
                padding: '14px 20px',
                cursor: 'pointer',
                color: activeTab === tab.key ? '#FF6B35' : '#5F5E5A',
                borderBottom: activeTab === tab.key ? '2px solid #FF6B35' : '2px solid transparent',
                fontWeight: activeTab === tab.key ? 600 : 400,
                fontSize: 14,
                userSelect: 'none',
              }}
            >
              {tab.label}
            </div>
          ))}
        </div>

        <div style={{ padding: '20px 0' }}>
          {tabs.find((t) => t.key === activeTab)?.children}
        </div>
      </div>
    </div>
  );
};

export default SplitPaymentPage;
