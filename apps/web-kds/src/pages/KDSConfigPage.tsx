/**
 * KDS 档口配置 -- 档口列表 + 新增/编辑 + WebSocket 连接配置
 * 大字号设计，厨房友好
 *
 * 新增配置区域：
 *   - Mac mini 地址（存 localStorage）
 *   - 档口ID选择
 *   - 声音开关
 *   - 超时阈值设置
 */
import { useState, useCallback } from 'react';
import { playNewOrder, playRush, playTimeout, warmUpAudio } from '../utils/audio';

/* ---------- Types ---------- */
interface Stall {
  id: string;
  name: string;
  dishCount: number;
  printer: string;
  status: 'online' | 'offline';
}

/* ---------- Mock Data ---------- */
const initialStalls: Stall[] = [
  { id: '1', name: '热菜档口', dishCount: 28, printer: '热菜出品机 (192.168.1.102)', status: 'online' },
  { id: '2', name: '凉菜档口', dishCount: 12, printer: '凉菜出品机 (192.168.1.103)', status: 'online' },
  { id: '3', name: '主食档口', dishCount: 8, printer: '主食出品机 (192.168.1.104)', status: 'online' },
  { id: '4', name: '蒸菜档口', dishCount: 15, printer: '蒸菜出品机 (192.168.1.105)', status: 'offline' },
];

/* ---------- localStorage helpers ---------- */

function getStoredValue(key: string, fallback: string): string {
  try { return localStorage.getItem(key) || fallback; } catch { return fallback; }
}

function setStoredValue(key: string, value: string): void {
  try { localStorage.setItem(key, value); } catch { /* quota exceeded */ }
}

