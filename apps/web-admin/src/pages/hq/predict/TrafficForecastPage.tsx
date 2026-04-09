/**
 * 客流预测详情 -- 24小时 x 7天客流预测矩阵
 * 天气图标叠加列头 | 高峰时段橙色高亮
 * 排班联动：当前排班 X 人 / 建议 Y 人
 *
 * 数据源：txFetch（后端 API）
 * 纯 CSS 实现，无第三方图表库
 */
import { useState, useEffect, useCallback } from 'react';
import { Select, Button, Spin, Tag, Tooltip } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { txFetch } from '../../../api';

// ─── 类型定义 ───────────────────────────────────────────────────────────────

interface StoreOption {
  store_id: string;
  store_name: string;
}

interface WeatherInfo {
  icon: string; // emoji
  desc: string;
  temp_high: number;
  temp_low: number;
}

interface HourlyTraffic {
  hour: number;
  predicted: number;
  actual: number | null; // 未来天无实际数据
  is_peak: boolean;
}

interface DayColumn {
  date: string;
  day_label: string; // "周一" 等
  weather: WeatherInfo;
  hourly: HourlyTraffic[];
  total_predicted: number;
  total_actual: number | null;
}

interface StaffingSuggestion {
  hour: number;
  current_staff: number;
  suggested_staff: number;
}

// ─── 天气图标映射 ─────────────────────────────────────────────────────────

const WEATHER_ICONS: Record<string, string> = {
  sunny: '☀️', cloudy: '⛅', rainy: '🌧️', stormy: '⛈️',
  snowy: '🌨️', overcast: '☁️', foggy: '🌫️',
};

const DAY_NAMES = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

// ─── Mock 数据 ──────────────────────────────────────────────────────────────

function mockStores(): StoreOption[] {
  return [
    { store_id: 's1', store_name: '长沙万达店' },
    { store_id: 's2', store_name: '长沙德思勤店' },
    { store_id: 's3', store_name: '株洲旗舰店' },
  ];
}

function mockDayColumns(): DayColumn[] {
  const today = dayjs();
  const weathers: WeatherInfo[] = [
    { icon: 'sunny', desc: '晴', temp_high: 28, temp_low: 18 },
    { icon: 'cloudy', desc: '多云', temp_high: 26, temp_low: 17 },
    { icon: 'rainy', desc: '小雨', temp_high: 22, temp_low: 15 },
    { icon: 'sunny', desc: '晴', temp_high: 30, temp_low: 20 },
    { icon: 'overcast', desc: '阴', temp_high: 24, temp_low: 16 },
    { icon: 'cloudy', desc: '多云', temp_high: 27, temp_low: 19 },
    { icon: 'sunny', desc: '晴', temp_high: 29, temp_low: 21 },
  ];

  return Array.from({ length: 7 }, (_, dayIdx) => {
    const d = today.add(dayIdx, 'day');
    const isPast = dayIdx === 0;
    const peakHours = new Set([11, 12, 13, 17, 18, 19]);

    const hourly: HourlyTraffic[] = Array.from({ length: 24 }, (_, h) => {
      let base = 0;
      if (h >= 10 && h <= 14) base = 30 + Math.floor(Math.random() * 25);
      else if (h >= 17 && h <= 21) base = 35 + Math.floor(Math.random() * 30);
      else if (h >= 7 && h <= 9) base = 10 + Math.floor(Math.random() * 10);
      else base = Math.floor(Math.random() * 8);

      // 雨天减少客流
      if (weathers[dayIdx].icon === 'rainy') base = Math.floor(base * 0.7);

      return {
        hour: h,
        predicted: base,
        actual: isPast ? base + Math.floor(Math.random() * 10) - 5 : null,
        is_peak: peakHours.has(h),
      };
    });

    return {
      date: d.format('MM-DD'),
      day_label: dayIdx === 0 ? '今天' : dayIdx === 1 ? '明天' : DAY_NAMES[d.day()],
      weather: weathers[dayIdx],
      hourly,
      total_predicted: hourly.reduce((s, h) => s + h.predicted, 0),
      total_actual: isPast ? hourly.reduce((s, h) => s + (h.actual ?? 0), 0) : null,
    };
  });
}

function mockStaffing(): StaffingSuggestion[] {
  return Array.from({ length: 24 }, (_, h) => {
    let suggested = 2;
    if (h >= 10 && h <= 14) suggested = 6 + Math.floor(Math.random() * 3);
    else if (h >= 17 && h <= 21) suggested = 7 + Math.floor(Math.random() * 3);
    else if (h >= 7 && h <= 9) suggested = 3;
    const current = Math.max(2, suggested + Math.floor(Math.random() * 3) - 1);
    return { hour: h, current_staff: current, suggested_staff: suggested };
  });
}

