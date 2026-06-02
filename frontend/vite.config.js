import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    host: '0.0.0.0',
    proxy: {
      '/api':        { target: 'http://localhost:8009', changeOrigin: true },
      '/ws':         { target: 'ws://localhost:8009',   changeOrigin: true, ws: true },
      '/artifacts':  { target: 'http://localhost:8009', changeOrigin: true },
    },
  },
})
