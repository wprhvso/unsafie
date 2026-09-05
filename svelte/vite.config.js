import { sveltekit } from '@sveltejs/kit/vite';
import { fileURLToPath } from 'node:url';

export default {
  plugins: [sveltekit()],
  resolve: {
    alias: { $fluent: fileURLToPath(new URL('../fluent', import.meta.url)) }
  },
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000' },
    fs: { allow: ['..'] }
  }
};
