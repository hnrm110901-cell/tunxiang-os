/**
 * 门店设置(精简版) — 桌台/打印机/KDS/日结餐段
 */
import { useState } from 'react';

/* ---------- Mock Data ---------- */
interface TableZone { id: string; name: string; tableCount: number; }
interface PrinterConfig { id: string; name: string; ip: string; department: string; }
interface KDSTerminal { id: string; name: string; stall: string; }
interface MealPeriod { id: string; name: string; start: string; end: string; }

const mockZones: TableZone[] = [
  { id: '1', name: 'A区-大厅', tableCount: 15 },
  { id: '2', name: 'B区-包厢', tableCount: 6 },
  { id: '3', name: 'C区-露台', tableCount: 8 },
];

const mockPrinters: PrinterConfig[] = [
  { id: '1', name: '前台打印机', ip: '192.168.1.101', department: '收银台' },
  { id: '2', name: '热菜出品', ip: '192.168.1.102', department: '热菜档口' },
  { id: '3', name: '凉菜出品', ip: '192.168.1.103', department: '凉菜档口' },
];

const mockKDS: KDSTerminal[] = [
  { id: '1', name: 'KDS-热菜', stall: '热菜档口' },
  { id: '2', name: 'KDS-凉菜', stall: '凉菜档口' },
  { id: '3', name: 'KDS-主食', stall: '主食档口' },
];

const mockPeriods: MealPeriod[] = [
  { id: '1', name: '午餐', start: '11:00', end: '14:00' },
  { id: '2', name: '下午茶', start: '14:00', end: '17:00' },
  { id: '3', name: '晚餐', start: '17:00', end: '21:30' },
];

/* ---------- Section Component ---------- */
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ background: '#112B36', borderRadius: 10, padding: 16, marginBottom: 16 }}>
      <h3 style={{ margin: '0 0 14px', fontSize: 15, color: '#fff', borderBottom: '1px solid #1A3A48', paddingBottom: 10 }}>
        {title}
      </h3>
      {children}
    </div>
  );
}

