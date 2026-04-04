/**
 * POS 登录页 — 全屏深色主题，触控数字键盘
 * 适配商米 T2/V2 触摸屏
 */
import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';

const STORE_ID = import.meta.env.VITE_STORE_ID || '未配置';
const STORE_NAME = import.meta.env.VITE_STORE_NAME || '屯象门店';

export function LoginPage() {
  const navigate = useNavigate();
  const { login, loading, error } = useAuthStore();

  const [employeeCode, setEmployeeCode] = useState('');
  const [pin, setPin] = useState('');
  const [activeField, setActiveField] = useState<'code' | 'pin'>('code');

  const handleNumPad = useCallback((digit: string) => {
    if (activeField === 'code') {
      setEmployeeCode((prev) => prev + digit);
    } else {
      if (pin.length < 6) {
        setPin((prev) => prev + digit);
      }
    }
  }, [activeField, pin.length]);

  const handleBackspace = useCallback(() => {
    if (activeField === 'code') {
      setEmployeeCode((prev) => prev.slice(0, -1));
    } else {
      setPin((prev) => prev.slice(0, -1));
    }
  }, [activeField]);

  const handleClear = useCallback(() => {
    if (activeField === 'code') {
      setEmployeeCode('');
    } else {
      setPin('');
    }
  }, [activeField]);

  const handleLogin = useCallback(async () => {
    if (!employeeCode.trim() || !pin.trim()) return;
    const success = await login(employeeCode.trim(), pin.trim());
    if (success) {
      navigate('/dashboard', { replace: true });
    }
  }, [employeeCode, pin, login, navigate]);

  const numPadKeys = [
    ['1', '2', '3'],
    ['4', '5', '6'],
    ['7', '8', '9'],
    ['clear', '0', 'back'],
  ];

  return (
    <div
      style={{
        minHeight: '100vh',
        background: '#0B1A20',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        padding: '24px',
      }}
    >
      {/* Brand header */}
      <div style={{ textAlign: 'center', marginBottom: '32px' }}>
        <div
          style={{
            fontSize: '48px',
            fontWeight: 800,
            color: '#FF6B2C',
            letterSpacing: '4px',
            marginBottom: '8px',
          }}
        >
          屯象OS
        </div>
        <div style={{ fontSize: '16px', color: '#6B8A99', letterSpacing: '2px' }}>
          AI-Native 连锁餐饮操作系统
        </div>
      </div>

      {/* Store info */}
      <div
        style={{
          background: '#112228',
          borderRadius: '12px',
          padding: '12px 24px',
          marginBottom: '24px',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
        }}
      >
        <span style={{ color: '#6B8A99', fontSize: '14px' }}>门店</span>
        <span style={{ color: '#E0E7EB', fontSize: '16px', fontWeight: 600 }}>
          {STORE_NAME}
        </span>
        <span style={{ color: '#4A6A78', fontSize: '12px' }}>({STORE_ID})</span>
      </div>

      {/* Login card */}
      <div
        style={{
          background: '#112228',
          borderRadius: '16px',
          padding: '32px',
          width: '100%',
          maxWidth: '420px',
        }}
      >
        {/* Error message */}
        {error && (
          <div
            style={{
              background: 'rgba(239, 68, 68, 0.15)',
              border: '1px solid rgba(239, 68, 68, 0.3)',
              borderRadius: '8px',
              padding: '12px 16px',
              marginBottom: '20px',
              color: '#FCA5A5',
              fontSize: '14px',
              textAlign: 'center',
            }}
          >
            {error}
          </div>
        )}

        {/* Employee code input */}
        <div style={{ marginBottom: '16px' }}>
          <label
            style={{
              display: 'block',
              color: '#6B8A99',
              fontSize: '13px',
              marginBottom: '6px',
              letterSpacing: '1px',
            }}
          >
            工号
          </label>
          <div
            onClick={() => setActiveField('code')}
            style={{
              background: '#0B1A20',
              border: `2px solid ${activeField === 'code' ? '#FF6B2C' : '#1E3A45'}`,
              borderRadius: '10px',
              padding: '14px 16px',
              fontSize: '22px',
              color: '#E0E7EB',
              fontWeight: 600,
              letterSpacing: '4px',
              minHeight: '56px',
              cursor: 'pointer',
              transition: 'border-color 0.15s',
            }}
          >
            {employeeCode || (
              <span style={{ color: '#3A5A68', letterSpacing: '1px', fontWeight: 400 }}>
                请输入工号
              </span>
            )}
          </div>
        </div>

        {/* PIN input */}
        <div style={{ marginBottom: '24px' }}>
          <label
            style={{
              display: 'block',
              color: '#6B8A99',
              fontSize: '13px',
              marginBottom: '6px',
              letterSpacing: '1px',
            }}
          >
            密码 (6位)
          </label>
          <div
            onClick={() => setActiveField('pin')}
            style={{
              background: '#0B1A20',
              border: `2px solid ${activeField === 'pin' ? '#FF6B2C' : '#1E3A45'}`,
              borderRadius: '10px',
              padding: '14px 16px',
              fontSize: '22px',
              minHeight: '56px',
              cursor: 'pointer',
              transition: 'border-color 0.15s',
              display: 'flex',
              gap: '8px',
              alignItems: 'center',
            }}
          >
            {pin.length > 0 ? (
              Array.from({ length: pin.length }).map((_, i) => (
                <div
                  key={i}
                  style={{
                    width: '14px',
                    height: '14px',
                    borderRadius: '50%',
                    background: '#FF6B2C',
                  }}
                />
              ))
            ) : (
              <span style={{ color: '#3A5A68', letterSpacing: '1px', fontWeight: 400, fontSize: '22px' }}>
                ******
              </span>
            )}
          </div>
        </div>

        {/* Number pad */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            gap: '10px',
            marginBottom: '20px',
          }}
        >
          {numPadKeys.flat().map((key) => {
            const isAction = key === 'clear' || key === 'back';
            return (
              <button
                key={key}
                onClick={() => {
                  if (key === 'clear') handleClear();
                  else if (key === 'back') handleBackspace();
                  else handleNumPad(key);
                }}
                disabled={loading}
                style={{
                  width: '100%',
                  height: '80px',
                  borderRadius: '12px',
                  border: 'none',
                  background: isAction ? '#1E3A45' : '#172F38',
                  color: isAction ? '#6B8A99' : '#E0E7EB',
                  fontSize: isAction ? '16px' : '28px',
                  fontWeight: isAction ? 500 : 700,
                  cursor: loading ? 'not-allowed' : 'pointer',
                  transition: 'background 0.1s, transform 0.08s',
                  userSelect: 'none',
                  WebkitTapHighlightColor: 'transparent',
                }}
                onPointerDown={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.95)';
                  (e.currentTarget as HTMLButtonElement).style.background = isAction
                    ? '#2A4D5A'
                    : '#1E3A45';
                }}
                onPointerUp={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)';
                  (e.currentTarget as HTMLButtonElement).style.background = isAction
                    ? '#1E3A45'
                    : '#172F38';
                }}
                onPointerLeave={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)';
                  (e.currentTarget as HTMLButtonElement).style.background = isAction
                    ? '#1E3A45'
                    : '#172F38';
                }}
              >
                {key === 'clear' ? '清除' : key === 'back' ? '退格' : key}
              </button>
            );
          })}
        </div>

        {/* Login button */}
        <button
          onClick={handleLogin}
          disabled={loading || !employeeCode.trim() || !pin.trim()}
          style={{
            width: '100%',
            height: '60px',
            borderRadius: '12px',
            border: 'none',
            background:
              loading || !employeeCode.trim() || !pin.trim()
                ? '#3A2A1E'
                : '#FF6B2C',
            color:
              loading || !employeeCode.trim() || !pin.trim()
                ? '#7A5A3E'
                : '#FFFFFF',
            fontSize: '20px',
            fontWeight: 700,
            cursor:
              loading || !employeeCode.trim() || !pin.trim()
                ? 'not-allowed'
                : 'pointer',
            letterSpacing: '4px',
            transition: 'background 0.15s',
          }}
        >
          {loading ? '登录中...' : '登 录'}
        </button>
      </div>

      {/* Footer */}
      <div
        style={{
          marginTop: '32px',
          color: '#3A5A68',
          fontSize: '12px',
          textAlign: 'center',
        }}
      >
        屯象科技 (湖南) &copy; {new Date().getFullYear()}
      </div>
    </div>
  );
}
