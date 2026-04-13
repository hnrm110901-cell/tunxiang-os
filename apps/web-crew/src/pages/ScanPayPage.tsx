/**
 * 扫码收款页 — 收银员扫顾客付款码（微信/支付宝/银联）完成收款
 * 路由: /scan-pay?order_id=xxx&amount_fen=xxxxx&table=xxx
 *
 * 状态机：waiting → processing → success | failed
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { formatPrice } from '@tx-ds/utils';
import { txFetch } from '../api/index';
import { startScan, isAndroidPOS, printReceipt } from '../bridge/TXBridge';

// ─── 类型 ───

type PayChannel = 'wechat' | 'alipay' | 'unionpay';
type PageState = 'waiting' | 'processing' | 'success' | 'failed';

interface ScanPayResult {
  payment_id: string;
  status: 'success' | 'pending' | 'failed';
  pay_channel: PayChannel;
  transaction_id: string;
  amount_fen: number;
  order_id: string;
  created_at: string;
  channel_label: string;
}

interface PaymentStatusResult {
  payment_id: string;
  status: 'success' | 'pending' | 'failed';
  pay_channel: PayChannel;
  channel_label: string;
  transaction_id: string;
  amount_fen: number;
  order_id: string;
  error_message: string | null;
}

// ─── 工具 ───

/** @deprecated Use formatPrice from @tx-ds/utils */
function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

function detectChannel(authCode: string): PayChannel {
  const prefix = authCode.slice(0, 2);
  const wechat = ['10', '11', '12', '13', '14', '15'];
  const alipay = ['25', '26', '27', '28', '29', '30'];
  if (wechat.includes(prefix)) return 'wechat';
  if (alipay.includes(prefix)) return 'alipay';
  return 'unionpay';
}

const CHANNEL_CONFIG: Record<PayChannel, { label: string; color: string; icon: string }> = {
  wechat: { label: '微信支付', color: '#07C160', icon: '微' },
  alipay: { label: '支付宝', color: '#1677FF', icon: '支' },
  unionpay: { label: '银联云闪付', color: '#E60012', icon: '云' },
};

// 生成简易ESC/POS小票内容（纯文本格式，实际收银机会解析）
function buildReceiptText(result: ScanPayResult, tableNo: string): string {
  const lines = [
    '================================',
    '        屯象OS 收款小票',
    '================================',
    `桌台: ${tableNo || '--'}`,
    `渠道: ${result.channel_label}`,
    `金额: ¥${fenToYuan(result.amount_fen)}`,
    `流水: ${result.transaction_id}`,
    `时间: ${new Date(result.created_at).toLocaleString('zh-CN')}`,
    '================================',
    '        感谢惠顾，欢迎再来！',
    '================================',
  ];
  return lines.join('\n');
}

// ─── 旋转加载动画（纯CSS内联） ───

const SpinnerStyle = `
@keyframes txSpin {
  0%   { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}
@keyframes txPop {
  0%   { transform: scale(0); opacity: 0; }
  60%  { transform: scale(1.2); opacity: 1; }
  100% { transform: scale(1); }
}
`;

// ─── 主页面 ───

