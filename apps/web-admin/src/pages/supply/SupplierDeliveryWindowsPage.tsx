/**
 * 供应商配送时间窗管理页 — 域D 供应链（PRD-05 / Tier 1 食安）
 * 路由：/supply/supplier-delivery-windows
 *
 * 功能：
 *   1. 选择 supplier + store，展示该 supplier 在该 store 的配送时间窗列表
 *   2. 新建时间窗（草稿态 — approved_by=NULL，weekday_mask + 时间窗 + grace）
 *   3. 二级审批（不允许 self-approve）
 *   4. 软删
 *   5. 时间窗合规性检查工具（输入 signed_at → 显示 within / violation_kind / violation_minutes）
 *
 * API:
 *   GET    /api/v1/supply/suppliers/{id}/delivery-windows?only_active=
 *   POST   /api/v1/supply/suppliers/{id}/delivery-windows         — 新建草稿
 *   POST   /api/v1/supply/delivery-windows/{window_id}/approve    — 二级审批
 *   DELETE /api/v1/supply/delivery-windows/{window_id}            — 软删
 *   POST   /api/v1/supply/receiving/check-delivery-window         — 合规检查
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Checkbox,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Radio,
  Switch,
  Table,
  Tag,
  TimePicker,
  Typography,
  message,
} from 'antd';
import {
  AlertOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  ExclamationCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { txFetchData } from '../../api/client';

const { Title, Text } = Typography;

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface Supplier {
  id: string;
  name: string;
  category?: string;
}

interface Store {
  id: string;
  name: string;
}

interface DeliveryWindow {
  id: string;
  tenant_id: string;
  supplier_id: string;
  store_id: string;
  weekday_mask: number;
  earliest_time: string; // HH:mm:ss
  latest_time: string;
  grace_minutes: number;
  auto_reject_on_late: boolean;
  approved_by: string | null;
  approved_at: string | null;
  notes: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  is_deleted: boolean;
}

interface CheckWindowResult {
  within_window: boolean;
  window_id: string | null;
  weekday_matched: boolean;
  scheduled_earliest: string | null;
  scheduled_latest: string | null;
  grace_minutes: number | null;
  violation_minutes: number;
  violation_kind: 'late' | 'early' | null;
}

const WEEKDAY_OPTIONS = [
  { label: '周一', value: 1 },
  { label: '周二', value: 2 },
  { label: '周三', value: 4 },
  { label: '周四', value: 8 },
  { label: '周五', value: 16 },
  { label: '周六', value: 32 },
  { label: '周日', value: 64 },
];

function weekdayMaskToLabels(mask: number): string {
  const labels: string[] = [];
  for (const { label, value } of WEEKDAY_OPTIONS) {
    if ((mask & value) !== 0) labels.push(label);
  }
  return labels.length === 7 ? '每天' : labels.join('、');
}

function statusTag(w: DeliveryWindow) {
  if (w.is_deleted) return <Tag color="default">已删除</Tag>;
  if (w.approved_by) return <Tag color="success">已审批</Tag>;
  return <Tag color="warning">待审批</Tag>;
}

// ─── 新建 Modal ──────────────────────────────────────────────────────────────

interface CreateModalProps {
  supplierId: string;
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

function CreateWindowModal({ supplierId, open, onClose, onSuccess }: CreateModalProps) {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    let values: Record<string, unknown>;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setSubmitting(true);
    try {
      const weekdays = (values['weekdays'] as number[]) ?? [];
      if (weekdays.length === 0) {
        message.error('至少选择一个工作日');
        setSubmitting(false);
        return;
      }
      const weekdayMask = weekdays.reduce((acc, w) => acc | w, 0);
      const earliest = values['earliest_time'] as dayjs.Dayjs;
      const latest = values['latest_time'] as dayjs.Dayjs;

      const body: Record<string, unknown> = {
        supplier_id: supplierId,
        store_id: values['store_id'] as string,
        weekday_mask: weekdayMask,
        earliest_time: earliest.format('HH:mm:ss'),
        latest_time: latest.format('HH:mm:ss'),
        grace_minutes: (values['grace_minutes'] as number) ?? 15,
        auto_reject_on_late: !!values['auto_reject_on_late'],
        notes: (values['notes'] as string | undefined) ?? null,
      };

      await txFetchData(`/api/v1/supply/suppliers/${supplierId}/delivery-windows`, {
        method: 'POST',
        body: JSON.stringify(body),
      });
      message.success('配送时间窗已创建（草稿态，需独立审批人审批生效）');
      form.resetFields();
      onSuccess();
      onClose();
    } catch (err) {
      const msg = err instanceof Error ? err.message : '创建失败';
      message.error(`创建失败: ${msg}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title="新建配送时间窗（草稿）"
      open={open}
      onCancel={() => { form.resetFields(); onClose(); }}
      onOk={handleSubmit}
      okText="创建草稿"
      cancelText="取消"
      confirmLoading={submitting}
      destroyOnClose
      width={620}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="二级审批必须"
        description="创建为草稿态，必须由非创建人独立审批后才参与签收合规检查。"
      />
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          weekdays: [1, 2, 4, 8, 16, 32, 64], // 每天
          earliest_time: dayjs('04:00:00', 'HH:mm:ss'),
          latest_time: dayjs('07:00:00', 'HH:mm:ss'),
          grace_minutes: 15,
          auto_reject_on_late: false,
        }}
      >
        <Form.Item
          name="store_id"
          label="门店 ID"
          rules={[{ required: true, message: '请输入门店 ID' }]}
          tooltip="UUID 格式 — 实际场景从 store 下拉框选择"
        >
          <Input placeholder="门店 UUID" />
        </Form.Item>
        <Form.Item name="weekdays" label="生效星期" rules={[{ required: true }]}>
          <Checkbox.Group options={WEEKDAY_OPTIONS} />
        </Form.Item>
        <Space size="middle" style={{ width: '100%' }}>
          <Form.Item
            name="earliest_time"
            label="最早允许到货时间"
            rules={[{ required: true }]}
          >
            <TimePicker format="HH:mm" minuteStep={5} />
          </Form.Item>
          <Form.Item
            name="latest_time"
            label="最晚允许到货时间"
            rules={[
              { required: true },
              ({ getFieldValue }) => ({
                validator(_, value: dayjs.Dayjs | undefined) {
                  const earliest = getFieldValue('earliest_time') as dayjs.Dayjs | undefined;
                  if (!value || !earliest) return Promise.resolve();
                  if (value.isAfter(earliest)) return Promise.resolve();
                  return Promise.reject(new Error('最晚时间必须晚于最早时间'));
                },
              }),
            ]}
          >
            <TimePicker format="HH:mm" minuteStep={5} />
          </Form.Item>
        </Space>
        <Form.Item
          name="grace_minutes"
          label="容忍偏差（分钟）"
          tooltip="signed_at 在 [earliest - grace, latest + grace] 内算合规"
          rules={[{ required: true }]}
        >
          <InputNumber min={0} max={240} step={5} style={{ width: '100%' }} addonAfter="min" />
        </Form.Item>
        <Form.Item
          name="auto_reject_on_late"
          label="超时自动拒收"
          tooltip="P0 仅记录违约不自动拒收；该字段保留供未来扩展"
          valuePropName="checked"
        >
          <Switch checkedChildren="启用" unCheckedChildren="禁用（仅记录）" />
        </Form.Item>
        <Form.Item name="notes" label="备注">
          <Input.TextArea
            rows={2}
            placeholder="如：徐记海鲜生鲜供应商 — 早班质检窗口"
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}

// ─── 审批 Modal ──────────────────────────────────────────────────────────────

interface ApproveModalProps {
  window: DeliveryWindow | null;
  currentUserId: string;
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

function ApproveWindowModal({
  window: w,
  currentUserId,
  open,
  onClose,
  onSuccess,
}: ApproveModalProps) {
  const [submitting, setSubmitting] = useState(false);
  const isSelfApprove = !!w && w.created_by === currentUserId;

  const handleApprove = async () => {
    if (!w) return;
    if (isSelfApprove) {
      message.error('不能审批自己创建的配送时间窗（必须独立审批人签字）');
      return;
    }
    setSubmitting(true);
    try {
      await txFetchData(`/api/v1/supply/delivery-windows/${w.id}/approve`, {
        method: 'POST',
        body: JSON.stringify({ approver_id: currentUserId }),
      });
      message.success('审批通过，配送时间窗已生效');
      onSuccess();
      onClose();
    } catch (err) {
      const msg = err instanceof Error ? err.message : '审批失败';
      message.error(`审批失败: ${msg}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title="二级审批配送时间窗"
      open={open}
      onCancel={onClose}
      onOk={handleApprove}
      okText="审批通过"
      okButtonProps={{ disabled: isSelfApprove }}
      cancelText="取消"
      confirmLoading={submitting}
      destroyOnClose
      width={520}
    >
      {w && (
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          {isSelfApprove && (
            <Alert
              type="error"
              showIcon
              message="不能审批自己创建的配送时间窗"
              description={`您 (${currentUserId}) 是创建人，必须由其他人作为审批人独立签字。`}
            />
          )}
          <Text><strong>生效星期:</strong> {weekdayMaskToLabels(w.weekday_mask)}</Text>
          <Text>
            <strong>时间窗:</strong> {w.earliest_time.slice(0, 5)} ～ {w.latest_time.slice(0, 5)}
          </Text>
          <Text><strong>容忍偏差:</strong> ±{w.grace_minutes} min</Text>
          <Text><strong>自动拒收:</strong> {w.auto_reject_on_late ? '启用' : '禁用（仅记录）'}</Text>
          <Text type="secondary"><strong>创建人:</strong> {w.created_by}</Text>
          {w.notes && <Text type="secondary"><strong>备注:</strong> {w.notes}</Text>}
        </Space>
      )}
    </Modal>
  );
}

// ─── 合规性检查 Modal ─────────────────────────────────────────────────────────

interface CheckModalProps {
  supplierId: string;
  open: boolean;
  onClose: () => void;
}

function CheckWindowModal({ supplierId, open, onClose }: CheckModalProps) {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<CheckWindowResult | null>(null);

  const handleCheck = async () => {
    let values: Record<string, unknown>;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setSubmitting(true);
    setResult(null);
    try {
      const signedAt = (values['signed_at'] as dayjs.Dayjs).toISOString();
      const body = {
        supplier_id: supplierId,
        store_id: values['store_id'] as string,
        signed_at: signedAt,
      };
      const data = await txFetchData<CheckWindowResult>(
        '/api/v1/supply/receiving/check-delivery-window',
        { method: 'POST', body: JSON.stringify(body) },
      );
      setResult(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : '检查失败';
      message.error(`检查失败: ${msg}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title="配送时间窗合规性检查"
      open={open}
      onCancel={() => { form.resetFields(); setResult(null); onClose(); }}
      onOk={handleCheck}
      okText="检查"
      cancelText="关闭"
      confirmLoading={submitting}
      destroyOnClose
      width={560}
    >
      <Form form={form} layout="vertical" initialValues={{ signed_at: dayjs() }}>
        <Form.Item
          name="store_id"
          label="门店 ID"
          rules={[{ required: true, message: '请输入门店 ID' }]}
        >
          <Input placeholder="门店 UUID" />
        </Form.Item>
        <Form.Item
          name="signed_at"
          label="签收时刻（模拟签收时刻判断）"
          rules={[{ required: true }]}
        >
          <DatePicker showTime style={{ width: '100%' }} format="YYYY-MM-DD HH:mm" />
        </Form.Item>
      </Form>
      {result && (
        <Alert
          type={result.within_window ? 'success' : 'error'}
          showIcon
          style={{ marginTop: 16 }}
          icon={result.within_window ? <CheckCircleOutlined /> : <AlertOutlined />}
          message={
            !result.weekday_matched
              ? '该工作日无生效时间窗（fail-open 不阻塞）'
              : result.within_window
                ? '合规：签收时刻落在配送窗口内'
                : `违约：${result.violation_kind === 'late' ? '晚到' : '早到'} ${result.violation_minutes} 分钟`
          }
          description={
            <Space direction="vertical" size={2}>
              {result.scheduled_earliest && (
                <Text>
                  适用窗口：{result.scheduled_earliest.slice(0, 5)} ～ {result.scheduled_latest?.slice(0, 5)}
                  （±{result.grace_minutes} min 容忍）
                </Text>
              )}
              {!result.weekday_matched && (
                <Text type="secondary">该 supplier 在所选 store 该工作日未配置时间窗 — 不记违约</Text>
              )}
            </Space>
          }
        />
      )}
    </Modal>
  );
}

// ─── 主页面 ──────────────────────────────────────────────────────────────────

export function SupplierDeliveryWindowsPage() {
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [supplierLoading, setSupplierLoading] = useState(false);
  const [selectedSupplierId, setSelectedSupplierId] = useState<string | null>(null);

  const [windows, setWindows] = useState<DeliveryWindow[]>([]);
  const [loading, setLoading] = useState(false);
  const [onlyActive, setOnlyActive] = useState<'all' | 'active'>('all');
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [checkOpen, setCheckOpen] = useState(false);
  const [approveTarget, setApproveTarget] = useState<DeliveryWindow | null>(null);

  const [currentUserId] = useState<string>(() => {
    return localStorage.getItem('tx_user_id') ?? 'admin';
  });

  const loadSuppliers = useCallback(async () => {
    setSupplierLoading(true);
    try {
      const data = await txFetchData<{ items: Supplier[]; total: number }>(
        '/api/v1/supply/supplier-portal/suppliers?page=1&size=100',
      );
      const items = data.items ?? [];
      setSuppliers(items);
      if (items.length > 0 && !selectedSupplierId) {
        setSelectedSupplierId(items[0].id);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrMsg(`加载供应商列表失败: ${msg}`);
    } finally {
      setSupplierLoading(false);
    }
  }, [selectedSupplierId]);

  useEffect(() => {
    void loadSuppliers();
  }, []);

  const loadWindows = useCallback(
    async (supplierId: string, mode: 'all' | 'active') => {
      setLoading(true);
      setErrMsg(null);
      try {
        const params = new URLSearchParams({
          only_active: mode === 'active' ? 'true' : 'false',
        });
        const data = await txFetchData<{ items: DeliveryWindow[]; total: number }>(
          `/api/v1/supply/suppliers/${supplierId}/delivery-windows?${params.toString()}`,
        );
        setWindows(data.items ?? []);
      } catch (err) {
        const errObj = err as { code?: string; message?: string };
        const msg = errObj.message ?? String(err);
        setErrMsg(`加载配送时间窗失败: ${msg}`);
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (selectedSupplierId) {
      void loadWindows(selectedSupplierId, onlyActive);
    }
  }, [selectedSupplierId, onlyActive, loadWindows]);

  const refresh = useCallback(() => {
    if (selectedSupplierId) {
      void loadWindows(selectedSupplierId, onlyActive);
    }
  }, [selectedSupplierId, onlyActive, loadWindows]);

  const handleDelete = useCallback(
    (w: DeliveryWindow) => {
      Modal.confirm({
        title: '确认删除配送时间窗',
        icon: <ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />,
        content: `软删后「${weekdayMaskToLabels(w.weekday_mask)} ${w.earliest_time.slice(0,5)}～${w.latest_time.slice(0,5)}」不再参与签收合规检查。确认删除？`,
        okText: '确认删除',
        okType: 'danger',
        cancelText: '取消',
        onOk: async () => {
          try {
            await txFetchData(`/api/v1/supply/delivery-windows/${w.id}`, { method: 'DELETE' });
            message.success('配送时间窗已删除');
            refresh();
          } catch (err) {
            const msg = err instanceof Error ? err.message : '删除失败';
            message.error(`删除失败: ${msg}`);
          }
        },
      });
    },
    [refresh],
  );

  const columns = [
    {
      title: '生效星期',
      dataIndex: 'weekday_mask',
      key: 'weekday_mask',
      width: 160,
      render: (v: number) => <Tag color="blue">{weekdayMaskToLabels(v)}</Tag>,
    },
    {
      title: '时间窗',
      key: 'time_window',
      width: 180,
      render: (_: unknown, r: DeliveryWindow) => (
        <Text strong>
          <ClockCircleOutlined />{' '}
          {r.earliest_time.slice(0, 5)} ～ {r.latest_time.slice(0, 5)}
        </Text>
      ),
    },
    {
      title: '容忍',
      dataIndex: 'grace_minutes',
      key: 'grace_minutes',
      width: 80,
      render: (v: number) => <Text>±{v} min</Text>,
    },
    {
      title: '自动拒收',
      dataIndex: 'auto_reject_on_late',
      key: 'auto_reject_on_late',
      width: 110,
      render: (v: boolean) =>
        v ? <Tag color="red">启用</Tag> : <Tag color="default">禁用</Tag>,
    },
    {
      title: '状态',
      key: 'status',
      width: 120,
      render: (_: unknown, r: DeliveryWindow) => (
        <Space direction="vertical" size={0}>
          {statusTag(r)}
          {r.approved_by && (
            <Text type="secondary" style={{ fontSize: 11 }}>
              {r.approved_at ? dayjs(r.approved_at).format('YYYY-MM-DD') : ''}
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: '创建人',
      dataIndex: 'created_by',
      key: 'created_by',
      width: 120,
      ellipsis: true,
      render: (v: string) => <Text type="secondary">{v}</Text>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      render: (_: unknown, r: DeliveryWindow) => (
        <Space>
          {!r.approved_by && !r.is_deleted && (
            <a style={{ color: '#52c41a' }} onClick={() => setApproveTarget(r)}>
              <CheckCircleOutlined /> 审批
            </a>
          )}
          {!r.is_deleted && (
            <a style={{ color: '#ff4d4f' }} onClick={() => handleDelete(r)}>
              删除
            </a>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Space style={{ marginBottom: 16, justifyContent: 'space-between', width: '100%' }}>
        <Title level={3} style={{ margin: 0 }}>
          供应商配送时间窗
        </Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={refresh} loading={loading}>
            刷新
          </Button>
          <Button
            icon={<AlertOutlined />}
            disabled={!selectedSupplierId}
            onClick={() => setCheckOpen(true)}
          >
            合规性检查
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            disabled={!selectedSupplierId}
            onClick={() => setCreateOpen(true)}
          >
            新建配送时间窗
          </Button>
        </Space>
      </Space>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="PRD-05 / Tier 1 食安：生鲜必须 4-7 点到货"
        description="违约自动写日志 + 扣 supplier_scoring.delivery_rate 分；P0 仅记录不自动拒收（auto_reject_on_late 字段保留待未来扩展）。"
      />

      {errMsg && (
        <Alert
          type="error"
          showIcon
          message="加载失败"
          description={errMsg}
          style={{ marginBottom: 16 }}
          closable
          onClose={() => setErrMsg(null)}
        />
      )}

      <Card style={{ marginBottom: 16 }}>
        <Space size="large" wrap>
          <Space>
            <Text type="secondary">供应商：</Text>
            <Select
              style={{ width: 240 }}
              placeholder="请选择供应商"
              loading={supplierLoading}
              value={selectedSupplierId}
              onChange={(v) => setSelectedSupplierId(v)}
              options={suppliers.map((s) => ({ label: s.name, value: s.id }))}
              showSearch
              optionFilterProp="label"
            />
          </Space>
          <Space>
            <Text type="secondary">范围：</Text>
            <Radio.Group
              value={onlyActive}
              onChange={(e) => setOnlyActive(e.target.value as 'all' | 'active')}
              buttonStyle="solid"
              size="small"
            >
              <Radio.Button value="all">全部（含草稿/已删）</Radio.Button>
              <Radio.Button value="active">仅生效中</Radio.Button>
            </Radio.Group>
          </Space>
          <Space>
            <Text type="secondary">当前操作员：</Text>
            <Text code>{currentUserId}</Text>
          </Space>
        </Space>
      </Card>

      <Card>
        <Table<DeliveryWindow>
          rowKey="id"
          dataSource={windows}
          columns={columns}
          loading={loading}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          locale={{
            emptyText: '该供应商暂无配送时间窗 — 点击「新建配送时间窗」录入',
          }}
        />
      </Card>

      {selectedSupplierId && (
        <>
          <CreateWindowModal
            supplierId={selectedSupplierId}
            open={createOpen}
            onClose={() => setCreateOpen(false)}
            onSuccess={refresh}
          />
          <CheckWindowModal
            supplierId={selectedSupplierId}
            open={checkOpen}
            onClose={() => setCheckOpen(false)}
          />
        </>
      )}
      <ApproveWindowModal
        window={approveTarget}
        currentUserId={currentUserId}
        open={!!approveTarget}
        onClose={() => setApproveTarget(null)}
        onSuccess={refresh}
      />
    </div>
  );
}

export default SupplierDeliveryWindowsPage;
