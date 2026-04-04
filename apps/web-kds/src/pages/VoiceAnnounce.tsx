/**
 * VoiceAnnounce — 语音播报管理页
 *
 * 后厨大屏站立操作，利用 Web Speech API 实现新单/催单/超时播报。
 *
 * 设计遵循 Store-KDS 触控规范：
 *   - 所有点击区域 >= 48x48px
 *   - 字体 >= 16px，标题 >= 24px
 *   - 深色主题：背景 #0B1A20，卡片 #112228，高亮 #FF6B35
 *   - 关键操作触发 navigator.vibrate(50)
 *   - 15s 轮询新订单
 */

import { useState, useEffect, useCallback, useRef } from 'react';

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

type AnnounceType = 'new_order' | 'rush' | 'timeout';
type SpeedLevel = 'slow' | 'normal' | 'fast';

interface AnnounceRecord {
  id: string;
  type: AnnounceType;
  content: string;
  time: number; // timestamp ms
  highlight: boolean;
}

interface VoiceConfig {
  enabled: boolean;
  volume: number; // 0-1
  speed: SpeedLevel;
  newOrder: boolean;
  rush: boolean;
  timeout: boolean;
}

// ─── Mock 数据 ────────────────────────────────────────────────────────────────

const MOCK_TABLES = ['A1', 'A2', 'A3', 'B1', 'B2', 'B5', 'C3', 'C7', 'D1', 'D4', 'E6'];
const MOCK_DISHES = ['红烧肉', '清蒸鲈鱼', '宫保鸡丁', '水煮牛肉', '糖醋排骨', '蒜蓉虾', '干锅花菜', '剁椒鱼头'];

function randomPick<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)];
}

function generateMockNewOrder(): { tableNo: string; dishCount: number } {
  return {
    tableNo: randomPick(MOCK_TABLES),
    dishCount: Math.floor(Math.random() * 6) + 1,
  };
}

function generateMockRush(): { tableNo: string; dishName: string; rushCount: number } {
  return {
    tableNo: randomPick(MOCK_TABLES),
    dishName: randomPick(MOCK_DISHES),
    rushCount: Math.floor(Math.random() * 3) + 1,
  };
}

function generateMockTimeout(): { tableNo: string; minutes: number } {
  return {
    tableNo: randomPick(MOCK_TABLES),
    minutes: Math.floor(Math.random() * 20) + 10,
  };
}

// ─── API 调用 ─────────────────────────────────────────────────────────────────

const BASE = 'http://localhost:8001';

interface PendingOrder {
  id: string;
  tableNo: string;
  dishCount: number;
}

interface RushAlert {
  id: string;
  tableNo: string;
  dishName: string;
  rushCount: number;
}

interface TimeoutAlert {
  id: string;
  tableNo: string;
  waitMinutes: number;
}

