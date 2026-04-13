/**
 * AttendanceAnomalies — 考勤异常
 * 域F · 组织人事 · 考勤管理
 *
 * 功能：
 *  1. 日期范围选择 + 门店选择 + 异常类型筛选
 *  2. ProTable展示异常记录（日期/姓名/类型/原因/处理状态）
 *  3. 操作列：调整考勤（ModalForm修改打卡时间+备注）
 *
 * API:
 *  GET /api/v1/attendance/anomalies?store_id=xxx&start_date=xxx&end_date=xxx
 */

import { useEffect, useRef, useState } from 'react';
import {
  Card,
  Col,
  DatePicker,
  message,
  Row,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd';
import {
  ModalForm,
  ProFormText,
  ProFormTextArea,
  ProFormTimePicker,
  ProTable,
} from '@ant-design/pro-components';
import type { ActionType, ProColumns } from '@ant-design/pro-components';
import { WarningOutlined } from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import { txFetchData } from '../../../api';

const { Title } = Typography;
const { RangePicker } = DatePicker;
const TX_PRIMARY = '#FF6B35';

// ─── Types ───────────────────────────────────────────────────────────────────

interface AnomalyRecord {
  id: string;
  employee_id: string;
  employee_name: string;
  attendance_date: string;
  anomaly_type: 'late' | 'early_leave' | 'absent' | 'missing_clock';
  reason: string;
  status: 'pending' | 'adjusted' | 'dismissed';
}

// ─── 枚举 ────────────────────────────────────────────────────────────────────

const ANOMALY_TYPE_MAP: Record<string, { label: string; color: string }> = {
  late:          { label: '迟到',     color: 'orange' },
  early_leave:   { label: '早退',     color: 'gold' },
  absent:        { label: '缺勤',     color: 'red' },
  missing_clock: { label: '漏打卡',   color: 'volcano' },
};

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  pending:   { label: '待处理', color: 'red' },
  adjusted:  { label: '已调整', color: 'green' },
  dismissed: { label: '已驳回', color: 'default' },
};

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export default function AttendanceAnomalies() {
  const actionRef = useRef<ActionType>();
  const [storeId, setStoreId] = useState<string>('');
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs]>([
    dayjs().subtract(7, 'day'),
    dayjs(),
  ]);
  const [stores, setStores] = useState<{ store_id: string; store_name: string }[]>([]);
  const [adjustTarget, setAdjustTarget] = useState<AnomalyRecord | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await txFetchData<{ store_id: string; store_name: string }[]>('/api/v1/org/stores');
        const list = res ?? [];
        setStores(list);
        if (list.length > 0) setStoreId(list[0].store_id);
      } catch {
        message.error('加载门店列表失败');
      }
    })();
  }, []);

  useEffect(() => {
    actionRef.current?.reload();
  }, [storeId, dateRange]);

  const columns: ProColumns<AnomalyRecord>[] = [
    { title: '日期', dataIndex: 'attendance_date', width: 110 },
    { title: '员工', dataIndex: 'employee_name', width: 100 },
    {
      title: '异常类型',
      dataIndex: 'anomaly_type',
      width: 100,
      valueEnum: {
        late:          { text: '迟到',   status: 'Warning' },
        early_leave:   { text: '早退',   status: 'Default' },
        absent:        { text: '缺勤',   status: 'Error' },
        missing_clock: { text: '漏打卡', status: 'Error' },
      },
      render: (_, r) => {
        const t = ANOMALY_TYPE_MAP[r.anomaly_type];
        return <Tag color={t?.color}>{t?.label}</Tag>;
      },
    },
    { title: '原因', dataIndex: 'reason', ellipsis: true },
    {
      title: '处理状态',
      dataIndex: 'status',
      width: 90,
      render: (_, r) => {
        const s = STATUS_MAP[r.status];
        return <Tag color={s?.color}>{s?.label}</Tag>;
      },
    },
    {
      title: '操作',
      width: 120,
      render: (_, r) =>
        r.status === 'pending' ? (
          <a onClick={() => setAdjustTarget(r)}>调整考勤</a>
        ) : (
          <span style={{ color: '#999' }}>-</span>
        ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            <WarningOutlined style={{ color: TX_PRIMARY, marginRight: 8 }} />
            考勤异常
          </Title>
        </Col>
        <Col>
          <Space>
            <Select
              value={storeId}
              onChange={setStoreId}
              style={{ width: 200 }}
              placeholder="选择门店"
              options={stores.map((s) => ({ label: s.store_name, value: s.store_id }))}
            />
            <RangePicker
              value={dateRange}
              onChange={(dates) => {
                if (dates && dates[0] && dates[1]) {
                  setDateRange([dates[0], dates[1]]);
                }
              }}
            />
          </Space>
        </Col>
      </Row>

      <Card>
        <ProTable<AnomalyRecord>
          actionRef={actionRef}
          columns={columns}
          request={async (params) => {
            if (!storeId) return { data: [], total: 0, success: true };
            const res = await txFetchData<{ items: AnomalyRecord[]; total: number }>(
              `/api/v1/attendance/anomalies?store_id=${storeId}&start_date=${dateRange[0].format('YYYY-MM-DD')}&end_date=${dateRange[1].format('YYYY-MM-DD')}&page=${params.current ?? 1}&size=${params.pageSize ?? 20}`,
            );
            return {
              data: res?.items ?? [],
              total: res?.total ?? 0,
              success: true,
            };
          }}
          rowKey="id"
          search={false}
          options={{ reload: true }}
          pagination={{ pageSize: 20 }}
        />
      </Card>

      {/* 调整考勤弹窗 */}
      <ModalForm
        title={`调整考勤 — ${adjustTarget?.employee_name} (${adjustTarget?.attendance_date})`}
        open={!!adjustTarget}
        onOpenChange={(open) => {
          if (!open) setAdjustTarget(null);
        }}
        onFinish={async (values) => {
          if (!adjustTarget) return false;
          try {
            await txFetchData(`/api/v1/attendance/records/${adjustTarget.id}/adjust`, {
              method: 'POST',
              body: JSON.stringify({
                new_clock_in: values.new_clock_in,
                new_clock_out: values.new_clock_out,
                remark: values.remark,
              }),
            });
            message.success('考勤调整成功');
            setAdjustTarget(null);
            actionRef.current?.reload();
            return true;
          } catch {
            message.error('考勤调整失败');
            return false;
          }
        }}
        width={480}
      >
        <ProFormTimePicker name="new_clock_in" label="调整上班时间" />
        <ProFormTimePicker name="new_clock_out" label="调整下班时间" />
        <ProFormTextArea
          name="remark"
          label="调整原因"
          rules={[{ required: true, message: '请输入调整原因' }]}
        />
      </ModalForm>
    </div>
  );
}
