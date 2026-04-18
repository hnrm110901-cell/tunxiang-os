/**
 * feedback/index.tsx — 意见反馈
 *
 * Features:
 *  - Feedback type tabs: 功能建议 / 问题反馈 / 服务投诉 / 其他
 *  - Textarea (500 chars max) with live counter
 *  - Upload up to 3 screenshots (Taro.chooseImage)
 *  - Optional contact info (phone / email)
 *  - Submit → POST /api/v1/feedback → success state with ticket number
 *  - My feedback history: list with status badge
 *  - Tap history item → reply detail view
 */

import React, { useState, useEffect } from 'react'
import Taro from '@tarojs/taro'
import { View, Text, Textarea, Image, ScrollView, Input } from '@tarojs/components'
import { txRequest } from '../../utils/request'

// ─── Brand tokens ─────────────────────────────────────────────────────────────
const C = {
  primary: '#FF6B35',
  primaryDark: '#E55A1F',
  bgDeep: '#0B1A20',
  bgCard: '#132029',
  bgHover: '#1A2E38',
  border: '#1E3040',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#5A7A88',
  red: '#E53935',
  success: '#4CAF50',
  white: '#fff',
} as const

// ─── Types ────────────────────────────────────────────────────────────────────
type FeedbackType = 'suggestion' | 'bug' | 'complaint' | 'other'

interface FeedbackTab {
  key: FeedbackType
  label: string
}

interface FeedbackRecord {
  id: string
  type: FeedbackType
  content: string
  status: 'pending' | 'replied'
  createdAt: string
  reply?: string
  ticketNo: string
}

interface SubmitPayload {
  type: FeedbackType
  content: string
  images: string[]
  contact?: string
}

// ─── Constants ────────────────────────────────────────────────────────────────
const TABS: FeedbackTab[] = [
  { key: 'suggestion', label: '功能建议' },
  { key: 'bug', label: '问题反馈' },
  { key: 'complaint', label: '服务投诉' },
  { key: 'other', label: '其他' },
]

const STATUS_MAP: Record<string, { label: string; color: string; bg: string }> = {
  pending: { label: '处理中', color: C.primary, bg: 'rgba(255,107,53,0.12)' },
  replied: { label: '已回复', color: C.success, bg: 'rgba(76,175,80,0.12)' },
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const s = STATUS_MAP[status] || STATUS_MAP.pending
  return (
    <View
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '6rpx 18rpx',
        borderRadius: '24rpx',
        background: s.bg,
      }}
    >
      <Text style={{ fontSize: '22rpx', color: s.color, fontWeight: '600' }}>{s.label}</Text>
    </View>
  )
}

function ImageUploadSlot({
  uri,
  onAdd,
  onRemove,
}: {
  uri?: string
  onAdd: () => void
  onRemove: () => void
}) {
  if (uri) {
    return (
      <View
        style={{
          width: '200rpx',
          height: '200rpx',
          borderRadius: '16rpx',
          overflow: 'hidden',
          position: 'relative',
        }}
      >
        <Image
          src={uri}
          style={{ width: '200rpx', height: '200rpx', objectFit: 'cover' }}
          mode="aspectFill"
        />
        <View
          onClick={onRemove}
          style={{
            position: 'absolute',
            top: '8rpx',
            right: '8rpx',
            width: '44rpx',
            height: '44rpx',
            borderRadius: '50%',
            background: 'rgba(0,0,0,0.6)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
          }}
        >
          <Text style={{ fontSize: '24rpx', color: C.white }}>✕</Text>
        </View>
      </View>
    )
  }
  return (
    <View
      onClick={onAdd}
      style={{
        width: '200rpx',
        height: '200rpx',
        borderRadius: '16rpx',
        background: C.bgHover,
        border: `2rpx dashed ${C.border}`,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '8rpx',
        cursor: 'pointer',
      }}
    >
      <Text style={{ fontSize: '48rpx', color: C.text3 }}>+</Text>
      <Text style={{ fontSize: '22rpx', color: C.text3 }}>添加截图</Text>
    </View>
  )
}

