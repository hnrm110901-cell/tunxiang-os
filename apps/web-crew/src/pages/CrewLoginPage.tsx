/**
 * 服务员端登录页 — 竖屏手机 PWA，单手拇指操作
 * 符合 TXTouch 规范：56px 按钮，18px 字体
 */
import { useState, FormEvent } from 'react';
import { setStoreToken } from '../api/index';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

interface CrewLoginPageProps {
  onLogin: () => void;
}

export function CrewLoginPage({ onLogin }: CrewLoginPageProps) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      const json = await res.json();
      if (json.ok) {
        setStoreToken(json.data.token);
        onLogin();
      } else {
        setError(json.error?.message || '账号或密码错误');
      }
    } catch {
      setError('网络错误，请检查连接');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      minHeight: '100vh',
      background: '#0B1A20',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '0 24px',
      fontFamily: '-apple-system, "PingFang SC", sans-serif',
    }}>
      {/* 品牌区 */}
      <div style={{ textAlign: 'center', marginBottom: 48 }}>
        <div style={{
          width: 64, height: 64, borderRadius: 16,
          background: 'linear-gradient(135deg, #FF6B2C, #FF8F5E)',
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 22, fontWeight: 900, color: '#fff', marginBottom: 16,
        }}>TX</div>
        <div style={{ fontSize: 22, fontWeight: 700, color: '#fff' }}>屯象服务员</div>
        <div style={{ fontSize: 16, color: 'rgba(255,255,255,0.4)', marginTop: 6 }}>登录开始今日服务</div>
      </div>

      {/* 表单 */}
      <form onSubmit={handleSubmit} style={{ width: '100%', maxWidth: 360 }}>
        <div style={{ marginBottom: 14 }}>
          <input
            type="text"
            placeholder="工号 / 账号"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoFocus
            autoComplete="username"
            style={{
              width: '100%', height: 56, padding: '0 16px',
              borderRadius: 14, border: '1.5px solid rgba(255,255,255,0.1)',
              background: 'rgba(255,255,255,0.05)', color: '#fff',
              fontSize: 18, outline: 'none', boxSizing: 'border-box',
              WebkitAppearance: 'none',
            }}
          />
        </div>

        <div style={{ marginBottom: 24 }}>
          <input
            type="password"
            placeholder="密码"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            style={{
              width: '100%', height: 56, padding: '0 16px',
              borderRadius: 14, border: '1.5px solid rgba(255,255,255,0.1)',
              background: 'rgba(255,255,255,0.05)', color: '#fff',
              fontSize: 18, outline: 'none', boxSizing: 'border-box',
              WebkitAppearance: 'none',
            }}
          />
        </div>

        {error && (
          <div style={{
            marginBottom: 16, padding: '12px 16px', borderRadius: 10,
            background: 'rgba(163,45,45,0.15)', border: '1px solid rgba(163,45,45,0.3)',
            color: '#f87171', fontSize: 16, textAlign: 'center',
          }}>{error}</div>
        )}

        {/* 登录按钮 — 拇指可达区，56px */}
        <button
          type="submit"
          disabled={loading || !username || !password}
          style={{
            width: '100%', height: 56, borderRadius: 14, border: 'none',
            background: (!loading && username && password)
              ? 'linear-gradient(135deg, #FF6B2C, #FF8F5E)'
              : 'rgba(255,107,44,0.25)',
            color: '#fff', fontSize: 18, fontWeight: 700,
            cursor: (!loading && username && password) ? 'pointer' : 'not-allowed',
            letterSpacing: 2, WebkitTapHighlightColor: 'transparent',
            transition: 'transform 150ms',
            active: { transform: 'scale(0.97)' },
          } as React.CSSProperties}
          onPointerDown={(e) => { if (!loading) (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)'; }}
          onPointerUp={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
          onPointerLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
        >
          {loading ? '登录中...' : '开始工作'}
        </button>
      </form>
    </div>
  );
}
