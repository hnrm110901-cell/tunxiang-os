/**
 * AttendanceMonthly — 月度考勤汇总
 * 域F · 组织人事 · 考勤管理
 *
 * 功能：
 *  1. 月份选择器 + 门店选择器
 *  2. StatisticCard行：总出勤天数/总缺勤/总迟到/平均工时
 *  3. ProTable展示每个员工的月汇总（出勤天/缺勤天/迟到次/总工时/出勤率%）
 *  4. 出勤率低于80%红色标记
 *
 * API:
 *  GET /api/v1/attendance/monthly-summary?store_id=xxx&year=2026&month=4
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
  Statistic,
  Typography,
} from 'antd';
import { ProTable } from '@ant-design/pro-components';
import type { ActionType, ProColumns } from '@ant-design/pro-components';
import { BarChartOutlined } from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import { txFetch } from '../../../api';

const { Title } = Typography;
const TX_PRIMARY = '#FF6B35';
const TX_SUCCESS = '#0F6E56';
const TX_WARNING = '#BA7517';
const TX_DANGER  = '#A32D2D';

// ─── Types ───────────────────────────────────────────────────────────────────

interface MonthlySummary {
  total_present_days: number;
  total_absent_days: number;
  total_late_count: number;
  avg_work_hours: number;
  employees: EmployeeMonthly[];
}

interface EmployeeMonthly {
  employee_id: string;
  employee_name: string;
  present_days: number;
  absent_days: number;
  late_count: number;
  total_hours: number;
  attendance_rate: number;
}

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export default function AttendanceMonthly() {
  const actionRef = useRef<ActionType>();
  const [storeId, setStoreId] = useState<string>('');
  const [month, setMonth] = useState<Dayjs>(dayjs());
  const [stores, setStores] = useState<{ store_id: string; store_name: string }[]>([]);
  const [summary, setSummary] = useState<MonthlySummary | null>(null);

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
  }, [storeId, month]);

  const columns: ProColumns<EmployeeMonthly>[] = [
    { title: '员工', dataIndex: 'employee_name', width: 100 },
    { title: '出勤天数', dataIndex: 'present_days', width: 90, sorter: true },
    { title: '缺勤天数', dataIndex: 'absent_days', width: 90, sorter: true },
    { title: '迟到次数', dataIndex: 'late_count', width: 90, sorter: true },
    {
      title: '总工时(h)',
      dataIndex: 'total_hours',
      width: 100,
      render: (_, r) => r.total_hours.toFixed(1),
      sorter: true,
    },
    {
      title: '出勤率',
      dataIndex: 'attendance_rate',
      width: 100,
      sorter: true,
      render: (_, r) => {
        const pct = (r.attendance_rate * 100).toFixed(1);
        return (
          <span style={{ color: r.attendance_rate < 0.8 ? TX_DANGER : TX_SUCCESS, fontWeight: 600 }}>
            {pct}%
          </span>
        );
      },
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            <BarChartOutlined style={{ color: TX_PRIMARY, marginRight: 8 }} />
            月度考勤汇总
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

      {/* 汇总统计 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="总出勤天数"
              value={summary?.total_present_days ?? '-'}
              valueStyle={{ color: TX_SUCCESS }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="总缺勤天数"
              value={summary?.total_absent_days ?? '-'}
              valueStyle={{ color: TX_DANGER }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="总迟到次数"
              value={summary?.total_late_count ?? '-'}
              valueStyle={{ color: TX_WARNING }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="平均工时(h)"
              value={summary?.avg_work_hours != null ? summary.avg_work_hours.toFixed(1) : '-'}
              valueStyle={{ color: TX_PRIMARY }}
            />
          </Card>
        </Col>
      </Row>

      {/* 员工月度列表 */}
      <Card>
        <ProTable<EmployeeMonthly>
          actionRef={actionRef}
          columns={columns}
          request={async () => {
            if (!storeId) return { data: [], total: 0, success: true };
            const res = await txFetch<MonthlySummary>(
              `/api/v1/attendance/monthly-summary?store_id=${storeId}&year=${month.year()}&month=${month.month() + 1}`,
            );
            const d = res.data;
            if (d) setSummary(d);
            return {
              data: d?.employees ?? [],
              total: d?.employees?.length ?? 0,
              success: true,
            };
          }}
          rowKey="employee_id"
          search={false}
          options={{ reload: true }}
          pagination={{ pageSize: 20 }}
        />
      </Card>
    </div>
  );
}
