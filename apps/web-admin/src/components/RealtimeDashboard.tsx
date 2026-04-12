/**
 * RealtimeDashboard — 实时经营数据看板（可嵌入其他页面）
 *
 * 终端：Admin（总部管理后台）
 * 用途：域G 经营驾驶舱 / 任意需要实时数据的页面
 *
 * Props:
 *   storeId?  — 指定门店ID，不传则为全品牌汇总
 *   compact?  — 精简模式，只显示3个核心指标（营收/订单数/翻台率）
 *
 * 刷新策略：每30秒自动刷新，组件卸载时清除定时器
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Badge, Col, Row, Space, Spin, Tag, Typography } from 'antd';
import { StatisticCard } from '@ant-design/pro-components';
import {
  AlertOutlined,
  ClockCircleOutlined,
  ReloadOutlined,
  ShopOutlined,
  TeamOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';

const { Text } = Typography;

// ── 类型定义 ─────────────────────────────────────────────────────────────────

interface RealtimeData {
  as_of: string;
  revenue_fen: number;
  order_count: number;
  avg_order_fen: number;
  table_turnover: number;
  occupied_tables: number;
  total_tables: number;
  kitchen_queue: number;
  avg_wait_minutes: number;
  refund_count: number;
  refund_amount_fen: number;
  new_members_today: number;
  _is_mock?: boolean;
}

interface RealtimeDashboardProps {
  storeId?: string;
  compact?: boolean;
}

// ── 工具函数 ──────────────────────────────────────────────────────────────────

/** 分 → 元，带千分位 */
const fenToYuan = (fen: number): string =>
  (fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** 距上次刷新的描述 */
const formatAsOf = (isoStr: string): string => {
  const d = new Date(isoStr);
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}:${d.getSeconds().toString().padStart(2, '0')} 更新`;
};

// ── 组件 ──────────────────────────────────────────────────────────────────────

const REFRESH_INTERVAL_MS = 30_000;
const API_BASE = '/api/v1/analytics/realtime';

const RealtimeDashboard: React.FC<RealtimeDashboardProps> = ({
  storeId,
  compact = false,
}) => {
  const [data, setData] = useState<RealtimeData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const tenantId =
    typeof window !== 'undefined'
      ? (localStorage.getItem('tx_tenant_id') ?? 'demo-tenant')
      : 'demo-tenant';

  const fetchData = useCallback(async () => {
    try {
      const params = storeId ? `?store_id=${storeId}` : '';
      const res = await fetch(`${API_BASE}/today${params}`, {
        headers: { 'X-Tenant-ID': tenantId },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      if (!json.ok) throw new Error(json.error?.message ?? '接口返回异常');
      setData(json.data as RealtimeData);
      setError(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [storeId, tenantId]);

  useEffect(() => {
    void fetchData();
    const timer = setInterval(() => void fetchData(), REFRESH_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [fetchData]);

  // ── 加载态 ──
  if (loading && !data) {
    return (
      <div style={{ textAlign: 'center', padding: 40 }}>
        <Spin size="large" tip="加载实时数据…" />
      </div>
    );
  }

  // ── 错误态 ──
  if (error && !data) {
    return (
      <Alert
        type="error"
        message="实时数据加载失败"
        description={error}
        showIcon
        action={
          <Text
            style={{ cursor: 'pointer', color: '#FF6B35' }}
            onClick={() => { setLoading(true); void fetchData(); }}
          >
            <ReloadOutlined /> 重试
          </Text>
        }
      />
    );
  }

  if (!data) return null;

  // ── 厨房队列告警色 ──
  const kitchenQueueDanger = data.kitchen_queue > 10;
  const kitchenQueueWarning = !kitchenQueueDanger && data.kitchen_queue > 5;

  // ── 翻台率颜色 ──
  const turnoverColor =
    data.table_turnover >= 2.5 ? '#0F6E56' :
    data.table_turnover >= 1.5 ? '#BA7517' : '#A32D2D';

  // ── compact 模式（3个核心指标） ──────────────────────────────
  if (compact) {
    return (
      <Row gutter={12} align="middle">
        {/* 当日营收 */}
        <Col flex="auto">
          <StatisticCard
            statistic={{
              title: '当日营收',
              value: fenToYuan(data.revenue_fen),
              prefix: '¥',
              valueStyle: { fontSize: 20, fontWeight: 700, color: '#FF6B35' },
            }}
            style={{ minWidth: 160 }}
          />
        </Col>

        {/* 订单数 */}
        <Col flex="auto">
          <StatisticCard
            statistic={{
              title: '订单数',
              value: data.order_count,
              suffix: '单',
              valueStyle: { fontSize: 20, fontWeight: 700 },
            }}
            style={{ minWidth: 120 }}
          />
        </Col>

        {/* 翻台率 */}
        <Col flex="auto">
          <StatisticCard
            statistic={{
              title: '翻台率',
              value: data.table_turnover,
              suffix: '次',
              valueStyle: { fontSize: 20, fontWeight: 700, color: turnoverColor },
            }}
            style={{ minWidth: 120 }}
          />
        </Col>

        {/* 刷新时间 */}
        <Col>
          <Text type="secondary" style={{ fontSize: 12 }}>
            <ReloadOutlined spin={loading} style={{ marginRight: 4 }} />
            {formatAsOf(data.as_of)}
          </Text>
          {data._is_mock && (
            <Tag color="blue" style={{ marginLeft: 8, fontSize: 11 }}>
              Mock
            </Tag>
          )}
        </Col>
      </Row>
    );
  }

  // ── 完整模式（6个指标卡片） ──────────────────────────────────
  return (
    <div>
      {/* 副标题 + 刷新时间 */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 12,
        }}
      >
        <Space>
          <ThunderboltOutlined style={{ color: '#FF6B35' }} />
          <Text strong style={{ color: '#2C2C2A' }}>
            实时经营数据
          </Text>
          {data._is_mock && <Tag color="blue">Mock数据</Tag>}
        </Space>
        <Space>
          {loading && <Spin size="small" />}
          <Text type="secondary" style={{ fontSize: 12 }}>
            <ReloadOutlined style={{ marginRight: 4 }} />
            {formatAsOf(data.as_of)}，每30秒自动刷新
          </Text>
        </Space>
      </div>

      {/* 错误条（有缓存数据时展示，不遮挡整体） */}
      {error && (
        <Alert
          type="warning"
          message={`刷新失败：${error}，显示上次数据`}
          showIcon
          closable
          style={{ marginBottom: 12 }}
        />
      )}

      {/* 6个指标卡片 */}
      <Row gutter={[12, 12]}>
        {/* 1 · 当日营收 — 32px 大字，品牌色 */}
        <Col xs={24} sm={12} lg={8}>
          <StatisticCard
            statistic={{
              title: '当日营收',
              value: fenToYuan(data.revenue_fen),
              prefix: '¥',
              valueStyle: {
                fontSize: 32,
                fontWeight: 700,
                color: '#FF6B35',
                letterSpacing: '-0.5px',
              },
              description: (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  客单价 ¥{fenToYuan(data.avg_order_fen)}
                </Text>
              ),
            }}
          />
        </Col>

        {/* 2 · 订单数 */}
        <Col xs={24} sm={12} lg={8}>
          <StatisticCard
            statistic={{
              title: '订单数',
              value: data.order_count,
              suffix: '单',
              valueStyle: { fontSize: 32, fontWeight: 700 },
              description: (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  退单 {data.refund_count} 笔 / ¥{fenToYuan(data.refund_amount_fen)}
                </Text>
              ),
            }}
            // @ts-ignore - icon is a valid StatisticCard prop
            icon={<ShopOutlined style={{ fontSize: 24, color: '#185FA5' }} />}
          />
        </Col>

        {/* 3 · 翻台率 */}
        <Col xs={24} sm={12} lg={8}>
          <StatisticCard
            statistic={{
              title: '翻台率',
              value: data.table_turnover,
              suffix: '次',
              valueStyle: { fontSize: 32, fontWeight: 700, color: turnoverColor },
              description: (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {data.table_turnover >= 2.5 ? '高效运营' :
                   data.table_turnover >= 1.5 ? '正常水平' : '偏低，关注'}
                </Text>
              ),
            }}
          />
        </Col>

        {/* 4 · 在用桌台 / 总桌台 */}
        <Col xs={24} sm={12} lg={8}>
          <StatisticCard
            statistic={{
              title: '在用桌台',
              value: `${data.occupied_tables} / ${data.total_tables}`,
              valueStyle: { fontSize: 28, fontWeight: 700 },
              description: (
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <div
                    style={{
                      flex: 1,
                      height: 6,
                      borderRadius: 3,
                      background: '#E8E6E1',
                      overflow: 'hidden',
                    }}
                  >
                    <div
                      style={{
                        width: `${Math.round((data.occupied_tables / data.total_tables) * 100)}%`,
                        height: '100%',
                        background: '#FF6B35',
                        borderRadius: 3,
                        transition: 'width 0.6s ease',
                      }}
                    />
                  </div>
                  <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>
                    {Math.round((data.occupied_tables / data.total_tables) * 100)}% 上座
                  </Text>
                </div>
              ),
            }}
          />
        </Col>

        {/* 5 · 厨房队列 — >10 红色警告 */}
        <Col xs={24} sm={12} lg={8}>
          <StatisticCard
            statistic={{
              title: (
                <Space size={4}>
                  <span>厨房待出餐</span>
                  {kitchenQueueDanger && (
                    <Badge
                      status="error"
                      text={
                        <Text style={{ fontSize: 11, color: '#A32D2D' }}>
                          积压！
                        </Text>
                      }
                    />
                  )}
                  {kitchenQueueWarning && (
                    <Badge
                      status="warning"
                      text={
                        <Text style={{ fontSize: 11, color: '#BA7517' }}>
                          偏多
                        </Text>
                      }
                    />
                  )}
                </Space>
              ),
              value: data.kitchen_queue,
              suffix: '单',
              valueStyle: {
                fontSize: 32,
                fontWeight: 700,
                color: kitchenQueueDanger ? '#A32D2D' : kitchenQueueWarning ? '#BA7517' : '#0F6E56',
                // critical 时脉冲动画
                animation: kitchenQueueDanger
                  ? 'tx-pulse 1.5s ease-in-out infinite'
                  : undefined,
              },
            }}
            // @ts-ignore - icon is a valid StatisticCard prop
            icon={
              <AlertOutlined
                style={{
                  fontSize: 24,
                  color: kitchenQueueDanger ? '#A32D2D' : '#185FA5',
                }}
              />
            }
          />
        </Col>

        {/* 6 · 平均等待时长 */}
        <Col xs={24} sm={12} lg={8}>
          <StatisticCard
            statistic={{
              title: '平均等待',
              value: data.avg_wait_minutes,
              suffix: '分钟',
              valueStyle: {
                fontSize: 32,
                fontWeight: 700,
                color:
                  data.avg_wait_minutes <= 15 ? '#0F6E56' :
                  data.avg_wait_minutes <= 25 ? '#BA7517' : '#A32D2D',
              },
              description: (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  今日新会员 {data.new_members_today} 人
                </Text>
              ),
            }}
            // @ts-ignore - icon is a valid StatisticCard prop
            icon={<ClockCircleOutlined style={{ fontSize: 24, color: '#185FA5' }} />}
          />
        </Col>
      </Row>

      {/* 内联样式：脉冲动画 keyframe（StatisticCard valueStyle 中引用） */}
      <style>{`
        @keyframes tx-pulse {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.55; }
        }
      `}</style>
    </div>
  );
};

export default RealtimeDashboard;
