/**
 * AttendanceToday — 今日考勤总览
 * 域F · 组织人事 · 考勤管理
 *
 * 功能：
 *  1. 门店选择器
 *  2. 三个StatisticCard：在岗/已下班/未打卡
 *  3. 未打卡员工Alert预警
 *  4. 今日打卡记录ProTable（姓名/打卡时间/状态/工时）
 *
 * API:
 *  GET /api/v1/attendance/today?store_id=xxx
 */

import { useEffect, useRef, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  message,
  Row,
  Select,
  Space,
  Statistic,
  Tag,
  Typography,
} from 'antd';
import { ProTable } from '@ant-design/pro-components';
import type { ActionType, ProColumns } from '@ant-design/pro-components';
import { ClockCircleOutlined, ReloadOutlined } from '@ant-design/icons';
import { txFetchData } from '../../../api';

const { Title } = Typography;

// ─── Design Token ────────────────────────────────────────────────────────────
const TX_PRIMARY = '#FF6B35';
const TX_SUCCESS = '#0F6E56';
const TX_DANGER  = '#A32D2D';

// ─── Types ───────────────────────────────────────────────────────────────────

interface TodayStats {
  on_duty: number;
  off_duty: number;
  absent: number;
  absent_employees: { id: string; name: string }[];
}

interface ClockRecord {
  id: string;
  employee_id: string;
  employee_name: string;
  clock_in: string | null;
  clock_out: string | null;
  status: 'normal' | 'late' | 'early_leave' | 'absent';
  work_hours: number | null;
}

// ─── 枚举 ────────────────────────────────────────────────────────────────────

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  normal:      { label: '正常',   color: 'green' },
  late:        { label: '迟到',   color: 'orange' },
  early_leave: { label: '早退',   color: 'gold' },
  absent:      { label: '缺勤',   color: 'red' },
};

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export default function AttendanceToday() {
  const actionRef = useRef<ActionType>();
  const [storeId, setStoreId] = useState<string>('');
  const [stores, setStores] = useState<{ store_id: string; store_name: string }[]>([]);
  const [stats, setStats] = useState<TodayStats | null>(null);
  const [loading, setLoading] = useState(false);

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

  const loadStats = async () => {
    if (!storeId) return;
    setLoading(true);
    try {
      const res = await txFetchData<TodayStats>(`/api/v1/attendance/today?store_id=${storeId}`);
      setStats(res);
    } catch {
      message.error('加载今日考勤失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStats();
    actionRef.current?.reload();
  }, [storeId]);

  const columns: ProColumns<ClockRecord>[] = [
    { title: '员工', dataIndex: 'employee_name', width: 100 },
    { title: '上班打卡', dataIndex: 'clock_in', width: 120, render: (_, r) => r.clock_in ?? '-' },
    { title: '下班打卡', dataIndex: 'clock_out', width: 120, render: (_, r) => r.clock_out ?? '-' },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (_, r) => {
        const s = STATUS_MAP[r.status];
        return <Tag color={s?.color}>{s?.label}</Tag>;
      },
    },
    {
      title: '工时(h)',
      dataIndex: 'work_hours',
      width: 90,
      render: (_, r) => (r.work_hours != null ? r.work_hours.toFixed(1) : '-'),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            <ClockCircleOutlined style={{ color: TX_PRIMARY, marginRight: 8 }} />
            今日考勤总览
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
            <Button
              icon={<ReloadOutlined />}
              onClick={() => {
                loadStats();
                actionRef.current?.reload();
              }}
              loading={loading}
            >
              刷新
            </Button>
          </Space>
        </Col>
      </Row>

      {/* 统计卡 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card>
            <Statistic title="在岗" value={stats?.on_duty ?? '-'} valueStyle={{ color: TX_SUCCESS }} />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic title="已下班" value={stats?.off_duty ?? '-'} valueStyle={{ color: '#888' }} />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic title="未打卡" value={stats?.absent ?? '-'} valueStyle={{ color: TX_DANGER }} />
          </Card>
        </Col>
      </Row>

      {/* 未打卡预警 */}
      {stats && stats.absent_employees.length > 0 && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
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

      {/* 打卡记录 */}
      <Card>
        <ProTable<ClockRecord>
          actionRef={actionRef}
          columns={columns}
          request={async () => {
            if (!storeId) return { data: [], total: 0, success: true };
            const res = await txFetchData<{ items: ClockRecord[]; total: number }>(
              `/api/v1/attendance/today-records?store_id=${storeId}`,
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
    </div>
  );
}
