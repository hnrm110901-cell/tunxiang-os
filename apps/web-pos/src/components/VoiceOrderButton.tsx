/**
 * VoiceOrderButton — 语音点餐浮动按钮 + 确认流程弹窗
 *
 * 触控规范（Store-POS 终端）：
 *   - 浮动按钮直径 72px（关键操作触控标准）
 *   - 确认/取消按钮高度 ≥ 48px
 *   - 最小字体 16px
 *   - 按压有 scale(0.97) 触控反馈
 *   - 无 hover 依赖（纯 touch 场景）
 *   - 关键操作（确认下单）有二次确认
 *
 * 状态机：
 *   idle → recording（按住说话）→ transcribing（识别中）
 *        → confirming（显示识别结果 + 匹配菜品）→ done
 *                                ↓ 重新录音
 *                             recording
 *
 * 降级处理：浏览器不支持 MediaRecorder 时隐藏按钮
 */

import { useCallback, useEffect, useRef, useState } from 'react';

// ─── Design Tokens（Store 终端 CSS Variables）───

const T = {
  primary: '#FF6B35',
  primaryActive: '#E55A28',
  success: '#0F6E56',
  successBg: '#E6F4F1',
  danger: '#A32D2D',
  dangerBg: '#FCEAEA',
  textPrimary: '#2C2C2A',
  textSecondary: '#5F5E5A',
  bgPrimary: '#FFFFFF',
  bgSecondary: '#F8F7F5',
  border: '#E8E6E1',
  radiusMd: '12px',
  radiusLg: '16px',
  shadowMd: '0 4px 12px rgba(0,0,0,0.08)',
  shadowLg: '0 8px 24px rgba(0,0,0,0.12)',
  fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
} as const;

// ─── 常量 ───

const KEYFRAMES_ID = 'tx-voice-order-keyframes';
const API_BASE = '/api/v1/voice';

// ─── 类型 ───

type VoiceState = 'idle' | 'recording' | 'transcribing' | 'confirming' | 'submitting';

interface MatchedDish {
  dish_id: string;
  name: string;
  quantity: number;
  unit_price: number;   // 分
  spec?: string;
}

interface VoiceOrderButtonProps {
  storeId: string;
  onOrderConfirmed: (orderId: string) => void;
}

// ─── 工具函数 ───

/** 将分转为元字符串，保留两位小数 */
const fenToYuan = (fen: number): string => (fen / 100).toFixed(2);

/** 注入动画关键帧（幂等） */
function ensureKeyframes(): void {
  if (document.getElementById(KEYFRAMES_ID)) return;
  const style = document.createElement('style');
  style.id = KEYFRAMES_ID;
  style.textContent = `
    @keyframes tx-voice-pulse {
      0%, 100% { box-shadow: 0 0 0 0 rgba(163, 45, 45, 0.5); }
      50%       { box-shadow: 0 0 0 12px rgba(163, 45, 45, 0); }
    }
    @keyframes tx-voice-dot {
      0%, 100% { opacity: 1; }
      50%       { opacity: 0.3; }
    }
    @keyframes tx-voice-modal-in {
      from { transform: translateY(100%); opacity: 0; }
      to   { transform: translateY(0);    opacity: 1; }
    }
    @keyframes tx-voice-spin {
      from { transform: rotate(0deg); }
      to   { transform: rotate(360deg); }
    }
  `;
  document.head.appendChild(style);
}

// ─── 子组件：状态提示点 ───

function RecordingDots() {
  return (
    <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center', marginLeft: 8 }}>
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: T.danger,
            animation: `tx-voice-dot 1.2s ease-in-out ${i * 0.4}s infinite`,
            display: 'inline-block',
          }}
        />
      ))}
    </span>
  );
}

// ─── 子组件：加载 Spinner ───

function Spinner() {
  return (
    <span
      style={{
        display: 'inline-block',
        width: 20,
        height: 20,
        border: `3px solid ${T.border}`,
        borderTopColor: T.primary,
        borderRadius: '50%',
        animation: 'tx-voice-spin 0.8s linear infinite',
        marginRight: 8,
        flexShrink: 0,
      }}
    />
  );
}

// ─── 主组件 ───

