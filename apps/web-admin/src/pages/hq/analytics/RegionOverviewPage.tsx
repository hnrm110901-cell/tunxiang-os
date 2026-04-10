/**
 * 区域经营总览 — 总部端
 * 功能: 按区域/品牌维度对比各区域经营表现，发现异常分布
 *
 * Sections:
 *   1. 维度切换Tabs (按区域/按品牌) + 时间选择器
 *   2. 关键指标对比矩阵（营收/客单价/翻台率/毛利率/人效/客诉率）
 *   3. 区域排名横向柱状图
 *   4. 异常分布统计（预警数量 + 整改完成率）
 *   5. 下钻：点击区域行展开门店列表
 *   6. 近4周趋势迷你折线图 Sparkline
 *
 * 调用 GET /api/v1/analytics/region-overview
 */
import { useState, useEffect, useCallback } from 'react';
import {
  fetchRegionOverview,
  fetchRegionStores,
  type RegionMetrics,
  type RegionOverviewData,
  type StoreMetrics,
} from '../../../api/regionOverviewApi';

// ─────────────────────────────────────────────
// 常量 & 工具函数
// ─────────────────────────────────────────────

const COLOR_PRIMARY = '#FF6B35';
const COLOR_SUCCESS = '#0F6E56';
const COLOR_WARNING = '#BA7517';
const COLOR_ERROR = '#A32D2D';
const COLOR_INFO = '#185FA5';

const BG_PAGE = '#0d1e28';
const BG_CARD = '#112228';
const BG_CELL = '#0B1A20';
const COLOR_TEXT = '#e0e8ef';
const COLOR_MUTED = '#6b8a9a';
const COLOR_BORDER = '#1a2a33';

const fmtYuan = (fen: number) =>
  `¥${(fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0 })}`;
const fmtPct = (rate: number) => `${(rate * 100).toFixed(1)}%`;

type Dimension = 'region' | 'brand';
type Period = 'today' | 'week' | 'month' | 'quarter';

const DIMENSION_LABELS: Record<Dimension, string> = {
  region: '按区域',
  brand: '按品牌',
};

const PERIOD_LABELS: Record<Period, string> = {
  today: '今日',
  week: '本周',
  month: '本月',
  quarter: '本季',
};

// ─────────────────────────────────────────────
// 子组件：环比箭头
// ─────────────────────────────────────────────

function ChangeArrow({ value }: { value: number }) {
  if (value > 0)
    return (
      <span style={{ color: COLOR_SUCCESS, fontSize: 11, marginLeft: 4 }}>
        ↑{fmtPct(value)}
      </span>
    );
  if (value < 0)
    return (
      <span style={{ color: COLOR_ERROR, fontSize: 11, marginLeft: 4 }}>
        ↓{fmtPct(Math.abs(value))}
      </span>
    );
  return (
    <span style={{ color: '#8c8c8c', fontSize: 11, marginLeft: 4 }}>—</span>
  );
}

// ─────────────────────────────────────────────
// 子组件：Sparkline 迷你折线图（纯 SVG）
// ─────────────────────────────────────────────

function Sparkline({
  data,
  width = 80,
  height = 24,
}: {
  data: number[];
  width?: number;
  height?: number;
}) {
  if (!data || data.length < 2) {
    return (
      <svg width={width} height={height}>
        <text
          x={width / 2}
          y={height / 2 + 4}
          textAnchor="middle"
          fill="#8c8c8c"
          fontSize={10}
        >
          —
        </text>
      </svg>
    );
  }

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const pad = 2;

  const points = data
    .map((v, i) => {
      const x = pad + (i / (data.length - 1)) * (width - pad * 2);
      const y = height - pad - ((v - min) / range) * (height - pad * 2);
      return `${x},${y}`;
    })
    .join(' ');

  const lastChange = data[data.length - 1] - data[data.length - 2];
  const lineColor = lastChange >= 0 ? COLOR_SUCCESS : COLOR_ERROR;

  // 最后一个点坐标
  const lastX =
    pad + ((data.length - 1) / (data.length - 1)) * (width - pad * 2);
  const lastY =
    height -
    pad -
    ((data[data.length - 1] - min) / range) * (height - pad * 2);

  return (
    <svg width={width} height={height}>
      <polyline
        points={points}
        fill="none"
        stroke={lineColor}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle cx={lastX} cy={lastY} r={2.5} fill={lineColor} />
    </svg>
  );
}

