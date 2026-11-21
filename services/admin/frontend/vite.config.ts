import { fileURLToPath, URL } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Как nginx в Docker: сайт, API сайта и открытый API отдаются с одного адреса
    proxy: {
      '/panel/api': 'http://127.0.0.1:8000',
      '/v1': 'http://127.0.0.1:8000',
      '/jira': 'http://127.0.0.1:8000',
    },
  },
  build: {
    rolldownOptions: {
      output: {
        // Библиотеки — отдельным чанком: он реже меняется и лучше кэшируется.
        codeSplitting: {
          groups: [
            {
              name: 'react',
              test: /node_modules[\\/](react|react-dom|react-router|scheduler)[\\/]/,
            },
            { name: 'vendor', test: /node_modules/ },
          ],
        },
      },
    },
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
});