// ─── 组件 ────────────────────────────────────────────────────────────────────

export function TrafficForecastPage() {
  const [stores] = useState<StoreOption[]>(mockStores);
  const [selectedStore, setSelectedStore] = useState<string>('s1');
  const [loading, setLoading] = useState(false);
  const [columns, setColumns] = useState<DayColumn[]>([]);
  const [staffing, setStaffing] = useState<StaffingSuggestion[]>([]);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      // TODO: 后端就绪后替换
      // const [trafficRes, staffRes] = await Promise.allSettled([
      //   txFetch(`/api/v1/predict/traffic/matrix?store_id=${selectedStore}`),
      //   txFetch(`/api/v1/predict/staffing?store_id=${selectedStore}`),
      // ]);
      await new Promise(r => setTimeout(r, 400));
      setColumns(mockDayColumns());
      setStaffing(mockStaffing());
    } finally {
      setLoading(false);
    }
  }, [selectedStore]);

  useEffect(() => { loadData(); }, [loadData]);

  // ─── 渲染辅助 ───

  const maxTraffic = Math.max(
    1,
    ...columns.flatMap(c => c.hourly.map(h => Math.max(h.predicted, h.actual ?? 0))),
  );

  const cellBg = (value: number, isPeak: boolean) => {
    const intensity = value / maxTraffic;
    if (isPeak && intensity > 0.5) return '#FFF3ED';
    return 'transparent';
  };

  const cellColor = (value: number) => {
    const intensity = value / maxTraffic;
    if (intensity > 0.7) return '#A32D2D';
    if (intensity > 0.4) return '#BA7517';
    return '#2C2C2A';
  };

  return (
    <div style={{ padding: 24, background: '#F8F7F5', minHeight: '100vh' }}>
      {/* ─── 顶部 ─── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 24, flexWrap: 'wrap', gap: 12,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <h2 style={{ margin: 0, fontSize: 20, color: '#2C2C2A' }}>客流预测详情</h2>
          <Select
            value={selectedStore}
            onChange={setSelectedStore}
            style={{ width: 180 }}
            options={stores.map(s => ({ label: s.store_name, value: s.store_id }))}
          />
        </div>
        <Button icon={<ReloadOutlined />} onClick={loadData} loading={loading}>
          刷新
        </Button>
      </div>

      <Spin spinning={loading}>
        {/* ─── 24h x 7天矩阵 ─── */}
        <div style={{
          background: '#fff', borderRadius: 8, padding: 24,
          boxShadow: '0 1px 2px rgba(0,0,0,0.05)', overflowX: 'auto',
          marginBottom: 24,
        }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              {/* 天气行 */}
              <tr>
                <th style={{ padding: '8px 12px', textAlign: 'left', color: '#5F5E5A', fontWeight: 500, minWidth: 60 }}>
                  时段
                </th>
                {columns.map(col => (
                  <th key={col.date} style={{ padding: '4px 8px', textAlign: 'center', minWidth: 80 }}>
                    <div style={{ fontSize: 20 }}>
                      {WEATHER_ICONS[col.weather.icon] || '🌤️'}
                    </div>
                    <div style={{ fontSize: 11, color: '#B4B2A9' }}>
                      {col.weather.desc} {col.weather.temp_low}~{col.weather.temp_high}°C
                    </div>
                  </th>
                ))}
                <th style={{ padding: '8px 12px', textAlign: 'center', color: '#5F5E5A', fontWeight: 500, minWidth: 120 }}>
                  排班建议
                </th>
              </tr>
              {/* 日期行 */}
              <tr style={{ borderBottom: '2px solid #E8E6E1' }}>
                <th style={{ padding: '6px 12px', textAlign: 'left', color: '#2C2C2A', fontWeight: 600 }}>
                  时间
                </th>
                {columns.map(col => (
                  <th key={col.date} style={{
                    padding: '6px 8px', textAlign: 'center', fontWeight: 600,
                    color: col.day_label === '今天' ? '#FF6B35' : '#2C2C2A',
                  }}>
                    {col.day_label}
                    <div style={{ fontSize: 11, fontWeight: 400, color: '#B4B2A9' }}>{col.date}</div>
                  </th>
                ))}
                <th style={{ padding: '6px 12px', textAlign: 'center', fontWeight: 600, color: '#2C2C2A' }}>
                  当前/建议
                </th>
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: 24 }, (_, h) => {
                const staff = staffing[h];
                const staffDiff = staff ? staff.suggested_staff - staff.current_staff : 0;
                return (
                  <tr
                    key={h}
                    style={{
                      borderBottom: '1px solid #F0EDE6',
                      background: (h >= 11 && h <= 13) || (h >= 17 && h <= 19) ? '#FFF9F5' : 'transparent',
                    }}
                  >
                    <td style={{
                      padding: '6px 12px', fontWeight: 500, color: '#2C2C2A',
                      whiteSpace: 'nowrap',
                    }}>
                      {String(h).padStart(2, '0')}:00
                      {((h >= 11 && h <= 13) || (h >= 17 && h <= 19)) && (
                        <span style={{
                          display: 'inline-block', width: 6, height: 6,
                          borderRadius: '50%', background: '#FF6B35',
                          marginLeft: 6, verticalAlign: 'middle',
                        }} />
                      )}
                    </td>
                    {columns.map(col => {
                      const cell = col.hourly[h];
                      return (
                        <td
                          key={col.date}
                          style={{
                            padding: '6px 8px', textAlign: 'center',
                            background: cellBg(cell.predicted, cell.is_peak),
                          }}
                        >
                          <Tooltip
                            title={`预测: ${cell.predicted}人${cell.actual !== null ? ` | 实际: ${cell.actual}人` : ''}`}
                          >
                            <span style={{ color: cellColor(cell.predicted), fontWeight: cell.is_peak ? 600 : 400 }}>
                              {cell.predicted}
                            </span>
                            {cell.actual !== null && (
                              <span style={{ fontSize: 11, color: '#B4B2A9', display: 'block' }}>
                                实{cell.actual}
                              </span>
                            )}
                          </Tooltip>
                        </td>
                      );
                    })}
                    {/* 排班列 */}
                    <td style={{ padding: '6px 12px', textAlign: 'center' }}>
                      {staff && (
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4 }}>
                          <span style={{ color: '#2C2C2A' }}>{staff.current_staff}人</span>
                          <span style={{ color: '#B4B2A9' }}>/</span>
                          <span style={{
                            color: staffDiff > 0 ? '#A32D2D' : staffDiff < 0 ? '#0F6E56' : '#2C2C2A',
                            fontWeight: staffDiff !== 0 ? 600 : 400,
                          }}>
                            {staff.suggested_staff}人
                          </span>
                          {staffDiff > 0 && (
                            <Tag color="red" style={{ fontSize: 11, margin: 0, padding: '0 4px', lineHeight: '18px' }}>
                              缺{staffDiff}
                            </Tag>
                          )}
                          {staffDiff < 0 && (
                            <Tag color="green" style={{ fontSize: 11, margin: 0, padding: '0 4px', lineHeight: '18px' }}>
                              余{-staffDiff}
                            </Tag>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
              {/* 合计行 */}
              <tr style={{ borderTop: '2px solid #E8E6E1', background: '#F8F7F5' }}>
                <td style={{ padding: '8px 12px', fontWeight: 700, color: '#2C2C2A' }}>合计</td>
                {columns.map(col => (
                  <td key={col.date} style={{ padding: '8px', textAlign: 'center', fontWeight: 700, color: '#FF6B35' }}>
                    {col.total_predicted}
                    {col.total_actual !== null && (
                      <span style={{ fontSize: 11, color: '#B4B2A9', display: 'block', fontWeight: 400 }}>
                        实{col.total_actual}
                      </span>
                    )}
                  </td>
                ))}
                <td />
              </tr>
            </tbody>
          </table>
        </div>

        {/* ─── 图例说明 ─── */}
        <div style={{
          background: '#fff', borderRadius: 8, padding: 16,
          boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
          display: 'flex', gap: 24, flexWrap: 'wrap', fontSize: 13, color: '#5F5E5A',
        }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#FF6B35', display: 'inline-block' }} />
            高峰时段
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 16, height: 12, borderRadius: 2, background: '#FFF9F5', border: '1px solid #E8E6E1', display: 'inline-block' }} />
            高峰行高亮
          </span>
          <span>
            <Tag color="red" style={{ fontSize: 11 }}>缺N</Tag> 需增派人手
          </span>
          <span>
            <Tag color="green" style={{ fontSize: 11 }}>余N</Tag> 可调配人手
          </span>
        </div>
      </Spin>
    </div>
  );
}

export default TrafficForecastPage;
