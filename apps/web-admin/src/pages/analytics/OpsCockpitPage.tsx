/**
 * OpsCockpitPage — 实时运营驾驶舱
 *
 * 终端：Admin（总部管理后台）
 * 域G：经营分析
 *
 * 布局：
 *   顶栏       — 页面标题 + 最后更新时间 + 门店选择器 + 自动刷新开关
 *   预警横幅   — 可折叠：折扣异常(红) / 食安违规(红) / 日结未完成(橙) / 客户流失(橙)
 *   KPI卡片行  — 4张响应式卡片：今日营收 / 翻台率 / 员工效率 / 客户健康
 *   渠道毛利图  — ECharts 分组柱状图：到店/美团/饿了么/抖音
 *   菜品毛利表  — Ant Table：Top 10 按毛利率排序
 *   日结进度    — 各门店日结完成进度条
 *   底部状态栏  — WebSocket 连接状态 + 最后刷新时间戳
 *
 * 数据源：
 *   GET  /api/v1/analytics/cockpit/overview?store_id=xxx
 *   GET  /api/v1/analytics/cockpit/alerts
 *   WS   /api/v1/analytics/cockpit/ws（可选实时推送）
 *
 * 技术：React 18 + Ant Design 5.x + ECharts (echarts-for-react) + dayjs
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Row, Col, Card, Tag, Badge, Typography, Button, Select,
  Space, Table, Tooltip, Progress, Collapse, Spin, Empty, Result,
} from 'antd';
import { StatisticCard } from '@ant-design/pro-components';
import type { ColumnsType } from 'antd/es/table';
import {
  ReloadOutlined,
  WarningFilled,
  CloseCircleFilled,
  CheckCircleFilled,
  InfoCircleFilled,
  ClockCircleFilled,
  HomeFilled,
  SyncOutlined,
  TeamOutlined,
  DollarOutlined,
  UserOutlined,
  CaretUpOutlined,
  CaretDownOutlined,
  ThunderboltOutlined,
  AlertOutlined,
} from '@ant-design/icons';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import { BarChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import dayjs from 'dayjs';
import { apiGet } from '../../api/client';
import { formatPrice } from '@tx-ds/utils';

echarts.use([BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

const { Text, Title } = Typography;
const { Panel } = Collapse;

// ─── Design Tokens（Admin 亮色主题） ───────────────────────────────────────────
const C = {
  primary: '#FF6B35',
  success: '#0F6E56',
  warning: '#BA7517',
  danger: '#A32D2D',
  info: '#185FA5',
  navy: '#1E2A3A',
  bg: '#F8F7F5',
  border: '#E8E6E1',
  textPrimary: '#2C2C2A',
  textSub: '#5F5E5A',
  textMuted: '#B4B2A9',
} as const;

// ─── 类型定义 ──────────────────────────────────────────────────────────────────

interface CockpitOverview {
  /** 今日营收（分） */
  today_revenue_fen: number;
  /** 昨日营收（分） */
  yesterday_revenue_fen: number;
  /** 今日订单数 */
  today_orders: number;
  /** 翻台次数 */
  table_turnover_count: number;
  /** 翻台利用率（0-1） */
  table_utilization_rate: number;
  /** 员工平均效率分 */
  avg_employee_efficiency: number;
  /** 出勤率（0-1） */
  attendance_rate: number;
  /** 今日客流量 */
  total_customers: number;
  /** 流失风险客户数 */
  churn_risk_count: number;
  /** 渠道毛利数据 */
  channel_margins: ChannelMargin[];
  /** 菜品毛利排行 */
  dish_profitability: DishProfitability[];
  /** 日结进度 */
  settlement_progress: SettlementProgress[];
  /** 数据生成时间 */
  generated_at: string;
}

interface ChannelMargin {
  channel: 'dine_in' | 'meituan' | 'eleme' | 'douyin';
  channel_label: string;
  gross_revenue_fen: number;
  net_revenue_fen: number;
  margin_rate: number; // 0-1
}

interface DishProfitability {
  dish_id: string;
  dish_name: string;
  category: string;
  order_count: number;
  margin_rate: number; // 0-1
  profitability_rank: number;
}

interface SettlementProgress {
  store_id: string;
  store_name: string;
  settlement_status: 'settled' | 'pending';
  completion_pct: number; // 0-100
}

