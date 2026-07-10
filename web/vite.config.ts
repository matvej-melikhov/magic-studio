import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  /* Относительный base: приложение живёт под префиксами /dev/ и /prod/
     (nginx отрезает префикс), поэтому пути ассетов должны разрешаться
     от текущего URL. Роуты — только односегментные. */
  base: './',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    /* Локальная разработка: vite dev-сервер проксирует API в server.py */
    proxy: {
      '/api': 'http://localhost:8080',
    },
  },
  test: {
    environment: 'jsdom',
  },
});
