/**
 * queue/index.tsx — 排号等位
 *
 * State machine: idle → taking → waiting → called → seated/expired
 *
 * Tabs:
 *   排号  — active ticket or idle take-a-number flow
 *   历史  — past queue records
 */

import React, {
  useState,
  useEffect,
  useRef,
  useCallback,
} from 'react'
import { View, Text, ScrollView } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { QueueTicket } from '../../components/QueueTicket'
import { useStoreInfo } from '../../store/useStoreInfo'
import { txRequest } from '../../utils/request'

// ─── Brand tokens ─────────────────────────────────────────────────────────────

const C = {
  primary:     '#FF6B35',
  primaryDark: '#E55A1F',
  bgDeep:      '#0B1A20',
  bgCard:      '#132029',
  bgHover:     '#1A2E38',
  border:      '#1E3340',
  success:     '#34C759',
  warning:     '#FF9F0A',
  text1:       '#E8F4F8',
  text2:       '#9EB5C0',
  text3:       '#5A7A88',
  white:       '#FFFFFF',
} as const

// ─── Types ────────────────────────────────────────────────────────────────────

type QueueState = 'idle' | 'taking' | 'waiting' | 'called' | 'seated' | 'expired'
type TabKey     = 'queue' | 'history'
type PartySize  = '1-2' | '3-4' | '5-6' | '7+'

interface WaitInfo {
  totalWaiting: number
  estimatedMinutes: number
  recentCalled: string[]
}

interface ActiveTicket {
  ticketId: string
  ticketNo: string
  queueAhead: number
  estimatedWait: number
  status: 'waiting' | 'called' | 'seated' | 'expired'
  partySize: string
  createdAt: string
}

interface HistoryRecord {
  ticketId: string
  ticketNo: string
  date: string
  partySize: string
  waitMinutes: number
  status: 'seated' | 'expired' | 'cancelled'
}

// ─── Fun facts (static content while waiting) ─────────────────────────────────

const FUN_FACTS = [
  '你知道吗？热锅起源于重庆码头工人的饮食文化，已有逾百年历史。',
  '辣椒中的辣椒素会让大脑释放内啡肽，带来愉悦感——所以越辣越开心！',
  '麻婆豆腐的"麻"来自花椒，"辣"来自辣豆瓣，是川菜中"麻辣"的代表。',
  '涮羊肉最早见于忽必烈大军行军途中，是边煮边吃的发明。',
  '正宗的四川火锅汤底需要熬制3小时以上，才能提炼出骨汤的醇厚。',
  '全世界每年消耗的辣椒超过3400万吨，中国是最大消费国。',
  '牛油火锅与清汤鸳鸯锅的组合，最早出现于1980年代的重庆街边摊。',
]

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatDate(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  const mm  = String(d.getMonth() + 1).padStart(2, '0')
  const dd  = String(d.getDate()).padStart(2, '0')
  const hh  = String(d.getHours()).padStart(2, '0')
  const min = String(d.getMinutes()).padStart(2, '0')
  return `${mm}-${dd} ${hh}:${min}`
}

