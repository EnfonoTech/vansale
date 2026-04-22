import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * Vitest config — isolated from the Vite build config so the app bundle
 * doesn't drag in test-only deps.
 *
 * - `happy-dom` gives us `window`, `document`, `crypto.randomUUID` for the
 *   offline/* modules that expect a browser-ish global.
 * - `fake-indexeddb/auto` (in setup.ts) patches global `indexedDB` so the
 *   idb wrapper works under Node.
 * - `define.__BUILD_TARGET__` / `__APP_VERSION__` mirror the Vite defines
 *   so source files that reference them don't blow up at import time.
 */
export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  test: {
    environment: "happy-dom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.ts"],
    globals: false,
    clearMocks: true,
    restoreMocks: true,
  },
  define: {
    __BUILD_TARGET__: JSON.stringify("web"),
    __APP_VERSION__: JSON.stringify("test"),
  },
});
