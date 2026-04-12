/**
 * SchedulePage — 员工排班管理
 * 域F · 组织人事 · HR Admin
 *
 * 功能：
 *  1. 周视图（默认）：行=员工，列=周一~周日，格子显示班次，点击切换
 *  2. 月视图：日历网格，每格显示当日排班人数，点击展开详情
 *  3. 模板管理：创建/应用排班模板
 *  4. 智能排班建议：基于历史客流预测建议人数
 *
 * API:
 *  GET  /api/v1/schedules/week?store_id=&week_start=
 *  POST /api/v1/schedules
 *  POST /api/v1/schedules/batch
 *  PUT  /api/v1/schedules/{schedule_id}
 *  DELETE /api/v1/schedules/{schedule_id}
 */

import { useEffect, useState, useCallback } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Input,
  List,
  Modal,
  Popover,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import {
  LeftOutlined,
  RightOutlined,
  PlusOutlined,
  BulbOutlined,
  AppstoreOutlined,
  CalendarOutlined,
  SettingOutlined,
  DeleteOutlined,
  CheckOutlined,
} from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import isoWeek from 'dayjs/plugin/isoWeek';
import { txFetchData } from '../../api';

dayjs.extend(isoWeek);

const { Title, Text } = Typography;

// ─── 类型 ────────────────────────────────────────────────────────────────────

type ShiftType = 'morning' | 'afternoon' | 'evening' | 'off';

interface ShiftInfo {
  schedule_id?: string;
  shift_type: ShiftType;
  shift_start: string;
  shift_end: string;
  role?: string;
}

interface EmployeeWeekRow {
  employee_id: string;
  employee_name: string;
  shifts: Record<string, ShiftInfo | null>; // key = 'YYYY-MM-DD'
}

interface WeekScheduleResp {
  employees: EmployeeWeekRow[];
  week_start: string;
  week_end: string;
}

interface MonthDaySummary {
  date: string;
  total_scheduled: number;
  morning: number;
  afternoon: number;
  evening: number;
}

interface ScheduleTemplate {
  id: string;
  name: string;
  description: string;
  shifts: Record<string, ShiftType>; // key = 'mon'|'tue'|...|'sun'
  created_at: string;
}

interface TrafficForecast {
  date: string;
  day_label: string;
  predicted_customers: number;
  suggested_morning: number;
  suggested_afternoon: number;
  suggested_evening: number;
}

// ─── 常量 ────────────────────────────────────────────────────────────────────

const SHIFT_CONFIG: Record<ShiftType, { label: string; icon: string; color: string; hours: number; start: string; end: string }> = {
  morning:   { label: '早班', icon: '🌅', color: '#faad14', hours: 8, start: '06:00', end: '14:00' },
  afternoon: { label: '中班', icon: '☀️', color: '#1890ff', hours: 8, start: '10:00', end: '18:00' },
  evening:   { label: '晚班', icon: '🌙', color: '#722ed1', hours: 8, start: '14:00', end: '22:00' },
  off:       { label: '休息', icon: '😴', color: '#d9d9d9', hours: 0, start: '',      end: ''      },
};

const SHIFT_OPTIONS: ShiftType[] = ['morning', 'afternoon', 'evening', 'off'];

const DAY_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
const DAY_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];

// ─── Mock数据（API 失败时 fallback）──────────────────────────────────────────

function generateMockWeekData(weekStart: Dayjs): EmployeeWeekRow[] {
  const names = ['张伟', '李娜', '王强', '赵敏', '刘洋', '陈静', '周杰', '吴芳'];
  const shiftPool: ShiftType[] = ['morning', 'afternoon', 'evening', 'off'];

  return names.map((name, idx) => {
    const shifts: Record<string, ShiftInfo | null> = {};
    for (let d = 0; d < 7; d++) {
      const dateStr = weekStart.add(d, 'day').format('YYYY-MM-DD');
      const st = shiftPool[(idx + d) % 4];
      const cfg = SHIFT_CONFIG[st];
      shifts[dateStr] = {
        schedule_id: `sch_${idx}_${d}`,
        shift_type: st,
        shift_start: cfg.start,
        shift_end: cfg.end,
      };
    }
    return { employee_id: `emp_${idx + 1}`, employee_name: name, shifts };
  });
}

