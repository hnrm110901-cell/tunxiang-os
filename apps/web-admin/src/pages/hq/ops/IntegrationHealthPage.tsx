/**
 * 集成健康中心 — Integration Health Center
 * 监控10个旧系统适配器和外部平台的连接状态
 */
import { useEffect, useState, useCallback } from 'react';
import {
  Card, Row, Col, Tag, Badge, Drawer, Tabs, Table, Timeline, Button,
  Statistic, Space, Tooltip, message, Spin, Progress, Empty,
} from 'antd';
import {
  SyncOutlined, CheckCircleFilled, WarningFilled, CloseCircleFilled,
  ReloadOutlined, ClockCircleOutlined, ApiOutlined,
} from '@ant-design/icons';
import {
  fetchIntegrationHealth, fetchAdapterDetail, retryAdapterSync,
  fetchRecentWebhooks,
} from '../../../api/integrationHealthApi';
import type { AdapterHealth, AdapterStatus, WebhookEvent } from '../../../api/integrationHealthApi';

// ─── 常量 ───

const ADAPTERS = [
  { id: 'pinzhi', name: '品智POS', icon: '🔌', description: '订单/菜品/会员/库存' },
  { id: 'aoqiwei', name: '奥琦玮', icon: '🔗', description: 'POS数据' },
  { id: 'tiancai', name: '天财商龙', icon: '🏪', description: 'POS数据' },
  { id: 'keruyun', name: '客如云', icon: '☁️', description: 'POS数据' },
  { id: 'weishenghuo', name: '微生活', icon: '👤', description: '会员数据' },
  { id: 'meituan', name: '美团SaaS', icon: '🛵', description: '外卖订单' },
  { id: 'eleme', name: '饿了么', icon: '🥡', description: '外卖订单' },
  { id: 'douyin', name: '抖音来客', icon: '🎵', description: '团购/外卖' },
  { id: 'yiding', name: '易鼎', icon: '🔧', description: 'POS数据' },
  { id: 'nuonuo', name: '诺诺发票', icon: '🧾', description: '电子发票' },
] as const;

const REFRESH_INTERVAL = 30_000;

const STATUS_MAP: Record<AdapterStatus, { label: string; color: string; icon: React.ReactNode }> = {
  online:   { label: '正常',  color: '#0F6E56', icon: <CheckCircleFilled style={{ color: '#0F6E56' }} /> },
  degraded: { label: '降级',  color: '#BA7517', icon: <WarningFilled style={{ color: '#BA7517' }} /> },
  offline:  { label: '离线',  color: '#A32D2D', icon: <CloseCircleFilled style={{ color: '#A32D2D' }} /> },
};

const WEBHOOK_STATUS_MAP: Record<string, { label: string; color: string }> = {
  processed: { label: '成功', color: '#0F6E56' },
  failed:    { label: '失败', color: '#A32D2D' },
  pending:   { label: '待处理', color: '#BA7517' },
};

// ─── 工具函数 ───

function formatSyncDelay(seconds: number): { text: string; color: string } {
  if (seconds < 0) return { text: '未同步', color: '#A32D2D' };
  if (seconds < 60) return { text: `${seconds}秒前`, color: '#0F6E56' };
  const minutes = Math.floor(seconds / 60);
  if (minutes < 30) return { text: `${minutes}分钟前`, color: '#0F6E56' };
  const hours = Math.floor(minutes / 60);
  if (minutes < 120) return { text: `${minutes}分钟前`, color: '#BA7517' };
  return { text: `${hours}小时前`, color: '#A32D2D' };
}

function formatNumber(n: number): string {
  if (n >= 10000) return `${(n / 10000).toFixed(1)}万`;
  return n.toLocaleString('zh-CN');
}

