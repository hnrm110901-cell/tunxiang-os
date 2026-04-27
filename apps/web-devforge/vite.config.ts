import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// 端口分配说明：5180 已被 web-hub 占用，5181 已被 h5-self-order 占用
// web-devforge 使用 5182（task 描述的 5180 与现有应用冲突，主动调整）
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src')
    }
  },
  server: {
    port: 5182,
    proxy: {
      // 代理到 tx-devforge:8017（DevForge 后端，8015/8016 被 tx-expense/tx-pay 占用）
      '/api': {
        target: 'http://localhost:8017',
        changeOrigin: true
      }
    }
  },
  build: {
    target: 'es2022',
    sourcemap: true
  }
})
