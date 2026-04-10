/**
 * 外部信号中心 — 天气信号 + 节庆日历 + 门店就绪度（V3.0）
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Tabs, Card, Tag, Button, Progress, Space, Drawer, Descriptions,
  Timeline, Row, Col, Spin, message, Table, Select, Empty,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  CloudOutlined,
  CalendarOutlined,
  ShopOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
  FireOutlined,
  CheckCircleOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import {
  fetchWeatherForecast,
  fetchCalendarUpcoming,
  fetchCalendarTriggers,
  fetchStoresReadinessRanking,
  fetchStoreGrowthReadiness,
  type WeatherSignal,
  type WeatherForecast,
  type CalendarEvent,
  type CalendarTrigger,
  type StoreReadinessRankItem,
  type StoreReadiness,
} from '../../../api/growthHubApi';

// ---- Weather Tab ----

const WEATHER_ICON_MAP: Record<string, string> = {
  rain: '🌧️',
  heavy_rain: '⛈️',
  snow: '❄️',
  extreme_heat: '🔥',
  extreme_cold: '🥶',
  sunny: '☀️',
  cloudy: '⛅',
};

const WEATHER_LABEL_MAP: Record<string, string> = {
  rain: '小雨',
  heavy_rain: '暴雨',
  snow: '雪',
  extreme_heat: '高温',
  extreme_cold: '严寒',
  sunny: '晴',
  cloudy: '多云',
};

function WeatherTab() {
  const [city, setCity] = useState('长沙');
  const [forecast, setForecast] = useState<WeatherForecast | null>(null);
  const [loading, setLoading] = useState(false);

  const loadForecast = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchWeatherForecast(city);
      setForecast(data);
    } catch {
      message.error('获取天气预报失败');
    } finally {
      setLoading(false);
    }
  }, [city]);

  useEffect(() => { loadForecast(); }, [loadForecast]);

  const impactColor = (val: number) => {
    if (val < -0.3) return '#A32D2D';
    if (val < -0.1) return '#BA7517';
    if (val > 0.1) return '#0F6E56';
    return '#666';
  };

  return (
    <Spin spinning={loading}>
      <div style={{ marginBottom: 16, display: 'flex', gap: 8, alignItems: 'center' }}>
        <Select
          value={city}
          onChange={setCity}
          style={{ width: 140 }}
          options={[
            { value: '长沙', label: '长沙' },
            { value: '深圳', label: '深圳' },
            { value: '北京', label: '北京' },
            { value: '上海', label: '上海' },
            { value: '广州', label: '广州' },
          ]}
        />
        <Button icon={<ReloadOutlined />} onClick={loadForecast}>刷新</Button>
        {forecast && (
          <span style={{ color: '#999', fontSize: 12 }}>
            预报周期: {forecast.period}
          </span>
        )}
      </div>

      {forecast && (
        <>
          <Row gutter={[12, 12]}>
            {forecast.daily_signals.map((sig: WeatherSignal) => (
              <Col key={sig.date} xs={24} sm={12} md={8} lg={6} xl={4}>
                <Card size="small" hoverable style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 10, color: '#999' }}>{sig.date}</div>
                  <div style={{ fontSize: 36, margin: '4px 0' }}>
                    {WEATHER_ICON_MAP[sig.weather_type] || '🌤️'}
                  </div>
                  <div style={{ fontWeight: 600 }}>
                    {WEATHER_LABEL_MAP[sig.weather_type] || sig.weather_type}
                  </div>
                  <div style={{ fontSize: 12, color: '#666' }}>
                    {sig.temperature_low}° ~ {sig.temperature_high}°
                  </div>
                  <div style={{ marginTop: 8 }}>
                    <Tag
                      color={sig.impact.traffic_impact < -0.2 ? 'red' : sig.impact.traffic_impact > 0 ? 'green' : 'default'}
                    >
                      客流 {sig.impact.traffic_impact > 0 ? '+' : ''}{(sig.impact.traffic_impact * 100).toFixed(0)}%
                    </Tag>
                  </div>
                  {sig.growth_recommendations.length > 0 && (
                    <div style={{ marginTop: 4 }}>
                      {sig.growth_recommendations.map((r, i) => (
                        <Tag key={i} color="blue" style={{ fontSize: 10, marginBottom: 2 }}>
                          {r.type === 'boost_delivery' ? '外卖加推' :
                           r.type === 'promote_indoor' ? '室内推荐' :
                           r.type === 'delivery_recall' ? '外卖召回' :
                           r.type === 'outdoor_dining' ? '户外推荐' : r.type}
                        </Tag>
                      ))}
                    </div>
                  )}
                </Card>
              </Col>
            ))}
          </Row>

          {forecast.aggregated_recommendations.length > 0 && (
            <Card title="汇总增长建议" size="small" style={{ marginTop: 16 }}>
              <Timeline
                items={forecast.aggregated_recommendations.map((r, i) => ({
                  key: i,
                  color: r.type === 'boost_delivery' ? 'red' :
                         r.type === 'delivery_recall' ? 'orange' :
                         r.type === 'promote_indoor' ? 'blue' : 'green',
                  children: (
                    <div>
                      <Tag>{r.date}</Tag>
                      <span>{r.description}</span>
                      {r.suggested_journey && (
                        <Tag color="purple" style={{ marginLeft: 8 }}>{r.suggested_journey}</Tag>
                      )}
                    </div>
                  ),
                }))}
              />
            </Card>
          )}
        </>
      )}
    </Spin>
  );
}


// ---- Calendar Tab ----

const EVENT_TYPE_MAP: Record<string, { label: string; color: string }> = {
  national: { label: '法定假日', color: 'red' },
  consumer: { label: '消费节日', color: 'magenta' },
  industry: { label: '行业节点', color: 'orange' },
};

const IMPACT_TAG: Record<string, { label: string; color: string }> = {
  high: { label: '高', color: 'red' },
  medium: { label: '中', color: 'orange' },
  low: { label: '低', color: 'default' },
};

function CalendarTab() {
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [triggers, setTriggers] = useState<CalendarTrigger[]>([]);
  const [loading, setLoading] = useState(false);
  const [days, setDays] = useState(14);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [evts, trigs] = await Promise.all([
        fetchCalendarUpcoming(days),
        fetchCalendarTriggers(),
      ]);
      setEvents(evts);
      setTriggers(trigs);
    } catch {
      message.error('获取节庆日历失败');
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => { load(); }, [load]);

  return (
    <Spin spinning={loading}>
      <div style={{ marginBottom: 16, display: 'flex', gap: 8, alignItems: 'center' }}>
        <span style={{ fontSize: 13 }}>展示范围:</span>
        <Select
          value={days}
          onChange={setDays}
          style={{ width: 120 }}
          options={[
            { value: 7, label: '未来7天' },
            { value: 14, label: '未来14天' },
            { value: 30, label: '未来30天' },
            { value: 60, label: '未来60天' },
          ]}
        />
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
      </div>

      {/* Active Triggers */}
      {triggers.length > 0 && (
        <Card
          title={<><ThunderboltOutlined style={{ color: '#FF6B35' }} /> 当前应触发的增长动作</>}
          size="small"
          style={{ marginBottom: 16, borderColor: '#FF6B35' }}
        >
          {triggers.map((t, i) => (
            <div key={i} style={{ padding: '8px 0', borderBottom: '1px solid #f0f0f0' }}>
              <Space>
                <Tag color={EVENT_TYPE_MAP[t.event_type]?.color || 'blue'}>
                  {EVENT_TYPE_MAP[t.event_type]?.label || t.event_type}
                </Tag>
                <strong>{t.event_name}</strong>
                <span style={{ color: '#666' }}>
                  {t.days_until === 0 ? '今天' : `${t.days_until}天后`}
                </span>
                <Tag color={IMPACT_TAG[t.impact]?.color}>影响: {IMPACT_TAG[t.impact]?.label}</Tag>
              </Space>
              <div style={{ color: '#333', marginTop: 4, fontSize: 13 }}>{t.description}</div>
              {t.suggested_journey && (
                <Button size="small" type="primary" style={{ marginTop: 4 }} icon={<FireOutlined />}>
                  发起旅程: {t.suggested_journey}
                </Button>
              )}
            </div>
          ))}
        </Card>
      )}

      {/* Event Timeline */}
      {events.length > 0 ? (
        <Timeline
          items={events.map((evt, i) => ({
            key: i,
            color: evt.should_push_now ? '#FF6B35' : '#1890ff',
            dot: evt.should_push_now ? <ThunderboltOutlined style={{ color: '#FF6B35' }} /> : undefined,
            children: (
              <div>
                <Space>
                  <Tag color={EVENT_TYPE_MAP[evt.type]?.color || 'blue'}>
                    {EVENT_TYPE_MAP[evt.type]?.label || evt.type}
                  </Tag>
                  <strong>{evt.name}</strong>
                  <span style={{ color: '#999' }}>{evt.date}</span>
                  <Tag color={IMPACT_TAG[evt.impact]?.color}>
                    {IMPACT_TAG[evt.impact]?.label}
                  </Tag>
                  {evt.days_until <= 3 && (
                    <Tag color="red">{evt.days_until === 0 ? '今天' : `${evt.days_until}天后`}</Tag>
                  )}
                  {evt.days_until > 3 && (
                    <span style={{ color: '#999', fontSize: 12 }}>还有{evt.days_until}天</span>
                  )}
                </Space>
                {evt.should_push_now && (
                  <div style={{ marginTop: 4 }}>
                    <Tag color="volcano">应立即推送</Tag>
                    {evt.suggested_journey && (
                      <Tag color="purple">建议旅程: {evt.suggested_journey}</Tag>
                    )}
                    {evt.target_segment && (
                      <Tag color="cyan">目标人群: {evt.target_segment}</Tag>
                    )}
                    {evt.seasonal_dish && (
                      <Tag color="orange">应季菜: {evt.seasonal_dish}</Tag>
                    )}
                  </div>
                )}
              </div>
            ),
          }))}
        />
      ) : (
        <Empty description="当前时间段无节庆事件" />
      )}
    </Spin>
  );
}


