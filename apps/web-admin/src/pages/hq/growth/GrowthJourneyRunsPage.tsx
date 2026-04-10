/**
 * GrowthJourneyRunsPage — 旅程运行中心
 * 路由: /hq/growth/journey-runs
 * 状态Tab + enrollment列表
 */
import { useState, useEffect, useCallback } from 'react';
import { Card, Table, Tag, Tabs, Spin, Space, Button } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { txFetch } from '../../../api';
import type { JourneyEnrollment } from '../../../api/growthHubApi';

// ---- 颜色常量 ----
const PAGE_BG = '#0d1e28';
const CARD_BG = '#142833';
const BORDER = '#1e3a4a';
const TEXT_PRIMARY = '#e8e8e8';
const TEXT_SECONDARY = '#8899a6';
const BRAND_ORANGE = '#FF6B35';

const STATE_COLORS: Record<string, string> = {
  eligible: 'blue',
  active: 'green',
  paused: 'orange',
  waiting_observe: 'cyan',
  completed: 'default',
  exited: 'red',
  cancelled: 'default',
};

const STATE_LABELS: Record<string, string> = {
  eligible: '待进入',
  active: '运行中',
  paused: '已暂停',
  waiting_observe: '观察中',
  completed: '已完成',
  exited: '已退出',
  cancelled: '已取消',
};

const EXIT_REASON_LABELS: Record<string, string> = {
  completed: '自然完成',
  manual: '手动退出',
  timeout: '超时退出',
  opt_out: '客户退订',
  condition_fail: '条件不满足',
  conflict: '旅程冲突',
};

interface EnrollmentRow extends JourneyEnrollment {
  customer_name?: string;
  journey_name?: string;
}

// ---- Tab配置 ----
const TAB_ITEMS = [
  { key: 'all', label: '全部' },
  { key: 'active', label: '运行中' },
  { key: 'paused', label: '已暂停' },
  { key: 'completed', label: '已完成' },
  { key: 'exited', label: '已退出' },
];

// ---- 组件 ----
export function GrowthJourneyRunsPage() {
  const [loading, setLoading] = useState(false);
  const [enrollments, setEnrollments] = useState<EnrollmentRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [activeTab, setActiveTab] = useState('all');

  const fetchEnrollments = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = { page: String(page), size: String(pageSize) };
      if (activeTab !== 'all') params.journey_state = activeTab;
      const qs = new URLSearchParams(params).toString();
      const resp = await txFetch<{ items: EnrollmentRow[]; total: number }>(
        `/api/v1/growth/journey-enrollments?${qs}`
      );
      if (resp.data) {
        setEnrollments(resp.data.items);
        setTotal(resp.data.total);
      }
    } catch (err) {
      console.error('fetch enrollments error', err);
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, activeTab]);

  useEffect(() => { fetchEnrollments(); }, [fetchEnrollments]);

  const handleTabChange = (key: string) => {
    setActiveTab(key);
    setPage(1);
  };

  const columns = [
    {
      title: '客户', dataIndex: 'customer_name', key: 'customer_name', width: 130,
      render: (val: string | undefined, record: EnrollmentRow) => (
        <span style={{ color: TEXT_PRIMARY, fontWeight: 500 }}>
          {val || record.customer_id?.slice(0, 8) || '-'}
        </span>
      ),
    },
    {
      title: '旅程名', dataIndex: 'journey_name', key: 'journey_name', width: 160,
      render: (val: string | undefined, record: EnrollmentRow) => (
        <span style={{ color: TEXT_PRIMARY }}>
          {val || record.journey_template_id?.slice(0, 8) || '-'}
        </span>
      ),
    },
    {
      title: '状态', dataIndex: 'journey_state', key: 'journey_state', width: 100,
      render: (val: string) => (
        <Tag color={STATE_COLORS[val] || 'default'}>
          {STATE_LABELS[val] || val}
        </Tag>
      ),
    },
    {
      title: '当前步骤', dataIndex: 'current_step_no', key: 'current_step_no', width: 90,
      render: (val: number | null) => (
        <span style={{ color: val ? BRAND_ORANGE : TEXT_SECONDARY, fontWeight: val ? 600 : 400 }}>
          {val != null ? `Step ${val}` : '-'}
        </span>
      ),
    },
    {
      title: '来源', dataIndex: 'enrollment_source', key: 'enrollment_source', width: 90,
      render: (val: string) => <Tag>{val}</Tag>,
    },
    {
      title: '进入时间', dataIndex: 'entered_at', key: 'entered_at', width: 140,
      render: (val: string) => <span style={{ color: TEXT_SECONDARY }}>{val?.slice(0, 16)?.replace('T', ' ') || '-'}</span>,
    },
    {
      title: '激活时间', dataIndex: 'activated_at', key: 'activated_at', width: 140,
      render: (val: string | null) => (
        <span style={{ color: val ? TEXT_PRIMARY : TEXT_SECONDARY }}>
          {val?.slice(0, 16)?.replace('T', ' ') || '-'}
        </span>
      ),
    },
    {
      title: '退出原因', dataIndex: 'exit_reason', key: 'exit_reason', width: 120,
      render: (val: string | null) =>
        val ? <Tag color="red">{EXIT_REASON_LABELS[val] || val}</Tag> : '-',
    },
    {
      title: '暂停原因', dataIndex: 'pause_reason', key: 'pause_reason', width: 120,
      render: (val: string | null) =>
        val ? <Tag color="orange">{val}</Tag> : '-',
    },
  ];

  return (
    <div style={{ padding: 24, background: PAGE_BG, minHeight: '100vh' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2 style={{ color: TEXT_PRIMARY, margin: 0 }}>旅程运行中心</h2>
        <Button
          icon={<ReloadOutlined />}
          onClick={fetchEnrollments}
          style={{ borderColor: BORDER, color: TEXT_SECONDARY }}
        >
          刷新
        </Button>
      </div>

      <Card
        style={{ background: CARD_BG, border: `1px solid ${BORDER}` }}
        bodyStyle={{ padding: 0 }}
      >
        <Tabs
          activeKey={activeTab}
          onChange={handleTabChange}
          style={{ padding: '0 16px' }}
          items={TAB_ITEMS.map((tab) => ({
            key: tab.key,
            label: (
              <span style={{ color: activeTab === tab.key ? BRAND_ORANGE : TEXT_SECONDARY }}>
                {tab.label}
              </span>
            ),
          }))}
        />

        <Table
          loading={loading}
          dataSource={enrollments}
          columns={columns}
          rowKey="id"
          size="small"
          pagination={{
            current: page,
            pageSize,
            total,
            onChange: (p) => setPage(p),
            showTotal: (t) => `共 ${t} 条`,
            size: 'small',
          }}
          scroll={{ x: 1200 }}
        />
      </Card>
    </div>
  );
}