/* ---------- Component ---------- */
export function POSSettingsPage() {
  const [zones, setZones] = useState(mockZones);
  const [printers] = useState(mockPrinters);
  const [kdsTerminals] = useState(mockKDS);
  const [periods] = useState(mockPeriods);
  const [dailySettleTime, setDailySettleTime] = useState('03:00');

  const cellStyle: React.CSSProperties = { padding: '10px 0', borderBottom: '1px solid #1A3A48', fontSize: 13 };
  const headerStyle: React.CSSProperties = { ...cellStyle, color: '#8899A6', fontWeight: 'bold', fontSize: 12 };
  const inputStyle: React.CSSProperties = {
    background: '#1A3A48', color: '#fff', border: '1px solid #2A4A58',
    borderRadius: 4, padding: '6px 10px', fontSize: 13, width: '100%', boxSizing: 'border-box',
  };

  return (
    <div style={{ background: '#0B1A20', minHeight: '100vh', color: '#E0E0E0', fontFamily: 'Noto Sans SC, sans-serif', padding: 20 }}>
      <h1 style={{ margin: '0 0 20px', fontSize: 22, color: '#fff' }}>门店设置</h1>

      {/* 桌台配置 */}
      <Section title="桌台配置">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 100px 80px', gap: 8 }}>
          <div style={headerStyle}>营业区</div>
          <div style={headerStyle}>桌台数</div>
          <div style={headerStyle}>操作</div>
          {zones.map(z => (
            <div key={z.id} style={{ display: 'contents' }}>
              <div style={cellStyle}>{z.name}</div>
              <div style={cellStyle}>
                <input
                  type="number"
                  value={z.tableCount}
                  onChange={e => setZones(prev => prev.map(zone =>
                    zone.id === z.id ? { ...zone, tableCount: Number(e.target.value) } : zone
                  ))}
                  style={{ ...inputStyle, width: 60 }}
                />
              </div>
              <div style={cellStyle}>
                <button style={{
                  padding: '4px 10px', background: 'transparent', color: '#1890ff',
                  border: '1px solid #1890ff', borderRadius: 4, cursor: 'pointer', fontSize: 12,
                }}>编辑</button>
              </div>
            </div>
          ))}
        </div>
        <button style={{
          marginTop: 10, padding: '6px 16px', background: '#1A3A48', color: '#52c41a',
          border: '1px dashed #52c41a', borderRadius: 4, cursor: 'pointer', fontSize: 12,
        }}>+ 新增营业区</button>
      </Section>

      {/* 打印机设置 */}
      <Section title="打印机设置">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 140px 1fr 80px', gap: 8 }}>
          <div style={headerStyle}>打印机名</div>
          <div style={headerStyle}>IP 地址</div>
          <div style={headerStyle}>关联部门</div>
          <div style={headerStyle}>状态</div>
          {printers.map(p => (
            <div key={p.id} style={{ display: 'contents' }}>
              <div style={cellStyle}>{p.name}</div>
              <div style={cellStyle}><code style={{ color: '#1890ff' }}>{p.ip}</code></div>
              <div style={cellStyle}>{p.department}</div>
              <div style={cellStyle}>
                <span style={{ color: '#52c41a', fontSize: 12 }}>在线</span>
              </div>
            </div>
          ))}
        </div>
        <button style={{
          marginTop: 10, padding: '6px 16px', background: '#1A3A48', color: '#52c41a',
          border: '1px dashed #52c41a', borderRadius: 4, cursor: 'pointer', fontSize: 12,
        }}>+ 新增打印机</button>
      </Section>

      {/* KDS 终端设置 */}
      <Section title="KDS 终端设置">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 80px', gap: 8 }}>
          <div style={headerStyle}>终端名</div>
          <div style={headerStyle}>关联档口</div>
          <div style={headerStyle}>状态</div>
          {kdsTerminals.map(k => (
            <div key={k.id} style={{ display: 'contents' }}>
              <div style={cellStyle}>{k.name}</div>
              <div style={cellStyle}>{k.stall}</div>
              <div style={cellStyle}>
                <span style={{ color: '#52c41a', fontSize: 12 }}>在线</span>
              </div>
            </div>
          ))}
        </div>
        <button style={{
          marginTop: 10, padding: '6px 16px', background: '#1A3A48', color: '#52c41a',
          border: '1px dashed #52c41a', borderRadius: 4, cursor: 'pointer', fontSize: 12,
        }}>+ 新增终端</button>
      </Section>

      {/* 日结/餐段设置 */}
      <Section title="日结 / 餐段设置">
        <div style={{ marginBottom: 16 }}>
          <span style={{ fontSize: 13, color: '#8899A6', marginRight: 12 }}>日结时间</span>
          <input
            type="time"
            value={dailySettleTime}
            onChange={e => setDailySettleTime(e.target.value)}
            style={{ ...inputStyle, width: 120 }}
          />
          <span style={{ fontSize: 11, color: '#666', marginLeft: 8 }}>每日自动触发日结流程</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 100px 100px 80px', gap: 8 }}>
          <div style={headerStyle}>餐段名</div>
          <div style={headerStyle}>开始</div>
          <div style={headerStyle}>结束</div>
          <div style={headerStyle}>操作</div>
          {periods.map(p => (
            <div key={p.id} style={{ display: 'contents' }}>
              <div style={cellStyle}>{p.name}</div>
              <div style={cellStyle}>{p.start}</div>
              <div style={cellStyle}>{p.end}</div>
              <div style={cellStyle}>
                <button style={{
                  padding: '4px 10px', background: 'transparent', color: '#1890ff',
                  border: '1px solid #1890ff', borderRadius: 4, cursor: 'pointer', fontSize: 12,
                }}>编辑</button>
              </div>
            </div>
          ))}
        </div>
        <button style={{
          marginTop: 10, padding: '6px 16px', background: '#1A3A48', color: '#52c41a',
          border: '1px dashed #52c41a', borderRadius: 4, cursor: 'pointer', fontSize: 12,
        }}>+ 新增餐段</button>
      </Section>

      {/* Save */}
      <button style={{
        width: '100%', padding: '12px 0', background: '#1890ff', color: '#fff',
        border: 'none', borderRadius: 8, cursor: 'pointer', fontSize: 16, fontWeight: 'bold',
      }}>
        保存设置
      </button>
    </div>
  );
}
