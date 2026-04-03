/**
 * AttendancePage — 考勤管理
 * 域F · 组织人事 · HR Admin
 *
 * 功能：
 *  1. 今日全店考勤看板（在岗/已下班/未打卡统计 + 未打卡员工预警）
 *  2. 月度考勤 ProTable（筛选/列表/考勤调整 ModalForm）
 *  3. 月度汇总卡（选中员工后展示出勤/缺勤/迟到/总工时）
 *  4. 排班周视图 Tab（7列日历网格 + 新建排班 ModalForm）
 *
 * API:
 *  GET  /api/v1/attendance/today?store_id=
 *  GET  /api/v1/attendance/records?store_id=&year=&month=
 *  POST /api/v1/attendance/records/{id}/adjust
 *  GET  /api/v1/attendance/employee-summary?employee_id=&year=&month=
 *  GET  /api/v1/schedules/week?store_id=&week_start=
 *  POST /api/v1/schedules
 */

import { useEffect, useRef, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  DatePicker,
  Row,
  Select,
  Space,
  Statistic,
  Tabs,
  Tag,
  TimePicker,
  Typography,
  message,
} from 'antd';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormSelect,
  ProFormText,
  ProFormTextArea,
  ProFormTimePicker,
  ProTable,
} from '@ant-design/pro-components';
import dayjs, { Dayjs } from 'dayjs';
import isoWeek from 'dayjs/plugin/isoWeek';
import { txFetch } from '../../api';

dayjs.extend(isoWeek);

const { Title, Text } = Typography;

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface TodayStats {
  on_duty: number;
  off_duty: number;
  absent: number;
  absent_employees: { id: string; name: string }[];
}

interface AttendanceRecord {
  id: string;
  employee_id: string;
  employee_name: string;
  store_id: string;
  store_name?: string;
  attendance_date: string;
  clock_in: string | null;
  clock_out: string | null;
  work_hours: number | null;
  status: 'normal' | 'late' | 'early_leave' | 'absent';
}

interface AttendanceListResp {
  items: AttendanceRecord[];
  total: number;
}

interface EmployeeSummary {
  employee_id: string;
  employee_name: string;
  present_days: number;
  absent_days: number;
  late_count: number;
  total_hours: number;
}

interface WeekSchedule {
  employee_id: string;
  employee_name: string;
  shifts: Record<string, { start: string; end: string; role: string } | null>;
}

// ─── 枚举 ────────────────────────────────────────────────────────────────────

const STATUS_ENUM: Record<string, { label: string; color: string }> = {
  normal:      { label: '正常',   color: 'green'  },
  late:        { label: '迟到',   color: 'orange' },
  early_leave: { label: '早退',   color: 'gold'   },
  absent:      { label: '缺勤',   color: 'red'    },
};

const ROLE_OPTIONS = [
  { label: '收银员', value: 'cashier' },
  { label: '厨师',   value: 'chef'    },
  { label: '服务员', value: 'waiter'  },
  { label: '店长',   value: 'manager' },
];

// ─── 今日看板子组件 ───────────────────────────────────────────────────────────

