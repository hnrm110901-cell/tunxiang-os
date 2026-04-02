import { create } from 'zustand'
import Taro from '@tarojs/taro'

// ─── Types ──────────────────────────────────────────────────────────────────

export type MemberLevel = 'bronze' | 'silver' | 'gold' | 'diamond'

export interface UserPreferences {
  spicy: string
  sweet: string
  allergies: string[]
}

export interface UserProfile {
  userId: string
  openId: string
  nickname: string
  avatarUrl: string
  phone: string
  memberLevel: MemberLevel
  pointsBalance: number
  storedValueFen: number
  preferences: UserPreferences
}

interface UserState {
  isLoggedIn: boolean
  userId: string
  openId: string
  nickname: string
  avatarUrl: string
  phone: string
  memberLevel: MemberLevel
  pointsBalance: number
  storedValueFen: number
  preferences: UserPreferences
}

interface UserActions {
  setUser: (profile: Partial<UserProfile>) => void
  setMemberInfo: (level: MemberLevel, points: number, storedValue: number) => void
  updatePreferences: (prefs: Partial<UserPreferences>) => void
  logout: () => void
}

type UserStore = UserState & UserActions

// ─── Defaults ────────────────────────────────────────────────────────────────

const DEFAULT_PREFERENCES: UserPreferences = {
  spicy: '',
  sweet: '',
  allergies: [],
}

const DEFAULT_STATE: UserState = {
  isLoggedIn: false,
  userId: '',
  openId: '',
  nickname: '',
  avatarUrl: '',
  phone: '',
  memberLevel: 'bronze',
  pointsBalance: 0,
  storedValueFen: 0,
  preferences: DEFAULT_PREFERENCES,
}

// ─── Restore from storage on init ────────────────────────────────────────────

function restoreSession(): Pick<UserState, 'userId' | 'isLoggedIn'> {
  try {
    const userId = Taro.getStorageSync('tx_user_id') as string | undefined
    const token = Taro.getStorageSync('tx_token') as string | undefined
    if (userId && token) {
      return { userId, isLoggedIn: true }
    }
  } catch (_e) {
    // storage unavailable — fall back to logged-out state
  }
  return { userId: '', isLoggedIn: false }
}

const sessionSnapshot = restoreSession()

// ─── Store ───────────────────────────────────────────────────────────────────

export const useUserStore = create<UserStore>((set) => ({
  ...DEFAULT_STATE,
  ...sessionSnapshot,

  setUser(profile) {
    set((state) => ({
      isLoggedIn: true,
      userId: profile.userId ?? state.userId,
      openId: profile.openId ?? state.openId,
      nickname: profile.nickname ?? state.nickname,
      avatarUrl: profile.avatarUrl ?? state.avatarUrl,
      phone: profile.phone ?? state.phone,
      memberLevel: profile.memberLevel ?? state.memberLevel,
      pointsBalance: profile.pointsBalance ?? state.pointsBalance,
      storedValueFen: profile.storedValueFen ?? state.storedValueFen,
      preferences: profile.preferences ?? state.preferences,
    }))
  },

  setMemberInfo(level, points, storedValue) {
    set({ memberLevel: level, pointsBalance: points, storedValueFen: storedValue })
  },

  updatePreferences(prefs) {
    set((state) => ({
      preferences: { ...state.preferences, ...prefs },
    }))
  },

  logout() {
    try {
      Taro.clearStorageSync()
    } catch (_e) {
      // clearing storage must not crash the app
    }
    set({ ...DEFAULT_STATE })
  },
}))
