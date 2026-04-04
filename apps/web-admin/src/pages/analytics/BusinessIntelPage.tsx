/**
 * 商业智能仪表盘 — BusinessIntelPage
 * 域G: 经营分析 / 商业智能
 *
 * 布局：
 *   1. 经营健康度大卡片（全宽，圆形评分仪表盘 + 5个维度进度条 + 异常提醒）
 *   2. 左侧60%：菜品四象限SVG图
 *   3. 右侧40%：异常检测Timeline
 *
 * 技术：Ant Design 5.x，React Hooks，fetch API（带 X-Tenant-ID）
 * 图表：纯CSS/SVG，无第三方图表库
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Row,
  Col,
  Progress,
  Tag,
  Timeline,
  Button,
  Tooltip,
  Spin,
  Badge,
  Select,
  message,
  Alert as AntAlert,
} from 'antd';
import {
  ExclamationCircleOutlined,
  CheckCircleOutlined,
  WarningOutlined,
  ThunderboltOutlined,
  FireOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons';

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

interface Dimension {
  key: string;
  label: string;
  score: number;
  weight: number;
  grade: string;
}

interface HealthScoreData {
  overall_score: number;
  grade: string;
  dimensions: Dimension[];
  trend: string;
  alerts: string[];
  _is_mock?: boolean;
}

interface DishPoint {
  dish_name: string;
  sales_count: number;
  gross_margin_pct: number;
}

interface DishMatrixData {
  quadrants: {
    star: DishPoint[];
    cash_cow: DishPoint[];
    question_mark: DishPoint[];
    dog: DishPoint[];
  };
  metadata: {
    sales_median: number;
    margin_median: number;
    total_dishes: number;
  };
  _is_mock?: boolean;
}

interface Anomaly {
  id: string;
  type: string;
  severity: 'critical' | 'warning' | 'info';
  description: string;
  occurred_at: string;
  dismissed: boolean;
}

interface AnomalyData {
  anomalies: Anomaly[];
  total: number;
  critical_count: number;
  warning_count: number;
  _is_mock?: boolean;
}

// ─── 常量 ─────────────────────────────────────────────────────────────────────

const INTEL_BASE = 'http://localhost:8011';

const GRADE_COLOR: Record<string, string> = {
  A: '#0F6E56',
  B: '#185FA5',
  C: '#BA7517',
  D: '#A32D2D',
};

const GRADE_BG: Record<string, string> = {
  A: '#e6f7f1',
  B: '#e8f0fb',
  C: '#fdf6e3',
  D: '#fde8e8',
};

const SEVERITY_COLOR: Record<string, string> = {
  critical: '#A32D2D',
  warning: '#BA7517',
  info: '#185FA5',
};

const SEVERITY_LABEL: Record<string, string> = {
  critical: '严重',
  warning: '警告',
  info: '提示',
};

const ANOMALY_TYPE_LABEL: Record<string, string> = {
  revenue_drop: '营收下滑',
  cost_spike: '成本超标',
  high_refund: '退单率高',
  slow_kitchen: '出餐超时',
  expiry_risk: '临期风险',
};

const QUADRANT_CONFIG = {
  star: { label: '明星菜', color: '#0F6E56', bg: 'rgba(15, 110, 86, 0.08)', symbol: '⭐' },
  cash_cow: { label: '现金牛', color: '#185FA5', bg: 'rgba(24, 95, 165, 0.08)', symbol: '🐄' },
  question_mark: { label: '问题菜', color: '#BA7517', bg: 'rgba(186, 117, 23, 0.08)', symbol: '❓' },
  dog: { label: '瘦狗菜', color: '#A32D2D', bg: 'rgba(163, 45, 45, 0.08)', symbol: '🐾' },
};

// ─── API 工具函数 ─────────────────────────────────────────────────────────────

function getTenantId(): string {
  return localStorage.getItem('tx_tenant_id') || '00000000-0000-0000-0000-000000000001';
}

async function fetchIntel<T>(path: string): Promise<T> {
  const res = await fetch(`${INTEL_BASE}${path}`, {
    headers: { 'X-Tenant-ID': getTenantId(), 'Content-Type': 'application/json' },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const json = await res.json();
  if (!json.ok) throw new Error(json.error || 'API error');
  return json.data as T;
}

async function dismissAnomalyApi(id: string): Promise<void> {
  const res = await fetch(`${INTEL_BASE}/api/v1/intel/anomalies/${id}/dismiss`, {
    method: 'POST',
    headers: { 'X-Tenant-ID': getTenantId(), 'Content-Type': 'application/json' },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

// ─── 子组件：圆形评分仪表盘 ────────────────────────────────────────────────────

function ScoreGauge({ score, grade }: { score: number; grade: string }) {
  const color = GRADE_COLOR[grade] ?? '#FF6B35';
  const pct = Math.min(100, Math.max(0, score));
  // conic-gradient 圆形进度
  const gradient = `conic-gradient(${color} ${pct}%, #f0ede6 0%)`;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
      <div
        style={{
          width: 140,
          height: 140,
          borderRadius: '50%',
          background: gradient,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          boxShadow: '0 4px 12px rgba(0,0,0,0.10)',
        }}
      >
        <div
          style={{
            width: 108,
            height: 108,
            borderRadius: '50%',
            background: '#fff',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <span style={{ fontSize: 36, fontWeight: 700, color, lineHeight: 1 }}>
            {Math.round(score)}
          </span>
          <span style={{ fontSize: 12, color: '#5F5E5A', marginTop: 2 }}>综合健康度</span>
        </div>
      </div>
      <div
        style={{
          padding: '4px 16px',
          borderRadius: 20,
          background: GRADE_BG[grade] ?? '#f5f5f5',
          color: GRADE_COLOR[grade] ?? '#555',
          fontWeight: 700,
          fontSize: 16,
        }}
      >
        {grade} 级
      </div>
    </div>
  );
}

// ─── 子组件：健康度大卡片 ───────────────────────────────────────────────────────

function HealthScoreCard({
  data,
  loading,
}: {
  data: HealthScoreData | null;
  loading: boolean;
}) {
  if (loading) {
    return (
      <Card style={{ marginBottom: 16, minHeight: 200 }}>
        <div style={{ display: 'flex', justifyContent: 'center', padding: '40px 0' }}>
          <Spin size="large" />
        </div>
      </Card>
    );
  }
  if (!data) return null;

  const trendNum = parseFloat(data.trend);
  const trendColor = trendNum >= 0 ? '#0F6E56' : '#A32D2D';
  const trendSign = trendNum >= 0 ? '+' : '';

  return (
    <Card
      title={
        <span style={{ fontSize: 16, fontWeight: 600 }}>
          经营健康度评分
          {data._is_mock && (
            <Tag color="orange" style={{ marginLeft: 8, fontSize: 11 }}>演示数据</Tag>
          )}
        </span>
      }
      extra={
        <span style={{ color: trendColor, fontSize: 13, fontWeight: 500 }}>
          本月较上月 {trendSign}{data.trend}分
        </span>
      }
      style={{ marginBottom: 16 }}
    >
      <Row gutter={32} align="middle" wrap={false}>
        {/* 圆形仪表盘 */}
        <Col flex="none">
          <ScoreGauge score={data.overall_score} grade={data.grade} />
        </Col>

        {/* 5个维度进度条 */}
        <Col flex="1" style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {data.dimensions.map((dim) => {
              const dimColor =
                dim.score >= 75
                  ? '#0F6E56'
                  : dim.score >= 60
                  ? '#185FA5'
                  : dim.score >= 45
                  ? '#BA7517'
                  : '#A32D2D';
              return (
                <div key={dim.key}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                    <span style={{ fontSize: 13, color: '#2C2C2A' }}>
                      {dim.label}
                      <span style={{ color: '#B4B2A9', fontSize: 11, marginLeft: 4 }}>
                        权重{(dim.weight * 100).toFixed(0)}%
                      </span>
                    </span>
                    <span style={{ fontSize: 13, fontWeight: 600, color: dimColor }}>
                      {dim.score.toFixed(0)}分
                    </span>
                  </div>
                  <Progress
                    percent={dim.score}
                    showInfo={false}
                    strokeColor={dimColor}
                    trailColor="#f0ede6"
                    size={['100%', 8]}
                  />
                </div>
              );
            })}
          </div>
        </Col>

        {/* 异常提醒 */}
        {data.alerts.length > 0 && (
          <Col flex="none" style={{ minWidth: 220, maxWidth: 280 }}>
            <div
              style={{
                background: '#fde8e8',
                borderRadius: 8,
                padding: '12px 16px',
                border: '1px solid #f5c6c6',
              }}
            >
              <div style={{ fontSize: 13, fontWeight: 600, color: '#A32D2D', marginBottom: 8 }}>
                <ExclamationCircleOutlined style={{ marginRight: 6 }} />
                需关注（{data.alerts.length}项）
              </div>
              {data.alerts.map((alert, idx) => (
                <div
                  key={idx}
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 6,
                    marginBottom: idx < data.alerts.length - 1 ? 6 : 0,
                  }}
                >
                  <Tag color="red" style={{ flexShrink: 0, marginTop: 1 }}>!</Tag>
                  <span style={{ fontSize: 12, color: '#A32D2D', lineHeight: 1.5 }}>{alert}</span>
                </div>
              ))}
            </div>
          </Col>
        )}
        {data.alerts.length === 0 && (
          <Col flex="none" style={{ minWidth: 180 }}>
            <div
              style={{
                background: '#e6f7f1',
                borderRadius: 8,
                padding: '16px 20px',
                textAlign: 'center',
              }}
            >
              <CheckCircleOutlined style={{ fontSize: 28, color: '#0F6E56', display: 'block', marginBottom: 8 }} />
              <span style={{ color: '#0F6E56', fontSize: 13, fontWeight: 500 }}>运营状态健康</span>
              <br />
              <span style={{ color: '#5F5E5A', fontSize: 11 }}>所有指标在正常范围内</span>
            </div>
          </Col>
        )}
      </Row>
    </Card>
  );
}

