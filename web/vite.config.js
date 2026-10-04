import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

// During `npm run dev`, API and WebSocket calls go to a running Mopidy.
const mopidy = process.env.MOPIDY_URL ?? 'http://localhost:6680'

export default defineConfig({
  base: '/beatballot/',
  plugins: [svelte()],
  build: {
    outDir: '../src/mopidy_beatballot/static',
    emptyOutDir: true,
  },
  server: {
    host: true,
    proxy: {
      '/beatballot/api': mopidy,
      '/beatballot/ws': { target: mopidy, ws: true },
    },
  },
})
