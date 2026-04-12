/**
 * ScheduleStoreWeek — 门店周排班 (P0核心)
 * 域F · 组织人事 · HR Admin
 *
 * 功能：
 *  - 周导航（上一周/本周/下一周）
 *  - 7列日历网格，行=员工，列=日期，单元格=班次（显示时段+岗位）
 *  - 空格子点击弹出新建排班ModalForm
 *  - 已有格子点击弹出编辑/取消
 *  - 冲突单元格红色边框标记
 *  - 批量排班按钮
 *
 * API: GET  /api/v1/schedules/week?store_id=&start_date=
 *      POST /api/v1/schedules
 *      POST /api/v1/schedules/batch
 */

import { useCallback, useEffect, useState } from 'react';
import {
  Button,
  Card,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  LeftOutlined,
  RightOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import {
  ModalForm,
  ProFormSelect,
  ProFormTimePicker,
  ProFormText,
} from '@ant-design/pro-components';
import dayjs, { Dayjs } from 'dayjs';
import isoWeek from 'dayjs/plugin/isoWeek';
import { useSearchParams } from 'react-router-dom';
import { txFetchData } from '../../../api';

dayjs.extend(isoWeek);

const { Title, Text } = Typography;
const TX_PRIMARY = '#FF6B35';

// ─── Types ───────────────────────────────────────────────────────────────────

interface ShiftInfo {
  schedule_id: string;
  shift_type: string;
  shift_start: string;
  shift_end: string;
  role?: string;
  has_conflict?: boolean;
}

interface EmployeeWeekRow {
  employee_id: string;
  employee_name: string;
  shifts: Record<string, ShiftInfo | null>;
}

const DAY_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];

const SHIFT_COLORS: Record<string, string> = {
  morning: '#faad14',
  afternoon: '#1890ff',
  evening: '#722ed1',
  off: '#d9d9d9',
};

const SHIFT_LABELS: Record<string, string> = {
  morning: '早班',
  afternoon: '中班',
  evening: '晚班',
  off: '休息',
};

// ─── Component ───────────────────────────────────────────────────────────────

