import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const target = env.BACKEND_PROXY_URL || 'http://10.43.0.10:8000'
  const proxy = { '/api': { target }, '/ws': { target, ws: true }, '/health': { target } }
  return { plugins: [react()], server: { proxy }, preview: { proxy } }
})
