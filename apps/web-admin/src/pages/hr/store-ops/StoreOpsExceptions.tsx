/**
 * StoreOpsExceptions — 店长异常处理台
 * 域F · 组织人事 · 门店作战台
 *
 * 功能：
 *  1. 顶部统计条：迟到N人/未打卡N人/早退N人
 *  2. ProTable展示异常列表（迟到/未打卡/早退）
 *  3. 每行操作列：确认/标记已处理/备注
 *
 * API:
 *  GET  /api/v1/store-ops/anomalies?store_id=xxx&date=xxx
 *  POST /api/v1/store-ops/quick-action
 */

import { useEffect, useRef, useState } from 'react';
import {
  Button,
  Card,
  Col,
  DatePicker,
  message,
  Row,
  Select,
  Space,
  Statistic,
  Tag,
  Typography,
} from 'antd';
import {
  ModalForm,
  ProFormSelect,
  ProFormTextArea,
  ProTable,
} from '@ant-design/pro-components';
import type { ActionType, ProColumns } from '@ant-design/pro-components';
import {
  ExclamationCircleOutlined,
  ReloadOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import { txFetchData } from '../../../api';

const { Title } = Typography;

// ─── Design Token ────────────────────────────────────────────────────────────
const TX_PRIMARY = '#FF6B35';
const TX_SUCCESS = '#0F6E56';
const TX_WARNING = '#BA7517';
const TX_DANGER  = '#A32D2D';

// ─── Types ───────────────────────────────────────────────────────────────────

interface AnomalyRecord {
  id: string;
  employee_id: string;
  employee_name: string;
  anomaly_type: 'late' | 'absent' | 'early_leave';
  anomaly_time: string;
  detail: string;
  status: 'pending' | 'confirmed' | 'resolved';
}

interface AnomalySummary {
  late_count: number;
  absent_count: number;
  early_leave_count: number;
  items: AnomalyRecord[];
  total: number;
}

// ─── 枚举 ────────────────────────────────────────────────────────────────────

const ANOMALY_TYPE_MAP: Record<string, { label: string; color: string }> = {
  late:        { label: '迟到',   color: 'orange' },
  absent:      { label: '未打卡', color: 'red' },
  early_leave: { label: '早退',   color: 'gold' },
};

const ANOMALY_STATUS_MAP: Record<string, { label: string; color: string }> = {
  pending:   { label: '待处理', color: 'red' },
  confirmed: { label: '已确认', color: 'orange' },
  resolved:  { label: '已处理', color: 'green' },
};

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export default function StoreOpsExceptions() {
  const actionRef = useRef<ActionType>();
  const [storeId, setStoreId] = useState<string>('');
  const [date, setDate] = useState<Dayjs>(dayjs());
  const [stores, setStores] = useState<{ store_id: string; store_name: string }[]>([]);
  const [summary, setSummary] = useState<{ late: number; absent: number; early: number }>({
    late: 0,
    absent: 0,
    early: 0,
  });
  const [remarkTarget, setRemarkTarget] = useState<AnomalyRecord | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await txFetchData<{ store_id: string; store_name: string }[]>('/api/v1/org/stores');
        const list = res.data ?? [];
        setStores(list);
        if (list.length > 0) setStoreId(list[0].store_id);
      } catch {
        message.error('加载门店列表失败');
      }
    })();
  }, []);

  const handleQuickAction = async (id: string, action: 'confirm' | 'resolve', remark?: string) => {
    try {
      await txFetchData('/api/v1/store-ops/quick-action', {
        method: 'POST',
        body: JSON.stringify({ anomaly_id: id, action, remark }),
      });
      message.success(action === 'confirm' ? '已确认' : '已标记处理');
      actionRef.current?.reload();
    } catch {
      message.error('操作失败');
    }
  };

  const columns: ProColumns<AnomalyRecord>[] = [
    { title: '员工', dataIndex: 'employee_name', width: 100 },
    {
      title: '异常类型',
      dataIndex: 'anomaly_type',
      width: 100,
      valueEnum: {
        late:        { text: '迟到',   status: 'Warning' },
        absent:      { text: '未打卡', status: 'Error' },
        early_leave: { text: '早退',   status: 'Default' },
      },
      render: (_, r) => {
        const t = ANOMALY_TYPE_MAP[r.anomaly_type];
        return <Tag color={t?.color}>{t?.label}</Tag>;
      },
    },
    { title: '时间', dataIndex: 'anomaly_time', width: 120 },
    { title: '详情', dataIndex: 'detail', ellipsis: true },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (_, r) => {
        const s = ANOMALY_STATUS_MAP[r.status];
        return <Tag color={s?.color}>{s?.label}</Tag>;
      },
    },
    {
      title: '操作',
      width: 200,
      render: (_, r) => (
        <Space>
          {r.status === 'pending' && (
            <Button type="link" size="small" onClick={() => handleQuickAction(r.id, 'confirm')}>
              确认
            </Button>
          )}
          {r.status !== 'resolved' && (
            <Button type="link" size="small" onClick={() => handleQuickAction(r.id, 'resolve')}>
              标记已处理
            </Button>
          )}
          <Button type="link" size="small" onClick={() => setRemarkTarget(r)}>
            备注
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      {/* 顶部 */}
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            <ExclamationCircleOutlined style={{ color: TX_PRIMARY, marginRight: 8 }} />
            店长异常处理台
          </Title>
        </Col>
        <Col>
          <Space>
            <Select
              value={storeId}
              onChange={(v) => {
                setStoreId(v);
                actionRef.current?.reload();
              }}
              style={{ width: 200 }}
              placeholder="选择门店"
              options={stores.map((s) => ({ label: s.store_name, value: s.store_id }))}
            />
            <DatePicker
              value={date}
              onChange={(d) => {
                if (d) {
                  setDate(d);
                  actionRef.current?.reload();
                }
              }}
              allowClear={false}
            />
          </Space>
        </Col>
      </Row>

      {/* 统计条 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card>
            <Statistic
              title="迟到"
              value={summary.late}
              suffix="人"
              valueStyle={{ color: TX_WARNING }}
              prefix={<WarningOutlined />}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="未打卡"
              value={summary.absent}
              suffix="人"
              valueStyle={{ color: TX_DANGER }}
              prefix={<ExclamationCircleOutlined />}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="早退"
              value={summary.early}
              suffix="人"
              valueStyle={{ color: '#D4A017' }}
              prefix={<WarningOutlined />}
            />
          </Card>
        </Col>
      </Row>

      {/* 异常列表 */}
      <Card>
        <ProTable<AnomalyRecord>
          actionRef={actionRef}
          columns={columns}
          request={async (params) => {
            if (!storeId) return { data: [], total: 0, success: true };
            const res = await txFetchData<AnomalySummary>(
              `/api/v1/store-ops/anomalies?store_id=${storeId}&date=${date.format('YYYY-MM-DD')}`,
            );
            const d = res.data;
            if (d) {
              setSummary({
                late: d.late_count,
                absent: d.absent_count,
                early: d.early_leave_count,
              });
            }
            return {
              data: d?.items ?? [],
              total: d?.total ?? 0,
              success: true,
            };
          }}
          rowKey="id"
          search={false}
          options={{ reload: true }}
          pagination={{ pageSize: 20 }}
        />
      </Card>

      {/* 备注弹窗 */}
      <ModalForm
        title={`备注 — ${remarkTarget?.employee_name}`}
        open={!!remarkTarget}
        onOpenChange={(open) => {
          if (!open) setRemarkTarget(null);
        }}
        onFinish={async (values) => {
          if (!remarkTarget) return false;
          await handleQuickAction(remarkTarget.id, 'resolve', values.remark);
          setRemarkTarget(null);
          return true;
        }}
        width={420}
      >
        <ProFormTextArea name="remark" label="备注说明" rules={[{ required: true, message: '请输入备注' }]} />
      </ModalForm>
    </div>
  );
}
