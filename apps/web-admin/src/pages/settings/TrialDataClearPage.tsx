/**
 * 试营业数据清除
 * 路由: /settings/trial-data-clear
 * 权限: 集团超级管理员
 * 终端: Admin（总部后台）
 */
import { useState, useEffect } from 'react';
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Tag,
  Typography,
  Divider,
  List,
} from 'antd';
import { ExclamationCircleOutlined, WarningOutlined } from '@ant-design/icons';
import { getToken } from '../../api/client';

const { Title, Text, Paragraph } = Typography;

// ─── 类型 ──────────────────────────────────────────────────────────────────

interface ClearRequest {
  request_id: string;
  status: 'pending' | 'approved' | 'rejected' | 'executed';
  reason: string;
  created_at: string;
  updated_at: string;
}

interface Store {
  id: string;
  name: string;
}

// ─── Mock 数据（API 不可用时降级） ──────────────────────────────────────────

const MOCK_STORES: Store[] = [
  { id: 'store-001', name: '尝在一起·河西万达店' },
  { id: 'store-002', name: '尝在一起·梅溪湖店' },
];

// ─── API 函数 ───────────────────────────────────────────────────────────────

const TENANT_ID = localStorage.getItem('tenantId') || 'demo-tenant';
const OPERATOR_ID = localStorage.getItem('operatorId') || 'demo-operator';

const headers = () => ({
  'Content-Type': 'application/json',
  Authorization: `Bearer ${getToken() || ''}`,
  'X-Tenant-ID': TENANT_ID,
  'X-Operator-ID': OPERATOR_ID,
});

async function fetchStores(): Promise<Store[]> {
  try {
    const res = await fetch('/api/v1/stores?size=100', { headers: headers() });
    if (!res.ok) throw new Error('stores fetch failed');
    const data = await res.json();
    return (data.data?.items ?? data.items ?? []) as Store[];
  } catch {
    return MOCK_STORES;
  }
}

async function fetchClearStatus(storeId: string): Promise<ClearRequest | null> {
  const res = await fetch(
    `/api/v1/ops/trial-data/status?store_id=${encodeURIComponent(storeId)}`,
    { headers: headers() },
  );
  if (!res.ok) throw new Error(await res.text());
  const body = await res.json();
  return body.data as ClearRequest | null;
}

async function submitClearRequest(storeId: string, reason: string): Promise<string> {
  const res = await fetch('/api/v1/ops/trial-data/request', {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({ store_id: storeId, reason }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '请求失败' }));
    throw new Error(err.detail ?? '提交失败');
  }
  const body = await res.json();
  return body.data.request_id as string;
}

async function executeClear(
  storeId: string,
  confirmStoreName: string,
  approvedRequestId: string,
): Promise<void> {
  const res = await fetch('/api/v1/ops/trial-data/execute', {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify({
      store_id: storeId,
      confirm_store_name: confirmStoreName,
      approved_request_id: approvedRequestId,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '执行失败' }));
    throw new Error(err.detail ?? '执行失败');
  }
}

// ─── 状态标签 ───────────────────────────────────────────────────────────────

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  pending: { label: '待审批', color: 'orange' },
  approved: { label: '已审批', color: 'green' },
  rejected: { label: '已拒绝', color: 'red' },
  executed: { label: '已执行', color: 'default' },
};

// ─── 清除范围常量 ───────────────────────────────────────────────────────────

const WILL_CLEAR = [
  '订单记录（orders / order_items）',
  '支付记录（payments）',
  '日清日结报告（daily_settlements / shift_reports）',
  '押金记录（biz_deposits）',
  '存酒记录（wine_storage_records）',
  '盘点记录（stocktake_records）',
];

const WILL_KEEP = [
  '菜品档案（菜单/分类/BOM配方）',
  '员工档案（员工信息/角色/排班模板）',
  '桌位配置',
  '会员基础信息（手机号/姓名/会员等级）',
  '门店配置参数',
];

// ─── 页面组件 ───────────────────────────────────────────────────────────────

