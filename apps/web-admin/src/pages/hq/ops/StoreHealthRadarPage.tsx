/**
 * 门店健康度雷达页 -- 总部端 P0
 *
 * 功能:
 *  1. 顶部汇总: 红/黄/绿门店数 + 总门店 + 整体健康度
 *  2. 视图切换: 卡片模式 / 区域分布图
 *  3. 门店卡片网格: 健康评分 + 评级 + 六维迷你雷达 + 异常标签
 *  4. Drawer 详情: 六维雷达 + 行业基准对比 + 趋势折线
 *  5. 风险门店排行: Top10
 *  6. 一键整改: 红色门店创建整改任务
 *  7. 筛选: 区域/品牌/健康等级
 *
 * 调用 GET /api/v1/store-health/radar/*
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  fetchHealthRadarSummary,
  fetchHealthRadarList,
  fetchStoreRadarDetail,
  createRectifyTask,
  type StoreHealthRadar,
  type HealthSummary,
  type StoreHealthRadarDetail,
} from '../../../api/storeHealthRadarApi';

// ─── 颜色常量 ──────────────────────────────────────────────────────────────────

const GRADE_COLOR: Record<string, string> = {
  A: '#0F6E56',  // ≥80
  B: '#185FA5',  // ≥60
  C: '#BA7517',  // ≥40
  D: '#A32D2D',  // <40
};

const LEVEL_CONFIG = {
  green:  { label: '达标',   color: '#0F6E56', bg: '#0F6E5615' },
  yellow: { label: '预警',   color: '#BA7517', bg: '#BA751715' },
  red:    { label: '不达标', color: '#A32D2D', bg: '#A32D2D15' },
} as const;

type ScoreLevel = keyof typeof LEVEL_CONFIG;

const DIMENSION_META: Record<string, { label: string; unit: string; inverse?: boolean }> = {
  revenue_rate:     { label: '营收达成率', unit: '%' },
  gross_margin:     { label: '毛利率',     unit: '%' },
  table_turnover:   { label: '翻台率',     unit: '次' },
  complaint_rate:   { label: '客诉率',     unit: '%', inverse: true },
  quality_rate:     { label: '出品合格率', unit: '%' },
  labor_efficiency: { label: '人效',       unit: '元/人/天' },
};

const DIMENSION_KEYS = Object.keys(DIMENSION_META);

// ─── 工具函数 ──────────────────────────────────────────────────────────────────

function fmtPct(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

function getGradeFromScore(score: number): 'A' | 'B' | 'C' | 'D' {
  if (score >= 80) return 'A';
  if (score >= 60) return 'B';
  if (score >= 40) return 'C';
  return 'D';
}

/** 将维度值归一化到 0-1 用于雷达图绘制 */
function normalizeDimValue(key: string, value: number): number {
  switch (key) {
    case 'revenue_rate':
    case 'gross_margin':
    case 'quality_rate':
      return Math.min(1, Math.max(0, value));
    case 'complaint_rate':
      // 越低越好，反转：0.05 → 0.95, 0 → 1
      return Math.min(1, Math.max(0, 1 - value * 10));
    case 'table_turnover':
      // 假设满分 5 次
      return Math.min(1, Math.max(0, value / 5));
    case 'labor_efficiency':
      // 假设满分 1000 元/人/天
      return Math.min(1, Math.max(0, value / 1000));
    default:
      return Math.min(1, Math.max(0, value));
  }
}

function formatDimValue(key: string, value: number): string {
  switch (key) {
    case 'revenue_rate':
    case 'gross_margin':
    case 'quality_rate':
    case 'complaint_rate':
      return fmtPct(value);
    case 'table_turnover':
      return `${value.toFixed(1)}次`;
    case 'labor_efficiency':
      return `${Math.round(value)}元`;
    default:
      return String(value);
  }
}

// ─── SVG 雷达图组件 ─────────────────────────────────────────────────────────────

