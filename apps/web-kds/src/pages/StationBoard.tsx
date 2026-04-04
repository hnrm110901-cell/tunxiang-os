/**
 * StationBoard — 档口绩效实时看板
 *
 * 展示在后厨墙上的实时绩效屏，纯展示无交互。
 * 全屏深色背景，文字超大（后厨抬头看）。
 *
 * 功能：
 *   - 档口卡片网格（2×3）：档口名、今日出品数、平均出品时长、在岗人数、状态指示灯
 *   - 全场统计栏（顶部横条）
 *   - SVG 环形图：各档口出品占比
 *   - 底部跑马灯：最近10笔出品记录
 *   - 60s 自动刷新 + 顶部进度条
 *
 * API：http://localhost:8001，try/catch 降级 Mock
 */
import { useState, useEffect, useCallback, useRef } from 'react';

/* ─────────────────── 类型定义 ─────────────────── */

interface StationData {
  name: string;
  todayCount: number;
  avgMinutes: number;
  staffCount: number;
  status: 'busy' | 'normal' | 'idle';
}

interface RecentDish {
  id: string;
  stationName: string;
  dishName: string;
  finishedAt: string;
  minutes: number;
}

interface StationStats {
  stations: StationData[];
  recentDishes: RecentDish[];
}

/* ─────────────────── 常量 ─────────────────── */

const BASE = 'http://localhost:8001';
const REFRESH_INTERVAL = 60_000;

const STATUS_MAP: Record<StationData['status'], { emoji: string; label: string; color: string }> = {
  busy:   { emoji: '🔴', label: '繁忙', color: '#FF4D4D' },
  normal: { emoji: '🟡', label: '正常', color: '#FFD700' },
  idle:   { emoji: '🟢', label: '空闲', color: '#4ADE80' },
};

const STATION_COLORS = ['#FF6B35', '#4FC3F7', '#81C784', '#FFD54F', '#CE93D8', '#FF8A65'];

/* ─────────────────── Mock 数据 ─────────────────── */

const STATION_NAMES = ['炒菜', '烧烤', '凉菜', '甜品', '蒸品', '面点'];