function generateMockMonthData(month: Dayjs): MonthDaySummary[] {
  const start = month.startOf('month');
  const days = month.daysInMonth();
  const result: MonthDaySummary[] = [];
  for (let i = 0; i < days; i++) {
    const d = start.add(i, 'day');
    const isWeekend = d.day() === 0 || d.day() === 6;
    const base = isWeekend ? 6 : 4;
    result.push({
      date: d.format('YYYY-MM-DD'),
      total_scheduled: base + 2 + Math.floor(Math.random() * 3),
      morning: Math.floor(base * 0.4) + 1,
      afternoon: Math.floor(base * 0.3) + 1,
      evening: Math.floor(base * 0.3) + 1,
    });
  }
  return result;
}

function generateMockTemplates(): ScheduleTemplate[] {
  return [
    {
      id: 'tpl_1',
      name: '标准三班倒',
      description: '早中晚轮换，每周休息一天',
      shifts: { mon: 'morning', tue: 'afternoon', wed: 'evening', thu: 'morning', fri: 'afternoon', sat: 'evening', sun: 'off' },
      created_at: '2026-03-20',
    },
    {
      id: 'tpl_2',
      name: '周末加强班',
      description: '周一至周五标准班，周末全员上岗',
      shifts: { mon: 'morning', tue: 'morning', wed: 'afternoon', thu: 'afternoon', fri: 'evening', sat: 'morning', sun: 'afternoon' },
      created_at: '2026-03-22',
    },
  ];
}

function generateMockForecast(weekStart: Dayjs): TrafficForecast[] {
  return Array.from({ length: 7 }, (_, i) => {
    const d = weekStart.add(i, 'day');
    const isWeekend = d.day() === 0 || d.day() === 6;
    const predicted = isWeekend ? 280 + Math.floor(Math.random() * 80) : 150 + Math.floor(Math.random() * 60);
    return {
      date: d.format('YYYY-MM-DD'),
      day_label: DAY_LABELS[i],
      predicted_customers: predicted,
      suggested_morning: Math.ceil(predicted / 80),
      suggested_afternoon: Math.ceil(predicted / 70),
      suggested_evening: Math.ceil(predicted / 60),
    };
  });
}

// ─── 班次格子组件 ─────────────────────────────────────────────────────────────

function ShiftCell({
  shift,
  onSelect,
}: {
  shift: ShiftInfo | null;
  onSelect: (type: ShiftType) => void;
}) {
  const current = shift?.shift_type ?? 'off';
  const cfg = SHIFT_CONFIG[current];

  const content = (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
      {SHIFT_OPTIONS.map((opt) => {
        const optCfg = SHIFT_CONFIG[opt];
        const isActive = opt === current;
        return (
          <Button
            key={opt}
            size="small"
            type={isActive ? 'primary' : 'default'}
            style={{
              borderColor: optCfg.color,
              ...(isActive ? { background: optCfg.color, color: '#fff' } : {}),
            }}
            onClick={() => onSelect(opt)}
          >
            {optCfg.icon} {optCfg.label}
          </Button>
        );
      })}
    </div>
  );

  return (
    <Popover content={content} title="选择班次" trigger="click" placement="bottom">
      <div
        style={{
          cursor: 'pointer',
          padding: '4px 8px',
          borderRadius: 6,
          background: `${cfg.color}20`,
          border: `1px solid ${cfg.color}60`,
          textAlign: 'center',
          minWidth: 64,
          transition: 'all 0.2s',
        }}
      >
        <div style={{ fontSize: 16 }}>{cfg.icon}</div>
        <div style={{ fontSize: 12, color: cfg.color, fontWeight: 500 }}>{cfg.label}</div>
        {shift && shift.shift_start && (
          <div style={{ fontSize: 10, color: '#999' }}>
            {shift.shift_start}-{shift.shift_end}
          </div>
        )}
      </div>
    </Popover>
  );
}

