/**
 * WineStoragePage — 存酒台账管理（总部后台）
 * 路由：/wine-storage
 * 终端：Admin（React 18 + TypeScript + Ant Design 5.x + ProComponents）
 *
 * 功能：
 *   - 顶部统计卡片（总存酒数 | 总价值 | 即将过期<7天 | 本月新存）
 *   - ProTable 主体表格（全字段 + 状态标签 + 操作列）
 *   - 取酒弹窗 / 续存弹窗 / 核销弹窗 / 转台弹窗 / 新增存酒表单
 */
import { useRef, useState } from 'react';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormDatePicker,
  ProFormDigit,
  ProFormSelect,
  ProFormText,
  ProFormTextArea,
  ProTable,
  StatisticCard,
} from '@ant-design/pro-components';
import {
  Badge,
  Button,
  Descriptions,
  Drawer,
  Form,
  InputNumber,
  message,
  Modal,
  Space,
  Tag,
  Typography,
} from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { txFetchData } from '../../api';

const { Text } = Typography;

// ─── 类型定义 ────────────────────────────────────────────────────────────────

type WineStatus = 'stored' | 'partial' | 'taken' | 'expired' | 'written_off';

interface WineRecord {
  id: string;
  bottle_code: string;
  wine_name: string;
  wine_brand: string | null;
  wine_spec: string | null;
  unit: string;
  initial_quantity: number;
  remaining_quantity: number;
  unit_price_fen: number | null;
  table_id: string | null;
  table_name: string | null;
  member_id: string | null;
  member_name: string | null;
  member_phone: string | null;
  stored_at: string;
  expiry_date: string | null;
  days_until_expiry: number | null;
  expiry_warning: boolean;
  status: WineStatus;
  cabinet_position: string | null;
  notes: string | null;
}

interface WineSummary {
  total_active_records: number;
  total_remaining_quantity: number;
  total_value_fen: number;
  expiring_soon_count: number;   // days_until_expiry < 7
  this_month_new_count: number;
}

// ─── 状态标签配置 ─────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<WineStatus, { label: string; color: string }> = {
  stored:     { label: '存储中', color: 'blue' },
  partial:    { label: '部分取出', color: 'orange' },
  taken:      { label: '已取完', color: 'default' },
  expired:    { label: '已过期', color: 'red' },
  written_off: { label: '已核销', color: 'default' },
};

// ─── 工具函数 ────────────────────────────────────────────────────────────────

function fenToYuan(fen: number | null | undefined): string {
  if (fen == null) return '—';
  return `¥${(fen / 100).toFixed(2)}`;
}

// ─── 取酒弹窗 ────────────────────────────────────────────────────────────────

