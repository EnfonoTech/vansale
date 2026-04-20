import path from "node:path";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Shared native-version file is the single source of truth for the APK
// version (bumped by scripts/bump-version.mjs). Exposing it as
// `__APP_VERSION__` keeps MoreView + About screens in sync; the old
// path read `../frontend/package.json.version` which is unrelated and
// never changes, so native MoreView crashed trying to dereference the
// undefined global.
const nativeVersionModule = readFileSync(
  path.resolve(__dirname, "../frontend/src/app/native-version.ts"),
  "utf8",
);
const versionMatch = nativeVersionModule.match(/NATIVE_VERSION\s*=\s*"([^"]+)"/);
const APP_VERSION = versionMatch ? versionMatch[1] : "0.0.0";

// Native build — symlinked `src/` points at `../frontend/src/`.
// `preserveSymlinks: false` (default) is load-bearing: setting it true
// makes the Capacitor plugin proxies fail to initialise (§5 rule 13).
export default defineConfig({
  plugins: [vue()],
  base: "./",
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  build: {
    outDir: path.resolve(__dirname, "www"),
    emptyOutDir: true,
    target: "es2020",
  },
  define: {
    __BUILD_TARGET__: JSON.stringify("native"),
    __APP_VERSION__: JSON.stringify(APP_VERSION),
  },
});
