/**
 * TradePage — 交易总览
 * 今日KPI / 实时订单列表 / 支付渠道分布 / 小时营收热力图
 */

import React, { useEffect, useState, useCallback } from 'react';
import { txFetchData } from '../api';

// ─── 类型定义 ───

interface DailyProfitKPI {
  date: string;
  revenue_fen: number;
  order_count: number;
  avg_order_fen: number;
  refund_fen: number;
}

interface OrderItem {
  order_id: string;
  order_no: string;
  table_no: string;
  status: string;
  total_fen: number;
  created_at: string;
}

interface PaymentMethod {
  method: string;
  method_label: string;
  count: number;
  amount_fen: number;
  percentage: number;
}

interface HourlyRevenue {
  hour: number;
  revenue_fen: number;
}

// ─── 样式常量 ───

const containerStyle: React.CSSProperties = {
  backgroundColor: '#0d1e28',
  color: '#E0E0E0',
  minHeight: '100vh',
  padding: '24px 32px',
  fontFamily: 'system-ui, -apple-system, sans-serif',
};

const headerStyle: React.CSSProperties = {
  fontSize: '24px',
  fontWeight: 700,
  color: '#FFFFFF',
  marginBottom: '4px',
};

const subtitleStyle: React.CSSProperties = {
  fontSize: '13px',
  color: '#8899A6',
  marginBottom: '24px',
};

const kpiGridStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(4, 1fr)',
  gap: '16px',
  marginBottom: '24px',
};

const kpiCardStyle: React.CSSProperties = {
  backgroundColor: '#1a2a33',
  borderRadius: '12px',
  padding: '20px',
  border: '1px solid #1E3A47',
};

const contentGridStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '1fr 1fr',
  gap: '20px',
  marginBottom: '20px',
};

const cardStyle: React.CSSProperties = {
  backgroundColor: '#1a2a33',
  borderRadius: '12px',
  padding: '20px',
  border: '1px solid #1E3A47',
};

const cardTitleStyle: React.CSSProperties = {
  fontSize: '15px',
  fontWeight: 600,
  color: '#4FC3F7',
  marginBottom: '14px',
  display: 'flex',
  alignItems: 'center',
  gap: '8px',
};

const listRowStyle: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  padding: '9px 0',
  borderBottom: '1px solid #1E3A47',
  fontSize: '13px',
};

const loadingStyle: React.CSSProperties = {
  color: '#8899A6',
  fontSize: '13px',
  padding: '20px 0',
  textAlign: 'center',
};

const errorStyle: React.CSSProperties = {
  color: '#EF5350',
  fontSize: '13px',
  padding: '12px',
  backgroundColor: 'rgba(239,83,80,0.08)',
  borderRadius: '8px',
  marginBottom: '16px',
};

// ─── 工具函数 ───

function fenToYuan(fen: number): string {
  return '¥' + (fen / 100).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

function statusColor(status: string): string {
  switch (status) {
    case 'completed': return '#66BB6A';
    case 'serving': return '#FFA726';
    case 'pending': return '#4FC3F7';
    case 'refunded': return '#EF5350';
    default: return '#8899A6';
  }
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    completed: '已完成',
    serving: '出餐中',
    pending: '待支付',
    refunded: '已退款',
    cancelled: '已取消',
  };
  return map[status] ?? status;
}

function methodLabel(method: string): string {
  const map: Record<string, string> = {
    wechat: '微信支付',
    alipay: '支付宝',
    cash: '现金',
    unionpay: '银联',
    other: '其他',
  };
  return map[method] ?? method;
}

// ─── 小时热力图组件（纯SVG） ───