// ─── 子组件：菜品四象限SVG图 ───────────────────────────────────────────────────

type QuadrantKey = 'star' | 'cash_cow' | 'question_mark' | 'dog';

function DishMatrixChart({
  data,
  loading,
}: {
  data: DishMatrixData | null;
  loading: boolean;
}) {
  const [hoveredDish, setHoveredDish] = useState<(DishPoint & { x: number; y: number }) | null>(null);

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: '60px 0' }}>
        <Spin />
      </div>
    );
  }
  if (!data) return null;

  const SVG_W = 520;
  const SVG_H = 400;
  const PAD = { left: 48, right: 20, top: 20, bottom: 48 };
  const plotW = SVG_W - PAD.left - PAD.right;
  const plotH = SVG_H - PAD.top - PAD.bottom;

  // 收集所有菜品
  const allDishes: (DishPoint & { quadrant: QuadrantKey })[] = [];
  (Object.entries(data.quadrants) as [QuadrantKey, DishPoint[]][]).forEach(([q, dishes]) => {
    dishes.forEach((d) => allDishes.push({ ...d, quadrant: q }));
  });

  if (allDishes.length === 0) return null;

  const maxSales = Math.max(...allDishes.map((d) => d.sales_count), 1);
  const maxMargin = 1.0;

  const toX = (sales: number) => PAD.left + (sales / maxSales) * plotW;
  const toY = (margin: number) => PAD.top + (1 - margin / maxMargin) * plotH;

  const medianX = PAD.left + (data.metadata.sales_median / maxSales) * plotW;
  const medianY = PAD.top + (1 - data.metadata.margin_median / maxMargin) * plotH;

  // 四个象限背景
  const quadrantBgs = [
    // star：右上
    { x: medianX, y: PAD.top, w: SVG_W - PAD.right - medianX, h: medianY - PAD.top, q: 'star' as QuadrantKey },
    // cash_cow：右下
    { x: medianX, y: medianY, w: SVG_W - PAD.right - medianX, h: SVG_H - PAD.bottom - medianY, q: 'cash_cow' as QuadrantKey },
    // question_mark：左上
    { x: PAD.left, y: PAD.top, w: medianX - PAD.left, h: medianY - PAD.top, q: 'question_mark' as QuadrantKey },
    // dog：左下
    { x: PAD.left, y: medianY, w: medianX - PAD.left, h: SVG_H - PAD.bottom - medianY, q: 'dog' as QuadrantKey },
  ];

  return (
    <div style={{ position: 'relative' }}>
      <svg
        width="100%"
        viewBox={`0 0 ${SVG_W} ${SVG_H}`}
        style={{ display: 'block', fontFamily: 'inherit' }}
      >
        {/* 象限背景 */}
        {quadrantBgs.map((bg) => (
          <rect
            key={bg.q}
            x={bg.x}
            y={bg.y}
            width={bg.w}
            height={bg.h}
            fill={QUADRANT_CONFIG[bg.q].bg}
          />
        ))}

        {/* 象限标签 */}
        {quadrantBgs.map((bg) => (
          <text
            key={`label-${bg.q}`}
            x={bg.x + bg.w / 2}
            y={bg.y + 18}
            textAnchor="middle"
            fontSize={11}
            fill={QUADRANT_CONFIG[bg.q].color}
            fontWeight={600}
            opacity={0.7}
          >
            {QUADRANT_CONFIG[bg.q].symbol} {QUADRANT_CONFIG[bg.q].label}
          </text>
        ))}

        {/* 中位数分割线 */}
        <line
          x1={medianX} y1={PAD.top}
          x2={medianX} y2={SVG_H - PAD.bottom}
          stroke="#B4B2A9" strokeWidth={1} strokeDasharray="4 3"
        />
        <line
          x1={PAD.left} y1={medianY}
          x2={SVG_W - PAD.right} y2={medianY}
          stroke="#B4B2A9" strokeWidth={1} strokeDasharray="4 3"
        />

        {/* X轴 */}
        <line
          x1={PAD.left} y1={SVG_H - PAD.bottom}
          x2={SVG_W - PAD.right} y2={SVG_H - PAD.bottom}
          stroke="#E8E6E1" strokeWidth={1}
        />
        <text x={SVG_W / 2} y={SVG_H - 8} textAnchor="middle" fontSize={11} fill="#5F5E5A">
          销量 →
        </text>

        {/* Y轴 */}
        <line
          x1={PAD.left} y1={PAD.top}
          x2={PAD.left} y2={SVG_H - PAD.bottom}
          stroke="#E8E6E1" strokeWidth={1}
        />
        <text
          x={14}
          y={SVG_H / 2}
          textAnchor="middle"
          fontSize={11}
          fill="#5F5E5A"
          transform={`rotate(-90, 14, ${SVG_H / 2})`}
        >
          毛利率 →
        </text>

        {/* 菜品散点 */}
        {allDishes.map((d, idx) => {
          const cx = toX(d.sales_count);
          const cy = toY(d.gross_margin_pct);
          const qColor = QUADRANT_CONFIG[d.quadrant].color;
          return (
            <g key={idx}>
              <circle
                cx={cx}
                cy={cy}
                r={6}
                fill={qColor}
                fillOpacity={0.75}
                stroke="#fff"
                strokeWidth={1.5}
                style={{ cursor: 'pointer' }}
                onMouseEnter={() => setHoveredDish({ ...d, x: cx, y: cy })}
                onMouseLeave={() => setHoveredDish(null)}
              />
            </g>
          );
        })}

        {/* Hover tooltip */}
        {hoveredDish && (() => {
          const tx = hoveredDish.x + 10;
          const ty = Math.max(hoveredDish.y - 40, PAD.top);
          return (
            <g>
              <rect
                x={tx - 4}
                y={ty - 14}
                width={160}
                height={52}
                rx={4}
                fill="#fff"
                stroke="#E8E6E1"
                strokeWidth={1}
                filter="drop-shadow(0 2px 4px rgba(0,0,0,0.10))"
              />
              <text x={tx} y={ty} fontSize={12} fill="#2C2C2A" fontWeight={600}>
                {hoveredDish.dish_name.length > 10
                  ? hoveredDish.dish_name.substring(0, 10) + '…'
                  : hoveredDish.dish_name}
              </text>
              <text x={tx} y={ty + 16} fontSize={11} fill="#5F5E5A">
                销量: {hoveredDish.sales_count}份
              </text>
              <text x={tx} y={ty + 30} fontSize={11} fill="#5F5E5A">
                毛利率: {(hoveredDish.gross_margin_pct * 100).toFixed(1)}%
              </text>
            </g>
          );
        })()}
      </svg>

      {/* 图例 */}
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 8 }}>
        {(Object.entries(QUADRANT_CONFIG) as [QuadrantKey, typeof QUADRANT_CONFIG[QuadrantKey]][]).map(([q, cfg]) => (
          <div key={q} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div
              style={{ width: 10, height: 10, borderRadius: '50%', background: cfg.color }}
            />
            <span style={{ fontSize: 12, color: '#5F5E5A' }}>
              {cfg.label}（{(data.quadrants[q] ?? []).length}款）
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── 子组件：异常检测卡片 ──────────────────────────────────────────────────────

function AnomalyIcon({ type }: { type: string }) {
  const icons: Record<string, React.ReactNode> = {
    revenue_drop: <ThunderboltOutlined />,
    cost_spike: <FireOutlined />,
    high_refund: <ExclamationCircleOutlined />,
    slow_kitchen: <ClockCircleOutlined />,
    expiry_risk: <WarningOutlined />,
  };
  return <>{icons[type] ?? <ExclamationCircleOutlined />}</>;
}

function AnomalyTimeline({
  data,
  loading,
  onDismiss,
}: {
  data: AnomalyData | null;
  loading: boolean;
  onDismiss: (id: string) => void;
}) {
  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: '40px 0' }}>
        <Spin />
      </div>
    );
  }
  if (!data || data.anomalies.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '32px 0', color: '#5F5E5A' }}>
        <CheckCircleOutlined style={{ fontSize: 32, color: '#0F6E56', marginBottom: 8, display: 'block' }} />
        最近7天无异常，运营状态良好
      </div>
    );
  }

  const allWithDismissed = [...data.anomalies];

  return (
    <Timeline
      items={allWithDismissed.map((a) => ({
        color: a.dismissed ? '#B4B2A9' : SEVERITY_COLOR[a.severity] ?? '#BA7517',
        dot: (
          <span style={{ fontSize: 14, color: a.dismissed ? '#B4B2A9' : SEVERITY_COLOR[a.severity] }}>
            <AnomalyIcon type={a.type} />
          </span>
        ),
        children: (
          <div
            style={{
              background: a.dismissed ? '#f8f7f5' : '#fff',
              border: `1px solid ${a.dismissed ? '#E8E6E1' : SEVERITY_COLOR[a.severity] + '33'}`,
              borderRadius: 6,
              padding: '10px 12px',
              marginBottom: 8,
              opacity: a.dismissed ? 0.6 : 1,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
              <div style={{ flex: 1 }}>
                <div style={{ marginBottom: 4 }}>
                  <Tag
                    color={a.dismissed ? 'default' : a.severity === 'critical' ? 'red' : 'orange'}
                    style={{ fontSize: 11 }}
                  >
                    {SEVERITY_LABEL[a.severity]}
                  </Tag>
                  <Tag style={{ fontSize: 11 }} color="default">
                    {ANOMALY_TYPE_LABEL[a.type] ?? a.type}
                  </Tag>
                </div>
                <div
                  style={{
                    fontSize: 13,
                    color: a.dismissed ? '#B4B2A9' : '#2C2C2A',
                    lineHeight: 1.5,
                  }}
                >
                  {a.description}
                </div>
                <div style={{ fontSize: 11, color: '#B4B2A9', marginTop: 4 }}>
                  {new Date(a.occurred_at).toLocaleString('zh-CN', {
                    month: 'numeric',
                    day: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
                </div>
              </div>
              {!a.dismissed && (
                <Button
                  size="small"
                  type="text"
                  style={{ fontSize: 11, color: '#5F5E5A', flexShrink: 0 }}
                  onClick={() => onDismiss(a.id)}
                >
                  已知悉
                </Button>
              )}
              {a.dismissed && (
                <span style={{ fontSize: 11, color: '#B4B2A9', flexShrink: 0 }}>已知悉</span>
              )}
            </div>
          </div>
        ),
      }))}
    />
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export default function BusinessIntelPage() {
  const [healthData, setHealthData] = useState<HealthScoreData | null>(null);
  const [matrixData, setMatrixData] = useState<DishMatrixData | null>(null);
  const [anomalyData, setAnomalyData] = useState<AnomalyData | null>(null);
  const [loadingHealth, setLoadingHealth] = useState(true);
  const [loadingMatrix, setLoadingMatrix] = useState(true);
  const [loadingAnomaly, setLoadingAnomaly] = useState(true);
  const [storeId, setStoreId] = useState<string | undefined>(undefined);
  const [periodDays, setPeriodDays] = useState(30);

  const fetchAll = useCallback(async () => {
    // 健康度
    setLoadingHealth(true);
    fetchIntel<HealthScoreData>(
      `/api/v1/intel/health-score${storeId ? `?store_id=${storeId}` : ''}`
    )
      .then(setHealthData)
      .catch(() => {
        // 降级演示数据
        setHealthData({
          overall_score: 74.5,
          grade: 'B',
          dimensions: [
            { key: 'revenue_trend', label: '营收趋势', score: 72, weight: 0.3, grade: 'B' },
            { key: 'cost_control', label: '成本控制', score: 68, weight: 0.25, grade: 'C' },
            { key: 'customer_satisfaction', label: '顾客满意度', score: 85, weight: 0.2, grade: 'A' },
            { key: 'operational_efficiency', label: '运营效率', score: 78, weight: 0.15, grade: 'B' },
            { key: 'inventory_health', label: '库存健康', score: 52, weight: 0.1, grade: 'D' },
          ],
          trend: '+3',
          alerts: ['食材损耗率偏高，或有较多临期预警', '食材/人力成本占比偏高，超出安全阈值'],
          _is_mock: true,
        });
      })
      .finally(() => setLoadingHealth(false));

    // 四象限
    setLoadingMatrix(true);
    fetchIntel<DishMatrixData>(
      `/api/v1/intel/dish-matrix?period_days=${periodDays}${storeId ? `&store_id=${storeId}` : ''}`
    )
      .then(setMatrixData)
      .catch(() => {
        setMatrixData({
          quadrants: {
            star: [
              { dish_name: '招牌红烧肉', sales_count: 320, gross_margin_pct: 0.68 },
              { dish_name: '辣椒炒肉', sales_count: 280, gross_margin_pct: 0.72 },
            ],
            cash_cow: [
              { dish_name: '白米饭', sales_count: 450, gross_margin_pct: 0.35 },
              { dish_name: '老坛酸菜鱼', sales_count: 380, gross_margin_pct: 0.42 },
            ],
            question_mark: [
              { dish_name: '松茸炖土鸡', sales_count: 45, gross_margin_pct: 0.71 },
              { dish_name: '和牛刺身拼盘', sales_count: 28, gross_margin_pct: 0.65 },
            ],
            dog: [
              { dish_name: '茄子炒肉', sales_count: 62, gross_margin_pct: 0.28 },
              { dish_name: '素炒时蔬', sales_count: 55, gross_margin_pct: 0.22 },
            ],
          },
          metadata: { sales_median: 171, margin_median: 0.535, total_dishes: 8 },
          _is_mock: true,
        });
      })
      .finally(() => setLoadingMatrix(false));

    // 异常
    setLoadingAnomaly(true);
    fetchIntel<AnomalyData>(`/api/v1/intel/anomalies?days=7`)
      .then(setAnomalyData)
      .catch(() => {
        setAnomalyData({
          anomalies: [
            {
              id: 'mock-001',
              type: 'expiry_risk',
              severity: 'critical',
              description: '7天内临期食材达14种，含三文鱼、牛里脊等高值食材',
              occurred_at: new Date(Date.now() - 86400000).toISOString(),
              dismissed: false,
            },
            {
              id: 'mock-002',
              type: 'cost_spike',
              severity: 'critical',
              description: '3月30日食材成本占比63%，超过60%阈值',
              occurred_at: new Date(Date.now() - 172800000).toISOString(),
              dismissed: false,
            },
            {
              id: 'mock-003',
              type: 'revenue_drop',
              severity: 'warning',
              description: '3月28日营收同比下滑22%',
              occurred_at: new Date(Date.now() - 432000000).toISOString(),
              dismissed: false,
            },
            {
              id: 'mock-004',
              type: 'high_refund',
              severity: 'warning',
              description: '近7天退单率6.2%，超过5%警戒线',
              occurred_at: new Date(Date.now() - 259200000).toISOString(),
              dismissed: true,
            },
          ],
          total: 4,
          critical_count: 2,
          warning_count: 2,
          _is_mock: true,
        });
      })
      .finally(() => setLoadingAnomaly(false));
  }, [storeId, periodDays]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const handleDismiss = useCallback(async (anomalyId: string) => {
    try {
      await dismissAnomalyApi(anomalyId);
      setAnomalyData((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          anomalies: prev.anomalies.map((a) =>
            a.id === anomalyId ? { ...a, dismissed: true } : a
          ),
        };
      });
      message.success('已标记为知悉');
    } catch {
      // mock 模式：直接更新本地状态
      setAnomalyData((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          anomalies: prev.anomalies.map((a) =>
            a.id === anomalyId ? { ...a, dismissed: true } : a
          ),
        };
      });
      message.success('已标记为知悉');
    }
  }, []);

  const undismissedCount =
    anomalyData?.anomalies.filter((a) => !a.dismissed).length ?? 0;
  const criticalCount = anomalyData?.anomalies.filter(
    (a) => !a.dismissed && a.severity === 'critical'
  ).length ?? 0;

  return (
    <div style={{ padding: '20px 24px', background: '#f8f7f5', minHeight: '100vh' }}>
      {/* 页面标题栏 */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 16,
        }}
      >
        <div>
          <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: '#1E2A3A' }}>
            商业智能仪表盘
          </h2>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: '#5F5E5A' }}>
            健康度评分 · 菜品四象限 · 异常检测
          </p>
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          {criticalCount > 0 && (
            <Badge count={criticalCount} color="#A32D2D">
              <AntAlert
                type="error"
                message={`${criticalCount}项严重异常待处理`}
                style={{ padding: '4px 12px', fontSize: 12 }}
                showIcon
              />
            </Badge>
          )}
          <Select
            placeholder="统计周期"
            value={periodDays}
            onChange={setPeriodDays}
            style={{ width: 100 }}
            options={[
              { value: 7, label: '近7天' },
              { value: 30, label: '近30天' },
              { value: 90, label: '近90天' },
            ]}
          />
          <Button type="primary" style={{ background: '#FF6B35', borderColor: '#FF6B35' }} onClick={fetchAll}>
            刷新
          </Button>
        </div>
      </div>

      {/* 模块1：经营健康度大卡片 */}
      <HealthScoreCard data={healthData} loading={loadingHealth} />

      {/* 模块2 + 3：四象限图 + 异常检测 */}
      <Row gutter={16}>
        {/* 菜品四象限（60%） */}
        <Col span={15}>
          <Card
            title={
              <span style={{ fontSize: 15, fontWeight: 600 }}>
                菜品四象限分析
                {matrixData?._is_mock && (
                  <Tag color="orange" style={{ marginLeft: 8, fontSize: 11 }}>演示数据</Tag>
                )}
              </span>
            }
            extra={
              matrixData && (
                <span style={{ fontSize: 12, color: '#5F5E5A' }}>
                  共{matrixData.metadata.total_dishes}款菜品 · 近{periodDays}天数据
                </span>
              )
            }
            style={{ height: '100%' }}
          >
            <DishMatrixChart data={matrixData} loading={loadingMatrix} />

            {/* 四象限说明 */}
            {!loadingMatrix && matrixData && (
              <div
                style={{
                  marginTop: 16,
                  display: 'grid',
                  gridTemplateColumns: '1fr 1fr',
                  gap: 8,
                }}
              >
                {(Object.entries(QUADRANT_CONFIG) as [QuadrantKey, typeof QUADRANT_CONFIG[QuadrantKey]][]).map(([q, cfg]) => {
                  const dishes = matrixData.quadrants[q] ?? [];
                  return (
                    <div
                      key={q}
                      style={{
                        background: cfg.bg,
                        borderRadius: 6,
                        padding: '8px 12px',
                        border: `1px solid ${cfg.color}22`,
                      }}
                    >
                      <div style={{ fontSize: 12, fontWeight: 600, color: cfg.color, marginBottom: 4 }}>
                        {cfg.symbol} {cfg.label}（{dishes.length}款）
                      </div>
                      {dishes.slice(0, 3).map((d, i) => (
                        <div
                          key={i}
                          style={{
                            fontSize: 11,
                            color: '#5F5E5A',
                            display: 'flex',
                            justifyContent: 'space-between',
                          }}
                        >
                          <span>
                            {d.dish_name.length > 8 ? d.dish_name.substring(0, 8) + '…' : d.dish_name}
                          </span>
                          <span>
                            {d.sales_count}份 / {(d.gross_margin_pct * 100).toFixed(0)}%毛利
                          </span>
                        </div>
                      ))}
                      {dishes.length > 3 && (
                        <div style={{ fontSize: 11, color: '#B4B2A9', marginTop: 2 }}>
                          +{dishes.length - 3}款...
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </Card>
        </Col>

        {/* 异常检测（40%） */}
        <Col span={9}>
          <Card
            title={
              <span style={{ fontSize: 15, fontWeight: 600 }}>
                异常检测
                {undismissedCount > 0 && (
                  <Badge
                    count={undismissedCount}
                    style={{ marginLeft: 8, backgroundColor: criticalCount > 0 ? '#A32D2D' : '#BA7517' }}
                  />
                )}
                {anomalyData?._is_mock && (
                  <Tag color="orange" style={{ marginLeft: 8, fontSize: 11 }}>演示数据</Tag>
                )}
              </span>
            }
            extra={<span style={{ fontSize: 12, color: '#5F5E5A' }}>最近7天</span>}
            style={{ height: '100%' }}
          >
            <AnomalyTimeline
              data={anomalyData}
              loading={loadingAnomaly}
              onDismiss={handleDismiss}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
