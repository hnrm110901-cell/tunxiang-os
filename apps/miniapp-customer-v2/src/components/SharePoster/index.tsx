/**
 * SharePoster — canvas-based promotional poster generator
 *
 * Flow:
 *  1. Render hidden canvas (600×900 logical px)
 *  2. Draw: dark bg → dish image → store name → discount badge → QR placeholder
 *  3. "保存图片" → canvasToTempFilePath → saveImageToPhotosAlbum
 *  4. "分享给朋友" → shareAppMessage
 *
 * Canvas ID: "share-poster-canvas"
 */
import { View, Text, Canvas } from '@tarojs/components'
import Taro from '@tarojs/taro'
import React, { useCallback, useEffect, useRef, useState } from 'react'

// ─── Types ────────────────────────────────────────────────────────────────────

export interface SharePosterProps {
  visible: boolean
  dishName: string
  storeName: string
  discount?: string
  dishImageUrl?: string
  onClose: () => void
}

// ─── Canvas constants ─────────────────────────────────────────────────────────

const CANVAS_W = 600
const CANVAS_H = 900
const CANVAS_ID = 'share-poster-canvas'

// Brand colours
const BG_COLOR = '#0B1A20'
const CARD_COLOR = '#132029'
const BRAND_COLOR = '#FF6B2C'

// ─── Drawing helpers ──────────────────────────────────────────────────────────

function drawRoundRect(
  ctx: Taro.CanvasContext,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.lineTo(x + w - r, y)
  ctx.arcTo(x + w, y, x + w, y + r, r)
  ctx.lineTo(x + w, y + h - r)
  ctx.arcTo(x + w, y + h, x + w - r, y + h, r)
  ctx.lineTo(x + r, y + h)
  ctx.arcTo(x, y + h, x, y + h - r, r)
  ctx.lineTo(x, y + r)
  ctx.arcTo(x, y, x + r, y, r)
  ctx.closePath()
}

function drawPosterOnCtx(
  ctx: Taro.CanvasContext,
  dishName: string,
  storeName: string,
  discount?: string,
): void {
  // ── Background
  ctx.setFillStyle(BG_COLOR)
  ctx.fillRect(0, 0, CANVAS_W, CANVAS_H)

  // ── Decorative top accent strip
  ctx.setFillStyle(BRAND_COLOR)
  ctx.fillRect(0, 0, CANVAS_W, 6)

  // ── Card background (image area)
  ctx.setFillStyle(CARD_COLOR)
  drawRoundRect(ctx, 24, 28, CANVAS_W - 48, 400, 20)
  ctx.fill()

  // ── Dish image placeholder (grey box with camera icon hint)
  ctx.setFillStyle('#1A2E38')
  drawRoundRect(ctx, 24, 28, CANVAS_W - 48, 400, 20)
  ctx.fill()

  // Camera icon placeholder lines
  ctx.setStrokeStyle('rgba(158,181,192,0.2)')
  ctx.setLineWidth(2)
  // Outer frame
  const camX = CANVAS_W / 2 - 36
  const camY = 200
  drawRoundRect(ctx, camX, camY, 72, 52, 8)
  ctx.stroke()
  // Lens circle
  ctx.beginPath()
  ctx.arc(CANVAS_W / 2, camY + 26, 14, 0, Math.PI * 2)
  ctx.stroke()

  ctx.setFillStyle('rgba(158,181,192,0.25)')
  ctx.setFontSize(22)
  ctx.setTextAlign('center')
  ctx.fillText('菜品图片', CANVAS_W / 2, camY + 82)

  // ── Store name
  ctx.setFillStyle('rgba(158,181,192,0.7)')
  ctx.setFontSize(24)
  ctx.setTextAlign('center')
  ctx.fillText(storeName, CANVAS_W / 2, 470)

  // ── Dish name
  ctx.setFillStyle('#FFFFFF')
  ctx.setFontSize(44)
  ctx.setTextAlign('center')
  // Simple line-wrap: split if longer than ~14 chars
  if (dishName.length <= 14) {
    ctx.fillText(dishName, CANVAS_W / 2, 530)
  } else {
    const half = Math.ceil(dishName.length / 2)
    ctx.fillText(dishName.slice(0, half), CANVAS_W / 2, 520)
    ctx.fillText(dishName.slice(half), CANVAS_W / 2, 574)
  }

  // ── Discount badge
  if (discount) {
    const badgeW = 240
    const badgeH = 68
    const badgeX = (CANVAS_W - badgeW) / 2
    const badgeY = 610

    ctx.setFillStyle(BRAND_COLOR)
    drawRoundRect(ctx, badgeX, badgeY, badgeW, badgeH, 34)
    ctx.fill()

    ctx.setFillStyle('#FFFFFF')
    ctx.setFontSize(30)
    ctx.setTextAlign('center')
    ctx.fillText(discount, CANVAS_W / 2, badgeY + 44)
  }

  // ── Divider
  ctx.setStrokeStyle('rgba(158,181,192,0.1)')
  ctx.setLineWidth(1)
  ctx.beginPath()
  ctx.moveTo(40, 720)
  ctx.lineTo(CANVAS_W - 40, 720)
  ctx.stroke()

  // ── QR code placeholder
  const qrSize = 120
  const qrX = (CANVAS_W - qrSize) / 2
  const qrY = 748

  ctx.setFillStyle('#FFFFFF')
  drawRoundRect(ctx, qrX, qrY, qrSize, qrSize, 8)
  ctx.fill()

  // Inner QR grid hint
  ctx.setFillStyle('rgba(11,26,32,0.15)')
  const cellSize = 12
  for (let row = 0; row < 4; row++) {
    for (let col = 0; col < 4; col++) {
      if ((row + col) % 2 === 0) {
        ctx.fillRect(qrX + 16 + col * cellSize, qrY + 16 + row * cellSize, 10, 10)
      }
    }
  }

  ctx.setFillStyle('rgba(158,181,192,0.5)')
  ctx.setFontSize(20)
  ctx.setTextAlign('center')
  ctx.fillText('扫码点餐', CANVAS_W / 2, qrY + qrSize + 28)

  // ── Bottom branding
  ctx.setFillStyle('rgba(158,181,192,0.35)')
  ctx.setFontSize(22)
  ctx.setTextAlign('center')
  ctx.fillText('屯象OS · 智慧餐饮', CANVAS_W / 2, CANVAS_H - 28)

  ctx.draw()
}

