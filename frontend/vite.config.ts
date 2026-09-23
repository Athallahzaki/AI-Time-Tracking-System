import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    tsconfigPaths: true,
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        // BACKEND_API_KEY is added server-side by the dev proxy so the key
        // never ships in the browser bundle. Leave unset when the backend
        // runs without BACKEND_API_KEY.
        headers: process.env.BACKEND_API_KEY
          ? { 'X-API-Key': process.env.BACKEND_API_KEY }
          : undefined,
      },
      // Proxy MediaMTX HLS endpoint to avoid CORS when embedding streams.
      // cameras.yaml stream_url should use /hls/<stream-name>/index.m3u8
      '/hls': {
        target: 'http://127.0.0.1:8888',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/hls/, ''),
      },
      // Keep WHEP relative: remote dashboard clients must contact this server,
      // not their own localhost:8889.
      '/whep': {
        target: 'http://127.0.0.1:8889',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/whep/, ''),
      },
    },
  },
})
