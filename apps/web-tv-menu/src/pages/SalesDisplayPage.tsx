/**
 * 营业数据展示屏
 * 布局：1920x1080，全屏无交互，纯展示
 * 顶部品牌栏 + 左侧核心指标/热销TOP5 + 右侧图表/滚动订单 + 底部跑马灯
 * 60秒自动刷新
 */
import { useState, useEffect, useCallback, useRef, type CSSProperties } from 'react';

/* ======================== 类型 ======================== */
interface SalesOverview {
  revenue: number;
  revenue_change: number; // 环比百分比，正数为增长
  order_count: number;
  avg_ticket: number;
  turnover_rate: number; // 翻台率
}

interface TopDish {
  rank: number;
  name: string;
  sold: number;
}

interface PaymentShare {
  method: string;
  percent: number;
  color: string;
}

interface HourlyRevenue {
  hour: number;
  amount: number;
}

interface RecentOrder {
  id: string;
  time: string;
  items: string;
  amount: number;
}

interface ReviewSnippet {
  text: string;
}

interface SalesData {
  store_name: string;
  overview: SalesOverview;
  top_dishes: TopDish[];
  payment_shares: PaymentShare[];
  hourly_revenue: HourlyRevenue[];
  recent_orders: RecentOrder[];
  reviews: ReviewSnippet[];
}

/* ======================== Mock数据 ======================== */
const MOCK_DATA: SalesData = {
  store_name: '徐记海鲜 \u00b7 长沙总店',
  overview: {
    revenue: 68520,
    revenue_change: 12.5,
    order_count: 186,
    avg_ticket: 368,
    turnover_rate: 2.8,
  },
  top_dishes: [
    { rank: 1, name: '蒜蓉粉丝蒸扇贝', sold: 62 },
    { rank: 2, name: '清蒸石斑鱼', sold: 55 },
    { rank: 3, name: '避风塘炒蟹', sold: 48 },
    { rank: 4, name: '白灼基围虾', sold: 41 },
    { rank: 5, name: '椒盐皮皮虾', sold: 37 },
  ],
  payment_shares: [
    { method: '微信支付', percent: 45, color: '#07C160' },
    { method: '支付宝', percent: 30, color: '#1677FF' },
    { method: '现金', percent: 10, color: '#FFD700' },
    { method: '银行卡', percent: 10, color: '#C0C0C0' },
    { method: '会员余额', percent: 5, color: '#FF6B35' },
  ],
  hourly_revenue: [
    { hour: 10, amount: 1200 },
    { hour: 11, amount: 8500 },
    { hour: 12, amount: 18200 },
    { hour: 13, amount: 12800 },
    { hour: 14, amount: 4500 },
    { hour: 15, amount: 2100 },
    { hour: 16, amount: 3200 },
    { hour: 17, amount: 6800 },
    { hour: 18, amount: 15600 },
    { hour: 19, amount: 19200 },
    { hour: 20, amount: 14500 },
    { hour: 21, amount: 8200 },
  ],
  recent_orders: [
    { id: 'T20260402-186', time: '20:35', items: '清蒸石斑鱼 等3道', amount: 528 },
    { id: 'T20260402-185', time: '20:32', items: '蒜蓉扇贝 等5道', amount: 892 },
    { id: 'T20260402-184', time: '20:28', items: '避风塘炒蟹 等2道', amount: 368 },
    { id: 'T20260402-183', time: '20:25', items: '白灼基围虾 等4道', amount: 656 },
    { id: 'T20260402-182', time: '20:21', items: '椒盐皮皮虾 等3道', amount: 482 },
    { id: 'T20260402-181', time: '20:18', items: '龙虾刺身拼盘 等6道', amount: 1280 },
    { id: 'T20260402-180', time: '20:14', items: '葱姜焗花蟹 等2道', amount: 398 },
    { id: 'T20260402-179', time: '20:10', items: '蒸汽海鲜锅 等4道', amount: 768 },
  ],
  reviews: [
    { text: '"石斑鱼超级新鲜，肉质嫩滑！" \u2014\u2014 微信用户' },
    { text: '"服务态度很好，上菜速度也快" \u2014\u2014 大众点评' },
    { text: '"环境优雅，适合家庭聚餐" \u2014\u2014 美团用户' },
    { text: '"扇贝个头很大，蒜蓉调味恰到好处" \u2014\u2014 微信用户' },
    { text: '"第三次来了，每次都不失望" \u2014\u2014 会员用户' },
  ],
};

/* ======================== API ======================== */
async function fetchSalesData(storeId = 'store-001'): Promise<SalesData> {
  const res = await fetch(`/api/v1/analytics/sales/today?store_id=${storeId}`, {
    headers: { 'X-Tenant-ID': 'demo-tenant' },
  });
  if (!res.ok) throw new Error('API error');
  const json = await res.json();
  if (!json.ok) throw new Error('API error');
  return json.data as SalesData;
}

