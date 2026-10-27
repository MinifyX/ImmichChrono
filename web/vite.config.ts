import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vitest/config';

const backend = process.env.CHRONO_BACKEND ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [tailwindcss(), sveltekit()],
  server: { proxy: { '/api': backend } },
  test: { include: ['src/**/*.test.ts'], environment: 'node' },
});
