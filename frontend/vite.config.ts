import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  build: {
    // Keep the 3D runtime cacheable and defer optional asset parsers until the arena requests them.
    chunkSizeWarningLimit: 650,
    rollupOptions: {
      output: {
        manualChunks(id) {
          const path = id.replace(/\\/g, '/')
          if (path.includes('/three/examples/jsm/loaders/')) return 'three-asset-loaders'
          if (path.includes('/three/examples/jsm/controls/')) return 'three-controls'
          if (path.includes('/node_modules/three/')) return 'three-engine'
          return undefined
        },
      },
    },
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
})
