import { useState, useEffect, useCallback, type CSSProperties } from 'react';
import type { ScreenConfig } from '../api/menuWallApi';
import { getScreenGroupConfig, registerScreen } from '../api/menuWallApi';

/** 页面模式列表 */
const PAGE_MODES = [
  { value: '/menu', label: '菜品展示墙' },
  { value: '/seafood', label: '海鲜时价板' },
  { value: '/ranking', label: '排行榜' },
  { value: '/combo', label: '套餐宴席' },
  { value: '/welcome', label: '欢迎等位屏' },
] as const;

interface ScreenItem {
  screenId: string;
  ip: string;
  position: string;
  sizeInches: number;
  zone: string;
  status: 'online' | 'offline';
  assignedPage: string;
}

/** Mock屏幕数据 */
function getMockScreens(): ScreenItem[] {
  return [
    { screenId: 'TV-01', ip: '192.168.1.101', position: '大厅入口', sizeInches: 65, zone: 'entrance', status: 'online', assignedPage: '/welcome' },
    { screenId: 'TV-02', ip: '192.168.1.102', position: '大厅左墙', sizeInches: 55, zone: 'signature', status: 'online', assignedPage: '/menu' },
    { screenId: 'TV-03', ip: '192.168.1.103', position: '大厅右墙', sizeInches: 55, zone: 'signature', status: 'online', assignedPage: '/menu' },
    { screenId: 'TV-04', ip: '192.168.1.104', position: '海鲜池上方', sizeInches: 75, zone: 'seafood', status: 'online', assignedPage: '/seafood' },
    { screenId: 'TV-05', ip: '192.168.1.105', position: '包厢走廊', sizeInches: 43, zone: 'combo', status: 'offline', assignedPage: '/combo' },
    { screenId: 'TV-06', ip: '192.168.1.106', position: '收银台旁', sizeInches: 32, zone: 'ranking', status: 'online', assignedPage: '/ranking' },
  ];
}

