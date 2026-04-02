/**
 * scan-order/index.tsx — 扫码点餐入口
 *
 * Features:
 *  - Camera scan view (Taro camera component)
 *  - "扫描桌台二维码开始点餐" instruction overlay
 *  - Manual table number input fallback
 *  - QR parse: extract store_id + table_id from URL params
 *  - On success: useStoreInfo.loadFromQRCode → navigate to menu
 *  - Camera permission denied → settings guide
 *  - Error handling for unrecognised QR codes
 */

import React, { useState, useCallback, useRef } from 'react'
import { View, Text, Camera, Input } from '@tarojs/components'
import Taro, { CameraContext } from '@tarojs/taro'
import { useStoreInfo } from '../../../store/useStoreInfo'

// ─── Brand tokens ─────────────────────────────────────────────────────────────
const C = {
  primary: '#FF6B2C',
  bgDeep: '#0B1A20',
  bgCard: '#132029',
  bgOverlay: 'rgba(11,26,32,0.75)',
  border: '#1E3040',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#5A7A88',
  red: '#E53935',
  white: '#fff',
  disabled: '#2A4050',
} as const

// ─── QR URL validation ────────────────────────────────────────────────────────

/**
 * Given a raw QR string, validate it contains store_id and optionally table_id.
 * Returns { valid, storeId, tableId } or { valid: false }.
 */
function parseQRPayload(raw: string): {
  valid: boolean
  storeId?: string
  tableId?: string
  qrData?: string
} {
  if (!raw) return { valid: false }

  let searchString = raw.trim()

  try {
    const url = new URL(raw)
    searchString = url.search.replace(/^\?/, '')
  } catch {
    // not a URL — treat as query string
  }

  const params = new URLSearchParams(searchString)
  const storeId = params.get('store_id') ?? ''
  const tableId = params.get('table_id') ?? ''

  if (!storeId) return { valid: false }

  return { valid: true, storeId, tableId: tableId || undefined, qrData: raw }
}

// ─── Corner finder overlay ────────────────────────────────────────────────────

function ScanFrame() {
  const cornerSize = 48
  const borderSize = 4
  const color = C.primary

  const corner = (pos: { top?: number; bottom?: number; left?: number; right?: number }) => (
    <View
      style={{
        position: 'absolute',
        width: `${cornerSize}rpx`,
        height: `${cornerSize}rpx`,
        borderColor: color,
        borderStyle: 'solid',
        borderTopWidth: pos.top !== undefined ? `${borderSize}rpx` : 0,
        borderBottomWidth: pos.bottom !== undefined ? `${borderSize}rpx` : 0,
        borderLeftWidth: pos.left !== undefined ? `${borderSize}rpx` : 0,
        borderRightWidth: pos.right !== undefined ? `${borderSize}rpx` : 0,
        ...pos,
      }}
    />
  )

  return (
    <View
      style={{
        position: 'absolute',
        top: '50%',
        left: '50%',
        transform: 'translate(-50%, -50%)',
        width: '500rpx',
        height: '500rpx',
      }}
    >
      {corner({ top: 0, left: 0 })}
      {corner({ top: 0, right: 0 })}
      {corner({ bottom: 0, left: 0 })}
      {corner({ bottom: 0, right: 0 })}

      {/* Scan line animation */}
      <ScanLine />
    </View>
  )
}

function ScanLine() {
  const [offset, setOffset] = useState(0)
  const dirRef = useRef<1 | -1>(1)

  React.useEffect(() => {
    const timer = setInterval(() => {
      setOffset((prev) => {
        const next = prev + dirRef.current * 4
        if (next >= 100) dirRef.current = -1
        if (next <= 0) dirRef.current = 1
        return Math.max(0, Math.min(100, next))
      })
    }, 20)
    return () => clearInterval(timer)
  }, [])

  return (
    <View
      style={{
        position: 'absolute',
        left: '8rpx',
        right: '8rpx',
        height: '4rpx',
        background: `linear-gradient(to right, transparent, ${C.primary}, transparent)`,
        top: `${offset}%`,
        opacity: 0.85,
      }}
    />
  )
}

// ─── Permission denied guide ──────────────────────────────────────────────────

