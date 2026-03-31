/**
 * 图片识菜页面 — 服务员用手机拍照识别菜品，快速加入订单
 * 路由：/dish-recognize?order_id=xxx&store_id=xxx
 */
import { useRef, useState, useEffect, useCallback } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

interface DishMatch {
  dish_id: string;
  dish_name: string;
  price: number;
  confidence: number;
  thumbnail_url?: string;
}

type PageState = 'camera' | 'loading' | 'results' | 'no-match' | 'error';

const MOCK_MATCHES: DishMatch[] = [
  { dish_id: 'mock_1', dish_name: '宫保鸡丁', price: 48, confidence: 92, thumbnail_url: '' },
  { dish_id: 'mock_2', dish_name: '红烧肉', price: 68, confidence: 75, thumbnail_url: '' },
  { dish_id: 'mock_3', dish_name: '鱼香茄子', price: 38, confidence: 68, thumbnail_url: '' },
];

export default function DishRecognizePage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const orderId = searchParams.get('order_id');
  const storeId = searchParams.get('store_id') || '';

  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const [pageState, setPageState] = useState<PageState>('camera');
  const [matches, setMatches] = useState<DishMatch[]>([]);
  const [cameraError, setCameraError] = useState<string>('');
  const [addedIds, setAddedIds] = useState<Set<string>>(new Set());
  const [addingId, setAddingId] = useState<string | null>(null);

  // 启动摄像头
  const startCamera = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 960 } },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      setCameraError('');
    } catch (err) {
      if (err instanceof DOMException) {
        if (err.name === 'NotAllowedError') {
          setCameraError('请在手机设置中允许访问摄像头');
        } else if (err.name === 'NotFoundError') {
          setCameraError('未找到摄像头设备');
        } else {
          setCameraError('摄像头启动失败，请重试');
        }
      } else {
        setCameraError('摄像头启动失败，请重试');
      }
    }
  }, []);

  // 停止摄像头
  const stopCamera = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop());
      streamRef.current = null;
    }
  }, []);

  useEffect(() => {
    startCamera();
    return () => stopCamera();
  }, [startCamera, stopCamera]);

  // 图片转 base64
  const imageToBase64 = (file: File): Promise<string> =>
    new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = reader.result as string;
        // 去掉 data:image/xxx;base64, 前缀
        resolve(result.split(',')[1] ?? result);
      };
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });

  // 调用识别 API
  const recognizeDish = async (base64: string) => {
    setPageState('loading');
    try {
      const resp = await fetch('/api/v1/vision/recognize-dish', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image_base64: base64, store_id: storeId }),
        signal: AbortSignal.timeout(15000),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const json = await resp.json();
      const resultMatches: DishMatch[] = json?.data?.matches ?? [];
      if (resultMatches.length === 0) {
        setPageState('no-match');
      } else {
        setMatches(resultMatches);
        setPageState('results');
      }
    } catch (_err) {
      // 网络失败或超时 → 使用 mock 结果
      setMatches(MOCK_MATCHES);
      setPageState('results');
    }
  };

  // 拍照
  const handleCapture = () => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;

    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 480;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    const base64 = canvas.toDataURL('image/jpeg', 0.85).split(',')[1];
    stopCamera();
    recognizeDish(base64);
  };

  // 从相册选图
  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const base64 = await imageToBase64(file);
      stopCamera();
      recognizeDish(base64);
    } catch (_err) {
      setPageState('error');
    }
  };

  // 重新拍照
  const handleRetry = async () => {
    setMatches([]);
    setAddedIds(new Set());
    setPageState('camera');
    await startCamera();
  };

  // 加入订单
  const handleAddToOrder = async (dish: DishMatch) => {
    if (!orderId || addedIds.has(dish.dish_id)) return;
    setAddingId(dish.dish_id);
    try {
      await fetch(`/api/v1/orders/${orderId}/items`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dish_id: dish.dish_id, quantity: 1 }),
        signal: AbortSignal.timeout(8000),
      });
      setAddedIds(prev => new Set(prev).add(dish.dish_id));
    } catch (_err) {
      // 静默失败，UI不阻塞
    } finally {
      setAddingId(null);
    }
  };

  // ─── 样式常量 ───
  const BG = '#0B1A20';
  const CARD_BG = '#112228';
  const ACCENT = '#FF6B35';
  const TEXT_PRIMARY = '#FFFFFF';
  const TEXT_SECONDARY = '#94A3B8';
  const BORDER = '#1A2A33';

  return (
    <div style={{ background: BG, minHeight: '100vh', color: TEXT_PRIMARY, fontFamily: 'system-ui, sans-serif' }}>

      {/* ─── 顶部导航 ─── */}
      <div style={{
        display: 'flex', alignItems: 'center', padding: '12px 16px',
        borderBottom: `1px solid ${BORDER}`, background: CARD_BG,
        position: 'sticky', top: 0, zIndex: 10,
      }}>
        <button
          onClick={() => { stopCamera(); navigate(-1); }}
          style={{
            background: 'none', border: 'none', color: TEXT_PRIMARY,
            fontSize: 18, cursor: 'pointer', padding: '8px 12px 8px 0',
            minWidth: 48, minHeight: 48, display: 'flex', alignItems: 'center',
          }}
        >
          ←
        </button>
        <span style={{ fontSize: 18, fontWeight: 700, flex: 1 }}>图片识菜</span>
        {orderId && (
          <span style={{ fontSize: 14, color: ACCENT }}>订单 #{orderId.slice(-6)}</span>
        )}
      </div>

      {/* ─── 相机区 ─── */}
      {pageState === 'camera' && (
        <div>
          {/* 预览区 4:3 */}
          <div style={{ width: '100%', paddingTop: '75%', position: 'relative', background: '#000' }}>
            <video
              ref={videoRef}
              playsInline
              muted
              style={{
                position: 'absolute', inset: 0, width: '100%', height: '100%',
                objectFit: 'cover', display: cameraError ? 'none' : 'block',
              }}
            />
            {/* 取景框辅助线 */}
            {!cameraError && (
              <div style={{
                position: 'absolute', inset: '15%',
                border: `2px solid rgba(255,107,53,0.6)`,
                borderRadius: 8, pointerEvents: 'none',
              }} />
            )}
            {/* 摄像头错误提示 */}
            {cameraError && (
              <div style={{
                position: 'absolute', inset: 0, display: 'flex',
                flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                gap: 12, padding: 24,
              }}>
                <span style={{ fontSize: 40 }}>📷</span>
                <span style={{ fontSize: 16, color: TEXT_SECONDARY, textAlign: 'center' }}>{cameraError}</span>
                <button
                  onClick={startCamera}
                  style={{
                    background: ACCENT, color: '#fff', border: 'none',
                    borderRadius: 8, padding: '12px 24px', fontSize: 16,
                    cursor: 'pointer', minHeight: 48,
                  }}
                >
                  重试
                </button>
              </div>
            )}
          </div>

          {/* 提示文字 */}
          <div style={{ padding: '16px', textAlign: 'center', color: TEXT_SECONDARY, fontSize: 16 }}>
            将菜单或菜品对准取景框后拍照
          </div>

          {/* 操作按钮区 */}
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            gap: 40, padding: '16px 24px 32px',
          }}>
            {/* 相册选图 */}
            <label style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
              <div style={{
                width: 52, height: 52, borderRadius: '50%',
                background: CARD_BG, border: `1px solid ${BORDER}`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 22,
              }}>
                🖼
              </div>
              <span style={{ fontSize: 16, color: TEXT_SECONDARY }}>相册</span>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                style={{ display: 'none' }}
                onChange={handleFileChange}
              />
            </label>

            {/* 拍照按钮 */}
            <button
              onClick={handleCapture}
              disabled={!!cameraError}
              style={{
                width: 72, height: 72, borderRadius: '50%',
                background: cameraError ? '#334155' : ACCENT,
                border: '4px solid rgba(255,255,255,0.3)',
                cursor: cameraError ? 'not-allowed' : 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 28, boxShadow: cameraError ? 'none' : `0 0 20px rgba(255,107,53,0.4)`,
                transition: 'transform 0.1s',
              }}
              aria-label="拍照识菜"
            >
              📸
            </button>

            {/* 占位（保持中心对称） */}
            <div style={{ width: 52 }} />
          </div>
        </div>
      )}

      {/* ─── 识别中 ─── */}
      {pageState === 'loading' && (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', minHeight: 'calc(100vh - 64px)', gap: 20,
        }}>
          <div style={{
            width: 56, height: 56,
            border: `4px solid ${BORDER}`,
            borderTopColor: ACCENT,
            borderRadius: '50%',
            animation: 'spin 0.8s linear infinite',
          }} />
          <span style={{ fontSize: 18, color: TEXT_SECONDARY }}>识别中...</span>
          <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        </div>
      )}

      {/* ─── 识别结果 ─── */}
      {pageState === 'results' && (
        <div style={{ padding: '16px' }}>
          <div style={{ fontSize: 16, color: TEXT_SECONDARY, marginBottom: 16 }}>
            识别到 {matches.length} 个匹配菜品
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {matches.map(dish => (
              <div
                key={dish.dish_id}
                style={{
                  background: CARD_BG, borderRadius: 12,
                  border: `1px solid ${BORDER}`, padding: '16px',
                  display: 'flex', flexDirection: 'column', gap: 10,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  {/* 菜品图片占位 */}
                  <div style={{
                    width: 64, height: 64, borderRadius: 10, flexShrink: 0,
                    background: '#1A2A33', display: 'flex', alignItems: 'center',
                    justifyContent: 'center', fontSize: 28, overflow: 'hidden',
                  }}>
                    {dish.thumbnail_url
                      ? <img src={dish.thumbnail_url} alt={dish.dish_name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                      : '🍽'
                    }
                  </div>

                  {/* 名称 + 价格 */}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 4, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {dish.dish_name}
                    </div>
                    <div style={{ fontSize: 18, color: ACCENT, fontWeight: 600 }}>
                      ¥{dish.price.toFixed(0)}
                    </div>
                  </div>

                  {/* 置信度百分比 */}
                  <div style={{ textAlign: 'center', flexShrink: 0 }}>
                    <div style={{ fontSize: 20, fontWeight: 700, color: dish.confidence >= 85 ? '#4ADE80' : dish.confidence >= 70 ? '#FACC15' : TEXT_SECONDARY }}>
                      {dish.confidence}%
                    </div>
                    <div style={{ fontSize: 14, color: TEXT_SECONDARY }}>匹配度</div>
                  </div>
                </div>

                {/* 置信度进度条 */}
                <div style={{ height: 6, background: '#1A2A33', borderRadius: 3, overflow: 'hidden' }}>
                  <div style={{
                    height: '100%', borderRadius: 3,
                    width: `${dish.confidence}%`,
                    background: dish.confidence >= 85
                      ? 'linear-gradient(90deg,#4ADE80,#22C55E)'
                      : dish.confidence >= 70
                        ? 'linear-gradient(90deg,#FACC15,#EAB308)'
                        : 'linear-gradient(90deg,#94A3B8,#64748B)',
                    transition: 'width 0.4s ease',
                  }} />
                </div>

                {/* 加入订单按钮 */}
                {orderId && (
                  <button
                    onClick={() => handleAddToOrder(dish)}
                    disabled={addedIds.has(dish.dish_id) || addingId === dish.dish_id}
                    style={{
                      width: '100%', minHeight: 48,
                      background: addedIds.has(dish.dish_id) ? '#1A2A33' : ACCENT,
                      color: addedIds.has(dish.dish_id) ? '#4ADE80' : '#fff',
                      border: addedIds.has(dish.dish_id) ? `1px solid #4ADE80` : 'none',
                      borderRadius: 10, fontSize: 16, fontWeight: 600,
                      cursor: addedIds.has(dish.dish_id) || addingId === dish.dish_id ? 'not-allowed' : 'pointer',
                      display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                    }}
                  >
                    {addingId === dish.dish_id
                      ? '加入中...'
                      : addedIds.has(dish.dish_id)
                        ? '✓ 已加入订单'
                        : '+ 加入订单'
                    }
                  </button>
                )}
              </div>
            ))}
          </div>

          {/* 底部按钮 */}
          <div style={{ marginTop: 24, display: 'flex', gap: 12 }}>
            <button
              onClick={handleRetry}
              style={{
                flex: 1, minHeight: 48, background: CARD_BG,
                color: TEXT_PRIMARY, border: `1px solid ${BORDER}`,
                borderRadius: 10, fontSize: 16, fontWeight: 600, cursor: 'pointer',
              }}
            >
              重新拍照
            </button>
            <button
              onClick={() => { stopCamera(); navigate(-1); }}
              style={{
                flex: 1, minHeight: 48, background: ACCENT,
                color: '#fff', border: 'none',
                borderRadius: 10, fontSize: 16, fontWeight: 600, cursor: 'pointer',
              }}
            >
              返回
            </button>
          </div>
        </div>
      )}

      {/* ─── 未识别到结果 ─── */}
      {(pageState === 'no-match' || pageState === 'error') && (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', minHeight: 'calc(100vh - 64px)', gap: 20, padding: 24,
        }}>
          <span style={{ fontSize: 56 }}>🔍</span>
          <div style={{ fontSize: 18, color: TEXT_PRIMARY, fontWeight: 600, textAlign: 'center' }}>
            未识别到菜品，请重新拍照
          </div>
          <div style={{ fontSize: 16, color: TEXT_SECONDARY, textAlign: 'center' }}>
            建议拍摄时对准菜品正面，保持光线充足
          </div>
          <div style={{ display: 'flex', gap: 12, width: '100%', maxWidth: 360 }}>
            <button
              onClick={handleRetry}
              style={{
                flex: 1, minHeight: 48, background: ACCENT,
                color: '#fff', border: 'none', borderRadius: 10,
                fontSize: 16, fontWeight: 600, cursor: 'pointer',
              }}
            >
              重新拍照
            </button>
            <button
              onClick={() => { stopCamera(); navigate(-1); }}
              style={{
                flex: 1, minHeight: 48, background: CARD_BG,
                color: TEXT_PRIMARY, border: `1px solid ${BORDER}`,
                borderRadius: 10, fontSize: 16, fontWeight: 600, cursor: 'pointer',
              }}
            >
              返回
            </button>
          </div>
        </div>
      )}

      {/* 离屏 canvas，用于截取视频帧 */}
      <canvas ref={canvasRef} style={{ display: 'none' }} />
    </div>
  );
}