function randomInt(min: number, max: number): number {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function pickStatus(): StationData['status'] {
  const r = Math.random();
  if (r < 0.3) return 'busy';
  if (r < 0.7) return 'normal';
  return 'idle';
}

function generateMock(): StationStats {
  const stations: StationData[] = STATION_NAMES.map((name) => ({
    name,
    todayCount: randomInt(30, 200),
    avgMinutes: randomInt(3, 15),
    staffCount: randomInt(1, 6),
    status: pickStatus(),
  }));

  const dishNames = ['宫保鸡丁', '烤羊排', '凉拌木耳', '芒果布丁', '清蒸鲈鱼', '担担面',
    '麻辣香锅', '烤生蚝', '皮蛋豆腐', '双皮奶', '粉蒸肉', '炸酱面'];

  const now = Date.now();
  const recentDishes: RecentDish[] = Array.from({ length: 10 }, (_, i) => ({
    id: `d-${i}`,
    stationName: STATION_NAMES[randomInt(0, 5)],
    dishName: dishNames[randomInt(0, dishNames.length - 1)],
    finishedAt: new Date(now - i * 120_000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
    minutes: randomInt(2, 12),
  }));

  return { stations, recentDishes };
}

/* ─────────────────── 组件 ─────────────────── */

export function StationBoard() {
  const [data, setData] = useState<StationStats>(generateMock);
  const [progress, setProgress] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const progressRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(`${BASE}/api/v1/kds/station-stats`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json: { ok: boolean; data: StationStats } = await res.json();
      if (json.ok) {
        setData(json.data);
      } else {
        setData(generateMock());
      }
    } catch (_err: unknown) {
      setData(generateMock());
    }
    setProgress(0);
  }, []);

  useEffect(() => {
    fetchData();

    timerRef.current = setInterval(fetchData, REFRESH_INTERVAL);
    progressRef.current = setInterval(() => {
      setProgress((prev) => Math.min(prev + 100 / (REFRESH_INTERVAL / 1000), 100));
    }, 1000);

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (progressRef.current) clearInterval(progressRef.current);
    };
  }, [fetchData]);

  const { stations, recentDishes } = data;
  const totalCount = stations.reduce((s, st) => s + st.todayCount, 0);
  const fastestStation = stations.reduce((a, b) => (a.avgMinutes < b.avgMinutes ? a : b));
  const slowestStation = stations.reduce((a, b) => (a.avgMinutes > b.avgMinutes ? a : b));

  /* 高峰时段 — 简单用当前小时推断 */
  const hour = new Date().getHours();
  const peakLabel = hour >= 11 && hour <= 13 ? '午高峰' : hour >= 17 && hour <= 20 ? '晚高峰' : '非高峰';

  /* SVG 环形图数据 */
  const ringRadius = 60;
  const ringCircumference = 2 * Math.PI * ringRadius;
  let accOffset = 0;
  const ringSegments = stations.map((st, idx) => {
    const ratio = totalCount > 0 ? st.todayCount / totalCount : 1 / stations.length;
    const dash = ratio * ringCircumference;
    const offset = accOffset;
    accOffset += dash;
    return { ...st, dash, offset, color: STATION_COLORS[idx % STATION_COLORS.length] };
  });

  /* 跑马灯文本 */
  const marqueeText = recentDishes
    .map((d) => `${d.stationName}·${d.dishName} ${d.minutes}min (${d.finishedAt})`)
    .join('　　　');

  return (
    <div style={styles.root}>
      {/* ── 进度条 ── */}
      <div style={styles.progressBar}>
        <div style={{ ...styles.progressFill, width: `${progress}%` }} />
      </div>

      {/* ── 全场统计栏 ── */}
      <div style={styles.statsBar}>
        <span style={styles.statItem}>
          今日总出品 <span style={styles.statValue}>{totalCount}</span>
        </span>
        <span style={styles.statItem}>
          当前时段 <span style={styles.statValue}>{peakLabel}</span>
        </span>
        <span style={styles.statItem}>
          最快档口 <span style={{ ...styles.statValue, color: '#4ADE80' }}>
            {fastestStation.name}({fastestStation.avgMinutes}min)
          </span>
        </span>
        <span style={styles.statItem}>
          最慢档口 <span style={{ ...styles.statValue, color: '#FF4D4D' }}>
            {slowestStation.name}({slowestStation.avgMinutes}min)
          </span>
        </span>
      </div>

      {/* ── 主体区域：左侧卡片网格 + 右侧环形图 ── */}
      <div style={styles.mainArea}>
        {/* 卡片网格 2×3 */}
        <div style={styles.grid}>
          {stations.map((st, idx) => {
            const statusInfo = STATUS_MAP[st.status];
            return (
              <div key={st.name} style={styles.card}>
                <div style={styles.cardHeader}>
                  <span style={styles.stationName}>{st.name}</span>
                  <span style={{ ...styles.statusBadge, background: statusInfo.color + '22', color: statusInfo.color }}>
                    {statusInfo.emoji} {statusInfo.label}
                  </span>
                </div>
                <div style={styles.bigNumber}>
                  <span style={{ color: STATION_COLORS[idx % STATION_COLORS.length] }}>{st.todayCount}</span>
                  <span style={styles.bigNumberUnit}>份</span>
                </div>
                <div style={styles.cardMeta}>
                  <span>平均 {st.avgMinutes} min</span>
                  <span>在岗 {st.staffCount} 人</span>
                </div>
              </div>
            );
          })}
        </div>

        {/* SVG 环形图 */}
        <div style={styles.ringArea}>
          <div style={styles.ringTitle}>出品占比</div>
          <svg width="180" height="180" viewBox="0 0 180 180">
            {ringSegments.map((seg) => (
              <circle
                key={seg.name}
                cx="90"
                cy="90"
                r={ringRadius}
                fill="none"
                stroke={seg.color}
                strokeWidth="18"
                strokeDasharray={`${seg.dash} ${ringCircumference - seg.dash}`}
                strokeDashoffset={-seg.offset}
                transform="rotate(-90 90 90)"
              />
            ))}
            <text x="90" y="85" textAnchor="middle" fill="#FFFFFF" fontSize="20" fontWeight="bold">
              {totalCount}
            </text>
            <text x="90" y="108" textAnchor="middle" fill="#94A3B8" fontSize="16">
              总出品
            </text>
          </svg>
          {/* 图例 */}
          <div style={styles.legend}>
            {ringSegments.map((seg) => (
              <div key={seg.name} style={styles.legendItem}>
                <span style={{ ...styles.legendDot, background: seg.color }} />
                <span style={styles.legendLabel}>{seg.name}</span>
                <span style={styles.legendValue}>
                  {totalCount > 0 ? Math.round((seg.todayCount / totalCount) * 100) : 0}%
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── 底部跑马灯 ── */}
      <div style={styles.marqueeWrap}>
        <div style={styles.marqueeLabel}>最近出品</div>
        <div style={styles.marqueeTrack}>
          <div style={styles.marqueeContent}>
            {marqueeText}　　　{marqueeText}
          </div>
        </div>
      </div>

      {/* CSS @keyframes 注入 */}
      <style>{`
        @keyframes marquee {
          0%   { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
      `}</style>
    </div>
  );
}

export default StationBoard;

/* ─────────────────── 样式 ─────────────────── */

const styles: Record<string, React.CSSProperties> = {
  root: {
    position: 'fixed',
    inset: 0,
    background: '#0B1A20',
    color: '#E2E8F0',
    fontFamily: '-apple-system, "Noto Sans SC", sans-serif',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },

  /* 进度条 */
  progressBar: {
    height: 3,
    background: '#1E2D34',
    flexShrink: 0,
  },
  progressFill: {
    height: '100%',
    background: '#FF6B35',
    transition: 'width 1s linear',
  },

  /* 统计栏 */
  statsBar: {
    display: 'flex',
    justifyContent: 'space-around',
    alignItems: 'center',
    padding: '12px 24px',
    background: '#0F2229',
    flexShrink: 0,
    flexWrap: 'wrap' as const,
    gap: 8,
  },
  statItem: {
    fontSize: 18,
    color: '#94A3B8',
  },
  statValue: {
    fontSize: 22,
    fontWeight: 700,
    color: '#FF6B35',
    marginLeft: 6,
  },

  /* 主体区域 */
  mainArea: {
    flex: 1,
    display: 'flex',
    padding: '16px 24px',
    gap: 24,
    minHeight: 0,
  },

  /* 卡片网格 */
  grid: {
    flex: 1,
    display: 'grid',
    gridTemplateColumns: 'repeat(3, 1fr)',
    gridTemplateRows: 'repeat(2, 1fr)',
    gap: 16,
  },
  card: {
    background: '#112228',
    borderRadius: 12,
    padding: '20px 24px',
    display: 'flex',
    flexDirection: 'column' as const,
    justifyContent: 'space-between',
    minHeight: 0,
  },
  cardHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  stationName: {
    fontSize: 28,
    fontWeight: 700,
    color: '#FFFFFF',
  },
  statusBadge: {
    fontSize: 16,
    padding: '4px 12px',
    borderRadius: 20,
    fontWeight: 600,
    minWidth: 48,
    minHeight: 48,
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  bigNumber: {
    fontSize: 48,
    fontWeight: 800,
    lineHeight: 1.1,
  },
  bigNumberUnit: {
    fontSize: 20,
    color: '#94A3B8',
    marginLeft: 4,
  },
  cardMeta: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: 18,
    color: '#94A3B8',
  },

  /* 环形图区域 */
  ringArea: {
    width: 220,
    flexShrink: 0,
    display: 'flex',
    flexDirection: 'column' as const,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
  },
  ringTitle: {
    fontSize: 20,
    fontWeight: 600,
    color: '#CBD5E1',
  },
  legend: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 6,
    width: '100%',
  },
  legendItem: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    fontSize: 16,
  },
  legendDot: {
    width: 10,
    height: 10,
    borderRadius: '50%',
    flexShrink: 0,
  },
  legendLabel: {
    color: '#CBD5E1',
    flex: 1,
  },
  legendValue: {
    color: '#94A3B8',
    fontWeight: 600,
  },

  /* 跑马灯 */
  marqueeWrap: {
    display: 'flex',
    alignItems: 'center',
    height: 48,
    background: '#0F2229',
    flexShrink: 0,
    overflow: 'hidden',
  },
  marqueeLabel: {
    fontSize: 16,
    fontWeight: 700,
    color: '#FF6B35',
    padding: '0 16px',
    flexShrink: 0,
    whiteSpace: 'nowrap' as const,
  },
  marqueeTrack: {
    flex: 1,
    overflow: 'hidden',
  },
  marqueeContent: {
    display: 'inline-block',
    whiteSpace: 'nowrap' as const,
    fontSize: 16,
    color: '#CBD5E1',
    animation: 'marquee 30s linear infinite',
  },
};
