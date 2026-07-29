import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import basicSsl from '@vitejs/plugin-basic-ssl'

export default defineConfig({
  plugins: [
    react(),
    basicSsl(),
  ],
  server: {
    host: true,   // expose on all network interfaces (LAN)
    port: 5173,
    https: {},
  },
  preview: {
    host: true,   // same for `vite preview` (serves built dist/)
    port: 4173,
    https: {},
  },
})