// ---- Store Readiness Tab ----

function StoreReadinessTab() {
  const [stores, setStores] = useState<StoreReadinessRankItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedReadiness, setSelectedReadiness] = useState<StoreReadiness | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const loadRanking = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchStoresReadinessRanking();
      setStores(data.stores);
    } catch {
      message.error('获取门店就绪度排行失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadRanking(); }, [loadRanking]);

  const openDetail = async (storeId: string) => {
    setDrawerOpen(true);
    setDetailLoading(true);
    try {
      const data = await fetchStoreGrowthReadiness(storeId);
      setSelectedReadiness(data);
    } catch {
      message.error('获取门店详情失败');
    } finally {
      setDetailLoading(false);
    }
  };

  const columns: ColumnsType<StoreReadinessRankItem> = [
    {
      title: '排名',
      width: 60,
      render: (_v, _r, idx) => idx + 1,
    },
    {
      title: '门店名称',
      dataIndex: 'store_name',
      width: 180,
    },
    {
      title: '城市',
      dataIndex: 'city',
      width: 80,
    },
    {
      title: '座位数',
      dataIndex: 'seats',
      width: 80,
      sorter: (a, b) => (a.seats ?? 0) - (b.seats ?? 0),
    },
    {
      title: '就绪度',
      dataIndex: 'readiness_pct',
      width: 200,
      sorter: (a, b) => a.readiness_pct - b.readiness_pct,
      defaultSortOrder: 'descend',
      render: (val: number) => (
        <Progress
          percent={val}
          size="small"
          strokeColor={val >= 80 ? '#0F6E56' : val >= 60 ? '#FF6B35' : '#A32D2D'}
          format={(p) => `${p}%`}
        />
      ),
    },
    {
      title: '支持旅程数',
      dataIndex: 'supported_journeys',
      width: 100,
      render: (val: number) => (
        <span>
          {val >= 8 ? <CheckCircleOutlined style={{ color: '#0F6E56', marginRight: 4 }} /> :
           val >= 6 ? null :
           <WarningOutlined style={{ color: '#BA7517', marginRight: 4 }} />}
          {val}/10
        </span>
      ),
    },
    {
      title: '操作',
      width: 100,
      render: (_v, record) => (
        <Button type="link" size="small" onClick={() => openDetail(record.store_id)}>
          查看详情
        </Button>
      ),
    },
  ];

  const CAP_LABELS: Record<string, string> = {
    has_private_room: '包厢',
    has_live_seafood: '活鲜',
    has_outdoor_seating: '露台',
    has_delivery: '外卖',
    has_stored_value: '储值卡',
  };

  return (
    <>
      <Table
        rowKey="store_id"
        columns={columns}
        dataSource={stores}
        loading={loading}
        pagination={{ defaultPageSize: 20 }}
        size="small"
      />

      <Drawer
        title={selectedReadiness ? `${selectedReadiness.store_name} — 增长就绪度` : '门店详情'}
        open={drawerOpen}
        onClose={() => { setDrawerOpen(false); setSelectedReadiness(null); }}
        width={480}
      >
        <Spin spinning={detailLoading}>
          {selectedReadiness && (
            <>
              <div style={{ textAlign: 'center', marginBottom: 24 }}>
                <Progress
                  type="dashboard"
                  percent={selectedReadiness.readiness_pct}
                  strokeColor={selectedReadiness.readiness_pct >= 80 ? '#0F6E56' : '#FF6B35'}
                  format={(p) => <span style={{ fontSize: 20 }}>{p}%</span>}
                />
                <div style={{ color: '#666', marginTop: 8 }}>
                  支持 {selectedReadiness.supported_journeys}/{selectedReadiness.total_journeys} 种旅程
                </div>
              </div>

              <Descriptions title="能力标签" column={2} bordered size="small">
                {Object.entries(selectedReadiness.capabilities).map(([key, val]) => (
                  <Descriptions.Item key={key} label={CAP_LABELS[key] || key}>
                    {val
                      ? <Tag color="green"><CheckCircleOutlined /> 已开启</Tag>
                      : <Tag color="default"><WarningOutlined /> 未开启</Tag>
                    }
                  </Descriptions.Item>
                ))}
              </Descriptions>

              {selectedReadiness.missing_capabilities.length > 0 && (
                <Card title="能力提升建议" size="small" style={{ marginTop: 16 }}>
                  {selectedReadiness.missing_capabilities.map((mc, i) => (
                    <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid #f5f5f5' }}>
                      <Tag color="orange">{CAP_LABELS[mc.capability] || mc.capability}</Tag>
                      <span style={{ fontSize: 13 }}>{mc.recommendation}</span>
                    </div>
                  ))}
                </Card>
              )}
            </>
          )}
        </Spin>
      </Drawer>
    </>
  );
}


// ---- Main Page ----

export function ExternalSignalsPage() {
  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginBottom: 16 }}>外部信号中心</h2>
      <Tabs
        defaultActiveKey="weather"
        items={[
          {
            key: 'weather',
            label: <><CloudOutlined /> 天气信号</>,
            children: <WeatherTab />,
          },
          {
            key: 'calendar',
            label: <><CalendarOutlined /> 节庆日历</>,
            children: <CalendarTab />,
          },
          {
            key: 'store-readiness',
            label: <><ShopOutlined /> 门店就绪度</>,
            children: <StoreReadinessTab />,
          },
        ]}
      />
    </div>
  );
}