interface CockpitAlert {
  id: string;
  level: 'error' | 'warning' | 'info';
  category: 'discount_anomaly' | 'food_safety' | 'settlement_incomplete' | 'customer_churn' | 'other';
  message: string;
  store_name: string;
  count: number;
  created_at: string;
}

// ─── 渠道中文映射 ──────────────────────────────────────────────────────────────
const CHANNEL_LABEL_MAP: Record<string, string> = {
  dine_in: '到店',
  meituan: '美团',
  eleme: '饿了么',
  douyin: '抖音',
};

const CHANNEL_ORDER = ['dine_in', 'meituan', 'eleme', 'douyin'];

// ─── 门店选项（演示用，实际由 API 提供或从 Store 读取） ───────────────────────
const STORE_OPTIONS = [
  { value: '', label: '全部门店' },
  { value: 'store_wenhucheng', label: '文化城店' },
  { value: 'store_luxiaoxian', label: '浏小鲜' },
  { value: 'store_yongan', label: '永安店' },
];

const REFRESH_OPTIONS = [
  { value: 5000, label: '5秒' },
  { value: 30000, label: '30秒' },
  { value: 0, label: '关闭' },
];

// ─── 工具函数 ──────────────────────────────────────────────────────────────────

/** 计算环比变化百分比 */
const calcChange = (today: number, yesterday: number): number => {
  if (yesterday === 0) return today > 0 ? 100 : 0;
  return ((today - yesterday) / yesterday) * 100;
};

/** 毛利率颜色 */
const marginColor = (rate: number): string => {
  if (rate >= 0.5) return C.success;
  if (rate >= 0.3) return C.warning;
  return C.danger;
};

/** 告警级别配置 */
const alertLevelConfig = (level: CockpitAlert['level']) => {
  switch (level) {
    case 'error': return { color: 'error' as const, icon: <CloseCircleFilled style={{ color: C.danger }} />, label: '严重' };
    case 'warning': return { color: 'warning' as const, icon: <WarningFilled style={{ color: C.warning }} />, label: '警告' };
    case 'info': return { color: 'processing' as const, icon: <InfoCircleFilled style={{ color: C.info }} />, label: '信息' };
  }
};

const alertCategoryLabel = (category: CockpitAlert['category']): string => {
  const map: Record<string, string> = {
    discount_anomaly: '折扣异常',
    food_safety: '食安违规',
    settlement_incomplete: '日结未完成',
    customer_churn: '客户流失',
    other: '其他',
  };
  return map[category] ?? category;
};

// ─── 主组件 ────────────────────────────────────────────────────────────────────