// ─── History item ─────────────────────────────────────────────────────────────
function HistoryItem({
  record,
  onTap,
}: {
  record: FeedbackRecord
  onTap: () => void
}) {
  const tab = TABS.find((t) => t.key === record.type)
  return (
    <View
      onClick={onTap}
      style={{
        background: C.bgCard,
        borderRadius: '20rpx',
        padding: '32rpx',
        marginBottom: '20rpx',
        border: `1rpx solid ${C.border}`,
        cursor: 'pointer',
      }}
    >
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '16rpx',
        }}
      >
        <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '16rpx' }}>
          <Text style={{ fontSize: '24rpx', color: C.text3 }}>#{record.ticketNo}</Text>
          <Text
            style={{
              fontSize: '24rpx',
              color: C.text3,
              background: C.bgHover,
              padding: '4rpx 12rpx',
              borderRadius: '8rpx',
            }}
          >
            {tab?.label || '其他'}
          </Text>
        </View>
        <StatusBadge status={record.status} />
      </View>
      <Text
        style={{
          fontSize: '28rpx',
          color: C.text1,
          display: '-webkit-box',
          WebkitLineClamp: 2,
          WebkitBoxOrient: 'vertical',
          overflow: 'hidden',
          marginBottom: '16rpx',
        }}
      >
        {record.content}
      </Text>
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <Text style={{ fontSize: '24rpx', color: C.text3 }}>{record.createdAt}</Text>
        {record.status === 'replied' && (
          <Text style={{ fontSize: '24rpx', color: C.primary }}>查看回复 &gt;</Text>
        )}
      </View>
    </View>
  )
}

// ─── Reply Detail Modal ───────────────────────────────────────────────────────
function ReplyDetailModal({
  record,
  onClose,
}: {
  record: FeedbackRecord
  onClose: () => void
}) {
  const tab = TABS.find((t) => t.key === record.type)
  return (
    <View
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 2000,
        background: 'rgba(0,0,0,0.7)',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'flex-end',
      }}
      onClick={onClose}
    >
      <View
        onClick={(e) => e.stopPropagation()}
        style={{
          background: C.bgCard,
          borderRadius: '32rpx 32rpx 0 0',
          padding: '40rpx 40rpx calc(40rpx + env(safe-area-inset-bottom))',
          maxHeight: '80vh',
          overflowY: 'auto',
        }}
      >
        {/* Handle */}
        <View
          style={{
            width: '80rpx',
            height: '8rpx',
            background: C.border,
            borderRadius: '4rpx',
            margin: '0 auto 32rpx',
          }}
        />
        <Text style={{ fontSize: '34rpx', fontWeight: '700', color: C.text1, display: 'block', marginBottom: '8rpx' }}>
          反馈详情
        </Text>
        <Text style={{ fontSize: '24rpx', color: C.text3, display: 'block', marginBottom: '32rpx' }}>
          #{record.ticketNo} · {tab?.label}
        </Text>

        {/* Original content */}
        <View
          style={{
            background: C.bgDeep,
            borderRadius: '16rpx',
            padding: '28rpx',
            marginBottom: '32rpx',
          }}
        >
          <Text style={{ fontSize: '24rpx', color: C.text3, display: 'block', marginBottom: '12rpx' }}>
            我的反馈
          </Text>
          <Text style={{ fontSize: '28rpx', color: C.text1, lineHeight: '1.6' }}>{record.content}</Text>
        </View>

        {/* Reply */}
        {record.reply ? (
          <View
            style={{
              background: 'rgba(255,107,53,0.08)',
              border: `1rpx solid rgba(255,107,53,0.3)`,
              borderRadius: '16rpx',
              padding: '28rpx',
            }}
          >
            <Text style={{ fontSize: '24rpx', color: C.primary, display: 'block', marginBottom: '12rpx', fontWeight: '600' }}>
              官方回复
            </Text>
            <Text style={{ fontSize: '28rpx', color: C.text1, lineHeight: '1.6' }}>{record.reply}</Text>
          </View>
        ) : (
          <View
            style={{
              textAlign: 'center',
              padding: '32rpx',
              color: C.text3,
              fontSize: '28rpx',
            }}
          >
            暂无回复，请耐心等待
          </View>
        )}
      </View>
    </View>
  )
}