// ─── Component ────────────────────────────────────────────────────────────────

const SharePoster: React.FC<SharePosterProps> = ({
  visible,
  dishName,
  storeName,
  discount,
  onClose,
}) => {
  const [rendered, setRendered] = useState(false)
  const [translateY, setTranslateY] = useState(100)
  const [saving, setSaving] = useState(false)
  const [tempFilePath, setTempFilePath] = useState<string | null>(null)
  const drawnRef = useRef(false)

  // Show / hide animation
  useEffect(() => {
    if (visible) {
      setRendered(true)
      drawnRef.current = false
      requestAnimationFrame(() => {
        requestAnimationFrame(() => setTranslateY(0))
      })
    } else {
      setTranslateY(100)
      const t = setTimeout(() => {
        setRendered(false)
        setTempFilePath(null)
        drawnRef.current = false
      }, 320)
      return () => clearTimeout(t)
    }
  }, [visible])

  // Draw poster after the sheet is visible
  useEffect(() => {
    if (!rendered || drawnRef.current) return

    // Short delay so canvas is in the DOM
    const t = setTimeout(() => {
      try {
        const ctx = Taro.createCanvasContext(CANVAS_ID)
        drawPosterOnCtx(ctx, dishName, storeName, discount)
        drawnRef.current = true
      } catch (e) {
        console.warn('[SharePoster] canvas draw error:', e)
      }
    }, 200)
    return () => clearTimeout(t)
  }, [rendered, dishName, storeName, discount])

  // Save image to album
  const handleSave = useCallback(async () => {
    if (saving) return
    setSaving(true)

    try {
      const res = await Taro.canvasToTempFilePath({
        canvasId: CANVAS_ID,
        x: 0,
        y: 0,
        width: CANVAS_W,
        height: CANVAS_H,
        destWidth: CANVAS_W * 2,
        destHeight: CANVAS_H * 2,
        fileType: 'jpg',
        quality: 0.95,
      })
      setTempFilePath(res.tempFilePath)

      await Taro.saveImageToPhotosAlbum({ filePath: res.tempFilePath })
      Taro.showToast({ title: '已保存到相册', icon: 'success', duration: 2000 })
    } catch (err: any) {
      if (err?.errMsg?.includes('auth deny')) {
        Taro.showModal({
          title: '需要相册权限',
          content: '请在设置中允许访问您的相册',
          confirmText: '去设置',
          success: (res) => {
            if (res.confirm) Taro.openSetting()
          },
        })
      } else {
        Taro.showToast({ title: '保存失败', icon: 'error', duration: 2000 })
      }
    } finally {
      setSaving(false)
    }
  }, [saving])

  // Share to friend
  const handleShare = useCallback(() => {
    Taro.showShareMenu({ withShareTicket: true })
    Taro.shareAppMessage({
      title: `${storeName} · ${dishName}${discount ? ' ' + discount : ''}`,
      path: '/pages/index/index',
      imageUrl: tempFilePath || '',
    })
  }, [dishName, storeName, discount, tempFilePath])

  if (!rendered) return null

  return (
    <>
      {/* Backdrop */}
      <View
        style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(0,0,0,0.75)',
          zIndex: 900,
          opacity: translateY === 0 ? 1 : 0,
          transition: 'opacity 0.32s ease',
        }}
        onClick={onClose}
      />

      {/* Sheet */}
      <View
        style={{
          position: 'fixed',
          left: 0,
          right: 0,
          bottom: 0,
          zIndex: 901,
          background: '#0B1A20',
          borderRadius: '32rpx 32rpx 0 0',
          paddingBottom: 'env(safe-area-inset-bottom)',
          transform: `translateY(${translateY}%)`,
          transition: 'transform 0.32s cubic-bezier(0.32,0.72,0,1)',
        }}
      >
        {/* Handle */}
        <View
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            paddingTop: '20rpx',
            paddingBottom: '8rpx',
          }}
        >
          <View
            style={{
              width: '80rpx',
              height: '8rpx',
              borderRadius: '4rpx',
              background: '#2A4558',
            }}
          />
        </View>

        {/* Header */}
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '20rpx 32rpx 24rpx',
          }}
        >
          <Text
            style={{
              color: '#FFFFFF',
              fontSize: '36rpx',
              fontWeight: '700',
            }}
          >
            分享海报
          </Text>
          <View
            style={{
              width: '64rpx',
              height: '64rpx',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
            onClick={onClose}
          >
            <Text style={{ color: '#9EB5C0', fontSize: '40rpx' }}>×</Text>
          </View>
        </View>

        {/* Canvas — poster preview */}
        <View
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '0 32rpx 32rpx',
          }}
        >
          <View
            style={{
              width: '480rpx',
              height: '720rpx',
              borderRadius: '24rpx',
              overflow: 'hidden',
              boxShadow: '0 8rpx 40rpx rgba(0,0,0,0.6)',
            }}
          >
            <Canvas
              id={CANVAS_ID}
              canvasId={CANVAS_ID}
              style={{
                width: `${CANVAS_W}px`,
                height: `${CANVAS_H}px`,
                transform: 'scale(0.8)',
                transformOrigin: 'top left',
              }}
            />
          </View>
        </View>

        {/* Action buttons */}
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            gap: '20rpx',
            padding: '0 32rpx 24rpx',
          }}
        >
          {/* 保存图片 */}
          <View
            style={{
              flex: 1,
              height: '96rpx',
              background: '#1A2E38',
              border: '2rpx solid #2A4558',
              borderRadius: '48rpx',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8rpx',
              opacity: saving ? 0.6 : 1,
            }}
            onClick={handleSave}
          >
            <Text style={{ fontSize: '34rpx', lineHeight: '1' }}>💾</Text>
            <Text
              style={{
                color: '#9EB5C0',
                fontSize: '30rpx',
                fontWeight: '600',
              }}
            >
              {saving ? '保存中…' : '保存图片'}
            </Text>
          </View>

          {/* 分享给朋友 */}
          <View
            style={{
              flex: 1,
              height: '96rpx',
              background: '#07C160',
              borderRadius: '48rpx',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8rpx',
              boxShadow: '0 4rpx 20rpx rgba(7,193,96,0.35)',
            }}
            onClick={handleShare}
          >
            <Text style={{ fontSize: '34rpx', lineHeight: '1' }}>💬</Text>
            <Text
              style={{
                color: '#FFFFFF',
                fontSize: '30rpx',
                fontWeight: '700',
              }}
            >
              分享给朋友
            </Text>
          </View>
        </View>
      </View>
    </>
  )
}

export default SharePoster
