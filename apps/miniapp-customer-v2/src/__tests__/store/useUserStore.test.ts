/**
 * useUserStore tests
 *
 * The store calls Taro.getStorageSync at module load time to restore session.
 * We use jest.resetModules() + require() to get a fresh store for each test
 * that needs a specific storage state.
 */

import Taro from '@tarojs/taro'
import type { UserProfile, MemberLevel } from '../../store/useUserStore'

// ─── helpers ─────────────────────────────────────────────────────────────────

function freshStore() {
  jest.resetModules()
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const mod = require('../../store/useUserStore') as typeof import('../../store/useUserStore')
  return mod.useUserStore
}

const FULL_PROFILE: UserProfile = {
  userId: 'u-001',
  openId: 'ox-abc',
  nickname: '屯象粉丝',
  avatarUrl: 'https://cdn.example.com/avatar.jpg',
  phone: '13812345678',
  memberLevel: 'gold',
  pointsBalance: 1500,
  storedValueFen: 20000,
  preferences: { spicy: 'mild', sweet: 'none', allergies: ['peanut'] },
}

// ─── tests ───────────────────────────────────────────────────────────────────

describe('useUserStore', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(Taro.getStorageSync as jest.Mock).mockReturnValue('')
  })

  // ── setUser ────────────────────────────────────────────────────────────────

  describe('setUser', () => {
    it('marks the user as logged in and populates all provided fields', () => {
      const store = freshStore()
      store.getState().setUser(FULL_PROFILE)

      const state = store.getState()
      expect(state.isLoggedIn).toBe(true)
      expect(state.userId).toBe('u-001')
      expect(state.openId).toBe('ox-abc')
      expect(state.nickname).toBe('屯象粉丝')
      expect(state.avatarUrl).toBe('https://cdn.example.com/avatar.jpg')
      expect(state.phone).toBe('13812345678')
      expect(state.memberLevel).toBe('gold')
      expect(state.pointsBalance).toBe(1500)
      expect(state.storedValueFen).toBe(20000)
      expect(state.preferences).toEqual({
        spicy: 'mild',
        sweet: 'none',
        allergies: ['peanut'],
      })
    })

    it('performs a partial update — only provided fields change', () => {
      const store = freshStore()
      store.getState().setUser(FULL_PROFILE)
      store.getState().setUser({ nickname: '新昵称', pointsBalance: 999 })

      const state = store.getState()
      expect(state.nickname).toBe('新昵称')
      expect(state.pointsBalance).toBe(999)
      // unchanged fields
      expect(state.userId).toBe('u-001')
      expect(state.phone).toBe('13812345678')
    })

    it('sets isLoggedIn to true even when only a single field is provided', () => {
      const store = freshStore()
      expect(store.getState().isLoggedIn).toBe(false)
      store.getState().setUser({ userId: 'u-999' })
      expect(store.getState().isLoggedIn).toBe(true)
    })
  })

  // ── logout ─────────────────────────────────────────────────────────────────

  describe('logout', () => {
    it('resets all state fields to defaults', () => {
      const store = freshStore()
      store.getState().setUser(FULL_PROFILE)
      store.getState().logout()

      const state = store.getState()
      expect(state.isLoggedIn).toBe(false)
      expect(state.userId).toBe('')
      expect(state.openId).toBe('')
      expect(state.nickname).toBe('')
      expect(state.avatarUrl).toBe('')
      expect(state.phone).toBe('')
      expect(state.memberLevel).toBe('bronze')
      expect(state.pointsBalance).toBe(0)
      expect(state.storedValueFen).toBe(0)
      expect(state.preferences).toEqual({ spicy: '', sweet: '', allergies: [] })
    })

    it('calls Taro.clearStorageSync to purge auth tokens', () => {
      const store = freshStore()
      store.getState().setUser(FULL_PROFILE)
      store.getState().logout()

      expect(Taro.clearStorageSync).toHaveBeenCalledTimes(1)
    })
  })

  // ── setMemberInfo ──────────────────────────────────────────────────────────

  describe('setMemberInfo', () => {
    it('updates memberLevel, pointsBalance, and storedValueFen atomically', () => {
      const store = freshStore()
      store.getState().setUser({ userId: 'u-001' })
      store.getState().setMemberInfo('diamond', 9999, 50000)

      const state = store.getState()
      expect(state.memberLevel).toBe<MemberLevel>('diamond')
      expect(state.pointsBalance).toBe(9999)
      expect(state.storedValueFen).toBe(50000)
    })

    it('does not affect other user state fields', () => {
      const store = freshStore()
      store.getState().setUser(FULL_PROFILE)
      store.getState().setMemberInfo('silver', 100, 0)

      expect(store.getState().nickname).toBe('屯象粉丝')
      expect(store.getState().phone).toBe('13812345678')
    })
  })

  // ── updatePreferences ──────────────────────────────────────────────────────

  describe('updatePreferences', () => {
    it('merges partial preferences without clobbering unspecified keys', () => {
      const store = freshStore()
      store.getState().setUser({
        preferences: { spicy: 'mild', sweet: 'none', allergies: ['peanut'] },
      })

      store.getState().updatePreferences({ spicy: 'hot' })

      const { preferences } = store.getState()
      expect(preferences.spicy).toBe('hot')
      expect(preferences.sweet).toBe('none')     // unchanged
      expect(preferences.allergies).toEqual(['peanut']) // unchanged
    })

    it('can update allergies array', () => {
      const store = freshStore()
      store.getState().updatePreferences({ allergies: ['shrimp', 'gluten'] })
      expect(store.getState().preferences.allergies).toEqual(['shrimp', 'gluten'])
    })
  })

  // ── restoreSession ─────────────────────────────────────────────────────────

  describe('restoreSession', () => {
    it('restores userId and sets isLoggedIn=true when both tx_user_id and tx_token exist in storage', () => {
      // getStorageSync is called with different keys — simulate per-key response
      ;(Taro.getStorageSync as jest.Mock).mockImplementation((key: string) => {
        if (key === 'tx_user_id') return 'u-restored'
        if (key === 'tx_token') return 'jwt-token-abc'
        return ''
      })

      const store = freshStore()
      expect(store.getState().isLoggedIn).toBe(true)
      expect(store.getState().userId).toBe('u-restored')
    })

    it('stays logged out when tx_token is missing', () => {
      ;(Taro.getStorageSync as jest.Mock).mockImplementation((key: string) => {
        if (key === 'tx_user_id') return 'u-restored'
        return '' // no token
      })

      const store = freshStore()
      expect(store.getState().isLoggedIn).toBe(false)
    })

    it('stays logged out when tx_user_id is missing', () => {
      ;(Taro.getStorageSync as jest.Mock).mockImplementation((key: string) => {
        if (key === 'tx_token') return 'jwt-token-abc'
        return '' // no userId
      })

      const store = freshStore()
      expect(store.getState().isLoggedIn).toBe(false)
    })
  })
})