function HourlyHeatmap({ data }: { data: HourlyRevenue[] }) {
  if (data.length === 0) {
    return <div style={loadingStyle}>暂无数据</div>;
  }

  const maxRev = Math.max(...data.map((d) => d.revenue_fen), 1);
  const cellW = 28;
  const cellH = 36;
  const cols = 12; // 两行：0-11 / 12-23
  const rows = 2;
  const padL = 36;
  const padT = 20;
  const svgW = padL + cols * (cellW + 2) + 8;
  const svgH = padT + rows * (cellH + 4) + 24;

  const cells = Array.from({ length: 24 }, (_, h) => {
    const entry = data.find((d) => d.hour === h);
    const rev = entry?.revenue_fen ?? 0;
    const intensity = rev / maxRev;
    const row = Math.floor(h / 12);
    const col = h % 12;
    const x = padL + col * (cellW + 2);
    const y = padT + row * (cellH + 4);
    const alpha = 0.12 + intensity * 0.85;
    const fill = rev === 0
      ? '#1E3A47'
      : `rgba(79,195,247,${alpha.toFixed(2)})`;
    return { h, x, y, fill, rev };
  });

  return (
    <svg width={svgW} height={svgH} style={{ display: 'block', margin: '0 auto' }}>
      {/* Y轴标签 */}
      <text x={0} y={padT + cellH / 2 + 4} fill="#8899A6" fontSize={11}>AM</text>
      <text x={0} y={padT + (cellH + 4) + cellH / 2 + 4} fill="#8899A6" fontSize={11}>PM</text>

      {/* 单元格 */}
      {cells.map(({ h, x, y, fill, rev }) => (
        <g key={h}>
          <rect
            x={x}
            y={y}
            width={cellW}
            height={cellH}
            rx={4}
            fill={fill}
            stroke="#1E3A47"
            strokeWidth={0.5}
          />
          <text
            x={x + cellW / 2}
            y={y + 14}
            textAnchor="middle"
            fill="#B0BEC5"
            fontSize={10}
          >
            {h}h
          </text>
          {rev > 0 && (
            <text
              x={x + cellW / 2}
              y={y + 27}
              textAnchor="middle"
              fill="#E0E0E0"
              fontSize={9}
            >
              {(rev / 100 / 1000).toFixed(1)}k
            </text>
          )}
        </g>
      ))}

      {/* 图例 */}
      <text x={padL} y={svgH - 4} fill="#8899A6" fontSize={10}>低</text>
      {[0.1, 0.3, 0.5, 0.7, 0.9].map((v, i) => (
        <rect
          key={i}
          x={padL + 18 + i * 14}
          y={svgH - 14}
          width={12}
          height={8}
          rx={2}
          fill={`rgba(79,195,247,${(0.12 + v * 0.85).toFixed(2)})`}
        />
      ))}
      <text x={padL + 18 + 5 * 14 + 4} y={svgH - 4} fill="#8899A6" fontSize={10}>高</text>
    </svg>
  );
}

// ─── 主组件 ───

