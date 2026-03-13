import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Form, Input, message } from 'antd';
import {
  UserOutlined,
  LockOutlined,
  LoginOutlined,
  RocketOutlined,
  WechatOutlined,
  MobileOutlined,
  SafetyOutlined,
  QrcodeOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { useAuth } from '../contexts/AuthContext';
import { useNavigate, useSearchParams } from 'react-router-dom';
import axios from 'axios';
import styles from './LoginPage.module.css';

// ── 登录方式 Tab ──────────────────────────────────────────
type LoginTab = 'password' | 'phone' | 'qrcode';

const LOGIN_TABS: { key: LoginTab; label: string; icon: React.ReactNode }[] = [
  { key: 'password', label: '密码登录', icon: <LockOutlined /> },
  { key: 'phone', label: '手机登录', icon: <MobileOutlined /> },
  { key: 'qrcode', label: '扫码登录', icon: <QrcodeOutlined /> },
];

const LoginPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<LoginTab>('password');
  const [loading, setLoading] = useState(false);
  const { login, setToken } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  // ── OAuth 回调处理 ────────────────────────────────────
  useEffect(() => {
    const code = searchParams.get('code');
    const authCode = searchParams.get('auth_code');
    const state = searchParams.get('state');
    const provider = searchParams.get('provider');

    if ((code || authCode) && provider) {
      handleOAuthCallback(provider, code, authCode, state);
    }
  }, [searchParams]);

  const handleOAuthCallback = async (
    provider: string,
    code: string | null,
    authCode: string | null,
    state: string | null
  ) => {
    setLoading(true);
    try {
      const endpoint = `/api/auth/oauth/${provider}/callback`;
      const payload =
        provider === 'dingtalk'
          ? { auth_code: authCode, state }
          : { code, state };

      const response = await axios.post(endpoint, payload);

      if (response.data.access_token) {
        setToken(response.data.access_token, response.data.refresh_token);
        message.success('登录成功！');
        setTimeout(() => navigate(state || '/'), 500);
      }
    } catch {
      message.error('OAuth登录失败，请重试');
      navigate('/login', { replace: true });
    } finally {
      setLoading(false);
    }
  };

  const handleOAuthLogin = (provider: string) => {
    const state = searchParams.get('redirect') || '/';
    const redirectUri = `${window.location.origin}/login?provider=${provider}`;
    let authUrl = '';

    if (provider === 'wechat-work') {
      const appId = import.meta.env.VITE_WECHAT_WORK_CORP_ID || 'YOUR_CORP_ID';
      authUrl = `https://open.weixin.qq.com/connect/oauth2/authorize?appid=${appId}&redirect_uri=${encodeURIComponent(redirectUri)}&response_type=code&scope=snsapi_base&state=${state}#wechat_redirect`;
    } else if (provider === 'feishu') {
      const appId = import.meta.env.VITE_FEISHU_APP_ID || 'YOUR_APP_ID';
      authUrl = `https://open.feishu.cn/open-apis/authen/v1/index?app_id=${appId}&redirect_uri=${encodeURIComponent(redirectUri)}&state=${state}`;
    } else if (provider === 'dingtalk') {
      const appId = import.meta.env.VITE_DINGTALK_APP_KEY || 'YOUR_APP_KEY';
      authUrl = `https://oapi.dingtalk.com/connect/oauth2/sns_authorize?appid=${appId}&response_type=code&scope=snsapi_login&state=${state}&redirect_uri=${encodeURIComponent(redirectUri)}`;
    }

    if (authUrl) window.location.href = authUrl;
  };

  // ── 密码登录 ──────────────────────────────────────────
  const onPasswordFinish = async (values: { username: string; password: string }) => {
    setLoading(true);
    try {
      const success = await login(values.username, values.password);
      if (success) {
        message.success('登录成功！');
        setTimeout(() => navigate(searchParams.get('redirect') || '/'), 500);
      } else {
        message.error('登录失败，请检查用户名和密码');
      }
    } catch {
      message.error('登录失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  };

  const quickLogin = (username: string, password: string) => {
    onPasswordFinish({ username, password });
  };

  return (
    <div className={styles.page}>
      {/* 背景装饰 */}
      <div className={`${styles.blob} ${styles.blobTopRight}`} />
      <div className={`${styles.blob} ${styles.blobBottomLeft}`} />

      <div className={styles.card}>
        {/* Logo 区 */}
        <div className={styles.header}>
          <div className={styles.emoji}>🍜</div>
          <h1 className={styles.brand}>屯象OS</h1>
          <p className={styles.subtitle}>
            <RocketOutlined /> 餐饮人的好伙伴
          </p>
        </div>

        {/* Tab 切换 */}
        <div className={styles.tabBar}>
          {LOGIN_TABS.map((tab) => (
            <button
              key={tab.key}
              className={`${styles.tab} ${activeTab === tab.key ? styles.tabActive : ''}`}
              onClick={() => setActiveTab(tab.key)}
            >
              {tab.icon} {tab.label}
            </button>
          ))}
        </div>

        {/* Tab 内容 */}
        <div className={styles.tabContent}>
          {activeTab === 'password' && (
            <PasswordForm
              loading={loading}
              onFinish={onPasswordFinish}
            />
          )}
          {activeTab === 'phone' && (
            <PhoneForm
              loading={loading}
              setLoading={setLoading}
              setToken={setToken}
              navigate={navigate}
              redirectPath={searchParams.get('redirect') || '/'}
            />
          )}
          {activeTab === 'qrcode' && (
            <QRCodeForm
              setToken={setToken}
              navigate={navigate}
              redirectPath={searchParams.get('redirect') || '/'}
            />
          )}
        </div>

        {/* 企业账号登录 */}
        <div className={styles.divider}>
          <span>企业账号登录</span>
        </div>

        <div className={styles.oauthList}>
          <button
            className={styles.oauthBtn}
            style={{ background: '#07c160' }}
            onClick={() => handleOAuthLogin('wechat-work')}
          >
            <WechatOutlined /> 企业微信登录
          </button>
          <button
            className={styles.oauthBtn}
            style={{ background: '#00b96b' }}
            onClick={() => handleOAuthLogin('feishu')}
          >
            🪶 飞书登录
          </button>
          <button
            className={styles.oauthBtn}
            style={{ background: '#0089ff' }}
            onClick={() => handleOAuthLogin('dingtalk')}
          >
            💼 钉钉登录
          </button>
        </div>

        {/* 快速登录 - 仅开发环境 */}
        {import.meta.env.DEV && (
          <>
            <div className={styles.divider}>
              <span>开发环境快速登录</span>
            </div>
            <div className={styles.quickList}>
              <button
                className={styles.quickCard}
                style={{ background: 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)' }}
                onClick={() => quickLogin('admin', 'admin123')}
              >
                <div>
                  <div className={styles.quickName}>👑 管理员</div>
                  <div className={styles.quickCred}>admin / admin123</div>
                </div>
                <LoginOutlined style={{ fontSize: 20 }} />
              </button>
              <button
                className={styles.quickCard}
                style={{ background: 'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)' }}
                onClick={() => quickLogin('manager001', 'manager123')}
              >
                <div>
                  <div className={styles.quickName}>💼 店长</div>
                  <div className={styles.quickCred}>manager001 / manager123</div>
                </div>
                <LoginOutlined style={{ fontSize: 20 }} />
              </button>
              <button
                className={styles.quickCard}
                style={{ background: 'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)' }}
                onClick={() => quickLogin('waiter001', 'waiter123')}
              >
                <div>
                  <div className={styles.quickName}>👤 服务员</div>
                  <div className={styles.quickCred}>waiter001 / waiter123</div>
                </div>
                <LoginOutlined style={{ fontSize: 20 }} />
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

// ══════════════════════════════════════════════════════════════
//  密码登录表单
// ══════════════════════════════════════════════════════════════
const PasswordForm: React.FC<{
  loading: boolean;
  onFinish: (values: { username: string; password: string }) => void;
}> = ({ loading, onFinish }) => (
  <Form name="login" onFinish={onFinish} autoComplete="off" size="large">
    <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
      <Input
        prefix={<UserOutlined style={{ color: '#0AAF9A' }} />}
        placeholder="用户名"
        style={{ borderRadius: 8 }}
      />
    </Form.Item>
    <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
      <Input.Password
        prefix={<LockOutlined style={{ color: '#0AAF9A' }} />}
        placeholder="密码"
        style={{ borderRadius: 8 }}
      />
    </Form.Item>
    <Form.Item>
      <button type="submit" className={styles.submitBtn} disabled={loading}>
        <LoginOutlined />
        {loading ? '登录中...' : '登录'}
      </button>
    </Form.Item>
  </Form>
);

// ══════════════════════════════════════════════════════════════
//  手机验证码登录表单
// ══════════════════════════════════════════════════════════════
const PhoneForm: React.FC<{
  loading: boolean;
  setLoading: (v: boolean) => void;
  setToken: (accessToken: string, refreshToken: string) => Promise<void>;
  navigate: (path: string) => void;
  redirectPath: string;
}> = ({ loading, setLoading, setToken, navigate, redirectPath }) => {
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [countdown, setCountdown] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const startCountdown = () => {
    setCountdown(60);
    timerRef.current = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          if (timerRef.current) clearInterval(timerRef.current);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  };

  const handleSendCode = async () => {
    if (!phone || phone.length !== 11) {
      message.warning('请输入正确的11位手机号');
      return;
    }
    try {
      await axios.post('/api/v1/auth/sms/send', { phone });
      message.success('验证码已发送');
      startCountdown();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || '验证码发送失败';
      message.error(detail);
    }
  };

  const handleSubmit = async () => {
    if (!phone || phone.length !== 11) {
      message.warning('请输入正确的11位手机号');
      return;
    }
    if (!code || code.length !== 6) {
      message.warning('请输入6位验证码');
      return;
    }

    setLoading(true);
    try {
      const response = await axios.post('/api/v1/auth/sms/login', { phone, code });
      if (response.data.access_token) {
        await setToken(response.data.access_token, response.data.refresh_token);
        message.success('登录成功！');
        setTimeout(() => navigate(redirectPath), 500);
      }
    } catch (err: any) {
      const detail = err?.response?.data?.detail || '登录失败';
      message.error(detail);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={styles.phoneForm}>
      <div className={styles.phoneInputRow}>
        <span className={styles.phonePrefix}>+86</span>
        <input
          className={styles.phoneInput}
          type="tel"
          placeholder="请输入手机号"
          maxLength={11}
          value={phone}
          onChange={(e) => setPhone(e.target.value.replace(/\D/g, ''))}
        />
      </div>

      <div className={styles.codeInputRow}>
        <input
          className={styles.codeInput}
          type="text"
          placeholder="6位验证码"
          maxLength={6}
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
        />
        <button
          className={styles.sendCodeBtn}
          disabled={countdown > 0}
          onClick={handleSendCode}
        >
          {countdown > 0 ? `${countdown}s` : '获取验证码'}
        </button>
      </div>

      <button
        className={styles.submitBtn}
        disabled={loading}
        onClick={handleSubmit}
      >
        <SafetyOutlined />
        {loading ? '登录中...' : '验证码登录'}
      </button>
    </div>
  );
};

// ══════════════════════════════════════════════════════════════
//  扫码登录
// ══════════════════════════════════════════════════════════════
const QRCodeForm: React.FC<{
  setToken: (accessToken: string, refreshToken: string) => Promise<void>;
  navigate: (path: string) => void;
  redirectPath: string;
}> = ({ setToken, navigate, redirectPath }) => {
  const [qrUrl, setQrUrl] = useState('');
  const [qrId, setQrId] = useState('');
  const [qrStatus, setQrStatus] = useState<'loading' | 'pending' | 'scanned' | 'confirmed' | 'expired'>('loading');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const expireRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cleanup = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (expireRef.current) {
      clearTimeout(expireRef.current);
      expireRef.current = null;
    }
  }, []);

  const generateQR = useCallback(async () => {
    cleanup();
    setQrStatus('loading');

    try {
      const response = await axios.post('/api/v1/auth/qr/generate');
      const { qr_id, qr_url, expires_in } = response.data;
      setQrId(qr_id);
      setQrUrl(qr_url);
      setQrStatus('pending');

      // 开始轮询
      pollRef.current = setInterval(async () => {
        try {
          const statusResp = await axios.get(`/api/v1/auth/qr/status/${qr_id}`);
          const { status: s } = statusResp.data;

          if (s === 'scanned') {
            setQrStatus('scanned');
          } else if (s === 'confirmed') {
            cleanup();
            setQrStatus('confirmed');
            await setToken(statusResp.data.access_token, statusResp.data.refresh_token);
            message.success('扫码登录成功！');
            setTimeout(() => navigate(redirectPath), 500);
          } else if (s === 'expired') {
            cleanup();
            setQrStatus('expired');
          }
        } catch {
          // 轮询异常忽略
        }
      }, 2000);

      // 超时自动过期
      expireRef.current = setTimeout(() => {
        cleanup();
        setQrStatus('expired');
      }, (expires_in || 300) * 1000);
    } catch {
      message.error('QR 码生成失败');
      setQrStatus('expired');
    }
  }, [cleanup, setToken, navigate, redirectPath]);

  useEffect(() => {
    generateQR();
    return cleanup;
  }, [generateQR, cleanup]);

  return (
    <div className={styles.qrContainer}>
      <div className={styles.qrBox}>
        {qrStatus === 'loading' && (
          <div className={styles.qrPlaceholder}>
            <ReloadOutlined spin style={{ fontSize: 32, color: '#0AAF9A' }} />
            <p>正在生成二维码...</p>
          </div>
        )}

        {(qrStatus === 'pending' || qrStatus === 'scanned') && qrUrl && (
          <QRCanvas value={qrUrl} size={200} />
        )}

        {qrStatus === 'expired' && (
          <div className={styles.qrPlaceholder}>
            <p>二维码已过期</p>
            <button className={styles.refreshQrBtn} onClick={generateQR}>
              <ReloadOutlined /> 刷新二维码
            </button>
          </div>
        )}

        {qrStatus === 'confirmed' && (
          <div className={styles.qrPlaceholder}>
            <div style={{ fontSize: 48 }}>✅</div>
            <p>登录成功，正在跳转...</p>
          </div>
        )}
      </div>

      <div className={styles.qrTip}>
        {qrStatus === 'pending' && '请使用企业微信扫描二维码'}
        {qrStatus === 'scanned' && '已扫码，请在手机上确认登录'}
        {qrStatus === 'expired' && '二维码已过期，请刷新'}
        {qrStatus === 'loading' && '加载中...'}
      </div>
    </div>
  );
};

// ══════════════════════════════════════════════════════════════
//  QR Canvas 渲染（纯 Canvas，无外部依赖）
// ══════════════════════════════════════════════════════════════
const QRCanvas: React.FC<{ value: string; size: number }> = ({ value, size }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    // 动态加载 qrcode 库，如果不可用则显示 URL 文字
    import('qrcode')
      .then((QRCode) => {
        QRCode.toCanvas(canvas, value, {
          width: size,
          margin: 2,
          color: { dark: '#1D1D1F', light: '#FFFFFF' },
        });
      })
      .catch(() => {
        // 降级：在 Canvas 上绘制提示文字
        const ctx = canvas.getContext('2d');
        if (ctx) {
          canvas.width = size;
          canvas.height = size;
          ctx.fillStyle = '#F5F5F7';
          ctx.fillRect(0, 0, size, size);
          ctx.fillStyle = '#1D1D1F';
          ctx.font = '14px sans-serif';
          ctx.textAlign = 'center';
          ctx.fillText('QR Code', size / 2, size / 2 - 10);
          ctx.font = '10px sans-serif';
          ctx.fillStyle = '#6E6E73';
          ctx.fillText('请安装 qrcode 包', size / 2, size / 2 + 10);
          ctx.fillText('pnpm add qrcode', size / 2, size / 2 + 26);
        }
      });
  }, [value, size]);

  return <canvas ref={canvasRef} className={styles.qrCanvas} />;
};

export default LoginPage;
