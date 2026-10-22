import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 15173,
    proxy: {
      '/uploads': {
        target: process.env.CITYMATE_API_URL || 'http://localhost:18000',
        changeOrigin: true,
      },
      '/api': {
        target: process.env.CITYMATE_API_URL || 'http://localhost:18000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