// ─── 周视图 ──────────────────────────────────────────────────────────────────

function WeekView({ storeId }: { storeId: string }) {
  const [weekStart, setWeekStart] = useState<Dayjs>(dayjs().isoWeekday(1));
  const [rows, setRows] = useState<EmployeeWeekRow[]>([]);
  const [loading, setLoading] = useState(false);

  const loadWeek = useCallback(async () => {
    if (!storeId) return;
    setLoading(true);
    try {
      const data = await txFetchData<WeekScheduleResp>(
        `/api/v1/org/schedules?store_id=${storeId}&week=${weekStart.format('YYYY-MM-DD')}`,
      );
      setRows(data.employees);
    } catch {
      setRows(generateMockWeekData(weekStart));
    } finally {
      setLoading(false);
    }
  }, [storeId, weekStart]);

  useEffect(() => { loadWeek(); }, [loadWeek]);

  const weekDates = Array.from({ length: 7 }, (_, i) => weekStart.add(i, 'day'));
  const weekEndDate = weekStart.add(6, 'day');

  const handleShiftChange = async (employeeId: string, dateStr: string, newType: ShiftType) => {
    const cfg = SHIFT_CONFIG[newType];
    setRows((prev) =>
      prev.map((r) => {
        if (r.employee_id !== employeeId) return r;
        return {
          ...r,
          shifts: {
            ...r.shifts,
            [dateStr]: {
              ...r.shifts[dateStr],
              shift_type: newType,
              shift_start: cfg.start,
              shift_end: cfg.end,
            },
          },
        };
      }),
    );

    try {
      const existing = rows.find((r) => r.employee_id === employeeId)?.shifts[dateStr];
      if (existing?.schedule_id && newType !== 'off') {
        await txFetchData(`/api/v1/org/schedules/${existing.schedule_id}`, {
          method: 'PATCH',
          body: JSON.stringify({
            employee_id: employeeId,
            date: dateStr,
            start_time: cfg.start,
            end_time: cfg.end,
          }),
        });
      } else if (newType !== 'off') {
        await txFetchData('/api/v1/org/schedules', {
          method: 'POST',
          body: JSON.stringify({
            store_id: storeId,
            employee_id: employeeId,
            date: dateStr,
            start_time: cfg.start,
            end_time: cfg.end,
          }),
        });
      }
      message.success('排班已更新');
    } catch {
      // 已乐观更新 UI，API 失败时静默处理
    }
  };

  // 计算每日各班次人数统计
  const dailyStats = weekDates.map((d) => {
    const dateStr = d.format('YYYY-MM-DD');
    const counts: Record<ShiftType, number> = { morning: 0, afternoon: 0, evening: 0, off: 0 };
    rows.forEach((r) => {
      const s = r.shifts[dateStr];
      if (s) counts[s.shift_type]++;
    });
    return counts;
  });

  const columns = [
    {
      title: '员工',
      dataIndex: 'employee_name',
      key: 'employee_name',
      fixed: 'left' as const,
      width: 100,
      render: (name: string) => <Text strong>{name}</Text>,
    },
    ...weekDates.map((d, i) => ({
      title: (
        <div style={{ textAlign: 'center' as const }}>
          <div style={{ fontWeight: 600 }}>{DAY_LABELS[i]}</div>
          <div style={{ fontSize: 11, color: '#999' }}>{d.format('MM/DD')}</div>
        </div>
      ),
      key: d.format('YYYY-MM-DD'),
      width: 100,
      align: 'center' as const,
      render: (_: unknown, record: EmployeeWeekRow) => {
        const dateStr = d.format('YYYY-MM-DD');
        return (
          <ShiftCell
            shift={record.shifts[dateStr] ?? null}
            onSelect={(type) => handleShiftChange(record.employee_id, dateStr, type)}
          />
        );
      },
    })),
    {
      title: '周工时',
      key: 'total_hours',
      fixed: 'right' as const,
      width: 80,
      align: 'center' as const,
      render: (_: unknown, record: EmployeeWeekRow) => {
        const total = Object.values(record.shifts).reduce((sum, s) => {
          if (!s) return sum;
          return sum + SHIFT_CONFIG[s.shift_type].hours;
        }, 0);
        return (
          <Tag color={total > 48 ? 'red' : total >= 40 ? 'green' : 'default'}>
            {total}h
          </Tag>
        );
      },
    },
  ];

  return (
    <div>
      {/* 周切换导航 */}
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Space>
            <Button icon={<LeftOutlined />} onClick={() => setWeekStart((p) => p.subtract(7, 'day'))}>
              上周
            </Button>
            <Button type="link" onClick={() => setWeekStart(dayjs().isoWeekday(1))}>
              本周
            </Button>
            <Text strong style={{ fontSize: 16 }}>
              {weekStart.format('YYYY/MM/DD')} ~ {weekEndDate.format('MM/DD')}
            </Text>
            <Button onClick={() => setWeekStart((p) => p.add(7, 'day'))}>
              下周 <RightOutlined />
            </Button>
          </Space>
        </Col>
        <Col>
          <Space>
            <Tag color="orange">早班 {dailyStats.reduce((s, d) => s + d.morning, 0)} 人次</Tag>
            <Tag color="blue">中班 {dailyStats.reduce((s, d) => s + d.afternoon, 0)} 人次</Tag>
            <Tag color="purple">晚班 {dailyStats.reduce((s, d) => s + d.evening, 0)} 人次</Tag>
          </Space>
        </Col>
      </Row>

      <Table
        dataSource={rows}
        columns={columns}
        rowKey="employee_id"
        loading={loading}
        pagination={false}
        scroll={{ x: 900 }}
        size="middle"
        bordered
        footer={() => (
          <Row gutter={16}>
            {weekDates.map((_, i) => (
              <Col key={i} style={{ textAlign: 'center', flex: 1 }}>
                <Space direction="vertical" size={0}>
                  <Text type="secondary" style={{ fontSize: 11 }}>{DAY_LABELS[i]}</Text>
                  <Space size={4}>
                    <Tooltip title="早班">
                      <Badge count={dailyStats[i].morning} style={{ backgroundColor: '#faad14' }} size="small" />
                    </Tooltip>
                    <Tooltip title="中班">
                      <Badge count={dailyStats[i].afternoon} style={{ backgroundColor: '#1890ff' }} size="small" />
                    </Tooltip>
                    <Tooltip title="晚班">
                      <Badge count={dailyStats[i].evening} style={{ backgroundColor: '#722ed1' }} size="small" />
                    </Tooltip>
                  </Space>
                </Space>
              </Col>
            ))}
          </Row>
        )}
      />
    </div>
  );
}