/* ======================== SVG环形图 ======================== */
function DonutChart({ shares }: { shares: PaymentShare[] }) {
  const size = 220;
  const cx = size / 2;
  const cy = size / 2;
  const outerR = 95;
  const innerR = 60;
  let cumulative = 0;

  const arcs = shares.map((s) => {
    const startAngle = cumulative * 3.6 * (Math.PI / 180);
    cumulative += s.percent;
    const endAngle = cumulative * 3.6 * (Math.PI / 180);
    const largeArc = s.percent > 50 ? 1 : 0;
    const x1 = cx + outerR * Math.sin(startAngle);
    const y1 = cy - outerR * Math.cos(startAngle);
    const x2 = cx + outerR * Math.sin(endAngle);
    const y2 = cy - outerR * Math.cos(endAngle);
    const x3 = cx + innerR * Math.sin(endAngle);
    const y3 = cy - innerR * Math.cos(endAngle);
    const x4 = cx + innerR * Math.sin(startAngle);
    const y4 = cy - innerR * Math.cos(startAngle);
    const d = [
      `M ${x1} ${y1}`,
      `A ${outerR} ${outerR} 0 ${largeArc} 1 ${x2} ${y2}`,
      `L ${x3} ${y3}`,
      `A ${innerR} ${innerR} 0 ${largeArc} 0 ${x4} ${y4}`,
      'Z',
    ].join(' ');
    return { d, color: s.color, method: s.method, percent: s.percent };
  });

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        {arcs.map((arc, i) => (
          <path key={i} d={arc.d} fill={arc.color} opacity={0.85} />
        ))}
      </svg>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {shares.map((s, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 18, color: '#ccc' }}>
            <div style={{ width: 12, height: 12, borderRadius: 2, background: s.color, flexShrink: 0 }} />
            <span>{s.method}</span>
            <span style={{ color: '#999', marginLeft: 4 }}>{s.percent}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ======================== SVG折线图 ======================== */
function LineChart({ data }: { data: HourlyRevenue[] }) {
  const W = 440;
  const H = 180;
  const padL = 50;
  const padR = 10;
  const padT = 10;
  const padB = 30;
  const chartW = W - padL - padR;
  const chartH = H - padT - padB;

  if (data.length === 0) return null;
  const maxAmt = Math.max(...data.map((d) => d.amount));
  const points = data.map((d, i) => {
    const x = padL + (i / (data.length - 1)) * chartW;
    const y = padT + chartH - (d.amount / maxAmt) * chartH;
    return { x, y, hour: d.hour, amount: d.amount };
  });

  const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ');
  const areaPath = linePath + ` L ${points[points.length - 1].x} ${padT + chartH} L ${points[0].x} ${padT + chartH} Z`;

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
      <defs>
        <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#FF6B35" stopOpacity={0.4} />
          <stop offset="100%" stopColor="#FF6B35" stopOpacity={0.02} />
        </linearGradient>
      </defs>
      {/* 网格线 */}
      {[0, 0.25, 0.5, 0.75, 1].map((r, i) => {
        const y = padT + chartH * (1 - r);
        return (
          <line key={i} x1={padL} y1={y} x2={padL + chartW} y2={y} stroke="#333" strokeWidth={0.5} />
        );
      })}
      {/* Y轴标签 */}
      {[0, 0.5, 1].map((r, i) => {
        const y = padT + chartH * (1 - r);
        const val = Math.round(maxAmt * r / 1000);
        return (
          <text key={i} x={padL - 8} y={y + 4} textAnchor="end" fill="#777" fontSize={12}>{val}k</text>
        );
      })}
      {/* 面积 */}
      <path d={areaPath} fill="url(#areaGrad)" />
      {/* 折线 */}
      <path d={linePath} fill="none" stroke="#FF6B35" strokeWidth={2.5} strokeLinejoin="round" />
      {/* 点 */}
      {points.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r={3} fill="#FF6B35" />
      ))}
      {/* X轴标签 */}
      {points.filter((_, i) => i % 2 === 0).map((p, i) => (
        <text key={i} x={p.x} y={H - 4} textAnchor="middle" fill="#777" fontSize={12}>{p.hour}:00</text>
      ))}
    </svg>
  );
}

