/**
 * 预测仪表盘 -- 总部视角
 * 门店选择器 + 日期范围 | 今日客流预测 & 本周营收预测
 * 7天客流趋势（柱状图：预测 vs 实际）| 菜品需求热力图 TOP20x7天
 * 预测准确率追踪（近30天折线，目标线85%）
 *
 * 数据源：txFetchData（后端 API）
 * 图表：纯 CSS/SVG（TxBarChart / TxHeatmap / TxLineChart）
 */
import { useState, useEffect, useCallback } from 'react';
import { Select, DatePicker, Button, Spin, Space } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { TxBarChart } from '../../../components/charts';
import { TxHeatmap } from '../../../components/charts';
import { TxLineChart } from '../../../components/charts';
import { txFetchData } from '../../../api';

// ─── 类型定义 ───────────────────────────────────────────────────────────────

interface StoreOption {
  store_id: string;
  store_name: string;
}

interface TrafficForecast {
  predicted: number;
  actual: number;
  deviation_rate: number; // 偏差率 %
}

interface RevenueForecast {
  predicted_fen: number;
  actual_fen: number;
  trend_percent: number;
}

interface DailyTraffic {
  date: string;
  predicted: number;
  actual: number;
}

interface DishDemandRow {
  dish_name: string;
  daily_demands: number[]; // 7天需求量
}

interface AccuracyPoint {
  date: string;
  accuracy: number; // 0-100
}

// ─── 工具函数 ────────────────────────────────────────────────────────────────

