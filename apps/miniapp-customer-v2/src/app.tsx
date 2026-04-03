import { PropsWithChildren } from 'react'
import { useLaunch } from '@tarojs/taro'
import './styles/global.css'

function App({ children }: PropsWithChildren) {
  useLaunch(() => {
    console.log('TunxiangOS MiniApp v2 launched')
  })
  return <>{children}</>
}

export default App
