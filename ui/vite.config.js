// Component-mode plugin bundle — Vite lib mode building src/plugin.jsx ->
// dist/architecture.js, the bundle aw-app.json's contributes.frontend.bundle
// points at.
//
// esbuild's JSX transform is repointed at host.h / host.React.Fragment instead
// of react's own createElement, so every component in plugin.jsx — all
// declared INSIDE register(host), closing over `host` — compiles against the
// ONE shared React instance the plugin host provides. react/react-dom stay
// external and are never bundled: a second React copy in the SPA breaks hooks.
import { defineConfig } from 'vite';

export default defineConfig({
  esbuild: {
    jsxFactory: 'host.h',
    jsxFragment: 'host.React.Fragment',
  },
  build: {
    outDir: 'dist',
    lib: {
      entry: 'src/plugin.jsx',
      formats: ['es'],
      fileName: () => 'architecture.js',
    },
    rollupOptions: {
      external: ['react', 'react-dom'],
    },
  },
});
