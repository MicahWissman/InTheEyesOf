import { defineConfig } from 'vite'
import type { Connect, Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import basicSsl from '@vitejs/plugin-basic-ssl'
import { appendFile, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// Same /log handler as server/ask-proxy.js, so a local `npm run dev` / `vite preview`
// test session also records the anonymous visit log (server/logs/visits.jsonl).
const VISIT_LOG = fileURLToPath(new URL('../server/logs/visits.jsonl', import.meta.url))

const visitLogHandler: Connect.NextHandleFunction = (req, res, next) => {
  if (req.url !== '/log' || req.method !== 'POST') return next()
  let body = ''
  req.on('data', chunk => { body += chunk; if (body.length > 65536) req.destroy() })
  req.on('end', () => {
    try {
      const events = JSON.parse(body)
      const received = new Date().toISOString()
      const lines = (Array.isArray(events) ? events.slice(0, 200) : [])
        .filter(e => e && typeof e === 'object' && typeof e.v === 'string' && typeof e.type === 'string')
        .map(e => JSON.stringify({ ...e, received }))
        .filter(l => l.length <= 2048)
      if (lines.length) {
        mkdirSync(fileURLToPath(new URL('../server/logs', import.meta.url)), { recursive: true })
        appendFile(VISIT_LOG, lines.join('\n') + '\n', () => {})
      }
    } catch { /* malformed batch — drop it */ }
    res.statusCode = 204
    res.end()
  })
}

const visitLog = (): Plugin => ({
  name: 'visit-log',
  configureServer: server => { server.middlewares.use(visitLogHandler) },
  configurePreviewServer: server => { server.middlewares.use(visitLogHandler) },
})

export default defineConfig({
  plugins: [
    react(),
    basicSsl(),
    visitLog(),
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
