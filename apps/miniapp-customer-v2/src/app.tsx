import { PropsWithChildren } from 'react'
import Taro, { useLaunch } from '@tarojs/taro'
import { getMerchantTheme } from './api/menu'
import { useMerchantTheme, DEFAULT_THEME } from './store/useMerchantTheme'
import { MemCache } from './utils/performance'
import './styles/global.css'

function App({ children }: PropsWithChildren) {
  const setTheme = useMerchantTheme((s) => s.setTheme)
  const setLoading = useMerchantTheme((s) => s.setLoading)

  useLaunch(() => {
    console.log('TunxiangOS MiniApp v2 launched')

    // ── 加载商户主题配置 ────────────────────────────────────────────
    const merchantCode = Taro.getStorageSync<string>('tx_merchant_code') || 'default'

    // 先检查内存缓存
    const cached = MemCache.get<ReturnType<typeof getMerchantTheme>>('merchant-theme')
    if (cached) {
      setTheme(cached as unknown as ReturnType<typeof getMerchantTheme>)
      return
    }

    setLoading(true)

    getMerchantTheme(merchantCode)
      .then((theme) => {
        setTheme(theme)
        MemCache.set('merchant-theme', theme, 180) // 3分钟TTL
      })
      .catch((err) => {
        console.error('[App] failed to load merchant theme, using default', err)
        setTheme(DEFAULT_THEME)
      })
  })

  return <>{children}</>
}

export default App
