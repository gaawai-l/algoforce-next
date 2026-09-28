import { defineConfig } from 'vite';
export default defineConfig({
  base: '/login/',
  build: { outDir: 'dist' },
  server: { proxy: { '/auth': 'http://127.0.0.1:18783' } },
});
