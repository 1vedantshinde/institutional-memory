import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'node:path'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    // Fixed URLs so a developer's .env.local (loaded by Vitest) can't change
    // which hosts the MSW handlers and tests expect.
    env: {
      VITE_CHAT_API_URL: 'http://localhost:8000',
      VITE_CORE_API_URL: 'http://localhost:8001',
      VITE_USE_MOCKS: 'false',
      VITE_ENABLE_PROPOSED: 'false',
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
})