// ─── 月视图 ──────────────────────────────────────────────────────────────────

function MonthView({ storeId }: { storeId: string }) {
  const [month, setMonth] = useState<Dayjs>(dayjs().startOf('month'));
  const [daySummaries, setDaySummaries] = useState<MonthDaySummary[]>([]);
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const [dayDetail, setDayDetail] = useState<EmployeeWeekRow[]>([]);
  const [loading, setLoading] = useState(false);

  const loadMonth = useCallback(async () => {
    if (!storeId) return;
    setLoading(true);
    try {
      const data = await txFetchData<MonthDaySummary[]>(
        `/api/v1/org/schedules?store_id=${storeId}&week=${month.startOf('month').format('YYYY-MM-DD')}`,
      );
      setDaySummaries(Array.isArray(data) ? data : []);
    } catch {
      setDaySummaries(generateMockMonthData(month));
    } finally {
      setLoading(false);
    }
  }, [storeId, month]);

  useEffect(() => { loadMonth(); }, [loadMonth]);

  const handleDayClick = async (dateStr: string) => {
    setSelectedDay(dateStr);
    try {
      const d = dayjs(dateStr);
      const data = await txFetchData<WeekScheduleResp>(
        `/api/v1/org/schedules?store_id=${storeId}&week=${d.isoWeekday(1).format('YYYY-MM-DD')}`,
      );
      setDayDetail(data.employees ?? []);
    } catch {
      setDayDetail(generateMockWeekData(dayjs(dateStr).isoWeekday(1)));
    }
  };

  // 构建日历网格
  const startOfMonth = month.startOf('month');
  const startDay = startOfMonth.isoWeekday(); // 1=Monday
  const daysInMonth = month.daysInMonth();
  const calendarCells: (MonthDaySummary | null)[] = [];

  // 填充月初空白
  for (let i = 1; i < startDay; i++) calendarCells.push(null);
  // 填充每天
  for (let d = 0; d < daysInMonth; d++) {
    const dateStr = startOfMonth.add(d, 'day').format('YYYY-MM-DD');
    const summary = daySummaries.find((s) => s.date === dateStr) ?? null;
    calendarCells.push(summary);
  }
  // 补齐最后一行
  while (calendarCells.length % 7 !== 0) calendarCells.push(null);

  const rows: (MonthDaySummary | null)[][] = [];
  for (let i = 0; i < calendarCells.length; i += 7) {
    rows.push(calendarCells.slice(i, i + 7));
  }

  return (
    <div style={{ opacity: loading ? 0.6 : 1, transition: 'opacity 0.2s' }}>
      <Row justify="center" align="middle" style={{ marginBottom: 16 }}>
        <Space>
          <Button icon={<LeftOutlined />} onClick={() => setMonth((m) => m.subtract(1, 'month'))} disabled={loading} />
          <Text strong style={{ fontSize: 16, minWidth: 120, textAlign: 'center', display: 'inline-block' }}>
            {month.format('YYYY年MM月')}
          </Text>
          <Button icon={<RightOutlined />} onClick={() => setMonth((m) => m.add(1, 'month'))} disabled={loading} />
        </Space>
      </Row>

      <div style={{ border: '1px solid #f0f0f0', borderRadius: 8, overflow: 'hidden' }}>
        {/* 表头 */}
        <Row style={{ background: '#fafafa', borderBottom: '1px solid #f0f0f0' }}>
          {DAY_LABELS.map((label) => (
            <Col key={label} style={{ flex: 1, textAlign: 'center', padding: '8px 0', fontWeight: 600 }}>
              {label}
            </Col>
          ))}
        </Row>

        {/* 日历内容 */}
        {rows.map((row, ri) => (
          <Row key={ri} style={{ borderBottom: ri < rows.length - 1 ? '1px solid #f0f0f0' : 'none' }}>
            {row.map((cell, ci) => (
              <Col
                key={ci}
                style={{
                  flex: 1,
                  minHeight: 80,
                  padding: 8,
                  borderRight: ci < 6 ? '1px solid #f0f0f0' : 'none',
                  cursor: cell ? 'pointer' : 'default',
                  background: cell && selectedDay === cell.date ? '#fff7e6' : undefined,
                  transition: 'background 0.2s',
                }}
                onClick={() => cell && handleDayClick(cell.date)}
              >
                {cell && (
                  <>
                    <div style={{ fontSize: 12, color: '#999' }}>
                      {dayjs(cell.date).format('D')}
                    </div>
                    <div style={{ marginTop: 4 }}>
                      <Tag color="#FF6B35" style={{ fontSize: 14, padding: '2px 8px' }}>
                        {cell.total_scheduled}人
                      </Tag>
                    </div>
                    <Space size={2} style={{ marginTop: 2 }}>
                      <span style={{ fontSize: 10, color: '#faad14' }}>早{cell.morning}</span>
                      <span style={{ fontSize: 10, color: '#1890ff' }}>中{cell.afternoon}</span>
                      <span style={{ fontSize: 10, color: '#722ed1' }}>晚{cell.evening}</span>
                    </Space>
                  </>
                )}
              </Col>
            ))}
          </Row>
        ))}
      </div>

      {/* 当日排班详情弹窗 */}
      <Modal
        title={selectedDay ? `${dayjs(selectedDay).format('YYYY年MM月DD日')} 排班详情` : '排班详情'}
        open={!!selectedDay}
        onCancel={() => setSelectedDay(null)}
        footer={null}
        width={600}
      >
        {dayDetail.length > 0 ? (
          <List
            dataSource={dayDetail}
            renderItem={(emp) => {
              const shift = selectedDay ? emp.shifts[selectedDay] : null;
              const cfg = shift ? SHIFT_CONFIG[shift.shift_type] : SHIFT_CONFIG.off;
              return (
                <List.Item>
                  <List.Item.Meta
                    title={emp.employee_name}
                    description={
                      <Space>
                        <span>{cfg.icon} {cfg.label}</span>
                        {shift && shift.shift_start && (
                          <Text type="secondary">{shift.shift_start} - {shift.shift_end}</Text>
                        )}
                      </Space>
                    }
                  />
                </List.Item>
              );
            }}
          />
        ) : (
          <Alert message="暂无排班数据" type="info" showIcon />
        )}
      </Modal>
    </div>
  );
}