export default function ScanPayPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const orderId = searchParams.get('order_id') || '';
  const amountFen = parseInt(searchParams.get('amount_fen') || '0', 10);
  const tableNo = searchParams.get('table') || '--';
  const operatorId = (window as unknown as Record<string, unknown>).__CREW_ID__ as string || '';
  const storeId = (window as unknown as Record<string, unknown>).__STORE_ID__ as string || '';

  const [pageState, setPageState] = useState<PageState>('waiting');
  const [authCode, setAuthCode] = useState('');
  const [showManualInput, setShowManualInput] = useState(false);
  const [manualCode, setManualCode] = useState('');
  const [detectedChannel, setDetectedChannel] = useState<PayChannel | null>(null);
  const [paymentResult, setPaymentResult] = useState<ScanPayResult | null>(null);
  const [currentPaymentId, setCurrentPaymentId] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [autoCountdown, setAutoCountdown] = useState(3);

  // 扫码枪输入速度检测
  const inputRef = useRef<HTMLInputElement>(null);
  const lastInputTimeRef = useRef<number>(0);
  const inputSpeedBuffer = useRef<number[]>([]);
  const submitTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const countdownTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 自动聚焦扫码输入框
  useEffect(() => {
    if (pageState === 'waiting' && !showManualInput) {
      inputRef.current?.focus();
    }
  }, [pageState, showManualInput]);

  // 清除轮询定时器
  const clearPoll = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  // 清除倒计时
  const clearCountdown = useCallback(() => {
    if (countdownTimerRef.current) {
      clearInterval(countdownTimerRef.current);
      countdownTimerRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => {
      clearPoll();
      clearCountdown();
      if (submitTimerRef.current) clearTimeout(submitTimerRef.current);
    };
  }, [clearPoll, clearCountdown]);

  // ─── 提交付款码 ───

  const submitAuthCode = useCallback(async (code: string) => {
    const trimmed = code.trim();
    if (!trimmed || trimmed.length < 6) return;

    const channel = detectChannel(trimmed);
    setDetectedChannel(channel);
    setPageState('processing');
    setErrorMessage('');

    try {
      const result = await txFetch<ScanPayResult>('/api/v1/payments/scan-pay', {
        method: 'POST',
        body: JSON.stringify({
          order_id: orderId,
          auth_code: trimmed,
          amount_fen: amountFen,
          operator_id: operatorId,
          store_id: storeId,
        }),
      });

      setCurrentPaymentId(result.payment_id);

      if (result.status === 'success') {
        setPaymentResult(result);
        setPageState('success');
        startSuccessCountdown();
      } else if (result.status === 'pending') {
        // 开始轮询
        startPolling(result.payment_id);
      } else {
        setErrorMessage('支付失败，请重试');
        setPageState('failed');
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '网络错误，请重试';
      setErrorMessage(msg);
      setPageState('failed');
    }
  }, [orderId, amountFen, operatorId, storeId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ─── 轮询支付状态 ───

  const startPolling = useCallback((paymentId: string) => {
    clearPoll();
    pollTimerRef.current = setInterval(async () => {
      try {
        const status = await txFetch<PaymentStatusResult>(
          `/api/v1/payments/scan-pay/${encodeURIComponent(paymentId)}/status`,
        );
        if (status.status === 'success') {
          clearPoll();
          setPaymentResult({
            payment_id: status.payment_id,
            status: 'success',
            pay_channel: status.pay_channel,
            transaction_id: status.transaction_id,
            amount_fen: status.amount_fen,
            order_id: status.order_id,
            created_at: new Date().toISOString(),
            channel_label: status.channel_label,
          });
          setPageState('success');
          startSuccessCountdown();
        } else if (status.status === 'failed') {
          clearPoll();
          setErrorMessage(status.error_message || '支付失败，请重试');
          setPageState('failed');
        }
      } catch {
        // 网络抖动不影响轮询，继续
      }
    }, 2000);
  }, [clearPoll]); // eslint-disable-line react-hooks/exhaustive-deps

  // ─── 成功倒计时自动返回 ───

  const startSuccessCountdown = useCallback(() => {
    setAutoCountdown(3);
    clearCountdown();
    countdownTimerRef.current = setInterval(() => {
      setAutoCountdown((prev) => {
        if (prev <= 1) {
          clearCountdown();
          navigate(-1);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  }, [clearCountdown, navigate]);

  // ─── 取消支付 ───

  const handleCancel = useCallback(async () => {
    clearPoll();
    if (currentPaymentId) {
      try {
        await txFetch(`/api/v1/payments/scan-pay/${encodeURIComponent(currentPaymentId)}/cancel`, {
          method: 'POST',
        });
      } catch {
        // 忽略取消失败
      }
    }
    setPageState('waiting');
    setAuthCode('');
    setManualCode('');
    setDetectedChannel(null);
    setCurrentPaymentId('');
  }, [clearPoll, currentPaymentId]);

  // ─── 打印小票 ───

  const handlePrint = useCallback(async () => {
    if (!paymentResult) return;
    const text = buildReceiptText(paymentResult, tableNo);
    await printReceipt(text);
  }, [paymentResult, tableNo]);

  // ─── 扫码枪输入处理 ───

  const handleScannerInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = e.target.value;
      setAuthCode(val);

      const now = Date.now();
      if (lastInputTimeRef.current > 0) {
        inputSpeedBuffer.current.push(now - lastInputTimeRef.current);
      }
      lastInputTimeRef.current = now;

      // 清除之前的定时器
      if (submitTimerRef.current) clearTimeout(submitTimerRef.current);

      // 扫码枪特征：输入完整后会自动发送 Enter，或者输入极快（<100ms/字符）
      // 设置50ms防抖：扫码枪输入完成后如果没有新字符，视为完整码
      submitTimerRef.current = setTimeout(() => {
        const avgInterval =
          inputSpeedBuffer.current.length > 0
            ? inputSpeedBuffer.current.reduce((a, b) => a + b, 0) / inputSpeedBuffer.current.length
            : 999;

        // 扫码枪：平均间隔 <30ms（远快于人工输入 >150ms）
        if (avgInterval < 100 && val.length >= 6) {
          inputSpeedBuffer.current = [];
          lastInputTimeRef.current = 0;
          setAuthCode('');
          void submitAuthCode(val);
        }
        // 若不满足速度条件，等待用户手动按 Enter
      }, 80);
    },
    [submitAuthCode],
  );

  const handleScannerKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter') {
        if (submitTimerRef.current) clearTimeout(submitTimerRef.current);
        inputSpeedBuffer.current = [];
        lastInputTimeRef.current = 0;
        const val = authCode;
        setAuthCode('');
        void submitAuthCode(val);
      }
    },
    [authCode, submitAuthCode],
  );

  // ─── 商米扫码枪触发 ───

  const handleNativeScan = useCallback(async () => {
    const result = await startScan();
    if (result) {
      void submitAuthCode(result);
    }
  }, [submitAuthCode]);

  // ─── 手动输入提交 ───

  const handleManualSubmit = useCallback(() => {
    const code = manualCode.trim();
    if (code.length < 6) return;
    setShowManualInput(false);
    setManualCode('');
    void submitAuthCode(code);
  }, [manualCode, submitAuthCode]);

  // ─── UI 渲染 ───

  const amountDisplay = `¥${fenToYuan(amountFen)}`;

  return (
    <div
      style={{
        minHeight: '100vh',
        background: '#0B1A20',
        color: '#fff',
        fontFamily: 'system-ui, -apple-system, sans-serif',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <style>{SpinnerStyle}</style>

      {/* ─── 顶部导航 ─── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '16px 16px 12px',
          background: '#112228',
          borderBottom: '1px solid #1a2a33',
          position: 'sticky',
          top: 0,
          zIndex: 10,
        }}
      >
        <button
          onClick={() => navigate(-1)}
          style={{
            minWidth: 48,
            minHeight: 48,
            background: 'transparent',
            border: 'none',
            color: '#FF6B35',
            fontSize: 24,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 0,
          }}
        >
          ←
        </button>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 20, fontWeight: 700 }}>扫码收款</div>
          {tableNo !== '--' && (
            <div style={{ fontSize: 14, color: '#9DB4B2' }}>{tableNo} 桌</div>
          )}
        </div>
        <div
          style={{
            background: '#1a2a33',
            borderRadius: 8,
            padding: '6px 16px',
            fontSize: 22,
            fontWeight: 700,
            color: '#FF6B35',
          }}
        >
          {amountDisplay}
        </div>
      </div>

      {/* ─── 内容区 ─── */}
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '32px 24px',
          gap: 32,
        }}
      >

        {/* ==== State 1: 等待扫码 ==== */}
        {pageState === 'waiting' && (
          <>
            {/* 图标 */}
            <div
              style={{
                width: 96,
                height: 96,
                borderRadius: '50%',
                background: '#1a2a33',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 48,
                border: '2px solid #FF6B35',
              }}
            >
              📱
            </div>

            {/* 提示文字 */}
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 24, fontWeight: 700, marginBottom: 8 }}>
                请扫顾客付款码
              </div>
              <div style={{ fontSize: 16, color: '#9DB4B2' }}>
                支持微信 / 支付宝 / 银联云闪付
              </div>
            </div>

            {/* 金额 */}
            <div
              style={{
                background: '#112228',
                borderRadius: 16,
                padding: '20px 40px',
                textAlign: 'center',
                border: '1px solid #1a2a33',
              }}
            >
              <div style={{ fontSize: 16, color: '#9DB4B2', marginBottom: 4 }}>收款金额</div>
              <div style={{ fontSize: 40, fontWeight: 700, color: '#FF6B35' }}>
                {amountDisplay}
              </div>
            </div>

            {/* 扫码枪隐藏输入框（自动聚焦，扫码枪输入后自动提交） */}
            <div style={{ width: '100%', maxWidth: 400 }}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  background: '#112228',
                  border: '2px solid #FF6B35',
                  borderRadius: 12,
                  padding: '0 16px',
                  minHeight: 56,
                }}
                onClick={() => inputRef.current?.focus()}
              >
                <span style={{ fontSize: 20 }}>🔍</span>
                <input
                  ref={inputRef}
                  type="text"
                  value={authCode}
                  onChange={handleScannerInput}
                  onKeyDown={handleScannerKeyDown}
                  inputMode="numeric"
                  placeholder="扫码枪已连接，等待扫码…"
                  style={{
                    flex: 1,
                    background: 'transparent',
                    border: 'none',
                    color: '#fff',
                    fontSize: 16,
                    outline: 'none',
                    minHeight: 52,
                  }}
                  autoFocus
                  autoComplete="off"
                />
              </div>
              <div style={{ fontSize: 13, color: '#9DB4B2', marginTop: 8, textAlign: 'center' }}>
                扫码枪扫描后自动提交，无需手动确认
              </div>
            </div>

            {/* 操作按钮行 */}
            <div style={{ display: 'flex', gap: 12, width: '100%', maxWidth: 400 }}>
              {/* 手动输入 */}
              <button
                onClick={() => setShowManualInput(true)}
                style={{
                  flex: 1,
                  minHeight: 52,
                  background: '#1a2a33',
                  border: '1px solid #334455',
                  borderRadius: 10,
                  color: '#E2EAE8',
                  fontSize: 16,
                  cursor: 'pointer',
                }}
              >
                手动输入付款码
              </button>
              {/* 商米原生扫码（仅安卓POS环境显示） */}
              {isAndroidPOS() && (
                <button
                  onClick={handleNativeScan}
                  style={{
                    flex: 1,
                    minHeight: 52,
                    background: '#FF6B35',
                    border: 'none',
                    borderRadius: 10,
                    color: '#fff',
                    fontSize: 16,
                    fontWeight: 700,
                    cursor: 'pointer',
                  }}
                >
                  启动摄像头扫码
                </button>
              )}
            </div>
          </>
        )}

        {/* ==== State 2: 支付中 ==== */}
        {pageState === 'processing' && (
          <>
            {/* 旋转加载圆环 */}
            <div
              style={{
                width: 80,
                height: 80,
                borderRadius: '50%',
                border: '6px solid #1a2a33',
                borderTopColor: '#FF6B35',
                animation: 'txSpin 0.9s linear infinite',
              }}
            />

            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 24, fontWeight: 700, marginBottom: 8 }}>
                正在收款 {amountDisplay}
              </div>
              {detectedChannel && (
                <div
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 8,
                    background: `${CHANNEL_CONFIG[detectedChannel].color}22`,
                    border: `1px solid ${CHANNEL_CONFIG[detectedChannel].color}`,
                    borderRadius: 20,
                    padding: '4px 16px',
                    fontSize: 16,
                    color: CHANNEL_CONFIG[detectedChannel].color,
                    marginTop: 4,
                  }}
                >
                  <span
                    style={{
                      width: 24,
                      height: 24,
                      borderRadius: '50%',
                      background: CHANNEL_CONFIG[detectedChannel].color,
                      color: '#fff',
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: 12,
                      fontWeight: 700,
                    }}
                  >
                    {CHANNEL_CONFIG[detectedChannel].icon}
                  </span>
                  {CHANNEL_CONFIG[detectedChannel].label}
                </div>
              )}
              <div style={{ fontSize: 14, color: '#9DB4B2', marginTop: 12 }}>
                请等待，正在向支付网关确认…
              </div>
            </div>

            {/* 取消按钮 */}
            <button
              onClick={handleCancel}
              style={{
                minWidth: 180,
                minHeight: 52,
                background: 'transparent',
                border: '2px solid #ef4444',
                borderRadius: 10,
                color: '#ef4444',
                fontSize: 18,
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              取消支付
            </button>
          </>
        )}

        {/* ==== State 3: 支付成功 ==== */}
        {pageState === 'success' && paymentResult && (
          <>
            {/* 绿色对勾弹出动画 */}
            <div
              style={{
                width: 96,
                height: 96,
                borderRadius: '50%',
                background: '#22c55e',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 52,
                color: '#fff',
                animation: 'txPop 0.4s ease-out',
              }}
            >
              ✓
            </div>

            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 28, fontWeight: 700, color: '#22c55e', marginBottom: 8 }}>
                收款成功
              </div>
              <div style={{ fontSize: 36, fontWeight: 700, color: '#FF6B35' }}>
                {amountDisplay}
              </div>
            </div>

            {/* 支付详情卡片 */}
            <div
              style={{
                background: '#112228',
                borderRadius: 16,
                padding: '20px 24px',
                width: '100%',
                maxWidth: 400,
                border: '1px solid #22c55e44',
              }}
            >
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 16, color: '#9DB4B2' }}>支付渠道</span>
                  <span
                    style={{
                      fontSize: 16,
                      fontWeight: 600,
                      color: CHANNEL_CONFIG[paymentResult.pay_channel].color,
                    }}
                  >
                    {paymentResult.channel_label}
                  </span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 16, color: '#9DB4B2' }}>交易流水号</span>
                  <span
                    style={{
                      fontSize: 13,
                      color: '#E2EAE8',
                      fontFamily: 'monospace',
                      maxWidth: 180,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {paymentResult.transaction_id}
                  </span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 16, color: '#9DB4B2' }}>桌台</span>
                  <span style={{ fontSize: 16, color: '#E2EAE8' }}>{tableNo}</span>
                </div>
              </div>
            </div>

            {/* 操作按钮 */}
            <div style={{ display: 'flex', gap: 12, width: '100%', maxWidth: 400 }}>
              <button
                onClick={handlePrint}
                style={{
                  flex: 1,
                  minHeight: 56,
                  background: '#1a2a33',
                  border: '1px solid #334455',
                  borderRadius: 12,
                  color: '#E2EAE8',
                  fontSize: 18,
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                打印小票
              </button>
              <button
                onClick={() => {
                  clearCountdown();
                  navigate(-1);
                }}
                style={{
                  flex: 2,
                  minHeight: 56,
                  background: '#22c55e',
                  border: 'none',
                  borderRadius: 12,
                  color: '#fff',
                  fontSize: 18,
                  fontWeight: 700,
                  cursor: 'pointer',
                }}
              >
                完成（{autoCountdown}s）
              </button>
            </div>
          </>
        )}

        {/* ==== State 4: 支付失败 ==== */}
        {pageState === 'failed' && (
          <>
            {/* 红色×图标 */}
            <div
              style={{
                width: 96,
                height: 96,
                borderRadius: '50%',
                background: '#ef4444',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 52,
                color: '#fff',
              }}
            >
              ✕
            </div>

            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 24, fontWeight: 700, color: '#ef4444', marginBottom: 8 }}>
                支付失败
              </div>
              <div
                style={{
                  fontSize: 16,
                  color: '#9DB4B2',
                  maxWidth: 300,
                  lineHeight: 1.6,
                }}
              >
                {errorMessage || '支付未成功，请重试'}
              </div>
            </div>

            {/* 操作按钮 */}
            <div style={{ display: 'flex', gap: 12, width: '100%', maxWidth: 400 }}>
              <button
                onClick={() => {
                  setPageState('waiting');
                  setAuthCode('');
                  setManualCode('');
                  setDetectedChannel(null);
                  setErrorMessage('');
                }}
                style={{
                  flex: 1,
                  minHeight: 56,
                  background: '#FF6B35',
                  border: 'none',
                  borderRadius: 12,
                  color: '#fff',
                  fontSize: 18,
                  fontWeight: 700,
                  cursor: 'pointer',
                }}
              >
                重新扫码
              </button>
              <button
                onClick={() => navigate(-1)}
                style={{
                  flex: 1,
                  minHeight: 56,
                  background: '#1a2a33',
                  border: '1px solid #334455',
                  borderRadius: 12,
                  color: '#E2EAE8',
                  fontSize: 18,
                  cursor: 'pointer',
                }}
              >
                切换支付方式
              </button>
            </div>
          </>
        )}
      </div>

      {/* ─── 手动输入付款码弹窗 ─── */}
      {showManualInput && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.75)',
            display: 'flex',
            alignItems: 'flex-end',
            justifyContent: 'center',
            zIndex: 100,
          }}
          onClick={(e) => {
            if (e.target === e.currentTarget) setShowManualInput(false);
          }}
        >
          <div
            style={{
              background: '#112228',
              borderRadius: '20px 20px 0 0',
              padding: '24px 24px 40px',
              width: '100%',
              maxWidth: 480,
              border: '1px solid #1a2a33',
              borderBottom: 'none',
            }}
          >
            <div style={{ fontSize: 20, fontWeight: 700, marginBottom: 4 }}>
              手动输入付款码
            </div>
            <div style={{ fontSize: 14, color: '#9DB4B2', marginBottom: 20 }}>
              请让顾客出示付款码，收银员输入18位数字
            </div>
            <input
              autoFocus
              type="text"
              inputMode="numeric"
              value={manualCode}
              onChange={(e) => setManualCode(e.target.value.replace(/\D/g, ''))}
              onKeyDown={(e) => e.key === 'Enter' && handleManualSubmit()}
              placeholder="输入付款码（18位数字）"
              maxLength={22}
              style={{
                display: 'block',
                width: '100%',
                minHeight: 56,
                background: '#0B1A20',
                border: '2px solid #FF6B35',
                borderRadius: 10,
                color: '#fff',
                fontSize: 20,
                padding: '0 16px',
                outline: 'none',
                boxSizing: 'border-box',
                letterSpacing: 2,
                fontFamily: 'monospace',
              }}
            />
            {manualCode.length > 0 && manualCode.length < 6 && (
              <div style={{ fontSize: 13, color: '#ef4444', marginTop: 6 }}>
                付款码至少6位
              </div>
            )}
            {manualCode.length >= 6 && (
              <div
                style={{
                  fontSize: 13,
                  color: CHANNEL_CONFIG[detectChannel(manualCode)].color,
                  marginTop: 6,
                }}
              >
                识别为：{CHANNEL_CONFIG[detectChannel(manualCode)].label}
              </div>
            )}
            <div style={{ display: 'flex', gap: 12, marginTop: 20 }}>
              <button
                onClick={() => {
                  setShowManualInput(false);
                  setManualCode('');
                }}
                style={{
                  flex: 1,
                  minHeight: 52,
                  background: '#1a2a33',
                  border: 'none',
                  borderRadius: 10,
                  color: '#9DB4B2',
                  fontSize: 18,
                  cursor: 'pointer',
                }}
              >
                取消
              </button>
              <button
                onClick={handleManualSubmit}
                disabled={manualCode.trim().length < 6}
                style={{
                  flex: 2,
                  minHeight: 52,
                  background: manualCode.trim().length >= 6 ? '#FF6B35' : '#3a2a1a',
                  border: 'none',
                  borderRadius: 10,
                  color: manualCode.trim().length >= 6 ? '#fff' : '#664433',
                  fontSize: 18,
                  fontWeight: 700,
                  cursor: manualCode.trim().length >= 6 ? 'pointer' : 'not-allowed',
                }}
              >
                确认收款
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