const fmtMoney = (fen: number) =>
  `¥${(fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const fmtPercent = (v: number) => `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`;

// ─── Mock 数据生成（后端就绪后切换为真实 API） ───────────────────────────────

function mockStores(): StoreOption[] {
  return [
    { store_id: 's1', store_name: '长沙万达店' },
    { store_id: 's2', store_name: '长沙德思勤店' },
    { store_id: 's3', store_name: '株洲旗舰店' },
    { store_id: 's4', store_name: '湘潭步行街店' },
  ];
}

function mockTrafficForecast(): TrafficForecast {
  const predicted = 320 + Math.floor(Math.random() * 60);
  const actual = predicted - 15 + Math.floor(Math.random() * 30);
  return { predicted, actual, deviation_rate: +((actual - predicted) / predicted * 100).toFixed(1) };
}

function mockRevenueForecast(): RevenueForecast {
  const predicted = 4500000 + Math.floor(Math.random() * 1000000);
  const actual = predicted - 200000 + Math.floor(Math.random() * 400000);
  return { predicted_fen: predicted, actual_fen: actual, trend_percent: 8.3 };
}

function mockWeeklyTraffic(): DailyTraffic[] {
  const today = dayjs();
  return Array.from({ length: 7 }, (_, i) => {
    const date = today.subtract(6 - i, 'day').format('MM-DD');
    const predicted = 280 + Math.floor(Math.random() * 100);
    const actual = i < 6 ? predicted - 20 + Math.floor(Math.random() * 40) : 0;
    return { date, predicted, actual };
  });
}

function mockDishDemand(): { dishes: DishDemandRow[]; dates: string[] } {
  const dishNames = [
    '剁椒鱼头', '小炒黄牛肉', '辣椒炒肉', '口味虾', '糖油粑粑',
    '酸菜鱼', '红烧肉', '蒜蓉蒸虾', '铁板牛肉', '干锅鸡',
    '水煮鱼片', '宫保鸡丁', '蚝油生菜', '蛋炒饭', '酸辣土豆丝',
    '清蒸鲈鱼', '回锅肉', '麻婆豆腐', '啤酒鸭', '紫苏桃子姜',
  ];
  const today = dayjs();
  const dates = Array.from({ length: 7 }, (_, i) => today.subtract(6 - i, 'day').format('MM-DD'));
  const dishes = dishNames.map(name => ({
    dish_name: name,
    daily_demands: Array.from({ length: 7 }, () => Math.floor(Math.random() * 120) + 10),
  }));
  return { dishes, dates };
}

function mockAccuracy(): AccuracyPoint[] {
  const today = dayjs();
  return Array.from({ length: 30 }, (_, i) => ({
    date: today.subtract(29 - i, 'day').format('MM-DD'),
    accuracy: 75 + Math.random() * 20,
  }));
}

// ─── 组件 ────────────────────────────────────────────────────────────────────

export function PredictDashboardPage() {
  const [stores] = useState<StoreOption[]>(mockStores);
  const [selectedStore, setSelectedStore] = useState<string>('s1');
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs]>([
    dayjs().subtract(6, 'day'),
    dayjs(),
  ]);
  const [loading, setLoading] = useState(false);

  // 数据状态
  const [traffic, setTraffic] = useState<TrafficForecast | null>(null);
  const [revenue, setRevenue] = useState<RevenueForecast | null>(null);
  const [weeklyTraffic, setWeeklyTraffic] = useState<DailyTraffic[]>([]);
  const [dishDemand, setDishDemand] = useState<{ dishes: DishDemandRow[]; dates: string[] }>({ dishes: [], dates: [] });
  const [accuracy, setAccuracy] = useState<AccuracyPoint[]>([]);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      // TODO: 后端就绪后替换为真实 API
      // const [tRes, rRes, wRes, dRes, aRes] = await Promise.allSettled([
      //   txFetchData(`/api/v1/predict/traffic/today?store_id=${selectedStore}`),
      //   txFetchData(`/api/v1/predict/revenue/week?store_id=${selectedStore}`),
      //   txFetchData(`/api/v1/predict/traffic/weekly?store_id=${selectedStore}`),
      //   txFetchData(`/api/v1/predict/demand/heatmap?store_id=${selectedStore}`),
      //   txFetchData(`/api/v1/predict/accuracy?store_id=${selectedStore}&days=30`),
      // ]);
      await new Promise(r => setTimeout(r, 400));
      setTraffic(mockTrafficForecast());
      setRevenue(mockRevenueForecast());
      setWeeklyTraffic(mockWeeklyTraffic());
      setDishDemand(mockDishDemand());
      setAccuracy(mockAccuracy());
    } finally {
      setLoading(false);
    }
  }, [selectedStore]);

  useEffect(() => { loadData(); }, [loadData]);

  // ─── 图表数据转换 ───

  const barChartData = {
    labels: weeklyTraffic.map(d => d.date),
    datasets: [
      { name: '预测客流', values: weeklyTraffic.map(d => d.predicted), color: '#FF6B35' },
      { name: '实际客流', values: weeklyTraffic.map(d => d.actual), color: '#185FA5' },
    ],
  };

  const heatmapData = {
    xLabels: dishDemand.dates,
    yLabels: dishDemand.dishes.map(d => d.dish_name),
    values: dishDemand.dishes.map(d => d.daily_demands),
  };

  const accuracyLineData = {
    labels: accuracy.map(a => a.date),
    datasets: [
      { name: '预测准确率', values: accuracy.map(a => +a.accuracy.toFixed(1)), color: '#FF6B35' },
      { name: '目标线(85%)', values: accuracy.map(() => 85), color: '#0F6E56' },
    ],
  };

  // ─── 渲染 ───

  const deviationColor = traffic
    ? Math.abs(traffic.deviation_rate) <= 5 ? '#0F6E56'
    : Math.abs(traffic.deviation_rate) <= 15 ? '#BA7517'
    : '#A32D2D'
    : '#5F5E5A';

  return (
    <div style={{ padding: 24, background: '#F8F7F5', minHeight: '100vh' }}>
      {/* ─── 顶部筛选栏 ─── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 24, flexWrap: 'wrap', gap: 12,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <h2 style={{ margin: 0, fontSize: 20, color: '#2C2C2A' }}>预测仪表盘</h2>
          <Select
            value={selectedStore}
            onChange={setSelectedStore}
            style={{ width: 180 }}
            options={stores.map(s => ({ label: s.store_name, value: s.store_id }))}
          />
          <DatePicker.RangePicker
            value={dateRange}
            onChange={(v) => v && setDateRange(v as [dayjs.Dayjs, dayjs.Dayjs])}
            allowClear={false}
            style={{ width: 260 }}
          />
        </div>
        <Button icon={<ReloadOutlined />} onClick={loadData} loading={loading}>
          刷新
        </Button>
      </div>

      <Spin spinning={loading}>
        {/* ─── 第一行：KPI 大字卡 ─── */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16, marginBottom: 24 }}>
          {/* 今日客流预测 */}
          <div style={{
            background: '#fff', borderRadius: 8, padding: 24,
            boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
          }}>
            <div style={{ fontSize: 14, color: '#5F5E5A', marginBottom: 8 }}>今日客流预测</div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 16 }}>
              <span style={{ fontSize: 36, fontWeight: 700, color: '#FF6B35' }}>
                {traffic?.predicted ?? '--'}
              </span>
              <span style={{ fontSize: 14, color: '#5F5E5A' }}>人</span>
            </div>
            <div style={{
              display: 'flex', gap: 24, marginTop: 12,
              fontSize: 13, color: '#5F5E5A',
            }}>
              <span>实际: <b style={{ color: '#2C2C2A' }}>{traffic?.actual ?? '--'}</b> 人</span>
              <span>
                偏差率:{' '}
                <b style={{ color: deviationColor }}>
                  {traffic ? fmtPercent(traffic.deviation_rate) : '--'}
                </b>
              </span>
            </div>
            {/* 偏差条 */}
            {traffic && (
              <div style={{ marginTop: 12 }}>
                <div style={{
                  height: 6, borderRadius: 3, background: '#E8E6E1',
                  position: 'relative', overflow: 'hidden',
                }}>
                  <div style={{
                    position: 'absolute', left: 0, top: 0, height: '100%',
                    borderRadius: 3,
                    width: `${Math.min(100, (traffic.actual / traffic.predicted) * 100)}%`,
                    background: deviationColor,
                    transition: 'width 0.6s ease',
                  }} />
                </div>
              </div>
            )}
          </div>

          {/* 本周营收预测 */}
          <div style={{
            background: '#fff', borderRadius: 8, padding: 24,
            boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
          }}>
            <div style={{ fontSize: 14, color: '#5F5E5A', marginBottom: 8 }}>本周营收预测</div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 16 }}>
              <span style={{ fontSize: 36, fontWeight: 700, color: '#1E2A3A' }}>
                {revenue ? fmtMoney(revenue.predicted_fen) : '--'}
              </span>
            </div>
            <div style={{
              display: 'flex', gap: 24, marginTop: 12,
              fontSize: 13, color: '#5F5E5A',
            }}>
              <span>实际: <b style={{ color: '#2C2C2A' }}>{revenue ? fmtMoney(revenue.actual_fen) : '--'}</b></span>
              <span>
                环比:{' '}
                <b style={{ color: (revenue?.trend_percent ?? 0) >= 0 ? '#0F6E56' : '#A32D2D' }}>
                  {revenue ? fmtPercent(revenue.trend_percent) : '--'}
                </b>
              </span>
            </div>
            {/* 完成进度 */}
            {revenue && (
              <div style={{ marginTop: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: '#B4B2A9', marginBottom: 4 }}>
                  <span>完成进度</span>
                  <span>{((revenue.actual_fen / revenue.predicted_fen) * 100).toFixed(1)}%</span>
                </div>
                <div style={{
                  height: 6, borderRadius: 3, background: '#E8E6E1',
                  position: 'relative', overflow: 'hidden',
                }}>
                  <div style={{
                    position: 'absolute', left: 0, top: 0, height: '100%',
                    borderRadius: 3,
                    width: `${Math.min(100, (revenue.actual_fen / revenue.predicted_fen) * 100)}%`,
                    background: '#FF6B35',
                    transition: 'width 0.6s ease',
                  }} />
                </div>
              </div>
            )}
          </div>
        </div>

        {/* ─── 第二行：7天客流趋势图 ─── */}
        <div style={{
          background: '#fff', borderRadius: 8, padding: 24, marginBottom: 24,
          boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
        }}>
          <div style={{ fontSize: 16, fontWeight: 600, color: '#2C2C2A', marginBottom: 16 }}>
            7天客流趋势
          </div>
          <div style={{ display: 'flex', gap: 16, marginBottom: 12, fontSize: 13, color: '#5F5E5A' }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ width: 12, height: 12, borderRadius: 2, background: '#FF6B35', display: 'inline-block' }} />
              预测客流
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ width: 12, height: 12, borderRadius: 2, background: '#185FA5', display: 'inline-block' }} />
              实际客流
            </span>
          </div>
          <TxBarChart data={barChartData} height={260} unit="人" />
        </div>

        {/* ─── 第三行：菜品需求热力图 ─── */}
        <div style={{
          background: '#fff', borderRadius: 8, padding: 24, marginBottom: 24,
          boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
        }}>
          <div style={{ fontSize: 16, fontWeight: 600, color: '#2C2C2A', marginBottom: 4 }}>
            菜品需求热力图
          </div>
          <div style={{ fontSize: 13, color: '#B4B2A9', marginBottom: 16 }}>
            TOP 20 菜品 x 近7天 | 颜色越深需求量越高
          </div>
          <TxHeatmap
            data={heatmapData}
            unit="份"
            colorRange={['#FFF3ED', '#FF6B35']}
          />
        </div>

        {/* ─── 第四行：预测准确率追踪 ─── */}
        <div style={{
          background: '#fff', borderRadius: 8, padding: 24,
          boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
        }}>
          <div style={{ fontSize: 16, fontWeight: 600, color: '#2C2C2A', marginBottom: 4 }}>
            预测准确率追踪
          </div>
          <div style={{ fontSize: 13, color: '#B4B2A9', marginBottom: 16 }}>
            近30天预测准确率 | 绿色虚线为85%目标线
          </div>
          <TxLineChart data={accuracyLineData} height={220} unit="%" />
        </div>
      </Spin>
    </div>
  );
}

export default PredictDashboardPage;