// ─────────────────────────────────────────────
// 子组件：异常高亮判定
// ─────────────────────────────────────────────

/** 判定某指标是否异常（用于单元格背景高亮） */
function isAnomaly(changeValue: number, isNegativeBetter = false): boolean {
  const threshold = 0.15; // 环比变化超过15%视为异常
  if (isNegativeBetter) {
    // 客诉率：上升为异常
    return changeValue > threshold;
  }
  // 营收/客单价/翻台率/毛利率/人效：下降为异常
  return changeValue < -threshold;
}

function cellBg(change: number, isNegativeBetter = false): string {
  return isAnomaly(change, isNegativeBetter) ? '#A32D2D20' : 'transparent';
}

// ─────────────────────────────────────────────
// 子组件：横向柱状图（营收排名）
// ─────────────────────────────────────────────

function RevenueBarChart({ items }: { items: RegionMetrics[] }) {
  const sorted = [...items].sort((a, b) => b.revenue_fen - a.revenue_fen);
  const maxVal = sorted[0]?.revenue_fen || 1;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {sorted.map((item, idx) => {
        const pct = (item.revenue_fen / maxVal) * 100;
        const barColor = idx < 3 ? COLOR_PRIMARY : COLOR_INFO;
        return (
          <div
            key={item.region_id}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
            }}
          >
            <span
              style={{
                width: 24,
                textAlign: 'center',
                fontSize: 14,
                fontWeight: 'bold',
                color: idx < 3 ? COLOR_PRIMARY : COLOR_MUTED,
              }}
            >
              {idx + 1}
            </span>
            <span
              style={{
                width: 80,
                fontSize: 13,
                color: COLOR_TEXT,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {item.region_name}
            </span>
            <div
              style={{
                flex: 1,
                height: 20,
                borderRadius: 4,
                background: BG_CELL,
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  width: `${pct}%`,
                  height: '100%',
                  borderRadius: 4,
                  background: barColor,
                  transition: 'width 0.6s ease',
                }}
              />
            </div>
            <span
              style={{
                width: 100,
                textAlign: 'right',
                fontSize: 13,
                fontWeight: 600,
                color: COLOR_TEXT,
              }}
            >
              {fmtYuan(item.revenue_fen)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ─────────────────────────────────────────────
// 子组件：门店下钻列表
// ─────────────────────────────────────────────

function StoreExpanded({
  regionId,
  regionName,
}: {
  regionId: string;
  regionName: string;
}) {
  const [stores, setStores] = useState<StoreMetrics[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchRegionStores(regionId)
      .then((data) => {
        if (!cancelled) setStores(data);
      })
      .catch(() => {
        if (!cancelled) setStores([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [regionId]);

  if (loading) {
    return (
      <tr>
        <td
          colSpan={9}
          style={{ padding: 16, textAlign: 'center', color: COLOR_MUTED }}
        >
          加载 {regionName} 门店数据...
        </td>
      </tr>
    );
  }

  if (stores.length === 0) {
    return (
      <tr>
        <td
          colSpan={9}
          style={{ padding: 16, textAlign: 'center', color: COLOR_MUTED }}
        >
          暂无门店数据
        </td>
      </tr>
    );
  }

  return (
    <>
      {stores.map((s) => (
        <tr
          key={s.store_id}
          style={{ background: '#0a1a22', borderBottom: `1px solid ${COLOR_BORDER}` }}
        >
          <td style={{ padding: '8px 12px', paddingLeft: 40, fontSize: 12, color: COLOR_MUTED }}>
            └ {s.store_name}
          </td>
          <td style={{ padding: '8px 12px', fontSize: 12, color: COLOR_TEXT }}>
            {fmtYuan(s.revenue_fen)}
            <ChangeArrow value={s.revenue_change} />
          </td>
          <td style={{ padding: '8px 12px', fontSize: 12, color: COLOR_TEXT }}>
            {fmtYuan(s.avg_ticket_fen)}
          </td>
          <td style={{ padding: '8px 12px', fontSize: 12, color: COLOR_TEXT }}>
            {s.table_turnover.toFixed(1)}
          </td>
          <td style={{ padding: '8px 12px', fontSize: 12, color: COLOR_TEXT }}>
            {fmtPct(s.gross_margin)}
          </td>
          <td style={{ padding: '8px 12px', fontSize: 12, color: COLOR_TEXT }}>
            {fmtYuan(s.labor_efficiency_fen)}
          </td>
          <td style={{ padding: '8px 12px', fontSize: 12, color: COLOR_TEXT }}>
            {fmtPct(s.complaint_rate)}
          </td>
          <td style={{ padding: '8px 12px', fontSize: 12, color: COLOR_TEXT }}>
            {s.alert_count > 0 ? (
              <span style={{ color: COLOR_WARNING }}>{s.alert_count}</span>
            ) : (
              <span style={{ color: COLOR_MUTED }}>0</span>
            )}
          </td>
          <td style={{ padding: '8px 12px' }}>—</td>
        </tr>
      ))}
    </>
  );
}

// ─────────────────────────────────────────────
// 主组件
// ─────────────────────────────────────────────

export function RegionOverviewPage() {
  const [dimension, setDimension] = useState<Dimension>('region');
  const [period, setPeriod] = useState<Period>('today');
  const [data, setData] = useState<RegionOverviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [expandedRegion, setExpandedRegion] = useState<string | null>(null);

  // 加载数据
  const loadData = useCallback(async () => {
    setLoading(true);
    setExpandedRegion(null);
    try {
      const result = await fetchRegionOverview({ dimension, period });
      setData(result);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [dimension, period]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const items = data?.items ?? [];

  // 统计汇总
  const totalAlerts = items.reduce((s, i) => s + i.alert_count, 0);
  const totalCritical = items.reduce((s, i) => s + i.alert_critical, 0);
  const avgRectification =
    items.length > 0
      ? items.reduce((s, i) => s + i.rectification_completion, 0) / items.length
      : 0;

  const dimensionLabel = dimension === 'region' ? '区域' : '品牌';

  return (
    <div style={{ minHeight: '100vh', background: BG_PAGE, color: COLOR_TEXT }}>
      {/* ── 顶栏：标题 + 维度切换 + 时间选择 ── */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 20,
          flexWrap: 'wrap',
          gap: 12,
        }}
      >
        <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>区域经营总览</h2>

        <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
          {/* 维度切换 */}
          <div
            style={{
              display: 'flex',
              background: BG_CARD,
              borderRadius: 8,
              padding: 2,
            }}
          >
            {(Object.entries(DIMENSION_LABELS) as [Dimension, string][]).map(
              ([key, label]) => (
                <button
                  key={key}
                  onClick={() => setDimension(key)}
                  style={{
                    padding: '6px 16px',
                    borderRadius: 6,
                    border: 'none',
                    cursor: 'pointer',
                    fontSize: 13,
                    fontWeight: 600,
                    background: dimension === key ? COLOR_PRIMARY : 'transparent',
                    color: dimension === key ? '#fff' : COLOR_MUTED,
                    transition: 'all 0.2s ease',
                  }}
                >
                  {label}
                </button>
              ),
            )}
          </div>

          {/* 时间选择 */}
          <div
            style={{
              display: 'flex',
              background: BG_CARD,
              borderRadius: 8,
              padding: 2,
            }}
          >
            {(Object.entries(PERIOD_LABELS) as [Period, string][]).map(
              ([key, label]) => (
                <button
                  key={key}
                  onClick={() => setPeriod(key)}
                  style={{
                    padding: '6px 14px',
                    borderRadius: 6,
                    border: 'none',
                    cursor: 'pointer',
                    fontSize: 12,
                    fontWeight: 600,
                    background: period === key ? COLOR_PRIMARY : 'transparent',
                    color: period === key ? '#fff' : COLOR_MUTED,
                    transition: 'all 0.2s ease',
                  }}
                >
                  {label}
                </button>
              ),
            )}
          </div>
        </div>
      </div>

      {/* ── 汇总统计条 ── */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: 12,
          marginBottom: 20,
        }}
      >
        {[
          {
            label: '总营收',
            value: fmtYuan(data?.total_revenue_fen ?? 0),
            color: COLOR_PRIMARY,
          },
          {
            label: '门店总数',
            value: `${data?.total_stores ?? 0} 家`,
            color: COLOR_INFO,
          },
          {
            label: '预警总数',
            value: `${totalAlerts} (危急 ${totalCritical})`,
            color: totalCritical > 0 ? COLOR_ERROR : COLOR_WARNING,
          },
          {
            label: '平均整改完成率',
            value: fmtPct(avgRectification),
            color: avgRectification >= 0.8 ? COLOR_SUCCESS : COLOR_WARNING,
          },
        ].map((stat) => (
          <div
            key={stat.label}
            style={{
              background: BG_CARD,
              borderRadius: 8,
              padding: 16,
              borderLeft: `4px solid ${stat.color}`,
            }}
          >
            <div style={{ fontSize: 12, color: COLOR_MUTED, marginBottom: 6 }}>
              {stat.label}
            </div>
            <div style={{ fontSize: 22, fontWeight: 700, color: stat.color }}>
              {stat.value}
            </div>
          </div>
        ))}
      </div>

      {/* ── 加载中 ── */}
      {loading ? (
        <div style={{ textAlign: 'center', color: COLOR_MUTED, padding: 60 }}>
          加载中...
        </div>
      ) : items.length === 0 ? (
        <div style={{ textAlign: 'center', color: COLOR_MUTED, padding: 60 }}>
          暂无数据
        </div>
      ) : (
        <>
          {/* ── 关键指标对比矩阵 ── */}
          <div
            style={{
              background: BG_CARD,
              borderRadius: 8,
              padding: 20,
              marginBottom: 20,
              overflowX: 'auto',
            }}
          >
            <h3 style={{ margin: '0 0 16px', fontSize: 16, fontWeight: 600 }}>
              关键指标对比矩阵
            </h3>
            <table
              style={{
                width: '100%',
                borderCollapse: 'collapse',
                fontSize: 13,
              }}
            >
              <thead>
                <tr
                  style={{
                    borderBottom: `2px solid ${COLOR_BORDER}`,
                  }}
                >
                  <th
                    style={{
                      textAlign: 'left',
                      padding: '10px 12px',
                      color: COLOR_MUTED,
                      fontWeight: 600,
                      fontSize: 12,
                    }}
                  >
                    {dimensionLabel}
                  </th>
                  <th style={thStyle}>营收</th>
                  <th style={thStyle}>客单价</th>
                  <th style={thStyle}>翻台率</th>
                  <th style={thStyle}>毛利率</th>
                  <th style={thStyle}>人效</th>
                  <th style={thStyle}>客诉率</th>
                  <th style={thStyle}>预警</th>
                  <th style={thStyle}>趋势</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const isExpanded = expandedRegion === item.region_id;
                  return (
                    <RegionRow
                      key={item.region_id}
                      item={item}
                      isExpanded={isExpanded}
                      onToggle={() =>
                        setExpandedRegion(isExpanded ? null : item.region_id)
                      }
                    />
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* ── 下方两栏：排名柱状图 + 异常分布 ── */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: 16,
            }}
          >
            {/* 营收排名柱状图 */}
            <div
              style={{
                background: BG_CARD,
                borderRadius: 8,
                padding: 20,
              }}
            >
              <h3 style={{ margin: '0 0 16px', fontSize: 16, fontWeight: 600 }}>
                {dimensionLabel}营收排名
              </h3>
              <RevenueBarChart items={items} />
            </div>

            {/* 异常分布统计 */}
            <div
              style={{
                background: BG_CARD,
                borderRadius: 8,
                padding: 20,
              }}
            >
              <h3 style={{ margin: '0 0 16px', fontSize: 16, fontWeight: 600 }}>
                异常分布统计
              </h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {[...items]
                  .sort((a, b) => b.alert_count - a.alert_count)
                  .map((item) => (
                    <div
                      key={item.region_id}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 12,
                        padding: '10px 12px',
                        background: BG_CELL,
                        borderRadius: 6,
                      }}
                    >
                      <span
                        style={{
                          flex: 1,
                          fontSize: 13,
                          fontWeight: 600,
                          color: COLOR_TEXT,
                        }}
                      >
                        {item.region_name}
                      </span>

                      {/* 预警标签 */}
                      <div style={{ display: 'flex', gap: 6 }}>
                        {item.alert_critical > 0 && (
                          <span
                            style={{
                              padding: '2px 8px',
                              borderRadius: 4,
                              fontSize: 11,
                              fontWeight: 600,
                              background: `${COLOR_ERROR}25`,
                              color: COLOR_ERROR,
                            }}
                          >
                            危急 {item.alert_critical}
                          </span>
                        )}
                        {item.alert_count - item.alert_critical > 0 && (
                          <span
                            style={{
                              padding: '2px 8px',
                              borderRadius: 4,
                              fontSize: 11,
                              fontWeight: 600,
                              background: `${COLOR_WARNING}25`,
                              color: COLOR_WARNING,
                            }}
                          >
                            预警 {item.alert_count - item.alert_critical}
                          </span>
                        )}
                        {item.alert_count === 0 && (
                          <span
                            style={{
                              padding: '2px 8px',
                              borderRadius: 4,
                              fontSize: 11,
                              fontWeight: 600,
                              background: `${COLOR_SUCCESS}25`,
                              color: COLOR_SUCCESS,
                            }}
                          >
                            正常
                          </span>
                        )}
                      </div>

                      {/* 整改完成率 */}
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 6,
                          width: 140,
                        }}
                      >
                        <div
                          style={{
                            flex: 1,
                            height: 6,
                            borderRadius: 3,
                            background: COLOR_BORDER,
                            overflow: 'hidden',
                          }}
                        >
                          <div
                            style={{
                              width: `${Math.min(item.rectification_completion * 100, 100)}%`,
                              height: '100%',
                              borderRadius: 3,
                              background:
                                item.rectification_completion >= 0.8
                                  ? COLOR_SUCCESS
                                  : item.rectification_completion >= 0.5
                                    ? COLOR_WARNING
                                    : COLOR_ERROR,
                              transition: 'width 0.4s ease',
                            }}
                          />
                        </div>
                        <span
                          style={{
                            fontSize: 11,
                            fontWeight: 600,
                            color: COLOR_MUTED,
                            width: 40,
                            textAlign: 'right',
                          }}
                        >
                          {fmtPct(item.rectification_completion)}
                        </span>
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────
// 子组件：表格行（含下钻展开）
// ─────────────────────────────────────────────

function RegionRow({
  item,
  isExpanded,
  onToggle,
}: {
  item: RegionMetrics;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      <tr
        onClick={onToggle}
        style={{
          borderBottom: `1px solid ${COLOR_BORDER}`,
          cursor: 'pointer',
          transition: 'background 0.15s ease',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = '#1a2a3380';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = 'transparent';
        }}
      >
        {/* 区域名称 */}
        <td style={{ padding: '12px 12px', fontWeight: 600 }}>
          <span style={{ marginRight: 6, fontSize: 10, color: COLOR_MUTED }}>
            {isExpanded ? '▼' : '▶'}
          </span>
          {item.region_name}
          <span
            style={{
              fontSize: 11,
              color: COLOR_MUTED,
              marginLeft: 6,
            }}
          >
            ({item.store_count}店)
          </span>
        </td>

        {/* 营收 */}
        <td
          style={{
            ...tdStyle,
            background: cellBg(item.revenue_change),
          }}
        >
          {fmtYuan(item.revenue_fen)}
          <ChangeArrow value={item.revenue_change} />
        </td>

        {/* 客单价 */}
        <td
          style={{
            ...tdStyle,
            background: cellBg(item.avg_ticket_change),
          }}
        >
          {fmtYuan(item.avg_ticket_fen)}
          <ChangeArrow value={item.avg_ticket_change} />
        </td>

        {/* 翻台率 */}
        <td
          style={{
            ...tdStyle,
            background: cellBg(item.table_turnover_change),
          }}
        >
          {item.table_turnover.toFixed(1)}
          <ChangeArrow value={item.table_turnover_change} />
        </td>

        {/* 毛利率 */}
        <td
          style={{
            ...tdStyle,
            background: cellBg(item.gross_margin_change),
          }}
        >
          {fmtPct(item.gross_margin)}
          <ChangeArrow value={item.gross_margin_change} />
        </td>

        {/* 人效 */}
        <td
          style={{
            ...tdStyle,
            background: cellBg(item.labor_efficiency_change),
          }}
        >
          {fmtYuan(item.labor_efficiency_fen)}
          <ChangeArrow value={item.labor_efficiency_change} />
        </td>

        {/* 客诉率 */}
        <td
          style={{
            ...tdStyle,
            background: cellBg(item.complaint_rate_change, true),
          }}
        >
          {fmtPct(item.complaint_rate)}
          <ChangeArrow value={-item.complaint_rate_change} />
        </td>

        {/* 预警 */}
        <td style={tdStyle}>
          {item.alert_critical > 0 && (
            <span
              style={{
                display: 'inline-block',
                padding: '1px 6px',
                borderRadius: 4,
                fontSize: 11,
                fontWeight: 600,
                background: `${COLOR_ERROR}25`,
                color: COLOR_ERROR,
                marginRight: 4,
              }}
            >
              {item.alert_critical}
            </span>
          )}
          {item.alert_count - item.alert_critical > 0 && (
            <span
              style={{
                display: 'inline-block',
                padding: '1px 6px',
                borderRadius: 4,
                fontSize: 11,
                fontWeight: 600,
                background: `${COLOR_WARNING}25`,
                color: COLOR_WARNING,
              }}
            >
              {item.alert_count - item.alert_critical}
            </span>
          )}
          {item.alert_count === 0 && (
            <span style={{ color: COLOR_MUTED, fontSize: 12 }}>0</span>
          )}
        </td>

        {/* Sparkline 趋势 */}
        <td style={tdStyle}>
          <Sparkline data={item.weekly_trend} />
        </td>
      </tr>

      {/* 展开的门店下钻列表 */}
      {isExpanded && (
        <StoreExpanded
          regionId={item.region_id}
          regionName={item.region_name}
        />
      )}
    </>
  );
}

// ─────────────────────────────────────────────
// 通用表格样式
// ─────────────────────────────────────────────

const thStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '10px 12px',
  color: '#6b8a9a',
  fontWeight: 600,
  fontSize: 12,
  whiteSpace: 'nowrap',
};

const tdStyle: React.CSSProperties = {
  padding: '12px 12px',
  fontSize: 13,
  whiteSpace: 'nowrap',
  borderRadius: 4,
};
