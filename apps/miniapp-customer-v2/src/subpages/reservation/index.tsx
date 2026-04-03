/**
 * reservation/index.tsx — 预约订座
 *
 * Two tabs:
 *   新建预约  — 3-step wizard: 选时间 → 选人数&偏好 → 联系方式 → 确认
 *   我的预约  — list of upcoming + past reservations with modify/cancel
 */

import React, {
  useState,
  useEffect,
  useCallback,
} from 'react'
import { View, Text, ScrollView, Input } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useStoreInfo } from '../../store/useStoreInfo'
import { fenToYuanDisplay } from '../../utils/format'
import { txRequest } from '../../utils/request'

// ─── Brand tokens ─────────────────────────────────────────────────────────────

const C = {
  primary:     '#FF6B2C',
  primaryDark: '#E55A1F',
  bgDeep:      '#0B1A20',
  bgCard:      '#132029',
  bgHover:     '#1A2E38',
  border:      '#1E3340',
  success:     '#34C759',
  warning:     '#FF9F0A',
  danger:      '#FF3B30',
  text1:       '#E8F4F8',
  text2:       '#9EB5C0',
  text3:       '#5A7A88',
  white:       '#FFFFFF',
} as const

// ─── Types ────────────────────────────────────────────────────────────────────

type TabKey = 'new' | 'mine'
type WizardStep = 1 | 2 | 3 | 'success'

type SlotAvail = 'available' | 'nearly-full' | 'full'
type DayAvail  = 'available' | 'partial' | 'full'

type TablePref   = '靠窗' | '包间' | '户外' | '大厅' | '无所谓'
type Occasion    = '无' | '生日' | '纪念日' | '商务'
type Decoration  = '气球' | '鲜花' | '蜡烛' | '横幅'

type ReservationStatus = '待确认' | '已确认' | '已到店' | '已取消' | '已过期'

interface DayInfo {
  date: string       // 'YYYY-MM-DD'
  avail: DayAvail
}

interface TimeSlot {
  time: string       // 'HH:mm'
  avail: SlotAvail
}

interface AvailabilityResponse {
  days: DayInfo[]
  slots: TimeSlot[]
}

interface ReservationRecord {
  reservationId: string
  date: string       // 'YYYY-MM-DD'
  time: string       // 'HH:mm'
  guestCount: number
  tablePref: TablePref
  occasion: Occasion
  decorations: Decoration[]
  contactName: string
  contactPhone: string
  specialRequests: string
  status: ReservationStatus
  depositFen: number
  createdAt: string
}

interface NewReservationPayload {
  store_id: string
  date: string
  time: string
  guest_count: number
  table_pref: TablePref
  occasion: Occasion
  decorations: Decoration[]
  contact_name: string
  contact_phone: string
  special_requests: string
}

// ─── Constants ────────────────────────────────────────────────────────────────

const TIME_SLOTS: string[] = [
  '11:00', '11:30', '12:00', '12:30', '13:00',
  '17:30', '18:00', '18:30', '19:00', '19:30', '20:00',
]

const TABLE_PREFS: TablePref[] = ['靠窗', '包间', '户外', '大厅', '无所谓']
const OCCASIONS:  Occasion[]   = ['无', '生日', '纪念日', '商务']
const DECORATIONS: Decoration[] = ['气球', '鲜花', '蜡烛', '横幅']

const OCCASION_DECORATION_MAP: Record<Occasion, Decoration[]> = {
  '无':  [],
  '生日': ['气球', '鲜花', '蜡烛', '横幅'],
  '纪念日': ['鲜花', '蜡烛', '横幅'],
  '商务': ['鲜花', '横幅'],
}

