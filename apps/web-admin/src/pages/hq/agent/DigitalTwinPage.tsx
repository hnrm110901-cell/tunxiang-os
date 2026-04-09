/**
 * DigitalTwinPage — 门店数字孪生概念页
 *
 * 门店选择器 + 实时状态概览（桌态/厨房/库存/人员）
 * What-If 模拟面板 + 时间轴回放
 *
 * 纯 Mock 数据 + Ant Design 5.x + 纯 CSS 可视化
 */
import { useCallback, useMemo, useState } from 'react';
import {
  Button,
  Card,
  Col,
  InputNumber,
  Modal,
  Row,
  Select,
  Slider,
  Space,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import {
  ClockCircleOutlined,
  ExperimentOutlined,
  LeftOutlined,
  RightOutlined,
  ShopOutlined,
  ThunderboltOutlined,
  UserOutlined,
  WarningOutlined,
} from '@ant-design/icons';

const { Title, Text, Paragraph } = Typography;

// ─── Design Tokens ───
const C = {
  primary: '#FF6B35',
  success: '#0F6E56',
  warning: '#BA7517',
  danger: '#A32D2D',
  info: '#185FA5',
  navy: '#1E2A3A',
  bgPrimary: '#FFFFFF',
  bgSecondary: '#F8F7F5',
  bgTertiary: '#F0EDE6',
  textPrimary: '#2C2C2A',
  textSub: '#5F5E5A',
  textMuted: '#B4B2A9',
  border: '#E8E6E1',
};

// ─── 门店列表 ───
const STORES = [
  { id: 's001', name: '长沙芙蓉店', tables: 28, staff: 12 },
  { id: 's002', name: '长沙天心店', tables: 22, staff: 10 },
  { id: 's003', name: '株洲中心店', tables: 18, staff: 8 },
];

// ─── 桌态 ───
type TableStatus = 'empty' | 'occupied' | 'billing' | 'reserved';

interface TableInfo {
  id: string;
  name: string;
  status: TableStatus;
  guests?: number;
  duration?: number; // 分钟
  amount?: number;
}

function generateTables(count: number): TableInfo[] {
  const statuses: TableStatus[] = ['empty', 'occupied', 'billing', 'reserved'];
  const weights = [0.25, 0.45, 0.15, 0.15];
  const tables: TableInfo[] = [];
  for (let i = 1; i <= count; i++) {
    let r = Math.random(), cum = 0, status: TableStatus = 'empty';
    for (let j = 0; j < weights.length; j++) {
      cum += weights[j];
      if (r <= cum) { status = statuses[j]; break; }
    }
    tables.push({
      id: `t${i}`,
      name: `${String.fromCharCode(65 + Math.floor((i - 1) / 7))}${((i - 1) % 7) + 1}`,
      status,
      guests: status === 'occupied' || status === 'billing' ? Math.floor(Math.random() * 6) + 2 : undefined,
      duration: status === 'occupied' ? Math.floor(Math.random() * 90) + 10 : status === 'billing' ? Math.floor(Math.random() * 20) + 60 : undefined,
      amount: status === 'billing' ? Math.floor(Math.random() * 400) + 120 : status === 'occupied' ? Math.floor(Math.random() * 300) + 80 : undefined,
    });
  }
  return tables;
}

// ─── 厨房状态 ───
interface KitchenOrder {
  id: string;
  dish: string;
  table: string;
  status: 'cooking' | 'waiting' | 'overtime';
  elapsed: number; // 秒
  limit: number; // 秒
}

const MOCK_KITCHEN: KitchenOrder[] = [
  { id: 'k1', dish: '剁椒鱼头', table: 'A3', status: 'cooking', elapsed: 420, limit: 900 },
  { id: 'k2', dish: '蒜蓉龙虾', table: 'B2', status: 'cooking', elapsed: 180, limit: 600 },
  { id: 'k3', dish: '红烧肉', table: 'A5', status: 'waiting', elapsed: 0, limit: 720 },
  { id: 'k4', dish: '酸菜鱼', table: 'C1', status: 'waiting', elapsed: 0, limit: 600 },
  { id: 'k5', dish: '水煮牛肉', table: 'B4', status: 'overtime', elapsed: 960, limit: 900 },
  { id: 'k6', dish: '宫保鸡丁', table: 'A1', status: 'cooking', elapsed: 300, limit: 480 },
  { id: 'k7', dish: '清蒸鲈鱼', table: 'C3', status: 'waiting', elapsed: 0, limit: 720 },
  { id: 'k8', dish: '麻婆豆腐', table: 'B1', status: 'cooking', elapsed: 240, limit: 360 },
];

// ─── 库存 ───
interface InventoryItem {
  name: string;
  stock: number;
  safetyLine: number;
  unit: string;
  level: 'green' | 'yellow' | 'red';
}

const MOCK_INVENTORY: InventoryItem[] = [
  { name: '三文鱼', stock: 6, safetyLine: 15, unit: '份', level: 'red' },
  { name: '龙虾', stock: 12, safetyLine: 10, unit: '只', level: 'green' },
  { name: '鲈鱼', stock: 8, safetyLine: 8, unit: '条', level: 'yellow' },
  { name: '牛肉', stock: 4.5, safetyLine: 5, unit: 'kg', level: 'red' },
  { name: '鸡肉', stock: 15, safetyLine: 8, unit: 'kg', level: 'green' },
  { name: '皮皮虾', stock: 3, safetyLine: 10, unit: '份', level: 'red' },
  { name: '基围虾', stock: 20, safetyLine: 12, unit: '份', level: 'green' },
  { name: '花甲', stock: 9, safetyLine: 8, unit: 'kg', level: 'yellow' },
];

// ─── 人员 ───
interface StaffInfo {
  name: string;
  role: string;
  status: 'onDuty' | 'break' | 'absent';
}

const MOCK_STAFF: StaffInfo[] = [
  { name: '张师傅', role: '主厨', status: 'onDuty' },
  { name: '李师傅', role: '副厨', status: 'onDuty' },
  { name: '王师傅', role: '冷菜', status: 'onDuty' },
  { name: '赵洁', role: '收银', status: 'onDuty' },
  { name: '刘涛', role: '服务员', status: 'onDuty' },
  { name: '陈芳', role: '服务员', status: 'onDuty' },
  { name: '黄伟', role: '服务员', status: 'break' },
  { name: '周明', role: '传菜', status: 'onDuty' },
  { name: '吴丽', role: '服务员', status: 'onDuty' },
  { name: '孙强', role: '洗碗', status: 'onDuty' },
  { name: '马杰', role: '保洁', status: 'absent' },
  { name: '郑欣', role: '迎宾', status: 'onDuty' },
];

// ─── 时间轴快照 ───
interface TimeSnapshot {
  hour: string;
  occupancy: number; // 0-100
  kitchenLoad: number; // 0-100
  revenue: number;
  staffOnDuty: number;
  events: string[];
}

const TIMELINE: TimeSnapshot[] = [
  { hour: '09:00', occupancy: 5,  kitchenLoad: 10, revenue: 0,     staffOnDuty: 8,  events: ['开店准备'] },
  { hour: '10:00', occupancy: 10, kitchenLoad: 15, revenue: 680,   staffOnDuty: 10, events: ['早茶客开始入座'] },
  { hour: '11:00', occupancy: 45, kitchenLoad: 55, revenue: 3200,  staffOnDuty: 12, events: ['午餐高峰开始', '启动排队系统'] },
  { hour: '12:00', occupancy: 92, kitchenLoad: 95, revenue: 8600,  staffOnDuty: 12, events: ['满座', '排队28桌', '出餐调度Agent介入'] },
  { hour: '13:00', occupancy: 78, kitchenLoad: 80, revenue: 14200, staffOnDuty: 12, events: ['高峰回落', '龙虾库存预警'] },
  { hour: '14:00', occupancy: 35, kitchenLoad: 30, revenue: 16800, staffOnDuty: 10, events: ['午休轮换', '2名服务员轮休'] },
  { hour: '15:00', occupancy: 15, kitchenLoad: 12, revenue: 17400, staffOnDuty: 8,  events: ['下午茶时段'] },
  { hour: '16:00', occupancy: 20, kitchenLoad: 20, revenue: 18100, staffOnDuty: 8,  events: ['备料晚餐食材'] },
  { hour: '17:00', occupancy: 55, kitchenLoad: 60, revenue: 21500, staffOnDuty: 12, events: ['晚餐高峰开始', '全员到岗'] },
  { hour: '18:00', occupancy: 88, kitchenLoad: 90, revenue: 28300, staffOnDuty: 12, events: ['接近满座', '会员洞察Agent推送VIP到店提醒'] },
  { hour: '19:00', occupancy: 95, kitchenLoad: 98, revenue: 36400, staffOnDuty: 12, events: ['满座+排队15桌', '三文鱼售罄', '折扣守护Agent拦截1笔'] },
  { hour: '20:00', occupancy: 72, kitchenLoad: 70, revenue: 42100, staffOnDuty: 12, events: ['高峰回落', '日营收突破4万'] },
];

// ─── What-If 模拟 ───
interface SimScenario {
  id: string;
  label: string;
  icon: React.ReactNode;
  paramLabel: string;
  paramUnit: string;
  defaultParam: number;
  min: number;
  max: number;
  step: number;
  simulate: (param: number) => string[];
}

const SCENARIOS: SimScenario[] = [
  {
    id: 'traffic_surge',
    label: '客流量增加',
    icon: <UserOutlined />,
    paramLabel: '增长幅度',
    paramUnit: '%',
    defaultParam: 30,
    min: 10,
    max: 100,
    step: 5,
    simulate: (pct: number) => {
      const extraStaff = Math.ceil(pct / 15);
      const extraPrep = Math.ceil(pct * 1.2);
      return [
        `需要增加 ${extraStaff} 名服务人员`,
        `需要提前准备 ${extraPrep} 份半成品`,
        `预计等位时间增加 ${Math.ceil(pct * 0.5)} 分钟`,
        `建议提前 ${Math.ceil(pct / 10)} 小时备料`,
        pct >= 50 ? '建议启用临时排队叫号系统' : '当前排队系统可应对',
      ];
    },
  },
  {
    id: 'price_change',
    label: '原材料涨价',
    icon: <WarningOutlined />,
    paramLabel: '涨价幅度',
    paramUnit: '%',
    defaultParam: 10,
    min: 5,
    max: 50,
    step: 5,
    simulate: (pct: number) => {
      const marginDrop = (pct * 0.6).toFixed(1);
      const suggestRaise = (pct * 0.4).toFixed(1);
      return [
        `整体毛利率下降约 ${marginDrop}%`,
        `建议菜品售价上调 ${suggestRaise}%`,
        `受影响菜品：龙虾、三文鱼、牛肉等 ${Math.ceil(pct / 5)} 道菜`,
        pct >= 20 ? `建议暂时下架高成本低毛利菜品` : '当前菜单结构可维持',
        `月度成本增加约 \u00A5${(pct * 380).toLocaleString()}`,
      ];
    },
  },
];

// ─── 桌态颜色映射 ───
const TABLE_COLORS: Record<TableStatus, { bg: string; border: string; text: string; label: string }> = {
  empty:    { bg: `${C.success}15`, border: C.success, text: C.success, label: '空' },
  occupied: { bg: `${C.primary}15`, border: C.primary, text: C.primary, label: '用餐中' },
  billing:  { bg: `${C.warning}15`, border: C.warning, text: C.warning, label: '买单' },
  reserved: { bg: `${C.info}15`,    border: C.info,    text: C.info,    label: '预约' },
};

// ─── 主组件 ───
export default function DigitalTwinPage() {
  const [storeId, setStoreId] = useState(STORES[0].id);
  const [timelineIdx, setTimelineIdx] = useState(7); // 默认16:00
  const [simOpen, setSimOpen] = useState(false);
  const [simScenario, setSimScenario] = useState(SCENARIOS[0]);
  const [simParam, setSimParam] = useState(SCENARIOS[0].defaultParam);
  const [simResults, setSimResults] = useState<string[] | null>(null);

  const store = useMemo(() => STORES.find(s => s.id === storeId)!, [storeId]);
  const [tables] = useState(() => generateTables(28));
  const snapshot = TIMELINE[timelineIdx];

  const tableStats = useMemo(() => {
    const counts = { empty: 0, occupied: 0, billing: 0, reserved: 0 };
    tables.forEach(t => counts[t.status]++);
    return counts;
  }, [tables]);

  const staffStats = useMemo(() => {
    const counts = { onDuty: 0, break: 0, absent: 0 };
    MOCK_STAFF.forEach(s => counts[s.status]++);
    return counts;
  }, []);

  const handleSimulate = useCallback(() => {
    setSimResults(simScenario.simulate(simParam));
  }, [simScenario, simParam]);

  const handleScenarioChange = useCallback((id: string) => {
    const s = SCENARIOS.find(sc => sc.id === id)!;
    setSimScenario(s);
    setSimParam(s.defaultParam);
    setSimResults(null);
  }, []);

  return (
    <div style={{ padding: 24, background: C.bgSecondary, minHeight: '100vh' }}>
      {/* 标题 + 门店选择器 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <Title level={3} style={{ margin: 0, color: C.textPrimary }}>
            <ShopOutlined style={{ color: C.primary, marginRight: 8 }} />
            门店数字孪生
          </Title>
          <Text style={{ color: C.textSub }}>实时监控门店运营全貌，模拟经营决策</Text>
        </div>
        <Space>
          <Select
            value={storeId}
            onChange={setStoreId}
            style={{ width: 180 }}
            options={STORES.map(s => ({ value: s.id, label: s.name }))}
          />
          <Button type="primary" icon={<ExperimentOutlined />} onClick={() => setSimOpen(true)}
            style={{ background: C.info, borderColor: C.info }}>
            What-If 模拟
          </Button>
        </Space>
      </div>

      {/* ═══ 实时状态概览 ═══ */}
      <Row gutter={[16, 16]}>

        {/* ── 桌态矩阵 ── */}
        <Col xs={24} lg={14}>
          <Card
            title={<><ShopOutlined style={{ color: C.primary, marginRight: 6 }} />桌态矩阵</>}
            extra={
              <Space size={12}>
                {(Object.entries(TABLE_COLORS) as [TableStatus, typeof TABLE_COLORS['empty']][]).map(([k, v]) => (
                  <Space key={k} size={4}>
                    <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: v.border }} />
                    <Text style={{ fontSize: 12, color: C.textSub }}>{v.label} ({tableStats[k]})</Text>
                  </Space>
                ))}
              </Space>
            }
            style={{ borderRadius: 8, height: '100%' }}
            styles={{ body: { padding: 16 } }}
          >
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(7, 1fr)',
              gap: 8,
            }}>
              {tables.map(t => {
                const tc = TABLE_COLORS[t.status];
                return (
                  <Tooltip
                    key={t.id}
                    title={
                      <div>
                        <div>{t.name} - {tc.label}</div>
                        {t.guests && <div>{t.guests}人</div>}
                        {t.duration && <div>已{t.duration}分钟</div>}
                        {t.amount && <div>\u00A5{t.amount}</div>}
                      </div>
                    }
                  >
                    <div
                      style={{
                        aspectRatio: '1',
                        background: tc.bg,
                        border: `2px solid ${tc.border}`,
                        borderRadius: 8,
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        justifyContent: 'center',
                        cursor: 'pointer',
                        transition: 'transform 0.15s',
                        position: 'relative',
                        overflow: 'hidden',
                      }}
                      onMouseEnter={e => (e.currentTarget.style.transform = 'scale(1.05)')}
                      onMouseLeave={e => (e.currentTarget.style.transform = 'scale(1)')}
                    >
                      <Text style={{ fontSize: 13, fontWeight: 700, color: tc.text }}>{t.name}</Text>
                      {t.guests && (
                        <Text style={{ fontSize: 10, color: tc.text }}>{t.guests}人</Text>
                      )}
                      {t.duration && t.duration > 60 && (
                        <div style={{
                          position: 'absolute', top: 2, right: 2,
                          width: 6, height: 6, borderRadius: '50%',
                          background: C.warning,
                          animation: 'dtPulse 1.5s infinite',
                        }} />
                      )}
                    </div>
                  </Tooltip>
                );
              })}
            </div>
          </Card>
        </Col>

        {/* ── 右侧面板：厨房 + 库存 + 人员 ── */}
        <Col xs={24} lg={10}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* 厨房状态 */}
            <Card
              title={<><ThunderboltOutlined style={{ color: C.warning, marginRight: 6 }} />厨房状态</>}
              size="small"
              style={{ borderRadius: 8 }}
              styles={{ body: { padding: 12 } }}
            >
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {MOCK_KITCHEN.map(k => {
                  const pct = k.status === 'waiting' ? 0 : (k.elapsed / k.limit) * 100;
                  const barColor = k.status === 'overtime' ? C.danger : pct > 70 ? C.warning : C.success;
                  const statusLabel = k.status === 'cooking' ? '出品中' : k.status === 'waiting' ? '等待中' : '超时';
                  return (
                    <div key={k.id} style={{
                      display: 'flex', alignItems: 'center', gap: 8, padding: '4px 8px',
                      background: k.status === 'overtime' ? `${C.danger}08` : 'transparent',
                      borderRadius: 4, border: k.status === 'overtime' ? `1px solid ${C.danger}20` : '1px solid transparent',
                    }}>
                      <Text style={{ fontSize: 12, width: 70, color: C.textPrimary, fontWeight: 500 }}>{k.dish}</Text>
                      <Tag style={{
                        fontSize: 10, lineHeight: '18px', margin: 0,
                        color: barColor, borderColor: `${barColor}40`, background: `${barColor}10`,
                      }}>{statusLabel}</Tag>
                      <div style={{ flex: 1, height: 6, background: C.bgTertiary, borderRadius: 3, overflow: 'hidden' }}>
                        <div style={{
                          width: `${Math.min(pct, 100)}%`,
                          height: '100%',
                          background: barColor,
                          borderRadius: 3,
                          transition: 'width 0.3s',
                          animation: k.status === 'overtime' ? 'dtPulse 1.5s infinite' : undefined,
                        }} />
                      </div>
                      <Text style={{ fontSize: 11, color: C.textMuted, width: 40, textAlign: 'right' }}>
                        {k.table}
                      </Text>
                    </div>
                  );
                })}
              </div>
            </Card>

            {/* 库存警戒灯 */}
            <Card
              title={<><WarningOutlined style={{ color: C.danger, marginRight: 6 }} />库存警戒</>}
              size="small"
              style={{ borderRadius: 8 }}
              styles={{ body: { padding: 12 } }}
            >
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
                {MOCK_INVENTORY.map(item => {
                  const color = item.level === 'green' ? C.success : item.level === 'yellow' ? C.warning : C.danger;
                  return (
                    <div key={item.name} style={{
                      padding: '8px 6px', borderRadius: 6, textAlign: 'center',
                      background: `${color}08`, border: `1px solid ${color}25`,
                    }}>
                      {/* 信号灯 */}
                      <div style={{
                        width: 10, height: 10, borderRadius: '50%',
                        background: color, margin: '0 auto 4px',
                        boxShadow: `0 0 6px ${color}60`,
                        animation: item.level === 'red' ? 'dtPulse 1.5s infinite' : undefined,
                      }} />
                      <Text style={{ fontSize: 12, fontWeight: 600, color: C.textPrimary, display: 'block' }}>{item.name}</Text>
                      <Text style={{ fontSize: 11, color }}>
                        {item.stock}{item.unit}
                      </Text>
                    </div>
                  );
                })}
              </div>
            </Card>

            {/* 人员状态 */}
            <Card
              title={<><UserOutlined style={{ color: C.info, marginRight: 6 }} />人员状态</>}
              extra={
                <Space size={8}>
                  <Tag color="green">{staffStats.onDuty}在岗</Tag>
                  <Tag color="orange">{staffStats.break}休息</Tag>
                  <Tag color="red">{staffStats.absent}缺勤</Tag>
                </Space>
              }
              size="small"
              style={{ borderRadius: 8 }}
              styles={{ body: { padding: 12 } }}
            >
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {MOCK_STAFF.map((s, i) => {
                  const color = s.status === 'onDuty' ? C.success : s.status === 'break' ? C.warning : C.danger;
                  return (
                    <Tooltip key={i} title={`${s.name} - ${s.role} (${s.status === 'onDuty' ? '在岗' : s.status === 'break' ? '休息' : '缺勤'})`}>
                      <div style={{
                        display: 'flex', alignItems: 'center', gap: 4,
                        padding: '4px 8px', borderRadius: 20,
                        background: `${color}10`, border: `1px solid ${color}30`,
                      }}>
                        <div style={{ width: 6, height: 6, borderRadius: '50%', background: color }} />
                        <Text style={{ fontSize: 11, color: C.textPrimary }}>{s.name}</Text>
                        <Text style={{ fontSize: 10, color: C.textMuted }}>{s.role}</Text>
                      </div>
                    </Tooltip>
                  );
                })}
              </div>
            </Card>
          </div>
        </Col>
      </Row>

      {/* ═══ 时间轴回放 ═══ */}
      <Card
        title={<><ClockCircleOutlined style={{ color: C.primary, marginRight: 6 }} />时间轴回放 — 今日门店状态</>}
        style={{ marginTop: 16, borderRadius: 8 }}
        styles={{ body: { padding: '16px 24px' } }}
      >
        {/* 时间轴控制 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
          <Button
            size="small" icon={<LeftOutlined />}
            disabled={timelineIdx === 0}
            onClick={() => setTimelineIdx(i => Math.max(0, i - 1))}
          />
          <div style={{ flex: 1 }}>
            <Slider
              min={0} max={TIMELINE.length - 1}
              value={timelineIdx}
              onChange={setTimelineIdx}
              tooltip={{ formatter: (v) => v !== undefined ? TIMELINE[v]?.hour : '' }}
              marks={Object.fromEntries(TIMELINE.map((t, i) => [i, { label: <span style={{ fontSize: 10 }}>{t.hour}</span> }]))}
              styles={{ track: { background: C.primary }, rail: { background: C.bgTertiary } }}
            />
          </div>
          <Button
            size="small" icon={<RightOutlined />}
            disabled={timelineIdx === TIMELINE.length - 1}
            onClick={() => setTimelineIdx(i => Math.min(TIMELINE.length - 1, i + 1))}
          />
        </div>

        {/* 快照数据 */}
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <div style={{ textAlign: 'center', padding: 12, background: C.bgSecondary, borderRadius: 8 }}>
              <Text style={{ fontSize: 11, color: C.textMuted }}>上座率</Text>
              <div style={{ fontSize: 28, fontWeight: 700, color: snapshot.occupancy > 85 ? C.danger : snapshot.occupancy > 60 ? C.warning : C.success }}>
                {snapshot.occupancy}%
              </div>
            </div>
          </Col>
          <Col span={6}>
            <div style={{ textAlign: 'center', padding: 12, background: C.bgSecondary, borderRadius: 8 }}>
              <Text style={{ fontSize: 11, color: C.textMuted }}>厨房负载</Text>
              <div style={{ fontSize: 28, fontWeight: 700, color: snapshot.kitchenLoad > 85 ? C.danger : snapshot.kitchenLoad > 60 ? C.warning : C.success }}>
                {snapshot.kitchenLoad}%
              </div>
            </div>
          </Col>
          <Col span={6}>
            <div style={{ textAlign: 'center', padding: 12, background: C.bgSecondary, borderRadius: 8 }}>
              <Text style={{ fontSize: 11, color: C.textMuted }}>累计营收</Text>
              <div style={{ fontSize: 28, fontWeight: 700, color: C.primary }}>
                \u00A5{snapshot.revenue.toLocaleString()}
              </div>
            </div>
          </Col>
          <Col span={6}>
            <div style={{ textAlign: 'center', padding: 12, background: C.bgSecondary, borderRadius: 8 }}>
              <Text style={{ fontSize: 11, color: C.textMuted }}>在岗人数</Text>
              <div style={{ fontSize: 28, fontWeight: 700, color: C.info }}>
                {snapshot.staffOnDuty}
              </div>
            </div>
          </Col>
        </Row>

        {/* 营收曲线（纯 CSS） */}
        <div style={{ marginBottom: 12 }}>
          <Text style={{ fontSize: 12, color: C.textMuted, marginBottom: 4, display: 'block' }}>营收趋势</Text>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 60 }}>
            {TIMELINE.map((t, i) => {
              const maxRev = Math.max(...TIMELINE.map(x => x.revenue), 1);
              const h = Math.max(4, (t.revenue / maxRev) * 56);
              const isActive = i <= timelineIdx;
              return (
                <div key={i} style={{
                  flex: 1,
                  height: h,
                  background: isActive ? (i === timelineIdx ? C.primary : `${C.primary}70`) : C.bgTertiary,
                  borderRadius: '3px 3px 0 0',
                  transition: 'all 0.3s',
                }} />
              );
            })}
          </div>
        </div>

        {/* 事件列表 */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {snapshot.events.map((evt, i) => (
            <Tag key={i} style={{
              borderRadius: 12, fontSize: 12,
              background: evt.includes('Agent') ? `${C.info}10` : C.bgSecondary,
              borderColor: evt.includes('Agent') ? `${C.info}30` : C.border,
              color: evt.includes('Agent') ? C.info : C.textSub,
            }}>
              {evt.includes('Agent') && '\u{1F916} '}{evt}
            </Tag>
          ))}
        </div>
      </Card>

      {/* ═══ What-If 模拟弹窗 ═══ */}
      <Modal
        title={<><ExperimentOutlined style={{ color: C.info, marginRight: 8 }} />What-If 经营模拟</>}
        open={simOpen}
        onCancel={() => { setSimOpen(false); setSimResults(null); }}
        footer={null}
        width={560}
      >
        {/* 场景选择 */}
        <div style={{ marginBottom: 16 }}>
          <Text style={{ fontSize: 13, color: C.textSub, display: 'block', marginBottom: 8 }}>选择模拟场景</Text>
          <div style={{ display: 'flex', gap: 8 }}>
            {SCENARIOS.map(s => (
              <Button
                key={s.id}
                type={simScenario.id === s.id ? 'primary' : 'default'}
                icon={s.icon}
                onClick={() => handleScenarioChange(s.id)}
                style={simScenario.id === s.id ? { background: C.info, borderColor: C.info } : {}}
              >
                {s.label}
              </Button>
            ))}
          </div>
        </div>

        {/* 参数调节 */}
        <div style={{ marginBottom: 16, padding: 16, background: C.bgSecondary, borderRadius: 8 }}>
          <Text style={{ fontSize: 13, color: C.textSub }}>{simScenario.paramLabel}</Text>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 8 }}>
            <Slider
              style={{ flex: 1 }}
              min={simScenario.min}
              max={simScenario.max}
              step={simScenario.step}
              value={simParam}
              onChange={setSimParam}
              styles={{ track: { background: C.info } }}
            />
            <InputNumber
              size="small"
              min={simScenario.min}
              max={simScenario.max}
              step={simScenario.step}
              value={simParam}
              onChange={(v) => v !== null && setSimParam(v)}
              addonAfter={simScenario.paramUnit}
              style={{ width: 100 }}
            />
          </div>
          <div style={{ textAlign: 'center', marginTop: 8 }}>
            <Text style={{ fontSize: 16, fontWeight: 700, color: C.info }}>
              如果{simScenario.label === '客流量增加' ? '今晚客流' : '龙虾等食材'}{simScenario.label === '客流量增加' ? '增加' : '涨价'} {simParam}{simScenario.paramUnit}？
            </Text>
          </div>
        </div>

        {/* 模拟按钮 */}
        <Button
          type="primary" block size="large"
          icon={<ThunderboltOutlined />}
          onClick={handleSimulate}
          style={{ background: C.info, borderColor: C.info, marginBottom: 16 }}
        >
          运行模拟
        </Button>

        {/* 结果展示 */}
        {simResults && (
          <div style={{
            padding: 16, borderRadius: 8,
            background: `${C.info}08`, border: `1px solid ${C.info}20`,
          }}>
            <Text strong style={{ color: C.info, fontSize: 14, display: 'block', marginBottom: 12 }}>
              模拟结果
            </Text>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {simResults.map((r, i) => (
                <div key={i} style={{
                  display: 'flex', alignItems: 'flex-start', gap: 8,
                  padding: '8px 12px', background: C.bgPrimary, borderRadius: 6,
                }}>
                  <span style={{
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                    width: 20, height: 20, borderRadius: '50%', flexShrink: 0,
                    background: C.info, color: '#fff', fontSize: 11, fontWeight: 700,
                  }}>{i + 1}</span>
                  <Text style={{ fontSize: 13, color: C.textPrimary }}>{r}</Text>
                </div>
              ))}
            </div>
          </div>
        )}
      </Modal>

      {/* 全局动画 CSS */}
      <style>{`
        @keyframes dtPulse {
          0%, 100% { opacity: 0.6; }
          50% { opacity: 1; }
        }
      `}</style>
    </div>
  );
}