function formatTime(iso: string): string {
  if (!iso) return '-';
  return new Date(iso).toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

// ─── 子组件：适配器卡片 ───

function AdapterCard({
  adapter,
  health,
  onClickCard,
  onRetry,
  retrying,
}: {
  adapter: typeof ADAPTERS[number];
  health: AdapterHealth | undefined;
  onClickCard: () => void;
  onRetry: () => void;
  retrying: boolean;
}) {
  const status = health?.status ?? 'offline';
  const statusInfo = STATUS_MAP[status];
  const delay = health ? formatSyncDelay(health.sync_delay_seconds) : { text: '未接入', color: '#888' };
  const totalSynced = health
    ? health.today_synced.orders + health.today_synced.members + health.today_synced.dishes
    : 0;

  return (
    <Card
      size="small"
      hoverable
      onClick={onClickCard}
      style={{ borderLeft: `3px solid ${statusInfo.color}`, height: '100%' }}
      styles={{ body: { padding: '16px' } }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 24 }}>{adapter.icon}</span>
          <div>
            <div style={{ fontWeight: 600, fontSize: 14, lineHeight: 1.4 }}>{adapter.name}</div>
            <div style={{ color: '#888', fontSize: 12 }}>{adapter.description}</div>
          </div>
        </div>
        <Badge
          status={status === 'online' ? 'success' : status === 'degraded' ? 'warning' : 'error'}
          text={<span style={{ fontSize: 12, color: statusInfo.color }}>{statusInfo.label}</span>}
        />
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 13 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: '#888' }}>
            <ClockCircleOutlined style={{ marginRight: 4 }} />
            最后同步
          </span>
          <span style={{ color: delay.color, fontWeight: 500 }}>{delay.text}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: '#888' }}>今日同步量</span>
          <span style={{ fontWeight: 500 }}>{formatNumber(totalSynced)} 条</span>
        </div>
        {health && health.recent_failures > 0 && (
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ color: '#888' }}>最近失败</span>
            <Tag color="error" style={{ margin: 0 }}>{health.recent_failures} 次</Tag>
          </div>
        )}
      </div>

      <div style={{ marginTop: 12, textAlign: 'right' }}>
        <Button
          size="small"
          icon={<ReloadOutlined spin={retrying} />}
          loading={retrying}
          onClick={(e) => { e.stopPropagation(); onRetry(); }}
          disabled={status === 'online' && (health?.recent_failures ?? 0) === 0}
        >
          重试
        </Button>
      </div>
    </Card>
  );
}

// ─── 子组件：详情 Drawer ───

