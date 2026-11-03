import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 開發時把 /api 轉送到 Controller（預設 http://127.0.0.1:8080）
const backend = process.env.CONTROLLER_URL || 'http://127.0.0.1:8080'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': { target: backend, changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