export default function ScheduleStoreWeek() {
  const [searchParams] = useSearchParams();
  const storeId = searchParams.get('store_id') ?? '';
  const [weekStart, setWeekStart] = useState<Dayjs>(() => dayjs().startOf('isoWeek'));
  const [rows, setRows] = useState<EmployeeWeekRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [messageApi, contextHolder] = message.useMessage();

  // ─── 新建/编辑弹窗状态 ──────────────────────────────────────────────────

  const [modalVisible, setModalVisible] = useState(false);
  const [editTarget, setEditTarget] = useState<{
    employee_id: string;
    employee_name: string;
    date: string;
    existing?: ShiftInfo;
  } | null>(null);

  // ─── 加载数据 ────────────────────────────────────────────────────────────

  const fetchWeek = useCallback(async () => {
    if (!storeId) return;
    setLoading(true);
    try {
      const res = await txFetchData(
        `/api/v1/schedules/week?store_id=${storeId}&start_date=${weekStart.format('YYYY-MM-DD')}`,
      ) as { ok: boolean; data: { employees: EmployeeWeekRow[] } };
      if (res.ok) {
        setRows(res.data.employees ?? []);
      }
    } catch { /* fallback */ }
    setLoading(false);
  }, [storeId, weekStart]);

  useEffect(() => {
    fetchWeek();
  }, [fetchWeek]);

  // ─── 周日期列表 ──────────────────────────────────────────────────────────

  const weekDates = Array.from({ length: 7 }, (_, i) => weekStart.add(i, 'day'));

  // ─── Table Columns ──────────────────────────────────────────────────────

  const tableColumns = [
    {
      title: '员工',
      dataIndex: 'employee_name',
      width: 100,
      fixed: 'left' as const,
    },
    ...weekDates.map((date, idx) => ({
      title: `${DAY_LABELS[idx]} ${date.format('MM-DD')}`,
      key: date.format('YYYY-MM-DD'),
      width: 130,
      render: (_: unknown, row: EmployeeWeekRow) => {
        const dateStr = date.format('YYYY-MM-DD');
        const shift = row.shifts[dateStr];
        if (!shift) {
          return (
            <Button
              type="dashed"
              size="small"
              icon={<PlusOutlined />}
              onClick={() => {
                setEditTarget({
                  employee_id: row.employee_id,
                  employee_name: row.employee_name,
                  date: dateStr,
                });
                setModalVisible(true);
              }}
              style={{ width: '100%' }}
            >
              排班
            </Button>
          );
        }
        return (
          <Tag
            color={SHIFT_COLORS[shift.shift_type] ?? '#1890ff'}
            style={{
              cursor: 'pointer',
              width: '100%',
              textAlign: 'center',
              border: shift.has_conflict ? '2px solid #ff4d4f' : undefined,
            }}
            onClick={() => {
              setEditTarget({
                employee_id: row.employee_id,
                employee_name: row.employee_name,
                date: dateStr,
                existing: shift,
              });
              setModalVisible(true);
            }}
          >
            {SHIFT_LABELS[shift.shift_type] ?? shift.shift_type}
            <br />
            <span style={{ fontSize: 11 }}>{shift.shift_start}-{shift.shift_end}</span>
          </Tag>
        );
      },
    })),
  ];

  // ─── 创建/编辑排班 ──────────────────────────────────────────────────────

  const handleSubmitShift = async (values: Record<string, unknown>) => {
    if (!editTarget) return false;
    try {
      const payload = {
        store_id: storeId,
        employee_id: editTarget.employee_id,
        date: editTarget.date,
        ...values,
      };
      const res = await txFetchData('/api/v1/schedules', {
        method: 'POST',
        body: JSON.stringify(payload),
      }) as { ok: boolean };
      if (res.ok) {
        messageApi.success('排班保存成功');
        fetchWeek();
        setModalVisible(false);
        return true;
      }
      messageApi.error('保存失败');
    } catch {
      messageApi.error('保存失败');
    }
    return false;
  };

  return (
    <div style={{ padding: 24 }}>
      {contextHolder}
      <Title level={4}>门店周排班</Title>

      {/* ── 周导航 ── */}
      <Card style={{ marginBottom: 16 }}>
        <Space>
          <Button icon={<LeftOutlined />} onClick={() => setWeekStart((w) => w.subtract(7, 'day'))}>
            上一周
          </Button>
          <Button onClick={() => setWeekStart(dayjs().startOf('isoWeek'))}>本周</Button>
          <Button onClick={() => setWeekStart((w) => w.add(7, 'day'))}>
            下一周 <RightOutlined />
          </Button>
          <Text strong style={{ marginLeft: 16 }}>
            {weekStart.format('YYYY-MM-DD')} ~ {weekStart.add(6, 'day').format('YYYY-MM-DD')}
          </Text>
          <ModalForm
            title="批量排班"
            trigger={
              <Button
                type="primary"
                icon={<PlusOutlined />}
                style={{ marginLeft: 24, backgroundColor: TX_PRIMARY, borderColor: TX_PRIMARY }}
              >
                批量排班
              </Button>
            }
            onFinish={async (values) => {
              try {
                const res = await txFetchData('/api/v1/schedules/batch', {
                  method: 'POST',
                  body: JSON.stringify({ store_id: storeId, ...values }),
                }) as { ok: boolean };
                if (res.ok) {
                  messageApi.success('批量排班成功');
                  fetchWeek();
                  return true;
                }
              } catch { /* empty */ }
              messageApi.error('批量排班失败');
              return false;
            }}
            modalProps={{ destroyOnClose: true }}
          >
            <ProFormSelect
              name="shift_type"
              label="班次模板"
              rules={[{ required: true }]}
              options={[
                { label: '早班 06:00-14:00', value: 'morning' },
                { label: '中班 10:00-18:00', value: 'afternoon' },
                { label: '晚班 14:00-22:00', value: 'evening' },
                { label: '休息', value: 'off' },
              ]}
            />
            <ProFormSelect
              name="employee_ids"
              label="选择员工"
              mode="multiple"
              rules={[{ required: true }]}
              request={async () => {
                try {
                  const res = await txFetchData(`/api/v1/org/employees?store_id=${storeId}&page=1&size=200`) as {
                    ok: boolean;
                    data: { items: { id: string; name: string }[] };
                  };
                  if (res.ok) return res.data.items.map((e) => ({ label: e.name, value: e.id }));
                } catch { /* empty */ }
                return [];
              }}
            />
            <ProFormText name="start_date" label="开始日期" placeholder="YYYY-MM-DD" rules={[{ required: true }]} />
            <ProFormText name="end_date" label="结束日期" placeholder="YYYY-MM-DD" rules={[{ required: true }]} />
          </ModalForm>
        </Space>
      </Card>

      {/* ── 周排班网格 ── */}
      <Table
        dataSource={rows}
        columns={tableColumns}
        rowKey="employee_id"
        loading={loading}
        pagination={false}
        scroll={{ x: 1100 }}
        bordered
        size="small"
      />

      {/* ── 新建/编辑弹窗 ── */}
      <ModalForm
        title={editTarget?.existing ? '编辑排班' : '新建排班'}
        open={modalVisible}
        onOpenChange={setModalVisible}
        onFinish={handleSubmitShift}
        modalProps={{ destroyOnClose: true }}
      >
        <ProFormText label="员工" initialValue={editTarget?.employee_name} disabled />
        <ProFormText label="日期" initialValue={editTarget?.date} disabled />
        <ProFormSelect
          name="shift_type"
          label="班次"
          initialValue={editTarget?.existing?.shift_type}
          rules={[{ required: true }]}
          options={[
            { label: '早班', value: 'morning' },
            { label: '中班', value: 'afternoon' },
            { label: '晚班', value: 'evening' },
            { label: '休息', value: 'off' },
          ]}
        />
        <ProFormTimePicker name="shift_start" label="开始时间" initialValue={editTarget?.existing?.shift_start} />
        <ProFormTimePicker name="shift_end" label="结束时间" initialValue={editTarget?.existing?.shift_end} />
        <ProFormSelect name="role" label="岗位" initialValue={editTarget?.existing?.role} options={[
          { label: '服务员', value: 'waiter' },
          { label: '厨师', value: 'chef' },
          { label: '收银员', value: 'cashier' },
          { label: '店长', value: 'manager' },
        ]} />
      </ModalForm>
    </div>
  );
}