function AdapterDetailDrawer({
  adapterId,
  open,
  onClose,
}: {
  adapterId: string | null;
  open: boolean;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<AdapterHealth | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!adapterId || !open) return;
    let cancelled = false;
    setLoading(true);
    fetchAdapterDetail(adapterId)
      .then((d) => { if (!cancelled) setDetail(d); })
      .catch(() => { /* 保留旧数据 */ })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [adapterId, open]);

  const adapterMeta = ADAPTERS.find((a) => a.id === adapterId);
  if (!adapterMeta) return null;

  const failedLogs = detail?.recent_logs.filter((l) => l.status === 'failure') ?? [];

  const volumeData = detail?.daily_volumes ?? [];
  const maxVolume = Math.max(...volumeData.map((v) => v.count), 1);

  return (
    <Drawer
      title={
        <Space>
          <span style={{ fontSize: 20 }}>{adapterMeta.icon}</span>
          <span>{adapterMeta.name} - 详情</span>
          {detail && (
            <Tag color={STATUS_MAP[detail.status].color} style={{ marginLeft: 8 }}>
              {STATUS_MAP[detail.status].label}
            </Tag>
          )}
        </Space>
      }
      width={640}
      open={open}
      onClose={onClose}
      destroyOnClose
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: 60 }}><Spin size="large" /></div>
      ) : !detail ? (
        <Empty description="暂无数据" />
      ) : (
        <Tabs
          defaultActiveKey="config"
          items={[
            {
              key: 'config',
              label: '同步配置',
              children: (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                  <Card size="small" title="连接配置">
                    <Row gutter={16}>
                      <Col span={12}>
                        <Statistic
                          title="同步间隔"
                          value={detail.config.sync_interval_seconds}
                          suffix="秒"
                        />
                      </Col>
                      <Col span={12}>
                        <Statistic
                          title="24h错误率"
                          value={detail.error_rate_24h}
                          precision={2}
                          suffix="%"
                          valueStyle={{
                            color: detail.error_rate_24h > 5 ? '#A32D2D'
                              : detail.error_rate_24h > 1 ? '#BA7517' : '#0F6E56',
                          }}
                        />
                      </Col>
                    </Row>
                    <div style={{ marginTop: 16, fontSize: 13, color: '#666' }}>
                      <div><strong>API 端点：</strong>{detail.config.api_endpoint}</div>
                      <div style={{ marginTop: 4 }}><strong>认证方式：</strong>{detail.config.auth_type}</div>
                    </div>
                  </Card>

                  <Card size="small" title="今日同步统计">
                    <Row gutter={16}>
                      <Col span={8}>
                        <Statistic title="订单" value={detail.today_synced.orders} />
                      </Col>
                      <Col span={8}>
                        <Statistic title="会员" value={detail.today_synced.members} />
                      </Col>
                      <Col span={8}>
                        <Statistic title="菜品" value={detail.today_synced.dishes} />
                      </Col>
                    </Row>
                  </Card>
                </div>
              ),
            },
            {
              key: 'timeline',
              label: '同步时间线（24h）',
              children: (
                <div style={{ maxHeight: 480, overflowY: 'auto' }}>
                  {detail.recent_logs.length === 0 ? (
                    <Empty description="暂无同步记录" />
                  ) : (
                    <Timeline
                      items={detail.recent_logs.map((log, i) => ({
                        key: i,
                        color: log.status === 'success' ? '#0F6E56' : '#A32D2D',
                        children: (
                          <div>
                            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                              <strong>{log.event}</strong>
                              <Tag
                                color={log.status === 'success' ? 'success' : 'error'}
                                style={{ margin: 0 }}
                              >
                                {log.status === 'success' ? '成功' : '失败'}
                              </Tag>
                            </div>
                            <div style={{ fontSize: 12, color: '#888', marginTop: 4 }}>
                              {formatTime(log.time)} | 耗时 {formatDuration(log.duration_ms)}
                            </div>
                            {log.error && (
                              <div style={{ fontSize: 12, color: '#A32D2D', marginTop: 4 }}>
                                {log.error}
                              </div>
                            )}
                          </div>
                        ),
                      }))}
                    />
                  )}
                </div>
              ),
            },
            {
              key: 'failures',
              label: (
                <span>
                  失败记录
                  {failedLogs.length > 0 && (
                    <Badge count={failedLogs.length} size="small" style={{ marginLeft: 6 }} />
                  )}
                </span>
              ),
              children: (
                <Table
                  dataSource={failedLogs}
                  rowKey={(_, i) => String(i)}
                  size="small"
                  pagination={{ pageSize: 10 }}
                  columns={[
                    {
                      title: '时间',
                      dataIndex: 'time',
                      width: 150,
                      render: (v: string) => formatTime(v),
                    },
                    {
                      title: '事件',
                      dataIndex: 'event',
                      width: 140,
                    },
                    {
                      title: '错误信息',
                      dataIndex: 'error',
                      ellipsis: true,
                      render: (v: string) => (
                        <Tooltip title={v}>
                          <span style={{ color: '#A32D2D' }}>{v || '-'}</span>
                        </Tooltip>
                      ),
                    },
                    {
                      title: '耗时',
                      dataIndex: 'duration_ms',
                      width: 80,
                      render: (v: number) => formatDuration(v),
                    },
                  ]}
                />
              ),
            },
            {
              key: 'volume',
              label: '数据量趋势（7天）',
              children: (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {volumeData.length === 0 ? (
                    <Empty description="暂无趋势数据" />
                  ) : (
                    volumeData.map((item) => (
                      <div key={item.date} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                        <span style={{ width: 80, fontSize: 13, color: '#666', flexShrink: 0 }}>
                          {item.date.slice(5)}
                        </span>
                        <Progress
                          percent={Math.round((item.count / maxVolume) * 100)}
                          showInfo={false}
                          strokeColor="#FF6B35"
                          style={{ flex: 1 }}
                        />
                        <span style={{ width: 70, fontSize: 13, textAlign: 'right', flexShrink: 0 }}>
                          {formatNumber(item.count)}
                        </span>
                      </div>
                    ))
                  )}
                </div>
              ),
            },
          ]}
        />
      )}
    </Drawer>
  );
}

