/**
 * AttendanceDaily — 日考勤台账
 * 域F · 组织人事 · 考勤管理
 *
 * 功能：
 *  1. 日期选择器 + 门店选择器
 *  2. ProTable展示当日所有员工打卡记录
 *  3. 状态Tag颜色编码（normal绿/late橙/early_leave金/absent红）
 *
 * API:
 *  GET /api/v1/attendance/daily?store_id=xxx&date=YYYY-MM-DD
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
import { ProTable } from '@ant-design/pro-components';
import type { ActionType, ProColumns } from '@ant-design/pro-components';
import { FileTextOutlined } from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import { txFetch } from '../../../api';

const { Title } = Typography;
const TX_PRIMARY = '#FF6B35';

// ─── Types ───────────────────────────────────────────────────────────────────

interface DailyRecord {
  id: string;
  employee_id: string;
  employee_name: string;
  attendance_date: string;
  clock_in: string | null;
  clock_out: string | null;
  work_hours: number | null;
  status: 'normal' | 'late' | 'early_leave' | 'absent';
}

// ─── 枚举 ────────────────────────────────────────────────────────────────────

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  normal:      { label: '正常', color: 'green' },
  late:        { label: '迟到', color: 'orange' },
  early_leave: { label: '早退', color: 'gold' },
  absent:      { label: '缺勤', color: 'red' },
};

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export default function AttendanceDaily() {
  const actionRef = useRef<ActionType>();
  const [storeId, setStoreId] = useState<string>('');
  const [date, setDate] = useState<Dayjs>(dayjs());
  const [stores, setStores] = useState<{ store_id: string; store_name: string }[]>([]);

  useEffect(() => {
    (async () => {
      try {
        const res = await txFetch<{ store_id: string; store_name: string }[]>('/api/v1/org/stores');
        const list = res.data ?? [];
        setStores(list);
        if (list.length > 0) setStoreId(list[0].store_id);
      } catch {
        message.error('加载门店列表失败');
      }
    })();
  }, []);

  useEffect(() => {
    actionRef.current?.reload();
  }, [storeId, date]);

  const columns: ProColumns<DailyRecord>[] = [
    { title: '员工', dataIndex: 'employee_name', width: 100 },
    { title: '日期', dataIndex: 'attendance_date', width: 110 },
    { title: '上班打卡', dataIndex: 'clock_in', width: 100, render: (_, r) => r.clock_in ?? '-' },
    { title: '下班打卡', dataIndex: 'clock_out', width: 100, render: (_, r) => r.clock_out ?? '-' },
    {
      title: '工时(h)',
      dataIndex: 'work_hours',
      width: 80,
      render: (_, r) => (r.work_hours != null ? r.work_hours.toFixed(1) : '-'),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 80,
      render: (_, r) => {
        const s = STATUS_MAP[r.status];
        return <Tag color={s?.color}>{s?.label}</Tag>;
      },
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            <FileTextOutlined style={{ color: TX_PRIMARY, marginRight: 8 }} />
            日考勤台账
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
            <DatePicker value={date} onChange={(d) => d && setDate(d)} allowClear={false} />
          </Space>
        </Col>
      </Row>

      <Card>
        <ProTable<DailyRecord>
          actionRef={actionRef}
          columns={columns}
          request={async (params) => {
            if (!storeId) return { data: [], total: 0, success: true };
            const res = await txFetch<{ items: DailyRecord[]; total: number }>(
              `/api/v1/attendance/daily?store_id=${storeId}&date=${date.format('YYYY-MM-DD')}&page=${params.current ?? 1}&size=${params.pageSize ?? 20}`,
            );
            return {
              data: res.data?.items ?? [],
              total: res.data?.total ?? 0,
              success: true,
            };
          }}
          rowKey="id"
          search={false}
          options={{ reload: true }}
          pagination={{ pageSize: 20 }}
        />
      </Card>
    </div>
  );
}
