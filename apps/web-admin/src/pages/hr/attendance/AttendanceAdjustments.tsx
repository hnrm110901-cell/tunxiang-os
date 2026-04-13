/**
 * AttendanceAdjustments — 考勤调整
 * 域F · 组织人事 · 考勤管理
 *
 * 功能：
 *  1. ProTable展示可调整的考勤记录
 *  2. 操作列：调整（ModalForm：调整原因+新打卡时间）
 *  3. 调整记录审计日志展示
 *
 * API:
 *  GET  /api/v1/attendance/records?store_id=xxx&year=2026&month=4
 *  POST /api/v1/attendance/records/{id}/adjust
 */

import { useEffect, useRef, useState } from 'react';
import {
  Card,
  Col,
  DatePicker,
  Descriptions,
  Drawer,
  message,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import {
  ModalForm,
  ProFormTextArea,
  ProFormTimePicker,
  ProTable,
} from '@ant-design/pro-components';
import type { ActionType, ProColumns } from '@ant-design/pro-components';
import { EditOutlined } from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import { txFetchData } from '../../../api';

const { Title, Text } = Typography;
const TX_PRIMARY = '#FF6B35';

// ─── Types ───────────────────────────────────────────────────────────────────

interface AttendanceRecord {
  id: string;
  employee_id: string;
  employee_name: string;
  attendance_date: string;
  clock_in: string | null;
  clock_out: string | null;
  work_hours: number | null;
  status: 'normal' | 'late' | 'early_leave' | 'absent';
  adjusted: boolean;
  adjust_logs?: AdjustLog[];
}

interface AdjustLog {
  id: string;
  adjusted_at: string;
  adjusted_by: string;
  old_clock_in: string | null;
  old_clock_out: string | null;
  new_clock_in: string | null;
  new_clock_out: string | null;
  remark: string;
}

// ─── 枚举 ────────────────────────────────────────────────────────────────────

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  normal:      { label: '正常', color: 'green' },
  late:        { label: '迟到', color: 'orange' },
  early_leave: { label: '早退', color: 'gold' },
  absent:      { label: '缺勤', color: 'red' },
};

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export default function AttendanceAdjustments() {
  const actionRef = useRef<ActionType>();
  const [storeId, setStoreId] = useState<string>('');
  const [month, setMonth] = useState<Dayjs>(dayjs());
  const [stores, setStores] = useState<{ store_id: string; store_name: string }[]>([]);
  const [adjustTarget, setAdjustTarget] = useState<AttendanceRecord | null>(null);
  const [logTarget, setLogTarget] = useState<AttendanceRecord | null>(null);

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
  }, [storeId, month]);

  const columns: ProColumns<AttendanceRecord>[] = [
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
    {
      title: '已调整',
      dataIndex: 'adjusted',
      width: 80,
      render: (_, r) =>
        r.adjusted ? <Tag color="blue">已调整</Tag> : <Tag color="default">未调整</Tag>,
    },
    {
      title: '操作',
      width: 160,
      render: (_, r) => (
        <Space>
          <a onClick={() => setAdjustTarget(r)}>调整</a>
          {r.adjusted && <a onClick={() => setLogTarget(r)}>日志</a>}
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            <EditOutlined style={{ color: TX_PRIMARY, marginRight: 8 }} />
            考勤调整
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
            <DatePicker
              picker="month"
              value={month}
              onChange={(m) => m && setMonth(m)}
              allowClear={false}
            />
          </Space>
        </Col>
      </Row>

      <Card>
        <ProTable<AttendanceRecord>
          actionRef={actionRef}
          columns={columns}
          request={async (params) => {
            if (!storeId) return { data: [], total: 0, success: true };
            const res = await txFetchData<{ items: AttendanceRecord[]; total: number }>(
              `/api/v1/attendance/records?store_id=${storeId}&year=${month.year()}&month=${month.month() + 1}&page=${params.current ?? 1}&size=${params.pageSize ?? 20}`,
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

      {/* 调整弹窗 */}
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
        <ProFormTimePicker
          name="new_clock_in"
          label="调整上班时间"
          initialValue={adjustTarget?.clock_in}
        />
        <ProFormTimePicker
          name="new_clock_out"
          label="调整下班时间"
          initialValue={adjustTarget?.clock_out}
        />
        <ProFormTextArea
          name="remark"
          label="调整原因"
          rules={[{ required: true, message: '请输入调整原因' }]}
        />
      </ModalForm>

      {/* 审计日志Drawer */}
      <Drawer
        title={`调整日志 — ${logTarget?.employee_name} (${logTarget?.attendance_date})`}
        open={!!logTarget}
        onClose={() => setLogTarget(null)}
        width={520}
      >
        <Table
          dataSource={logTarget?.adjust_logs ?? []}
          rowKey="id"
          size="small"
          pagination={false}
          columns={[
            { title: '调整时间', dataIndex: 'adjusted_at', width: 140 },
            { title: '操作人', dataIndex: 'adjusted_by', width: 80 },
            {
              title: '变更',
              render: (_, r: AdjustLog) => (
                <div>
                  <div>
                    <Text type="secondary">上班：</Text>
                    <Text delete>{r.old_clock_in ?? '-'}</Text>
                    {' -> '}
                    <Text strong>{r.new_clock_in ?? '-'}</Text>
                  </div>
                  <div>
                    <Text type="secondary">下班：</Text>
                    <Text delete>{r.old_clock_out ?? '-'}</Text>
                    {' -> '}
                    <Text strong>{r.new_clock_out ?? '-'}</Text>
                  </div>
                </div>
              ),
            },
            { title: '原因', dataIndex: 'remark', ellipsis: true },
          ]}
        />
      </Drawer>
    </div>
  );
}