// ─── 主页面 ───

export function IntegrationHealthPage() {
  const [healthList, setHealthList] = useState<AdapterHealth[]>([]);
  const [webhooks, setWebhooks] = useState<WebhookEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'adapters' | 'webhooks'>('adapters');
  const [drawerAdapterId, setDrawerAdapterId] = useState<string | null>(null);
  const [retryingMap, setRetryingMap] = useState<Record<string, boolean>>({});
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [countdown, setCountdown] = useState(REFRESH_INTERVAL / 1000);

  // 构建 adapter_id → health 映射
  const healthMap: Record<string, AdapterHealth> = {};
  for (const h of healthList) {
    healthMap[h.adapter_id] = h;
  }

  const fetchData = useCallback(async () => {
    try {
      const [health, wh] = await Promise.all([
        fetchIntegrationHealth(),
        fetchRecentWebhooks(50),
      ]);
      setHealthList(health);
      setWebhooks(wh);
      setLastRefresh(new Date());
      setCountdown(REFRESH_INTERVAL / 1000);
    } catch {
      /* 保留旧数据 */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, REFRESH_INTERVAL);
    return () => clearInterval(timer);
  }, [fetchData]);

  useEffect(() => {
    const timer = setInterval(() => setCountdown((c) => Math.max(0, c - 1)), 1000);
    return () => clearInterval(timer);
  }, [lastRefresh]);

  const handleRetry = useCallback(async (adapterId: string) => {
    setRetryingMap((m) => ({ ...m, [adapterId]: true }));
    try {
      await retryAdapterSync(adapterId);
      message.success(`${ADAPTERS.find((a) => a.id === adapterId)?.name ?? adapterId} 重试已触发`);
      // 刷新数据
      setTimeout(fetchData, 2000);
    } catch (err: unknown) {
      message.error(`重试失败：${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setRetryingMap((m) => ({ ...m, [adapterId]: false }));
    }
  }, [fetchData]);

  // 汇总统计
  const onlineCount = healthList.filter((h) => h.status === 'online').length;
  const degradedCount = healthList.filter((h) => h.status === 'degraded').length;
  const offlineCount = healthList.filter((h) => h.status === 'offline').length;
  const totalAdapters = ADAPTERS.length;
  const healthPercent = totalAdapters > 0
    ? Math.round(((onlineCount + degradedCount * 0.5) / totalAdapters) * 100)
    : 0;

  return (
    <div style={{ padding: 24, minHeight: '100vh', background: '#0d1e28', color: '#fff' }}>
      {/* 页头 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>
            <ApiOutlined style={{ marginRight: 8 }} />
            集成健康中心
          </h2>
          <p style={{ color: '#888', margin: '4px 0 0', fontSize: 13 }}>
            监控 {totalAdapters} 个旧系统适配器与外部平台的连接状态
          </p>
        </div>
        <div style={{ textAlign: 'right' }}>
          <button
            onClick={fetchData}
            style={{
              padding: '6px 14px', borderRadius: 6, border: '1px solid #2a3a44',
              background: 'transparent', color: '#888', cursor: 'pointer', fontSize: 13, marginBottom: 4,
            }}
          >
            <SyncOutlined style={{ marginRight: 4 }} />
            立即刷新
          </button>
          <div style={{ color: '#888', fontSize: 12 }}>
            {countdown}s 后自动刷新 · 上次 {lastRefresh.toLocaleTimeString('zh-CN')}
          </div>
        </div>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 60, color: '#888' }}>
          <Spin size="large" />
          <div style={{ marginTop: 16 }}>加载中...</div>
        </div>
      ) : (
        <>
          {/* 顶部汇总 */}
          <div style={{
            background: '#1a2a33', borderRadius: 12, padding: '20px 24px', marginBottom: 24,
            display: 'flex', alignItems: 'center', gap: 32,
            border: `1px solid ${healthPercent >= 80 ? '#0F6E5644' : healthPercent >= 50 ? '#BA751744' : '#A32D2D44'}`,
          }}>
            <div style={{ textAlign: 'center', minWidth: 100 }}>
              <Progress
                type="circle"
                percent={healthPercent}
                size={80}
                strokeColor={healthPercent >= 80 ? '#0F6E56' : healthPercent >= 50 ? '#BA7517' : '#A32D2D'}
                trailColor="#2a3a44"
                format={(p) => <span style={{ color: '#fff', fontSize: 20, fontWeight: 700 }}>{p}%</span>}
              />
              <div style={{ color: '#888', fontSize: 12, marginTop: 8 }}>整体健康度</div>
            </div>

            <div style={{ display: 'flex', gap: 40, flex: 1 }}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 32, fontWeight: 700, color: '#0F6E56' }}>{onlineCount}</div>
                <div style={{ color: '#888', fontSize: 13, marginTop: 4 }}>
                  <CheckCircleFilled style={{ color: '#0F6E56', marginRight: 4 }} />
                  正常
                </div>
              </div>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 32, fontWeight: 700, color: '#BA7517' }}>{degradedCount}</div>
                <div style={{ color: '#888', fontSize: 13, marginTop: 4 }}>
                  <WarningFilled style={{ color: '#BA7517', marginRight: 4 }} />
                  降级
                </div>
              </div>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 32, fontWeight: 700, color: '#A32D2D' }}>{offlineCount}</div>
                <div style={{ color: '#888', fontSize: 13, marginTop: 4 }}>
                  <CloseCircleFilled style={{ color: '#A32D2D', marginRight: 4 }} />
                  离线
                </div>
              </div>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 32, fontWeight: 700, color: '#888' }}>
                  {totalAdapters - onlineCount - degradedCount - offlineCount}
                </div>
                <div style={{ color: '#888', fontSize: 13, marginTop: 4 }}>未接入</div>
              </div>
            </div>
          </div>

          {/* 主内容 Tab 切换 */}
          <div style={{ marginBottom: 16, display: 'flex', gap: 8 }}>
            <button
              onClick={() => setActiveTab('adapters')}
              style={{
                padding: '8px 20px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 14,
                background: activeTab === 'adapters' ? '#FF6B35' : '#1a2a33',
                color: activeTab === 'adapters' ? '#fff' : '#888',
                fontWeight: activeTab === 'adapters' ? 600 : 400,
              }}
            >
              适配器状态
            </button>
            <button
              onClick={() => setActiveTab('webhooks')}
              style={{
                padding: '8px 20px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 14,
                background: activeTab === 'webhooks' ? '#FF6B35' : '#1a2a33',
                color: activeTab === 'webhooks' ? '#fff' : '#888',
                fontWeight: activeTab === 'webhooks' ? 600 : 400,
              }}
            >
              Webhook 日志
              {webhooks.filter((w) => w.status === 'failed').length > 0 && (
                <Badge
                  count={webhooks.filter((w) => w.status === 'failed').length}
                  size="small"
                  style={{ marginLeft: 6 }}
                />
              )}
            </button>
          </div>

          {/* 适配器卡片网格 */}
          {activeTab === 'adapters' && (
            <Row gutter={[16, 16]}>
              {ADAPTERS.map((adapter) => (
                <Col key={adapter.id} xs={24} sm={12} md={8} lg={6} xl={{ span: 24 / 5 }} xxl={{ span: 24 / 5 }}>
                  <AdapterCard
                    adapter={adapter}
                    health={healthMap[adapter.id]}
                    onClickCard={() => setDrawerAdapterId(adapter.id)}
                    onRetry={() => handleRetry(adapter.id)}
                    retrying={!!retryingMap[adapter.id]}
                  />
                </Col>
              ))}
            </Row>
          )}

          {/* Webhook 日志表格 */}
          {activeTab === 'webhooks' && (
            <div style={{ background: '#1a2a33', borderRadius: 12, overflow: 'hidden' }}>
              <Table<WebhookEvent>
                dataSource={webhooks}
                rowKey="id"
                size="small"
                pagination={{ pageSize: 20 }}
                style={{ background: 'transparent' }}
                columns={[
                  {
                    title: '时间',
                    dataIndex: 'received_at',
                    width: 160,
                    render: (v: string) => (
                      <span style={{ color: '#ccc', fontSize: 13 }}>{formatTime(v)}</span>
                    ),
                    sorter: (a, b) => new Date(a.received_at).getTime() - new Date(b.received_at).getTime(),
                    defaultSortOrder: 'descend',
                  },
                  {
                    title: '来源',
                    dataIndex: 'source',
                    width: 120,
                    render: (v: string) => {
                      const adapter = ADAPTERS.find((a) => a.id === v);
                      return (
                        <span>
                          {adapter ? `${adapter.icon} ${adapter.name}` : v}
                        </span>
                      );
                    },
                    filters: ADAPTERS.map((a) => ({ text: `${a.icon} ${a.name}`, value: a.id })),
                    onFilter: (value, record) => record.source === value,
                  },
                  {
                    title: '事件类型',
                    dataIndex: 'event_type',
                    width: 180,
                    render: (v: string) => <Tag style={{ margin: 0 }}>{v}</Tag>,
                  },
                  {
                    title: '状态',
                    dataIndex: 'status',
                    width: 90,
                    render: (v: string) => {
                      const info = WEBHOOK_STATUS_MAP[v] ?? { label: v, color: '#888' };
                      return <Tag color={info.color} style={{ margin: 0 }}>{info.label}</Tag>;
                    },
                    filters: [
                      { text: '成功', value: 'processed' },
                      { text: '失败', value: 'failed' },
                      { text: '待处理', value: 'pending' },
                    ],
                    onFilter: (value, record) => record.status === value,
                  },
                  {
                    title: '响应时间',
                    dataIndex: 'response_ms',
                    width: 100,
                    render: (v: number) => (
                      <span style={{ color: v > 3000 ? '#A32D2D' : v > 1000 ? '#BA7517' : '#0F6E56' }}>
                        {formatDuration(v)}
                      </span>
                    ),
                    sorter: (a, b) => a.response_ms - b.response_ms,
                  },
                  {
                    title: '载荷大小',
                    dataIndex: 'payload_size',
                    width: 100,
                    render: (v: number) => {
                      if (v < 1024) return `${v} B`;
                      return `${(v / 1024).toFixed(1)} KB`;
                    },
                  },
                ]}
              />
            </div>
          )}
        </>
      )}

      {/* 适配器详情 Drawer */}
      <AdapterDetailDrawer
        adapterId={drawerAdapterId}
        open={!!drawerAdapterId}
        onClose={() => setDrawerAdapterId(null)}
      />
    </div>
  );
}