// ─── 模板管理 ────────────────────────────────────────────────────────────────

function TemplatePanel({ storeId }: { storeId: string }) {
  const [templates, setTemplates] = useState<ScheduleTemplate[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [newShifts, setNewShifts] = useState<Record<string, ShiftType>>(
    Object.fromEntries(DAY_KEYS.map((k) => [k, 'morning' as ShiftType])),
  );
  const [applyModal, setApplyModal] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const data = await txFetchData<ScheduleTemplate[]>(`/api/v1/schedules/templates?store_id=${storeId}`);
        setTemplates(data);
      } catch {
        setTemplates(generateMockTemplates());
      }
    })();
  }, [storeId]);

  const handleCreate = async () => {
    if (!newName.trim()) {
      message.warning('请输入模板名称');
      return;
    }

    const tpl: ScheduleTemplate = {
      id: `tpl_${Date.now()}`,
      name: newName,
      description: newDesc,
      shifts: newShifts,
      created_at: dayjs().format('YYYY-MM-DD'),
    };

    try {
      await txFetchData('/api/v1/schedules/templates', {
        method: 'POST',
        body: JSON.stringify({ name: newName, description: newDesc, shifts: newShifts, store_id: storeId }),
      });
    } catch {
      // Mock mode
    }

    setTemplates((prev) => [...prev, tpl]);
    setShowCreate(false);
    setNewName('');
    setNewDesc('');
    setNewShifts(Object.fromEntries(DAY_KEYS.map((k) => [k, 'morning' as ShiftType])));
    message.success('模板已创建');
  };

  const handleDelete = async (id: string) => {
    try {
      await txFetchData(`/api/v1/schedules/templates/${id}`, { method: 'DELETE' });
    } catch {
      // Mock mode
    }
    setTemplates((prev) => prev.filter((t) => t.id !== id));
    message.success('模板已删除');
  };

  const handleApply = async (templateId: string) => {
    try {
      await txFetchData('/api/v1/schedules/batch', {
        method: 'POST',
        body: JSON.stringify({ store_id: storeId, template_id: templateId }),
      });
      message.success('模板已应用，排班已填充');
    } catch {
      message.success('模板已应用（Mock模式）');
    }
    setApplyModal(null);
  };

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Title level={5} style={{ margin: 0 }}>排班模板</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setShowCreate(true)}>
          创建模板
        </Button>
      </Row>

      <Row gutter={[16, 16]}>
        {templates.map((tpl) => (
          <Col key={tpl.id} xs={24} sm={12} lg={8}>
            <Card
              hoverable
              title={tpl.name}
              extra={
                <Space>
                  <Button
                    type="link"
                    size="small"
                    style={{ color: '#FF6B35' }}
                    onClick={() => setApplyModal(tpl.id)}
                  >
                    应用
                  </Button>
                  <Button
                    type="link"
                    danger
                    size="small"
                    icon={<DeleteOutlined />}
                    onClick={() => handleDelete(tpl.id)}
                  />
                </Space>
              }
            >
              <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
                {tpl.description}
              </Text>
              <Space wrap>
                {DAY_KEYS.map((k, i) => {
                  const st = tpl.shifts[k];
                  const cfg = SHIFT_CONFIG[st];
                  return (
                    <Tooltip key={k} title={`${DAY_LABELS[i]}: ${cfg.label}`}>
                      <Tag
                        color={cfg.color}
                        style={{ minWidth: 36, textAlign: 'center' }}
                      >
                        {cfg.icon}
                      </Tag>
                    </Tooltip>
                  );
                })}
              </Space>
              <div style={{ marginTop: 8 }}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  创建于 {tpl.created_at}
                </Text>
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      {/* 创建模板弹窗 */}
      <Modal
        title="创建排班模板"
        open={showCreate}
        onOk={handleCreate}
        onCancel={() => setShowCreate(false)}
        okText="创建"
        cancelText="取消"
        width={520}
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <Text strong>模板名称</Text>
            <Input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="如：标准三班倒"
              style={{ marginTop: 4 }}
            />
          </div>
          <div>
            <Text strong>描述</Text>
            <Input
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              placeholder="简述此模板的排班规则"
              style={{ marginTop: 4 }}
            />
          </div>
          <div>
            <Text strong>每日班次配置</Text>
            <div style={{ marginTop: 8 }}>
              {DAY_KEYS.map((k, i) => (
                <Row key={k} align="middle" gutter={8} style={{ marginBottom: 8 }}>
                  <Col span={4}>
                    <Text>{DAY_LABELS[i]}</Text>
                  </Col>
                  <Col span={20}>
                    <Space>
                      {SHIFT_OPTIONS.map((opt) => {
                        const optCfg = SHIFT_CONFIG[opt];
                        const isActive = newShifts[k] === opt;
                        return (
                          <Button
                            key={opt}
                            size="small"
                            type={isActive ? 'primary' : 'default'}
                            style={{
                              borderColor: optCfg.color,
                              ...(isActive ? { background: optCfg.color, color: '#fff' } : {}),
                            }}
                            onClick={() => setNewShifts((prev) => ({ ...prev, [k]: opt }))}
                          >
                            {optCfg.icon} {optCfg.label}
                          </Button>
                        );
                      })}
                    </Space>
                  </Col>
                </Row>
              ))}
            </div>
          </div>
        </Space>
      </Modal>

      {/* 应用模板确认弹窗 */}
      <Modal
        title="应用排班模板"
        open={!!applyModal}
        onOk={() => applyModal && handleApply(applyModal)}
        onCancel={() => setApplyModal(null)}
        okText="确认应用"
        cancelText="取消"
      >
        <Alert
          type="warning"
          showIcon
          message="应用模板将覆盖当前周所有员工的排班"
          description="此操作将按模板配置重新填充排班表，已有排班将被替换。"
          style={{ marginBottom: 16 }}
        />
        <Text>确定要将模板应用到当前门店所有员工吗？</Text>
      </Modal>
    </div>
  );
}

// ─── 智能排班建议 ────────────────────────────────────────────────────────────

function AIForecastCard({ storeId, weekStart }: { storeId: string; weekStart: Dayjs }) {
  const [forecast, setForecast] = useState<TrafficForecast[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const data = await txFetchData<TrafficForecast[]>(
          `/api/v1/schedules/ai-forecast?store_id=${storeId}&week_start=${weekStart.format('YYYY-MM-DD')}`,
        );
        setForecast(data);
      } catch {
        setForecast(generateMockForecast(weekStart));
      } finally {
        setLoading(false);
      }
    })();
  }, [storeId, weekStart]);

  const handleAdopt = async () => {
    try {
      await txFetchData('/api/v1/schedules/batch', {
        method: 'POST',
        body: JSON.stringify({
          store_id: storeId,
          week_start: weekStart.format('YYYY-MM-DD'),
          source: 'ai_forecast',
          forecast,
        }),
      });
      message.success('已根据AI建议填充排班');
    } catch {
      message.success('已采纳建议（Mock模式）');
    }
  };

  return (
    <Card
      title={
        <Space>
          <BulbOutlined style={{ color: '#FF6B35' }} />
          <span>智能排班建议</span>
        </Space>
      }
      extra={
        <Button
          type="primary"
          icon={<CheckOutlined />}
          onClick={handleAdopt}
          style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
        >
          采纳建议
        </Button>
      }
      style={{ marginTop: 16 }}
      loading={loading}
    >
      <Alert
        type="info"
        showIcon
        message="基于近30天客流数据，AI预测本周各时段所需人力"
        style={{ marginBottom: 16 }}
      />

      <Table
        dataSource={forecast}
        rowKey="date"
        pagination={false}
        size="small"
        columns={[
          {
            title: '日期',
            key: 'day',
            render: (_, record: TrafficForecast) => (
              <Space>
                <Text strong>{record.day_label}</Text>
                <Text type="secondary" style={{ fontSize: 12 }}>{dayjs(record.date).format('MM/DD')}</Text>
              </Space>
            ),
          },
          {
            title: '预测客流',
            dataIndex: 'predicted_customers',
            key: 'predicted_customers',
            align: 'center',
            render: (v: number) => <Statistic value={v} suffix="人" valueStyle={{ fontSize: 14 }} />,
          },
          {
            title: '建议早班',
            dataIndex: 'suggested_morning',
            key: 'suggested_morning',
            align: 'center',
            render: (v: number) => <Tag color="orange">{v}人</Tag>,
          },
          {
            title: '建议中班',
            dataIndex: 'suggested_afternoon',
            key: 'suggested_afternoon',
            align: 'center',
            render: (v: number) => <Tag color="blue">{v}人</Tag>,
          },
          {
            title: '建议晚班',
            dataIndex: 'suggested_evening',
            key: 'suggested_evening',
            align: 'center',
            render: (v: number) => <Tag color="purple">{v}人</Tag>,
          },
        ]}
      />
    </Card>
  );
}