function TodayBoard({ storeId }: { storeId: string }) {
  const [stats, setStats] = useState<TodayStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    if (!storeId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await txFetch<TodayStats>(
        `/api/v1/attendance/today?store_id=${storeId}`,
      );
      setStats(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载今日看板失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [storeId]);

  return (
    <Card
      title="今日全店考勤"
      extra={
        <Button icon={<ReloadOutlined />} size="small" onClick={load} loading={loading}>
          刷新
        </Button>
      }
      style={{ marginBottom: 16 }}
    >
      {error && (
        <Alert type="error" message={error} style={{ marginBottom: 12 }} showIcon />
      )}
      <Row gutter={24}>
        <Col span={8}>
          <Statistic
            title="在岗人数"
            value={stats?.on_duty ?? '-'}
            valueStyle={{ color: '#0F6E56' }}
          />
        </Col>
        <Col span={8}>
          <Statistic
            title="已下班"
            value={stats?.off_duty ?? '-'}
            valueStyle={{ color: '#888' }}
          />
        </Col>
        <Col span={8}>
          <Statistic
            title="未打卡"
            value={stats?.absent ?? '-'}
            valueStyle={{ color: '#A32D2D' }}
          />
        </Col>
      </Row>

      {stats && stats.absent_employees.length > 0 && (
        <Alert
          type="error"
          showIcon
          style={{ marginTop: 16 }}
          message={
            <span>
              <strong>未打卡员工：</strong>
              {stats.absent_employees.map((e) => (
                <Tag color="red" key={e.id} style={{ marginLeft: 4 }}>
                  {e.name}
                </Tag>
              ))}
            </span>
          }
        />
      )}
    </Card>
  );
}

// ─── 月度汇总卡子组件 ─────────────────────────────────────────────────────────

function EmployeeSummaryCard({
  employeeId,
  year,
  month,
}: {
  employeeId: string | null;
  year: number;
  month: number;
}) {
  const [summary, setSummary] = useState<EmployeeSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!employeeId) { setSummary(null); return; }
    txFetch<EmployeeSummary>(
      `/api/v1/attendance/employee-summary?employee_id=${employeeId}&year=${year}&month=${month}`,
    )
      .then(setSummary)
      .catch((err) => setError(err instanceof Error ? err.message : '加载汇总失败'));
  }, [employeeId, year, month]);

  if (!employeeId) return null;

  return (
    <Card title="员工月度汇总" size="small" style={{ marginBottom: 16 }}>
      {error && <Alert type="error" message={error} showIcon />}
      {summary && (
        <Row gutter={16}>
          <Col span={6}>
            <Statistic title="出勤天数" value={summary.present_days} suffix="天" />
          </Col>
          <Col span={6}>
            <Statistic
              title="缺勤天数"
              value={summary.absent_days}
              suffix="天"
              valueStyle={summary.absent_days > 0 ? { color: '#A32D2D' } : undefined}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="迟到次数"
              value={summary.late_count}
              suffix="次"
              valueStyle={summary.late_count > 0 ? { color: '#BA7517' } : undefined}
            />
          </Col>
          <Col span={6}>
            <Statistic title="总工时" value={summary.total_hours.toFixed(1)} suffix="小时" />
          </Col>
        </Row>
      )}
    </Card>
  );
}

// ─── 排班周视图子组件 ──────────────────────────────────────────────────────────