function RadarChart({
  dimensions,
  size = 120,
  color = '#FF6B35',
  showLabels = false,
}: {
  dimensions: Record<string, number>;
  size?: number;
  color?: string;
  showLabels?: boolean;
}) {
  const cx = size / 2;
  const cy = size / 2;
  const radius = (size / 2) * 0.78;
  const labelRadius = (size / 2) * 0.96;
  const n = DIMENSION_KEYS.length;
  const angleStep = (2 * Math.PI) / n;
  const startAngle = -Math.PI / 2; // 从顶部开始

  // 顶点坐标
  const getPoint = (i: number, r: number) => {
    const angle = startAngle + i * angleStep;
    return { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
  };

  // 网格层数
  const gridLevels = [0.2, 0.4, 0.6, 0.8, 1.0];

  // 数据多边形顶点
  const dataPoints = DIMENSION_KEYS.map((key, i) => {
    const norm = normalizeDimValue(key, dimensions[key] ?? 0);
    return getPoint(i, norm * radius);
  });
  const dataPath = dataPoints.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ') + ' Z';

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      {/* 背景网格 */}
      {gridLevels.map((level) => {
        const pts = Array.from({ length: n }, (_, i) => getPoint(i, level * radius));
        const path = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ') + ' Z';
        return <path key={level} d={path} fill="none" stroke="#1a2a33" strokeWidth={0.8} />;
      })}

      {/* 轴线 */}
      {Array.from({ length: n }, (_, i) => {
        const p = getPoint(i, radius);
        return <line key={i} x1={cx} y1={cy} x2={p.x} y2={p.y} stroke="#1a2a33" strokeWidth={0.6} />;
      })}

      {/* 数据区域 */}
      <path d={dataPath} fill={`${color}30`} stroke={color} strokeWidth={1.5} />

      {/* 数据点 */}
      {dataPoints.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r={2} fill={color} />
      ))}

      {/* 维度标签 */}
      {showLabels && DIMENSION_KEYS.map((key, i) => {
        const p = getPoint(i, labelRadius);
        const meta = DIMENSION_META[key];
        return (
          <text
            key={key}
            x={p.x}
            y={p.y}
            textAnchor="middle"
            dominantBaseline="central"
            fill="#999"
            fontSize={size > 200 ? 11 : 9}
          >
            {meta.label}
          </text>
        );
      })}
    </svg>
  );
}

// ─── 详情雷达图（大号 + 基准对比） ──────────────────────────────────────────────

function RadarChartLarge({
  dimensions,
  benchmarks,
  size = 280,
}: {
  dimensions: Record<string, number>;
  benchmarks?: Record<string, number>;
  size?: number;
}) {
  const cx = size / 2;
  const cy = size / 2;
  const radius = (size / 2) * 0.65;
  const labelRadius = (size / 2) * 0.88;
  const n = DIMENSION_KEYS.length;
  const angleStep = (2 * Math.PI) / n;
  const startAngle = -Math.PI / 2;

  const getPoint = (i: number, r: number) => {
    const angle = startAngle + i * angleStep;
    return { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
  };

  const gridLevels = [0.2, 0.4, 0.6, 0.8, 1.0];

  const buildPath = (values: Record<string, number>) => {
    const pts = DIMENSION_KEYS.map((key, i) => {
      const norm = normalizeDimValue(key, values[key] ?? 0);
      return getPoint(i, norm * radius);
    });
    return pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ') + ' Z';
  };

  const dataPath = buildPath(dimensions);
  const benchPath = benchmarks ? buildPath(benchmarks) : null;

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      {gridLevels.map((level) => {
        const pts = Array.from({ length: n }, (_, i) => getPoint(i, level * radius));
        const path = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ') + ' Z';
        return <path key={level} d={path} fill="none" stroke="#1a2a33" strokeWidth={1} />;
      })}
      {Array.from({ length: n }, (_, i) => {
        const p = getPoint(i, radius);
        return <line key={i} x1={cx} y1={cy} x2={p.x} y2={p.y} stroke="#1a2a33" strokeWidth={0.8} />;
      })}

      {/* 行业基准 */}
      {benchPath && (
        <path d={benchPath} fill="rgba(24,95,165,0.1)" stroke="#185FA5" strokeWidth={1.2} strokeDasharray="4 3" />
      )}

      {/* 门店数据 */}
      <path d={dataPath} fill="rgba(255,107,53,0.2)" stroke="#FF6B35" strokeWidth={2} />
      {DIMENSION_KEYS.map((key, i) => {
        const norm = normalizeDimValue(key, dimensions[key] ?? 0);
        const p = getPoint(i, norm * radius);
        return <circle key={`d-${i}`} cx={p.x} cy={p.y} r={3.5} fill="#FF6B35" />;
      })}

      {/* 标签 */}
      {DIMENSION_KEYS.map((key, i) => {
        const p = getPoint(i, labelRadius);
        const meta = DIMENSION_META[key];
        return (
          <text
            key={key}
            x={p.x}
            y={p.y}
            textAnchor="middle"
            dominantBaseline="central"
            fill="#ccc"
            fontSize={12}
            fontWeight={500}
          >
            {meta.label}
          </text>
        );
      })}
    </svg>
  );
}

// ─── 趋势迷你折线 ───────────────────────────────────────────────────────────────

