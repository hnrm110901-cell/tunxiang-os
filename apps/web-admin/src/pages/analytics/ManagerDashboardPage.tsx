/**
 * 管理直通车 — 移动端店长看板
 * 终端：Admin（移动端优先响应式，375px～1440px 均可用）
 * API：/api/v1/manager/* + /api/v1/analytics/*
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Collapse,
  DatePicker,
  Divider,
  Empty,
  Modal,
  Progress,
  Row,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  BellOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import {
  getDailyTrend,
  getGoalProgress,
  getManagerAlerts,
  getMultiStoreOverview,
  getTodayStats,
  markAlertRead,
  type DailyTrendItem,
  type GoalProgress,
  type ManagerAlert,
  type StoreComparison,
  type StoreDailyStats,
} from '../../api/managerDashboardApi';
import { txFetchData } from '../../api';

const { Title, Text, Paragraph } = Typography;

// ─── 工具函数 ───

function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

function fenToWan(fen: number): string {
  return (fen / 1000000).toFixed(2);
}

function formatRevenue(fen: number): string {
  if (fen >= 1000000) return `${fenToWan(fen)} 万`;
  return `¥${fenToYuan(fen)}`;
}

interface StoreOption {
  value: string;
  label: string;
}

// ─── 子组件：KPI 卡片 ───

interface KpiCardProps {
  title: string;
  value: string;
  sub?: string;
  trend?: number | null; // 正数=涨，负数=跌
  color?: string;
}

function KpiCard({ title, value, sub, trend }: KpiCardProps) {
  return (
    <Card
      size="small"
      style={{ textAlign: 'center', borderRadius: 8 }}
      styles={{ body: { padding: '16px 12px' } }}
    >
      <Text style={{ fontSize: 12, color: '#5F5E5A', display: 'block', marginBottom: 6 }}>
        {title}
      </Text>
      <div style={{ fontSize: 22, fontWeight: 700, color: '#2C2C2A', lineHeight: 1.2 }}>
        {value}
      </div>
      {(sub || trend != null) && (
        <div style={{ marginTop: 6, fontSize: 12 }}>
          {trend != null && (
            <span
              style={{
                color: trend >= 0 ? '#0F6E56' : '#A32D2D',
                fontWeight: 600,
              }}
            >
              {trend >= 0 ? (
                <ArrowUpOutlined style={{ fontSize: 10 }} />
              ) : (
                <ArrowDownOutlined style={{ fontSize: 10 }} />
              )}
              {' '}
              {Math.abs(trend).toFixed(1)}%
            </span>
          )}
          {sub && (
            <span style={{ color: '#B4B2A9', marginLeft: trend != null ? 6 : 0 }}>{sub}</span>
          )}
        </div>
      )}
    </Card>
  );
}

// ─── 子组件：告警列表 ───

interface AlertListProps {
  alerts: ManagerAlert[];
  loading: boolean;
  onMarkRead: (id: string) => void;
}

const SEVERITY_COLOR: Record<ManagerAlert['severity'], string> = {
  critical: '#A32D2D',
  warning: '#BA7517',
  info: '#185FA5',
};
const SEVERITY_TAG: Record<ManagerAlert['severity'], string> = {
  critical: 'red',
  warning: 'orange',
  info: 'blue',
};
const SEVERITY_LABEL: Record<ManagerAlert['severity'], string> = {
  critical: '严重',
  warning: '警告',
  info: '提示',
};

function AlertList({ alerts, loading, onMarkRead }: AlertListProps) {
  const unread = alerts.filter((a) => !a.is_read);
  const display = alerts.slice(0, 5);

  return (
    <Spin spinning={loading}>
      {display.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={<Text style={{ color: '#0F6E56' }}>暂无异常告警</Text>}
        />
      ) : (
        <Space direction="vertical" style={{ width: '100%' }} size={8}>
          {unread.length > 0 && (
            <Alert
              type="warning"
              showIcon
              message={`${unread.length} 条未读告警`}
              style={{ borderRadius: 6 }}
            />
          )}
          {display.map((alert) => (
            <div
              key={alert.id}
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: 10,
                padding: '10px 12px',
                background: alert.is_read ? '#F8F7F5' : '#FFF3ED',
                borderRadius: 8,
                borderLeft: `3px solid ${SEVERITY_COLOR[alert.severity]}`,
              }}
            >
              <Tag
                color={SEVERITY_TAG[alert.severity]}
                style={{ flexShrink: 0, marginTop: 1 }}
              >
                {SEVERITY_LABEL[alert.severity]}
              </Tag>
              <div style={{ flex: 1, minWidth: 0 }}>
                <Text
                  style={{
                    fontSize: 13,
                    fontWeight: alert.is_read ? 400 : 600,
                    color: '#2C2C2A',
                    display: 'block',
                  }}
                >
                  {alert.message}
                </Text>
                <Text style={{ fontSize: 11, color: '#B4B2A9' }}>
                  {dayjs(alert.created_at).format('HH:mm')}
                </Text>
              </div>
              {!alert.is_read && (
                <Button
                  size="small"
                  type="link"
                  style={{ padding: 0, fontSize: 12, flexShrink: 0 }}
                  onClick={() => onMarkRead(alert.id)}
                >
                  已读
                </Button>
              )}
            </div>
          ))}
        </Space>
      )}
    </Spin>
  );
}

// ─── 子组件：7天趋势表格 ───

function TrendTable({ data, loading }: { data: DailyTrendItem[]; loading: boolean }) {
  const columns: ColumnsType<DailyTrendItem> = [
    {
      title: '日期',
      dataIndex: 'date',
      key: 'date',
      render: (d: string) => dayjs(d).format('MM/DD'),
    },
    {
      title: '营收',
      dataIndex: 'revenue_fen',
      key: 'revenue_fen',
      align: 'right',
      render: (v: number) => (
        <Text strong style={{ fontSize: 13 }}>
          {formatRevenue(v)}
        </Text>
      ),
    },
    {
      title: '同比',
      dataIndex: 'yoy_pct',
      key: 'yoy_pct',
      align: 'right',
      render: (v: number | null) => {
        if (v == null) return <Text style={{ color: '#B4B2A9' }}>—</Text>;
        return (
          <span style={{ color: v >= 0 ? '#0F6E56' : '#A32D2D', fontWeight: 600 }}>
            {v >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}{' '}
            {Math.abs(v).toFixed(1)}%
          </span>
        );
      },
    },
    {
      title: '订单数',
      dataIndex: 'order_count',
      key: 'order_count',
      align: 'right',
    },
  ];

  return (
    <Spin spinning={loading}>
      <Table
        columns={columns}
        dataSource={data}
        rowKey="date"
        pagination={false}
        size="small"
        style={{ fontSize: 13 }}
      />
    </Spin>
  );
}

// ─── 主页面 ───

export function ManagerDashboardPage() {
  const today = dayjs().format('YYYY-MM-DD');
  const thisMonth = dayjs().format('YYYY-MM');

  const [stores, setStores] = useState<StoreOption[]>([]);
  const [storeId, setStoreId] = useState<string | undefined>(undefined);
  const [bizDate, setBizDate] = useState<string>(today);

  const [statsLoading, setStatsLoading] = useState(false);
  const [stats, setStats] = useState<StoreDailyStats | null>(null);

  const [goalLoading, setGoalLoading] = useState(false);
  const [goal, setGoal] = useState<GoalProgress | null>(null);

  const [trendLoading, setTrendLoading] = useState(false);
  const [trend, setTrend] = useState<DailyTrendItem[]>([]);

  const [multiLoading, setMultiLoading] = useState(false);
  const [multiStores, setMultiStores] = useState<StoreComparison[]>([]);

  const [alertsLoading, setAlertsLoading] = useState(false);
  const [alerts, setAlerts] = useState<ManagerAlert[]>([]);

  // 快速报表 Modal
  const [reportModal, setReportModal] = useState<{
    open: boolean;
    title: string;
    content: string;
  }>({ open: false, title: '', content: '' });

  // 加载门店列表
  useEffect(() => {
    txFetchData<{ items: Array<{ id: string; name: string }> }>('/api/v1/org/stores?status=active')
      .then((data) => {
        const list = (data.items ?? []).map((s) => ({ value: s.id, label: s.name }));
        setStores(list);
        if (list.length > 0 && !storeId) {
          setStoreId(list[0].value);
        }
      })
      .catch(() => setStores([]));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 加载多门店对比
  useEffect(() => {
    if (stores.length < 2) return;
    const ids = stores.map((s) => s.value);
    setMultiLoading(true);
    getMultiStoreOverview(ids)
      .then(setMultiStores)
      .catch(() => setMultiStores([]))
      .finally(() => setMultiLoading(false));
  }, [stores]);

  // 加载门店数据
  const loadStoreData = useCallback(
    async (sid: string) => {
      setStatsLoading(true);
      setGoalLoading(true);
      setTrendLoading(true);
      setAlertsLoading(true);

      // 并行加载
      const [statsResult, goalResult, trendResult, alertsResult] = await Promise.allSettled([
        getTodayStats(sid),
        getGoalProgress(sid, thisMonth),
        getDailyTrend(sid, 7),
        getManagerAlerts(sid),
      ]);

      if (statsResult.status === 'fulfilled') setStats(statsResult.value);
      else setStats(null);
      setStatsLoading(false);

      if (goalResult.status === 'fulfilled') setGoal(goalResult.value);
      else setGoal(null);
      setGoalLoading(false);

      if (trendResult.status === 'fulfilled') setTrend(trendResult.value);
      else setTrend([]);
      setTrendLoading(false);

      if (alertsResult.status === 'fulfilled') setAlerts(alertsResult.value);
      else setAlerts([]);
      setAlertsLoading(false);
    },
    [thisMonth],
  );

  useEffect(() => {
    if (storeId) void loadStoreData(storeId);
  }, [storeId, bizDate, loadStoreData]);

  // 标记已读
  const handleMarkRead = useCallback(
    async (alertId: string) => {
      try {
        await markAlertRead(alertId);
        setAlerts((prev) =>
          prev.map((a) => (a.id === alertId ? { ...a, is_read: true } : a)),
        );
      } catch {
        message.error('标记失败，请重试');
      }
    },
    [],
  );

  // 生成快速报表文字
  const handleReport = (type: 'daily' | 'weekly') => {
    const storeName =
      stores.find((s) => s.value === storeId)?.label || storeId || '门店';

    if (type === 'daily') {
      const content = stats
        ? `📊 ${storeName} 今日日报（${bizDate}）\n\n` +
          `💰 营收：${formatRevenue(stats.revenue_fen)}\n` +
          `🧾 订单数：${stats.order_count} 单\n` +
          `👥 接待宾客：${stats.guest_count} 人\n` +
          `🍽️ 人均消费：${formatRevenue(stats.avg_per_guest_fen)}\n` +
          `🔄 翻台率：${stats.turnover_rate.toFixed(1)} 次\n` +
          (goal
            ? `🎯 月度目标完成率：${goal.completion_pct.toFixed(1)}%\n`
            : '') +
          `\n—— 屯象OS 管理直通车`
        : `${storeName} 今日日报数据加载中，请稍后重试。`;
      setReportModal({ open: true, title: '今日日报', content });
    } else {
      const content =
        `📊 ${storeName} 本周小结\n\n` +
        (trend.length > 0
          ? trend
              .slice(0, 7)
              .map(
                (d) =>
                  `${dayjs(d.date).format('M/D')}  ${formatRevenue(d.revenue_fen)}` +
                  (d.yoy_pct != null
                    ? `  ${d.yoy_pct >= 0 ? '↑' : '↓'}${Math.abs(d.yoy_pct).toFixed(1)}%`
                    : ''),
              )
              .join('\n')
          : '暂无数据') +
        `\n\n—— 屯象OS 管理直通车`;
      setReportModal({ open: true, title: '本周小结', content });
    }
  };

  const unreadCount = alerts.filter((a) => !a.is_read).length;
  const storeName = stores.find((s) => s.value === storeId)?.label || '';

  // 多门店对比 Table 列
  const multiColumns: ColumnsType<StoreComparison> = [
    { title: '门店', dataIndex: 'store_name', key: 'store_name', ellipsis: true },
    {
      title: '今日营收',
      dataIndex: 'today_revenue_fen',
      key: 'today_revenue_fen',
      align: 'right',
      render: (v: number) => formatRevenue(v),
    },
    {
      title: '完成率',
      dataIndex: 'completion_pct',
      key: 'completion_pct',
      align: 'right',
      render: (v: number) => (
        <span style={{ color: v >= 100 ? '#0F6E56' : v >= 80 ? '#BA7517' : '#A32D2D', fontWeight: 600 }}>
          {v.toFixed(1)}%
        </span>
      ),
    },
  ];

  return (
    /* max-w-sm on mobile, full width on desktop */
    <div
      style={{
        maxWidth: 520,
        margin: '0 auto',
        padding: '16px 12px 40px',
        boxSizing: 'border-box',
      }}
    >
      {/* ── 页头 ── */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Title level={4} style={{ margin: 0, color: '#2C2C2A' }}>
            管理直通车
          </Title>
          <Space size={8}>
            <Badge count={unreadCount} size="small">
              <BellOutlined style={{ fontSize: 18, color: unreadCount > 0 ? '#FF6B35' : '#B4B2A9' }} />
            </Badge>
            <Button
              size="small"
              icon={<ReloadOutlined />}
              onClick={() => storeId && void loadStoreData(storeId)}
              type="text"
            />
          </Space>
        </div>
        <Paragraph style={{ margin: '4px 0 0', fontSize: 12, color: '#5F5E5A' }}>
          店长实时看板 · {storeName || '请选择门店'}
        </Paragraph>
      </div>

      {/* ── 门店 & 日期选择器 ── */}
      <Card
        size="small"
        style={{ marginBottom: 16, borderRadius: 8 }}
        styles={{ body: { padding: '12px 16px' } }}
      >
        <Row gutter={8}>
          <Col span={14}>
            <Select
              placeholder="选择门店"
              options={stores}
              value={storeId}
              onChange={setStoreId}
              style={{ width: '100%' }}
              size="middle"
            />
          </Col>
          <Col span={10}>
            <DatePicker
              defaultValue={dayjs()}
              onChange={(_, ds) => {
                const d = Array.isArray(ds) ? ds[0] : ds;
                if (d) setBizDate(d);
              }}
              style={{ width: '100%' }}
              size="middle"
              allowClear={false}
            />
          </Col>
        </Row>
      </Card>

      {/* ── 实时数据卡片行 ── */}
      <Spin spinning={statsLoading}>
        <Row gutter={8} style={{ marginBottom: 12 }}>
          <Col span={12}>
            <KpiCard
              title="今日营收"
              value={stats ? formatRevenue(stats.revenue_fen) : '—'}
              trend={null} // revenue_vs_yesterday 从 realtime-kpi 额外字段获取
            />
          </Col>
          <Col span={12}>
            <KpiCard
              title="今日桌台数"
              value={stats ? `${stats.order_count} 单` : '—'}
            />
          </Col>
        </Row>
        <Row gutter={8} style={{ marginBottom: 16 }}>
          <Col span={12}>
            <KpiCard
              title="人均消费"
              value={stats ? formatRevenue(stats.avg_per_guest_fen) : '—'}
            />
          </Col>
          <Col span={12}>
            <KpiCard
              title="翻台率"
              value={stats ? `${stats.turnover_rate.toFixed(1)} 次` : '—'}
            />
          </Col>
        </Row>
      </Spin>

      {/* ── 月度目标进度 ── */}
      <Card
        size="small"
        title="月度目标进度"
        style={{ marginBottom: 16, borderRadius: 8 }}
        styles={{ body: { padding: '16px', textAlign: 'center' } }}
      >
        <Spin spinning={goalLoading}>
          {goal ? (
            <>
              <Progress
                type="circle"
                percent={Math.min(Math.round(goal.completion_pct), 100)}
                size={120}
                strokeColor={
                  goal.completion_pct >= 100
                    ? '#0F6E56'
                    : goal.completion_pct >= 80
                    ? '#FF6B35'
                    : '#A32D2D'
                }
                format={(pct) => (
                  <span style={{ fontSize: 20, fontWeight: 700 }}>{pct}%</span>
                )}
              />
              <div style={{ marginTop: 12 }}>
                <Text style={{ fontSize: 13, color: '#5F5E5A' }}>
                  目标{' '}
                  <Text strong style={{ color: '#2C2C2A' }}>
                    {fenToWan(goal.target_fen)} 万
                  </Text>
                  ，已完成{' '}
                  <Text strong style={{ color: '#FF6B35' }}>
                    {fenToWan(goal.achieved_fen)} 万
                  </Text>
                </Text>
              </div>
              {goal.remaining_days > 0 && (
                <Text style={{ fontSize: 12, color: '#B4B2A9', display: 'block', marginTop: 4 }}>
                  还剩 {goal.remaining_days} 天，每日需完成 {formatRevenue(goal.daily_needed_fen)}
                </Text>
              )}
            </>
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无目标数据" />
          )}
        </Spin>
      </Card>

      {/* ── 在桌状态 ── */}
      <Card
        size="small"
        title="在桌状态"
        style={{ marginBottom: 16, borderRadius: 8 }}
        styles={{ body: { padding: '14px 16px' } }}
      >
        <Spin spinning={statsLoading}>
          <Row gutter={16}>
            <Col span={12} style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 28, fontWeight: 700, color: '#FF6B35' }}>
                {/* 数据来自 manager_app_routes.py 的 on_table_count */}
                {stats ? (stats as unknown as Record<string, number>)['on_table_count'] ?? '—' : '—'}
              </div>
              <Text style={{ fontSize: 12, color: '#5F5E5A' }}>桌在营业</Text>
            </Col>
            <Col span={12} style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 28, fontWeight: 700, color: '#0F6E56' }}>
                {stats ? (stats as unknown as Record<string, number>)['free_table_count'] ?? '—' : '—'}
              </div>
              <Text style={{ fontSize: 12, color: '#5F5E5A' }}>桌空闲</Text>
            </Col>
          </Row>
        </Spin>
      </Card>

      {/* ── 最近7天趋势 ── */}
      <Card
        size="small"
        title="最近 7 天营收趋势"
        style={{ marginBottom: 16, borderRadius: 8 }}
        styles={{ body: { padding: '8px 0 4px' } }}
      >
        <TrendTable data={trend} loading={trendLoading} />
      </Card>

      {/* ── 多门店对比（可折叠，区经视角）── */}
      {stores.length >= 2 && (
        <Collapse
          ghost
          style={{ marginBottom: 16, background: '#fff', borderRadius: 8, border: '1px solid #E8E6E1' }}
          items={[
            {
              key: 'multi',
              label: (
                <Text strong style={{ fontSize: 14 }}>
                  多门店对比
                  <Tag color="orange" style={{ marginLeft: 8, fontWeight: 400 }}>
                    区经视角
                  </Tag>
                </Text>
              ),
              children: (
                <Spin spinning={multiLoading}>
                  {multiStores.length > 0 ? (
                    <Table
                      columns={multiColumns}
                      dataSource={multiStores}
                      rowKey="store_id"
                      pagination={false}
                      size="small"
                    />
                  ) : (
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无多门店数据" />
                  )}
                </Spin>
              ),
            },
          ]}
        />
      )}

      {/* ── 异常告警列表 ── */}
      <Card
        size="small"
        title={
          <Space>
            <span>异常告警</span>
            {unreadCount > 0 && <Badge count={unreadCount} size="small" />}
            <Tag color="blue" style={{ fontWeight: 400 }}>
              折扣守护 Agent
            </Tag>
          </Space>
        }
        style={{ marginBottom: 16, borderRadius: 8 }}
        styles={{ body: { padding: '12px 16px' } }}
      >
        <AlertList alerts={alerts} loading={alertsLoading} onMarkRead={handleMarkRead} />
      </Card>

      {/* ── 快速报表按钮组 ── */}
      <Card
        size="small"
        title="快速报表"
        style={{ marginBottom: 16, borderRadius: 8 }}
        styles={{ body: { padding: '14px 16px' } }}
      >
        <Row gutter={12}>
          <Col span={12}>
            <Button
              block
              type="primary"
              style={{ background: '#FF6B35', borderColor: '#FF6B35', borderRadius: 8 }}
              onClick={() => handleReport('daily')}
              disabled={!storeId}
            >
              今日日报
            </Button>
          </Col>
          <Col span={12}>
            <Button
              block
              style={{ borderRadius: 8 }}
              onClick={() => handleReport('weekly')}
              disabled={!storeId}
            >
              本周小结
            </Button>
          </Col>
        </Row>
      </Card>

      {/* ── 快速报表 Modal ── */}
      <Modal
        title={reportModal.title}
        open={reportModal.open}
        onCancel={() => setReportModal((p) => ({ ...p, open: false }))}
        footer={[
          <Button
            key="copy"
            type="primary"
            style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
            onClick={() => {
              navigator.clipboard?.writeText(reportModal.content).then(() => {
                message.success('已复制到剪贴板');
              });
            }}
          >
            复制文字
          </Button>,
          <Button key="close" onClick={() => setReportModal((p) => ({ ...p, open: false }))}>
            关闭
          </Button>,
        ]}
        width={400}
      >
        <Divider style={{ margin: '8px 0' }} />
        <pre
          style={{
            background: '#F8F7F5',
            borderRadius: 8,
            padding: 16,
            fontSize: 13,
            lineHeight: 1.8,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
            margin: 0,
          }}
        >
          {reportModal.content}
        </pre>
      </Modal>
    </div>
  );
}