export function TradePage() {
  const [kpi, setKpi] = useState<DailyProfitKPI | null>(null);
  const [kpiLoading, setKpiLoading] = useState(true);
  const [kpiError, setKpiError] = useState<string | null>(null);

  const [orders, setOrders] = useState<OrderItem[]>([]);
  const [ordersLoading, setOrdersLoading] = useState(true);
  const [ordersError, setOrdersError] = useState<string | null>(null);

  const [payMethods, setPayMethods] = useState<PaymentMethod[]>([]);
  const [payLoading, setPayLoading] = useState(true);
  const [payError, setPayError] = useState<string | null>(null);

  const [hourly, setHourly] = useState<HourlyRevenue[]>([]);
  const [hourlyLoading, setHourlyLoading] = useState(true);

  const loadAll = useCallback(async () => {
    // 今日KPI
    setKpiLoading(true);
    setKpiError(null);
    try {
      const data = await txFetchData<DailyProfitKPI>('/api/v1/finance/daily-profit');
      setKpi(data);
    } catch (e) {
      setKpiError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setKpiLoading(false);
    }

    // 实时订单列表
    setOrdersLoading(true);
    setOrdersError(null);
    try {
      const data = await txFetchData<{ items: OrderItem[]; total: number }>(
        '/api/v1/trade/orders?page=1&size=10',
      );
      setOrders(data.items ?? []);
    } catch (e) {
      setOrdersError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setOrdersLoading(false);
    }

    // 支付渠道分布
    setPayLoading(true);
    setPayError(null);
    try {
      const data = await txFetchData<{ items: PaymentMethod[] }>(
        '/api/v1/finance/analytics/payment-methods?period=day',
      );
      setPayMethods(data.items ?? []);
    } catch (e) {
      setPayError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setPayLoading(false);
    }

    // 小时营收热力图
    setHourlyLoading(true);
    try {
      const data = await txFetchData<{ items: HourlyRevenue[] }>(
        '/api/v1/finance/analytics/hourly-revenue?period=day',
      );
      setHourly(data.items ?? []);
    } catch {
      setHourly([]);
    } finally {
      setHourlyLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const kpiItems = kpi
    ? [
        { label: '今日总收入', value: fenToYuan(kpi.revenue_fen), color: '#66BB6A' },
        { label: '订单数', value: `${kpi.order_count} 单`, color: '#4FC3F7' },
        { label: '客单价', value: fenToYuan(kpi.avg_order_fen), color: '#FFA726' },
        { label: '退款额', value: fenToYuan(kpi.refund_fen), color: '#EF5350' },
      ]
    : [];

  return (
    <div style={containerStyle}>
      {/* 页头 */}
      <h1 style={headerStyle}>交易总览</h1>
      <p style={subtitleStyle}>
        今日 {new Date().toLocaleDateString('zh-CN')} · 实时数据
      </p>

      {/* 今日KPI */}
      {kpiError && <div style={errorStyle}>KPI 加载失败：{kpiError}</div>}
      <div style={kpiGridStyle}>
        {kpiLoading
          ? Array.from({ length: 4 }).map((_, i) => (
              <div key={i} style={kpiCardStyle}>
                <div style={{ ...loadingStyle, padding: '8px 0' }}>加载中...</div>
              </div>
            ))
          : kpiItems.map((item) => (
              <div key={item.label} style={kpiCardStyle}>
                <div style={{ fontSize: '12px', color: '#8899A6', marginBottom: '8px' }}>
                  {item.label}
                </div>
                <div style={{ fontSize: '22px', fontWeight: 700, color: item.color }}>
                  {item.value}
                </div>
              </div>
            ))}
      </div>

      {/* 订单列表 + 支付渠道 */}
      <div style={contentGridStyle}>
        {/* 实时订单 */}
        <div style={cardStyle}>
          <div style={cardTitleStyle}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: '#66BB6A', display: 'inline-block' }} />
            实时订单（最新10笔）
          </div>
          {ordersError && <div style={errorStyle}>{ordersError}</div>}
          {ordersLoading ? (
            <div style={loadingStyle}>加载中...</div>
          ) : orders.length === 0 ? (
            <div style={loadingStyle}>暂无订单</div>
          ) : (
            orders.map((o) => (
              <div key={o.order_id} style={listRowStyle}>
                <span style={{ color: '#8899A6', fontSize: '12px', width: '140px', flexShrink: 0 }}>
                  {o.order_no}
                </span>
                <span style={{ flex: 1, paddingLeft: '8px' }}>
                  {o.table_no ? `桌 ${o.table_no}` : '—'}
                </span>
                <span style={{ color: '#4FC3F7', fontWeight: 600, marginRight: '12px' }}>
                  {fenToYuan(o.total_fen)}
                </span>
                <span
                  style={{
                    color: statusColor(o.status),
                    fontSize: '12px',
                    backgroundColor: `${statusColor(o.status)}18`,
                    padding: '2px 8px',
                    borderRadius: '4px',
                  }}
                >
                  {statusLabel(o.status)}
                </span>
              </div>
            ))
          )}
        </div>

        {/* 支付渠道分布 */}
        <div style={cardStyle}>
          <div style={cardTitleStyle}>
            <span>支付渠道分布（今日）</span>
          </div>
          {payError && <div style={errorStyle}>{payError}</div>}
          {payLoading ? (
            <div style={loadingStyle}>加载中...</div>
          ) : payMethods.length === 0 ? (
            <div style={loadingStyle}>暂无数据</div>
          ) : (
            payMethods.map((p) => (
              <div key={p.method} style={{ marginBottom: '14px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '5px', fontSize: '13px' }}>
                  <span>{p.method_label || methodLabel(p.method)}</span>
                  <span style={{ color: '#8899A6' }}>
                    {p.count} 笔 · {fenToYuan(p.amount_fen)}
                  </span>
                  <span style={{ color: '#4FC3F7', fontWeight: 600 }}>
                    {p.percentage?.toFixed(1) ?? 0}%
                  </span>
                </div>
                <div style={{ width: '100%', height: '6px', backgroundColor: '#1E3A47', borderRadius: '3px' }}>
                  <div
                    style={{
                      width: `${Math.min(p.percentage ?? 0, 100)}%`,
                      height: '100%',
                      backgroundColor: '#4FC3F7',
                      borderRadius: '3px',
                      transition: 'width 0.6s ease',
                    }}
                  />
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* 小时营收热力图 */}
      <div style={cardStyle}>
        <div style={cardTitleStyle}>小时营收热力图（今日 0-23时）</div>
        {hourlyLoading ? (
          <div style={loadingStyle}>加载中...</div>
        ) : (
          <HourlyHeatmap data={hourly} />
        )}
      </div>

      {/* 刷新按钮 */}
      <div style={{ textAlign: 'right', marginTop: '16px' }}>
        <button
          onClick={loadAll}
          style={{
            backgroundColor: '#1E3A47',
            border: '1px solid #2a4a5a',
            color: '#4FC3F7',
            padding: '8px 20px',
            borderRadius: '8px',
            cursor: 'pointer',
            fontSize: '13px',
          }}
        >
          刷新数据
        </button>
      </div>
    </div>
  );
}
