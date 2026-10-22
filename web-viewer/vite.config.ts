import { defineConfig, type Plugin } from 'vite'
import type { Server, Socket } from 'node:net'
import react from '@vitejs/plugin-react'
import basicSsl from '@vitejs/plugin-basic-ssl'

// iOS browsers often send plain http:// to the HTTPS port, which the TLS server
// silently drops ("connection was lost"). Sniff the first byte of each connection
// and answer non-TLS traffic with a redirect to https on the same port.
function httpToHttpsRedirect(): Plugin {
  const wrap = (srv: Server | null | undefined) => {
    if (!srv) return
    const tlsListeners = srv.listeners('connection') as ((s: Socket) => void)[]
    srv.removeAllListeners('connection')
    // Without these, a client reset before the TLS layer takes over would crash Vite.
    srv.on('tlsClientError', (err: NodeJS.ErrnoException, s: Socket) =>
      console.warn(`[https] TLS error from ${s.remoteAddress}: ${err.code ?? ''} ${err.message}`))
    srv.on('connection', (socket: Socket) => {
      socket.on('error', () => socket.destroy())
      socket.once('readable', () => {
        const buf: Buffer | null = socket.read()
        if (!buf) return socket.destroy()
        socket.unshift(buf)
        if (buf[0] === 0x16) { // TLS handshake record
          tlsListeners.forEach((l) => l.call(srv, socket))
          return
        }
        const head = buf.toString('latin1')
        const host = /^host:\s*(\S+)/im.exec(head)?.[1]
        const path = /^[A-Z]+ (\S+)/.exec(head)?.[1] ?? '/'
        socket.end(host
          ? `HTTP/1.1 301 Moved Permanently\r\nLocation: https://${host}${path}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n`
          : 'HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n')
      })
    })
  }
  return {
    name: 'http-to-https-redirect',
    configureServer: (server) => wrap(server.httpServer as Server | null),
    configurePreviewServer: (server) => wrap(server.httpServer as Server | null),
  }
}

export default defineConfig({
  plugins: [
    react(),
    basicSsl(),
    httpToHttpsRedirect(),
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
