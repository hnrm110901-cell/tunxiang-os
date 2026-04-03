import { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLang } from '@/i18n/LangContext';
import { setApiTenantId, setApiLang } from '@/api/index';
import { resolveTableQR } from '@/api/orderApi';
import { useOrderStore } from '@/store/useOrderStore';
import LangSwitcher from '@/components/LangSwitcher';

/** 扫码入口页 — 自动调摄像头扫桌码 */
export default function ScanEntry() {
  const { t, lang } = useLang();
  const navigate = useNavigate();
  const setStoreInfo = useOrderStore((s) => s.setStoreInfo);

  const videoRef = useRef<HTMLVideoElement>(null);
  const [cameraError, setCameraError] = useState('');
  const [storeData, setStoreData] = useState<{
    storeId: string; storeName: string; tableNo: string; tenantId: string;
  } | null>(null);
  const [scanning, setScanning] = useState(false);

  // 解析二维码内容
  const handleQRResult = useCallback(async (code: string) => {
    if (storeData) return; // 已扫描成功
    try {
      const data = await resolveTableQR(code);
      setStoreData(data);
      setStoreInfo(data);
      setApiTenantId(data.tenantId);
    } catch {
      // 解析失败，继续扫描
    }
  }, [storeData, setStoreInfo]);

  // 启动摄像头扫码
  useEffect(() => {
    let stream: MediaStream | null = null;
    let animFrameId: number;
    let canvas: HTMLCanvasElement;
    let ctx: CanvasRenderingContext2D | null;

    async function startCamera() {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: 'environment', width: 640, height: 480 },
        });
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play();
          setScanning(true);
          scanFrame();
        }
      } catch {
        setCameraError(t('scanPermissionDenied'));
      }
    }

    function scanFrame() {
      if (!videoRef.current || videoRef.current.readyState < 2) {
        animFrameId = requestAnimationFrame(scanFrame);
        return;
      }
      if (!canvas) {
        canvas = document.createElement('canvas');
        canvas.width = 640;
        canvas.height = 480;
        ctx = canvas.getContext('2d');
      }
      if (ctx) {
        ctx.drawImage(videoRef.current, 0, 0, 640, 480);
        // 使用 BarcodeDetector API（Chrome/Edge/Safari 支持）
        if ('BarcodeDetector' in window) {
          const detector = new (window as any).BarcodeDetector({ formats: ['qr_code'] });
          const imageData = ctx.getImageData(0, 0, 640, 480);
          detector.detect(imageData).then((barcodes: any[]) => {
            if (barcodes.length > 0) {
              handleQRResult(barcodes[0].rawValue);
            }
          }).catch(() => { /* 忽略单帧失败 */ });
        }
      }
      animFrameId = requestAnimationFrame(scanFrame);
    }

    startCamera();

    return () => {
      cancelAnimationFrame(animFrameId);
      stream?.getTracks().forEach((track) => track.stop());
    };
  }, [handleQRResult, t]);

  // 设置语言到 API header
  useEffect(() => {
    setApiLang(lang);
  }, [lang]);

  const handleStart = () => {
    if (storeData) {
      navigate('/menu');
    }
  };

  // 手动输入桌号（备用方案）
  const [manualCode, setManualCode] = useState('');
  const handleManualSubmit = async () => {
    if (!manualCode.trim()) return;
    await handleQRResult(manualCode.trim());
  };

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', minHeight: '100vh',
      background: 'var(--tx-bg-primary)', padding: '16px',
    }}>
      {/* 标题 */}
      <h1 style={{
        fontSize: 'var(--tx-font-xxl)', fontWeight: 700,
        color: 'var(--tx-text-primary)', textAlign: 'center',
        marginTop: 40, marginBottom: 24,
      }}>
        {t('scanTitle')}
      </h1>

      {/* 语言选择 */}
      <LangSwitcher />

      {/* 摄像头区域 */}
      <div style={{
        marginTop: 32, borderRadius: 'var(--tx-radius-lg)',
        overflow: 'hidden', position: 'relative',
        aspectRatio: '4/3', background: '#000',
      }}>
        <video
          ref={videoRef}
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
          playsInline
          muted
        />
        {/* 扫描框 */}
        {scanning && !storeData && (
          <div style={{
            position: 'absolute', inset: '20%',
            border: '2px solid var(--tx-brand)',
            borderRadius: 12,
          }}>
            <div style={{
              position: 'absolute', top: -2, left: -2,
              width: 24, height: 24,
              borderTop: '4px solid var(--tx-brand)',
              borderLeft: '4px solid var(--tx-brand)',
              borderRadius: '4px 0 0 0',
            }} />
            <div style={{
              position: 'absolute', top: -2, right: -2,
              width: 24, height: 24,
              borderTop: '4px solid var(--tx-brand)',
              borderRight: '4px solid var(--tx-brand)',
              borderRadius: '0 4px 0 0',
            }} />
            <div style={{
              position: 'absolute', bottom: -2, left: -2,
              width: 24, height: 24,
              borderBottom: '4px solid var(--tx-brand)',
              borderLeft: '4px solid var(--tx-brand)',
              borderRadius: '0 0 0 4px',
            }} />
            <div style={{
              position: 'absolute', bottom: -2, right: -2,
              width: 24, height: 24,
              borderBottom: '4px solid var(--tx-brand)',
              borderRight: '4px solid var(--tx-brand)',
              borderRadius: '0 0 4px 0',
            }} />
          </div>
        )}
        {cameraError && (
          <div style={{
            position: 'absolute', inset: 0,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: 'var(--tx-text-secondary)', fontSize: 'var(--tx-font-sm)',
            padding: 24, textAlign: 'center',
          }}>
            {cameraError}
          </div>
        )}
      </div>

      <p style={{
        textAlign: 'center', marginTop: 12,
        color: 'var(--tx-text-tertiary)', fontSize: 'var(--tx-font-sm)',
      }}>
        {t('scanHint')}
      </p>

      {/* 手动输入（备用） */}
      {!storeData && (
        <div style={{ display: 'flex', gap: 8, marginTop: 24 }}>
          <input
            type="text"
            value={manualCode}
            onChange={(e) => setManualCode(e.target.value)}
            placeholder="手动输入桌码"
            style={{
              flex: 1, height: 48, padding: '0 16px',
              borderRadius: 'var(--tx-radius-md)',
              background: 'var(--tx-bg-tertiary)',
              color: 'var(--tx-text-primary)',
              fontSize: 'var(--tx-font-md)',
            }}
          />
          <button
            className="tx-pressable"
            onClick={handleManualSubmit}
            style={{
              padding: '0 20px', height: 48,
              borderRadius: 'var(--tx-radius-md)',
              background: 'var(--tx-brand)',
              color: '#fff', fontWeight: 600,
              fontSize: 'var(--tx-font-md)',
            }}
          >
            {t('confirm')}
          </button>
        </div>
      )}

      {/* 门店信息 */}
      {storeData && (
        <div style={{
          marginTop: 24, padding: 20,
          borderRadius: 'var(--tx-radius-lg)',
          background: 'var(--tx-bg-card)',
        }}
        className="tx-fade-in"
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ color: 'var(--tx-text-secondary)', fontSize: 'var(--tx-font-sm)' }}>
              {t('storeInfo')}
            </span>
            <span style={{
              padding: '4px 12px', borderRadius: 'var(--tx-radius-full)',
              background: 'var(--tx-brand-light)', color: 'var(--tx-brand)',
              fontSize: 'var(--tx-font-sm)', fontWeight: 600,
            }}>
              {t('tableNo')} {storeData.tableNo}
            </span>
          </div>
          <div style={{
            marginTop: 8, fontSize: 'var(--tx-font-xl)',
            fontWeight: 700, color: 'var(--tx-text-primary)',
          }}>
            {storeData.storeName}
          </div>
        </div>
      )}

      {/* 开始点餐按钮 */}
      <div style={{ flex: 1 }} />
      <button
        className="tx-pressable"
        onClick={handleStart}
        disabled={!storeData}
        style={{
          width: '100%', height: 56,
          borderRadius: 'var(--tx-radius-full)',
          background: storeData ? 'var(--tx-brand)' : 'var(--tx-bg-tertiary)',
          color: storeData ? '#fff' : 'var(--tx-text-tertiary)',
          fontSize: 'var(--tx-font-lg)', fontWeight: 700,
          marginBottom: 16,
          transition: 'background 0.2s',
        }}
      >
        {t('startOrder')}
      </button>
    </div>
  );
}