function secondsToMMSS(secs: number): string {
  const m = Math.floor(secs / 60)
  const s = secs % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

// ─── Sub-components ───────────────────────────────────────────────────────────

// Chip selector for party size
interface PartySizeChipsProps {
  value: PartySize
  onChange: (v: PartySize) => void
}

const PARTY_SIZES: { key: PartySize; label: string }[] = [
  { key: '1-2', label: '1-2人' },
  { key: '3-4', label: '3-4人' },
  { key: '5-6', label: '5-6人' },
  { key: '7+',  label: '7人以上' },
]

function PartySizeChips({ value, onChange }: PartySizeChipsProps) {
  return (
    <View
      style={{
        display: 'flex',
        flexDirection: 'row',
        gap: '16rpx',
        flexWrap: 'wrap',
      }}
    >
      {PARTY_SIZES.map((ps) => {
        const active = value === ps.key
        return (
          <View
            key={ps.key}
            onClick={() => onChange(ps.key)}
            style={{
              flex: '1 1 calc(50% - 8rpx)',
              minWidth: '160rpx',
              height: '88rpx',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: '44rpx',
              background: active ? C.primary : C.bgCard,
              border: `2rpx solid ${active ? C.primary : C.border}`,
              transition: 'all 0.2s',
            }}
          >
            <Text
              style={{
                color: active ? C.white : C.text2,
                fontSize: '30rpx',
                fontWeight: active ? '700' : '400',
              }}
            >
              {ps.label}
            </Text>
          </View>
        )
      })}
    </View>
  )
}

// Scrolling ticker for recently called numbers
interface CalledTickerProps {
  numbers: string[]
}

function CalledTicker({ numbers }: CalledTickerProps) {
  if (!numbers.length) return null
  return (
    <View
      style={{
        background: C.bgCard,
        borderRadius: '20rpx',
        padding: '20rpx 28rpx',
        border: `1rpx solid ${C.border}`,
        overflow: 'hidden',
      }}
    >
      <Text style={{ color: C.text3, fontSize: '24rpx', marginBottom: '12rpx', display: 'block' }}>
        最近叫号
      </Text>
      <ScrollView
        scrollX
        style={{ whiteSpace: 'nowrap' }}
      >
        <View style={{ display: 'flex', flexDirection: 'row', gap: '16rpx' }}>
          {numbers.map((n) => (
            <View
              key={n}
              style={{
                background: 'rgba(255,107,53,0.12)',
                borderRadius: '12rpx',
                padding: '8rpx 24rpx',
                border: `1rpx solid rgba(255,107,53,0.3)`,
              }}
            >
              <Text style={{ color: C.primary, fontSize: '32rpx', fontWeight: '700' }}>{n}</Text>
            </View>
          ))}
        </View>
      </ScrollView>
    </View>
  )
}

// Countdown ring (conic-gradient via inline style)
interface CountdownRingProps {
  totalSecs: number
  remainSecs: number
}

function CountdownRing({ totalSecs, remainSecs }: CountdownRingProps) {
  const pct = totalSecs > 0 ? Math.max(0, remainSecs / totalSecs) : 0
  const deg = Math.round(pct * 360)
  return (
    <View
      style={{
        width: '200rpx',
        height: '200rpx',
        borderRadius: '50%',
        background: `conic-gradient(${C.success} ${deg}deg, rgba(52,199,89,0.15) ${deg}deg)`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        position: 'relative',
      }}
    >
      {/* Inner circle */}
      <View
        style={{
          width: '160rpx',
          height: '160rpx',
          borderRadius: '50%',
          background: C.bgDeep,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexDirection: 'column',
        }}
      >
        <Text style={{ color: C.success, fontSize: '40rpx', fontWeight: '900' }}>
          {secondsToMMSS(remainSecs)}
        </Text>
        <Text style={{ color: C.text3, fontSize: '20rpx' }}>剩余</Text>
      </View>
    </View>
  )
}

// Fun facts carousel
function FunFactsCarousel() {
  const [idx, setIdx] = useState(0)
  const [fade, setFade] = useState(true)

  useEffect(() => {
    const timer = setInterval(() => {
      setFade(false)
      setTimeout(() => {
        setIdx((i) => (i + 1) % FUN_FACTS.length)
        setFade(true)
      }, 400)
    }, 5000)
    return () => clearInterval(timer)
  }, [])

  return (
    <View
      style={{
        background: C.bgCard,
        borderRadius: '24rpx',
        padding: '28rpx',
        border: `1rpx solid ${C.border}`,
      }}
    >
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          gap: '12rpx',
          marginBottom: '16rpx',
        }}
      >
        <Text style={{ fontSize: '32rpx' }}>💡</Text>
        <Text style={{ color: C.primary, fontSize: '26rpx', fontWeight: '600' }}>
          等位小知识
        </Text>
      </View>
      <Text
        style={{
          color: C.text2,
          fontSize: '28rpx',
          lineHeight: '1.7',
          opacity: fade ? 1 : 0,
          transition: 'opacity 0.4s',
        }}
      >
        {FUN_FACTS[idx]}
      </Text>
      {/* Dot indicators */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          gap: '8rpx',
          marginTop: '20rpx',
          justifyContent: 'center',
        }}
      >
        {FUN_FACTS.map((_, i) => (
          <View
            key={i}
            onClick={() => setIdx(i)}
            style={{
              width: i === idx ? '24rpx' : '12rpx',
              height: '12rpx',
              borderRadius: '6rpx',
              background: i === idx ? C.primary : C.border,
              transition: 'all 0.3s',
            }}
          />
        ))}
      </View>
    </View>
  )
}