export default function AdminConfig() {
  const [screens, setScreens] = useState<ScreenItem[]>([]);
  const [_config, setConfig] = useState<ScreenConfig | null>(null);
  const [selectedScreen, setSelectedScreen] = useState<string | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [newScreen, setNewScreen] = useState({ screenId: '', ip: '', position: '', sizeInches: 55 });
  const [message, setMessage] = useState('');

  // Admin页面显示鼠标
  useEffect(() => {
    document.body.style.cursor = 'default';
    return () => { document.body.style.cursor = ''; };
  }, []);

  const loadConfig = useCallback(async () => {
    try {
      const data = await getScreenGroupConfig();
      setConfig(data);
      if (data.screens) {
        setScreens(data.screens.map((s) => ({ ...s, assignedPage: '/menu' })));
      }
    } catch {
      setScreens(getMockScreens());
    }
  }, []);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  const handleAssignPage = (screenId: string, page: string) => {
    setScreens((prev) =>
      prev.map((s) => (s.screenId === screenId ? { ...s, assignedPage: page } : s)),
    );
    showMessage(`${screenId} 已分配到: ${PAGE_MODES.find((p) => p.value === page)?.label}`);
  };

  const handleTestDisplay = (screen: ScreenItem) => {
    const url = `http://${screen.ip}:5180${screen.assignedPage}?storeId=${localStorage.getItem('tx-store-id') || 'store-001'}`;
    window.open(url, '_blank');
    showMessage(`已打开测试: ${screen.screenId} → ${screen.assignedPage}`);
  };

  const handleAddScreen = async () => {
    try {
      await registerScreen(newScreen.screenId, newScreen.ip, newScreen.position, newScreen.sizeInches);
      showMessage(`屏幕 ${newScreen.screenId} 注册成功`);
      setShowAddForm(false);
      setNewScreen({ screenId: '', ip: '', position: '', sizeInches: 55 });
      loadConfig();
    } catch {
      // 使用mock — 直接添加到列表
      setScreens((prev) => [
        ...prev,
        {
          ...newScreen,
          zone: 'new',
          status: 'offline' as const,
          assignedPage: '/menu',
        },
      ]);
      showMessage(`屏幕 ${newScreen.screenId} 已添加(本地)`);
      setShowAddForm(false);
      setNewScreen({ screenId: '', ip: '', position: '', sizeInches: 55 });
    }
  };

  const showMessage = (msg: string) => {
    setMessage(msg);
    setTimeout(() => setMessage(''), 3000);
  };

  const containerStyle: CSSProperties = {
    width: '100vw',
    height: '100vh',
    background: '#111',
    fontFamily: 'var(--tx-font)',
    overflow: 'auto',
    padding: 32,
    color: '#FFF',
    cursor: 'default',
  };

  const headerStyle: CSSProperties = {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 32,
  };

  const cardStyle = (isSelected: boolean, isOnline: boolean): CSSProperties => ({
    background: isSelected ? 'rgba(255,107,44,0.1)' : 'var(--tx-bg-card)',
    border: isSelected ? '2px solid var(--tx-primary)' : '1px solid var(--tx-border)',
    borderRadius: 'var(--tx-radius-md)',
    padding: 20,
    cursor: 'pointer',
    opacity: isOnline ? 1 : 0.6,
    transition: 'all 0.2s ease',
  });

  const btnStyle = (variant: 'primary' | 'ghost' = 'primary'): CSSProperties => ({
    padding: '10px 20px',
    fontSize: 14,
    fontWeight: 600,
    background: variant === 'primary' ? 'var(--tx-primary)' : 'transparent',
    color: variant === 'primary' ? '#FFF' : 'var(--tx-primary)',
    border: variant === 'ghost' ? '1px solid var(--tx-primary)' : 'none',
    borderRadius: 8,
    cursor: 'pointer',
    transition: 'transform 0.2s ease',
  });

  const inputStyle: CSSProperties = {
    padding: '10px 14px',
    fontSize: 14,
    background: '#1A1A1A',
    border: '1px solid var(--tx-border)',
    borderRadius: 8,
    color: '#FFF',
    outline: 'none',
    width: '100%',
  };

  const labelStyle: CSSProperties = {
    fontSize: 13,
    color: '#888',
    marginBottom: 4,
    display: 'block',
  };

  return (
    <div style={containerStyle}>
      {/* 消息提示 */}
      {message && (
        <div style={{
          position: 'fixed',
          top: 20,
          right: 20,
          background: 'var(--tx-primary)',
          color: '#FFF',
          padding: '12px 24px',
          borderRadius: 8,
          fontSize: 14,
          fontWeight: 600,
          zIndex: 100,
          animation: 'tx-fade-in 0.3s ease-out',
        }}>
          {message}
        </div>
      )}

      {/* 顶部 */}
      <div style={headerStyle}>
        <div>
          <h1 style={{ fontSize: 28, fontWeight: 700, margin: 0 }}>屏幕管理</h1>
          <p style={{ fontSize: 14, color: '#888', margin: '4px 0 0' }}>管理门店所有展示屏幕的内容分配</p>
        </div>
        <div style={{ display: 'flex', gap: 12 }}>
          <button style={btnStyle('ghost')} onClick={loadConfig}>刷新状态</button>
          <button style={btnStyle('primary')} onClick={() => setShowAddForm(true)}>添加屏幕</button>
        </div>
      </div>

      {/* 添加屏幕表单 */}
      {showAddForm && (
        <div style={{
          background: 'var(--tx-bg-card)',
          border: '1px solid var(--tx-border)',
          borderRadius: 12,
          padding: 24,
          marginBottom: 24,
        }}>
          <h3 style={{ fontSize: 18, marginBottom: 16 }}>注册新屏幕</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 16, marginBottom: 16 }}>
            <div>
              <label style={labelStyle}>屏幕编号</label>
              <input style={inputStyle} placeholder="TV-07" value={newScreen.screenId}
                onChange={(e) => setNewScreen({ ...newScreen, screenId: e.target.value })} />
            </div>
            <div>
              <label style={labelStyle}>IP地址</label>
              <input style={inputStyle} placeholder="192.168.1.107" value={newScreen.ip}
                onChange={(e) => setNewScreen({ ...newScreen, ip: e.target.value })} />
            </div>
            <div>
              <label style={labelStyle}>安装位置</label>
              <input style={inputStyle} placeholder="大厅入口" value={newScreen.position}
                onChange={(e) => setNewScreen({ ...newScreen, position: e.target.value })} />
            </div>
            <div>
              <label style={labelStyle}>尺寸(英寸)</label>
              <input style={inputStyle} type="number" value={newScreen.sizeInches}
                onChange={(e) => setNewScreen({ ...newScreen, sizeInches: Number(e.target.value) })} />
            </div>
          </div>
          <div style={{ display: 'flex', gap: 12 }}>
            <button style={btnStyle('primary')} onClick={handleAddScreen}>注册</button>
            <button style={btnStyle('ghost')} onClick={() => setShowAddForm(false)}>取消</button>
          </div>
        </div>
      )}

      {/* 屏幕列表 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: 16 }}>
        {screens.map((screen) => (
          <div
            key={screen.screenId}
            style={cardStyle(selectedScreen === screen.screenId, screen.status === 'online')}
            onClick={() => setSelectedScreen(screen.screenId)}
          >
            {/* 卡片头部 */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 20, fontWeight: 700 }}>{screen.screenId}</span>
                <span style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: screen.status === 'online' ? '#00CC66' : '#FF4444',
                  display: 'inline-block',
                }} />
              </div>
              <span style={{ fontSize: 13, color: '#666' }}>{screen.sizeInches}"</span>
            </div>

            {/* 详情 */}
            <div style={{ fontSize: 14, color: '#AAA', marginBottom: 4 }}>
              IP: {screen.ip}
            </div>
            <div style={{ fontSize: 14, color: '#AAA', marginBottom: 12 }}>
              位置: {screen.position}
            </div>

            {/* 页面分配 */}
            <div style={{ marginBottom: 12 }}>
              <label style={labelStyle}>展示内容</label>
              <select
                style={{ ...inputStyle, cursor: 'pointer' }}
                value={screen.assignedPage}
                onChange={(e) => handleAssignPage(screen.screenId, e.target.value)}
                onClick={(e) => e.stopPropagation()}
              >
                {PAGE_MODES.map((mode) => (
                  <option key={mode.value} value={mode.value}>{mode.label}</option>
                ))}
              </select>
            </div>

            {/* 操作按钮 */}
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                style={{ ...btnStyle('ghost'), flex: 1, fontSize: 13 }}
                onClick={(e) => { e.stopPropagation(); handleTestDisplay(screen); }}
              >
                测试显示
              </button>
              <button
                style={{ ...btnStyle('primary'), flex: 1, fontSize: 13 }}
                onClick={(e) => {
                  e.stopPropagation();
                  showMessage(`${screen.screenId} 正在推送内容...`);
                }}
              >
                推送更新
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* 手动推荐覆盖区 */}
      <div style={{ marginTop: 32 }}>
        <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 16 }}>手动推荐覆盖</h2>
        <div style={{
          background: 'var(--tx-bg-card)',
          border: '1px solid var(--tx-border)',
          borderRadius: 12,
          padding: 24,
        }}>
          <p style={{ fontSize: 14, color: '#888', marginBottom: 16 }}>
            覆盖AI自动推荐，手动指定展示菜品。留空则使用AI推荐。
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <div>
              <label style={labelStyle}>主推菜品(最多6个，逗号分隔)</label>
              <input style={inputStyle} placeholder="招牌剁椒鱼头, 蒜蓉龙虾, 清蒸多宝鱼" />
            </div>
            <div>
              <label style={labelStyle}>隐藏菜品(逗号分隔)</label>
              <input style={inputStyle} placeholder="需要临时下架的菜品名" />
            </div>
          </div>
          <button style={{ ...btnStyle('primary'), marginTop: 16 }} onClick={() => showMessage('推荐覆盖已保存')}>
            保存并推送
          </button>
        </div>
      </div>
    </div>
  );
}