function PermissionDeniedView({ onRetry }: { onRetry: () => void }) {
  function openSettings() {
    Taro.openSetting({
      success: (res) => {
        if (res.authSetting['scope.camera']) {
          onRetry()
        }
      },
    })
  }

  return (
    <View
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '48rpx',
        gap: '32rpx',
      }}
    >
      <Text style={{ fontSize: '80rpx', lineHeight: '1' }}>📷</Text>

      <Text style={{ color: C.text1, fontSize: '32rpx', fontWeight: '600', textAlign: 'center' }}>
        需要摄像头权限
      </Text>

      <Text
        style={{
          color: C.text2,
          fontSize: '26rpx',
          textAlign: 'center',
          lineHeight: '40rpx',
        }}
      >
        请在设置中允许使用摄像头，才能扫描桌台二维码开始点餐。
      </Text>

      {/* Step guide */}
      <View
        style={{
          background: C.bgCard,
          borderRadius: '16rpx',
          padding: '24rpx',
          width: '100%',
        }}
      >
        {[
          '点击下方「前往设置」',
          '找到「摄像头」权限',
          '开启后返回小程序',
        ].map((step, i) => (
          <View
            key={i}
            style={{
              display: 'flex',
              flexDirection: 'row',
              alignItems: 'center',
              gap: '16rpx',
              marginBottom: i < 2 ? '16rpx' : 0,
            }}
          >
            <View
              style={{
                width: '40rpx',
                height: '40rpx',
                borderRadius: '20rpx',
                background: C.primary,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
              }}
            >
              <Text style={{ color: C.white, fontSize: '22rpx', fontWeight: '700' }}>
                {i + 1}
              </Text>
            </View>
            <Text style={{ color: C.text2, fontSize: '26rpx', flex: 1 }}>{step}</Text>
          </View>
        ))}
      </View>

      <View
        style={{
          background: C.primary,
          borderRadius: '44rpx',
          height: '88rpx',
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
        onClick={openSettings}
      >
        <Text style={{ color: C.white, fontSize: '32rpx', fontWeight: '700' }}>
          前往设置
        </Text>
      </View>
    </View>
  )
}

// ─── Manual input modal ───────────────────────────────────────────────────────

interface ManualInputProps {
  visible: boolean
  onConfirm: (storeId: string, tableNo: string) => void
  onClose: () => void
}

