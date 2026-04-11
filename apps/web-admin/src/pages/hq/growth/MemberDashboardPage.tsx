/**
 * 会员驾驶舱 — 总部查看会员整体经营数据
 * 功能: KPI卡片 + RFM饼图 + 生命周期漏斗 + 30天趋势 + 渠道来源
 * API: /api/v1/member/dashboard
 */
import { useState, useEffect, useCallback } from 'react';
import { Card, Row, Col, Spin, Tooltip, Empty } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import {
  fetchMemberDashboard,
  type MemberDashboardData,
  type RFMDistItem,
} from '../../../api/memberGrowthApi';

// ---------- 工具函数 ----------
const fmtYuan = (fen: number) => `¥${(fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`;
const fmtPct = (v: number) => `${(v * 100).toFixed(1)}%`;
const fmtChange = (v: number) => {
  const pct = (v * 100).toFixed(1);
  return v >= 0 ? `+${pct}%` : `${pct}%`;
};

const COLOR = {
  primary: '#FF6B35',
  success: '#0F6E56',
  warning: '#BA7517',
  error: '#A32D2D',
  info: '#185FA5',
};

// ---------- KPI 卡片定义 ----------
function buildKPICards(d: MemberDashboardData) {
  return [
    {
      title: '总会员数',
      value: d.total_members.toLocaleString(),
      sub: `今日新增 ${d.daily_new}`,
      color: COLOR.primary,
      up: d.daily_new > 0,
    },
    {
      title: '活跃会员（30天）',
      value: d.active_members.toLocaleString(),
      sub: `活跃率 ${fmtPct(d.active_rate)}`,
      color: COLOR.success,
      up: d.active_rate > 0.3,
    },
    {
      title: '储值余额',
      value: fmtYuan(d.stored_value_total_fen),
      sub: `本月充值 ${fmtYuan(d.monthly_recharge_fen)}`,
      color: COLOR.warning,
      up: d.monthly_recharge_fen > 0,
    },
    {
      title: '平均客单价',
      value: fmtYuan(d.avg_ticket_fen),
      sub: `环比 ${fmtChange(d.avg_ticket_change)}`,
      color: COLOR.info,
      up: d.avg_ticket_change >= 0,
    },
    {
      title: '复购率',
      value: fmtPct(d.repurchase_rate),
      sub: `环比 ${fmtChange(d.repurchase_change)}`,
      color: COLOR.success,
      up: d.repurchase_change >= 0,
    },
    {
      title: '会员消费占比',
      value: fmtPct(d.member_revenue_ratio),
      sub: `环比 ${fmtChange(d.member_revenue_change)}`,
      color: COLOR.primary,
      up: d.member_revenue_change >= 0,
    },
  ];
}