// ─── Main Component ───────────────────────────────────────────────────────────
export default function FeedbackPage() {
  const [activeTab, setActiveTab] = useState<FeedbackType>('suggestion')
  const [content, setContent] = useState('')
  const [images, setImages] = useState<string[]>([])
  const [contact, setContact] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [successTicket, setSuccessTicket] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<'form' | 'history'>('form')
  const [history, setHistory] = useState<FeedbackRecord[]>([])
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [selectedRecord, setSelectedRecord] = useState<FeedbackRecord | null>(null)

  const MAX_CHARS = 500

  useEffect(() => {
    if (viewMode === 'history') {
      fetchHistory()
    }
  }, [viewMode])

  async function fetchHistory() {
    setLoadingHistory(true)
    try {
      const res = await txRequest<{ items: FeedbackRecord[] }>('/api/v1/feedback/mine')
      setHistory(res.items || [])
    } catch {
      setHistory([])
    } finally {
      setLoadingHistory(false)
    }
  }

  async function handleChooseImage() {
    if (images.length >= 3) {
      Taro.showToast({ title: '最多上传3张截图', icon: 'none' })
      return
    }
    try {
      const res = await Taro.chooseImage({
        count: 3 - images.length,
        sizeType: ['compressed'],
        sourceType: ['album', 'camera'],
      })
      setImages((prev) => [...prev, ...res.tempFilePaths].slice(0, 3))
    } catch {
      // user cancelled
    }
  }

  function handleRemoveImage(idx: number) {
    setImages((prev) => prev.filter((_, i) => i !== idx))
  }

  async function handleSubmit() {
    if (content.trim().length < 10) {
      Taro.showToast({ title: '请至少输入10个字', icon: 'none' })
      return
    }
    setSubmitting(true)
    try {
      const payload: SubmitPayload = {
        type: activeTab,
        content: content.trim(),
        images,
        contact: contact.trim() || undefined,
      }
      const res = await txRequest<{ ticketNo: string }>('/api/v1/feedback', 'POST', payload as any)
      setSuccessTicket(res.ticketNo)
    } catch {
      Taro.showToast({ title: '提交失败，请重试', icon: 'error' })
    } finally {
      setSubmitting(false)
    }
  }

  function handleReset() {
    setSuccessTicket(null)
    setContent('')
    setImages([])
    setContact('')
    setActiveTab('suggestion')
  }

  // ── Success state ──────────────────────────────────────────────────────────
  if (successTicket) {
    return (
      <View
        style={{
          minHeight: '100vh',
          background: C.bgDeep,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '60rpx',
          gap: '32rpx',
        }}
      >
        <Text style={{ fontSize: '100rpx' }}>✅</Text>
        <Text style={{ fontSize: '40rpx', fontWeight: '700', color: C.text1 }}>提交成功</Text>
        <Text style={{ fontSize: '28rpx', color: C.text2, textAlign: 'center', lineHeight: '1.6' }}>
          感谢您的反馈！我们将尽快处理。
        </Text>
        <View
          style={{
            background: C.bgCard,
            borderRadius: '16rpx',
            padding: '24rpx 48rpx',
            border: `1rpx solid ${C.border}`,
          }}
        >
          <Text style={{ fontSize: '26rpx', color: C.text3 }}>工单编号</Text>
          <Text style={{ fontSize: '36rpx', color: C.primary, fontWeight: '700', display: 'block', marginTop: '8rpx' }}>
            #{successTicket}
          </Text>
        </View>
        <View style={{ display: 'flex', flexDirection: 'row', gap: '24rpx', marginTop: '16rpx' }}>
          <View
            onClick={() => { handleReset(); setViewMode('history') }}
            style={{
              padding: '24rpx 48rpx',
              borderRadius: '48rpx',
              border: `2rpx solid ${C.border}`,
              cursor: 'pointer',
            }}
          >
            <Text style={{ fontSize: '30rpx', color: C.text2 }}>查看记录</Text>
          </View>
          <View
            onClick={handleReset}
            style={{
              padding: '24rpx 48rpx',
              borderRadius: '48rpx',
              background: C.primary,
              cursor: 'pointer',
            }}
          >
            <Text style={{ fontSize: '30rpx', color: C.white }}>继续反馈</Text>
          </View>
        </View>
      </View>
    )
  }

  return (
    <View style={{ minHeight: '100vh', background: C.bgDeep, display: 'flex', flexDirection: 'column' }}>
      {/* ── Top nav ── */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '24rpx 40rpx',
          paddingTop: 'calc(24rpx + env(safe-area-inset-top))',
          background: C.bgCard,
          borderBottom: `1rpx solid ${C.border}`,
        }}
      >
        <Text style={{ fontSize: '36rpx', fontWeight: '700', color: C.text1 }}>意见反馈</Text>
        <View style={{ display: 'flex', flexDirection: 'row', gap: '0' }}>
          {(['form', 'history'] as const).map((mode) => (
            <View
              key={mode}
              onClick={() => setViewMode(mode)}
              style={{
                padding: '12rpx 28rpx',
                borderRadius: '8rpx',
                background: viewMode === mode ? C.primary : 'transparent',
                cursor: 'pointer',
              }}
            >
              <Text style={{ fontSize: '26rpx', color: viewMode === mode ? C.white : C.text3 }}>
                {mode === 'form' ? '提交反馈' : '我的反馈'}
              </Text>
            </View>
          ))}
        </View>
      </View>

      <ScrollView scrollY style={{ flex: 1 }}>
        <View style={{ padding: '32rpx' }}>

          {/* ── Form mode ── */}
          {viewMode === 'form' && (
            <>
              {/* Type tabs */}
              <View
                style={{
                  display: 'flex',
                  flexDirection: 'row',
                  gap: '16rpx',
                  marginBottom: '40rpx',
                  flexWrap: 'wrap',
                }}
              >
                {TABS.map((tab) => (
                  <View
                    key={tab.key}
                    onClick={() => setActiveTab(tab.key)}
                    style={{
                      padding: '16rpx 32rpx',
                      borderRadius: '48rpx',
                      background: activeTab === tab.key ? C.primary : C.bgCard,
                      border: `2rpx solid ${activeTab === tab.key ? C.primary : C.border}`,
                      cursor: 'pointer',
                    }}
                  >
                    <Text
                      style={{
                        fontSize: '28rpx',
                        color: activeTab === tab.key ? C.white : C.text2,
                        fontWeight: activeTab === tab.key ? '600' : '400',
                      }}
                    >
                      {tab.label}
                    </Text>
                  </View>
                ))}
              </View>

              {/* Content textarea */}
              <View
                style={{
                  background: C.bgCard,
                  borderRadius: '20rpx',
                  padding: '32rpx',
                  border: `1rpx solid ${C.border}`,
                  marginBottom: '32rpx',
                }}
              >
                <Text style={{ fontSize: '28rpx', color: C.text2, display: 'block', marginBottom: '20rpx' }}>
                  反馈内容 *
                </Text>
                <Textarea
                  value={content}
                  placeholder="请详细描述您的问题或建议，至少10个字..."
                  placeholderStyle={`color: ${C.text3}; font-size: 28rpx;`}
                  maxlength={MAX_CHARS}
                  autoHeight
                  style={{
                    width: '100%',
                    minHeight: '240rpx',
                    fontSize: '30rpx',
                    color: C.text1,
                    lineHeight: '1.6',
                  }}
                  onInput={(e) => setContent(e.detail.value)}
                />
                <View style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '16rpx' }}>
                  <Text
                    style={{
                      fontSize: '24rpx',
                      color: content.length >= MAX_CHARS ? C.red : C.text3,
                    }}
                  >
                    {content.length}/{MAX_CHARS}
                  </Text>
                </View>
              </View>

              {/* Image upload */}
              <View
                style={{
                  background: C.bgCard,
                  borderRadius: '20rpx',
                  padding: '32rpx',
                  border: `1rpx solid ${C.border}`,
                  marginBottom: '32rpx',
                }}
              >
                <Text style={{ fontSize: '28rpx', color: C.text2, display: 'block', marginBottom: '20rpx' }}>
                  上传截图（最多3张）
                </Text>
                <View style={{ display: 'flex', flexDirection: 'row', gap: '20rpx' }}>
                  {[0, 1, 2].map((idx) => (
                    <ImageUploadSlot
                      key={idx}
                      uri={images[idx]}
                      onAdd={handleChooseImage}
                      onRemove={() => handleRemoveImage(idx)}
                    />
                  ))}
                </View>
              </View>

              {/* Contact info */}
              <View
                style={{
                  background: C.bgCard,
                  borderRadius: '20rpx',
                  padding: '32rpx',
                  border: `1rpx solid ${C.border}`,
                  marginBottom: '48rpx',
                }}
              >
                <Text style={{ fontSize: '28rpx', color: C.text2, display: 'block', marginBottom: '20rpx' }}>
                  联系方式（选填）
                </Text>
                <Input
                  value={contact}
                  placeholder="手机号或邮箱，方便我们回复您"
                  placeholderStyle={`color: ${C.text3}; font-size: 28rpx;`}
                  style={{
                    fontSize: '30rpx',
                    color: C.text1,
                    padding: '20rpx 0',
                    borderBottom: `1rpx solid ${C.border}`,
                  }}
                  onInput={(e) => setContact(e.detail.value)}
                />
              </View>

              {/* Submit button */}
              <View
                onClick={submitting ? undefined : handleSubmit}
                style={{
                  height: '96rpx',
                  borderRadius: '48rpx',
                  background: submitting ? C.text3 : C.primary,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  cursor: submitting ? 'not-allowed' : 'pointer',
                  marginBottom: 'calc(48rpx + env(safe-area-inset-bottom))',
                }}
              >
                <Text style={{ fontSize: '34rpx', color: C.white, fontWeight: '700' }}>
                  {submitting ? '提交中...' : '提交反馈'}
                </Text>
              </View>
            </>
          )}

          {/* ── History mode ── */}
          {viewMode === 'history' && (
            <>
              {loadingHistory && (
                <View style={{ textAlign: 'center', padding: '60rpx 0' }}>
                  <Text style={{ color: C.text3 }}>加载中...</Text>
                </View>
              )}
              {!loadingHistory && history.length === 0 && (
                <View
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    padding: '80rpx 0',
                    gap: '24rpx',
                  }}
                >
                  <Text style={{ fontSize: '80rpx' }}>📋</Text>
                  <Text style={{ fontSize: '30rpx', color: C.text2 }}>暂无反馈记录</Text>
                  <View
                    onClick={() => setViewMode('form')}
                    style={{
                      marginTop: '16rpx',
                      padding: '20rpx 48rpx',
                      background: C.primary,
                      borderRadius: '48rpx',
                      cursor: 'pointer',
                    }}
                  >
                    <Text style={{ fontSize: '30rpx', color: C.white }}>去提交反馈</Text>
                  </View>
                </View>
              )}
              {!loadingHistory &&
                history.map((record) => (
                  <HistoryItem
                    key={record.id}
                    record={record}
                    onTap={() => setSelectedRecord(record)}
                  />
                ))}
            </>
          )}
        </View>
      </ScrollView>

      {/* ── Reply detail modal ── */}
      {selectedRecord && (
        <ReplyDetailModal record={selectedRecord} onClose={() => setSelectedRecord(null)} />
      )}
    </View>
  )
}