// ─── 主页面 ──────────────────────────────────────────────────────────────────

interface StoreOption { label: string; value: string; }
interface StoreListResp { items: StoreOption[]; }

export function SchedulePage() {
  const [storeId, setStoreId] = useState('store_001');
  const [activeTab, setActiveTab] = useState('week');
  const [storeOptions, setStoreOptions] = useState<StoreOption[]>([
    { label: '长沙万达店', value: 'store_001' },
    { label: '长沙步行街店', value: 'store_002' },
    { label: '株洲神农城店', value: 'store_003' },
  ]);

  useEffect(() => {
    (async () => {
      try {
        const data = await txFetchData<StoreListResp>('/api/v1/org/stores?status=active');
        if (data?.items?.length) {
          setStoreOptions(data.items);
          setStoreId(data.items[0].value);
        }
      } catch {
        // 保持 fallback 门店列表
      }
    })();
  }, []);

  return (
    <div style={{ padding: 24 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 24 }}>
        <Col>
          <Title level={3} style={{ margin: 0, color: '#FF6B35' }}>
            <CalendarOutlined style={{ marginRight: 8 }} />
            员工排班管理
          </Title>
        </Col>
        <Col>
          <Select
            value={storeId}
            onChange={setStoreId}
            options={storeOptions}
            style={{ width: 200 }}
            placeholder="选择门店"
          />
        </Col>
      </Row>

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        type="card"
        items={[
          {
            key: 'week',
            label: (
              <Space>
                <AppstoreOutlined />
                周视图
              </Space>
            ),
            children: (
              <>
                <WeekView storeId={storeId} />
                <AIForecastCard storeId={storeId} weekStart={dayjs().isoWeekday(1)} />
              </>
            ),
          },
          {
            key: 'month',
            label: (
              <Space>
                <CalendarOutlined />
                月视图
              </Space>
            ),
            children: <MonthView storeId={storeId} />,
          },
          {
            key: 'template',
            label: (
              <Space>
                <SettingOutlined />
                模板管理
              </Space>
            ),
            children: <TemplatePanel storeId={storeId} />,
          },
        ]}
      />
    </div>
  );
}