export function TrialDataClearPage() {
  const [stores, setStores] = useState<Store[]>([]);
  const [selectedStoreId, setSelectedStoreId] = useState<string | null>(null);
  const [clearStatus, setClearStatus] = useState<ClearRequest | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);

  // 申请表单
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState<string | null>(null);

  // 最终确认弹窗
  const [confirmVisible, setConfirmVisible] = useState(false);
  const [confirmNameInput, setConfirmNameInput] = useState('');
  const [executing, setExecuting] = useState(false);
  const [executeError, setExecuteError] = useState<string | null>(null);

  // 加载门店列表
  useEffect(() => {
    fetchStores().then(setStores).catch(() => setStores(MOCK_STORES));
  }, []);

  // 选择门店后加载申请状态
  useEffect(() => {
    if (!selectedStoreId) {
      setClearStatus(null);
      return;
    }
    setStatusLoading(true);
    fetchClearStatus(selectedStoreId)
      .then(setClearStatus)
      .catch(() => setClearStatus(null))
      .finally(() => setStatusLoading(false));
  }, [selectedStoreId]);

  const selectedStore = stores.find((s) => s.id === selectedStoreId);

  const handleSubmitRequest = async (values: { store_id: string; reason: string }) => {
    setSubmitting(true);
    setSubmitError(null);
    setSubmitSuccess(null);
    try {
      const requestId = await submitClearRequest(values.store_id, values.reason);
      setSubmitSuccess(`申请已提交（ID: ${requestId}），等待集团审批`);
      form.resetFields(['reason']);
      // 刷新状态
      const status = await fetchClearStatus(values.store_id);
      setClearStatus(status);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : '提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleExecuteConfirm = async () => {
    if (!selectedStore || !clearStatus) return;
    if (confirmNameInput.trim() !== selectedStore.name.trim()) {
      setExecuteError(`门店名称不匹配，请输入"${selectedStore.name}"`);
      return;
    }
    setExecuting(true);
    setExecuteError(null);
    try {
      await executeClear(selectedStoreId!, selectedStore.name, clearStatus.request_id);
      setConfirmVisible(false);
      setConfirmNameInput('');
      Modal.success({
        title: '清除完成',
        content: '试营业数据已成功清除，档案数据已保留。',
      });
      // 刷新状态
      const status = await fetchClearStatus(selectedStoreId!);
      setClearStatus(status);
    } catch (err) {
      setExecuteError(err instanceof Error ? err.message : '执行失败');
    } finally {
      setExecuting(false);
    }
  };

  return (
    <div style={{ padding: '24px', maxWidth: 800 }}>
      <Title level={3}>试营业数据清除</Title>

      {/* 危险操作警示横幅 */}
      <Alert
        type="error"
        showIcon
        icon={<WarningOutlined />}
        message="危险操作警告"
        description={
          <span>
            <strong>此操作不可撤销！</strong>
            清除后交易数据将永久软删除，即使是管理员也无法通过系统界面恢复。
            档案数据（菜品/员工/桌位）将完整保留。
            <br />
            <strong>仅限试营业阶段正式开业前使用。</strong>
          </span>
        }
        style={{ marginBottom: 24 }}
      />

      {/* 清除范围说明 */}
      <Card
        title="清除范围说明"
        size="small"
        style={{ marginBottom: 24 }}
      >
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <div>
            <Text type="danger" strong>
              <ExclamationCircleOutlined style={{ marginRight: 6 }} />
              将被清除的数据
            </Text>
            <List
              size="small"
              dataSource={WILL_CLEAR}
              renderItem={(item) => (
                <List.Item style={{ padding: '4px 0', color: '#A32D2D' }}>
                  · {item}
                </List.Item>
              )}
            />
          </div>
          <div>
            <Text type="success" strong>
              将保留的档案数据
            </Text>
            <List
              size="small"
              dataSource={WILL_KEEP}
              renderItem={(item) => (
                <List.Item style={{ padding: '4px 0', color: '#0F6E56' }}>
                  · {item}
                </List.Item>
              )}
            />
          </div>
        </div>
        <Divider style={{ margin: '12px 0' }} />
        <Text type="secondary" style={{ fontSize: 12 }}>
          所有清除均使用软删除（is_deleted=True），数据保留在数据库中可供合规审计，但不会在系统界面显示。
          同一门店 30 天内仅允许执行一次清除。
        </Text>
      </Card>

      {/* 申请表单 */}
      <Card title="提交清除申请" style={{ marginBottom: 24 }}>
        {submitError && (
          <Alert type="error" message={submitError} showIcon style={{ marginBottom: 16 }} closable />
        )}
        {submitSuccess && (
          <Alert type="success" message={submitSuccess} showIcon style={{ marginBottom: 16 }} closable />
        )}
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSubmitRequest}
          onValuesChange={(changed) => {
            if (changed.store_id) setSelectedStoreId(changed.store_id);
          }}
        >
          <Form.Item
            name="store_id"
            label="选择门店"
            rules={[{ required: true, message: '请选择目标门店' }]}
          >
            <Select
              placeholder="请选择要清除数据的门店"
              options={stores.map((s) => ({ label: s.name, value: s.id }))}
              loading={stores.length === 0}
              style={{ width: '100%' }}
            />
          </Form.Item>

          <Form.Item
            name="reason"
            label="清除原因"
            rules={[
              { required: true, message: '请填写清除原因' },
              { min: 5, message: '原因不少于5个字' },
            ]}
          >
            <Input.TextArea
              rows={3}
              placeholder="如：试营业阶段结束，正式开业前清除测试数据"
              maxLength={200}
              showCount
            />
          </Form.Item>

          <Form.Item>
            <Button
              type="primary"
              danger
              htmlType="submit"
              loading={submitting}
              disabled={!selectedStoreId}
            >
              提交清除申请
            </Button>
          </Form.Item>
        </Form>
      </Card>

      {/* 审批状态 */}
      {selectedStoreId && (
        <Card title="申请状态" loading={statusLoading} style={{ marginBottom: 24 }}>
          {clearStatus ? (
            <Space direction="vertical" style={{ width: '100%' }}>
              <div>
                <Text type="secondary">申请 ID：</Text>{' '}
                <Text code>{clearStatus.request_id}</Text>
              </div>
              <div>
                <Text type="secondary">状态：</Text>{' '}
                <Tag color={STATUS_MAP[clearStatus.status]?.color ?? 'default'}>
                  {STATUS_MAP[clearStatus.status]?.label ?? clearStatus.status}
                </Tag>
              </div>
              <div>
                <Text type="secondary">原因：</Text>{' '}
                <Text>{clearStatus.reason}</Text>
              </div>
              <div>
                <Text type="secondary">提交时间：</Text>{' '}
                <Text>{clearStatus.created_at?.slice(0, 19).replace('T', ' ')}</Text>
              </div>

              {clearStatus.status === 'approved' && (
                <>
                  <Alert
                    type="warning"
                    showIcon
                    message="申请已审批通过，可执行清除"
                    description="点击下方按钮后，系统将要求你输入门店名称以二次确认。"
                    style={{ marginTop: 12 }}
                  />
                  <Button
                    danger
                    type="primary"
                    size="large"
                    icon={<ExclamationCircleOutlined />}
                    onClick={() => {
                      setConfirmNameInput('');
                      setExecuteError(null);
                      setConfirmVisible(true);
                    }}
                    style={{ marginTop: 8 }}
                  >
                    确认执行清除（危险）
                  </Button>
                </>
              )}
            </Space>
          ) : (
            <Text type="secondary">该门店暂无清除申请记录</Text>
          )}
        </Card>
      )}

      {/* 最终确认弹窗 */}
      <Modal
        open={confirmVisible}
        title={
          <span style={{ color: '#A32D2D' }}>
            <WarningOutlined style={{ marginRight: 8 }} />
            最终确认：执行试营业数据清除
          </span>
        }
        onCancel={() => {
          if (!executing) {
            setConfirmVisible(false);
            setConfirmNameInput('');
            setExecuteError(null);
          }
        }}
        footer={
          <Space>
            <Button onClick={() => setConfirmVisible(false)} disabled={executing}>
              取消
            </Button>
            <Button
              danger
              type="primary"
              loading={executing}
              disabled={confirmNameInput.trim() !== (selectedStore?.name ?? '')}
              onClick={handleExecuteConfirm}
            >
              确认执行（危险）
            </Button>
          </Space>
        }
        destroyOnClose
      >
        <Alert
          type="error"
          showIcon
          message="此操作执行后无法撤销"
          style={{ marginBottom: 16 }}
        />
        <Paragraph>
          你即将清除门店 <Text strong>{selectedStore?.name}</Text> 的全部试营业交易数据。
        </Paragraph>
        <Paragraph>
          请在下方输入框中输入门店名称以确认：
        </Paragraph>
        <Input
          placeholder={`请输入：${selectedStore?.name ?? ''}`}
          value={confirmNameInput}
          onChange={(e) => {
            setConfirmNameInput(e.target.value);
            setExecuteError(null);
          }}
          size="large"
          status={
            confirmNameInput && confirmNameInput !== selectedStore?.name ? 'error' : undefined
          }
        />
        {executeError && (
          <Alert
            type="error"
            message={executeError}
            showIcon
            style={{ marginTop: 12 }}
          />
        )}
        <Text type="secondary" style={{ display: 'block', marginTop: 12, fontSize: 12 }}>
          只有完全匹配门店名称，"确认执行"按钮才会激活。
        </Text>
      </Modal>
    </div>
  );
}

export default TrialDataClearPage;