export function OpsCockpitPage() {
  // 状态
  const [overview, setOverview] = useState<CockpitOverview | null>(null);
  const [alerts, setAlerts] = useState<CockpitAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedStore, setSelectedStore] = useState('');
  const [refreshInterval, setRefreshInterval] = useState(30000);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [alertBannerOpen, setAlertBannerOpen] = useState(true);

  const refreshTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ─── 数据加载 ──────────────────────────────────────────────────────────────

  const loadOverview = useCallback(async () => {
    try {
      const params = selectedStore ? `?store_id=${selectedStore}` : '';
      const data = await apiGet<CockpitOverview>(`/api/v1/analytics/cockpit/overview${params}`);
      setOverview(data);
      setLastRefresh(new Date());
      setError(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '加载运营数据失败';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [selectedStore]);

  const loadAlerts = useCallback(async () => {
    try {
      const data = await apiGet<CockpitAlert[]>('/api/v1/analytics/cockpit/alerts');
      setAlerts(data);
    } catch {
      // 告警加载失败不影响主面板
    }
  }, []);

  // ─── 初始化加载 ────────────────────────────────────────────────────────────

  useEffect(() => {
    setLoading(true);
    loadOverview();
    loadAlerts();
  }, [loadOverview, loadAlerts]);

  // ─── 自动刷新 ──────────────────────────────────────────────────────────────

  useEffect(() => {
    if (refreshTimerRef.current) {
      clearInterval(refreshTimerRef.current);
      refreshTimerRef.current = null;
    }
    if (refreshInterval > 0) {
      refreshTimerRef.current = setInterval(() => {
        loadOverview();
        loadAlerts();
      }, refreshInterval);
    }
    return () => {
      if (refreshTimerRef.current) {
        clearInterval(refreshTimerRef.current);
      }
    };
  }, [refreshInterval, loadOverview, loadAlerts]);

  // ─── WebSocket 连接 ────────────────────────────────────────────────────────

  useEffect(() => {
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;

    const connect = () => {
      if (cancelled) return;
      try {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host;
        const wsUrl = `${protocol}//${host}/api/v1/analytics/cockpit/ws`;
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
          if (!cancelled) setWsConnected(true);
        };

        ws.onmessage = () => {
          // 收到推送后静默刷新数据
          loadOverview();
          loadAlerts();
        };

        ws.onclose = () => {
          if (!cancelled) {
            setWsConnected(false);
            // 5 秒后重连
            reconnectTimer = setTimeout(connect, 5000);
          }
        };

        ws.onerror = () => {
          ws?.close();
        };
      } catch {
        // WebSocket 不可用时静默降级
      }
    };

    connect();

    return () => {
      cancelled = true;
      ws?.close();
      if (reconnectTimer) clearTimeout(reconnectTimer);
    };
  }, [loadOverview, loadAlerts]);

  // ─── 按严重性排序告警 ──────────────────────────────────────────────────────
  const sortedAlerts = useMemo(() => {
    const order: Record<string, number> = { error: 0, warning: 1, info: 2 };
    return [...alerts].sort((a, b) => (order[a.level] ?? 3) - (order[b.level] ?? 3));
  }, [alerts]);

  const errorCount = alerts.filter((a) => a.level === 'error').length;
  const warningCount = alerts.filter((a) => a.level === 'warning').length;

  // ─── 衍生数据计算 ──────────────────────────────────────────────────────────

  const revenueChange = overview
    ? calcChange(overview.today_revenue_fen, overview.yesterday_revenue_fen)
    : 0;

  // ─── 渠道毛利图配置 ────────────────────────────────────────────────────────

  const channelChartOption = useMemo(() => {
    if (!overview?.channel_margins?.length) return null;

    const sortedChannels = CHANNEL_ORDER
      .map((ch) => overview.channel_margins.find((c) => c.channel === ch))
      .filter(Boolean) as ChannelMargin[];

    return {
      tooltip: {
        trigger: 'axis' as const,
        axisPointer: { type: 'shadow' as const },
        formatter: (params: Array<{ seriesName: string; value: number; color: string }>) => {
          let html = params[0]?.name ?? '';
          for (const p of params) {
            const formatted = p.seriesName.includes('率')
              ? `${(p.value * 100).toFixed(1)}%`
              : `${(p.value / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0 })}元`;
            html += `<br/><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${p.color};margin-right:6px;"></span>${p.seriesName}: ${formatted}`;
          }
          return html;
        },
      },
      legend: {
        data: ['毛收入', '净收入', '毛利率'],
        top: 0,
        textStyle: { fontSize: 12, color: C.textSub },
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '3%',
        top: 36,
        containLabel: true,
      },
      xAxis: {
        type: 'category',
        data: sortedChannels.map((c) => c.channel_label || CHANNEL_LABEL_MAP[c.channel] || c.channel),
        axisLabel: { fontSize: 12, color: C.textSub },
        axisLine: { lineStyle: { color: C.border } },
      },
      yAxis: [
        {
          type: 'value',
          name: '收入（元）',
          nameTextStyle: { fontSize: 11, color: C.textMuted },
          axisLabel: {
            fontSize: 11,
            color: C.textMuted,
            formatter: (v: number) => `¥${(v / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0 })}`,
          },
          splitLine: { lineStyle: { color: C.border, type: 'dashed' as const } },
        },
        {
          type: 'value',
          name: '毛利率',
          min: 0,
          max: 1,
          nameTextStyle: { fontSize: 11, color: C.textMuted },
          axisLabel: {
            fontSize: 11,
            color: C.textMuted,
            formatter: (v: number) => `${(v * 100).toFixed(0)}%`,
          },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: '毛收入',
          type: 'bar',
          data: sortedChannels.map((c) => c.gross_revenue_fen),
          itemStyle: {
            color: C.primary,
            borderRadius: [4, 4, 0, 0],
          },
          barMaxWidth: 32,
        },
        {
          name: '净收入',
          type: 'bar',
          data: sortedChannels.map((c) => c.net_revenue_fen),
          itemStyle: {
            color: C.navy,
            borderRadius: [4, 4, 0, 0],
          },
          barMaxWidth: 32,
        },
        {
          name: '毛利率',
          type: 'line',
          yAxisIndex: 1,
          data: sortedChannels.map((c) => c.margin_rate),
          lineStyle: { color: C.warning, width: 2 },
          itemStyle: { color: C.warning },
          symbol: 'circle',
          symbolSize: 8,
        },
      ],
    };
  }, [overview]);

  // ─── 菜品毛利表格列定义 ────────────────────────────────────────────────────

  const dishColumns: ColumnsType<DishProfitability> = [
    {
      title: '排名',
      dataIndex: 'profitability_rank',
      key: 'rank',
      width: 60,
      align: 'center',
      render: (rank: number) => (
        <span style={{
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          width: 24, height: 24, borderRadius: '50%',
          background: rank <= 3 ? C.primary : C.bg,
          color: rank <= 3 ? '#fff' : C.textSub,
          fontSize: 12, fontWeight: 700,
        }}>
          {rank}
        </span>
      ),
    },
    {
      title: '菜品名称',
      dataIndex: 'dish_name',
      key: 'name',
      ellipsis: true,
    },
    {
      title: '分类',
      dataIndex: 'category',
      key: 'category',
      width: 100,
      render: (cat: string) => <Tag>{cat}</Tag>,
    },
    {
      title: '订单数',
      dataIndex: 'order_count',
      key: 'orders',
      width: 90,
      align: 'right',
      render: (count: number) => count.toLocaleString('zh-CN'),
    },
    {
      title: '毛利率',
      dataIndex: 'margin_rate',
      key: 'margin',
      width: 100,
      align: 'right',
      sorter: (a, b) => a.margin_rate - b.margin_rate,
      render: (rate: number) => (
        <Tag color={marginColor(rate)} style={{ fontWeight: 600 }}>
          {(rate * 100).toFixed(1)}%
        </Tag>
      ),
    },
  ];

  // ─── 加载状态 ────────────────────────────────────────────────────────────────

  if (loading && !overview) {
    return (
      <div style={{ padding: 24 }}>
        <div style={{ marginBottom: 24 }}>
          <Spin size="large" />
          <Text style={{ marginLeft: 12, color: C.textSub }}>正在加载运营数据...</Text>
        </div>
        <Row gutter={16}>
          {[0, 1, 2, 3].map((i) => (
            <Col span={6} key={i}>
              <Card loading style={{ height: 140 }} />
            </Col>
          ))}
        </Row>
      </div>
    );
  }

  // ─── 错误状态 ────────────────────────────────────────────────────────────────

  if (error && !overview) {
    return (
      <Result
        status="error"
        title="数据加载失败"
        subTitle={error}
        extra={
          <Button type="primary" icon={<ReloadOutlined />} onClick={loadOverview}>
            重新加载
          </Button>
        }
      />
    );
  }

  // ─── 空状态保护 ──────────────────────────────────────────────────────────────

  const o = overview;
  if (!o) {
    return (
      <div style={{ padding: 24, textAlign: 'center' }}>
        <Empty description="暂无运营数据" />
      </div>
    );
  }

  // ─── 渲染 ────────────────────────────────────────────────────────────────────

  return (
    <div style={{ padding: '16px 24px', minWidth: 1280, background: '#fff', minHeight: '100vh' }}>
      {/* ── 顶栏 ──────────────────────────────────────────────────────────── */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: 16, flexWrap: 'wrap', gap: 12,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <div>
            <Title level={3} style={{ margin: 0, color: C.textPrimary, fontSize: 20 }}>
              实时运营驾驶舱
            </Title>
            {lastRefresh && (
              <Text style={{ fontSize: 12, color: C.textMuted }}>
                最后更新：{dayjs(lastRefresh).format('HH:mm:ss')}
              </Text>
            )}
          </div>
        </div>

        <Space size="middle" wrap>
          <Space size={4}>
            <Text style={{ fontSize: 12, color: C.textSub }}>门店：</Text>
            <Select
              value={selectedStore}
              onChange={setSelectedStore}
              options={STORE_OPTIONS}
              size="small"
              style={{ minWidth: 120 }}
              popupMatchSelectWidth={false}
            />
          </Space>

          <Space size={4}>
            <Text style={{ fontSize: 12, color: C.textSub }}>自动刷新：</Text>
            <Select
              value={refreshInterval}
              onChange={setRefreshInterval}
              options={REFRESH_OPTIONS}
              size="small"
              style={{ minWidth: 80 }}
            />
          </Space>

          <Tooltip title="手动刷新">
            <Button
              icon={<ReloadOutlined />}
              size="small"
              onClick={() => { loadOverview(); loadAlerts(); }}
              loading={loading}
            />
          </Tooltip>
        </Space>
      </div>

      {/* ── 预警横幅 ──────────────────────────────────────────────────────── */}
      {sortedAlerts.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <Collapse
            activeKey={alertBannerOpen ? ['alerts'] : []}
            onChange={(keys) => setAlertBannerOpen(keys.length > 0)}
            style={{ background: '#FFF7F0', border: `1px solid ${C.warning}` }}
            expandIconPosition="end"
          >
            <Panel
              key="alerts"
              header={
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <AlertOutlined style={{ color: C.danger, fontSize: 16 }} />
                  <Text strong style={{ color: C.textPrimary }}>
                    实时预警
                  </Text>
                  {errorCount > 0 && (
                    <Badge count={errorCount} size="small" style={{ backgroundColor: C.danger }}>
                      <Tag color="error" style={{ margin: 0 }}>严重</Tag>
                    </Badge>
                  )}
                  {warningCount > 0 && (
                    <Tag color="warning" style={{ margin: 0 }}>
                      {warningCount} 条警告
                    </Tag>
                  )}
                </div>
              }
              extra={null}
            >
              <div style={{ maxHeight: 200, overflowY: 'auto' }}>
                {sortedAlerts.map((alert) => {
                  const cfg = alertLevelConfig(alert.level);
                  return (
                    <div
                      key={alert.id}
                      style={{
                        display: 'flex', alignItems: 'flex-start', gap: 10,
                        padding: '8px 0',
                        borderBottom: `1px solid ${C.border}`,
                      }}
                    >
                      <span style={{ marginTop: 2, flexShrink: 0 }}>{cfg.icon}</span>
                      <div style={{ flex: 1 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
                          <Tag color={cfg.color} style={{ margin: 0, fontSize: 11 }}>{cfg.label}</Tag>
                          <Tag style={{ margin: 0, fontSize: 11 }}>{alertCategoryLabel(alert.category)}</Tag>
                          <Text style={{ fontSize: 11, color: C.textMuted }}>{alert.store_name}</Text>
                        </div>
                        <Text style={{ fontSize: 13, color: C.textPrimary }}>{alert.message}</Text>
                        {alert.count > 0 && (
                          <Text style={{ fontSize: 11, color: C.textMuted, marginLeft: 8 }}>
                            ({alert.count} 条)
                          </Text>
                        )}
                      </div>
                      <Text style={{ fontSize: 11, color: C.textMuted, flexShrink: 0 }}>
                        {dayjs(alert.created_at).format('HH:mm')}
                      </Text>
                    </div>
                  );
                })}
              </div>
            </Panel>
          </Collapse>
        </div>
      )}

      {/* ── KPI 卡片行 ────────────────────────────────────────────────────── */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        {/* 今日营收 */}
        <Col xs={24} sm={12} lg={6}>
          <StatisticCard
            statistic={{
              title: '今日营收',
              value: formatPrice(o.today_revenue_fen),
              valueStyle: { color: C.primary, fontSize: 26, fontWeight: 700 },
              prefix: <DollarOutlined style={{ fontSize: 18, color: C.primary }} />,
              description: (
                <Space size={4}>
                  {revenueChange >= 0
                    ? <CaretUpOutlined style={{ color: C.success }} />
                    : <CaretDownOutlined style={{ color: C.danger }} />
                  }
                  <span style={{
                    color: revenueChange >= 0 ? C.success : C.danger,
                    fontSize: 12, fontWeight: 600,
                  }}>
                    环比昨日 {revenueChange >= 0 ? '+' : ''}{revenueChange.toFixed(1)}%
                  </span>
                </Space>
              ),
            }}
            chart={null}
          />
        </Col>

        {/* 翻台率 */}
        <Col xs={24} sm={12} lg={6}>
          <StatisticCard
            statistic={{
              title: '翻台次数 / 利用率',
              value: o.table_turnover_count,
              suffix: '次',
              valueStyle: { color: C.navy, fontSize: 26, fontWeight: 700 },
              prefix: <ThunderboltOutlined style={{ fontSize: 18, color: C.info }} />,
              description: (
                <div style={{ marginTop: 4 }}>
                  <Progress
                    percent={Math.round(o.table_utilization_rate * 100)}
                    size="small"
                    strokeColor={o.table_utilization_rate >= 0.8 ? C.success : o.table_utilization_rate >= 0.5 ? C.warning : C.danger}
                    format={(pct) => `利用率 ${pct}%`}
                  />
                </div>
              ),
            }}
            chart={null}
          />
        </Col>

        {/* 员工效率 */}
        <Col xs={24} sm={12} lg={6}>
          <StatisticCard
            statistic={{
              title: '员工效率',
              value: o.avg_employee_efficiency,
              suffix: '分',
              precision: 1,
              valueStyle: {
                color: o.avg_employee_efficiency >= 80 ? C.success : o.avg_employee_efficiency >= 60 ? C.warning : C.danger,
                fontSize: 26,
                fontWeight: 700,
              },
              prefix: <TeamOutlined style={{ fontSize: 18, color: C.info }} />,
              description: (
                <Space size={4}>
                  <CheckCircleFilled style={{ color: o.attendance_rate >= 0.9 ? C.success : C.warning, fontSize: 12 }} />
                  <span style={{ fontSize: 12, color: C.textSub }}>
                    出勤率 {(o.attendance_rate * 100).toFixed(0)}%
                  </span>
                </Space>
              ),
            }}
            chart={null}
          />
        </Col>

        {/* 客户健康 */}
        <Col xs={24} sm={12} lg={6}>
          <StatisticCard
            statistic={{
              title: '客户健康',
              value: o.total_customers,
              suffix: '人次',
              valueStyle: { color: C.navy, fontSize: 26, fontWeight: 700 },
              prefix: <UserOutlined style={{ fontSize: 18, color: C.primary }} />,
              description: (
                <Space size={4}>
                  {o.churn_risk_count > 0
                    ? (
                      <>
                        <WarningFilled style={{ color: C.danger, fontSize: 12 }} />
                        <span style={{ fontSize: 12, color: C.danger, fontWeight: 600 }}>
                          {o.churn_risk_count} 人流失风险
                        </span>
                      </>
                    )
                    : (
                      <>
                        <CheckCircleFilled style={{ color: C.success, fontSize: 12 }} />
                        <span style={{ fontSize: 12, color: C.success }}>健康</span>
                      </>
                    )}
                </Space>
              ),
            }}
            chart={null}
          />
        </Col>
      </Row>

      {/* ── 中间区域：渠道毛利图 + 菜品毛利表 ───────────────────────────────── */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        {/* 渠道毛利图 */}
        <Col xs={24} lg={14}>
          <Card
            title={
              <Space>
                <HomeFilled style={{ color: C.primary }} />
                <span>渠道毛利对比</span>
              </Space>
            }
            extra={
              <Text style={{ fontSize: 11, color: C.textMuted }}>毛收入 / 净收入 / 毛利率</Text>
            }
            styles={{ body: { padding: '16px 16px 8px' } }}
          >
            {channelChartOption ? (
              <ReactEChartsCore
                echarts={echarts}
                option={channelChartOption}
                style={{ height: 320 }}
                notMerge
                lazyUpdate
              />
            ) : (
              <div style={{
                height: 320, display: 'flex', alignItems: 'center',
                justifyContent: 'center', color: C.textMuted, fontSize: 13,
              }}>
                暂无渠道毛利数据
              </div>
            )}
          </Card>
        </Col>

        {/* 菜品毛利表 */}
        <Col xs={24} lg={10}>
          <Card
            title={
              <Space>
                <ThunderboltOutlined style={{ color: C.primary }} />
                <span>菜品毛利率排行 TOP10</span>
              </Space>
            }
            extra={
              <Tooltip title="按毛利率从高到低排列">
                <Tag color="blue" style={{ fontSize: 11 }}>利润率排名</Tag>
              </Tooltip>
            }
            styles={{ body: { padding: 0 } }}
          >
            {o.dish_profitability?.length > 0 ? (
              <Table<DishProfitability>
                columns={dishColumns}
                dataSource={o.dish_profitability.slice(0, 10)}
                rowKey="dish_id"
                size="small"
                pagination={false}
                scroll={{ y: 320 }}
                style={{ minWidth: 400 }}
              />
            ) : (
              <div style={{
                height: 320, display: 'flex', alignItems: 'center',
                justifyContent: 'center', color: C.textMuted, fontSize: 13,
              }}>
                暂无菜品数据
              </div>
            )}
          </Card>
        </Col>
      </Row>

      {/* ── 日结进度 ──────────────────────────────────────────────────────── */}
      <Card
        title={
          <Space>
            <ClockCircleFilled style={{ color: C.primary }} />
            <span>门店日结进度</span>
          </Space>
        }
        extra={
          <Space size={4}>
            <span style={{
              display: 'inline-block', width: 10, height: 10,
              borderRadius: '50%', background: C.success, marginRight: 2,
            }} />
            <Text style={{ fontSize: 11, color: C.textMuted }}>已日结</Text>
            <span style={{
              display: 'inline-block', width: 10, height: 10,
              borderRadius: '50%', background: C.border, marginRight: 2, marginLeft: 8,
            }} />
            <Text style={{ fontSize: 11, color: C.textMuted }}>待日结</Text>
          </Space>
        }
        styles={{ body: { padding: '16px 20px' } }}
      >
        {o.settlement_progress?.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {o.settlement_progress.map((store) => (
              <div key={store.store_id} style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                <div style={{ width: 100, flexShrink: 0 }}>
                  <Text style={{ fontSize: 13, fontWeight: 500 }}>{store.store_name}</Text>
                </div>
                <div style={{ flex: 1 }}>
                  <Progress
                    percent={store.completion_pct}
                    strokeColor={
                      store.settlement_status === 'settled'
                        ? C.success
                        : store.completion_pct >= 80
                          ? C.warning
                          : C.danger
                    }
                    trailColor={C.border}
                    size="small"
                    format={(pct) => {
                      if (store.settlement_status === 'settled') {
                        return <CheckCircleFilled style={{ color: C.success }} />;
                      }
                      return `${pct}%`;
                    }}
                  />
                </div>
                <div style={{ width: 60, flexShrink: 0, textAlign: 'right' }}>
                  {store.settlement_status === 'settled' ? (
                    <Tag color="success" style={{ margin: 0 }}>已日结</Tag>
                  ) : (
                    <Tag color="default" style={{ margin: 0 }}>进行中</Tag>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <Empty description="暂无日结数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        )}
      </Card>

      {/* ── 底部状态栏 ────────────────────────────────────────────────────── */}
      <div style={{
        marginTop: 16, padding: '10px 16px',
        background: C.bg, borderRadius: 6,
        border: `1px solid ${C.border}`,
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        flexWrap: 'wrap', gap: 8,
      }}>
        <Space size="middle">
          {/* WebSocket 状态 */}
          <Space size={4}>
            <span style={{
              display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
              background: wsConnected ? C.success : C.textMuted,
              boxShadow: wsConnected ? `0 0 6px ${C.success}` : 'none',
              transition: 'all 0.3s ease',
            }} />
            <Text style={{ fontSize: 12, color: wsConnected ? C.success : C.textMuted }}>
              {wsConnected ? 'WebSocket 已连接' : 'WebSocket 未连接'}
            </Text>
          </Space>
        </Space>

        <Space size="middle">
          {lastRefresh && (
            <Text style={{ fontSize: 12, color: C.textMuted }}>
              <SyncOutlined spin={loading} style={{ marginRight: 4 }} />
              数据刷新于 {dayjs(lastRefresh).format('YYYY-MM-DD HH:mm:ss')}
            </Text>
          )}
          {o.generated_at && (
            <Text style={{ fontSize: 12, color: C.textMuted }}>
              数据截至 {dayjs(o.generated_at).format('HH:mm:ss')}
            </Text>
          )}
        </Space>
      </div>
    </div>
  );
}

export default OpsCockpitPage;
