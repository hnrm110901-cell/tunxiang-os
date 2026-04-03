/**
 * Jest global setup — mocks all Taro APIs and components so tests run in
 * jsdom without a WeChat/Taro runtime.
 */
import React from 'react'

// ─── @tarojs/taro ────────────────────────────────────────────────────────────

jest.mock('@tarojs/taro', () => ({
  getStorageSync: jest.fn().mockReturnValue(''),
  setStorageSync: jest.fn(),
  removeStorageSync: jest.fn(),
  clearStorageSync: jest.fn(),
  showToast: jest.fn().mockResolvedValue({}),
  showModal: jest.fn().mockResolvedValue({ confirm: true }),
  navigateTo: jest.fn().mockResolvedValue({}),
  navigateBack: jest.fn().mockResolvedValue({}),
  switchTab: jest.fn().mockResolvedValue({}),
  redirectTo: jest.fn().mockResolvedValue({}),
  login: jest.fn().mockResolvedValue({ code: 'mock_code' }),
  request: jest.fn(),
  requestPayment: jest.fn().mockResolvedValue({}),
  setClipboardData: jest.fn().mockResolvedValue({}),
  makePhoneCall: jest.fn(),
  chooseImage: jest.fn().mockResolvedValue({ tempFilePaths: ['mock://image.jpg'] }),
  useDidShow: jest.fn(),
  usePullDownRefresh: jest.fn(),
  useReachBottom: jest.fn(),
  stopPullDownRefresh: jest.fn(),
  getCurrentInstance: jest.fn().mockReturnValue({ router: { params: {} } }),
  getSystemInfoSync: jest.fn().mockReturnValue({ platform: 'devtools' }),
  ENV_TYPE: { WEAPP: 'WEAPP', TT: 'TT', WEB: 'WEB' },
  getEnv: jest.fn().mockReturnValue('WEAPP'),
}))

// ─── @tarojs/components ──────────────────────────────────────────────────────

jest.mock('@tarojs/components', () => ({
  View: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) =>
    React.createElement('div', props, children),
  Text: ({ children, ...props }: React.HTMLAttributes<HTMLSpanElement>) =>
    React.createElement('span', props, children),
  Image: (props: React.ImgHTMLAttributes<HTMLImageElement>) =>
    React.createElement('img', props),
  Input: (props: React.InputHTMLAttributes<HTMLInputElement>) =>
    React.createElement('input', props),
  Textarea: (props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) =>
    React.createElement('textarea', props),
  ScrollView: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) =>
    React.createElement('div', props, children),
  Swiper: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', {}, children),
  SwiperItem: ({ children }: { children: React.ReactNode }) =>
    React.createElement('div', {}, children),
  Button: ({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) =>
    React.createElement('button', props, children),
  Switch: (props: React.InputHTMLAttributes<HTMLInputElement>) =>
    React.createElement('input', { type: 'checkbox', ...props }),
}))
