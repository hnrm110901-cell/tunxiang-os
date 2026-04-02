/**
 * Explicit manual mock for @tarojs/taro, used by moduleNameMapper in jest.config.js.
 * Kept in sync with the inline mock in setup.ts — having both lets individual
 * test files import from '@tarojs/taro' and get typed jest.fn() references.
 */
const Taro = {
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
}

export default Taro
export const {
  getStorageSync,
  setStorageSync,
  removeStorageSync,
  clearStorageSync,
  showToast,
  showModal,
  navigateTo,
  navigateBack,
  switchTab,
  redirectTo,
  login,
  request,
  requestPayment,
  setClipboardData,
  makePhoneCall,
  chooseImage,
  useDidShow,
  usePullDownRefresh,
  useReachBottom,
  stopPullDownRefresh,
  getCurrentInstance,
  getSystemInfoSync,
  ENV_TYPE,
  getEnv,
} = Taro