function ManualInputModal({ visible, onConfirm, onClose }: ManualInputProps) {
  const [storeIdInput, setStoreIdInput] = useState('')
  const [tableInput, setTableInput] = useState('')
  const [error, setError] = useState<string | null>(null)

  function handleConfirm() {
    setError(null)
    if (!storeIdInput.trim()) {
      setError('请输入门店编号')
      return
    }
    onConfirm(storeIdInput.trim(), tableInput.trim())
  }

  if (!visible) return null

  return (
    <View
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'flex-end',
      }}
    >
      <View
        style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.7)' }}
        onClick={onClose}
      />
      <View
        style={{
          position: 'relative',
          background: C.bgCard,
          borderRadius: '24rpx 24rpx 0 0',
          padding: '32rpx 32rpx calc(32rpx + env(safe-area-inset-bottom))',
        }}
      >
        {/* Handle */}
        <View style={{ display: 'flex', justifyContent: 'center', marginBottom: '24rpx' }}>
          <View
            style={{
              width: '64rpx',
              height: '8rpx',
              borderRadius: '4rpx',
              background: C.border,
            }}
          />
        </View>

        <Text style={{ color: C.text1, fontSize: '32rpx', fontWeight: '600', marginBottom: '32rpx' }}>
          手动输入桌台信息
        </Text>

        {/* Store ID input */}
        <View style={{ marginBottom: '24rpx' }}>
          <Text style={{ color: C.text2, fontSize: '24rpx', marginBottom: '12rpx' }}>
            门店编号 *
          </Text>
          <Input
            value={storeIdInput}
            onInput={(e) => setStoreIdInput(e.detail.value)}
            placeholder='如：S001'
            placeholderStyle={`color:${C.text3}`}
            style={{
              background: C.bgDeep,
              color: C.text1,
              fontSize: '28rpx',
              borderRadius: '12rpx',
              padding: '20rpx 24rpx',
              border: `1rpx solid ${C.border}`,
              height: '88rpx',
            }}
          />
        </View>

        {/* Table number input */}
        <View style={{ marginBottom: error ? '12rpx' : '32rpx' }}>
          <Text style={{ color: C.text2, fontSize: '24rpx', marginBottom: '12rpx' }}>
            桌台号（可选）
          </Text>
          <Input
            value={tableInput}
            onInput={(e) => setTableInput(e.detail.value)}
            placeholder='如：A01 或 12'
            placeholderStyle={`color:${C.text3}`}
            style={{
              background: C.bgDeep,
              color: C.text1,
              fontSize: '28rpx',
              borderRadius: '12rpx',
              padding: '20rpx 24rpx',
              border: `1rpx solid ${C.border}`,
              height: '88rpx',
            }}
          />
        </View>

        {error && (
          <Text style={{ color: C.red, fontSize: '24rpx', marginBottom: '24rpx' }}>
            {error}
          </Text>
        )}

        <View style={{ display: 'flex', flexDirection: 'row', gap: '16rpx' }}>
          <View
            style={{
              flex: 1,
              height: '88rpx',
              border: `2rpx solid ${C.border}`,
              borderRadius: '44rpx',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
            onClick={onClose}
          >
            <Text style={{ color: C.text2, fontSize: '28rpx' }}>取消</Text>
          </View>
          <View
            style={{
              flex: 2,
              height: '88rpx',
              background: C.primary,
              borderRadius: '44rpx',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
            onClick={handleConfirm}
          >
            <Text style={{ color: C.white, fontSize: '30rpx', fontWeight: '700' }}>
              开始点餐
            </Text>
          </View>
        </View>
      </View>
    </View>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

type ScanState = 'idle' | 'scanning' | 'success' | 'error' | 'permission-denied'

export default function ScanOrderPage() {
  const { loadFromQRCode, setStore, setTable } = useStoreInfo()

  const [scanState, setScanState] = useState<ScanState>('idle')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [manualVisible, setManualVisible] = useState(false)
  const [torchOn, setTorchOn] = useState(false)
  const cameraContextRef = useRef<CameraContext | null>(null)

  // Whether camera is currently mounted
  const [cameraReady, setCameraReady] = useState(false)
  const processingRef = useRef(false)

  // Initialize camera context once ready
  function handleCameraReady() {
    setCameraReady(true)
    setScanState('scanning')
    cameraContextRef.current = Taro.createCameraContext()
  }

  function handleCameraError(e: { detail?: { errMsg?: string } }) {
    const msg = e.detail?.errMsg ?? ''
    if (msg.includes('auth') || msg.includes('denied') || msg.includes('permission')) {
      setScanState('permission-denied')
    } else {
      setErrorMsg('摄像头初始化失败，请重试')
      setScanState('error')
    }
  }

  // The Camera component emits onScanCode (WeChat 2.18+); also support manual scan
  function handleScanCode(e: { detail?: { result?: string } }) {
    const result = e.detail?.result
    if (!result || processingRef.current) return
    processQRResult(result)
  }

  function processQRResult(raw: string) {
    if (processingRef.current) return
    processingRef.current = true

    const parsed = parseQRPayload(raw)
    if (!parsed.valid) {
      setErrorMsg('无法识别此二维码，请确认是否为屯象餐厅的桌台码')
      setScanState('error')
      processingRef.current = false
      return
    }

    // Haptic feedback
    Taro.vibrateShort({ type: 'medium' }).catch(() => {})

    // Update store info
    if (parsed.qrData) {
      loadFromQRCode(parsed.qrData)
    }

    setScanState('success')

    // Navigate to menu
    setTimeout(() => {
      Taro.redirectTo({ url: '/pages/menu/index' }).catch(() => {
        Taro.switchTab({ url: '/pages/menu/index' })
      })
      processingRef.current = false
    }, 600)
  }

  function handleManualInput(storeId: string, tableNo: string) {
    setManualVisible(false)
    // Build a synthetic QR string
    const fakeQR = `store_id=${encodeURIComponent(storeId)}&table_id=${encodeURIComponent(tableNo)}&mode=dine-in`
    processQRResult(fakeQR)
  }

  function handleRetryPermission() {
    setScanState('idle')
    // Force re-mount of camera by toggling a key — done via cameraReady reset
    setCameraReady(false)
    setTimeout(() => setScanState('scanning'), 100)
  }

  function handleRetryError() {
    setErrorMsg(null)
    setScanState('scanning')
    processingRef.current = false
  }

  // ── Tap to scan via wx.scanCode fallback ───────────────────────────────────
  function useSystemScan() {
    Taro.scanCode({
      onlyFromCamera: true,
      scanType: ['qrCode'],
      success: (res) => {
        processQRResult(res.result)
      },
      fail: (err) => {
        const msg =
          typeof err === 'object' && err !== null && 'errMsg' in err
            ? String((err as { errMsg: string }).errMsg)
            : '扫码失败'
        if (msg.includes('cancel')) return
        if (msg.includes('auth') || msg.includes('denied')) {
          setScanState('permission-denied')
        } else {
          setErrorMsg('扫码失败，请重试')
          setScanState('error')
        }
      },
    })
  }

  // ── Render: permission denied ──────────────────────────────────────────────
  if (scanState === 'permission-denied') {
    return (
      <View style={{ minHeight: '100vh', background: C.bgDeep, display: 'flex', flexDirection: 'column' }}>
        {/* Back button */}
        <View
          style={{ padding: '20rpx 24rpx', display: 'flex', flexDirection: 'row', alignItems: 'center' }}
        >
          <View
            style={{ padding: '8rpx 16rpx' }}
            onClick={() => Taro.navigateBack()}
          >
            <Text style={{ color: C.text2, fontSize: '28rpx' }}>‹ 返回</Text>
          </View>
        </View>
        <PermissionDeniedView onRetry={handleRetryPermission} />
      </View>
    )
  }

  // ── Render: error state ────────────────────────────────────────────────────
  if (scanState === 'error') {
    return (
      <View
        style={{
          minHeight: '100vh',
          background: C.bgDeep,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '48rpx',
          gap: '32rpx',
        }}
      >
        <Text style={{ fontSize: '80rpx', lineHeight: '1' }}>⚠️</Text>
        <Text style={{ color: C.text1, fontSize: '32rpx', fontWeight: '600', textAlign: 'center' }}>
          识别失败
        </Text>
        <Text
          style={{
            color: C.text2,
            fontSize: '26rpx',
            textAlign: 'center',
            lineHeight: '40rpx',
          }}
        >
          {errorMsg}
        </Text>
        <View style={{ display: 'flex', flexDirection: 'column', gap: '16rpx', width: '100%' }}>
          <View
            style={{
              background: C.primary,
              borderRadius: '44rpx',
              height: '88rpx',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
            onClick={handleRetryError}
          >
            <Text style={{ color: C.white, fontSize: '30rpx', fontWeight: '700' }}>
              重新扫码
            </Text>
          </View>
          <View
            style={{
              border: `2rpx solid ${C.border}`,
              borderRadius: '44rpx',
              height: '88rpx',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
            onClick={() => {
              setErrorMsg(null)
              setScanState('scanning')
              setManualVisible(true)
              processingRef.current = false
            }}
          >
            <Text style={{ color: C.text2, fontSize: '28rpx' }}>手动输入桌台号</Text>
          </View>
        </View>
      </View>
    )
  }

  // ── Render: success flash ──────────────────────────────────────────────────
  if (scanState === 'success') {
    return (
      <View
        style={{
          minHeight: '100vh',
          background: C.bgDeep,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '32rpx',
        }}
      >
        <View
          style={{
            width: '160rpx',
            height: '160rpx',
            borderRadius: '80rpx',
            background: C.primary,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Text style={{ color: C.white, fontSize: '80rpx', lineHeight: '1' }}>✓</Text>
        </View>
        <Text style={{ color: C.text1, fontSize: '32rpx', fontWeight: '600' }}>
          识别成功，正在跳转...
        </Text>
      </View>
    )
  }

  // ── Render: camera scan view ───────────────────────────────────────────────
  return (
    <View style={{ height: '100vh', background: '#000', position: 'relative', overflow: 'hidden' }}>
      {/* Camera */}
      <Camera
        style={{ width: '100%', height: '100%', position: 'absolute', inset: 0 }}
        mode='scanCode'
        resolution='medium'
        flash={torchOn ? 'torch' : 'off'}
        scanArea={[200, 150, 550, 600]}
        onReady={handleCameraReady}
        onError={handleCameraError}
        onScanCode={handleScanCode}
        onInitDone={() => setCameraReady(true)}
      />

      {/* Dark overlay with scan frame hole */}
      <View
        style={{
          position: 'absolute',
          inset: 0,
          pointerEvents: 'none',
        }}
      >
        {/* Top overlay */}
        <View
          style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 'calc(50% - 250rpx)', background: C.bgOverlay }}
        />
        {/* Bottom overlay */}
        <View
          style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: 'calc(50% - 250rpx)', background: C.bgOverlay }}
        />
        {/* Left overlay */}
        <View
          style={{
            position: 'absolute',
            top: 'calc(50% - 250rpx)',
            bottom: 'calc(50% - 250rpx)',
            left: 0,
            width: 'calc(50% - 250rpx)',
            background: C.bgOverlay,
          }}
        />
        {/* Right overlay */}
        <View
          style={{
            position: 'absolute',
            top: 'calc(50% - 250rpx)',
            bottom: 'calc(50% - 250rpx)',
            right: 0,
            width: 'calc(50% - 250rpx)',
            background: C.bgOverlay,
          }}
        />
      </View>

      {/* Corner frame + scan line */}
      {cameraReady && <ScanFrame />}

      {/* Top bar */}
      <View
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          paddingTop: 'env(safe-area-inset-top)',
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          padding: '20rpx 24rpx',
          zIndex: 10,
        }}
      >
        <View
          style={{
            background: 'rgba(0,0,0,0.4)',
            borderRadius: '32rpx',
            padding: '12rpx 24rpx',
          }}
          onClick={() => Taro.navigateBack()}
        >
          <Text style={{ color: C.white, fontSize: '28rpx' }}>‹ 返回</Text>
        </View>
        <View style={{ flex: 1 }} />
        {/* Torch toggle */}
        <View
          style={{
            background: torchOn ? 'rgba(255,107,44,0.8)' : 'rgba(0,0,0,0.4)',
            borderRadius: '32rpx',
            padding: '12rpx 24rpx',
          }}
          onClick={() => setTorchOn(!torchOn)}
        >
          <Text style={{ color: C.white, fontSize: '28rpx' }}>
            {torchOn ? '🔦 关闭' : '🔦 补光'}
          </Text>
        </View>
      </View>

      {/* Center instruction */}
      <View
        style={{
          position: 'absolute',
          top: '50%',
          left: 0,
          right: 0,
          marginTop: '300rpx',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: '16rpx',
          zIndex: 10,
        }}
      >
        <Text
          style={{
            color: C.white,
            fontSize: '28rpx',
            textAlign: 'center',
            background: 'rgba(0,0,0,0.5)',
            borderRadius: '32rpx',
            padding: '12rpx 32rpx',
          }}
        >
          扫描桌台二维码开始点餐
        </Text>
      </View>

      {/* Bottom actions */}
      <View
        style={{
          position: 'absolute',
          bottom: 0,
          left: 0,
          right: 0,
          paddingBottom: 'calc(48rpx + env(safe-area-inset-bottom))',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: '24rpx',
          zIndex: 10,
        }}
      >
        {/* System scan fallback (for platforms without Camera onScanCode) */}
        <View
          style={{
            background: C.primary,
            borderRadius: '44rpx',
            height: '88rpx',
            minWidth: '400rpx',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '0 48rpx',
          }}
          onClick={useSystemScan}
        >
          <Text style={{ color: C.white, fontSize: '30rpx', fontWeight: '700' }}>
            点击扫码
          </Text>
        </View>

        {/* Manual input fallback */}
        <View
          style={{
            background: 'rgba(0,0,0,0.5)',
            borderRadius: '44rpx',
            height: '72rpx',
            minWidth: '320rpx',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '0 40rpx',
            border: `1rpx solid rgba(255,255,255,0.2)`,
          }}
          onClick={() => setManualVisible(true)}
        >
          <Text style={{ color: 'rgba(255,255,255,0.8)', fontSize: '26rpx' }}>
            手动输入桌台号
          </Text>
        </View>
      </View>

      {/* Manual input modal */}
      <ManualInputModal
        visible={manualVisible}
        onConfirm={handleManualInput}
        onClose={() => setManualVisible(false)}
      />
    </View>
  )
}