/* ---------- Component ---------- */
export function KDSConfigPage() {
  const [stalls, setStalls] = useState(initialStalls);
  const [editing, setEditing] = useState<Stall | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [formName, setFormName] = useState('');
  const [formPrinter, setFormPrinter] = useState('');

  // ─── WebSocket 配置 ───
  const [macHost, setMacHost] = useState(() => getStoredValue('kds_mac_host', ''));
  const [stationId, setStationId] = useState(() => getStoredValue('kds_station_id', 'default'));
  const [soundEnabled, setSoundEnabled] = useState(() => getStoredValue('kds_sound', 'on') === 'on');
  const [timeoutMinutes, setTimeoutMinutes] = useState(() =>
    parseInt(getStoredValue('kds_timeout_minutes', '25'), 10),
  );
  const [wsTestStatus, setWsTestStatus] = useState<'idle' | 'testing' | 'ok' | 'fail'>('idle');
  const [configSaved, setConfigSaved] = useState(false);

  // 保存 WebSocket 配置
  const saveWsConfig = useCallback(() => {
    setStoredValue('kds_mac_host', macHost.trim());
    setStoredValue('kds_station_id', stationId.trim() || 'default');
    setStoredValue('kds_sound', soundEnabled ? 'on' : 'off');
    setStoredValue('kds_timeout_minutes', String(timeoutMinutes));
    setConfigSaved(true);
    setTimeout(() => setConfigSaved(false), 2000);
  }, [macHost, stationId, soundEnabled, timeoutMinutes]);

  // 测试 WebSocket 连接
  const testConnection = useCallback(() => {
    if (!macHost.trim()) return;
    setWsTestStatus('testing');

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${macHost.trim()}/ws/kds/${encodeURIComponent(stationId || 'test')}`;

    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      setWsTestStatus('fail');
      return;
    }

    const timeout = setTimeout(() => {
      ws.close();
      setWsTestStatus('fail');
    }, 5000);

    ws.onopen = () => {
      clearTimeout(timeout);
      // 发送 ping 验证服务端响应
      ws.send('ping');
    };

    ws.onmessage = (event) => {
      if (event.data === 'pong') {
        clearTimeout(timeout);
        setWsTestStatus('ok');
        ws.close();
      }
    };

    ws.onerror = () => {
      clearTimeout(timeout);
      setWsTestStatus('fail');
    };

    ws.onclose = () => {
      clearTimeout(timeout);
    };
  }, [macHost, stationId]);

  // 测试提示音
  const testSound = useCallback((type: 'new' | 'rush' | 'timeout') => {
    warmUpAudio();
    if (type === 'new') playNewOrder();
    else if (type === 'rush') playRush();
    else playTimeout();
  }, []);

  // 档口管理
  const openAdd = () => {
    setEditing(null);
    setFormName('');
    setFormPrinter('');
    setShowForm(true);
  };

  const openEdit = (stall: Stall) => {
    setEditing(stall);
    setFormName(stall.name);
    setFormPrinter(stall.printer);
    setShowForm(true);
  };

  const handleSave = () => {
    if (!formName.trim()) return;
    if (editing) {
      setStalls(prev => prev.map(s =>
        s.id === editing.id ? { ...s, name: formName, printer: formPrinter } : s
      ));
    } else {
      setStalls(prev => [...prev, {
        id: Date.now().toString(),
        name: formName,
        dishCount: 0,
        printer: formPrinter || '未配置',
        status: 'offline',
      }]);
    }
    setShowForm(false);
  };

  const handleDelete = (id: string) => {
    setStalls(prev => prev.filter(s => s.id !== id));
  };

  const inputStyle: React.CSSProperties = {
    width: '100%', boxSizing: 'border-box', padding: '12px 14px',
    background: '#1A3A48', color: '#fff', border: '1px solid #2A4A58',
    borderRadius: 6, fontSize: 18,
  };

  return (
    <div style={{
      background: '#0B1A20', minHeight: '100vh', color: '#E0E0E0',
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
      padding: 16,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: 28, color: '#fff' }}>档口配置</h1>
        <a
          href="/board"
          style={{
            padding: '10px 24px', background: '#FF6B35', color: '#fff',
            borderRadius: 8, fontSize: 18, fontWeight: 'bold',
            textDecoration: 'none', minHeight: 48, display: 'inline-flex', alignItems: 'center',
          }}
        >
          返回看板
        </a>
      </div>

      {/* ─── WebSocket 连接配置 ─── */}
      <div style={{
        background: '#112B36', borderRadius: 12, padding: 24,
        marginBottom: 24, borderLeft: '5px solid #FF6B35',
      }}>
        <h2 style={{ margin: '0 0 20px', fontSize: 24, color: '#FF6B35' }}>
          实时推送配置
        </h2>

        {/* Mac mini 地址 */}
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: 'block', fontSize: 18, color: '#8899A6', marginBottom: 8 }}>
            Mac mini 地址
          </label>
          <div style={{ display: 'flex', gap: 10 }}>
            <input
              value={macHost}
              onChange={e => setMacHost(e.target.value)}
              placeholder="如: 192.168.1.100:8000"
              style={{ ...inputStyle, flex: 1 }}
            />
            <button
              onClick={testConnection}
              disabled={!macHost.trim() || wsTestStatus === 'testing'}
              style={{
                padding: '12px 20px', minWidth: 100, minHeight: 48,
                background: wsTestStatus === 'ok' ? '#0F6E56'
                  : wsTestStatus === 'fail' ? '#A32D2D'
                  : '#1A3A48',
                color: '#fff', border: '1px solid #2A4A58',
                borderRadius: 6, cursor: 'pointer', fontSize: 18,
                opacity: (!macHost.trim() || wsTestStatus === 'testing') ? 0.5 : 1,
              }}
            >
              {wsTestStatus === 'testing' ? '测试中...'
                : wsTestStatus === 'ok' ? '连接成功'
                : wsTestStatus === 'fail' ? '连接失败'
                : '测试连接'}
            </button>
          </div>
          <div style={{ fontSize: 16, color: '#556', marginTop: 6 }}>
            输入 Mac mini 的局域网 IP + 端口。留空则使用离线 Mock 数据。
          </div>
        </div>

        {/* 档口 ID */}
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: 'block', fontSize: 18, color: '#8899A6', marginBottom: 8 }}>
            当前档口 ID
          </label>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {stalls.map(s => (
              <button
                key={s.id}
                onClick={() => setStationId(s.id)}
                style={{
                  padding: '10px 20px', minHeight: 48, minWidth: 48,
                  fontSize: 18,
                  fontWeight: stationId === s.id ? 'bold' : 'normal',
                  color: stationId === s.id ? '#fff' : '#888',
                  background: stationId === s.id ? '#FF6B35' : '#1A3A48',
                  border: stationId === s.id ? '2px solid #FF6B35' : '1px solid #2A4A58',
                  borderRadius: 8, cursor: 'pointer',
                }}
              >
                {s.name}
              </button>
            ))}
            <input
              value={stationId}
              onChange={e => setStationId(e.target.value)}
              placeholder="自定义ID"
              style={{ ...inputStyle, width: 180 }}
            />
          </div>
        </div>

        {/* 声音开关 */}
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: 'block', fontSize: 18, color: '#8899A6', marginBottom: 8 }}>
            声音提示
          </label>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
            <button
              onClick={() => setSoundEnabled(!soundEnabled)}
              style={{
                padding: '12px 28px', minHeight: 56, minWidth: 120,
                fontSize: 20, fontWeight: 'bold',
                color: '#fff',
                background: soundEnabled ? '#0F6E56' : '#A32D2D',
                border: 'none', borderRadius: 8, cursor: 'pointer',
                transition: 'transform 200ms ease',
              }}
              onTouchStart={e => (e.currentTarget.style.transform = 'scale(0.97)')}
              onTouchEnd={e => (e.currentTarget.style.transform = 'scale(1)')}
            >
              {soundEnabled ? '已开启' : '已关闭'}
            </button>

            {/* 试听按钮 */}
            {soundEnabled && (
              <>
                <button
                  onClick={() => testSound('new')}
                  style={{
                    padding: '10px 16px', minHeight: 48,
                    background: '#1A3A48', color: '#0F6E56',
                    border: '1px solid #0F6E56', borderRadius: 6,
                    cursor: 'pointer', fontSize: 16,
                  }}
                >
                  试听: 新订单
                </button>
                <button
                  onClick={() => testSound('rush')}
                  style={{
                    padding: '10px 16px', minHeight: 48,
                    background: '#1A3A48', color: '#BA7517',
                    border: '1px solid #BA7517', borderRadius: 6,
                    cursor: 'pointer', fontSize: 16,
                  }}
                >
                  试听: 催单
                </button>
                <button
                  onClick={() => testSound('timeout')}
                  style={{
                    padding: '10px 16px', minHeight: 48,
                    background: '#1A3A48', color: '#A32D2D',
                    border: '1px solid #A32D2D', borderRadius: 6,
                    cursor: 'pointer', fontSize: 16,
                  }}
                >
                  试听: 超时
                </button>
              </>
            )}
          </div>
        </div>

        {/* 超时阈值 */}
        <div style={{ marginBottom: 20 }}>
          <label style={{ display: 'block', fontSize: 18, color: '#8899A6', marginBottom: 8 }}>
            超时告警阈值（分钟）
          </label>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            <button
              onClick={() => setTimeoutMinutes(m => Math.max(5, m - 5))}
              style={{
                width: 56, height: 56, fontSize: 28, fontWeight: 'bold',
                background: '#1A3A48', color: '#fff', border: '1px solid #2A4A58',
                borderRadius: 8, cursor: 'pointer',
              }}
            >
              -
            </button>
            <span style={{
              fontSize: 36, fontWeight: 'bold', color: '#fff',
              fontFamily: 'JetBrains Mono, monospace',
              minWidth: 80, textAlign: 'center',
            }}>
              {timeoutMinutes}
            </span>
            <button
              onClick={() => setTimeoutMinutes(m => Math.min(60, m + 5))}
              style={{
                width: 56, height: 56, fontSize: 28, fontWeight: 'bold',
                background: '#1A3A48', color: '#fff', border: '1px solid #2A4A58',
                borderRadius: 8, cursor: 'pointer',
              }}
            >
              +
            </button>
            <span style={{ fontSize: 16, color: '#556' }}>
              警告阈值: {Math.max(Math.floor(timeoutMinutes * 0.6), 5)}分钟 / 严重阈值: {timeoutMinutes}分钟
            </span>
          </div>
        </div>

        {/* 保存按钮 */}
        <button
          onClick={saveWsConfig}
          style={{
            width: '100%', padding: '16px 0', minHeight: 56,
            background: configSaved ? '#0F6E56' : '#FF6B35',
            color: '#fff', border: 'none', borderRadius: 8,
            fontSize: 22, fontWeight: 'bold', cursor: 'pointer',
            transition: 'background 300ms ease, transform 200ms ease',
          }}
          onTouchStart={e => (e.currentTarget.style.transform = 'scale(0.97)')}
          onTouchEnd={e => (e.currentTarget.style.transform = 'scale(1)')}
        >
          {configSaved ? '已保存' : '保存配置'}
        </button>
      </div>

      {/* ─── 档口管理 ─── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ margin: 0, fontSize: 24, color: '#fff' }}>档口管理</h2>
        <button onClick={openAdd} style={{
          padding: '10px 24px', background: '#52c41a', color: '#fff',
          border: 'none', borderRadius: 8, cursor: 'pointer', fontSize: 18,
          fontWeight: 'bold', minHeight: 48,
        }}>
          + 新增档口
        </button>
      </div>

      {/* Stall List */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 14 }}>
        {stalls.map(stall => (
          <div key={stall.id} style={{
            background: '#112B36', borderRadius: 12, padding: 20,
            borderLeft: `5px solid ${stall.status === 'online' ? '#52c41a' : '#ff4d4f'}`,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <span style={{ fontSize: 24, fontWeight: 'bold', color: '#fff' }}>{stall.name}</span>
              <span style={{
                fontSize: 16, padding: '4px 10px', borderRadius: 4,
                background: stall.status === 'online' ? '#52c41a22' : '#ff4d4f22',
                color: stall.status === 'online' ? '#52c41a' : '#ff4d4f',
              }}>
                {stall.status === 'online' ? '在线' : '离线'}
              </span>
            </div>

            <div style={{ fontSize: 16, color: '#8899A6', marginBottom: 8 }}>
              关联菜品: <span style={{ color: '#E0C97F', fontWeight: 'bold' }}>{stall.dishCount}</span> 道
            </div>

            <div style={{ fontSize: 16, color: '#666', marginBottom: 14 }}>
              打印机: {stall.printer}
            </div>

            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={() => openEdit(stall)} style={{
                flex: 1, padding: '8px 0', minHeight: 48,
                background: '#1A3A48', color: '#1890ff',
                border: '1px solid #1890ff', borderRadius: 6, cursor: 'pointer', fontSize: 16,
              }}>
                编辑
              </button>
              <button onClick={() => handleDelete(stall.id)} style={{
                flex: 1, padding: '8px 0', minHeight: 48,
                background: '#1A3A48', color: '#ff4d4f',
                border: '1px solid #ff4d4f', borderRadius: 6, cursor: 'pointer', fontSize: 16,
              }}>
                删除
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Edit/Add Modal */}
      {showForm && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
        }}>
          <div style={{ background: '#112B36', borderRadius: 12, padding: 28, width: 420 }}>
            <h2 style={{ margin: '0 0 20px', fontSize: 24, color: '#fff' }}>
              {editing ? '编辑档口' : '新增档口'}
            </h2>

            <div style={{ marginBottom: 16 }}>
              <label style={{ display: 'block', fontSize: 16, color: '#8899A6', marginBottom: 6 }}>档口名称</label>
              <input
                value={formName}
                onChange={e => setFormName(e.target.value)}
                placeholder="如：热菜档口"
                style={inputStyle}
              />
            </div>

            <div style={{ marginBottom: 24 }}>
              <label style={{ display: 'block', fontSize: 16, color: '#8899A6', marginBottom: 6 }}>关联打印机</label>
              <input
                value={formPrinter}
                onChange={e => setFormPrinter(e.target.value)}
                placeholder="如：热菜出品机 (192.168.1.102)"
                style={inputStyle}
              />
            </div>

            <div style={{ display: 'flex', gap: 10 }}>
              <button onClick={handleSave} style={{
                flex: 1, padding: '12px 0', minHeight: 56,
                background: '#1890ff', color: '#fff',
                border: 'none', borderRadius: 8, cursor: 'pointer', fontSize: 18, fontWeight: 'bold',
              }}>
                保存
              </button>
              <button onClick={() => setShowForm(false)} style={{
                flex: 1, padding: '12px 0', minHeight: 56,
                background: '#1A3A48', color: '#aaa',
                border: 'none', borderRadius: 8, cursor: 'pointer', fontSize: 18,
              }}>
                取消
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