const STATUS_META: Record<ReservationStatus, { color: string; bgColor: string }> = {
  '待确认': { color: C.warning,  bgColor: 'rgba(255,159,10,0.15)' },
  '已确认': { color: C.success,  bgColor: 'rgba(52,199,89,0.15)'  },
  '已到店': { color: C.text2,    bgColor: 'rgba(158,181,192,0.1)' },
  '已取消': { color: C.danger,   bgColor: 'rgba(255,59,48,0.1)'   },
  '已过期': { color: C.text3,    bgColor: 'rgba(90,122,136,0.1)'  },
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function todayStr(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function addDays(dateStr: string, n: number): string {
  const d = new Date(dateStr)
  d.setDate(d.getDate() + n)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function formatDisplayDate(dateStr: string): string {
  const d = new Date(dateStr)
  const month = d.getMonth() + 1
  const day   = d.getDate()
  const dow   = ['日', '一', '二', '三', '四', '五', '六'][d.getDay()]
  return `${month}月${day}日 (周${dow})`
}

function shortDayLabel(dateStr: string): { day: string; dow: string } {
  const d   = new Date(dateStr)
  const dow = ['日', '一', '二', '三', '四', '五', '六'][d.getDay()]
  return { day: String(d.getDate()), dow }
}

function isUpcoming(status: ReservationStatus): boolean {
  return status === '待确认' || status === '已确认'
}

// ─── Wizard form state ────────────────────────────────────────────────────────

interface WizardForm {
  date: string
  time: string
  guestCount: number
  tablePref: TablePref
  occasion: Occasion
  decorations: Decoration[]
  contactName: string
  contactPhone: string
  specialRequests: string
}

const DEFAULT_FORM: WizardForm = {
  date: todayStr(),
  time: '',
  guestCount: 2,
  tablePref: '无所谓',
  occasion: '无',
  decorations: [],
  contactName: '',
  contactPhone: '',
  specialRequests: '',
}

// ─── Sub-components ───────────────────────────────────────────────────────────

// Step indicator
function StepBar({ step }: { step: 1 | 2 | 3 }) {
  const steps = ['选时间', '选人数', '联系方式']
  return (
    <View
      style={{
        display: 'flex',
        flexDirection: 'row',
        alignItems: 'center',
        marginBottom: '32rpx',
      }}
    >
      {steps.map((label, i) => {
        const n    = i + 1
        const done = n < step
        const curr = n === step
        return (
          <React.Fragment key={n}>
            {i > 0 && (
              <View
                style={{
                  flex: 1,
                  height: '2rpx',
                  background: done ? C.primary : C.border,
                  margin: '0 8rpx',
                }}
              />
            )}
            <View style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8rpx' }}>
              <View
                style={{
                  width: '56rpx',
                  height: '56rpx',
                  borderRadius: '28rpx',
                  background: curr ? C.primary : done ? 'rgba(255,107,44,0.3)' : C.bgCard,
                  border: `2rpx solid ${curr ? C.primary : done ? C.primary : C.border}`,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <Text
                  style={{
                    color: curr ? C.white : done ? C.primary : C.text3,
                    fontSize: '26rpx',
                    fontWeight: '700',
                  }}
                >
                  {done ? '✓' : n}
                </Text>
              </View>
              <Text
                style={{
                  color: curr ? C.primary : done ? C.text2 : C.text3,
                  fontSize: '22rpx',
                  fontWeight: curr ? '600' : '400',
                }}
              >
                {label}
              </Text>
            </View>
          </React.Fragment>
        )
      })}
    </View>
  )
}

// Availability dot
function AvailDot({ avail }: { avail: DayAvail | SlotAvail }) {
  const colorMap: Record<string, string> = {
    available:    C.success,
    partial:      C.warning,
    'nearly-full': C.warning,
    full:         C.text3,
  }
  return (
    <View
      style={{
        width: '12rpx',
        height: '12rpx',
        borderRadius: '6rpx',
        background: colorMap[avail] ?? C.text3,
      }}
    />
  )
}

// Calendar grid (14 days)
interface CalendarGridProps {
  days: DayInfo[]
  selected: string
  onSelect: (d: string) => void
}

function CalendarGrid({ days, selected, onSelect }: CalendarGridProps) {
  const today = todayStr()
  return (
    <ScrollView scrollX style={{ whiteSpace: 'nowrap' }}>
      <View style={{ display: 'flex', flexDirection: 'row', gap: '12rpx', padding: '8rpx 0' }}>
        {days.map((d) => {
          const { day, dow } = shortDayLabel(d.date)
          const isToday  = d.date === today
          const isSelected = d.date === selected
          const isFull   = d.avail === 'full'

          return (
            <View
              key={d.date}
              onClick={() => !isFull && onSelect(d.date)}
              style={{
                width: '96rpx',
                borderRadius: '20rpx',
                padding: '16rpx 0',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '8rpx',
                background: isSelected ? C.primary : C.bgCard,
                border: `2rpx solid ${isSelected ? C.primary : isToday ? 'rgba(255,107,44,0.4)' : C.border}`,
                opacity: isFull ? 0.45 : 1,
                flexShrink: 0,
              }}
            >
              {isToday && !isSelected && (
                <Text style={{ color: C.primary, fontSize: '18rpx', fontWeight: '700' }}>今</Text>
              )}
              {(!isToday || isSelected) && (
                <Text style={{ color: isSelected ? 'rgba(255,255,255,0.7)' : C.text3, fontSize: '22rpx' }}>
                  {`周${dow}`}
                </Text>
              )}
              <Text
                style={{
                  color: isSelected ? C.white : C.text1,
                  fontSize: '36rpx',
                  fontWeight: '800',
                }}
              >
                {day}
              </Text>
              <AvailDot avail={d.avail} />
            </View>
          )
        })}
      </View>
    </ScrollView>
  )
}

// Time slots grid
interface TimeSlotsGridProps {
  slots: TimeSlot[]
  selected: string
  onSelect: (t: string) => void
}

function TimeSlotsGrid({ slots, selected, onSelect }: TimeSlotsGridProps) {
  const slotMap = new Map(slots.map((s) => [s.time, s.avail]))

  return (
    <View
      style={{
        display: 'flex',
        flexDirection: 'row',
        flexWrap: 'wrap',
        gap: '16rpx',
      }}
    >
      {TIME_SLOTS.map((t) => {
        const avail = slotMap.get(t) ?? 'available'
        const isSelected = t === selected
        const isFull = avail === 'full'

        let bg     = isSelected ? C.primary : C.bgCard
        let border = isSelected ? C.primary : C.border
        let color  = isSelected ? C.white   : C.text1
        if (!isSelected && avail === 'nearly-full') {
          border = 'rgba(255,159,10,0.5)'
          color  = C.warning
        }

        return (
          <View
            key={t}
            onClick={() => !isFull && onSelect(t)}
            style={{
              width: 'calc(33.33% - 12rpx)',
              height: '88rpx',
              borderRadius: '20rpx',
              background: bg,
              border: `2rpx solid ${border}`,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '4rpx',
              opacity: isFull ? 0.4 : 1,
            }}
          >
            <Text style={{ color, fontSize: '30rpx', fontWeight: isSelected ? '700' : '500' }}>{t}</Text>
            {avail === 'nearly-full' && !isSelected && (
              <Text style={{ color: C.warning, fontSize: '18rpx' }}>即将约满</Text>
            )}
            {avail === 'full' && (
              <Text style={{ color: C.text3, fontSize: '18rpx' }}>已约满</Text>
            )}
          </View>
        )
      })}
    </View>
  )
}

// Chip selector (generic single-select)
function ChipSelect<T extends string>({
  options,
  value,
  onChange,
}: {
  options: T[]
  value: T
  onChange: (v: T) => void
}) {
  return (
    <View style={{ display: 'flex', flexDirection: 'row', flexWrap: 'wrap', gap: '16rpx' }}>
      {options.map((opt) => {
        const active = opt === value
        return (
          <View
            key={opt}
            onClick={() => onChange(opt)}
            style={{
              padding: '12rpx 32rpx',
              borderRadius: '40rpx',
              background: active ? C.primary : C.bgCard,
              border: `2rpx solid ${active ? C.primary : C.border}`,
            }}
          >
            <Text style={{ color: active ? C.white : C.text2, fontSize: '28rpx', fontWeight: active ? '600' : '400' }}>
              {opt}
            </Text>
          </View>
        )
      })}
    </View>
  )
}

// Multi-select chips
function MultiChipSelect<T extends string>({
  options,
  values,
  onChange,
}: {
  options: T[]
  values: T[]
  onChange: (v: T[]) => void
}) {
  const toggle = (opt: T) => {
    if (values.includes(opt)) {
      onChange(values.filter((v) => v !== opt))
    } else {
      onChange([...values, opt])
    }
  }
  return (
    <View style={{ display: 'flex', flexDirection: 'row', flexWrap: 'wrap', gap: '16rpx' }}>
      {options.map((opt) => {
        const active = values.includes(opt)
        return (
          <View
            key={opt}
            onClick={() => toggle(opt)}
            style={{
              padding: '12rpx 32rpx',
              borderRadius: '40rpx',
              background: active ? 'rgba(255,107,44,0.15)' : C.bgCard,
              border: `2rpx solid ${active ? C.primary : C.border}`,
            }}
          >
            <Text style={{ color: active ? C.primary : C.text2, fontSize: '28rpx', fontWeight: active ? '600' : '400' }}>
              {opt}
            </Text>
          </View>
        )
      })}
    </View>
  )
}

// Guest count stepper
interface GuestStepperProps {
  value: number
  onChange: (v: number) => void
  min?: number
  max?: number
}

function GuestStepper({ value, onChange, min = 1, max = 20 }: GuestStepperProps) {
  return (
    <View
      style={{
        display: 'flex',
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '48rpx',
      }}
    >
      <View
        onClick={() => value > min && onChange(value - 1)}
        style={{
          width: '96rpx',
          height: '96rpx',
          borderRadius: '48rpx',
          background: value > min ? C.bgCard : 'rgba(30,51,64,0.4)',
          border: `2rpx solid ${value > min ? C.border : 'rgba(30,51,64,0.3)'}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Text style={{ color: value > min ? C.text1 : C.text3, fontSize: '48rpx', lineHeight: '1', marginTop: '-4rpx' }}>
          −
        </Text>
      </View>

      <View style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        <Text style={{ color: C.white, fontSize: '96rpx', fontWeight: '900', lineHeight: '1' }}>
          {value}
        </Text>
        <Text style={{ color: C.text3, fontSize: '24rpx', marginTop: '8rpx' }}>人</Text>
      </View>

      <View
        onClick={() => value < max && onChange(value + 1)}
        style={{
          width: '96rpx',
          height: '96rpx',
          borderRadius: '48rpx',
          background: value < max ? C.primary : 'rgba(255,107,44,0.2)',
          border: `2rpx solid ${value < max ? C.primary : 'rgba(255,107,44,0.2)'}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Text style={{ color: C.white, fontSize: '48rpx', lineHeight: '1', marginTop: '-4rpx' }}>
          +
        </Text>
      </View>
    </View>
  )
}

// Section card wrapper
function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View
      style={{
        background: C.bgCard,
        borderRadius: '24rpx',
        padding: '32rpx',
        border: `1rpx solid ${C.border}`,
        display: 'flex',
        flexDirection: 'column',
        gap: '24rpx',
      }}
    >
      <Text style={{ color: C.text2, fontSize: '26rpx', fontWeight: '600' }}>{title}</Text>
      {children}
    </View>
  )
}

// Form input row
function FormInput({
  label,
  value,
  placeholder,
  type,
  onChange,
}: {
  label: string
  value: string
  placeholder: string
  type?: 'text' | 'number' | 'digit' | 'phone'
  onChange: (v: string) => void
}) {
  return (
    <View
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '12rpx',
      }}
    >
      <Text style={{ color: C.text2, fontSize: '26rpx' }}>{label}</Text>
      <View
        style={{
          height: '88rpx',
          background: C.bgDeep,
          borderRadius: '16rpx',
          border: `1rpx solid ${C.border}`,
          padding: '0 24rpx',
          display: 'flex',
          alignItems: 'center',
        }}
      >
        <Input
          value={value}
          placeholder={placeholder}
          placeholderStyle={`color: ${C.text3}; font-size: 28rpx;`}
          type={type ?? 'text'}
          style={{ color: C.text1, fontSize: '28rpx', width: '100%' }}
          onInput={(e) => onChange(e.detail.value)}
        />
      </View>
    </View>
  )
}

// Animated success checkmark
function SuccessCheck() {
  return (
    <View
      style={{
        width: '160rpx',
        height: '160rpx',
        borderRadius: '80rpx',
        background: 'rgba(52,199,89,0.15)',
        border: `4rpx solid ${C.success}`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <Text style={{ color: C.success, fontSize: '80rpx', lineHeight: '1' }}>✓</Text>
    </View>
  )
}

// Reservation list card
interface ReservationCardProps {
  record: ReservationRecord
  onModify: (r: ReservationRecord) => void
  onCancel: (id: string) => void
}

function ReservationCard({ record, onModify, onCancel }: ReservationCardProps) {
  const sm = STATUS_META[record.status]
  const upcoming = isUpcoming(record.status)

  return (
    <View
      style={{
        background: C.bgCard,
        borderRadius: '24rpx',
        border: `1rpx solid ${C.border}`,
        overflow: 'hidden',
      }}
    >
      {/* Top color bar for upcoming */}
      {upcoming && (
        <View style={{ height: '6rpx', background: C.primary }} />
      )}

      <View style={{ padding: '32rpx' }}>
        {/* Header row */}
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            marginBottom: '24rpx',
          }}
        >
          <View>
            <Text style={{ color: C.white, fontSize: '36rpx', fontWeight: '800', display: 'block' }}>
              {formatDisplayDate(record.date)}
            </Text>
            <Text style={{ color: C.primary, fontSize: '40rpx', fontWeight: '900', display: 'block', marginTop: '4rpx' }}>
              {record.time}
            </Text>
          </View>
          <View
            style={{
              background: sm.bgColor,
              borderRadius: '12rpx',
              padding: '8rpx 20rpx',
            }}
          >
            <Text style={{ color: sm.color, fontSize: '26rpx', fontWeight: '600' }}>
              {record.status}
            </Text>
          </View>
        </View>

        {/* Details */}
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            flexWrap: 'wrap',
            gap: '16rpx',
            marginBottom: record.occasion !== '无' || record.decorations.length > 0 ? '16rpx' : '0',
          }}
        >
          <View
            style={{
              background: C.bgDeep,
              borderRadius: '12rpx',
              padding: '8rpx 20rpx',
              display: 'flex',
              flexDirection: 'row',
              alignItems: 'center',
              gap: '8rpx',
            }}
          >
            <Text style={{ fontSize: '24rpx' }}>👥</Text>
            <Text style={{ color: C.text2, fontSize: '26rpx' }}>{record.guestCount}人</Text>
          </View>
          <View
            style={{
              background: C.bgDeep,
              borderRadius: '12rpx',
              padding: '8rpx 20rpx',
              display: 'flex',
              flexDirection: 'row',
              alignItems: 'center',
              gap: '8rpx',
            }}
          >
            <Text style={{ fontSize: '24rpx' }}>🪑</Text>
            <Text style={{ color: C.text2, fontSize: '26rpx' }}>{record.tablePref}</Text>
          </View>
          {record.occasion !== '无' && (
            <View
              style={{
                background: 'rgba(255,107,44,0.1)',
                borderRadius: '12rpx',
                padding: '8rpx 20rpx',
              }}
            >
              <Text style={{ color: C.primary, fontSize: '26rpx' }}>{record.occasion}</Text>
            </View>
          )}
        </View>

        {/* Decorations */}
        {record.decorations.length > 0 && (
          <View
            style={{
              display: 'flex',
              flexDirection: 'row',
              gap: '12rpx',
              marginBottom: '16rpx',
              flexWrap: 'wrap',
            }}
          >
            {record.decorations.map((d) => (
              <Text key={d} style={{ color: C.text3, fontSize: '24rpx' }}>
                {d}
              </Text>
            ))}
          </View>
        )}

        {/* Deposit notice */}
        {record.depositFen > 0 && (
          <View
            style={{
              background: 'rgba(255,159,10,0.1)',
              borderRadius: '12rpx',
              padding: '12rpx 20rpx',
              marginBottom: '16rpx',
            }}
          >
            <Text style={{ color: C.warning, fontSize: '24rpx' }}>
              定金 {fenToYuanDisplay(record.depositFen)}
            </Text>
          </View>
        )}

        {/* Special requests */}
        {record.specialRequests && (
          <Text style={{ color: C.text3, fontSize: '24rpx', display: 'block', marginBottom: '16rpx' }}>
            备注：{record.specialRequests}
          </Text>
        )}

        {/* Action buttons for upcoming */}
        {upcoming && (
          <View
            style={{
              display: 'flex',
              flexDirection: 'row',
              gap: '16rpx',
              marginTop: '8rpx',
            }}
          >
            <View
              onClick={() => onModify(record)}
              style={{
                flex: 1,
                height: '80rpx',
                background: C.bgDeep,
                borderRadius: '40rpx',
                border: `2rpx solid ${C.border}`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Text style={{ color: C.text2, fontSize: '28rpx' }}>修改</Text>
            </View>
            <View
              onClick={() => {
                Taro.showModal({
                  title: '取消预约',
                  content: '确认取消该预约？取消后不可恢复。',
                  confirmText: '确认取消',
                  cancelText: '我再想想',
                  confirmColor: C.danger,
                  success: (res) => {
                    if (res.confirm) onCancel(record.reservationId)
                  },
                })
              }}
              style={{
                flex: 1,
                height: '80rpx',
                background: 'rgba(255,59,48,0.1)',
                borderRadius: '40rpx',
                border: `2rpx solid rgba(255,59,48,0.3)`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Text style={{ color: C.danger, fontSize: '28rpx' }}>取消预约</Text>
            </View>
          </View>
        )}
      </View>
    </View>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function ReservationPage() {
  const { storeId } = useStoreInfo()

  // Tabs
  const [tab, setTab] = useState<TabKey>('new')

  // Wizard
  const [step, setStep]       = useState<WizardStep>(1)
  const [form, setForm]       = useState<WizardForm>({ ...DEFAULT_FORM })
  const [modifyId, setModifyId] = useState<string | null>(null)
  const [successRecord, setSuccessRecord] = useState<ReservationRecord | null>(null)

  // Availability
  const [days, setDays]         = useState<DayInfo[]>([])
  const [slots, setSlots]       = useState<TimeSlot[]>([])
  const [availLoading, setAvailLoading] = useState(false)

  // Deposit
  const [depositFen, setDepositFen] = useState(0)

  // Submitting
  const [submitting, setSubmitting] = useState(false)

  // My reservations
  const [reservations, setReservations]     = useState<ReservationRecord[]>([])
  const [resLoading, setResLoading]         = useState(false)

  // ── Availability fetch ────────────────────────────────────────────────────

  const fetchAvailability = useCallback(async (date: string) => {
    setAvailLoading(true)
    try {
      const data = await txRequest<AvailabilityResponse>(
        `/api/v1/reservations/availability?date=${date}&store_id=${storeId}`
      )
      setDays(data.days)
      setSlots(data.slots)
    } catch {
      // Build fallback 14-day structure if API unavailable
      const today = todayStr()
      setDays(
        Array.from({ length: 14 }, (_, i) => ({
          date: addDays(today, i),
          avail: 'available' as DayAvail,
        }))
      )
      setSlots(TIME_SLOTS.map((t) => ({ time: t, avail: 'available' as SlotAvail })))
    } finally {
      setAvailLoading(false)
    }
  }, [storeId])

  // Re-fetch slots when selected date changes
  useEffect(() => {
    if (step === 1) {
      fetchAvailability(form.date)
    }
  }, [form.date, step, fetchAvailability])

  // Initial load
  useEffect(() => {
    fetchAvailability(todayStr())
  }, [fetchAvailability])

  // ── My reservations ───────────────────────────────────────────────────────

  const fetchReservations = useCallback(async () => {
    setResLoading(true)
    try {
      const data = await txRequest<ReservationRecord[]>(
        `/api/v1/reservations?store_id=${storeId}`
      )
      setReservations(data)
    } catch {
      // ignore
    } finally {
      setResLoading(false)
    }
  }, [storeId])

  useEffect(() => {
    if (tab === 'mine') fetchReservations()
  }, [tab, fetchReservations])

  // ── Auto-fill phone from user store ──────────────────────────────────────
  useEffect(() => {
    const phone = Taro.getStorageSync<string>('tx_user_phone') ?? ''
    if (phone && !form.contactPhone) {
      setForm((f) => ({ ...f, contactPhone: phone }))
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Form helpers ──────────────────────────────────────────────────────────

  const updateForm = useCallback(<K extends keyof WizardForm>(key: K, val: WizardForm[K]) => {
    setForm((f) => ({ ...f, [key]: val }))
  }, [])

  // ── Navigation ────────────────────────────────────────────────────────────

  const goStep1 = useCallback(() => setStep(1), [])
  const goStep2 = useCallback(() => {
    if (!form.date || !form.time) {
      Taro.showToast({ title: '请选择日期和时间', icon: 'none', duration: 2000 })
      return
    }
    setStep(2)
  }, [form.date, form.time])

  const goStep3 = useCallback(async () => {
    // Optionally check deposit amount
    try {
      const res = await txRequest<{ deposit_fen: number }>(
        '/api/v1/reservations/deposit-check',
        'POST',
        {
          store_id: storeId,
          date: form.date,
          time: form.time,
          guest_count: form.guestCount,
        }
      )
      setDepositFen(res.deposit_fen ?? 0)
    } catch {
      setDepositFen(0)
    }
    setStep(3)
  }, [storeId, form])

  // ── Submit ────────────────────────────────────────────────────────────────

  const handleSubmit = useCallback(async () => {
    if (!form.contactName.trim()) {
      Taro.showToast({ title: '请填写姓名', icon: 'none', duration: 2000 })
      return
    }
    if (!form.contactPhone.trim() || form.contactPhone.length < 11) {
      Taro.showToast({ title: '请填写正确的手机号', icon: 'none', duration: 2000 })
      return
    }

    setSubmitting(true)
    try {
      const payload: NewReservationPayload = {
        store_id:        storeId,
        date:            form.date,
        time:            form.time,
        guest_count:     form.guestCount,
        table_pref:      form.tablePref,
        occasion:        form.occasion,
        decorations:     form.decorations,
        contact_name:    form.contactName,
        contact_phone:   form.contactPhone,
        special_requests: form.specialRequests,
      }

      const method = modifyId ? 'PUT' : 'POST'
      const path   = modifyId
        ? `/api/v1/reservations/${modifyId}`
        : '/api/v1/reservations'

      const data = await txRequest<ReservationRecord>(path, method, payload as unknown as Record<string, unknown>)

      setSuccessRecord(data)
      setStep('success')
      setModifyId(null)
    } catch (err: any) {
      Taro.showToast({ title: err?.message ?? '提交失败，请重试', icon: 'none', duration: 2500 })
    } finally {
      setSubmitting(false)
    }
  }, [form, storeId, modifyId])

  // ── Cancel reservation ────────────────────────────────────────────────────

  const handleCancel = useCallback(async (reservationId: string) => {
    try {
      await txRequest(`/api/v1/reservations/${reservationId}`, 'DELETE')
      Taro.showToast({ title: '预约已取消', icon: 'success', duration: 2000 })
      fetchReservations()
    } catch (err: any) {
      Taro.showToast({ title: err?.message ?? '取消失败', icon: 'none', duration: 2000 })
    }
  }, [fetchReservations])

  // ── Modify flow ───────────────────────────────────────────────────────────

  const handleModify = useCallback((record: ReservationRecord) => {
    setForm({
      date:            record.date,
      time:            record.time,
      guestCount:      record.guestCount,
      tablePref:       record.tablePref,
      occasion:        record.occasion,
      decorations:     record.decorations,
      contactName:     record.contactName,
      contactPhone:    record.contactPhone,
      specialRequests: record.specialRequests,
    })
    setModifyId(record.reservationId)
    setTab('new')
    setStep(1)
  }, [])

  // ── Add to calendar ───────────────────────────────────────────────────────

  const handleAddCalendar = useCallback(() => {
    if (!successRecord) return
    const [year, month, day] = successRecord.date.split('-').map(Number)
    const [hour, minute] = successRecord.time.split(':').map(Number)
    const startTime = new Date(year, month - 1, day, hour, minute)
    const endTime   = new Date(startTime.getTime() + 2 * 60 * 60 * 1000)

    Taro.addPhoneCalendar?.({
      title:     `餐厅预约 ${successRecord.guestCount}人`,
      startTime: Math.floor(startTime.getTime() / 1000),
      endTime:   Math.floor(endTime.getTime() / 1000),
      notes:     successRecord.specialRequests || '用餐预约',
      success: () => Taro.showToast({ title: '已添加到日历', icon: 'success', duration: 2000 }),
      fail: () => Taro.showToast({ title: '无法访问日历', icon: 'none', duration: 2000 }),
    })
  }, [successRecord])

  // ── Reset wizard ──────────────────────────────────────────────────────────

  const resetWizard = useCallback(() => {
    setForm({ ...DEFAULT_FORM })
    setModifyId(null)
    setStep(1)
    setSuccessRecord(null)
    setDepositFen(0)
  }, [])

  // ─── Render ───────────────────────────────────────────────────────────────

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
        <Text style={{ color: C.white, fontSize: '40rpx', fontWeight: '800' }}>
          预约订座
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
        {(
          [
            { key: 'new',  label: modifyId ? '修改预约' : '新建预约' },
            { key: 'mine', label: '我的预约' },
          ] as { key: TabKey; label: string }[]
        ).map((t) => {
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
      <ScrollView scrollY style={{ flex: 1 }} enableFlex>
        <View style={{ padding: '32rpx', paddingBottom: '80rpx' }}>

          {/* ═══ NEW RESERVATION TAB ════════════════════════════════════════ */}
          {tab === 'new' && (
            <View style={{ display: 'flex', flexDirection: 'column', gap: '24rpx' }}>

              {/* ── SUCCESS STATE ── */}
              {step === 'success' && successRecord && (
                <View
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    gap: '32rpx',
                    paddingTop: '40rpx',
                  }}
                >
                  <SuccessCheck />
                  <Text style={{ color: C.white, fontSize: '44rpx', fontWeight: '800' }}>
                    {modifyId ? '修改成功' : '预约成功'}
                  </Text>

                  {/* Summary card */}
                  <View
                    style={{
                      width: '100%',
                      background: C.bgCard,
                      borderRadius: '24rpx',
                      border: `1rpx solid ${C.border}`,
                      padding: '32rpx',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '20rpx',
                    }}
                  >
                    {[
                      { label: '日期', value: formatDisplayDate(successRecord.date) },
                      { label: '时间', value: successRecord.time },
                      { label: '人数', value: `${successRecord.guestCount}人` },
                      { label: '座位偏好', value: successRecord.tablePref },
                      ...(successRecord.occasion !== '无' ? [{ label: '特殊场合', value: successRecord.occasion }] : []),
                      { label: '联系人', value: successRecord.contactName },
                      { label: '手机', value: successRecord.contactPhone },
                    ].map(({ label, value }) => (
                      <View
                        key={label}
                        style={{
                          display: 'flex',
                          flexDirection: 'row',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                        }}
                      >
                        <Text style={{ color: C.text3, fontSize: '26rpx' }}>{label}</Text>
                        <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '600' }}>{value}</Text>
                      </View>
                    ))}
                    {successRecord.depositFen > 0 && (
                      <View
                        style={{
                          background: 'rgba(255,159,10,0.1)',
                          borderRadius: '12rpx',
                          padding: '16rpx',
                          marginTop: '8rpx',
                        }}
                      >
                        <Text style={{ color: C.warning, fontSize: '26rpx', textAlign: 'center' }}>
                          定金 {fenToYuanDisplay(successRecord.depositFen)} 已支付
                        </Text>
                      </View>
                    )}
                  </View>

                  {/* Add to calendar */}
                  <View
                    onClick={handleAddCalendar}
                    style={{
                      width: '100%',
                      height: '96rpx',
                      background: C.bgCard,
                      borderRadius: '48rpx',
                      border: `2rpx solid ${C.border}`,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '12rpx',
                    }}
                  >
                    <Text style={{ fontSize: '32rpx' }}>📅</Text>
                    <Text style={{ color: C.text2, fontSize: '28rpx' }}>添加到微信日历</Text>
                  </View>

                  {/* New reservation button */}
                  <View
                    onClick={resetWizard}
                    style={{
                      width: '100%',
                      height: '96rpx',
                      background: C.primary,
                      borderRadius: '48rpx',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      boxShadow: '0 8rpx 32rpx rgba(255,107,44,0.4)',
                    }}
                  >
                    <Text style={{ color: C.white, fontSize: '32rpx', fontWeight: '700' }}>
                      再次预约
                    </Text>
                  </View>
                </View>
              )}

              {/* ── STEP 1: 选时间 ── */}
              {typeof step === 'number' && step === 1 && (
                <>
                  <StepBar step={1} />

                  {/* Calendar */}
                  <SectionCard title="选择日期">
                    {availLoading ? (
                      <Text style={{ color: C.text3, fontSize: '26rpx' }}>加载中…</Text>
                    ) : (
                      <CalendarGrid
                        days={days.length > 0 ? days : Array.from({ length: 14 }, (_, i) => ({
                          date: addDays(todayStr(), i),
                          avail: 'available' as DayAvail,
                        }))}
                        selected={form.date}
                        onSelect={(d) => updateForm('date', d)}
                      />
                    )}
                  </SectionCard>

                  {/* Time slots */}
                  {form.date && (
                    <SectionCard title={`${formatDisplayDate(form.date)} 可用时段`}>
                      {/* Legend */}
                      <View style={{ display: 'flex', flexDirection: 'row', gap: '24rpx', marginBottom: '8rpx' }}>
                        {[
                          { color: C.success,  label: '有位' },
                          { color: C.warning,  label: '即将约满' },
                          { color: C.text3,    label: '已约满' },
                        ].map(({ color, label }) => (
                          <View
                            key={label}
                            style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '8rpx' }}
                          >
                            <View
                              style={{ width: '16rpx', height: '16rpx', borderRadius: '8rpx', background: color }}
                            />
                            <Text style={{ color: C.text3, fontSize: '22rpx' }}>{label}</Text>
                          </View>
                        ))}
                      </View>
                      <TimeSlotsGrid
                        slots={slots}
                        selected={form.time}
                        onSelect={(t) => updateForm('time', t)}
                      />
                    </SectionCard>
                  )}

                  {/* Next button */}
                  <View
                    onClick={goStep2}
                    style={{
                      height: '104rpx',
                      background: form.time ? C.primary : 'rgba(255,107,44,0.3)',
                      borderRadius: '52rpx',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      boxShadow: form.time ? '0 8rpx 32rpx rgba(255,107,44,0.4)' : 'none',
                    }}
                  >
                    <Text style={{ color: C.white, fontSize: '34rpx', fontWeight: '700' }}>
                      下一步：选人数
                    </Text>
                  </View>
                </>
              )}

              {/* ── STEP 2: 选人数 & 偏好 ── */}
              {typeof step === 'number' && step === 2 && (
                <>
                  <StepBar step={2} />

                  {/* Guest count */}
                  <SectionCard title="用餐人数">
                    <GuestStepper
                      value={form.guestCount}
                      onChange={(v) => updateForm('guestCount', v)}
                    />
                  </SectionCard>

                  {/* Table preference */}
                  <SectionCard title="座位偏好（可选）">
                    <ChipSelect
                      options={TABLE_PREFS}
                      value={form.tablePref}
                      onChange={(v) => updateForm('tablePref', v)}
                    />
                  </SectionCard>

                  {/* Special occasion */}
                  <SectionCard title="特殊场合">
                    <ChipSelect
                      options={OCCASIONS}
                      value={form.occasion}
                      onChange={(v) => {
                        updateForm('occasion', v)
                        updateForm('decorations', [])
                      }}
                    />
                  </SectionCard>

                  {/* Decoration options (conditional) */}
                  {form.occasion !== '无' && OCCASION_DECORATION_MAP[form.occasion].length > 0 && (
                    <SectionCard title={`${form.occasion}布置选项（多选）`}>
                      <MultiChipSelect
                        options={OCCASION_DECORATION_MAP[form.occasion]}
                        values={form.decorations}
                        onChange={(v) => updateForm('decorations', v)}
                      />
                    </SectionCard>
                  )}

                  {/* Nav buttons */}
                  <View style={{ display: 'flex', flexDirection: 'row', gap: '16rpx' }}>
                    <View
                      onClick={goStep1}
                      style={{
                        flex: 1,
                        height: '96rpx',
                        background: C.bgCard,
                        borderRadius: '48rpx',
                        border: `2rpx solid ${C.border}`,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                      }}
                    >
                      <Text style={{ color: C.text2, fontSize: '32rpx' }}>上一步</Text>
                    </View>
                    <View
                      onClick={goStep3}
                      style={{
                        flex: 2,
                        height: '96rpx',
                        background: C.primary,
                        borderRadius: '48rpx',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        boxShadow: '0 8rpx 32rpx rgba(255,107,44,0.4)',
                      }}
                    >
                      <Text style={{ color: C.white, fontSize: '32rpx', fontWeight: '700' }}>
                        下一步：联系方式
                      </Text>
                    </View>
                  </View>
                </>
              )}

              {/* ── STEP 3: 联系方式 ── */}
              {typeof step === 'number' && step === 3 && (
                <>
                  <StepBar step={3} />

                  {/* Reservation summary strip */}
                  <View
                    style={{
                      background: 'rgba(255,107,44,0.08)',
                      borderRadius: '20rpx',
                      padding: '20rpx 28rpx',
                      border: `1rpx solid rgba(255,107,44,0.25)`,
                      display: 'flex',
                      flexDirection: 'row',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                    }}
                  >
                    <Text style={{ color: C.primary, fontSize: '28rpx', fontWeight: '700' }}>
                      {formatDisplayDate(form.date)} {form.time}
                    </Text>
                    <Text style={{ color: C.text2, fontSize: '28rpx' }}>
                      {form.guestCount}人 · {form.tablePref}
                    </Text>
                  </View>

                  {/* Contact form */}
                  <SectionCard title="联系方式">
                    <FormInput
                      label="姓名"
                      value={form.contactName}
                      placeholder="请输入您的姓名"
                      onChange={(v) => updateForm('contactName', v)}
                    />
                    <FormInput
                      label="手机号"
                      value={form.contactPhone}
                      placeholder="请输入手机号"
                      type="number"
                      onChange={(v) => updateForm('contactPhone', v)}
                    />
                    {/* Special requests textarea */}
                    <View style={{ display: 'flex', flexDirection: 'column', gap: '12rpx' }}>
                      <Text style={{ color: C.text2, fontSize: '26rpx' }}>特殊要求（可选）</Text>
                      <View
                        style={{
                          background: C.bgDeep,
                          borderRadius: '16rpx',
                          border: `1rpx solid ${C.border}`,
                          padding: '16rpx 24rpx',
                          minHeight: '160rpx',
                        }}
                      >
                        <Input
                          value={form.specialRequests}
                          placeholder="例如：需要儿童座椅、有过敏食物等"
                          placeholderStyle={`color: ${C.text3}; font-size: 28rpx;`}
                          style={{ color: C.text1, fontSize: '28rpx', width: '100%' }}
                          onInput={(e) => updateForm('specialRequests', e.detail.value)}
                        />
                      </View>
                    </View>
                  </SectionCard>

                  {/* Deposit notice */}
                  {depositFen > 0 && (
                    <View
                      style={{
                        background: 'rgba(255,159,10,0.1)',
                        borderRadius: '20rpx',
                        padding: '24rpx 28rpx',
                        border: `1rpx solid rgba(255,159,10,0.3)`,
                        display: 'flex',
                        flexDirection: 'row',
                        alignItems: 'center',
                        gap: '16rpx',
                      }}
                    >
                      <Text style={{ fontSize: '36rpx' }}>💳</Text>
                      <Text style={{ color: C.warning, fontSize: '28rpx', flex: 1 }}>
                        需支付定金 {fenToYuanDisplay(depositFen)} 以完成预约
                      </Text>
                    </View>
                  )}

                  {/* Nav buttons */}
                  <View style={{ display: 'flex', flexDirection: 'row', gap: '16rpx' }}>
                    <View
                      onClick={() => setStep(2)}
                      style={{
                        flex: 1,
                        height: '96rpx',
                        background: C.bgCard,
                        borderRadius: '48rpx',
                        border: `2rpx solid ${C.border}`,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                      }}
                    >
                      <Text style={{ color: C.text2, fontSize: '32rpx' }}>上一步</Text>
                    </View>
                    <View
                      onClick={!submitting ? handleSubmit : undefined}
                      style={{
                        flex: 2,
                        height: '96rpx',
                        background: submitting ? 'rgba(255,107,44,0.5)' : C.primary,
                        borderRadius: '48rpx',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        boxShadow: submitting ? 'none' : '0 8rpx 32rpx rgba(255,107,44,0.4)',
                      }}
                    >
                      <Text style={{ color: C.white, fontSize: '32rpx', fontWeight: '700' }}>
                        {submitting ? '提交中…' : depositFen > 0 ? '支付定金并预约' : '确认预约'}
                      </Text>
                    </View>
                  </View>
                </>
              )}
            </View>
          )}

          {/* ═══ MY RESERVATIONS TAB ════════════════════════════════════════ */}
          {tab === 'mine' && (
            <View style={{ display: 'flex', flexDirection: 'column', gap: '20rpx' }}>
              {resLoading && (
                <View
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    paddingTop: '80rpx',
                  }}
                >
                  <Text style={{ color: C.text3, fontSize: '28rpx' }}>加载中…</Text>
                </View>
              )}

              {!resLoading && reservations.length === 0 && (
                <View
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    gap: '24rpx',
                    paddingTop: '120rpx',
                  }}
                >
                  <Text style={{ fontSize: '80rpx' }}>📅</Text>
                  <Text style={{ color: C.text3, fontSize: '30rpx' }}>暂无预约记录</Text>
                  <View
                    onClick={() => setTab('new')}
                    style={{
                      marginTop: '16rpx',
                      height: '88rpx',
                      padding: '0 56rpx',
                      background: C.primary,
                      borderRadius: '44rpx',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      boxShadow: '0 8rpx 32rpx rgba(255,107,44,0.3)',
                    }}
                  >
                    <Text style={{ color: C.white, fontSize: '30rpx', fontWeight: '700' }}>
                      立即预约
                    </Text>
                  </View>
                </View>
              )}

              {!resLoading && reservations.length > 0 && (
                <>
                  {/* Upcoming */}
                  {reservations.filter((r) => isUpcoming(r.status)).length > 0 && (
                    <>
                      <Text
                        style={{
                          color: C.text3,
                          fontSize: '24rpx',
                          fontWeight: '600',
                          letterSpacing: '2rpx',
                          textTransform: 'uppercase',
                          display: 'block',
                          marginBottom: '4rpx',
                        }}
                      >
                        即将到来
                      </Text>
                      {reservations
                        .filter((r) => isUpcoming(r.status))
                        .map((r) => (
                          <ReservationCard
                            key={r.reservationId}
                            record={r}
                            onModify={handleModify}
                            onCancel={handleCancel}
                          />
                        ))}
                    </>
                  )}

                  {/* Past */}
                  {reservations.filter((r) => !isUpcoming(r.status)).length > 0 && (
                    <>
                      <Text
                        style={{
                          color: C.text3,
                          fontSize: '24rpx',
                          fontWeight: '600',
                          letterSpacing: '2rpx',
                          display: 'block',
                          marginTop: '8rpx',
                          marginBottom: '4rpx',
                        }}
                      >
                        历史记录
                      </Text>
                      {reservations
                        .filter((r) => !isUpcoming(r.status))
                        .map((r) => (
                          <ReservationCard
                            key={r.reservationId}
                            record={r}
                            onModify={handleModify}
                            onCancel={handleCancel}
                          />
                        ))}
                    </>
                  )}
                </>
              )}
            </View>
          )}

        </View>
      </ScrollView>
    </View>
  )
}
