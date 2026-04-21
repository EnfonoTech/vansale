import path from "node:path";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";
import { defineConfig, loadEnv } from "vite";
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
export default defineConfig(({ mode }) => {
  // Load VITE_*-prefixed vars from process.env and .env files so we can
  // fail fast when the APK would otherwise ship without an API base URL
  // baked in. Prior release (v1.0.17) shipped once with VITE_API_BASE
  // missing, causing every API call to throw "VITE_API_BASE not set".
  const env = loadEnv(mode, __dirname, "VITE_");
  const apiBase = env.VITE_API_BASE ?? process.env.VITE_API_BASE;
  if (!apiBase) {
    throw new Error(
      "VITE_API_BASE is required for native builds. Export it (e.g. " +
      "`VITE_API_BASE=https://host CUSTOMER_BUILD_TARGET=native pnpm exec vite build`) " +
      "or source customers/.env.<customer> before running. Without it, " +
      "the APK fails every network call with apiBase() throwing at runtime.",
    );
  }

  return {
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
  };
});