// ---------- SVG 饼图组件 ----------
function RFMPieChart({
  data,
  onSelect,
  selected,
}: {
  data: RFMDistItem[];
  onSelect: (item: RFMDistItem | null) => void;
  selected: string | null;
}) {
  const total = data.reduce((s, d) => s + d.count, 0) || 1;
  const size = 260;
  const cx = size / 2;
  const cy = size / 2;
  const r = 100;

  let cumAngle = -Math.PI / 2;
  const slices = data.map((item) => {
    const angle = (item.count / total) * Math.PI * 2;
    const startAngle = cumAngle;
    cumAngle += angle;
    const endAngle = cumAngle;

    const x1 = cx + r * Math.cos(startAngle);
    const y1 = cy + r * Math.sin(startAngle);
    const x2 = cx + r * Math.cos(endAngle);
    const y2 = cy + r * Math.sin(endAngle);
    const largeArc = angle > Math.PI ? 1 : 0;

    const path = `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2} Z`;

    const midAngle = startAngle + angle / 2;
    const labelR = r * 0.65;
    const lx = cx + labelR * Math.cos(midAngle);
    const ly = cy + labelR * Math.sin(midAngle);

    return { ...item, path, lx, ly, pct: ((item.count / total) * 100).toFixed(1) };
  });

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
      <svg width={size} height={size} style={{ flexShrink: 0 }}>
        {slices.map((s) => (
          <g key={s.level}>
            <Tooltip title={`${s.label}: ${s.count}人 (${s.pct}%)`}>
              <path
                d={s.path}
                fill={s.color}
                opacity={selected && selected !== s.level ? 0.4 : 0.85}
                stroke="#fff"
                strokeWidth={1.5}
                style={{ cursor: 'pointer', transition: 'opacity 0.2s' }}
                onClick={() => onSelect(selected === s.level ? null : s)}
              />
            </Tooltip>
            {parseFloat(s.pct) > 5 && (
              <text
                x={s.lx}
                y={s.ly}
                textAnchor="middle"
                dominantBaseline="central"
                fill="#fff"
                fontSize={11}
                fontWeight={600}
                style={{ pointerEvents: 'none' }}
              >
                {s.pct}%
              </text>
            )}
          </g>
        ))}
      </svg>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {data.map((item) => (
          <div
            key={item.level}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              cursor: 'pointer',
              opacity: selected && selected !== item.level ? 0.5 : 1,
              transition: 'opacity 0.2s',
            }}
            onClick={() => onSelect(selected === item.level ? null : item)}
          >
            <span
              style={{
                width: 10,
                height: 10,
                borderRadius: 2,
                background: item.color,
                flexShrink: 0,
              }}
            />
            <span style={{ fontSize: 13, color: '#333', whiteSpace: 'nowrap' }}>
              {item.label}
            </span>
            <span style={{ fontSize: 12, color: '#999' }}>
              {item.count.toLocaleString()}人
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------- SVG 折线图组件 ----------
function TrendLineChart({
  data,
}: {
  data: MemberDashboardData['trend_30d'];
}) {
  if (data.length === 0) return <Empty description="暂无趋势数据" />;

  const W = 560;
  const H = 220;
  const PAD = { top: 20, right: 20, bottom: 40, left: 50 };
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;

  const maxNew = Math.max(...data.map((d) => d.new_members), 1);
  const maxActive = Math.max(...data.map((d) => d.active), 1);
  const maxRecharge = Math.max(...data.map((d) => d.recharge_fen / 100), 1);
  const globalMax = Math.max(maxNew, maxActive, maxRecharge);

  const xStep = data.length > 1 ? innerW / (data.length - 1) : 0;

  const buildLine = (values: number[], color: string) => {
    const points = values.map((v, i) => {
      const x = PAD.left + i * xStep;
      const y = PAD.top + innerH - (v / globalMax) * innerH;
      return `${x},${y}`;
    });
    return { d: `M ${points.join(' L ')}`, color };
  };

  const lines = [
    buildLine(data.map((d) => d.new_members), COLOR.primary),
    buildLine(data.map((d) => d.active), COLOR.success),
    buildLine(data.map((d) => d.recharge_fen / 100), COLOR.warning),
  ];

  const labelNames = ['新增会员', '活跃会员', '储值金额(元)'];
  const labelColors = [COLOR.primary, COLOR.success, COLOR.warning];

  // X轴标签：每隔5天显示
  const xLabels = data
    .map((d, i) => ({ label: d.date.slice(5), i }))
    .filter((_, i) => i % 5 === 0 || i === data.length - 1);

  return (
    <div>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto' }}>
        {/* 网格线 */}
        {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
          const y = PAD.top + innerH - ratio * innerH;
          return (
            <g key={ratio}>
              <line x1={PAD.left} y1={y} x2={W - PAD.right} y2={y} stroke="#f0f0f0" />
              <text x={PAD.left - 6} y={y + 4} textAnchor="end" fill="#999" fontSize={10}>
                {Math.round(globalMax * ratio)}
              </text>
            </g>
          );
        })}
        {/* 折线 */}
        {lines.map((l, i) => (
          <path key={i} d={l.d} fill="none" stroke={l.color} strokeWidth={2} />
        ))}
        {/* X轴标签 */}
        {xLabels.map(({ label, i }) => (
          <text
            key={i}
            x={PAD.left + i * xStep}
            y={H - 8}
            textAnchor="middle"
            fill="#999"
            fontSize={10}
          >
            {label}
          </text>
        ))}
      </svg>
      {/* 图例 */}
      <div style={{ display: 'flex', gap: 16, justifyContent: 'center', marginTop: 4 }}>
        {labelNames.map((name, i) => (
          <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span
              style={{
                width: 16,
                height: 3,
                background: labelColors[i],
                borderRadius: 2,
              }}
            />
            <span style={{ fontSize: 12, color: '#666' }}>{name}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------- 主组件 ----------
export function MemberDashboardPage() {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<MemberDashboardData | null>(null);
  const [selectedRFM, setSelectedRFM] = useState<RFMDistItem | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchMemberDashboard();
      setData(res);
    } catch {
      // 保持空状态
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const kpiCards = data ? buildKPICards(data) : [];

  return (
    <div style={{ padding: 24 }}>
      {/* 标题 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ margin: 0, fontSize: 20, fontWeight: 600 }}>会员驾驶舱</h2>
        <button
          onClick={loadData}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            padding: '6px 16px',
            borderRadius: 6,
            border: `1px solid ${COLOR.primary}`,
            background: 'transparent',
            color: COLOR.primary,
            cursor: 'pointer',
            fontSize: 13,
            fontWeight: 500,
          }}
        >
          <ReloadOutlined /> 刷新
        </button>
      </div>

      <Spin spinning={loading}>
        {/* 1. KPI 卡片 */}
        <Row gutter={[12, 12]} style={{ marginBottom: 20 }}>
          {(kpiCards.length > 0 ? kpiCards : Array.from({ length: 6 }, (_, i) => ({
            title: '',
            value: '--',
            sub: '',
            color: '#e0e0e0',
            up: true,
            _empty: true,
            key: i,
          }))).map((kpi, i) => (
            <Col span={4} key={kpi.title || i}>
              <Card
                size="small"
                style={{
                  borderTop: `3px solid ${kpi.color}`,
                  minHeight: 100,
                }}
                bodyStyle={{ padding: '12px 16px' }}
              >
                <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>{kpi.title}</div>
                <div style={{ fontSize: 24, fontWeight: 700, color: '#2C2C2A' }}>{kpi.value}</div>
                {kpi.sub && (
                  <div
                    style={{
                      fontSize: 12,
                      marginTop: 4,
                      color: kpi.up ? COLOR.success : COLOR.error,
                    }}
                  >
                    {kpi.up ? '\u2191' : '\u2193'} {kpi.sub}
                  </div>
                )}
              </Card>
            </Col>
          ))}
        </Row>

        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          {/* 2. RFM 分层饼图 */}
          <Col span={12}>
            <Card
              title="RFM 会员分层"
              size="small"
              bodyStyle={{ padding: 16 }}
            >
              {data?.rfm_distribution && data.rfm_distribution.length > 0 ? (
                <>
                  <RFMPieChart
                    data={data.rfm_distribution}
                    onSelect={(item) => setSelectedRFM(item)}
                    selected={selectedRFM?.level ?? null}
                  />
                  {selectedRFM && (
                    <div
                      style={{
                        marginTop: 12,
                        padding: '8px 12px',
                        borderRadius: 6,
                        background: '#F8F7F5',
                        fontSize: 13,
                      }}
                    >
                      <strong>{selectedRFM.label}</strong>：
                      {selectedRFM.count.toLocaleString()} 人，
                      占比{' '}
                      {(
                        (selectedRFM.count /
                          (data.rfm_distribution.reduce((s, d) => s + d.count, 0) || 1)) *
                        100
                      ).toFixed(1)}
                      %
                    </div>
                  )}
                </>
              ) : (
                <Empty description="暂无 RFM 分层数据" />
              )}
            </Card>
          </Col>

          {/* 3. 生命周期漏斗 */}
          <Col span={12}>
            <Card
              title="会员生命周期漏斗"
              size="small"
              bodyStyle={{ padding: 16 }}
            >
              {data?.lifecycle && data.lifecycle.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {data.lifecycle.map((step, i) => {
                    const maxCount = data.lifecycle[0]?.count ?? 1;
                    const widthPct = Math.max((step.count / maxCount) * 100, 15);
                    const stageColors = [
                      COLOR.primary,
                      COLOR.info,
                      COLOR.success,
                      COLOR.warning,
                      '#999',
                      COLOR.error,
                    ];
                    const barColor = stageColors[i % stageColors.length];
                    return (
                      <div key={step.stage}>
                        <div
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            marginBottom: 4,
                          }}
                        >
                          <span style={{ fontSize: 13, color: '#333' }}>{step.stage}</span>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <span style={{ fontSize: 14, fontWeight: 600, color: '#2C2C2A' }}>
                              {step.count.toLocaleString()}人
                            </span>
                            {i > 0 && (
                              <span
                                style={{
                                  fontSize: 10,
                                  padding: '1px 6px',
                                  borderRadius: 4,
                                  background: `${COLOR.info}15`,
                                  color: COLOR.info,
                                  fontWeight: 600,
                                }}
                              >
                                转化 {(step.conversion_rate * 100).toFixed(1)}%
                              </span>
                            )}
                          </div>
                        </div>
                        <div
                          style={{
                            height: 22,
                            borderRadius: 4,
                            background: '#F0F0F0',
                            overflow: 'hidden',
                            display: 'flex',
                            justifyContent: 'center',
                          }}
                        >
                          <div
                            style={{
                              width: `${widthPct}%`,
                              height: '100%',
                              borderRadius: 4,
                              background: barColor,
                              transition: 'width 0.5s ease',
                            }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <Empty description="暂无生命周期数据" />
              )}
            </Card>
          </Col>
        </Row>

        <Row gutter={[16, 16]}>
          {/* 4. 近30天趋势 */}
          <Col span={16}>
            <Card
              title="近30天趋势"
              size="small"
              bodyStyle={{ padding: 16 }}
            >
              {data?.trend_30d && data.trend_30d.length > 0 ? (
                <TrendLineChart data={data.trend_30d} />
              ) : (
                <Empty description="暂无趋势数据" />
              )}
            </Card>
          </Col>

          {/* 5. 渠道来源分布 */}
          <Col span={8}>
            <Card
              title="渠道来源分布"
              size="small"
              bodyStyle={{ padding: 16 }}
            >
              {data?.channel_sources && data.channel_sources.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {data.channel_sources.map((ch) => {
                    const channelColors: Record<string, string> = {
                      小程序: COLOR.success,
                      堂食注册: COLOR.primary,
                      企微: COLOR.info,
                      抖音: '#222',
                      美团: '#FFD100',
                    };
                    const barColor = channelColors[ch.channel] ?? COLOR.info;
                    return (
                      <div key={ch.channel}>
                        <div
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            marginBottom: 4,
                          }}
                        >
                          <span style={{ fontSize: 13, color: '#333' }}>{ch.channel}</span>
                          <span style={{ fontSize: 12, color: '#999' }}>
                            {ch.count.toLocaleString()}人（{(ch.ratio * 100).toFixed(1)}%）
                          </span>
                        </div>
                        <div
                          style={{
                            height: 16,
                            borderRadius: 4,
                            background: '#F0F0F0',
                            overflow: 'hidden',
                          }}
                        >
                          <div
                            style={{
                              width: `${ch.ratio * 100}%`,
                              height: '100%',
                              borderRadius: 4,
                              background: barColor,
                              transition: 'width 0.5s ease',
                            }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <Empty description="暂无渠道数据" />
              )}
            </Card>
          </Col>
        </Row>
      </Spin>
    </div>
  );
}