function WeekScheduleView({ storeId }: { storeId: string }) {
  const [weekStart, setWeekStart] = useState<Dayjs>(dayjs().startOf('isoWeek'));
  const [schedules, setSchedules] = useState<WeekSchedule[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    if (!storeId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await txFetch<{ items: WeekSchedule[] }>(
        `/api/v1/schedules/week?store_id=${storeId}&week_start=${weekStart.format('YYYY-MM-DD')}`,
      );
      setSchedules(data.items ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载排班失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [storeId, weekStart]);

  const weekDays = Array.from({ length: 7 }, (_, i) => weekStart.add(i, 'day'));

  return (
    <div>
      {error && <Alert type="error" message={error} showIcon style={{ marginBottom: 12 }} />}

      <Space style={{ marginBottom: 12 }} wrap>
        <Button onClick={() => setWeekStart(weekStart.subtract(1, 'week'))}>
          &lt; 上一周
        </Button>
        <Text strong>
          {weekStart.format('YYYY-MM-DD')} — {weekStart.add(6, 'day').format('YYYY-MM-DD')}
        </Text>
        <Button onClick={() => setWeekStart(weekStart.add(1, 'week'))}>
          下一周 &gt;
        </Button>
        <Button
          icon={<ReloadOutlined />}
          onClick={load}
          loading={loading}
        >
          刷新
        </Button>

        <ModalForm
          title="新建排班"
          trigger={
            <Button type="primary" icon={<PlusOutlined />}>
              新建排班
            </Button>
          }
          onFinish={async (values) => {
            try {
              await txFetch('/api/v1/schedules', {
                method: 'POST',
                body: JSON.stringify({
                  store_id: storeId,
                  employee_id: values.employee_id,
                  schedule_date: values.schedule_date,
                  shift_start: values.shift_start,
                  shift_end: values.shift_end,
                  role: values.role,
                }),
              });
              message.success('排班创建成功');
              load();
              return true;
            } catch (err) {
              message.error(err instanceof Error ? err.message : '创建失败');
              return false;
            }
          }}
        >
          <ProFormText
            name="employee_id"
            label="员工ID"
            rules={[{ required: true }]}
            placeholder="输入员工ID"
          />
          <ProFormText
            name="schedule_date"
            label="日期"
            rules={[{ required: true }]}
            placeholder="YYYY-MM-DD"
          />
          <ProFormTimePicker
            name="shift_start"
            label="开始时间"
            rules={[{ required: true }]}
            fieldProps={{ format: 'HH:mm' }}
          />
          <ProFormTimePicker
            name="shift_end"
            label="结束时间"
            rules={[{ required: true }]}
            fieldProps={{ format: 'HH:mm' }}
          />
          <ProFormSelect
            name="role"
            label="岗位"
            options={ROLE_OPTIONS}
            rules={[{ required: true }]}
          />
        </ModalForm>
      </Space>

      {/* 周视图网格 */}
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 800 }}>
          <thead>
            <tr>
              <th style={thStyle}>员工</th>
              {weekDays.map((d) => (
                <th key={d.format('YYYY-MM-DD')} style={thStyle}>
                  <div>{d.format('ddd')}</div>
                  <div style={{ fontWeight: 400, fontSize: 12, color: '#666' }}>
                    {d.format('MM/DD')}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {schedules.length === 0 && (
              <tr>
                <td colSpan={8} style={{ textAlign: 'center', padding: 32, color: '#999' }}>
                  {loading ? '加载中...' : '暂无排班数据'}
                </td>
              </tr>
            )}
            {schedules.map((emp) => (
              <tr key={emp.employee_id}>
                <td style={tdStyle}>
                  <Text strong>{emp.employee_name}</Text>
                </td>
                {weekDays.map((d) => {
                  const key = d.format('YYYY-MM-DD');
                  const shift = emp.shifts[key];
                  return (
                    <td key={key} style={tdStyle}>
                      {shift ? (
                        <Tag color="blue" style={{ fontSize: 11 }}>
                          {shift.start}–{shift.end}
                        </Tag>
                      ) : (
                        <Text type="secondary" style={{ fontSize: 12 }}>休</Text>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const thStyle: React.CSSProperties = {
  padding: '8px 12px',
  background: '#F8F7F5',
  border: '1px solid #e8e8e8',
  textAlign: 'center',
  fontWeight: 600,
};

const tdStyle: React.CSSProperties = {
  padding: '8px 12px',
  border: '1px solid #e8e8e8',
  textAlign: 'center',
  verticalAlign: 'middle',
};

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export function AttendancePage() {
  const actionRef = useRef<ActionType>();
  const [storeId, setStoreId] = useState<string>('');
  const [selectedYear, setSelectedYear] = useState(dayjs().year());
  const [selectedMonth, setSelectedMonth] = useState(dayjs().month() + 1);
  const [selectedEmployeeId, setSelectedEmployeeId] = useState<string | null>(null);
  const [adjustRecord, setAdjustRecord] = useState<AttendanceRecord | null>(null);
  const [adjustOpen, setAdjustOpen] = useState(false);

  const columns: ProColumns<AttendanceRecord>[] = [
    {
      title: '员工姓名',
      dataIndex: 'employee_name',
      valueType: 'text',
    },
    {
      title: '日期',
      dataIndex: 'attendance_date',
      valueType: 'date',
      search: false,
    },
    {
      title: '上班时间',
      dataIndex: 'clock_in',
      valueType: 'text',
      search: false,
      render: (_, r) => r.clock_in ?? <Text type="secondary">—</Text>,
    },
    {
      title: '下班时间',
      dataIndex: 'clock_out',
      valueType: 'text',
      search: false,
      render: (_, r) => r.clock_out ?? <Text type="secondary">—</Text>,
    },
    {
      title: '工时',
      dataIndex: 'work_hours',
      valueType: 'text',
      search: false,
      render: (_, r) =>
        r.work_hours != null ? `${r.work_hours.toFixed(1)} h` : <Text type="secondary">—</Text>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      valueType: 'select',
      valueEnum: Object.fromEntries(
        Object.entries(STATUS_ENUM).map(([k, v]) => [k, { text: v.label }]),
      ),
      render: (_, r) => {
        const cfg = STATUS_ENUM[r.status] ?? { label: r.status, color: 'default' };
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    {
      title: '操作',
      valueType: 'option',
      render: (_, record) => [
        <a
          key="adjust"
          onClick={() => {
            setAdjustRecord(record);
            setAdjustOpen(true);
            setSelectedEmployeeId(record.employee_id);
          }}
        >
          调整
        </a>,
      ],
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Title level={4} style={{ marginBottom: 16 }}>考勤管理</Title>

      {/* 门店选择器 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Text>门店：</Text>
          <Select
            placeholder="选择门店"
            style={{ width: 200 }}
            allowClear
            onChange={(v) => setStoreId(v ?? '')}
            options={[
              { label: '芙蓉路店（示例）', value: 'store-001' },
            ]}
          />
          <Text>年月：</Text>
          <DatePicker
            picker="month"
            defaultValue={dayjs()}
            onChange={(d) => {
              if (d) {
                setSelectedYear(d.year());
                setSelectedMonth(d.month() + 1);
              }
            }}
          />
        </Space>
      </Card>

      <Tabs
        defaultActiveKey="attendance"
        items={[
          {
            key: 'attendance',
            label: '考勤记录',
            children: (
              <>
                {/* 1. 今日看板 */}
                <TodayBoard storeId={storeId} />

                {/* 3. 员工月度汇总（选中员工后展示） */}
                <EmployeeSummaryCard
                  employeeId={selectedEmployeeId}
                  year={selectedYear}
                  month={selectedMonth}
                />

                {/* 2. 月度考勤 ProTable */}
                <ProTable<AttendanceRecord>
                  actionRef={actionRef}
                  rowKey="id"
                  columns={columns}
                  request={async (params) => {
                    try {
                      const qs = new URLSearchParams({
                        ...(storeId ? { store_id: storeId } : {}),
                        year: String(selectedYear),
                        month: String(selectedMonth),
                        page: String(params.current ?? 1),
                        size: String(params.pageSize ?? 20),
                        ...(params.employee_name ? { employee_name: params.employee_name } : {}),
                        ...(params.status ? { status: params.status } : {}),
                      });
                      const data = await txFetch<AttendanceListResp>(
                        `/api/v1/attendance/records?${qs}`,
                      );
                      return { data: data.items, total: data.total, success: true };
                    } catch (err) {
                      return { data: [], total: 0, success: false };
                    }
                  }}
                  search={{ labelWidth: 'auto' }}
                  pagination={{ defaultPageSize: 20 }}
                  onRow={(record) => ({
                    onClick: () => setSelectedEmployeeId(record.employee_id),
                    style: { cursor: 'pointer' },
                  })}
                  cardProps={{ title: '月度考勤明细' }}
                />
              </>
            ),
          },
          {
            key: 'schedule',
            label: '排班管理',
            children: <WeekScheduleView storeId={storeId} />,
          },
        ]}
      />

      {/* 考勤调整弹窗 */}
      <ModalForm
        title={`调整考勤 — ${adjustRecord?.employee_name ?? ''} ${adjustRecord?.attendance_date ?? ''}`}
        open={adjustOpen}
        onOpenChange={(open) => {
          if (!open) { setAdjustOpen(false); setAdjustRecord(null); }
        }}
        onFinish={async (values) => {
          if (!adjustRecord) return false;
          try {
            await txFetch(`/api/v1/attendance/records/${adjustRecord.id}/adjust`, {
              method: 'POST',
              body: JSON.stringify({
                clock_in: values.clock_in,
                clock_out: values.clock_out,
                reason: values.reason,
              }),
            });
            message.success('考勤调整成功');
            actionRef.current?.reload();
            return true;
          } catch (err) {
            message.error(err instanceof Error ? err.message : '调整失败，请重试');
            return false;
          }
        }}
      >
        <ProFormTimePicker
          name="clock_in"
          label="调整上班时间"
          fieldProps={{ format: 'HH:mm' }}
          initialValue={adjustRecord?.clock_in ?? undefined}
        />
        <ProFormTimePicker
          name="clock_out"
          label="调整下班时间"
          fieldProps={{ format: 'HH:mm' }}
          initialValue={adjustRecord?.clock_out ?? undefined}
        />
        <ProFormTextArea
          name="reason"
          label="调整原因"
          rules={[{ required: true, message: '请填写调整原因' }]}
          placeholder="请说明本次调整的原因"
          fieldProps={{ rows: 3 }}
        />
      </ModalForm>
    </div>
  );
}