export const VoiceOrderButton: React.FC<VoiceOrderButtonProps> = ({
  storeId,
  onOrderConfirmed,
}) => {
  ensureKeyframes();

  // 浏览器能力检测（降级隐藏）
  const [supported] = useState<boolean>(
    () => typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia,
  );

  const [state, setState] = useState<VoiceState>('idle');
  const [transcript, setTranscript] = useState<string>('');
  const [matchedDishes, setMatchedDishes] = useState<MatchedDish[]>([]);
  const [errorMsg, setErrorMsg] = useState<string>('');
  const [btnPressing, setBtnPressing] = useState(false);
  const [confirmPressing, setConfirmPressing] = useState(false);
  const [retryPressing, setRetryPressing] = useState(false);
  const [modalVisible, setModalVisible] = useState(false);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);

  // 清理录音资源
  const stopStream = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => {
      stopStream();
    };
  }, [stopStream]);

  if (!supported) return null;

  // ─── 录音逻辑 ───

  const startRecording = async () => {
    setErrorMsg('');
    setTranscript('');
    setMatchedDishes([]);

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err: unknown) {
      const msg = err instanceof DOMException
        ? (err.name === 'NotAllowedError' ? '请允许麦克风权限后重试' : `麦克风错误：${err.message}`)
        : '无法访问麦克风，请检查设备';
      setErrorMsg(msg);
      return;
    }

    streamRef.current = stream;
    audioChunksRef.current = [];

    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
      ? 'audio/webm;codecs=opus'
      : 'audio/webm';

    const recorder = new MediaRecorder(stream, { mimeType });
    mediaRecorderRef.current = recorder;

    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) audioChunksRef.current.push(e.data);
    };

    recorder.onstop = () => {
      stopStream();
      void processAudio();
    };

    recorder.start(100);
    setState('recording');
    setModalVisible(true);
  };

  const stopRecording = () => {
    if (
      mediaRecorderRef.current &&
      mediaRecorderRef.current.state !== 'inactive'
    ) {
      mediaRecorderRef.current.stop();
      setState('transcribing');
    }
  };

  // ─── 语音处理流程 ───

  const processAudio = async () => {
    try {
      // 1. 转录
      const blob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
      const base64 = await blobToBase64(blob);

      const transcribeRes = await fetchVoiceAPI<{ transcript: string }>(
        `${API_BASE}/transcribe`,
        { store_id: storeId, audio_base64: base64 },
      );
      const text = transcribeRes.transcript;
      setTranscript(text);

      // 2. 意图解析
      const intentRes = await fetchVoiceAPI<{ intent: string; parsed_items: unknown }>(
        `${API_BASE}/parse-intent`,
        { store_id: storeId, transcript: text },
      );

      // 3. 菜品匹配
      const matchRes = await fetchVoiceAPI<{ dishes: MatchedDish[] }>(
        `${API_BASE}/match-dishes`,
        { store_id: storeId, intent: intentRes.intent, parsed_items: intentRes.parsed_items },
      );

      setMatchedDishes(matchRes.dishes);
      setState('confirming');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '语音识别失败，请重试';
      setErrorMsg(msg);
      setState('confirming'); // 进入确认页展示错误，允许重试
    }
  };

  // ─── 确认下单 ───

  const confirmOrder = async () => {
    setState('submitting');
    try {
      const res = await fetchVoiceAPI<{ order_id: string }>(
        `${API_BASE}/confirm-order`,
        {
          store_id: storeId,
          transcript,
          dishes: matchedDishes,
        },
      );
      setModalVisible(false);
      setState('idle');
      onOrderConfirmed(res.order_id);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '下单失败，请重试';
      setErrorMsg(msg);
      setState('confirming');
    }
  };

  // ─── 重新录音 ───

  const handleRetry = () => {
    setErrorMsg('');
    setTranscript('');
    setMatchedDishes([]);
    void startRecording();
  };

  // ─── 关闭弹窗 ───

  const handleClose = () => {
    if (state === 'recording') stopRecording();
    stopStream();
    setModalVisible(false);
    setState('idle');
    setErrorMsg('');
    setTranscript('');
    setMatchedDishes([]);
  };

  // ─── 计算总价 ───

  const totalFen = matchedDishes.reduce(
    (sum, d) => sum + d.unit_price * d.quantity,
    0,
  );

  // ─── 浮动按钮样式 ───

  const isRecording = state === 'recording';
  const fabBg = isRecording ? T.danger : T.primary;
  const fabAnimation = isRecording
    ? 'tx-voice-pulse 1s ease-in-out infinite'
    : 'none';

  return (
    <>
      {/* ── 浮动按钮 ── */}
      <button
        type="button"
        aria-label={isRecording ? '录音中，松开结束录音' : '按住说话，开始语音点餐'}
        disabled={state === 'transcribing' || state === 'submitting'}
        onPointerDown={() => {
          setBtnPressing(true);
          if (state === 'idle') void startRecording();
        }}
        onPointerUp={() => {
          setBtnPressing(false);
          if (state === 'recording') stopRecording();
        }}
        onPointerLeave={() => {
          setBtnPressing(false);
          if (state === 'recording') stopRecording();
        }}
        style={{
          position: 'fixed',
          bottom: 32,
          right: 32,
          zIndex: 1000,
          width: 72,
          height: 72,
          borderRadius: '50%',
          border: 'none',
          background: fabBg,
          color: '#FFFFFF',
          fontSize: 28,
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          boxShadow: `0 4px 16px rgba(0,0,0,0.2)`,
          animation: fabAnimation,
          transform: btnPressing ? 'scale(0.94)' : 'scale(1)',
          transition: 'transform 200ms ease, background 200ms ease',
          userSelect: 'none',
          WebkitUserSelect: 'none',
          opacity: (state === 'transcribing' || state === 'submitting') ? 0.6 : 1,
        }}
      >
        🎤
      </button>

      {/* ── 弹窗遮罩 ── */}
      {modalVisible && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="语音点餐"
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 2000,
            background: 'rgba(0,0,0,0.45)',
            display: 'flex',
            alignItems: 'flex-end',
            fontFamily: T.fontFamily,
          }}
          onPointerDown={(e) => {
            // 点击遮罩关闭（仅 idle/confirming 状态）
            if (
              e.target === e.currentTarget &&
              (state === 'idle' || state === 'confirming')
            ) {
              handleClose();
            }
          }}
        >
          {/* ── 弹窗主体（从底部滑入）── */}
          <div
            style={{
              width: '100%',
              maxHeight: '80vh',
              background: T.bgPrimary,
              borderRadius: '20px 20px 0 0',
              boxShadow: T.shadowLg,
              animation: 'tx-voice-modal-in 300ms ease-out',
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
            }}
          >
            {/* ── 弹窗头部 ── */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '20px 24px 16px',
                borderBottom: `1px solid ${T.border}`,
                flexShrink: 0,
              }}
            >
              <span style={{ fontSize: 20, fontWeight: 700, color: T.textPrimary }}>
                语音点餐
              </span>
              <button
                type="button"
                aria-label="关闭"
                onPointerDown={() => handleClose()}
                style={{
                  width: 48,
                  height: 48,
                  borderRadius: '50%',
                  border: 'none',
                  background: T.bgSecondary,
                  color: T.textSecondary,
                  fontSize: 20,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  userSelect: 'none',
                  WebkitUserSelect: 'none',
                  flexShrink: 0,
                }}
              >
                ✕
              </button>
            </div>

            {/* ── 弹窗内容区 ── */}
            <div
              style={{
                flex: 1,
                overflowY: 'auto',
                WebkitOverflowScrolling: 'touch' as React.CSSProperties['WebkitOverflowScrolling'],
                padding: '20px 24px',
              }}
            >
              {/* 录音中 */}
              {state === 'recording' && (
                <div style={{ textAlign: 'center', padding: '24px 0' }}>
                  <div style={{ fontSize: 56, marginBottom: 16 }}>🎤</div>
                  <div
                    style={{
                      fontSize: 20,
                      fontWeight: 600,
                      color: T.danger,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                  >
                    录音中
                    <RecordingDots />
                  </div>
                  <div
                    style={{
                      fontSize: 16,
                      color: T.textSecondary,
                      marginTop: 12,
                    }}
                  >
                    请说出您要点的菜品，如「两份红烧肉，一个蒜蓉虾」
                  </div>
                  <button
                    type="button"
                    onPointerDown={() => stopRecording()}
                    style={{
                      marginTop: 32,
                      width: '100%',
                      height: 56,
                      borderRadius: T.radiusMd,
                      border: `2px solid ${T.danger}`,
                      background: T.dangerBg,
                      color: T.danger,
                      fontSize: 18,
                      fontWeight: 600,
                      cursor: 'pointer',
                      userSelect: 'none',
                      WebkitUserSelect: 'none',
                    }}
                  >
                    停止录音
                  </button>
                </div>
              )}

              {/* 识别中 */}
              {state === 'transcribing' && (
                <div style={{ textAlign: 'center', padding: '40px 0' }}>
                  <div style={{ fontSize: 48, marginBottom: 16 }}>⏳</div>
                  <div
                    style={{
                      fontSize: 18,
                      color: T.textSecondary,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                  >
                    <Spinner />
                    正在识别语音…
                  </div>
                </div>
              )}

              {/* 确认 / 错误 */}
              {(state === 'confirming' || state === 'submitting') && (
                <div>
                  {/* 错误提示 */}
                  {errorMsg ? (
                    <div
                      role="alert"
                      style={{
                        background: T.dangerBg,
                        border: `1px solid ${T.danger}`,
                        borderRadius: T.radiusMd,
                        padding: '12px 16px',
                        fontSize: 16,
                        color: T.danger,
                        marginBottom: 20,
                      }}
                    >
                      {errorMsg}
                    </div>
                  ) : null}

                  {/* 识别到的文字 */}
                  {transcript ? (
                    <div
                      style={{
                        background: T.bgSecondary,
                        borderRadius: T.radiusMd,
                        padding: '16px',
                        marginBottom: 20,
                      }}
                    >
                      <div
                        style={{
                          fontSize: 16,
                          color: T.textSecondary,
                          marginBottom: 8,
                          fontWeight: 500,
                        }}
                      >
                        识别内容
                      </div>
                      <div
                        style={{
                          fontSize: 18,
                          color: T.textPrimary,
                          lineHeight: 1.5,
                          fontWeight: 600,
                        }}
                      >
                        「{transcript}」
                      </div>
                    </div>
                  ) : null}

                  {/* 匹配菜品列表 */}
                  {matchedDishes.length > 0 ? (
                    <div>
                      <div
                        style={{
                          fontSize: 16,
                          color: T.textSecondary,
                          marginBottom: 12,
                          fontWeight: 500,
                        }}
                      >
                        匹配到的菜品
                      </div>
                      <div
                        style={{
                          border: `1px solid ${T.border}`,
                          borderRadius: T.radiusMd,
                          overflow: 'hidden',
                          marginBottom: 20,
                        }}
                      >
                        {matchedDishes.map((dish, idx) => (
                          <div
                            key={dish.dish_id}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'space-between',
                              padding: '14px 16px',
                              borderBottom:
                                idx < matchedDishes.length - 1
                                  ? `1px solid ${T.border}`
                                  : 'none',
                              background: T.bgPrimary,
                            }}
                          >
                            <div style={{ flex: 1 }}>
                              <div
                                style={{
                                  fontSize: 18,
                                  fontWeight: 600,
                                  color: T.textPrimary,
                                }}
                              >
                                {dish.name}
                                {dish.spec ? (
                                  <span
                                    style={{
                                      fontSize: 16,
                                      color: T.textSecondary,
                                      fontWeight: 400,
                                      marginLeft: 8,
                                    }}
                                  >
                                    （{dish.spec}）
                                  </span>
                                ) : null}
                              </div>
                              <div
                                style={{
                                  fontSize: 16,
                                  color: T.textSecondary,
                                  marginTop: 2,
                                }}
                              >
                                ¥{fenToYuan(dish.unit_price)} × {dish.quantity}
                              </div>
                            </div>
                            <div
                              style={{
                                fontSize: 18,
                                fontWeight: 700,
                                color: T.textPrimary,
                                whiteSpace: 'nowrap',
                                marginLeft: 16,
                              }}
                            >
                              ¥{fenToYuan(dish.unit_price * dish.quantity)}
                            </div>
                          </div>
                        ))}

                        {/* 合计行 */}
                        <div
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            padding: '14px 16px',
                            background: T.bgSecondary,
                          }}
                        >
                          <div
                            style={{ fontSize: 18, fontWeight: 600, color: T.textPrimary }}
                          >
                            合计
                          </div>
                          <div
                            style={{
                              fontSize: 22,
                              fontWeight: 700,
                              color: T.primary,
                            }}
                          >
                            ¥{fenToYuan(totalFen)}
                          </div>
                        </div>
                      </div>
                    </div>
                  ) : null}

                  {/* 无匹配菜品且无报错 */}
                  {matchedDishes.length === 0 && !errorMsg && (
                    <div
                      style={{
                        textAlign: 'center',
                        padding: '20px 0',
                        color: T.textSecondary,
                        fontSize: 16,
                      }}
                    >
                      未能匹配到菜品，请重新录音
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* ── 弹窗底部操作按钮 ── */}
            {(state === 'confirming' || state === 'submitting') && (
              <div
                style={{
                  padding: '16px 24px 24px',
                  borderTop: `1px solid ${T.border}`,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 12,
                  flexShrink: 0,
                }}
              >
                {/* 确认下单按钮（仅有匹配菜品时显示） */}
                {matchedDishes.length > 0 && (
                  <button
                    type="button"
                    disabled={state === 'submitting'}
                    onPointerDown={() => setConfirmPressing(true)}
                    onPointerUp={() => {
                      setConfirmPressing(false);
                      if (state !== 'submitting') void confirmOrder();
                    }}
                    onPointerLeave={() => setConfirmPressing(false)}
                    style={{
                      width: '100%',
                      height: 56,
                      borderRadius: T.radiusMd,
                      border: 'none',
                      background: state === 'submitting' ? '#B0C9C4' : T.success,
                      color: '#FFFFFF',
                      fontSize: 18,
                      fontWeight: 700,
                      cursor: state === 'submitting' ? 'not-allowed' : 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 8,
                      transform: confirmPressing ? 'scale(0.97)' : 'scale(1)',
                      transition: 'transform 200ms ease',
                      userSelect: 'none',
                      WebkitUserSelect: 'none',
                    }}
                  >
                    {state === 'submitting' ? (
                      <>
                        <Spinner />
                        下单中…
                      </>
                    ) : (
                      '✅ 确认下单'
                    )}
                  </button>
                )}

                {/* 重新录音按钮 */}
                <button
                  type="button"
                  disabled={state === 'submitting'}
                  onPointerDown={() => setRetryPressing(true)}
                  onPointerUp={() => {
                    setRetryPressing(false);
                    if (state !== 'submitting') handleRetry();
                  }}
                  onPointerLeave={() => setRetryPressing(false)}
                  style={{
                    width: '100%',
                    height: 56,
                    borderRadius: T.radiusMd,
                    border: `2px solid ${T.border}`,
                    background: T.bgPrimary,
                    color: T.textPrimary,
                    fontSize: 18,
                    fontWeight: 600,
                    cursor: state === 'submitting' ? 'not-allowed' : 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    transform: retryPressing ? 'scale(0.97)' : 'scale(1)',
                    transition: 'transform 200ms ease',
                    userSelect: 'none',
                    WebkitUserSelect: 'none',
                    opacity: state === 'submitting' ? 0.5 : 1,
                  }}
                >
                  ❌ 重新录音
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
};

// ─── 工具：Blob 转 Base64 ───

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== 'string') {
        reject(new Error('FileReader 返回非字符串结果'));
        return;
      }
      // 去掉 data:audio/webm;base64, 前缀
      const base64 = result.split(',')[1] ?? '';
      resolve(base64);
    };
    reader.onerror = () => reject(new Error('音频读取失败'));
    reader.readAsDataURL(blob);
  });
}

// ─── 工具：统一 API 请求（带 X-Tenant-ID）───

async function fetchVoiceAPI<T>(url: string, body: unknown): Promise<T> {
  const tenantId =
    (typeof window !== 'undefined' && (window as Window & { __TX_TENANT_ID__?: string }).__TX_TENANT_ID__) || '';

  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(tenantId ? { 'X-Tenant-ID': tenantId } : {}),
    },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    let errMsg = `请求失败（${res.status}）`;
    try {
      const errBody = await res.json() as { error?: { message?: string } };
      if (errBody.error?.message) errMsg = errBody.error.message;
    } catch {
      // 忽略 JSON 解析失败
    }
    throw new Error(errMsg);
  }

  const data = await res.json() as { ok: boolean; data: T; error?: { message?: string } };
  if (!data.ok) {
    throw new Error(data.error?.message ?? '接口返回 ok=false');
  }
  return data.data;
}