function TakeWineModal({
  record,
  onClose,
  onSuccess,
}: {
  record: WineRecord;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  const handleOk = async () => {
    const values = await form.validateFields();
    setLoading(true);
    try {
      await txFetchData(`/api/v1/wine-storage/${record.id}/take`, {
        method: 'POST',
        body: JSON.stringify({ quantity: values.quantity }),
      });
      message.success('取酒成功');
      onSuccess();
      onClose();
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '取酒失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title={`取酒 · ${record.wine_name}`}
      open
      onCancel={onClose}
      onOk={handleOk}
      confirmLoading={loading}
      okText="确认取酒"
      cancelText="取消"
      width={420}
    >
      <Descriptions column={1} size="small" style={{ marginBottom: 16 }}>
        <Descriptions.Item label="酒名">{record.wine_name}{record.wine_brand ? ` / ${record.wine_brand}` : ''}</Descriptions.Item>
        <Descriptions.Item label="当前剩余">
          <Text strong style={{ color: '#FF6B35' }}>
            {record.remaining_quantity} {record.unit}
          </Text>
        </Descriptions.Item>
        {record.table_name && <Descriptions.Item label="存放台位">{record.table_name}</Descriptions.Item>}
        {record.cabinet_position && <Descriptions.Item label="酒柜位置">{record.cabinet_position}</Descriptions.Item>}
      </Descriptions>
      <Form form={form} layout="vertical">
        <Form.Item
          name="quantity"
          label="本次取用数量"
          rules={[
            { required: true, message: '请输入取酒数量' },
            {
              validator: (_, value) => {
                if (value <= 0) return Promise.reject('数量必须大于0');
                if (value > record.remaining_quantity) return Promise.reject(`不能超过剩余数量 ${record.remaining_quantity}`);
                return Promise.resolve();
              },
            },
          ]}
          initialValue={1}
        >
          <InputNumber
            min={1}
            max={record.remaining_quantity}
            style={{ width: '100%' }}
            addonAfter={record.unit}
            size="large"
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}

// ─── 续存弹窗 ────────────────────────────────────────────────────────────────

function ExtendWineModal({
  record,
  onClose,
  onSuccess,
}: {
  record: WineRecord;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  const handleOk = async () => {
    const values = await form.validateFields();
    setLoading(true);
    try {
      await txFetchData(`/api/v1/wine-storage/${record.id}/extend`, {
        method: 'POST',
        body: JSON.stringify({ expiry_date: values.expiry_date }),
      });
      message.success('续存成功');
      onSuccess();
      onClose();
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '续存失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title={`续存 · ${record.wine_name}`}
      open
      onCancel={onClose}
      onOk={handleOk}
      confirmLoading={loading}
      okText="确认续存"
      cancelText="取消"
      width={420}
    >
      <Descriptions column={1} size="small" style={{ marginBottom: 16 }}>
        <Descriptions.Item label="当前有效期">
          {record.expiry_date
            ? <Text type={record.expiry_warning ? 'danger' : 'secondary'}>{record.expiry_date}</Text>
            : <Text type="secondary">未设置</Text>
          }
        </Descriptions.Item>
        <Descriptions.Item label="剩余数量">{record.remaining_quantity} {record.unit}</Descriptions.Item>
      </Descriptions>
      <Form form={form} layout="vertical">
        <Form.Item
          name="expiry_date"
          label="新的有效期"
          rules={[{ required: true, message: '请选择新的有效期' }]}
        >
          <ProFormDatePicker name="expiry_date" noStyle fieldProps={{ style: { width: '100%' } }} />
        </Form.Item>
      </Form>
    </Modal>
  );
}

// ─── 核销弹窗 ────────────────────────────────────────────────────────────────

function WriteOffModal({
  record,
  onClose,
  onSuccess,
}: {
  record: WineRecord;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  const handleOk = async () => {
    const values = await form.validateFields();
    setLoading(true);
    try {
      await txFetchData(`/api/v1/wine-storage/${record.id}/write-off`, {
        method: 'POST',
        body: JSON.stringify({
          reason: values.reason,
          authorized_by: values.authorized_by,
        }),
      });
      message.success('核销成功');
      onSuccess();
      onClose();
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '核销失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title={`核销 · ${record.wine_name}`}
      open
      onCancel={onClose}
      onOk={handleOk}
      confirmLoading={loading}
      okText="确认核销"
      okButtonProps={{ danger: true }}
      cancelText="取消"
      width={420}
    >
      <Descriptions column={1} size="small" style={{ marginBottom: 16 }}>
        <Descriptions.Item label="剩余数量">{record.remaining_quantity} {record.unit}</Descriptions.Item>
        {record.member_name && <Descriptions.Item label="关联会员">{record.member_name}</Descriptions.Item>}
      </Descriptions>
      <Form form={form} layout="vertical">
        <Form.Item
          name="reason"
          label="核销原因"
          rules={[{ required: true, message: '请输入核销原因' }]}
        >
          <ProFormTextArea
            name="reason"
            noStyle
            fieldProps={{ placeholder: '如：会员消费 / 活动赠送 / 会员申请退存...', rows: 3 }}
          />
        </Form.Item>
        <Form.Item
          name="authorized_by"
          label="授权人"
          rules={[{ required: true, message: '请输入授权人姓名' }]}
        >
          <ProFormText name="authorized_by" noStyle fieldProps={{ placeholder: '授权人姓名' }} />
        </Form.Item>
      </Form>
    </Modal>
  );
}

// ─── 转台弹窗 ────────────────────────────────────────────────────────────────

function TransferModal({
  record,
  onClose,
  onSuccess,
}: {
  record: WineRecord;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  const handleOk = async () => {
    const values = await form.validateFields();
    setLoading(true);
    try {
      await txFetchData(`/api/v1/wine-storage/${record.id}/transfer`, {
        method: 'POST',
        body: JSON.stringify({ new_table_id: values.new_table_id }),
      });
      message.success('转台成功');
      onSuccess();
      onClose();
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '转台失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title={`转台 · ${record.wine_name}`}
      open
      onCancel={onClose}
      onOk={handleOk}
      confirmLoading={loading}
      okText="确认转台"
      cancelText="取消"
      width={420}
    >
      <Descriptions column={1} size="small" style={{ marginBottom: 16 }}>
        <Descriptions.Item label="当前台位">{record.table_name || '未关联台位'}</Descriptions.Item>
      </Descriptions>
      <Form form={form} layout="vertical">
        <Form.Item
          name="new_table_id"
          label="目标台位ID"
          rules={[{ required: true, message: '请输入目标台位ID' }]}
        >
          <ProFormText name="new_table_id" noStyle fieldProps={{ placeholder: '输入目标台位ID' }} />
        </Form.Item>
      </Form>
    </Modal>
  );
}

// ─── 详情抽屉 ────────────────────────────────────────────────────────────────

function DetailDrawer({
  record,
  onClose,
}: {
  record: WineRecord;
  onClose: () => void;
}) {
  return (
    <Drawer
      title={`存酒详情 · ${record.bottle_code}`}
      placement="right"
      width={480}
      open
      onClose={onClose}
    >
      <Descriptions column={1} size="default" bordered>
        <Descriptions.Item label="酒名">{record.wine_name}</Descriptions.Item>
        <Descriptions.Item label="品牌">{record.wine_brand || '—'}</Descriptions.Item>
        <Descriptions.Item label="规格">{record.wine_spec || '—'}</Descriptions.Item>
        <Descriptions.Item label="单位">{record.unit}</Descriptions.Item>
        <Descriptions.Item label="存入数量">{record.initial_quantity}</Descriptions.Item>
        <Descriptions.Item label="剩余数量">
          <Text strong style={{ color: '#FF6B35' }}>{record.remaining_quantity}</Text>
        </Descriptions.Item>
        <Descriptions.Item label="存入价值">{fenToYuan(record.unit_price_fen ? record.unit_price_fen * record.initial_quantity : null)}</Descriptions.Item>
        <Descriptions.Item label="关联台位">{record.table_name || '—'}</Descriptions.Item>
        <Descriptions.Item label="关联会员">
          {record.member_name
            ? `${record.member_name}（${record.member_phone || '无电话'}）`
            : '—'}
        </Descriptions.Item>
        <Descriptions.Item label="存入日期">{record.stored_at?.slice(0, 10) || '—'}</Descriptions.Item>
        <Descriptions.Item label="有效期">
          {record.expiry_date
            ? <Tag color={record.expiry_warning ? 'red' : 'default'}>{record.expiry_date}</Tag>
            : '—'}
        </Descriptions.Item>
        <Descriptions.Item label="酒柜位置">{record.cabinet_position || '—'}</Descriptions.Item>
        <Descriptions.Item label="状态">
          <Tag color={STATUS_CONFIG[record.status]?.color ?? 'default'}>
            {STATUS_CONFIG[record.status]?.label ?? record.status}
          </Tag>
        </Descriptions.Item>
        <Descriptions.Item label="备注">{record.notes || '—'}</Descriptions.Item>
      </Descriptions>
    </Drawer>
  );
}

// ─── 主页面 ──────────────────────────────────────────────────────────────────

export function WineStoragePage() {
  const actionRef = useRef<ActionType>(null);
  const [summary, setSummary] = useState<WineSummary | null>(null);
  const [takeRecord, setTakeRecord] = useState<WineRecord | null>(null);
  const [extendRecord, setExtendRecord] = useState<WineRecord | null>(null);
  const [writeOffRecord, setWriteOffRecord] = useState<WineRecord | null>(null);
  const [transferRecord, setTransferRecord] = useState<WineRecord | null>(null);
  const [detailRecord, setDetailRecord] = useState<WineRecord | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  // 刷新表格 + 统计
  const reload = () => {
    actionRef.current?.reload();
    fetchSummary();
  };

  const fetchSummary = async () => {
    try {
      const data = await txFetchData<WineSummary>('/api/v1/wine-storage/stats/summary');
      setSummary(data);
    } catch {
      // 统计卡片加载失败不阻断主流程
    }
  };

  // ─── 列定义 ───────────────────────────────────────────────────────────────

  const columns: ProColumns<WineRecord>[] = [
    {
      title: '编号',
      dataIndex: 'bottle_code',
      width: 130,
      copyable: true,
      fixed: 'left',
    },
    {
      title: '酒名 / 品牌 / 规格',
      dataIndex: 'wine_name',
      width: 200,
      render: (_, r) => (
        <Space direction="vertical" size={2}>
          <Text strong>{r.wine_name}</Text>
          {r.wine_brand && <Text type="secondary" style={{ fontSize: 12 }}>{r.wine_brand}</Text>}
          {r.wine_spec && <Text type="secondary" style={{ fontSize: 12 }}>{r.wine_spec}</Text>}
        </Space>
      ),
    },
    {
      title: '关联台位',
      dataIndex: 'table_name',
      width: 100,
      render: (_, r) => r.table_name || <Text type="secondary">—</Text>,
    },
    {
      title: '关联会员',
      dataIndex: 'member_name',
      width: 120,
      render: (_, r) => r.member_name
        ? <span>{r.member_name}<br /><Text type="secondary" style={{ fontSize: 12 }}>{r.member_phone}</Text></span>
        : <Text type="secondary">—</Text>,
    },
    {
      title: '存入数量',
      dataIndex: 'initial_quantity',
      width: 90,
      search: false,
      render: (_, r) => `${r.initial_quantity} ${r.unit}`,
    },
    {
      title: '剩余数量',
      dataIndex: 'remaining_quantity',
      width: 90,
      search: false,
      render: (_, r) => (
        <Text strong style={{ color: r.remaining_quantity === 0 ? '#B4B2A9' : '#FF6B35' }}>
          {r.remaining_quantity} {r.unit}
        </Text>
      ),
    },
    {
      title: '存入日期',
      dataIndex: 'stored_at',
      width: 110,
      search: false,
      render: (_, r) => r.stored_at?.slice(0, 10) || '—',
      valueType: 'date',
    },
    {
      title: '有效期',
      dataIndex: 'expiry_date',
      width: 130,
      search: false,
      render: (_, r) => {
        if (!r.expiry_date) return <Text type="secondary">—</Text>;
        return (
          <Space size={4}>
            <Tag color={r.expiry_warning ? 'red' : 'default'}>{r.expiry_date}</Tag>
            {r.days_until_expiry !== null && r.days_until_expiry <= 7 && r.days_until_expiry >= 0 && (
              <Badge count={`${r.days_until_expiry}天`} color="#A32D2D" />
            )}
          </Space>
        );
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      valueType: 'select',
      valueEnum: {
        stored:      { text: '存储中', status: 'Processing' },
        partial:     { text: '部分取出', status: 'Warning' },
        taken:       { text: '已取完', status: 'Default' },
        expired:     { text: '已过期', status: 'Error' },
        written_off: { text: '已核销', status: 'Default' },
      },
      render: (_, r) => {
        const cfg = STATUS_CONFIG[r.status];
        return cfg ? <Tag color={cfg.color}>{cfg.label}</Tag> : r.status;
      },
    },
    {
      title: '操作',
      valueType: 'option',
      width: 220,
      fixed: 'right',
      render: (_, r) => [
        (r.status === 'stored' || r.status === 'partial') && (
          <a key="take" onClick={() => setTakeRecord(r)}>取酒</a>
        ),
        (r.status === 'stored' || r.status === 'partial') && (
          <a key="extend" onClick={() => setExtendRecord(r)}>续存</a>
        ),
        r.table_id && (r.status === 'stored' || r.status === 'partial') && (
          <a key="transfer" onClick={() => setTransferRecord(r)}>转台</a>
        ),
        (r.status === 'stored' || r.status === 'partial') && (
          <a key="writeoff" onClick={() => setWriteOffRecord(r)} style={{ color: '#A32D2D' }}>核销</a>
        ),
        <a key="detail" onClick={() => setDetailRecord(r)}>详情</a>,
      ].filter(Boolean),
    },
  ];

  return (
    <div style={{ padding: '0 24px 24px' }}>
      {/* 顶部统计卡片 */}
      <StatisticCard.Group
        style={{ marginBottom: 24, marginTop: 8 }}
        direction="row"
      >
        <StatisticCard
          statistic={{
            title: '总存酒数（有效）',
            value: summary?.total_active_records ?? '—',
            suffix: '条',
          }}
        />
        <StatisticCard
          statistic={{
            title: '总存酒价值',
            value: summary ? `¥${(summary.total_value_fen / 100).toFixed(0)}` : '—',
          }}
        />
        <StatisticCard
          statistic={{
            title: '即将过期（<7天）',
            value: summary?.expiring_soon_count ?? '—',
            suffix: '条',
            valueStyle: (summary?.expiring_soon_count ?? 0) > 0
              ? { color: '#A32D2D' }
              : undefined,
          }}
        />
        <StatisticCard
          statistic={{
            title: '本月新存',
            value: summary?.this_month_new_count ?? '—',
            suffix: '条',
          }}
        />
      </StatisticCard.Group>

      {/* 主体表格 */}
      <ProTable<WineRecord>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        scroll={{ x: 1400 }}
        request={async (params) => {
          try {
            const query = new URLSearchParams({
              page: String(params.current ?? 1),
              size: String(params.pageSize ?? 20),
              ...(params.status ? { status: params.status } : {}),
              ...(params.wine_name ? { wine_name: params.wine_name } : {}),
              ...(params.member_name ? { member_name: params.member_name } : {}),
            });
            const data = await txFetchData<{ items: WineRecord[]; total: number }>(
              `/api/v1/wine-storage?${query}`
            );
            // 顺便刷新统计
            void fetchSummary();
            return { data: data.items, total: data.total, success: true };
          } catch {
            return { data: [], total: 0, success: false };
          }
        }}
        search={{ labelWidth: 'auto' }}
        pagination={{ defaultPageSize: 20, showQuickJumper: true }}
        toolBarRender={() => [
          <Button
            key="create"
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setCreateOpen(true)}
          >
            新增存酒
          </Button>,
        ]}
        headerTitle="存酒台账"
      />

      {/* 操作弹窗 */}
      {takeRecord && (
        <TakeWineModal record={takeRecord} onClose={() => setTakeRecord(null)} onSuccess={reload} />
      )}
      {extendRecord && (
        <ExtendWineModal record={extendRecord} onClose={() => setExtendRecord(null)} onSuccess={reload} />
      )}
      {writeOffRecord && (
        <WriteOffModal record={writeOffRecord} onClose={() => setWriteOffRecord(null)} onSuccess={reload} />
      )}
      {transferRecord && (
        <TransferModal record={transferRecord} onClose={() => setTransferRecord(null)} onSuccess={reload} />
      )}
      {detailRecord && (
        <DetailDrawer record={detailRecord} onClose={() => setDetailRecord(null)} />
      )}

      {/* 新增存酒 ModalForm */}
      <ModalForm
        title="新增存酒"
        open={createOpen}
        onOpenChange={setCreateOpen}
        onFinish={async (values) => {
          try {
            await txFetchData('/api/v1/wine-storage', {
              method: 'POST',
              body: JSON.stringify({
                ...values,
                unit_price_fen: values.unit_price_yuan ? Math.round(values.unit_price_yuan * 100) : undefined,
              }),
            });
            message.success('存酒创建成功');
            reload();
            return true;
          } catch (e: unknown) {
            message.error(e instanceof Error ? e.message : '创建失败');
            return false;
          }
        }}
        width={560}
        modalProps={{ destroyOnClose: true }}
        submitter={{ searchConfig: { submitText: '确认存入', resetText: '取消' } }}
      >
        <ProFormText
          name="wine_name"
          label="酒名"
          rules={[{ required: true, message: '请输入酒名' }]}
          placeholder="如：茅台飞天 / 拉菲 2015"
        />
        <ProFormText name="wine_brand" label="品牌" placeholder="如：茅台 / Château Lafite" />
        <ProFormText name="wine_spec" label="规格" placeholder="如：500ml / 750ml×6" />
        <ProFormDigit
          name="quantity"
          label="数量"
          rules={[{ required: true, message: '请输入数量' }]}
          min={1}
          fieldProps={{ precision: 0 }}
        />
        <ProFormSelect
          name="unit"
          label="单位"
          options={['瓶', '箱', '支', '杯'].map(u => ({ label: u, value: u }))}
          initialValue="瓶"
          rules={[{ required: true }]}
        />
        <ProFormDigit
          name="unit_price_yuan"
          label="单瓶存入价格（元）"
          min={0}
          fieldProps={{ precision: 2 }}
          tooltip="用于计算存酒总价值"
        />
        <ProFormText
          name="table_id"
          label="关联台位ID（可选）"
          placeholder="输入台位ID"
        />
        <ProFormText
          name="member_id"
          label="关联会员ID（可选）"
          placeholder="输入会员ID或手机号搜索"
        />
        <ProFormDatePicker
          name="expiry_date"
          label="有效期（可选）"
          tooltip="到期前7天自动预警"
        />
        <ProFormText
          name="cabinet_position"
          label="酒柜位置（可选）"
          placeholder="如：A区-3层-5号"
        />
        <ProFormTextArea
          name="notes"
          label="备注（可选）"
          placeholder="特殊说明、存储要求等"
          fieldProps={{ rows: 2 }}
        />
      </ModalForm>
    </div>
  );
}

export default WineStoragePage;
