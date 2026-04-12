/**
 * KDS 登录页 — 后厨大屏触控，字体加大，按钮超大
 * 厨师戴手套操作，最小点击区域 72px
 */
import { useState, FormEvent } from 'react';
import { setStoreToken } from '../api/index';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

interface KdsLoginPageProps {
  onLogin: () => void;
}

export function KdsLoginPage({ onLogin }: KdsLoginPageProps) {
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
      setError('网络错误');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      minHeight: '100vh',
      background: '#060E10',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: '-apple-system, "PingFang SC", sans-serif',
    }}>
      <div style={{
        width: 560,
        background: '#0D1F27',
        borderRadius: 24,
        padding: '56px 48px',
        boxShadow: '0 8px 64px rgba(0,0,0,0.6)',
      }}>
        <div style={{ textAlign: 'center', marginBottom: 48 }}>
          <div style={{
            width: 72, height: 72, borderRadius: 18,
            background: 'linear-gradient(135deg, #FF6B2C, #FF8F5E)',
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 28, fontWeight: 900, color: '#fff', marginBottom: 20,
          }}>KDS</div>
          <div style={{ fontSize: 28, fontWeight: 700, color: '#fff' }}>后厨出餐系统</div>
          <div style={{ fontSize: 18, color: 'rgba(255,255,255,0.4)', marginTop: 8 }}>请登录以启动工作站</div>
        </div>

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 20 }}>
            <input
              type="text"
              placeholder="账号"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
              style={{
                width: '100%', height: 64, padding: '0 20px',
                borderRadius: 14, border: '1.5px solid rgba(255,255,255,0.12)',
                background: 'rgba(255,255,255,0.06)', color: '#fff',
                fontSize: 22, outline: 'none', boxSizing: 'border-box',
              }}
            />
          </div>

          <div style={{ marginBottom: 28 }}>
            <input
              type="password"
              placeholder="密码"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={{
                width: '100%', height: 64, padding: '0 20px',
                borderRadius: 14, border: '1.5px solid rgba(255,255,255,0.12)',
                background: 'rgba(255,255,255,0.06)', color: '#fff',
                fontSize: 22, outline: 'none', boxSizing: 'border-box',
              }}
            />
          </div>

          {error && (
            <div style={{
              marginBottom: 20, padding: '14px 18px', borderRadius: 12,
              background: 'rgba(163,45,45,0.15)', border: '1px solid rgba(163,45,45,0.4)',
              color: '#f87171', fontSize: 18, textAlign: 'center',
            }}>{error}</div>
          )}

          <button
            type="submit"
            disabled={loading || !username || !password}
            style={{
              width: '100%', height: 80, borderRadius: 16, border: 'none',
              background: (!loading && username && password)
                ? 'linear-gradient(135deg, #FF6B2C, #FF8F5E)'
                : 'rgba(255,107,44,0.2)',
              color: '#fff', fontSize: 24, fontWeight: 700,
              cursor: (!loading && username && password) ? 'pointer' : 'not-allowed',
              letterSpacing: 4,
              transition: 'transform 200ms',
            }}
            onPointerDown={(e) => { if (!loading) (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)'; }}
            onPointerUp={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
          >
            {loading ? '登录中...' : '开始工作'}
          </button>
        </form>
      </div>
    </div>
  );
}