function MiniTrendLine({
  data,
  width = 200,
  height = 40,
  color = '#FF6B35',
}: {
  data: { date: string; value: number }[];
  width?: number;
  height?: number;
  color?: string;
}) {
  if (data.length < 2) return <div style={{ width, height, color: '#555', fontSize: 12, display: 'flex', alignItems: 'center' }}>暂无趋势数据</div>;

  const values = data.map((d) => d.value);
  const minV = Math.min(...values);
  const maxV = Math.max(...values);
  const range = maxV - minV || 1;
  const pad = 4;

  const points = data.map((d, i) => {
    const x = pad + (i / (data.length - 1)) * (width - pad * 2);
    const y = height - pad - ((d.value - minV) / range) * (height - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <polyline points={points.join(' ')} fill="none" stroke={color} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
      {/* 最后一个点 */}
      {(() => {
        const lastParts = points[points.length - 1].split(',');
        return <circle cx={parseFloat(lastParts[0])} cy={parseFloat(lastParts[1])} r={2.5} fill={color} />;
      })()}
    </svg>
  );
}

// ─── 汇总指标卡 ─────────────────────────────────────────────────────────────────

function SummaryBadge({
  label,
  count,
  color,
  bg,
}: {
  label: string;
  count: number;
  color: string;
  bg: string;
}) {
  return (
    <div style={{
      background: bg,
      borderRadius: 8,
      padding: '14px 20px',
      flex: 1,
      minWidth: 100,
      textAlign: 'center',
    }}>
      <div style={{ fontSize: 28, fontWeight: 700, color, lineHeight: 1.1 }}>{count}</div>
      <div style={{ fontSize: 12, color, marginTop: 4 }}>{label}</div>
    </div>
  );
}

// ─── 门店卡片 ───────────────────────────────────────────────────────────────────

function StoreCard({
  store,
  onClick,
}: {
  store: StoreHealthRadar;
  onClick: () => void;
}) {
  const levelCfg = LEVEL_CONFIG[store.level];
  const gradeColor = GRADE_COLOR[store.health_grade] ?? '#555';

  return (
    <div
      onClick={onClick}
      style={{
        background: '#112228',
        borderRadius: 8,
        padding: 16,
        borderLeft: `4px solid ${levelCfg.color}`,
        cursor: 'pointer',
        transition: 'transform 0.15s ease, box-shadow 0.15s ease',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.transform = 'translateY(-2px)';
        e.currentTarget.style.boxShadow = '0 4px 12px rgba(0,0,0,0.2)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = 'translateY(0)';
        e.currentTarget.style.boxShadow = 'none';
      }}
    >
      {/* 头部：名称 + 等级标签 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: '#fff', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, marginRight: 8 }}>
          {store.store_name}
        </span>
        <span style={{
          fontSize: 10, padding: '2px 8px', borderRadius: 4, fontWeight: 600,
          background: levelCfg.bg, color: levelCfg.color,
        }}>
          {levelCfg.label}
        </span>
      </div>

      {/* 分数 + 评级 + 迷你雷达 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10 }}>
        <div style={{ textAlign: 'center', flexShrink: 0 }}>
          <div style={{ fontSize: 28, fontWeight: 'bold', color: gradeColor, lineHeight: 1 }}>
            {store.health_score}
          </div>
          <div style={{ fontSize: 11, color: gradeColor, marginTop: 2 }}>
            {store.health_grade}级
          </div>
        </div>
        <div style={{ flex: 1, display: 'flex', justifyContent: 'center' }}>
          <RadarChart
            dimensions={store.dimensions as unknown as Record<string, number>}
            size={90}
            color={gradeColor}
          />
        </div>
      </div>

      {/* 7天趋势 */}
      <div style={{ fontSize: 11, color: '#999', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 4 }}>
        <span>7日趋势</span>
        <span style={{ color: store.trend_7d >= 0 ? '#0F6E56' : '#A32D2D', fontWeight: 600 }}>
          {store.trend_7d >= 0 ? '+' : ''}{store.trend_7d}
        </span>
      </div>

      {/* 异常标签 */}
      {store.alerts.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {store.alerts.slice(0, 3).map((alert, i) => (
            <span
              key={i}
              style={{
                background: 'rgba(163,45,45,0.15)',
                color: '#A32D2D',
                fontSize: 10,
                padding: '2px 6px',
                borderRadius: 10,
                whiteSpace: 'nowrap',
              }}
            >
              {alert}
            </span>
          ))}
          {store.alerts.length > 3 && (
            <span style={{ fontSize: 10, color: '#666' }}>+{store.alerts.length - 3}</span>
          )}
        </div>
      )}
    </div>
  );
}

// ─── 区域分布视图 ────────────────────────────────────────────────────────────────

function RegionDistributionView({
  stores,
  onStoreClick,
}: {
  stores: StoreHealthRadar[];
  onStoreClick: (store: StoreHealthRadar) => void;
}) {
  // 按区域分组
  const regionMap = useMemo(() => {
    const map = new Map<string, StoreHealthRadar[]>();
    for (const s of stores) {
      const region = s.region || '未分配';
      if (!map.has(region)) map.set(region, []);
      map.get(region)!.push(s);
    }
    return map;
  }, [stores]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {Array.from(regionMap.entries()).map(([region, regionStores]) => {
        const greenCount = regionStores.filter((s) => s.level === 'green').length;
        const yellowCount = regionStores.filter((s) => s.level === 'yellow').length;
        const redCount = regionStores.filter((s) => s.level === 'red').length;
        const avgScore = Math.round(regionStores.reduce((sum, s) => sum + s.health_score, 0) / regionStores.length);

        return (
          <div key={region} style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
            {/* 区域头 */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{ fontSize: 16, fontWeight: 600, color: '#fff' }}>{region}</span>
                <span style={{ fontSize: 12, color: '#999' }}>{regionStores.length}家门店</span>
              </div>
              <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                <span style={{ fontSize: 12 }}>
                  <span style={{ color: LEVEL_CONFIG.green.color }}>●{greenCount}</span>
                  {' '}
                  <span style={{ color: LEVEL_CONFIG.yellow.color }}>●{yellowCount}</span>
                  {' '}
                  <span style={{ color: LEVEL_CONFIG.red.color }}>●{redCount}</span>
                </span>
                <span style={{ fontSize: 14, fontWeight: 'bold', color: GRADE_COLOR[getGradeFromScore(avgScore)] }}>
                  均分 {avgScore}
                </span>
              </div>
            </div>

            {/* 门店点阵 */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {regionStores
                .sort((a, b) => a.health_score - b.health_score)
                .map((s) => {
                  const cfg = LEVEL_CONFIG[s.level];
                  return (
                    <div
                      key={s.store_id}
                      onClick={() => onStoreClick(s)}
                      title={`${s.store_name} - ${s.health_score}分`}
                      style={{
                        width: 44,
                        height: 44,
                        borderRadius: 6,
                        background: cfg.bg,
                        border: `2px solid ${cfg.color}`,
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        justifyContent: 'center',
                        cursor: 'pointer',
                        transition: 'transform 0.15s',
                      }}
                      onMouseEnter={(e) => { e.currentTarget.style.transform = 'scale(1.15)'; }}
                      onMouseLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                    >
                      <span style={{ fontSize: 13, fontWeight: 'bold', color: cfg.color, lineHeight: 1 }}>
                        {s.health_score}
                      </span>
                      <span style={{ fontSize: 8, color: cfg.color, lineHeight: 1, marginTop: 1 }}>
                        {s.store_name.slice(0, 2)}
                      </span>
                    </div>
                  );
                })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── 风险排行 ───────────────────────────────────────────────────────────────────

function RiskRanking({
  stores,
  onStoreClick,
  onRectify,
  rectifyLoading,
}: {
  stores: StoreHealthRadar[];
  onStoreClick: (store: StoreHealthRadar) => void;
  onRectify: (storeId: string) => void;
  rectifyLoading: string | null;
}) {
  const riskStores = useMemo(
    () => [...stores].sort((a, b) => a.health_score - b.health_score).slice(0, 10),
    [stores],
  );

  return (
    <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h3 style={{ margin: 0, fontSize: 16, color: '#fff' }}>风险门店 Top10</h3>
        <span style={{ fontSize: 11, color: '#999' }}>按健康度从低到高</span>
      </div>

      {riskStores.length === 0 ? (
        <div style={{ textAlign: 'center', color: '#666', padding: 24 }}>暂无风险门店</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {riskStores.map((store, idx) => {
            const gradeColor = GRADE_COLOR[store.health_grade] ?? '#555';
            const levelCfg = LEVEL_CONFIG[store.level];
            const isRed = store.level === 'red';
            const isRectifying = rectifyLoading === store.store_id;

            return (
              <div
                key={store.store_id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  padding: '10px 12px',
                  borderRadius: 6,
                  background: '#0B1A20',
                  cursor: 'pointer',
                  transition: 'background 0.15s',
                }}
                onClick={() => onStoreClick(store)}
                onMouseEnter={(e) => { e.currentTarget.style.background = '#1a2a33'; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = '#0B1A20'; }}
              >
                {/* 排名 */}
                <span style={{
                  width: 22,
                  textAlign: 'center',
                  fontSize: 13,
                  fontWeight: 'bold',
                  color: idx < 3 ? '#A32D2D' : '#666',
                }}>
                  {idx + 1}
                </span>

                {/* 门店名 */}
                <span style={{ flex: 1, fontSize: 13, color: '#fff', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {store.store_name}
                </span>

                {/* 等级标签 */}
                <span style={{
                  fontSize: 10, padding: '2px 6px', borderRadius: 4,
                  background: levelCfg.bg, color: levelCfg.color, fontWeight: 600,
                }}>
                  {levelCfg.label}
                </span>

                {/* 进度条 */}
                <div style={{ width: 80, height: 6, borderRadius: 3, background: '#1a2a33', overflow: 'hidden' }}>
                  <div style={{
                    width: `${store.health_score}%`,
                    height: '100%',
                    borderRadius: 3,
                    background: gradeColor,
                    transition: 'width 0.6s ease',
                  }} />
                </div>

                {/* 分数 */}
                <span style={{ width: 32, textAlign: 'right', fontSize: 14, fontWeight: 'bold', color: gradeColor }}>
                  {store.health_score}
                </span>

                {/* 整改按钮（仅红色门店） */}
                {isRed && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onRectify(store.store_id);
                    }}
                    disabled={isRectifying}
                    style={{
                      padding: '4px 10px',
                      borderRadius: 4,
                      border: 'none',
                      background: isRectifying ? '#555' : '#A32D2D',
                      color: '#fff',
                      fontSize: 11,
                      fontWeight: 600,
                      cursor: isRectifying ? 'not-allowed' : 'pointer',
                      whiteSpace: 'nowrap',
                      flexShrink: 0,
                    }}
                  >
                    {isRectifying ? '创建中...' : '整改'}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── Drawer 详情面板 ────────────────────────────────────────────────────────────

function DetailDrawer({
  detail,
  loading,
  onClose,
  onRectify,
  rectifyLoading,
}: {
  detail: StoreHealthRadarDetail | null;
  loading: boolean;
  onClose: () => void;
  onRectify: (storeId: string) => void;
  rectifyLoading: string | null;
}) {
  const [trendRange, setTrendRange] = useState<'7d' | '30d'>('7d');

  if (!detail && !loading) return null;

  const isRed = detail?.level === 'red';
  const isRectifying = rectifyLoading === detail?.store_id;

  // 构建基准对比数据（来自 dimension_details）
  const benchmarks: Record<string, number> = {};
  if (detail?.dimension_details) {
    for (const dd of detail.dimension_details) {
      benchmarks[dd.key] = dd.benchmark;
    }
  }

  return (
    <>
      {/* 遮罩 */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(0,0,0,0.5)',
          zIndex: 1000,
        }}
      />

      {/* 抽屉面板 */}
      <div style={{
        position: 'fixed',
        top: 0,
        right: 0,
        width: 520,
        maxWidth: '100vw',
        height: '100vh',
        background: '#0B1A20',
        zIndex: 1001,
        display: 'flex',
        flexDirection: 'column',
        boxShadow: '-4px 0 24px rgba(0,0,0,0.3)',
      }}>
        {/* 头部 */}
        <div style={{
          padding: '20px 24px',
          borderBottom: '1px solid #1a2a33',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}>
          <div>
            <h3 style={{ margin: 0, fontSize: 18, color: '#fff' }}>
              {loading ? '加载中...' : detail?.store_name}
            </h3>
            {detail && (
              <span style={{ fontSize: 12, color: '#999' }}>
                {detail.region} · {detail.brand}
              </span>
            )}
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {isRed && detail && (
              <button
                onClick={() => onRectify(detail.store_id)}
                disabled={isRectifying}
                style={{
                  padding: '6px 16px',
                  borderRadius: 6,
                  border: 'none',
                  background: isRectifying ? '#555' : '#A32D2D',
                  color: '#fff',
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: isRectifying ? 'not-allowed' : 'pointer',
                }}
              >
                {isRectifying ? '创建中...' : '一键整改'}
              </button>
            )}
            <button
              onClick={onClose}
              style={{
                width: 32, height: 32, borderRadius: 6, border: 'none',
                background: '#1a2a33', color: '#999', fontSize: 18,
                cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}
            >
              &times;
            </button>
          </div>
        </div>

        {/* 内容 */}
        <div style={{ flex: 1, overflow: 'auto', padding: 24 }}>
          {loading ? (
            <div style={{ textAlign: 'center', color: '#666', padding: 60 }}>加载详情数据中...</div>
          ) : detail ? (
            <>
              {/* 评分概览 */}
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: 20,
                marginBottom: 24,
                padding: 16,
                background: '#112228',
                borderRadius: 8,
              }}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{
                    fontSize: 48,
                    fontWeight: 'bold',
                    color: GRADE_COLOR[detail.health_grade],
                    lineHeight: 1,
                  }}>
                    {detail.health_score}
                  </div>
                  <div style={{
                    fontSize: 14,
                    color: GRADE_COLOR[detail.health_grade],
                    marginTop: 4,
                    fontWeight: 600,
                  }}>
                    {detail.health_grade}级 · {LEVEL_CONFIG[detail.level].label}
                  </div>
                </div>
                <div style={{ flex: 1, display: 'flex', gap: 16 }}>
                  <div style={{ flex: 1, textAlign: 'center' }}>
                    <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>7日变化</div>
                    <div style={{
                      fontSize: 18,
                      fontWeight: 'bold',
                      color: detail.trend_7d >= 0 ? '#0F6E56' : '#A32D2D',
                    }}>
                      {detail.trend_7d >= 0 ? '+' : ''}{detail.trend_7d}
                    </div>
                  </div>
                  <div style={{ flex: 1, textAlign: 'center' }}>
                    <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>30日变化</div>
                    <div style={{
                      fontSize: 18,
                      fontWeight: 'bold',
                      color: detail.trend_30d >= 0 ? '#0F6E56' : '#A32D2D',
                    }}>
                      {detail.trend_30d >= 0 ? '+' : ''}{detail.trend_30d}
                    </div>
                  </div>
                </div>
              </div>

              {/* 六维雷达图 */}
              <div style={{
                background: '#112228',
                borderRadius: 8,
                padding: 20,
                marginBottom: 24,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
              }}>
                <h4 style={{ margin: '0 0 12px', fontSize: 14, color: '#ccc', alignSelf: 'flex-start' }}>
                  六维健康雷达
                </h4>
                <div style={{ display: 'flex', justifyContent: 'center', gap: 16, marginBottom: 8, fontSize: 11, color: '#999' }}>
                  <span><span style={{ color: '#FF6B35' }}>●</span> 门店数据</span>
                  <span><span style={{ color: '#185FA5' }}>- -</span> 行业基准</span>
                </div>
                <RadarChartLarge
                  dimensions={detail.dimensions as unknown as Record<string, number>}
                  benchmarks={Object.keys(benchmarks).length > 0 ? benchmarks : undefined}
                  size={280}
                />
              </div>

              {/* 维度明细 */}
              <div style={{
                background: '#112228',
                borderRadius: 8,
                padding: 20,
                marginBottom: 24,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                  <h4 style={{ margin: 0, fontSize: 14, color: '#ccc' }}>维度详情</h4>
                  <div style={{ display: 'flex', gap: 4 }}>
                    {(['7d', '30d'] as const).map((r) => (
                      <button
                        key={r}
                        onClick={() => setTrendRange(r)}
                        style={{
                          padding: '3px 10px',
                          borderRadius: 4,
                          border: 'none',
                          fontSize: 11,
                          fontWeight: 600,
                          background: trendRange === r ? '#FF6B2C' : '#0B1A20',
                          color: trendRange === r ? '#fff' : '#999',
                          cursor: 'pointer',
                        }}
                      >
                        {r === '7d' ? '近7天' : '近30天'}
                      </button>
                    ))}
                  </div>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {(detail.dimension_details ?? []).map((dd) => {
                    const meta = DIMENSION_META[dd.key];
                    const isInverse = meta?.inverse;
                    const isBad = isInverse
                      ? dd.value > dd.benchmark
                      : dd.value < dd.benchmark;

                    // 根据趋势范围过滤数据
                    const trendData = trendRange === '7d'
                      ? (dd.trend ?? []).slice(-7)
                      : (dd.trend ?? []);

                    return (
                      <div key={dd.key} style={{
                        padding: 12,
                        background: '#0B1A20',
                        borderRadius: 6,
                      }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                          <span style={{ fontSize: 13, color: '#ccc', fontWeight: 500 }}>
                            {dd.label}
                          </span>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <span style={{
                              fontSize: 16,
                              fontWeight: 'bold',
                              color: isBad ? '#A32D2D' : '#0F6E56',
                            }}>
                              {formatDimValue(dd.key, dd.value)}
                            </span>
                            <span style={{ fontSize: 11, color: '#666' }}>
                              基准 {formatDimValue(dd.key, dd.benchmark)}
                            </span>
                          </div>
                        </div>
                        {/* 迷你趋势线 */}
                        <MiniTrendLine
                          data={trendData}
                          width={440}
                          height={32}
                          color={isBad ? '#A32D2D' : '#0F6E56'}
                        />
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* 异常标签 */}
              {detail.alerts.length > 0 && (
                <div style={{
                  background: '#112228',
                  borderRadius: 8,
                  padding: 20,
                }}>
                  <h4 style={{ margin: '0 0 12px', fontSize: 14, color: '#ccc' }}>当前异常</h4>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                    {detail.alerts.map((alert, i) => (
                      <span
                        key={i}
                        style={{
                          background: 'rgba(163,45,45,0.15)',
                          color: '#A32D2D',
                          fontSize: 12,
                          padding: '4px 12px',
                          borderRadius: 12,
                        }}
                      >
                        {alert}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </>
          ) : null}
        </div>
      </div>
    </>
  );
}

// ─── 主页面 ────────────────────────────────────────────────────────────────────

export function StoreHealthRadarPage() {
  const [summary, setSummary] = useState<HealthSummary | null>(null);
  const [stores, setStores] = useState<StoreHealthRadar[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // 筛选
  const [filterRegion, setFilterRegion] = useState('');
  const [filterBrand, setFilterBrand] = useState('');
  const [filterLevel, setFilterLevel] = useState('');

  // 视图模式
  const [viewMode, setViewMode] = useState<'card' | 'map'>('card');

  // Drawer 详情
  const [selectedStoreId, setSelectedStoreId] = useState<string | null>(null);
  const [detail, setDetail] = useState<StoreHealthRadarDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // 整改
  const [rectifyLoading, setRectifyLoading] = useState<string | null>(null);

  // ─── 加载数据 ───
  const loadData = useCallback(async () => {
    try {
      const params: Record<string, string> = {};
      if (filterRegion) params.region = filterRegion;
      if (filterBrand) params.brand = filterBrand;
      if (filterLevel) params.level = filterLevel;

      const [summaryData, listData] = await Promise.all([
        fetchHealthRadarSummary().catch(() => null),
        fetchHealthRadarList(params).catch(() => [] as StoreHealthRadar[]),
      ]);

      if (summaryData) setSummary(summaryData);
      setStores(listData);
      setLastUpdated(new Date());
      setError(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '未知错误';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [filterRegion, filterBrand, filterLevel]);

  useEffect(() => { loadData(); }, [loadData]);

  // 30 秒自动刷新
  useEffect(() => {
    const timer = setInterval(loadData, 30_000);
    return () => clearInterval(timer);
  }, [loadData]);

  // ─── 加载详情 ───
  const openDetail = useCallback(async (store: StoreHealthRadar) => {
    setSelectedStoreId(store.store_id);
    setDetail(null);
    setDetailLoading(true);
    try {
      const data = await fetchStoreRadarDetail(store.store_id);
      setDetail(data);
    } catch {
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const closeDetail = useCallback(() => {
    setSelectedStoreId(null);
    setDetail(null);
  }, []);

  // ─── 一键整改 ───
  const handleRectify = useCallback(async (storeId: string) => {
    setRectifyLoading(storeId);
    try {
      await createRectifyTask(storeId);
      // 简单提示
      window.alert('整改任务已创建');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '创建失败';
      window.alert(`创建整改任务失败：${msg}`);
    } finally {
      setRectifyLoading(null);
    }
  }, []);

  // ─── 筛选选项 ───
  const regionOptions = useMemo(() => {
    const set = new Set(stores.map((s) => s.region).filter(Boolean));
    return Array.from(set).sort();
  }, [stores]);

  const brandOptions = useMemo(() => {
    const set = new Set(stores.map((s) => s.brand).filter(Boolean));
    return Array.from(set).sort();
  }, [stores]);

  // ─── 整体健康度评级 ───
  const avgGrade = summary ? getGradeFromScore(summary.avg_score) : 'D';

  return (
    <div style={{ padding: 24 }}>
      {/* 页头 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: '#fff' }}>门店健康度雷达</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <span style={{ fontSize: 12, color: '#555' }}>
            {loading && !summary
              ? '加载中...'
              : lastUpdated
                ? `更新于 ${lastUpdated.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`
                : null}
          </span>
          <button
            onClick={loadData}
            style={{
              padding: '6px 14px',
              borderRadius: 6,
              border: '1px solid #1a2a33',
              background: '#112228',
              color: '#ccc',
              fontSize: 12,
              cursor: 'pointer',
            }}
          >
            刷新
          </button>
        </div>
      </div>

      {/* 顶部汇总 */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
        <SummaryBadge
          label="达标门店"
          count={summary?.green ?? 0}
          color={LEVEL_CONFIG.green.color}
          bg={LEVEL_CONFIG.green.bg}
        />
        <SummaryBadge
          label="预警门店"
          count={summary?.yellow ?? 0}
          color={LEVEL_CONFIG.yellow.color}
          bg={LEVEL_CONFIG.yellow.bg}
        />
        <SummaryBadge
          label="不达标门店"
          count={summary?.red ?? 0}
          color={LEVEL_CONFIG.red.color}
          bg={LEVEL_CONFIG.red.bg}
        />
        <div style={{
          background: '#112228',
          borderRadius: 8,
          padding: '14px 20px',
          flex: 1,
          minWidth: 100,
          textAlign: 'center',
        }}>
          <div style={{ fontSize: 28, fontWeight: 700, color: '#E0E0E0', lineHeight: 1.1 }}>
            {summary?.total ?? 0}
          </div>
          <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>总门店数</div>
        </div>
        <div style={{
          background: '#112228',
          borderRadius: 8,
          padding: '14px 20px',
          flex: 1,
          minWidth: 100,
          textAlign: 'center',
        }}>
          <div style={{
            fontSize: 28,
            fontWeight: 700,
            color: summary ? GRADE_COLOR[avgGrade] : '#555',
            lineHeight: 1.1,
          }}>
            {summary?.avg_score ?? '—'}
          </div>
          <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>整体健康度</div>
        </div>
      </div>

      {/* 筛选栏 + 视图切换 */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: 16,
        gap: 12,
        flexWrap: 'wrap',
      }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {/* 区域筛选 */}
          <select
            value={filterRegion}
            onChange={(e) => setFilterRegion(e.target.value)}
            style={{
              padding: '6px 12px',
              borderRadius: 6,
              border: '1px solid #1a2a33',
              background: '#112228',
              color: '#ccc',
              fontSize: 12,
              cursor: 'pointer',
              outline: 'none',
            }}
          >
            <option value="">全部区域</option>
            {regionOptions.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>

          {/* 品牌筛选 */}
          <select
            value={filterBrand}
            onChange={(e) => setFilterBrand(e.target.value)}
            style={{
              padding: '6px 12px',
              borderRadius: 6,
              border: '1px solid #1a2a33',
              background: '#112228',
              color: '#ccc',
              fontSize: 12,
              cursor: 'pointer',
              outline: 'none',
            }}
          >
            <option value="">全部品牌</option>
            {brandOptions.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>

          {/* 健康等级筛选 */}
          <div style={{ display: 'flex', gap: 4 }}>
            {[
              { value: '', label: '全部' },
              { value: 'green', label: '达标' },
              { value: 'yellow', label: '预警' },
              { value: 'red', label: '不达标' },
            ].map((opt) => (
              <button
                key={opt.value}
                onClick={() => setFilterLevel(opt.value)}
                style={{
                  padding: '5px 12px',
                  borderRadius: 6,
                  border: 'none',
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: 'pointer',
                  background: filterLevel === opt.value ? '#FF6B2C' : '#0B1A20',
                  color: filterLevel === opt.value ? '#fff' : '#999',
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* 视图切换 */}
        <div style={{ display: 'flex', gap: 4, background: '#0B1A20', borderRadius: 6, padding: 2 }}>
          <button
            onClick={() => setViewMode('card')}
            style={{
              padding: '5px 14px',
              borderRadius: 4,
              border: 'none',
              fontSize: 12,
              fontWeight: 600,
              cursor: 'pointer',
              background: viewMode === 'card' ? '#FF6B2C' : 'transparent',
              color: viewMode === 'card' ? '#fff' : '#999',
            }}
          >
            卡片
          </button>
          <button
            onClick={() => setViewMode('map')}
            style={{
              padding: '5px 14px',
              borderRadius: 4,
              border: 'none',
              fontSize: 12,
              fontWeight: 600,
              cursor: 'pointer',
              background: viewMode === 'map' ? '#FF6B2C' : 'transparent',
              color: viewMode === 'map' ? '#fff' : '#999',
            }}
          >
            区域
          </button>
        </div>
      </div>

      {/* 错误提示 */}
      {error && (
        <div style={{
          background: 'rgba(163,45,45,0.1)',
          border: '1px solid rgba(163,45,45,0.3)',
          borderRadius: 8,
          padding: '12px 16px',
          marginBottom: 16,
          color: '#A32D2D',
          fontSize: 14,
        }}>
          数据加载失败：{error}
        </div>
      )}

      {/* 主体内容 */}
      {loading && !summary ? (
        <div style={{ color: '#555', textAlign: 'center', padding: 60, fontSize: 14 }}>
          正在加载门店健康度数据...
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: 16, alignItems: 'start' }}>
          {/* 左侧：门店列表 */}
          <div>
            {stores.length === 0 ? (
              <div style={{ color: '#555', textAlign: 'center', padding: 60, fontSize: 14 }}>
                暂无门店数据
              </div>
            ) : viewMode === 'card' ? (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 12 }}>
                {stores.map((store) => (
                  <StoreCard
                    key={store.store_id}
                    store={store}
                    onClick={() => openDetail(store)}
                  />
                ))}
              </div>
            ) : (
              <RegionDistributionView
                stores={stores}
                onStoreClick={openDetail}
              />
            )}
          </div>

          {/* 右侧：风险排行 */}
          <RiskRanking
            stores={stores}
            onStoreClick={openDetail}
            onRectify={handleRectify}
            rectifyLoading={rectifyLoading}
          />
        </div>
      )}

      {/* Drawer 详情 */}
      {selectedStoreId && (
        <DetailDrawer
          detail={detail}
          loading={detailLoading}
          onClose={closeDetail}
          onRectify={handleRectify}
          rectifyLoading={rectifyLoading}
        />
      )}
    </div>
  );
}