async function fetchNewOrders(): Promise<PendingOrder[]> {
  try {
    const res = await fetch(`${BASE}/api/v1/kds/orders?status=new`, {
      headers: { 'X-Tenant-ID': 'default' },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    return (json.data?.items ?? []).map((item: Record<string, unknown>) => ({
      id: String(item.id ?? ''),
      tableNo: String(item.table_no ?? ''),
      dishCount: Number(item.dish_count ?? 0),
    }));
  } catch {
    return [];
  }
}

async function fetchRushAlerts(): Promise<RushAlert[]> {
  try {
    const res = await fetch(`${BASE}/api/v1/kds/rush-alerts`, {
      headers: { 'X-Tenant-ID': 'default' },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    return (json.data?.items ?? []).map((item: Record<string, unknown>) => ({
      id: String(item.id ?? ''),
      tableNo: String(item.table_no ?? ''),
      dishName: String(item.dish_name ?? ''),
      rushCount: Number(item.rush_count ?? 0),
    }));
  } catch {
    return [];
  }
}

async function fetchTimeoutAlerts(): Promise<TimeoutAlert[]> {
  try {
    const res = await fetch(`${BASE}/api/v1/kds/timeout-alerts`, {
      headers: { 'X-Tenant-ID': 'default' },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    return (json.data?.items ?? []).map((item: Record<string, unknown>) => ({
      id: String(item.id ?? ''),
      tableNo: String(item.table_no ?? ''),
      waitMinutes: Number(item.wait_minutes ?? 0),
    }));
  } catch {
    return [];
  }
}

// ─── 语速映射 ─────────────────────────────────────────────────────────────────

const SPEED_MAP: Record<SpeedLevel, number> = {
  slow: 0.7,
  normal: 1.0,
  fast: 1.4,
};

const SPEED_LABELS: Record<SpeedLevel, string> = {
  slow: '慢',
  normal: '正常',
  fast: '快',
};

// ─── 颜色常量 ─────────────────────────────────────────────────────────────────

const C = {
  bg: '#0B1A20',
  card: '#112228',
  accent: '#FF6B35',
  green: '#22C55E',
  blue: '#3B82F6',
  orange: '#F59E0B',
  red: '#EF4444',
  white: '#F1F5F9',
  muted: '#94A3B8',
  border: '#1E3A44',
} as const;

// ─── 类型标签配置 ─────────────────────────────────────────────────────────────

const TYPE_CONFIG: Record<AnnounceType, { label: string; color: string; bgColor: string }> = {
  new_order: { label: '新单', color: C.blue, bgColor: 'rgba(59,130,246,0.15)' },
  rush:      { label: '催单', color: C.orange, bgColor: 'rgba(245,158,11,0.15)' },
  timeout:   { label: '超时', color: C.red, bgColor: 'rgba(239,68,68,0.15)' },
};

// ─── 组件 ─────────────────────────────────────────────────────────────────────

export function VoiceAnnounce() {
  const [config, setConfig] = useState<VoiceConfig>({
    enabled: false,
    volume: 0.8,
    speed: 'normal',
    newOrder: true,
    rush: true,
    timeout: true,
  });

  const [history, setHistory] = useState<AnnounceRecord[]>([]);
  const [paused, setPaused] = useState(false);
  const [pauseRemaining, setPauseRemaining] = useState(0);
  const [manualText, setManualText] = useState('');
  const [useMock, setUseMock] = useState(true);

  const seenOrderIdsRef = useRef<Set<string>>(new Set());
  const seenRushIdsRef = useRef<Set<string>>(new Set());
  const seenTimeoutIdsRef = useRef<Set<string>>(new Set());
  const historyRef = useRef<HTMLDivElement>(null);
  const pauseTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const idCounterRef = useRef(0);

  // ─── 语音播报 ────────────────────────────────────────────────────────────

  const speak = useCallback((text: string) => {
    if (!window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    const utt = new SpeechSynthesisUtterance(text);
    utt.lang = 'zh-CN';
    utt.volume = config.volume;
    utt.rate = SPEED_MAP[config.speed];
    window.speechSynthesis.speak(utt);
  }, [config.volume, config.speed]);

  const addRecord = useCallback((type: AnnounceType, content: string) => {
    idCounterRef.current += 1;
    const record: AnnounceRecord = {
      id: `ann-${Date.now()}-${idCounterRef.current}`,
      type,
      content,
      time: Date.now(),
      highlight: true,
    };
    setHistory(prev => {
      const next = [record, ...prev].slice(0, 20);
      return next;
    });
    // 3s 后取消高亮
    setTimeout(() => {
      setHistory(prev => prev.map(r => r.id === record.id ? { ...r, highlight: false } : r));
    }, 3000);

    if (config.enabled && !paused) {
      speak(content);
      if (navigator.vibrate) navigator.vibrate(50);
    }
  }, [config.enabled, paused, speak]);

  // ─── Mock 数据轮询 ──────────────────────────────────────────────────────

  useEffect(() => {
    if (!config.enabled || paused) return;

    const timer = setInterval(() => {
      if (useMock) {
        // Mock: 随机产生事件
        const rand = Math.random();
        if (rand < 0.5 && config.newOrder) {
          const o = generateMockNewOrder();
          addRecord('new_order', `新订单，桌号${o.tableNo}，共${o.dishCount}道菜`);
        } else if (rand < 0.75 && config.rush) {
          const r = generateMockRush();
          addRecord('rush', `催菜提醒，桌号${r.tableNo}，菜品${r.dishName}，已催${r.rushCount}次`);
        } else if (rand < 0.9 && config.timeout) {
          const t = generateMockTimeout();
          addRecord('timeout', `超时预警，桌号${t.tableNo}，已等${t.minutes}分钟`);
        }
      }
    }, 15000);

    return () => clearInterval(timer);
  }, [config.enabled, config.newOrder, config.rush, config.timeout, paused, useMock, addRecord]);

  // ─── 真实 API 轮询 ─────────────────────────────────────────────────────

  useEffect(() => {
    if (!config.enabled || paused || useMock) return;

    const timer = setInterval(async () => {
      if (config.newOrder) {
        const orders = await fetchNewOrders();
        for (const o of orders) {
          if (!seenOrderIdsRef.current.has(o.id)) {
            seenOrderIdsRef.current.add(o.id);
            addRecord('new_order', `新订单，桌号${o.tableNo}，共${o.dishCount}道菜`);
          }
        }
      }
      if (config.rush) {
        const rushes = await fetchRushAlerts();
        for (const r of rushes) {
          if (!seenRushIdsRef.current.has(r.id)) {
            seenRushIdsRef.current.add(r.id);
            addRecord('rush', `催菜提醒，桌号${r.tableNo}，菜品${r.dishName}，已催${r.rushCount}次`);
          }
        }
      }
      if (config.timeout) {
        const timeouts = await fetchTimeoutAlerts();
        for (const t of timeouts) {
          if (!seenTimeoutIdsRef.current.has(t.id)) {
            seenTimeoutIdsRef.current.add(t.id);
            addRecord('timeout', `超时预警，桌号${t.tableNo}，已等${t.waitMinutes}分钟`);
          }
        }
      }
    }, 15000);

    return () => clearInterval(timer);
  }, [config.enabled, config.newOrder, config.rush, config.timeout, paused, useMock, addRecord]);

  // ─── 暂停倒计时 ─────────────────────────────────────────────────────────

  const handlePause = useCallback(() => {
    if (paused) {
      setPaused(false);
      setPauseRemaining(0);
      if (pauseTimerRef.current) clearInterval(pauseTimerRef.current);
      return;
    }
    setPaused(true);
    setPauseRemaining(300);
    pauseTimerRef.current = setInterval(() => {
      setPauseRemaining(prev => {
        if (prev <= 1) {
          setPaused(false);
          if (pauseTimerRef.current) clearInterval(pauseTimerRef.current);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  }, [paused]);

  useEffect(() => {
    return () => {
      if (pauseTimerRef.current) clearInterval(pauseTimerRef.current);
    };
  }, []);

  // ─── 手动播报 ───────────────────────────────────────────────────────────

  const handleManualSpeak = useCallback(() => {
    const text = manualText.trim();
    if (!text) return;
    speak(text);
    addRecord('new_order', text);
    setManualText('');
    if (navigator.vibrate) navigator.vibrate(50);
  }, [manualText, speak, addRecord]);

  // ─── 重播 ───────────────────────────────────────────────────────────────

  const handleReplay = useCallback((content: string) => {
    speak(content);
    if (navigator.vibrate) navigator.vibrate(50);
  }, [speak]);

  // ─── 格式化时间 ─────────────────────────────────────────────────────────

  const formatTime = (ts: number): string => {
    const d = new Date(ts);
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
  };

  const formatPauseTime = (seconds: number): string => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  };

  // ─── 渲染 ───────────────────────────────────────────────────────────────

  return (
    <div style={{
      minHeight: '100vh',
      background: C.bg,
      color: C.white,
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      display: 'flex',
      flexDirection: 'column',
      padding: 16,
      gap: 16,
      boxSizing: 'border-box',
    }}>
      {/* ── 顶部标题 ─────────────────────────────────────────────────── */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}>
        <h1 style={{ fontSize: 28, fontWeight: 700, margin: 0 }}>
          语音播报管理
        </h1>
        <label style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          fontSize: 14,
          color: C.muted,
          cursor: 'pointer',
        }}>
          <input
            type="checkbox"
            checked={useMock}
            onChange={e => setUseMock(e.target.checked)}
            style={{ width: 18, height: 18, cursor: 'pointer' }}
          />
          模拟数据
        </label>
      </div>

      {/* ── 控制区 ───────────────────────────────────────────────────── */}
      <div style={{
        background: C.card,
        borderRadius: 12,
        padding: 20,
        display: 'flex',
        flexWrap: 'wrap',
        gap: 24,
        alignItems: 'center',
      }}>
        {/* 语音开关 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 16, fontWeight: 600 }}>语音</span>
          <button
            onClick={() => setConfig(c => ({ ...c, enabled: !c.enabled }))}
            style={{
              width: 48,
              height: 48,
              borderRadius: 24,
              border: 'none',
              cursor: 'pointer',
              background: config.enabled ? C.green : '#334155',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              position: 'relative',
              overflow: 'visible',
            }}
          >
            <span style={{ fontSize: 22 }}>{config.enabled ? '🔊' : '🔇'}</span>
            {config.enabled && (
              <span style={{
                position: 'absolute',
                inset: -4,
                borderRadius: '50%',
                border: `2px solid ${C.green}`,
                animation: 'pulse-ring 1.5s ease-out infinite',
                pointerEvents: 'none',
              }} />
            )}
          </button>
        </div>

        {/* 音量滑块 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 180 }}>
          <span style={{ fontSize: 16, fontWeight: 600 }}>音量</span>
          <input
            type="range"
            min={0}
            max={100}
            value={Math.round(config.volume * 100)}
            onChange={e => setConfig(c => ({ ...c, volume: Number(e.target.value) / 100 }))}
            style={{
              flex: 1,
              height: 8,
              cursor: 'pointer',
              accentColor: C.accent,
            }}
          />
          <span style={{ fontSize: 14, color: C.muted, minWidth: 36, textAlign: 'right' }}>
            {Math.round(config.volume * 100)}%
          </span>
        </div>

        {/* 语速 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 16, fontWeight: 600 }}>语速</span>
          {(['slow', 'normal', 'fast'] as SpeedLevel[]).map(s => (
            <button
              key={s}
              onClick={() => setConfig(c => ({ ...c, speed: s }))}
              style={{
                minWidth: 56,
                height: 48,
                borderRadius: 8,
                border: `2px solid ${config.speed === s ? C.accent : C.border}`,
                background: config.speed === s ? 'rgba(255,107,53,0.15)' : 'transparent',
                color: config.speed === s ? C.accent : C.muted,
                fontSize: 16,
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              {SPEED_LABELS[s]}
            </button>
          ))}
        </div>

        {/* 播报类型开关 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 16, fontWeight: 600 }}>类型</span>
          {([
            { key: 'newOrder' as const, label: '新单', color: C.blue },
            { key: 'rush' as const, label: '催单', color: C.orange },
            { key: 'timeout' as const, label: '超时', color: C.red },
          ]).map(item => (
            <button
              key={item.key}
              onClick={() => setConfig(c => ({ ...c, [item.key]: !c[item.key] }))}
              style={{
                minWidth: 64,
                height: 48,
                borderRadius: 8,
                border: `2px solid ${config[item.key] ? item.color : C.border}`,
                background: config[item.key] ? `${item.color}22` : 'transparent',
                color: config[item.key] ? item.color : C.muted,
                fontSize: 16,
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {/* ── 播报历史 ─────────────────────────────────────────────────── */}
      <div style={{
        flex: 1,
        background: C.card,
        borderRadius: 12,
        padding: 16,
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0,
        overflow: 'hidden',
      }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 12,
        }}>
          <h2 style={{ fontSize: 20, fontWeight: 600, margin: 0 }}>播报历史</h2>
          <span style={{ fontSize: 14, color: C.muted }}>最近 {history.length} 条</span>
        </div>

        <div
          ref={historyRef}
          style={{
            flex: 1,
            overflowY: 'auto',
            display: 'flex',
            flexDirection: 'column',
            gap: 8,
          }}
        >
          {history.length === 0 ? (
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flex: 1,
              color: C.muted,
              fontSize: 16,
            }}>
              {config.enabled ? '等待新播报...' : '请先开启语音播报'}
            </div>
          ) : (
            history.map(record => {
              const typeConf = TYPE_CONFIG[record.type];
              return (
                <div
                  key={record.id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 12,
                    padding: '12px 16px',
                    borderRadius: 8,
                    background: record.highlight ? 'rgba(255,107,53,0.08)' : 'rgba(255,255,255,0.02)',
                    border: record.highlight ? `1px solid ${C.accent}44` : '1px solid transparent',
                    transition: 'all 0.3s ease',
                  }}
                >
                  <span style={{ fontSize: 14, color: C.muted, whiteSpace: 'nowrap' }}>
                    {formatTime(record.time)}
                  </span>
                  <span style={{
                    fontSize: 13,
                    fontWeight: 600,
                    color: typeConf.color,
                    background: typeConf.bgColor,
                    padding: '4px 10px',
                    borderRadius: 4,
                    whiteSpace: 'nowrap',
                  }}>
                    {typeConf.label}
                  </span>
                  <span style={{ fontSize: 16, flex: 1 }}>{record.content}</span>
                  <button
                    onClick={() => handleReplay(record.content)}
                    style={{
                      minWidth: 48,
                      height: 48,
                      borderRadius: 8,
                      border: `1px solid ${C.border}`,
                      background: 'transparent',
                      color: C.accent,
                      fontSize: 14,
                      fontWeight: 600,
                      cursor: 'pointer',
                    }}
                  >
                    重播
                  </button>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* ── 底部操作 ─────────────────────────────────────────────────── */}
      <div style={{
        background: C.card,
        borderRadius: 12,
        padding: 16,
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        flexWrap: 'wrap',
      }}>
        {/* 手动播报 */}
        <input
          type="text"
          placeholder="输入自定义播报内容..."
          value={manualText}
          onChange={e => setManualText(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') handleManualSpeak(); }}
          style={{
            flex: 1,
            minWidth: 200,
            height: 48,
            borderRadius: 8,
            border: `1px solid ${C.border}`,
            background: C.bg,
            color: C.white,
            fontSize: 16,
            padding: '0 16px',
            outline: 'none',
          }}
        />
        <button
          onClick={handleManualSpeak}
          style={{
            height: 48,
            minWidth: 100,
            borderRadius: 8,
            border: 'none',
            background: C.accent,
            color: '#fff',
            fontSize: 16,
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          手动播报
        </button>

        {/* 暂停按钮 */}
        <button
          onClick={handlePause}
          style={{
            height: 48,
            minWidth: 160,
            borderRadius: 8,
            border: 'none',
            background: paused ? C.orange : C.red,
            color: '#fff',
            fontSize: 16,
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          {paused
            ? `恢复播报 (${formatPauseTime(pauseRemaining)})`
            : '全场暂停 5分钟'
          }
        </button>
      </div>

      {/* ── 脉冲动画 keyframes ────────────────────────────────────────── */}
      <style>{`
        @keyframes pulse-ring {
          0% { transform: scale(1); opacity: 0.6; }
          100% { transform: scale(1.6); opacity: 0; }
        }
      `}</style>
    </div>
  );
}

export default VoiceAnnounce;