// History record row
function HistoryRow({ record }: { record: HistoryRecord }) {
  const statusMap: Record<HistoryRecord['status'], { label: string; color: string }> = {
    seated:    { label: '已入座', color: C.success },
    expired:   { label: '已过号', color: C.text3 },
    cancelled: { label: '已取消', color: '#FF3B30' },
  }
  const s = statusMap[record.status]

  return (
    <View
      style={{
        background: C.bgCard,
        borderRadius: '20rpx',
        padding: '28rpx',
        border: `1rpx solid ${C.border}`,
        display: 'flex',
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}
    >
      <View>
        <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'baseline', gap: '12rpx' }}>
          <Text style={{ color: C.white, fontSize: '44rpx', fontWeight: '900' }}>
            {record.ticketNo}
          </Text>
          <Text style={{ color: C.text3, fontSize: '24rpx' }}>{record.partySize}人</Text>
        </View>
        <Text style={{ color: C.text3, fontSize: '24rpx', marginTop: '8rpx', display: 'block' }}>
          {formatDate(record.date)}
        </Text>
        {record.waitMinutes > 0 && (
          <Text style={{ color: C.text3, fontSize: '24rpx', display: 'block' }}>
            实际等待 {record.waitMinutes} 分钟
          </Text>
        )}
      </View>
      <View
        style={{
          background: `${s.color}22`,
          borderRadius: '12rpx',
          padding: '8rpx 20rpx',
          border: `1rpx solid ${s.color}55`,
        }}
      >
        <Text style={{ color: s.color, fontSize: '26rpx', fontWeight: '600' }}>{s.label}</Text>
      </View>
    </View>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function QueuePage() {
  const { storeId } = useStoreInfo()

  // Tabs
  const [tab, setTab] = useState<TabKey>('queue')

  // Queue FSM
  const [queueState, setQueueState] = useState<QueueState>('idle')
  const [partySize, setPartySize] = useState<PartySize>('1-2')
  const [waitInfo, setWaitInfo]     = useState<WaitInfo>({ totalWaiting: 0, estimatedMinutes: 0, recentCalled: [] })
  const [ticket, setTicket]         = useState<ActiveTicket | null>(null)
  const [taking, setTaking]         = useState(false)

  // Called-state countdown (3 min = 180 s)
  const ARRIVAL_SECS = 180
  const [arrivalRemain, setArrivalRemain] = useState(ARRIVAL_SECS)
  const arrivalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Polling ref
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // History
  const [history, setHistory]     = useState<HistoryRecord[]>([])
  const [histLoading, setHistLoading] = useState(false)

  // ── Fetch idle wait info ──────────────────────────────────────────────────

  const fetchWaitInfo = useCallback(async () => {
    try {
      const data = await txRequest<WaitInfo>(`/api/v1/queue/wait-info?store_id=${storeId}`)
      setWaitInfo(data)
    } catch {
      // non-critical — show stale data
    }
  }, [storeId])

  // ── Fetch ticket status (polling) ─────────────────────────────────────────

  const fetchTicketStatus = useCallback(async (ticketId: string) => {
    try {
      const data = await txRequest<ActiveTicket>(`/api/v1/queue/status/${ticketId}`)
      setTicket(data)
      if (data.status === 'called') {
        setQueueState('called')
        startArrivalCountdown()
      } else if (data.status === 'seated') {
        setQueueState('seated')
        stopPolling()
      } else if (data.status === 'expired') {
        setQueueState('expired')
        stopPolling()
      }
    } catch {
      // keep last known state
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  const startPolling = useCallback((ticketId: string) => {
    stopPolling()
    pollRef.current = setInterval(() => {
      fetchTicketStatus(ticketId)
    }, 5000)
  }, [stopPolling, fetchTicketStatus])

  // ── Arrival countdown (called state) ──────────────────────────────────────

  const startArrivalCountdown = useCallback(() => {
    setArrivalRemain(ARRIVAL_SECS)
    if (arrivalRef.current) clearInterval(arrivalRef.current)
    arrivalRef.current = setInterval(() => {
      setArrivalRemain((s) => {
        if (s <= 1) {
          if (arrivalRef.current) clearInterval(arrivalRef.current)
          setQueueState('expired')
          return 0
        }
        return s - 1
      })
    }, 1000)
  }, [])

  // ── Take a number ──────────────────────────────────────────────────────────

  const handleTakeNumber = useCallback(async () => {
    if (taking) return
    setTaking(true)
    setQueueState('taking')
    try {
      const partySizeMap: Record<PartySize, number> = {
        '1-2': 2, '3-4': 4, '5-6': 6, '7+': 8,
      }
      const data = await txRequest<ActiveTicket>('/api/v1/queue/take', 'POST', {
        store_id: storeId,
        party_size: partySizeMap[partySize],
      })
      setTicket(data)
      setQueueState('waiting')
      startPolling(data.ticketId)
      Taro.showToast({ title: `取号成功 ${data.ticketNo}`, icon: 'success', duration: 2000 })
    } catch (err: any) {
      setQueueState('idle')
      Taro.showToast({ title: err?.message ?? '取号失败，请重试', icon: 'none', duration: 2500 })
    } finally {
      setTaking(false)
    }
  }, [taking, storeId, partySize, startPolling])

  // ── Confirm arrival ───────────────────────────────────────────────────────

  const handleConfirmArrival = useCallback(async () => {
    if (!ticket) return
    try {
      await txRequest(`/api/v1/queue/${ticket.ticketId}/confirm-arrival`, 'POST')
      if (arrivalRef.current) clearInterval(arrivalRef.current)
      stopPolling()
      setQueueState('seated')
      Taro.showToast({ title: '已确认到达，请入座！', icon: 'success', duration: 2000 })
    } catch (err: any) {
      Taro.showToast({ title: err?.message ?? '确认失败', icon: 'none', duration: 2000 })
    }
  }, [ticket, stopPolling])

  // ── Give up ───────────────────────────────────────────────────────────────

  const handleGiveUp = useCallback(async () => {
    if (!ticket) return
    try {
      await txRequest(`/api/v1/queue/${ticket.ticketId}`, 'DELETE')
      stopPolling()
      if (arrivalRef.current) clearInterval(arrivalRef.current)
      setTicket(null)
      setQueueState('idle')
      await fetchWaitInfo()
    } catch (err: any) {
      Taro.showToast({ title: err?.message ?? '操作失败', icon: 'none', duration: 2000 })
    }
  }, [ticket, stopPolling, fetchWaitInfo])

  // ── Subscribe notifications ───────────────────────────────────────────────

  const handleSubscribe = useCallback(() => {
    Taro.requestSubscribeMessage({
      tmplIds: ['QUEUE_CALLED_TEMPLATE_ID'],
      success: (res: any) => {
        const accepted = res['QUEUE_CALLED_TEMPLATE_ID'] === 'accept'
        Taro.showToast({
          title: accepted ? '叫号通知已开启' : '通知订阅已取消',
          icon: accepted ? 'success' : 'none',
          duration: 2000,
        })
      },
      fail: () => {
        Taro.showToast({ title: '订阅失败，请重试', icon: 'none', duration: 2000 })
      },
    })
  }, [])

  // ── Fetch history ─────────────────────────────────────────────────────────

  const fetchHistory = useCallback(async () => {
    setHistLoading(true)
    try {
      const data = await txRequest<HistoryRecord[]>(`/api/v1/queue/history?store_id=${storeId}`)
      setHistory(data)
    } catch {
      // ignore
    } finally {
      setHistLoading(false)
    }
  }, [storeId])

  // ── Effects ───────────────────────────────────────────────────────────────

  useEffect(() => {
    fetchWaitInfo()
    // Check for existing active ticket in storage
    const savedTicketId = Taro.getStorageSync<string>('tx_queue_ticket_id')
    if (savedTicketId) {
      fetchTicketStatus(savedTicketId).then(() => {
        // state will be set based on the fetched status
      })
    }
    const infoTimer = setInterval(fetchWaitInfo, 30000)
    return () => clearInterval(infoTimer)
  }, [fetchWaitInfo, fetchTicketStatus])

  useEffect(() => {
    if (ticket?.ticketId) {
      Taro.setStorageSync('tx_queue_ticket_id', ticket.ticketId)
    }
  }, [ticket?.ticketId])

  useEffect(() => {
    if (tab === 'history') fetchHistory()
  }, [tab, fetchHistory])

  useEffect(() => {
    return () => {
      stopPolling()
      if (arrivalRef.current) clearInterval(arrivalRef.current)
    }
  }, [stopPolling])

  // ─── Render ──────────────────────────────────────────────────────────────

  return (
    <View
      style={{
        minHeight: '100vh',
        background: C.bgDeep,
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Header */}
      <View
        style={{
          padding: '48rpx 32rpx 24rpx',
          background: C.bgDeep,
          borderBottom: `1rpx solid ${C.border}`,
        }}
      >
        <Text
          style={{
            color: C.white,
            fontSize: '40rpx',
            fontWeight: '800',
          }}
        >
          排号等位
        </Text>
      </View>

      {/* Tabs */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          background: C.bgDeep,
          borderBottom: `1rpx solid ${C.border}`,
          paddingLeft: '32rpx',
        }}
      >
        {([ { key: 'queue', label: '排号' }, { key: 'history', label: '历史记录' } ] as { key: TabKey; label: string }[]).map((t) => {
          const active = tab === t.key
          return (
            <View
              key={t.key}
              onClick={() => setTab(t.key)}
              style={{
                padding: '24rpx 32rpx',
                borderBottom: `4rpx solid ${active ? C.primary : 'transparent'}`,
                marginRight: '8rpx',
              }}
            >
              <Text
                style={{
                  color: active ? C.primary : C.text2,
                  fontSize: '30rpx',
                  fontWeight: active ? '700' : '400',
                }}
              >
                {t.label}
              </Text>
            </View>
          )
        })}
      </View>

      {/* Content */}
      <ScrollView
        scrollY
        style={{ flex: 1 }}
        enableFlex
      >
        <View style={{ padding: '32rpx', paddingBottom: '80rpx' }}>

          {/* ═══ QUEUE TAB ═══════════════════════════════════════════════════ */}
          {tab === 'queue' && (
            <View style={{ display: 'flex', flexDirection: 'column', gap: '24rpx' }}>

              {/* ── IDLE STATE ── */}
              {(queueState === 'idle') && (
                <>
                  {/* Wait info banner */}
                  <View
                    style={{
                      background: C.bgCard,
                      borderRadius: '24rpx',
                      padding: '32rpx',
                      border: `1rpx solid ${C.border}`,
                    }}
                  >
                    <View
                      style={{
                        display: 'flex',
                        flexDirection: 'row',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                      }}
                    >
                      <View>
                        <Text style={{ color: C.text2, fontSize: '26rpx', display: 'block', marginBottom: '8rpx' }}>
                          当前等位
                        </Text>
                        <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'baseline', gap: '8rpx' }}>
                          <Text style={{ color: C.white, fontSize: '64rpx', fontWeight: '900' }}>
                            {waitInfo.totalWaiting}
                          </Text>
                          <Text style={{ color: C.text2, fontSize: '28rpx' }}>桌</Text>
                        </View>
                      </View>
                      <View
                        style={{
                          background: 'rgba(255,107,53,0.12)',
                          borderRadius: '20rpx',
                          padding: '20rpx 28rpx',
                          border: `1rpx solid rgba(255,107,53,0.3)`,
                          display: 'flex',
                          flexDirection: 'column',
                          alignItems: 'center',
                        }}
                      >
                        <Text style={{ color: C.text3, fontSize: '22rpx' }}>预计等待</Text>
                        <Text style={{ color: C.primary, fontSize: '44rpx', fontWeight: '800' }}>
                          {waitInfo.estimatedMinutes}
                        </Text>
                        <Text style={{ color: C.text3, fontSize: '22rpx' }}>分钟</Text>
                      </View>
                    </View>
                  </View>

                  {/* Party size selector */}
                  <View
                    style={{
                      background: C.bgCard,
                      borderRadius: '24rpx',
                      padding: '32rpx',
                      border: `1rpx solid ${C.border}`,
                    }}
                  >
                    <Text
                      style={{
                        color: C.text2,
                        fontSize: '28rpx',
                        fontWeight: '600',
                        display: 'block',
                        marginBottom: '24rpx',
                      }}
                    >
                      用餐人数
                    </Text>
                    <PartySizeChips value={partySize} onChange={setPartySize} />
                  </View>

                  {/* Take number button */}
                  <View
                    onClick={handleTakeNumber}
                    style={{
                      height: '112rpx',
                      background: C.primary,
                      borderRadius: '56rpx',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      boxShadow: '0 8rpx 32rpx rgba(255,107,53,0.4)',
                    }}
                  >
                    <Text
                      style={{
                        color: C.white,
                        fontSize: '36rpx',
                        fontWeight: '800',
                        letterSpacing: '4rpx',
                      }}
                    >
                      立即取号
                    </Text>
                  </View>

                  {/* Recent called */}
                  {waitInfo.recentCalled.length > 0 && (
                    <CalledTicker numbers={waitInfo.recentCalled} />
                  )}
                </>
              )}

              {/* ── TAKING STATE (spinner) ── */}
              {queueState === 'taking' && (
                <View
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    paddingTop: '120rpx',
                    gap: '24rpx',
                  }}
                >
                  <Text style={{ fontSize: '72rpx' }}>🎫</Text>
                  <Text style={{ color: C.text2, fontSize: '32rpx' }}>正在取号，请稍候…</Text>
                </View>
              )}

              {/* ── WAITING STATE ── */}
              {queueState === 'waiting' && ticket && (
                <>
                  <QueueTicket
                    ticketNo={ticket.ticketNo}
                    queueAhead={ticket.queueAhead}
                    estimatedWait={ticket.estimatedWait}
                    status='waiting'
                    onGiveUp={handleGiveUp}
                  />

                  {/* Action row */}
                  <View style={{ display: 'flex', flexDirection: 'row', gap: '16rpx' }}>
                    {/* Refresh */}
                    <View
                      onClick={() => fetchTicketStatus(ticket.ticketId)}
                      style={{
                        flex: 1,
                        height: '88rpx',
                        background: C.bgCard,
                        borderRadius: '44rpx',
                        border: `2rpx solid ${C.border}`,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: '8rpx',
                      }}
                    >
                      <Text style={{ fontSize: '28rpx' }}>🔄</Text>
                      <Text style={{ color: C.text2, fontSize: '28rpx' }}>刷新</Text>
                    </View>
                    {/* Subscribe */}
                    <View
                      onClick={handleSubscribe}
                      style={{
                        flex: 2,
                        height: '88rpx',
                        background: 'rgba(255,107,53,0.12)',
                        borderRadius: '44rpx',
                        border: `2rpx solid rgba(255,107,53,0.4)`,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: '8rpx',
                      }}
                    >
                      <Text style={{ fontSize: '28rpx' }}>🔔</Text>
                      <Text style={{ color: C.primary, fontSize: '28rpx', fontWeight: '600' }}>
                        订阅叫号通知
                      </Text>
                    </View>
                  </View>

                  {/* Fun facts */}
                  <FunFactsCarousel />
                </>
              )}

              {/* ── CALLED STATE ── */}
              {queueState === 'called' && ticket && (
                <>
                  {/* Full-screen green alert card */}
                  <View
                    style={{
                      background: 'rgba(52,199,89,0.08)',
                      borderRadius: '32rpx',
                      border: `3rpx solid rgba(52,199,89,0.5)`,
                      padding: '56rpx 40rpx',
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      gap: '32rpx',
                      position: 'relative',
                      overflow: 'hidden',
                    }}
                  >
                    {/* Top glow bar */}
                    <View
                      style={{
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        right: 0,
                        height: '8rpx',
                        background: `linear-gradient(90deg, transparent, ${C.success}, transparent)`,
                      }}
                    />

                    <Text
                      style={{
                        color: C.success,
                        fontSize: '48rpx',
                        fontWeight: '900',
                        letterSpacing: '4rpx',
                      }}
                    >
                      您的号码到了！
                    </Text>

                    {/* Flashing ticket number */}
                    <Text
                      style={{
                        color: C.success,
                        fontSize: '144rpx',
                        fontWeight: '900',
                        lineHeight: '1',
                        letterSpacing: '-4rpx',
                      }}
                    >
                      {ticket.ticketNo}
                    </Text>

                    {/* Countdown ring */}
                    <CountdownRing totalSecs={ARRIVAL_SECS} remainSecs={arrivalRemain} />

                    <Text style={{ color: 'rgba(52,199,89,0.7)', fontSize: '26rpx', textAlign: 'center' }}>
                      请在 3 分钟内到达，否则号码将失效
                    </Text>

                    {/* Confirm arrival button */}
                    <View
                      onClick={handleConfirmArrival}
                      style={{
                        width: '100%',
                        height: '112rpx',
                        background: C.success,
                        borderRadius: '56rpx',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        boxShadow: '0 8rpx 32rpx rgba(52,199,89,0.4)',
                      }}
                    >
                      <Text
                        style={{
                          color: C.white,
                          fontSize: '36rpx',
                          fontWeight: '800',
                          letterSpacing: '4rpx',
                        }}
                      >
                        我来了
                      </Text>
                    </View>
                  </View>
                </>
              )}

              {/* ── SEATED STATE ── */}
              {queueState === 'seated' && (
                <View
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    gap: '24rpx',
                    paddingTop: '80rpx',
                  }}
                >
                  <Text style={{ fontSize: '96rpx' }}>🍽️</Text>
                  <Text style={{ color: C.white, fontSize: '44rpx', fontWeight: '800' }}>
                    已入座，用餐愉快！
                  </Text>
                  <View
                    onClick={() => {
                      Taro.removeStorageSync('tx_queue_ticket_id')
                      setTicket(null)
                      setQueueState('idle')
                      fetchWaitInfo()
                    }}
                    style={{
                      marginTop: '32rpx',
                      height: '88rpx',
                      padding: '0 64rpx',
                      background: C.bgCard,
                      borderRadius: '44rpx',
                      border: `2rpx solid ${C.border}`,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                  >
                    <Text style={{ color: C.text2, fontSize: '28rpx' }}>返回首页</Text>
                  </View>
                </View>
              )}

              {/* ── EXPIRED STATE ── */}
              {queueState === 'expired' && (
                <View
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    gap: '24rpx',
                    paddingTop: '80rpx',
                  }}
                >
                  <Text style={{ fontSize: '80rpx' }}>⏰</Text>
                  <Text style={{ color: C.text2, fontSize: '36rpx', fontWeight: '700' }}>
                    排号已失效
                  </Text>
                  <Text
                    style={{
                      color: C.text3,
                      fontSize: '28rpx',
                      textAlign: 'center',
                      lineHeight: '1.7',
                    }}
                  >
                    很抱歉，您的号码已过期。{'\n'}如需就餐请重新取号。
                  </Text>
                  <View
                    onClick={() => {
                      Taro.removeStorageSync('tx_queue_ticket_id')
                      setTicket(null)
                      setQueueState('idle')
                      fetchWaitInfo()
                    }}
                    style={{
                      marginTop: '24rpx',
                      height: '96rpx',
                      padding: '0 64rpx',
                      background: C.primary,
                      borderRadius: '48rpx',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      boxShadow: '0 8rpx 32rpx rgba(255,107,53,0.4)',
                    }}
                  >
                    <Text style={{ color: C.white, fontSize: '32rpx', fontWeight: '700' }}>
                      重新取号
                    </Text>
                  </View>
                </View>
              )}
            </View>
          )}

          {/* ═══ HISTORY TAB ═════════════════════════════════════════════════ */}
          {tab === 'history' && (
            <View style={{ display: 'flex', flexDirection: 'column', gap: '16rpx' }}>
              {histLoading && (
                <View style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', paddingTop: '80rpx' }}>
                  <Text style={{ color: C.text3, fontSize: '28rpx' }}>加载中…</Text>
                </View>
              )}
              {!histLoading && history.length === 0 && (
                <View
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    gap: '20rpx',
                    paddingTop: '120rpx',
                  }}
                >
                  <Text style={{ fontSize: '80rpx' }}>📋</Text>
                  <Text style={{ color: C.text3, fontSize: '30rpx' }}>暂无排号记录</Text>
                </View>
              )}
              {!histLoading && history.map((r) => (
                <HistoryRow key={r.ticketId} record={r} />
              ))}
            </View>
          )}

        </View>
      </ScrollView>
    </View>
  )
}
