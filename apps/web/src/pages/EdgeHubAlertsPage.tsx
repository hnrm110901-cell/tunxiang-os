import React, { useState, useEffect, useCallback } from 'react';
import {
  Card, Table, Tag, Input, Select, Space, Button,
  Tooltip, Empty, Spin, Popconfirm, message, Row, Col,
  Drawer, Descriptions, Badge,
} from 'antd';
import {
  SearchOutlined, ReloadOutlined, CheckCircleOutlined, InfoCircleOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { apiClient, handleApiError } from '../services/api';
import styles from './EdgeHubAlertsPage.module.css';

const { Option } = Select;

// ── 类型 ──────────────────────────────────────────────────────────────────────

interface AlertItem {
  id:         string;
  storeId:    string;
  hubId:      string | null;
  deviceId:   string | null;
  level:      string;
  alertType:  string;
  message:    string | null;
  status:     string;
  resolvedAt: string | null;
  createdAt:  string | null;
}

interface PageMeta {
  page: number;
  pageSize: number;
  total: number;
  hasMore: boolean;
}

// ── 常量 ──────────────────────────────────────────────────────────────────────

const LEVEL_COLOR: Record<string, string>  = { p1: 'red', p2: 'orange', p3: 'blue' };
const LEVEL_LABEL: Record<string, string>  = { p1: 'P1 严重', p2: 'P2 重要', p3: 'P3 一般' };

const ALERT_TYPES = [
  'headset_offline', 'hub_disconnect', 'device_error',
  'high_cpu', 'high_memory', 'firmware_outdated',
];

// ── 主组件 ────────────────────────────────────────────────────────────────────

const EdgeHubAlertsPage: React.FC = () => {
  const [alerts, setAlerts]       = useState<AlertItem[]>([]);
  const [meta, setMeta]           = useState<PageMeta>({ page: 1, pageSize: 20, total: 0, hasMore: false });
  const [loading, setLoading]     = useState(false);
  const [resolving, setResolving] = useState<string | null>(null);

  // 详情抽屉
  const [drawerAlert, setDrawerAlert] = useState<AlertItem | null>(null);

  // 筛选状态
  const [keyword,   setKeyword]   = useState('');
  const [status,    setStatus]    = useState<string>('');
  const [level,     setLevel]     = useState<string>('');
  const [storeId,   setStoreId]   = useState<string>('');
  const [page, setPage]           = useState(1);
  const pageSize = 20;

  const fetchAlerts = useCallback(async (pg = 1) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(pg), pageSize: String(pageSize) });
      if (status)  params.set('status',  status);
      if (level)   params.set('level',   level);
      if (storeId) params.set('store_id', storeId);

      const resp = await apiClient.get(`/api/v1/edge-hub/alerts?${params}`);
      let items: AlertItem[] = ((resp as any).data?.list) ?? [];

      // 客户端过滤关键词（alertType / message / storeId）
      if (keyword) {
        const kw = keyword.toLowerCase();
        items = items.filter(
          a =>
            a.alertType.includes(kw) ||
            a.storeId.toLowerCase().includes(kw) ||
            (a.message ?? '').toLowerCase().includes(kw)
        );
      }

      setAlerts(items);
      setMeta((resp as any).meta ?? { page: pg, pageSize, total: 0, hasMore: false });
      setPage(pg);
    } catch (err) {
      handleApiError(err);
    } finally {
      setLoading(false);
    }
  }, [keyword, status, level, storeId]);

  useEffect(() => { fetchAlerts(1); }, [status, level, storeId]);

  const handleResolve = async (alertId: string) => {
    setResolving(alertId);
    try {
      await apiClient.patch(`/api/v1/edge-hub/alerts/${alertId}/resolve`, {});
      message.success('告警已标记为已解决');
      await fetchAlerts(page);
    } catch (err) {
      handleApiError(err);
    } finally {
      setResolving(null);
    }
  };

  // ── 快速统计 ─────────────────────────────────────────────────────────────────
  const p1Count    = alerts.filter(a => a.level === 'p1' && a.status === 'open').length;
  const p2Count    = alerts.filter(a => a.level === 'p2' && a.status === 'open').length;
  const openCount  = alerts.filter(a => a.status === 'open').length;

  // ── 列定义 ───────────────────────────────────────────────────────────────────
  const columns = [
    {
      title: '级别', dataIndex: 'level', width: 100,
      render: (v: string) => <Tag color={LEVEL_COLOR[v] ?? 'default'}>{LEVEL_LABEL[v] ?? v.toUpperCase()}</Tag>,
    },
    {
      title: '门店', dataIndex: 'storeId', width: 100,
    },
    {
      title: '告警类型', dataIndex: 'alertType', width: 170,
      render: (v: string) => (
        <code className={styles.alertType}>{v.replace(/_/g, ' ')}</code>
      ),
    },
    {
      title: '描述', dataIndex: 'message', ellipsis: true,
      render: (v: string | null) => v ?? '—',
    },
    {
      title: '状态', dataIndex: 'status', width: 90,
      render: (v: string) => (
        <Tag color={v === 'open' ? 'red' : v === 'resolved' ? 'green' : 'default'}>
          {v === 'open' ? '未解决' : v === 'resolved' ? '已解决' : v}
        </Tag>
      ),
    },
    {
      title: '发生时间', dataIndex: 'createdAt', width: 140,
      render: (v: string | null) => v ? (
        <Tooltip title={dayjs(v).format('YYYY-MM-DD HH:mm:ss')}>
          {dayjs(v).format('MM-DD HH:mm')}
        </Tooltip>
      ) : '—',
      sorter: (a: AlertItem, b: AlertItem) =>
        new Date(a.createdAt ?? 0).getTime() - new Date(b.createdAt ?? 0).getTime(),
    },
    {
      title: '解决时间', dataIndex: 'resolvedAt', width: 130,
      render: (v: string | null) => v ? dayjs(v).format('MM-DD HH:mm') : '—',
    },
    {
      title: '操作', key: 'actions', width: 130, fixed: 'right' as const,
      render: (_: unknown, r: AlertItem) => (
        <Space size={4}>
          <Button
            type="link" size="small" icon={<InfoCircleOutlined />}
            onClick={() => setDrawerAlert(r)}
          >
            详情
          </Button>
          {r.status === 'open' && (
            <Popconfirm
              title="确认标记此告警为已解决？"
              onConfirm={() => handleResolve(r.id)}
              okText="确认" cancelText="取消"
            >
              <Button
                type="link" size="small" icon={<CheckCircleOutlined />}
                loading={resolving === r.id}
              >
                解决
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h2 className={styles.title}>告警管理</h2>
        <span className={styles.total}>共 {meta.total} 条告警</span>
      </div>

      {/* 快速统计 */}
      <Row gutter={[12, 12]} className={styles.statsRow}>
        <Col xs={8}>
          <Card size="small" className={styles.statCard}>
            <div className={styles.statNum} style={{ color: '#ff4d4f' }}>{p1Count}</div>
            <div className={styles.statLabel}>P1 严重（未解决）</div>
          </Card>
        </Col>
        <Col xs={8}>
          <Card size="small" className={styles.statCard}>
            <div className={styles.statNum} style={{ color: '#fa8c16' }}>{p2Count}</div>
            <div className={styles.statLabel}>P2 重要（未解决）</div>
          </Card>
        </Col>
        <Col xs={8}>
          <Card size="small" className={styles.statCard}>
            <div className={styles.statNum} style={{ color: openCount > 0 ? '#1677ff' : '#52c41a' }}>{openCount}</div>
            <div className={styles.statLabel}>未解决总数</div>
          </Card>
        </Col>
      </Row>

      {/* 筛选栏 */}
      <Card size="small" className={styles.filterCard}>
        <Space wrap>
          <Input
            prefix={<SearchOutlined />}
            placeholder="搜索告警类型 / 门店 / 描述"
            value={keyword}
            onChange={e => setKeyword(e.target.value)}
            onPressEnter={() => fetchAlerts(1)}
            style={{ width: 240 }}
            allowClear
          />
          <Select
            placeholder="全部级别"
            value={level || undefined}
            onChange={v => setLevel(v ?? '')}
            style={{ width: 120 }}
            allowClear
          >
            <Option value="p1">P1 严重</Option>
            <Option value="p2">P2 重要</Option>
            <Option value="p3">P3 一般</Option>
          </Select>
          <Select
            placeholder="全部状态"
            value={status || undefined}
            onChange={v => setStatus(v ?? '')}
            style={{ width: 120 }}
            allowClear
          >
            <Option value="open">未解决</Option>
            <Option value="resolved">已解决</Option>
            <Option value="ignored">已忽略</Option>
          </Select>
          <Input
            placeholder="按门店ID过滤"
            value={storeId}
            onChange={e => setStoreId(e.target.value)}
            style={{ width: 140 }}
            allowClear
          />
          <Button icon={<ReloadOutlined />} onClick={() => fetchAlerts(page)}>刷新</Button>
        </Space>
      </Card>

      {/* 告警表格 */}
      <Spin spinning={loading}>
        <Card size="small" style={{ marginTop: 0 }}>
          {alerts.length === 0 && !loading ? (
            <Empty description="暂无告警数据" />
          ) : (
            <Table
              dataSource={alerts}
              columns={columns}
              rowKey="id"
              size="small"
              scroll={{ x: 1000 }}
              pagination={{
                current: page,
                pageSize,
                total: meta.total,
                showSizeChanger: false,
                size: 'small',
                onChange: fetchAlerts,
              }}
              rowClassName={(r) => {
                if (r.level === 'p1' && r.status === 'open') return styles.p1Row;
                if (r.status === 'resolved') return styles.resolvedRow;
                return '';
              }}
            />
          )}
        </Card>
      </Spin>

      {/* 告警详情抽屉 */}
      <Drawer
        title={drawerAlert ? `告警详情 — ${drawerAlert.id.slice(0, 8)}…` : '告警详情'}
        open={!!drawerAlert}
        onClose={() => setDrawerAlert(null)}
        width={480}
        destroyOnClose
      >
        {drawerAlert && (
          <Descriptions size="small" column={1} bordered>
            <Descriptions.Item label="级别">
              <Tag color={LEVEL_COLOR[drawerAlert.level] ?? 'default'}>
                {LEVEL_LABEL[drawerAlert.level] ?? drawerAlert.level.toUpperCase()}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag color={drawerAlert.status === 'open' ? 'red' : 'green'}>
                {drawerAlert.status === 'open' ? '未解决' : '已解决'}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="门店">{drawerAlert.storeId}</Descriptions.Item>
            <Descriptions.Item label="告警类型">
              <code>{drawerAlert.alertType.replace(/_/g, ' ')}</code>
            </Descriptions.Item>
            <Descriptions.Item label="描述">{drawerAlert.message ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="Hub ID">{drawerAlert.hubId ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="设备 ID">{drawerAlert.deviceId ?? '—'}</Descriptions.Item>
            <Descriptions.Item label="发生时间">
              {drawerAlert.createdAt ? dayjs(drawerAlert.createdAt).format('YYYY-MM-DD HH:mm:ss') : '—'}
            </Descriptions.Item>
            <Descriptions.Item label="解决时间">
              {drawerAlert.resolvedAt ? dayjs(drawerAlert.resolvedAt).format('YYYY-MM-DD HH:mm:ss') : '—'}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Drawer>
    </div>
  );
};

export default EdgeHubAlertsPage;