/* ======================== 主组件 ======================== */
export default function SalesDisplayPage() {
  const [data, setData] = useState<SalesData>(MOCK_DATA);
  const [currentTime, setCurrentTime] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);

  /* 实时时钟 */
  useEffect(() => {
    const update = () => {
      setCurrentTime(new Date().toLocaleTimeString('zh-CN', {
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
      }));
    };
    update();
    const t = setInterval(update, 1000);
    return () => clearInterval(t);
  }, []);

  /* 60秒刷新 */
  const loadData = useCallback(async () => {
    try {
      const fresh = await fetchSalesData();
      setData(fresh);
    } catch {
      // 静默降级，保留上次数据
    }
  }, []);

  useEffect(() => {
    loadData();
    const t = setInterval(loadData, 60_000);
    return () => clearInterval(t);
  }, [loadData]);

  /* 跑马灯CSS注入 */
  useEffect(() => {
    const styleId = 'sales-marquee-style';
    if (!document.getElementById(styleId)) {
      const style = document.createElement('style');
      style.id = styleId;
      style.textContent = `
        @keyframes sales-scroll-up {
          0% { transform: translateY(0); }
          100% { transform: translateY(-50%); }
        }
        @keyframes sales-marquee {
          0% { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
      `;
      document.head.appendChild(style);
    }
    return () => {
      const el = document.getElementById(styleId);
      if (el) el.remove();
    };
  }, []);

  /* 排名颜色 */
  const rankColor = (rank: number): string => {
    if (rank === 1) return '#FFD700';
    if (rank === 2) return '#C0C0C0';
    if (rank === 3) return '#CD7F32';
    return '#888';
  };

  const changeArrow = data.overview.revenue_change >= 0 ? '\u25B2' : '\u25BC';
  const changeColor = data.overview.revenue_change >= 0 ? '#00CC66' : '#FF4444';

  /* ===== 样式 ===== */
  const rootStyle: CSSProperties = {
    width: 1920,
    height: 1080,
    overflow: 'hidden',
    background: 'linear-gradient(180deg, #0d0500 0%, #1a0a00 40%, #0d0500 100%)',
    display: 'flex',
    flexDirection: 'column',
    fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif',
    cursor: 'none',
    userSelect: 'none',
  };

  const headerStyle: CSSProperties = {
    flexShrink: 0,
    height: 80,
    background: 'linear-gradient(90deg, #3d1200 0%, #2a0e00 50%, #3d1200 100%)',
    borderBottom: '2px solid #FF6B35',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '0 60px',
  };

  const mainStyle: CSSProperties = {
    flex: 1,
    display: 'flex',
    overflow: 'hidden',
  };

  const leftStyle: CSSProperties = {
    width: '60%',
    display: 'flex',
    flexDirection: 'column',
    padding: '30px 40px',
    gap: 24,
    borderRight: '2px solid #2a1500',
  };

  const rightStyle: CSSProperties = {
    width: '40%',
    display: 'flex',
    flexDirection: 'column',
    padding: '24px 30px',
    gap: 20,
    overflow: 'hidden',
  };

  const footerStyle: CSSProperties = {
    flexShrink: 0,
    height: 40,
    background: '#2d1500',
    borderTop: '2px solid #3d2000',
    display: 'flex',
    alignItems: 'center',
    overflow: 'hidden',
    whiteSpace: 'nowrap',
  };

  const cardStyle: CSSProperties = {
    background: 'rgba(255,255,255,0.04)',
    border: '1px solid #3d2000',
    borderRadius: 12,
    padding: '20px 28px',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 6,
    flex: 1,
  };

  const sectionTitleStyle: CSSProperties = {
    fontSize: 20,
    fontWeight: 700,
    color: '#c8a882',
    letterSpacing: 4,
    marginBottom: 8,
  };

  const marqueeText = data.reviews.map((r) => r.text).join('    \u2605    ');
  const doubledMarquee = marqueeText + '    \u2605    ' + marqueeText;

  return (
    <div style={rootStyle}>
      {/* ===== 顶部品牌栏 ===== */}
      <div style={headerStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
          {/* Logo占位 */}
          <div style={{
            width: 48, height: 48, borderRadius: 8,
            background: 'linear-gradient(135deg, #FF6B35, #FF8555)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 24, fontWeight: 900, color: '#fff',
          }}>TX</div>
          <div style={{ fontSize: 32, fontWeight: 800, color: '#fff', letterSpacing: 4 }}>
            {data.store_name}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 40 }}>
          <div style={{ fontSize: 24, fontWeight: 700, color: '#FF6B35', letterSpacing: 2 }}>
            今日营业数据
          </div>
          <div style={{
            fontSize: 28, fontWeight: 600, color: '#c8a882',
            fontVariantNumeric: 'tabular-nums', letterSpacing: 2,
          }}>
            {currentTime}
          </div>
        </div>
      </div>

      {/* ===== 主区域 ===== */}
      <div style={mainStyle}>
        {/* 左侧 60% */}
        <div style={leftStyle}>
          {/* 今日营收 大字 */}
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 16 }}>
            <span style={{ fontSize: 24, color: '#9e7a55', fontWeight: 600 }}>今日营收</span>
            <span style={{
              fontSize: 120, fontWeight: 900, color: '#FF6B35', lineHeight: 1,
              fontVariantNumeric: 'tabular-nums',
              textShadow: '0 0 40px rgba(255, 107, 53, 0.5)',
            }}>
              {'\u00A5'}{data.overview.revenue.toLocaleString()}
            </span>
            <span style={{ fontSize: 28, fontWeight: 700, color: changeColor }}>
              {changeArrow} {Math.abs(data.overview.revenue_change)}%
            </span>
          </div>

          {/* 三张指标卡 */}
          <div style={{ display: 'flex', gap: 20 }}>
            <div style={cardStyle}>
              <div style={{ fontSize: 16, color: '#9e7a55', letterSpacing: 2 }}>订单数</div>
              <div style={{ fontSize: 56, fontWeight: 900, color: '#fff', fontVariantNumeric: 'tabular-nums' }}>
                {data.overview.order_count}
              </div>
              <div style={{ fontSize: 14, color: '#666' }}>笔</div>
            </div>
            <div style={cardStyle}>
              <div style={{ fontSize: 16, color: '#9e7a55', letterSpacing: 2 }}>客单价</div>
              <div style={{ fontSize: 56, fontWeight: 900, color: '#fff', fontVariantNumeric: 'tabular-nums' }}>
                {'\u00A5'}{data.overview.avg_ticket}
              </div>
              <div style={{ fontSize: 14, color: '#666' }}>元/笔</div>
            </div>
            <div style={cardStyle}>
              <div style={{ fontSize: 16, color: '#9e7a55', letterSpacing: 2 }}>翻台率</div>
              <div style={{ fontSize: 56, fontWeight: 900, color: '#fff', fontVariantNumeric: 'tabular-nums' }}>
                {data.overview.turnover_rate}
              </div>
              <div style={{ fontSize: 14, color: '#666' }}>次/桌</div>
            </div>
          </div>

          {/* 热销TOP5 */}
          <div style={{ flex: 1 }}>
            <div style={sectionTitleStyle}>热销 TOP 5</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {data.top_dishes.map((dish) => (
                <div key={dish.rank} style={{
                  display: 'flex', alignItems: 'center', gap: 16,
                  padding: '10px 20px', borderRadius: 8,
                  background: dish.rank <= 3 ? 'rgba(255,255,255,0.04)' : 'transparent',
                }}>
                  <div style={{
                    width: 40, height: 40, borderRadius: 20,
                    background: rankColor(dish.rank),
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 20, fontWeight: 900, color: dish.rank <= 3 ? '#1a0a00' : '#fff',
                    flexShrink: 0,
                  }}>
                    {dish.rank}
                  </div>
                  <div style={{ fontSize: 26, fontWeight: 600, color: '#fff', flex: 1 }}>
                    {dish.name}
                  </div>
                  <div style={{ fontSize: 24, fontWeight: 700, color: rankColor(dish.rank), fontVariantNumeric: 'tabular-nums' }}>
                    {dish.sold} 份
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* 右侧 40% */}
        <div style={rightStyle}>
          {/* 支付方式占比 */}
          <div>
            <div style={sectionTitleStyle}>支付方式占比</div>
            <DonutChart shares={data.payment_shares} />
          </div>

          {/* 逐小时营收趋势 */}
          <div>
            <div style={sectionTitleStyle}>逐小时营收趋势</div>
            <LineChart data={data.hourly_revenue} />
          </div>

          {/* 最近订单滚动 */}
          <div style={{ flex: 1, overflow: 'hidden' }}>
            <div style={sectionTitleStyle}>最近订单</div>
            <div style={{ height: '100%', overflow: 'hidden', position: 'relative' }}>
              <div
                ref={scrollRef}
                style={{
                  animation: 'sales-scroll-up 20s linear infinite',
                }}
              >
                {/* 复制两份实现无缝滚动 */}
                {[...data.recent_orders, ...data.recent_orders].map((order, i) => (
                  <div key={`${order.id}-${i}`} style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '8px 12px', borderBottom: '1px solid #2a1500',
                  }}>
                    <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                      <span style={{ fontSize: 14, color: '#666', fontVariantNumeric: 'tabular-nums' }}>{order.time}</span>
                      <span style={{ fontSize: 16, color: '#ccc' }}>{order.items}</span>
                    </div>
                    <span style={{ fontSize: 18, fontWeight: 700, color: '#FF6B35', fontVariantNumeric: 'tabular-nums' }}>
                      {'\u00A5'}{order.amount}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ===== 底部跑马灯 ===== */}
      <div style={footerStyle}>
        <div style={{
          display: 'inline-block',
          animation: 'sales-marquee 30s linear infinite',
          fontSize: 18,
          color: '#c8a882',
          letterSpacing: 2,
          paddingLeft: 1920,
        }}>
          {doubledMarquee}
        </div>
      </div>
    </div>
  );
}
